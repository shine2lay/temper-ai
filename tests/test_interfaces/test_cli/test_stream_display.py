"""Tests for StreamDisplay stage/agent progress indicators.

Verifies:
- _SourceStream includes stage_name field
- Panel title includes stage context or running indicator
- _current_stage is propagated to new source streams
"""
from unittest.mock import MagicMock

from temper_ai.interfaces.cli.stream_display import StreamDisplay, _SourceStream
from temper_ai.interfaces.cli.stream_events import StreamEvent, LLM_TOKEN


def _make_console() -> MagicMock:
    """Create a mock Rich Console."""
    return MagicMock()


class TestSourceStreamStageField:
    """Test _SourceStream stage_name field."""

    def test_default_stage_name_is_empty(self) -> None:
        stream = _SourceStream(name="agent1")
        assert stream.stage_name == ""

    def test_stage_name_set_at_construction(self) -> None:
        stream = _SourceStream(name="agent1", stage_name="analysis")
        assert stream.stage_name == "analysis"


class TestStreamDisplayCurrentStage:
    """Test _current_stage propagation to new source streams."""

    def test_current_stage_default_empty(self) -> None:
        display = StreamDisplay(_make_console())
        assert display._current_stage == ""

    def test_current_stage_propagated_to_new_source(self) -> None:
        display = StreamDisplay(_make_console())
        display._current_stage = "analysis"

        event = StreamEvent(
            source="agent1",
            event_type=LLM_TOKEN,
            content="hello",
            metadata={"model": "qwen3"},
        )
        # Call _on_event directly to create source
        display._on_event("agent1", event)

        assert "agent1" in display._sources
        assert display._sources["agent1"].stage_name == "analysis"

    def test_current_stage_not_retroactive(self) -> None:
        """Stage set after source creation doesn't change existing sources."""
        display = StreamDisplay(_make_console())

        event = StreamEvent(
            source="agent1",
            event_type=LLM_TOKEN,
            content="hello",
            metadata={"model": "qwen3"},
        )
        display._on_event("agent1", event)

        # Set stage after source was created
        display._current_stage = "implementation"

        # Existing source keeps its original (empty) stage
        assert display._sources["agent1"].stage_name == ""


class TestPanelTitleStageContext:
    """Test that panel titles include stage context."""

    def test_panel_title_with_stage_name(self) -> None:
        display = StreamDisplay(_make_console())
        stream = _SourceStream(
            name="agent1",
            model="qwen3",
            stage_name="analysis",
            color="cyan",
        )
        panel = display._build_source_panel(stream)
        assert "analysis" in panel.title
        assert "\u25cf" in panel.title

    def test_panel_title_without_stage_name(self) -> None:
        display = StreamDisplay(_make_console())
        stream = _SourceStream(
            name="agent1",
            model="qwen3",
            stage_name="",
            color="cyan",
        )
        panel = display._build_source_panel(stream)
        assert "running" in panel.title
        assert "\u25cf" in panel.title

    def test_panel_title_no_longer_says_streaming(self) -> None:
        display = StreamDisplay(_make_console())
        stream = _SourceStream(
            name="agent1",
            model="qwen3",
            stage_name="analysis",
            color="cyan",
        )
        panel = display._build_source_panel(stream)
        assert "streaming" not in panel.title
