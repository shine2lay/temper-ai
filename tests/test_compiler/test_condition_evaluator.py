"""Tests for ConditionEvaluator and helper functions."""
import pytest

from src.compiler.condition_evaluator import (
    ConditionEvaluator,
    get_default_condition,
    get_default_loop_condition,
)


class TestConditionEvaluator:
    """Tests for ConditionEvaluator.evaluate()."""

    def setup_method(self):
        self.evaluator = ConditionEvaluator()

    def test_evaluate_true(self):
        result = self.evaluator.evaluate("{{ true }}", {})
        assert result is True

    def test_evaluate_false(self):
        result = self.evaluator.evaluate("{{ false }}", {})
        assert result is False

    def test_evaluate_comparison_true(self):
        state = {"status": "failed"}
        result = self.evaluator.evaluate("{{ status == 'failed' }}", state)
        assert result is True

    def test_evaluate_comparison_false(self):
        state = {"status": "success"}
        result = self.evaluator.evaluate("{{ status == 'failed' }}", state)
        assert result is False

    def test_evaluate_nested_dict_access(self):
        state = {
            "stage_outputs": {
                "test": {"stage_status": "failed", "tests": {"success": False}}
            }
        }
        condition = "{{ stage_outputs.test.stage_status == 'failed' }}"
        result = self.evaluator.evaluate(condition, state)
        assert result is True

    def test_evaluate_nested_dict_get(self):
        state = {"stage_outputs": {"test": {"stage_status": "success"}}}
        condition = "{{ stage_outputs.get('test', {}).get('stage_status') == 'failed' }}"
        result = self.evaluator.evaluate(condition, state)
        assert result is False

    def test_evaluate_in_operator(self):
        state = {"stage_outputs": {"test": {"stage_status": "degraded"}}}
        condition = "{{ stage_outputs.test.stage_status in ['failed', 'degraded'] }}"
        result = self.evaluator.evaluate(condition, state)
        assert result is True

    def test_safe_context_filters_internals(self):
        """Infrastructure keys should be filtered from context."""
        state = {
            "stage_outputs": {"test": "result"},
            "tracker": object(),
            "tool_registry": object(),
            "config_loader": object(),
            "visualizer": object(),
        }
        # Should not raise even though tracker etc. are non-serializable
        result = self.evaluator.evaluate(
            "{{ stage_outputs.test == 'result' }}", state
        )
        assert result is True

    def test_missing_key_graceful(self):
        """Missing keys should not raise, should return falsy."""
        state = {}
        result = self.evaluator.evaluate(
            "{{ stage_outputs.nonexistent.value == 'x' }}", state
        )
        assert result is False

    def test_missing_key_with_get(self):
        state = {"stage_outputs": {}}
        result = self.evaluator.evaluate(
            "{{ stage_outputs.get('missing', {}).get('status') == 'failed' }}",
            state,
        )
        assert result is False

    def test_template_caching(self):
        """Same condition string should use cached template."""
        condition = "{{ x == 1 }}"
        self.evaluator.evaluate(condition, {"x": 1})
        self.evaluator.evaluate(condition, {"x": 2})
        # Verify template was cached
        assert condition in self.evaluator._template_cache
        assert len(self.evaluator._template_cache) == 1

    def test_evaluate_bad_syntax_returns_false(self):
        """Invalid Jinja2 syntax should return False, not raise."""
        result = self.evaluator.evaluate("{{ %%invalid%% }}", {})
        assert result is False


class TestGetDefaultCondition:
    """Tests for get_default_condition()."""

    def test_returns_none_for_first_stage(self):
        stages = [{"name": "init"}]
        result = get_default_condition(0, stages)
        assert result is None

    def test_generates_condition_for_second_stage(self):
        stages = [{"name": "test"}, {"name": "fix"}]
        result = get_default_condition(1, stages)
        assert result is not None
        assert "test" in result
        assert "stage_status" in result
        assert "failed" in result
        assert "degraded" in result

    def test_condition_works_with_evaluator(self):
        """Default condition should be evaluable."""
        stages = [{"name": "test"}, {"name": "fix"}]
        condition = get_default_condition(1, stages)
        evaluator = ConditionEvaluator()

        # Test with failed status
        state_failed = {"stage_outputs": {"test": {"stage_status": "failed"}}}
        assert evaluator.evaluate(condition, state_failed) is True

        # Test with success status
        state_success = {"stage_outputs": {"test": {"stage_status": "success"}}}
        assert evaluator.evaluate(condition, state_success) is False

    def test_works_with_pydantic_models(self):
        """Should work with objects that have .name attribute."""

        class FakeRef:
            def __init__(self, name):
                self.name = name

        stages = [FakeRef("test"), FakeRef("fix")]
        result = get_default_condition(1, stages)
        assert result is not None
        assert "test" in result


class TestGetDefaultLoopCondition:
    """Tests for get_default_loop_condition()."""

    def test_generates_condition(self):
        result = get_default_loop_condition("fix")
        assert result is not None
        assert "fix" in result
        assert "stage_status" in result

    def test_condition_evaluates_correctly(self):
        condition = get_default_loop_condition("fix")
        evaluator = ConditionEvaluator()

        state_failed = {"stage_outputs": {"fix": {"stage_status": "failed"}}}
        assert evaluator.evaluate(condition, state_failed) is True

        state_ok = {"stage_outputs": {"fix": {"stage_status": "success"}}}
        assert evaluator.evaluate(condition, state_ok) is False
