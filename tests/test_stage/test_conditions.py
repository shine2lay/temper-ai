"""Tests for stage/conditions.py — condition evaluation."""

import pytest

from temper_ai.shared.types import NodeResult, Status
from temper_ai.stage.conditions import (
    _apply_operator,
    _resolve_source,
    evaluate_condition,
)
from temper_ai.stage.exceptions import ConditionError


@pytest.fixture
def node_outputs():
    return {
        "planner": NodeResult(
            status=Status.COMPLETED,
            output="Plan: do X then Y",
            structured_output={"steps": ["X", "Y"], "count": 2},
            cost_usd=0.05,
            total_tokens=500,
        ),
        "review": NodeResult(
            status=Status.COMPLETED,
            output="Looks good",
            structured_output={
                "verdict": "PASS",
                "issues": [],
                "nested": {"deep": "value"},
            },
        ),
        "failed_node": NodeResult(
            status=Status.FAILED,
            error="Something broke",
        ),
        "no_structured": NodeResult(
            status=Status.COMPLETED,
            output="Just text",
        ),
    }


class TestResolveSource:
    def test_output_field(self, node_outputs):
        assert _resolve_source("planner.output", node_outputs) == "Plan: do X then Y"

    def test_status_field(self, node_outputs):
        assert _resolve_source("planner.status", node_outputs) == Status.COMPLETED
        assert _resolve_source("failed_node.status", node_outputs) == Status.FAILED

    def test_structured_field(self, node_outputs):
        assert _resolve_source("review.structured.verdict", node_outputs) == "PASS"

    def test_structured_nested(self, node_outputs):
        assert _resolve_source("review.structured.nested.deep", node_outputs) == "value"

    def test_structured_list(self, node_outputs):
        assert _resolve_source("planner.structured.steps", node_outputs) == ["X", "Y"]

    def test_structured_none(self, node_outputs):
        assert _resolve_source("no_structured.structured.anything", node_outputs) is None

    def test_cost_field(self, node_outputs):
        assert _resolve_source("planner.cost_usd", node_outputs) == 0.05

    def test_tokens_field(self, node_outputs):
        assert _resolve_source("planner.total_tokens", node_outputs) == 500

    def test_error_field(self, node_outputs):
        assert _resolve_source("failed_node.error", node_outputs) == "Something broke"
        assert _resolve_source("planner.error", node_outputs) is None

    def test_missing_node_raises(self, node_outputs):
        with pytest.raises(KeyError, match="not found"):
            _resolve_source("nonexistent.output", node_outputs)

    def test_bad_format_raises(self, node_outputs):
        with pytest.raises(KeyError, match="must be"):
            _resolve_source("planner", node_outputs)

    def test_unknown_field_raises(self, node_outputs):
        with pytest.raises(KeyError, match="Unknown field"):
            _resolve_source("planner.foo", node_outputs)


class TestApplyOperator:
    def test_equals(self):
        assert _apply_operator("PASS", "equals", "PASS") is True
        assert _apply_operator("PASS", "equals", "FAIL") is False
        assert _apply_operator(42, "equals", 42) is True

    def test_not_equals(self):
        assert _apply_operator("PASS", "not_equals", "FAIL") is True
        assert _apply_operator("PASS", "not_equals", "PASS") is False

    def test_contains_string(self):
        assert _apply_operator("hello world", "contains", "world") is True
        assert _apply_operator("hello world", "contains", "xyz") is False

    def test_contains_list(self):
        assert _apply_operator(["a", "b", "c"], "contains", "b") is True
        assert _apply_operator(["a", "b", "c"], "contains", "z") is False

    def test_contains_non_iterable(self):
        assert _apply_operator(42, "contains", "2") is False

    def test_in_operator(self):
        assert _apply_operator("b", "in", ["a", "b", "c"]) is True
        assert _apply_operator("z", "in", ["a", "b", "c"]) is False

    def test_in_non_list(self):
        assert _apply_operator("a", "in", "not a list") is False

    def test_exists(self):
        assert _apply_operator("something", "exists", None) is True
        assert _apply_operator(None, "exists", None) is False
        assert _apply_operator(0, "exists", None) is True

    def test_not_exists(self):
        assert _apply_operator(None, "not_exists", None) is True
        assert _apply_operator("something", "not_exists", None) is False

    def test_unknown_operator_raises(self):
        with pytest.raises(ConditionError, match="Unknown operator"):
            _apply_operator("a", "bogus", "b")


