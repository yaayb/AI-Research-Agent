"""Long-term, cross-session semantic memory backed by a ChromaDB ``PersistentClient``.

Design decisions
- One collection holds four memory ``kind``s: ``fact`` (atomic verified claim), ``brief`` (whole
  report summary), ``source`` (source summary) and ``preference`` (user report preferences).
- Cosine space so ``score = 1 - distance`` is an intuitive 0..1 relevance, exposed to the UI so the
  developer can observe retrieval quality.
- Chroma's default embedder downloads an ONNX model on first use. Offline/test runs use a
  deterministic hashing embedder (separate collection name -> no embedding-config conflicts).
- Chroma is synchronous; async callers wrap calls in ``asyncio.to_thread``.
"""
from __future__ import annotations

import hashlib
import math
import re
import threading
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

import chromadb
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings

from app.config import Settings, get_settings

_TOKEN = re.compile(r"[a-z0-9]+")
_DIM = 384


class HashingEmbeddingFunction(EmbeddingFunction[Documents]):
    """Deterministic bag-of-words (+bigram) hashing embedder; no network, no model files."""

    def __init__(self) -> None:  # chroma inspects __init__ signature
        pass

    @staticmethod
    def name() -> str:
        return "deepbrief-hash"

    def get_config(self) -> dict[str, Any]:
        return {}

    @staticmethod
    def build_from_config(config: dict[str, Any]) -> "HashingEmbeddingFunction":
        return HashingEmbeddingFunction()

    def __call__(self, input: Documents) -> Embeddings:  # noqa: A002
        out: Embeddings = []
        for text in input:
            vec = [0.0] * _DIM
            toks = _TOKEN.findall(text.lower())
            feats = toks + [f"{a}_{b}" for a, b in zip(toks, toks[1:])]
            for f in feats:
                h = int(hashlib.md5(f.encode()).hexdigest(), 16)
                vec[h % _DIM] += 1.0
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            out.append([v / norm for v in vec])
        return out


class SemanticMemory:
    def __init__(self, persist_dir: str, use_hash_embeddings: bool = False) -> None:
        self._lock = threading.Lock()
        self.client = chromadb.PersistentClient(path=str(persist_dir))
        kwargs: dict[str, Any] = {"metadata": {"hnsw:space": "cosine"}}
        name = "deepbrief_memory"
        if use_hash_embeddings:
            name = "deepbrief_memory_hash"
            kwargs["embedding_function"] = HashingEmbeddingFunction()
        self.collection = self.client.get_or_create_collection(name=name, **kwargs)

    # ---- writes ------------------------------------------------------------
    def upsert(
        self, text: str, kind: str = "fact", topic: str = "", source_urls: list[str] | None = None,
        session_id: str = "", item_id: str | None = None, confidence: float = 0.8,
    ) -> str:
        text = text.strip()
        if not text:
            raise ValueError("Cannot store empty memory")
        item_id = item_id or f"{kind}-{hashlib.sha1((kind + text).encode()).hexdigest()[:16]}"
        meta = {
            "kind": kind, "topic": topic[:300], "source_urls": "|".join(source_urls or []),
            "verified_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "session_id": session_id, "confidence": float(confidence),
        }
        with self._lock:
            self.collection.upsert(ids=[item_id], documents=[text], metadatas=[meta])
        return item_id

    def delete(self, item_id: str) -> bool:
        with self._lock:
            if not self.collection.get(ids=[item_id])["ids"]:
                return False
            self.collection.delete(ids=[item_id])
        return True

    # ---- reads -------------------------------------------------------------
    @staticmethod
    def _shape(item_id: str, doc: str, meta: dict[str, Any], score: float | None) -> dict[str, Any]:
        urls = [u for u in str(meta.get("source_urls", "")).split("|") if u]
        return {"id": item_id, "text": doc, "score": None if score is None else round(score, 4),
                "kind": meta.get("kind", "fact"), "topic": meta.get("topic", ""), "source_urls": urls,
                "verified_at": meta.get("verified_at", ""), "session_id": meta.get("session_id", ""),
                "confidence": meta.get("confidence", 0.0)}

    def search(self, query: str, k: int = 5, kind: str | None = None, min_score: float = 0.0) -> list[dict[str, Any]]:
        n = self.collection.count()
        if n == 0 or not query.strip():
            return []
        with self._lock:
            res = self.collection.query(
                query_texts=[query], n_results=min(k, n), where={"kind": kind} if kind else None
            )
        items = [
            self._shape(i, d, m, 1.0 - dist)
            for i, d, m, dist in zip(res["ids"][0], res["documents"][0], res["metadatas"][0], res["distances"][0])
        ]
        return [it for it in items if it["score"] >= min_score]

    def list_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            res = self.collection.get(limit=1000)
        items = [self._shape(i, d, m, None) for i, d, m in zip(res["ids"], res["documents"], res["metadatas"])]
        items.sort(key=lambda x: x["verified_at"], reverse=True)
        return items[:limit]

    def stats(self) -> dict[str, Any]:
        items = self.list_recent(limit=1000)
        by_kind: dict[str, int] = {}
        for it in items:
            by_kind[it["kind"]] = by_kind.get(it["kind"], 0) + 1
        return {"total": len(items), "by_kind": by_kind, "topics": len({i["topic"] for i in items if i["topic"]}),
                "last_updated": items[0]["verified_at"] if items else None}


_stores: dict[str, SemanticMemory] = {}
_stores_lock = threading.Lock()


def get_semantic_store(settings: Settings | None = None) -> SemanticMemory:
    """Process-wide store per (directory, embedder) so FastAPI, tools and nodes share one client."""
    s = settings or get_settings()
    use_hash = s.offline_test_mode or s.embedding_backend == "hash"
    key = f"{s.chroma_dir}|{use_hash}"
    with _stores_lock:
        if key not in _stores:
            s.chroma_dir.mkdir(parents=True, exist_ok=True)
            _stores[key] = SemanticMemory(str(s.chroma_dir), use_hash_embeddings=use_hash)
        return _stores[key]
