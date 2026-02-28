"""Tests for DSPyProgramBuilder."""

import sys
from unittest.mock import MagicMock, patch

import pytest

from temper_ai.optimization.dspy._schemas import PromptOptimizationConfig
from temper_ai.optimization.dspy.program_builder import (
    DSPyProgramBuilder,
)


class _MockSignature:
    """Stub base class for dspy.Signature so type() subclassing works."""


@pytest.fixture
def mock_dspy():
    """Mock dspy module."""
    dspy = MagicMock()
    dspy.Predict.return_value = MagicMock(name="PredictModule")
    dspy.ChainOfThought.return_value = MagicMock(name="CoTModule")
    # Provide a real class so _build_class_signature can subclass it
    dspy.Signature = _MockSignature
    with patch.dict(sys.modules, {"dspy": dspy}):
        yield dspy


class TestDSPyProgramBuilder:

    def test_build_predict_module(self, mock_dspy):
        config = PromptOptimizationConfig(
            input_fields=["topic"],
            output_fields=["analysis"],
        )
        builder = DSPyProgramBuilder()
        with patch("temper_ai.optimization.dspy._helpers.ensure_dspy_available"):
            builder.build_from_config(config)
        mock_dspy.Predict.assert_called_once()
        sig_arg = mock_dspy.Predict.call_args[0][0]
        assert "topic" in sig_arg
        assert "analysis" in sig_arg

    def test_build_cot_module(self, mock_dspy):
        config = PromptOptimizationConfig(
            module_type="chain_of_thought",
            input_fields=["topic"],
            output_fields=["analysis"],
        )
        builder = DSPyProgramBuilder()
        with patch("temper_ai.optimization.dspy._helpers.ensure_dspy_available"):
            builder.build_from_config(config)
        mock_dspy.ChainOfThought.assert_called_once()
        sig_arg = mock_dspy.ChainOfThought.call_args[0][0]
        assert "topic" in sig_arg
        assert "analysis" in sig_arg

    def test_extract_fields_from_template(self):
        builder = DSPyProgramBuilder()
        fields = builder._extract_fields("Research {{ topic }} in {{ domain }}")
        assert fields == ["topic", "domain"]

    def test_extract_fields_filters_internal_vars(self):
        builder = DSPyProgramBuilder()
        template = "{{ topic }} {{ dialogue_context }} {{ memory_context }}"
        fields = builder._extract_fields(template)
        assert "topic" in fields
        assert "dialogue_context" not in fields
        assert "memory_context" not in fields

    def test_extract_fields_deduplicates(self):
        builder = DSPyProgramBuilder()
        fields = builder._extract_fields("{{ x }} and {{ x }} again")
        assert fields == ["x"]

    def test_extract_fields_none_template(self):
        builder = DSPyProgramBuilder()
        fields = builder._extract_fields(None)
        assert fields == []

    def test_default_input_field_when_empty(self, mock_dspy):
        config = PromptOptimizationConfig(
            input_fields=[],
            output_fields=["output"],
        )
        builder = DSPyProgramBuilder()
        with patch("temper_ai.optimization.dspy._helpers.ensure_dspy_available"):
            builder.build_from_config(config)
        # Should use default "input" field
        sig_arg = mock_dspy.Predict.call_args[0][0]
        assert "input" in sig_arg

    def test_build_signature_format(self):
        sig = DSPyProgramBuilder._build_signature(
            MagicMock(),
            ["topic", "context"],
            ["analysis"],
        )
        assert sig == "topic, context -> analysis"

    def test_module_type_react_dispatches_to_registry(self, mock_dspy):
        config = PromptOptimizationConfig(
            module_type="react",
            input_fields=["query"],
            output_fields=["answer"],
            module_params={"tools": [MagicMock()]},
        )
        builder = DSPyProgramBuilder()
        with patch("temper_ai.optimization.dspy._helpers.ensure_dspy_available"):
            builder.build_from_config(config)
        # ReAct requires class-based signature, so should auto-upgrade
        mock_dspy.ReAct.assert_called_once()

    def test_module_type_program_of_thought_dispatches(self, mock_dspy):
        config = PromptOptimizationConfig(
            module_type="program_of_thought",
            input_fields=["input"],
            output_fields=["output"],
            module_params={"max_iters": 5},
        )
        builder = DSPyProgramBuilder()
        with patch("temper_ai.optimization.dspy._helpers.ensure_dspy_available"):
            builder.build_from_config(config)
        mock_dspy.ProgramOfThought.assert_called_once()

    def test_module_type_best_of_n_wraps_base(self, mock_dspy):
        config = PromptOptimizationConfig(
            module_type="best_of_n",
            input_fields=["input"],
            output_fields=["output"],
            module_params={"N": 3, "threshold": 0.8},
        )
        builder = DSPyProgramBuilder()
        with patch("temper_ai.optimization.dspy._helpers.ensure_dspy_available"):
            builder.build_from_config(config)
        mock_dspy.Predict.assert_called_once()  # default base module
        mock_dspy.BestOfN.assert_called_once()

    def test_signature_style_class_creates_signature_subclass(self, mock_dspy):
        config = PromptOptimizationConfig(
            signature_style="class",
            input_fields=["topic"],
            output_fields=["analysis"],
            field_descriptions={
                "topic": "The research topic",
                "analysis": "Detailed analysis output",
            },
        )
        builder = DSPyProgramBuilder()
        with patch("temper_ai.optimization.dspy._helpers.ensure_dspy_available"):
            builder.build_from_config(config)
        # Should use class-based signature (calls InputField/OutputField)
        mock_dspy.InputField.assert_called_once()
        mock_dspy.OutputField.assert_called_once()

    def test_build_class_signature_creates_subclass(self):
        mock_dspy_mod = MagicMock()
        mock_dspy_mod.Signature = _MockSignature
        sig_cls = DSPyProgramBuilder._build_class_signature(
            mock_dspy_mod,
            ["topic"],
            ["answer"],
            {"topic": "The topic", "answer": "The answer"},
        )
        assert issubclass(sig_cls, _MockSignature)
        mock_dspy_mod.InputField.assert_called_with(desc="The topic")
        mock_dspy_mod.OutputField.assert_called_with(desc="The answer")
