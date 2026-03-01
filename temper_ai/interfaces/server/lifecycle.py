"""Graceful shutdown manager for MAF Server."""

import asyncio
import logging
import signal
import time
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_TENANT_ID = "default"


def ensure_default_tenant() -> str:
    """Create default tenant if it doesn't exist. Returns tenant_id."""
    from temper_ai.storage.database.manager import get_session
    from temper_ai.storage.database.models_tenancy import Tenant

    with get_session() as session:
        from sqlmodel import select

        existing = session.exec(
            select(Tenant).where(Tenant.id == DEFAULT_TENANT_ID)
        ).first()
        if existing is None:
            tenant = Tenant(
                id=DEFAULT_TENANT_ID,
                name="Default Workspace",
                slug="default",
                is_active=True,
                plan="self-hosted",
                max_workflows=10000,
            )
            session.add(tenant)
            session.commit()
            logger.info("Created default tenant")
    return DEFAULT_TENANT_ID


def mark_orphaned_workflows(backend: Any) -> int:
    """Mark all 'running' workflows as stuck on startup (threshold=0). Returns count."""
    stuck = backend.find_stuck_workflows(threshold_seconds=0)
    # Update each via track_workflow_end to mark as stuck
    from temper_ai.storage.database.datetime_utils import utcnow

    now = utcnow()
    for wf in stuck:
        try:
            backend.track_workflow_end(
                wf["id"],
                end_time=now,
                status="failed",
                error_message="Orphaned by server restart",
            )
        except Exception:  # noqa: BLE001
            logger.warning("Failed to mark orphaned workflow %s", wf.get("id"))
    return len(stuck)


async def run_stuck_detector(
    backend: Any,
    execution_service: Any,
    interval_seconds: int = 300,
    threshold_seconds: int = 1800,
) -> None:
    """Periodic task: finds workflows stuck for >threshold.

    Skips workflows that are actively tracked in execution_service._executions.
    """
    from temper_ai.storage.database.datetime_utils import utcnow

    while True:
        await asyncio.sleep(interval_seconds)
        try:
            stuck = backend.find_stuck_workflows(threshold_seconds)
            now = utcnow()
            for wf in stuck:
                wf_id = wf.get("id", "")
                # Skip workflows actively tracked in-memory
                if any(
                    m.workflow_id == wf_id
                    for m in execution_service._executions.values()
                ):
                    continue
                try:
                    backend.track_workflow_end(
                        wf_id,
                        end_time=now,
                        status="failed",
                        error_message=f"No progress for {threshold_seconds}s",
                    )
                except Exception:  # noqa: BLE001
                    logger.warning("Failed to mark stuck workflow %s", wf_id)
        except Exception:
            logger.exception("Stuck run detector error")


# Default drain timeout before forceful shutdown
DEFAULT_DRAIN_TIMEOUT_SECONDS = 30


class GracefulShutdownManager:
    """Manages server lifecycle: readiness gate, signal handling, and drain.

    Usage with FastAPI lifespan::

        shutdown_mgr = GracefulShutdownManager()

        @asynccontextmanager
        async def lifespan(app):
            shutdown_mgr.register_signals()
            yield
            await shutdown_mgr.drain(execution_service)

        app = FastAPI(lifespan=lifespan)
    """

    def __init__(self) -> None:
        self.readiness_gate: bool = True
        self._original_sigterm: Any = None
        self._original_sigint: Any = None

    # ------------------------------------------------------------------
    # Signal registration
    # ------------------------------------------------------------------

    def register_signals(self) -> None:
        """Install SIGTERM and SIGINT handlers that flip the readiness gate."""
        try:
            loop = asyncio.get_running_loop()
            loop.add_signal_handler(signal.SIGTERM, self._handle_signal)
            loop.add_signal_handler(signal.SIGINT, self._handle_signal)
            logger.info("Registered graceful shutdown signal handlers")
        except (NotImplementedError, RuntimeError):
            # Fallback for platforms without loop.add_signal_handler (e.g. Windows)
            self._original_sigterm = signal.getsignal(signal.SIGTERM)
            self._original_sigint = signal.getsignal(signal.SIGINT)
            signal.signal(signal.SIGTERM, self._handle_signal_sync)
            signal.signal(signal.SIGINT, self._handle_signal_sync)
            logger.info("Registered graceful shutdown signal handlers (sync fallback)")

    def _handle_signal(self) -> None:
        """Async-safe signal callback — flips readiness gate."""
        logger.info("Received shutdown signal, starting drain")
        self.readiness_gate = False

    def _handle_signal_sync(self, signum: int, _frame: Any) -> None:
        """Sync signal callback — flips readiness gate."""
        logger.info("Received signal %s, starting drain", signum)
        self.readiness_gate = False

    # ------------------------------------------------------------------
    # Drain
    # ------------------------------------------------------------------

    async def drain(
        self,
        execution_service: Any | None = None,
        timeout: int = DEFAULT_DRAIN_TIMEOUT_SECONDS,
    ) -> None:
        """Wait for active workflows to finish, then return.

        Args:
            execution_service: WorkflowExecutionService with _executions dict.
            timeout: Maximum seconds to wait before giving up.
        """
        if execution_service is None:
            return

        logger.info("Draining active workflows (timeout=%ds)", timeout)
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            active = sum(
                1
                for m in execution_service._executions.values()
                if m.status.value in ("pending", "running")
            )
            if active == 0:
                logger.info("All workflows drained")
                return
            logger.info("Waiting for %d active workflow(s)…", active)
            await asyncio.sleep(1)  # Intentional polling: wait for workflow drain

        logger.warning("Drain timeout reached, shutting down with active workflows")
