"""Tests for sampling strategy and performance tracker integration in ExecutionTracker."""

from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from temper_ai.observability.sampling import SamplingContext, SamplingDecision
from temper_ai.observability.tracker import ExecutionTracker

# ========== Fixtures ==========


@contextmanager
def _fake_session_ctx():
    """Fake session context manager for mocked backend."""
    yield MagicMock()


class _FakeAsyncSessionCtx:
    """Fake async context manager for mocked backend."""

    async def __aenter__(self):
        return MagicMock()

    async def __aexit__(self, *args):
        pass


def _make_mock_backend():
    """Create a mock backend with session context managers wired up."""
    backend = MagicMock()
    backend.get_session_context = _fake_session_ctx
    backend.aget_session_context = _FakeAsyncSessionCtx
    # Ensure async methods return coroutines
    backend.atrack_workflow_start = AsyncMock()
    return backend


def _make_never_sample_strategy():
    """Create a sampling strategy that always returns sampled=False."""
    strategy = MagicMock()
    strategy.should_sample.return_value = SamplingDecision(
        sampled=False, reason="test skip", strategy_name="never"
    )
    return strategy


def _make_always_sample_strategy():
    """Create a sampling strategy that always returns sampled=True."""
    strategy = MagicMock()
    strategy.should_sample.return_value = SamplingDecision(
        sampled=True, reason="test sample", strategy_name="always"
    )
    return strategy


@pytest.fixture
def mock_backend():
    """Mock observability backend."""
    return _make_mock_backend()


@pytest.fixture
def mock_perf_tracker():
    """Mock performance tracker."""
    return MagicMock()


@pytest.fixture
def tracker_no_sample(mock_backend, mock_perf_tracker):
    """Tracker with NeverSample strategy.

    Note: _performance_tracker is set directly because ExecutionTracker
    has no public constructor parameter for performance tracker injection.
    """
    t = ExecutionTracker(
        backend=mock_backend,
        sampling_strategy=_make_never_sample_strategy(),
    )
    t._performance_tracker = mock_perf_tracker
    return t


@pytest.fixture
def tracker_always_sample(mock_backend, mock_perf_tracker):
    """Tracker with AlwaysSample strategy."""
    t = ExecutionTracker(
        backend=mock_backend,
        sampling_strategy=_make_always_sample_strategy(),
    )
    t._performance_tracker = mock_perf_tracker
    return t


@pytest.fixture
def tracker_no_strategy(mock_backend, mock_perf_tracker):
    """Tracker with no sampling strategy (default behavior)."""
    t = ExecutionTracker(backend=mock_backend)
    t._performance_tracker = mock_perf_tracker
    return t


# ========== Sync track_workflow sampling tests ==========


class TestSyncWorkflowSampling:
    """Tests for sampling in sync track_workflow."""

    def test_skip_backend_when_not_sampled(self, tracker_no_sample, mock_backend):
        """Workflow runs but backend is not called when not sampled."""
        with tracker_no_sample.track_workflow("test_wf", {"key": "val"}) as wf_id:
            assert wf_id is not None
            assert wf_id.startswith("wf-")

        # Backend tracking should NOT be called
        mock_backend.track_workflow_start.assert_not_called()

    def test_context_cleared_when_not_sampled(self, tracker_no_sample):
        """workflow_id is cleared from context after unsampled workflow exits."""
        with tracker_no_sample.track_workflow("test_wf", {}) as wf_id:
            assert tracker_no_sample.context.workflow_id == wf_id

        assert tracker_no_sample.context.workflow_id is None

    def test_full_tracking_when_sampled(self, tracker_always_sample, mock_backend):
        """Backend is fully called when sampling says yes."""
        with tracker_always_sample.track_workflow("sampled_wf", {"k": "v"}) as wf_id:
            assert wf_id is not None

        mock_backend.track_workflow_start.assert_called_once()

    def test_full_tracking_when_no_strategy(self, tracker_no_strategy, mock_backend):
        """Backend is fully called when no sampling strategy is configured."""
        with tracker_no_strategy.track_workflow("default_wf", {"k": "v"}) as wf_id:
            assert wf_id is not None

        mock_backend.track_workflow_start.assert_called_once()

    def test_sampling_context_built_correctly(self, mock_backend, mock_perf_tracker):
        """SamplingContext is built with correct fields from params."""
        strategy = MagicMock()
        strategy.should_sample.return_value = SamplingDecision(
            sampled=False, reason="test", strategy_name="test"
        )
        t = ExecutionTracker(backend=mock_backend, sampling_strategy=strategy)
        t._performance_tracker = mock_perf_tracker

        with t.track_workflow(
            "my_wf", {}, environment="production", tags=["critical"]
        ) as wf_id:
            pass

        call_args = strategy.should_sample.call_args[0][0]
        assert isinstance(call_args, SamplingContext)
        assert call_args.workflow_name == "my_wf"
        assert call_args.environment == "production"
        assert call_args.tags == ["critical"]
        assert call_args.workflow_id == wf_id


