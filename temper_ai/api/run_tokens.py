"""A run's own key: lets its script steps start and fork runs, nothing else.

A workflow whose scripts start other runs (a loop that dispatches work, a
trial that starts its arms) declares ``starts_runs: true``. When such a run
starts, its process makes a fresh key:

* the key stays in that process's memory (not its environment, so not in
  /proc/<pid>/environ of the box's main process) and goes only to the run's
  script steps, as ``TEMPER_RUN_TOKEN``; agent tools never get it
  (shared/agent_env.py builds their environment without it);
* the server keeps only its sha256, with the run (table ``run_tokens``);
* it answers to the caller name ``box:<run id>``, which the guard
  (api/caller.py) lets start and fork runs and nothing else -- never answer
  a wait, cancel, resume or clean up;
* it dies with the run: the row goes when the run's process ends, and a
  row whose run is over no longer counts.

A workflow without ``starts_runs`` gets no key at all.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import threading

logger = logging.getLogger(__name__)

ENV_NAME = "TEMPER_RUN_TOKEN"  # noqa: S105 - a variable name, not a secret
KEY_PREFIX = "trun_"
_FINISHED = frozenset({"completed", "failed", "cancelled", "orphaned"})

_lock = threading.Lock()
_held: dict[str, str] = {}


def _digest(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def open_for_run(execution_id: str, workflow_name: str = "") -> str | None:
    """Make this run's key, store its hash, and keep the key for its script steps.

    A run that starts again (a resume, a fork into a new box) gets a new key
    and the old one stops working. Returns None when the hash could not be
    stored: the run goes on, and its starts are then refused (in enforce)
    rather than the whole run failing here.
    """
    from temper_ai.api.guard_models import RunToken
    from temper_ai.database.session import get_session

    raw = KEY_PREFIX + secrets.token_urlsafe(32)
    try:
        with get_session() as session:
            row = session.get(RunToken, execution_id)
            if row is None:
                row = RunToken(execution_id=execution_id)
            row.token_hash = _digest(raw)
            row.workflow_name = workflow_name
            session.add(row)
    except Exception:  # noqa: BLE001 - see docstring
        logger.warning("run %s: could not store its own key; its scripts can't start runs", execution_id,
                       exc_info=True)
        return None
    with _lock:
        _held[execution_id] = raw
    logger.info("run %s holds its own key (starts_runs)", execution_id)
    return raw


def close_for_run(execution_id: str) -> None:
    """The run's process is done with it: forget the key and drop its hash."""
    with _lock:
        had = _held.pop(execution_id, None)
    if had is None:
        return
    try:
        from temper_ai.api.guard_models import RunToken
        from temper_ai.database.session import get_session

        with get_session() as session:
            row = session.get(RunToken, execution_id)
            if row is not None and row.token_hash == _digest(had):
                session.delete(row)
    except Exception:  # noqa: BLE001 - the run-status check below still retires it
        logger.warning("run %s: could not drop its own key's hash", execution_id, exc_info=True)


def held(execution_id: str | None) -> str | None:
    """This process's key for the run, for its script steps; None when it has none."""
    if not execution_id:
        return None
    with _lock:
        return _held.get(str(execution_id))


def identify_run_token(presented: str | None) -> str | None:
    """The run id a presented run key belongs to, or None.

    Looked up by the key's hash (a 256-bit random value: its hash says
    nothing). A key whose run is over does not count even if its row
    somehow outlived the run's process.
    """
    if not presented or not presented.startswith(KEY_PREFIX):
        return None
    from sqlmodel import select

    from temper_ai.api.guard_models import RunToken
    from temper_ai.database.session import get_session
    from temper_ai.runner.models import WorkflowRun

    digest = _digest(presented)
    try:
        with get_session() as session:
            row = session.exec(select(RunToken).where(RunToken.token_hash == digest)).first()
            if row is None:
                return None
            run = session.get(WorkflowRun, row.execution_id)
            if run is not None and run.status in _FINISHED:
                return None
            return row.execution_id
    except Exception:  # noqa: BLE001 - unknown is the safe answer
        logger.warning("could not look up a run key", exc_info=True)
        return None


def _reset_for_tests() -> None:
    with _lock:
        _held.clear()
