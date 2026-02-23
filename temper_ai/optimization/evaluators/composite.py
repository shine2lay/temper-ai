"""Composite evaluator — blends evaluation score with free metrics."""

from __future__ import annotations

import logging
from typing import Any

from temper_ai.optimization._evaluation_schemas import AgentEvaluationConfig
from temper_ai.optimization._schemas import EvaluationResult, EvaluatorConfig
from temper_ai.optimization.engine_constants import MAX_SCORE, MIN_SCORE

logger = logging.getLogger(__name__)

# Default weights when not specified
DEFAULT_QUALITY_WEIGHT = 0.7
DEFAULT_COST_WEIGHT = 0.15
DEFAULT_LATENCY_WEIGHT = 0.15

# Normalization thresholds for free metrics
# Costs above this are scored 0; at or below scored 1
MAX_REASONABLE_COST_USD = 1.0
# Latency above this (seconds) is scored 0
MAX_REASONABLE_LATENCY_SECONDS = 60.0

# Zero threshold for metric comparisons (not a score bound)
_ZERO_METRIC = 0.0

_DEFAULT_PASS_THRESHOLD = 0.5


class CompositeEvaluator:
    """Blends an inner quality score with free metrics (cost, latency, tokens).

    Weights are specified in the AgentEvaluationConfig:
        - "quality": weight for the inner LLM/rubric score
        - "cost": weight for cost efficiency (lower is better)
        - "latency": weight for speed (lower is better)

    Missing weights default to 0.7/0.15/0.15.
    """

    def __init__(
        self,
        config: AgentEvaluationConfig,
        llm: Any | None = None,
    ) -> None:
        self._config = config
        self._llm = llm
        weights = config.weights or {}
        self._quality_weight = weights.get("quality", DEFAULT_QUALITY_WEIGHT)
        self._cost_weight = weights.get("cost", DEFAULT_COST_WEIGHT)
        self._latency_weight = weights.get("latency", DEFAULT_LATENCY_WEIGHT)

    def evaluate(
        self,
        output: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> EvaluationResult:
        """Score output by blending quality, cost, and latency."""
        quality_score = self._get_quality_score(output, context)
        metrics = (context or {}).get("metrics", {})
        cost_score = self._normalize_cost(metrics.get("cost_usd", 0.0))
        latency_score = self._normalize_latency(
            metrics.get("duration_seconds", 0.0),
        )

        blended = (
            self._quality_weight * quality_score
            + self._cost_weight * cost_score
            + self._latency_weight * latency_score
        )
        blended = max(MIN_SCORE, min(MAX_SCORE, blended))

        return EvaluationResult(
            passed=blended >= _DEFAULT_PASS_THRESHOLD,
            score=blended,
            details={
                "quality_score": quality_score,
                "cost_score": cost_score,
                "latency_score": latency_score,
                "weights": {
                    "quality": self._quality_weight,
                    "cost": self._cost_weight,
                    "latency": self._latency_weight,
                },
            },
        )

    def _get_quality_score(
        self,
        output: dict[str, Any],
        context: dict[str, Any] | None,
    ) -> float:
        """Get inner quality score via LLM rubric or default to 1.0."""
        if not self._llm or not self._config.rubric:
            return MAX_SCORE

        try:
            from temper_ai.optimization.evaluators.scored import ScoredEvaluator

            inner_config = EvaluatorConfig(
                type="scored",
                rubric=self._config.rubric,
            )
            evaluator = ScoredEvaluator(inner_config, llm=self._llm)
            result = evaluator.evaluate(output, context)
            return result.score
        except (AttributeError, TypeError, RuntimeError) as exc:
            logger.warning("Composite inner quality eval failed: %s", exc)
            return MAX_SCORE

    @staticmethod
    def _normalize_cost(cost_usd: float) -> float:
        """Convert cost to 0-1 score (lower cost = higher score)."""
        if cost_usd <= _ZERO_METRIC:
            return MAX_SCORE
        if cost_usd >= MAX_REASONABLE_COST_USD:
            return MIN_SCORE
        return MAX_SCORE - (cost_usd / MAX_REASONABLE_COST_USD)

    @staticmethod
    def _normalize_latency(duration_seconds: float) -> float:
        """Convert latency to 0-1 score (lower latency = higher score)."""
        if duration_seconds <= _ZERO_METRIC:
            return MAX_SCORE
        if duration_seconds >= MAX_REASONABLE_LATENCY_SECONDS:
            return MIN_SCORE
        return MAX_SCORE - (duration_seconds / MAX_REASONABLE_LATENCY_SECONDS)
