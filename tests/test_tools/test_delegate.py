"""Tests for Delegate tool."""

from unittest.mock import MagicMock

from temper_ai.tools.delegate import Delegate


class TestDelegateValidation:
    def test_no_context_bound(self):
        d = Delegate()
        r = d.execute(tasks=[{"agent": "test", "inputs": {}}])
        assert r.success is False
        assert "context" in r.error.lower() or "bound" in r.error.lower()

    def test_empty_tasks(self):
        d = Delegate()
        d._execution_context = MagicMock()
        r = d.execute(tasks=[])
        assert r.success is False

    def test_no_tasks_param(self):
        d = Delegate()
        d._execution_context = MagicMock()
        r = d.execute()
        assert r.success is False


class TestDelegateBindContext:
    def test_bind_context(self):
        d = Delegate()
        ctx = MagicMock()
        d.bind_context(ctx)
        assert d._execution_context is ctx

    def test_bind_context_overrides(self):
        d = Delegate()
        ctx1 = MagicMock()
        ctx2 = MagicMock()
        d.bind_context(ctx1)
        d.bind_context(ctx2)
        assert d._execution_context is ctx2
