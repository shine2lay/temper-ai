"""One account per Pi run, and what an account's refusal or limit does (M4 ADR-M4-09, -14,
-16, -18, -19; SW-53, SW-54, SW-20).

**The run's account.** The Pi lane picks it once, at the run's first claim (runner/pi_lane.py),
from the team settings' ``account_slots`` (:mod:`temper_ai.pi_agent.team_config`), the way the
settings' ``account_pick`` says:

* ``room`` (the default; ADR-M4-18, docs/pi-lane.md) -- by the account-room file ops' writer
  publishes on the host (``account_room_file``, which pi-worker reads through its read-only
  mount): of the slots whose reading is fresh and under 85% of their 5-hour and 90% of their
  7-day use (R-D6), the one with the least 7-day use, ties in the settings' order
  (:func:`read_room`, :func:`pick`). Recorded with the reading it was picked by and the
  file's sha256 and schema version (``by: room``);
* ``settings_order`` (ADR-M4-19, the frozen first trial) -- the first allowed slot in the
  settings' order with **no capacity check** (:func:`pick_by_settings_order`): no file is
  read, no usage is asked and no figure is recorded, so the slot may be near or at its limit.
  Recorded as ``by: settings_order`` with ``capacity: not_checked``.

Either way it is recorded by its slot label on the run's row (``spawner_metadata``
``pi_lane.account``) before any member works, kept for every attempt of the run, and never
swapped for another: a resume, and Continue after a limit, carry on with the same account and
never pick again (nor read the file). Account 1 -- the slot named like the canonical
provider -- is refused by name. Inside a member's box the provider stays the canonical one;
only the host helper sees the slot. Any other ``account_pick``, or ``settings_order`` beside
an ``account_room_file``, picks no account at all: every Pi run is refused, even one with an
account kept, until the settings are fixed (``TeamConfig.account_pick_refusal``).

**How a model call can end** (:func:`call_trouble`), read on the error path only:

* the account refused the call (its organisation doesn't allow it: a 403 ``permission_error``
  / ``oauth_not_allowed_for_organization``, or a call with no model output at all whose whole
  result is the refusal sentence) -> ``refused``: the turn fails red naming the slot and the
  refusal, and the team stops with a plain problem. No wait, no other account, no retry: no
  reset fixes it;
* the account hit a usage limit -> ``limit``: a recovery wait naming the slot, the limit and
  the reset when known; retrying keeps the same account, model and thinking;
* anything else -> None: a failed turn as before (the error is never the answer).

A member's normal answer is never read for these sentences: a member may quote them.
"""

from __future__ import annotations

import errno
import hashlib
import json
import logging
import math
import os
import re
import stat
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from temper_ai.llm.account_messages import DISABLED, LIMIT, account_trouble
from temper_ai.pi_agent.member import usage_limit
from temper_ai.pi_agent.team_config import (
    PICK_BY_SETTINGS_ORDER,
    TeamConfig,
    load_team_config,
    slot_problem,
)
from temper_ai.shared.clock import as_utc, utcnow

logger = logging.getLogger(__name__)

#: R-D6 (L4): a slot may start a run only under these shares of its windows, in percent.
FIVE_HOUR_MAX = 85.0
SEVEN_DAY_MAX = 90.0
#: A slot's reading this old or older doesn't start a run (seconds; ADR-M4-18).
ROOM_MAX_AGE_S = 15 * 60
#: The account-room file this reader knows (the account-room interface, version 1), and the
#: most bytes it reads.
ROOM_SCHEMA_VERSION = 1
ROOM_MAX_BYTES = 64 * 1024
_FILE_FIELDS = frozenset({"schema_version", "slots"})
_ROW_FIELDS = frozenset({"slot", "status", "observed_at", "five_hour", "seven_day", "reason"})
_WINDOW_FIELDS = frozenset({"used_percent", "resets_at"})
_WINDOWS = (("five_hour", "5-hour"), ("seven_day", "7-day"))
#: Why the writer may say a slot is unavailable, in plain words. Any other reason leaves the
#: slot unavailable with no reason given; it doesn't refuse the file.
UNAVAILABLE_REASONS = {
    "signed_out": "signed out",
    "not_subscription": "not signed in with a subscription",
    "sign_in_expired": "its sign-in expired",
    "busy": "busy when it was read",
    "timeout": "its reading timed out",
    "no_answer": "no answer when it was read",
    "incomplete_reading": "its reading was incomplete",
    "check_failed": "its check failed",
    "auth_unreadable": "its login couldn't be read",
    "login_changed": "its login changed",
}
#: Where the run's account is recorded: ``spawner_metadata[pi_lane][account]``.
ACCOUNT_KEY = "account"
#: What a run picked by the settings' order records of its account's capacity: nothing was
#: checked (ADR-M4-19). Never a figure, a snapshot or a reset time.
CAPACITY_NOT_CHECKED = "not_checked"
#: The two ways an account stops a call (:func:`call_trouble`).
REFUSED = "refused"
LIMITED = "limit"
_RESET_RE = re.compile(r"\breset(?:s|ting)?\b(?:\s+(?:at|in|on))?\s*([^;\n]{1,80})", re.IGNORECASE)


