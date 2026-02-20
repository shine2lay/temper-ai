"""
Tests for visualize_trace module.

Tests Gantt chart generation, trace flattening, and visualization functions.
"""
from datetime import datetime, timedelta

import pytest

# Check if plotly is available
try:
    import plotly.graph_objects as go
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False

from temper_ai.observability.visualize_trace import (
    _flatten_trace_with_tree,
    create_hierarchical_gantt,
    visualize_trace,
)


# Sample trace data for testing
@pytest.fixture
def simple_trace():
    """Create a simple trace for testing."""
    start = datetime(2024, 1, 1, 12, 0, 0)
    end = datetime(2024, 1, 1, 12, 0, 5)

    return {
        "id": "workflow-1",
        "name": "test_workflow",
        "type": "workflow",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "duration": 5.0,
        "status": "completed",
        "metadata": {},
        "children": []
    }


@pytest.fixture
def nested_trace():
    """Create a nested trace with multiple levels."""
    start = datetime(2024, 1, 1, 12, 0, 0)

    return {
        "id": "workflow-1",
        "name": "complex_workflow",
        "type": "workflow",
        "start": start.isoformat(),
        "end": (start + timedelta(seconds=10)).isoformat(),
        "duration": 10.0,
        "status": "completed",
        "metadata": {},
        "children": [
            {
                "id": "stage-1",
                "name": "stage1",
                "type": "stage",
                "start": (start + timedelta(seconds=1)).isoformat(),
                "end": (start + timedelta(seconds=5)).isoformat(),
                "duration": 4.0,
                "status": "completed",
                "metadata": {},
                "children": [
                    {
                        "id": "agent-1",
                        "name": "agent1",
                        "type": "agent",
                        "start": (start + timedelta(seconds=1)).isoformat(),
                        "end": (start + timedelta(seconds=4)).isoformat(),
                        "duration": 3.0,
                        "status": "completed",
                        "metadata": {},
                        "children": [
                            {
                                "id": "llm-1",
                                "name": "llm_call",
                                "type": "llm",
                                "start": (start + timedelta(seconds=1)).isoformat(),
                                "end": (start + timedelta(seconds=3)).isoformat(),
                                "duration": 2.0,
                                "status": "completed",
                                "metadata": {},
                                "children": []
                            },
                            {
                                "id": "tool-1",
                                "name": "calculator",
                                "type": "tool",
                                "start": (start + timedelta(seconds=3)).isoformat(),
                                "end": (start + timedelta(seconds=4)).isoformat(),
                                "duration": 1.0,
                                "status": "completed",
                                "metadata": {},
                                "children": []
                            }
                        ]
                    }
                ]
            }
        ]
    }


@pytest.mark.skipif(not PLOTLY_AVAILABLE, reason="Plotly not installed")
class TestCreateHierarchicalGantt:
    """Test create_hierarchical_gantt function."""

    def test_create_gantt_simple_trace(self, simple_trace):
        """Test Gantt chart creation with simple trace."""
        fig = create_hierarchical_gantt(simple_trace)

        assert fig is not None
        assert isinstance(fig, go.Figure)
        assert len(fig.data) >= 1
        # Verify the trace contains the workflow name in y-axis labels
        all_y = [y for trace in fig.data if hasattr(trace, 'y') and trace.y for y in trace.y]
        assert any("test_workflow" in str(y) for y in all_y), "Figure should contain workflow name"

    def test_create_gantt_nested_trace(self, nested_trace):
        """Test Gantt chart creation with nested trace."""
        fig = create_hierarchical_gantt(nested_trace)

        assert fig is not None
        assert isinstance(fig, go.Figure)
        # Should have multiple traces for different types
        assert len(fig.data) >= 3  # workflow, stage, agent at minimum

    def test_create_gantt_with_title(self, simple_trace):
        """Test Gantt chart with custom title."""
        fig = create_hierarchical_gantt(simple_trace, title="Custom Title")

        # Title may include additional text like " - Hierarchical Timeline"
        assert "Custom Title" in fig.layout.title.text

    def test_create_gantt_with_tree_lines(self, nested_trace):
        """Test Gantt chart with tree structure lines."""
        fig = create_hierarchical_gantt(nested_trace, show_tree_lines=True)

        assert fig is not None
        # Verify y-axis labels contain tree characters (├─ or └─)
        all_y = [y for trace in fig.data if hasattr(trace, 'y') and trace.y for y in trace.y]
        has_tree = any("\u251c\u2500" in str(y) or "\u2514\u2500" in str(y) for y in all_y)
        assert has_tree, "Y-axis labels should contain tree characters when show_tree_lines=True"

    def test_create_gantt_without_tree_lines(self, nested_trace):
        """Test Gantt chart without tree structure lines."""
        fig = create_hierarchical_gantt(nested_trace, show_tree_lines=False)

        assert fig is not None
        # Verify y-axis labels do NOT contain tree characters
        all_y = [y for trace in fig.data if hasattr(trace, 'y') and trace.y for y in trace.y]
        no_tree = not any("\u251c\u2500" in str(y) or "\u2514\u2500" in str(y) for y in all_y)
        assert no_tree, "Y-axis labels should NOT contain tree characters when show_tree_lines=False"

    def test_create_gantt_colors(self, nested_trace):
        """Test that different types have different colors."""
        fig = create_hierarchical_gantt(nested_trace)

        # Get colors from traces
        colors = set()
        for trace in fig.data:
            if hasattr(trace, 'marker') and trace.marker.color:
                colors.add(trace.marker.color)

        # Should have multiple colors for different types
        assert len(colors) >= 2

    def test_create_gantt_empty_children(self, simple_trace):
        """Test Gantt chart with trace that has empty children."""
        simple_trace["children"] = []
        fig = create_hierarchical_gantt(simple_trace)

        assert fig is not None

    def test_create_gantt_calculates_height(self, nested_trace):
        """Test that chart height is calculated based on items."""
        fig = create_hierarchical_gantt(nested_trace)

        # Height should be proportional to number of items
        assert fig.layout.height >= 600  # Minimum height


