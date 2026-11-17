"""Report artefact writer: one call renders .md, .html and .pdf into a directory."""
from __future__ import annotations

from pathlib import Path
from typing import Any


def export_all(report: dict[str, Any], out_dir: str | Path, basename: str = "report") -> dict[str, str]:
    from app.exporters.html_exporter import render_html
    from app.exporters.markdown_exporter import render_markdown
    from app.exporters.pdf_exporter import render_pdf

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = {"md": out / f"{basename}.md", "html": out / f"{basename}.html", "pdf": out / f"{basename}.pdf"}
    paths["md"].write_text(render_markdown(report), encoding="utf-8")
    paths["html"].write_text(render_html(report), encoding="utf-8")
    paths["pdf"].write_bytes(render_pdf(report))
    return {k: str(v) for k, v in paths.items()}
