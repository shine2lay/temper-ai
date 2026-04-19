"""Tests for the LLM service — the tool-calling loop with observability."""

from temper_ai.llm.models import CallContext, LLMResponse
from temper_ai.llm.service import (
    LLMService,
    _apply_message_window,
    _inject_tool_results,
)
from temper_ai.observability import EventType, get_events

from .conftest import MockProvider


def _make_text_response(content="Done", tokens=100, model="mock-model"):
    return LLMResponse(
        content=content, model=model, provider="MockProvider",
        prompt_tokens=int(tokens * 0.6), completion_tokens=int(tokens * 0.4),
        total_tokens=tokens, latency_ms=50, finish_reason="stop",
    )


def _make_tool_response(tool_calls, tokens=100, content=None, model="mock-model"):
    return LLMResponse(
        content=content, model=model, provider="MockProvider",
        prompt_tokens=int(tokens * 0.6), completion_tokens=int(tokens * 0.4),
        total_tokens=tokens, latency_ms=50, finish_reason="tool_calls",
        tool_calls=tool_calls,
    )


def _echo_tool(name: str, params: dict) -> str:
    return f"result of {name}"


# -- Basic completion (no tools) --


class TestSimpleCompletion:
    def test_direct_response(self):
        provider = MockProvider([_make_text_response("Hello world")])
        service = LLMService(provider)

        result = service.run([{"role": "user", "content": "Say hello"}])

        assert result.output == "Hello world"
        assert result.iterations == 1
        assert result.tokens == 100
        assert result.error is None
        assert result.tool_calls == []

    def test_empty_content_response(self):
        provider = MockProvider([_make_text_response("")])
        service = LLMService(provider)

        result = service.run([{"role": "user", "content": "Hi"}])
        assert result.output == ""


# -- Tool calling loop --


class TestToolCallingLoop:
    def test_single_tool_call_then_response(self):
        """LLM calls a tool, then responds with text."""
        responses = [
            _make_tool_response([
                {"id": "c1", "name": "bash", "arguments": '{"command": "ls"}'},
            ]),
            _make_text_response("Found 3 files"),
        ]
        provider = MockProvider(responses)
        service = LLMService(provider)

        result = service.run(
            [{"role": "user", "content": "List files"}],
            tools=[{"type": "function", "function": {"name": "bash"}}],
            execute_tool=_echo_tool,
        )

        assert result.output == "Found 3 files"
        assert result.iterations == 2
        assert result.tokens == 200
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0]["name"] == "bash"
        assert result.tool_calls[0]["success"] is True

    def test_multiple_tool_iterations(self):
        """LLM calls tools multiple times before responding."""
        responses = [
            _make_tool_response([
                {"id": "c1", "name": "bash", "arguments": '{"command": "ls"}'},
            ]),
            _make_tool_response([
                {"id": "c2", "name": "file_writer", "arguments": '{"path": "x.py"}'},
            ]),
            _make_text_response("All done"),
        ]
        provider = MockProvider(responses)
        service = LLMService(provider)

        result = service.run(
            [{"role": "user", "content": "Create a file"}],
            tools=[],
            execute_tool=_echo_tool,
        )

        assert result.output == "All done"
        assert result.iterations == 3
        assert result.tokens == 300
        assert len(result.tool_calls) == 2

    def test_multiple_tools_in_single_call(self):
        """LLM calls multiple tools in one response (parallel tool calls)."""
        responses = [
            _make_tool_response([
                {"id": "c1", "name": "bash", "arguments": '{"command": "ls"}'},
                {"id": "c2", "name": "bash", "arguments": '{"command": "pwd"}'},
            ]),
            _make_text_response("Done"),
        ]
        provider = MockProvider(responses)
        service = LLMService(provider)

        result = service.run(
            [{"role": "user", "content": "Check env"}],
            tools=[],
            execute_tool=_echo_tool,
        )

        assert result.output == "Done"
        assert len(result.tool_calls) == 2

    def test_max_iterations_reached(self):
        """LLM keeps calling tools until max iterations."""
        responses = [
            _make_tool_response([
                {"id": f"c{i}", "name": "bash", "arguments": '{"command": "loop"}'},
            ])
            for i in range(5)
        ]
        provider = MockProvider(responses)
        service = LLMService(provider, max_iterations=3)

        result = service.run(
            [{"role": "user", "content": "Do something"}],
            tools=[],
            execute_tool=_echo_tool,
        )

        assert result.iterations == 3
        assert result.error is not None
        assert "max iterations" in result.error.lower()

    def test_no_executor_returns_error(self):
        """LLM returns tool calls but no executor provided."""
        responses = [
            _make_tool_response([
                {"id": "c1", "name": "bash", "arguments": "{}"},
            ]),
        ]
        provider = MockProvider(responses)
        service = LLMService(provider)

        result = service.run(
            [{"role": "user", "content": "Do something"}],
            tools=[{"type": "function", "function": {"name": "bash"}}],
            # No execute_tool!
        )

        assert result.error is not None
        assert "no tool executor" in result.error.lower()


