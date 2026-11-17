"""Long-term memory inspection endpoints (search with scores, list, stats, delete, add preference)."""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/memory", tags=["memory"])


class PreferenceIn(BaseModel):
    text: str = Field(min_length=3, description="e.g. 'Always include a pricing table and keep summaries under 120 words'")


def _store(request: Request):
    return request.app.state.ctx.store


@router.get("/search")
async def search(request: Request, q: str = Query(min_length=1), k: int = 8, kind: str | None = None) -> list[dict[str, Any]]:
    return await asyncio.to_thread(_store(request).search, q, k, kind, 0.0)


@router.get("/stats")
async def stats(request: Request) -> dict[str, Any]:
    return await asyncio.to_thread(_store(request).stats)


@router.get("/items")
async def items(request: Request, limit: int = 50) -> list[dict[str, Any]]:
    return await asyncio.to_thread(_store(request).list_recent, limit)


@router.post("/preference")
async def add_preference(body: PreferenceIn, request: Request) -> dict[str, str]:
    item_id = await asyncio.to_thread(_store(request).upsert, body.text, "preference", "user preference")
    return {"id": item_id}


@router.delete("/{item_id}")
async def delete(item_id: str, request: Request) -> dict[str, bool]:
    if not await asyncio.to_thread(_store(request).delete, item_id):
        raise HTTPException(404, "Memory item not found")
    return {"deleted": True}
