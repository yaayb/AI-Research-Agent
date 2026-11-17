"""SQLAlchemy 2.0 ORM tables for session & report metadata.

Design decision: relational metadata (status, paths, per-source credibility) lives here, while the
agent's *working* state lives in the LangGraph checkpointer and *knowledge* lives in ChromaDB.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class ResearchSession(Base):
    __tablename__ = "research_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    topic: Mapped[str] = mapped_column(Text)
    depth: Mapped[str] = mapped_column(String(16), default="quick")
    status: Mapped[str] = mapped_column(String(24), default="PENDING")  # PENDING|RUNNING|AWAITING_APPROVAL|COMPLETED|FAILED
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    iterations: Mapped[int] = mapped_column(Integer, default=0)
    coverage_score: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    sources: Mapped[list["SourceRecord"]] = relationship(back_populates="session", cascade="all, delete-orphan")
    reports: Mapped[list["GeneratedReport"]] = relationship(back_populates="session", cascade="all, delete-orphan")


class SourceRecord(Base):
    __tablename__ = "source_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("research_sessions.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(Text)
    domain: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(Text, default="")
    published_date: Mapped[str | None] = mapped_column(String(64), nullable=True)
    credibility_tier: Mapped[str] = mapped_column(String(16), default="medium")
    relevance_score: Mapped[float] = mapped_column(Float, default=0.5)
    key_takeaway: Mapped[str] = mapped_column(Text, default="")

    session: Mapped[ResearchSession] = relationship(back_populates="sources")


class GeneratedReport(Base):
    __tablename__ = "generated_reports"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("research_sessions.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(Text)
    topic: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[str] = mapped_column(String(16), default="Medium")
    summary: Mapped[str] = mapped_column(Text, default="")
    source_count: Mapped[int] = mapped_column(Integer, default=0)
    md_path: Mapped[str] = mapped_column(Text, default="")
    html_path: Mapped[str] = mapped_column(Text, default="")
    pdf_path: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    session: Mapped[ResearchSession] = relationship(back_populates="reports")
