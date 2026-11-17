"""Provider-agnostic LLM client: Gemini / OpenAI behind one tiny async interface.

Design decisions
- Nodes depend on the ``LLMClient`` protocol (``structured`` / ``tool_step`` / ``chat``), never on a
  vendor SDK, so providers swap via ``LLM_PROVIDER`` and tests inject fakes.
- Structured output uses ``with_structured_output(PydanticModel)`` (strict Pydantic v2 validation)
  with bounded retries; tool calling uses ``bind_tools`` (works with Gemini function calling).
- ``OfflineLLM`` is a scripted deterministic stand-in for ``OFFLINE_TEST_MODE`` that still exercises
  parallel tool calls, ToolNode, comparison, gap-loop routing and report writing.
"""
from __future__ import annotations

import asyncio
import logging
import re
import uuid
from typing import Any, Protocol, TypeVar

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.schemas.research import (
    ClaimPosition, ComparisonAnalysis, CorroboratedClaim, CoverageReflection, DisputedClaim,
    FinalReportDraft, ReportSection, ResearchPlan, SourceQuality,
)

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


class ConfigError(RuntimeError):
    pass


class LLMClient(Protocol):
    async def structured(self, schema: type[T], system: str, user: str, context: dict[str, Any] | None = None) -> T: ...
    async def tool_step(self, messages: list[BaseMessage], tools: list[Any]) -> AIMessage: ...
    async def chat(self, system: str, user: str, context: dict[str, Any] | None = None) -> str: ...


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p if isinstance(p, str) else p.get("text", "") for p in content)
    return str(content)


class ProviderLLM:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._model = None

    @property
    def model(self):
        """Built lazily so the API can boot (and report the problem) before keys are configured."""
        if self._model is None:
            self._model = self._build(self.settings, temperature=0.2)
        return self._model

    @staticmethod
    def _build(s: Settings, temperature: float):
        if not s.llm_configured:
            name = "GEMINI_API_KEY" if s.llm_provider == "gemini" else "OPENAI_API_KEY"
            raise ConfigError(f"{name} is not set. Add it to .env (see .env.example) or set OFFLINE_TEST_MODE=true.")
        if s.llm_provider == "gemini":
            from langchain_google_genai import ChatGoogleGenerativeAI

            return ChatGoogleGenerativeAI(model=s.gemini_model, google_api_key=s.gemini_api_key,
                                          temperature=temperature, max_retries=2)
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=s.openai_model, api_key=s.openai_api_key, temperature=temperature, max_retries=2)

    async def structured(self, schema: type[T], system: str, user: str, context: dict[str, Any] | None = None) -> T:
        runnable = self.model.with_structured_output(schema)
        last: Exception | None = None
        for attempt in range(3):
            try:
                out = await runnable.ainvoke([SystemMessage(content=system), HumanMessage(content=user)])
                if out is None:
                    raise ValueError("model returned no structured output")
                return out if isinstance(out, schema) else schema.model_validate(out)
            except Exception as exc:  # noqa: BLE001
                last = exc
                log.warning("structured(%s) attempt %d failed: %s", schema.__name__, attempt + 1, exc)
                await asyncio.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"Structured output for {schema.__name__} failed: {last}")

    async def tool_step(self, messages: list[BaseMessage], tools: list[Any]) -> AIMessage:
        return await self.model.bind_tools(tools).ainvoke(messages)

    async def chat(self, system: str, user: str, context: dict[str, Any] | None = None) -> str:
        out = await self.model.ainvoke([SystemMessage(content=system), HumanMessage(content=user)])
        return _text(out.content)


# --------------------------------------------------------------------------- offline
_FIGURE = re.compile(r"\$(\d+(?:\.\d+)?)\s*billion", re.I)


def _body(s: dict[str, Any]) -> str:
    return s.get("content") or s.get("snippet") or ""


