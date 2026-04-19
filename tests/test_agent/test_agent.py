"""Tests for agent module — base class, factory, and LLMAgent."""


import pytest

from temper_ai.agent import AGENT_TYPES, create_agent, register_agent_type
from temper_ai.agent.base import AgentABC
from temper_ai.agent.llm_agent import (
    LLMAgent,
    _extract_structured_output,
    _truncate_input_data,
)
from temper_ai.agent.script_agent import ScriptAgent
from temper_ai.shared.types import AgentResult, Status

# --- Factory ---

class TestCreateAgent:
    def test_creates_llm_agent(self):
        agent = create_agent({"name": "test", "type": "llm", "system_prompt": "hi"})
        assert isinstance(agent, LLMAgent)
        assert agent.name == "test"

    def test_creates_script_agent(self):
        agent = create_agent({"name": "test", "type": "script", "script_template": "echo hi"})
        assert isinstance(agent, ScriptAgent)

    def test_default_type_is_llm(self):
        agent = create_agent({"name": "test", "system_prompt": "hi"})
        assert isinstance(agent, LLMAgent)

    def test_unknown_type_raises(self):
        with pytest.raises(ValueError, match="Unknown agent type"):
            create_agent({"name": "test", "type": "nonexistent"})

    def test_register_custom_type(self):
        class CustomAgent(AgentABC):
            def run(self, input_data, context):
                return AgentResult(status=Status.COMPLETED, output="custom")

        register_agent_type("custom_test", CustomAgent)
        try:
            agent = create_agent({"name": "test", "type": "custom_test"})
            assert isinstance(agent, CustomAgent)
        finally:
            del AGENT_TYPES["custom_test"]


# --- LLMAgent ---

class TestLLMAgent:
    def test_init_defaults(self):
        agent = LLMAgent({"name": "test", "system_prompt": "hi"})
        assert agent.name == "test"
        assert agent.provider == "openai"
        assert agent.model == "gpt-4o-mini"
        assert agent.max_iterations == 10
        assert agent.token_budget == 8000

    def test_init_custom(self):
        agent = LLMAgent({
            "name": "custom",
            "provider": "anthropic",
            "model": "claude-sonnet",
            "max_iterations": 5,
            "token_budget": 4000,
        })
        assert agent.provider == "anthropic"
        assert agent.model == "claude-sonnet"
        assert agent.max_iterations == 5

    def test_validate_config_needs_prompt(self):
        agent = LLMAgent({"name": "test"})
        errors = agent.validate_config()
        assert any("system_prompt" in e or "task_template" in e for e in errors)

    def test_validate_config_ok(self):
        agent = LLMAgent({"name": "test", "system_prompt": "hi"})
        errors = agent.validate_config()
        assert errors == []

    def test_get_interface(self):
        agent = LLMAgent({
            "name": "test", "system_prompt": "hi",
            "inputs": {"task": "string"},
            "outputs": {"result": "dict"},
        })
        interface = agent.get_interface()
        assert interface.inputs == {"task": "string"}
        assert interface.outputs == {"result": "dict"}


# --- ScriptAgent ---

class TestScriptAgent:
    def test_validate_config_needs_template(self):
        agent = ScriptAgent({"name": "test"})
        errors = agent.validate_config()
        assert any("script_template" in e for e in errors)

    def test_validate_config_ok(self):
        agent = ScriptAgent({"name": "test", "script_template": "echo hi"})
        errors = agent.validate_config()
        assert errors == []


# --- Structured Output Extraction ---

class TestExtractStructuredOutput:
    def test_full_json(self):
        result = _extract_structured_output('{"verdict": "PASS", "issues": []}')
        assert result == {"verdict": "PASS", "issues": []}

    def test_json_in_code_block(self):
        text = 'Here is the result:\n```json\n{"verdict": "PASS"}\n```\nDone.'
        result = _extract_structured_output(text)
        assert result == {"verdict": "PASS"}

    def test_json_embedded_in_text(self):
        text = 'Analysis complete. {"score": 0.95, "label": "good"} End.'
        result = _extract_structured_output(text)
        assert result["score"] == 0.95

    def test_no_json(self):
        result = _extract_structured_output("Just plain text, no JSON here.")
        assert result is None

    def test_empty_string(self):
        assert _extract_structured_output("") is None

    def test_none(self):
        assert _extract_structured_output(None) is None

    def test_array_not_extracted(self):
        # We only extract dicts, not arrays
        result = _extract_structured_output('[1, 2, 3]')
        assert result is None


# --- Input Data Truncation ---

class TestTruncateInputData:
    def test_short_values_unchanged(self):
        data = {"task": "short", "num": 42}
        assert _truncate_input_data(data) == data

    def test_long_strings_truncated(self):
        data = {"task": "x" * 1000}
        result = _truncate_input_data(data, max_value_len=100)
        assert len(result["task"]) < 200
        assert "chars total" in result["task"]

    def test_internal_fields_stripped(self):
        data = {"task": "hello", "_strategy_context": "internal stuff"}
        result = _truncate_input_data(data)
        assert "_strategy_context" not in result
        assert "task" in result

    def test_nested_dicts(self):
        data = {"outer": {"inner": "x" * 1000}}
        result = _truncate_input_data(data, max_value_len=100)
        assert "chars total" in result["outer"]["inner"]

    def test_long_lists_trimmed(self):
        data = {"items": list(range(50))}
        result = _truncate_input_data(data)
        assert len(result["items"]) == 10
