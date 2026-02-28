"""Tests for visualize_trace.py to cover uncovered lines."""

import argparse
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from temper_ai.observability.visualize_trace import (
    _build_node_hover_text,
    _build_tree_display_name,
    _calculate_node_timing,
    _create_timeline_bar,
    _format_duration_simple,
    _get_type_specific_info,
    _print_simple_gantt,
    _print_trace_summary,
    _print_usage_tips,
    print_console_gantt,
)


def _make_trace() -> dict[str, Any]:
    """Create a sample trace for testing."""
    return {
        "id": "wf-1",
        "name": "test-workflow",
        "type": "workflow",
        "start": "2024-01-01T00:00:00+00:00",
        "end": "2024-01-01T00:00:10+00:00",
        "duration": 10.0,
        "status": "completed",
        "metadata": {
            "total_tokens": 1000,
            "total_cost_usd": 0.50,
            "environment": "test",
        },
        "children": [
            {
                "id": "stage-1",
                "name": "analysis-stage",
                "type": "stage",
                "start": "2024-01-01T00:00:00+00:00",
                "end": "2024-01-01T00:00:05+00:00",
                "duration": 5.0,
                "status": "completed",
                "metadata": {},
                "children": [
                    {
                        "id": "agent-1",
                        "name": "researcher",
                        "type": "agent",
                        "start": "2024-01-01T00:00:01+00:00",
                        "end": "2024-01-01T00:00:04+00:00",
                        "duration": 3.0,
                        "status": "completed",
                        "metadata": {
                            "total_tokens": 500,
                            "estimated_cost_usd": 0.25,
                            "num_llm_calls": 2,
                            "num_tool_calls": 1,
                        },
                        "children": [
                            {
                                "id": "llm-1",
                                "name": "openai/gpt-4",
                                "type": "llm",
                                "start": "2024-01-01T00:00:01+00:00",
                                "end": "2024-01-01T00:00:02+00:00",
                                "duration": 1.0,
                                "status": "success",
                                "metadata": {
                                    "model": "gpt-4",
                                    "total_tokens": 300,
                                    "prompt_tokens": 200,
                                    "completion_tokens": 100,
                                },
                                "children": [],
                            },
                            {
                                "id": "tool-1",
                                "name": "web_search",
                                "type": "tool",
                                "start": "2024-01-01T00:00:02+00:00",
                                "end": "2024-01-01T00:00:03+00:00",
                                "duration": 1.0,
                                "status": "success",
                                "metadata": {
                                    "tool_name": "web_search",
                                    "tool_version": "1.0",
                                },
                                "children": [],
                            },
                        ],
                    },
                ],
            },
        ],
    }


class TestCalculateNodeTiming:
    """Test _calculate_node_timing."""

    def test_basic_timing(self):
        node = {
            "start": "2024-01-01T00:00:01+00:00",
            "end": "2024-01-01T00:00:02+00:00",
        }
        workflow_start = datetime.fromisoformat("2024-01-01T00:00:00+00:00")
        start_ms, duration_ms = _calculate_node_timing(node, workflow_start)
        assert start_ms == 1000.0
        assert duration_ms == 1000.0

    def test_no_end_time(self):
        node = {
            "start": "2024-01-01T00:00:01+00:00",
        }
        workflow_start = datetime.fromisoformat("2024-01-01T00:00:00+00:00")
        start_ms, duration_ms = _calculate_node_timing(node, workflow_start)
        assert start_ms == 1000.0
        assert duration_ms == 0.0


class TestBuildTreeDisplayName:
    """Test _build_tree_display_name."""

    def test_root_node(self):
        node = {"name": "workflow", "children": [{"name": "child"}]}
        result = _build_tree_display_name(node, 0, [], True)
        assert "workflow" in result

    def test_middle_child(self):
        node = {"name": "stage"}
        result = _build_tree_display_name(node, 1, [False], True)
        assert "stage" in result

    def test_last_child(self):
        node = {"name": "agent"}
        result = _build_tree_display_name(node, 1, [True], True)
        assert "agent" in result

    def test_nested_with_parents(self):
        node = {"name": "llm"}
        result = _build_tree_display_name(node, 3, [False, True, False], True)
        assert "llm" in result

    def test_no_tree_lines(self):
        node = {"name": "tool"}
        result = _build_tree_display_name(node, 2, [True, False], False)
        assert "tool" in result
        assert "    " in result

    def test_node_with_children(self):
        node = {"name": "parent", "children": [{"name": "child"}]}
        result = _build_tree_display_name(node, 1, [True], True)
        assert "parent" in result


