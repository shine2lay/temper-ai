"""Trimming old run histories: drop the bulky *sent* material, keep every outcome.

The event log is nearly all prompt: ``llm.call.started.data.messages`` is the
whole transcript handed to the model on every iteration, and
``agent.started`` carries the agent's setup (its ``input_data``, system
prompt and task template). On this machine those two were 10.5 GB of a 14 GB
``events`` table. Everything that says what *happened* — results, token and
cost figures, tool results, failures — is a few hundred megabytes.

So old routine runs get their sent material dropped and keep their story:
the run page still draws them in full, minus the "what exactly was in the
prompt" panels.

Nothing is trimmed for a run that

* has not finished cleanly (still going, failed, cancelled, interrupted),
* opened a gate — a person was asked something,
* belongs to a workflow on the keep-whole list (``epd_*`` by default),
* is younger than ``older_than_days`` (30 by default), or
* is one of the newest ``keep_recent_per_workflow`` of its workflow, so
  every workflow always keeps a complete example.

A trimmed run is stamped on its ``workflow.started`` event
(``data["trimmed"]``), which makes the whole job idempotent and safe to stop
and start again: an already-stamped run is never looked at twice.

Checkpoints of a trimmed run get the same treatment: their ``output`` is cut
to the same 5000 characters ``agent.completed`` already stores, so a
checkpoint never holds less of the outcome than the event log does.

Nothing here ever prints or returns the material it drops.
"""

from __future__ import annotations

import fnmatch
import json
import logging
from collections import defaultdict
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, col, select

from temper_ai.checkpoint.models import Checkpoint
from temper_ai.observability.models import Event
from temper_ai.shared.clock import as_utc, utcnow

logger = logging.getLogger(__name__)


def _utc(value: datetime) -> datetime:
    """``as_utc`` where the value is known to be set.

    ``as_utc`` passes ``None`` through, which is right for it and wrong here:
    every timestamp this module compares has already been checked. This keeps
    that promise in one place instead of a cast at each use.
    """
    out = as_utc(value)
    if out is None:  # pragma: no cover - only reachable if a caller ignores the type
        raise TrimError("a run timestamp was missing where one is required")
    return out

# The only run outcome that may be trimmed. Anything else — running, failed,
# cancelled, interrupted, orphaned — is kept whole.
COMPLETED = "completed"

# Statuses an event carries only while a human gate is open or after it was
# answered (temper_ai/stage/executor.py::_wait_for_gate and the approve
# route). Any of them anywhere in a run means a person was asked something.
GATE_STATUSES = ("waiting", "approved", "rejected")

# What comes out of each kind of row. Everything else on the row stays.
TRIMMED_KEYS: dict[str, tuple[str, ...]] = {
    # The transcript sent to the model. `message_count` beside it stays, so
    # the page can still say how long the conversation was.
    "llm.call.started": ("messages",),
    # The agent's setup: what it was handed, and the two long template
    # fields of its config. Model, provider, role, tools, budgets stay.
    "agent.started": ("input_data",),
}
TRIMMED_CONFIG_KEYS: dict[str, tuple[str, ...]] = {
    "agent.started": ("system_prompt", "task_template"),
}

# The same cut `agent.completed` already applies to an agent's output, so a
# trimmed checkpoint never holds less of the outcome than the event log.
CHECKPOINT_OUTPUT_CHARS = 5000

DEFAULT_OLDER_THAN_DAYS = 30
DEFAULT_KEEP_RECENT_PER_WORKFLOW = 5
# The workflows we are actively grading: their runs are the evidence.
DEFAULT_KEEP_WHOLE = ("epd_*",)


class TrimError(RuntimeError):
    """The trim cannot run as asked."""


# ----------------------------------------------------------------- policy


