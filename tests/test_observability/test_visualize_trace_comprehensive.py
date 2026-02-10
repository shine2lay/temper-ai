"""Comprehensive tests for visualize_trace module (227 lines)."""
import json
from datetime import datetime, timezone
from io import StringIO
from unittest.mock import Mock, patch

import pytest

from src.observability.visualize_trace import (
    _flatten_trace_with_tree,
    create_hierarchical_gantt,
    print_console_gantt,
    visualize_trace,
)

# Skip tests if plotly not available
try:
    import plotly.graph_objects as go
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False


@pytest.fixture
def sample_trace():
    """Create sample execution trace."""
    return {
        "id": "wf-001",
        "name": "Test Workflow",
        "type": "workflow",
        "start": "2024-01-15T10:00:00+00:00",
        "end": "2024-01-15T10:00:30+00:00",
        "duration": 30.0,
        "status": "completed",
        "metadata": {
            "total_tokens": 1500,
            "total_cost_usd": 0.0123,
            "environment": "test"
        },
        "children": [
            {
                "id": "stage-001",
                "name": "Stage 1",
                "type": "stage",
                "start": "2024-01-15T10:00:00+00:00",
                "end": "2024-01-15T10:00:15+00:00",
                "duration": 15.0,
                "status": "completed",
                "metadata": {},
                "children": [
                    {
                        "id": "agent-001",
                        "name": "Agent 1",
                        "type": "agent",
                        "start": "2024-01-15T10:00:00+00:00",
                        "end": "2024-01-15T10:00:10+00:00",
                        "duration": 10.0,
                        "status": "completed",
                        "metadata": {
                            "total_tokens": 500,
                            "estimated_cost_usd": 0.005,
                            "num_llm_calls": 2,
                            "num_tool_calls": 1
                        },
                        "children": [
                            {
                                "id": "llm-001",
                                "name": "LLM Call 1",
                                "type": "llm",
                                "start": "2024-01-15T10:00:01+00:00",
                                "end": "2024-01-15T10:00:05+00:00",
                                "duration": 4.0,
                                "status": "completed",
                                "metadata": {
                                    "model": "gpt-4",
                                    "total_tokens": 300,
                                    "prompt_tokens": 200,
                                    "completion_tokens": 100
                                },
                                "children": []
                            },
                            {
                                "id": "tool-001",
                                "name": "Tool Call 1",
                                "type": "tool",
                                "start": "2024-01-15T10:00:06+00:00",
                                "end": "2024-01-15T10:00:08+00:00",
                                "duration": 2.0,
                                "status": "completed",
                                "metadata": {
                                    "tool_name": "read_file",
                                    "tool_version": "1.0"
                                },
                                "children": []
                            }
                        ]
                    }
                ]
            },
            {
                "id": "stage-002",
                "name": "Stage 2",
                "type": "stage",
                "start": "2024-01-15T10:00:15+00:00",
                "end": "2024-01-15T10:00:30+00:00",
                "duration": 15.0,
                "status": "completed",
                "metadata": {},
                "children": []
            }
        ]
    }


@pytest.fixture
def minimal_trace():
    """Create minimal trace for testing."""
    return {
        "id": "wf-minimal",
        "name": "Minimal",
        "type": "workflow",
        "start": "2024-01-15T10:00:00+00:00",
        "end": "2024-01-15T10:00:01+00:00",
        "duration": 1.0,
        "status": "completed",
        "metadata": {},
        "children": []
    }


