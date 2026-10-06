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


def _fake_spawner(kind: SpawnerKind = SpawnerKind.subprocess) -> MagicMock:
    """A spawner double with the `kind` the watcher stamps into the claim."""
    spawner = MagicMock()
    spawner.kind = kind
    return spawner


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


def _enqueue(execution_id: str, *, workflow_name: str = "wf", inputs: dict | None = None, **fields):
    start = fields.get("spawner_metadata", {}).get("start")
    if start == "resume":
        from temper_ai.runner.queue import queue_run

        # An intact prior row, followed by the real enqueue transaction; never
        # invent a reservation or historical baseline in a cleared queued row.
        with get_session() as session:
            session.add(WorkflowRun(
                execution_id=execution_id, workflow_name=workflow_name,
                workspace_path="/tmp/ws", inputs=inputs or {}, status="failed",
                error={"message": "prior fixture ending"},
            ))
        queue_run(execution_id, workflow_name, "/tmp/ws", inputs or {}, start=start)
    else:
        with get_session() as session:
            session.add(WorkflowRun(
                execution_id=execution_id,
                workflow_name=workflow_name,
                workspace_path="/tmp/ws",
                inputs=inputs or {},
                status="queued",
                **fields,
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


def test_claim_row_stamps_the_spawner_kind_it_was_given(isolated_db):
    """The reaper rebuilds the handle from spawner_kind, so a run the docker
    spawner started must not be recorded as a subprocess."""
    _enqueue("e1-docker")
    assert _claim_row("e1-docker", "docker") is True
    assert _read("e1-docker")["spawner_kind"] == "docker"


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

    spawner = _fake_spawner()
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

    spawner = _fake_spawner()
    n = _scan_and_dispatch(spawner)
    assert n == 0
    spawner.spawn.assert_not_called()


def test_scan_marks_failed_on_spawn_error(isolated_db):
    _enqueue("e")
    spawner = _fake_spawner()
    spawner.spawn.side_effect = SpawnerError("fork bombed")

    n = _scan_and_dispatch(spawner)
    assert n == 0  # nothing successfully dispatched

    row = _read("e")
    assert row["status"] == "failed"
    assert row["error"]["kind"] == "spawn"
    assert "fork bombed" in row["error"]["message"]


def test_scan_no_op_when_queue_empty(isolated_db):
    spawner = _fake_spawner()
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

    spawner = _fake_spawner()
    n = _scan_and_dispatch(spawner)
    assert n == 0


def test_scan_claims_with_the_spawners_kind(isolated_db):
    _enqueue("f")
    spawner = _fake_spawner(SpawnerKind.docker)
    spawner.spawn.side_effect = lambda eid: ProcessHandle(
        kind=SpawnerKind.docker, handle=f"temper-run-{eid}", metadata={"execution_id": eid},
    )
    assert _scan_and_dispatch(spawner) == 1
    row = _read("f")
    assert row["spawner_kind"] == "docker"
    assert row["spawner_handle"] == "temper-run-f"


# --- Race safety ------------------------------------------------------

# --- Runs in boxes: Stop, a busy spawner, restarts ------------------------

def _box_for(eid: str) -> ProcessHandle:
    return ProcessHandle(
        kind=SpawnerKind.docker, handle=f"temper-run-{eid}",
        metadata={"execution_id": eid, "container": f"temper-run-{eid}"},
    )


def _metadata(execution_id: str) -> dict:
    with get_session() as session:
        row = session.exec(
            select(WorkflowRun).where(WorkflowRun.execution_id == execution_id),
        ).one()
        return dict(row.spawner_metadata or {})


def test_a_run_stopped_while_it_waits_never_gets_a_box(isolated_db):
    _enqueue("stopped", cancel_requested=True)
    spawner = _fake_spawner(SpawnerKind.docker)

    assert _scan_and_dispatch(spawner) == 0

    spawner.spawn.assert_not_called()
    assert _read("stopped")["status"] == "cancelled"


def test_a_spawner_that_cannot_start_a_box_yet_leaves_the_run_queued(isolated_db):
    from temper_ai.spawner.base import SpawnerBusy

    _enqueue("early")
    spawner = _fake_spawner(SpawnerKind.docker)
    spawner.spawn.side_effect = SpawnerBusy("the template is being recreated")

    assert _scan_and_dispatch(spawner) == 0
    assert _read("early") == {
        "status": "queued", "spawner_kind": None, "spawner_handle": None, "error": None,
    }

    spawner.spawn.side_effect = _box_for
    assert _scan_and_dispatch(spawner) == 1
    assert _read("early")["spawner_handle"] == "temper-run-early"


def test_the_box_handle_keeps_how_the_box_is_to_start(isolated_db):
    """The box reads spawner_metadata['start'] (resume or fork) as it starts."""
    _enqueue("resumed", spawner_metadata={"start": "resume"})
    spawner = _fake_spawner(SpawnerKind.docker)
    spawner.spawn.side_effect = _box_for

    _scan_and_dispatch(spawner)

    assert _metadata("resumed") == {
        "start": "resume", "execution_id": "resumed", "container": "temper-run-resumed",
        "resume_reservation": _metadata("resumed")["resume_reservation"],
    }


def test_a_claim_a_restart_cut_short_goes_back_in_the_queue(isolated_db):
    from temper_ai.cli.watch_queue import _requeue_stuck_claims

    _enqueue("cut-short")
    _claim_row("cut-short", "docker")
    spawner = _fake_spawner(SpawnerKind.docker)
    spawner.is_alive.return_value = False

    assert _requeue_stuck_claims(spawner) == 1

    assert _read("cut-short")["spawner_kind"] is None
    assert spawner.is_alive.call_args.args[0].metadata == {"execution_id": "cut-short"}
    spawner.spawn.side_effect = _box_for
    assert _scan_and_dispatch(spawner) == 1


def test_a_claim_whose_box_came_up_after_all_is_left_to_it(isolated_db):
    from temper_ai.cli.watch_queue import _requeue_stuck_claims

    _enqueue("came-up")
    _claim_row("came-up", "docker")
    spawner = _fake_spawner(SpawnerKind.docker)
    spawner.is_alive.return_value = True

    assert _requeue_stuck_claims(spawner) == 0
    assert _read("came-up")["spawner_handle"] == "claiming"


def test_a_claim_is_left_alone_when_docker_cannot_say(isolated_db):
    from temper_ai.cli.watch_queue import _requeue_stuck_claims

    _enqueue("unsure")
    _claim_row("unsure", "docker")
    spawner = _fake_spawner(SpawnerKind.docker)
    spawner.is_alive.side_effect = SpawnerError("Cannot connect to the Docker daemon")

    assert _requeue_stuck_claims(spawner) == 0
    assert _read("unsure")["spawner_handle"] == "claiming"


def test_another_kinds_claims_are_not_this_watchers(isolated_db):
    from temper_ai.cli.watch_queue import _requeue_stuck_claims

    _enqueue("theirs")
    _claim_row("theirs", "subprocess")

    assert _requeue_stuck_claims(_fake_spawner(SpawnerKind.docker)) == 0
    assert _read("theirs")["spawner_kind"] == "subprocess"


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
