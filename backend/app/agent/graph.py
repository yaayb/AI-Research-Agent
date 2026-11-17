"""Compiled LangGraph StateGraph + streaming and follow-up helpers.

Topology (cyclic)::

    START -> recall_memory -> plan_research -> approve_plan -> investigator_agent
    investigator_agent --(tool_calls?)--> execute_tools -> investigator_agent
                       \\--(no tool calls)--> compare_sources -> reflect_coverage
    reflect_coverage --(coverage < 0.8 and iteration < max)--> investigator_agent
                     \\--(else)--> synthesize_report -> END

Design decisions
- ``approve_plan`` is a thin extra node that hosts the optional human-approval ``interrupt`` so the
  (non-idempotent) planning LLM call is never re-executed when the thread resumes.
- ``stream_research`` converts LangGraph ``custom`` + ``updates`` streams into one flat event
  dict stream shared by the CLI and the SSE API.
- ``answer_followup`` answers from the *checkpointed* thread state (no re-scraping) and appends
  the exchange back to the thread so multi-turn chat is persistent.
"""
from __future__ import annotations

import logging
from typing import Any, AsyncIterator, Callable

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from app.agent import prompts
from app.agent.llm import LLMClient, get_llm
from app.agent.nodes import (
    ResearchNodes, ground_citations, route_after_reflection, should_continue_tools,
)
from app.agent.state import ResearchAgentState
from app.config import Settings, get_settings
from app.database import set_session_status
from app.exporters.markdown_exporter import render_markdown
from app.memory.checkpointer import thread_config
from app.memory.semantic_store import get_semantic_store
from app.tools.search_tool import normalize_url

log = logging.getLogger(__name__)


def build_graph(
    checkpointer: BaseCheckpointSaver | None = None,
    llm: LLMClient | None = None,
    settings: Settings | None = None,
    store_factory: Callable | None = None,
):
    s = settings or get_settings()
    nodes = ResearchNodes(llm or get_llm(s), s, store_factory or (lambda: get_semantic_store(s)))
    g = StateGraph(ResearchAgentState)
    g.add_node("recall_memory", nodes.recall_memory)
    g.add_node("plan_research", nodes.plan_research)
    g.add_node("approve_plan", nodes.approve_plan)
    g.add_node("investigator_agent", nodes.investigator_agent)
    g.add_node("execute_tools", nodes.execute_tools)
    g.add_node("compare_sources", nodes.compare_sources)
    g.add_node("reflect_coverage", nodes.reflect_coverage)
    g.add_node("synthesize_report", nodes.synthesize_report)

    g.add_edge(START, "recall_memory")
    g.add_edge("recall_memory", "plan_research")
    g.add_edge("plan_research", "approve_plan")
    g.add_edge("approve_plan", "investigator_agent")
    g.add_conditional_edges("investigator_agent", should_continue_tools,
                            {"execute_tools": "execute_tools", "compare_sources": "compare_sources"})
    g.add_edge("execute_tools", "investigator_agent")
    g.add_edge("compare_sources", "reflect_coverage")
    g.add_conditional_edges("reflect_coverage", route_after_reflection,
                            {"investigator_agent": "investigator_agent", "synthesize_report": "synthesize_report"})
    g.add_edge("synthesize_report", END)
    graph = g.compile(checkpointer=checkpointer)
    graph.llm = nodes.llm  # type: ignore[attr-defined]  (reused by follow-up Q&A)
    return graph


async def stream_research(
    graph, topic: str, session_id: str, depth: str = "quick", require_approval: bool = False,
    resume: Any = None, settings: Settings | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Run (or resume) a research thread, yielding telemetry events until it finishes or pauses."""
    s = settings or get_settings()
    config = thread_config(session_id)
    if resume is not None:
        inp: Any = Command(resume=resume)
        yield {"type": "session_resumed", "session_id": session_id}
    else:
        inp = {"session_id": session_id, "topic": topic, "depth": depth, "max_iterations": s.depth_to_iterations(depth),
               "iteration": 0, "tool_rounds": 0, "require_approval": require_approval, "messages": []}
        yield {"type": "session_started", "session_id": session_id, "topic": topic, "depth": depth,
               "max_iterations": inp["max_iterations"], "llm": s.active_llm_model, "search": s.search_provider}
    await set_session_status(session_id, "RUNNING")
    interrupted = False
    try:
        async for mode, data in graph.astream(inp, config, stream_mode=["updates", "custom"]):
            if mode == "custom":
                yield data
            elif isinstance(data, dict) and "__interrupt__" in data:
                interrupted = True
                payload = data["__interrupt__"][0].value
                await set_session_status(session_id, "AWAITING_APPROVAL")
                yield {"type": "plan_approval_required", "plan": payload["plan"]}
        if interrupted:
            return
        snap = await graph.aget_state(config)
        vals = snap.values
        yield {"type": "complete", "session_id": session_id, "title": vals["report"]["title"],
               "artifacts": vals.get("artifacts", {}), "coverage_score": vals.get("coverage_score", 0.0),
               "iterations": vals.get("iteration", 0), "sources": len(vals["report"]["sources"])}
    except Exception as exc:  # noqa: BLE001
        log.exception("research run failed")
        await set_session_status(session_id, "FAILED", str(exc))
        yield {"type": "error", "message": f"{type(exc).__name__}: {exc}"}


async def get_thread_values(graph, session_id: str) -> dict[str, Any]:
    snap = await graph.aget_state(thread_config(session_id))
    return dict(snap.values or {})


async def answer_followup(graph, session_id: str, question: str) -> str:
    """Answer from persisted checkpoint state -- no new searches or scrapes."""
    config = thread_config(session_id)
    vals = await get_thread_values(graph, session_id)
    report = vals.get("report")
    if not report:
        raise ValueError("No completed research found for this session")
    sources = [s for s in vals.get("collected_sources", []) if s.get("status") != "failed"]
    allowed = {normalize_url(s["url"]): s["url"] for s in sources}
    excerpts = "\n\n".join(f"[{s['url']}] {s.get('title', '')}: {(s.get('content') or s.get('snippet') or '')[:1200]}"
                           for s in sources[:10])
    history = "\n".join(f"Q: {f['question']}\nA: {f['answer']}" for f in vals.get("followups", [])[-6:]) or "(none)"
    user = (f"FINAL REPORT:\n{render_markdown(report)}\n\nSOURCE EXCERPTS:\n{excerpts}\n\n"
            f"EARLIER FOLLOW-UPS:\n{history}\n\nNEW QUESTION: {question}")
    answer = await graph.llm.chat(prompts.FOLLOWUP_SYSTEM, user, {"report": report, "question": question})
    answer = ground_citations(answer, allowed)
    await graph.aupdate_state(config, {"followups": [{"question": question, "answer": answer}]}, as_node="synthesize_report")
    return answer
