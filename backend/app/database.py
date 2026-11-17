"""SQLAlchemy 2.0 *async* engine + helpers for session & report metadata.

Design decision: a small ``Database`` holder (not import-time globals) so tests and the API can
bind to different SQLite files. All writes used by the agent go through ``persist_*`` helpers that
are no-ops until ``init`` has been called, keeping the graph usable standalone (CLI/tests).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.models import Base, GeneratedReport, ResearchSession, SourceRecord

log = logging.getLogger(__name__)


class Database:
    def __init__(self) -> None:
        self.engine: AsyncEngine | None = None
        self.maker: async_sessionmaker[AsyncSession] | None = None

    @property
    def ready(self) -> bool:
        return self.maker is not None

    async def init(self, db_path: str | Path) -> None:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{path.as_posix()}")
        self.maker = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def dispose(self) -> None:
        if self.engine is not None:
            await self.engine.dispose()
        self.engine = self.maker = None

    def session(self) -> AsyncSession:
        if self.maker is None:
            raise RuntimeError("Database not initialised")
        return self.maker()


db = Database()


async def create_session_row(session_id: str, topic: str, depth: str) -> None:
    if not db.ready:
        return
    async with db.session() as s:
        await s.merge(ResearchSession(id=session_id, topic=topic, depth=depth, status="PENDING"))
        await s.commit()


async def set_session_status(session_id: str, status: str, error: str | None = None) -> None:
    if not db.ready:
        return
    async with db.session() as s:
        row = await s.get(ResearchSession, session_id)
        if row is None:
            return
        row.status = status
        row.error = error
        if status in ("COMPLETED", "FAILED"):
            row.completed_at = datetime.now(timezone.utc)
        await s.commit()


async def persist_completed_run(
    session_id: str, report: dict[str, Any], artifacts: dict[str, str], iterations: int, coverage: float
) -> None:
    """Mark the session COMPLETED and store report + per-source credibility metadata."""
    if not db.ready:
        return
    async with db.session() as s:
        row = await s.get(ResearchSession, session_id)
        if row is None:
            row = ResearchSession(id=session_id, topic=report.get("topic", ""), depth="quick")
            s.add(row)
        row.status, row.error = "COMPLETED", None
        row.iterations, row.coverage_score = iterations, coverage
        row.completed_at = datetime.now(timezone.utc)
        await s.execute(delete(SourceRecord).where(SourceRecord.session_id == session_id))
        await s.execute(delete(GeneratedReport).where(GeneratedReport.session_id == session_id))
        quality = {q["url"]: q for q in report.get("comparison", {}).get("source_quality_table", [])}
        for src in report.get("sources", []):
            q = quality.get(src["url"], {})
            s.add(
                SourceRecord(
                    session_id=session_id, url=src["url"], domain=src["domain"], title=src.get("title", ""),
                    published_date=src.get("published_date"), credibility_tier=q.get("credibility_tier", "medium"),
                    relevance_score=q.get("relevance_score", 0.5), key_takeaway=q.get("key_takeaway", ""),
                )
            )
        s.add(
            GeneratedReport(
                id=session_id, session_id=session_id, title=report.get("title", ""), topic=report.get("topic", ""),
                confidence=report.get("confidence_rating", "Medium"), summary=report.get("executive_summary", "")[:1500],
                source_count=len(report.get("sources", [])), md_path=artifacts.get("md", ""),
                html_path=artifacts.get("html", ""), pdf_path=artifacts.get("pdf", ""),
            )
        )
        await s.commit()


async def list_reports() -> list[GeneratedReport]:
    async with db.session() as s:
        res = await s.execute(select(GeneratedReport).order_by(GeneratedReport.created_at.desc()))
        return list(res.scalars())


async def get_report(report_or_session_id: str) -> GeneratedReport | None:
    async with db.session() as s:
        res = await s.execute(
            select(GeneratedReport).where(
                (GeneratedReport.id == report_or_session_id) | (GeneratedReport.session_id == report_or_session_id)
            )
        )
        return res.scalars().first()


async def get_session_row(session_id: str) -> ResearchSession | None:
    async with db.session() as s:
        return await s.get(ResearchSession, session_id)


async def list_sessions() -> list[ResearchSession]:
    async with db.session() as s:
        res = await s.execute(select(ResearchSession).order_by(ResearchSession.created_at.desc()))
        return list(res.scalars())