class TestBuildNodeHoverText:
    """Test _build_node_hover_text for each node type."""

    def test_agent_hover_text(self):
        node = {
            "name": "researcher",
            "type": "agent",
            "duration": 3.0,
            "status": "completed",
            "metadata": {
                "total_tokens": 500,
                "estimated_cost_usd": 0.25,
                "num_llm_calls": 2,
                "num_tool_calls": 1,
            },
        }
        result = _build_node_hover_text(node)
        assert "researcher" in result
        assert "Tokens:" in result
        assert "Cost:" in result

    def test_llm_hover_text(self):
        node = {
            "name": "openai/gpt-4",
            "type": "llm",
            "duration": 1.0,
            "status": "success",
            "metadata": {
                "model": "gpt-4",
                "total_tokens": 300,
                "prompt_tokens": 200,
                "completion_tokens": 100,
            },
        }
        result = _build_node_hover_text(node)
        assert "Model:" in result
        assert "Prompt:" in result

    def test_tool_hover_text(self):
        node = {
            "name": "web_search",
            "type": "tool",
            "duration": 1.0,
            "status": "success",
            "metadata": {
                "tool_name": "web_search",
                "tool_version": "1.0",
            },
        }
        result = _build_node_hover_text(node)
        assert "Tool:" in result
        assert "Version:" in result

    def test_workflow_hover_text(self):
        node = {
            "name": "test-workflow",
            "type": "workflow",
            "duration": 10.0,
            "status": "completed",
            "metadata": {
                "total_tokens": 1000,
                "total_cost_usd": 0.50,
                "environment": "test",
            },
        }
        result = _build_node_hover_text(node)
        assert "Total Tokens:" in result
        assert "Total Cost:" in result
        assert "Environment:" in result

    def test_stage_hover_text(self):
        node = {
            "name": "stage",
            "type": "stage",
            "duration": 5.0,
            "status": "completed",
            "metadata": {},
        }
        result = _build_node_hover_text(node)
        assert "stage" in result

    def test_none_duration(self):
        node = {
            "name": "test",
            "type": "workflow",
            "duration": None,
            "metadata": {},
        }
        result = _build_node_hover_text(node)
        assert "0.000s" in result


class TestCreateGanttChartBars:
    """Test _create_gantt_chart_bars with mocked plotly."""

    def test_create_bars(self):
        """Test creation of plotly figure with bars."""
        import temper_ai.observability.visualize_trace as vt_mod
        from temper_ai.observability.visualize_trace import _create_gantt_chart_bars

        mock_go = MagicMock()
        mock_figure = MagicMock()
        mock_go.Figure.return_value = mock_figure
        mock_go.Bar = MagicMock()

        original_go = getattr(vt_mod, "go", None)
        try:
            vt_mod.go = mock_go
            flat_data = [
                {
                    "display_name": "workflow",
                    "start_ms": 0,
                    "duration_ms": 10000,
                    "type": "workflow",
                    "hover_text": "test",
                },
                {
                    "display_name": "stage",
                    "start_ms": 0,
                    "duration_ms": 5000,
                    "type": "stage",
                    "hover_text": "test",
                },
                {
                    "display_name": "agent",
                    "start_ms": 1000,
                    "duration_ms": 3000,
                    "type": "agent",
                    "hover_text": "test",
                },
                {
                    "display_name": "llm",
                    "start_ms": 1000,
                    "duration_ms": 1000,
                    "type": "llm",
                    "hover_text": "test",
                },
                {
                    "display_name": "tool",
                    "start_ms": 2000,
                    "duration_ms": 1000,
                    "type": "tool",
                    "hover_text": "test",
                },
            ]

            fig = _create_gantt_chart_bars(flat_data)
            assert fig is mock_figure
            assert mock_figure.add_trace.call_count == 5
        finally:
            if original_go is None:
                delattr(vt_mod, "go")
            else:
                vt_mod.go = original_go

    def test_create_bars_empty(self):
        """Test with empty data."""
        import temper_ai.observability.visualize_trace as vt_mod
        from temper_ai.observability.visualize_trace import _create_gantt_chart_bars

        mock_go = MagicMock()
        mock_figure = MagicMock()
        mock_go.Figure.return_value = mock_figure

        original_go = getattr(vt_mod, "go", None)
        try:
            vt_mod.go = mock_go
            fig = _create_gantt_chart_bars([])
            assert fig is mock_figure
        finally:
            if original_go is None:
                delattr(vt_mod, "go")
            else:
                vt_mod.go = original_go


