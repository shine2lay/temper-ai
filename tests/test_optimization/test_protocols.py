"""Tests for improvement module protocols."""

from temper_ai.optimization._schemas import EvaluatorConfig
from temper_ai.optimization.evaluators.comparative import ComparativeEvaluator
from temper_ai.optimization.evaluators.criteria import CriteriaEvaluator
from temper_ai.optimization.evaluators.human import HumanEvaluator
from temper_ai.optimization.evaluators.scored import ScoredEvaluator
from temper_ai.optimization.optimizers.refinement import RefinementOptimizer
from temper_ai.optimization.optimizers.selection import SelectionOptimizer
from temper_ai.optimization.optimizers.tuning import TuningOptimizer
from temper_ai.optimization.protocols import EvaluatorProtocol, OptimizerProtocol


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
