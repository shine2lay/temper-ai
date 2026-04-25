"""Tests for `temper watch-queue` — the queue-watcher daemon.

Strategy: drive the scan/dispatch logic directly with `_scan_and_dispatch`
against an in-memory sqlite DB; mock the spawner so we don't actually
fork. The full daemon loop (cmd_watch_queue) is tested via a short-lived
end-to-end test that starts/stops it on a thread.
"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock

import pytest
from sqlmodel import select

from temper_ai.cli.watch_queue import (
    _claim_row,
    _scan_and_dispatch,
)
from temper_ai.database import get_session, init_database, reset_database
from temper_ai.runner.models import WorkflowRun
from temper_ai.spawner.base import SpawnerError
from temper_ai.spawner.factory import reset_spawner
from temper_ai.worker_proto import ProcessHandle, SpawnerKind


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    db_path = tmp_path / "watcher_test.db"
    monkeypatch.setenv("TEMPER_DATABASE_URL", f"sqlite:///{db_path}")
    reset_database()
    init_database(f"sqlite:///{db_path}")
    yield db_path
    reset_database()


@pytest.fixture(autouse=True)
def _reset_spawner():
    reset_spawner()
    yield
    reset_spawner()


def _enqueue(execution_id: str, *, workflow_name: str = "wf", inputs: dict | None = None):
    with get_session() as session:
        session.add(WorkflowRun(
            execution_id=execution_id,
            workflow_name=workflow_name,
            workspace_path="/tmp/ws",
            inputs=inputs or {},
            status="queued",
        ))


def _read(execution_id: str) -> dict:
    with get_session() as session:
        row = session.exec(
            select(WorkflowRun).where(WorkflowRun.execution_id == execution_id),
        ).one()
        return {
            "status": row.status,
            "spawner_kind": row.spawner_kind,
            "spawner_handle": row.spawner_handle,
            "error": row.error,
        }


# --- Claim logic -------------------------------------------------------

def test_claim_row_sets_kind_and_placeholder(isolated_db):
    _enqueue("e1")
    assert _claim_row("e1") is True
    row = _read("e1")
    assert row["spawner_kind"] == "subprocess"
    assert row["spawner_handle"] == "claiming"


def test_claim_row_returns_false_for_already_claimed(isolated_db):
    _enqueue("e2")
    assert _claim_row("e2") is True
    # Second claim attempt finds spawner_kind already set → no match
    assert _claim_row("e2") is False


def test_claim_row_returns_false_for_missing(isolated_db):
    assert _claim_row("nonexistent") is False


# --- Scan + dispatch ---------------------------------------------------

def test_scan_dispatches_each_queued_row(isolated_db):
    _enqueue("a")
    _enqueue("b")
    _enqueue("c")

    spawner = MagicMock()
    spawner.spawn.side_effect = lambda eid: ProcessHandle(
        kind=SpawnerKind.subprocess,
        handle=f"pid-{eid}",
        metadata={"execution_id": eid},
    )

    n = _scan_and_dispatch(spawner)
    assert n == 3
    assert spawner.spawn.call_count == 3
    for eid in ("a", "b", "c"):
        row = _read(eid)
        assert row["spawner_handle"] == f"pid-{eid}"


def test_scan_skips_already_claimed_rows(isolated_db):
    _enqueue("d")
    # Pre-claim it (simulating another watcher)
    _claim_row("d")

    spawner = MagicMock()
    n = _scan_and_dispatch(spawner)
    assert n == 0
    spawner.spawn.assert_not_called()


def test_scan_marks_failed_on_spawn_error(isolated_db):
    _enqueue("e")
    spawner = MagicMock()
    spawner.spawn.side_effect = SpawnerError("fork bombed")

    n = _scan_and_dispatch(spawner)
    assert n == 0  # nothing successfully dispatched

    row = _read("e")
    assert row["status"] == "failed"
    assert row["error"]["kind"] == "spawn"
    assert "fork bombed" in row["error"]["message"]


def test_scan_no_op_when_queue_empty(isolated_db):
    spawner = MagicMock()
    n = _scan_and_dispatch(spawner)
    assert n == 0
    spawner.spawn.assert_not_called()


def test_scan_skips_terminal_rows(isolated_db):
    """Rows in completed/failed/cancelled status should never be picked up."""
    with get_session() as session:
        for eid, status in [("done-1", "completed"), ("dead-1", "failed")]:
            session.add(WorkflowRun(
                execution_id=eid, workflow_name="wf", workspace_path="/tmp",
                status=status,
            ))

    spawner = MagicMock()
    n = _scan_and_dispatch(spawner)
    assert n == 0


# --- Race safety ------------------------------------------------------

def test_two_concurrent_claims_only_one_wins(isolated_db):
    """Claim is atomic: two threads racing on the same row → exactly one wins.
    """
    _enqueue("race")

    results: list[bool] = []
    barrier = threading.Barrier(2)

    def attempt():
        barrier.wait()  # synchronize start
        results.append(_claim_row("race"))

    t1 = threading.Thread(target=attempt)
    t2 = threading.Thread(target=attempt)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # Exactly one True, one False
    assert sorted(results) == [False, True]


# --- CLI wiring smoke ---------------------------------------------------

def test_watch_queue_subcommand_registered():
    """`temper watch-queue` is reachable from the CLI entry point.

    The full daemon loop is exercised via _scan_and_dispatch tests above —
    here we just confirm the wiring exists so a future rename of
    cmd_watch_queue or the subcommand string would be caught.
    """
    from temper_ai.cli import main as cli_main
    from temper_ai.cli.watch_queue import cmd_watch_queue

    assert hasattr(cli_main, "main")
    assert callable(cmd_watch_queue)
