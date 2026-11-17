export type Depth = "quick" | "deep";

export interface MemoryItem {
  id: string;
  text: string;
  score: number | null;
  kind: string;
  topic: string;
  source_urls: string[];
  verified_at: string;
  session_id: string;
  confidence: number;
}

export interface ResearchPlan {
  research_goal: string;
  sub_questions: string[];
  initial_queries: string[];
}

export interface ClaimPosition { url: string; domain: string; stance_or_figure: string; published_date?: string | null }
export interface CorroboratedClaim { claim: string; source_urls: string[]; confidence: number }
export interface DisputedClaim { claim: string; positions: ClaimPosition[]; likely_explanation: string }
export interface SourceQuality {
  url: string; domain: string; title: string; relevance_score: number;
  credibility_tier: "high" | "medium" | "low"; key_takeaway: string;
}
export interface ComparisonAnalysis {
  corroborated_claims: CorroboratedClaim[];
  disputed_or_conflicting_claims: DisputedClaim[];
  source_quality_table: SourceQuality[];
}

export interface SourceRef { url: string; title: string; domain: string; published_date?: string | null }
export interface ReportSection { heading: string; body_markdown: string }
export interface FinalReport {
  title: string; topic: string; generated_at: string; executive_summary: string;
  confidence_rating: "High" | "Medium" | "Low"; confidence_rationale: string;
  key_findings: string[]; sections: ReportSection[]; risks_limitations: string[]; open_questions: string[];
  iterations: number; coverage_score: number; sources: SourceRef[]; comparison: ComparisonAnalysis;
}

export interface FollowUp { question: string; answer: string }

export interface ResearchResult {
  session_id: string; topic: string; status: string;
  plan: ResearchPlan | null; report: FinalReport | null; comparison: ComparisonAnalysis | null;
  consensus_findings: string[]; prior_knowledge: MemoryItem[]; stored_facts: MemoryItem[];
  coverage_score: number; iterations: number; followups: FollowUp[];
}

export interface ProviderStatus {
  llm_provider: string; llm_model: string; llm_configured: boolean; search_provider: string; offline: boolean;
}

export interface MemoryStats { total: number; by_kind: Record<string, number>; topics: number; last_updated: string | null }

/** Telemetry event emitted by the LangGraph run (see backend/app/agent/nodes.py). */
export type AgentEvent =
  | { type: "session_started"; session_id: string; topic: string; depth: string; max_iterations: number; llm: string; search: string }
  | { type: "session_resumed"; session_id: string }
  | { type: "node_start"; node: string; iteration: number }
  | { type: "node_end"; node: string }
  | { type: "memory_recalled"; items: MemoryItem[] }
  | { type: "plan"; plan: ResearchPlan; approved?: boolean }
  | { type: "plan_approval_required"; plan: ResearchPlan }
  | { type: "tool_call"; tool: string; args: Record<string, unknown> }
  | { type: "tool_result"; tool: string; ok: boolean; summary: string; count: number }
  | { type: "source"; url: string; title: string; domain: string; status: string; error?: string | null }
  | { type: "comparison"; corroborated: number; disputed: number; sources: number }
  | { type: "reflection"; coverage_score: number; iteration: number; max_iterations: number; gap_queries: string[]; decision: string; rationale?: string }
  | { type: "memory_stored"; count: number; items: MemoryItem[] }
  | { type: "artifacts"; artifacts: Record<string, string> }
  | { type: "complete"; session_id: string; title: string; coverage_score: number; iterations: number; sources: number }
  | { type: "error"; message: string };
