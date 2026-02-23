"""Background mining job for server mode."""

import asyncio
import logging

from temper_ai.learning.convergence import ConvergenceDetector
from temper_ai.learning.orchestrator import MiningOrchestrator

logger = logging.getLogger(__name__)

MINING_INTERVAL_HOURS = 6
SECONDS_PER_HOUR = 3600


class BackgroundMiningJob:
    """Periodic mining job that runs in server mode."""

    def __init__(
        self,
        orchestrator: MiningOrchestrator,
        convergence: ConvergenceDetector,
        interval_hours: int = MINING_INTERVAL_HOURS,
    ) -> None:
        self.orchestrator = orchestrator
        self.convergence = convergence
        self.interval_seconds = interval_hours * SECONDS_PER_HOUR
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        """Start the background mining loop."""
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            "Background mining job started (interval=%dh)",
            self.interval_seconds // SECONDS_PER_HOUR,
        )

    async def stop(self) -> None:
        """Stop the background mining loop."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Background mining job stopped")

    async def _run_loop(self) -> None:
        """Run mining at regular intervals unless converged."""
        while self._running:
            try:
                await asyncio.sleep(
                    self.interval_seconds
                )  # intentional: periodic mining interval
                if self.convergence.is_converged():
                    logger.info("Mining converged — skipping this cycle")
                    continue
                run = await asyncio.get_running_loop().run_in_executor(
                    None, self.orchestrator.run_mining
                )
                logger.info(
                    "Background mining: %d found, %d new (novelty=%.2f)",
                    run.patterns_found,
                    run.patterns_new,
                    run.novelty_score,
                )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("Background mining error: %s", exc)
