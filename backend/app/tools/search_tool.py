"""``web_search`` tool: Tavily (primary) -> DDGS (keyless fallback), normalised + de-duplicated.

Design decisions
- Typed ``@tool`` with ``response_format="content_and_artifact"``: the model sees a compact text
  rendering, while the graph receives the structured result list as the ``ToolMessage.artifact``.
- URL de-duplication uses a ``ContextVar`` of already-collected URLs that the ``execute_tools``
  node sets, so tools stay pure/stateless yet skip URLs already in ``collected_sources``.
- Any provider failure degrades (Tavily -> DDGS -> empty result) instead of raising into the graph.
"""
from __future__ import annotations

import asyncio
import logging
from contextvars import ContextVar
from typing import Any, Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from langchain_core.tools import tool

from app.config import get_settings
from app.tools.fixtures import offline_search

log = logging.getLogger(__name__)

SEEN_URLS: ContextVar[frozenset[str]] = ContextVar("seen_urls", default=frozenset())
_TRACKING = ("utm_", "fbclid", "gclid", "mc_cid", "mc_eid", "ref_src", "igshid")


def normalize_url(url: str) -> str:
    """Strip tracking params + fragment, lower-case host, drop trailing slash."""
    parts = urlsplit(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not k.lower().startswith(_TRACKING)]
    path = parts.path.rstrip("/") if parts.path != "/" else ""
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), ""))


def domain_of(url: str) -> str:
    host = urlsplit(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _normalise(items: list[dict[str, Any]], seen: frozenset[str], limit: int) -> list[dict[str, Any]]:
    out, urls = [], set(seen)
    for it in items:
        raw = it.get("url") or it.get("href") or ""
        if not raw.startswith("http"):
            continue
        url = normalize_url(raw)
        if url in urls:
            continue
        urls.add(url)
        out.append({
            "title": (it.get("title") or domain_of(url)).strip(),
            "url": url,
            "snippet": (it.get("snippet") or it.get("content") or it.get("body") or "").strip()[:600],
            "domain": domain_of(url),
            "published_date": it.get("published_date") or it.get("date"),
        })
        if len(out) >= limit:
            break
    return out


async def _tavily(query: str, n: int, topic: str, key: str) -> list[dict[str, Any]]:
    from tavily import AsyncTavilyClient

    resp = await AsyncTavilyClient(api_key=key).search(query=query, max_results=n + 3, topic=topic)
    return [{"title": r.get("title"), "url": r.get("url"), "snippet": r.get("content"),
             "published_date": r.get("published_date")} for r in resp.get("results", [])]


def _ddgs_sync(query: str, n: int, topic: str) -> list[dict[str, Any]]:
    from ddgs import DDGS

    client = DDGS()
    if topic == "news":
        raw = client.news(query, max_results=n + 3)
        return [{"title": r.get("title"), "url": r.get("url"), "snippet": r.get("body"), "published_date": r.get("date")} for r in raw]
    raw = client.text(query, max_results=n + 3)
    return [{"title": r.get("title"), "url": r.get("href"), "snippet": r.get("body")} for r in raw]


async def run_search(query: str, max_results: int = 5, topic_filter: str = "general") -> tuple[list[dict[str, Any]], str]:
    """Returns (results, provider_used)."""
    s = get_settings()
    seen = SEEN_URLS.get()
    if s.offline_test_mode:
        return _normalise(offline_search(query, 10), seen, max_results), "offline"
    if s.tavily_api_key.strip():
        try:
            return _normalise(await _tavily(query, max_results, topic_filter, s.tavily_api_key), seen, max_results), "tavily"
        except Exception as exc:  # noqa: BLE001 - degrade to keyless search
            log.warning("Tavily failed (%s); falling back to ddgs", exc)
    try:
        raw = await asyncio.to_thread(_ddgs_sync, query, max_results, topic_filter)
        return _normalise(raw, seen, max_results), "ddgs"
    except Exception as exc:  # noqa: BLE001
        log.warning("ddgs failed: %s", exc)
        return [], "error"


@tool(response_format="content_and_artifact")
async def web_search(
    query: str, max_results: int = 5, topic_filter: Literal["general", "news"] = "general"
) -> tuple[str, list[dict[str, Any]]]:
    """Search the live web. Returns title, URL, snippet, domain and date for each new result.

    Args:
        query: A specific, self-contained search query.
        max_results: Number of results to return (1-10).
        topic_filter: "news" for recent events, otherwise "general".
    """
    max_results = max(1, min(int(max_results), 10))
    results, provider = await run_search(query, max_results, topic_filter)
    if not results:
        return f"No new results for '{query}' (provider={provider}). Try rephrasing the query.", []
    lines = [f"[{i}] {r['title']} | {r['url']} | {r['published_date'] or 'n/a'}\n    {r['snippet'][:300]}"
             for i, r in enumerate(results, 1)]
    return f"web_search('{query}') via {provider}:\n" + "\n".join(lines), results