# ========== Async atrack_workflow sampling tests ==========


class TestAsyncWorkflowSampling:
    """Tests for sampling in async atrack_workflow."""

    @pytest.mark.asyncio
    async def test_skip_backend_when_not_sampled(self, tracker_no_sample, mock_backend):
        """Async workflow runs but backend is not called when not sampled."""
        async with tracker_no_sample.atrack_workflow("async_wf", {"k": "v"}) as wf_id:
            assert wf_id is not None
            assert wf_id.startswith("wf-")

        mock_backend.atrack_workflow_start.assert_not_called()

    @pytest.mark.asyncio
    async def test_context_cleared_when_not_sampled(self, tracker_no_sample):
        """workflow_id is cleared from context after unsampled async workflow."""
        async with tracker_no_sample.atrack_workflow("async_wf", {}) as wf_id:
            assert tracker_no_sample.context.workflow_id == wf_id

        assert tracker_no_sample.context.workflow_id is None

    @pytest.mark.asyncio
    async def test_full_tracking_when_sampled(
        self, tracker_always_sample, mock_backend
    ):
        """Async backend is fully called when sampling says yes."""
        async with tracker_always_sample.atrack_workflow(
            "sampled_wf", {"k": "v"}
        ) as wf_id:
            assert wf_id is not None

        mock_backend.atrack_workflow_start.assert_called_once()


# ========== Performance tracker integration tests ==========


class TestPerfTrackerWorkflow:
    """Tests for PerformanceTracker recording in workflow tracking."""

    def test_perf_recorded_on_workflow_success(
        self, tracker_always_sample, mock_perf_tracker
    ):
        """Performance is recorded after successful workflow."""
        with tracker_always_sample.track_workflow("perf_wf", {}) as wf_id:
            pass

        mock_perf_tracker.record.assert_called()
        call_args = mock_perf_tracker.record.call_args
        assert call_args[0][0] == "workflow_execution"
        assert call_args[0][1] > 0  # latency_ms > 0
        assert call_args[0][2]["workflow_id"] == wf_id

    def test_perf_recorded_on_workflow_error(
        self, tracker_always_sample, mock_perf_tracker
    ):
        """Performance is recorded even when workflow raises."""
        with pytest.raises(ValueError):
            with tracker_always_sample.track_workflow("err_wf", {}) as wf_id:
                raise ValueError("test error")

        mock_perf_tracker.record.assert_called()
        call_args = mock_perf_tracker.record.call_args
        assert call_args[0][0] == "workflow_execution"

    @pytest.mark.asyncio
    async def test_async_perf_recorded_on_workflow(
        self, tracker_always_sample, mock_perf_tracker
    ):
        """Performance is recorded in async workflow finally block."""
        async with tracker_always_sample.atrack_workflow("async_perf", {}) as wf_id:
            pass

        mock_perf_tracker.record.assert_called()
        call_args = mock_perf_tracker.record.call_args
        assert call_args[0][0] == "workflow_execution"
        assert call_args[0][2]["workflow_id"] == wf_id


class TestPerfTrackerStage:
    """Tests for PerformanceTracker recording in stage tracking."""

    def test_perf_recorded_on_stage(self, tracker_no_strategy, mock_perf_tracker):
        """Performance is recorded after stage execution."""
        with tracker_no_strategy.track_workflow("wf", {}) as wf_id:
            with tracker_no_strategy.track_stage("stage1", {}, wf_id) as stage_id:
                pass

        # Find the stage_execution call
        stage_calls = [
            c
            for c in mock_perf_tracker.record.call_args_list
            if c[0][0] == "stage_execution"
        ]
        assert len(stage_calls) == 1
        assert stage_calls[0][0][2]["stage_id"] == stage_id


class TestPerfTrackerAgent:
    """Tests for PerformanceTracker recording in agent tracking."""

    def test_perf_recorded_on_agent(self, tracker_no_strategy, mock_perf_tracker):
        """Performance is recorded after agent execution."""
        with tracker_no_strategy.track_workflow("wf", {}) as wf_id:
            with tracker_no_strategy.track_stage("s1", {}, wf_id) as stage_id:
                with tracker_no_strategy.track_agent(
                    "agent1", {}, stage_id
                ) as agent_id:
                    pass

        agent_calls = [
            c
            for c in mock_perf_tracker.record.call_args_list
            if c[0][0] == "agent_execution"
        ]
        assert len(agent_calls) == 1
        assert agent_calls[0][0][2]["agent_id"] == agent_id


