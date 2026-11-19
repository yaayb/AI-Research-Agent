import type {
  AgentEvent, Depth, MemoryItem, MemoryStats, ProviderStatus, ResearchPlan, ResearchResult,
} from "../types";

const KEY_STORAGE = "deepbrief_access_key";
export const getAccessKey = () => localStorage.getItem(KEY_STORAGE) ?? "";
export const setAccessKey = (k: string) => localStorage.setItem(KEY_STORAGE, k);
/** Append ?key= for requests the browser makes without custom headers (SSE, downloads). */
const withKey = (url: string) => {
  const k = getAccessKey();
  return k ? `${url}${url.includes("?") ? "&" : "?"}key=${encodeURIComponent(k)}` : url;
};

export class AuthError extends Error {}

async function http<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, { headers: { "Content-Type": "application/json", "X-Access-Key": getAccessKey() }, ...init });
  if (res.status === 401) throw new AuthError("Access key required");
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
  downloadUrl: (id: string, fmt: "md" | "html" | "pdf") => withKey(`/api/reports/${id}/download/${fmt}`),
  memorySearch: (q: string) => http<MemoryItem[]>(`/api/memory/search?q=${encodeURIComponent(q)}&k=10`),
  memoryItems: () => http<MemoryItem[]>("/api/memory/items?limit=100"),
  memoryStats: () => http<MemoryStats>("/api/memory/stats"),
  memoryDelete: (id: string) => http<{ deleted: boolean }>(`/api/memory/${encodeURIComponent(id)}`, { method: "DELETE" }),
};

/** Subscribe to a run's SSE telemetry. Returns a disposer. EventSource auto-resumes via Last-Event-ID. */
export function streamRun(
  id: string, onEvent: (e: AgentEvent) => void, onEnd: () => void, onFail: (msg: string) => void,
): () => void {
  const es = new EventSource(withKey(`/api/research/${id}/stream`));
  es.onmessage = (m) => {
    try { onEvent(JSON.parse(m.data) as AgentEvent); } catch { /* ignore malformed frame */ }
  };
  es.addEventListener("end", () => { es.close(); onEnd(); });
  es.onerror = () => {
    if (es.readyState === EventSource.CLOSED) onFail("Live stream closed unexpectedly");
  };
  return () => es.close();
}
