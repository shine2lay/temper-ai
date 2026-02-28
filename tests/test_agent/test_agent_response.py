"""Tests for AgentResponse and ToolCallRecord in temper_ai.agent.models.response."""

import pytest

from temper_ai.agent.models.response import AgentResponse, ToolCallRecord
from temper_ai.agent.utils.constants import (
    BASE_CONFIDENCE,
    MIN_OUTPUT_LENGTH,
    MIN_REASONING_LENGTH,
    REASONING_BONUS,
    TOOL_FAILURE_MAJOR_PENALTY,
    TOOL_FAILURE_MINOR_PENALTY,
)
from temper_ai.shared.constants.probabilities import CONFIDENCE_LOW

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_tool_call(success: bool = True) -> ToolCallRecord:
    return ToolCallRecord(
        tool_name="test_tool",
        arguments={"key": "value"},
        result="result text",
        success=success,
        duration_seconds=0.1,
    )


SHORT_OUTPUT = "short"  # 5 chars — below MIN_OUTPUT_LENGTH (10)
LONG_OUTPUT = "long output!"  # 12 chars — above MIN_OUTPUT_LENGTH (10)
SHORT_REASONING = "too short"  # 9 chars — below MIN_REASONING_LENGTH (20)
EXACTLY_MIN_REASONING = (
    "a" * MIN_REASONING_LENGTH
)  # exactly 20 — condition is >, so no bonus
LONG_REASONING = "a" * (MIN_REASONING_LENGTH + 1)  # 21 chars — qualifies for bonus


# ---------------------------------------------------------------------------
# ToolCallRecord
# ---------------------------------------------------------------------------


class TestToolCallRecord:
    def test_create_with_all_fields(self):
        record = ToolCallRecord(
            tool_name="tool",
            arguments={},
            result="ok",
            success=True,
            duration_seconds=0.0,
        )
        assert record["tool_name"] == "tool"
        assert record["arguments"] == {}
        assert record["result"] == "ok"
        assert record["success"] is True
        assert record["duration_seconds"] == 0.0

    def test_create_with_failure(self):
        record = make_tool_call(success=False)
        assert record["tool_name"] == "test_tool"
        assert record["success"] is False
        assert record["duration_seconds"] == 0.1

    def test_is_plain_dict_at_runtime(self):
        # TypedDict produces a regular dict at runtime
        record = make_tool_call()
        assert isinstance(record, dict)
        assert record.get("success") is True


# ---------------------------------------------------------------------------
# AgentResponse — creation and defaults
# ---------------------------------------------------------------------------


class TestAgentResponseCreation:
    def test_minimal_creation_sets_defaults(self):
        resp = AgentResponse(output=LONG_OUTPUT)
        assert resp.output == LONG_OUTPUT
        assert resp.reasoning is None
        assert resp.tool_calls == []
        assert resp.metadata == {}
        assert resp.tokens == 0
        assert resp.estimated_cost_usd == 0.0
        assert resp.latency_seconds == 0.0
        assert resp.error is None

    def test_confidence_auto_calculated_when_not_provided(self):
        resp = AgentResponse(output=LONG_OUTPUT)
        assert resp.confidence is not None

    def test_explicit_confidence_preserved(self):
        resp = AgentResponse(output=LONG_OUTPUT, confidence=0.42)
        assert resp.confidence == 0.42

    def test_full_creation_stores_all_fields(self):
        tc = make_tool_call()
        resp = AgentResponse(
            output=LONG_OUTPUT,
            reasoning=LONG_REASONING,
            tool_calls=[tc],
            metadata={"key": "val"},
            tokens=100,
            estimated_cost_usd=0.01,
            latency_seconds=2.5,
            error=None,
        )
        assert resp.tokens == 100
        assert resp.estimated_cost_usd == 0.01
        assert resp.latency_seconds == 2.5
        assert len(resp.tool_calls) == 1

    def test_error_response_auto_assigns_confidence_low(self):
        resp = AgentResponse(output="", error="Something went wrong")
        assert resp.error == "Something went wrong"
        assert resp.confidence == CONFIDENCE_LOW


# ---------------------------------------------------------------------------
# _tool_failure_penalty (static method — tested directly)
# ---------------------------------------------------------------------------


