"""Stopping a run stops the work already going on inside it.

A cancel used to be looked at only between nodes. An agent that kept calling
tools went on until it finished by itself, which for a build agent could be an
hour; the only way to stop it sooner was to restart the server, and a restart
kills every run on it (2026-09-24, the b022/b028 pitch writers).

Now the run's stop flag reaches:
  - the agent's loop, which makes no further LLM call once it is set;
  - the tool executor, which starts no tool call once it is set;
  - a shell command still running, which is killed with everything it started.
A call to the model already on its way is not interrupted: it returns first.
"""

import threading
import time
from dataclasses import replace
from typing import Any
from unittest.mock import MagicMock, patch

from temper_ai.agent.llm_agent import LLMAgent
from temper_ai.llm.models import CallContext, LLMResponse, LLMRunResult
from temper_ai.llm.service import CANCELLED_ERROR, LLMService
from temper_ai.shared.types import ExecutionContext
from temper_ai.tools.base import BaseTool, ToolResult
from temper_ai.tools.bash import Bash, _run_subprocess
from temper_ai.tools.executor import ToolExecutor

from ..test_llm.conftest import MockProvider

_BASH = [{"type": "function", "function": {"name": "bash"}}]


def _tool_call(n: int) -> LLMResponse:
    return LLMResponse(
        content=None, model="mock-model", provider="MockProvider",
        prompt_tokens=60, completion_tokens=40, total_tokens=100,
        latency_ms=5, finish_reason="tool_calls",
        tool_calls=[{"id": f"c{n}", "name": "bash", "arguments": '{"command": "ls"}'}],
    )


def _answer(text: str = "done") -> LLMResponse:
    return LLMResponse(
        content=text, model="mock-model", provider="MockProvider",
        prompt_tokens=60, completion_tokens=40, total_tokens=100,
        latency_ms=5, finish_reason="stop",
    )


class TestTheAgentLoop:
    def test_a_stopped_run_makes_no_call_at_all(self):
        stop = threading.Event()
        stop.set()
        provider = MockProvider([_answer()])

        result = LLMService(provider).run(
            [{"role": "user", "content": "go"}], context=CallContext(cancel_event=stop),
        )

        assert provider.calls == []
        assert result.error == CANCELLED_ERROR
        assert result.iterations == 0

    def test_a_stop_during_a_tool_call_ends_the_loop_before_the_next_call(self):
        stop = threading.Event()
        provider = MockProvider([_tool_call(1), _tool_call(2), _answer()])

        def tool(name: str, params: dict) -> str:
            stop.set()  # the owner presses stop while the first tool runs
            return "listing"

        result = LLMService(provider).run(
            [{"role": "user", "content": "go"}], tools=_BASH, execute_tool=tool,
            context=CallContext(cancel_event=stop),
        )

        assert len(provider.calls) == 1, "the model was called again after the stop"
        assert result.error == CANCELLED_ERROR
        assert result.iterations == 1
        assert result.tokens == 100, "what the finished call cost is still counted"

    def test_a_flag_that_is_never_set_changes_nothing(self):
        provider = MockProvider([_tool_call(1), _answer("all good")])

        result = LLMService(provider).run(
            [{"role": "user", "content": "go"}], tools=_BASH,
            execute_tool=lambda name, params: "ok",
            context=CallContext(cancel_event=threading.Event()),
        )

        assert result.error is None
        assert result.output == "all good"

    @patch("temper_ai.agent.llm_agent.LLMService")
    def test_the_agent_hands_the_runs_flag_to_its_loop(self, MockLLMService):
        MockLLMService.return_value.run.return_value = LLMRunResult(output="ok")
        stop = threading.Event()
        agent = LLMAgent({"name": "a", "type": "llm", "provider": "openai",
                          "model": "gpt-4o-mini", "task_template": "Do: {{ task }}"})
        recorder = MagicMock()
        recorder.record = MagicMock(return_value="evt-1")
        tool_executor = MagicMock()
        tool_executor.get_tool = MagicMock(return_value=None)
        ctx = ExecutionContext(
            run_id="r", workflow_name="wf", node_path="a", agent_name="a",
            event_recorder=recorder, tool_executor=tool_executor,
            llm_providers={"openai": MagicMock()}, cancel_event=stop,
        )

        agent.run({"task": "x"}, ctx)

        assert MockLLMService.return_value.run.call_args.kwargs["context"].cancel_event is stop


