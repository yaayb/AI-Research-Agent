"""Graph state for the DeepBrief research agent.

Design decisions
- ``TypedDict`` + ``Annotated`` reducers (LangGraph idiom): ``add_messages`` for the tool-calling
  transcript, a *deduplicating, upgrading* reducer for ``collected_sources`` (a full-page read
  replaces an earlier snippet-only record for the same URL), and ``operator.add`` for append-only logs.
- Structured objects are stored as plain dicts (Pydantic ``model_dump``) so any checkpointer can
  serialise them and follow-up Q&A can read them straight from the persisted thread state.
"""
from __future__ import annotations

from typing import Annotated, Any, TypedDict
import operator

from langgraph.graph.message import add_messages

from app.tools.search_tool import normalize_url


def merge_sources(existing: list[dict[str, Any]] | None, new: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {normalize_url(s["url"]): s for s in (existing or [])}
    for src in new or []:
        key = normalize_url(src["url"])
        old = merged.get(key)
        if old is None:
            merged[key] = src
        elif old.get("status") != "read" and src.get("status") == "read":
            merged[key] = {**old, **src}  # upgrade snippet -> full read
        elif old.get("status") == "failed" and src.get("status") != "failed":
            merged[key] = {**old, **src}
    return list(merged.values())


class ResearchAgentState(TypedDict, total=False):
    # inputs / control
    session_id: str
    topic: str
    depth: str
    max_iterations: int
    iteration: int            # completed investigate->compare->reflect loops
    tool_rounds: int          # tool-call rounds spent in the current loop
    require_approval: bool
    # memory
    prior_knowledge: list[dict[str, Any]]
    stored_facts: list[dict[str, Any]]
    # planning & investigation
    plan: dict[str, Any]
    messages: Annotated[list, add_messages]
    collected_sources: Annotated[list[dict[str, Any]], merge_sources]
    search_log: Annotated[list[str], operator.add]
    # analysis
    comparison: dict[str, Any]
    consensus_findings: list[str]
    coverage_score: float
    gap_queries: list[str]
    # output
    report: dict[str, Any]
    artifacts: dict[str, str]
    status: str
    followups: Annotated[list[dict[str, str]], operator.add]