@dataclass(frozen=True)
class TrimPolicy:
    """What may be trimmed. See ``configs/retention/retention.yaml``."""

    older_than_days: int = DEFAULT_OLDER_THAN_DAYS
    keep_recent_per_workflow: int = DEFAULT_KEEP_RECENT_PER_WORKFLOW
    keep_whole: tuple[str, ...] = DEFAULT_KEEP_WHOLE
    trim_checkpoints: bool = True
    batch_size: int = 200

    def __post_init__(self) -> None:
        if self.older_than_days < 1:
            raise TrimError("older_than_days must be at least 1 day")
        if self.keep_recent_per_workflow < 0:
            raise TrimError("keep_recent_per_workflow cannot be negative")
        if self.batch_size < 1:
            raise TrimError("batch_size must be at least 1")

    def cutoff(self, now: datetime) -> datetime:
        return _utc(now) - timedelta(days=self.older_than_days)

    def kept_whole(self, workflow_name: str) -> bool:
        """True when the workflow is on the keep-whole list (globs allowed)."""
        return any(fnmatch.fnmatchcase(workflow_name, pattern) for pattern in self.keep_whole)


def default_config_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "configs"


def config_path(config_dir: str | Path | None = None) -> Path | None:
    """The file in use: the local one if it exists, else the tracked one."""
    root = (Path(config_dir) if config_dir else default_config_dir()) / "retention"
    for candidate in (root / "local" / "retention.yaml", root / "retention.yaml"):
        if candidate.is_file():
            return candidate
    return None


def parse_policy(raw: Any, where: str = "retention") -> TrimPolicy:
    """A policy from the YAML shape; anything unknown is an error, not a shrug."""
    if raw is None:
        return TrimPolicy()
    if not isinstance(raw, dict):
        raise TrimError(f"{where}: expected a mapping")
    block = raw.get("retention", raw)
    if block is None:
        return TrimPolicy()
    if not isinstance(block, dict):
        raise TrimError(f"{where}: retention must be a mapping")

    known = {"older_than_days", "keep_recent_per_workflow", "keep_whole", "trim_checkpoints", "batch_size"}
    unknown = sorted(set(block) - known)
    if unknown:
        raise TrimError(f"{where}: unknown setting(s) {', '.join(unknown)}")

    keep_whole = block.get("keep_whole", list(DEFAULT_KEEP_WHOLE))
    if isinstance(keep_whole, str):
        keep_whole = [keep_whole]
    if not isinstance(keep_whole, list) or any(not isinstance(item, str) or not item.strip() for item in keep_whole):
        raise TrimError(f"{where}: keep_whole must be a list of workflow names or globs")

    def _int(key: str, fallback: int) -> int:
        value = block.get(key, fallback)
        if isinstance(value, bool) or not isinstance(value, int):
            raise TrimError(f"{where}: {key} must be a whole number")
        return value

    trim_checkpoints = block.get("trim_checkpoints", True)
    if not isinstance(trim_checkpoints, bool):
        raise TrimError(f"{where}: trim_checkpoints must be true or false")

    return TrimPolicy(
        older_than_days=_int("older_than_days", DEFAULT_OLDER_THAN_DAYS),
        keep_recent_per_workflow=_int("keep_recent_per_workflow", DEFAULT_KEEP_RECENT_PER_WORKFLOW),
        keep_whole=tuple(item.strip() for item in keep_whole),
        trim_checkpoints=trim_checkpoints,
        batch_size=_int("batch_size", 200),
    )


def load_policy(config_dir: str | Path | None = None) -> TrimPolicy:
    """The policy on disk, or the defaults when there is no settings file."""
    path = config_path(config_dir)
    if path is None:
        return TrimPolicy()
    try:
        with open(path, encoding="utf-8") as handle:
            raw = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        raise TrimError(f"{path}: not valid YAML: {exc}") from exc
    return parse_policy(raw, str(path))


# ------------------------------------------------------------------ facts


@dataclass(frozen=True)
class RunFacts:
    """Everything the choosing needs to know about one run.

    ``recency_rank`` is the run's place in its workflow's newest-first list:
    0 is the newest run of that workflow.
    """

    execution_id: str
    workflow_name: str
    status: str
    asked_a_person: bool
    started_at: datetime
    recency_rank: int
    already_trimmed: bool = False


@dataclass(frozen=True)
class Verdict:
    """Trim this run, or keep it whole and why."""

    trim: bool
    reason: str