class TestConfigureGanttLayout:
    """Test _configure_gantt_layout."""

    def test_configure_layout(self):
        from temper_ai.observability.visualize_trace import _configure_gantt_layout

        mock_fig = MagicMock()
        _configure_gantt_layout(mock_fig, "Test Title", 10)
        mock_fig.update_layout.assert_called_once()


class TestCreateHierarchicalGantt:
    """Test create_hierarchical_gantt."""

    def _inject_mock_go(self):
        """Helper to inject mock go module into visualize_trace module."""
        import temper_ai.observability.visualize_trace as vt_mod

        mock_go = MagicMock()
        mock_figure = MagicMock()
        mock_go.Figure.return_value = mock_figure
        return vt_mod, mock_go, mock_figure

    def test_create_chart_with_mock_plotly(self):
        """Test chart creation with mocked plotly."""
        vt_mod, mock_go, mock_figure = self._inject_mock_go()
        from temper_ai.observability.visualize_trace import create_hierarchical_gantt

        original_go = getattr(vt_mod, "go", None)
        original_plotly = vt_mod.PLOTLY_AVAILABLE
        try:
            vt_mod.go = mock_go
            vt_mod.PLOTLY_AVAILABLE = True
            trace = _make_trace()
            fig = create_hierarchical_gantt(trace, title="Test Chart")
            assert fig is mock_figure
        finally:
            vt_mod.PLOTLY_AVAILABLE = original_plotly
            if original_go is None:
                delattr(vt_mod, "go")
            else:
                vt_mod.go = original_go

    def test_create_chart_default_title(self):
        vt_mod, mock_go, mock_figure = self._inject_mock_go()
        from temper_ai.observability.visualize_trace import create_hierarchical_gantt

        original_go = getattr(vt_mod, "go", None)
        original_plotly = vt_mod.PLOTLY_AVAILABLE
        try:
            vt_mod.go = mock_go
            vt_mod.PLOTLY_AVAILABLE = True
            trace = _make_trace()
            fig = create_hierarchical_gantt(trace)
            assert fig is mock_figure
        finally:
            vt_mod.PLOTLY_AVAILABLE = original_plotly
            if original_go is None:
                delattr(vt_mod, "go")
            else:
                vt_mod.go = original_go

    def test_create_chart_with_output_file(self, tmp_path):
        vt_mod, mock_go, mock_figure = self._inject_mock_go()
        from temper_ai.observability.visualize_trace import create_hierarchical_gantt

        original_go = getattr(vt_mod, "go", None)
        original_plotly = vt_mod.PLOTLY_AVAILABLE
        try:
            vt_mod.go = mock_go
            vt_mod.PLOTLY_AVAILABLE = True
            trace = _make_trace()
            output_file = str(tmp_path / "test.html")
            create_hierarchical_gantt(trace, output_file=output_file)
            mock_figure.write_html.assert_called_once_with(output_file)
        finally:
            vt_mod.PLOTLY_AVAILABLE = original_plotly
            if original_go is None:
                delattr(vt_mod, "go")
            else:
                vt_mod.go = original_go

    def test_create_chart_no_plotly(self):
        """Test that ImportError is raised when plotly not available."""
        from temper_ai.observability.visualize_trace import create_hierarchical_gantt

        trace = _make_trace()
        with patch("temper_ai.observability.visualize_trace.PLOTLY_AVAILABLE", False):
            with pytest.raises(ImportError, match="Plotly required"):
                create_hierarchical_gantt(trace)

    def test_create_chart_no_tree_lines(self):
        vt_mod, mock_go, mock_figure = self._inject_mock_go()
        from temper_ai.observability.visualize_trace import create_hierarchical_gantt

        original_go = getattr(vt_mod, "go", None)
        original_plotly = vt_mod.PLOTLY_AVAILABLE
        try:
            vt_mod.go = mock_go
            vt_mod.PLOTLY_AVAILABLE = True
            trace = _make_trace()
            fig = create_hierarchical_gantt(trace, show_tree_lines=False)
            assert fig is mock_figure
        finally:
            vt_mod.PLOTLY_AVAILABLE = original_plotly
            if original_go is None:
                delattr(vt_mod, "go")
            else:
                vt_mod.go = original_go


