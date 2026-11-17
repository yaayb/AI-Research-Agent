import { useEffect, useRef } from "react";
import type { AgentEvent } from "../types";

const NODES = ["recall_memory", "plan_research", "investigator_agent", "execute_tools", "compare_sources", "reflect_coverage", "synthesize_report"];
const LABEL: Record<string, string> = {
  recall_memory: "Recall", plan_research: "Plan", investigator_agent: "Investigate", execute_tools: "Tools",
  compare_sources: "Compare", reflect_coverage: "Reflect", synthesize_report: "Synthesize",
};

type Row = { icon: string; text: string; tone: string };

function describe(e: AgentEvent): Row | null {
  switch (e.type) {
    case "session_started": return { icon: "🚀", text: `Started "${e.topic}" · ${e.depth} (max ${e.max_iterations} loops) · ${e.llm} + ${e.search}`, tone: "text-slate-700" };
    case "session_resumed": return { icon: "▶️", text: "Plan approved — resuming", tone: "text-slate-700" };
    case "node_start": return { icon: "◉", text: `${e.node} · loop ${e.iteration + 1}`, tone: "text-indigo-700 font-semibold" };
    case "memory_recalled": return { icon: "🧠", text: `Recalled ${e.items.length} prior memories`, tone: "text-purple-700" };
    case "plan": return { icon: "🗺️", text: `Plan${e.approved ? " (approved)" : ""}: ${e.plan.sub_questions.length} sub-questions, ${e.plan.initial_queries.length} initial queries`, tone: "text-blue-700" };
    case "plan_approval_required": return { icon: "⏸️", text: "Waiting for plan approval", tone: "text-amber-700 font-semibold" };
    case "tool_call": {
      const arg = String(e.args.query ?? e.args.url ?? JSON.stringify(e.args));
      return { icon: e.tool === "web_search" ? "🔎" : e.tool === "read_webpage" ? "📄" : "🧠", text: `${e.tool}("${arg}")`, tone: "font-mono text-xs text-slate-800" };
    }
    case "tool_result": return { icon: e.ok ? "✔" : "✘", text: e.summary, tone: e.ok ? "text-emerald-700 text-xs" : "text-red-600 text-xs" };
    case "source": return { icon: "•", text: `${e.domain} — ${e.title || e.url}${e.status === "failed" ? ` (failed: ${e.error})` : e.status === "read" ? " (read in full)" : ""}`, tone: "text-slate-500 text-xs" };
    case "comparison": return { icon: "⚖️", text: `${e.corroborated} corroborated · ${e.disputed} disputed · ${e.sources} sources`, tone: "text-slate-700" };
    case "reflection": return { icon: "🪞", text: `Coverage ${(e.coverage_score * 100).toFixed(0)}% · loop ${e.iteration}/${e.max_iterations} → ${e.decision}${e.gap_queries.length ? ` (gaps: ${e.gap_queries.join("; ")})` : ""}`, tone: e.decision === "synthesize" ? "text-emerald-700 font-semibold" : "text-amber-700 font-semibold" };
    case "memory_stored": return { icon: "💾", text: `Stored ${e.count} items in long-term memory`, tone: "text-purple-700" };
    case "artifacts": return { icon: "📦", text: "Exported .md, .html and .pdf", tone: "text-slate-700" };
    case "complete": return { icon: "🏁", text: `Complete: ${e.title}`, tone: "text-emerald-700 font-bold" };
    case "error": return { icon: "⚠️", text: e.message, tone: "text-red-600 font-semibold" };
    default: return null;
  }
}

export default function LiveAgentGraphFeed({ events, running }: { events: AgentEvent[]; running: boolean }) {
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [events.length]);

  const starts = events.filter((e): e is Extract<AgentEvent, { type: "node_start" }> => e.type === "node_start");
  const active = running ? starts[starts.length - 1]?.node : undefined;
  const visited = new Set(starts.map((s) => s.node));
  const lastReflection = [...events].reverse().find((e): e is Extract<AgentEvent, { type: "reflection" }> => e.type === "reflection");
  const sources = events.filter((e) => e.type === "source").length;
  const rows = events.map((e, i) => ({ row: describe(e), i })).filter((r): r is { row: Row; i: number } => r.row !== null);

  return (
    <section className="flex h-full min-h-[24rem] flex-col rounded-xl bg-white shadow-sm ring-1 ring-slate-200">
      <header className="border-b border-slate-100 p-3">
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-700">Live execution timeline</h2>
          <span className="text-xs text-slate-500">
            {sources} sources{lastReflection ? ` · coverage ${(lastReflection.coverage_score * 100).toFixed(0)}%` : ""}
          </span>
        </div>
        <ol className="flex flex-wrap gap-1.5">
          {NODES.map((n) => (
            <li key={n} className={`rounded-md px-2 py-0.5 text-xs ring-1 ${
              active === n ? "animate-pulse bg-indigo-600 text-white ring-indigo-600"
                : visited.has(n) ? "bg-indigo-50 text-indigo-700 ring-indigo-200" : "bg-slate-50 text-slate-400 ring-slate-200"}`}>
              {LABEL[n]}
            </li>
          ))}
        </ol>
      </header>
      <div className="flex-1 space-y-1 overflow-y-auto p-3 text-sm" style={{ maxHeight: "34rem" }}>
        {rows.length === 0 && <p className="text-slate-400">Agent activity will stream here in real time.</p>}
        {rows.map(({ row, i }) => (
          <div key={i} className={`flex gap-2 ${row.tone}`}>
            <span className="w-5 shrink-0 text-center">{row.icon}</span>
            <span className="min-w-0 break-words">{row.text}</span>
          </div>
        ))}
        {running && <div className="pl-7 text-xs text-slate-400">working…</div>}
        <div ref={endRef} />
      </div>
    </section>
  );
}