class AccountError(Exception):
    """The run's account can't be chosen or kept: the run doesn't start (a plain problem)."""


# --- the account-room file (ADR-M4-18) -------------------------------------------------------

@dataclass(frozen=True)
class Room:
    """One slot's reading: the use of each window in percent, when each resets (None:
    unknown), when it was observed, and -- when the slot can't start a run -- why not, in
    plain words (``unusable``)."""

    slot: str
    five_hour: float | None = None
    seven_day: float | None = None
    five_hour_resets_at: str | None = None
    seven_day_resets_at: str | None = None
    observed_at: str | None = None
    unusable: str | None = None

    def passes(self) -> bool:
        return (self.unusable is None and self.five_hour is not None
                and self.seven_day is not None and self.five_hour < FIVE_HOUR_MAX
                and self.seven_day < SEVEN_DAY_MAX)

    def figures(self) -> dict:
        """What the run records of the reading it was picked by."""
        return {"five_hour": self.five_hour, "seven_day": self.seven_day,
                "five_hour_resets_at": self.five_hour_resets_at,
                "seven_day_resets_at": self.seven_day_resets_at,
                "observed_at": self.observed_at}

    def words(self) -> str:
        """The reading in plain words, with the resets known and why it can't start a run."""
        def window(name: str, used: float | None, resets: str | None) -> str:
            text = f"{name} {'unknown' if used is None else f'{used:g}%'}"
            return f"{text} (resets {resets})" if resets else text

        parts = []
        if self.five_hour is not None or self.seven_day is not None:
            parts.append(f"{window('5 h', self.five_hour, self.five_hour_resets_at)}, "
                         f"{window('7 d', self.seven_day, self.seven_day_resets_at)}")
        why = self.unusable or _over_limits(self.five_hour, self.seven_day)
        if why:
            parts.append(why)
        return f"{self.slot}: {' -- '.join(parts) or 'no reading'}"


@dataclass(frozen=True)
class RoomReading:
    """The account-room file as read once at a run's first claim: each slot's reading,
    judged, and the evidence the run records (the sha256 of the exact bytes read, the schema
    version)."""

    rooms: dict[str, Room]
    sha256: str
    schema_version: int


def _over_limits(five: float | None, seven: float | None) -> str | None:
    over = []
    if five is not None and five >= FIVE_HOUR_MAX:
        over.append(f"5-hour use at or over {FIVE_HOUR_MAX:g}%")
    if seven is not None and seven >= SEVEN_DAY_MAX:
        over.append(f"7-day use at or over {SEVEN_DAY_MAX:g}%")
    return "; ".join(over) or None