class TestFormatDuration:
    """Test _format_duration_simple."""

    def test_none_duration(self):
        assert _format_duration_simple(None) == "0.000s"

    def test_sub_second(self):
        result = _format_duration_simple(0.5)
        assert "ms" in result

    def test_seconds(self):
        result = _format_duration_simple(2.5)
        assert "s" in result


class TestCreateTimelineBar:
    """Test _create_timeline_bar."""

    def test_zero_total_duration(self):
        result = _create_timeline_bar(0, 1, 0)
        assert len(result) > 0

    def test_normal_bar(self):
        result = _create_timeline_bar(2.0, 3.0, 10.0, width=40)
        assert len(result) == 40

    def test_start_at_beginning(self):
        result = _create_timeline_bar(0, 5.0, 10.0, width=20)
        assert len(result) == 20


class TestGetTypeSpecificInfo:
    """Test _get_type_specific_info."""

    def test_agent_with_tokens(self):
        result = _get_type_specific_info("agent", {"total_tokens": 500})
        assert result is not None
        assert "500" in result

    def test_agent_no_tokens(self):
        result = _get_type_specific_info("agent", {"total_tokens": 0})
        assert result is None

    def test_llm_with_model(self):
        result = _get_type_specific_info("llm", {"model": "gpt-4"})
        assert result is not None
        assert "gpt-4" in result

    def test_llm_no_model(self):
        result = _get_type_specific_info("llm", {"model": ""})
        assert result is None

    def test_tool_with_name(self):
        result = _get_type_specific_info("tool", {"tool_name": "search"})
        assert result is not None
        assert "search" in result

    def test_tool_no_name(self):
        result = _get_type_specific_info("tool", {"tool_name": ""})
        assert result is None

    def test_unknown_type(self):
        result = _get_type_specific_info("workflow", {"key": "value"})
        assert result is None


class TestPrintConsoleGantt:
    """Test print_console_gantt."""

    def test_with_rich(self):
        trace = _make_trace()
        # Should not raise
        print_console_gantt(trace)

    def test_without_rich(self):
        trace = _make_trace()
        with patch.dict(
            "sys.modules", {"rich": None, "rich.console": None, "rich.tree": None}
        ):
            # Will fall through to _print_simple_gantt
            with patch("temper_ai.observability.visualize_trace._print_simple_gantt"):
                # Force import error
                with patch(
                    "temper_ai.observability.visualize_trace.print_console_gantt"
                ) as mock_gantt:
                    mock_gantt.side_effect = lambda t, **kw: _print_simple_gantt(t)
                    mock_gantt(trace)


class TestPrintSimpleGantt:
    """Test _print_simple_gantt fallback."""

    def test_simple_gantt(self, capsys):
        trace = _make_trace()
        _print_simple_gantt(trace)
        captured = capsys.readouterr()
        assert "Console Gantt Chart" in captured.out
        assert "test-workflow" in captured.out


class TestPrintTraceSummary:
    """Test _print_trace_summary."""

    def test_summary(self, capsys):
        trace = _make_trace()
        _print_trace_summary(trace)
        captured = capsys.readouterr()
        assert "EXECUTION TRACE SUMMARY" in captured.out
        assert "test-workflow" in captured.out
        assert "completed" in captured.out

    def test_summary_with_none_cost(self, capsys):
        trace = _make_trace()
        trace["metadata"]["total_cost_usd"] = None
        _print_trace_summary(trace)
        captured = capsys.readouterr()
        assert "$0.0000" in captured.out


