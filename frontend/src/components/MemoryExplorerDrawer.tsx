import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { MemoryItem, MemoryStats } from "../types";

function MemoryRow({ m, onDelete }: { m: MemoryItem; onDelete?: (id: string) => void }) {
  return (
    <li className="rounded-lg border border-slate-200 bg-white p-2.5 text-sm">
      <div className="mb-1 flex items-center gap-2 text-xs">
        <span className="rounded bg-purple-100 px-1.5 py-0.5 font-medium text-purple-700">{m.kind}</span>
        {m.score !== null && <span className="rounded bg-sky-100 px-1.5 py-0.5 text-sky-700">score {m.score.toFixed(2)}</span>}
        <span className="truncate text-slate-400">{m.topic}</span>
        {onDelete && <button onClick={() => onDelete(m.id)} className="ml-auto text-red-500 hover:underline" aria-label="Delete memory">delete</button>}
      </div>
      <p className="text-slate-700">{m.text}</p>
      <div className="mt-1 flex flex-wrap gap-1">
        {m.source_urls.slice(0, 4).map((u) => (
          <a key={u} href={u} target="_blank" rel="noopener noreferrer" className="max-w-[14rem] truncate text-xs text-indigo-600 hover:underline">{u}</a>
        ))}
      </div>
      <div className="mt-0.5 text-[11px] text-slate-400">verified {m.verified_at}</div>
    </li>
  );
}

/** "Agent Memory" tab: recalled-at-start vs newly stored memories for the current run. */
export function RunMemoryPanel({ recalled, stored }: { recalled: MemoryItem[]; stored: MemoryItem[] }) {
  return (
    <div className="grid gap-4 p-4 md:grid-cols-2">
      <section>
        <h3 className="mb-2 text-sm font-semibold text-purple-700">Recalled at start ({recalled.length})</h3>
        <ul className="space-y-2">{recalled.map((m) => <MemoryRow key={m.id} m={m} />)}</ul>
        {recalled.length === 0 && <p className="text-sm text-slate-400">No prior knowledge matched this topic.</p>}
      </section>
      <section>
        <h3 className="mb-2 text-sm font-semibold text-emerald-700">Newly stored ({stored.length})</h3>
        <ul className="space-y-2">{stored.map((m) => <MemoryRow key={m.id} m={m} />)}</ul>
        {stored.length === 0 && <p className="text-sm text-slate-400">Nothing stored yet.</p>}
      </section>
    </div>
  );
}

/** Drawer to inspect, semantically search and delete long-term ChromaDB memories across sessions. */
export default function MemoryExplorerDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<MemoryItem[]>([]);
  const [stats, setStats] = useState<MemoryStats | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (q: string) => {
    try {
      setError(null);
      const [list, s] = await Promise.all([q.trim() ? api.memorySearch(q) : api.memoryItems(), api.memoryStats()]);
      setItems(list);
      setStats(s);
    } catch (e) { setError((e as Error).message); }
  }, []);

  useEffect(() => { if (open) void load(""); }, [open, load]);

  const remove = async (id: string) => { await api.memoryDelete(id); void load(query); };

  if (!open) return null;
  return (
    <aside className="fixed inset-y-0 right-0 z-30 flex w-full max-w-md flex-col bg-slate-50 shadow-2xl ring-1 ring-slate-300">
      <header className="flex items-center justify-between border-b border-slate-200 bg-white p-3">
        <div>
          <h2 className="font-semibold">Long-term memory</h2>
          {stats && <p className="text-xs text-slate-500">{stats.total} items · {stats.topics} topics · {Object.entries(stats.by_kind).map(([k, v]) => `${k}:${v}`).join(" ")}</p>}
        </div>
        <button onClick={onClose} className="rounded px-2 py-1 text-slate-500 hover:bg-slate-100" aria-label="Close memory drawer">✕</button>
      </header>
      <form className="flex gap-2 border-b border-slate-200 p-3" onSubmit={(e) => { e.preventDefault(); void load(query); }}>
        <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Semantic search (e.g. agent frameworks)…"
          className="min-w-0 flex-1 rounded-lg border border-slate-300 px-3 py-1.5 text-sm outline-none focus:border-indigo-500" />
        <button className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700">Search</button>
      </form>
      <ul className="flex-1 space-y-2 overflow-y-auto p-3">
        {error && <li className="text-sm text-red-600">{error}</li>}
        {items.map((m) => <MemoryRow key={m.id} m={m} onDelete={remove} />)}
        {!error && items.length === 0 && <li className="text-sm text-slate-400">No memories yet — complete a research run first.</li>}
      </ul>
    </aside>
  );
}
