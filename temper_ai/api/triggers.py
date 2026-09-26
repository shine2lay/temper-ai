"""Read-only view of trigger rules and what they decided.

    GET /api/triggers            every rule, with the next due time of schedules
    GET /api/triggers/fires      recent decisions (started / skipped / failed)
    POST /api/triggers/tick      run one scheduler pass now (testing, catching up)
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from temper_ai.triggers import scheduler

router = APIRouter(prefix="/api/triggers", tags=["triggers"])


@router.get("")
def list_triggers() -> dict[str, Any]:
    return {"triggers": scheduler.describe()}


@router.get("/fires")
def list_fires(trigger: str | None = None, limit: int = 50) -> dict[str, Any]:
    return {"fires": scheduler.history(trigger, max(1, min(limit, 500)))}


@router.post("/tick")
def tick() -> dict[str, Any]:
    return {"decisions": scheduler.Scheduler().tick()}
