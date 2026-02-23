"""Health check models and functions for MAF Server."""

from datetime import UTC, datetime

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Response model for GET /api/health."""

    status: str = "healthy"
    version: str = "0.1.0"
    timestamp: str


class ReadinessResponse(BaseModel):
    """Response model for GET /api/health/ready."""

    status: str  # "ready" or "draining"
    database_ok: bool
    active_runs: int


def check_health() -> HealthResponse:
    """Return basic health status — always succeeds if the process is up."""
    return HealthResponse(
        status="healthy",
        version="0.1.0",
        timestamp=datetime.now(UTC).isoformat(),
    )


def check_readiness(
    execution_service: object | None = None,
    readiness_gate: bool = True,
) -> ReadinessResponse:
    """Check whether the server is ready to accept new work.

    Args:
        execution_service: WorkflowExecutionService instance (for active run count).
        readiness_gate: False when the server is draining (SIGTERM received).

    Returns:
        ReadinessResponse with current readiness state.
    """
    active_runs = 0
    if execution_service is not None and hasattr(execution_service, "_executions"):
        active_runs = sum(
            1
            for m in execution_service._executions.values()
            if m.status.value in ("pending", "running")
        )

    db_ok = True
    try:
        from sqlalchemy import text

        from temper_ai.storage.database import get_session

        with get_session() as session:
            session.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 — best-effort DB check
        db_ok = False

    status = "ready" if readiness_gate and db_ok else "draining"
    return ReadinessResponse(
        status=status,
        database_ok=db_ok,
        active_runs=active_runs,
    )
