import os
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver

from app.agent.graph import answer_followup, build_graph, get_thread_values, stream_research
from app.agent.nodes import ground_citations, route_after_reflection, sanitize_analysis, should_continue_tools
from app.agent.state import merge_sources
from app.config import get_settings
from app.memory.semantic_store import SemanticMemory
from app.schemas.research import ClaimPosition, ComparisonAnalysis, CorroboratedClaim, DisputedClaim


@pytest.fixture
def graph(tmp_path):
    store = SemanticMemory(str(tmp_path / "chroma"), use_hash_embeddings=True)
    return build_graph(MemorySaver(), settings=get_settings(), store_factory=lambda: store), store


async def collect(graph, topic, sid, **kw):
    return [ev async for ev in stream_research(graph, topic, sid, **kw)]


def test_router_should_continue_tools():
    with_calls = AIMessage(content="", tool_calls=[{"name": "web_search", "args": {"query": "x"}, "id": "1", "type": "tool_call"}])
    assert should_continue_tools({"messages": [with_calls]}) == "execute_tools"
    assert should_continue_tools({"messages": [AIMessage(content="done")]}) == "compare_sources"


def test_router_reflection_loop_conditions():
    base = {"coverage_score": 0.5, "iteration": 1, "max_iterations": 3, "gap_queries": ["q"]}
    assert route_after_reflection(base) == "investigator_agent"
    assert route_after_reflection({**base, "coverage_score": 0.9}) == "synthesize_report"
    assert route_after_reflection({**base, "iteration": 3}) == "synthesize_report"
    assert route_after_reflection({**base, "gap_queries": []}) == "synthesize_report"


def test_merge_sources_dedupes_and_upgrades_snippets():
    a = [{"url": "https://x.com/a?utm_source=1", "status": "snippet", "content": ""}]
    b = [{"url": "https://x.com/a", "status": "read", "content": "full"}, {"url": "https://y.com/b", "status": "snippet"}]
    merged = merge_sources(a, b)
    assert len(merged) == 2 and merged[0]["content"] == "full"


def test_ground_citations_strips_fabricated_urls():
    allowed = {"https://real.com/a": "https://real.com/a"}
    out = ground_citations("Real [A](https://real.com/a?utm_x=1) fake [B](https://fake.com/z).", allowed)
    assert "[A](https://real.com/a)" in out and "fake.com" not in out and "B" in out


def test_sanitize_analysis_enforces_two_domains_and_known_urls():
    srcs = [{"url": "https://a.com/1", "domain": "a.com", "title": "A"}, {"url": "https://a.com/2", "domain": "a.com", "title": "A2"},
            {"url": "https://b.com/1", "domain": "b.com", "title": "B"}]
    pos = lambda u, d: ClaimPosition(url=u, domain=d, stance_or_figure="1")  # noqa: E731
    raw = ComparisonAnalysis(
        corroborated_claims=[CorroboratedClaim(claim="same-domain", source_urls=["https://a.com/1", "https://a.com/2"]),
                             CorroboratedClaim(claim="ok", source_urls=["https://a.com/1", "https://b.com/1", "https://made.up/x"])],
        disputed_or_conflicting_claims=[DisputedClaim(claim="d", positions=[pos("https://a.com/1", "a.com"), pos("https://nope.com", "nope.com")])])
    out = sanitize_analysis(raw, srcs)
    assert [c.claim for c in out.corroborated_claims] == ["ok"] and out.corroborated_claims[0].source_urls == ["https://a.com/1", "https://b.com/1"]
    assert out.disputed_or_conflicting_claims == [] and len(out.source_quality_table) == 3


async def test_full_graph_loops_then_synthesizes_with_artifacts(graph):
    g, store = graph
    events = await collect(g, "Compare open-source AI agent frameworks", "sess-loop", depth="deep")
    types = [e["type"] for e in events]
    assert types[0] == "session_started" and types[-1] == "complete"
    nodes = [e["node"] for e in events if e["type"] == "node_start"]
    assert nodes[:3] == ["recall_memory", "plan_research", "approve_plan"]
    assert nodes.count("investigator_agent") >= 4 and nodes.count("execute_tools") >= 2   # tool loop + gap loop
    refl = [e for e in events if e["type"] == "reflection"]
    assert [round(r["coverage_score"], 1) for r in refl] == [0.6, 0.9] and refl[0]["decision"] == "investigate_more"
    assert any(e["type"] == "tool_call" and e["tool"] == "web_search" for e in events)
    assert any(e["type"] == "tool_call" and e["tool"] == "read_webpage" for e in events)

    vals = await get_thread_values(g, "sess-loop")
    assert vals["status"] == "COMPLETED" and vals["iteration"] == 2
    rep = vals["report"]
    retrieved = {s["url"] for s in vals["collected_sources"]}
    assert rep["comparison"]["disputed_or_conflicting_claims"], "offline fixtures contain a market-size conflict"
    import re
    cited = set(re.findall(r"\]\((https?://[^)]+)\)", rep["executive_summary"] + "".join(s["body_markdown"] for s in rep["sections"])))
    assert cited and cited <= retrieved
    for fmt, path in vals["artifacts"].items():
        assert Path(path).is_file() and Path(path).stat().st_size > 500, fmt
    assert Path(vals["artifacts"]["pdf"]).read_bytes()[:5] == b"%PDF-"
    assert store.stats()["total"] >= 2 and vals["stored_facts"]


async def test_quick_depth_caps_loops_and_cross_session_recall(graph):
    g, store = graph
    await collect(g, "Agent framework memory design", "s-a", depth="quick")
    events = await collect(g, "Agent framework memory design", "s-b", depth="quick")
    recalled = next(e for e in events if e["type"] == "memory_recalled")
    assert recalled["items"], "second session should recall facts stored by the first"
    assert (await get_thread_values(g, "s-b"))["iteration"] <= 2


async def test_plan_approval_interrupt_and_resume(graph):
    g, _ = graph
    first = await collect(g, "Agent frameworks", "s-appr", depth="quick", require_approval=True)
    assert first[-1]["type"] == "plan_approval_required" and not any(e["type"] == "complete" for e in first)
    second = await collect(g, "Agent frameworks", "s-appr", resume={"initial_queries": ["custom approved query"]})
    assert second[-1]["type"] == "complete"
    assert any(e["type"] == "tool_call" and e["args"].get("query") == "custom approved query" for e in second)


async def test_followup_uses_checkpoint_state_without_new_tool_calls(graph):
    g, _ = graph
    await collect(g, "Agent frameworks", "s-fu")
    before = len((await get_thread_values(g, "s-fu"))["collected_sources"])
    answer = await answer_followup(g, "s-fu", "Why did the sources disagree?")
    vals = await get_thread_values(g, "s-fu")
    assert answer and len(vals["collected_sources"]) == before
    assert vals["followups"][0]["question"] == "Why did the sources disagree?"
    await answer_followup(g, "s-fu", "Expand section 1")
    assert len((await get_thread_values(g, "s-fu"))["followups"]) == 2
    with pytest.raises(ValueError):
        await answer_followup(g, "does-not-exist", "hi")
