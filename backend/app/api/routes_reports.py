"""Report listing and downloads (md / html / pdf)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.database import get_report, list_reports

router = APIRouter(prefix="/api/reports", tags=["reports"])
MEDIA = {"md": "text/markdown", "html": "text/html", "pdf": "application/pdf"}


def _dto(r) -> dict[str, Any]:
    return {"id": r.id, "session_id": r.session_id, "title": r.title, "topic": r.topic, "confidence": r.confidence,
            "summary": r.summary, "source_count": r.source_count, "created_at": r.created_at.isoformat(),
            "formats": [f for f, p in (("md", r.md_path), ("html", r.html_path), ("pdf", r.pdf_path)) if p]}


@router.get("")
async def reports() -> list[dict[str, Any]]:
    return [_dto(r) for r in await list_reports()]


@router.get("/{report_id}/download/{fmt}")
async def download(report_id: str, fmt: str) -> FileResponse:
    if fmt not in MEDIA:
        raise HTTPException(400, "Format must be one of: md, html, pdf")
    r = await get_report(report_id)
    if r is None:
        raise HTTPException(404, "Report not found")
    path = Path({"md": r.md_path, "html": r.html_path, "pdf": r.pdf_path}[fmt])
    if not path.is_file():
        raise HTTPException(404, "Report file missing on disk")
    return FileResponse(path, media_type=MEDIA[fmt], filename=f"{r.session_id}.{fmt}")
