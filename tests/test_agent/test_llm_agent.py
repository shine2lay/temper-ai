"""Tests for agent/llm_agent.py — LLMAgent.run() pipeline."""

from unittest.mock import MagicMock, patch

import pytest

from temper_ai.agent.exceptions import ToolsNotRegisteredError
from temper_ai.agent.llm_agent import (
    DEFAULT_TOTAL_TIMEOUT,
    LLMAgent,
    _extract_structured_output,
    _truncate_input_data,
)
from temper_ai.llm.context import DEFAULT_CONTEXT_POLICY
from temper_ai.llm.fallback import FallbackTarget
from temper_ai.llm.models import LLMRunResult
from temper_ai.llm.service import (
    DEFAULT_MAX_CONTEXT_TOKENS,
    DEFAULT_MAX_MESSAGES,
    WRAP_UP_TURNS,
)
from temper_ai.observability import EventType
from temper_ai.shared.types import ExecutionContext, Status
from temper_ai.tools.base import BaseTool, ToolResult
from temper_ai.tools.executor import ALL_TOOLS, ToolExecutor


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

        # LLMService was initialized with the correct provider. The defaults are
        # asserted through the constants they come from, so changing a default
        # does not leave a stale literal failing here.
        MockLLMService.assert_called_once_with(
            provider=mock_llm,
            max_iterations=10,
            max_messages=DEFAULT_MAX_MESSAGES,
            total_timeout=DEFAULT_TOTAL_TIMEOUT,
            max_context_tokens=DEFAULT_MAX_CONTEXT_TOKENS,
            context_policy=DEFAULT_CONTEXT_POLICY,
            wrap_up_turns=WRAP_UP_TURNS,
            fallbacks=[],
            token=None,
            resolve_llm=ctx.get_llm,
        )

    @patch("temper_ai.agent.llm_agent.LLMService")
    def test_the_fallback_list_reaches_the_service(self, MockLLMService):
        mock_service = MockLLMService.return_value
        mock_service.run.return_value = LLMRunResult(output="ok", tokens=0, iterations=1)

        agent = _make_agent({"provider": "vllm", "fallback": [
            "qwen3-small", {"provider": "openai", "model": "gpt-5.6-luna"}]})
        ctx = _make_context(llm_providers={"vllm": MagicMock()})
        agent.run({"task": "x"}, ctx)

        assert MockLLMService.call_args.kwargs["fallbacks"] == [
            FallbackTarget(model="qwen3-small"),
            FallbackTarget(provider="openai", model="gpt-5.6-luna"),
        ]

    def test_a_malformed_fallback_list_fails_when_the_agent_is_loaded(self):
        """Not on the day a limit is finally hit."""
        with pytest.raises(ValueError, match=r"fallback\[0\] has unknown key\(s\) modle"):
            _make_agent({"provider": "vllm", "fallback": [{"modle": "x"}]})

    @patch("temper_ai.agent.llm_agent.LLMService")
    def test_the_agents_token_reaches_the_service(self, MockLLMService):
        MockLLMService.return_value.run.return_value = LLMRunResult(output="ok", tokens=0, iterations=1)
        agent = _make_agent({"provider": "anthropic", "token": "wai2shine",
                             "fallback": [{"token": "aungshine"}]})
        agent.run({"task": "x"}, _make_context(llm_providers={"anthropic": MagicMock()}))

        assert MockLLMService.call_args.kwargs["token"] == "wai2shine"
        assert MockLLMService.call_args.kwargs["fallbacks"] == [FallbackTarget(token="aungshine")]

    def test_a_credential_where_a_token_name_belongs_fails_when_the_agent_is_loaded(self):
        with pytest.raises(ValueError, match="not be the token itself") as err:
            _make_agent({"provider": "anthropic", "token": "sk-ant-oat01-secret"})
        assert "sk-ant-oat01-secret" not in str(err.value)

    @patch("temper_ai.agent.llm_agent.LLMService")
    def test_context_policy_is_the_agents_choice(self, MockLLMService):
        mock_service = MockLLMService.return_value
        mock_service.run.return_value = LLMRunResult(output="ok", tokens=0, iterations=1)

        agent = _make_agent({"provider": "vllm", "context_policy": "truncate"})
        ctx = _make_context(llm_providers={"vllm": MagicMock()})
        agent.run({"task": "x"}, ctx)

        assert MockLLMService.call_args.kwargs["context_policy"] == "truncate"

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


B012_ANSWER = '{"verdict": "FAIL", "notes": "total shows "−$120.00" not +$120"}'


def _recorded(ctx, event_type):
    return [c for c in ctx.event_recorder.record.call_args_list if c.args[0] == event_type]


