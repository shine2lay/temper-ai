"""Tests for the Reaper — drives reaper.tick() against a fake spawner.

We don't start the background thread (use direct .tick() calls for
determinism). Spawner is mocked since the reaper's only contract with it
is is_alive() / kill() — we want to test the row-state transitions, not
re-test SubprocessSpawner.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from sqlmodel import select

from temper_ai.database import get_session, init_database, reset_database
from temper_ai.runner.models import WorkflowRun
from temper_ai.spawner.base import Spawner, SpawnerError
from temper_ai.spawner.reaper import Reaper


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    db_path = tmp_path / "reaper_test.db"
    monkeypatch.setenv("TEMPER_DATABASE_URL", f"sqlite:///{db_path}")
    reset_database()
    init_database(f"sqlite:///{db_path}")
    yield db_path
    reset_database()


def _insert_run(
    execution_id: str,
    *,
    status: str = "running",
    spawner_kind: str | None = "subprocess",
    spawner_handle: str | None = "12345",
    cancel_requested: bool = False,
) -> None:
    with get_session() as session:
        session.add(WorkflowRun(
            execution_id=execution_id,
            workflow_name="test",
            workspace_path="/tmp/test",
            status=status,
            spawner_kind=spawner_kind,
            spawner_handle=spawner_handle,
            cancel_requested=cancel_requested,
            started_at=datetime.now(UTC),
        ))


def _read_status(execution_id: str) -> str:
    with get_session() as session:
        row = session.exec(
            select(WorkflowRun).where(WorkflowRun.execution_id == execution_id),
        ).one()
        return row.status


def _read_error(execution_id: str) -> dict | None:
    with get_session() as session:
        row = session.exec(
            select(WorkflowRun).where(WorkflowRun.execution_id == execution_id),
        ).one()
        return row.error


@pytest.fixture
def fake_spawner() -> Spawner:
    """Mock Spawner for reaper tests — fully controlled is_alive / kill."""
    return MagicMock(spec=Spawner)


# --- Liveness reaping --------------------------------------------------

def test_dead_running_row_marked_orphaned(isolated_db, fake_spawner):
    _insert_run("dead-1")
    fake_spawner.is_alive.return_value = False

    reaper = Reaper(fake_spawner, interval_seconds=0.01)
    reaper.tick()

    assert _read_status("dead-1") == "orphaned"
    err = _read_error("dead-1")
    assert err is not None
    assert err["kind"] == "orphaned"


def test_alive_running_row_left_alone(isolated_db, fake_spawner):
    _insert_run("alive-1")
    fake_spawner.is_alive.return_value = True

    reaper = Reaper(fake_spawner, interval_seconds=0.01)
    reaper.tick()

    assert _read_status("alive-1") == "running"
    fake_spawner.kill.assert_not_called()


def test_terminal_row_skipped(isolated_db, fake_spawner):
    """Reaper only looks at status='running' rows."""
    _insert_run("done-1", status="completed")
    fake_spawner.is_alive.return_value = False

    reaper = Reaper(fake_spawner, interval_seconds=0.01)
    reaper.tick()

    assert _read_status("done-1") == "completed"
    fake_spawner.is_alive.assert_not_called()


def test_missing_handle_marked_orphaned(isolated_db, fake_spawner):
    """Spawn was attempted but handle never persisted — orphan it."""
    _insert_run("no-handle", spawner_handle=None)

    reaper = Reaper(fake_spawner, interval_seconds=0.01)
    reaper.tick()

    assert _read_status("no-handle") == "orphaned"
    fake_spawner.is_alive.assert_not_called()


def test_in_process_runs_skipped(isolated_db, fake_spawner):
    """Reaper only sweeps rows with spawner_kind set (subprocess runs).
    In-process runs predate the WorkflowRun row mechanism entirely."""
    _insert_run("inprocess-1", spawner_kind=None)

    reaper = Reaper(fake_spawner, interval_seconds=0.01)
    reaper.tick()

    assert _read_status("inprocess-1") == "running"
    fake_spawner.is_alive.assert_not_called()


# --- Cancellation flow -------------------------------------------------

def test_cancel_requested_sends_sigterm(isolated_db, fake_spawner):
    _insert_run("cancel-1", cancel_requested=True)
    fake_spawner.is_alive.return_value = True

    reaper = Reaper(fake_spawner, interval_seconds=0.01, kill_grace_seconds=10)
    reaper.tick()

    fake_spawner.kill.assert_called_once()
    assert fake_spawner.kill.call_args.kwargs["force"] is False
    # Status remains running — worker writes the cancelled milestone itself
    assert _read_status("cancel-1") == "running"


def test_cancel_grace_elapsed_escalates_to_sigkill(isolated_db, fake_spawner):
    _insert_run("cancel-2", cancel_requested=True)
    fake_spawner.is_alive.return_value = True

    reaper = Reaper(fake_spawner, interval_seconds=0.01, kill_grace_seconds=0)
    # First tick: SIGTERM
    reaper.tick()
    # Force grace to be 'long expired'
    reaper._termed_at["cancel-2"] = datetime.now(UTC) - timedelta(seconds=60)
    # Second tick: SIGKILL + mark cancelled
    reaper.tick()

    assert fake_spawner.kill.call_count == 2
    second_call = fake_spawner.kill.call_args_list[1]
    assert second_call.kwargs["force"] is True
    assert _read_status("cancel-2") == "cancelled"


def test_cancel_signal_failure_marks_orphaned(isolated_db, fake_spawner):
    _insert_run("cancel-3", cancel_requested=True)
    fake_spawner.is_alive.return_value = True
    fake_spawner.kill.side_effect = SpawnerError("kill failed")

    reaper = Reaper(fake_spawner, interval_seconds=0.01)
    reaper.tick()

    assert _read_status("cancel-3") == "orphaned"


def test_dead_worker_with_cancel_requested_marked_orphaned(isolated_db, fake_spawner):
    """If the worker died on its own before cancel arrived, no kill needed —
    just orphan the row so the UI moves on."""
    _insert_run("cancel-dead", cancel_requested=True)
    fake_spawner.is_alive.return_value = False

    reaper = Reaper(fake_spawner, interval_seconds=0.01)
    reaper.tick()

    assert _read_status("cancel-dead") == "orphaned"
    fake_spawner.kill.assert_not_called()


# --- Runs in boxes ---------------------------------------------------------
# The dashboard, Slack and the notify loop read the run's workflow.started
# event, not its row: when the reaper ends a run, it ends that event too.

def _open_event(execution_id: str, status: str = "running") -> str:
    from temper_ai.observability.models import Event

    with get_session() as session:
        session.add(Event(
            id=f"ev-{execution_id}", type="workflow.started", execution_id=execution_id,
            status=status, data={}, timestamp=datetime.now(UTC).replace(tzinfo=None),
        ))
    return f"ev-{execution_id}"


def _event(event_id: str) -> tuple[str, dict]:
    from temper_ai.observability.models import Event

    with get_session() as session:
        event = session.get(Event, event_id)
        return event.status, dict(event.data or {})


def test_a_box_that_died_mid_run_ends_its_event_too(isolated_db, fake_spawner):
    _insert_run("box-dead", spawner_kind="docker", spawner_handle="temper-run-box-dead")
    event_id = _open_event("box-dead")
    fake_spawner.is_alive.return_value = False

    Reaper(fake_spawner, interval_seconds=0.01).tick()

    assert _read_status("box-dead") == "orphaned"
    status, data = _event(event_id)
    assert status == "interrupted"
    assert "stopped before it finished" in data["error"]


def test_a_run_that_ended_itself_keeps_its_own_event(isolated_db, fake_spawner):
    _insert_run("box-done", spawner_kind="docker", spawner_handle="temper-run-box-done")
    event_id = _open_event("box-done", status="completed")
    fake_spawner.is_alive.return_value = False

    Reaper(fake_spawner, interval_seconds=0.01).tick()

    assert _event(event_id)[0] == "completed"


def test_a_stop_that_needed_force_ends_the_event_as_cancelled(isolated_db, fake_spawner):
    _insert_run("box-stuck", spawner_kind="docker", spawner_handle="temper-run-box-stuck",
                cancel_requested=True)
    event_id = _open_event("box-stuck", status="waiting")
    fake_spawner.is_alive.return_value = True

    reaper = Reaper(fake_spawner, interval_seconds=0.01, kill_grace_seconds=0)
    reaper.tick()
    reaper._termed_at["box-stuck"] = datetime.now(UTC) - timedelta(seconds=60)
    reaper.tick()

    assert _read_status("box-stuck") == "cancelled"
    assert _event(event_id)[0] == "cancelled"


def test_a_box_that_died_before_starting_its_run_fails_it(isolated_db, fake_spawner):
    _insert_run("box-early", status="queued", spawner_kind="docker",
                spawner_handle="temper-run-box-early")
    fake_spawner.is_alive.return_value = False

    Reaper(fake_spawner, interval_seconds=0.01).tick()

    assert _read_status("box-early") == "failed"
    assert _read_error("box-early")["kind"] == "spawn"


def test_a_run_stopped_before_its_box_started_it_is_cancelled(isolated_db, fake_spawner):
    _insert_run("box-stop", status="queued", spawner_kind="docker",
                spawner_handle="temper-run-box-stop", cancel_requested=True)
    fake_spawner.is_alive.return_value = False

    Reaper(fake_spawner, interval_seconds=0.01).tick()

    assert _read_status("box-stop") == "cancelled"


def test_a_box_still_starting_is_left_to_start(isolated_db, fake_spawner):
    _insert_run("box-starting", status="queued", spawner_kind="docker",
                spawner_handle="temper-run-box-starting")
    fake_spawner.is_alive.return_value = True

    Reaper(fake_spawner, interval_seconds=0.01).tick()

    assert _read_status("box-starting") == "queued"
    fake_spawner.kill.assert_not_called()


def test_a_claim_with_no_box_yet_is_the_watchers_not_the_reapers(isolated_db, fake_spawner):
    _insert_run("claiming", status="queued", spawner_kind="docker", spawner_handle="claiming")

    Reaper(fake_spawner, interval_seconds=0.01).tick()

    fake_spawner.is_alive.assert_not_called()
    assert _read_status("claiming") == "queued"


def test_a_docker_that_does_not_answer_buries_nothing(isolated_db, fake_spawner):
    _insert_run("box-unsure", spawner_kind="docker", spawner_handle="temper-run-box-unsure")
    event_id = _open_event("box-unsure")
    fake_spawner.is_alive.side_effect = SpawnerError("Cannot connect to the Docker daemon")

    Reaper(fake_spawner, interval_seconds=0.01).tick()

    assert _read_status("box-unsure") == "running"
    assert _event(event_id)[0] == "running"


def test_one_bad_row_does_not_stop_the_rest(isolated_db, fake_spawner):
    _insert_run("row-a", spawner_kind="docker", spawner_handle="temper-run-row-a")
    _insert_run("row-b", spawner_kind="docker", spawner_handle="temper-run-row-b")
    fake_spawner.is_alive.side_effect = [RuntimeError("surprise"), False]

    Reaper(fake_spawner, interval_seconds=0.01).tick()

    assert sorted([_read_status("row-a"), _read_status("row-b")]) == ["orphaned", "running"]


# --- Lifecycle ---------------------------------------------------------

def test_start_and_stop_thread(isolated_db, fake_spawner):
    """Reaper.start() spawns a thread; stop() joins it."""
    fake_spawner.is_alive.return_value = True
    reaper = Reaper(fake_spawner, interval_seconds=0.05)
    reaper.start()
    try:
        # Brief wait so the thread runs at least one tick
        import time
        time.sleep(0.1)
        assert reaper._thread is not None
        assert reaper._thread.is_alive()
    finally:
        reaper.stop(timeout=2.0)
    assert not reaper._thread.is_alive()


def test_double_start_is_idempotent(isolated_db, fake_spawner):
    fake_spawner.is_alive.return_value = True
    reaper = Reaper(fake_spawner, interval_seconds=0.05)
    reaper.start()
    first_thread = reaper._thread
    reaper.start()  # no-op while already running
    assert reaper._thread is first_thread
    reaper.stop(timeout=2.0)


def test_handle_with_bad_kind_marked_orphaned(isolated_db, fake_spawner):
    """Corrupt spawner_kind string in DB → orphan, don't crash."""
    _insert_run("bad-kind", spawner_kind="not-a-real-kind")

    reaper = Reaper(fake_spawner, interval_seconds=0.01)
    reaper.tick()

    assert _read_status("bad-kind") == "orphaned"
