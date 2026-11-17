import re

from app.exporters import export_all
from app.exporters.html_exporter import render_html
from app.exporters.markdown_exporter import render_markdown
from app.exporters.pdf_exporter import render_pdf, safe


def sample_report(n_sections: int = 8) -> dict:
    srcs = [{"url": f"https://site{i}.example.com/article-{i}", "title": f"Article {i} – “Quoted” café", "domain": f"site{i}.example.com",
             "published_date": "2026-01-0%d" % (i + 1)} for i in range(4)]
    para = " ".join(f"Claim {k} grows 12% [Article 0]({srcs[0]['url']})." for k in range(25))
    return {
        "title": "Research Brief: Café Agents → 2026", "topic": "Agents", "generated_at": "2026-03-01 10:00 UTC",
        "executive_summary": f"Summary with cite [Article 1]({srcs[1]['url']}). **Bold** text and `code`.",
        "confidence_rating": "High", "confidence_rationale": "Strong corroboration.", "research_scope": "Agents scope",
        "iterations": 2, "coverage_score": 0.9, "key_findings": [f"Finding [Article 2]({srcs[2]['url']})"],
        "sections": [{"heading": f"Section {i}", "body_markdown": f"### Sub\n\n{para}\n\n- bullet [A]({srcs[3]['url']})\n\n"
                      "| Metric | Value |\n|---|---|\n| Size | $4.2B |\n| Share | 38% |"} for i in range(n_sections)],
        "risks_limitations": ["Limited data | pipes"], "open_questions": ["What next?"], "sources": srcs,
        "comparison": {
            "corroborated_claims": [{"claim": "A | B", "source_urls": [srcs[0]["url"], srcs[1]["url"]], "confidence": 0.9}],
            "disputed_or_conflicting_claims": [{"claim": "Market size", "likely_explanation": "Scope", "positions": [
                {"url": srcs[0]["url"], "domain": srcs[0]["domain"], "stance_or_figure": "$4.2B", "published_date": "2026-01-01"},
                {"url": srcs[1]["url"], "domain": srcs[1]["domain"], "stance_or_figure": "$5.1B", "published_date": "2026-02-01"}]}],
            "source_quality_table": [{"url": s["url"], "domain": s["domain"], "title": s["title"], "relevance_score": 0.8,
                                      "credibility_tier": "high", "key_takeaway": "Takeaway"} for s in srcs]},
    }


def test_pdf_is_valid_multipage_with_clickable_links():
    data = render_pdf(sample_report())
    assert data[:5] == b"%PDF-" and data.rstrip().endswith(b"%%EOF") and len(data) > 5000
    assert len(re.findall(rb"/Type\s*/Page(?!s)", data)) >= 3
    assert b"https://site0.example.com/article-0" in data and b"/URI" in data  # link annotations


def test_pdf_survives_exotic_unicode_and_empty_comparison():
    r = sample_report(1)
    r["comparison"] = {"corroborated_claims": [], "disputed_or_conflicting_claims": [], "source_quality_table": []}
    r["executive_summary"] = "日本語 emoji 🚀 — “quotes” … ≥ ≤"
    assert render_pdf(r)[:5] == b"%PDF-"
    assert safe("a–b “x” 🚀") == 'a-b "x" ?'


def test_markdown_and_html_contain_required_sections_and_citations():
    r = sample_report(2)
    md = render_markdown(r)
    for heading in ("Executive Summary", "Key Findings", "Cross-Source Comparison & Contradiction Matrix",
                    "Risks, Limitations & Open Questions", "Verified References & Bibliography"):
        assert f"## {heading}" in md
    assert "Sources analyzed:** 4" in md and "A \\| B" in md and "$5.1B" in md
    html = render_html(r)
    assert html.startswith("<!doctype html>") and "<table>" in html and 'target="_blank"' in html and "@media print" in html


def test_export_all_writes_three_files(tmp_path):
    paths = export_all(sample_report(2), tmp_path / "out")
    assert set(paths) == {"md", "html", "pdf"}
    assert all((tmp_path / "out" / f"report.{e}").stat().st_size > 300 for e in paths)
