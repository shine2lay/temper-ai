"""Pure clarification history, separate from the frozen context_profile/v2 contract.

No caller, storage, UI, clock, model or runtime integration lives here. Attribution
is supplied by the caller, not authenticated. See context-profile-clarifications.md.
"""

from __future__ import annotations

import hashlib
import json
import math
import re

CONTRACT = "context_profile_clarifications/v1"
FIELDS = (
    "maturity.stage", "current_system.state", "current_system.items", "external_systems",
    "workload.observed", "workload.projected", "workload.peaks", "performance.targets",
    "reliability.availability", "reliability.data_loss_tolerance", "reliability.recovery_time",
    "privacy.data_categories", "privacy.sensitivity", "privacy.retention", "privacy.sharing",
    "privacy.jurisdictions_or_rules", "security.requirements", "security.threats",
    "security.compliance", "team.size", "team.skills", "team.operating_capacity",
    "budget.build", "budget.run_monthly", "constraints", "goals",
)
PROFILE_FIELDS = {
    "contract", "brief_sha256", "product", "maturity", "current_system", "external_systems",
    "workload", "performance", "reliability", "privacy", "security", "team", "budget",
    "constraints", "goals", "unknowns", "assumptions",
}
UNKNOWN_REQUIRED = {"question", "why_it_matters", "decisions_affected", "material"}
EVENT_REQUIRED = {"event_id", "question_id", "kind", "actor", "source"}
HASH_PATTERN = r"[0-9a-f]{64}"
QUESTION_PATTERN = r"q-[0-9a-f]{64}"
EVENT_PATTERN = r"e-[A-Za-z0-9][A-Za-z0-9._:-]*"
REF_PATTERN = r"[A-Za-z][A-Za-z0-9+.-]*:[^\s\x00-\x20\x7f]+"


