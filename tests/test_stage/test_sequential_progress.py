"""Tests for sequential execution progress display indicators.

Verifies:
- Stage header includes index format [N/M]
- Agent running indicator is printed before execution
- Stage completion line is printed after all agents finish
"""
from unittest.mock import MagicMock, patch, call

from temper_ai.agent.base_agent import AgentResponse
from temper_ai.stage.executors._sequential_helpers import (
    AgentExecutionContext,
    run_all_agents,
)
from temper_ai.stage.executors.state_keys import StateKeys


def _make_response(output: str = "ok") -> AgentResponse:
    return AgentResponse(
        output=output,
        reasoning="reason",
        confidence=0.9,
        tokens=100,
        estimated_cost_usd=0.001,
        tool_calls=[],
    )


def _make_detail_console() -> MagicMock:
    return MagicMock()


def _make_executor() -> MagicMock:
    executor = MagicMock()
    executor._extract_agent_name = lambda ref: ref if isinstance(ref, str) else ref.get("name", "")
    executor._agent_cache = {}
    return executor


def _make_ctx(
    stage_name: str = "analysis",
    stage_outputs: dict | None = None,
    total_stages: int = 3,
    show_details: bool = True,
) -> tuple[AgentExecutionContext, MagicMock]:
    """Create a test context with detail console.

    Returns (ctx, detail_console).
    """
    detail_console = _make_detail_console()
    state = {
        StateKeys.SHOW_DETAILS: show_details,
        StateKeys.DETAIL_CONSOLE: detail_console,
        StateKeys.STAGE_OUTPUTS: stage_outputs or {},
        StateKeys.TOTAL_STAGES: total_stages,
        StateKeys.WORKFLOW_ID: "wf-1",
    }
    ctx = AgentExecutionContext(
        executor=_make_executor(),
        stage_id="stage-1",
        stage_name=stage_name,
        workflow_id="wf-1",
        state=state,
        tracker=None,
        config_loader=MagicMock(),
    )
    return ctx, detail_console


class TestStageHeaderIndex:
    """Test that stage header includes index format."""

    @patch("temper_ai.stage.executors._sequential_helpers.execute_agent")
    def test_header_shows_index_and_total(self, mock_exec: MagicMock) -> None:
        mock_exec.return_value = {
            StateKeys.AGENT_NAME: "agent1",
            StateKeys.STATUS: "success",
            StateKeys.OUTPUT_DATA: {"output": "ok"},
            StateKeys.METRICS: {"duration_seconds": 1.0, "tokens": 100, "cost_usd": 0.0, "tool_calls": 0},
        }
        ctx, detail_console = _make_ctx(total_stages=3)

        run_all_agents(ctx, ["agent1"], error_handling={})

        # First print call should be the header
        header_call = detail_console.print.call_args_list[0]
        header_text = header_call[0][0]
        assert "[1/3]" in header_text
        assert "analysis" in header_text

    @patch("temper_ai.stage.executors._sequential_helpers.execute_agent")
    def test_header_shows_correct_index_for_second_stage(self, mock_exec: MagicMock) -> None:
        mock_exec.return_value = {
            StateKeys.AGENT_NAME: "agent1",
            StateKeys.STATUS: "success",
            StateKeys.OUTPUT_DATA: {"output": "ok"},
            StateKeys.METRICS: {"duration_seconds": 1.0, "tokens": 100, "cost_usd": 0.0, "tool_calls": 0},
        }
        # Simulate one stage already completed
        ctx, detail_console = _make_ctx(
            stage_name="implementation",
            stage_outputs={"analysis": {"output": "done"}},
            total_stages=3,
        )

        run_all_agents(ctx, ["agent1"], error_handling={})

        header_call = detail_console.print.call_args_list[0]
        header_text = header_call[0][0]
        assert "[2/3]" in header_text
        assert "implementation" in header_text


class TestAgentRunningIndicator:
    """Test that running indicator is printed before agent executes."""

    @patch("temper_ai.stage.executors._sequential_helpers.execute_agent")
    def test_running_indicator_before_execution(self, mock_exec: MagicMock) -> None:
        mock_exec.return_value = {
            StateKeys.AGENT_NAME: "research_agent",
            StateKeys.STATUS: "success",
            StateKeys.OUTPUT_DATA: {"output": "ok"},
            StateKeys.METRICS: {"duration_seconds": 1.0, "tokens": 100, "cost_usd": 0.0, "tool_calls": 0},
        }
        ctx, detail_console = _make_ctx()

        run_all_agents(ctx, ["research_agent"], error_handling={})

        # Second print call (after header) should be the running indicator
        calls = detail_console.print.call_args_list
        running_call = calls[1]
        running_text = running_call[0][0]
        assert "research_agent" in running_text
        assert "running" in running_text

    @patch("temper_ai.stage.executors._sequential_helpers.execute_agent")
    def test_running_indicator_not_shown_without_details(self, mock_exec: MagicMock) -> None:
        mock_exec.return_value = {
            StateKeys.AGENT_NAME: "agent1",
            StateKeys.STATUS: "success",
            StateKeys.OUTPUT_DATA: {"output": "ok"},
            StateKeys.METRICS: {"duration_seconds": 1.0, "tokens": 100, "cost_usd": 0.0, "tool_calls": 0},
        }
        ctx, detail_console = _make_ctx(show_details=False)

        run_all_agents(ctx, ["agent1"], error_handling={})

        detail_console.print.assert_not_called()


class TestStageCompletionLine:
    """Test that stage completion line is printed after all agents."""

    @patch("temper_ai.stage.executors._sequential_helpers.execute_agent")
    def test_completion_line_printed(self, mock_exec: MagicMock) -> None:
        mock_exec.return_value = {
            StateKeys.AGENT_NAME: "agent1",
            StateKeys.STATUS: "success",
            StateKeys.OUTPUT_DATA: {"output": "ok"},
            StateKeys.METRICS: {"duration_seconds": 1.0, "tokens": 100, "cost_usd": 0.0, "tool_calls": 0},
        }
        ctx, detail_console = _make_ctx()

        run_all_agents(ctx, ["agent1"], error_handling={})

        # Last print call before cost summary should be completion line
        calls = detail_console.print.call_args_list
        # Find the completion line
        completion_found = False
        for c in calls:
            text = c[0][0]
            if "\u2713" in text and "Stage complete" in text:
                completion_found = True
                break
        assert completion_found, f"Stage completion line not found in: {[c[0][0] for c in calls]}"