class TestFlattenTraceWithTree:
    """Test _flatten_trace_with_tree function."""

    def test_flatten_simple_trace(self, simple_trace):
        """Test flattening a simple trace with no children."""
        result = _flatten_trace_with_tree(simple_trace, show_tree_lines=False)

        assert len(result) == 1
        assert "test_workflow" in result[0]["display_name"]
        assert result[0]["type"] == "workflow"
        assert "duration_ms" in result[0]
        assert "start_ms" in result[0]

    def test_flatten_nested_trace(self, nested_trace):
        """Test flattening a nested trace."""
        result = _flatten_trace_with_tree(nested_trace, show_tree_lines=False)

        # Should have 5 items: workflow, stage, agent, llm, tool
        assert len(result) == 5

        # Check types are present
        types = [item["type"] for item in result]
        assert "workflow" in types
        assert "stage" in types
        assert "agent" in types
        assert "llm" in types
        assert "tool" in types

    def test_flatten_with_tree_lines(self, nested_trace):
        """Test that tree structure lines are added."""
        result = _flatten_trace_with_tree(nested_trace, show_tree_lines=True)

        # Check that display names contain tree characters
        display_names = [item["display_name"] for item in result]

        # First item should not have prefix
        assert not display_names[0].startswith("├─") and not display_names[0].startswith("└─")

        # Other items should have tree characters
        has_tree_chars = any("├─" in name or "└─" in name for name in display_names[1:])
        assert has_tree_chars

    def test_flatten_preserves_order(self, nested_trace):
        """Test that flattening preserves hierarchical order."""
        result = _flatten_trace_with_tree(nested_trace, show_tree_lines=False)

        # Workflow should be first
        assert result[0]["type"] == "workflow"

        # Stage should come after workflow
        stage_idx = next(i for i, item in enumerate(result) if item["type"] == "stage")
        assert stage_idx > 0

        # Agent should come after stage
        agent_idx = next(i for i, item in enumerate(result) if item["type"] == "agent")
        assert agent_idx > stage_idx

    def test_flatten_duration_conversion(self, simple_trace):
        """Test that duration is converted to milliseconds."""
        result = _flatten_trace_with_tree(simple_trace, show_tree_lines=False)

        # Duration should be in milliseconds
        assert result[0]["duration_ms"] == 5000  # 5 seconds = 5000 ms

    def test_flatten_empty_trace(self):
        """Test flattening an empty trace."""
        trace = {
            "id": "empty",
            "name": "empty",
            "type": "workflow",
            "start": "2024-01-01T12:00:00",
            "end": "2024-01-01T12:00:00",
            "duration": 0,
            "status": "completed",
            "metadata": {},
            "children": []
        }

        result = _flatten_trace_with_tree(trace, show_tree_lines=False)
        assert len(result) == 1


@pytest.mark.skipif(not PLOTLY_AVAILABLE, reason="Plotly not installed")
class TestVisualizeTrace:
    """Test visualize_trace function."""

    def test_visualize_trace_basic(self, simple_trace):
        """Test basic trace visualization."""
        fig = visualize_trace(simple_trace, auto_open=False)

        assert fig is not None
        assert isinstance(fig, go.Figure)
        assert len(fig.data) >= 1, "Figure should have at least one trace"

    def test_visualize_trace_nested(self, nested_trace):
        """Test visualizing nested trace."""
        fig = visualize_trace(nested_trace, auto_open=False)

        assert fig is not None
        assert isinstance(fig, go.Figure)
        # Nested trace has 5 items (workflow, stage, agent, llm, tool)
        assert len(fig.data) >= 3, "Nested trace should produce multiple traces"

    def test_visualize_trace_with_output_file(self, simple_trace, tmp_path):
        """Test saving visualization to HTML file."""
        output_file = tmp_path / "gantt.html"

        fig = visualize_trace(simple_trace, output_file=str(output_file), auto_open=False)

        assert fig is not None
        assert output_file.exists()

    def test_visualize_trace_without_tree_lines(self, simple_trace):
        """Test visualization without tree lines."""
        fig = visualize_trace(simple_trace, show_tree_lines=False, auto_open=False)

        assert fig is not None
        assert len(fig.data) >= 1, "Figure should have at least one trace"


