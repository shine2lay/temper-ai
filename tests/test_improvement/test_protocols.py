"""Tests for improvement module protocols."""

from temper_ai.improvement.evaluators.comparative import ComparativeEvaluator
from temper_ai.improvement.evaluators.criteria import CriteriaEvaluator
from temper_ai.improvement.evaluators.human import HumanEvaluator
from temper_ai.improvement.evaluators.scored import ScoredEvaluator
from temper_ai.improvement.optimizers.refinement import RefinementOptimizer
from temper_ai.improvement.optimizers.selection import SelectionOptimizer
from temper_ai.improvement.optimizers.tuning import TuningOptimizer
from temper_ai.improvement.protocols import EvaluatorProtocol, OptimizerProtocol
from temper_ai.improvement._schemas import EvaluatorConfig


class TestEvaluatorProtocol:
    def test_criteria_implements(self):
        e = CriteriaEvaluator(config=EvaluatorConfig())
        assert isinstance(e, EvaluatorProtocol)

    def test_comparative_implements(self):
        e = ComparativeEvaluator(config=EvaluatorConfig())
        assert isinstance(e, EvaluatorProtocol)

    def test_scored_implements(self):
        e = ScoredEvaluator(config=EvaluatorConfig())
        assert isinstance(e, EvaluatorProtocol)

    def test_human_implements(self):
        e = HumanEvaluator()
        assert isinstance(e, EvaluatorProtocol)


class TestOptimizerProtocol:
    def test_refinement_implements(self):
        assert isinstance(RefinementOptimizer(), OptimizerProtocol)

    def test_selection_implements(self):
        assert isinstance(SelectionOptimizer(), OptimizerProtocol)

    def test_tuning_implements(self):
        assert isinstance(TuningOptimizer(), OptimizerProtocol)