class TestToolFailurePenalty:
    def test_empty_list_returns_zero(self):
        assert AgentResponse._tool_failure_penalty([]) == 0.0

    def test_all_successful_returns_zero(self):
        calls = [make_tool_call(success=True) for _ in range(3)]
        assert AgentResponse._tool_failure_penalty(calls) == 0.0

    def test_single_success_rate_one_returns_zero(self):
        assert AgentResponse._tool_failure_penalty([make_tool_call(True)]) == 0.0

    def test_all_failed_returns_major_penalty(self):
        # 0/1 = 0.0 rate < PROB_MEDIUM → MAJOR
        calls = [make_tool_call(success=False)]
        assert AgentResponse._tool_failure_penalty(calls) == TOOL_FAILURE_MAJOR_PENALTY

    def test_rate_below_prob_medium_major_penalty(self):
        # 1/4 = 0.25 < 0.5 → MAJOR
        calls = [make_tool_call(True)] + [make_tool_call(False)] * 3
        assert AgentResponse._tool_failure_penalty(calls) == TOOL_FAILURE_MAJOR_PENALTY

    def test_rate_zero_multiple_failures_major_penalty(self):
        # 0/2 = 0.0 < 0.5 → MAJOR
        calls = [make_tool_call(False), make_tool_call(False)]
        assert AgentResponse._tool_failure_penalty(calls) == TOOL_FAILURE_MAJOR_PENALTY

    def test_rate_exactly_prob_medium_minor_penalty(self):
        # 1/2 = 0.5, NOT < 0.5, but < 1.0 → MINOR
        calls = [make_tool_call(True), make_tool_call(False)]
        assert AgentResponse._tool_failure_penalty(calls) == TOOL_FAILURE_MINOR_PENALTY

    def test_rate_above_prob_medium_below_one_minor_penalty(self):
        # 3/4 = 0.75, NOT < 0.5, but < 1.0 → MINOR
        calls = [make_tool_call(True)] * 3 + [make_tool_call(False)]
        assert AgentResponse._tool_failure_penalty(calls) == TOOL_FAILURE_MINOR_PENALTY


# ---------------------------------------------------------------------------
# _calculate_confidence (exercised via __post_init__)
# ---------------------------------------------------------------------------


