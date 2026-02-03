"""Tests for code-high-recursive-retry-34.

Verifies that quality gate retry in ParallelStageExecutor uses an
iterative loop instead of recursion, preventing stack overflow.
"""

import sys
import pytest
from unittest.mock import Mock, patch, MagicMock, call

from src.compiler.executors.parallel import ParallelStageExecutor
from src.strategies.base import SynthesisResult


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
        )

    def _make_state(self):
        """Create minimal workflow state."""
        return {
            "stage_outputs": {},
            "current_stage": None,
        }

    @patch("src.compiler.executors.parallel.StateGraph")
    def test_no_recursion_with_high_max_retries(self, mock_sg_class):
        """With max_retries=100, no RecursionError should occur."""
        # All 100 attempts fail, then exhausted
        fail_result = _make_synthesis_result(confidence=0.3)
        pass_result = _make_synthesis_result(confidence=0.95)

        # Fail 99 times, pass on attempt 100
        synthesis_results = [fail_result] * 99 + [pass_result]
        quality_results = [(False, ["low confidence"])] * 99 + [(True, [])]

        executor = self._make_executor(
            synthesis_results=synthesis_results,
            quality_results=quality_results,
        )

        # Mock the subgraph compilation and invocation
        mock_compiled = Mock()
        mock_compiled.invoke.return_value = {
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
        mock_sg_instance = Mock()
        mock_sg_instance.compile.return_value = mock_compiled
        mock_sg_class.return_value = mock_sg_instance

        config = _make_stage_config(max_retries=100, min_confidence=0.8)
        state = self._make_state()

        # This would cause RecursionError if recursive
        initial_limit = sys.getrecursionlimit()
        try:
            sys.setrecursionlimit(50)  # Very low limit to catch recursion
            result = executor.execute_stage(
                stage_name="test_stage",
                stage_config=config,
                state=state,
                config_loader=Mock(),
            )
        finally:
            sys.setrecursionlimit(initial_limit)

        assert result["stage_outputs"]["test_stage"]["decision"] == "test_decision"

    @patch("src.compiler.executors.parallel.StateGraph")
    def test_pass_on_nth_retry(self, mock_sg_class):
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

        mock_compiled = Mock()
        mock_compiled.invoke.return_value = {
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
        mock_sg_instance = Mock()
        mock_sg_instance.compile.return_value = mock_compiled
        mock_sg_class.return_value = mock_sg_instance

        config = _make_stage_config(max_retries=5, min_confidence=0.8)
        state = self._make_state()

        result = executor.execute_stage(
            stage_name="test_stage",
            stage_config=config,
            state=state,
            config_loader=Mock(),
        )

        # Should succeed on 3rd attempt
        assert "test_stage" in result["stage_outputs"]
        assert result["stage_outputs"]["test_stage"]["decision"] == "test_decision"
        # Synthesis was called 3 times
        assert executor.synthesis_coordinator.synthesize.call_count == 3

    @patch("src.compiler.executors.parallel.StateGraph")
    def test_retries_exhausted_raises(self, mock_sg_class):
        """All retries exhausted should raise RuntimeError."""
        fail_result = _make_synthesis_result(confidence=0.3)

        executor = self._make_executor(
            synthesis_results=[fail_result] * 3,
            quality_results=[(False, ["low confidence"])] * 3,
        )

        mock_compiled = Mock()
        mock_compiled.invoke.return_value = {
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
        mock_sg_instance = Mock()
        mock_sg_instance.compile.return_value = mock_compiled
        mock_sg_class.return_value = mock_sg_instance

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

    @patch("src.compiler.executors.parallel.StateGraph")
    def test_max_retries_zero_no_retries(self, mock_sg_class):
        """max_retries=0 means no retries, immediate escalation."""
        fail_result = _make_synthesis_result(confidence=0.3)

        executor = self._make_executor(
            synthesis_results=[fail_result],
            quality_results=[(False, ["low confidence"])],
        )

        mock_compiled = Mock()
        mock_compiled.invoke.return_value = {
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
        mock_sg_instance = Mock()
        mock_sg_instance.compile.return_value = mock_compiled
        mock_sg_class.return_value = mock_sg_instance

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

    @patch("src.compiler.executors.parallel.StateGraph")
    def test_max_retries_one(self, mock_sg_class):
        """max_retries=1 allows exactly one retry attempt."""
        fail_result = _make_synthesis_result(confidence=0.3)

        executor = self._make_executor(
            synthesis_results=[fail_result, fail_result],
            quality_results=[(False, ["low confidence"])] * 2,
        )

        mock_compiled = Mock()
        mock_compiled.invoke.return_value = {
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
        mock_sg_instance = Mock()
        mock_sg_instance.compile.return_value = mock_compiled
        mock_sg_class.return_value = mock_sg_instance

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

    @patch("src.compiler.executors.parallel.StateGraph")
    def test_retry_count_tracked_in_state(self, mock_sg_class):
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

        mock_compiled = Mock()
        mock_compiled.invoke.return_value = {
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
        mock_sg_instance = Mock()
        mock_sg_instance.compile.return_value = mock_compiled
        mock_sg_class.return_value = mock_sg_instance

        config = _make_stage_config(max_retries=5, min_confidence=0.8)
        state = self._make_state()

        result = executor.execute_stage(
            stage_name="test_stage",
            stage_config=config,
            state=state,
            config_loader=Mock(),
        )

        # Retry counter should be cleaned up after success
        assert "test_stage" not in state.get("stage_retry_counts", {})

    @patch("src.compiler.executors.parallel.StateGraph")
    def test_stack_depth_constant(self, mock_sg_class):
        """Stack depth should not increase with retry count."""
        stack_depths = []

        original_validate = ParallelStageExecutor._validate_quality_gates

        def tracking_validate(self_inner, synthesis_result, stage_config, stage_name, state):
            stack_depths.append(len([
                f for f in _get_stack_frames()
                if "execute_stage" in f
            ]))
            # Fail for first 9, pass on 10th
            if len(stack_depths) < 10:
                return (False, ["low confidence"])
            return (True, [])

        mock_compiled = Mock()
        mock_compiled.invoke.return_value = {
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
        mock_sg_instance = Mock()
        mock_sg_instance.compile.return_value = mock_compiled
        mock_sg_class.return_value = mock_sg_instance

        executor = ParallelStageExecutor(
            synthesis_coordinator=Mock(
                synthesize=Mock(return_value=_make_synthesis_result())
            ),
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
        assert all(d == stack_depths[0] for d in stack_depths), (
            f"Stack depths varied: {stack_depths}"
        )


def _get_stack_frames():
    """Get current stack frame names."""
    import traceback
    return [line.name for line in traceback.extract_stack()]
