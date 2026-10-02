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


def _start_mcp_manager(config_dir: str | None, manager: Any = None) -> None:
    """Load the MCP server configs into the shared manager, as the server does when it starts.

    execute_workflow binds an agent's MCP tools (``playwright.browser_navigate``) only for the
    servers the shared manager knows. The server loads them at startup (server.py); a run in a
    process of its own -- this command, under the subprocess and docker spawners -- never did,
    so every MCP tool was skipped without a word and its agent stopped with
    ToolsNotRegisteredError (seen 2026-09-27, the first runs in boxes: task_verify's browser).

    The manager's coroutines need a loop that keeps running: it gets one of its own in a daemon
    thread, which the tools and the pre-connect reach with run_coroutine_threadsafe. A failure
    here is not fatal, as in the server: a run whose agents use no MCP tool goes on without.
    """
    import asyncio

    if manager is None:
        from temper_ai.tools.mcp_client import mcp_manager as manager
    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, name="mcp-loop", daemon=True).start()
    manager._event_loop = loop
    try:
        asyncio.run_coroutine_threadsafe(manager.start(config_dir=config_dir), loop).result(timeout=10)
        configured = manager.get_configured_servers()
        if configured:
            logger.info("MCP: %d server(s) configured (lazy connect): %s", len(configured), ", ".join(configured))
    except Exception as exc:  # noqa: BLE001 - as the server: non-fatal, a run may need no MCP tool
        logger.warning("MCP setup failed (non-fatal): %s", exc)


def _stop_mcp_manager(manager: Any = None, timeout: float = 15) -> None:
    """End the MCP sessions this run opened, before its process exits.

    Ending a session tells its server so (an HTTP session is deleted). A run in a box of its own
    used to exit holding the session it opens up front to learn the tools (preconnect_mcp_servers),
    and the server on the other end kept it until it gave up waiting. The signed-in browser's proxy
    (local/chrome-mcp) keeps an idle session 30 minutes and allows six at once, so five runs in a
    row filled it and the next session was turned away with a bare "503 Service Unavailable" (seen
    2026-10-01). An agent's own session already ends with its node (MCPClientManager.release);
    this ends the rest. Best effort, like the setup: a session that will not close must not change
    the run's result.
    """
    import asyncio

    if manager is None:
        from temper_ai.tools.mcp_client import mcp_manager as manager
    loop = getattr(manager, "_event_loop", None)
    if loop is None or not loop.is_running():
        return
    ending = asyncio.run_coroutine_threadsafe(manager.stop(), loop)
    try:
        ending.result(timeout=timeout)
    except Exception as exc:  # noqa: BLE001 - never the run's undoing
        ending.cancel()
        logger.warning("MCP sessions did not all close at the end of the run: %r", exc)


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

    # --- Resume or fork? --------------------------------------------------------
    # The server queues resumes and forks too (spawner_metadata["start"]), so
    # they run in a box like any other run. Both restore from checkpoints; a
    # resume also links to the attempt it continues and replays its dispatches.
    # Worked out before this attempt writes its own workflow.started event.
    meta = run_row.get("spawner_metadata") or {}
    start = meta.get("start")
    # Ticked on the preview: steps that finished and are to run again anyway. And, for the
    # pass that runs a failed run's held clean-ups, the only paths it may run.
    rerun = [str(p) for p in (meta.get("rerun") or [])]
    run_only = [str(p) for p in (meta.get("only") or [])] or None
    try:
        initial_outputs, resume_metadata = _restored_state(execution_id, start)
    except Exception as exc:
        logger.exception("Could not restore %s for its %s: %s", execution_id, start, exc)
        _safe_mark_failed(execution_id, f"{start} failed: {exc}")
        return 2

    # --- Mark running ---------------------------------------------------------
    # The handle the reaper polls: our PID under the subprocess spawner, our
    # container's name when the docker spawner put us in one (a PID would
    # mean nothing outside the container).
    _update_run_row(
        execution_id,
        status="running",
        started_at=datetime.now(UTC),
        spawner_handle=os.environ.get("TEMPER_RUN_CONTAINER") or str(os.getpid()),
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
    from temper_ai.observability.webhook_notifier import WebhookNotifier
    webhook = WebhookNotifier()
    notifier = CompositeNotifier(
        redis_notifier,
        jsonl_notifier,
        webhook if webhook.enabled else None,
    )

    # --- MCP servers: their configs, as the server loads them when it starts --
    _start_mcp_manager(getattr(args, "config_dir", None))

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
            initial_outputs=initial_outputs,
            resume_metadata=resume_metadata,
            replay_dispatch_history=start == "resume",
            rerun=rerun,
            run_only=run_only,
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
        # And the MCP sessions the run opened, so no server holds them after it.
        _stop_mcp_manager()

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


def _restored_state(
    execution_id: str, start: str | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """(initial_outputs, resume_metadata) for a queued resume or fork.

    A fresh run gets (None, None). A fork's checkpoints were copied under its
    new id by the server, so both kinds restore the same way.
    """
    if start not in ("resume", "fork", "cleanup"):
        return None, None
    from temper_ai.checkpoint.service import CheckpointService
    initial_outputs = CheckpointService(execution_id).reconstruct()
    if start == "fork":
        return initial_outputs, None
    if start == "cleanup":
        # Only the clean-ups the run was holding, now that the wait is over. Everything
        # else keeps the result it has; the run stays failed.
        return initial_outputs, {"cleanup_of": execution_id,
                                 "restored_node_names": sorted(initial_outputs)}
    from temper_ai.runner.resume import find_latest_workflow_event
    previous = find_latest_workflow_event(execution_id)
    return initial_outputs, {
        "resume_of": previous["id"] if previous else None,
        "restored_node_names": sorted(initial_outputs),
        "replayed_dispatches": [],
    }


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
            "spawner_metadata": dict(row.spawner_metadata or {}),
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
