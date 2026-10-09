"""`temper run-workflow --execution-id <id>` — standalone worker entry point.

This is the CLI the spawner (phase 3) launches as a subprocess. Distinct
from `temper run`, the user-facing command:

  - `temper run` asks the server to start a run (POST /api/runs) and
    follows it; it never executes anything itself (cli/run_on_server.py).
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

    # --- The box's own check, before anything is loaded -------------------------
    # A box started with a profile (box_profile.py) checks it matches its digest and, when
    # sealed, that the box is exactly what it grants (a sealed box ran the same check
    # before this program, from code the worker passed it). A box that fails it loads
    # nothing and leaves; the reaper ends the run when the box is gone. A legacy box is
    # never stopped by its profile: it goes on as a box without one.
    from temper_ai.spawner import box_view
    box_doc: dict | None = None
    try:
        box_doc = box_view.check_box()
    except box_view.BoxStartRefused as exc:
        if not _legacy_profile_in_env():
            print(f"box refused: {exc}", file=sys.stderr)
            return BOX_REFUSED_EXIT
        logger.warning("Box for %s: its legacy profile can't be used (%s); it runs without "
                       "one", execution_id, exc)
    unboxed = _unboxed_under_sealed(box_doc)
    if unboxed is not None:
        print(f"box refused: {unboxed}", file=sys.stderr)
        return BOX_REFUSED_EXIT

    # --- A sealed box loads only the launch the worker classified ------------------
    # Every closure file is checked against the profile before anything is loaded; from
    # here on configs come only from those files, and anything outside the launch is
    # refused where it would be used (box_guard.py). A legacy box has no guard.
    from temper_ai.spawner import box_guard
    try:
        box_guard.activate(box_doc)
    except box_guard.LaunchRefused as exc:
        print(f"box refused: {exc}", file=sys.stderr)
        return BOX_REFUSED_EXIT

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

    # --- Is this box the run's current one, and the one its row describes? -----
    refused = _box_refused(execution_id, box_doc, run_row.get("spawner_metadata"))
    if refused is not None:
        return refused

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

    # --- The run's lane (runner/lanes.py, runner/pi_lane.py) -------------------
    # Outside the Pi lane a Pi run refuses; in it, only a Pi run passes, after the Pi-only
    # rule, the preflight and the commit it runs on. Unmarked runs elsewhere: untouched.
    from temper_ai.runner import pi_lane

    lane_refusal = pi_lane.check_run(execution_id, run_row, start=start,
                                     graph_loader=runner_ctx.graph_loader)
    if lane_refusal is not None:
        from temper_ai.runner.parked import repark_timer_refusal

        if start == "resume" and repark_timer_refusal(
                execution_id, run_row, lane_refusal,
                resume_of=(resume_metadata or {}).get("resume_of")):
            # This transport did start, but no member did. Keep its handle until the
            # reaper confirms it gone, exactly as for an ordinary parked workflow.
            _update_run_row(
                execution_id, status="running", started_at=datetime.now(UTC),
                spawner_handle=os.environ.get("TEMPER_RUN_CONTAINER") or str(os.getpid()),
                attempts=run_row["attempts"] + 1,
            )
            logger.info("Run %s: usage-check wake held by %s; stays waiting for its next "
                        "check", execution_id, lane_refusal.kind)
            return 0
        logger.error("Run %s refused: %s", execution_id, lane_refusal.message)
        pi_lane.record_refusal(execution_id, run_row, lane_refusal,
                               resume_of=(resume_metadata or {}).get("resume_of"))
        _safe_mark_failed(execution_id, lane_refusal.message, kind=lane_refusal.kind)
        return pi_lane.REFUSED_EXIT

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
    from temper_ai.runner.attempts import REPLACED_STATUS
    from temper_ai.runner.execute import execute_workflow
    stood_down = False
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
        stood_down = result.status == REPLACED_STATUS
    except pi_lane.LaneDrained as drained:
        # The Pi lane is stopping and this run left at a turn boundary: interrupted, not
        # failed. The Pi lane's next start picks it up from its ledger (runner/pi_lane.py).
        message = ("The Pi lane stopped; the run left at a turn boundary "
                   f"({drained}) and carries on when the lane starts again.")
        _update_run_row(
            execution_id,
            status="orphaned",
            completed_at=datetime.now(UTC),
            error={"message": message, "kind": "drained"},
        )
        from temper_ai.observability.reconcile import INTERRUPTED, settle_run_event

        settle_run_event(execution_id, INTERRUPTED, message)
        return pi_lane.DRAINED_EXIT
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
        if stood_down:
            # A later attempt of the run streams to its viewers now: this box closes its
            # own log file only, and sends them no end-of-run sentinel (SW-84).
            jsonl_notifier.cleanup(execution_id)
        else:
            # Composite cleanup fans out to both sinks: Redis sends terminal
            # sentinel + closes; JSONL writes footer + closes the file.
            notifier.cleanup(execution_id)
        # Redis publisher needs explicit close (TCP socket); JSONL is
        # closed by its own cleanup. Only call close() on the one that has it.
        redis_notifier.close()
        # And the MCP sessions the run opened, so no server holds them after it.
        _stop_mcp_manager()

    # --- A later attempt took the run over: this box stands down ---------------
    if stood_down:
        # The run's row is the newer attempt's (its status, its end, its error): writing
        # this box's end into it would end that attempt's run (SW-84).
        logger.info("Run %s: this box stands down for a later attempt: %s",
                    execution_id, result.error)
        return result.exit_code

    # --- A Pi run waiting on the owner: this box lets go ----------------------
    from temper_ai.runner.parked import PARKED_STATUS, cancel_parked

    if result.status == PARKED_STATUS:
        if cancel_event.is_set():
            # Cancelled while it was letting go: nothing is left to stop.
            cancel_parked(execution_id, by="cancel while its box let go")
            return result.exit_code
        # Its row stays as it is: the worker's reaper sees this box gone, frees the run and
        # carries it on once the owner has answered (runner/parked.py). Writing the row here
        # would let a new box start under this one's name before this one is gone.
        logger.info("Run %s waits on you; its box lets go", execution_id)
        return result.exit_code

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


#: The exit code of a box that refused to start (stale, or not the box its profile says).
BOX_REFUSED_EXIT = 3


def _unboxed_under_sealed(doc: dict | None) -> str | None:
    """Why this process may not run a workflow on a sealed install (None: it may).

    The subprocess spawner's child, or `temper run-workflow` typed by hand, inherits
    TEMPER_BOX_RUNTIME_BOUNDARY=sealed but has no sealed box around it.
    """
    from temper_ai.spawner import box_profile

    try:
        boundary = box_profile.boundary_setting()
    except box_profile.BoxProfileError as exc:
        return str(exc)
    if boundary == box_profile.SEALED and (doc is None or doc.get("boundary") != box_profile.SEALED):
        return (f"{box_profile.BOUNDARY_ENV}=sealed, but this process is not in a sealed box; "
                "runs start only through the docker spawner")
    return None


def _legacy_profile_in_env() -> bool:
    """Whether the profile this box was given (readable or not) is a legacy one."""
    import json

    from temper_ai.spawner import box_view
    try:
        doc = json.loads(os.environ.get(box_view.PROFILE_ENV) or "null")
    except ValueError:
        return False
    return isinstance(doc, dict) and doc.get("boundary") == "legacy"


def _box_refused(execution_id: str, doc: dict | None, metadata: Any) -> int | None:
    """None when the box may run; else its exit code, after failing the run when it should.

    A box whose profile generation is older than the row's is stale (a newer box took the
    run over): it leaves without touching the row. Any other mismatch with the row (a
    sealed run's box without its profile, say) fails the run before any tool.
    """
    from temper_ai.spawner import box_profile, box_view

    try:
        box_profile.check_row(doc, metadata)
    except box_profile.BoxIsStale as exc:
        logger.warning("Box for %s is stale and leaves the run alone: %s", execution_id, exc)
        return BOX_REFUSED_EXIT
    except box_view.BoxStartRefused as exc:
        logger.error("Box for %s refused: %s", execution_id, exc)
        _safe_mark_failed(execution_id, f"box refused: {exc}", kind="box")
        return BOX_REFUSED_EXIT
    return None


def _safe_mark_failed(execution_id: str, message: str, kind: str = "bootstrap") -> None:
    """Best-effort terminal write when bootstrap fails. Swallows DB errors
    because if the DB itself is down there's nothing we can do — the
    server's reaper will sweep us up via process-exit detection.
    """
    try:
        _update_run_row(
            execution_id,
            status="failed",
            completed_at=datetime.now(UTC),
            error={"message": message, "kind": kind},
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