class OfflineLLM:
    """Deterministic scripted model. Coverage is 0.6 on the first reflection, 0.9 afterwards."""

    async def structured(self, schema: type[T], system: str, user: str, context: dict[str, Any] | None = None) -> T:
        ctx = context or {}
        topic = ctx.get("topic", "the topic")
        if schema is ResearchPlan:
            return ResearchPlan(
                research_goal=f"Establish a sourced, balanced understanding of: {topic}",
                sub_questions=[f"What is the current state of {topic}?", f"What do quantitative sources say about {topic}?",
                               f"Where do sources disagree about {topic}?"],
                initial_queries=[f"{topic} overview", f"{topic} market size statistics", f"{topic} comparison analysis"],
            )  # type: ignore[return-value]
        if schema is ComparisonAnalysis:
            return self._comparison(ctx.get("sources", []))  # type: ignore[return-value]
        if schema is CoverageReflection:
            first = ctx.get("iteration", 0) == 0
            return CoverageReflection(
                coverage_score=0.6 if first else 0.9,
                uncovered_sub_questions=[f"Where do sources disagree about {topic}?"] if first else [],
                gap_queries=[f"{topic} conflicting estimates reasons"] if first else [],
                rationale="Scripted offline reflection.",
            )  # type: ignore[return-value]
        if schema is FinalReportDraft:
            return self._report(topic, ctx)  # type: ignore[return-value]
        raise NotImplementedError(f"OfflineLLM cannot produce {schema.__name__}")

    @staticmethod
    def _comparison(sources: list[dict[str, Any]]) -> ComparisonAnalysis:
        corro, disputed = [], []
        lang = [s for s in sources if "langgraph" in _body(s).lower()]
        if len({s["domain"] for s in lang}) >= 2:
            corro.append(CorroboratedClaim(claim="LangGraph is a widely adopted stateful orchestration framework.",
                                           source_urls=[s["url"] for s in lang], confidence=0.9))
        mem = [s for s in sources if "dual-tier memory" in _body(s).lower() or "memory" in _body(s).lower()]
        if len({s["domain"] for s in mem}) >= 2:
            corro.append(CorroboratedClaim(claim="Pairing checkpoints with a vector store is the dominant memory pattern.",
                                           source_urls=[s["url"] for s in mem], confidence=0.8))
        figs = [(s, m.group(1)) for s in sources if (m := _FIGURE.search(_body(s)))]
        if len({f for _, f in figs}) > 1:
            disputed.append(DisputedClaim(
                claim="2025 agent-framework market size",
                positions=[ClaimPosition(url=s["url"], domain=s["domain"], stance_or_figure=f"${f} billion",
                                         published_date=s.get("published_date")) for s, f in figs],
                likely_explanation="Different market definitions and survey scope."))
        quality = [SourceQuality(url=s["url"], domain=s["domain"], title=s.get("title") or s["domain"], relevance_score=0.8,
                                 credibility_tier="high" if s["domain"].endswith((".gov", ".edu")) else "medium",
                                 key_takeaway=_body(s)[:140].replace("\n", " ")) for s in sources]
        return ComparisonAnalysis(corroborated_claims=corro, disputed_or_conflicting_claims=disputed, source_quality_table=quality)

    @staticmethod
    def _report(topic: str, ctx: dict[str, Any]) -> FinalReportDraft:
        sources = ctx.get("sources", [])
        comp = ctx.get("comparison", {})
        title_of = {s["url"]: s.get("title") or s["domain"] for s in sources}

        def cite(url: str) -> str:
            return f"[{title_of.get(url, url)}]({url})"

        findings = []
        for c in comp.get("corroborated_claims", []):
            findings.append(f"{c['claim']} {cite(c['source_urls'][0])}")
        disputes = []
        for d in comp.get("disputed_or_conflicting_claims", []):
            disputes.append(f"**{d['claim']}**: " + "; ".join(f"{p['stance_or_figure']} {cite(p['url'])}" for p in d["positions"]))
        sections = [
            ReportSection(heading="Current Landscape",
                          body_markdown="\n\n".join(findings) or "Evidence retrieved was limited."),
            ReportSection(heading="Where Sources Disagree",
                          body_markdown="\n\n".join(disputes) or "No material contradictions were detected."),
        ]
        return FinalReportDraft(
            title=f"Research Brief: {topic}",
            executive_summary=f"This brief examines {topic} using {len(sources)} sources. " + (findings[0] if findings else ""),
            confidence_rating="Medium", confidence_rationale="Offline scripted run with limited sources.",
            key_findings=findings or ["No corroborated findings."], sections=sections,
            risks_limitations=["Limited number of sources.", "Figures differ by definition and date."],
            open_questions=["How will estimates converge as more data is published?"],
        )

    async def tool_step(self, messages: list[BaseMessage], tools: list[Any]) -> AIMessage:
        last_h = max((i for i, m in enumerate(messages) if isinstance(m, HumanMessage)), default=-1)
        tail = messages[last_h + 1:]
        tool_msgs = [m for m in tail if isinstance(m, ToolMessage)]
        names = {m.name for m in tool_msgs}

        def call(name: str, args: dict) -> dict:
            return {"name": name, "args": args, "id": f"call_{uuid.uuid4().hex[:10]}", "type": "tool_call"}

        if not tool_msgs:
            qs = re.findall(r"^QUERY: (.+)$", _text(messages[last_h].content), re.M)[:3]
            if qs:
                return AIMessage(content="Searching.", tool_calls=[call("web_search", {"query": q, "max_results": 5}) for q in qs])
        elif "read_webpage" not in names:
            urls = [r["url"] for m in tool_msgs if m.name == "web_search" and isinstance(m.artifact, list) for r in m.artifact][:3]
            if urls:
                return AIMessage(content="Reading top sources.", tool_calls=[call("read_webpage", {"url": u}) for u in urls])
        return AIMessage(content="Evidence for this round collected.")

    async def chat(self, system: str, user: str, context: dict[str, Any] | None = None) -> str:
        ctx = context or {}
        report = ctx.get("report", {})
        return (f"Based on the stored research state for '{report.get('title', 'this report')}': "
                f"{report.get('executive_summary', 'no summary available')}\n\n(Question: {user[:200]})")


def get_llm(settings: Settings | None = None) -> LLMClient:
    s = settings or get_settings()
    return OfflineLLM() if s.offline_test_mode else ProviderLLM(s)