class TestEvaluateCondition:
    def test_equals_pass(self, node_outputs):
        cond = {"source": "review.structured.verdict", "operator": "equals", "value": "PASS"}
        assert evaluate_condition(cond, node_outputs) is True

    def test_equals_fail(self, node_outputs):
        cond = {"source": "review.structured.verdict", "operator": "equals", "value": "FAIL"}
        assert evaluate_condition(cond, node_outputs) is False

    def test_status_check(self, node_outputs):
        cond = {"source": "planner.status", "operator": "equals", "value": "completed"}
        assert evaluate_condition(cond, node_outputs) is True

    def test_exists_check(self, node_outputs):
        cond = {"source": "failed_node.error", "operator": "exists"}
        assert evaluate_condition(cond, node_outputs) is True

    def test_default_operator_is_equals(self, node_outputs):
        cond = {"source": "review.structured.verdict", "value": "PASS"}
        assert evaluate_condition(cond, node_outputs) is True

    def test_missing_source_raises(self, node_outputs):
        with pytest.raises(ConditionError, match="missing 'source'"):
            evaluate_condition({"operator": "equals", "value": "x"}, node_outputs)

    def test_unresolvable_source_raises(self, node_outputs):
        with pytest.raises(ConditionError, match="Cannot resolve"):
            evaluate_condition(
                {"source": "nonexistent.output", "operator": "equals", "value": "x"},
                node_outputs,
            )


class TestStrict:
    """ROA-5: a loop condition whose structured field is missing fails, and says why."""

    def test_missing_field_raises_with_parse_error(self, node_outputs):
        node_outputs["check"] = NodeResult(
            status=Status.COMPLETED,
            output='{"verdict": FAIL oops',
            metadata={"structured_parse_error": "Expecting value: line 1 column 13 (char 12)"},
        )
        cond = {"source": "check.structured.verdict", "operator": "equals", "value": "FAIL"}
        with pytest.raises(ConditionError) as exc:
            evaluate_condition(cond, node_outputs, strict=True)
        assert str(exc.value) == (
            "field 'verdict' not found in structured output: "
            "Expecting value: line 1 column 13 (char 12)"
        )

    def test_empty_structured_without_parse_error(self, node_outputs):
        cond = {"source": "no_structured.structured.verdict", "operator": "equals", "value": "x"}
        with pytest.raises(
            ConditionError,
            match="field 'verdict' not found in structured output: structured output is empty",
        ):
            evaluate_condition(cond, node_outputs, strict=True)

    def test_key_missing(self, node_outputs):
        cond = {"source": "review.structured.nested.gone", "operator": "equals", "value": "x"}
        with pytest.raises(
            ConditionError, match="field 'nested.gone' not found in structured output: key missing",
        ):
            evaluate_condition(cond, node_outputs, strict=True)

    def test_present_field_and_explicit_null_pass(self, node_outputs):
        node_outputs["check"] = NodeResult(
            status=Status.COMPLETED, structured_output={"verdict": None},
        )
        assert evaluate_condition(
            {"source": "review.structured.verdict", "value": "PASS"}, node_outputs, strict=True,
        ) is True
        assert evaluate_condition(
            {"source": "check.structured.verdict", "value": "FAIL"}, node_outputs, strict=True,
        ) is False

    def test_exists_not_strict(self, node_outputs):
        cond = {"source": "no_structured.structured.verdict", "operator": "not_exists"}
        assert evaluate_condition(cond, node_outputs, strict=True) is True
        cond = {"source": "review.structured.gone", "operator": "exists"}
        assert evaluate_condition(cond, node_outputs, strict=True) is False

    def test_non_strict_unchanged(self, node_outputs):
        cond = {"source": "no_structured.structured.verdict", "operator": "equals", "value": "x"}
        assert evaluate_condition(cond, node_outputs) is False
