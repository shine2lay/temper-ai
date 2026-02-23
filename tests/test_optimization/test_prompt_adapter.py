"""Tests for DSPyPromptAdapter."""

from unittest.mock import MagicMock

from temper_ai.optimization.dspy.constants import (
    EXAMPLES_HEADER,
    OPTIMIZATION_HEADER,
)
from temper_ai.optimization.dspy.prompt_adapter import DSPyPromptAdapter


def _make_store(program_data=None):
    """Create a mock store."""
    store = MagicMock()
    store.load_latest.return_value = program_data
    return store


class TestDSPyPromptAdapter:

    def test_no_program_returns_original(self):
        store = _make_store(None)
        adapter = DSPyPromptAdapter(store=store)
        result = adapter.augment_prompt("agent", "Original prompt")
        assert result == "Original prompt"

    def test_empty_program_data_returns_original(self):
        store = _make_store({"program_data": {}})
        adapter = DSPyPromptAdapter(store=store)
        result = adapter.augment_prompt("agent", "Original prompt")
        assert result == "Original prompt"

    def test_injects_instruction(self):
        store = _make_store(
            {
                "program_data": {
                    "instruction": "Be thorough and precise.",
                    "demos": [],
                }
            }
        )
        adapter = DSPyPromptAdapter(store=store)
        result = adapter.augment_prompt("agent", "Original prompt")
        assert "Original prompt" in result
        assert OPTIMIZATION_HEADER in result
        assert "Be thorough and precise." in result

    def test_injects_demos(self):
        store = _make_store(
            {
                "program_data": {
                    "instruction": "",
                    "demos": [
                        {"input": "AI safety", "output": "Analysis of AI safety"},
                        {"input": "ML ops", "output": "Analysis of ML ops"},
                    ],
                }
            }
        )
        adapter = DSPyPromptAdapter(store=store)
        result = adapter.augment_prompt("agent", "Original prompt")
        assert EXAMPLES_HEADER in result
        assert "Example 1" in result
        assert "Example 2" in result
        assert "AI safety" in result

    def test_limits_demos_to_max(self):
        demos = [{"input": f"in_{i}", "output": f"out_{i}"} for i in range(10)]
        store = _make_store({"program_data": {"instruction": "test", "demos": demos}})
        adapter = DSPyPromptAdapter(store=store)
        result = adapter.augment_prompt("agent", "Prompt", max_demos=2)
        assert "Example 1" in result
        assert "Example 2" in result
        assert "Example 3" not in result

    def test_instruction_and_demos_together(self):
        store = _make_store(
            {
                "program_data": {
                    "instruction": "Be concise.",
                    "demos": [{"input": "q1", "output": "a1"}],
                }
            }
        )
        adapter = DSPyPromptAdapter(store=store)
        result = adapter.augment_prompt("agent", "Original")
        assert "Original" in result
        assert "Be concise." in result
        assert "Example 1" in result

    def test_separator_present(self):
        store = _make_store({"program_data": {"instruction": "test", "demos": []}})
        adapter = DSPyPromptAdapter(store=store)
        result = adapter.augment_prompt("agent", "Original")
        assert "---" in result

    def test_format_demos_static(self):
        demos = [
            {"input": "in1", "output": "out1"},
            {"input": "in2", "output": "out2"},
        ]
        result = DSPyPromptAdapter._format_demos(demos, 2)
        assert "Example 1" in result
        assert "Example 2" in result
        assert "in1" in result
        assert "out2" in result

    def test_augment_prompt_calls_store(self):
        store = _make_store(None)
        adapter = DSPyPromptAdapter(store=store)
        adapter.augment_prompt("my_agent", "prompt text")
        store.load_latest.assert_called_once_with("my_agent")

    def test_augment_with_only_instruction_no_demos(self):
        store = _make_store(
            {
                "program_data": {
                    "instruction": "Focus on key points",
                }
            }
        )
        adapter = DSPyPromptAdapter(store=store)
        result = adapter.augment_prompt("agent", "Base prompt")
        assert "Focus on key points" in result
        assert EXAMPLES_HEADER not in result
