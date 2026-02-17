"""Background analysis job for server mode."""

import asyncio
import logging

from src.goals.analysis_orchestrator import AnalysisOrchestrator
from src.goals.constants import ANALYSIS_INTERVAL_HOURS, SECONDS_PER_HOUR

logger = logging.getLogger(__name__)


class BackgroundAnalysisJob:
    """Periodic goal analysis job that runs in server mode."""

    def __init__(
        self,
        orchestrator: AnalysisOrchestrator,
        interval_hours: int = ANALYSIS_INTERVAL_HOURS,
    ) -> None:
        self.orchestrator = orchestrator
        self.interval_seconds = interval_hours * SECONDS_PER_HOUR
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        """Start the background analysis loop."""
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            "Background analysis job started (interval=%dh)",
            self.interval_seconds // SECONDS_PER_HOUR,
        )

    async def stop(self) -> None:
        """Stop the background analysis loop."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Background analysis job stopped")

    async def _run_loop(self) -> None:
        """Run analysis at regular intervals."""
        while self._running:
            try:
                await asyncio.sleep(self.interval_seconds)  # intentional: periodic analysis interval
                run = await asyncio.get_running_loop().run_in_executor(
                    None, self.orchestrator.run_analysis
                )
                logger.info(
                    "Background analysis: %d proposals generated (status=%s)",
                    run.proposals_generated,
                    run.status,
                )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("Background analysis error: %s", exc)
