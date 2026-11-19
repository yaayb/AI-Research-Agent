"""FastAPI entrypoint: CORS, lifespan initialisation, router wiring.

Design decision: all long-lived resources (SQLAlchemy engine, AsyncSqliteSaver connection, compiled
graph, Chroma store) are created once in the lifespan and shared through ``app.state.ctx``.
"""
from __future__ import annotations

import hmac
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.agent.graph import build_graph
from app.api import routes_memory, routes_reports, routes_research
from app.config import Settings, get_settings
from app.database import db
from app.memory.checkpointer import open_checkpointer
from app.memory.semantic_store import SemanticMemory, get_semantic_store

logging.basicConfig(level=logging.INFO)


@dataclass
class AppContext:
    settings: Settings
    graph: Any
    store: SemanticMemory
    channels: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, dict] = field(default_factory=dict)
    tasks: set = field(default_factory=set)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.reports_path.mkdir(parents=True, exist_ok=True)
    await db.init(settings.db_path)
    store = get_semantic_store(settings)
    async with open_checkpointer(settings) as saver:
        try:
            graph = build_graph(saver, settings=settings, store_factory=lambda: store)
        except Exception:  # noqa: BLE001 - e.g. missing API key: API still boots, /start reports the problem
            logging.exception("graph construction failed")
            raise
        app.state.ctx = AppContext(settings=settings, graph=graph, store=store)
        yield
    await db.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title="DeepBrief AI", version="1.0.0", lifespan=lifespan)
    s = get_settings()
    app.add_middleware(CORSMiddleware, allow_origins=s.cors_origins, allow_methods=["*"], allow_headers=["*"],
                       expose_headers=["Content-Disposition"])
    app.include_router(routes_research.router)
    app.include_router(routes_reports.router)
    app.include_router(routes_memory.router)

    if s.access_key:
        @app.middleware("http")
        async def require_access_key(request: Request, call_next):
            p = request.url.path
            if p.startswith("/api/") and p != "/api/health" and request.method != "OPTIONS":
                supplied = request.headers.get("x-access-key") or request.query_params.get("key")
                if not supplied or not hmac.compare_digest(supplied, s.access_key):
                    return JSONResponse({"detail": "Invalid or missing access key"}, status_code=401)
            return await call_next(request)

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "llm": s.active_llm_model, "search": s.search_provider,
                "llm_configured": s.llm_configured, "auth_required": bool(s.access_key)}

    dist = Settings.resolve(s.frontend_dist)
    if (dist / "index.html").is_file():  # single-container deployment: API + built React app
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa(full_path: str) -> FileResponse:
            f = (dist / full_path).resolve()
            return FileResponse(f if f.is_file() and dist in f.parents else dist / "index.html")

    return app


app = create_app()
