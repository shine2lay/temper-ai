"""Tests for agent/llm_agent.py — LLMAgent.run() pipeline."""

from unittest.mock import MagicMock, patch

import pytest

from temper_ai.agent.llm_agent import LLMAgent, _extract_structured_output, _truncate_input_data
from temper_ai.llm.models import LLMRunResult
from temper_ai.shared.types import ExecutionContext, Status


def _make_context(**overrides) -> ExecutionContext:
    """Build a minimal ExecutionContext with mocked infrastructure."""
    recorder = MagicMock()
    recorder.record = MagicMock(return_value="evt-123")

    mock_llm = MagicMock()
    tool_executor = MagicMock()
    tool_executor.get_tool = MagicMock(return_value=None)

    defaults = dict(
        run_id="run-1",
        workflow_name="test_wf",
        node_path="test_node",
        agent_name="test_agent",
        event_recorder=recorder,
        tool_executor=tool_executor,
        llm_providers={"openai": mock_llm},
    )
    defaults.update(overrides)
    return ExecutionContext(**defaults)


def _make_agent(config_overrides=None) -> LLMAgent:
    """Build an LLMAgent with sensible defaults."""
    config = {
        "name": "test_agent",
        "type": "llm",
        "provider": "openai",
        "model": "gpt-4o-mini",
        "system_prompt": "You are a test agent.",
        "task_template": "Do: {{ task }}",
    }
    if config_overrides:
        config.update(config_overrides)
    return LLMAgent(config)


class TestLLMAgentRun:
    @patch("temper_ai.agent.llm_agent.LLMService")
    def test_successful_run(self, MockLLMService):
        mock_service = MockLLMService.return_value
        mock_service.run.return_value = LLMRunResult(
            output="Done!", tokens=100, cost=0.01, iterations=1,
        )

        agent = _make_agent()
        ctx = _make_context()
        result = agent.run({"task": "hello"}, ctx)

        assert result.status == Status.COMPLETED
        assert result.output == "Done!"
        assert result.tokens.total_tokens == 100
        assert result.cost_usd == 0.01
        assert result.llm_calls == 1
        assert result.error is None

    @patch("temper_ai.agent.llm_agent.LLMService")
    def test_failed_run_returns_failed_status(self, MockLLMService):
        mock_service = MockLLMService.return_value
        mock_service.run.return_value = LLMRunResult(
            output="", error="Rate limit exceeded", tokens=0, iterations=1,
        )

        agent = _make_agent()
        ctx = _make_context()
        result = agent.run({"task": "hello"}, ctx)

        assert result.status == Status.FAILED
        assert result.error == "Rate limit exceeded"

    @patch("temper_ai.agent.llm_agent.LLMService")
    def test_exception_during_run(self, MockLLMService):
        mock_service = MockLLMService.return_value
        mock_service.run.side_effect = RuntimeError("Connection timeout")

        agent = _make_agent()
        ctx = _make_context()
        result = agent.run({"task": "hello"}, ctx)

        assert result.status == Status.FAILED
        assert "Connection timeout" in result.error
        assert result.duration_seconds >= 0

    @patch("temper_ai.agent.llm_agent.LLMService")
    def test_structured_output_extraction(self, MockLLMService):
        mock_service = MockLLMService.return_value
        mock_service.run.return_value = LLMRunResult(
            output='{"verdict": "PASS", "score": 95}',
            tokens=50, iterations=1,
        )

        agent = _make_agent()
        ctx = _make_context()
        result = agent.run({"task": "review"}, ctx)

        assert result.structured_output == {"verdict": "PASS", "score": 95}

    @patch("temper_ai.agent.llm_agent.LLMService")
    def test_records_agent_events(self, MockLLMService):
        mock_service = MockLLMService.return_value
        mock_service.run.return_value = LLMRunResult(
            output="ok", tokens=10, iterations=1,
        )

        agent = _make_agent()
        ctx = _make_context()
        agent.run({"task": "x"}, ctx)

        record = ctx.event_recorder.record
        # Should record AGENT_STARTED and AGENT_COMPLETED
        assert record.call_count >= 2
        event_types = [call.args[0].value for call in record.call_args_list]
        assert "agent.started" in event_types
        assert "agent.completed" in event_types

    @patch("temper_ai.agent.llm_agent.LLMService")
    def test_records_failed_event_on_exception(self, MockLLMService):
        mock_service = MockLLMService.return_value
        mock_service.run.side_effect = ValueError("bad")

        agent = _make_agent()
        ctx = _make_context()
        agent.run({"task": "x"}, ctx)

        record = ctx.event_recorder.record
        event_types = [call.args[0].value for call in record.call_args_list]
        assert "agent.failed" in event_types

    @patch("temper_ai.agent.llm_agent.LLMService")
    def test_passes_correct_provider(self, MockLLMService):
        mock_service = MockLLMService.return_value
        mock_service.run.return_value = LLMRunResult(output="ok", tokens=0, iterations=1)

        agent = _make_agent({"provider": "vllm"})
        mock_llm = MagicMock()
        ctx = _make_context(llm_providers={"vllm": mock_llm})
        agent.run({"task": "x"}, ctx)

        # LLMService was initialized with the correct provider
        MockLLMService.assert_called_once_with(provider=mock_llm, max_iterations=10, max_messages=50, total_timeout=300.0, max_context_tokens=120000)

    @patch("temper_ai.agent.llm_agent.LLMService")
    def test_tools_passed_to_llm_service(self, MockLLMService):
        mock_service = MockLLMService.return_value
        mock_service.run.return_value = LLMRunResult(output="ok", tokens=0, iterations=1)

        mock_tool = MagicMock()
        mock_tool.to_llm_schema.return_value = {"type": "function", "function": {"name": "bash"}}

        agent = _make_agent({"tools": ["bash"]})
        ctx = _make_context()
        ctx.tool_executor.get_tool.return_value = mock_tool

        agent.run({"task": "x"}, ctx)

        # LLMService.run was called with tool schemas
        call_kwargs = mock_service.run.call_args
        assert call_kwargs.kwargs.get("tools") or call_kwargs[1].get("tools")

    @patch("temper_ai.agent.llm_agent.LLMService")
    def test_tracks_usage_on_tool_executor(self, MockLLMService):
        mock_service = MockLLMService.return_value
        mock_service.run.return_value = LLMRunResult(
            output="ok", tokens=500, cost=0.05, iterations=1,
        )

        agent = _make_agent()
        ctx = _make_context()
        agent.run({"task": "x"}, ctx)

        ctx.tool_executor.track_usage.assert_called_once_with(
            cost_usd=0.05, tokens=500,
        )


