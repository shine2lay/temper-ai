"""Tests for CompositeEvaluator."""

from unittest.mock import MagicMock

import pytest

from temper_ai.optimization._evaluation_schemas import AgentEvaluationConfig
from temper_ai.optimization.evaluators.composite import (
    DEFAULT_COST_WEIGHT,
    DEFAULT_LATENCY_WEIGHT,
    DEFAULT_QUALITY_WEIGHT,
    MAX_REASONABLE_COST_USD,
    MAX_REASONABLE_LATENCY_SECONDS,
    CompositeEvaluator,
)


def _make_config(**kwargs):
    """Build a CompositeEvaluator-compatible config."""
    defaults = {"type": "composite"}
    defaults.update(kwargs)
    return AgentEvaluationConfig(**defaults)


class TestCompositeEvaluator:
    """Tests for CompositeEvaluator."""

    def test_default_weights(self):
        config = _make_config()
        evaluator = CompositeEvaluator(config)
        assert evaluator._quality_weight == DEFAULT_QUALITY_WEIGHT
        assert evaluator._cost_weight == DEFAULT_COST_WEIGHT
        assert evaluator._latency_weight == DEFAULT_LATENCY_WEIGHT

    def test_custom_weights(self):
        config = _make_config(weights={"quality": 0.5, "cost": 0.3, "latency": 0.2})
        evaluator = CompositeEvaluator(config)
        assert evaluator._quality_weight == 0.5
        assert evaluator._cost_weight == 0.3
        assert evaluator._latency_weight == 0.2

    def test_no_llm_quality_defaults_to_max(self):
        config = _make_config()
        evaluator = CompositeEvaluator(config, llm=None)

        result = evaluator.evaluate(
            {"output": "test"},
            context={"metrics": {"cost_usd": 0.0, "duration_seconds": 0.0}},
        )

        # All scores are 1.0: quality=1.0 (no LLM), cost=1.0 (free), latency=1.0 (instant)
        assert result.score == pytest.approx(1.0)
        assert result.passed is True

    def test_blend_with_free_metrics(self):
        config = _make_config(
            weights={"quality": 0.5, "cost": 0.25, "latency": 0.25},
        )
        evaluator = CompositeEvaluator(config, llm=None)

        result = evaluator.evaluate(
            {"output": "test"},
            context={
                "metrics": {
                    "cost_usd": 0.5,  # 50% of max → cost_score = 0.5
                    "duration_seconds": 30.0,  # 50% of max → latency_score = 0.5
                }
            },
        )

        # quality=1.0*0.5 + cost=0.5*0.25 + latency=0.5*0.25 = 0.5 + 0.125 + 0.125 = 0.75
        assert result.score == pytest.approx(0.75)
        assert result.passed is True

    def test_high_cost_low_score(self):
        config = _make_config(
            weights={"quality": 0.0, "cost": 1.0, "latency": 0.0},
        )
        evaluator = CompositeEvaluator(config, llm=None)

        result = evaluator.evaluate(
            {"output": "test"},
            context={"metrics": {"cost_usd": MAX_REASONABLE_COST_USD}},
        )

        assert result.score == pytest.approx(0.0)
        assert result.passed is False

    def test_high_latency_low_score(self):
        config = _make_config(
            weights={"quality": 0.0, "cost": 0.0, "latency": 1.0},
        )
        evaluator = CompositeEvaluator(config, llm=None)

        result = evaluator.evaluate(
            {"output": "test"},
            context={"metrics": {"duration_seconds": MAX_REASONABLE_LATENCY_SECONDS}},
        )

        assert result.score == pytest.approx(0.0)

    def test_with_llm_rubric(self):
        mock_llm = MagicMock()
        mock_llm.generate.return_value = "0.6"

        config = _make_config(
            rubric="Rate this output",
            weights={"quality": 1.0, "cost": 0.0, "latency": 0.0},
        )
        evaluator = CompositeEvaluator(config, llm=mock_llm)

        result = evaluator.evaluate(
            {"output": "test"},
            context={"metrics": {}},
        )

        assert result.score == pytest.approx(0.6)

    def test_details_include_breakdown(self):
        config = _make_config(
            weights={"quality": 0.6, "cost": 0.2, "latency": 0.2},
        )
        evaluator = CompositeEvaluator(config, llm=None)

        result = evaluator.evaluate(
            {"output": "test"},
            context={"metrics": {"cost_usd": 0.1, "duration_seconds": 6.0}},
        )

        assert "quality_score" in result.details
        assert "cost_score" in result.details
        assert "latency_score" in result.details
        assert "weights" in result.details
        assert result.details["weights"]["quality"] == 0.6

    def test_no_context_uses_defaults(self):
        config = _make_config()
        evaluator = CompositeEvaluator(config, llm=None)

        result = evaluator.evaluate({"output": "test"})

        # No metrics → cost=0, latency=0 → both scores=1.0
        assert result.score == pytest.approx(1.0)

    def test_llm_failure_returns_zero_quality(self):
        mock_llm = MagicMock()
        mock_llm.generate.side_effect = RuntimeError("LLM down")

        config = _make_config(
            rubric="Rate this",
            weights={"quality": 1.0, "cost": 0.0, "latency": 0.0},
        )
        evaluator = CompositeEvaluator(config, llm=mock_llm)

        result = evaluator.evaluate(
            {"output": "test"},
            context={"metrics": {}},
        )

        # ScoredEvaluator catches RuntimeError and returns score=0.0
        assert result.score == pytest.approx(0.0)


class TestNormalization:
    """Tests for cost/latency normalization helpers."""

    def test_normalize_cost_zero(self):
        assert CompositeEvaluator._normalize_cost(0.0) == 1.0

    def test_normalize_cost_max(self):
        assert CompositeEvaluator._normalize_cost(MAX_REASONABLE_COST_USD) == 0.0

    def test_normalize_cost_over_max(self):
        assert CompositeEvaluator._normalize_cost(MAX_REASONABLE_COST_USD * 2) == 0.0

    def test_normalize_cost_half(self):
        assert CompositeEvaluator._normalize_cost(
            MAX_REASONABLE_COST_USD / 2,
        ) == pytest.approx(0.5)

    def test_normalize_latency_zero(self):
        assert CompositeEvaluator._normalize_latency(0.0) == 1.0

    def test_normalize_latency_max(self):
        assert (
            CompositeEvaluator._normalize_latency(
                MAX_REASONABLE_LATENCY_SECONDS,
            )
            == 0.0
        )

    def test_normalize_latency_over_max(self):
        assert (
            CompositeEvaluator._normalize_latency(
                MAX_REASONABLE_LATENCY_SECONDS * 2,
            )
            == 0.0
        )

    def test_normalize_latency_half(self):
        assert CompositeEvaluator._normalize_latency(
            MAX_REASONABLE_LATENCY_SECONDS / 2,
        ) == pytest.approx(0.5)