class TestCalculateConfidence:
    def test_error_returns_confidence_low(self):
        resp = AgentResponse(output=LONG_OUTPUT, error="oops")
        assert resp.confidence == CONFIDENCE_LOW

    def test_error_overrides_output_and_reasoning(self):
        resp = AgentResponse(output=LONG_OUTPUT, reasoning=LONG_REASONING, error="err")
        assert resp.confidence == CONFIDENCE_LOW

    def test_good_output_no_reasoning_no_tools_returns_base(self):
        resp = AgentResponse(output=LONG_OUTPUT)
        assert resp.confidence == BASE_CONFIDENCE

    def test_short_output_reduces_confidence_by_confidence_low(self):
        resp = AgentResponse(output=SHORT_OUTPUT)
        expected = BASE_CONFIDENCE - CONFIDENCE_LOW
        assert resp.confidence == pytest.approx(expected)

    def test_output_at_exactly_min_length_not_penalised(self):
        # Condition is <MIN_OUTPUT_LENGTH, so exactly 10 chars → no penalty
        resp = AgentResponse(output="a" * MIN_OUTPUT_LENGTH)
        assert resp.confidence == BASE_CONFIDENCE

    def test_output_one_below_min_length_is_penalised(self):
        resp = AgentResponse(output="a" * (MIN_OUTPUT_LENGTH - 1))
        expected = BASE_CONFIDENCE - CONFIDENCE_LOW
        assert resp.confidence == pytest.approx(expected)

    def test_long_reasoning_adds_bonus_capped_at_base(self):
        # 1.0 + 0.1 = 1.1 → capped at BASE_CONFIDENCE (1.0)
        resp = AgentResponse(output=LONG_OUTPUT, reasoning=LONG_REASONING)
        assert resp.confidence == BASE_CONFIDENCE

    def test_short_reasoning_adds_no_bonus(self):
        resp = AgentResponse(output=LONG_OUTPUT, reasoning=SHORT_REASONING)
        assert resp.confidence == BASE_CONFIDENCE

    def test_reasoning_at_exactly_min_length_adds_no_bonus(self):
        # Condition is > MIN_REASONING_LENGTH (not >=), so exactly 20 chars → no bonus
        resp = AgentResponse(output=LONG_OUTPUT, reasoning=EXACTLY_MIN_REASONING)
        assert resp.confidence == BASE_CONFIDENCE

    def test_reasoning_one_above_min_length_adds_bonus(self):
        # 21 chars > 20 → bonus, but capped at 1.0
        resp = AgentResponse(output=LONG_OUTPUT, reasoning=LONG_REASONING)
        assert resp.confidence == BASE_CONFIDENCE

    def test_confidence_never_exceeds_base(self):
        resp = AgentResponse(output=LONG_OUTPUT, reasoning=LONG_REASONING)
        assert resp.confidence <= BASE_CONFIDENCE

    def test_none_reasoning_adds_no_bonus(self):
        resp = AgentResponse(output=LONG_OUTPUT, reasoning=None)
        assert resp.confidence == BASE_CONFIDENCE

    def test_major_tool_failure_subtracts_major_penalty(self):
        # 0/1 rate → MAJOR
        resp = AgentResponse(output=LONG_OUTPUT, tool_calls=[make_tool_call(False)])
        expected = BASE_CONFIDENCE - TOOL_FAILURE_MAJOR_PENALTY
        assert resp.confidence == pytest.approx(expected)

    def test_minor_tool_failure_subtracts_minor_penalty(self):
        # 1/2 = 0.5 rate → MINOR
        calls = [make_tool_call(True), make_tool_call(False)]
        resp = AgentResponse(output=LONG_OUTPUT, tool_calls=calls)
        expected = BASE_CONFIDENCE - TOOL_FAILURE_MINOR_PENALTY
        assert resp.confidence == pytest.approx(expected)

    def test_all_tools_succeed_no_penalty(self):
        calls = [make_tool_call(True), make_tool_call(True)]
        resp = AgentResponse(output=LONG_OUTPUT, tool_calls=calls)
        assert resp.confidence == BASE_CONFIDENCE

    def test_short_output_plus_major_penalty(self):
        # 1.0 - 0.3 (short) - 0.2 (major) = 0.5
        calls = [make_tool_call(False)]
        resp = AgentResponse(output=SHORT_OUTPUT, tool_calls=calls)
        expected = BASE_CONFIDENCE - CONFIDENCE_LOW - TOOL_FAILURE_MAJOR_PENALTY
        assert resp.confidence == pytest.approx(expected)

    def test_short_output_plus_long_reasoning_plus_major_penalty(self):
        # 1.0 - 0.3 (short) = 0.7; +0.1 (reasoning) → min(1.0, 0.8) = 0.8; -0.2 (major) = 0.6
        calls = [make_tool_call(False)]
        resp = AgentResponse(
            output=SHORT_OUTPUT, reasoning=LONG_REASONING, tool_calls=calls
        )
        after_short = BASE_CONFIDENCE - CONFIDENCE_LOW
        after_reasoning = min(BASE_CONFIDENCE, after_short + REASONING_BONUS)
        expected = after_reasoning - TOOL_FAILURE_MAJOR_PENALTY
        assert resp.confidence == pytest.approx(expected)

    def test_confidence_never_below_zero(self):
        # Even in worst-case combination confidence is clamped to ≥ 0
        calls = [make_tool_call(False)]
        resp = AgentResponse(output=SHORT_OUTPUT, tool_calls=calls)
        assert resp.confidence >= 0.0

    def test_whitespace_only_output_treated_as_short(self):
        # "   ".strip() = "" → len 0 < MIN_OUTPUT_LENGTH → penalised
        resp = AgentResponse(output="   ")
        expected = BASE_CONFIDENCE - CONFIDENCE_LOW
        assert resp.confidence == pytest.approx(expected)

    def test_whitespace_only_reasoning_not_counted_as_long(self):
        # "   ".strip() = "" → len 0, not > MIN_REASONING_LENGTH → no bonus
        resp = AgentResponse(output=LONG_OUTPUT, reasoning="   ")
        assert resp.confidence == BASE_CONFIDENCE
