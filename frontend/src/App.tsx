import { useCallback, useEffect, useRef, useState } from "react";
import { api, streamRun } from "./api/client";
import FollowUpChatPanel from "./components/FollowUpChatPanel";
import LiveAgentGraphFeed from "./components/LiveAgentGraphFeed";
import MemoryExplorerDrawer, { RunMemoryPanel } from "./components/MemoryExplorerDrawer";
import ReportViewer from "./components/ReportViewer";
import ResearchPromptBar from "./components/ResearchPromptBar";
import SourceComparisonTable from "./components/SourceComparisonTable";
import type { AgentEvent, Depth, MemoryItem, ProviderStatus, ResearchPlan, ResearchResult } from "./types";

type Tab = "report" | "compare" | "memory";

export default function App() {
  const [providers, setProviders] = useState<ProviderStatus | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<ResearchResult | null>(null);
  const [tab, setTab] = useState<Tab>("report");
  const [error, setError] = useState<string | null>(null);
  const [pendingPlan, setPendingPlan] = useState<ResearchPlan | null>(null);
  const [drawer, setDrawer] = useState(false);
  const dispose = useRef<(() => void) | null>(null);

  useEffect(() => { api.providers().then(setProviders).catch((e: Error) => setError(`Backend unreachable: ${e.message}`)); }, []);
  useEffect(() => () => dispose.current?.(), []);

  const subscribe = useCallback((id: string) => {
    dispose.current?.();
    setRunning(true);
    dispose.current = streamRun(
      id,
      (e) => {
        setEvents((prev) => [...prev, e]);
        if (e.type === "plan_approval_required") { setPendingPlan(e.plan); setRunning(false); }
        if (e.type === "error") setError(e.message);
      },
      () => {
        setRunning(false);
        api.result(id).then((r) => { setResult(r); }).catch(() => undefined);
      },
      (msg) => { setRunning(false); setError(msg); },
    );
  }, []);

  const start = async (topic: string, depth: Depth, approval: boolean) => {
    setError(null); setResult(null); setEvents([]); setPendingPlan(null); setTab("report");
    try {
      const { session_id } = await api.start(topic, depth, approval);
      setSessionId(session_id);
      subscribe(session_id);
    } catch (e) { setError((e as Error).message); }
  };

  const approve = async () => {
    if (!sessionId) return;
    try {
      await api.approve(sessionId);
      setPendingPlan(null);
      subscribe(sessionId);
    } catch (e) { setError((e as Error).message); }
  };

  const recalled = (events.find((e) => e.type === "memory_recalled") as Extract<AgentEvent, { type: "memory_recalled" }> | undefined)?.items ?? [];
  const storedEv = events.find((e) => e.type === "memory_stored") as Extract<AgentEvent, { type: "memory_stored" }> | undefined;
  const stored: MemoryItem[] = result?.stored_facts?.length ? result.stored_facts : storedEv?.items ?? [];
  const done = result?.status === "COMPLETED" && !!result.report;

  const tabBtn = (t: Tab, label: string) => (
    <button key={t} onClick={() => setTab(t)} role="tab" aria-selected={tab === t}
      className={`border-b-2 px-4 py-2 text-sm font-medium ${tab === t ? "border-indigo-600 text-indigo-700" : "border-transparent text-slate-500 hover:text-slate-800"}`}>
      {label}
    </button>
  );

  return (
    <div className="mx-auto max-w-[96rem] space-y-4 p-4">
      <ResearchPromptBar providers={providers} running={running} onStart={start} />
      {error && (
        <div className="flex items-start justify-between rounded-lg bg-red-50 p-3 text-sm text-red-700 ring-1 ring-red-200" role="alert">
          <span>{error}</span><button onClick={() => setError(null)} aria-label="Dismiss error">✕</button>
        </div>
      )}
      {pendingPlan && (
        <div className="rounded-xl bg-amber-50 p-4 ring-1 ring-amber-300">
          <h3 className="font-semibold text-amber-800">Review the research plan</h3>
          <p className="mt-1 text-sm">{pendingPlan.research_goal}</p>
          <ul className="my-2 list-disc pl-6 text-sm">{pendingPlan.sub_questions.map((q) => <li key={q}>{q}</li>)}</ul>
          <p className="mb-2 text-xs text-slate-600">Initial queries: {pendingPlan.initial_queries.join(" · ")}</p>
          <button onClick={approve} className="rounded-lg bg-amber-600 px-4 py-1.5 text-sm font-semibold text-white hover:bg-amber-700">Approve & start searching</button>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[minmax(20rem,26rem)_1fr]">
        <div className="space-y-4">
          <LiveAgentGraphFeed events={events} running={running} />
          <FollowUpChatPanel sessionId={sessionId} ready={done} initial={result?.followups ?? []} />
        </div>
        <section className="min-h-[32rem] rounded-xl bg-white shadow-sm ring-1 ring-slate-200">
          <div className="flex items-center border-b border-slate-200 px-2" role="tablist">
            {tabBtn("report", "Report")}
            {tabBtn("compare", "Source Comparison Matrix")}
            {tabBtn("memory", "Agent Memory")}
            <button onClick={() => setDrawer(true)} className="ml-auto rounded-lg px-3 py-1.5 text-sm text-indigo-700 hover:bg-indigo-50">🧠 Memory explorer</button>
          </div>
          {tab === "report" && <ReportViewer report={result?.report ?? null} sessionId={done ? sessionId : null} />}
          {tab === "compare" && <SourceComparisonTable comparison={result?.comparison ?? null} />}
          {tab === "memory" && <RunMemoryPanel recalled={recalled} stored={stored} />}
        </section>
      </div>
      <MemoryExplorerDrawer open={drawer} onClose={() => setDrawer(false)} />
    </div>
  );
}