def _pct(value: Any) -> float | None:
    """A use figure: a number (not true or false), finite, from 0 to 100; else None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) and 0 <= value <= 100 else None


def _time(value: Any) -> tuple[datetime | None, str | None]:
    """``(time, None)`` for a timezone-aware ISO time, else ``(None, why)``."""
    if not isinstance(value, str) or not value:
        return None, "missing"
    try:
        when = datetime.fromisoformat(value) if len(value) <= 40 else None
    except ValueError:
        when = None
    if when is None:
        return None, "not a time"
    if when.tzinfo is None:
        return None, "without a timezone"
    return as_utc(when), None


def _judge(row: dict, now: datetime) -> Room:
    """One slot's row, judged at ``now`` (account-room interface, "treats one slot as
    unusable")."""
    slot = row["slot"]
    status = row.get("status")
    if status == "unavailable":
        reason = row.get("reason")
        why = UNAVAILABLE_REASONS.get(reason) if isinstance(reason, str) else None
        return Room(slot, unusable=f"unavailable ({why})" if why else "unavailable")
    if status != "ok":
        return Room(slot, unusable="its reading isn't ok")
    problems: list[str] = []
    used: dict[str, float | None] = {}
    resets: dict[str, str | None] = {}
    for key, name in _WINDOWS:
        part = row.get(key)
        part = part if isinstance(part, dict) else {}
        used[key] = _pct(part.get("used_percent"))
        if used[key] is None:
            problems.append(f"its {name} use is missing or not a number from 0 to 100")
        resets[key] = None
        if part.get("resets_at") is not None:
            when, bad = _time(part.get("resets_at"))
            if when is None:
                problems.append(f"its {name} reset time is {bad}")
            else:
                resets[key] = str(part["resets_at"])
                if when <= now:
                    problems.append(f"its {name} window reset since the reading")
    observed, bad = _time(row.get("observed_at"))
    if observed is None:
        problems.append(f"its reading time is {bad}")
    elif observed > now:
        problems.append("its reading time is in the future")
    elif (now - observed).total_seconds() >= ROOM_MAX_AGE_S:
        problems.append(f"its reading is {int((now - observed).total_seconds() // 60)} min old "
                        f"(it must be under {ROOM_MAX_AGE_S // 60} min)")
    over = _over_limits(used["five_hour"], used["seven_day"])
    if over:
        problems.append(over)
    return Room(slot, five_hour=used["five_hour"], seven_day=used["seven_day"],
                five_hour_resets_at=resets["five_hour"],
                seven_day_resets_at=resets["seven_day"],
                observed_at=str(row["observed_at"]) if observed is not None else None,
                unusable="; ".join(problems) or None)


class _DuplicateKey(ValueError):
    pass


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict:
    found: dict[str, Any] = {}
    for key, value in pairs:
        if key in found:
            raise _DuplicateKey(key)
        found[key] = value
    return found


def _file_problem(path: str, why: str) -> AccountError:
    return AccountError(f"the account-room file {path} {why}")


def _room_bytes(path: str) -> bytes:
    """The file's bytes, read once: without following a link, a regular file, at most
    :data:`ROOM_MAX_BYTES`."""
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
    try:
        fd = os.open(path, flags)
    except FileNotFoundError:
        raise _file_problem(path, "is missing") from None
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise _file_problem(path, "is a link") from None
        raise _file_problem(path, f"can't be read ({exc.strerror or type(exc).__name__})") \
            from None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise _file_problem(path, "is not a regular file")
        chunks: list[bytes] = []
        size = 0
        while size <= ROOM_MAX_BYTES:
            chunk = os.read(fd, ROOM_MAX_BYTES + 1 - size)
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
    except OSError as exc:
        raise _file_problem(path, f"can't be read ({exc.strerror or type(exc).__name__})") \
            from None
    finally:
        os.close(fd)
    if size > ROOM_MAX_BYTES:
        raise _file_problem(path, f"is over {ROOM_MAX_BYTES // 1024} KiB")
    return b"".join(chunks)


def read_room(path: str | Path, *, now: datetime | None = None) -> RoomReading:
    """The account-room file (version 1; the account-room interface), read once: every slot's
    row judged at ``now``. Raises :class:`AccountError` naming the file when the whole file
    is refused: missing, unreadable, a link, not a regular file, over 64 KiB, not JSON, a
    duplicate JSON key, another schema version, a field version 1 doesn't list, slots that
    aren't a list, or the same slot twice. A row that can't start a run only makes that slot
    unusable (:class:`Room` ``unusable``). Its words are fixed: they never echo a key or a
    value from the file, which only ops' writer controls (SW-52)."""
    path = str(path)
    raw = _room_bytes(path)
    try:
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_keys)
    except _DuplicateKey:
        raise _file_problem(path, "has a JSON key twice") from None
    except ValueError:  # not UTF-8, not JSON
        raise _file_problem(path, "is not JSON") from None
    if not isinstance(data, dict):
        raise _file_problem(path, "is not a JSON object")
    if set(data) - _FILE_FIELDS:
        raise _file_problem(path, "has a top-level field version 1 doesn't list")
    version = data.get("schema_version")
    if type(version) is not int or version != ROOM_SCHEMA_VERSION:
        raise _file_problem(path, f"has no schema_version {ROOM_SCHEMA_VERSION}")
    rows = data.get("slots")
    if not isinstance(rows, list):
        raise _file_problem(path, "has slots that aren't a list")
    seen: dict[str, dict] = {}
    rows_of: dict[str, int] = {}
    for n, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise _file_problem(path, f"has slot row {n} that isn't an object")
        unlisted = set(row) - _ROW_FIELDS or any(
            set(row[key]) - _WINDOW_FIELDS for key, _name in _WINDOWS
            if isinstance(row.get(key), dict))
        if unlisted:
            raise _file_problem(path, f"has a field version 1 doesn't list in slot row {n}")
        slot = row.get("slot")
        if not isinstance(slot, str) or not slot:
            raise _file_problem(path, f"has slot row {n} without a slot label")
        if slot in seen:
            raise _file_problem(path, f"lists one slot twice (slot rows {rows_of[slot]} "
                                      f"and {n})")
        seen[slot] = row
        rows_of[slot] = n
    when = now or utcnow()
    return RoomReading({slot: _judge(row, when) for slot, row in seen.items()},
                       hashlib.sha256(raw).hexdigest(), version)