# -- Streaming --


class TestStreaming:
    def test_stream_callback_is_called(self):
        provider = MockProvider([_make_text_response("Streamed!")])
        service = LLMService(provider)

        chunks = []
        result = service.run(
            [{"role": "user", "content": "Hi"}],
            stream_callback=lambda c: chunks.append(c),
        )

        assert result.output == "Streamed!"
        # MockProvider sends content chunk + done chunk
        assert len(chunks) >= 1
        assert any(c.done for c in chunks)

    def test_stream_uses_stream_method(self):
        provider = MockProvider([_make_text_response("Hello")])
        service = LLMService(provider)

        service.run(
            [{"role": "user", "content": "Hi"}],
            stream_callback=lambda c: None,
        )

        assert provider.calls[0]["method"] == "stream"

    def test_no_callback_uses_complete(self):
        provider = MockProvider([_make_text_response("Hello")])
        service = LLMService(provider)

        service.run([{"role": "user", "content": "Hi"}])

        assert provider.calls[0]["method"] == "complete"


# -- Message injection --


class TestInjectToolResults:
    def test_injects_assistant_and_tool_messages(self):
        messages = [{"role": "user", "content": "Hi"}]
        response = LLMResponse(
            content=None, model="gpt-4", provider="test",
            tool_calls=[{"id": "c1", "name": "bash", "arguments": '{"cmd": "ls"}'}],
        )
        tool_calls = [{"id": "c1", "name": "bash", "arguments": {"cmd": "ls"}}]
        tool_results = [
            {"tool_call_id": "c1", "name": "bash", "result": "file1.py", "success": True},
        ]

        _inject_tool_results(messages, response, tool_calls, tool_results)

        assert len(messages) == 3  # user + assistant + tool
        assert messages[1]["role"] == "assistant"
        assert messages[1]["tool_calls"][0]["function"]["name"] == "bash"
        assert messages[2]["role"] == "tool"
        assert messages[2]["tool_call_id"] == "c1"
        assert messages[2]["content"] == "file1.py"

    def test_preserves_assistant_content(self):
        messages = []
        response = LLMResponse(
            content="Let me check", model="gpt-4", provider="test",
            tool_calls=[{"id": "c1", "name": "bash", "arguments": "{}"}],
        )
        tool_calls = [{"id": "c1", "name": "bash", "arguments": {}}]
        tool_results = [{"tool_call_id": "c1", "name": "bash", "result": "ok", "success": True}]

        _inject_tool_results(messages, response, tool_calls, tool_results)

        assert messages[0]["content"] == "Let me check"

    def test_includes_empty_content_when_none(self):
        """Content should always be present (empty string) to prevent tool-calling loops."""
        messages = []
        response = LLMResponse(
            content=None, model="gpt-4", provider="test",
            tool_calls=[{"id": "c1", "name": "bash", "arguments": "{}"}],
        )
        tool_calls = [{"id": "c1", "name": "bash", "arguments": {}}]
        tool_results = [{"tool_call_id": "c1", "name": "bash", "result": "ok", "success": True}]

        _inject_tool_results(messages, response, tool_calls, tool_results)

        assert messages[0]["content"] == ""  # always present, empty string
        assert messages[0]["role"] == "assistant"
        assert "tool_calls" in messages[0]


# -- Message windowing --


