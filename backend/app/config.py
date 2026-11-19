"""Application settings (Pydantic Settings).

Design decisions
- One ``Settings`` object is the single source of truth for provider flags, paths and limits.
- Relative filesystem paths are resolved against ``backend/`` so the CLI, API and tests share the
  same ``./data`` directory no matter where the process is launched from.
- ``OFFLINE_TEST_MODE=true`` swaps in deterministic search/scrape fixtures and a scripted LLM so the
  whole graph runs with no network or API keys (used by the test-suite and for demos).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(ROOT_DIR / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    llm_provider: Literal["gemini", "openai"] = "gemini"
    gemini_api_key: str = ""
    openai_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    openai_model: str = "gpt-4o-mini"
    tavily_api_key: str = ""

    chroma_persist_dir: str = "./data/chroma"
    sqlite_db_path: str = "./data/research.db"
    checkpoint_db_path: str = "./data/checkpoints.db"
    reports_dir: str = "./data/reports"
    embedding_backend: Literal["default", "hash"] = "default"

    max_iterations: int = Field(default=3, ge=1, le=10)
    offline_test_mode: bool = False
    tool_timeout_s: float = 60.0
    http_timeout_s: float = 12.0
    max_page_chars: int = 12000
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    # production controls
    max_concurrent_runs: int = Field(default=3, ge=1, le=50)
    channel_ttl_s: int = 3600          # finished live-run buffers are evicted after this
    access_key: str = ""               # if set, /api/* requires header X-Access-Key (or ?key= for SSE/downloads)
    frontend_dist: str = "../frontend/dist"

    # ---- derived helpers -------------------------------------------------
    @staticmethod
    def resolve(path: str) -> Path:
        p = Path(path)
        return p if p.is_absolute() else (BACKEND_DIR / p).resolve()

    @property
    def chroma_dir(self) -> Path:
        return self.resolve(self.chroma_persist_dir)

    @property
    def db_path(self) -> Path:
        return self.resolve(self.sqlite_db_path)

    @property
    def checkpoint_path(self) -> Path:
        return self.resolve(self.checkpoint_db_path)

    @property
    def reports_path(self) -> Path:
        return self.resolve(self.reports_dir)

    @property
    def search_provider(self) -> str:
        if self.offline_test_mode:
            return "offline"
        return "tavily" if self.tavily_api_key.strip() else "ddgs"

    @property
    def active_llm_model(self) -> str:
        if self.offline_test_mode:
            return "offline-scripted"
        return self.gemini_model if self.llm_provider == "gemini" else self.openai_model

    @property
    def llm_configured(self) -> bool:
        if self.offline_test_mode:
            return True
        key = self.gemini_api_key if self.llm_provider == "gemini" else self.openai_api_key
        return bool(key.strip())

    def depth_to_iterations(self, depth: str) -> int:
        """Quick = max 2 loops, Deep = max 4 loops (spec); anything else uses MAX_ITERATIONS."""
        return {"quick": 2, "deep": 4}.get(depth, self.max_iterations)


@lru_cache
def get_settings() -> Settings:
    return Settings()
