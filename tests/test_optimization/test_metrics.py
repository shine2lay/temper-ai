"""Tests for temper_ai.optimization.dspy.metrics module."""

import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from temper_ai.optimization.dspy.metrics import (
    _contains_metric,
    _exact_match_metric,
    _fuzzy_metric,
    _parse_score,
    create_gepa_feedback_metric,
    create_llm_judge_metric,
    get_metric,
    list_metrics,
    register_metric,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _Ex:
    """Minimal example-like object."""

    def __init__(self, output: str = "", input: str = "") -> None:
        self.output = output
        self.input = input


class _Pred:
    """Minimal prediction-like object."""

    def __init__(self, output: str = "") -> None:
        self.output = output


# ---------------------------------------------------------------------------
# _exact_match_metric
# ---------------------------------------------------------------------------


class TestExactMatchMetric:
    def test_match_returns_true(self) -> None:
        assert _exact_match_metric(_Ex("hello"), _Pred("hello")) is True

    def test_mismatch_returns_false(self) -> None:
        assert _exact_match_metric(_Ex("hello"), _Pred("world")) is False

    def test_empty_strings_match(self) -> None:
        assert _exact_match_metric(_Ex(""), _Pred("")) is True

    def test_partial_is_mismatch(self) -> None:
        assert _exact_match_metric(_Ex("hello world"), _Pred("hello")) is False


# ---------------------------------------------------------------------------
# _contains_metric
# ---------------------------------------------------------------------------


class TestContainsMetric:
    def test_substring_returns_true(self) -> None:
        assert _contains_metric(_Ex("ell"), _Pred("hello world")) is True

    def test_full_match_returns_true(self) -> None:
        assert _contains_metric(_Ex("hello"), _Pred("hello")) is True

    def test_not_contained_returns_false(self) -> None:
        assert _contains_metric(_Ex("xyz"), _Pred("hello")) is False

    def test_empty_expected_in_any_string(self) -> None:
        assert _contains_metric(_Ex(""), _Pred("anything")) is True


# ---------------------------------------------------------------------------
# _fuzzy_metric
# ---------------------------------------------------------------------------


class TestFuzzyMetric:
    def test_identical_returns_true(self) -> None:
        assert _fuzzy_metric(_Ex("quick brown fox"), _Pred("quick brown fox")) is True

    def test_full_mismatch_returns_false(self) -> None:
        assert _fuzzy_metric(_Ex("cat sat mat"), _Pred("dog ran far")) is False

    def test_partial_overlap_above_threshold(self) -> None:
        # "a b c" vs "a b d" → 2 overlap / 4 union = 0.5 >= 0.5
        assert _fuzzy_metric(_Ex("a b c"), _Pred("a b d")) is True

    def test_empty_expected_empty_actual_true(self) -> None:
        assert _fuzzy_metric(_Ex(""), _Pred("")) is True

    def test_empty_expected_nonempty_actual_false(self) -> None:
        assert _fuzzy_metric(_Ex(""), _Pred("something")) is False


# ---------------------------------------------------------------------------
# _parse_score
# ---------------------------------------------------------------------------


class TestParseScore:
    def test_valid_float_returned(self) -> None:
        assert _parse_score(0.5) == pytest.approx(0.5)

    def test_string_float_parsed(self) -> None:
        assert _parse_score("0.7") == pytest.approx(0.7)

    def test_garbage_returns_zero(self) -> None:
        assert _parse_score("abc") == pytest.approx(0.0)

    def test_above_max_clamped_to_one(self) -> None:
        assert _parse_score(1.5) == pytest.approx(1.0)

    def test_below_min_clamped_to_zero(self) -> None:
        assert _parse_score(-0.3) == pytest.approx(0.0)

    def test_boundary_zero(self) -> None:
        assert _parse_score(0.0) == pytest.approx(0.0)

    def test_boundary_one(self) -> None:
        assert _parse_score(1.0) == pytest.approx(1.0)

    def test_none_returns_zero(self) -> None:
        assert _parse_score(None) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# get_metric dispatch
# ---------------------------------------------------------------------------


class TestGetMetricDispatch:
    def test_exact_match_returns_callable(self) -> None:
        fn = get_metric("exact_match")
        assert callable(fn)

    def test_contains_returns_callable(self) -> None:
        fn = get_metric("contains")
        assert callable(fn)

    def test_fuzzy_returns_callable(self) -> None:
        fn = get_metric("fuzzy")
        assert callable(fn)

    def test_llm_judge_returns_callable(self) -> None:
        fn = get_metric("llm_judge")
        assert callable(fn)

    def test_gepa_feedback_returns_callable(self) -> None:
        fn = get_metric("gepa_feedback")
        assert callable(fn)

    def test_unknown_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="unknown_metric"):
            get_metric("unknown_metric")


# ---------------------------------------------------------------------------
# register_metric
# ---------------------------------------------------------------------------