class TestStructuredRepair:
    """ROA-5: an almost-JSON answer is repaired or retried, never dropped silently."""

    def test_b012_unescaped_quotes_repaired(self):
        parsed = _extract_structured_output(B012_ANSWER)
        assert parsed["verdict"] == "FAIL"
        assert parsed["notes"] == 'total shows "−$120.00" not +$120'

    def test_valid_json_escaped_quotes_untouched(self):
        assert _extract_structured_output(r'{"a": "say \"hi\""}') == {"a": 'say "hi"'}

    def test_trailing_comma_repaired(self):
        assert _extract_structured_output('{"a": 1,}') == {"a": 1}
        assert _extract_structured_output('{"a": [1, 2,],}') == {"a": [1, 2]}

    def test_trailing_comma_comma_in_string_kept(self):
        assert _extract_structured_output('{"a": "x, }", "b": 1,}') == {"a": "x, }", "b": 1}

    def test_quotes_and_trailing_comma_together(self):
        parsed = _extract_structured_output('{"notes": "shows "x" here", }')
        assert parsed == {"notes": 'shows "x" here'}

    @patch("temper_ai.agent.llm_agent.LLMService")
    def test_trailing_comma_repair_records_event_no_retry(self, MockLLMService):
        mock_service = MockLLMService.return_value
        mock_service.run.return_value = LLMRunResult(output='{"verdict": "pass",}', tokens=10, iterations=1)

        ctx = _make_context()
        result = _make_agent().run({"task": "check"}, ctx)

        assert result.structured_output == {"verdict": "pass"}
        assert mock_service.run.call_count == 1
        events = _recorded(ctx, EventType.AGENT_OUTPUT_REPAIRED)
        assert len(events) == 1
        assert events[0].kwargs["data"]["outcome"] == "repaired"
        assert "Expecting" in events[0].kwargs["data"]["parse_error"]
        assert _recorded(ctx, EventType.AGENT_OUTPUT_RETRY) == []

    def test_repair_in_code_block(self):
        text = f"Verdict:\n```json\n{B012_ANSWER}\n```\n"
        assert _extract_structured_output(text)["verdict"] == "FAIL"

    @patch("temper_ai.agent.llm_agent.LLMService")
    def test_repair_records_event(self, MockLLMService):
        mock_service = MockLLMService.return_value
        mock_service.run.return_value = LLMRunResult(output=B012_ANSWER, tokens=10, iterations=1)

        ctx = _make_context()
        result = _make_agent().run({"task": "check"}, ctx)

        assert result.structured_output["verdict"] == "FAIL"
        assert mock_service.run.call_count == 1
        events = _recorded(ctx, EventType.AGENT_OUTPUT_REPAIRED)
        assert len(events) == 1
        assert events[0].kwargs["status"] == "completed"
        assert "Expecting" in events[0].kwargs["data"]["parse_error"]
        assert events[0].kwargs["data"]["outcome"] == "repaired"

    @patch("temper_ai.agent.llm_agent.LLMService")
    def test_retry_turn_recovers(self, MockLLMService):
        mock_service = MockLLMService.return_value
        mock_service.run.side_effect = [
            LLMRunResult(output='{"verdict": FAIL oops', tokens=10, cost=0.01, iterations=1),
            LLMRunResult(output='{"verdict":"PASS"}', tokens=5, cost=0.02, iterations=1),
        ]

        ctx = _make_context()
        result = _make_agent().run({"task": "check"}, ctx)

        assert result.structured_output == {"verdict": "PASS"}
        assert result.output == '{"verdict": FAIL oops'
        assert mock_service.run.call_count == 2
        retry_msgs = mock_service.run.call_args_list[1].kwargs["messages"]
        assert retry_msgs[-2] == {"role": "assistant", "content": '{"verdict": FAIL oops'}
        assert retry_msgs[-1]["role"] == "user"
        assert retry_msgs[-1]["content"].startswith("Your last answer wasn't valid JSON: `Expecting value")
        assert retry_msgs[-1]["content"].endswith("Reply with only the corrected JSON.")
        assert mock_service.run.call_args_list[1].kwargs["tools"] is None
        # The retry's spend counts.
        assert result.tokens.total_tokens == 15
        assert result.cost_usd == pytest.approx(0.03)
        assert result.llm_calls == 2
        events = _recorded(ctx, EventType.AGENT_OUTPUT_RETRY)
        assert len(events) == 1
        assert events[0].kwargs["status"] == "completed"
        assert events[0].kwargs["data"]["parse_error"].startswith("Expecting value")
        assert events[0].kwargs["data"]["outcome"] == "retry_ok"

    @patch("temper_ai.agent.llm_agent.LLMService")
    def test_retry_failure_sets_metadata(self, MockLLMService):
        mock_service = MockLLMService.return_value
        mock_service.run.side_effect = [
            LLMRunResult(output='{"verdict": FAIL oops', tokens=10, iterations=1),
            LLMRunResult(output='{"verdict": still broken', tokens=5, iterations=1),
        ]

        ctx = _make_context()
        result = _make_agent().run({"task": "check"}, ctx)

        assert result.structured_output is None
        assert mock_service.run.call_count == 2
        assert result.metadata["structured_parse_error"].startswith("Expecting value")
        events = _recorded(ctx, EventType.AGENT_OUTPUT_RETRY)
        assert len(events) == 1
        assert events[0].kwargs["status"] == "failed"
        assert events[0].kwargs["data"]["outcome"] == "retry_failed"
        assert events[0].kwargs["data"]["parse_error"]

    @patch("temper_ai.agent.llm_agent.LLMService")
    def test_plain_text_no_retry(self, MockLLMService):
        mock_service = MockLLMService.return_value
        mock_service.run.return_value = LLMRunResult(output="no json here", tokens=10, iterations=1)

        ctx = _make_context()
        result = _make_agent().run({"task": "check"}, ctx)

        assert result.structured_output is None
        assert mock_service.run.call_count == 1
        assert result.metadata == {}
        assert not _recorded(ctx, EventType.AGENT_OUTPUT_RETRY)

    @patch("temper_ai.agent.llm_agent.LLMService")
    def test_failed_call_no_retry(self, MockLLMService):
        mock_service = MockLLMService.return_value
        mock_service.run.return_value = LLMRunResult(
            output='{"verdict": FAIL', error="Rate limit exceeded", iterations=1,
        )

        _make_agent().run({"task": "check"}, _make_context())

        assert mock_service.run.call_count == 1


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


