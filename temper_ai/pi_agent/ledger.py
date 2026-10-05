"""The Pi ledger: who is in each Pi conversation, what they were sent, what each turn did, and
what the owner is being asked -- for one Pi step (L2) or a team of Pi members (T4/T5).

Five tables in their own SQLAlchemy ``MetaData`` -- never Temper's SQLModel metadata, so
Temper's ``create_all`` and migrations never see them. They are created on first use, on the
database Temper's engine already points at; with the Pi agent switched off nothing creates or
reads them. Schema: ``docs/pi-agent.md`` and ``docs/pi-team-messages.md``.

Identities kept apart on purpose:

* member (participant) -- one row per (run, host node path, member name), with the Pi session
  id it keeps for life: one member, one conversation, reused for every turn (R2 B8). A single
  Pi step's member is its role.
* message -- one row per message, with one id from arrival to use (R2 B1). A member's message
  is keyed by (run, sender, client message id) and carries a digest of its content: the same
  send again returns the original, a different one under the same key is refused (B3).
* turn -- one row per Pi prompt cycle. It takes the member's pending messages as one ordered
  batch at a turn boundary (later ones wait for the next); what it sends is held with it and
  released only when it settles (B4). At most one unsettled turn per team, enforced by the
  database (``claim_key``), and every write of a turn's owner is fenced by the turn's epoch,
  so a second process can never run or finish the same turn (B6, A3's lease).
* wait -- one owner question at a time per team: while any is open no turn starts (B6, B11).
* review -- the leader's review record (#38 writes it; read here for the quiet-team check).

Every change is one transaction. What must hold across processes is enforced by the database
(unique keys, compare-and-set updates); the process-wide lock only keeps one process's own
threads in line.
"""

from __future__ import annotations

import hashlib
import logging
import os
import socket
import threading
import uuid
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError, OperationalError, ProgrammingError

from temper_ai.pi_agent.route import model as route_model
from temper_ai.pi_agent.route.router import (
    POLICY_VERSION,
    Refusal,
    all_policy,
    check_payload,
    content_digest,
    roster_entry,
    route,
    route_reply,
)
from temper_ai.stage.step_waits import wait_name

logger = logging.getLogger(__name__)

metadata = sa.MetaData()

_LOCK = threading.RLock()
_BOOT = uuid.uuid4().hex[:12]

#: Member states. ``idle``: no box, its conversation on disk. ``uncertain``: its last turn was
#: cut off and the owner decides. ``ended``: the team ended (cancelled or done).
PARTICIPANT_STATES = ("idle", "running", "uncertain", "failed", "retired", "ended")
#: Turn states. Unsettled ones hold the team's claim.
TURN_STATES = ("running", "completed", "failed", "uncertain", "accepted", "superseded",
               "cancelled")
UNSETTLED = ("running", "uncertain")
#: Message states: ``held`` (sent by a turn that has not settled: an outbox), ``pending``
#: (waiting for the recipient's next turn), ``consumed`` (given to a turn), ``undelivered``.
MESSAGE_STATES = ("held", "pending", "consumed", "undelivered")
SENDER_KINDS = ("member", "owner", "temper")
UNDELIVERED_REASONS = ("turn_failed", "turn_superseded", "turn_cancelled", "run_cancelled",
                       "run_completed", "late", "recipient_retired", "recipient_unknown")
END_REASONS = ("run_cancelled", "run_completed")
#: Wait kinds: ``owner`` (next message or finish), ``recovery`` (a turn that was cut off or
#: failed), ``stalled`` (several members with nothing to do).
WAIT_KINDS = ("owner", "recovery", "stalled")
MAX_REFUSALS = 200

participants = sa.Table(
    "pi_participants", metadata,
    sa.Column("participant_id", sa.String(64), primary_key=True),
    sa.Column("run_id", sa.String(64), nullable=False, index=True),
    sa.Column("host_path", sa.String(255), nullable=False),
    # The member's team name (its agent config's ``name:``); a single Pi step uses its role.
    sa.Column("member", sa.String(128), nullable=False),
    sa.Column("role", sa.String(128), nullable=False),
    sa.Column("state", sa.String(16), nullable=False),
    sa.Column("session_id", sa.String(64), nullable=False),
    sa.Column("session_dir", sa.String(1024), nullable=False),
    # Pinned at creation and compared before every turn: Pi version, provider, model,
    # thinking, tools, extensions (name -> digest), workflow, cwd, image, team settings.
    sa.Column("pin", sa.JSON, nullable=False),
    sa.Column("turns", sa.Integer, nullable=False, default=0),
    sa.Column("retire_requested", sa.Boolean, nullable=False, default=False),
    # A3's fencing epoch: +1 at every turn claim and every takeover.
    sa.Column("epoch", sa.Integer, nullable=False, default=0),
    sa.Column("ended_reason", sa.String(32)),
    sa.Column("created_attempt", sa.String(64)),
    sa.Column("created_at", sa.String(40)),
    sa.Column("retired_at", sa.String(40)),
    sa.UniqueConstraint("run_id", "host_path", "member", name="uq_pi_participant_member"),
)

