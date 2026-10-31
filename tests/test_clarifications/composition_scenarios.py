"""Shared synthetic constructors, not a checker, store or composition simulator.

The complete-profile/input builders come from M1, the responder behavior from
M2, the reference constructor from the clarified checker tests. Provider I/O
reuses the existing FakeTelegram. Legacy tests retain their own literal cases
and assertions; F0/F1 are explicit variants, not inferred checker outputs.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from configs.architecture.bin import context_profile_check as v2
from temper_ai.clarifications import contracts as canonical
from tests.test_integrations.conftest import FakeTelegram

BRIEF = "Synthetic brief: a small booking tool for one clinic.\nKeep exact text: café, 東京.\r\n"
BRIEF_SHA = hashlib.sha256(BRIEF.encode("utf-8")).hexdigest()
# Independent literal list, not derived from a validator.
BASE_FIELDS = (
    "maturity.stage", "current_system.state", "external_systems",
    "workload.observed", "workload.projected", "workload.peaks", "performance.targets",
    "reliability.availability", "reliability.data_loss_tolerance", "reliability.recovery_time",
    "privacy.data_categories", "privacy.sensitivity", "privacy.retention", "privacy.sharing",
    "privacy.jurisdictions_or_rules", "security.requirements", "security.threats",
    "security.compliance", "team.size", "team.skills", "team.operating_capacity",
    "budget.build", "budget.run_monthly", "constraints", "goals",
)
COMPOSITION_UNKNOWN = {
    "question": "Must it work offline?", "why_it_matters": "It changes the storage design.",
    "decisions_affected": ["offline storage"], "material": False, "field": "constraints",
}
COMPOSITION_ANSWER = " Yes \n"


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def base_unknown(field: str) -> dict:
    return {
        "question": f"What is the {field} for this synthetic tool?", "why_it_matters": f"It changes the {field} design.",
        "decisions_affected": [f"{field} plan"], "material": False, "field": field,
    }


def profile(*probes: dict, reverse: bool = False, quote: str = "a small booking tool for one clinic") -> dict:
    """M1's complete synthetic v2 candidate, preserving its original fixture."""
    unknowns = [base_unknown(field) for field in BASE_FIELDS] + [copy.deepcopy(probe) for probe in probes]
    if reverse:
        unknowns.reverse()
    return {
        "contract": "context_profile/v2", "brief_sha256": BRIEF_SHA,
        "product": {"summary": "Synthetic booking tool", "source": {"kind": "quote", "quote": quote}},
        "maturity": {"stage": "unknown", "evidence": []}, "current_system": {"state": "unknown", "items": []},
        "external_systems": [], "workload": {"observed": [], "projected": [], "peaks": []},
        "performance": {"targets": []},
        "reliability": {"availability": "unknown", "data_loss_tolerance": "unknown", "recovery_time": "unknown"},
        "privacy": {"data_categories": [], "sensitivity": "unknown", "retention": [], "sharing": [],
                    "jurisdictions_or_rules": []},
        "security": {"requirements": [], "threats": [], "compliance": []},
        "team": {"size": "unknown", "skills": [], "operating_capacity": []},
        "budget": {"build": "unknown", "run_monthly": "unknown"},
        "constraints": [], "goals": [], "assumptions": [], "unknowns": unknowns,
    }


def inputs(candidate, *, revision=0, record=None, ask=(), contracts=canonical, **changes):
    """M1's input factory; canonical by default, explicit module variant for M1."""
    text = candidate if isinstance(candidate, str) else json.dumps(candidate, ensure_ascii=False)
    record_json = record if record is None or isinstance(record, str) else json.dumps(record, ensure_ascii=False)
    fields = {
        "stream": contracts.StreamKey("project:synthetic-clinic", BRIEF_SHA),
        "original_text": BRIEF, "original_sha256": BRIEF_SHA,
        "candidate_json": text, "candidate_sha256": sha(text), "candidate_ref": "candidate:synthetic/1",
        "candidate_brief_sha256": None, "prior_revision": revision, "prior_record_json": record_json,
        "prior_record_sha256": None if record_json is None else sha(record_json),
        "question_ids": tuple(ask), "source_authority_ref": "authority:synthetic/clinic",
        "transport": contracts.TransportNamespace("telegram", "7001"), "chat_id": "-1001",
        "responder_policy_ref": "responder-policy:synthetic/owner-only",
    }
    fields.update(changes)
    return contracts.CallerInput(**fields)