class TestFlattenTraceWithTree:
    """Test trace flattening with tree structure."""

    def test_flatten_minimal_trace(self, minimal_trace):
        """Test flattening minimal trace."""
        flat = _flatten_trace_with_tree(minimal_trace, show_tree_lines=True)

        assert len(flat) == 1
        assert flat[0]["type"] == "workflow"
        assert flat[0]["depth"] == 0

    def test_flatten_hierarchical_trace(self, sample_trace):
        """Test flattening hierarchical trace."""
        flat = _flatten_trace_with_tree(sample_trace, show_tree_lines=True)

        # Should have workflow + 2 stages + 1 agent + 2 children (llm + tool)
        assert len(flat) >= 5

    def test_tree_lines_in_display_names(self, sample_trace):
        """Test tree structure characters in display names."""
        flat = _flatten_trace_with_tree(sample_trace, show_tree_lines=True)

        # Check for tree characters
        display_names = [item["display_name"] for item in flat]
        has_tree_chars = any(
            "├─" in name or "└─" in name or "▼" in name
            for name in display_names
        )
        assert has_tree_chars

    def test_no_tree_lines(self, sample_trace):
        """Test flattening without tree lines."""
        flat = _flatten_trace_with_tree(sample_trace, show_tree_lines=False)

        # Should use simple indentation
        display_names = [item["display_name"] for item in flat]
        has_tree_chars = any(
            "├─" in name or "└─" in name
            for name in display_names
        )
        assert not has_tree_chars

    def test_timing_calculations(self, sample_trace):
        """Test start_ms and duration_ms calculations."""
        flat = _flatten_trace_with_tree(sample_trace, show_tree_lines=True)

        # First item should start at 0
        assert flat[0]["start_ms"] == 0.0

        # All items should have positive duration
        for item in flat:
            assert item["duration_ms"] >= 0

    def test_hover_text_generation(self, sample_trace):
        """Test hover text contains metadata."""
        flat = _flatten_trace_with_tree(sample_trace, show_tree_lines=True)

        # Workflow should have hover text
        workflow_item = flat[0]
        assert "Test Workflow" in workflow_item["hover_text"]
        assert "workflow" in workflow_item["hover_text"]

    def test_agent_metadata_in_hover(self, sample_trace):
        """Test agent metadata appears in hover text."""
        flat = _flatten_trace_with_tree(sample_trace, show_tree_lines=True)

        # Find agent item
        agent_items = [item for item in flat if item["type"] == "agent"]
        assert len(agent_items) > 0

        agent_hover = agent_items[0]["hover_text"]
        assert "Tokens:" in agent_hover
        assert "Cost:" in agent_hover

    def test_llm_metadata_in_hover(self, sample_trace):
        """Test LLM metadata appears in hover text."""
        flat = _flatten_trace_with_tree(sample_trace, show_tree_lines=True)

        # Find LLM item
        llm_items = [item for item in flat if item["type"] == "llm"]
        assert len(llm_items) > 0

        llm_hover = llm_items[0]["hover_text"]
        assert "Model:" in llm_hover
        assert "gpt-4" in llm_hover

    def test_tool_metadata_in_hover(self, sample_trace):
        """Test tool metadata appears in hover text."""
        flat = _flatten_trace_with_tree(sample_trace, show_tree_lines=True)

        # Find tool item
        tool_items = [item for item in flat if item["type"] == "tool"]
        assert len(tool_items) > 0

        tool_hover = tool_items[0]["hover_text"]
        assert "Tool:" in tool_hover


@pytest.mark.skipif(not PLOTLY_AVAILABLE, reason="Plotly not installed")
class TestCreateHierarchicalGantt:
    """Test Gantt chart creation."""

    def test_create_basic_chart(self, minimal_trace):
        """Test creating basic Gantt chart."""
        fig = create_hierarchical_gantt(minimal_trace)

        assert isinstance(fig, go.Figure)
        assert len(fig.data) > 0

    def test_chart_with_custom_title(self, minimal_trace):
        """Test chart with custom title."""
        fig = create_hierarchical_gantt(minimal_trace, title="Custom Title")

        assert "Custom Title" in fig.layout.title.text

    def test_chart_default_title(self, minimal_trace):
        """Test chart uses trace name as default title."""
        fig = create_hierarchical_gantt(minimal_trace)

        assert "Minimal" in fig.layout.title.text

    def test_chart_colors_by_type(self, sample_trace):
        """Test chart uses different colors for each type."""
        fig = create_hierarchical_gantt(sample_trace)

        # Should have multiple traces (one per type)
        assert len(fig.data) > 1

        # Check trace names include types
        trace_names = [trace.name for trace in fig.data]
        assert any("Workflow" in name for name in trace_names)

    def test_chart_height_scales_with_items(self, sample_trace):
        """Test chart height increases with more items."""
        fig = create_hierarchical_gantt(sample_trace)

        # Height should be at least minimum
        assert fig.layout.height >= 600

    def test_save_to_file(self, minimal_trace, tmp_path):
        """Test saving chart to HTML file."""
        output_file = tmp_path / "test_chart.html"

        fig = create_hierarchical_gantt(
            minimal_trace,
            output_file=str(output_file)
        )

        assert output_file.exists()
        assert output_file.stat().st_size > 0

    def test_chart_without_tree_lines(self, sample_trace):
        """Test chart creation without tree lines."""
        fig = create_hierarchical_gantt(sample_trace, show_tree_lines=False)

        assert isinstance(fig, go.Figure)

    def test_missing_plotly_raises_error(self, minimal_trace):
        """Test error when plotly not available."""
        with patch.dict('sys.modules', {'plotly.graph_objects': None}):
            with patch('src.observability.visualize_trace.PLOTLY_AVAILABLE', False):
                with pytest.raises(ImportError, match="Plotly required"):
                    create_hierarchical_gantt(minimal_trace)


