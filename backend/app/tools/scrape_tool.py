"""``read_webpage`` tool: async httpx fetch + Trafilatura boilerplate-free Markdown extraction.

Design decisions
- Never raises into the graph: 403/429/5xx, PDFs, non-HTML, timeouts and parse failures all return
  a ``status="failed"`` artifact with a human-readable reason the LLM can react to.
- Extraction is CPU-bound -> ``asyncio.to_thread``.
- ``smart_truncate`` keeps the lead plus headings and number-bearing paragraphs (statistics) when
  a page exceeds the per-page budget.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any

import httpx
import trafilatura
from langchain_core.tools import tool

from app.config import get_settings
from app.tools.fixtures import offline_page
from app.tools.search_tool import domain_of, normalize_url

log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0 Safari/537.36 DeepBriefBot/1.0",
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
_STAT = re.compile(r"\d")


def smart_truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    paras = [p for p in re.split(r"\n{2,}", text) if p.strip()]
    keep: set[int] = set()
    used = 0
    # 1) lead (up to 55% of budget), 2) headings, 3) statistic-bearing paragraphs, 4) the rest
    order = (
        [i for i, _ in enumerate(paras)][: max(1, len(paras) // 4)]
        + [i for i, p in enumerate(paras) if p.lstrip().startswith("#")]
        + [i for i, p in enumerate(paras) if _STAT.search(p)]
        + list(range(len(paras)))
    )
    for i in order:
        if i in keep:
            continue
        cost = len(paras[i]) + 2
        if used + cost > limit - 40:
            if used > limit * 0.55:
                continue
            paras[i] = paras[i][: max(0, limit - 40 - used)]
            cost = len(paras[i]) + 2
        keep.add(i)
        used += cost
        if used >= limit - 40:
            break
    return "\n\n".join(paras[i] for i in sorted(keep)) + "\n\n[...truncated]"


def _failed(url: str, reason: str) -> dict[str, Any]:
    return {"url": url, "domain": domain_of(url), "title": "", "author": None, "published_date": None,
            "snippet": "", "content": "", "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "status": "failed", "error": reason}


def _extract(html: str, url: str, limit: int) -> dict[str, Any] | None:
    text = trafilatura.extract(html, url=url, include_links=True, include_tables=True, output_format="markdown")
    if not text:
        return None
    meta = trafilatura.extract_metadata(html, default_url=url)
    return {
        "title": (meta.title if meta and meta.title else "") or "",
        "author": meta.author if meta else None,
        "published_date": meta.date if meta else None,
        "content": smart_truncate(text, limit),
    }


async def fetch_page(url: str) -> dict[str, Any]:
    s = get_settings()
    url = normalize_url(url)
    if not url.startswith(("http://", "https://")):
        return _failed(url, "Invalid URL (must start with http/https)")
    if s.offline_test_mode:
        page = offline_page(url)
        if page is None:
            return _failed(url, "Offline fixture: page not found")
        page["content"] = smart_truncate(page["content"], s.max_page_chars)
        meta = page
    else:
        if url.lower().split("?")[0].endswith(".pdf"):
            return _failed(url, "PDF documents are not supported by read_webpage; rely on the search snippet")
        try:
            async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=s.http_timeout_s) as client:
                resp = await client.get(url)
        except httpx.TimeoutException:
            return _failed(url, f"Timed out after {s.http_timeout_s:.0f}s")
        except httpx.HTTPError as exc:
            return _failed(url, f"Network error: {type(exc).__name__}")
        if resp.status_code in (403, 429) or resp.status_code >= 400:
            return _failed(url, f"HTTP {resp.status_code} (blocked or unavailable)")
        ctype = resp.headers.get("content-type", "").lower()
        if "pdf" in ctype or ("html" not in ctype and "xml" not in ctype and "text" not in ctype):
            return _failed(url, f"Unsupported content type: {ctype or 'unknown'}")
        try:
            meta = await asyncio.to_thread(_extract, resp.text, url, s.max_page_chars)
        except Exception as exc:  # noqa: BLE001
            return _failed(url, f"Extraction error: {type(exc).__name__}")
        if not meta:
            return _failed(url, "No extractable article text (likely JS-rendered or boilerplate-only)")
    return {
        "url": url, "domain": domain_of(url), "title": meta.get("title") or domain_of(url),
        "author": meta.get("author"), "published_date": meta.get("published_date"),
        "snippet": meta["content"][:300].replace("\n", " "), "content": meta["content"],
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "status": "read",
    }


@tool(response_format="content_and_artifact")
async def read_webpage(url: str) -> tuple[str, dict[str, Any]]:
    """Fetch a web page and return its clean article text (Markdown) plus title/author/date metadata.

    Use after web_search to read the most promising URLs in full. Handles blocked pages gracefully.

    Args:
        url: Absolute http(s) URL returned by web_search.
    """
    page = await fetch_page(url)
    if page["status"] == "failed":
        return f"read_webpage FAILED for {url}: {page.get('error')}", page
    head = (f"read_webpage('{page['url']}') OK | title: {page['title']} | author: {page['author'] or 'n/a'} "
            f"| date: {page['published_date'] or 'n/a'} | domain: {page['domain']}\n\n")
    return head + page["content"][:5000], page