# ========== LLM/Tool perf recording tests ==========


class TestPerfTrackerLLMTool:
    """Tests for PerformanceTracker recording in LLM and tool helpers."""

    def test_llm_perf_recorded(self, tracker_no_strategy):
        """Performance tracker records llm_call latency."""
        from temper_ai.observability._tracker_helpers import LLMCallTrackingData

        with patch(
            "temper_ai.observability.performance.get_performance_tracker"
        ) as mock_get:
            mock_pt = MagicMock()
            mock_get.return_value = mock_pt

            tracker_no_strategy.track_llm_call(
                LLMCallTrackingData(
                    agent_id="a1",
                    provider="test",
                    model="test-model",
                    prompt="hello",
                    response="world",
                    prompt_tokens=10,
                    completion_tokens=10,
                    latency_ms=250,
                    estimated_cost_usd=0.01,
                )
            )

            mock_pt.record.assert_called_once()
            call_args = mock_pt.record.call_args
            assert call_args[0][0] == "llm_call"
            assert call_args[0][1] == 250.0
            assert call_args[0][2]["provider"] == "test"
            assert call_args[0][2]["model"] == "test-model"

    def test_tool_perf_recorded(self, tracker_no_strategy):
        """Performance tracker records tool_execution latency."""
        from temper_ai.observability._tracker_helpers import ToolCallTrackingData

        with patch(
            "temper_ai.observability.performance.get_performance_tracker"
        ) as mock_get:
            mock_pt = MagicMock()
            mock_get.return_value = mock_pt

            tracker_no_strategy.track_tool_call(
                ToolCallTrackingData(
                    agent_id="a1",
                    tool_name="bash",
                    input_params={"cmd": "ls"},
                    output_data={"result": "ok"},
                    duration_seconds=1.5,
                )
            )

            mock_pt.record.assert_called_once()
            call_args = mock_pt.record.call_args
            assert call_args[0][0] == "tool_execution"
            assert call_args[0][1] == 1500.0  # 1.5 * 1000
            assert call_args[0][2]["tool_name"] == "bash"


# ========== Best-effort / failure resilience tests ==========


class TestPerfRecordingResilience:
    """Tests that perf recording failures do not break tracking."""

    def test_perf_failure_does_not_break_workflow(
        self, tracker_always_sample, mock_perf_tracker
    ):
        """Workflow completes even if perf recording raises."""
        mock_perf_tracker.record.side_effect = RuntimeError("perf boom")

        # Should NOT raise
        with tracker_always_sample.track_workflow("resilient_wf", {}) as wf_id:
            assert wf_id is not None

        # Workflow completed despite perf failure
        assert tracker_always_sample.context.workflow_id is None

    def test_llm_perf_failure_does_not_break_tracking(self, tracker_no_strategy):
        """LLM tracking returns call ID even if perf recording fails."""
        from temper_ai.observability._tracker_helpers import LLMCallTrackingData

        with patch(
            "temper_ai.observability.performance.get_performance_tracker"
        ) as mock_get:
            mock_pt = MagicMock()
            mock_pt.record.side_effect = RuntimeError("perf boom")
            mock_get.return_value = mock_pt

            call_id = tracker_no_strategy.track_llm_call(
                LLMCallTrackingData(
                    agent_id="a1",
                    provider="test",
                    model="test-model",
                    prompt="hello",
                    response="world",
                    prompt_tokens=10,
                    completion_tokens=10,
                    latency_ms=100,
                    estimated_cost_usd=0.01,
                )
            )

            assert call_id is not None

    def test_tool_perf_failure_does_not_break_tracking(self, tracker_no_strategy):
        """Tool tracking returns execution ID even if perf recording fails."""
        from temper_ai.observability._tracker_helpers import ToolCallTrackingData

        with patch(
            "temper_ai.observability.performance.get_performance_tracker"
        ) as mock_get:
            mock_pt = MagicMock()
            mock_pt.record.side_effect = RuntimeError("perf boom")
            mock_get.return_value = mock_pt

            exec_id = tracker_no_strategy.track_tool_call(
                ToolCallTrackingData(
                    agent_id="a1",
                    tool_name="bash",
                    input_params={"cmd": "ls"},
                    output_data={"result": "ok"},
                    duration_seconds=0.5,
                )
            )

            assert exec_id is not None