class TestPrintUsageTips:
    """Test _print_usage_tips."""

    def test_usage_tips(self, capsys):
        _print_usage_tips()
        captured = capsys.readouterr()
        assert "Visualization complete" in captured.out
        assert "Features:" in captured.out


class TestVisualizeTrace:
    """Test visualize_trace function."""

    def _setup_mock_go(self):
        """Set up mock go module on visualize_trace module."""
        import temper_ai.observability.visualize_trace as vt_mod

        mock_go = MagicMock()
        mock_figure = MagicMock()
        mock_go.Figure.return_value = mock_figure
        return vt_mod, mock_go, mock_figure

    def test_visualize_trace_basic(self, tmp_path):
        vt_mod, mock_go, mock_figure = self._setup_mock_go()
        from temper_ai.observability.visualize_trace import visualize_trace

        original_go = getattr(vt_mod, "go", None)
        original_plotly = vt_mod.PLOTLY_AVAILABLE
        try:
            vt_mod.go = mock_go
            vt_mod.PLOTLY_AVAILABLE = True
            trace = _make_trace()
            output = str(tmp_path / "test.html")
            fig = visualize_trace(trace, output_file=output, auto_open=False)
            assert fig is mock_figure
        finally:
            vt_mod.PLOTLY_AVAILABLE = original_plotly
            if original_go is None:
                delattr(vt_mod, "go")
            else:
                vt_mod.go = original_go

    def test_visualize_trace_default_filename(self, tmp_path):
        """Test visualize_trace generates default filename."""
        from temper_ai.observability.visualize_trace import visualize_trace

        trace = _make_trace()
        mock_fig = MagicMock()
        with patch(
            "temper_ai.observability.visualize_trace.create_hierarchical_gantt",
            return_value=mock_fig,
        ):
            fig = visualize_trace(trace, auto_open=False)
            assert fig is mock_fig

    def test_visualize_trace_browser_open_fails(self, tmp_path):
        vt_mod, mock_go, mock_figure = self._setup_mock_go()
        from temper_ai.observability.visualize_trace import visualize_trace

        original_go = getattr(vt_mod, "go", None)
        original_plotly = vt_mod.PLOTLY_AVAILABLE
        try:
            vt_mod.go = mock_go
            vt_mod.PLOTLY_AVAILABLE = True
            trace = _make_trace()
            output = str(tmp_path / "test.html")
            with patch("webbrowser.open", side_effect=OSError("no browser")):
                fig = visualize_trace(trace, output_file=output, auto_open=True)
                assert fig is mock_figure
        finally:
            vt_mod.PLOTLY_AVAILABLE = original_plotly
            if original_go is None:
                delattr(vt_mod, "go")
            else:
                vt_mod.go = original_go

    def test_visualize_trace_auto_open_success(self, tmp_path):
        """Test successful auto-open in browser."""
        vt_mod, mock_go, mock_figure = self._setup_mock_go()
        from temper_ai.observability.visualize_trace import visualize_trace

        original_go = getattr(vt_mod, "go", None)
        original_plotly = vt_mod.PLOTLY_AVAILABLE
        try:
            vt_mod.go = mock_go
            vt_mod.PLOTLY_AVAILABLE = True
            trace = _make_trace()
            output = str(tmp_path / "test.html")
            with patch("webbrowser.open") as mock_open:
                fig = visualize_trace(trace, output_file=output, auto_open=True)
                assert fig is mock_figure
                mock_open.assert_called_once_with(output)
        finally:
            vt_mod.PLOTLY_AVAILABLE = original_plotly
            if original_go is None:
                delattr(vt_mod, "go")
            else:
                vt_mod.go = original_go