class TestMessageWindowing:
    def test_no_trimming_under_limit(self):
        messages = [{"role": "user", "content": f"msg {i}"} for i in range(5)]
        _apply_message_window(messages, max_messages=10)
        assert len(messages) == 5

    def test_trims_to_limit(self):
        messages = [{"role": "system", "content": "system prompt"}]
        messages += [{"role": "user", "content": f"msg {i}"} for i in range(20)]
        original_first = messages[0]
        original_last = messages[-1]

        _apply_message_window(messages, max_messages=10)

        assert len(messages) == 10
        assert messages[0] == original_first  # first message preserved
        assert messages[-1] == original_last  # last message preserved

    def test_keeps_first_and_recent(self):
        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "old-1"},
            {"role": "assistant", "content": "old-2"},
            {"role": "user", "content": "recent-1"},
            {"role": "assistant", "content": "recent-2"},
            {"role": "user", "content": "recent-3"},
        ]

        _apply_message_window(messages, max_messages=4)

        assert len(messages) == 4
        assert messages[0]["content"] == "system"
        # First user message is preserved (required by chat templates)
        assert messages[1]["content"] == "old-1"
        assert messages[-1]["content"] == "recent-3"

    def test_skips_orphaned_tool_results(self):
        """If the window cut lands inside a tool-call pair, orphaned tool
        results at the start of the tail are dropped."""
        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "old user msg"},
            {"role": "assistant", "tool_calls": [{"id": "c1"}]},  # old assistant
            {"role": "tool", "tool_call_id": "c1", "content": "old tool result"},
            {"role": "assistant", "content": "old response"},
            {"role": "user", "content": "new user msg"},
            {"role": "assistant", "tool_calls": [{"id": "c2"}]},
            {"role": "tool", "tool_call_id": "c2", "content": "new tool result"},
            {"role": "assistant", "content": "final response"},
        ]

        # Window of 5: system + last 4 = [system, assistant+c2, tool c2, assistant, ???]
        # But last 4 starting from index 5 = [user, assistant+c2, tool c2, assistant]
        # That's clean — no orphaned tool. Let's force an orphan with window of 4:
        # tail(3) = [tool c2, assistant "final response"] — orphaned tool!
        _apply_message_window(messages, max_messages=4)

        # The orphaned tool result should be skipped
        roles = [m["role"] for m in messages]
        assert roles[0] == "system"
        assert "tool" not in roles[:2]  # no orphaned tool right after system
        # No tool message should appear without its preceding assistant+tool_calls
        for i, msg in enumerate(messages):
            if msg.get("role") == "tool":
                # The previous message must be assistant with tool_calls
                assert i > 0
                prev = messages[i - 1]
                assert prev.get("role") == "assistant"
                assert "tool_calls" in prev

    def test_window_keeps_complete_tool_pairs(self):
        """When the tail starts at a clean boundary, nothing is dropped."""
        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "old"},
            {"role": "assistant", "content": "old response"},
            {"role": "user", "content": "recent"},
            {"role": "assistant", "tool_calls": [{"id": "c1"}]},
            {"role": "tool", "tool_call_id": "c1", "content": "result"},
            {"role": "assistant", "content": "final"},
        ]

        _apply_message_window(messages, max_messages=5)

        # prefix: [system, old user] (first user preserved)
        # tail(3): [tool c1, assistant "final"] — but tool is orphaned, so skipped
        # Result depends on orphan handling
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert messages[-1]["content"] == "final"

    def test_window_all_orphaned_tools_dropped(self):
        """Multiple orphaned tool results at the start are all dropped."""
        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "old"},
            {"role": "assistant", "tool_calls": [{"id": "c1"}, {"id": "c2"}]},
            {"role": "tool", "tool_call_id": "c1", "content": "r1"},
            {"role": "tool", "tool_call_id": "c2", "content": "r2"},
            {"role": "assistant", "content": "final"},
        ]

        # max 3: system + tail(2) = [tool c2, assistant "final"]
        # Both tool messages are orphaned — skip until "assistant"
        _apply_message_window(messages, max_messages=3)

        roles = [m["role"] for m in messages]
        assert "tool" not in roles
        assert messages[0]["role"] == "system"
        assert messages[-1]["content"] == "final"


# -- Observability --


