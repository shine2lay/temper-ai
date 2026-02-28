"""Tests for temper_ai/optimization/engine_constants.py."""

from temper_ai.optimization.engine_constants import (
    CHECK_METHOD_LLM,
    CHECK_METHOD_PROGRAMMATIC,
    DEFAULT_MAX_ITERATIONS,
    DEFAULT_OPTIMIZATION_TIMEOUT_SECONDS,
    DEFAULT_RUNS,
    EVALUATOR_COMPARATIVE,
    EVALUATOR_CRITERIA,
    EVALUATOR_HUMAN,
    EVALUATOR_SCORED,
    FIRST_BETTER,
    MAX_SCORE,
    MIN_SCORE,
    OPTIMIZER_PROMPT,
    OPTIMIZER_REFINEMENT,
    OPTIMIZER_SELECTION,
    OPTIMIZER_TUNING,
    SECOND_BETTER,
    TIE,
)


class TestScoreBounds:
    def test_min_score(self):
        assert MIN_SCORE == 0.0

    def test_max_score(self):
        assert MAX_SCORE == 1.0

    def test_min_less_than_max(self):
        assert MIN_SCORE < MAX_SCORE


class TestDefaultLimits:
    def test_max_iterations_positive(self):
        assert DEFAULT_MAX_ITERATIONS > 0

    def test_default_runs_positive(self):
        assert DEFAULT_RUNS > 0

    def test_timeout_positive(self):
        assert DEFAULT_OPTIMIZATION_TIMEOUT_SECONDS > 0


class TestComparisonOutcomes:
    def test_first_better(self):
        assert FIRST_BETTER == -1

    def test_tie(self):
        assert TIE == 0

    def test_second_better(self):
        assert SECOND_BETTER == 1

    def test_outcomes_are_ordered(self):
        assert FIRST_BETTER < TIE < SECOND_BETTER


class TestEvaluatorTypes:
    def test_criteria(self):
        assert EVALUATOR_CRITERIA == "criteria"

    def test_comparative(self):
        assert EVALUATOR_COMPARATIVE == "comparative"

    def test_scored(self):
        assert EVALUATOR_SCORED == "scored"

    def test_human(self):
        assert EVALUATOR_HUMAN == "human"

    def test_all_unique(self):
        values = [
            EVALUATOR_CRITERIA,
            EVALUATOR_COMPARATIVE,
            EVALUATOR_SCORED,
            EVALUATOR_HUMAN,
        ]
        assert len(values) == len(set(values))


class TestOptimizerTypes:
    def test_refinement(self):
        assert OPTIMIZER_REFINEMENT == "refinement"

    def test_selection(self):
        assert OPTIMIZER_SELECTION == "selection"

    def test_tuning(self):
        assert OPTIMIZER_TUNING == "tuning"

    def test_prompt(self):
        assert OPTIMIZER_PROMPT == "prompt"

    def test_all_unique(self):
        values = [
            OPTIMIZER_REFINEMENT,
            OPTIMIZER_SELECTION,
            OPTIMIZER_TUNING,
            OPTIMIZER_PROMPT,
        ]
        assert len(values) == len(set(values))


class TestCheckMethods:
    def test_programmatic(self):
        assert CHECK_METHOD_PROGRAMMATIC == "programmatic"

    def test_llm(self):
        assert CHECK_METHOD_LLM == "llm"
