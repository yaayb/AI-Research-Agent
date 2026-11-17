"""Short-term (thread-scoped) memory: LangGraph checkpointers.

Design decisions
- ``AsyncSqliteSaver`` persists every super-step per ``thread_id`` (= research session id), which is
  what enables resume-after-restart, human plan approval (``interrupt``) and grounded follow-ups.
- ``MemorySaver`` is used in unit tests (``in_memory=True``) so no files are touched.
- Exposed as an async context manager so the aiosqlite connection is always closed cleanly.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

import aiosqlite
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.config import Settings, get_settings


def thread_config(session_id: str, **extra) -> dict:
    return {"configurable": {"thread_id": session_id}, "recursion_limit": 120, **extra}


@asynccontextmanager
async def open_checkpointer(settings: Settings | None = None, in_memory: bool = False) -> AsyncIterator[BaseCheckpointSaver]:
    if in_memory:
        yield MemorySaver()
        return
    s = settings or get_settings()
    s.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(str(s.checkpoint_path))
    try:
        saver = AsyncSqliteSaver(conn)
        await saver.setup()
        yield saver
    finally:
        await conn.close()
