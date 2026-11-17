import httpx
import pytest

from app.config import get_settings
from app.tools import scrape_tool
from app.tools.scrape_tool import fetch_page, read_webpage, smart_truncate
from app.tools.search_tool import SEEN_URLS, normalize_url, web_search

REAL_CLIENT = httpx.AsyncClient
ARTICLE = "<html><head><title>Quantum Widgets Report</title><meta name='author' content='Ada Writer'>" \
          "<meta property='article:published_time' content='2026-01-05'></head><body><nav>MENU HOME ABOUT</nav><article>" \
          "<h1>Quantum Widgets Report</h1>" + "".join(
              f"<p>Paragraph {i}: quantum widget shipments grew {i + 10}% year over year as manufacturers scaled production "
              f"capacity across several regions, according to industry surveys and filings.</p>" for i in range(12)) + \
          "</article><footer>Cookie banner subscribe now</footer></body></html>"


def test_normalize_url_strips_tracking_and_fragment():
    assert normalize_url("HTTPS://Example.com/a/?utm_source=x&id=7&fbclid=z#frag") == "https://example.com/a?id=7"


async def test_web_search_offline_normalises_and_dedupes():
    out = await web_search.ainvoke({"query": "agent frameworks", "max_results": 3})
    assert "web_search('agent frameworks')" in out
    res = await web_search.ainvoke({"type": "tool_call", "name": "web_search", "id": "1",
                                    "args": {"query": "agent frameworks", "max_results": 3}})
    arts = res.artifact
    assert len(arts) == 3 and all({"title", "url", "snippet", "domain", "published_date"} <= set(a) for a in arts)
    token = SEEN_URLS.set(frozenset(a["url"] for a in arts))
    try:
        res2 = await web_search.ainvoke({"type": "tool_call", "name": "web_search", "id": "2",
                                         "args": {"query": "agent frameworks", "max_results": 5}})
    finally:
        SEEN_URLS.reset(token)
    assert not {a["url"] for a in res2.artifact} & {a["url"] for a in arts}


async def test_read_webpage_offline_fixture():
    res = await read_webpage.ainvoke({"type": "tool_call", "name": "read_webpage", "id": "1",
                                      "args": {"url": "https://analyst-reports.example.com/agent-frameworks-2026"}})
    assert res.artifact["status"] == "read" and "$4.2 billion" in res.artifact["content"]
    assert res.artifact["domain"] == "analyst-reports.example.com"


def test_smart_truncate_keeps_headings_and_statistics():
    paras = ["# Title"] + [f"Filler paragraph number {i} " * 12 for i in range(60)]
    paras.insert(40, "Revenue reached 42% growth in 2025.")
    paras.insert(30, "## Key Section")
    text = "\n\n".join(paras)
    out = smart_truncate(text, 3000)
    assert len(out) <= 3100 and "## Key Section" in out and "42% growth" in out and out.endswith("[...truncated]")


@pytest.fixture
def live_mode(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "offline_test_mode", False)

    def install(handler):
        monkeypatch.setattr(scrape_tool.httpx, "AsyncClient",
                            lambda **kw: REAL_CLIENT(transport=httpx.MockTransport(handler), **kw))
    return install


async def test_fetch_page_extracts_clean_markdown_and_metadata(live_mode):
    live_mode(lambda req: httpx.Response(200, text=ARTICLE, headers={"content-type": "text/html"}))
    page = await fetch_page("https://news.example.com/qw?utm_source=tw")
    assert page["status"] == "read" and page["url"] == "https://news.example.com/qw"
    assert "quantum widget shipments" in page["content"] and "MENU HOME" not in page["content"]
    assert page["domain"] == "news.example.com" and page["published_date"] == "2026-01-05"


@pytest.mark.parametrize("status", [403, 429, 500])
async def test_fetch_page_http_errors_do_not_raise(live_mode, status):
    live_mode(lambda req: httpx.Response(status))
    page = await fetch_page("https://blocked.example.com/x")
    assert page["status"] == "failed" and str(status) in page["error"]


async def test_fetch_page_pdf_and_timeout(live_mode):
    live_mode(lambda req: httpx.Response(200, content=b"%PDF-1.4", headers={"content-type": "application/pdf"}))
    assert (await fetch_page("https://x.example.com/doc"))["status"] == "failed"
    assert "PDF" in (await fetch_page("https://x.example.com/file.pdf"))["error"]

    def boom(req):
        raise httpx.ReadTimeout("slow")
    live_mode(boom)
    assert "Timed out" in (await fetch_page("https://slow.example.com/"))["error"]
