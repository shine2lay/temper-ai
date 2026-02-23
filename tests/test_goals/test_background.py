"""Tests for BackgroundAnalysisJob."""

from unittest.mock import MagicMock

import pytest

from temper_ai.goals.background import BackgroundAnalysisJob


class TestBackgroundAnalysisJob:
    def test_init(self):
        orch = MagicMock()
        job = BackgroundAnalysisJob(orchestrator=orch, interval_hours=6)
        assert job.interval_seconds == 6 * 3600
        assert job._running is False

    @pytest.mark.asyncio
    async def test_start_stop(self):
        orch = MagicMock()
        job = BackgroundAnalysisJob(orchestrator=orch, interval_hours=1)
        await job.start()
        assert job._running is True
        assert job._task is not None
        await job.stop()
        assert job._running is False

    @pytest.mark.asyncio
    async def test_stop_without_start(self):
        orch = MagicMock()
        job = BackgroundAnalysisJob(orchestrator=orch)
        await job.stop()
        assert job._running is False

    @pytest.mark.asyncio
    async def test_loop_cancellation(self):
        orch = MagicMock()
        job = BackgroundAnalysisJob(orchestrator=orch, interval_hours=1)
        await job.start()
        # Immediately cancel
        await job.stop()
        assert not job._running
