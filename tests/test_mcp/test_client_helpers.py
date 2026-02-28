"""Tests for temper_ai/mcp/_client_helpers.py."""

import asyncio
from unittest.mock import MagicMock

from temper_ai.mcp._client_helpers import (
    create_event_loop_thread,
    map_annotations_to_metadata,
    stop_event_loop,
)


class TestCreateEventLoopThread:
    """Tests for create_event_loop_thread."""

    def test_returns_loop_and_thread(self):
        loop, thread = create_event_loop_thread()
        try:
            assert isinstance(loop, asyncio.AbstractEventLoop)
            assert thread.is_alive()
            assert thread.daemon is True
        finally:
            stop_event_loop(loop, thread)

    def test_loop_is_running(self):
        loop, thread = create_event_loop_thread()
        try:
            assert loop.is_running()
        finally:
            stop_event_loop(loop, thread)

    def test_can_submit_coroutine(self):
        loop, thread = create_event_loop_thread()
        try:

            async def _coro():
                return 42

            future = asyncio.run_coroutine_threadsafe(_coro(), loop)
            result = future.result(timeout=5)
            assert result == 42
        finally:
            stop_event_loop(loop, thread)


class TestStopEventLoop:
    """Tests for stop_event_loop."""

    def test_stops_running_loop(self):
        loop, thread = create_event_loop_thread()
        assert thread.is_alive()
        stop_event_loop(loop, thread, join_timeout=5.0)
        assert not thread.is_alive()

    def test_idempotent_on_closed_loop(self):
        loop, thread = create_event_loop_thread()
        stop_event_loop(loop, thread)
        # Closing the loop and calling stop again should not raise
        if not loop.is_closed():
            loop.close()
        stop_event_loop(loop, thread)


class TestMapAnnotationsToMetadata:
    """Tests for map_annotations_to_metadata."""

    def test_none_annotations(self):
        assert map_annotations_to_metadata(None) == {}

    def test_read_only_hint(self):
        ann = MagicMock()
        ann.readOnlyHint = True
        ann.destructiveHint = None
        ann.openWorldHint = None
        result = map_annotations_to_metadata(ann)
        assert result["modifies_state"] is False

    def test_destructive_hint(self):
        ann = MagicMock()
        ann.readOnlyHint = False
        ann.destructiveHint = True
        ann.openWorldHint = None
        result = map_annotations_to_metadata(ann)
        assert result["modifies_state"] is True

    def test_read_only_takes_precedence_over_destructive(self):
        ann = MagicMock()
        ann.readOnlyHint = True
        ann.destructiveHint = True
        ann.openWorldHint = None
        result = map_annotations_to_metadata(ann)
        assert result["modifies_state"] is False

    def test_open_world_hint(self):
        ann = MagicMock()
        ann.readOnlyHint = None
        ann.destructiveHint = None
        ann.openWorldHint = True
        result = map_annotations_to_metadata(ann)
        assert result["requires_network"] is True

    def test_no_hints_set(self):
        ann = MagicMock()
        ann.readOnlyHint = None
        ann.destructiveHint = None
        ann.openWorldHint = None
        result = map_annotations_to_metadata(ann)
        assert result == {}

    def test_all_hints_set(self):
        ann = MagicMock()
        ann.readOnlyHint = True
        ann.destructiveHint = False
        ann.openWorldHint = True
        result = map_annotations_to_metadata(ann)
        assert result["modifies_state"] is False
        assert result["requires_network"] is True

    def test_missing_attributes_graceful(self):
        """Annotations object without hint attributes."""
        ann = object()  # No attributes at all
        result = map_annotations_to_metadata(ann)
        assert result == {}
