"""LangGraph node implementations for the Plan-Search-Extract-Compare-Reflect-Synthesize workflow.

Design decisions
- Nodes live on a ``ResearchNodes`` class that receives its dependencies (LLM client, settings,
  memory store) -- graph construction is therefore trivially testable with fakes.
- Telemetry: every node emits typed events through LangGraph's custom stream writer
  (``get_stream_writer``); CLI and SSE API both consume the same event stream.
- Guardrails are enforced in *code* after the LLM answers: claims need 2+ independent domains,
  every URL must have been retrieved this run, and links to unretrieved URLs are stripped.
- Tool-call loops are bounded (``MAX_TOOL_ROUNDS`` per loop) so an LLM cannot spin forever.
"""
from __future__ import annotations

import asyncio
import functools
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.config import get_stream_writer
from langgraph.prebuilt import ToolNode
from langgraph.types import interrupt

from app.agent import prompts
from app.agent.llm import LLMClient
from app.agent.state import ResearchAgentState
from app.config import Settings
from app.database import persist_completed_run
from app.exporters import export_all
from app.memory.semantic_store import SemanticMemory
from app.schemas.research import (
    ComparisonAnalysis, CoverageReflection, FinalReport, FinalReportDraft, ResearchPlan, SourceQuality, SourceRef,
)
from app.tools.memory_tools import recall_prior_research
from app.tools.scrape_tool import read_webpage
from app.tools.search_tool import SEEN_URLS, domain_of, normalize_url, web_search

log = logging.getLogger(__name__)

TOOLS = [web_search, read_webpage, recall_prior_research]
MAX_TOOL_ROUNDS = 3
COVERAGE_THRESHOLD = 0.8
_MD_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_HIGH = ("reuters.com", "apnews.com", "bbc.com", "nature.com", "science.org", "arxiv.org", "ieee.org", "acm.org",
         "who.int", "worldbank.org", "oecd.org", "imf.org", "nih.gov", "sec.gov", "wikipedia.org", "mit.edu")
_LOW = ("reddit.com", "quora.com", "medium.com", "blogspot.com", "substack.com", "facebook.com", "x.com",
        "twitter.com", "pinterest.com", "tiktok.com", "linkedin.com")


def emit(type_: str, **data: Any) -> None:
    try:
        get_stream_writer()({"type": type_, **data})
    except Exception:  # noqa: BLE001 - not streaming (e.g. plain ainvoke)
        pass


def traced(name: str):
    def deco(fn):
        @functools.wraps(fn)
        async def wrapper(self, state, *a, **k):
            emit("node_start", node=name, iteration=state.get("iteration", 0))
            out = await fn(self, state, *a, **k)
            emit("node_end", node=name)
            return out
        return wrapper
    return deco


# ---------------------------------------------------------------- pure helpers
def heuristic_tier(domain: str) -> str:
    d = domain.lower()
    if d.endswith((".gov", ".edu", ".int", ".ac.uk")) or any(d == h or d.endswith("." + h) for h in _HIGH):
        return "high"
    if any(d == h or d.endswith("." + h) for h in _LOW):
        return "low"
    return "medium"


def usable_sources(state: ResearchAgentState) -> list[dict[str, Any]]:
    return [s for s in state.get("collected_sources", []) if s.get("status") != "failed" and (s.get("content") or s.get("snippet"))]


def ground_citations(text: str, allowed: dict[str, str]) -> str:
    """Keep links only if their URL was retrieved this run (``allowed``: normalized -> canonical)."""
    def fix(m: re.Match) -> str:
        canon = allowed.get(normalize_url(m.group(2)))
        return f"[{m.group(1)}]({canon})" if canon else m.group(1)
    return _MD_LINK.sub(fix, text)


def sanitize_analysis(a: ComparisonAnalysis, sources: list[dict[str, Any]]) -> ComparisonAnalysis:
    by_norm = {normalize_url(s["url"]): s for s in sources}

    def canon(u: str) -> str | None:
        s = by_norm.get(normalize_url(u))
        return s["url"] if s else None

    corro = []
    for c in a.corroborated_claims:
        urls = list(dict.fromkeys(u for u in map(canon, c.source_urls) if u))
        if len({domain_of(u) for u in urls}) >= 2:
            corro.append(c.model_copy(update={"source_urls": urls}))
    disputed = []
    for d in a.disputed_or_conflicting_claims:
        pos = []
        for p in d.positions:
            u = canon(p.url)
            if u:
                pos.append(p.model_copy(update={"url": u, "domain": domain_of(u)}))
        if len(pos) >= 2:
            disputed.append(d.model_copy(update={"positions": pos}))
    quality: dict[str, SourceQuality] = {}
    for q in a.source_quality_table:
        u = canon(q.url)
        if u:
            quality[u] = q.model_copy(update={"url": u, "domain": domain_of(u)})
    for s in sources:
        if s["url"] not in quality:
            quality[s["url"]] = SourceQuality(
                url=s["url"], domain=s["domain"], title=s.get("title") or s["domain"], relevance_score=0.5,
                credibility_tier=heuristic_tier(s["domain"]),
                key_takeaway=(s.get("snippet") or s.get("content", ""))[:140].replace("\n", " "))
    return ComparisonAnalysis(corroborated_claims=corro, disputed_or_conflicting_claims=disputed,
                              source_quality_table=list(quality.values()))