def pick(slots: tuple[str, ...] | list[str], rooms: dict[str, Room]) -> Room:
    """Of the allowed slots (never account 1), the one whose reading passes with the least
    7-day use; ties go to the settings' order (ADR-M4-18). Rows for other labels are never
    picked. Raises :class:`AccountError` naming every allowed slot's reading, or why it has
    none, with the resets known, when none passes: the run is then refused at its claim, with
    no wait and no retry."""
    allowed = [slot for slot in slots if not slot_problem(slot)]
    if not allowed:
        raise AccountError("no account slot is allowed for Pi runs (team setting "
                           "account_slots)")
    passing = [(rooms[slot].seven_day, i, rooms[slot]) for i, slot in enumerate(allowed)
               if slot in rooms and rooms[slot].passes()]
    if not passing:
        seen = "; ".join(rooms[slot].words() if slot in rooms else f"{slot}: no reading"
                         for slot in allowed)
        raise AccountError(
            f"no allowed account can start the run (each needs a reading under "
            f"{ROOM_MAX_AGE_S // 60} min old with under {FIVE_HOUR_MAX:g}% of its 5-hour and "
            f"under {SEVEN_DAY_MAX:g}% of its 7-day use): {seen}. Start a new run once an "
            "account has room")
    return min(passing, key=lambda p: (p[0], p[1]))[2]


def pick_by_settings_order(slots: tuple[str, ...] | list[str]) -> str:
    """The first allowed slot (never account 1) in the settings' order: the run's account
    under ``account_pick: settings_order`` (ADR-M4-19). It does **no capacity check**: it
    reads no account-room file and asks nothing about any account's use, so the slot may be
    near or at its limit; a limit then ends a turn like on any account (a recovery wait on
    the same slot). Raises :class:`AccountError` when no slot is allowed."""
    for slot in slots:
        if not slot_problem(slot):
            return slot
    raise AccountError("no account slot is allowed for Pi runs (team setting account_slots)")


# --- the run's account -----------------------------------------------------------------------

def recorded_account(run_row: dict | None) -> dict | None:
    """The account recorded on a run's row (picked by room: ``{slot, picked_at, by, room,
    room_file}``; by the settings' order: ``{slot, picked_at, by, capacity}``), else None."""
    meta = (run_row or {}).get("spawner_metadata") or {}
    from temper_ai.runner.pi_lane import LANE_RECORD_KEY

    account = (meta.get(LANE_RECORD_KEY) or {}).get(ACCOUNT_KEY) if isinstance(meta, dict) \
        else None
    return dict(account) if isinstance(account, dict) and account.get("slot") else None