def decide(facts: RunFacts, policy: TrimPolicy, now: datetime) -> Verdict:
    """Keep this run whole, or trim its sent material.

    The order matters only for which reason is reported; every refusal below
    is on its own enough to keep a run whole.
    """
    if facts.already_trimmed:
        return Verdict(False, "already trimmed")
    if facts.status != COMPLETED:
        # Covers a run still going, one that failed, was cancelled,
        # interrupted or orphaned: its story is the interesting one.
        return Verdict(False, f"did not complete ({facts.status})")
    if facts.asked_a_person:
        return Verdict(False, "a person was asked something")
    if policy.kept_whole(facts.workflow_name):
        return Verdict(False, "workflow is kept whole")
    if _utc(facts.started_at) >= policy.cutoff(now):
        return Verdict(False, f"younger than {policy.older_than_days} days")
    if facts.recency_rank < policy.keep_recent_per_workflow:
        return Verdict(False, f"one of the newest {policy.keep_recent_per_workflow} of its workflow")
    return Verdict(True, "old routine run")


def choose(runs: Iterable[RunFacts], policy: TrimPolicy, now: datetime) -> list[tuple[RunFacts, Verdict]]:
    """Every run with its verdict, in the order given."""
    return [(run, decide(run, policy, now)) for run in runs]


def rank_by_recency(runs: Sequence[RunFacts]) -> list[RunFacts]:
    """Fill in ``recency_rank``: 0 for the newest run of each workflow."""
    by_workflow: dict[str, list[RunFacts]] = defaultdict(list)
    for run in runs:
        by_workflow[run.workflow_name].append(run)
    ranked: list[RunFacts] = []
    for group in by_workflow.values():
        group.sort(key=lambda r: (as_utc(r.started_at), r.execution_id), reverse=True)
        ranked.extend(replace(run, recency_rank=rank) for rank, run in enumerate(group))
    ranked.sort(key=lambda r: (as_utc(r.started_at), r.execution_id))
    return ranked


def load_facts(session: Session) -> list[RunFacts]:
    """Read every run's facts out of the event log.

    One pass over the ``workflow.started`` rows (small: a few hundred bytes
    each) plus one indexed pass for the gate statuses. A resumed run has
    several ``workflow.started`` rows under the same execution id; they are
    folded into one run whose status is the worst of them, so a run that
    failed once is never trimmed on the strength of a later clean attempt.
    """
    gated: set[str] = {
        value
        for value in _scalars(
            session.exec(  # type: ignore[call-overload]
                select(Event.execution_id)
                .where(col(Event.status).in_(GATE_STATUSES))
                .where(col(Event.execution_id).is_not(None))
                .distinct(),
            ).all(),
        )
        if value
    }

    starts = session.exec(
        select(Event.execution_id, Event.status, Event.data, Event.timestamp)  # type: ignore[call-overload]
        .where(Event.type == "workflow.started")
        .where(col(Event.execution_id).is_not(None)),
    ).all()

    merged: dict[str, dict[str, Any]] = {}
    for execution_id, status, data, timestamp in starts:
        # A row without an id or a time cannot be placed in any run, and a
        # run we cannot date is one we must not judge old. Skip both.
        if execution_id is None or timestamp is None:
            continue
        data = data or {}
        entry = merged.get(execution_id)
        name = str(data.get("name") or "")
        trimmed = "trimmed" in data
        if entry is None:
            merged[execution_id] = {
                "name": name,
                "status": status or "",
                "started_at": timestamp,
                "trimmed": trimmed,
            }
            continue
        entry["name"] = entry["name"] or name
        # Worst-of: one attempt that did not complete keeps the whole run.
        if entry["status"] == COMPLETED and status != COMPLETED:
            entry["status"] = status or ""
        if _utc(timestamp) > _utc(entry["started_at"]):
            entry["started_at"] = timestamp
        # Only a run whose every attempt is stamped counts as done.
        entry["trimmed"] = entry["trimmed"] and trimmed

    runs = [
        RunFacts(
            execution_id=execution_id,
            workflow_name=entry["name"],
            status=entry["status"],
            asked_a_person=execution_id in gated,
            started_at=entry["started_at"],
            recency_rank=0,
            already_trimmed=entry["trimmed"],
        )
        for execution_id, entry in merged.items()
    ]
    return rank_by_recency(runs)


# ------------------------------------------------------------- the trimming


