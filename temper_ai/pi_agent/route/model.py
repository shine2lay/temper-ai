"""Shared value types and codes for the A7 routing proof (test contract a7.contract.v1).

This is a proof contract, not a frozen production API. It is standard-library only and
holds no I/O: durable storage, worker channels and UI belong to the later integration.

Ported unchanged from A7 (company-lab/pi-agent-proofs/A7/code/a7route/model.py, sha256
16106b5df388...). In Temper the durable storage is the Pi ledger (``pi_messages``) and the
worker channel is the box's team socket (:mod:`temper_ai.pi_agent.route.router`).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

CONTRACT_VERSION = "a7.contract.v1"

WORK_REQUEST = "work_request"  # opens an obligation: the recipient owes the sender a reply
REPLY = "reply"                # closes exactly one open work_request obligation
INFO = "info"                  # FYI: never creates an obligation
KINDS = (WORK_REQUEST, REPLY, INFO)
RULE_KINDS = (WORK_REQUEST, INFO)  # kinds a policy rule may grant; replies are derived
REPLY_OUTCOMES = ("answered", "declined")

ACTIVE = "active"
REMOVED = "removed"

RUN_ACTIVE = "active"
RUN_PAUSED = "paused"
RUN_COMPLETED = "completed"
RUN_CANCELLED = "cancelled"
RUN_ENDED = frozenset({RUN_COMPLETED, RUN_CANCELLED})

# Names agents can never address and the control plane never registers as participants.
RESERVED_IDS = frozenset({
    "owner", "system", "router", "policy", "runtime", "temper", "scheduler", "admin",
    "all", "any", "everyone", "broadcast", "*",
})

ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,62}$")
RUN_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")

# Agent-facing rejection codes. A rejection never carries details about other participants.
UNKNOWN_RECIPIENT = "unknown_recipient"            # nonexistent, hidden, removed, reserved or other-run
ROUTE_DENIED = "route_denied"                      # visible recipient, but this kind/route is not allowed
INVALID_CHANNEL = "invalid_channel"                # unknown, malformed or revoked channel handle
INVALID_MESSAGE = "invalid_message"                # payload shape problem (detail names the field rule)
IDENTITY_CLAIM_MISMATCH = "identity_claim_mismatch"  # payload claimed a sender/run/session it is not
IDEMPOTENCY_CONFLICT = "idempotency_conflict"      # same client_msg_id reused for different content
INVALID_REFERENCE = "invalid_reference"            # in_reply_to/status target not visible to the caller
REPLY_REQUIRES_OPEN_REQUEST = "reply_requires_open_request"
RUN_NOT_ACTIVE = "run_not_active"                  # completed or cancelled run

# Control-plane error codes (owner/runtime API misuse), raised as ControlError.
NOT_AUTHORIZED = "not_authorized"


class ControlError(Exception):
    """Control-plane refusal. Never used to deliver anything to an agent."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Participant:
    """Trusted roster entry. Only the control plane creates or changes one."""

    run_id: str
    participant_id: str
    role: str
    groups: frozenset[str]
    session_id: str
    parent_id: str | None = None  # set only for private children
    status: str = ACTIVE

    @property
    def is_child(self) -> bool:
        return self.parent_id is not None