class TestToolContextBinding:
    """Verify _make_tool_executor binds ExecutionContext on every tool that
    declares bind_context — not just Delegate (was hardcoded previously)."""

    def _ctx_with_tools(self, tools: dict):
        """Build an ExecutionContext whose tool_executor returns the given tools by name."""
        ctx = _make_context()
        ctx.tool_executor.get_tool = MagicMock(side_effect=lambda name: tools.get(name))
        return ctx

    def test_binds_each_listed_tool_that_has_bind_context(self):
        delegate = MagicMock()
        query = MagicMock()
        plain = MagicMock(spec=[])  # no bind_context attribute
        ctx = self._ctx_with_tools({"Delegate": delegate, "QueryRunState": query, "Bash": plain})

        agent = _make_agent({"tools": ["Delegate", "QueryRunState", "Bash"]})
        agent._make_tool_executor(ctx)

        delegate.bind_context.assert_called_once_with(ctx)
        query.bind_context.assert_called_once_with(ctx)
        # Bash has no bind_context — no attempt to call

    def test_skips_tools_not_in_agent_config(self):
        delegate = MagicMock()
        query = MagicMock()
        ctx = self._ctx_with_tools({"Delegate": delegate, "QueryRunState": query})

        # Agent only lists Delegate — QueryRunState should not be bound
        agent = _make_agent({"tools": ["Delegate"]})
        agent._make_tool_executor(ctx)

        delegate.bind_context.assert_called_once_with(ctx)
        query.bind_context.assert_not_called()

    def test_no_tools_config_binds_nothing(self):
        delegate = MagicMock()
        ctx = self._ctx_with_tools({"Delegate": delegate})

        agent = _make_agent({})  # no tools list
        agent._make_tool_executor(ctx)

        delegate.bind_context.assert_not_called()

    def test_unregistered_tool_is_skipped_silently(self):
        """Agent lists a tool that isn't registered — don't crash."""
        ctx = self._ctx_with_tools({})
        agent = _make_agent({"tools": ["GhostTool"]})
        # Should not raise
        agent._make_tool_executor(ctx)


class _Echo(BaseTool):
    name = "echo"
    description = "echo"
    parameters = {"type": "object", "properties": {}}

    def __init__(self, config=None):
        super().__init__(config)
        self.calls: list[dict] = []

    def execute(self, **params):
        self.calls.append(params)
        return ToolResult(success=True, result="ran")


