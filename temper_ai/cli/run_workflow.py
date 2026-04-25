"""`temper run-workflow --execution-id <id>` — standalone worker entry point.

This is the CLI the spawner (phase 3) launches as a subprocess. Distinct
from `temper run` which is the user-facing terminal command:

  - `temper run` creates a fresh execution_id, prints to stdout, designed
    for interactive single-shot use.
  - `temper run-workflow` reads an existing WorkflowRun row that the
    server (or another orchestrator) has pre-inserted, executes it, and
    writes the terminal status back. No interactive output — events flow
    through the EventRecorder (DB) and, in phase 4, Redis chunks.

Lifecycle (matches WorkflowRun docstring):
  1. Server inserts WorkflowRun row with status="queued"
  2. Spawner launches `temper run-workflow --execution-id <id>`
  3. This module updates row to status="running", started_at=now
  4. SIGTERM/SIGINT → cancel_event.set() → executor exits at next node boundary
  5. execute_workflow() returns ExecuteResult
  6. This module updates row with terminal status + result/error + completed_at
  7. Process exits with result.exit_code

Phase 2 ships steps 3-7. Step 2 (the spawner) lands in phase 3; step 1
already exists in routes.py.
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import threading
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


def cmd_run_workflow(args: argparse.Namespace) -> int:
    """Run a single WorkflowRun row to completion. Returns the exit code.

    The CLI dispatcher in main.py calls sys.exit(cmd_run_workflow(args));
    keeping the function pure-return makes it testable without a subprocess.
    """
    execution_id: str = args.execution_id

    # --- Bootstrap (DB + LLM + memory + configs) ------------------------------
    from temper_ai.runner.bootstrap import bootstrap_runner_context_from_env
    try:
        runner_ctx = bootstrap_runner_context_from_env(
            config_dir=getattr(args, "config_dir", None),
        )
    except Exception as exc:
        logger.exception("Worker bootstrap failed for %s: %s", execution_id, exc)
        _safe_mark_failed(execution_id, f"bootstrap failed: {exc}")
        return 2

    # --- Read the queued run row ---------------------------------------------
    run_row = _load_run_row(execution_id)
    if run_row is None:
        print(
            f"Error: no WorkflowRun row for execution_id={execution_id}",
            file=sys.stderr,
        )
        return 2

    # --- Mark running ---------------------------------------------------------
    _update_run_row(
        execution_id,
        status="running",
        started_at=datetime.now(UTC),
        spawner_handle=str(os.getpid()),
        attempts=run_row["attempts"] + 1,
    )

    # --- Cancel signal handling ----------------------------------------------
    cancel_event = threading.Event()
    _install_signal_handlers(cancel_event, execution_id)

    # --- Sinks: live-streaming + JSONL forensic log --------------------------
    # Two sinks composed via CompositeNotifier:
    #   * RedisChunkNotifier: chunks → Redis Streams → server WS forwarder
    #     (best-effort live UX; degrades silently if Redis is down)
    #   * JsonlNotifier: every event → ${TEMPER_LOG_DIR}/{exec_id}/events.jsonl
    #     (forensic record + analytics input; survives DB resets)
    # Events also go to DB via EventRecorder; these sinks are additive.
    from temper_ai.observability.composite_notifier import CompositeNotifier
    from temper_ai.observability.jsonl_logger import JsonlNotifier
    from temper_ai.streaming import RedisChunkNotifier
    redis_notifier = RedisChunkNotifier()
    jsonl_notifier = JsonlNotifier(
        execution_id,
        run_row["workflow_name"],
        metadata={
            "workspace_path": run_row["workspace_path"],
            "spawned_via": "temper run-workflow",
        },
    )
    notifier = CompositeNotifier(redis_notifier, jsonl_notifier)

    # --- Execute --------------------------------------------------------------
    from temper_ai.runner.execute import execute_workflow
    try:
        result = execute_workflow(
            execution_id=execution_id,
            workflow_name=run_row["workflow_name"],
            workspace_path=run_row["workspace_path"],
            inputs=run_row["inputs"] or {},
            runner_ctx=runner_ctx,
            notifier=notifier,
            cancel_event=cancel_event,
        )
    except Exception as exc:
        # execute_workflow already catches its own exceptions and returns
        # ExecuteResult; getting here means a bug in execute_workflow itself.
        logger.exception("Worker crashed unexpectedly: %s", exc)
        _update_run_row(
            execution_id,
            status="failed",
            completed_at=datetime.now(UTC),
            error={"message": str(exc), "kind": type(exc).__name__},
        )
        return 1
    finally:
        # Composite cleanup fans out to both sinks: Redis sends terminal
        # sentinel + closes; JSONL writes footer + closes the file.
        notifier.cleanup(execution_id)
        # Redis publisher needs explicit close (TCP socket); JSONL is
        # closed by its own cleanup. Only call close() on the one that has it.
        redis_notifier.close()

    # --- Persist terminal state ----------------------------------------------
    final_status = (
        "cancelled" if cancel_event.is_set() and result.status != "completed"
        else result.status
    )
    _update_run_row(
        execution_id,
        status=final_status,
        completed_at=datetime.now(UTC),
        result={
            "cost_usd": result.cost_usd,
            "total_tokens": result.total_tokens,
            "exit_code": result.exit_code,
        },
        error={"message": result.error} if result.error else None,
    )

    return result.exit_code


# --- WorkflowRun row helpers -------------------------------------------------

def _load_run_row(execution_id: str) -> dict[str, Any] | None:
    """Fetch the WorkflowRun row as a plain dict, or None if missing.

    Returning a dict (vs the SQLModel object) decouples callers from the
    session lifetime — important here since the row is read once at startup
    and then we don't hold the session for the whole run.
    """
    from sqlmodel import select

    from temper_ai.database import get_session
    from temper_ai.runner.models import WorkflowRun

    with get_session() as session:
        row = session.exec(
            select(WorkflowRun).where(WorkflowRun.execution_id == execution_id),
        ).first()
        if row is None:
            return None
        return {
            "execution_id": row.execution_id,
            "workflow_name": row.workflow_name,
            "workspace_path": row.workspace_path,
            "inputs": row.inputs,
            "status": row.status,
            "attempts": row.attempts,
        }


def _update_run_row(execution_id: str, **fields: Any) -> None:
    """Patch named fields on the WorkflowRun row. Silently no-ops if the
    row vanished — at terminal time, missing-row means cleanup happened
    elsewhere; not worth crashing the worker over.
    """
    from sqlmodel import select

    from temper_ai.database import get_session
    from temper_ai.runner.models import WorkflowRun

    with get_session() as session:
        row = session.exec(
            select(WorkflowRun).where(WorkflowRun.execution_id == execution_id),
        ).first()
        if row is None:
            logger.warning(
                "WorkflowRun row vanished mid-update for %s; fields=%s",
                execution_id, list(fields.keys()),
            )
            return
        for key, value in fields.items():
            setattr(row, key, value)
        session.add(row)


def _safe_mark_failed(execution_id: str, message: str) -> None:
    """Best-effort terminal write when bootstrap fails. Swallows DB errors
    because if the DB itself is down there's nothing we can do — the
    server's reaper will sweep us up via process-exit detection.
    """
    try:
        _update_run_row(
            execution_id,
            status="failed",
            completed_at=datetime.now(UTC),
            error={"message": message, "kind": "bootstrap"},
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Could not mark run %s as failed: %s", execution_id, exc,
        )


# --- Signal handlers ---------------------------------------------------------

def _install_signal_handlers(
    cancel_event: threading.Event, execution_id: str,
) -> None:
    """Wire SIGTERM/SIGINT → cancel_event.set().

    Cooperative cancellation: the executor checks cancel_event at node
    boundaries. The first signal politely asks; a second signal in the
    same process restores the default handler so the user (or spawner)
    can hard-kill if the workflow refuses to wind down.
    """
    def _handle(signum: int, _frame: Any) -> None:
        logger.warning(
            "Worker %s received signal %d — requesting cancellation",
            execution_id, signum,
        )
        cancel_event.set()
        # Restore default so a second signal terminates immediately.
        signal.signal(signum, signal.SIG_DFL)

    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)
