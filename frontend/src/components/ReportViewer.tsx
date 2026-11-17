import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api } from "../api/client";
import type { FinalReport } from "../types";

function toMarkdown(r: FinalReport): string {
  const parts = [
    `# ${r.title}`,
    `> **Topic:** ${r.topic} · **Generated:** ${r.generated_at} · **Sources:** ${r.sources.length} · **Confidence:** ${r.confidence_rating} · **Coverage:** ${Math.round(r.coverage_score * 100)}%`,
    `## Executive Summary\n\n${r.executive_summary}`,
    r.confidence_rationale ? `**Confidence — ${r.confidence_rating}:** ${r.confidence_rationale}` : "",
    `## Key Findings\n\n${r.key_findings.map((f) => `- ${f}`).join("\n")}`,
    ...r.sections.map((s) => `## ${s.heading}\n\n${s.body_markdown}`),
    `## Risks, Limitations & Open Questions\n\n${r.risks_limitations.map((x) => `- ${x}`).join("\n")}\n\n**Open questions**\n\n${r.open_questions.map((x) => `- ${x}`).join("\n")}`,
    `## Verified References\n\n${r.sources.map((s, i) => `${i + 1}. [${s.title}](${s.url}) — ${s.domain}${s.published_date ? `, ${s.published_date}` : ""}`).join("\n")}`,
  ];
  return parts.filter(Boolean).join("\n\n");
}

export default function ReportViewer({ report, sessionId }: { report: FinalReport | null; sessionId: string | null }) {
  if (!report || !sessionId) return <p className="p-6 text-sm text-slate-400">The cited report will render here when the run completes.</p>;
  const btn = "rounded-lg px-3 py-1.5 text-sm font-medium ring-1 ring-slate-300 hover:bg-slate-50";
  return (
    <div className="p-5">
      <div className="mb-4 flex flex-wrap gap-2">
        <a className={`${btn} bg-indigo-600 text-white ring-indigo-600 hover:bg-indigo-700`} href={api.downloadUrl(sessionId, "pdf")} download>⬇ Download PDF</a>
        <a className={btn} href={api.downloadUrl(sessionId, "md")} download>⬇ Markdown</a>
        <a className={btn} href={api.downloadUrl(sessionId, "html")} download>⬇ HTML</a>
      </div>
      <article className="report-prose max-w-none text-[15px]">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{ a: ({ href, children }) => <a href={href} target="_blank" rel="noopener noreferrer">{children}</a> }}
        >
          {toMarkdown(report)}
        </ReactMarkdown>
      </article>
    </div>
  );
}
