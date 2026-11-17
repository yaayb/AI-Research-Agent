import { useState } from "react";
import type { Depth, ProviderStatus } from "../types";

interface Props {
  providers: ProviderStatus | null;
  running: boolean;
  onStart: (topic: string, depth: Depth, approval: boolean) => void;
}

const EXAMPLES = [
  "Compare open-source AI agent frameworks in 2026",
  "State of solid-state battery commercialization",
];

function Pill({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ring-1 ${
      ok ? "bg-emerald-50 text-emerald-700 ring-emerald-200" : "bg-amber-50 text-amber-700 ring-amber-200"}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${ok ? "bg-emerald-500" : "bg-amber-500"}`} />
      {label}
    </span>
  );
}

export default function ResearchPromptBar({ providers, running, onStart }: Props) {
  const [topic, setTopic] = useState("");
  const [depth, setDepth] = useState<Depth>("quick");
  const [approval, setApproval] = useState(false);
  const canStart = topic.trim().length >= 3 && !running;

  const llmLabel = providers
    ? providers.offline ? "Offline scripted LLM"
      : `${providers.llm_provider === "gemini" ? "Gemini" : "OpenAI"} · ${providers.llm_model}${providers.llm_configured ? "" : " (no key)"}`
    : "Connecting…";
  const searchLabel = providers
    ? providers.search_provider === "tavily" ? "Tavily Search" : providers.search_provider === "offline" ? "Offline fixtures" : "DDGS Free Search"
    : "…";

  return (
    <form
      className="rounded-xl bg-white p-4 shadow-sm ring-1 ring-slate-200"
      onSubmit={(e) => { e.preventDefault(); if (canStart) onStart(topic.trim(), depth, approval); }}
    >
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <h1 className="mr-auto text-lg font-bold tracking-tight text-indigo-700">DeepBrief AI <span className="font-normal text-slate-500">Research Studio</span></h1>
        <Pill ok={!!providers?.llm_configured} label={llmLabel} />
        <Pill ok={!!providers} label={searchLabel} />
      </div>
      <textarea
        value={topic} onChange={(e) => setTopic(e.target.value)} rows={2} disabled={running}
        placeholder="Describe a complex research topic…"
        className="w-full resize-none rounded-lg border border-slate-300 p-3 text-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-200 disabled:bg-slate-50"
      />
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <div className="inline-flex overflow-hidden rounded-lg ring-1 ring-slate-300" role="radiogroup" aria-label="Research depth">
          {(["quick", "deep"] as Depth[]).map((d) => (
            <button type="button" key={d} role="radio" aria-checked={depth === d} onClick={() => setDepth(d)} disabled={running}
              className={`px-3 py-1.5 text-sm ${depth === d ? "bg-indigo-600 text-white" : "bg-white text-slate-700 hover:bg-slate-50"}`}>
              {d === "quick" ? "Quick · 2 loops" : "Deep · 4 loops"}
            </button>
          ))}
        </div>
        <label className="flex items-center gap-2 text-sm text-slate-600">
          <input type="checkbox" checked={approval} onChange={(e) => setApproval(e.target.checked)} disabled={running} />
          Approve plan before searching
        </label>
        <div className="hidden gap-2 text-xs text-slate-500 md:flex">
          {EXAMPLES.map((ex) => (
            <button type="button" key={ex} onClick={() => setTopic(ex)} disabled={running} className="underline decoration-dotted hover:text-indigo-600">
              {ex.length > 34 ? ex.slice(0, 34) + "…" : ex}
            </button>
          ))}
        </div>
        <button type="submit" disabled={!canStart}
          className="ml-auto rounded-lg bg-indigo-600 px-5 py-2 text-sm font-semibold text-white shadow-sm hover:bg-indigo-700 disabled:cursor-not-allowed disabled:bg-slate-300">
          {running ? "Researching…" : "Start research"}
        </button>
      </div>
    </form>
  );
}
