"""Pure-Python multi-page PDF exporter (fpdf2 -- no OS-level C libraries, works on Win/macOS/Linux).

Design decisions
- Renders from the canonical Markdown (same text as the .md/.html) via a tiny block parser:
  headings, bullets, numbered lists, block quotes, pipe tables and paragraphs with inline
  ``[text](url)`` links that become *clickable PDF link annotations*.
- Core Helvetica is Latin-1 only, so text is transliterated (smart quotes, dashes, arrows...) and
  anything else is replaced -- the document can never crash on exotic Unicode.
- Title banner on page 1, coloured section headers, "Page X/Y" footer on every page.
"""
from __future__ import annotations

import re
from typing import Any

from fpdf import FPDF
from fpdf.enums import XPos, YPos
from fpdf.fonts import FontFace

from app.exporters.markdown_exporter import render_markdown

ACCENT = (59, 76, 202)
INK = (27, 36, 48)
MUTED = (91, 102, 117)
LINK_RGB = (30, 64, 200)
_MAP = {"\u2013": "-", "\u2014": "-", "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u2022": "*",
        "\u2026": "...", "\u2192": "->", "\u2190": "<-", "\u2265": ">=", "\u2264": "<=", "\u2248": "~", "\u00a0": " ",
        "\u2212": "-", "\u2713": "v", "\u2717": "x", "\u200b": ""}
_INLINE = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)|\*\*(.+?)\*\*|`([^`]+)`")
_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")


def safe(text: str) -> str:
    for k, v in _MAP.items():
        text = text.replace(k, v)
    return text.encode("latin-1", "replace").decode("latin-1")


def _plain(text: str) -> str:
    text = _LINK.sub(lambda m: m.group(1), text)
    return safe(re.sub(r"[*`]|\\\|", lambda m: "|" if m.group(0).endswith("|") else "", text)).strip()


