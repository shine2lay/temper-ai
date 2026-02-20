"""Tests for parallel execution progress display indicators.

Verifies:
- _print_stage_header includes index format [N/M]
- Stream callback stage context is set
"""
from unittest.mock import MagicMock

from temper_ai.stage.executors.parallel import _print_stage_header
from temper_ai.stage.executors.state_keys import StateKeys


def _make_state(
    stage_outputs: dict | None = None,
    total_stages: int = 3,
) -> dict:
    detail_console = MagicMock()
    state = {
        StateKeys.SHOW_DETAILS: True,
        StateKeys.DETAIL_CONSOLE: detail_console,
        StateKeys.STAGE_OUTPUTS: stage_outputs or {},
        StateKeys.TOTAL_STAGES: total_stages,
    }
    return state


class TestParallelStageHeader:
    """Test parallel stage header index format."""

    def test_header_shows_index(self) -> None:
        state = _make_state(total_stages=4)
        _print_stage_header(state, "analysis")

        console = state[StateKeys.DETAIL_CONSOLE]
        console.print.assert_called_once()
        header_text = console.print.call_args[0][0]
        assert "[1/4]" in header_text
        assert "analysis" in header_text

    def test_header_shows_second_index(self) -> None:
        state = _make_state(
            stage_outputs={"analysis": {"output": "done"}},
            total_stages=4,
        )
        _print_stage_header(state, "implementation")

        console = state[StateKeys.DETAIL_CONSOLE]
        header_text = console.print.call_args[0][0]
        assert "[2/4]" in header_text

    def test_header_sets_stream_callback_stage(self) -> None:
        stream_cb = MagicMock()
        stream_cb._current_stage = ""
        state = _make_state()
        state[StateKeys.STREAM_CALLBACK] = stream_cb

        _print_stage_header(state, "analysis")

        assert stream_cb._current_stage == "analysis"

    def test_no_print_when_show_details_false(self) -> None:
        state = _make_state()
        state[StateKeys.SHOW_DETAILS] = False

        _print_stage_header(state, "analysis")

        state[StateKeys.DETAIL_CONSOLE].print.assert_not_called()
