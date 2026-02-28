"""Tests for temper_ai/events/_subscription_helpers.py."""

from unittest.mock import MagicMock

from temper_ai.events._subscription_helpers import (
    matches_filter,
    register_handler,
    resolve_handler,
)


class TestMatchesFilter:
    """Tests for subscription filter matching."""

    def _make_sub(self, event_type, workflow_filter=None, payload_filter=None):
        sub = MagicMock()
        sub.event_type = event_type
        sub.source_workflow_filter = workflow_filter
        sub.payload_filter = payload_filter
        return sub

    def test_matching_event_type(self):
        sub = self._make_sub("task.completed")
        assert matches_filter(sub, "task.completed", None, None) is True

    def test_non_matching_event_type(self):
        sub = self._make_sub("task.completed")
        assert matches_filter(sub, "task.started", None, None) is False

    def test_workflow_filter_match(self):
        sub = self._make_sub("task.completed", workflow_filter="wf-123")
        assert matches_filter(sub, "task.completed", None, "wf-123") is True

    def test_workflow_filter_mismatch(self):
        sub = self._make_sub("task.completed", workflow_filter="wf-123")
        assert matches_filter(sub, "task.completed", None, "wf-999") is False

    def test_no_workflow_filter_accepts_any(self):
        sub = self._make_sub("task.completed", workflow_filter=None)
        assert matches_filter(sub, "task.completed", None, "wf-999") is True

    def test_payload_filter_match(self):
        sub = self._make_sub("task.completed", payload_filter={"status": "ok"})
        assert (
            matches_filter(sub, "task.completed", {"status": "ok", "extra": 1}, None)
            is True
        )

    def test_payload_filter_mismatch(self):
        sub = self._make_sub("task.completed", payload_filter={"status": "ok"})
        assert matches_filter(sub, "task.completed", {"status": "error"}, None) is False

    def test_payload_filter_missing_key(self):
        sub = self._make_sub("task.completed", payload_filter={"status": "ok"})
        assert matches_filter(sub, "task.completed", {"other": "val"}, None) is False

    def test_payload_filter_with_none_payload(self):
        sub = self._make_sub("task.completed", payload_filter={"status": "ok"})
        # payload_filter exists but payload is None → filter not checked
        assert matches_filter(sub, "task.completed", None, None) is True

    def test_no_payload_filter(self):
        sub = self._make_sub("task.completed", payload_filter=None)
        assert matches_filter(sub, "task.completed", {"anything": True}, None) is True

    def test_combined_filters(self):
        sub = self._make_sub(
            "task.completed",
            workflow_filter="wf-1",
            payload_filter={"key": "val"},
        )
        assert matches_filter(sub, "task.completed", {"key": "val"}, "wf-1") is True
        assert matches_filter(sub, "task.completed", {"key": "val"}, "wf-2") is False
        assert matches_filter(sub, "task.completed", {"key": "wrong"}, "wf-1") is False


class TestHandlerRegistry:
    """Tests for register_handler and resolve_handler."""

    def test_register_and_resolve(self):
        def my_handler():
            pass

        register_handler("test_handler", my_handler)
        assert resolve_handler("test_handler") is my_handler

    def test_resolve_unknown_returns_none(self):
        assert resolve_handler("nonexistent_handler_xyz") is None

    def test_register_overwrites(self):
        def handler_v1():
            pass

        def handler_v2():
            pass

        register_handler("overwrite_test", handler_v1)
        register_handler("overwrite_test", handler_v2)
        assert resolve_handler("overwrite_test") is handler_v2
