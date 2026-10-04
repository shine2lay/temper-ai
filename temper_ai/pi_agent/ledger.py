"""The Pi agent step's durable ledger: who is in the conversation, what they were sent, what
each turn did, and what the owner is being asked.

Four tables in their own SQLAlchemy ``MetaData`` -- never Temper's SQLModel metadata, so
Temper's ``create_all`` and migrations never see them. They are created on first use, on the
database Temper's engine already points at; with the Pi agent step switched off nothing
creates or reads them. Schema and retention: ``docs/pi-agent.md``.

Identities kept apart on purpose:

* participant -- one row per (run, host node path, role), with the Pi session id it keeps for
  life. Created once, re-attached on every attempt; its session is reopened, never replaced.
* turn -- one row per Pi prompt cycle; it consumes every message that was pending for that
  participant when it started, as one ordered batch.
* model call -- the Pi stream mapper's ids, recorded on the turn.
* workflow attempt -- Temper's ``workflow.started`` event id of the attempt that did the work.

Every change is one transaction under one process-wide lock, so a turn's completion and the
owner wait it opens land together or not at all, and a wait is decided by compare-and-set
exactly once.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa

metadata = sa.MetaData()

_LOCK = threading.RLock()

#: Participant states. ``uncertain``: its last turn was cut off or failed and the owner decides.
PARTICIPANT_STATES = ("idle", "running", "uncertain", "failed", "retired")
#: Turn states.
TURN_STATES = ("running", "completed", "failed", "uncertain", "accepted", "superseded")
#: Wait kinds: ``owner`` (next message or finish), ``recovery`` (accept or retry a turn that
#: was cut off or failed), ``stalled`` (several participants with nothing to do; L3).
WAIT_KINDS = ("owner", "recovery", "stalled")

participants = sa.Table(
    "pi_participants", metadata,
    sa.Column("participant_id", sa.String(64), primary_key=True),
    sa.Column("run_id", sa.String(64), nullable=False, index=True),
    sa.Column("host_path", sa.String(255), nullable=False),
    sa.Column("role", sa.String(128), nullable=False),
    sa.Column("state", sa.String(16), nullable=False),
    sa.Column("session_id", sa.String(64), nullable=False),
    sa.Column("session_dir", sa.String(1024), nullable=False),
    # Pinned at creation and compared before every turn: Pi version, provider, model,
    # thinking, tools, extensions (name -> digest), workflow, cwd, image.
    sa.Column("pin", sa.JSON, nullable=False),
    sa.Column("turns", sa.Integer, nullable=False, default=0),
    sa.Column("retire_requested", sa.Boolean, nullable=False, default=False),
    sa.Column("created_attempt", sa.String(64)),
    sa.Column("created_at", sa.String(40)),
    sa.Column("retired_at", sa.String(40)),
    sa.UniqueConstraint("run_id", "host_path", "role", name="uq_pi_participant_role"),
)

messages = sa.Table(
    "pi_messages", metadata,
    sa.Column("seq", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("message_id", sa.String(64), nullable=False, unique=True),
    sa.Column("dedupe_key", sa.String(255), unique=True),
    sa.Column("run_id", sa.String(64), nullable=False, index=True),
    sa.Column("host_path", sa.String(255), nullable=False),
    sa.Column("to_participant", sa.String(64)),
    sa.Column("to_role", sa.String(128), nullable=False),
    sa.Column("sender", sa.String(128), nullable=False),
    sa.Column("body", sa.Text, nullable=False),
    # pending | consumed | undeliverable
    sa.Column("state", sa.String(16), nullable=False),
    sa.Column("turn_id", sa.String(64)),
    sa.Column("created_at", sa.String(40)),
)

turns = sa.Table(
    "pi_turns", metadata,
    sa.Column("turn_id", sa.String(64), primary_key=True),
    sa.Column("participant_id", sa.String(64), nullable=False, index=True),
    sa.Column("run_id", sa.String(64), nullable=False, index=True),
    sa.Column("turn_no", sa.Integer, nullable=False),
    sa.Column("attempt_id", sa.String(64)),
    sa.Column("state", sa.String(16), nullable=False),
    sa.Column("input_seqs", sa.JSON, nullable=False),
    # The turn's own agent.started event: its model calls and tools hang below it.
    sa.Column("agent_event_id", sa.String(64)),
    sa.Column("model_call_ids", sa.JSON, nullable=False),
    # none (prompt not sent) | intent (sent: the model may have acted) | committed (settled)
    sa.Column("effect_state", sa.String(16), nullable=False),
    sa.Column("output", sa.Text),
    sa.Column("error", sa.Text),
    # The worker box's receipt: container, exit, teardown, handoff and tunnel counts. No tokens.
    sa.Column("worker", sa.JSON),
    sa.Column("started_at", sa.String(40)),
    sa.Column("ended_at", sa.String(40)),
)

waits = sa.Table(
    "pi_waits", metadata,
    sa.Column("wait_id", sa.String(64), primary_key=True),
    sa.Column("run_id", sa.String(64), nullable=False, index=True),
    sa.Column("host_path", sa.String(255), nullable=False),
    sa.Column("kind", sa.String(16), nullable=False),
    sa.Column("gate_name", sa.String(255), nullable=False),
    # Pre-assigned, so a crash between writing the wait and recording its event can never
    # produce a second event for the same wait.
    sa.Column("event_id", sa.String(64), nullable=False),
    # open | decided | cancelled
    sa.Column("state", sa.String(16), nullable=False),
    sa.Column("subject", sa.JSON),
    sa.Column("decision", sa.JSON),
    sa.Column("opened_attempt", sa.String(64)),
    sa.Column("decided_attempt", sa.String(64)),
    sa.Column("opened_at", sa.String(40)),
    sa.Column("decided_at", sa.String(40)),
    sa.Column("event_recorded", sa.Boolean, nullable=False, default=False),
)

TABLES = (participants, messages, turns, waits)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def _new_id() -> str:
    return uuid.uuid4().hex


def gate_name_for(host_path: str, wait_id: str) -> str:
    """A gate name no other wait can share: a stale approval of an old wait finds nothing."""
    return f"{host_path}~wait-{wait_id[:12]}"


class Ledger:
    """All reads and writes of the four tables. Bound to one SQLAlchemy engine."""

    def __init__(self, engine: sa.Engine):
        self.engine = engine

    def ensure(self) -> None:
        with _LOCK:
            metadata.create_all(self.engine, checkfirst=True)

    def _tx(self):
        return self.engine.begin()

    # --- participants ---------------------------------------------------------------

    def attach_participant(self, run_id: str, host_path: str, role: str, *, session_root: str,
                           pin: dict, attempt_id: str) -> tuple[dict, bool]:
        """The participant for this role, created on first attach only. Returns (row, created).

        A new participant gets a new Pi session id and its own folder under ``session_root``."""
        with _LOCK, self._tx() as conn:
            row = conn.execute(sa.select(participants).where(
                participants.c.run_id == run_id, participants.c.host_path == host_path,
                participants.c.role == role)).mappings().first()
            if row is not None:
                return dict(row), False
            pid = _new_id()
            values = {
                "participant_id": pid, "run_id": run_id, "host_path": host_path, "role": role,
                "state": "idle", "session_id": str(uuid.uuid4()),
                "session_dir": f"{session_root.rstrip('/')}/{pid}/sessions", "pin": dict(pin),
                "turns": 0, "retire_requested": False, "created_attempt": attempt_id,
                "created_at": _now(), "retired_at": None,
            }
            conn.execute(participants.insert().values(**values))
            return values, True

    def participants_of(self, run_id: str, host_path: str) -> list[dict]:
        with _LOCK, self._tx() as conn:
            rows = conn.execute(sa.select(participants).where(
                participants.c.run_id == run_id, participants.c.host_path == host_path,
            ).order_by(participants.c.created_at)).mappings().all()
            return [dict(r) for r in rows]

    def participant(self, participant_id: str) -> dict | None:
        with _LOCK, self._tx() as conn:
            row = conn.execute(sa.select(participants).where(
                participants.c.participant_id == participant_id)).mappings().first()
            return dict(row) if row else None

    def set_participant_state(self, participant_id: str, state: str) -> None:
        with _LOCK, self._tx() as conn:
            conn.execute(participants.update().where(
                participants.c.participant_id == participant_id).values(state=state))

    # --- messages -------------------------------------------------------------------

    def post(self, run_id: str, host_path: str, to_role: str, sender: str, body: str,
             dedupe_key: str | None = None, conn: Any = None) -> dict:
        """Queue a message for a role. Idempotent by ``dedupe_key``. A message to a retired or
        unknown role is kept, marked ``undeliverable`` -- never silently dropped."""
        if conn is None:
            with _LOCK, self._tx() as c:
                return self.post(run_id, host_path, to_role, sender, body, dedupe_key, conn=c)
        if dedupe_key is not None:
            existing = conn.execute(sa.select(messages).where(
                messages.c.dedupe_key == dedupe_key)).mappings().first()
            if existing is not None:
                return {**dict(existing), "duplicate": True}
        target = conn.execute(sa.select(participants).where(
            participants.c.run_id == run_id, participants.c.host_path == host_path,
            participants.c.role == to_role)).mappings().first()
        if target is None or target["state"] == "retired":
            state, pid = "undeliverable", (target["participant_id"] if target else None)
        else:
            state, pid = "pending", target["participant_id"]
        values = {
            "message_id": _new_id(), "dedupe_key": dedupe_key, "run_id": run_id,
            "host_path": host_path, "to_participant": pid, "to_role": to_role, "sender": sender,
            "body": body, "state": state, "turn_id": None, "created_at": _now(),
        }
        seq = conn.execute(messages.insert().values(**values)).inserted_primary_key[0]
        return {**values, "seq": seq, "duplicate": False}

    def messages_by_seq(self, seqs: list[int]) -> list[dict]:
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

    def runnable(self, run_id: str, host_path: str) -> list[tuple[str, int]]:
        """Idle participants with pending messages, oldest waiting message first (FIFO)."""
        with _LOCK, self._tx() as conn:
            rows = conn.execute(
                sa.select(participants.c.participant_id, sa.func.min(messages.c.seq))
                .join(messages, messages.c.to_participant == participants.c.participant_id)
                .where(participants.c.run_id == run_id, participants.c.host_path == host_path,
                       participants.c.state == "idle", messages.c.state == "pending")
                .group_by(participants.c.participant_id)
                .order_by(sa.func.min(messages.c.seq)),
            ).all()
            return [(r[0], r[1]) for r in rows]

    # --- turns ----------------------------------------------------------------------

    def start_turn(self, participant_id: str, attempt_id: str) -> tuple[dict, list[dict]] | None:
        """Claim every pending message of an idle participant as one ordered batch."""
        with _LOCK, self._tx() as conn:
            p = conn.execute(sa.select(participants).where(
                participants.c.participant_id == participant_id)).mappings().first()
            if p is None or p["state"] != "idle":
                return None
            # No turn starts while the owner is being asked something.
            if conn.execute(sa.select(sa.func.count()).select_from(waits).where(
                    waits.c.run_id == p["run_id"], waits.c.host_path == p["host_path"],
                    waits.c.state == "open")).scalar_one():
                return None
            batch = [dict(r) for r in conn.execute(sa.select(messages).where(
                messages.c.to_participant == participant_id, messages.c.state == "pending",
            ).order_by(messages.c.seq)).mappings().all()]
            if not batch:
                return None
            # Numbered after every turn the participant ever started (failed, uncertain,
            # accepted and superseded ones included), not after its completed turns: a turn
            # that follows a failed one must never take that turn's number again.
            last_no = conn.execute(sa.select(sa.func.max(turns.c.turn_no)).where(
                turns.c.participant_id == participant_id)).scalar()
            turn = {
                "turn_id": _new_id(), "participant_id": participant_id, "run_id": p["run_id"],
                "turn_no": (last_no or 0) + 1, "attempt_id": attempt_id, "state": "running",
                "input_seqs": [m["seq"] for m in batch], "agent_event_id": None,
                "model_call_ids": [], "effect_state": "none", "output": None, "error": None,
                "worker": None, "started_at": _now(), "ended_at": None,
            }
            conn.execute(turns.insert().values(**turn))
            conn.execute(messages.update().where(
                messages.c.seq.in_(turn["input_seqs"])).values(state="consumed",
                                                              turn_id=turn["turn_id"]))
            conn.execute(participants.update().where(
                participants.c.participant_id == participant_id).values(state="running"))
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

    def set_turn_agent_event(self, turn_id: str, agent_event_id: str) -> None:
        with _LOCK, self._tx() as conn:
            conn.execute(turns.update().where(turns.c.turn_id == turn_id).values(
                agent_event_id=agent_event_id))

    def mark_effect(self, turn_id: str, effect_state: str) -> None:
        with _LOCK, self._tx() as conn:
            conn.execute(turns.update().where(turns.c.turn_id == turn_id).values(
                effect_state=effect_state))

    def finish_turn(self, turn_id: str, *, output: str, model_call_ids: list[str],
                    worker: dict | None, ask_owner: dict | None, attempt_id: str,
                    retire: bool = False) -> dict:
        """Complete a turn: the participant idle (or retired) and, when ``ask_owner`` is given
        (``{"question", "options"}``), the owner wait that follows it -- in one transaction."""
        with _LOCK, self._tx() as conn:
            t = conn.execute(sa.select(turns).where(turns.c.turn_id == turn_id)).mappings().first()
            p = conn.execute(sa.select(participants).where(
                participants.c.participant_id == t["participant_id"])).mappings().first()
            conn.execute(turns.update().where(turns.c.turn_id == turn_id).values(
                state="completed", output=output, model_call_ids=list(model_call_ids),
                effect_state="committed", worker=worker, ended_at=_now()))
            arrived_meanwhile = conn.execute(sa.select(sa.func.count()).select_from(messages).where(
                messages.c.to_participant == p["participant_id"],
                messages.c.state == "pending")).scalar_one()
            # Retirement only with an empty inbox: a message that arrived meanwhile is
            # answered first (the retirement is deferred), never dropped.
            retired = bool(retire) and arrived_meanwhile == 0
            conn.execute(participants.update().where(
                participants.c.participant_id == p["participant_id"]).values(
                state="retired" if retired else "idle", turns=p["turns"] + 1,
                retire_requested=bool(retire) and not retired,
                retired_at=_now() if retired else None))
            wait = None
            if ask_owner and not retired:
                wait = self._open_wait(conn, p["run_id"], p["host_path"], "owner", {
                    "participant_id": p["participant_id"], "role": p["role"],
                    "turn_id": turn_id, "turn_no": t["turn_no"], **ask_owner}, attempt_id)
            return {"retired": retired, "arrived_meanwhile": arrived_meanwhile, "wait": wait}

    def fail_turn(self, turn_id: str, error: str, model_call_ids: list[str],
                  worker: dict | None = None) -> None:
        """A turn that failed visibly: the participant waits for a recovery decision."""
        with _LOCK, self._tx() as conn:
            t = conn.execute(sa.select(turns).where(turns.c.turn_id == turn_id)).mappings().first()
            conn.execute(turns.update().where(turns.c.turn_id == turn_id).values(
                state="failed", error=error, model_call_ids=list(model_call_ids), worker=worker,
                ended_at=_now()))
            conn.execute(participants.update().where(
                participants.c.participant_id == t["participant_id"]).values(state="failed"))

    def hold_turn(self, turn_id: str, error: str, model_call_ids: list[str],
                  worker: dict | None, attempt_id: str) -> dict:
        """A turn whose effects are unknown (worker gone, disk error, a tool never ended): it
        becomes ``uncertain`` and an owner recovery wait opens -- never a blind re-run."""
        with _LOCK, self._tx() as conn:
            conn.execute(turns.update().where(turns.c.turn_id == turn_id).values(
                error=error, model_call_ids=list(model_call_ids), worker=worker))
        turn = self.turn(turn_id)
        assert turn is not None
        return self.mark_uncertain(turn, attempt_id, why=error)

    def interrupted_turns(self, run_id: str, host_path: str) -> list[dict]:
        """Turns still ``running`` in the ledger: their attempt died under them."""
        with _LOCK, self._tx() as conn:
            rows = conn.execute(sa.select(turns).join(
                participants, participants.c.participant_id == turns.c.participant_id).where(
                participants.c.run_id == run_id, participants.c.host_path == host_path,
                turns.c.state == "running").order_by(turns.c.started_at)).mappings().all()
            return [dict(r) for r in rows]

    def mark_uncertain(self, turn: dict, attempt_id: str, why: str | None = None) -> dict:
        """No blind retry: the turn becomes ``uncertain`` and an owner recovery wait opens."""
        with _LOCK, self._tx() as conn:
            conn.execute(turns.update().where(turns.c.turn_id == turn["turn_id"]).values(
                state="uncertain", ended_at=_now()))
            p = conn.execute(sa.select(participants).where(
                participants.c.participant_id == turn["participant_id"])).mappings().first()
            conn.execute(participants.update().where(
                participants.c.participant_id == turn["participant_id"]).values(state="uncertain"))
            effect = turn["effect_state"]
            did = ("nothing was sent to the model" if effect == "none" else
                   "the model may have acted (its prompt was sent)")
            return self._open_wait(conn, p["run_id"], p["host_path"], "recovery", {
                "participant_id": p["participant_id"], "role": p["role"],
                "turn_id": turn["turn_id"], "turn_no": turn["turn_no"], "effect_state": effect,
                "input_seqs": turn["input_seqs"], "why": why or "cut off",
                "question": (f"{p['role']}'s turn {turn['turn_no']} did not finish "
                             f"({why or 'cut off'}); {did}. Reply 'accept' to keep what it did "
                             "without running it again, or 'retry' to send its messages again."),
                "options": ["accept", "retry"],
            }, attempt_id)

    def open_recovery_for_failed(self, run_id: str, host_path: str, attempt_id: str) -> list[dict]:
        """On a resume after a failure: each failed participant's last failed turn gets an
        owner recovery wait (accept and go on / retry it), never an automatic re-run."""
        with _LOCK, self._tx() as conn:
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
                opened.append(self._open_wait(conn, run_id, host_path, "recovery", {
                    "participant_id": p["participant_id"], "role": p["role"],
                    "turn_id": t["turn_id"], "turn_no": t["turn_no"],
                    "effect_state": t["effect_state"], "input_seqs": t["input_seqs"],
                    "why": "failed",
                    "question": (f"{p['role']}'s turn {t['turn_no']} failed: "
                                 f"{(t['error'] or '')[:300]}. Reply 'accept' to go on without "
                                 "running it again, or 'retry' to send its messages again."),
                    "options": ["accept", "retry"],
                }, attempt_id))
            return opened

    # --- waits ----------------------------------------------------------------------

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
        with _LOCK, self._tx() as conn:
            return self._open_wait(conn, run_id, host_path, kind, subject, attempt_id)

    def open_waits(self, run_id: str, host_path: str) -> list[dict]:
        with _LOCK, self._tx() as conn:
            rows = conn.execute(sa.select(waits).where(
                waits.c.run_id == run_id, waits.c.host_path == host_path,
                waits.c.state == "open").order_by(waits.c.opened_at)).mappings().all()
            return [dict(r) for r in rows]

    def mark_event_recorded(self, wait_id: str) -> None:
        with _LOCK, self._tx() as conn:
            conn.execute(waits.update().where(waits.c.wait_id == wait_id).values(
                event_recorded=True))

    def decide_wait(self, wait_id: str, decision: dict, attempt_id: str,
                    deliveries: Sequence[tuple[str, str, str]] = (),
                    turn_state: tuple[str, str] | None = None,
                    participant_states: Sequence[tuple[str, str]] = ()) -> bool:
        """Compare-and-set open -> decided, with everything the decision does, exactly once.

        ``deliveries``: (to_role, sender, body). ``turn_state``: (turn_id, new state).
        ``participant_states``: (participant_id, new state)."""
        with _LOCK, self._tx() as conn:
            w = conn.execute(sa.select(waits).where(waits.c.wait_id == wait_id)).mappings().first()
            changed = conn.execute(waits.update().where(
                waits.c.wait_id == wait_id, waits.c.state == "open").values(
                state="decided", decision=decision, decided_attempt=attempt_id,
                decided_at=_now())).rowcount
            if changed != 1:
                return False
            if turn_state is not None:
                conn.execute(turns.update().where(turns.c.turn_id == turn_state[0]).values(
                    state=turn_state[1]))
            for pid, state in participant_states:
                values: dict[str, Any] = {"state": state}
                if state == "retired":
                    values["retired_at"] = _now()
                conn.execute(participants.update().where(
                    participants.c.participant_id == pid).values(**values))
            for i, (to_role, sender, body) in enumerate(deliveries):
                self.post(w["run_id"], w["host_path"], to_role, sender, body,
                          dedupe_key=f"{wait_id}:decision:{i}", conn=conn)
            return True

    def cancel_open_waits(self, run_id: str, host_path: str, attempt_id: str,
                          why: str) -> list[dict]:
        with _LOCK, self._tx() as conn:
            rows = [dict(r) for r in conn.execute(sa.select(waits).where(
                waits.c.run_id == run_id, waits.c.host_path == host_path,
                waits.c.state == "open")).mappings().all()]
            for w in rows:
                conn.execute(waits.update().where(
                    waits.c.wait_id == w["wait_id"], waits.c.state == "open").values(
                    state="cancelled", decision={"cancelled": why},
                    decided_attempt=attempt_id, decided_at=_now()))
            return rows

    # --- reading everything back (evidence) ------------------------------------------

    def snapshot(self, run_id: str) -> dict[str, list[dict]]:
        with _LOCK, self._tx() as conn:
            out = {}
            for name, table, order in (
                ("participants", participants, participants.c.created_at),
                ("messages", messages, messages.c.seq),
                ("turns", turns, turns.c.started_at),
                ("waits", waits, waits.c.opened_at),
            ):
                out[name] = [dict(r) for r in conn.execute(
                    sa.select(table).where(table.c.run_id == run_id).order_by(order)).mappings()]
            return out
