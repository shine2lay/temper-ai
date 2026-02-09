"""Tests for progress reporter."""
import pytest
from datetime import datetime, timezone
from src.self_improvement.loop.progress_reporter import ProgressReporter
from src.self_improvement.loop.models import (
    LoopState,
    LoopStatus,
    Phase,
    PhaseProgress,
    ProgressReport
)
from src.self_improvement.loop.metrics import LoopMetrics


class TestProgressReporter:
    """Test ProgressReporter functionality."""

    def test_initialization(self):
        """Test reporter initialization."""
        reporter = ProgressReporter()
        assert reporter is not None

    def test_build_progress_report_no_state(self):
        """Test building report when agent has no state."""
        reporter = ProgressReporter()

        report = reporter.build_progress_report("test_agent", None, None)

        assert isinstance(report, ProgressReport)
        assert report.agent_name == "test_agent"
        assert report.current_phase == Phase.DETECT
        assert report.current_iteration == 0
        assert report.total_iterations_completed == 0
        assert report.phase_progress == {}
        assert report.health_status == "not_started"
        assert report.last_success is None

    def test_build_progress_report_with_state(self):
        """Test building report with state."""
        reporter = ProgressReporter()
        now = datetime.now(timezone.utc)

        state = LoopState(
            agent_name="test_agent",
            current_phase=Phase.ANALYZE,
            status=LoopStatus.RUNNING,
            iteration_number=3,
            started_at=now,
            updated_at=now
        )

        report = reporter.build_progress_report("test_agent", state, None)

        assert report.agent_name == "test_agent"
        assert report.current_phase == Phase.ANALYZE
        assert report.current_iteration == 3
        assert report.total_iterations_completed == 0
        assert report.health_status == "healthy"
        assert isinstance(report.phase_progress, dict)

    def test_build_progress_report_with_metrics(self):
        """Test building report with metrics."""
        reporter = ProgressReporter()
        now = datetime.now(timezone.utc)

        state = LoopState(
            agent_name="test_agent",
            current_phase=Phase.DEPLOY,
            status=LoopStatus.RUNNING,
            iteration_number=5,
            started_at=now,
            updated_at=now
        )

        metrics = LoopMetrics(
            agent_name="test_agent",
            total_iterations=10,
            successful_iterations=8,
            last_iteration_at=now
        )

        report = reporter.build_progress_report("test_agent", state, metrics)

        assert report.total_iterations_completed == 10
        assert report.last_success == now

    def test_build_phase_progress(self):
        """Test phase progress building."""
        reporter = ProgressReporter()

        phase_progress = reporter._build_phase_progress()

        assert isinstance(phase_progress, dict)
        assert len(phase_progress) == 5  # All 5 phases
        assert Phase.DETECT in phase_progress
        assert Phase.ANALYZE in phase_progress
        assert Phase.STRATEGY in phase_progress
        assert Phase.EXPERIMENT in phase_progress
        assert Phase.DEPLOY in phase_progress

        # Check all phases have not_started status
        for phase, progress in phase_progress.items():
            assert isinstance(progress, PhaseProgress)
            assert progress.phase == phase
            assert progress.status == "not_started"

    def test_determine_health_status_healthy(self):
        """Test health status determination - healthy."""
        reporter = ProgressReporter()
        now = datetime.now(timezone.utc)

        state = LoopState(
            agent_name="test_agent",
            current_phase=Phase.DETECT,
            status=LoopStatus.RUNNING,
            iteration_number=1,
            started_at=now,
            updated_at=now
        )

        health = reporter._determine_health_status(state)

        assert health == "healthy"

    def test_determine_health_status_failed(self):
        """Test health status determination - failed."""
        reporter = ProgressReporter()
        now = datetime.now(timezone.utc)

        state = LoopState(
            agent_name="test_agent",
            current_phase=Phase.DETECT,
            status=LoopStatus.FAILED,
            iteration_number=1,
            last_error="Test error",
            started_at=now,
            updated_at=now
        )

        health = reporter._determine_health_status(state)

        assert health == "failed"

    def test_determine_health_status_paused(self):
        """Test health status determination - paused."""
        reporter = ProgressReporter()
        now = datetime.now(timezone.utc)

        state = LoopState(
            agent_name="test_agent",
            current_phase=Phase.DETECT,
            status=LoopStatus.PAUSED,
            iteration_number=1,
            started_at=now,
            updated_at=now
        )

        health = reporter._determine_health_status(state)

        assert health == "paused"

    def test_determine_health_status_degraded(self):
        """Test health status determination - degraded (has error but not failed)."""
        reporter = ProgressReporter()
        now = datetime.now(timezone.utc)

        state = LoopState(
            agent_name="test_agent",
            current_phase=Phase.DETECT,
            status=LoopStatus.RUNNING,
            iteration_number=1,
            last_error="Non-fatal error",
            started_at=now,
            updated_at=now
        )

        health = reporter._determine_health_status(state)

        assert health == "degraded"

    def test_determine_health_status_completed(self):
        """Test health status determination - completed status."""
        reporter = ProgressReporter()
        now = datetime.now(timezone.utc)

        state = LoopState(
            agent_name="test_agent",
            current_phase=Phase.DEPLOY,
            status=LoopStatus.COMPLETED,
            iteration_number=1,
            started_at=now,
            updated_at=now
        )

        health = reporter._determine_health_status(state)

        # Completed with no error is healthy
        assert health == "healthy"

    def test_build_progress_report_full(self):
        """Test building complete progress report with all data."""
        reporter = ProgressReporter()
        now = datetime.now(timezone.utc)

        state = LoopState(
            agent_name="test_agent",
            current_phase=Phase.EXPERIMENT,
            status=LoopStatus.RUNNING,
            iteration_number=2,
            phase_data={"experiment_id": "exp-123"},
            started_at=now,
            updated_at=now
        )

        metrics = LoopMetrics(
            agent_name="test_agent",
            total_iterations=5,
            successful_iterations=4,
            failed_iterations=1,
            total_experiments=3,
            successful_deployments=2,
            rollbacks=1,
            avg_iteration_duration=120.5,
            last_iteration_at=now
        )

        report = reporter.build_progress_report("test_agent", state, metrics)

        assert report.agent_name == "test_agent"
        assert report.current_phase == Phase.EXPERIMENT
        assert report.current_iteration == 2
        assert report.total_iterations_completed == 5
        assert report.health_status == "healthy"
        assert report.last_success == now
        assert len(report.phase_progress) == 5
