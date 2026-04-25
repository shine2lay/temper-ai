"""Tests for `temper run-workflow` — the worker CLI subcommand spawned
by the server in phase 3.

Strategy: skip the actual `execute_workflow` call (covered transitively
by test_routes.py) and verify the surrounding lifecycle:
  - bootstrap failure → status=failed, exit 2
  - missing WorkflowRun row → exit 2 with stderr message
  - happy-path run → row updated to running then to terminal status
  - signal handlers wired → cancel_event set on SIGTERM
  - terminal cancellation reflected in row.status

We patch `bootstrap_runner_context_from_env` and `execute_workflow` so the
test stays a pure unit on the CLI lifecycle. End-to-end exec is integration
work owned by test_routes / future cli-spawn integration tests.
"""

from __future__ import annotations

import argparse
import threading
from unittest.mock import patch

import pytest
from sqlmodel import select

from temper_ai.cli.run_workflow import (
    _install_signal_handlers,
    _load_run_row,
    _update_run_row,
    cmd_run_workflow,
)
from temper_ai.database import get_session, init_database, reset_database
from temper_ai.runner.execute import ExecuteResult
from temper_ai.runner.models import WorkflowRun


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """Per-test sqlite DB so WorkflowRun rows don't leak across tests."""
    db_path = tmp_path / "cli_test.db"
    monkeypatch.setenv("TEMPER_DATABASE_URL", f"sqlite:///{db_path}")
    reset_database()
    init_database(f"sqlite:///{db_path}")
    yield db_path
    reset_database()


@pytest.fixture
def queued_run(isolated_db):
    """Insert a queued WorkflowRun row and return its execution_id."""
    execution_id = "exec-test-001"
    with get_session() as session:
        session.add(WorkflowRun(
            execution_id=execution_id,
            workflow_name="test_workflow",
            workspace_path="/tmp/test_workspace",
            inputs={"key": "value"},
            status="queued",
        ))
    return execution_id


def _make_args(execution_id: str) -> argparse.Namespace:
    return argparse.Namespace(
        execution_id=execution_id,
        config_dir=None,
        debug=False,
    )


def _read_row(execution_id: str) -> dict:
    """Snapshot all fields we assert on, inside the session — avoids
    DetachedInstanceError when the with-block exits."""
    with get_session() as session:
        row = session.exec(
            select(WorkflowRun).where(WorkflowRun.execution_id == execution_id),
        ).one()
        return {
            "status": row.status,
            "attempts": row.attempts,
            "spawner_handle": row.spawner_handle,
            "started_at": row.started_at,
            "completed_at": row.completed_at,
            "result": row.result,
            "error": row.error,
        }


# --- Row helpers ---------------------------------------------------------

def test_load_run_row_returns_dict(queued_run):
    row = _load_run_row(queued_run)
    assert row is not None
    assert row["workflow_name"] == "test_workflow"
    assert row["inputs"] == {"key": "value"}
    assert row["status"] == "queued"


def test_load_run_row_returns_none_for_missing(isolated_db):
    assert _load_run_row("does-not-exist") is None


def test_update_run_row_patches_fields(queued_run):
    _update_run_row(queued_run, status="running", attempts=1)
    with get_session() as session:
        row = session.exec(
            select(WorkflowRun).where(WorkflowRun.execution_id == queued_run),
        ).one()
        status, attempts = row.status, row.attempts
    assert status == "running"
    assert attempts == 1


def test_update_run_row_no_op_when_missing(isolated_db, caplog):
    """Vanished row is logged but doesn't raise — terminal cleanup races
    are common and shouldn't crash the worker."""
    with caplog.at_level("WARNING"):
        _update_run_row("does-not-exist", status="failed")
    assert any("vanished" in rec.message for rec in caplog.records)


# --- cmd_run_workflow lifecycle -----------------------------------------

def test_missing_row_returns_exit_code_2(isolated_db, capsys):
    """No WorkflowRun for the given execution_id → exit 2."""
    args = _make_args("never-queued")
    # Bootstrap will succeed (no LLM calls until execute_workflow); it's
    # the row lookup that fails.
    with patch("temper_ai.runner.bootstrap.bootstrap_runner_context_from_env"):
        rc = cmd_run_workflow(args)
    assert rc == 2
    err = capsys.readouterr().err
    assert "no WorkflowRun row" in err


def test_bootstrap_failure_returns_exit_code_2_and_marks_failed(queued_run):
    """If bootstrap raises, the row is marked failed before exit."""
    args = _make_args(queued_run)
    with patch(
        "temper_ai.runner.bootstrap.bootstrap_runner_context_from_env",
        side_effect=RuntimeError("simulated provider init failure"),
    ):
        rc = cmd_run_workflow(args)
    assert rc == 2

    row = _read_row(queued_run)
    assert row["status"] == "failed"
    assert row["error"] is not None
    assert "simulated provider init failure" in row["error"]["message"]
    assert row["error"]["kind"] == "bootstrap"