messages = sa.Table(
    "pi_messages", metadata,
    sa.Column("seq", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("message_id", sa.String(64), nullable=False, unique=True),
    # Temper's own key for its posts (seed, owner reply). Members' sends use A7's key below.
    sa.Column("dedupe_key", sa.String(255), unique=True),
    sa.Column("run_id", sa.String(64), nullable=False, index=True),
    sa.Column("host_path", sa.String(255), nullable=False),
    sa.Column("to_participant", sa.String(64)),
    sa.Column("to_member", sa.String(128), nullable=False),
    # Who sent it, always written by Temper: never read from a message (B2).
    sa.Column("sender", sa.String(128), nullable=False),
    sa.Column("sender_kind", sa.String(16), nullable=False),
    sa.Column("sender_participant", sa.String(64)),
    sa.Column("sender_session", sa.String(64)),
    sa.Column("sender_turn", sa.String(64)),
    sa.Column("sender_epoch", sa.Integer),
    sa.Column("kind", sa.String(32), nullable=False),
    sa.Column("client_msg_id", sa.String(128)),
    sa.Column("content_sha256", sa.String(64), nullable=False),
    sa.Column("in_reply_to", sa.String(64)),
    sa.Column("thread_id", sa.String(64)),
    sa.Column("outcome", sa.String(16)),
    sa.Column("policy_version", sa.String(32), nullable=False),
    sa.Column("body", sa.Text, nullable=False),
    sa.Column("state", sa.String(16), nullable=False),
    # The delivering turn: the turn whose batch carried it.
    sa.Column("turn_id", sa.String(64)),
    sa.Column("delivery_count", sa.Integer, nullable=False, default=0),
    sa.Column("redeliver_turn", sa.String(64)),
    sa.Column("undelivered_reason", sa.String(32)),
    sa.Column("released_at", sa.String(40)),
    sa.Column("delivered_at", sa.String(40)),
    sa.Column("review_id", sa.String(64)),
    sa.Column("created_at", sa.String(40)),
    sa.UniqueConstraint("run_id", "sender_participant", "client_msg_id",
                        name="uq_pi_message_client"),
    sa.Index("ix_pi_messages_team_state", "run_id", "host_path", "state"),
)

turns = sa.Table(
    "pi_turns", metadata,
    sa.Column("turn_id", sa.String(64), primary_key=True),
    sa.Column("participant_id", sa.String(64), nullable=False, index=True),
    sa.Column("run_id", sa.String(64), nullable=False, index=True),
    sa.Column("host_path", sa.String(255), nullable=False),
    sa.Column("turn_no", sa.Integer, nullable=False),
    sa.Column("attempt_id", sa.String(64)),
    sa.Column("state", sa.String(16), nullable=False),
    # "{run}|{team}" while the turn is unsettled, else null: one unsettled turn per team.
    sa.Column("claim_key", sa.String(330), unique=True),
    sa.Column("epoch", sa.Integer, nullable=False),
    sa.Column("claimed_by", sa.String(255), nullable=False),
    sa.Column("retry_of", sa.String(64)),
    sa.Column("input_seqs", sa.JSON, nullable=False),
    # The highest team seq the claim could see: no batch message is above it.
    sa.Column("cut_seq", sa.Integer),
    sa.Column("policy_version", sa.String(32)),
    # The turn's own agent.started event: its model calls and tools hang below it.
    sa.Column("agent_event_id", sa.String(64)),
    sa.Column("model_call_ids", sa.JSON, nullable=False),
    # none (prompt not sent) | intent (sent: the model may have acted) | committed (settled)
    sa.Column("effect_state", sa.String(16), nullable=False),
    sa.Column("refusals", sa.JSON, nullable=False),
    # The worker box's container name (written before it is created) and, after a takeover,
    # how it was confirmed stopped.
    sa.Column("box_name", sa.String(255)),
    sa.Column("box_stop", sa.JSON),
    sa.Column("output", sa.Text),
    sa.Column("error", sa.Text),
    # The worker box's receipt: container, exit, teardown, handoff and tunnel counts. No tokens.
    sa.Column("worker", sa.JSON),
    sa.Column("started_at", sa.String(40)),
    sa.Column("ended_at", sa.String(40)),
    sa.Index("ix_pi_turns_team_state", "run_id", "host_path", "state"),
)

waits = sa.Table(
    "pi_waits", metadata,
    sa.Column("wait_id", sa.String(64), primary_key=True),
    sa.Column("run_id", sa.String(64), nullable=False, index=True),
    sa.Column("host_path", sa.String(255), nullable=False),
    sa.Column("kind", sa.String(16), nullable=False),
    # The name ``ask_owner`` files the wait's events under (``<step path>~ask-<wait id>``):
    # a wait's events are found by it (C7).
    sa.Column("gate_name", sa.String(255), nullable=False),
    # Not read since C7 (a wait's events are ask_owner's own, found by gate_name); still
    # written, because a database made before keeps the column NOT NULL.
    sa.Column("event_id", sa.String(64), nullable=False),
    # open | decided | cancelled
    sa.Column("state", sa.String(16), nullable=False),
    sa.Column("subject", sa.JSON),
    sa.Column("decision", sa.JSON),
    sa.Column("opened_attempt", sa.String(64)),
    sa.Column("decided_attempt", sa.String(64)),
    sa.Column("opened_at", sa.String(40)),
    sa.Column("decided_at", sa.String(40)),
    # Not read or set since C7; kept for databases made before (NOT NULL).
    sa.Column("event_recorded", sa.Boolean, nullable=False, default=False),
)

reviews = sa.Table(
    "pi_reviews", metadata,
    sa.Column("review_id", sa.String(64), primary_key=True),
    sa.Column("run_id", sa.String(64), nullable=False, index=True),
    sa.Column("host_path", sa.String(255), nullable=False),
    sa.Column("round", sa.Integer, nullable=False),
    sa.Column("leader_participant", sa.String(64), nullable=False),
    sa.Column("asked_turn", sa.String(64), nullable=False),
    # The commit of the leader's copy the reviewers' copies were moved to.
    sa.Column("commit_sha", sa.String(64), nullable=False),
    sa.Column("files", sa.JSON, nullable=False),
    # open | collected | decided | superseded
    sa.Column("state", sa.String(16), nullable=False),
    # done | keep_going | done_refused
    sa.Column("decision", sa.String(16)),
    sa.Column("decided_turn", sa.String(64)),
    sa.Column("summary", sa.Text),
    sa.Column("cost", sa.JSON),
    sa.Column("opened_at", sa.String(40)),
    sa.Column("decided_at", sa.String(40)),
    sa.UniqueConstraint("run_id", "host_path", "round", name="uq_pi_review_round"),
)

TABLES = (participants, messages, turns, waits, reviews)


class LedgerError(Exception):
    """A ledger refusal with a plain message."""


class LedgerLayoutError(LedgerError):
    """The database has ``pi_`` tables of an older layout: refuse instead of mixing layouts."""


class LedgerConflict(LedgerError):
    """A key used again for different content (R2 B3)."""

    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code


class TakeoverRefused(LedgerError):
    """A cut-off turn's worker box could not be confirmed stopped: nothing is taken over."""

    def __init__(self, turn_id: str, result: dict):
        super().__init__(f"the worker box of cut-off turn {turn_id[:12]} could not be confirmed "
                         f"stopped ({result.get('error') or 'still listed'}); refusing to take "
                         "the turn over while it may still be running")
        self.turn_id = turn_id
        self.result = result


class _Rollback(Exception):
    pass


@dataclass(frozen=True)
class Binding:
    """Who a box's team socket speaks for, fixed by Temper when it claims the turn (R2 B2).
    There is no token: the socket itself is the binding, and it dies with the turn."""

    run_id: str
    host_path: str
    participant_id: str
    member: str
    session_id: str
    turn_id: str
    epoch: int

    def trusted(self) -> dict[str, str]:
        return {"from": self.member, "sender": self.member, "member": self.member,
                "participant_id": self.participant_id, "run_id": self.run_id,
                "session_id": self.session_id, "turn_id": self.turn_id}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def _new_id() -> str:
    return uuid.uuid4().hex


def gate_name_for(host_path: str, wait_id: str) -> str:
    """The wait's name: the one ``ask_owner`` asks it under (``<step path>~ask-<wait id>``,
    stage/step_waits.py), so the row names its events from the start. No other wait shares
    it: a stale approval of an old wait finds nothing."""
    return wait_name(host_path, wait_id)


def team_claim_key(run_id: str, host_path: str) -> str:
    return f"{run_id}|{host_path}"


def team_lock_key(run_id: str, host_path: str) -> int:
    """The team's Postgres advisory lock number (a signed 64-bit integer)."""
    digest = hashlib.sha256(f"temper-pi-team|{run_id}|{host_path}".encode()).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


def process_identity() -> str:
    """``host:pid:boot`` of this process: who claimed a turn (takeover, diagnostics)."""
    return f"{socket.gethostname()}:{os.getpid()}:{_BOOT}"


def _creation_race(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(s in text for s in ("already exists", "duplicate key",
                                   "pg_type_typname_nsp_index"))


def _short(value: Any, limit: int = 128) -> str | None:
    return None if value is None else str(value)[:limit]


def _fence(conn: Any, turn_id: str, epoch: int | None) -> bool:
    """Touch the turn row only if its owner still holds it (running, same epoch). It takes the
    row's write lock first, so what follows in the transaction is serialised with a takeover."""
    if epoch is None:
        return False
    return conn.execute(turns.update().where(
        turns.c.turn_id == turn_id, turns.c.state == "running", turns.c.epoch == epoch,
    ).values(epoch=turns.c.epoch)).rowcount == 1


class Ledger:
    """All reads and writes of the five tables. Bound to one SQLAlchemy engine."""

    def __init__(self, engine: sa.Engine):
        self.engine = engine

    def ensure(self) -> None:
        """Create the tables if absent and check their layout (N4: a creation race between two
        processes on Postgres is checked again once, not failed)."""
        with _LOCK:
            try:
                metadata.create_all(self.engine, checkfirst=True)
            except (OperationalError, ProgrammingError, IntegrityError) as exc:
                if not _creation_race(exc):
                    raise
                metadata.create_all(self.engine, checkfirst=True)
            inspector = sa.inspect(self.engine)
            missing = []
            for table in TABLES:
                have = {c["name"] for c in inspector.get_columns(table.name)}
                missing += [f"{table.name}.{c.name}" for c in table.columns if c.name not in have]
            if missing:
                raise LedgerLayoutError(
                    "this database's pi_ tables have an older layout (missing "
                    + ", ".join(missing[:12]) + (", ..." if len(missing) > 12 else "")
                    + "); they come from an earlier Pi build: use a fresh database")

    def _tx(self):
        return self.engine.begin()

    @contextmanager
    def _team_tx(self, run_id: str, host_path: str) -> Iterator[Any]:
        """One change to one team, serialised with every other change to that team, in any
        process (R2 B6, A3's lease): Postgres takes the team's transaction-scoped advisory lock
        before reading anything, SQLite its database write lock. So no change decides on a
        team state another change is about to replace -- a post racing the team's end, a claim
        racing a cancel, a send racing a takeover -- and two changes never wait on each other
        in opposite orders."""
        with self.engine.begin() as conn:
            if conn.dialect.name == "postgresql":
                conn.execute(sa.text("SELECT pg_advisory_xact_lock(:key)"),
                             {"key": team_lock_key(run_id, host_path)})
            else:
                # A write statement that changes nothing still takes SQLite's write lock.
                conn.execute(participants.update().where(sa.false()).values(
                    epoch=participants.c.epoch))
            yield conn

    def _team_of(self, table: sa.Table, column: sa.Column, key: str) -> tuple[str, str] | None:
        """(run, team) of a turn or wait: fixed when the row is made, read before locking."""
        with self._tx() as conn:
            row = conn.execute(sa.select(table.c.run_id, table.c.host_path).where(
                column == key)).first()
        return (row[0], row[1]) if row else None

    # --- members ----------------------------------------------------------------------

    def attach_participant(self, run_id: str, host_path: str, member: str, *,
                           role: str | None = None, session_root: str, pin: dict,
                           attempt_id: str) -> tuple[dict, bool]:
        """The member's row, created on first attach only. Returns (row, created).

        A new member gets a new Pi session id and its own folder under ``session_root``."""
        return self.attach_team(run_id, host_path, [(member, role or member, pin)],
                                session_root=session_root, attempt_id=attempt_id)[0]

    def attach_team(self, run_id: str, host_path: str,
                    members: Sequence[tuple[str, str, dict]], *, session_root: str,
                    attempt_id: str) -> list[tuple[dict, bool]]:
        """Every member's row in one transaction: (member, role, pin) each. A re-run finds
        the rows (and their sessions) instead of creating new ones."""
        with _LOCK:
            for last in (False, True):
                try:
                    with self._tx() as conn:
                        return [self._attach(conn, run_id, host_path, member, role, pin,
                                             session_root, attempt_id)
                                for member, role, pin in members]
                except IntegrityError:
                    if last:
                        raise
            raise AssertionError("unreachable")

    @staticmethod
    def _attach(conn: Any, run_id: str, host_path: str, member: str, role: str, pin: dict,
                session_root: str, attempt_id: str) -> tuple[dict, bool]:
        row = conn.execute(sa.select(participants).where(
            participants.c.run_id == run_id, participants.c.host_path == host_path,
            participants.c.member == member)).mappings().first()
        if row is not None:
            return dict(row), False
        pid = _new_id()
        values = {
            "participant_id": pid, "run_id": run_id, "host_path": host_path, "member": member,
            "role": role, "state": "idle", "session_id": str(uuid.uuid4()),
            "session_dir": f"{session_root.rstrip('/')}/{pid}/sessions", "pin": dict(pin),
            "turns": 0, "retire_requested": False, "epoch": 0, "ended_reason": None,
            "created_attempt": attempt_id, "created_at": _now(), "retired_at": None,
        }
        conn.execute(participants.insert().values(**values))
        return values, True

    def participants_of(self, run_id: str, host_path: str) -> list[dict]:
        with _LOCK, self._tx() as conn:
            return self._members(conn, run_id, host_path)

    @staticmethod
    def _members(conn: Any, run_id: str, host_path: str) -> list[dict]:
        rows = conn.execute(sa.select(participants).where(
            participants.c.run_id == run_id, participants.c.host_path == host_path,
        ).order_by(participants.c.created_at, participants.c.member)).mappings().all()
        return [dict(r) for r in rows]

    def participant(self, participant_id: str) -> dict | None:
        with _LOCK, self._tx() as conn:
            row = conn.execute(sa.select(participants).where(
                participants.c.participant_id == participant_id)).mappings().first()
            return dict(row) if row else None

    def member_row(self, run_id: str, host_path: str, member: str) -> dict | None:
        with _LOCK, self._tx() as conn:
            row = conn.execute(sa.select(participants).where(
                participants.c.run_id == run_id, participants.c.host_path == host_path,
                participants.c.member == member)).mappings().first()
            return dict(row) if row else None

    def set_participant_state(self, participant_id: str, state: str) -> None:
        with _LOCK, self._tx() as conn:
            conn.execute(participants.update().where(
                participants.c.participant_id == participant_id).values(state=state))

    # --- messages -------------------------------------------------------------------

    @staticmethod
    def _team_ended(conn: Any, run_id: str, host_path: str) -> bool:
        return bool(conn.execute(sa.select(sa.func.count()).select_from(participants).where(
            participants.c.run_id == run_id, participants.c.host_path == host_path,
            participants.c.state == "ended")).scalar_one())

    def post(self, run_id: str, host_path: str, to_member: str, body: str, *,
             sender: str = "owner", sender_kind: str = "owner", kind: str = "owner_reply",
             dedupe_key: str | None = None, review_id: str | None = None,
             conn: Any = None) -> dict:
        """A message from Temper or the owner (goal, owner reply, notice), idempotent by
        ``dedupe_key``: the same message again returns the original; a different one under the
        same key is refused (``LedgerConflict``, R2 B3). Never dropped: a message nobody can
        take is kept ``undelivered`` with the reason."""
        if conn is None:
            with _LOCK:
                try:
                    with self._team_tx(run_id, host_path) as c:
                        return self.post(run_id, host_path, to_member, body, sender=sender,
                                         sender_kind=sender_kind, kind=kind,
                                         dedupe_key=dedupe_key, review_id=review_id, conn=c)
                except IntegrityError:
                    # Another team posted the same key first: compare against its row.
                    with self._team_tx(run_id, host_path) as c:
                        return self.post(run_id, host_path, to_member, body, sender=sender,
                                         sender_kind=sender_kind, kind=kind,
                                         dedupe_key=dedupe_key, review_id=review_id, conn=c)
        digest = content_digest(kind, to_member, body, None, None)
        if dedupe_key is not None:
            existing = conn.execute(sa.select(messages).where(
                messages.c.dedupe_key == dedupe_key)).mappings().first()
            if existing is not None:
                if existing["content_sha256"] != digest:
                    raise LedgerConflict("idempotency_conflict",
                                         f"message key {dedupe_key!r} was already used for a "
                                         "different message")
                return {**dict(existing), "duplicate": True}
        target = conn.execute(sa.select(participants).where(
            participants.c.run_id == run_id, participants.c.host_path == host_path,
            participants.c.member == to_member)).mappings().first()
        if target is None:
            state = "undelivered"
            reason = "late" if self._team_ended(conn, run_id, host_path) else "recipient_unknown"
        elif target["state"] == "ended":
            state, reason = "undelivered", "late"
        elif target["state"] == "retired":
            state, reason = "undelivered", "recipient_retired"
        else:
            state, reason = "pending", None
        mid = _new_id()
        values = {
            "message_id": mid, "dedupe_key": dedupe_key, "run_id": run_id,
            "host_path": host_path, "to_participant": target["participant_id"] if target else None,
            "to_member": to_member, "sender": sender, "sender_kind": sender_kind,
            "sender_participant": None, "sender_session": None, "sender_turn": None,
            "sender_epoch": None, "kind": kind, "client_msg_id": None, "content_sha256": digest,
            "in_reply_to": None, "thread_id": mid, "outcome": None,
            "policy_version": POLICY_VERSION, "body": body, "state": state, "turn_id": None,
            "delivery_count": 0, "redeliver_turn": None, "undelivered_reason": reason,
            "released_at": None, "delivered_at": None, "review_id": review_id,
            "created_at": _now(),
        }
        seq = conn.execute(messages.insert().values(**values)).inserted_primary_key[0]
        return {**values, "seq": seq, "duplicate": False}

    def member_send(self, binding: Binding, payload: Any) -> dict:
        """A member's message from its box (the team socket of a running turn), in A7's order:
        channel, payload, key, reference, recipient. Stored ``held`` with its turn (B4); the
        sender comes from the binding only (B2). Returns what the send tool shows the model:
        ``{ok, message_id, to, kind, duplicate}`` or ``{ok: False, code, detail}``."""
        with _LOCK, self._team_tx(binding.run_id, binding.host_path) as conn:
            if not _fence(conn, binding.turn_id, binding.epoch):
                # The turn is over or was taken over: nothing stored, no id used. Logged for
                # the audit without naming a run or a sender (A7 identity-invalid-channel).
                logger.info("pi team: a send on a closed message channel was refused")
                return {"ok": False, "code": route_model.INVALID_CHANNEL,
                        "detail": "this turn's message channel is closed"}
            try:
                return self._admit(conn, binding, payload)
            except Refusal as refusal:
                self._audit(conn, binding, refusal, payload)
                return {"ok": False, "code": refusal.code, "detail": refusal.detail}

    def _admit(self, conn: Any, binding: Binding, payload: Any) -> dict:
        send = check_payload(payload, binding.trusted())
        existing = conn.execute(sa.select(messages).where(
            messages.c.run_id == binding.run_id,
            messages.c.sender_participant == binding.participant_id,
            messages.c.client_msg_id == send.client_msg_id)).mappings().first()
        if existing is not None:
            if existing["content_sha256"] != send.content_sha256:
                raise Refusal(route_model.IDEMPOTENCY_CONFLICT,
                              "that message id was already used for a different message")
            return {"ok": True, "message_id": existing["message_id"],
                    "to": existing["to_member"], "kind": existing["kind"], "duplicate": True}
        ref = None
        if send.in_reply_to is not None:
            ref = conn.execute(sa.select(messages).where(
                messages.c.message_id == send.in_reply_to, messages.c.run_id == binding.run_id,
                messages.c.host_path == binding.host_path)).mappings().first()
            received = (ref is not None and ref["to_participant"] == binding.participant_id
                        and ref["state"] == "consumed")
            own = ref is not None and ref["sender_participant"] == binding.participant_id
            if not (received or (own and send.kind != route_model.REPLY)):
                raise Refusal(route_model.INVALID_REFERENCE,
                              "in_reply_to must be a message you received")
        members = self._members(conn, binding.run_id, binding.host_path)
        by_name = {m["member"]: m for m in members}
        me = by_name[binding.member]
        policy = all_policy(binding.run_id)
        sender = roster_entry(binding.run_id, me)
        target: dict | None
        if send.kind == route_model.REPLY:
            assert ref is not None
            asker = next((m for m in members
                          if m["participant_id"] == ref["sender_participant"]), None)
            if ref["sender_kind"] != "member" or asker is None:
                raise Refusal(route_model.INVALID_REFERENCE,
                              "a reply answers a message from another member")
            if send.to is not None and send.to != asker["member"]:
                raise Refusal(route_model.INVALID_REFERENCE,
                              "a reply goes to the member who sent the message it answers")
            decision = route_reply(policy, sender, roster_entry(binding.run_id, asker))
            target = asker
        else:
            target = by_name.get(send.to or "")
            decision = route(policy, sender, None if target is None else
                             roster_entry(binding.run_id, target), send.kind)
        assert target is not None  # route() refuses an unknown name before this
        mid = _new_id()
        values = {
            "message_id": mid, "dedupe_key": None, "run_id": binding.run_id,
            "host_path": binding.host_path, "to_participant": target["participant_id"],
            "to_member": target["member"], "sender": binding.member, "sender_kind": "member",
            "sender_participant": binding.participant_id,
            "sender_session": binding.session_id, "sender_turn": binding.turn_id,
            "sender_epoch": binding.epoch, "kind": send.kind,
            "client_msg_id": send.client_msg_id, "content_sha256": send.content_sha256,
            "in_reply_to": send.in_reply_to,
            "thread_id": (ref["thread_id"] or ref["message_id"]) if ref is not None else mid,
            "outcome": send.outcome, "policy_version": f"all@{decision.policy_version}",
            "body": send.body, "state": "held", "turn_id": None, "delivery_count": 0,
            "redeliver_turn": None, "undelivered_reason": None, "released_at": None,
            "delivered_at": None, "review_id": None, "created_at": _now(),
        }
        conn.execute(messages.insert().values(**values))
        return {"ok": True, "message_id": mid, "to": target["member"], "kind": send.kind,
                "duplicate": False}

    @staticmethod
    def _audit(conn: Any, binding: Binding, refusal: Refusal, payload: Any) -> None:
        """A refused send is recorded on its turn (A7 audit), names only, no bodies."""
        row = conn.execute(sa.select(turns.c.refusals).where(
            turns.c.turn_id == binding.turn_id)).first()
        items = list((row[0] if row else None) or [])
        item: dict[str, Any] = {"at": _now(), "code": refusal.code}
        if isinstance(payload, dict):
            item["to"] = _short(payload.get("to"))
            item["client_msg_id"] = _short(payload.get("client_msg_id"))
        if refusal.claims:
            item["claims"] = list(refusal.claims)
        items = (items + [item])[-MAX_REFUSALS:]
        conn.execute(turns.update().where(
            turns.c.turn_id == binding.turn_id, turns.c.state == "running",
            turns.c.epoch == binding.epoch).values(refusals=items))

    def messages_by_seq(self, seqs: Sequence[int]) -> list[dict]:
        with _LOCK, self._tx() as conn:
            rows = conn.execute(sa.select(messages).where(messages.c.seq.in_(list(seqs)))
                                .order_by(messages.c.seq)).mappings().all()
            return [dict(r) for r in rows]

    def pending_for(self, participant_id: str) -> list[dict]:
        with _LOCK, self._tx() as conn:
            rows = conn.execute(sa.select(messages).where(
                messages.c.to_participant == participant_id, messages.c.state == "pending",
            ).order_by(messages.c.seq)).mappings().all()
            return [dict(r) for r in rows]

    # --- turns ----------------------------------------------------------------------

    def claim_turn(self, run_id: str, host_path: str, *, attempt_id: str,
                   claimed_by: str | None = None) -> tuple[dict, list[dict]] | None:
        """The team's next turn, or None (R2 B6): no turn while any wait is open, while a turn
        is unsettled, or while a member's turn awaits the owner (failed or uncertain). The
        idle member holding the team's oldest pending message goes; its batch is the messages
        of a retried turn (same ids, B1) if it has one, else every message pending for it up
        to now, in order (later ones wait for the next turn boundary). All or nothing: the
        unique claim key, the member's epoch compare-and-set and the batch's row count make a
        second process's claim of the same turn fail."""
        with _LOCK:
            try:
                with self._team_tx(run_id, host_path) as conn:
                    return self._claim(conn, run_id, host_path, attempt_id,
                                       claimed_by or process_identity())
            except (_Rollback, IntegrityError):
                return None
            except OperationalError as exc:
                text = str(exc).lower()
                if any(s in text for s in ("locked", "deadlock", "could not serialize")):
                    return None
                raise

    def _claim(self, conn: Any, run_id: str, host_path: str, attempt_id: str,
               claimed_by: str) -> tuple[dict, list[dict]] | None:
        team = (participants.c.run_id == run_id, participants.c.host_path == host_path)
        if self._open_wait_count(conn, run_id, host_path):
            return None
        if conn.execute(sa.select(sa.func.count()).select_from(turns).where(
                turns.c.run_id == run_id, turns.c.host_path == host_path,
                turns.c.claim_key.is_not(None))).scalar_one():
            return None
        if conn.execute(sa.select(sa.func.count()).select_from(participants).where(
                *team, participants.c.state.in_(("failed", "uncertain")))).scalar_one():
            return None
        pick = conn.execute(
            sa.select(participants.c.participant_id)
            .join(messages, messages.c.to_participant == participants.c.participant_id)
            .where(*team, participants.c.state == "idle", messages.c.state == "pending")
            .group_by(participants.c.participant_id)
            .order_by(sa.func.min(messages.c.seq)).limit(1)).first()
        if pick is None:
            return None
        p = dict(conn.execute(sa.select(participants).where(
            participants.c.participant_id == pick[0])).mappings().one())
        cut = conn.execute(sa.select(sa.func.max(messages.c.seq)).where(
            messages.c.run_id == run_id, messages.c.host_path == host_path)).scalar()
        mine = (messages.c.to_participant == p["participant_id"], messages.c.state == "pending",
                messages.c.seq <= cut)
        redeliver = conn.execute(sa.select(messages.c.seq, messages.c.redeliver_turn).where(
            *mine, messages.c.redeliver_turn.is_not(None)).order_by(messages.c.seq)).all()
        if redeliver:
            retry_of = redeliver[0][1]
            seqs = [r[0] for r in redeliver if r[1] == retry_of]
        else:
            retry_of = None
            seqs = list(conn.execute(sa.select(messages.c.seq).where(*mine)
                                     .order_by(messages.c.seq)).scalars())
        if not seqs:
            return None
        last_no = conn.execute(sa.select(sa.func.max(turns.c.turn_no)).where(
            turns.c.participant_id == p["participant_id"])).scalar()
        epoch = p["epoch"] + 1
        turn = {
            "turn_id": _new_id(), "participant_id": p["participant_id"], "run_id": run_id,
            "host_path": host_path, "turn_no": (last_no or 0) + 1, "attempt_id": attempt_id,
            "state": "running", "claim_key": team_claim_key(run_id, host_path), "epoch": epoch,
            "claimed_by": claimed_by[:255], "retry_of": retry_of, "input_seqs": seqs,
            "cut_seq": cut, "policy_version": POLICY_VERSION, "agent_event_id": None,
            "model_call_ids": [], "effect_state": "none", "refusals": [], "box_name": None,
            "box_stop": None, "output": None, "error": None, "worker": None,
            "started_at": _now(), "ended_at": None,
        }
        conn.execute(turns.insert().values(**turn))
        if conn.execute(participants.update().where(
                participants.c.participant_id == p["participant_id"],
                participants.c.state == "idle", participants.c.epoch == p["epoch"],
        ).values(state="running", epoch=epoch)).rowcount != 1:
            raise _Rollback
        if conn.execute(messages.update().where(
                messages.c.seq.in_(seqs), messages.c.state == "pending",
        ).values(state="consumed", turn_id=turn["turn_id"],
                 delivery_count=messages.c.delivery_count + 1, redeliver_turn=None,
                 delivered_at=_now())).rowcount != len(seqs):
            raise _Rollback
        # A wait opened by a turn that settled while this claim ran (its owner question)
        # is seen here, after the claim key was taken: no turn starts past an open wait.
        if self._open_wait_count(conn, run_id, host_path):
            raise _Rollback
        batch = [dict(r) for r in conn.execute(sa.select(messages).where(
            messages.c.seq.in_(seqs)).order_by(messages.c.seq)).mappings().all()]
        return turn, batch

    def turn(self, turn_id: str) -> dict | None:
        with _LOCK, self._tx() as conn:
            row = conn.execute(sa.select(turns).where(turns.c.turn_id == turn_id)).mappings().first()
            return dict(row) if row else None

    def turns_of(self, participant_id: str) -> list[dict]:
        with _LOCK, self._tx() as conn:
            rows = conn.execute(sa.select(turns).where(
                turns.c.participant_id == participant_id).order_by(turns.c.turn_no)).mappings().all()
            return [dict(r) for r in rows]

    def _fenced(self, turn_id: str, epoch: int | None, **values: Any) -> bool:
        """One write of a turn's owner, refused once the turn is no longer its own (C1)."""
        if epoch is None:
            return False
        with _LOCK, self._tx() as conn:
            return conn.execute(turns.update().where(
                turns.c.turn_id == turn_id, turns.c.state == "running", turns.c.epoch == epoch,
            ).values(**values)).rowcount == 1

    def record_box(self, turn_id: str, epoch: int | None, box_name: str | None) -> bool:
        """The worker box's name, written before the box is created (C1)."""
        return self._fenced(turn_id, epoch, box_name=box_name)

    def set_turn_agent_event(self, turn_id: str, agent_event_id: str, *,
                             epoch: int | None = None) -> bool:
        return self._fenced(turn_id, epoch, agent_event_id=agent_event_id)

    def mark_effect(self, turn_id: str, effect_state: str, *, epoch: int | None = None) -> bool:
        return self._fenced(turn_id, epoch, effect_state=effect_state)

    @staticmethod
    def _release(conn: Any, turn_id: str) -> dict[str, int]:
        """A settled turn's held messages leave (B4), each recipient checked again (C5)."""
        held = conn.execute(sa.select(messages.c.seq, messages.c.to_participant).where(
            messages.c.sender_turn == turn_id, messages.c.state == "held")).all()
        counts = {"pending": 0, "undelivered": 0}
        now = _now()
        for seq, pid in held:
            state = conn.execute(sa.select(participants.c.state).where(
                participants.c.participant_id == pid)).scalar() if pid else None
            if state in ("retired", "ended", None):
                reason = {"retired": "recipient_retired", "ended": "late"}.get(
                    state or "", "recipient_unknown")
                values: dict[str, Any] = {"state": "undelivered", "undelivered_reason": reason}
                counts["undelivered"] += 1
            else:
                values = {"state": "pending", "released_at": now}
                counts["pending"] += 1
            conn.execute(messages.update().where(messages.c.seq == seq,
                                                 messages.c.state == "held").values(**values))
        return counts

    @staticmethod
    def _withhold(conn: Any, turn_id: str, reason: str) -> int:
        """A turn that did not settle as done: what it sent is recorded, never delivered."""
        return conn.execute(messages.update().where(
            messages.c.sender_turn == turn_id, messages.c.state == "held",
        ).values(state="undelivered", undelivered_reason=reason)).rowcount

    def finish_turn(self, turn_id: str, *, epoch: int | None, output: str,
                    model_call_ids: list[str], worker: dict | None, ask_owner: dict | None,
                    attempt_id: str, retire: bool = False) -> dict | None:
        """Complete a turn: its held messages leave, the member goes idle (or retires) and,
        when ``ask_owner`` is given (``{"question", "options"}``), the owner wait follows -- in
        one transaction. None when the turn is no longer this owner's (stale write)."""
        team = self._team_of(turns, turns.c.turn_id, turn_id)
        if team is None:
            return None
        with _LOCK, self._team_tx(*team) as conn:
            if conn.execute(turns.update().where(
                    turns.c.turn_id == turn_id, turns.c.state == "running",
                    turns.c.epoch == epoch,
            ).values(state="completed", claim_key=None, output=output,
                     model_call_ids=list(model_call_ids), effect_state="committed",
                     worker=worker, ended_at=_now())).rowcount != 1:
                return None
            t = conn.execute(sa.select(turns).where(turns.c.turn_id == turn_id)).mappings().one()
            released = self._release(conn, turn_id)
            p = conn.execute(sa.select(participants).where(
                participants.c.participant_id == t["participant_id"])).mappings().one()
            arrived = conn.execute(sa.select(sa.func.count()).select_from(messages).where(
                messages.c.to_participant == p["participant_id"],
                messages.c.state == "pending")).scalar_one()
            # Retirement only with an empty inbox: a message that arrived meanwhile is
            # answered first (the retirement is deferred), never dropped.
            retired = bool(retire) and arrived == 0
            conn.execute(participants.update().where(
                participants.c.participant_id == p["participant_id"]).values(
                state="retired" if retired else "idle", turns=p["turns"] + 1,
                retire_requested=bool(retire) and not retired,
                retired_at=_now() if retired else None))
            wait = None
            if ask_owner and not retired:
                wait = self._open_wait(conn, p["run_id"], p["host_path"], "owner", {
                    "participant_id": p["participant_id"], "member": p["member"],
                    "role": p["role"], "turn_id": turn_id, "turn_no": t["turn_no"],
                    **ask_owner}, attempt_id)
            return {"retired": retired, "arrived_meanwhile": arrived, "wait": wait,
                    "released": released}

    def fail_turn(self, turn_id: str, error: str, model_call_ids: list[str],
                  worker: dict | None = None, *, epoch: int | None) -> bool:
        """A turn that failed visibly: what it sent stays undelivered and the member waits for
        the owner (retry or stop). False when the turn is no longer this owner's."""
        team = self._team_of(turns, turns.c.turn_id, turn_id)
        if team is None:
            return False
        with _LOCK, self._team_tx(*team) as conn:
            if conn.execute(turns.update().where(
                    turns.c.turn_id == turn_id, turns.c.state == "running",
                    turns.c.epoch == epoch,
            ).values(state="failed", claim_key=None, error=error,
                     model_call_ids=list(model_call_ids), worker=worker,
                     ended_at=_now())).rowcount != 1:
                return False
            t = conn.execute(sa.select(turns).where(turns.c.turn_id == turn_id)).mappings().one()
            self._withhold(conn, turn_id, "turn_failed")
            conn.execute(participants.update().where(
                participants.c.participant_id == t["participant_id"]).values(state="failed"))
            return True

    def hold_turn(self, turn_id: str, error: str, model_call_ids: list[str],
                  worker: dict | None, attempt_id: str, *, epoch: int | None) -> dict | None:
        """A turn whose effects are unknown (worker gone, timeout, a tool that never ended, a
        usage limit): ``uncertain``, still holding the team's claim, and a recovery wait that
        pauses the team (B11) -- never a blind re-run. None when no longer this owner's."""
        team = self._team_of(turns, turns.c.turn_id, turn_id)
        if team is None:
            return None
        with _LOCK, self._team_tx(*team) as conn:
            if conn.execute(turns.update().where(
                    turns.c.turn_id == turn_id, turns.c.state == "running",
                    turns.c.epoch == epoch,
            ).values(state="uncertain", error=error, model_call_ids=list(model_call_ids),
                     worker=worker, ended_at=_now())).rowcount != 1:
                return None
            t = dict(conn.execute(sa.select(turns).where(
                turns.c.turn_id == turn_id)).mappings().one())
            p = dict(conn.execute(sa.select(participants).where(
                participants.c.participant_id == t["participant_id"])).mappings().one())
            conn.execute(participants.update().where(
                participants.c.participant_id == p["participant_id"]).values(state="uncertain"))
            return self._recovery_wait(conn, p, t, error or "cut off", ["accept", "retry"],
                                       attempt_id)

    def interrupted_turns(self, run_id: str, host_path: str) -> list[dict]:
        """Turns still ``running`` in the ledger: when a step starts, their attempt is gone."""
        with _LOCK, self._tx() as conn:
            rows = conn.execute(sa.select(turns).where(
                turns.c.run_id == run_id, turns.c.host_path == host_path,
                turns.c.state == "running").order_by(turns.c.started_at)).mappings().all()
            return [dict(r) for r in rows]

    def take_over(self, run_id: str, host_path: str, attempt_id: str,
                  stop_box: Callable[[str], dict],
                  why: str = "the service stopped during the turn") -> list[tuple[dict, dict]]:
        """Every turn of the team still ``running`` (its owner is gone) becomes ``uncertain``
        with a recovery wait (B11) -- only once its worker box is confirmed stopped (C1, A3
        rule 4). First the turn's epoch moves on (every late write of the old owner now fails
        its fence), then the box is confirmed gone, then the effect state is read. A box that
        cannot be confirmed gone raises :class:`TakeoverRefused` and nothing is taken over."""
        out = []
        for old in self.interrupted_turns(run_id, host_path):
            with _LOCK, self._team_tx(run_id, host_path) as conn:
                if conn.execute(turns.update().where(
                        turns.c.turn_id == old["turn_id"], turns.c.state == "running",
                        turns.c.epoch == old["epoch"],
                ).values(epoch=old["epoch"] + 1)).rowcount != 1:
                    continue
                box_name = conn.execute(sa.select(turns.c.box_name).where(
                    turns.c.turn_id == old["turn_id"])).scalar()
            epoch = old["epoch"] + 1
            if box_name:
                try:
                    result = dict(stop_box(box_name))
                except Exception as exc:  # noqa: BLE001 - recorded, then refused red
                    result = {"box": box_name, "confirmed": False,
                              "error": f"{type(exc).__name__}: {exc}"[:300]}
            else:
                # The name is written before the box is created: none means no box ever was.
                result = {"box": None, "found": False, "was_running": False, "removed": False,
                          "confirmed": True, "error": None, "note": "no box was created"}
            result["at"] = _now()
            if not result.get("confirmed"):
                self._fenced(old["turn_id"], epoch, box_stop=result)
                raise TakeoverRefused(old["turn_id"], result)
            with _LOCK, self._team_tx(run_id, host_path) as conn:
                if conn.execute(turns.update().where(
                        turns.c.turn_id == old["turn_id"], turns.c.state == "running",
                        turns.c.epoch == epoch,
                ).values(state="uncertain", box_stop=result, ended_at=_now())).rowcount != 1:
                    continue
                t = dict(conn.execute(sa.select(turns).where(
                    turns.c.turn_id == old["turn_id"])).mappings().one())
                p = dict(conn.execute(sa.select(participants).where(
                    participants.c.participant_id == t["participant_id"])).mappings().one())
                conn.execute(participants.update().where(
                    participants.c.participant_id == p["participant_id"]).values(
                    state="uncertain", epoch=participants.c.epoch + 1))
                wait = self._recovery_wait(conn, p, t, why, ["accept", "retry"], attempt_id)
            out.append((t, wait))
        return out

    def open_recovery_for_failed(self, run_id: str, host_path: str, attempt_id: str) -> list[dict]:
        """On a re-run after a failure: each failed member's last failed turn gets an owner
        recovery wait -- retry it or stop (N1) -- never an automatic re-run."""
        with _LOCK, self._team_tx(run_id, host_path) as conn:
            failed = conn.execute(sa.select(participants).where(
                participants.c.run_id == run_id, participants.c.host_path == host_path,
                participants.c.state == "failed")).mappings().all()
            opened = []
            for p in failed:
                t = conn.execute(sa.select(turns).where(
                    turns.c.participant_id == p["participant_id"], turns.c.state == "failed",
                ).order_by(turns.c.turn_no.desc())).mappings().first()
                if t is None:
                    continue
                conn.execute(participants.update().where(
                    participants.c.participant_id == p["participant_id"]).values(
                    state="uncertain"))
                opened.append(self._recovery_wait(conn, dict(p), dict(t), "failed",
                                                  ["retry", "stop"], attempt_id))
            return opened

    def _recovery_wait(self, conn: Any, p: dict, t: dict, why: str, options: list[str],
                       attempt_id: str) -> dict:
        name = p["member"]
        if options == ["retry", "stop"]:
            question = (f"{name}'s turn {t['turn_no']} failed: {(t['error'] or '')[:300]}. "
                        "Reply 'retry' to send its messages again, or 'stop' to end the step.")
        else:
            did = ("nothing was sent to the model" if t["effect_state"] == "none" else
                   "the model may have acted (its prompt was sent)")
            question = (f"{name}'s turn {t['turn_no']} did not finish ({why}); {did}. Reply "
                        "'accept' to keep what it did without running it again, or 'retry' to "
                        "send its messages again.")
        return self._open_wait(conn, p["run_id"], p["host_path"], "recovery", {
            "participant_id": p["participant_id"], "member": name, "role": p["role"],
            "turn_id": t["turn_id"], "turn_no": t["turn_no"],
            "effect_state": t["effect_state"], "input_seqs": t["input_seqs"], "why": why,
            "question": question, "options": options,
        }, attempt_id)

    # --- waits ----------------------------------------------------------------------

    @staticmethod
    def _open_wait_count(conn: Any, run_id: str, host_path: str) -> int:
        return conn.execute(sa.select(sa.func.count()).select_from(waits).where(
            waits.c.run_id == run_id, waits.c.host_path == host_path,
            waits.c.state == "open")).scalar_one()

    def _open_wait(self, conn: Any, run_id: str, host_path: str, kind: str, subject: dict,
                   attempt_id: str) -> dict:
        wait_id = _new_id()
        values = {
            "wait_id": wait_id, "run_id": run_id, "host_path": host_path, "kind": kind,
            "gate_name": gate_name_for(host_path, wait_id), "event_id": str(uuid.uuid4()),
            "state": "open", "subject": subject, "decision": None,
            "opened_attempt": attempt_id, "decided_attempt": None, "opened_at": _now(),
            "decided_at": None, "event_recorded": False,
        }
        conn.execute(waits.insert().values(**values))
        return values

    def open_wait(self, run_id: str, host_path: str, kind: str, subject: dict,
                  attempt_id: str) -> dict:
        with _LOCK, self._team_tx(run_id, host_path) as conn:
            return self._open_wait(conn, run_id, host_path, kind, subject, attempt_id)

    def open_waits(self, run_id: str, host_path: str) -> list[dict]:
        with _LOCK, self._tx() as conn:
            rows = conn.execute(sa.select(waits).where(
                waits.c.run_id == run_id, waits.c.host_path == host_path,
                waits.c.state == "open").order_by(waits.c.opened_at)).mappings().all()
            return [dict(r) for r in rows]

    def decide_wait(self, wait_id: str, decision: dict, attempt_id: str,
                    deliveries: Sequence[tuple[str, str]] = (),
                    recovery: tuple[str, str] | None = None,
                    participant_states: Sequence[tuple[str, str]] = ()) -> bool:
        """Compare-and-set open -> decided, with everything the decision does, exactly once.

        ``deliveries``: (to_member, body) from the owner. ``recovery``: (word, turn_id) with
        word ``accept`` (the turn stands; what it sent leaves), ``retry`` (superseded; what it
        sent is never delivered; its messages go back to the member with the same ids, B1) or
        ``stop`` (failed). ``participant_states``: (participant_id, new state)."""
        team = self._team_of(waits, waits.c.wait_id, wait_id)
        if team is None:
            return False
        with _LOCK, self._team_tx(*team) as conn:
            w = conn.execute(sa.select(waits).where(waits.c.wait_id == wait_id)).mappings().first()
            if w is None or conn.execute(waits.update().where(
                    waits.c.wait_id == wait_id, waits.c.state == "open").values(
                    state="decided", decision=decision, decided_attempt=attempt_id,
                    decided_at=_now())).rowcount != 1:
                return False
            if recovery is not None:
                self._recover(conn, *recovery)
            for pid, state in participant_states:
                values: dict[str, Any] = {"state": state}
                if state == "retired":
                    values["retired_at"] = _now()
                conn.execute(participants.update().where(
                    participants.c.participant_id == pid).values(**values))
            for i, (to_member, body) in enumerate(deliveries):
                self.post(w["run_id"], w["host_path"], to_member, body,
                          dedupe_key=f"{wait_id}:decision:{i}", conn=conn)
            return True

    def _recover(self, conn: Any, word: str, turn_id: str) -> None:
        t = conn.execute(sa.select(turns).where(turns.c.turn_id == turn_id)).mappings().first()
        if t is None:
            return
        pid = t["participant_id"]
        if word == "accept":
            if conn.execute(turns.update().where(
                    turns.c.turn_id == turn_id, turns.c.state == "uncertain",
            ).values(state="accepted", claim_key=None)).rowcount == 1:
                self._release(conn, turn_id)
            member_state = "idle"
        elif word == "retry":
            if conn.execute(turns.update().where(
                    turns.c.turn_id == turn_id, turns.c.state.in_(("uncertain", "failed")),
            ).values(state="superseded", claim_key=None)).rowcount == 1:
                self._withhold(conn, turn_id, "turn_superseded")
                conn.execute(messages.update().where(
                    messages.c.turn_id == turn_id, messages.c.state == "consumed",
                ).values(state="pending", turn_id=None, redeliver_turn=turn_id,
                         delivered_at=None))
            member_state = "idle"
        else:
            if conn.execute(turns.update().where(
                    turns.c.turn_id == turn_id, turns.c.state == "uncertain",
            ).values(state="failed", claim_key=None, ended_at=_now())).rowcount == 1:
                self._withhold(conn, turn_id, "turn_failed")
            member_state = "failed"
        conn.execute(participants.update().where(
            participants.c.participant_id == pid,
            participants.c.state.notin_(("retired", "ended"))).values(state=member_state))

    def cancel_open_waits(self, run_id: str, host_path: str, attempt_id: str,
                          why: str) -> list[dict]:
        with _LOCK, self._team_tx(run_id, host_path) as conn:
            return self._cancel_waits(conn, run_id, host_path, attempt_id, why)

    @staticmethod
    def _cancel_waits(conn: Any, run_id: str, host_path: str, attempt_id: str,
                      why: str) -> list[dict]:
        rows = [dict(r) for r in conn.execute(sa.select(waits).where(
            waits.c.run_id == run_id, waits.c.host_path == host_path,
            waits.c.state == "open")).mappings().all()]
        for w in rows:
            conn.execute(waits.update().where(
                waits.c.wait_id == w["wait_id"], waits.c.state == "open").values(
                state="cancelled", decision={"cancelled": why},
                decided_attempt=attempt_id, decided_at=_now()))
        return rows

    # --- the team's end (B6, B12) -----------------------------------------------------

    def end_team(self, run_id: str, host_path: str, reason: str, attempt_id: str) -> dict:
        """The team ends (cancelled or done): unsettled turns cancelled, every held or pending
        message recorded undelivered with the reason, open waits cancelled, members ended.
        Nothing is deleted; anything posted afterwards is recorded ``late``."""
        if reason not in END_REASONS:
            raise ValueError(f"unknown end reason {reason!r}")
        with _LOCK, self._team_tx(run_id, host_path) as conn:
            open_turns = [dict(r) for r in conn.execute(sa.select(turns).where(
                turns.c.run_id == run_id, turns.c.host_path == host_path,
                turns.c.claim_key.is_not(None))).mappings().all()]
            for t in open_turns:
                conn.execute(turns.update().where(
                    turns.c.turn_id == t["turn_id"], turns.c.state.in_(UNSETTLED),
                ).values(state="cancelled", claim_key=None, ended_at=_now()))
                self._withhold(conn, t["turn_id"], "turn_cancelled")
            undelivered = conn.execute(messages.update().where(
                messages.c.run_id == run_id, messages.c.host_path == host_path,
                messages.c.state.in_(("held", "pending")),
            ).values(state="undelivered", undelivered_reason=reason)).rowcount
            cancelled = self._cancel_waits(conn, run_id, host_path, attempt_id, reason)
            ended = conn.execute(participants.update().where(
                participants.c.run_id == run_id, participants.c.host_path == host_path,
                participants.c.state.notin_(("retired", "ended")),
            ).values(state="ended", ended_reason=reason)).rowcount
            return {"cancelled_turns": [t["turn_id"] for t in open_turns],
                    "undelivered": undelivered, "cancelled_waits": cancelled,
                    "ended_members": ended}

    def end_teams_for_run(self, run_id: str, reason: str, attempt_id: str) -> list[dict]:
        """Every Pi team and Pi step of a run ends (a parked run's cancel, C2)."""
        with _LOCK, self._tx() as conn:
            hosts = sorted(set(conn.execute(sa.select(participants.c.host_path).where(
                participants.c.run_id == run_id)).scalars()))
        return [{"host_path": h, **self.end_team(run_id, h, reason, attempt_id)} for h in hosts]

    # --- the quiet-team check and the review record -----------------------------------

    def team_state(self, run_id: str, host_path: str) -> dict:
        """What the team is doing, straight from the tables: quiet when nothing is unsettled,
        nothing is waiting to be delivered, no wait or review is open and nothing is done."""
        with _LOCK, self._tx() as conn:
            unsettled = [dict(r) for r in conn.execute(sa.select(turns).where(
                turns.c.run_id == run_id, turns.c.host_path == host_path,
                turns.c.claim_key.is_not(None))).mappings().all()]
            waiting = [dict(r) for r in conn.execute(sa.select(messages).where(
                messages.c.run_id == run_id, messages.c.host_path == host_path,
                messages.c.state.in_(("pending", "held"))).order_by(messages.c.seq))
                .mappings().all()]
            open_w = [dict(r) for r in conn.execute(sa.select(waits).where(
                waits.c.run_id == run_id, waits.c.host_path == host_path,
                waits.c.state == "open")).mappings().all()]
            revs = [dict(r) for r in conn.execute(sa.select(reviews).where(
                reviews.c.run_id == run_id, reviews.c.host_path == host_path,
            ).order_by(reviews.c.round)).mappings().all()]
            members = self._members(conn, run_id, host_path)
        counts = {
            "unsettled": len(unsettled), "waiting_messages": len(waiting),
            "open_waits": len(open_w),
            "open_reviews": sum(1 for r in revs if r["state"] in ("open", "collected")),
            "done": sum(1 for r in revs if r["decision"] == "done"),
        }
        return {**counts, "quiet": not any(counts.values()), "turns": unsettled,
                "messages": waiting, "waits": open_w, "reviews": revs, "members": members}

    def open_review(self, run_id: str, host_path: str, *, round_no: int,
                    leader_participant: str, asked_turn: str, commit_sha: str,
                    files: dict) -> dict:
        values = {
            "review_id": _new_id(), "run_id": run_id, "host_path": host_path,
            "round": round_no, "leader_participant": leader_participant,
            "asked_turn": asked_turn, "commit_sha": commit_sha, "files": dict(files),
            "state": "open", "decision": None, "decided_turn": None, "summary": None,
            "cost": None, "opened_at": _now(), "decided_at": None,
        }
        with _LOCK, self._team_tx(run_id, host_path) as conn:
            conn.execute(reviews.insert().values(**values))
        return values

    def update_review(self, review_id: str, **values: Any) -> bool:
        allowed = {"state", "decision", "decided_turn", "summary", "cost", "decided_at"}
        unknown = set(values) - allowed
        if unknown:
            raise ValueError(f"not review fields: {sorted(unknown)}")
        with _LOCK, self._tx() as conn:
            return conn.execute(reviews.update().where(
                reviews.c.review_id == review_id).values(**values)).rowcount == 1

    def reviews_of(self, run_id: str, host_path: str) -> list[dict]:
        with _LOCK, self._tx() as conn:
            return [dict(r) for r in conn.execute(sa.select(reviews).where(
                reviews.c.run_id == run_id, reviews.c.host_path == host_path,
            ).order_by(reviews.c.round)).mappings().all()]

    # --- reading everything back (evidence) ------------------------------------------

    def snapshot(self, run_id: str) -> dict[str, list[dict]]:
        with _LOCK, self._tx() as conn:
            out = {}
            for name, table, order in (
                ("participants", participants, participants.c.created_at),
                ("messages", messages, messages.c.seq),
                ("turns", turns, turns.c.started_at),
                ("waits", waits, waits.c.opened_at),
                ("reviews", reviews, reviews.c.round),
            ):
                out[name] = [dict(r) for r in conn.execute(
                    sa.select(table).where(table.c.run_id == run_id).order_by(order)).mappings()]
            return out