class TestPerAgentToolScope:
    """The agent declares its tools on every execute() call.

    The gate itself lives in ToolExecutor.execute (tested in test_executor.py);
    these cover the wiring: the model's callback passes this agent's declared
    list, shown and declared come from one source, and nothing about the scope
    is written into the context — Delegate copies it to sub-agents that declare
    their own tools, and ScriptAgent declares its own.
    """

    def _ctx_with_root(self):
        """A real ToolExecutor holding two agents' tools, as a run does."""
        root = ToolExecutor()
        mine, theirs = _Echo(), _Echo()
        root.register_tools({"github-ci.get_job_logs": mine, "github-full.merge_pull_request": theirs})
        return _make_context(tool_executor=root), root, mine, theirs

    def test_declared_tool_runs_undeclared_is_refused(self):
        ctx, _, mine, theirs = self._ctx_with_root()
        run = _make_agent({"tools": ["github-ci.get_job_logs"]})._make_tool_executor(ctx)

        assert run("github-ci.get_job_logs", {"run_id": 1}) == "ran"
        assert mine.calls == [{"run_id": 1}]

        out = run("github-full.merge_pull_request", {"pullNumber": 1})
        assert out.startswith("Error: Tool 'github-full.merge_pull_request' is not available to agent 'test_agent'")
        assert "github-ci.get_job_logs" in out, "the model is told what it does have"
        assert theirs.calls == [], "the other agent's tool was never invoked"

    def test_context_keeps_the_unrestricted_executor(self):
        """Regression guard: the scope must not leak into the context, or a Delegate
        child (or ScriptAgent) would inherit this agent's narrower list."""
        ctx, root, _, theirs = self._ctx_with_root()
        agent = _make_agent({"tools": ["github-ci.get_job_logs"]})
        agent._get_tools(ctx)
        agent._make_tool_executor(ctx)

        assert ctx.tool_executor is root
        assert root.execute(
            "github-full.merge_pull_request", {}, allowed_tools=ALL_TOOLS,
        ).success is True
        assert theirs.calls == [{}]

    def test_shown_and_executable_come_from_one_source(self):
        """A {name, config} spec entry counts for visibility AND execution."""
        ctx, _, mine, _ = self._ctx_with_root()
        agent = _make_agent({"tools": [{"name": "github-ci.get_job_logs", "config": {}}]})

        assert [s["function"]["name"] for s in agent._get_tools(ctx)] == ["echo"]
        run = agent._make_tool_executor(ctx)
        assert run("github-ci.get_job_logs", {}) == "ran"
        assert mine.calls == [{}]

    def test_agent_with_no_tools_can_execute_nothing(self):
        ctx, _, _, theirs = self._ctx_with_root()
        run = _make_agent({"tools": []})._make_tool_executor(ctx)
        assert run("github-full.merge_pull_request", {}).startswith("Error: Tool ")
        assert theirs.calls == []


class TestAConfiguredToolThatIsNotThere:
    """An agent whose tools are missing must not answer anyway.

    This was a warning. A walk agent configured with a browser was given none (its config lived
    one stage deep, where the binder never looked), and it did not stop: it produced three
    accounts of using a product it had never loaded, and the run stored them as findings.
    """

    @staticmethod
    def _executor(registered: dict):
        te = MagicMock()
        te.get_tool = MagicMock(side_effect=lambda n: registered.get(n))
        te.tool_names = MagicMock(return_value=sorted(registered))
        return te

    def test_it_refuses_before_the_first_call(self):
        ctx = _make_context(tool_executor=self._executor({}))
        agent = _make_agent({"tools": ["playwright.browser_navigate"]})
        with pytest.raises(ToolsNotRegisteredError, match="playwright.browser_navigate"):
            agent._get_tools(ctx)

    def test_it_names_the_agent_and_everything_missing(self):
        ctx = _make_context(tool_executor=self._executor({}))
        agent = _make_agent({"tools": ["playwright.browser_click", "playwright.browser_type"]})
        with pytest.raises(ToolsNotRegisteredError) as exc:
            agent._get_tools(ctx)
        assert "test_agent" in str(exc.value)
        assert "playwright.browser_click, playwright.browser_type" in str(exc.value)

    def test_it_says_what_was_registered_instead(self):
        tool = MagicMock()
        tool.to_llm_schema = MagicMock(return_value={"function": {"name": "Read"}})
        ctx = _make_context(tool_executor=self._executor({"Read": tool}))
        agent = _make_agent({"tools": ["Read", "playwright.browser_snapshot"]})
        with pytest.raises(ToolsNotRegisteredError, match="Registered here: Read"):
            agent._get_tools(ctx)

    def test_a_fully_registered_agent_is_untouched(self):
        tool = MagicMock()
        tool.to_llm_schema = MagicMock(return_value={"function": {"name": "Read"}})
        ctx = _make_context(tool_executor=self._executor({"Read": tool}))
        assert _make_agent({"tools": ["Read"]})._get_tools(ctx) == [{"function": {"name": "Read"}}]

    def test_an_agent_that_asked_for_nothing_is_not_a_failure(self):
        ctx = _make_context(tool_executor=self._executor({}))
        assert _make_agent({"tools": []})._get_tools(ctx) == []
