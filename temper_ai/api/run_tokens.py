"""A run's own keys: each lets the run do one narrow thing through temper's API, nothing else.

Two kinds, both made by the run's own process when the run starts:

* **Starts runs** (``STARTS_RUNS``). A workflow whose scripts start other
  runs (a loop that dispatches work, a trial that starts its arms) declares
  ``starts_runs: true``. Its key goes only to the run's script steps, as
  ``TEMPER_RUN_TOKEN``, and may start and fork runs. A workflow without
  ``starts_runs`` gets none.
* **GitHub tokens** (``GITHUB_TOKENS``). Every run whose process can't make
  GitHub tokens itself (a run in its own box: the app's private key stays on
  the server) gets one, because any run may come to use a GitHub tool: an
  agent's Delegate, AddNode or a dispatch can bring in an agent with one while
  the run goes on. Only the run's own process holds it, to ask the server for
  a token for one repository (``POST /api/github/token``, used by
  integrations/github/app.py ``ServerApp``). It goes to no script step and no
  agent tool: shared/agent_env.py drops it by name and by look.

For both kinds:

* the key stays in that process's memory (not its environment, so not in
  /proc/<pid>/environ of the box's main process);
* the server keeps only its sha256, with the run (tables ``run_tokens`` and
  ``run_github_keys``);
* it answers to the caller name ``box:<run id>``, which the guard
  (api/caller.py) lets do only what its kind may -- never answer a wait,
  cancel, resume or clean up;
* it dies with the run: the row goes when the run's process ends, and a row
  whose run is over no longer counts.

What is still open: an agent in the same box runs as the same user as the
run's process, so until the box runs its process apart from its agents, a
determined agent could dig a key out of that process (docs/api-access.md).
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import threading
from dataclasses import dataclass

from temper_ai.api.caller import BOX_ACTIONS, GITHUB_TOKEN_ACTIONS
from temper_ai.shared.box_env import RUN_GITHUB_KEY_PREFIX

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RunKeyKind:
    """One kind of key a run holds: what it is for, how its keys start, where its hashes are."""

    what: str                # for the log: "starts runs", "GitHub tokens"
    prefix: str              # every key of this kind starts so, which finds its table
    table: str               # api/guard_models.py: "run_tokens", "run_github_keys"
    powers: frozenset[str]   # what the guard lets it do (api/caller.py)
    # Where it opens the door when the server asks a token on every route (TEMPER_API_TOKEN,
    # api/auth.py): path prefixes, or () for every path.
    paths: tuple[str, ...] = ()

    def opens(self, path: str) -> bool:
        return not self.paths or any(path.startswith(p) for p in self.paths)


STARTS_RUNS = RunKeyKind("starts runs", "trun_", "run_tokens", BOX_ACTIONS)
# Its process asks for a token (POST /api/github/token) and lists the app's repos (GET
# /api/github/repos); nothing else.
GITHUB_TOKENS = RunKeyKind("GitHub tokens", RUN_GITHUB_KEY_PREFIX, "run_github_keys", GITHUB_TOKEN_ACTIONS,
                           paths=("/api/github/",))
KINDS = (STARTS_RUNS, GITHUB_TOKENS)

ENV_NAME = "TEMPER_RUN_TOKEN"  # noqa: S105 - a variable name, not a secret
KEY_PREFIX = STARTS_RUNS.prefix
_FINISHED = frozenset({"completed", "failed", "cancelled", "orphaned"})

_lock = threading.Lock()
_held: dict[tuple[str, str], str] = {}  # (kind's table, execution id) -> the key


def _digest(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _model(kind: RunKeyKind):
    from temper_ai.api.guard_models import RunGithubKey, RunToken

    return RunGithubKey if kind is GITHUB_TOKENS else RunToken


def open_for_run(execution_id: str, workflow_name: str = "", kind: RunKeyKind = STARTS_RUNS) -> str | None:
    """Make this run's key of ``kind``, store its hash, and keep the key in this process.

    A run that starts again (a resume, a fork into a new box) gets a new key
    and the old one stops working. Returns None when the hash could not be
    stored: the run goes on, and what the key was for is then refused (in
    enforce) rather than the whole run failing here.
    """
    from temper_ai.database.session import get_session

    model = _model(kind)
    raw = kind.prefix + secrets.token_urlsafe(32)
    try:
        with get_session() as session:
            row = session.get(model, execution_id)
            if row is None:
                row = model(execution_id=execution_id)
            row.token_hash = _digest(raw)
            row.workflow_name = workflow_name
            session.add(row)
    except Exception:  # noqa: BLE001 - see docstring
        logger.warning("run %s: could not store its own key (%s); it goes on without it",
                       execution_id, kind.what, exc_info=True)
        return None
    with _lock:
        _held[(kind.table, execution_id)] = raw
    logger.info("run %s holds its own key (%s)", execution_id, kind.what)
    return raw


def close_for_run(execution_id: str, kind: RunKeyKind = STARTS_RUNS) -> None:
    """The run's process is done with its key of ``kind``: forget the key and drop its hash."""
    with _lock:
        had = _held.pop((kind.table, execution_id), None)
    if had is None:
        return
    try:
        from temper_ai.database.session import get_session

        with get_session() as session:
            row = session.get(_model(kind), execution_id)
            if row is not None and row.token_hash == _digest(had):
                session.delete(row)
    except Exception:  # noqa: BLE001 - the run-status check below still retires it
        logger.warning("run %s: could not drop its own key's hash (%s)", execution_id, kind.what,
                       exc_info=True)


def held(execution_id: str | None, kind: RunKeyKind = STARTS_RUNS) -> str | None:
    """This process's key of ``kind`` for the run; None when it has none."""
    if not execution_id:
        return None
    with _lock:
        return _held.get((kind.table, str(execution_id)))


def is_run_key(presented: str | None) -> bool:
    """Whether a presented key looks like any kind of run key (only then is it looked up)."""
    if not presented:
        return False
    return any(presented.startswith(k.prefix) for k in KINDS)


def identify_run_key(presented: str | None) -> tuple[str, RunKeyKind] | None:
    """The run a presented run key belongs to and its kind, or None.

    Looked up by the key's hash (a 256-bit random value: its hash says
    nothing). A key whose run is over does not count even if its row
    somehow outlived the run's process.
    """
    kind = next((k for k in KINDS if presented and presented.startswith(k.prefix)), None)
    if kind is None or not presented:
        return None
    from sqlmodel import select

    from temper_ai.database.session import get_session
    from temper_ai.runner.models import WorkflowRun

    model = _model(kind)
    digest = _digest(presented)
    try:
        with get_session() as session:
            row = session.exec(select(model).where(model.token_hash == digest)).first()
            if row is None:
                return None
            run = session.get(WorkflowRun, row.execution_id)
            if run is not None and run.status in _FINISHED:
                return None
            return row.execution_id, kind
    except Exception:  # noqa: BLE001 - unknown is the safe answer
        logger.warning("could not look up a run key", exc_info=True)
        return None


def identify_run_token(presented: str | None) -> str | None:
    """The run a presented start/fork key belongs to, or None (any other kind: None)."""
    found = identify_run_key(presented)
    return found[0] if found and found[1] is STARTS_RUNS else None


def _reset_for_tests() -> None:
    with _lock:
        _held.clear()
