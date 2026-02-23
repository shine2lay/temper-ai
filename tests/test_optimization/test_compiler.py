"""Tests for DSPyCompiler."""

import sys
from unittest.mock import MagicMock, patch

import pytest

from temper_ai.optimization.dspy._schemas import (
    CompilationResult,
    PromptOptimizationConfig,
    TrainingExample,
)
from temper_ai.optimization.dspy.compiler import DSPyCompiler


def _make_examples(count=10):
    return [
        TrainingExample(
            input_text=f"input_{i}",
            output_text=f"output_{i}",
            metric_score=0.9,
            agent_name="researcher",
        )
        for i in range(count)
    ]


@pytest.fixture
def mock_dspy():
    """Mock dspy module for compilation tests."""
    dspy = MagicMock()

    # Mock Example class
    mock_example = MagicMock()
    mock_example.with_inputs.return_value = mock_example
    mock_example.input = "test_input"
    dspy.Example.return_value = mock_example

    # Mock LM
    dspy.LM.return_value = MagicMock()

    # Mock optimizer
    compiled_program = MagicMock()
    compiled_program.return_value = MagicMock(output="output_0")

    optimizer = MagicMock()
    optimizer.compile.return_value = compiled_program
    dspy.BootstrapFewShot.return_value = optimizer
    dspy.MIPROv2.return_value = optimizer
    dspy.COPRO.return_value = optimizer
    dspy.SIMBA.return_value = optimizer
    dspy.GEPA.return_value = optimizer

    with patch.dict(sys.modules, {"dspy": dspy}):
        yield dspy, compiled_program


class TestDSPyCompiler:

    def test_compile_returns_result(self, mock_dspy):
        dspy, _ = mock_dspy
        config = PromptOptimizationConfig(optimizer="bootstrap", max_demos=3)
        compiler = DSPyCompiler()
        result = compiler.compile(
            program=MagicMock(),
            training_examples=_make_examples(),
            config=config,
        )
        assert isinstance(result, CompilationResult)
        assert result.optimizer_type == "bootstrap"
        assert result.num_examples == 10

    def test_compile_with_mipro(self, mock_dspy):
        dspy, _ = mock_dspy
        config = PromptOptimizationConfig(optimizer="mipro")
        compiler = DSPyCompiler()
        result = compiler.compile(
            program=MagicMock(),
            training_examples=_make_examples(),
            config=config,
        )
        assert dspy.MIPROv2.called
        assert result.optimizer_type == "mipro"

    def test_compile_with_bootstrap(self, mock_dspy):
        dspy, _ = mock_dspy
        config = PromptOptimizationConfig(optimizer="bootstrap", max_demos=5)
        compiler = DSPyCompiler()
        compiler.compile(
            program=MagicMock(),
            training_examples=_make_examples(),
            config=config,
        )
        assert dspy.BootstrapFewShot.called
        assert dspy.BootstrapFewShot.call_args[1]["max_bootstrapped_demos"] == 5

    def test_split_data(self):
        compiler = DSPyCompiler()
        examples = list(range(10))
        train, val = compiler._split_data(examples)
        assert len(train) == 2  # 20% of 10
        assert len(val) == 8

    def test_split_data_minimum_one_train(self):
        compiler = DSPyCompiler()
        examples = list(range(2))
        train, val = compiler._split_data(examples)
        assert len(train) >= 1

    def test_generate_id(self):
        config = PromptOptimizationConfig(optimizer="bootstrap")
        program_id = DSPyCompiler._generate_id(config)
        assert program_id.startswith("prog_bootstrap_")
        assert len(program_id) > len("prog_bootstrap_")

    def test_default_metric(self):
        config = PromptOptimizationConfig()
        metric = DSPyCompiler._resolve_metric(config)
        example = MagicMock(output="hello")
        pred_match = MagicMock(output="hello")
        pred_no_match = MagicMock(output="world")
        assert metric(example, pred_match) is True
        assert metric(example, pred_no_match) is False

    def test_evaluate_empty_dataset(self):
        result = DSPyCompiler._evaluate(MagicMock(), [], lambda e, p: True)
        assert result is None

    def test_evaluate_with_data(self):
        program = MagicMock()
        program.return_value = MagicMock(output="correct")

        examples = [
            MagicMock(input="in1", output="correct"),
            MagicMock(input="in2", output="correct"),
        ]

        def metric(ex, pred, trace=None):
            return getattr(pred, "output", "") == getattr(ex, "output", "")

        score = DSPyCompiler._evaluate(program, examples, metric)
        assert score is not None
        assert 0.0 <= score <= 1.0

    def test_compile_returns_program_data(self, mock_dspy):
        config = PromptOptimizationConfig(max_demos=7)
        compiler = DSPyCompiler()
        result = compiler.compile(
            program=MagicMock(),
            training_examples=_make_examples(),
            config=config,
        )
        assert "instruction" in result.program_data
        assert "demos" in result.program_data
        assert isinstance(result.program_data["demos"], list)