class TestEdgeCases:
    """Test edge cases and error handling."""

    @pytest.mark.skipif(not PLOTLY_AVAILABLE, reason="Plotly not installed")
    def test_trace_with_missing_fields(self):
        """Test handling trace with missing optional fields."""
        trace = {
            "id": "test",
            "name": "test",
            "type": "workflow",
            "start": "2024-01-01T12:00:00",
            "end": "2024-01-01T12:00:01",
            "duration": 1.0,
            "status": "completed",
            # metadata missing
            "children": []
        }

        # Should handle missing metadata gracefully
        fig = create_hierarchical_gantt(trace)
        assert fig is not None

    @pytest.mark.skipif(not PLOTLY_AVAILABLE, reason="Plotly not installed")
    def test_trace_with_errors(self):
        """Test handling trace with error status."""
        trace = {
            "id": "test",
            "name": "test",
            "type": "workflow",
            "start": "2024-01-01T12:00:00",
            "end": "2024-01-01T12:00:01",
            "duration": 1.0,
            "status": "error",
            "metadata": {"error": "Something went wrong"},
            "children": []
        }

        fig = create_hierarchical_gantt(trace)
        assert fig is not None

    @pytest.mark.skipif(not PLOTLY_AVAILABLE, reason="Plotly not installed")
    def test_parallel_execution(self):
        """Test visualization of parallel stages."""
        start = datetime(2024, 1, 1, 12, 0, 0)

        trace = {
            "id": "workflow-1",
            "name": "parallel_workflow",
            "type": "workflow",
            "start": start.isoformat(),
            "end": (start + timedelta(seconds=5)).isoformat(),
            "duration": 5.0,
            "status": "completed",
            "metadata": {},
            "children": [
                {
                    "id": "stage-1",
                    "name": "stage1",
                    "type": "stage",
                    "start": start.isoformat(),
                    "end": (start + timedelta(seconds=3)).isoformat(),
                    "duration": 3.0,
                    "status": "completed",
                    "metadata": {},
                    "children": []
                },
                {
                    "id": "stage-2",
                    "name": "stage2",
                    "type": "stage",
                    "start": start.isoformat(),  # Same start time (parallel)
                    "end": (start + timedelta(seconds=5)).isoformat(),
                    "duration": 5.0,
                    "status": "completed",
                    "metadata": {},
                    "children": []
                }
            ]
        }

        fig = create_hierarchical_gantt(trace)
        assert fig is not None
        assert len(fig.data) > 0


@pytest.mark.skipif(PLOTLY_AVAILABLE, reason="Test only when plotly not installed")
class TestPlotlyNotAvailable:
    """Test behavior when plotly is not installed."""

    def test_create_gantt_without_plotly(self, simple_trace):
        """Test that appropriate error is raised when plotly not available."""
        with pytest.raises(ImportError, match="Plotly required"):
            create_hierarchical_gantt(simple_trace)


class TestTimingAccuracy:
    """Test timing calculations and accuracy."""

    def test_duration_calculation(self, simple_trace):
        """Test that durations are calculated correctly."""
        result = _flatten_trace_with_tree(simple_trace, show_tree_lines=False)

        # 5 seconds should be 5000 milliseconds
        assert result[0]["duration_ms"] == 5000

    def test_start_time_offset(self, nested_trace):
        """Test that start times are calculated relative to workflow start."""
        result = _flatten_trace_with_tree(nested_trace, show_tree_lines=False)

        # Workflow should start at 0
        workflow_item = next(item for item in result if item["type"] == "workflow")
        assert workflow_item["start_ms"] == 0

        # Child items should have positive offsets
        stage_item = next(item for item in result if item["type"] == "stage")
        assert stage_item["start_ms"] > 0


class TestHoverText:
    """Test hover text generation."""

    def test_hover_text_includes_details(self, nested_trace):
        """Test that hover text includes relevant details."""
        result = _flatten_trace_with_tree(nested_trace, show_tree_lines=False)

        for item in result:
            assert "hover_text" in item
            hover = item["hover_text"]

            # Should include duration info
            assert "duration" in hover.lower() or "ms" in hover.lower() or "s" in hover.lower()
