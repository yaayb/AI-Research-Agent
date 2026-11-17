"""Research routes: start, SSE stream, plan approval, results and follow-up chat.

Design decisions
- Each run executes in a background task that appends events to an in-memory ``RunChannel``;
  SSE clients replay from ``Last-Event-ID`` so refresh/reconnect never loses the timeline.
- Results are read back from the LangGraph checkpoint (single source of truth), which also
  makes completed sessions viewable after the server restarts.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from app.agent.graph import answer_followup, get_thread_values, stream_research
from app.database import create_session_row, get_session_row, list_sessions
from app.schemas.research import ApprovePlanRequest, FollowUpRequest, StartResearchRequest

router = APIRouter(prefix="/api/research", tags=["research"])


class RunChannel:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.cond = asyncio.Condition()
        self.finished = False

    async def push(self, ev: dict[str, Any]) -> None:
        async with self.cond:
            self.events.append(ev)
            self.cond.notify_all()

    async def finish(self) -> None:
        async with self.cond:
            self.finished = True
            self.cond.notify_all()


async def _run(request_app, sid: str, channel: RunChannel, topic: str, depth: str, approval: bool, resume: Any = None) -> None:
    ctx = request_app.state.ctx
    try:
        async for ev in stream_research(ctx.graph, topic, sid, depth, approval, resume, ctx.settings):
            await channel.push(ev)
    except Exception as exc:  # noqa: BLE001
        await channel.push({"type": "error", "message": str(exc)})
    finally:
        await channel.finish()


@router.post("/start")
async def start_research(body: StartResearchRequest, request: Request) -> dict[str, Any]:
    ctx = request.app.state.ctx
    if not ctx.settings.llm_configured:
        raise HTTPException(400, f"LLM provider '{ctx.settings.llm_provider}' has no API key. Set it in .env or enable OFFLINE_TEST_MODE.")
    sid = uuid.uuid4().hex[:12]
    await create_session_row(sid, body.topic, body.depth)
    channel = RunChannel()
    ctx.channels[sid] = channel
    ctx.meta[sid] = {"topic": body.topic, "depth": body.depth, "approval": body.require_plan_approval}
    task = asyncio.create_task(_run(request.app, sid, channel, body.topic, body.depth, body.require_plan_approval))
    ctx.tasks.add(task)
    task.add_done_callback(ctx.tasks.discard)
    return {"session_id": sid, "stream_url": f"/api/research/{sid}/stream"}


@router.get("/providers")
async def providers(request: Request) -> dict[str, Any]:
    s = request.app.state.ctx.settings
    return {"llm_provider": "offline" if s.offline_test_mode else s.llm_provider, "llm_model": s.active_llm_model,
            "llm_configured": s.llm_configured, "search_provider": s.search_provider, "offline": s.offline_test_mode}


@router.get("")
async def sessions() -> list[dict[str, Any]]:
    return [{"id": r.id, "topic": r.topic, "depth": r.depth, "status": r.status, "created_at": r.created_at.isoformat(),
             "coverage_score": r.coverage_score} for r in await list_sessions()]


@router.get("/{session_id}/stream")
async def stream(session_id: str, request: Request) -> EventSourceResponse:
    channel: RunChannel | None = request.app.state.ctx.channels.get(session_id)
    if channel is None:
        raise HTTPException(404, "Unknown or expired live session (completed sessions: use GET /result)")
    last = request.headers.get("last-event-id")
    start = int(last) + 1 if last and last.isdigit() else 0

    async def gen():
        idx = start
        while True:
            async with channel.cond:
                while idx >= len(channel.events) and not channel.finished:
                    try:
                        await asyncio.wait_for(channel.cond.wait(), timeout=15)
                    except asyncio.TimeoutError:
                        break
                batch = channel.events[idx:]
                done = channel.finished and idx + len(batch) >= len(channel.events)
            for ev in batch:
                yield {"id": str(idx), "data": json.dumps(ev, default=str)}
                idx += 1
            if done:
                yield {"event": "end", "data": "{}"}
                return
            if await request.is_disconnected():
                return

    return EventSourceResponse(gen(), ping=10)


@router.post("/{session_id}/approve")
async def approve_plan(session_id: str, body: ApprovePlanRequest, request: Request) -> dict[str, str]:
    ctx = request.app.state.ctx
    meta = ctx.meta.get(session_id)
    if meta is None:
        raise HTTPException(404, "Unknown session")
    row = await get_session_row(session_id)
    if row is None or row.status != "AWAITING_APPROVAL":
        raise HTTPException(409, "Session is not awaiting plan approval")
    channel = RunChannel()
    channel.events = list(ctx.channels[session_id].events)  # keep timeline continuity
    ctx.channels[session_id] = channel
    resume = body.model_dump()
    task = asyncio.create_task(_run(request.app, session_id, channel, meta["topic"], meta["depth"], True, resume))
    ctx.tasks.add(task)
    task.add_done_callback(ctx.tasks.discard)
    return {"status": "resumed"}


@router.get("/{session_id}/result")
async def result(session_id: str, request: Request) -> dict[str, Any]:
    ctx = request.app.state.ctx
    vals = await get_thread_values(ctx.graph, session_id)
    if not vals:
        raise HTTPException(404, "No state for this session")
    sources = [{k: v for k, v in s.items() if k != "content"} for s in vals.get("collected_sources", [])]
    return {"session_id": session_id, "topic": vals.get("topic"), "status": vals.get("status", "RUNNING"),
            "plan": vals.get("plan"), "report": vals.get("report"), "comparison": vals.get("comparison"),
            "consensus_findings": vals.get("consensus_findings", []), "prior_knowledge": vals.get("prior_knowledge", []),
            "stored_facts": vals.get("stored_facts", []), "sources": sources, "search_log": vals.get("search_log", []),
            "coverage_score": vals.get("coverage_score", 0), "iterations": vals.get("iteration", 0),
            "artifacts": vals.get("artifacts", {}), "followups": vals.get("followups", [])}


@router.post("/{session_id}/followup")
async def followup(session_id: str, body: FollowUpRequest, request: Request) -> dict[str, str]:
    ctx = request.app.state.ctx
    row = await get_session_row(session_id)
    if row is None:
        raise HTTPException(404, "Unknown session")
    if row.status != "COMPLETED":
        raise HTTPException(409, f"Research is {row.status}; follow-ups need a completed run")
    try:
        answer = await answer_followup(ctx.graph, session_id, body.question)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"question": body.question, "answer": answer}
