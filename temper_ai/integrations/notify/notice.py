"""The shapes the notify layer hands to each place it sends to.

A *notice* is one occasion (a question waiting, a run gone quiet, a run
that ended); a *copy* is that notice in one place; a *decision* is how a
question was answered. A *sender* knows one kind of place (Slack,
Telegram) and turns notices into its own messages.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


@dataclass
class Notice:
    kind: str                       # question | stuck | failed | finished
    execution_id: str
    workflow: str = ""
    url: str = ""
    # question
    node: str = ""
    event_id: str = ""
    upstream: list[dict[str, Any]] = field(default_factory=list)
    questions: list[dict[str, Any]] = field(default_factory=list)
    nudged_after_min: int = 0       # sent again elsewhere: nobody answered for this long
    # failed / finished: the run's summary (TemperOps.summary)
    summary: dict[str, Any] = field(default_factory=dict)
    stopped_by: str = ""            # "Stopped in Telegram by Shine"
    # stuck
    status: str = ""
    idle_min: int = 0
    last_at: str = ""
    active_nodes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Copy:
    """A snapshot of one ``notify_copies`` row."""

    id: int
    key: str
    kind: str
    execution_id: str
    node: str
    event_id: str
    via: str
    target: str
    ref: str
    status: str
    nudge: bool
    state: dict[str, Any]
    created_at: datetime | None = None


@dataclass(frozen=True)
class Decision:
    """How a question was answered, and by whom, wherever that was."""

    verdict: str                    # approved | rejected | resumed | cancelled | ...
    who: str = ""                   # "Shine"
    where: str = ""                 # Slack | Telegram | "" (temper's dashboard or API)
    reason: str = ""
    answers: tuple[tuple[str, str], ...] = ()   # (question, answer) pairs

    @classmethod
    def from_event(cls, decision: dict[str, Any] | None) -> Decision:
        """From a gate event's status and data (``TemperOps.gate_decision``)."""
        data = (decision or {}).get("data") or {}
        verdict = str(data.get("gate_status") or (decision or {}).get("status") or "gone")
        who, where = split_who(str(data.get("gate_decided_by") or ""))
        response = data.get("gate_response") if isinstance(data.get("gate_response"), dict) else {}
        reason = str(response.get("response") or "") if response else ""
        pairs = []
        for a in (response.get("answers") or []) if response else []:
            if isinstance(a, dict):
                chosen = ", ".join(str(s) for s in a.get("selected") or [])
                custom = str(a.get("custom") or "")
                pairs.append((str(a.get("question") or a.get("id") or ""), ", ".join(x for x in (chosen, custom) if x)))
        return cls(verdict=verdict, who=who, where=where, reason=reason, answers=tuple(pairs))

    def line(self) -> str:
        """"Approved by Shine in Telegram" -- plain words, no markup."""
        verb = {"approved": "Approved", "rejected": "Rejected", "resumed": "Approved",
                "cancelled": "Closed: the run was stopped"}.get(self.verdict, f"Closed ({self.verdict})")
        by = f" by {self.who}" if self.who else ""
        place = f" in {self.where}" if self.where else (" in temper" if self.verdict in ("approved", "rejected") else "")
        text = f"{verb}{by}{place}"
        if self.verdict == "rejected":
            text += "; the run is stopped"
        if self.verdict == "resumed":
            text += ", but temper had restarted since this was asked, so the run was resumed; it will ask again"
        return text


def split_who(who: str) -> tuple[str, str]:
    """"Shine (Telegram)" -> ("Shine", "Telegram")."""
    who = who.strip()
    if who.endswith(")") and " (" in who:
        name, _, where = who[:-1].rpartition(" (")
        return name.strip(), where.strip()
    return who, ""


class Sender(Protocol):
    """One kind of place messages can go (Slack, Telegram)."""

    via: str

    def canonical(self, target: str) -> str:
        """The id a place is known by, so one place named two ways is one place."""

    def origins(self, execution_id: str) -> list[str]:
        """Where the run was started from, in this kind of place."""

    def send(self, notice: Notice, target: str, copy: Copy) -> str:
        """Post the notice; returns a ref to the message (for later edits)."""

    def close_question(self, copy: Copy, notice: Notice, decision: Decision) -> None:
        """Take the buttons off an answered question and say who answered."""

    def close_stuck(self, copy: Copy, notice: Notice) -> None:
        """A run that went quiet has ended: take its Stop button off."""