class TestLLMAgentMemory:
    @patch("temper_ai.agent.llm_agent.LLMService")
    def test_recalls_memories_when_enabled(self, MockLLMService):
        mock_service = MockLLMService.return_value
        mock_service.run.return_value = LLMRunResult(output="ok", tokens=0, iterations=1)

        agent = _make_agent({
            "memory": {"enabled": True},
            "task_template": "Memories: {{ memories }}. Task: {{ task }}",
        })

        memory_service = MagicMock()
        memory_service.recall.return_value = ["user likes Python"]

        ctx = _make_context(memory_service=memory_service)
        agent.run({"task": "plan"}, ctx)

        memory_service.recall.assert_called_once()

    @patch("temper_ai.agent.llm_agent.LLMService")
    def test_no_recall_when_memory_disabled(self, MockLLMService):
        mock_service = MockLLMService.return_value
        mock_service.run.return_value = LLMRunResult(output="ok", tokens=0, iterations=1)

        agent = _make_agent()  # no memory config
        memory_service = MagicMock()
        ctx = _make_context(memory_service=memory_service)
        agent.run({"task": "plan"}, ctx)

        memory_service.recall.assert_not_called()

    @patch("temper_ai.agent.llm_agent.LLMService")
    def test_stores_memories_when_configured(self, MockLLMService):
        mock_service = MockLLMService.return_value
        mock_service.run.return_value = LLMRunResult(output="important finding", tokens=0, iterations=1)

        agent = _make_agent({
            "memory": {"enabled": True, "store_observations": True},
        })

        memory_service = MagicMock()
        memory_service.store.return_value = "mem-123"
        ctx = _make_context(memory_service=memory_service)

        result = agent.run({"task": "analyze"}, ctx)

        memory_service.store.assert_called_once()
        assert result.memories_formed == ["mem-123"]

    @patch("temper_ai.agent.llm_agent.LLMService")
    def test_memory_recall_failure_doesnt_crash(self, MockLLMService):
        mock_service = MockLLMService.return_value
        mock_service.run.return_value = LLMRunResult(output="ok", tokens=0, iterations=1)

        agent = _make_agent({"memory": {"enabled": True}})

        memory_service = MagicMock()
        memory_service.recall.side_effect = ConnectionError("mem0 down")
        ctx = _make_context(memory_service=memory_service)

        result = agent.run({"task": "plan"}, ctx)
        assert result.status == Status.COMPLETED  # graceful degradation


class TestLLMAgentValidation:
    def test_validate_config_ok(self):
        agent = _make_agent()
        assert agent.validate_config() == []

    def test_validate_config_no_prompt(self):
        agent = _make_agent({"system_prompt": None, "task_template": None})
        errors = agent.validate_config()
        assert any("system_prompt" in e or "task_template" in e for e in errors)

    def test_get_interface(self):
        agent = _make_agent({
            "inputs": {"task": "string"},
            "outputs": {"verdict": "string"},
        })
        interface = agent.get_interface()
        assert interface.inputs == {"task": "string"}
        assert interface.outputs == {"verdict": "string"}


class TestExtractStructuredOutput:
    def test_full_json(self):
        assert _extract_structured_output('{"a": 1}') == {"a": 1}

    def test_json_code_block(self):
        text = 'Here:\n```json\n{"a": 1}\n```\nDone'
        assert _extract_structured_output(text) == {"a": 1}

    def test_embedded_json(self):
        text = 'Result is {"verdict": "PASS"} as expected'
        assert _extract_structured_output(text) == {"verdict": "PASS"}

    def test_no_json(self):
        assert _extract_structured_output("no json here") is None

    def test_empty_string(self):
        assert _extract_structured_output("") is None

    def test_list_not_returned(self):
        """Only dicts are returned as structured output."""
        assert _extract_structured_output("[1, 2, 3]") is None


class TestTruncateInputData:
    def test_short_values_unchanged(self):
        data = {"task": "hello", "n": 5}
        assert _truncate_input_data(data) == data

    def test_long_strings_truncated(self):
        data = {"code": "x" * 1000}
        result = _truncate_input_data(data, max_value_len=100)
        assert len(result["code"]) < 1000
        assert "chars total" in result["code"]

    def test_internal_fields_stripped(self):
        data = {"task": "hello", "_strategy_context": "internal"}
        result = _truncate_input_data(data)
        assert "_strategy_context" not in result
        assert result["task"] == "hello"

    def test_nested_dicts(self):
        data = {"nested": {"long_val": "x" * 1000}}
        result = _truncate_input_data(data, max_value_len=100)
        assert "chars total" in result["nested"]["long_val"]

    def test_long_lists_capped(self):
        data = {"items": list(range(50))}
        result = _truncate_input_data(data)
        assert len(result["items"]) == 10
