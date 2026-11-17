"""Pydantic v2 schemas used for strict structured LLM outputs and API payloads.

Design decisions
- Everything the LLM must return is a Pydantic model passed to ``with_structured_output``; the
  graph state itself stores plain ``dict`` dumps so checkpoints stay JSON-serialisable.
- ``FinalReportDraft`` is what the LLM writes; ``FinalReport`` adds system-owned facts (sources,
  comparison matrix, dates) so the model can never fabricate them.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ResearchPlan(BaseModel):
    research_goal: str = Field(description="One-sentence statement of what the research must establish.")
    sub_questions: list[str] = Field(description="3-6 investigative sub-questions that together cover the topic.")
    initial_queries: list[str] = Field(description="3-6 concrete web search queries to start with.")


class ExtractedSource(BaseModel):
    url: str
    domain: str
    title: str = ""
    author: str | None = None
    published_date: str | None = None
    snippet: str = ""
    content: str = ""
    fetched_at: str | None = None
    status: Literal["snippet", "read", "failed"] = "snippet"


class ClaimPosition(BaseModel):
    url: str = Field(description="Exact URL retrieved during the run.")
    domain: str
    stance_or_figure: str = Field(description="The exact figure/date/stance this source reports.")
    published_date: str | None = None


class CorroboratedClaim(BaseModel):
    claim: str
    source_urls: list[str] = Field(description="Exact URLs of 2+ independent domains supporting the claim.")
    confidence: float = Field(ge=0, le=1, default=0.8)


class DisputedClaim(BaseModel):
    claim: str
    positions: list[ClaimPosition] = Field(description="Each source's exact figure/stance and date.")
    likely_explanation: str = ""


class SourceQuality(BaseModel):
    url: str
    domain: str
    title: str
    relevance_score: float = Field(ge=0, le=1)
    credibility_tier: Literal["high", "medium", "low"]
    key_takeaway: str


class ComparisonAnalysis(BaseModel):
    corroborated_claims: list[CorroboratedClaim] = Field(default_factory=list)
    disputed_or_conflicting_claims: list[DisputedClaim] = Field(default_factory=list)
    source_quality_table: list[SourceQuality] = Field(default_factory=list)


class CoverageReflection(BaseModel):
    coverage_score: float = Field(ge=0, le=1, description="Fraction of sub-questions with corroborated evidence.")
    uncovered_sub_questions: list[str] = Field(default_factory=list)
    gap_queries: list[str] = Field(default_factory=list, description="Targeted search queries to close the gaps.")
    rationale: str = ""


class ReportSection(BaseModel):
    heading: str
    body_markdown: str = Field(description="Markdown body with inline [Title](url) citations on every claim.")


class FinalReportDraft(BaseModel):
    title: str
    executive_summary: str
    confidence_rating: Literal["High", "Medium", "Low"]
    confidence_rationale: str = ""
    key_findings: list[str] = Field(description="Bullets, each carrying an inline citation.")
    sections: list[ReportSection] = Field(description="Deep-dive thematic sections.")
    risks_limitations: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


class SourceRef(BaseModel):
    url: str
    title: str
    domain: str
    published_date: str | None = None


class FinalReport(FinalReportDraft):
    topic: str = ""
    generated_at: str = ""
    research_scope: str = ""
    iterations: int = 0
    coverage_score: float = 0.0
    sources: list[SourceRef] = Field(default_factory=list)
    comparison: ComparisonAnalysis = Field(default_factory=ComparisonAnalysis)


class StartResearchRequest(BaseModel):
    topic: str = Field(min_length=3)
    depth: Literal["quick", "deep"] = "quick"
    require_plan_approval: bool = False


class FollowUpRequest(BaseModel):
    question: str = Field(min_length=2)


class ApprovePlanRequest(BaseModel):
    sub_questions: list[str] | None = None
    initial_queries: list[str] | None = None