def choose(run_row: dict, *, config: TeamConfig | None = None,
           read: Callable[..., RoomReading] | None = None,
           now: datetime | None = None, admitted: bool = False) -> dict:
    """The run's account: the one already recorded on its row (every later attempt keeps it,
    if the settings still allow it), else -- at the run's first claim only -- picked now: by
    the account-room file (``account_pick: room``), or the first allowed slot in the
    settings' order with no capacity check (``settings_order``: no file is read, ``read`` is
    never called, and the record says ``capacity: not_checked`` with no figure). A run
    ``admitted`` before (it ran) with no account recorded is refused: a run's account is never
    picked again. Settings whose ``account_pick`` can't be used refuse every run first, even
    one with an account kept, and read nothing. Raises :class:`AccountError`."""
    cfg = config or load_team_config()
    refusal = cfg.account_pick_refusal
    if refusal:
        # first: a bad account_pick never turns into the other way of picking, nor admits
        # a run on the account it kept (Architecture's #75 check, F1)
        raise AccountError(refusal)
    kept = recorded_account(run_row)
    if kept is not None:
        return _keep(kept, cfg)
    if admitted:
        raise AccountError("the run started before but has no account recorded; a run's "
                           "account is picked once, at its first claim, and never again "
                           "(start a new run)")
    if not cfg.account_slots:
        raise AccountError("no account slot is allowed for Pi runs (team setting "
                           "account_slots)")
    if cfg.picks_without_capacity_check:
        # ADR-M4-19: the settings' order, nothing read and no figure recorded or made up
        return {"slot": pick_by_settings_order(cfg.account_slots),
                "picked_at": (now or utcnow()).isoformat(), "by": PICK_BY_SETTINGS_ORDER,
                "capacity": CAPACITY_NOT_CHECKED}
    if not cfg.account_room_file:
        raise AccountError("the Pi lane has no account-room file to pick the run's account "
                           "by (team setting account_room_file)")
    when = now or utcnow()
    reading = (read or read_room)(cfg.account_room_file, now=when)
    room = pick(cfg.account_slots, reading.rooms)
    return {"slot": room.slot, "picked_at": when.isoformat(), "by": "room",
            "room": room.figures(),
            "room_file": {"sha256": reading.sha256, "schema_version": reading.schema_version}}


def _keep(kept: dict, cfg: TeamConfig) -> dict:
    """The run's recorded account, if the settings still allow it; never another one."""
    slot = str(kept["slot"])
    why = slot_problem(slot)
    if why:
        raise AccountError(f"the run's account {slot} can't be used: {why}")
    if slot not in cfg.account_slots:
        raise AccountError(f"the run's account {slot} is no longer allowed (team setting "
                           "account_slots); a run never moves to another account")
    return kept


def settle(execution_id: str, run_row: dict, *, admitted: bool = False,
           config: TeamConfig | None = None, read: Callable[..., RoomReading] | None = None,
           now: datetime | None = None) -> dict:
    """The run's one account, settled at a claim: :func:`choose` on ``run_row``, then -- when
    the row had none -- recorded. The account the database keeps is the run's account: when
    an earlier claim recorded one first (a double claim, a race, a stale ``run_row``), that
    one stands and is checked by the same rules as any recorded account, so a winner the
    settings no longer allow refuses the run; it is never swapped or picked again. Raises
    :class:`AccountError`."""
    cfg = config or load_team_config()
    account = choose(run_row, config=cfg, read=read, now=now, admitted=admitted)
    if recorded_account(run_row) is not None:
        return account
    won = record_account(execution_id, account)
    return account if won == account else _keep(won, cfg)


def record_account(execution_id: str, account: dict) -> dict:
    """Write the run's account on its row (``spawner_metadata`` ``pi_lane.account``), unless
    one is there already: a second claim of the same run (a double claim, a race) gets back
    the account the first recorded, which is never overwritten (ADR-M4-18). Returns the
    run's account."""
    from sqlmodel import select

    from temper_ai.database import get_session
    from temper_ai.runner.models import WorkflowRun
    from temper_ai.runner.pi_lane import LANE_RECORD_KEY

    with get_session() as session:
        row = session.exec(
            select(WorkflowRun).where(WorkflowRun.execution_id == execution_id)
            .with_for_update()).first()
        if row is None:
            raise AccountError(f"run {execution_id} has no row to record its account on")
        meta = dict(row.spawner_metadata or {})
        record = dict(meta.get(LANE_RECORD_KEY) or {})
        kept = record.get(ACCOUNT_KEY)
        if isinstance(kept, dict) and kept.get("slot"):
            logger.info("Pi run %s keeps account %s, recorded by an earlier claim",
                        execution_id, kept.get("slot"))
            return dict(kept)
        record[ACCOUNT_KEY] = dict(account)
        meta[LANE_RECORD_KEY] = record
        row.spawner_metadata = meta
        session.add(row)
    logger.info("Pi run %s uses account %s", execution_id, account.get("slot"))
    return dict(account)


