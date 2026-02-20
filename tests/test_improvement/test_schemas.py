"""Tests for improvement module schemas."""

import pytest
from pydantic import ValidationError

from temper_ai.optimization._schemas import (
    CheckConfig,
    EvaluationResult,
    EvaluatorConfig,
    OptimizationConfig,
    OptimizationResult,
    PipelineStepConfig,
)


class TestCheckConfig:
    def test_defaults(self):
        c = CheckConfig(name="test_check")
        assert c.method == "programmatic"
        assert c.command is None
        assert c.timeout == 600  # noqa

    def test_llm_method(self):
        c = CheckConfig(name="q", method="llm", prompt="Is it good?")
        assert c.method == "llm"
        assert c.prompt == "Is it good?"

    def test_invalid_method(self):
        with pytest.raises(ValidationError):
            CheckConfig(name="bad", method="unknown")


class TestEvaluatorConfig:
    def test_defaults(self):
        e = EvaluatorConfig()
        assert e.type == "criteria"
        assert e.checks == []
        assert e.prompt is None

    def test_scored_with_rubric(self):
        e = EvaluatorConfig(type="scored", rubric="Rate quality 0-1")
        assert e.type == "scored"
        assert e.rubric == "Rate quality 0-1"

    def test_invalid_type(self):
        with pytest.raises(ValidationError):
            EvaluatorConfig(type="invalid_type")


class TestPipelineStepConfig:
    def test_defaults(self):
        p = PipelineStepConfig(evaluator="quality")
        assert p.optimizer == "refinement"
        assert p.max_iterations == 3  # noqa
        assert p.runs == 3  # noqa
        assert p.strategies == []

    def test_selection_optimizer(self):
        p = PipelineStepConfig(optimizer="selection", evaluator="q", runs=5)  # noqa
        assert p.optimizer == "selection"
        assert p.runs == 5  # noqa

    def test_invalid_optimizer(self):
        with pytest.raises(ValidationError):
            PipelineStepConfig(optimizer="bad", evaluator="q")


class TestOptimizationConfig:
    def test_empty_config(self):
        c = OptimizationConfig()
        assert c.enabled is True
        assert c.evaluators == {}
        assert c.pipeline == []

    def test_disabled(self):
        c = OptimizationConfig(enabled=False)
        assert c.enabled is False

    def test_full_config(self):
        c = OptimizationConfig(
            evaluators={"q": EvaluatorConfig(type="scored", rubric="test")},
            pipeline=[PipelineStepConfig(evaluator="q", optimizer="selection")],
        )
        assert len(c.evaluators) == 1
        assert len(c.pipeline) == 1


class TestEvaluationResult:
    def test_defaults(self):
        r = EvaluationResult(passed=True)
        assert r.score == 1.0
        assert r.details == {}

    def test_clamp_score_high(self):
        r = EvaluationResult(passed=True, score=1.5)
        assert r.score == 1.0

    def test_clamp_score_low(self):
        r = EvaluationResult(passed=False, score=-0.5)
        assert r.score == 0.0

    def test_with_details(self):
        r = EvaluationResult(passed=False, score=0.3, details={"reason": "bad"})
        assert r.details["reason"] == "bad"
        assert r.score == pytest.approx(0.3)


class TestOptimizationResult:
    def test_defaults(self):
        r = OptimizationResult(output={"x": 1})
        assert r.output == {"x": 1}
        assert r.iterations == 0
        assert r.improved is False

    def test_clamp(self):
        r = OptimizationResult(output={}, score=2.0)
        assert r.score == 1.0
