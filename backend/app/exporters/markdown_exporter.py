"""Markdown exporter: banner, executive summary, findings, comparison matrix, risks, bibliography.

Design decision: the Markdown is the canonical rendering; the HTML exporter converts this exact
text, and the PDF exporter renders the same ``FinalReport`` structure, so formats never diverge.
"""
from __future__ import annotations

from typing import Any


def cell(text: Any, limit: int = 220) -> str:
    s = " ".join(str(text if text is not None else "").split()).replace("|", "\\|")
    return s if len(s) <= limit else s[: limit - 1] + "…"


def link(title: str, url: str) -> str:
    return f"[{cell(title, 80)}]({url})"


def render_markdown(r: dict[str, Any]) -> str:
    sources = r.get("sources", [])
    comp = r.get("comparison", {}) or {}
    by_url = {s["url"]: s for s in sources}
    L: list[str] = [f"# {r['title']}", ""]
    L += [f"> **Topic:** {r.get('topic', '')}  ", f"> **Generated:** {r.get('generated_at', '')}  ",
          f"> **Sources analyzed:** {len(sources)}  ", f"> **Confidence:** {r.get('confidence_rating', 'n/a')}  ",
          f"> **Research loops:** {r.get('iterations', 0)} | **Coverage:** {r.get('coverage_score', 0):.0%}", ""]
    L += ["## Executive Summary", "", r["executive_summary"], ""]
    L += [f"**Scope:** {r.get('research_scope') or r.get('topic', '')}", ""]
    if r.get("confidence_rationale"):
        L += [f"**Confidence rating — {r['confidence_rating']}:** {r['confidence_rationale']}", ""]
    L += ["## Key Findings", ""] + [f"- {f}" for f in r.get("key_findings", [])] + [""]
    for sec in r.get("sections", []):
        L += [f"## {sec['heading']}", "", sec["body_markdown"].strip(), ""]

    L += ["## Cross-Source Comparison & Contradiction Matrix", ""]
    corro = comp.get("corroborated_claims", [])
    L += ["### Corroborated Claims", ""]
    if corro:
        L += ["| Claim | Supporting sources | Confidence |", "|---|---|---|"]
        for c in corro:
            srcs = ", ".join(link(by_url.get(u, {}).get("domain", u), u) for u in c["source_urls"])
            L.append(f"| {cell(c['claim'])} | {srcs} | {c.get('confidence', 0):.0%} |")
    else:
        L.append("_No claims were corroborated by two or more independent domains._")
    L += ["", "### Disputed or Conflicting Claims", ""]
    disp = comp.get("disputed_or_conflicting_claims", [])
    if disp:
        L += ["| Claim | Source | Figure / stance | Published | Likely explanation |", "|---|---|---|---|---|"]
        for d in disp:
            for i, p in enumerate(d["positions"]):
                L.append(f"| {cell(d['claim']) if i == 0 else ''} | {link(p['domain'], p['url'])} | {cell(p['stance_or_figure'])} "
                         f"| {cell(p.get('published_date') or 'n/a')} | {cell(d.get('likely_explanation', '')) if i == 0 else ''} |")
    else:
        L.append("_No material contradictions detected between sources._")
    L += ["", "### Source Quality", ""]
    sq = comp.get("source_quality_table", [])
    if sq:
        L += ["| Source | Domain | Relevance | Credibility | Key takeaway |", "|---|---|---|---|---|"]
        for q in sq:
            L.append(f"| {link(q['title'] or q['domain'], q['url'])} | {cell(q['domain'])} | {q['relevance_score']:.2f} "
                     f"| {q['credibility_tier']} | {cell(q['key_takeaway'], 160)} |")
    L.append("")
    L += ["## Risks, Limitations & Open Questions", "", "### Risks & Limitations", ""]
    L += [f"- {x}" for x in r.get("risks_limitations", [])] or ["- None identified."]
    L += ["", "### Open Questions", ""] + ([f"- {x}" for x in r.get("open_questions", [])] or ["- None identified."]) + [""]
    L += ["## Verified References & Bibliography", ""]
    for i, s in enumerate(sources, 1):
        date = f", {s['published_date']}" if s.get("published_date") else ""
        L.append(f"{i}. [{cell(s.get('title') or s['domain'], 120)}]({s['url']}) — {s['domain']}{date}")
    return "\n".join(L).rstrip() + "\n"
