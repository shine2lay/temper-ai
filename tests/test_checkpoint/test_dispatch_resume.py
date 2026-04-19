"""Tests for checkpoint persistence + resume of runtime dispatch.

Covers:
  - save_dispatch_applied persists an entry that survives a fresh service
  - reconstruct() restores op=remove targets as SKIPPED in node_outputs
  - reconstruct_dispatch_history returns events in order with full payload
  - Multiple dispatches accumulate dispatched_count correctly
"""

import uuid

import pytest

from temper_ai.checkpoint.service import CheckpointService
from temper_ai.shared.types import NodeResult, Status


@pytest.fixture
def svc():
    """Fresh CheckpointService with a unique execution_id so tests don't
    interfere with each other."""
    return CheckpointService(f"test-dispatch-{uuid.uuid4()}")


class TestSaveDispatchApplied:
    def test_save_single_add(self, svc):
        svc.save_dispatch_applied(
            dispatcher_name="allocator",
            added_nodes=[{
                "name": "tokyo_research",
                "type": "agent",
                "agent": "activity_researcher",
                "input_map": {"city": "Tokyo"},
            }],
            removed_targets=[],
            dispatcher_depth=0,
            dispatcher_fingerprint=("allocator", "abc123"),
            dispatched_count_delta=1,
        )
        history = svc.reconstruct_dispatch_history()
        assert len(history) == 1
        assert history[0]["dispatcher_name"] == "allocator"
        assert history[0]["added_nodes"][0]["name"] == "tokyo_research"
        assert history[0]["removed_targets"] == []
        assert history[0]["dispatcher_depth"] == 0
        assert history[0]["dispatcher_fingerprint"] == ("allocator", "abc123")
        assert history[0]["dispatched_count_delta"] == 1

    def test_save_multiple_adds(self, svc):
        svc.save_dispatch_applied(
            dispatcher_name="allocator",
            added_nodes=[
                {"name": "a", "type": "agent", "agent": "x"},
                {"name": "b", "type": "agent", "agent": "y"},
                {"name": "c", "type": "agent", "agent": "z"},
            ],
            removed_targets=[],
            dispatcher_depth=0,
            dispatcher_fingerprint=("allocator", "abc"),
            dispatched_count_delta=3,
        )
        history = svc.reconstruct_dispatch_history()
        assert len(history[0]["added_nodes"]) == 3

    def test_save_removes_only(self, svc):
        svc.save_dispatch_applied(
            dispatcher_name="pruner",
            added_nodes=[],
            removed_targets=["placeholder_a", "placeholder_b"],
            dispatcher_depth=0,
            dispatcher_fingerprint=("pruner", "def"),
            dispatched_count_delta=0,
        )
        history = svc.reconstruct_dispatch_history()
        assert history[0]["removed_targets"] == ["placeholder_a", "placeholder_b"]
        assert history[0]["added_nodes"] == []


class TestReconstructMarksRemoved:
    def test_removed_targets_become_skipped(self, svc):
        """After a dispatch_applied with op=remove, reconstruct() should
        return those targets as SKIPPED so the executor doesn't try to
        execute them on resume."""
        svc.save_node_completed("dispatcher", NodeResult(
            status=Status.COMPLETED, output="ok",
        ))
        svc.save_dispatch_applied(
            dispatcher_name="dispatcher",
            added_nodes=[],
            removed_targets=["unneeded"],
            dispatcher_depth=0,
            dispatcher_fingerprint=("dispatcher", "x"),
            dispatched_count_delta=0,
        )
        outputs = svc.reconstruct()
        assert "unneeded" in outputs
        assert outputs["unneeded"].status == Status.SKIPPED
        assert "dispatcher" in outputs["unneeded"].error

    def test_removed_doesnt_override_completed(self, svc):
        """If a target was already completed before being removed, keep
        the completed result — don't overwrite with SKIPPED."""
        svc.save_node_completed("target", NodeResult(
            status=Status.COMPLETED, output="already done",
        ))
        svc.save_node_completed("dispatcher", NodeResult(
            status=Status.COMPLETED, output="ok",
        ))
        svc.save_dispatch_applied(
            dispatcher_name="dispatcher",
            added_nodes=[],
            removed_targets=["target"],
            dispatcher_depth=0,
            dispatcher_fingerprint=("dispatcher", "x"),
            dispatched_count_delta=0,
        )
        outputs = svc.reconstruct()
        # Completed result preserved
        assert outputs["target"].status == Status.COMPLETED
        assert outputs["target"].output == "already done"


class TestDispatchHistoryOrder:
    def test_multiple_dispatches_ordered(self, svc):
        svc.save_dispatch_applied(
            dispatcher_name="first",
            added_nodes=[{"name": "f1", "type": "agent", "agent": "x"}],
            removed_targets=[],
            dispatcher_depth=0,
            dispatcher_fingerprint=("first", "a"),
            dispatched_count_delta=1,
        )
        svc.save_dispatch_applied(
            dispatcher_name="second",
            added_nodes=[{"name": "s1", "type": "agent", "agent": "x"}],
            removed_targets=[],
            dispatcher_depth=0,
            dispatcher_fingerprint=("second", "b"),
            dispatched_count_delta=1,
        )
        history = svc.reconstruct_dispatch_history()
        assert [h["dispatcher_name"] for h in history] == ["first", "second"]

    def test_dispatched_count_accumulates(self, svc):
        """Run-wide count restored by summing deltas across all events."""
        svc.save_dispatch_applied(
            dispatcher_name="a",
            added_nodes=[{"name": "n1", "agent": "x"}],
            removed_targets=[],
            dispatcher_depth=0,
            dispatcher_fingerprint=("a", "a"),
            dispatched_count_delta=1,
        )
        svc.save_dispatch_applied(
            dispatcher_name="b",
            added_nodes=[
                {"name": "n2", "agent": "x"},
                {"name": "n3", "agent": "x"},
            ],
            removed_targets=[],
            dispatcher_depth=1,
            dispatcher_fingerprint=("b", "b"),
            dispatched_count_delta=2,
        )
        history = svc.reconstruct_dispatch_history()
        total = sum(h["dispatched_count_delta"] for h in history)
        assert total == 3


class TestFreshServiceReadsPersistedHistory:
    """Simulates a crash → restart by creating a new CheckpointService
    instance with the same execution_id. The new service must see the
    checkpoints the old one wrote."""

    def test_new_service_sees_dispatch_history(self):
        exec_id = f"test-dispatch-persist-{uuid.uuid4()}"
        original = CheckpointService(exec_id)
        original.save_dispatch_applied(
            dispatcher_name="d",
            added_nodes=[{"name": "child", "type": "agent", "agent": "x"}],
            removed_targets=[],
            dispatcher_depth=0,
            dispatcher_fingerprint=("d", "fp"),
            dispatched_count_delta=1,
        )
        # Fresh service with same execution_id — simulates process restart
        reloaded = CheckpointService(exec_id)
        history = reloaded.reconstruct_dispatch_history()
        assert len(history) == 1
        assert history[0]["dispatcher_name"] == "d"
        assert history[0]["added_nodes"][0]["name"] == "child"