def trimmed_data(event_type: str, data: dict[str, Any]) -> dict[str, Any] | None:
    """The row's ``data`` without its sent material, or None when there is none.

    Pure: takes a dict, returns a new dict. Never touches an outcome field.
    """
    dropped: list[str] = []
    out = dict(data or {})

    for key in TRIMMED_KEYS.get(event_type, ()):
        if key in out:
            out.pop(key)
            dropped.append(key)

    config_keys = TRIMMED_CONFIG_KEYS.get(event_type, ())
    if config_keys:
        config = out.get("agent_config")
        if isinstance(config, dict):
            new_config = dict(config)
            for key in config_keys:
                if key in new_config:
                    new_config.pop(key)
                    dropped.append(f"agent_config.{key}")
            if len(new_config) != len(config):
                out["agent_config"] = new_config

    if not dropped:
        return None
    out["trimmed"] = dropped
    return out


def trimmed_output(output: str | None, limit: int = CHECKPOINT_OUTPUT_CHARS) -> str | None:
    """A checkpoint's output cut to ``limit`` characters, or None when it already fits."""
    if not output or len(output) <= limit:
        return None
    return output[:limit] + f"\n\n[trimmed: {len(output) - limit} more characters]"


@dataclass
class TrimStats:
    """What one pass changed. Sizes are bytes of stored ``data``."""

    runs_scanned: int = 0
    runs_trimmed: int = 0
    runs_failed: int = 0
    events_trimmed: int = 0
    checkpoints_trimmed: int = 0
    bytes_freed: int = 0
    kept: dict[str, int] = field(default_factory=dict)

    def keep(self, reason: str) -> None:
        self.kept[reason] = self.kept.get(reason, 0) + 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "runs_scanned": self.runs_scanned,
            "runs_trimmed": self.runs_trimmed,
            "runs_failed": self.runs_failed,
            "events_trimmed": self.events_trimmed,
            "checkpoints_trimmed": self.checkpoints_trimmed,
            "bytes_freed": self.bytes_freed,
            "kept": dict(sorted(self.kept.items())),
        }