class ClarificationError(ValueError):
    """An invalid record or ambiguous history operation; input remains unchanged."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ClarificationError(message)


def _json_data(value: object, ancestors: set[int] | None = None) -> None:
    """Reject non-JSON objects, cycles, nonfinite numbers and non-UTF-8 strings."""
    if value is None or type(value) in (bool, int):
        return
    if type(value) is float:
        _require(math.isfinite(value), "nonfinite number")
        return
    if type(value) is str:
        try:
            value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ClarificationError("string is not valid UTF-8") from exc
        return
    _require(type(value) in (dict, list), "expected plain JSON data")
    ancestors = set() if ancestors is None else ancestors
    _require(id(value) not in ancestors, "cyclic data")
    ancestors.add(id(value))
    if type(value) is dict:
        for key, item in value.items():
            _require(type(key) is str, "object keys must be strings")
            _json_data(key, ancestors)
            _json_data(item, ancestors)
    else:
        for item in value:
            _json_data(item, ancestors)
    ancestors.remove(id(value))


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _copy(value: object):
    return json.loads(_canonical(value))


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _object(value: object, required: set[str], optional: set[str] | None = None) -> None:
    _require(type(value) is dict, "expected object")
    _require(required <= value.keys(), "missing required fields")
    _require(value.keys() <= required | (optional or set()), "unknown fields")


def _text(value: object, minimum: int = 1) -> None:
    _require(type(value) is str and len(value) >= minimum and bool(value.strip()), "invalid text")


def _pattern(value: object, pattern: str) -> None:
    _require(type(value) is str and re.fullmatch(pattern, value) is not None, "malformed reference or ID")


def _unknown(value: object) -> None:
    _object(value, UNKNOWN_REQUIRED, {"field"})
    _text(value["question"], 5)
    _text(value["why_it_matters"], 5)
    decisions = value["decisions_affected"]
    _require(type(decisions) is list and bool(decisions), "decisions_affected must be nonempty")
    for decision in decisions:
        _text(decision, 2)
    _require(type(value["material"]) is bool, "material must be boolean")
    if "field" in value:
        _require(value["field"] in FIELDS, "unknown affected field")


def _question_id(brief_sha256: str, unknown: dict) -> str:
    return "q-" + _sha(_canonical({"contract": CONTRACT, "brief_sha256": brief_sha256, "unknown": unknown}))


def derive_questions(profile: dict, original_brief: str) -> list[dict]:
    """Derive exact questions from a caller-validated v2 profile; sort/dedupe by ID.

    The upstream caller still owns full v2 schema/meaning checks. This boundary
    checks its envelope, all unknown metadata and any supplied brief binding.
    IDs bind the exact metadata and UTF-8 brief, not unknowns' array positions.
    """
    _json_data(profile)
    _json_data(original_brief)
    _require(type(original_brief) is str, "original_brief must be text")
    _object(profile, {"contract", "unknowns"}, PROFILE_FIELDS - {"contract", "unknowns"})
    _require(profile["contract"] == "context_profile/v2", "expected context_profile/v2")
    brief_sha256 = _sha(original_brief)
    if "brief_sha256" in profile:
        _pattern(profile["brief_sha256"], HASH_PATTERN)
        _require(profile["brief_sha256"] == brief_sha256, "original brief hash mismatch")
    _require(type(profile["unknowns"]) is list, "unknowns must be an array")
    questions = {}
    for unknown in profile["unknowns"]:
        _unknown(unknown)
        question_id = _question_id(brief_sha256, unknown)
        questions[question_id] = {"question_id": question_id, **_copy(unknown)}
    return [questions[key] for key in sorted(questions)]


def create_record(profile: dict, original_brief: str, *, previous: dict | None = None) -> dict:
    """Start or extend a record; never erase old questions or their events.

    Repeated identical unknowns reuse existing IDs/history, even if reordered.
    Changed metadata creates a new question; this function does not guess that
    it means an old one. A different original brief requires a separate record.
    """
    questions = derive_questions(profile, original_brief)
    record = {"contract": CONTRACT, "brief_sha256": _sha(original_brief), "questions": [], "events": []}
    if previous is not None:
        validate_record(previous)
        _require(previous["brief_sha256"] == record["brief_sha256"], "original brief hash mismatch")
        record = _copy(previous)
    by_id = {question["question_id"]: question for question in record["questions"]}
    by_id.update({question["question_id"]: question for question in questions})
    record["questions"] = [by_id[key] for key in sorted(by_id)]
    return record


def _event_shape(event: object) -> None:
    _require(type(event) is dict, "expected event object")
    if event.get("kind") == "answer":
        _object(event, EVENT_REQUIRED | {"answer", "disposition", "supersedes"}, {"reason"})
        _text(event["answer"])
        _require(event["disposition"] in ("answered", "deferred", "unknown"), "invalid answer disposition")
        supersedes = event["supersedes"]
        _require(type(supersedes) is list, "supersedes must be an array")
        for target in supersedes:
            _pattern(target, EVENT_PATTERN)
        _require(len(supersedes) == len(set(supersedes)), "duplicate supersession target")
        if supersedes:
            _require("reason" in event, "correction requires a reason")
        if "reason" in event:
            _text(event["reason"])
    elif event.get("kind") == "reopen":
        _object(event, EVENT_REQUIRED | {"reason"})
        _text(event["reason"])
    else:
        raise ClarificationError("unknown event kind")
    _pattern(event["event_id"], EVENT_PATTERN)
    _pattern(event["question_id"], QUESTION_PATTERN)
    _object(event["actor"], {"kind", "ref"})
    _object(event["source"], {"kind", "ref"})
    _pattern(event["actor"]["ref"], REF_PATTERN)
    _pattern(event["source"]["ref"], REF_PATTERN)
    pair = (event["actor"]["kind"], event["source"]["kind"])
    _require(pair in (("human", "human_response"), ("model", "model_output")), "actor/source kind mismatch")
    if event["actor"]["kind"] == "model":
        _require(event["kind"] == "answer" and not event["supersedes"], "model output cannot revise or reopen")


def validate_record(record: dict) -> None:
    """Validate closed shapes, content-bound IDs and ordered reference integrity.

    Identical duplicate events are legal replays; changed content for an event
    ID is refused. Supersession can name only earlier answers to this question.
    This validates caller attribution, not its truth, authority or consent.
    """
    _json_data(record)
    _object(record, {"contract", "brief_sha256", "questions", "events"})
    _require(record["contract"] == CONTRACT, "wrong clarification contract")
    _pattern(record["brief_sha256"], HASH_PATTERN)
    _require(type(record["questions"]) is list, "questions must be an array")
    _require(type(record["events"]) is list, "events must be an array")
    questions = set()
    for question in record["questions"]:
        _object(question, UNKNOWN_REQUIRED | {"question_id"}, {"field"})
        unknown = {key: value for key, value in question.items() if key != "question_id"}
        _unknown(unknown)
        _pattern(question["question_id"], QUESTION_PATTERN)
        _require(question["question_id"] == _question_id(record["brief_sha256"], unknown), "question ID binding mismatch")
        _require(question["question_id"] not in questions, "duplicate question ID")
        questions.add(question["question_id"])
    seen = {}
    for event in record["events"]:
        _event_shape(event)
        event_id = event["event_id"]
        if event_id in seen:
            _require(event == seen[event_id], "event ID reused with changed content")
            continue
        _require(event["question_id"] in questions, "event names missing question")
        for target_id in event.get("supersedes", []):
            _require(target_id in seen, "supersession must name an earlier event")
            target = seen[target_id]
            _require(target["kind"] == "answer", "supersession must name an answer")
            _require(target["question_id"] == event["question_id"], "cross-question supersession")
        seen[event_id] = event


def append_event(record: dict, event: dict) -> dict:
    """Return a new valid record. Replaying an identical ID does not append it."""
    validate_record(record)
    _json_data(event)
    _event_shape(event)
    for previous in record["events"]:
        if previous["event_id"] == event["event_id"]:
            _require(previous == event, "event ID reused with changed content")
            return _copy(record)
    result = _copy(record)
    result["events"].append(_copy(event))
    validate_record(result)
    return result


def _unique_events(record: dict) -> list[dict]:
    # Validation has already refused differing content under one ID.
    return list({event["event_id"]: event for event in record["events"]}.values())


def project_states(record: dict) -> list[dict]:
    """Project current states without interpreting prose or picking a last answer.

    Only human-attributed answers participate. Multiple active answers resolve
    only when every disposition is answered and their exact texts agree.
    Reopening retires earlier answers without deleting them from history.
    """
    validate_record(record)
    events = _unique_events(record)
    states = []
    for question in sorted(record["questions"], key=lambda item: item["question_id"]):
        history = [event for event in events if event["question_id"] == question["question_id"]]
        active = {}
        reopened = False
        for event in history:
            if event["actor"]["kind"] == "model":
                continue
            if event["kind"] == "reopen":
                active.clear()
                reopened = True
            else:
                for target in event["supersedes"]:
                    active.pop(target, None)
                active[event["event_id"]] = event
        dispositions = {event["disposition"] for event in active.values()}
        texts = {event["answer"] for event in active.values()}
        answer = None
        if not active:
            state = "reopened" if reopened else "unanswered"
        elif dispositions == {"answered"} and len(texts) == 1:
            state = "answered"
            answer = next(iter(texts))
        elif dispositions == {"deferred"}:
            state = "deferred"
        elif dispositions == {"unknown"}:
            state = "unknown"
        else:
            state = "conflicting"
        states.append({
            **_copy(question), "state": state, "answer": answer,
            "active_event_ids": list(active),
            "history_event_ids": [event["event_id"] for event in history],
            "model_event_ids": [event["event_id"] for event in history if event["actor"]["kind"] == "model"],
        })
    return states


def compose_supplement(record: dict, original_brief: str) -> dict:
    """Return separate original text, JSON source text and exact source mapping.

    The supplement contains only currently answered human-attributed responses,
    paired with their questions. Other states remain visible in project_states.
    JSON quoting is a data boundary, not a promise against model prompt injection.
    """
    states = project_states(record)
    _json_data(original_brief)
    _require(type(original_brief) is str, "original_brief must be text")
    _require(_sha(original_brief) == record["brief_sha256"], "original brief hash mismatch")
    canonical_record = _copy(record)
    canonical_record["questions"].sort(key=lambda item: item["question_id"])
    canonical_record["events"] = _unique_events(record)
    record_sha256 = _sha(_canonical(canonical_record))
    events = {event["event_id"]: event for event in canonical_record["events"]}
    answers, mapping = [], []
    for state in states:
        if state["state"] != "answered":
            continue
        question = {key: state[key] for key in (*sorted(UNKNOWN_REQUIRED), "question_id")}
        if "field" in state:
            question["field"] = state["field"]
        attributions = [
            {"event_id": event_id, "actor": events[event_id]["actor"], "source": events[event_id]["source"]}
            for event_id in state["active_event_ids"]
        ]
        index = len(answers)
        answers.append({"question": question, "answer": state["answer"], "attributions": attributions})
        mapping.append({
            "question_id": state["question_id"],
            "question_pointer": f"/answers/{index}/question/question",
            "answer_pointer": f"/answers/{index}/answer",
            "attributions_pointer": f"/answers/{index}/attributions",
            "event_ids": state["active_event_ids"],
            **({"field": state["field"]} if "field" in state else {}),
        })
    supplement = _canonical({
        "contract": CONTRACT, "original_brief_sha256": record["brief_sha256"],
        "record_sha256": record_sha256, "answers": answers,
    })
    supplement_sha256 = _sha(supplement)
    return {
        "original_brief": original_brief,
        "supplement": supplement,
        "source_mapping": {
            "source_id": "clarifications-sha256:" + supplement_sha256,
            "supplement_sha256": supplement_sha256,
            "original_brief_sha256": record["brief_sha256"],
            "record_sha256": record_sha256,
            "entries": _copy(mapping),
        },
    }