def run_account(execution_id: str) -> dict:
    """The account recorded for the run (``{}`` when none: outside the Pi lane, or a test;
    the box then refuses the login hand-off, ADR-M4-15)."""
    from sqlmodel import select

    from temper_ai.database import get_session
    from temper_ai.runner.models import WorkflowRun

    try:
        with get_session() as session:
            row = session.exec(
                select(WorkflowRun).where(WorkflowRun.execution_id == execution_id)).first()
            meta = dict(row.spawner_metadata or {}) if row is not None else {}
    except Exception:  # noqa: BLE001 - no row is no account: the hand-off is then refused
        logger.warning("Could not read run %s's account", execution_id, exc_info=True)
        return {}
    return recorded_account({"spawner_metadata": meta}) or {}


def run_slot(execution_id: str) -> str:
    """The slot recorded for the run (``""`` when none)."""
    return str(run_account(execution_id).get("slot") or "")


# --- how a model call ended (ADR-M4-16) ------------------------------------------------------

def no_model_output(outcome: Any) -> bool:
    """Whether a turn's model calls produced no output at all: no model reply ended, or none
    wrote a token or asked for a tool."""
    if outcome is None or getattr(outcome, "last_stop", None) is None:
        return True
    tokens = getattr(outcome, "tokens", None) or {}
    return not tokens.get("completion_tokens") and not getattr(outcome, "tool_calls", 0)


def whole_result_refusal(outcome: Any) -> str | None:
    """The refusal sentence, when a turn with no model output at all has it alone as its
    whole result (the Claude CLI's shape; the shared whole-result guard), else None."""
    text = getattr(outcome, "output", "") or ""
    if text and no_model_output(outcome) and account_trouble(text, model_work=False) == DISABLED:
        return text.strip()
    return None


def call_trouble(outcome: Any, error: str | None) -> tuple[str, str] | None:
    """``(REFUSED | LIMITED, the error's words)`` when the account stopped the turn's model
    call, else None. Read on the error path only: the last model reply's own error
    (``outcome.last_error``), and the turn's error (``error``: Pi's, the box's) when no
    model reply produced any output. A member's answer -- whatever it says -- is never read
    here; a turn whose whole result was the refusal alone, with no model output, was made a
    failed turn with that error first (:func:`whole_result_refusal`, turn.py)."""
    texts: list[str] = []
    last_error = getattr(outcome, "last_error", None)
    if last_error:
        texts.append(last_error)
    if error and no_model_output(outcome):
        texts.append(error)
    for text in texts:
        if account_trouble(text, is_error=True) == DISABLED:
            return REFUSED, text
    for text in texts:
        if account_trouble(text, is_error=True) == LIMIT or usage_limit(text):
            return LIMITED, text
    return None


def _short(text: str, limit: int = 300) -> str:
    return " ".join(str(text).split())[:limit]


def refusal_words(slot: str, error: str) -> str:
    """The red turn's words: the slot and the refusal."""
    return (f"account {slot or 'unknown'} refused the call (not allowed for this "
            f"organization): {_short(error, 200)}")


def refusal_problem(slot: str, stopped: str = "the team") -> str:
    """The plain problem the team (or a single Pi step, ``stopped="the step"``) stops with."""
    return (f"account {slot or 'unknown'} refused the call (not allowed for this "
            f"organization); {stopped} was stopped")


def limit_reset(error: str, room: dict | None = None) -> str | None:
    """When the limit resets: from the error's words, else the room figures recorded at the
    run's start (a run picked by the settings' order has none), else None."""
    m = _RESET_RE.search(error or "")
    reset = m.group(1).strip().rstrip(".") if m else None
    if not reset and room:
        reset = room.get("five_hour_resets_at") or room.get("seven_day_resets_at")
        reset = f"{reset} (room figures at the run's start)" if reset else None
    return reset or None


def limit_words(slot: str, error: str, room: dict | None = None) -> str:
    """The recovery wait's reason: the slot, the limit and the reset when known."""
    words = f"account {slot or 'unknown'} hit a usage limit: {_short(error, 200).rstrip('.')}"
    if not _RESET_RE.search(error or ""):  # the limit's own words name the reset otherwise
        reset = limit_reset(error, room)
        words += f"; it resets {reset or 'at a time the provider did not say'}"
    return words + ". Retrying keeps the same account, model and thinking"


FIVE_HOUR = "five_hour"
WEEKLY = "weekly"
#: A free-flowing team's five-hour limit carries on at reset. Anything else -- a weekly or
#: model limit, or words that do not say -- waits and asks the owner before restarting.
_FIVE_HOUR_RE = re.compile(r"\bsession limit\b|\b5[- ]?hour\b|\b5 ?h\b|\bfive[- ]hour\b",
                           re.IGNORECASE)
