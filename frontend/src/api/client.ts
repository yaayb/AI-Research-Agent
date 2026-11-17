import type {
  AgentEvent, Depth, MemoryItem, MemoryStats, ProviderStatus, ResearchPlan, ResearchResult,
} from "../types";

async function http<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, { headers: { "Content-Type": "application/json" }, ...init });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail ?? detail; } catch { /* non-JSON error */ }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res.json() as Promise<T>;
}

export const api = {
  providers: () => http<ProviderStatus>("/api/research/providers"),
  start: (topic: string, depth: Depth, requirePlanApproval: boolean) =>
    http<{ session_id: string }>("/api/research/start", {
      method: "POST",
      body: JSON.stringify({ topic, depth, require_plan_approval: requirePlanApproval }),
    }),
  approve: (id: string, plan?: Partial<ResearchPlan>) =>
    http<{ status: string }>(`/api/research/${id}/approve`, { method: "POST", body: JSON.stringify(plan ?? {}) }),
  result: (id: string) => http<ResearchResult>(`/api/research/${id}/result`),
  followup: (id: string, question: string) =>
    http<{ question: string; answer: string }>(`/api/research/${id}/followup`, {
      method: "POST", body: JSON.stringify({ question }),
    }),
  downloadUrl: (id: string, fmt: "md" | "html" | "pdf") => `/api/reports/${id}/download/${fmt}`,
  memorySearch: (q: string) => http<MemoryItem[]>(`/api/memory/search?q=${encodeURIComponent(q)}&k=10`),
  memoryItems: () => http<MemoryItem[]>("/api/memory/items?limit=100"),
  memoryStats: () => http<MemoryStats>("/api/memory/stats"),
  memoryDelete: (id: string) => http<{ deleted: boolean }>(`/api/memory/${encodeURIComponent(id)}`, { method: "DELETE" }),
};

/** Subscribe to a run's SSE telemetry. Returns a disposer. EventSource auto-resumes via Last-Event-ID. */
export function streamRun(
  id: string, onEvent: (e: AgentEvent) => void, onEnd: () => void, onFail: (msg: string) => void,
): () => void {
  const es = new EventSource(`/api/research/${id}/stream`);
  es.onmessage = (m) => {
    try { onEvent(JSON.parse(m.data) as AgentEvent); } catch { /* ignore malformed frame */ }
  };
  es.addEventListener("end", () => { es.close(); onEnd(); });
  es.onerror = () => {
    if (es.readyState === EventSource.CLOSED) onFail("Live stream closed unexpectedly");
  };
  return () => es.close();
}
