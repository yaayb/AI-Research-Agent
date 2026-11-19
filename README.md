# DeepBrief AI — Autonomous Research Agent

Give it a complex topic. It decomposes it into sub-questions, searches the live web, reads full pages,
cross-examines sources for consensus and contradictions, reflects on coverage (looping until it is
good enough), and writes a **cited** report in **Markdown, HTML and PDF**. Runs as a rich CLI or a
live-streaming React web studio.

## Architecture

```
START → recall_memory → plan_research → approve_plan → investigator_agent ⇄ execute_tools
                                                          │ (no tool calls)
                                              compare_sources → reflect_coverage
                                   coverage < 0.8 and iteration < max → investigator_agent
                                   else → synthesize_report → END
```

| Pillar | Implementation |
|---|---|
| Stateful graph orchestration | LangGraph `StateGraph`, `ToolNode`, conditional edges, `interrupt` for plan approval (`backend/app/agent/`) |
| Search & scraping | `web_search` (Tavily → keyless **ddgs** fallback, URL de-dup, `utm_*` stripping); `read_webpage` (httpx + Trafilatura Markdown, smart truncation to ~12k chars) |
| Structured tool calling | Typed `@tool`s bound with `bind_tools`; Pydantic v2 structured outputs; Gemini (`gemini-2.5-flash`) or OpenAI (`gpt-4o-mini`) via `LLM_PROVIDER` |
| Dual-tier memory | Short-term: SQLite LangGraph checkpointer per `thread_id`. Long-term: ChromaDB `PersistentClient` (facts, briefs, source summaries, preferences) |

Hallucination guardrails (enforced in prompts **and** code): claims need 2+ independent domains, every
URL must have been retrieved in the run, and links to unretrieved URLs are stripped from the report.

Deviation notes: an extra `approve_plan` node hosts the optional human-approval `interrupt` so the
planning LLM call is not re-run on resume; `ComparisonAnalysis` claims failing the 2-domain rule are dropped.

## Quickstart

```powershell
# 1. Backend
cd backend
python -m venv .venv ; .\.venv\Scripts\Activate.ps1      # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy ..\.env.example ..\.env                              # then set GEMINI_API_KEY (or OPENAI_API_KEY + LLM_PROVIDER=openai)
```

TAVILY_API_KEY is optional — without it the keyless `ddgs` search is used automatically.

### CLI
```powershell
python -m app.cli "Compare open-source AI agent frameworks in 2026" --depth deep --output ./reports
python -m app.cli "topic" --approve-plan        # pause to approve the research plan
python -m app.cli "topic" --chat                # follow-up Q&A afterwards
python -m app.cli "topic" --offline             # no network / no keys: deterministic demo
```
`--depth quick` = max 2 loops, `deep` = max 4 loops.

### Web studio
```powershell
# terminal 1 (from backend/)
uvicorn app.main:app --reload --port 8000
# terminal 2
cd frontend ; npm install ; npm run dev            # http://localhost:5173
```
Set `OFFLINE_TEST_MODE=true` in `.env` to try the whole UI without any API keys.

### API
| Endpoint | Purpose |
|---|---|
| `POST /api/research/start` | `{topic, depth, require_plan_approval}` → `session_id` |
| `GET /api/research/{id}/stream` | SSE telemetry (node transitions, tool calls, sources, reflection scores) |
| `POST /api/research/{id}/approve` | resume after plan approval |
| `GET /api/research/{id}/result` | report, comparison matrix, memories (from checkpoint) |
| `POST /api/research/{id}/followup` | Q&A grounded in the thread's checkpoint state |
| `GET /api/reports`, `GET /api/reports/{id}/download/{md\|html\|pdf}` | report library & downloads |
| `GET /api/memory/search?q=`, `GET /api/memory/stats`, `DELETE /api/memory/{id}` | ChromaDB inspection |

## Tests
```powershell
cd backend ; pytest -q          # offline; 4 suites + API smoke test
cd frontend ; npm run build     # TypeScript + Tailwind check
```
Suites: `test_search_and_scrape`, `test_memory_persistence`, `test_agent_graph`, `test_pdf_exporter`, plus `test_api`.

## Notes
- Data lives in `backend/data/` (Chroma, checkpoints, SQLite metadata, reports).
- The first non-offline memory use downloads Chroma's default ONNX embedding model (~80 MB).
- Page extraction can't read JS-rendered sites or PDFs; those degrade to search snippets.

## Deploying (Docker)
```bash
cp .env.example .env     # set GEMINI_API_KEY (or OPENAI_API_KEY), ACCESS_KEY, optional TAVILY_API_KEY; keep OFFLINE_TEST_MODE=false
docker compose up -d --build   # app + UI on http://localhost:8000, data in the deepbrief-data volume
```
- Put it behind HTTPS (Caddy/nginx/Cloudflare, disable proxy buffering for `/api/research/*/stream`).
- Set `ACCESS_KEY` on any public instance; `MAX_CONCURRENT_RUNS` caps spend (HTTP 429 when busy).
- Run one worker (live-run buffers are in-process); finished sessions stay readable from the checkpoint DB.
- Online mode needs an LLM key; search works keyless via ddgs (Tavily recommended for reliability at scale).
