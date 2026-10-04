"""A7 policy evaluator: explicit, default-deny, body-blind communication permissions.

Inputs are only a parsed policy snapshot, trusted roster records and a message kind.
Message bodies and agent payloads never reach this module, so text inside a message
cannot change a decision. Every decision names the policy version and rule behind it.

Relationship scope is checked before any rule: a private child talks only with its own
parent (and, as a parent itself, with its own children). Group or role rules can never
open a private child to anyone else.

Ported from A7 (company-lab/pi-agent-proofs/A7/code/a7route/policy.py, sha256 9b64aa87227d...)
unchanged except the import lines (sorted, ``collections.abc``). Temper builds one policy per
team from its communication type: :func:`temper_ai.pi_agent.route.router.all_policy`.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .model import (
    ACTIVE,
    INFO,
    RESERVED_IDS,
    RULE_KINDS,
    WORK_REQUEST,
    ControlError,
    Participant,
)

POLICY_SCHEMA = "a7.policy.v1"
SELECTOR_KEYS = ("participant", "group", "role")
DEFAULT_CHILD_LINK_KINDS = (WORK_REQUEST, INFO)
CHILD_LINK_RULE = "child-link"

PEER = "peer"
PARENT_TO_CHILD = "parent_to_child"
CHILD_TO_PARENT = "child_to_parent"


@dataclass(frozen=True)
class Selector:
    key: str
    value: str

    def matches(self, participant: Participant) -> bool:
        if self.key == "participant":
            return participant.participant_id == self.value
        if self.key == "group":
            return self.value in participant.groups
        return participant.role == self.value


@dataclass(frozen=True)
class Rule:
    rule_id: str
    source: Selector
    target: Selector
    kinds: frozenset[str]


@dataclass(frozen=True)
class Policy:
    run_id: str
    version: int
    rules: tuple[Rule, ...]
    child_link_kinds: frozenset[str]


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str
    policy_version: int
    rule_id: str | None = None

    def safe(self) -> dict:
        return {"allowed": self.allowed, "reason": self.reason, "policy_version": self.policy_version,
                "rule_id": self.rule_id}


def _selector(raw: object) -> Selector:
    if not isinstance(raw, dict) or len(raw) != 1:
        raise ControlError("policy_invalid_selector")
    ((key, value),) = raw.items()
    if key not in SELECTOR_KEYS or not isinstance(value, str) or not value or value.strip() != value:
        raise ControlError("policy_invalid_selector")
    if any(ch in value for ch in "*?[]") or value in RESERVED_IDS:
        raise ControlError("policy_wildcard_forbidden")
    return Selector(key, value)


def _kinds(raw: object, *, allow_empty: bool) -> frozenset[str]:
    if not isinstance(raw, list) or (not raw and not allow_empty):
        raise ControlError("policy_invalid_kinds")
    if any(kind not in RULE_KINDS for kind in raw) or len(set(raw)) != len(raw):
        raise ControlError("policy_invalid_kinds")
    return frozenset(raw)


def parse_policy(run_id: str, version: int, doc: object) -> Policy:
    """Validate a whole policy document; any problem rejects it (no partial policy)."""
    if not isinstance(doc, dict) or doc.get("schema") != POLICY_SCHEMA:
        raise ControlError("policy_invalid_schema")
    if set(doc) - {"schema", "rules", "child_link_kinds"}:
        raise ControlError("policy_unknown_field")
    rules_raw = doc.get("rules", [])
    if not isinstance(rules_raw, list):
        raise ControlError("policy_invalid_rules")
    rules: list[Rule] = []
    seen: set[str] = set()
    for raw in rules_raw:
        if not isinstance(raw, dict) or set(raw) != {"id", "from", "to", "kinds"}:
            raise ControlError("policy_invalid_rule")
        rule_id = raw["id"]
        if not isinstance(rule_id, str) or not rule_id or rule_id in seen or rule_id == CHILD_LINK_RULE:
            raise ControlError("policy_invalid_rule_id")
        seen.add(rule_id)
        rules.append(Rule(rule_id, _selector(raw["from"]), _selector(raw["to"]), _kinds(raw["kinds"], allow_empty=False)))
    child_kinds = _kinds(doc.get("child_link_kinds", list(DEFAULT_CHILD_LINK_KINDS)), allow_empty=True)
    return Policy(run_id, version, tuple(rules), child_kinds)


class PolicyEvaluator:
    """Pure decisions over (policy snapshot, trusted participants, kind). No I/O, no bodies."""

    @staticmethod
    def scope(sender: Participant, recipient: Participant) -> str | None:
        """Relationship between two roster entries, or None when the pair can never communicate."""
        if sender.run_id != recipient.run_id:
            return None
        if sender.status != ACTIVE or recipient.status != ACTIVE:
            return None
        if sender.participant_id == recipient.participant_id:
            return None
        if sender.is_child or recipient.is_child:
            if recipient.parent_id == sender.participant_id:
                return PARENT_TO_CHILD
            if sender.parent_id == recipient.participant_id:
                return CHILD_TO_PARENT
            return None
        return PEER

    @staticmethod
    def edge(policy: Policy, sender: Participant, recipient: Participant, kind: str) -> Decision:
        """May sender originate a message of this kind to recipient right now?"""
        version = policy.version
        if kind not in RULE_KINDS:
            return Decision(False, "kind_not_grantable", version)
        if policy.run_id != sender.run_id or policy.run_id != recipient.run_id:
            return Decision(False, "policy_run_mismatch", version)
        relation = PolicyEvaluator.scope(sender, recipient)
        if relation is None:
            return Decision(False, "out_of_scope", version)
        if relation != PEER:
            if kind in policy.child_link_kinds:
                return Decision(True, relation, version, CHILD_LINK_RULE)
            return Decision(False, "child_link_kind_not_allowed", version)
        for rule in policy.rules:
            if kind in rule.kinds and rule.source.matches(sender) and rule.target.matches(recipient):
                return Decision(True, "rule", version, rule.rule_id)
        return Decision(False, "default_deny", version)

    @staticmethod
    def reply(policy: Policy, replier: Participant, requester: Participant) -> Decision:
        """A reply rides on the original grant: requester -> replier work_request must still hold."""
        version = policy.version
        if PolicyEvaluator.scope(replier, requester) is None:
            return Decision(False, "out_of_scope", version)
        grant = PolicyEvaluator.edge(policy, requester, replier, WORK_REQUEST)
        if not grant.allowed:
            return Decision(False, "request_grant_revoked", version)
        return Decision(True, "reply_to_open_request", version, grant.rule_id)

    @staticmethod
    def allowed_kinds(policy: Policy, sender: Participant, recipient: Participant) -> tuple[str, ...]:
        return tuple(kind for kind in RULE_KINDS if PolicyEvaluator.edge(policy, sender, recipient, kind).allowed)

    @staticmethod
    def visible(policy: Policy, viewer: Participant, target: Participant) -> bool:
        """A target exists for a viewer only if the viewer may originate at least one kind to it."""
        return bool(PolicyEvaluator.allowed_kinds(policy, viewer, target))

    @staticmethod
    def discover(policy: Policy, roster: Mapping[str, Participant], viewer: Participant) -> list[dict]:
        found = []
        for participant_id in sorted(roster):
            target = roster[participant_id]
            kinds = PolicyEvaluator.allowed_kinds(policy, viewer, target)
            if kinds:
                found.append({"participant_id": participant_id, "role": target.role,
                              "relationship": PolicyEvaluator.scope(viewer, target), "allowed_kinds": list(kinds)})
        return found