_WEEKLY_RE = re.compile(r"\bweekly\b|\bweek\b|\b7[- ]?day\b|\bopus\b", re.IGNORECASE)
#: Re-check a limit whose reset time can't be read this long after it was hit.
LIMIT_RECHECK_S = 15 * 60
#: Wait this long past a read reset time before the next turn.
LIMIT_PAD_S = 30
_CLOCK_RE = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b(?:\s*\(([A-Za-z_]+/[A-Za-z_/]+)\))?",
                       re.IGNORECASE)


def limit_kind(error: str | None) -> str:
    """``five_hour`` when the limit's own words name the 5-hour (session) limit and nothing
    weekly; otherwise ``weekly`` (unknown words take the weekly path)."""
    text = error or ""
    if _FIVE_HOUR_RE.search(text) and not _WEEKLY_RE.search(text):
        return FIVE_HOUR
    return WEEKLY


def reset_moment(reset: str | None, *, now: datetime | None = None) -> datetime | None:
    """The reset time the limit's words give (an ISO time, epoch seconds, or a clock time
    like ``3pm (America/Los_Angeles)``, taken as its next occurrence), or None."""
    from zoneinfo import ZoneInfo

    from temper_ai.llm.allowance import _as_moment, reset_in_text

    if not reset:
        return None
    now = _aware(now)
    raw = reset.split(" (room figures", 1)[0].strip()
    seconds = _as_moment(raw) or reset_in_text(raw)
    if seconds is not None:
        return datetime.fromtimestamp(seconds, tz=now.tzinfo)
    m = _CLOCK_RE.search(raw)
    if not m:
        return None
    hour = int(m.group(1)) % 12 + (12 if m.group(3).lower() == "pm" else 0)
    minute = int(m.group(2) or 0)
    if hour > 23 or minute > 59:
        return None
    try:
        zone = ZoneInfo(m.group(4)) if m.group(4) else now.tzinfo
    except Exception:  # noqa: BLE001 - an unknown zone: no time read
        return None
    local = now.astimezone(zone)
    when = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if when <= local:
        from datetime import timedelta

        when += timedelta(days=1)
    return as_utc(when)


def limit_ready(subject: dict, *, now: datetime | None = None) -> bool:
    """Whether the next fresh usage check is due, not permission to restart.
    A missing or unreadable time is never due."""
    try:
        at = as_utc(datetime.fromisoformat(str(subject.get("resumes_at"))))
    except (ValueError, TypeError):
        return False
    return bool(at is not None and (now or utcnow()) >= at)


def limit_resume(details: dict, *, now: datetime | None = None) -> dict:
    """When a team held by a usage limit tries again: ``{kind, resumes_at, how}`` -- the
    read reset time plus a short pad (``how`` ``reset``), or a re-check after
    ``LIMIT_RECHECK_S`` when no time can be read (``how`` ``recheck``)."""
    from datetime import timedelta

    moment = _aware(now)
    kind = limit_kind(details.get("limit"))
    when = reset_moment(details.get("resets"), now=moment)
    if when is not None and when > moment:
        at = when + timedelta(seconds=LIMIT_PAD_S)
        return {"kind": kind, "resumes_at": at.isoformat(), "how": "reset"}
    later = moment + timedelta(seconds=LIMIT_RECHECK_S)
    return {"kind": kind, "resumes_at": later.isoformat(), "how": "recheck"}


def limit_restart_ready(subject: dict, *, now: datetime | None = None) -> bool:
    """Only a fresh available reading, not a timer or an expired sign-in, permits restart."""
    return subject.get("resume_verified") is True and limit_ready(subject, now=now)


