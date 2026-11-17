import type { ComparisonAnalysis } from "../types";

const TIER: Record<string, string> = {
  high: "bg-emerald-100 text-emerald-800",
  medium: "bg-amber-100 text-amber-800",
  low: "bg-red-100 text-red-800",
};

export default function SourceComparisonTable({ comparison }: { comparison: ComparisonAnalysis | null }) {
  if (!comparison) return <p className="p-6 text-sm text-slate-400">The comparison matrix appears once sources have been analysed.</p>;
  const domainOf = (url: string) => comparison.source_quality_table.find((q) => q.url === url)?.domain ?? new URL(url).hostname;
  const { corroborated_claims: corro, disputed_or_conflicting_claims: disputed, source_quality_table: quality } = comparison;

  return (
    <div className="space-y-6 p-4">
      <section>
        <h3 className="mb-2 text-sm font-semibold text-emerald-700">✔ Consensus ({corro.length})</h3>
        {corro.length === 0 ? <p className="text-sm text-slate-400">No claims corroborated by 2+ independent domains.</p> : (
          <div className="overflow-x-auto rounded-lg ring-1 ring-slate-200">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
                <tr><th className="p-2">Claim</th><th className="p-2">Supporting sources</th><th className="p-2">Confidence</th></tr>
              </thead>
              <tbody>
                {corro.map((c, i) => (
                  <tr key={i} className="border-t border-slate-100 align-top">
                    <td className="p-2">{c.claim}</td>
                    <td className="p-2">
                      <div className="flex flex-wrap gap-1">
                        {c.source_urls.map((u) => (
                          <a key={u} href={u} target="_blank" rel="noopener noreferrer" className="rounded bg-indigo-50 px-1.5 py-0.5 text-xs text-indigo-700 hover:underline">{domainOf(u)}</a>
                        ))}
                      </div>
                    </td>
                    <td className="p-2">{Math.round(c.confidence * 100)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section>
        <h3 className="mb-2 text-sm font-semibold text-red-700">⚠ Disputed / conflicting ({disputed.length})</h3>
        {disputed.length === 0 ? <p className="text-sm text-slate-400">No material contradictions detected.</p> : (
          <div className="space-y-3">
            {disputed.map((d, i) => (
              <div key={i} className="rounded-lg border border-red-200 bg-red-50/40 p-3">
                <p className="mb-2 text-sm font-medium">{d.claim}</p>
                <div className="grid gap-2 sm:grid-cols-2">
                  {d.positions.map((p) => (
                    <a key={p.url} href={p.url} target="_blank" rel="noopener noreferrer" className="rounded-md bg-white p-2 text-sm ring-1 ring-red-100 hover:ring-red-300">
                      <div className="text-xs text-slate-500">{p.domain} · {p.published_date ?? "date n/a"}</div>
                      <div className="font-semibold text-red-700">{p.stance_or_figure}</div>
                    </a>
                  ))}
                </div>
                {d.likely_explanation && <p className="mt-2 text-xs text-slate-600">Likely reason: {d.likely_explanation}</p>}
              </div>
            ))}
          </div>
        )}
      </section>

      <section>
        <h3 className="mb-2 text-sm font-semibold text-slate-700">Per-source credibility ({quality.length})</h3>
        <div className="overflow-x-auto rounded-lg ring-1 ring-slate-200">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
              <tr><th className="p-2">Source</th><th className="p-2">Credibility</th><th className="p-2">Relevance</th><th className="p-2">Key takeaway</th></tr>
            </thead>
            <tbody>
              {quality.map((q) => (
                <tr key={q.url} className="border-t border-slate-100 align-top">
                  <td className="p-2"><a href={q.url} target="_blank" rel="noopener noreferrer" className="font-medium text-indigo-700 hover:underline">{q.title || q.domain}</a><div className="text-xs text-slate-400">{q.domain}</div></td>
                  <td className="p-2"><span className={`rounded-full px-2 py-0.5 text-xs font-medium ${TIER[q.credibility_tier]}`}>{q.credibility_tier}</span></td>
                  <td className="p-2">
                    <div className="h-1.5 w-20 rounded bg-slate-200"><div className="h-1.5 rounded bg-indigo-500" style={{ width: `${q.relevance_score * 100}%` }} /></div>
                    <span className="text-xs text-slate-500">{q.relevance_score.toFixed(2)}</span>
                  </td>
                  <td className="p-2 text-slate-600">{q.key_takeaway}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