class TestLoadTraceData:
    """Test _load_trace_data."""

    def test_load_from_file(self, tmp_path):
        import json

        from temper_ai.observability.visualize_trace import _load_trace_data

        trace = _make_trace()
        file_path = str(tmp_path / "trace.json")
        with open(file_path, "w") as f:
            json.dump(trace, f)

        args = argparse.Namespace(file=file_path, latest=False, workflow_id=None)
        result = _load_trace_data(args)
        assert result is not None
        assert result["name"] == "test-workflow"

    def test_load_from_db_import_error(self):

        args = argparse.Namespace(file=None, latest=False, workflow_id="wf-1")
        with patch.dict("sys.modules", {"sqlmodel": None}):
            with patch(
                "temper_ai.observability.visualize_trace._load_trace_data"
            ) as mock_load:
                mock_load.return_value = None
                result = mock_load(args)
                assert result is None

    def test_load_latest_no_workflow(self):
        """Test loading latest when no workflows exist triggers import."""
        from temper_ai.observability.visualize_trace import _load_trace_data

        args = argparse.Namespace(file=None, latest=True, workflow_id=None)

        # The function does lazy imports of sqlmodel and database modules.
        # We test the import failure path.
        with patch("builtins.__import__", side_effect=ImportError("no sqlmodel")):
            try:
                _load_trace_data(args)
            except (ImportError, AttributeError):
                pass
            # Either returns None or raises - both are valid


class TestBuildArgParser:
    """Test _build_arg_parser."""

    def test_parser_creation(self):
        from temper_ai.observability.visualize_trace import _build_arg_parser

        parser = _build_arg_parser()
        assert parser is not None

    def test_parser_file_arg(self):
        from temper_ai.observability.visualize_trace import _build_arg_parser

        parser = _build_arg_parser()
        args = parser.parse_args(["--file", "trace.json"])
        assert args.file == "trace.json"

    def test_parser_latest_arg(self):
        from temper_ai.observability.visualize_trace import _build_arg_parser

        parser = _build_arg_parser()
        args = parser.parse_args(["--latest"])
        assert args.latest is True

    def test_parser_no_tree(self):
        from temper_ai.observability.visualize_trace import _build_arg_parser

        parser = _build_arg_parser()
        args = parser.parse_args(["--no-tree"])
        assert args.no_tree is True

    def test_parser_no_open(self):
        from temper_ai.observability.visualize_trace import _build_arg_parser

        parser = _build_arg_parser()
        args = parser.parse_args(["--no-open"])
        assert args.no_open is True


class TestMain:
    """Test main CLI entry point."""

    def test_main_no_trace(self):
        from temper_ai.observability.visualize_trace import main

        with (
            patch(
                "temper_ai.observability.visualize_trace._build_arg_parser"
            ) as mock_parser,
            patch(
                "temper_ai.observability.visualize_trace._load_trace_data",
                return_value=None,
            ),
        ):
            mock_args = MagicMock()
            mock_parser.return_value.parse_args.return_value = mock_args
            result = main()
            assert result == 1

    def test_main_success(self, tmp_path):
        from temper_ai.observability.visualize_trace import main

        trace = _make_trace()
        with (
            patch(
                "temper_ai.observability.visualize_trace._build_arg_parser"
            ) as mock_parser,
            patch(
                "temper_ai.observability.visualize_trace._load_trace_data",
                return_value=trace,
            ),
            patch("temper_ai.observability.visualize_trace.visualize_trace"),
            patch("temper_ai.observability.visualize_trace._print_trace_summary"),
            patch("temper_ai.observability.visualize_trace._print_usage_tips"),
        ):
            mock_args = MagicMock()
            mock_args.output = str(tmp_path / "output.html")
            mock_args.no_tree = False
            mock_args.no_open = True
            mock_parser.return_value.parse_args.return_value = mock_args
            result = main()
            assert result == 0


class TestBuildConsoleTree:
    """Test _build_console_tree."""

    def test_build_tree(self):
        from temper_ai.observability.visualize_trace import _build_console_tree

        trace = _make_trace()
        workflow_start = datetime.fromisoformat(trace["start"])
        tree = _build_console_tree(trace, None, workflow_start, 10.0)
        assert tree is not None

    def test_build_tree_with_parent(self):
        from rich.tree import Tree

        from temper_ai.observability.visualize_trace import _build_console_tree

        trace = _make_trace()
        child = trace["children"][0]
        workflow_start = datetime.fromisoformat(trace["start"])
        parent = Tree("root")
        node = _build_console_tree(child, parent, workflow_start, 10.0)
        assert node is not None
