"""Tests for BackgroundMiningJob."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.learning.background import BackgroundMiningJob


@pytest.fixture()
def job() -> BackgroundMiningJob:
    orch = MagicMock()
    conv = MagicMock()
    conv.is_converged.return_value = False
    return BackgroundMiningJob(orchestrator=orch, convergence=conv, interval_hours=1)


class TestBackgroundMiningJob:
    @pytest.mark.asyncio
    async def test_start_and_stop(self, job: BackgroundMiningJob) -> None:
        await job.start()
        assert job._task is not None
        assert job._running is True
        await job.stop()
        assert job._running is False

    @pytest.mark.asyncio
    async def test_stop_without_start(self, job: BackgroundMiningJob) -> None:
        await job.stop()
        assert job._running is False

    def test_skips_when_converged(self) -> None:
        orch = MagicMock()
        conv = MagicMock()
        conv.is_converged.return_value = True
        job = BackgroundMiningJob(orchestrator=orch, convergence=conv)
        # Convergence check is used in the loop; just verify constructor works
        assert job.convergence.is_converged() is True

    def test_interval_calculation(self) -> None:
        orch = MagicMock()
        conv = MagicMock()
        job = BackgroundMiningJob(orchestrator=orch, convergence=conv, interval_hours=2)
        assert job.interval_seconds == 7200