class ReportPDF(FPDF):
    def __init__(self, title: str) -> None:
        super().__init__(format="A4", unit="mm")
        self.report_title = safe(title)
        self.set_margins(18, 18, 18)
        self.set_auto_page_break(True, margin=20)
        self.set_title(self.report_title)
        self.set_creator("DeepBrief AI")
        self.alias_nb_pages()

    def header(self) -> None:
        if self.page_no() > 1:
            self.set_font("Helvetica", "I", 8)
            self.set_text_color(*MUTED)
            self.cell(0, 6, self.report_title[:95], new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            self.set_draw_color(220, 224, 232)
            self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
            self.ln(4)

    def footer(self) -> None:
        self.set_y(-14)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*MUTED)
        self.cell(0, 8, f"DeepBrief AI  |  Page {self.page_no()}/{{nb}}", align="C")

    # ---- building blocks -------------------------------------------------
    def banner(self, title: str, meta: list[str]) -> None:
        self.set_fill_color(*ACCENT)
        self.rect(0, 0, self.w, 58, style="F")
        self.set_xy(self.l_margin, 14)
        self.set_text_color(255, 255, 255)
        self.set_font("Helvetica", "B", 21)
        self.multi_cell(self.epw, 9, safe(title), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_font("Helvetica", "", 9.5)
        self.set_x(self.l_margin)
        self.multi_cell(self.epw, 5.5, safe("   |   ".join(meta)), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_y(max(self.get_y(), 58) + 8)
        self.set_text_color(*INK)

    def section(self, text: str) -> None:
        if self.get_y() > self.h - 55:
            self.add_page()
        self.ln(4)
        self.set_font("Helvetica", "B", 14)
        self.set_text_color(*ACCENT)
        self.set_x(self.l_margin)
        self.multi_cell(self.epw, 7, safe(text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_draw_color(*ACCENT)
        self.set_line_width(0.5)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.set_line_width(0.2)
        self.ln(3)
        self.set_text_color(*INK)

    def subheading(self, text: str) -> None:
        self.ln(2)
        self.set_font("Helvetica", "B", 11)
        self.set_text_color(42, 53, 80)
        self.set_x(self.l_margin)
        self.multi_cell(self.epw, 6, _plain(text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_text_color(*INK)

    def inline(self, text: str, size: float = 10, indent: float = 0, italic: bool = False) -> None:
        self.set_x(self.l_margin + indent)
        pos = 0
        h = size * 0.5
        base = "I" if italic else ""

        def plain(chunk: str, style: str = "") -> None:
            if chunk:
                self.set_font("Helvetica", base + style, size)
                self.set_text_color(*INK)
                self.write(h, safe(chunk))

        for m in _INLINE.finditer(text):
            plain(text[pos:m.start()])
            if m.group(1):
                self.set_font("Helvetica", base + "U", size)
                self.set_text_color(*LINK_RGB)
                self.write(h, safe(m.group(1)), link=m.group(2))
            elif m.group(3):
                plain(m.group(3), "B")
            else:
                self.set_font("Courier", "", size - 0.5)
                self.write(h, safe(m.group(4)))
            pos = m.end()
        plain(text[pos:])
        self.ln(h + 1.6)
        self.set_text_color(*INK)
        self.set_x(self.l_margin)

    def md_table(self, rows: list[list[str]]) -> None:
        ncol = max(len(r) for r in rows)
        rows = [r + [""] * (ncol - len(r)) for r in rows]
        weights = [min(max(sum(len(_plain(r[c])) for r in rows) / len(rows), 8), 55) for c in range(ncol)]
        self.ln(1)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*INK)
        head = FontFace(emphasis="BOLD", color=(255, 255, 255), fill_color=ACCENT)
        with self.table(col_widths=tuple(weights), width=self.epw, line_height=4.4, headings_style=head,
                        text_align="LEFT", padding=1.3, borders_layout="ALL") as table:
            for r in rows:
                row = table.row()
                for cell in r:
                    m = _LINK.search(cell)
                    row.cell(_plain(cell), link=m.group(2) if m else None)
        self.ln(3)
        self.set_x(self.l_margin)


def _split_row(line: str) -> list[str]:
    inner = line.strip().strip("|")
    return [c.strip() for c in re.split(r"(?<!\\)\|", inner)]


def render_blocks(pdf: ReportPDF, md_text: str) -> None:
    lines = md_text.splitlines()
    i, para = 0, []

    def flush() -> None:
        if para:
            pdf.inline(" ".join(para))
            para.clear()

    while i < len(lines):
        ln = lines[i].rstrip()
        s = ln.strip()
        if not s:
            flush()
        elif s.startswith("|"):
            flush()
            tbl = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                if not re.fullmatch(r"\|?[\s:\-|]+\|?", lines[i].strip()):
                    tbl.append(_split_row(lines[i]))
                i += 1
            if tbl:
                pdf.md_table(tbl)
            continue
        elif s.startswith("## "):
            flush(); pdf.section(s[3:])
        elif s.startswith("#"):
            flush(); pdf.subheading(s.lstrip("#").strip())
        elif re.match(r"^[-*] ", s):
            flush(); pdf.inline("* " + s[2:], indent=3)
        elif re.match(r"^\d+\. ", s):
            flush(); pdf.inline(s, indent=3)
        elif s.startswith(">"):
            flush(); pdf.inline(s.lstrip("> ").strip(), italic=True)
        else:
            para.append(s)
        i += 1
    flush()


def render_pdf(report: dict[str, Any]) -> bytes:
    md_text = render_markdown(report)
    # drop H1 + the metadata blockquote: they are rendered as the title banner instead
    body = md_text.split("\n## ", 1)
    body_md = "## " + body[1] if len(body) > 1 else md_text
    pdf = ReportPDF(report["title"])
    pdf.add_page()
    meta = [f"Topic: {report.get('topic', '')[:60]}", f"Date: {report.get('generated_at', '')[:10]}",
            f"Sources: {len(report.get('sources', []))}", f"Confidence: {report.get('confidence_rating', 'n/a')}"]
    pdf.banner(report["title"], meta)
    render_blocks(pdf, body_md)
    return bytes(pdf.output())