def _fmt_sources(sources: list[dict[str, Any]], chars: int) -> str:
    out = []
    for i, s in enumerate(sources, 1):
        body = (s.get("content") or s.get("snippet") or "")[:chars]
        out.append(f"[{i}] URL: {s['url']}\n    domain: {s['domain']} | title: {s.get('title', '')} | "
                   f"date: {s.get('published_date') or 'n/a'} | {s.get('status')}\n    {body}")
    return "\n\n".join(out) or "(no sources retrieved)"


def _compress_history(messages: list[BaseMessage]) -> list[BaseMessage]:
    """Shorten tool outputs from earlier loops so context stays bounded (structure preserved)."""
    last_h = max((i for i, m in enumerate(messages) if isinstance(m, HumanMessage)), default=0)
    out = []
    for i, m in enumerate(messages):
        if i < last_h and isinstance(m, ToolMessage) and len(str(m.content)) > 400:
            m = m.model_copy(update={"content": str(m.content)[:400] + " ...[earlier output truncated]"})
        out.append(m)
    return out


class ResearchNodes:
    def __init__(self, llm: LLMClient, settings: Settings, store_factory) -> None:
        self.llm, self.settings, self._store_factory = llm, settings, store_factory
        self.tool_node = ToolNode(TOOLS, handle_tool_errors=True)

    @property
    def store(self) -> SemanticMemory:
        return self._store_factory()

    # ------------------------------------------------------------ 1. recall
    @traced("recall_memory")
    async def recall_memory(self, state: ResearchAgentState) -> dict:
        topic = state["topic"]
        facts = await asyncio.to_thread(self.store.search, topic, 6, None, 0.2)
        prefs = await asyncio.to_thread(self.store.search, f"report preferences {topic}", 3, "preference", 0.0)
        items = list({i["id"]: i for i in facts + prefs}.values())
        emit("memory_recalled", items=items)
        return {"prior_knowledge": items, "iteration": 0, "tool_rounds": 0, "status": "RUNNING"}

    # ------------------------------------------------------------ 2. plan
    @traced("plan_research")
    async def plan_research(self, state: ResearchAgentState) -> dict:
        prior = "\n".join(f"- {i['text']}" for i in state.get("prior_knowledge", [])) or "(none)"
        user = f"TOPIC: {state['topic']}\nDEPTH: {state.get('depth', 'quick')}\nPRIOR KNOWLEDGE:\n{prior}"
        plan = await self.llm.structured(ResearchPlan, prompts.PLANNER_SYSTEM, user, {"topic": state["topic"]})
        emit("plan", plan=plan.model_dump())
        return {"plan": plan.model_dump()}

    @traced("approve_plan")
    async def approve_plan(self, state: ResearchAgentState) -> dict:
        """Optional human-in-the-loop gate (``interrupt``) + builds the first investigator brief."""
        plan = dict(state["plan"])
        if state.get("require_approval"):
            decision = interrupt({"plan": plan})
            if isinstance(decision, dict):
                plan["sub_questions"] = decision.get("sub_questions") or plan["sub_questions"]
                plan["initial_queries"] = decision.get("initial_queries") or plan["initial_queries"]
            emit("plan", plan=plan, approved=True)
        brief = "Round 1: run these searches in parallel, then read the most promising URLs.\n" + "\n".join(
            f"QUERY: {q}" for q in plan["initial_queries"])
        return {"plan": plan, "messages": [HumanMessage(content=brief)]}

    # ------------------------------------------------------------ 3. investigate
    @traced("investigator_agent")
    async def investigator_agent(self, state: ResearchAgentState) -> dict:
        if state.get("tool_rounds", 0) >= MAX_TOOL_ROUNDS:
            return {"messages": [AIMessage(content="Tool budget for this loop exhausted; moving to comparison.")]}
        plan = state["plan"]
        prior = "\n".join(f"- {i['text']}" for i in state.get("prior_knowledge", [])) or "(none)"
        system = prompts.INVESTIGATOR_SYSTEM.format(
            goal=plan["research_goal"], sub_questions="\n".join(f"- {q}" for q in plan["sub_questions"]), prior=prior)
        msgs = [SystemMessage(content=system)] + _compress_history(state["messages"])
        ai = await self.llm.tool_step(msgs, TOOLS)
        for tc in ai.tool_calls:
            emit("tool_call", tool=tc["name"], args=tc["args"])
        return {"messages": [ai]}

    # ------------------------------------------------------------ 4. tools
    @traced("execute_tools")
    async def execute_tools(self, state: ResearchAgentState) -> dict:
        last = state["messages"][-1]
        seen = frozenset(normalize_url(s["url"]) for s in state.get("collected_sources", []))
        token = SEEN_URLS.set(seen)
        try:
            result = await asyncio.wait_for(self.tool_node.ainvoke({"messages": list(state["messages"])}),
                                            timeout=self.settings.tool_timeout_s)
            tool_msgs: list[ToolMessage] = result["messages"]
        except (asyncio.TimeoutError, Exception) as exc:  # noqa: BLE001 - resilience: never crash the graph
            log.warning("tool round failed: %r", exc)
            tool_msgs = [ToolMessage(content=f"Tool execution failed or timed out: {type(exc).__name__}",
                                     tool_call_id=tc["id"], name=tc["name"], status="error") for tc in last.tool_calls]
        finally:
            SEEN_URLS.reset(token)

        new_sources: list[dict[str, Any]] = []
        log_lines: list[str] = []
        for tc in last.tool_calls:
            arg = tc["args"].get("query") or tc["args"].get("url") or ""
            log_lines.append(f'{tc["name"]}("{arg}")')
        for m in tool_msgs:
            art = getattr(m, "artifact", None)
            found: list[dict[str, Any]] = []
            if isinstance(art, list):
                found = [{**r, "content": "", "status": "snippet"} for r in art if isinstance(r, dict) and r.get("url")]
            elif isinstance(art, dict) and art.get("url"):
                found = [art]
            new_sources.extend(found)
            ok = m.status != "error" and not (isinstance(art, dict) and art.get("status") == "failed")
            emit("tool_result", tool=m.name, ok=ok, summary=str(m.content).split("\n", 1)[0][:200], count=len(found))
            for f in found:
                emit("source", url=f["url"], title=f.get("title", ""), domain=f.get("domain", ""),
                     status=f.get("status", "snippet"), error=f.get("error"))
        return {"messages": tool_msgs, "collected_sources": new_sources,
                "tool_rounds": state.get("tool_rounds", 0) + 1, "search_log": log_lines}

    # ------------------------------------------------------------ 5. compare
    @traced("compare_sources")
    async def compare_sources(self, state: ResearchAgentState) -> dict:
        sources = usable_sources(state)
        if sources:
            user = f"TOPIC: {state['topic']}\n\nSOURCES:\n{_fmt_sources(sources, 2500)}"
            raw = await self.llm.structured(ComparisonAnalysis, prompts.COMPARE_SYSTEM, user,
                                            {"topic": state["topic"], "sources": sources})
            analysis = sanitize_analysis(raw, sources)
        else:
            analysis = ComparisonAnalysis()
        emit("comparison", corroborated=len(analysis.corroborated_claims),
             disputed=len(analysis.disputed_or_conflicting_claims), sources=len(sources))
        return {"comparison": analysis.model_dump(), "consensus_findings": [c.claim for c in analysis.corroborated_claims]}

    # ------------------------------------------------------------ 6. reflect
    @traced("reflect_coverage")
    async def reflect_coverage(self, state: ResearchAgentState) -> dict:
        it = state.get("iteration", 0)
        max_it = state.get("max_iterations", self.settings.max_iterations)
        comp = state.get("comparison", {})
        user = (f"SUB-QUESTIONS:\n" + "\n".join(f"- {q}" for q in state["plan"]["sub_questions"])
                + "\n\nCORROBORATED:\n" + "\n".join(f"- {c}" for c in state.get("consensus_findings", []))
                + "\n\nDISPUTED:\n" + "\n".join(f"- {d['claim']}" for d in comp.get("disputed_or_conflicting_claims", []))
                + f"\n\nEARLIER QUERIES:\n" + "\n".join(state.get("search_log", [])[-30:]))
        ref = await self.llm.structured(CoverageReflection, prompts.REFLECT_SYSTEM, user,
                                        {"topic": state["topic"], "iteration": it})
        done = set(q.lower() for q in state.get("search_log", []))
        gaps = [q for q in ref.gap_queries if f'web_search("{q}")'.lower() not in done][:4]
        iteration = it + 1
        looping = ref.coverage_score < COVERAGE_THRESHOLD and iteration < max_it and bool(gaps)
        emit("reflection", coverage_score=ref.coverage_score, iteration=iteration, max_iterations=max_it,
             gap_queries=gaps if looping else [], decision="investigate_more" if looping else "synthesize",
             rationale=ref.rationale)
        update: dict[str, Any] = {"iteration": iteration, "coverage_score": ref.coverage_score,
                                  "gap_queries": gaps if looping else [], "tool_rounds": 0}
        if looping:
            update["messages"] = [HumanMessage(content=f"Round {iteration + 1}: close these evidence gaps. Uncovered: "
                                               f"{'; '.join(ref.uncovered_sub_questions)}\n" + "\n".join(f"QUERY: {q}" for q in gaps))]
        return update

    # ------------------------------------------------------------ 7. synthesize
    @traced("synthesize_report")
    async def synthesize_report(self, state: ResearchAgentState) -> dict:
        sources = usable_sources(state)
        comp = ComparisonAnalysis(**state.get("comparison", {})) if state.get("comparison") else ComparisonAnalysis()
        allowed = {normalize_url(s["url"]): s["url"] for s in sources}
        prior = "\n".join(f"- {i['text']}" for i in state.get("prior_knowledge", [])) or "(none)"
        user = (f"TOPIC: {state['topic']}\nRESEARCH GOAL: {state['plan']['research_goal']}\n"
                f"SUB-QUESTIONS:\n" + "\n".join(f"- {q}" for q in state["plan"]["sub_questions"])
                + f"\n\nPRIOR KNOWLEDGE (verify before using; cite only retrieved sources):\n{prior}"
                + f"\n\nCOMPARISON ANALYSIS (JSON):\n{comp.model_dump_json(indent=1)}"
                + f"\n\nAVAILABLE SOURCES (cite ONLY these URLs):\n{_fmt_sources(sources, 1500)}")
        draft = await self.llm.structured(FinalReportDraft, prompts.WRITER_SYSTEM, user,
                                          {"topic": state["topic"], "sources": sources, "comparison": comp.model_dump()})
        g = lambda t: ground_citations(t, allowed)  # noqa: E731
        draft = draft.model_copy(update={
            "executive_summary": g(draft.executive_summary),
            "key_findings": [g(f) for f in draft.key_findings],
            "sections": [s.model_copy(update={"body_markdown": g(s.body_markdown)}) for s in draft.sections],
            "risks_limitations": [g(x) for x in draft.risks_limitations],
            "open_questions": [g(x) for x in draft.open_questions],
        })
        report = FinalReport(
            **draft.model_dump(), topic=state["topic"], generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            research_scope=state["plan"]["research_goal"], iterations=state.get("iteration", 0),
            coverage_score=state.get("coverage_score", 0.0),
            sources=[SourceRef(url=s["url"], title=s.get("title") or s["domain"], domain=s["domain"],
                               published_date=s.get("published_date")) for s in sources],
            comparison=comp).model_dump()

        stored = await self._persist_memory(state, report, comp)
        emit("memory_stored", count=len(stored), items=stored)
        sid = state.get("session_id", "adhoc")
        artifacts = await asyncio.to_thread(export_all, report, self.settings.reports_path / sid)
        emit("artifacts", artifacts=artifacts)
        await persist_completed_run(sid, report, artifacts, state.get("iteration", 0), state.get("coverage_score", 0.0))
        return {"report": report, "artifacts": artifacts, "stored_facts": stored, "status": "COMPLETED"}

    async def _persist_memory(self, state: ResearchAgentState, report: dict, comp: ComparisonAnalysis) -> list[dict]:
        sid, topic, out = state.get("session_id", ""), state["topic"], []

        def work() -> list[dict]:
            ids = []
            for c in comp.corroborated_claims:
                if c.confidence >= 0.7 and len(c.source_urls) >= 2:
                    ids.append(self.store.upsert(c.claim, "fact", topic, c.source_urls, sid, confidence=c.confidence))
            ids.append(self.store.upsert(f"{report['title']}: {report['executive_summary']}", "brief", topic,
                                         [s["url"] for s in report["sources"]][:8], sid))
            for q in [q for q in comp.source_quality_table if q.credibility_tier == "high"][:5]:
                ids.append(self.store.upsert(f"{q.title} ({q.domain}): {q.key_takeaway}", "source", topic, [q.url], sid))
            return ids

        ids = await asyncio.to_thread(work)
        recent = await asyncio.to_thread(self.store.list_recent, 200)
        out = [i for i in recent if i["id"] in set(ids)]
        return out


# ---------------------------------------------------------------- routers
def should_continue_tools(state: ResearchAgentState) -> str:
    last = state["messages"][-1] if state.get("messages") else None
    return "execute_tools" if isinstance(last, AIMessage) and last.tool_calls else "compare_sources"


def route_after_reflection(state: ResearchAgentState) -> str:
    if (state.get("coverage_score", 1.0) < COVERAGE_THRESHOLD and state.get("iteration", 0) < state.get("max_iterations", 1)
            and state.get("gap_queries")):
        return "investigator_agent"
    return "synthesize_report"
