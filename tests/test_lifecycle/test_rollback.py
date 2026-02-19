"""Tests for rollback monitor."""

import uuid

import pytest

from temper_ai.lifecycle._schemas import DegradationReport, WorkflowMetrics
from temper_ai.lifecycle.history import HistoryAnalyzer
from temper_ai.lifecycle.models import LifecycleAdaptation
from temper_ai.lifecycle.rollback import RollbackMonitor
from temper_ai.lifecycle.store import LifecycleStore


@pytest.fixture
def store():
    return LifecycleStore(database_url="sqlite:///:memory:")


@pytest.fixture
def history():
    return HistoryAnalyzer(db_url=None)


@pytest.fixture
def monitor(store, history):
    return RollbackMonitor(store=store, history=history)


class TestRollbackMonitor:
    """Tests for RollbackMonitor."""

    def test_no_data_returns_none(self, monitor):
        result = monitor.check_degradation("lean")
        assert result is None

    def test_insufficient_data_returns_none(self, monitor, store):
        store.save_adaptation(LifecycleAdaptation(
            id="a-1", workflow_id="wf-1", profile_name="lean",
        ))
        result = monitor.check_degradation("lean")
        assert result is None

    def test_no_degradation(self, monitor, store):
        for i in range(5):
            store.save_adaptation(LifecycleAdaptation(
                id=f"a-{i}", workflow_id=f"wf-{i}",
                profile_name="lean",
                characteristics={"workflow_name": "test"},
            ))
        result = monitor.check_degradation("lean")
        # With default history (no real DB), no degradation detected
        assert result is None

    def test_revert_profile_in_db(self, monitor, store):
        from temper_ai.lifecycle.models import LifecycleProfileRecord
        store.save_profile(LifecycleProfileRecord(
            id="p-1", name="lean", enabled=True,
        ))
        monitor.revert_profile("lean")
        profile = store.get_profile("lean")
        assert profile is not None
        assert profile.enabled is False

    def test_revert_missing_profile(self, monitor):
        monitor.revert_profile("nonexistent")
        assert monitor._store.get_profile("nonexistent") is None

    def test_custom_threshold(self, store, history):
        monitor = RollbackMonitor(
            store=store, history=history, threshold=0.01,
        )
        assert monitor._threshold == 0.01

    def test_window_parameter(self, monitor, store):
        for i in range(20):
            store.save_adaptation(LifecycleAdaptation(
                id=f"a-{i}", workflow_id=f"wf-{i}",
                profile_name="lean",
            ))
        result = monitor.check_degradation("lean", window=5)
        assert result is None
