"""Temper's router for team messages: what a member may send, to whom (R2 B2, B3, B7).

A7's router (``company-lab/pi-agent-proofs/A7/code/a7route/router.py``) made durable: the
checks run here, in A7's order, and the Pi ledger stores the result in the same transaction
(:meth:`temper_ai.pi_agent.ledger.Ledger.member_send`). Pure functions, no I/O.

* The sender is never read from the payload. Temper knows it from the box binding (the turn
  it gave the box its team socket for); a payload that claims another identity is refused
  (``identity_claim_mismatch``) and audited, one that repeats the true one is ignored.
* Communication type ``all`` only: one generated policy, every member may send
  ``work_request`` and ``info`` to every other member (A7 group rule over the team), and may
  reply to a message it received from another member (R2 B7; ``edges`` is refused at run start
  by the team's pre-run check, and here by :func:`policy_for`).
* Message bodies never reach a decision (A7: body-blind).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from .model import (
    ACTIVE,
    IDENTITY_CLAIM_MISMATCH,
    INFO,
    INVALID_MESSAGE,
    KINDS,
    REMOVED,
    REPLY,
    REPLY_OUTCOMES,
    RESERVED_IDS,
    ROUTE_DENIED,
    UNKNOWN_RECIPIENT,
    WORK_REQUEST,
    ControlError,
    Participant,
)
from .policy import POLICY_SCHEMA, Decision, Policy, PolicyEvaluator, parse_policy

#: The policy every message of this slice is admitted and delivered under.
POLICY_NUMBER = 1
POLICY_VERSION = f"all@{POLICY_NUMBER}"
TEAM_GROUP = "team"
#: A7's payload fields. ``client_msg_id`` is set by the box's send tool from the Pi tool-call
#: id; the model never chooses it.
PAYLOAD_KEYS = frozenset({"to", "kind", "body", "client_msg_id", "in_reply_to", "outcome"})
#: Identity fields a payload may repeat but never change (A7 identity-forged-claims).
IDENTITY_CLAIMS = ("from", "sender", "member", "participant_id", "run_id", "session_id",
                   "turn_id")
MAX_BODY_CHARS = 65536
MAX_CLIENT_ID = 128
MAX_REF = 64


class Refusal(Exception):
    """A send Temper refuses: nothing is stored and no id is used (A7). ``detail`` never names
    another member, so a refusal cannot be used to learn who exists."""

    def __init__(self, code: str, detail: str, *, claims: tuple[str, ...] = ()):
        super().__init__(code)
        self.code = code
        self.detail = detail
        self.claims = claims


@dataclass(frozen=True)
class Send:
    """A send that passed the payload checks: still to be keyed, referenced and routed."""

    kind: str
    to: str | None
    body: str
    client_msg_id: str
    in_reply_to: str | None
    outcome: str | None
    content_sha256: str


def content_digest(kind: str, to: str | None, body: str, in_reply_to: str | None,
                   outcome: str | None) -> str:
    """A7's content digest (R2 B3): same key + same digest is a resend, else a conflict."""
    body_sha = hashlib.sha256(body.encode("utf-8")).hexdigest()
    canon = json.dumps([kind, to, body_sha, in_reply_to, outcome], separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def all_policy(run_id: str) -> Policy:
    """The one policy of communication type ``all``: every member to every other member."""
    return parse_policy(run_id, POLICY_NUMBER, {
        "schema": POLICY_SCHEMA,
        "rules": [{"id": "all", "from": {"group": TEAM_GROUP}, "to": {"group": TEAM_GROUP},
                   "kinds": [WORK_REQUEST, INFO]}],
        "child_link_kinds": [],
    })


def policy_for(communication: str, run_id: str) -> Policy:
    """The router knows ``all`` only (R2 B7); anything else is refused, never guessed."""
    if communication != "all":
        raise ControlError("communication_not_built")
    return all_policy(run_id)


def roster_entry(run_id: str, row: dict) -> Participant:
    """A7's trusted roster entry for a member row: retired or ended members are removed."""
    status = REMOVED if row.get("state") in ("retired", "ended") else ACTIVE
    return Participant(run_id=run_id, participant_id=row["member"], role=row.get("role") or "",
                       groups=frozenset({TEAM_GROUP}), session_id=row.get("session_id") or "",
                       parent_id=None, status=status)


def check_payload(payload: Any, trusted: dict[str, str]) -> Send:
    """A7's payload checks, in A7's order (after the channel check, which the ledger does)."""
    if not isinstance(payload, dict):
        raise Refusal(INVALID_MESSAGE, "the message must be an object")
    unknown = sorted(k for k in payload if k not in PAYLOAD_KEYS and k not in IDENTITY_CLAIMS)
    if unknown:
        raise Refusal(INVALID_MESSAGE, "unknown field(s): " + ", ".join(unknown)[:200])
    forged = tuple(k for k in IDENTITY_CLAIMS
                   if k in payload and str(payload[k]) != str(trusted.get(k, "")))
    if forged:
        raise Refusal(IDENTITY_CLAIM_MISMATCH,
                      "a message cannot say who sent it: Temper fills that in", claims=forged)
    kind = payload.get("kind")
    if kind not in KINDS:
        raise Refusal(INVALID_MESSAGE, "kind must be one of: " + ", ".join(KINDS))
    body = payload.get("body", "")
    if not isinstance(body, str) or len(body) > MAX_BODY_CHARS:
        raise Refusal(INVALID_MESSAGE, f"body must be text of at most {MAX_BODY_CHARS} characters")
    client_msg_id = payload.get("client_msg_id")
    if not isinstance(client_msg_id, str) or not 0 < len(client_msg_id) <= MAX_CLIENT_ID:
        raise Refusal(INVALID_MESSAGE, "client_msg_id is missing")
    ref = payload.get("in_reply_to")
    if ref is not None and (not isinstance(ref, str) or not 0 < len(ref) <= MAX_REF):
        raise Refusal(INVALID_MESSAGE, "in_reply_to must be a message id")
    to = payload.get("to")
    if to is not None and (not isinstance(to, str) or not to.strip()):
        raise Refusal(INVALID_MESSAGE, "to must be a member's name")
    outcome = payload.get("outcome")
    if kind == REPLY:
        outcome = "answered" if outcome is None else outcome
        if outcome not in REPLY_OUTCOMES:
            raise Refusal(INVALID_MESSAGE, "outcome must be answered or declined")
        if ref is None:
            raise Refusal(INVALID_MESSAGE, "a reply needs in_reply_to")
    else:
        if outcome is not None:
            raise Refusal(INVALID_MESSAGE, "only a reply has an outcome")
        if to is None:
            raise Refusal(INVALID_MESSAGE, "to is required")
    return Send(kind=kind, to=to, body=body, client_msg_id=client_msg_id, in_reply_to=ref,
                outcome=outcome, content_sha256=content_digest(kind, to, body, ref, outcome))


def route(policy: Policy, sender: Participant, recipient: Participant | None,
          kind: str) -> Decision:
    """May ``sender`` start a message of ``kind`` to ``recipient``? A reserved, unknown,
    removed or hidden recipient looks the same to the sender: ``unknown_recipient``."""
    if recipient is None or recipient.participant_id in RESERVED_IDS:
        raise Refusal(UNKNOWN_RECIPIENT, "no member you can reach has that name")
    decision = PolicyEvaluator.edge(policy, sender, recipient, kind)
    if decision.allowed:
        return decision
    if PolicyEvaluator.visible(policy, sender, recipient):
        raise Refusal(ROUTE_DENIED, "that kind of message is not allowed to that member")
    raise Refusal(UNKNOWN_RECIPIENT, "no member you can reach has that name")


def route_reply(policy: Policy, replier: Participant, requester: Participant) -> Decision:
    """A reply rides on the original grant (A7): the asker must still be reachable."""
    decision = PolicyEvaluator.reply(policy, replier, requester)
    if decision.allowed:
        return decision
    raise Refusal(UNKNOWN_RECIPIENT, "the member who sent that message can no longer be reached")


def reachable(policy: Policy, sender: Participant, roster: list[Participant]) -> list[str]:
    """Names the sender can message (the send tool's description lists them)."""
    return [p["participant_id"] for p in PolicyEvaluator.discover(
        policy, {r.participant_id: r for r in roster}, sender)]
