"""Tests for bounded collection eviction in ApprovalWorkflow and RollbackManager.

Verifies that:
1. ApprovalWorkflow evicts oldest completed requests when over max_requests
2. RollbackManager evicts oldest snapshots when over max_snapshots
3. RollbackManager evicts oldest history entries when over max_history
"""

import pytest
from datetime import datetime, timedelta, UTC

from src.safety.approval import ApprovalWorkflow, ApprovalStatus
from src.safety.rollback import RollbackManager, RollbackResult, RollbackStatus


# ── ApprovalWorkflow eviction tests ──────────────────────────────────────


class TestApprovalWorkflowEviction:
    """Verify ApprovalWorkflow._requests stays bounded."""

    def test_stays_within_max_requests(self):
        wf = ApprovalWorkflow(max_requests=5)
        for i in range(10):
            req = wf.request_approval(
                action={"tool": f"tool_{i}"},
                reason=f"reason_{i}",
            )
            # Approve immediately so eviction can target completed requests
            wf.approve(req.id, approver="admin")

        assert wf.request_count() <= 5

    def test_evicts_completed_before_pending(self):
        wf = ApprovalWorkflow(max_requests=3)

        # Create and approve 2 requests (completed)
        completed_ids = []
        for i in range(2):
            req = wf.request_approval(action={"tool": f"done_{i}"}, reason="done")
            wf.approve(req.id, approver="admin")
            completed_ids.append(req.id)

        # Create 1 pending request
        pending_req = wf.request_approval(action={"tool": "pending"}, reason="wait")

        # Now at limit (3). Add one more completed to trigger eviction.
        extra = wf.request_approval(action={"tool": "extra"}, reason="extra")
        wf.approve(extra.id, approver="admin")

        # Pending request should survive; oldest completed should be evicted
        assert wf.get_request(pending_req.id) is not None
        assert wf.get_request(pending_req.id).is_pending()

    def test_evicts_oldest_completed_first(self):
        wf = ApprovalWorkflow(max_requests=3)

        # Create 3 completed requests with staggered creation times
        ids = []
        for i in range(3):
            req = wf.request_approval(action={"tool": f"t{i}"}, reason=f"r{i}")
            wf.approve(req.id, approver="admin")
            ids.append(req.id)

        # Add one more to trigger eviction
        new_req = wf.request_approval(action={"tool": "new"}, reason="new")
        wf.approve(new_req.id, approver="admin")

        # Oldest (first created) should be evicted
        assert wf.get_request(ids[0]) is None
        # Newer ones should survive
        assert wf.get_request(ids[-1]) is not None

    def test_default_max_requests(self):
        wf = ApprovalWorkflow()
        assert wf._max_requests == ApprovalWorkflow.MAX_REQUESTS

    def test_custom_max_requests(self):
        wf = ApprovalWorkflow(max_requests=42)
        assert wf._max_requests == 42


# ── RollbackManager snapshot eviction tests ──────────────────────────────


class TestRollbackSnapshotEviction:
    """Verify RollbackManager._snapshots stays bounded."""

    def test_stays_within_max_snapshots(self):
        mgr = RollbackManager(max_snapshots=5)
        for i in range(10):
            mgr.create_snapshot(action={"tool": f"action_{i}"})

        assert len(mgr._snapshots) <= 5

    def test_evicts_oldest_snapshot(self):
        mgr = RollbackManager(max_snapshots=3)

        ids = []
        for i in range(4):
            snap = mgr.create_snapshot(action={"tool": f"action_{i}"})
            ids.append(snap.id)

        # First snapshot should be evicted (oldest by created_at)
        assert mgr.get_snapshot(ids[0]) is None
        # Last 3 should survive
        for sid in ids[1:]:
            assert mgr.get_snapshot(sid) is not None

    def test_default_max_snapshots(self):
        mgr = RollbackManager()
        assert mgr._max_snapshots == RollbackManager.MAX_SNAPSHOTS

    def test_custom_max_snapshots(self):
        mgr = RollbackManager(max_snapshots=77)
        assert mgr._max_snapshots == 77


# ── RollbackManager history eviction tests ────────────────────────────────


class TestRollbackHistoryEviction:
    """Verify RollbackManager._history stays bounded."""

    def test_stays_within_max_history(self):
        mgr = RollbackManager(max_snapshots=100, max_history=5)
        for i in range(10):
            snap = mgr.create_snapshot(action={"tool": f"action_{i}"})
            mgr.execute_rollback(snap.id)

        assert len(mgr._history) <= 5

    def test_keeps_most_recent_entries(self):
        mgr = RollbackManager(max_snapshots=100, max_history=3)

        snapshot_ids = []
        for i in range(5):
            snap = mgr.create_snapshot(action={"tool": f"action_{i}"})
            snapshot_ids.append(snap.id)
            mgr.execute_rollback(snap.id)

        # History should contain only the last 3 entries
        assert len(mgr._history) == 3
        history_snap_ids = [r.snapshot_id for r in mgr._history]
        assert history_snap_ids == snapshot_ids[2:]

    def test_default_max_history(self):
        mgr = RollbackManager()
        assert mgr._max_history == RollbackManager.MAX_HISTORY

    def test_custom_max_history(self):
        mgr = RollbackManager(max_history=99)
        assert mgr._max_history == 99
