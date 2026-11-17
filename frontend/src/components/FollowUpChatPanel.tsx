import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api } from "../api/client";
import type { FollowUp } from "../types";

interface Props { sessionId: string | null; ready: boolean; initial: FollowUp[] }

export default function FollowUpChatPanel({ sessionId, ready, initial }: Props) {
  const [turns, setTurns] = useState<FollowUp[]>(initial);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => { setTurns(initial); }, [initial, sessionId]);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [turns.length, busy]);

  const send = async () => {
    if (!sessionId || !q.trim() || busy) return;
    const question = q.trim();
    setQ(""); setBusy(true); setError(null);
    try {
      const r = await api.followup(sessionId, question);
      setTurns((t) => [...t, { question: r.question, answer: r.answer }]);
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };

  return (
    <section className="flex h-[28rem] flex-col rounded-xl bg-white shadow-sm ring-1 ring-slate-200">
      <header className="border-b border-slate-100 p-3">
        <h2 className="text-sm font-semibold text-slate-700">Follow-up chat</h2>
        <p className="text-xs text-slate-500">Answers come from the persisted LangGraph checkpoint — no re-scraping.</p>
      </header>
      <div className="flex-1 space-y-3 overflow-y-auto p-3 text-sm">
        {!ready && <p className="text-slate-400">Available once the report is complete.</p>}
        {ready && turns.length === 0 && (
          <p className="text-slate-400">Try: “Why did the sources disagree?” or “Expand section 1 with a table.”</p>
        )}
        {turns.map((t, i) => (
          <div key={i} className="space-y-1.5">
            <div className="ml-8 rounded-lg bg-indigo-600 px-3 py-2 text-white">{t.question}</div>
            <div className="report-prose mr-8 rounded-lg bg-slate-100 px-3 py-2">
              <ReactMarkdown remarkPlugins={[remarkGfm]}
                components={{ a: ({ href, children }) => <a href={href} target="_blank" rel="noopener noreferrer">{children}</a> }}>
                {t.answer}
              </ReactMarkdown>
            </div>
          </div>
        ))}
        {busy && <div className="text-xs text-slate-400">thinking…</div>}
        {error && <div className="text-xs text-red-600">{error}</div>}
        <div ref={endRef} />
      </div>
      <form className="flex gap-2 border-t border-slate-100 p-3" onSubmit={(e) => { e.preventDefault(); void send(); }}>
        <input value={q} onChange={(e) => setQ(e.target.value)} disabled={!ready || busy} placeholder="Ask a follow-up…"
          className="min-w-0 flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500 disabled:bg-slate-50" />
        <button disabled={!ready || busy || !q.trim()} className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:bg-slate-300">Send</button>
      </form>
    </section>
  );
}