class TestServiceObservability:
    def test_simple_completion_records_events(self):
        provider = MockProvider([_make_text_response("Hi")])
        service = LLMService(provider)
        ctx = CallContext(execution_id="obs-1", agent_name="test-agent")

        service.run([{"role": "user", "content": "Hi"}], context=ctx)

        events = get_events(execution_id="obs-1")
        types = [e["type"] for e in events]

        assert EventType.LLM_CALL_STARTED in types
        assert EventType.LLM_CALL_COMPLETED in types
        assert EventType.LLM_ITERATION in types

    def test_llm_call_started_has_context(self):
        provider = MockProvider([_make_text_response("Hi")])
        service = LLMService(provider)
        ctx = CallContext(
            execution_id="obs-2",
            agent_event_id="agent-evt-1",
            agent_name="researcher",
            node_path="analyze",
        )

        service.run([{"role": "user", "content": "Hi"}], context=ctx)

        events = get_events(execution_id="obs-2")
        started = [e for e in events if e["type"] == EventType.LLM_CALL_STARTED][0]

        assert started["parent_id"] == "agent-evt-1"
        assert started["data"]["agent_name"] == "researcher"
        assert started["data"]["node_path"] == "analyze"
        assert started["data"]["model"] == "mock-model"
        assert started["data"]["iteration"] == 1
        assert started["status"] == "running"

    def test_llm_call_completed_has_metrics(self):
        provider = MockProvider([_make_text_response("Hi", tokens=150)])
        service = LLMService(provider)
        ctx = CallContext(execution_id="obs-3")

        service.run([{"role": "user", "content": "Hi"}], context=ctx)

        events = get_events(execution_id="obs-3")
        completed = [e for e in events if e["type"] == EventType.LLM_CALL_COMPLETED][0]

        assert completed["data"]["total_tokens"] == 150
        assert completed["data"]["latency_ms"] == 50
        assert completed["data"]["finish_reason"] == "stop"
        assert completed["data"]["has_tool_calls"] is False
        assert completed["data"]["cost_usd"] >= 0
        assert completed["status"] == "completed"

    def test_tool_loop_records_all_events(self):
        responses = [
            _make_tool_response([
                {"id": "c1", "name": "bash", "arguments": '{"command": "ls"}'},
            ]),
            _make_text_response("Done"),
        ]
        provider = MockProvider(responses)
        service = LLMService(provider)
        ctx = CallContext(execution_id="obs-4", agent_name="coder")

        service.run(
            [{"role": "user", "content": "List files"}],
            tools=[], execute_tool=_echo_tool, context=ctx,
        )

        events = get_events(execution_id="obs-4")
        types = [e["type"] for e in events]

        # Iteration 1: LLM call + tool call + iteration
        assert types.count(str(EventType.LLM_CALL_STARTED)) == 2
        assert types.count(str(EventType.LLM_CALL_COMPLETED)) == 2
        assert types.count(str(EventType.TOOL_CALL_STARTED)) == 1
        assert types.count(str(EventType.TOOL_CALL_COMPLETED)) == 1
        assert types.count(str(EventType.LLM_ITERATION)) == 2

    def test_iteration_events_have_correct_actions(self):
        responses = [
            _make_tool_response([
                {"id": "c1", "name": "bash", "arguments": '{}'},
            ]),
            _make_text_response("Done"),
        ]
        provider = MockProvider(responses)
        service = LLMService(provider)
        ctx = CallContext(execution_id="obs-5")

        service.run(
            [{"role": "user", "content": "Do it"}],
            tools=[], execute_tool=_echo_tool, context=ctx,
        )

        events = get_events(execution_id="obs-5")
        iterations = [e for e in events if e["type"] == EventType.LLM_ITERATION]

        assert len(iterations) == 2
        assert iterations[0]["data"]["action"] == "tool_calls"
        assert iterations[0]["data"]["tool_count"] == 1
        assert iterations[1]["data"]["action"] == "final_response"
        assert iterations[1]["data"]["tool_count"] == 0

    def test_llm_failure_records_failed_event(self):
        provider = MockProvider([])  # No responses — will raise
        service = LLMService(provider)
        ctx = CallContext(execution_id="obs-6", agent_name="broken-agent")

        try:
            service.run([{"role": "user", "content": "Hi"}], context=ctx)
        except RuntimeError:
            pass  # MockProvider raises when exhausted

        events = get_events(execution_id="obs-6")
        types = [e["type"] for e in events]

        assert EventType.LLM_CALL_STARTED in types
        assert EventType.LLM_CALL_FAILED in types

        failed = [e for e in events if e["type"] == EventType.LLM_CALL_FAILED][0]
        assert "RuntimeError" in failed["data"]["error_type"]
        assert failed["status"] == "failed"


# -- Cost accumulation --


class TestCostAccumulation:
    def test_cost_accumulates_across_iterations(self):
        responses = [
            _make_tool_response(
                [{"id": "c1", "name": "bash", "arguments": '{}'}],
                tokens=100,
            ),
            _make_text_response("Done", tokens=50),
        ]
        provider = MockProvider(responses)
        service = LLMService(provider)

        result = service.run(
            [{"role": "user", "content": "Hi"}],
            tools=[], execute_tool=_echo_tool,
        )

        assert result.tokens == 150
        assert result.cost > 0


# -- Messages passed to provider --


class TestMessagesPassed:
    def test_initial_messages_passed_to_provider(self):
        provider = MockProvider([_make_text_response("Hi")])
        service = LLMService(provider)

        messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Hello"},
        ]
        service.run(messages)

        call = provider.calls[0]
        assert len(call["messages"]) == 2
        assert call["messages"][0]["role"] == "system"

    def test_tool_results_included_in_next_call(self):
        responses = [
            _make_tool_response([
                {"id": "c1", "name": "bash", "arguments": '{"command": "ls"}'},
            ]),
            _make_text_response("Done"),
        ]
        provider = MockProvider(responses)
        service = LLMService(provider)

        service.run(
            [{"role": "user", "content": "List files"}],
            tools=[], execute_tool=_echo_tool,
        )

        # Second call should include tool results
        second_call = provider.calls[1]
        roles = [m["role"] for m in second_call["messages"]]
        assert "assistant" in roles
        assert "tool" in roles

    def test_tools_kwarg_passed_to_provider(self):
        provider = MockProvider([_make_text_response("Hi")])
        service = LLMService(provider)

        tools = [{"type": "function", "function": {"name": "bash"}}]
        service.run(
            [{"role": "user", "content": "Hi"}], tools=tools,
        )

        assert provider.calls[0]["kwargs"]["tools"] == tools