class TestMetricDispatch:
    """Test _resolve_metric delegates to the metric registry."""

    def test_default_is_exact_match(self):
        from temper_ai.optimization.dspy.metrics import get_metric

        metric = get_metric("exact_match")
        example = MagicMock(output="hello")
        pred = MagicMock(output="hello")
        assert metric(example, pred)

    def test_exact_match_mismatch(self):
        from temper_ai.optimization.dspy.metrics import get_metric

        metric = get_metric("exact_match")
        example = MagicMock(output="hello")
        pred = MagicMock(output="world")
        assert not metric(example, pred)

    def test_contains_metric(self):
        from temper_ai.optimization.dspy.metrics import get_metric

        metric = get_metric("contains")
        example = MagicMock(output="world")
        pred = MagicMock(output="hello world")
        assert metric(example, pred)

    def test_fuzzy_metric_above_threshold(self):
        from temper_ai.optimization.dspy.metrics import get_metric

        metric = get_metric("fuzzy")
        example = MagicMock(output="the quick brown fox")
        pred = MagicMock(output="the quick brown dog")
        assert metric(example, pred)

    def test_fuzzy_metric_below_threshold(self):
        from temper_ai.optimization.dspy.metrics import get_metric

        metric = get_metric("fuzzy")
        example = MagicMock(output="hello world")
        pred = MagicMock(output="goodbye universe forever")
        assert not metric(example, pred)


class TestResolveMetric:
    """Test compiler._resolve_metric for GEPA auto-selection."""

    def test_gepa_auto_selects_gepa_feedback(self):
        config = PromptOptimizationConfig(
            optimizer="gepa",
            training_metric="exact_match",
        )
        metric = DSPyCompiler._resolve_metric(config)
        assert callable(metric)

    def test_gepa_respects_explicit_metric(self):
        config = PromptOptimizationConfig(
            optimizer="gepa",
            training_metric="fuzzy",
        )
        metric = DSPyCompiler._resolve_metric(config)
        # Should use fuzzy, not gepa_feedback
        example = MagicMock(output="a b c")
        pred = MagicMock(output="a b c")
        assert metric(example, pred) is True

    def test_metric_params_forwarded(self):
        config = PromptOptimizationConfig(
            training_metric="llm_judge",
            metric_params={"rubric": "Test rubric"},
        )
        metric = DSPyCompiler._resolve_metric(config)
        assert callable(metric)


class TestOptimizerDispatch:
    """Test that compile delegates to optimizer registry."""

    def test_copro_dispatched(self, mock_dspy):
        dspy, _ = mock_dspy
        config = PromptOptimizationConfig(optimizer="copro")
        compiler = DSPyCompiler()
        result = compiler.compile(
            program=MagicMock(),
            training_examples=_make_examples(),
            config=config,
        )
        assert dspy.COPRO.called
        assert result.optimizer_type == "copro"

    def test_simba_dispatched(self, mock_dspy):
        dspy, _ = mock_dspy
        config = PromptOptimizationConfig(optimizer="simba")
        compiler = DSPyCompiler()
        result = compiler.compile(
            program=MagicMock(),
            training_examples=_make_examples(),
            config=config,
        )
        assert dspy.SIMBA.called
        assert result.optimizer_type == "simba"

    def test_gepa_dispatched(self, mock_dspy):
        dspy, _ = mock_dspy
        # GEPA auto-selects gepa_feedback metric which needs submodule mocking
        mock_gepa_utils = MagicMock()
        mock_gepa_utils.ScoreWithFeedback = MagicMock(
            side_effect=lambda **kw: MagicMock(**kw),
        )
        mock_result = MagicMock()
        mock_result.score = "0.5"
        mock_result.feedback = ""
        dspy.ChainOfThought.return_value.return_value = mock_result

        with patch.dict(
            sys.modules,
            {
                "dspy.teleprompt": MagicMock(),
                "dspy.teleprompt.gepa": MagicMock(),
                "dspy.teleprompt.gepa.gepa_utils": mock_gepa_utils,
            },
        ):
            config = PromptOptimizationConfig(optimizer="gepa")
            compiler = DSPyCompiler()
            result = compiler.compile(
                program=MagicMock(),
                training_examples=_make_examples(),
                config=config,
            )
        assert dspy.GEPA.called
        assert result.optimizer_type == "gepa"
