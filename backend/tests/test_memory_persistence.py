from pathlib import Path

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from app.config import Settings
from app.memory.checkpointer import open_checkpointer, thread_config
from app.memory.semantic_store import SemanticMemory


def make_store(path: Path) -> SemanticMemory:
    return SemanticMemory(str(path), use_hash_embeddings=True)


def test_semantic_store_upsert_recall_ranking_and_metadata(tmp_path):
    store = make_store(tmp_path / "c")
    store.upsert("LangGraph supports durable checkpointing with SQLite", "fact", "agents", ["https://a.example/x"], "s1")
    store.upsert("Sourdough bread needs a long fermentation", "fact", "baking", ["https://b.example/y"], "s2")
    hits = store.search("durable checkpointing in LangGraph", k=2)
    assert hits[0]["topic"] == "agents" and hits[0]["score"] > hits[1]["score"]
    assert hits[0]["source_urls"] == ["https://a.example/x"] and hits[0]["session_id"] == "s1" and hits[0]["verified_at"]
    assert store.upsert("LangGraph supports durable checkpointing with SQLite", "fact") == hits[0]["id"]  # idempotent
    assert store.stats()["total"] == 2


def test_semantic_store_persists_across_instances_and_deletes(tmp_path):
    path = tmp_path / "persist"
    item_id = make_store(path).upsert("Brief about vector databases", "brief", "vectors")
    reopened = make_store(path)
    assert [i["id"] for i in reopened.search("vector databases")] == [item_id]
    assert reopened.delete(item_id) is True and reopened.delete(item_id) is False
    assert reopened.search("vector databases") == []


def test_semantic_store_kind_filter(tmp_path):
    s = make_store(tmp_path / "k")
    s.upsert("Always include a pricing table", "preference")
    s.upsert("Pricing of cloud GPUs fell 20%", "fact")
    assert {i["kind"] for i in s.search("pricing", k=5, kind="preference")} == {"preference"}


class S(TypedDict, total=False):
    n: int


def _counter_graph(saver):
    g = StateGraph(S)
    g.add_node("inc", lambda s: {"n": s.get("n", 0) + 1})
    g.add_edge(START, "inc")
    g.add_edge("inc", END)
    return g.compile(checkpointer=saver)


async def test_sqlite_checkpointer_persists_thread_state_across_connections(tmp_path):
    settings = Settings(checkpoint_db_path=str(tmp_path / "cp.db"))
    async with open_checkpointer(settings) as saver:
        await _counter_graph(saver).ainvoke({"n": 41}, thread_config("thread-1"))
    async with open_checkpointer(settings) as saver:  # fresh connection = simulated restart
        snap = await _counter_graph(saver).aget_state(thread_config("thread-1"))
        assert snap.values["n"] == 42
        other = await _counter_graph(saver).aget_state(thread_config("thread-2"))
        assert not other.values


async def test_in_memory_checkpointer_fallback():
    async with open_checkpointer(in_memory=True) as saver:
        assert isinstance(saver, MemorySaver)