class _Counting(BaseTool):
    name = "Counting"
    description = "Counts its calls"
    parameters = {"type": "object", "properties": {}}

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def execute(self, **params: Any) -> ToolResult:
        self.calls += 1
        return ToolResult(success=True, result="ran")


class TestTheToolExecutor:
    def test_no_tool_call_starts_once_the_run_is_stopped(self):
        tool = _Counting()
        executor = ToolExecutor()
        executor.register_tools({"Counting": tool})
        stop = threading.Event()
        executor.cancel_event = stop

        assert executor.execute("Counting", {}, allowed_tools={"Counting"}).success
        stop.set()
        result = executor.execute("Counting", {}, allowed_tools={"Counting"})

        assert result.success is False
        assert "Cancelled" in result.error
        assert tool.calls == 1

    def test_bash_gets_the_flag_whether_it_is_registered_before_or_after(self):
        stop = threading.Event()
        before, after = Bash(), Bash()
        executor = ToolExecutor()
        executor.register_tools({"Bash": before})
        executor.cancel_event = stop
        executor.register_tools({"Bash2": after})

        assert before.cancel_event is stop
        assert after.cancel_event is stop

    def test_a_running_command_is_killed_when_the_run_is_stopped(self, tmp_path):
        executor = ToolExecutor(workspace_root=str(tmp_path))
        executor.register_tools({"Bash": Bash(config={"allowed_commands": ["sleep"]})})
        stop = threading.Event()
        executor.cancel_event = stop
        threading.Timer(0.5, stop.set).start()

        started = time.monotonic()
        result = executor.execute("Bash", {"command": "sleep 30"}, allowed_tools={"Bash"})

        assert time.monotonic() - started < 5, "the command was waited out, not killed"
        assert result.success is False
        assert "Cancelled" in result.error

    def test_the_runs_context_hands_its_flag_to_the_runs_executor(self):
        stop = threading.Event()
        executor = ToolExecutor()
        ctx = ExecutionContext(
            run_id="r", workflow_name="wf", node_path="", agent_name="",
            event_recorder=MagicMock(), tool_executor=executor, cancel_event=stop,
        )

        assert executor.cancel_event is stop
        replace(ctx, node_path="child")  # every node runs on a copy
        assert executor.cancel_event is stop


class TestAShellCommand:
    def test_a_stop_kills_everything_the_command_started(self, tmp_path):
        """The subshell would touch the marker 2s in; killed with the group at 0.5s, it does not."""
        mark = tmp_path / "survived"
        stop = threading.Event()
        threading.Timer(0.5, stop.set).start()

        result = _run_subprocess(f"(sleep 2; touch {mark}) & sleep 30", timeout=60,
                                 cwd=str(tmp_path), cancel_event=stop)

        assert result.success is False
        assert "Cancelled" in result.error
        time.sleep(2.5)
        assert not mark.exists(), "a child of the stopped command outlived it"

    def test_the_timeout_still_applies_while_the_flag_is_watched(self, tmp_path):
        result = _run_subprocess("sleep 10", timeout=1, cwd=str(tmp_path),
                                 cancel_event=threading.Event())

        assert result.success is False
        assert "timed out" in result.error

    def test_output_is_whole_when_nothing_stops_it(self, tmp_path):
        # communicate() is called in slices while the flag is watched; the
        # slices must not lose output a command wrote in between.
        result = _run_subprocess("for i in 1 2 3; do echo line$i; sleep 0.4; done",
                                 timeout=30, cwd=str(tmp_path), cancel_event=threading.Event())

        assert result.success is True
        assert [ln for ln in result.result.splitlines() if ln.startswith("line")] == \
            ["line1", "line2", "line3"]
