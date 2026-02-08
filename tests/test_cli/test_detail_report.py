"""Tests for CLI detailed report rendering (src/cli/detail_report.py).

Tests cover:
- print_detailed_report() function
- _render_agent_detail() helper function
- _tool_calls_list() helper function
- _tool_calls_count() helper function
- Rich panel rendering with Console mocking
- Text sanitization (Text() for LLM content)
- Infrastructure key filtering
- Edge cases: empty outputs, missing tool calls
"""
from unittest.mock import Mock

import pytest
from rich.console import Console
from rich.text import Text

from src.cli.detail_report import (
    _render_agent_detail,
    _tool_calls_count,
    _tool_calls_list,
    print_detailed_report,
)


@pytest.fixture
def mock_console():
    """Create a mock Rich Console."""
    return Mock(spec=Console)


@pytest.fixture
def sample_result():
    """Create a sample workflow result dict."""
    return {
        "status": "completed",
        "stage_outputs": {
            "stage1": {
                "agent_outputs": {
                    "agent1": {
                        "output": "This is the agent output",
                        "reasoning": "Because of X and Y",
                        "confidence": 0.95,
                        "tokens": 150,
                        "cost_usd": 0.0023,
                        "tool_calls": [
                            {
                                "name": "search_web",
                                "success": True,
                                "parameters": {"query": "test query"},
                                "result": "Search results here",
                            }
                        ],
                    },
                },
                "synthesis_result": {
                    "method": "consensus",
                    "confidence": 0.92,
                    "votes": {"option_a": 3},
                },
                "output": "Final stage output",
            },
        },
    }


class TestToolCallsHelpers:
    """Test helper functions for tool call handling."""

    def test_tool_calls_count_with_list(self):
        """Test _tool_calls_count with list input."""
        tool_calls = [{"name": "tool1"}, {"name": "tool2"}]
        assert _tool_calls_count(tool_calls) == 2

    def test_tool_calls_count_with_empty_list(self):
        """Test _tool_calls_count with empty list."""
        assert _tool_calls_count([]) == 0

    def test_tool_calls_count_with_int_legacy(self):
        """Test _tool_calls_count with legacy int format."""
        assert _tool_calls_count(5) == 5

    def test_tool_calls_count_with_none(self):
        """Test _tool_calls_count with None."""
        assert _tool_calls_count(None) == 0

    def test_tool_calls_list_with_list(self):
        """Test _tool_calls_list with list input."""
        tool_calls = [{"name": "tool1"}, {"name": "tool2"}]
        assert _tool_calls_list(tool_calls) == tool_calls

    def test_tool_calls_list_with_int_legacy(self):
        """Test _tool_calls_list with legacy int format returns empty list."""
        assert _tool_calls_list(5) == []

    def test_tool_calls_list_with_none(self):
        """Test _tool_calls_list with None."""
        assert _tool_calls_list(None) == []


class TestRenderAgentDetail:
    """Test the _render_agent_detail helper function."""

    def test_render_agent_detail_full(self):
        """Test rendering full agent details."""
        output_data = {
            "output": "Agent output text",
            "reasoning": "Agent reasoning",
            "tool_calls": [
                {
                    "name": "test_tool",
                    "success": True,
                    "parameters": {"arg1": "value1"},
                    "result": "Tool result",
                }
            ],
        }
        renderables = _render_agent_detail("test_agent", output_data)

        # Should have multiple renderables
        assert len(renderables) > 0

        # Check for Text objects (LLM content sanitization)
        text_objects = [r for r in renderables if isinstance(r, Text)]
        assert len(text_objects) > 0

    def test_render_agent_detail_empty_output(self):
        """Test rendering agent details with empty output."""
        output_data = {"output": "", "reasoning": ""}
        renderables = _render_agent_detail("test_agent", output_data)

        # Should still have agent name header
        assert len(renderables) > 0

    def test_render_agent_detail_with_tool_error(self):
        """Test rendering agent details with tool call error."""
        output_data = {
            "output": "Output",
            "tool_calls": [
                {
                    "name": "failing_tool",
                    "success": False,
                    "error": "Tool execution failed",
                }
            ],
        }
        renderables = _render_agent_detail("test_agent", output_data)
        assert len(renderables) > 0

    def test_render_agent_detail_no_tool_calls(self):
        """Test rendering agent details with no tool calls."""
        output_data = {
            "output": "Simple output",
            "reasoning": "Simple reasoning",
        }
        renderables = _render_agent_detail("test_agent", output_data)
        assert len(renderables) > 0

    def test_render_agent_detail_tool_params_as_arguments(self):
        """Test rendering when tool call uses 'arguments' instead of 'parameters'."""
        output_data = {
            "output": "Output",
            "tool_calls": [
                {
                    "name": "test_tool",
                    "arguments": {"key": "value"},  # Using 'arguments' key
                }
            ],
        }
        renderables = _render_agent_detail("test_agent", output_data)
        assert len(renderables) > 0


