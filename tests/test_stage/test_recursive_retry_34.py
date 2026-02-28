"""Tests for code-high-recursive-retry-34.

Verifies that quality gate retry in ParallelStageExecutor uses an
iterative loop instead of recursion, preventing stack overflow.
"""

import sys
from collections.abc import Callable
from typing import Any
from unittest.mock import Mock, patch

import pytest

from temper_ai.agent.strategies.base import SynthesisResult
from temper_ai.stage.executors.base import ParallelRunner
from temper_ai.stage.executors.parallel import ParallelStageExecutor
from temper_ai.stage.executors.state_keys import StateKeys

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

# Standard parallel result returned by FakeParallelRunner.
# Mirrors the shape that LangGraphParallelRunner produces.
_PARALLEL_RESULT: dict[str, Any] = {
    "agent_outputs": {
        "agent_a": {
            "output": "test",
            "reasoning": "r",
            "confidence": 0.9,
            "metadata": {},
        },
        "__aggregate_metrics__": {},
    },
    "agent_statuses": {"agent_a": "success"},
    "agent_metrics": {},
}


class FakeParallelRunner(ParallelRunner):
    """In-process parallel runner that returns a fixed result.

    Replaces the LangGraph-based runner so tests exercise the retry
    logic without coupling to the graph engine at all.
    """

    def __init__(self, result: dict[str, Any] | None = None):
        self._result = result if result is not None else dict(_PARALLEL_RESULT)
        self.call_count = 0

    def run_parallel(
        self,
        nodes: dict[str, Callable[[dict[str, Any]], dict[str, Any]]],
        initial_state: dict[str, Any],
        *,
        init_node: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        collect_node: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        self.call_count += 1
        return dict(self._result)


def _make_synthesis_result(confidence=0.9, method="consensus"):
    """Create a SynthesisResult for testing."""
    return SynthesisResult(
        decision="test_decision",
        confidence=confidence,
        method=method,
        votes={"A": 1},
        conflicts=[],
        reasoning="test reasoning",
        metadata={},
    )


def _make_stage_config(
    on_failure="retry_stage",
    max_retries=2,
    min_confidence=0.8,
    enabled=True,
):
    """Create stage config with quality gates."""
    return {
        "agents": [{"name": "agent_a"}],
        "quality_gates": {
            "enabled": enabled,
            "min_confidence": min_confidence,
            "on_failure": on_failure,
            "max_retries": max_retries,
            "min_findings": 0,
            "require_citations": False,
        },
    }


class TestIterativeRetry:
    """Verify quality gate retry uses iteration, not recursion."""

    def _make_executor(self, synthesis_results=None, quality_results=None):
        """Create executor with controlled synthesis and quality gate results.

        Uses FakeParallelRunner instead of mocking LangGraph internals.

        Args:
            synthesis_results: List of SynthesisResult to return in sequence
            quality_results: List of (passed, violations) tuples
        """
        coordinator = Mock()
        if synthesis_results:
            coordinator.synthesize.side_effect = synthesis_results
        else:
            coordinator.synthesize.return_value = _make_synthesis_result()

        validator = Mock()
        if quality_results:
            validator.validate.side_effect = quality_results
        else:
            validator.validate.return_value = (True, [])

        return ParallelStageExecutor(
            synthesis_coordinator=coordinator,
            quality_gate_validator=validator,
            parallel_runner=FakeParallelRunner(),
        )

    def _make_state(self):
        """Create minimal workflow state."""
        return {
            "stage_outputs": {},
            "current_stage": None,
        }

    def test_no_recursion_with_high_max_retries(self, worker_id):
        """With max_retries=100, no RecursionError should occur.

        Note: Skipped in parallel mode due to sys.setrecursionlimit() modifying global state.
        """
        if worker_id != "master":
            pytest.skip("Test modifies global recursion limit - run serially only")
        fail_result = _make_synthesis_result(confidence=0.3)
        pass_result = _make_synthesis_result(confidence=0.95)

        # Fail 99 times, pass on attempt 100
        synthesis_results = [fail_result] * 99 + [pass_result]
        quality_results = [(False, ["low confidence"])] * 99 + [(True, [])]

        executor = self._make_executor(
            synthesis_results=synthesis_results,
            quality_results=quality_results,
        )

        config = _make_stage_config(max_retries=100, min_confidence=0.8)
        state = self._make_state()

        # This would cause RecursionError if recursive
        initial_limit = sys.getrecursionlimit()
        try:
            sys.setrecursionlimit(150)  # Low limit to catch recursion
            result = executor.execute_stage(
                stage_name="test_stage",
                stage_config=config,
                state=state,
                config_loader=Mock(),
            )
        finally:
            sys.setrecursionlimit(initial_limit)

        assert (
            result[StateKeys.STAGE_OUTPUTS]["test_stage"][StateKeys.DECISION]
            == "test_decision"
        )
        assert executor.parallel_runner.call_count == 100

    def test_pass_on_nth_retry(self):
        """Quality gate passes on the 3rd attempt (after 2 failures)."""
        fail_result = _make_synthesis_result(confidence=0.5)
        pass_result = _make_synthesis_result(confidence=0.95)

        executor = self._make_executor(
            synthesis_results=[fail_result, fail_result, pass_result],
            quality_results=[
                (False, ["Confidence 0.50 below minimum 0.80"]),
                (False, ["Confidence 0.50 below minimum 0.80"]),
                (True, []),
            ],
        )

        config = _make_stage_config(max_retries=5, min_confidence=0.8)
        state = self._make_state()

        result = executor.execute_stage(
            stage_name="test_stage",
            stage_config=config,
            state=state,
            config_loader=Mock(),
        )

        # Should succeed on 3rd attempt
        assert "test_stage" in result[StateKeys.STAGE_OUTPUTS]
        assert (
            result[StateKeys.STAGE_OUTPUTS]["test_stage"][StateKeys.DECISION]
            == "test_decision"
        )
        # Synthesis was called 3 times
        assert executor.synthesis_coordinator.synthesize.call_count == 3
        assert executor.parallel_runner.call_count == 3

    def test_retries_exhausted_raises(self):
        """All retries exhausted should raise RuntimeError."""
        fail_result = _make_synthesis_result(confidence=0.3)

        executor = self._make_executor(
            synthesis_results=[fail_result] * 3,
            quality_results=[(False, ["low confidence"])] * 3,
        )

        config = _make_stage_config(max_retries=2, min_confidence=0.8)
        state = self._make_state()

        with pytest.raises(RuntimeError, match="after 2 retries"):
            executor.execute_stage(
                stage_name="test_stage",
                stage_config=config,
                state=state,
                config_loader=Mock(),
            )

        # 1 initial + 2 retries = 3 calls
        assert executor.synthesis_coordinator.synthesize.call_count == 3

    def test_max_retries_zero_no_retries(self):
        """max_retries=0 means no retries, immediate escalation."""
        fail_result = _make_synthesis_result(confidence=0.3)

        executor = self._make_executor(
            synthesis_results=[fail_result],
            quality_results=[(False, ["low confidence"])],
        )

        config = _make_stage_config(max_retries=0, min_confidence=0.8)
        state = self._make_state()

        with pytest.raises(RuntimeError, match="after 0 retries"):
            executor.execute_stage(
                stage_name="test_stage",
                stage_config=config,
                state=state,
                config_loader=Mock(),
            )

        # Only 1 call (no retries)
        assert executor.synthesis_coordinator.synthesize.call_count == 1

    def test_max_retries_one(self):
        """max_retries=1 allows exactly one retry attempt."""
        fail_result = _make_synthesis_result(confidence=0.3)

        executor = self._make_executor(
            synthesis_results=[fail_result, fail_result],
            quality_results=[(False, ["low confidence"])] * 2,
        )

        config = _make_stage_config(max_retries=1, min_confidence=0.8)
        state = self._make_state()

        with pytest.raises(RuntimeError, match="after 1 retries"):
            executor.execute_stage(
                stage_name="test_stage",
                stage_config=config,
                state=state,
                config_loader=Mock(),
            )

        # 1 initial + 1 retry = 2 calls
        assert executor.synthesis_coordinator.synthesize.call_count == 2

    def test_retry_count_tracked_in_state(self):
        """Retry count is correctly tracked in state['stage_retry_counts']."""
        fail_result = _make_synthesis_result(confidence=0.3)
        pass_result = _make_synthesis_result(confidence=0.95)

        executor = self._make_executor(
            synthesis_results=[fail_result, fail_result, pass_result],
            quality_results=[
                (False, ["low confidence"]),
                (False, ["low confidence"]),
                (True, []),
            ],
        )

        config = _make_stage_config(max_retries=5, min_confidence=0.8)
        state = self._make_state()

        executor.execute_stage(
            stage_name="test_stage",
            stage_config=config,
            state=state,
            config_loader=Mock(),
        )

        # Retry counter should be cleaned up after success
        assert "test_stage" not in state.get("stage_retry_counts", {})

    def test_stack_depth_constant(self):
        """Stack depth should not increase with retry count."""
        stack_depths = []

        def tracking_validate(
            self_inner, synthesis_result, stage_config, stage_name, state
        ):
            stack_depths.append(
                len([f for f in _get_stack_frames() if "execute_stage" in f])
            )
            # Fail for first 9, pass on 10th
            if len(stack_depths) < 10:
                return (False, ["low confidence"])
            return (True, [])

        executor = ParallelStageExecutor(
            synthesis_coordinator=Mock(
                synthesize=Mock(return_value=_make_synthesis_result())
            ),
            parallel_runner=FakeParallelRunner(),
        )

        config = _make_stage_config(max_retries=15, min_confidence=0.8)
        state = self._make_state()

        with patch.object(
            ParallelStageExecutor,
            "_validate_quality_gates",
            tracking_validate,
        ):
            executor.execute_stage(
                stage_name="test_stage",
                stage_config=config,
                state=state,
                config_loader=Mock(),
            )

        # All stack depths should be equal (constant depth)
        assert len(stack_depths) == 10
        assert all(
            d == stack_depths[0] for d in stack_depths
        ), f"Stack depths varied: {stack_depths}"


def _get_stack_frames():
    """Get current stack frame names."""
    import traceback

    return [line.name for line in traceback.extract_stack()]