def row(prepared: dict, question_id: str) -> dict:
    return next(item for item in prepared["questions"] if item["question_id"] == question_id)


def receipt_event(caller_input, prepared, question_id, text, message_id, *, disposition="answered",
                  contracts=canonical) -> dict:
    """M1's synthetic M0-validated event builder; not provider/authentication evidence."""
    metadata = row(prepared, question_id)["metadata_sha256"]
    presentation = caller_input.presentation(question_id, metadata, 1)
    copy_id = str(int(message_id) + 100)
    action = contracts.ActionReceipt(
        ingress="provider_pull",
        action=contracts.ActionIdentity(caller_input.transport, caller_input.chat_id, "message", message_id),
        update_id=int(message_id) + 1000, sender_id="5001", sender_is_bot=False, forwarded=False,
        text=text, text_sha256=sha(text),
        binding=contracts.PresentationBinding(
            caller_input.stream.stream_id, question_id, presentation.presentation_id, 1, copy_id,
        ),
        responder=contracts.ResponderDecision(
            caller_input.responder_policy_ref, "5001", "authorised", "responder_policy",
        ),
        intent="answer", disposition=disposition,
    )
    result = contracts.validate_receipt(
        action, presentation=presentation, copies={copy_id}, current_generation=1, question_ids={question_id},
    )
    assert result.status == "accepted"
    return result.event()


class SyntheticResponderPolicy:
    """M2's recording allow/deny fixture, with an explicit set of allowed triples."""

    def __init__(self, allowed: set[tuple[str, str, str]]) -> None:
        self.allowed = set(allowed)
        self.calls: list[tuple[str, str, str]] = []
        self.answer: object = None
        self.fail = False

    def decide(self, *, policy_ref: str, chat_id: str, sender_id: str) -> object:
        self.calls.append((policy_ref, chat_id, sender_id))
        if self.fail:
            raise RuntimeError("the responder policy is down")
        if self.answer is not None:
            return self.answer
        return "authorised" if (policy_ref, chat_id, sender_id) in self.allowed else "denied"


class SyntheticTelegram(FakeTelegram):
    """The existing recording provider with M4's explicit synthetic bot/copy IDs."""

    def __init__(self, *, bot_id: int = 7001, message_ids=(500, 600)) -> None:
        super().__init__()
        self.bot_id = bot_id
        self._ids = iter(message_ids)

    def get_me(self) -> dict:
        return {**super().get_me(), "id": self.bot_id}


def clarification_reference(*, question_id, answer, event_ids, question, source_id):
    """Closed clarified/v1 source shape; values are supplied, never inferred."""
    return {"kind": "clarification", "source_id": source_id, "question_id": question_id,
            "event_ids": list(event_ids), "question": question, "answer": answer}


def clarified_validator():
    """Load the actual shipped clarified/v1 schema, not a same-labelled substitute."""
    path = Path(__file__).resolve().parents[2] / "configs/architecture/stages/context_profile/contract.clarified.v1.schema.json"
    return v2.Validator(json.loads(path.read_text(encoding="utf-8")))


def composition_profile():
    """F0: complete M1 profile plus the plan's one non-material offline unknown."""
    return profile(COMPOSITION_UNKNOWN)


def clarified_candidate(candidate, *, source_mapping, question_id, question, answer, event_ids):
    """F1: supplied exact bindings; no checker-output feedback or guessed event IDs."""
    result = copy.deepcopy(candidate)
    result["contract"] = "context_profile_clarified/v1"
    result["clarification_source"] = {key: source_mapping[key] for key in ("source_id", "record_sha256")}
    result["constraints"] = [{
        "id": "C1", "text": "Must work offline",
        "source": clarification_reference(
            question_id=question_id, answer=answer, event_ids=event_ids,
            question=question, source_id=source_mapping["source_id"],
        ),
    }]
    return result