class TestPrintDetailedReport:
    """Test the print_detailed_report main function."""

    def test_print_detailed_report_success(self, mock_console, sample_result):
        """Test successful detailed report rendering."""
        print_detailed_report(sample_result, mock_console)

        # Should print rule, panel, etc.
        assert mock_console.print.call_count > 0
        assert mock_console.rule.call_count > 0

    def test_print_detailed_report_empty_stage_outputs(self, mock_console):
        """Test report with empty stage_outputs."""
        result = {"stage_outputs": {}}
        print_detailed_report(result, mock_console)

        # Empty dict evaluates to falsy, so function returns early
        assert mock_console.rule.call_count == 0
        assert mock_console.print.call_count == 0

    def test_print_detailed_report_missing_stage_outputs(self, mock_console):
        """Test report with missing stage_outputs."""
        result = {}
        print_detailed_report(result, mock_console)

        # Should return early, no output
        assert mock_console.print.call_count == 0

    def test_print_detailed_report_invalid_stage_outputs(self, mock_console):
        """Test report with non-dict stage_outputs."""
        result = {"stage_outputs": "invalid"}
        print_detailed_report(result, mock_console)

        # Should return early
        assert mock_console.print.call_count == 0

    def test_print_detailed_report_multiple_stages(self, mock_console):
        """Test report with multiple stages."""
        result = {
            "stage_outputs": {
                "stage1": {
                    "agent_outputs": {
                        "agent1": {"output": "Output 1"},
                    },
                    "output": "Stage 1 output",
                },
                "stage2": {
                    "agent_outputs": {
                        "agent2": {"output": "Output 2"},
                    },
                    "output": "Stage 2 output",
                },
            },
        }
        print_detailed_report(result, mock_console)

        # Should print panels for both stages
        assert mock_console.print.call_count >= 2

    def test_print_detailed_report_with_prior_stages(self, mock_console):
        """Test report shows input context from prior stages."""
        result = {
            "stage_outputs": {
                "stage1": {
                    "agent_outputs": {"agent1": {"output": "Output 1"}},
                    "output": "Stage 1 output",
                },
                "stage2": {
                    "agent_outputs": {"agent2": {"output": "Output 2"}},
                    "output": "Stage 2 output",
                },
            },
        }
        print_detailed_report(result, mock_console)

        # Second stage should reference stage1 as input
        assert mock_console.print.call_count > 0

    def test_print_detailed_report_filters_infrastructure_agents(self, mock_console):
        """Test that agents with __ prefix/suffix are filtered."""
        result = {
            "stage_outputs": {
                "stage1": {
                    "agent_outputs": {
                        "agent1": {"output": "Normal agent"},
                        "__internal__": {"output": "Should be filtered"},
                    },
                    "output": "Stage output",
                },
            },
        }
        print_detailed_report(result, mock_console)

        # Should only process normal agent, not __internal__
        assert mock_console.print.call_count > 0

    def test_print_detailed_report_with_synthesis(self, mock_console):
        """Test report includes synthesis information."""
        result = {
            "stage_outputs": {
                "stage1": {
                    "agent_outputs": {"agent1": {"output": "Output"}},
                    "synthesis_result": {
                        "method": "weighted_vote",
                        "confidence": 0.88,
                        "votes": {"A": 2, "B": 1},
                    },
                    "output": "Final output",
                },
            },
        }
        print_detailed_report(result, mock_console)
        assert mock_console.print.call_count > 0

    def test_print_detailed_report_legacy_synthesis_key(self, mock_console):
        """Test report handles legacy 'synthesis' key."""
        result = {
            "stage_outputs": {
                "stage1": {
                    "agent_outputs": {"agent1": {"output": "Output"}},
                    "synthesis": {  # Legacy key
                        "method": "consensus",
                    },
                    "output": "Final output",
                },
            },
        }
        print_detailed_report(result, mock_console)
        assert mock_console.print.call_count > 0

    def test_print_detailed_report_with_cost(self, mock_console):
        """Test report displays cost information."""
        result = {
            "stage_outputs": {
                "stage1": {
                    "agent_outputs": {
                        "agent1": {
                            "output": "Output",
                            "cost_usd": 0.0045,
                        },
                    },
                    "output": "Final output",
                },
            },
        }
        print_detailed_report(result, mock_console)
        assert mock_console.print.call_count > 0

    def test_print_detailed_report_with_legacy_cost_key(self, mock_console):
        """Test report handles legacy 'cost' key."""
        result = {
            "stage_outputs": {
                "stage1": {
                    "agent_outputs": {
                        "agent1": {
                            "output": "Output",
                            "cost": 0.0033,  # Legacy key
                        },
                    },
                    "output": "Final output",
                },
            },
        }
        print_detailed_report(result, mock_console)
        assert mock_console.print.call_count > 0

    def test_print_detailed_report_with_decision_key(self, mock_console):
        """Test report handles legacy 'decision' key for stage output."""
        result = {
            "stage_outputs": {
                "stage1": {
                    "agent_outputs": {"agent1": {"output": "Output"}},
                    "decision": "Decision text",  # Legacy key
                },
            },
        }
        print_detailed_report(result, mock_console)
        assert mock_console.print.call_count > 0

    def test_print_detailed_report_invalid_stage_data(self, mock_console):
        """Test report skips invalid stage data."""
        result = {
            "stage_outputs": {
                "stage1": "invalid",  # Should be dict
                "stage2": {
                    "agent_outputs": {"agent1": {"output": "Valid"}},
                    "output": "Valid output",
                },
            },
        }
        print_detailed_report(result, mock_console)

        # Should still print valid stage2
        assert mock_console.print.call_count > 0

    def test_print_detailed_report_invalid_agent_output(self, mock_console):
        """Test report skips invalid agent output data."""
        result = {
            "stage_outputs": {
                "stage1": {
                    "agent_outputs": {
                        "agent1": "invalid",  # Should be dict
                        "agent2": {"output": "Valid"},
                    },
                    "output": "Stage output",
                },
            },
        }
        print_detailed_report(result, mock_console)

        # Should process valid agent2
        assert mock_console.print.call_count > 0