def limit_after_check(subject: dict, reading: dict, *, now: datetime | None = None) -> dict:
    """The held team's next state from the helper's fresh, rebuilt usage reading.

    Unavailable readings keep the hold and schedule another check, without an expiry.
    Every reported exhausted window must reset; a weekly window makes the hold weekly
    (never downgrading an already weekly or unknown hold to automatic five-hour resume).
    Once a scoped cap is known, every later check must report that scope, including the
    fresh check of a delayed owner answer. Overall weekly usage is not a substitute.
    """
    from datetime import timedelta

    moment = _aware(now)
    later = moment + timedelta(seconds=LIMIT_RECHECK_S)
    required = {"5h", "7d", *(subject.get("required_windows") or []),
                *(subject.get("blocked_windows") or [])}
    out = {**subject, "usage": dict(reading), "usage_checked_at": moment.isoformat(),
           "resume_verified": False, "resumes_at": later.isoformat(), "how": "recheck",
           "required_windows": sorted(required),
           "blocked_windows": list(subject.get("blocked_windows") or [])}
    if reading.get("status") != "ok":
        return out
    windows = reading.get("windows") or []
    if not required <= {w["key"] for w in windows}:
        out["usage"] = {"status": "unavailable", "reason": "incomplete_reading"}
        return out
    blocked = [w for w in windows if w["used_percent"] >= 100]
    out["blocked_windows"] = [w["key"] for w in blocked]
    out["required_windows"] = sorted(required | {w["key"] for w in blocked})
    if not blocked:
        return {**out, "resume_verified": True, "resumes_at": moment.isoformat(),
                "how": "verified"}
    if any(w["key"].startswith("7d") for w in blocked):
        out["kind"] = WEEKLY
    dates: list[datetime] = []
    unknown = False
    for window in blocked:
        when = reset_moment(window.get("resets_at"), now=moment)
        if when is not None and when > moment:
            dates.append(when + timedelta(seconds=LIMIT_PAD_S))
        else:
            unknown = True
    if dates:
        at = min(max(dates), later) if unknown else max(dates)
        out.update(resumes_at=at.isoformat(), how="recheck" if unknown else "reset")
    return out


def _aware(now: datetime | None) -> datetime:
    """``now`` (or the clock's now) as an aware UTC datetime."""
    got = as_utc(now or utcnow())
    if got is None:  # pragma: no cover - as_utc keeps a datetime a datetime
        raise ValueError("no time")
    return got


def limit_details(slot: str, error: str, room: dict | None = None) -> dict:
    """The limit's fields on its recovery wait (the run view shows them)."""
    return {"account_slot": slot or None, "limit": _short(error, 200),
            "resets": limit_reset(error, room)}


#: How Pi reports a model's own refusal (a safety classifier's stop): the reply ends in an
#: error saying the model refused (Pi's words for the API's ``refusal`` stop when it gives no
#: explanation), naming a classifier or a refusal, or that the provider stopped it as
#: sensitive. A request the API turned down ("400 invalid_request_error: ... refused") is
#: not one: it stays an ordinary failed turn.
_CLASSIFIER_RE = re.compile(r"\bthe model refused\b|\brefusal\b|\bclassifier\b"
                            r"|provider stopped with: ?sensitive", re.IGNORECASE)


def classifier_refusal(outcome: Any) -> str | None:
    """The last model reply's error when the model refused the request (a cyber or safety
    classifier, SW-54), else None. Read on the error path only, after the account's own
    refusal (:func:`call_trouble`) was ruled out."""
    last_error = getattr(outcome, "last_error", None)
    if getattr(outcome, "last_stop", None) == "error" and last_error \
            and _CLASSIFIER_RE.search(last_error):
        return _short(last_error, 200)
    return None


def classifier_words(error: str) -> str:
    """The red turn's words for a model's refusal."""
    return f"the model refused the request (safety classifier): {_short(error, 200)}"


@dataclass(frozen=True)
class Ending:
    """How a turn that did not complete ends. ``refused``: the run's account refused the
    call -- a red turn, and the team (or the step) stops; never a wait, another slot or a
    retry, since no reset fixes it. ``held``: cut off, or a usage limit -- a recovery wait
    (``details``: the limit's slot, words and reset). ``failed``: a red turn."""

    kind: str
    text: str
    details: dict | None = None


def turn_ending(report: Any, slot: str, room: dict | None = None) -> Ending:
    """The mapping for a turn that did not complete (``report``: turn.TurnReport, state
    ``failed`` or ``uncertain``), read on the error path only (ADR-M4-09, ADR-M4-16)."""
    if report.state == "uncertain":
        return Ending("held", report.error or "cut off")
    trouble = call_trouble(report.outcome, report.error)
    if trouble and trouble[0] == REFUSED:
        return Ending("refused", refusal_words(slot, trouble[1]))
    limit = trouble[1] if trouble else (report.error if usage_limit(report.error) else None)
    if limit:
        return Ending("held", limit_words(slot, limit, room), limit_details(slot, limit, room))
    model_refusal = classifier_refusal(report.outcome)
    if model_refusal:
        return Ending("failed", classifier_words(model_refusal))
    return Ending("failed", report.error or "the turn failed")
