"""Deterministic offline fixtures (``OFFLINE_TEST_MODE=true``).

Design decision: fixtures deliberately contain *corroborating* and *conflicting* figures from
different domains so the comparison/contradiction logic is exercised without a network.
"""
from __future__ import annotations

import hashlib
import re

_PAGES = {
    "https://analyst-reports.example.com/agent-frameworks-2026": {
        "title": "Agent Framework Landscape 2026", "author": "A. Analyst", "date": "2026-02-10",
        "body": "# Agent Framework Landscape 2026\n\nThe market for agent frameworks reached **$4.2 billion** in 2025. "
                "LangGraph is the most adopted stateful orchestration framework, used by 38% of surveyed teams.\n\n"
                "## Memory\n\nDual-tier memory (checkpoints plus vector stores) is the dominant production pattern.",
    },
    "https://tech-journal.example.org/open-source-agents": {
        "title": "Open-Source Agent Frameworks Compared", "author": "J. Writer", "date": "2026-03-01",
        "body": "# Open-Source Agent Frameworks Compared\n\nLangGraph, CrewAI and AutoGen lead open-source adoption. "
                "Analysts estimate the agent framework market at **$5.1 billion** for 2025. "
                "LangGraph is favoured for stateful, cyclic workflows with persistence.\n\n"
                "## Tooling\n\nStructured tool calling and observability are top selection criteria.",
    },
    "https://gov-stats.example.gov/ai-adoption": {
        "title": "National AI Adoption Statistics", "author": None, "date": "2026-01-15",
        "body": "# National AI Adoption Statistics\n\nAbout 38% of engineering teams use a stateful orchestration framework. "
                "Dual-tier memory architectures are reported by a majority of production deployments.",
    },
    "https://dev-blog.example.net/choosing-an-agent-framework": {
        "title": "How We Chose an Agent Framework", "author": "D. Engineer", "date": "2025-11-20",
        "body": "# How We Chose an Agent Framework\n\nWe picked LangGraph for persistence and human-in-the-loop approval. "
                "Observability and structured tool calling mattered most.",
    },
}


def _slug(query: str) -> str:
    return hashlib.sha1(query.lower().encode()).hexdigest()[:8]


def offline_search(query: str, max_results: int = 5) -> list[dict]:
    results = [
        {"title": p["title"], "url": u, "snippet": p["body"].split("\n\n")[1][:240], "published_date": p["date"]}
        for u, p in _PAGES.items()
    ]
    slug = _slug(query)
    results.append({
        "title": f"Research note: {re.sub(r'[^A-Za-z0-9 ]', '', query)[:60]}",
        "url": f"https://notes.example.edu/{slug}",
        "snippet": f"Background note addressing '{query}' with additional evidence.",
        "published_date": "2026-04-01",
    })
    return results[:max_results]


def offline_page(url: str) -> dict | None:
    if url in _PAGES:
        p = _PAGES[url]
        return {"title": p["title"], "author": p["author"], "published_date": p["date"], "content": p["body"]}
    if url.startswith("https://notes.example.edu/"):
        return {"title": "Research note", "author": None, "published_date": "2026-04-01",
                "content": "# Research note\n\nAdditional evidence: LangGraph adoption continues to grow and dual-tier memory is standard."}
    return None
