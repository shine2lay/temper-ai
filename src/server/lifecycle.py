"""Graceful shutdown manager for MAF Server."""
import asyncio
import logging
import signal
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

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

    def _handle_signal_sync(self, signum: int, frame: Any) -> None:
        """Sync signal callback — flips readiness gate."""
        logger.info("Received signal %s, starting drain", signum)
        self.readiness_gate = False

    # ------------------------------------------------------------------
    # Drain
    # ------------------------------------------------------------------

    async def drain(
        self,
        execution_service: Optional[Any] = None,
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