def _chunks(items: Sequence[Any], size: int) -> Iterator[Sequence[Any]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _first_cell(row: Any) -> Any:
    """The one value in a one-column result.

    SQLAlchemy hands back a bare value for some queries and a Row for others
    (notably ``session.exec(text(...))`` on Postgres). Row is not a tuple, so
    checking for tuple alone is not enough.
    """
    if isinstance(row, (tuple, list)) or hasattr(row, "_mapping"):
        return row[0]
    return row


def _scalars(rows: Iterable[Any]) -> list[Any]:
    """One-column results, whether the driver hands back tuples, Rows or values."""
    return [_first_cell(row) for row in rows]


def _json_bytes(data: Any) -> int:
    """How much room this payload takes, for backends that cannot measure it."""
    try:
        return len(json.dumps(data, default=str).encode())
    except (TypeError, ValueError):  # pragma: no cover — defensive
        return 0


def _is_postgres(session: Session) -> bool:
    bind = session.get_bind()
    return bool(bind is not None and bind.dialect.name == "postgresql")


def _data_bytes(session: Session, ids: Sequence[str]) -> int:
    """Stored size of those rows' ``data``. Postgres only; 0 elsewhere."""
    if not ids or not _is_postgres(session):
        return 0
    total = session.exec(  # type: ignore[call-overload]
        text("SELECT COALESCE(SUM(pg_column_size(data)), 0) FROM events WHERE id = ANY(:ids)").bindparams(ids=list(ids)),
    ).one()
    return int(_first_cell(total))


def _trim_events_of_run(session: Session, execution_id: str, policy: TrimPolicy, stats: TrimStats) -> None:
    """Drop the sent material from one run's rows, a batch at a time."""
    ids = _scalars(
        session.exec(  # type: ignore[call-overload]
            select(Event.id)
            .where(Event.execution_id == execution_id)
            .where(col(Event.type).in_(tuple(TRIMMED_KEYS))),
        ).all(),
    )
    measured = _is_postgres(session)
    for batch in _chunks(ids, policy.batch_size):
        before = _data_bytes(session, batch) if measured else 0
        changed = 0
        counted = 0
        rows = session.exec(select(Event).where(col(Event.id).in_(list(batch)))).all()
        for row in rows:
            old_data = row.data or {}
            new_data = trimmed_data(row.type, old_data)
            if new_data is None:
                continue
            if not measured:
                counted += max(0, _json_bytes(old_data) - _json_bytes(new_data))
            row.data = new_data
            session.add(row)
            changed += 1
        if not changed:
            continue
        session.flush()
        stats.events_trimmed += changed
        stats.bytes_freed += max(0, before - _data_bytes(session, batch)) if measured else counted


def _trim_checkpoints_of_run(session: Session, execution_id: str, policy: TrimPolicy, stats: TrimStats) -> None:
    rows = session.exec(
        select(Checkpoint).where(Checkpoint.execution_id == execution_id),
    ).all()
    for row in rows:
        cut = trimmed_output(row.output)
        if cut is None:
            continue
        stats.bytes_freed += max(0, len(row.output or "") - len(cut))
        row.output = cut
        session.add(row)
        stats.checkpoints_trimmed += 1


def _stamp_run(session: Session, execution_id: str, policy: TrimPolicy, now: datetime) -> None:
    """Mark the run's ``workflow.started`` rows as trimmed, so it is skipped next time."""
    rows = session.exec(
        select(Event)
        .where(Event.execution_id == execution_id)
        .where(Event.type == "workflow.started"),
    ).all()
    for row in rows:
        data = dict(row.data or {})
        data["trimmed"] = {
            "at": _utc(now).isoformat(),
            "older_than_days": policy.older_than_days,
        }
        row.data = data
        session.add(row)


def _still_completed(session: Session, execution_id: str) -> bool:
    """Re-read the run's outcome just before touching it.

    Selection and trimming are minutes apart on a big first pass; a run that
    started again in between must be left alone.
    """
    statuses = _scalars(
        session.exec(  # type: ignore[call-overload]
            select(Event.status)
            .where(Event.execution_id == execution_id)
            .where(Event.type == "workflow.started"),
        ).all(),
    )
    return bool(statuses) and all(status == COMPLETED for status in statuses)


def trim_run(session: Session, execution_id: str, policy: TrimPolicy, now: datetime, stats: TrimStats) -> bool:
    """Trim one run in its own transaction. Returns False when it was skipped."""
    if not _still_completed(session, execution_id):
        stats.keep("outcome changed since it was chosen")
        return False
    _trim_events_of_run(session, execution_id, policy, stats)
    if policy.trim_checkpoints:
        _trim_checkpoints_of_run(session, execution_id, policy, stats)
    _stamp_run(session, execution_id, policy, now)
    session.commit()
    stats.runs_trimmed += 1
    return True


@dataclass
class TrimReport:
    """What a whole pass did. Safe to log: no run material, only figures."""

    started_at: datetime
    finished_at: datetime
    policy: TrimPolicy
    stats: TrimStats
    dry_run: bool
    db_bytes_before: int | None = None
    db_bytes_after: int | None = None
    database: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "seconds": round((self.finished_at - self.started_at).total_seconds(), 1),
            "dry_run": self.dry_run,
            "database": self.database,
            "policy": {
                "older_than_days": self.policy.older_than_days,
                "keep_recent_per_workflow": self.policy.keep_recent_per_workflow,
                "keep_whole": list(self.policy.keep_whole),
                "trim_checkpoints": self.policy.trim_checkpoints,
            },
            "db_bytes_before": self.db_bytes_before,
            "db_bytes_after": self.db_bytes_after,
            **self.stats.as_dict(),
        }

    def as_line(self) -> str:
        return json.dumps(self.as_dict(), sort_keys=True)


def database_name(session: Session) -> str:
    """Which database this pass is about to change, as ``host:port/name``.

    Never the password. Several projects on this machine have a database
    called ``temper_ai``; a pass that quietly went to the wrong one should be
    obvious from its own log line, so every report carries this.
    """
    bind = session.get_bind()
    if bind is None:  # pragma: no cover - defensive
        return ""
    url = bind.engine.url
    where = url.host or "local"
    if url.port:
        where = f"{where}:{url.port}"
    return f"{where}/{url.database or '?'}"