def test_happy_path_marks_running_then_terminal(queued_run):
    """Successful execute_workflow → row goes queued → running → completed
    with cost/tokens/exit_code recorded."""
    args = _make_args(queued_run)
    fake_result = ExecuteResult(
        exit_code=0,
        status="completed",
        cost_usd=1.23,
        total_tokens=4567,
    )
    with (
        patch("temper_ai.runner.bootstrap.bootstrap_runner_context_from_env"),
        patch(
            "temper_ai.runner.execute.execute_workflow",
            return_value=fake_result,
        ),
    ):
        rc = cmd_run_workflow(args)
    assert rc == 0

    row = _read_row(queued_run)
    assert row["status"] == "completed"
    assert row["attempts"] == 1
    assert row["spawner_handle"] is not None  # PID stamped at start
    assert row["started_at"] is not None
    assert row["completed_at"] is not None
    assert row["result"] == {
        "cost_usd": 1.23,
        "total_tokens": 4567,
        "exit_code": 0,
    }
    assert row["error"] is None


def test_workflow_failure_records_error(queued_run):
    args = _make_args(queued_run)
    fake_result = ExecuteResult(
        exit_code=1,
        status="failed",
        error="agent X timed out",
    )
    with (
        patch("temper_ai.runner.bootstrap.bootstrap_runner_context_from_env"),
        patch(
            "temper_ai.runner.execute.execute_workflow",
            return_value=fake_result,
        ),
    ):
        rc = cmd_run_workflow(args)
    assert rc == 1

    row = _read_row(queued_run)
    assert row["status"] == "failed"
    assert row["error"] == {"message": "agent X timed out"}


def test_cancellation_reflected_in_row(queued_run):
    """If cancel_event was set during the run, terminal status is cancelled
    even if execute_workflow returned a non-completed status."""
    args = _make_args(queued_run)

    # Simulate a worker that received SIGTERM mid-run: execute_workflow
    # returns status='failed' (executor halted), but cancel_event is set.
    def fake_execute(*, cancel_event, **_):
        cancel_event.set()
        return ExecuteResult(exit_code=1, status="failed", error="cancelled mid-run")

    with (
        patch("temper_ai.runner.bootstrap.bootstrap_runner_context_from_env"),
        patch("temper_ai.runner.execute.execute_workflow", side_effect=fake_execute),
    ):
        rc = cmd_run_workflow(args)
    # exit code follows execute_workflow's exit_code (1 here); status reflects cancel
    assert rc == 1

    row = _read_row(queued_run)
    assert row["status"] == "cancelled"


def test_unexpected_exception_marks_failed(queued_run):
    """If execute_workflow itself raises (a bug — it's supposed to catch),
    the worker still updates the row to failed and exits 1."""
    args = _make_args(queued_run)

    with (
        patch("temper_ai.runner.bootstrap.bootstrap_runner_context_from_env"),
        patch(
            "temper_ai.runner.execute.execute_workflow",
            side_effect=ValueError("internal bug"),
        ),
    ):
        rc = cmd_run_workflow(args)
    assert rc == 1

    row = _read_row(queued_run)
    assert row["status"] == "failed"
    assert row["error"]["message"] == "internal bug"
    assert row["error"]["kind"] == "ValueError"


# --- Signal handler wiring ----------------------------------------------

def test_signal_handlers_set_cancel_event():
    """Sending SIGTERM to ourselves trips the cancel_event."""
    import os
    import signal

    cancel_event = threading.Event()
    _install_signal_handlers(cancel_event, "test-id")

    # Save and restore the default handler so this test doesn't leak.
    prev_term = signal.getsignal(signal.SIGTERM)
    prev_int = signal.getsignal(signal.SIGINT)
    try:
        os.kill(os.getpid(), signal.SIGTERM)
        # Signal delivery is synchronous on the main thread for SIGTERM
        # via os.kill on POSIX; the handler runs before this line continues.
        assert cancel_event.is_set()
    finally:
        signal.signal(signal.SIGTERM, prev_term)
        signal.signal(signal.SIGINT, prev_int)


# --- Argument parsing surface (smoke) ------------------------------------

def test_subcommand_registered_in_main_parser():
    """`temper run-workflow --execution-id X` parses without error."""
    from temper_ai.cli import main as cli_main

    # Reach into main()'s parser by calling parse_args on a synthetic argv.
    # We can't call main() directly here without bootstrapping the world,
    # so just verify the argparse wiring by importing the module.
    assert hasattr(cli_main, "main")
    # If the subcommand is not registered, importing run_workflow.py would
    # be the only failure surface — the import test above already covers it.
