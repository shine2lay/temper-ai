"""Tests for the evaluator/optimizer registry."""

import threading

import pytest

from src.improvement.evaluators.criteria import CriteriaEvaluator
from src.improvement.evaluators.scored import ScoredEvaluator
from src.improvement.optimizers.refinement import RefinementOptimizer
from src.improvement.optimizers.selection import SelectionOptimizer
from src.improvement.registry import OptimizationRegistry


class TestOptimizationRegistry:
    def setup_method(self):
        OptimizationRegistry.reset_for_testing()

    def teardown_method(self):
        OptimizationRegistry.reset_for_testing()

    def test_singleton(self):
        r1 = OptimizationRegistry.get_instance()
        r2 = OptimizationRegistry.get_instance()
        assert r1 is r2

    def test_reset_creates_new_instance(self):
        r1 = OptimizationRegistry.get_instance()
        OptimizationRegistry.reset_for_testing()
        r2 = OptimizationRegistry.get_instance()
        assert r1 is not r2

    def test_builtin_evaluators(self):
        r = OptimizationRegistry.get_instance()
        assert r.get_evaluator_class("criteria") is CriteriaEvaluator
        assert r.get_evaluator_class("scored") is ScoredEvaluator

    def test_builtin_optimizers(self):
        r = OptimizationRegistry.get_instance()
        assert r.get_optimizer_class("refinement") is RefinementOptimizer
        assert r.get_optimizer_class("selection") is SelectionOptimizer

    def test_unknown_evaluator_raises(self):
        r = OptimizationRegistry.get_instance()
        with pytest.raises(KeyError, match="Unknown evaluator"):
            r.get_evaluator_class("nonexistent")

    def test_unknown_optimizer_raises(self):
        r = OptimizationRegistry.get_instance()
        with pytest.raises(KeyError, match="Unknown optimizer"):
            r.get_optimizer_class("nonexistent")

    def test_register_custom_evaluator(self):
        r = OptimizationRegistry.get_instance()

        class CustomEval:
            pass

        r.register_evaluator("custom", CustomEval)
        assert r.get_evaluator_class("custom") is CustomEval

    def test_register_custom_optimizer(self):
        r = OptimizationRegistry.get_instance()

        class CustomOpt:
            pass

        r.register_optimizer("custom", CustomOpt)
        assert r.get_optimizer_class("custom") is CustomOpt

    def test_thread_safety(self):
        """Concurrent access to singleton returns same instance."""
        instances = []

        def get_reg():
            instances.append(OptimizationRegistry.get_instance())

        threads = [threading.Thread(target=get_reg) for _ in range(10)]  # noqa
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(instances) == 10  # noqa
        assert all(inst is instances[0] for inst in instances)