class TestRegisterMetric:
    def test_custom_metric_registered_and_retrieved(self) -> None:
        def _my_factory(**kw: Any) -> Any:
            def _fn(example: Any, prediction: Any, trace: Any = None) -> bool:
                return True

            return _fn

        register_metric("custom_always_true", _my_factory)
        fn = get_metric("custom_always_true")
        assert callable(fn)
        assert fn(_Ex("x"), _Pred("y")) is True

    def test_registered_metric_appears_in_list(self) -> None:
        register_metric("custom_for_list_test", lambda **kw: _exact_match_metric)
        assert "custom_for_list_test" in list_metrics()


# ---------------------------------------------------------------------------
# list_metrics
# ---------------------------------------------------------------------------


class TestListMetrics:
    def test_returns_sorted_list(self) -> None:
        metrics = list_metrics()
        assert metrics == sorted(metrics)

    def test_all_five_builtins_present(self) -> None:
        metrics = list_metrics()
        for name in ("exact_match", "contains", "fuzzy", "llm_judge", "gepa_feedback"):
            assert name in metrics


# ---------------------------------------------------------------------------
# create_llm_judge_metric with mocked dspy
# ---------------------------------------------------------------------------


class TestLLMJudgeMetric:
    def test_returns_float_from_mocked_dspy(self) -> None:
        mock_dspy = MagicMock()
        mock_result = MagicMock()
        mock_result.score = "0.8"
        mock_dspy.ChainOfThought.return_value.return_value = mock_result

        with patch.dict(sys.modules, {"dspy": mock_dspy}):
            fn = create_llm_judge_metric()
            score = fn(_Ex("expected", "input"), _Pred("actual"))

        assert isinstance(score, float)
        assert score == pytest.approx(0.8)

    def test_accepts_rubric_kwarg(self) -> None:
        mock_dspy = MagicMock()
        mock_result = MagicMock()
        mock_result.score = "0.5"
        mock_dspy.ChainOfThought.return_value.return_value = mock_result

        with patch.dict(sys.modules, {"dspy": mock_dspy}):
            fn = create_llm_judge_metric(rubric="My custom rubric.")
            score = fn(_Ex("x"), _Pred("x"))

        assert isinstance(score, float)

    def test_garbage_score_returns_zero(self) -> None:
        mock_dspy = MagicMock()
        mock_result = MagicMock()
        mock_result.score = "not-a-number"
        mock_dspy.ChainOfThought.return_value.return_value = mock_result

        with patch.dict(sys.modules, {"dspy": mock_dspy}):
            fn = create_llm_judge_metric()
            score = fn(_Ex("x"), _Pred("y"))

        assert score == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# create_gepa_feedback_metric with mocked dspy
# ---------------------------------------------------------------------------


class TestGepaFeedbackMetric:
    def test_returns_score_with_feedback(self) -> None:
        mock_score_obj = MagicMock()
        mock_score_obj.score = 0.9
        mock_score_obj.feedback = "Looks good."

        mock_gepa_utils = MagicMock()

        def _fake_score_with_feedback(**kw: Any) -> Any:
            obj = MagicMock()
            obj.score = kw.get("score", 0.0)
            obj.feedback = kw.get("feedback", "")
            return obj

        mock_gepa_utils.ScoreWithFeedback.side_effect = _fake_score_with_feedback

        mock_result = MagicMock()
        mock_result.score = "0.9"
        mock_result.feedback = "Looks good."

        mock_dspy = MagicMock()
        mock_dspy.ChainOfThought.return_value.return_value = mock_result

        with patch.dict(
            sys.modules,
            {
                "dspy": mock_dspy,
                "dspy.teleprompt": MagicMock(),
                "dspy.teleprompt.gepa": MagicMock(),
                "dspy.teleprompt.gepa.gepa_utils": mock_gepa_utils,
            },
        ):
            fn = create_gepa_feedback_metric()
            result = fn(
                _Ex("expected", "input"),
                _Pred("actual"),
                trace=None,
                _pred_name=None,
                _pred_trace=None,
            )

        assert hasattr(result, "score")
        assert hasattr(result, "feedback")
        assert result.score == pytest.approx(0.9)

    def test_accepts_rubric_kwarg(self) -> None:
        mock_gepa_utils = MagicMock()

        def _fake_score_with_feedback(**kw: Any) -> Any:
            obj = MagicMock()
            obj.score = kw.get("score", 0.0)
            obj.feedback = kw.get("feedback", "")
            return obj

        mock_gepa_utils.ScoreWithFeedback.side_effect = _fake_score_with_feedback

        mock_result = MagicMock()
        mock_result.score = "0.5"
        mock_result.feedback = ""

        mock_dspy = MagicMock()
        mock_dspy.ChainOfThought.return_value.return_value = mock_result

        with patch.dict(
            sys.modules,
            {
                "dspy": mock_dspy,
                "dspy.teleprompt": MagicMock(),
                "dspy.teleprompt.gepa": MagicMock(),
                "dspy.teleprompt.gepa.gepa_utils": mock_gepa_utils,
            },
        ):
            fn = create_gepa_feedback_metric(rubric="Custom rubric.")
            result = fn(_Ex("e"), _Pred("a"))

        assert hasattr(result, "score")