def database_bytes(session: Session) -> int | None:
    """Size of the whole database, or None when the backend cannot say."""
    if not _is_postgres(session):
        return None
    row = session.exec(text("SELECT pg_database_size(current_database())")).one()  # type: ignore[call-overload]
    return int(_first_cell(row))


def run_trim(
    session: Session,
    policy: TrimPolicy,
    now: datetime | None = None,
    limit: int | None = None,
    dry_run: bool = False,
) -> TrimReport:
    """Choose, then trim. Stop-and-start safe: each run commits on its own."""
    now = _utc(now or utcnow())
    started_at = now
    stats = TrimStats()
    before = database_bytes(session)
    target = database_name(session)

    verdicts = choose(load_facts(session), policy, now)
    stats.runs_scanned = len(verdicts)
    todo: list[str] = []
    for run, verdict in verdicts:
        if verdict.trim:
            todo.append(run.execution_id)
        else:
            stats.keep(verdict.reason)
    if limit is not None:
        todo = todo[:limit]

    if not dry_run:
        for execution_id in todo:
            try:
                trim_run(session, execution_id, policy, now, stats)
            except Exception:
                session.rollback()
                stats.runs_failed += 1
                # One bad run must not stop the pass, but a pass that fails
                # everywhere must not read as "nothing to do" either.
                logger.exception("Trim failed for run %s; leaving it whole", execution_id)
        # Not a trim: the Pi teams of cancelled runs whose teams were never ended get ended
        # here too (G-a), so their undelivered messages are recorded within a week.
        from temper_ai.runner.parked import end_cancelled_pi_teams

        end_cancelled_pi_teams()
    else:
        stats.runs_trimmed = len(todo)

    after = database_bytes(session) if not dry_run else before
    return TrimReport(
        started_at=started_at,
        finished_at=utcnow(),
        policy=policy,
        stats=stats,
        dry_run=dry_run,
        db_bytes_before=before,
        db_bytes_after=after,
        database=target,
    )


def vacuum(session: Session) -> list[str]:
    """Hand the trimmed rows' space back for reuse.

    Plain VACUUM, never FULL: FULL takes an exclusive lock and would stop
    every run on the machine. Plain VACUUM runs alongside live traffic; it
    makes the space reusable rather than returning it to the filesystem,
    which is what matters here: a backup only ever carries live rows.

    PARALLEL 0 on purpose. Postgres in Docker gets the default 64 MB of
    /dev/shm, and a parallel vacuum's workers ask for shared memory beyond
    that on a table this size; it comes back as "No space left on device"
    even with the disk half empty. One worker is slower and always fits.

    Returns the tables it could not vacuum, rather than raising: by the time
    this runs the trimming is committed and the report is worth having.
    Space that is not handed back today is handed back by autovacuum anyway.
    """
    if not _is_postgres(session):
        return []
    bind = session.get_bind()
    if bind is None:  # pragma: no cover - defensive
        return []
    failed: list[str] = []
    # VACUUM cannot run inside a transaction block.
    with bind.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        for table in ("events", "checkpoints"):
            try:
                conn.execute(text(f"VACUUM (ANALYZE, PARALLEL 0) {table}"))
            except SQLAlchemyError as exc:
                logger.warning("vacuum of %s failed: %s", table, exc.__class__.__name__)
                failed.append(table)
    return failed


def fmt_bytes(n: int | None) -> str:
    if n is None:
        return "?"
    step = 1024.0
    value = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < step or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= step
    return f"{value:.1f} TB"


__all__ = [
    "COMPLETED",
    "DEFAULT_KEEP_RECENT_PER_WORKFLOW",
    "DEFAULT_KEEP_WHOLE",
    "DEFAULT_OLDER_THAN_DAYS",
    "RunFacts",
    "TrimError",
    "TrimPolicy",
    "TrimReport",
    "TrimStats",
    "Verdict",
    "choose",
    "config_path",
    "vacuum",
    "database_bytes",
    "database_name",
    "decide",
    "fmt_bytes",
    "load_facts",
    "load_policy",
    "parse_policy",
    "rank_by_recency",
    "run_trim",
    "trim_run",
    "trimmed_data",
    "trimmed_output",
]
