"""Tests for DSPyCompiler."""

import sys
from unittest.mock import MagicMock, patch

import pytest

from temper_ai.optimization._schemas import (
    CompilationResult,
    PromptOptimizationConfig,
    TrainingExample,
)
from temper_ai.optimization.compiler import DSPyCompiler


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
        metric = DSPyCompiler._get_metric(None)
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

        examples = [MagicMock(input="in1", output="correct"), MagicMock(input="in2", output="correct")]

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
