"""Tests for DSPyProgramBuilder."""

import sys
from unittest.mock import MagicMock, patch

import pytest

from temper_ai.optimization.dspy._schemas import PromptOptimizationConfig
from temper_ai.optimization.dspy.program_builder import (
    DSPyProgramBuilder,
    INTERNAL_TEMPLATE_VARS,
    TEMPLATE_VAR_PATTERN,
)


@pytest.fixture
def mock_dspy():
    """Mock dspy module."""
    dspy = MagicMock()
    dspy.Predict.return_value = MagicMock(name="PredictModule")
    dspy.ChainOfThought.return_value = MagicMock(name="CoTModule")
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
            result = builder.build_from_config(config)
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
            result = builder.build_from_config(config)
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
            result = builder.build_from_config(config)
        # Should use default "input" field
        sig_arg = mock_dspy.Predict.call_args[0][0]
        assert "input" in sig_arg

    def test_build_signature_format(self):
        sig = DSPyProgramBuilder._build_signature(
            MagicMock(), ["topic", "context"], ["analysis"],
        )
        assert sig == "topic, context -> analysis"