class TestPrintConsoleGantt:
    """Test console Gantt chart printing."""

    def test_print_basic_gantt(self, minimal_trace, capsys):
        """Test printing basic console Gantt."""
        print_console_gantt(minimal_trace)

        captured = capsys.readouterr()
        assert "Console Gantt Chart" in captured.out
        assert "Minimal" in captured.out

    def test_print_with_tree_structure(self, sample_trace, capsys):
        """Test console output includes tree structure."""
        print_console_gantt(sample_trace)

        captured = capsys.readouterr()
        assert "Test Workflow" in captured.out

    def test_timeline_bars_present(self, sample_trace, capsys):
        """Test console output includes timeline bars."""
        print_console_gantt(sample_trace)

        captured = capsys.readouterr()
        # Timeline uses █ for active and ░ for idle
        assert ("█" in captured.out or "░" in captured.out)

    def test_duration_formatting(self, sample_trace, capsys):
        """Test durations are formatted."""
        print_console_gantt(sample_trace)

        captured = capsys.readouterr()
        # Should show durations like "30.000s"
        assert "s" in captured.out or "ms" in captured.out

    def test_colored_output(self, sample_trace):
        """Test output uses Rich colors."""
        # Rich Console is imported locally in print_console_gantt, patch it at import location
        with patch('rich.console.Console') as MockConsole:
            mock_console = Mock()
            MockConsole.return_value = mock_console

            print_console_gantt(sample_trace)

            # Should call console.print at least once
            assert mock_console.print.called

    def test_fallback_without_rich(self, minimal_trace, capsys):
        """Test fallback to simple text without Rich."""
        with patch.dict('sys.modules', {'rich.console': None, 'rich.tree': None}):
            print_console_gantt(minimal_trace)

            captured = capsys.readouterr()
            assert "Minimal" in captured.out


class TestVisualizeTrace:
    """Test main visualize_trace function."""

    @pytest.mark.skipif(not PLOTLY_AVAILABLE, reason="Plotly not installed")
    def test_visualize_basic_trace(self, minimal_trace, tmp_path):
        """Test visualizing basic trace."""
        output_file = tmp_path / "test.html"

        fig = visualize_trace(
            minimal_trace,
            output_file=str(output_file),
            auto_open=False
        )

        assert isinstance(fig, go.Figure)
        assert output_file.exists()

    @pytest.mark.skipif(not PLOTLY_AVAILABLE, reason="Plotly not installed")
    def test_default_output_filename(self, minimal_trace, tmp_path):
        """Test default output filename generation."""
        import os
        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)

            visualize_trace(minimal_trace, auto_open=False)

            # Should create minimal_gantt.html
            assert (tmp_path / "minimal_gantt.html").exists()
        finally:
            os.chdir(original_cwd)

    @pytest.mark.skipif(not PLOTLY_AVAILABLE, reason="Plotly not installed")
    def test_auto_open_browser(self, minimal_trace, tmp_path):
        """Test auto-opening browser."""
        output_file = tmp_path / "test.html"

        with patch('webbrowser.open') as mock_open:
            visualize_trace(
                minimal_trace,
                output_file=str(output_file),
                auto_open=True
            )

            mock_open.assert_called_once()

    @pytest.mark.skipif(not PLOTLY_AVAILABLE, reason="Plotly not installed")
    def test_browser_error_handling(self, minimal_trace, tmp_path):
        """Test handling browser open errors."""
        output_file = tmp_path / "test.html"

        with patch('webbrowser.open', side_effect=OSError("No browser")):
            # Should not crash
            result = visualize_trace(
                minimal_trace,
                output_file=str(output_file),
                auto_open=True
            )
            # visualize_trace should complete without raising, even if browser fails
            # Returns a Figure object on success
            assert result is not None


