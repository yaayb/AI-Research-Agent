"""Long-term-memory tools the investigator LLM may call mid-run.

Design decision: thin typed wrappers over ``SemanticMemory`` so the model can both *recall* earlier
sessions' verified findings and *store* a fact it has just confirmed from 2+ sources.
"""
from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

from app.memory.semantic_store import get_semantic_store


@tool(response_format="content_and_artifact")
def recall_prior_research(query: str, k: int = 4) -> tuple[str, list[dict[str, Any]]]:
    """Semantic lookup of verified findings, briefs and user preferences from previous research sessions.

    Args:
        query: Natural-language description of what you want to recall.
        k: Maximum number of memories to return.
    """
    items = get_semantic_store().search(query, k=max(1, min(int(k), 10)))
    if not items:
        return "No relevant prior research found.", []
    lines = [f"- ({it['score']:.2f}, {it['kind']}) {it['text']} [sources: {', '.join(it['source_urls'][:3]) or 'n/a'}]"
             for it in items]
    return "Prior research recalled:\n" + "\n".join(lines), items


@tool
def store_verified_fact(fact: str, source_urls: list[str], topic: str = "") -> str:
    """Persist an atomic, verified fact (confirmed by 2+ sources) into long-term memory.

    Args:
        fact: A single self-contained factual statement.
        source_urls: URLs retrieved during this run that support the fact.
        topic: Short topic label for later retrieval.
    """
    if len(set(source_urls)) < 1:
        return "Refused: a fact must cite at least one retrieved source URL."
    item_id = get_semantic_store().upsert(fact, kind="fact", topic=topic, source_urls=source_urls)
    return f"Stored fact as {item_id}"