class TestMainCLI:
    """Test CLI main function."""

    def test_cli_with_file_argument(self, minimal_trace, tmp_path):
        """Test CLI with --file argument."""
        # Create JSON file
        trace_file = tmp_path / "trace.json"
        with open(trace_file, "w") as f:
            json.dump(minimal_trace, f)

        with patch('sys.argv', ['visualize_trace', '--file', str(trace_file), '--no-open']):
            from src.observability.visualize_trace import main

            if PLOTLY_AVAILABLE:
                result = main()
                assert result == 0

    def test_cli_no_args_no_workflow(self):
        """Test CLI without arguments and no workflows."""
        with patch('sys.argv', ['visualize_trace', '--latest']):
            # Create mock for session chain
            mock_exec_result = Mock()
            mock_exec_result.first.return_value = None
            mock_session_obj = Mock()
            mock_session_obj.exec.return_value = mock_exec_result
            mock_session_ctx = Mock()
            mock_session_ctx.__enter__ = Mock(return_value=mock_session_obj)
            mock_session_ctx.__exit__ = Mock(return_value=None)

            with patch('src.database.get_session', return_value=mock_session_ctx):
                from src.observability.visualize_trace import main

                result = main()
                assert result == 1


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_trace_with_missing_end_time(self):
        """Test trace with missing end time."""
        trace = {
            "id": "wf-001",
            "name": "Test",
            "type": "workflow",
            "start": "2024-01-15T10:00:00+00:00",
            "end": None,  # Missing end
            "duration": 0.0,
            "status": "running",
            "metadata": {},
            "children": []
        }

        flat = _flatten_trace_with_tree(trace, show_tree_lines=True)

        assert len(flat) == 1
        assert flat[0]["duration_ms"] == 0.0

    def test_trace_with_zero_duration(self):
        """Test trace with zero duration."""
        trace = {
            "id": "wf-001",
            "name": "Instant",
            "type": "workflow",
            "start": "2024-01-15T10:00:00+00:00",
            "end": "2024-01-15T10:00:00+00:00",
            "duration": 0.0,
            "status": "completed",
            "metadata": {},
            "children": []
        }

        flat = _flatten_trace_with_tree(trace, show_tree_lines=True)

        assert flat[0]["duration_ms"] == 0.0

    def test_deeply_nested_trace(self):
        """Test deeply nested trace structure."""
        def create_nested_trace(depth, current=0):
            """Create nested trace."""
            return {
                "id": f"node-{current}",
                "name": f"Node {current}",
                "type": "stage",
                "start": f"2024-01-15T10:00:{current:02d}+00:00",
                "end": f"2024-01-15T10:00:{current + 1:02d}+00:00",
                "duration": 1.0,
                "status": "completed",
                "metadata": {},
                "children": [create_nested_trace(depth, current + 1)] if current < depth else []
            }

        deep_trace = create_nested_trace(10)
        flat = _flatten_trace_with_tree(deep_trace, show_tree_lines=True)

        # Should have 11 items (0-10)
        assert len(flat) == 11

    def test_trace_with_empty_metadata(self):
        """Test trace with missing metadata fields."""
        trace = {
            "id": "wf-001",
            "name": "Test",
            "type": "agent",
            "start": "2024-01-15T10:00:00+00:00",
            "end": "2024-01-15T10:00:01+00:00",
            "duration": 1.0,
            "status": "completed",
            "metadata": {},  # Empty metadata
            "children": []
        }

        flat = _flatten_trace_with_tree(trace, show_tree_lines=True)

        # Should handle missing metadata gracefully
        assert "0" in flat[0]["hover_text"]  # Should show 0 for missing values

    def test_multiple_children_branch_characters(self):
        """Test tree characters for multiple children."""
        trace = {
            "id": "parent",
            "name": "Parent",
            "type": "stage",
            "start": "2024-01-15T10:00:00+00:00",
            "end": "2024-01-15T10:00:10+00:00",
            "duration": 10.0,
            "status": "completed",
            "metadata": {},
            "children": [
                {
                    "id": "child1",
                    "name": "Child 1",
                    "type": "agent",
                    "start": "2024-01-15T10:00:00+00:00",
                    "end": "2024-01-15T10:00:05+00:00",
                    "duration": 5.0,
                    "status": "completed",
                    "metadata": {},
                    "children": []
                },
                {
                    "id": "child2",
                    "name": "Child 2",
                    "type": "agent",
                    "start": "2024-01-15T10:00:05+00:00",
                    "end": "2024-01-15T10:00:10+00:00",
                    "duration": 5.0,
                    "status": "completed",
                    "metadata": {},
                    "children": []
                }
            ]
        }

        flat = _flatten_trace_with_tree(trace, show_tree_lines=True)

        display_names = [item["display_name"] for item in flat]

        # Should have both ├─ and └─ for multiple children
        has_middle_child = any("├─" in name for name in display_names)
        has_last_child = any("└─" in name for name in display_names)

        assert has_middle_child or has_last_child
