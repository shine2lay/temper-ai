"""Requirements preparation for the clarification loop (M1, Temper #205).

Joins pieces that already exist, in one fixed order, and adds no new contract:

1. The input is M0's exact ``CallerInput`` (temper_ai/clarifications/contracts.py),
   which has already refused a missing original or prior record, a missing source
   authority and every hash or binding that does not match.
2. The frozen complete ``context_profile/v2`` checker (``context_profile_check.check``)
   runs first, on the candidate and the exact original text. Any error refuses.
   The #308 foundation's envelope check is not a replacement for it.
3. The record is always ``create_record(candidate, original, previous=<prior record>)``:
   no question or event is ever dropped, and changed metadata is a new question.
4. The display shows every question with its state and history, model suggestions
   apart. Only unresolved questions of the current candidate may be asked.
5. ``compose_supplement`` returns the original text unchanged, the separate
   supplement and the foundation's exact source mapping, bound together.

Public functions do no file, environment, clock, network, subprocess, database,
model or transport access, and store nothing. Loading this module reads two files:
M0's contracts.py (by path, because importing the temper_ai package has side
effects) and the frozen v2 schema. A structural ok is never a judgment of meaning:
meaning_status is always NOT_EVALUATED. See docs/clarifications/caller.md.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

from configs.architecture.bin import context_profile_check as checker
from configs.architecture.bin import context_profile_clarifications as clarifications

FORMAT = "context_profile_clarification_caller/v1"
MEANING_STATUS = "NOT_EVALUATED"
CONTRACTS_PATH = Path(__file__).resolve().parents[3] / "temper_ai" / "clarifications" / "contracts.py"


def _load_contracts_by_path():
    """M0's pure contracts.py as its own module object; never imports temper_ai."""
    spec = importlib.util.spec_from_file_location("context_profile_clarification_contracts", CONTRACTS_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Build every CallerInput with this module's `contracts`: M0's types are exact, so a
# CallerInput from another load of contracts.py is refused (guard caller.type).
contracts = _load_contracts_by_path()
VALIDATOR = checker.load_validator()


class CallerRefusal(clarifications.ClarificationError):
    """A refused preparation or composition: nothing was built, asked or composed.

    guard: the literal label of the check that refused. errors: the frozen v2
    checker's diagnostics when it refused, else empty. meaning_status stays
    NOT_EVALUATED: a refusal judges no meaning. A prior record the #308 foundation
    finds invalid is refused by the foundation's own ClarificationError, passed
    through unchanged.
    """

    meaning_status = MEANING_STATUS

    def __init__(self, guard: str, message: str, errors: tuple[dict, ...] = ()) -> None:
        super().__init__(f"{message} [{guard}]")
        self.guard = guard
        self.errors = errors


def _refuse_unless(ok: bool, guard: str, message: str, errors: tuple[dict, ...] = ()) -> None:
    """The one guard primitive. Each call site has its own literal guard label."""
    if not ok:
        raise CallerRefusal(guard, message, errors)


def _json_text(value: object) -> str:
    """The foundation's canonical JSON form (sorted keys, no spaces, exact Unicode)."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _fresh(value: object):
    """A plain-JSON copy, so no returned container aliases another."""
    return json.loads(_json_text(value))


def _check_with_schema_error_recovery(candidate: dict, caller: contracts.CallerInput) -> dict:
    """Complete check first; recover only TypeError with real schema-invalid evidence.

    The frozen checker can reach set/map operations after finding schema errors
    (unhashable unknown fields or constraint/goal IDs). Reuse its validator to
    recover those diagnostics, not a successful or completed semantic check.
    Schema-valid TypeError and every other exception remain internal failures.
    """
    try:
        return checker.check(candidate, caller.original_text, caller.original_sha256, VALIDATOR)
    except TypeError:
        schema_errors = VALIDATOR.errors(candidate)
        if not schema_errors:
            raise
        # Adapt the validator's tuples to the checker's existing diagnostic shape;
        # no quote, identity, rank or other semantic checking is reproduced here.
        return {
            "ok": False,
            "errors": [
                {"reason": ("missing_section" if keyword == "required" and path == "$"
                            else "bad_enum" if keyword == "enum" else "schema"),
                 "path": path, "detail": detail}
                for keyword, path, detail in schema_errors
            ],
            "counts": {},
        }


def _checked_input(caller: object) -> tuple[dict, dict | None, dict]:
    """M0's exact input type, then the complete v2 checker, before any record work."""
    _refuse_unless(
        type(caller) is contracts.CallerInput, "caller.type",
        "expected a CallerInput built with this module's contracts",
    )
    candidate = caller.candidate()
    report = _check_with_schema_error_recovery(candidate, caller)
    _refuse_unless(
        report["ok"], "candidate.complete",
        f"candidate {caller.candidate_ref} is not a complete context_profile/v2 profile of this original text",
        tuple(dict(error) for error in report["errors"]),
    )
    return candidate, caller.prior_record(), report


def _current_question_ids(candidate: dict, original: str) -> set[str]:
    return {question["question_id"] for question in clarifications.derive_questions(candidate, original)}


def _shown(event: dict) -> dict:
    return {key: event[key] for key in ("event_id", "disposition", "answer", "actor", "source")}


def _display(record: dict, current: set[str], before: set[str]) -> list[dict]:
    """One row per record question: metadata, state, events and what changed."""
    questions = {question["question_id"]: question for question in record["questions"]}
    events = {event["event_id"]: event for event in record["events"]}
    rows = []
    for state in clarifications.project_states(record):
        question_id = state["question_id"]
        unknown = {key: value for key, value in questions[question_id].items() if key != "question_id"}
        if question_id not in before:
            change = "new"
        elif question_id in current:
            change = "repeated"
        else:
            change = "absent"
        rows.append({
            **unknown,
            "question_id": question_id,
            "metadata_sha256": contracts.metadata_sha256(unknown),
            "change": change,
            "state": state["state"],
            "resolved": state["state"] == "answered",
            "answer": state["answer"],
            "active": [_shown(events[event_id]) for event_id in state["active_event_ids"]],
            "active_event_ids": state["active_event_ids"],
            "history_event_ids": state["history_event_ids"],
            "model_suggestions": [_shown(events[event_id]) for event_id in state["model_event_ids"]],
        })
    return rows


def prepare(caller: contracts.CallerInput) -> dict:
    """Build or extend the record for one candidate and show what is unresolved.

    The record is create_record(candidate, original, previous=<the prior record>):
    exact repeated or reordered metadata keeps its question ID and history; changed
    metadata is a new question, and the old one keeps its history. Nothing is mapped
    across, rephrased or asked again once answered. The record comes back as
    canonical JSON for the store's compare-and-set at expected_revision; nothing is
    stored here. ask is the caller's selection, refused unless every selected
    question is an unresolved question of this candidate.
    """
    candidate, previous, report = _checked_input(caller)
    record = clarifications.create_record(candidate, caller.original_text, previous=previous)
    current = _current_question_ids(candidate, caller.original_text)
    before = set() if previous is None else {question["question_id"] for question in previous["questions"]}
    rows = _display(record, current, before)
    resolved = {row["question_id"] for row in rows if row["resolved"]}
    for question_id in caller.question_ids:
        _refuse_unless(
            question_id in current, "ask.current",
            f"{question_id} is not a question of this candidate (unknown, changed or dropped): ask a current one",
        )
        _refuse_unless(
            question_id not in resolved, "ask.unresolved",
            f"{question_id} is already answered: its answer is shown, it is not asked again",
        )
    record_json = _json_text(record)
    return _fresh({
        "format": FORMAT,
        "meaning_status": MEANING_STATUS,
        "stream_id": caller.stream.stream_id,
        "original_sha256": caller.original_sha256,
        "candidate_ref": caller.candidate_ref,
        "candidate_sha256": caller.candidate_sha256,
        "structural_check": {"ok": True, "counts": report["counts"]},
        "expected_revision": caller.prior_revision,
        "prior_record_sha256": caller.prior_record_sha256,
        "record_json": record_json,
        "record_json_sha256": _sha256(record_json),
        "questions": rows,
        "unresolved_question_ids": [row["question_id"] for row in rows if not row["resolved"]],
        "ask": list(caller.question_ids),
        "affected_decisions": list(caller.affected_decisions),
    })


def compose_supplement(caller: contracts.CallerInput) -> dict:
    """The original text unchanged, the separate supplement and its exact mapping.

    Needs the committed prior record (revision 1 or later), holding every question
    of this candidate. Only current human answers enter the supplement (the #308
    foundation's rule); every other state stays listed in unresolved_questions.
    Original, record and supplement keep three separate identities, and the
    consumption ID binds stream, revision and supplement. Nothing is concatenated,
    padded or rewritten, and meaning stays NOT_EVALUATED.
    """
    candidate, record, _report = _checked_input(caller)
    _refuse_unless(
        record is not None, "compose.committed",
        "composing needs the committed prior record (revision 1 or later)",
    )
    states = clarifications.project_states(record)
    held = {state["question_id"] for state in states}
    _refuse_unless(
        _current_question_ids(candidate, caller.original_text) <= held, "compose.covers_candidate",
        "the committed record lacks questions of this candidate: prepare and commit it first",
    )
    composed = clarifications.compose_supplement(record, caller.original_text)
    mapping = composed["source_mapping"]
    return {
        "format": FORMAT,
        "meaning_status": MEANING_STATUS,
        "stream_id": caller.stream.stream_id,
        "revision": caller.prior_revision,
        "candidate_ref": caller.candidate_ref,
        "candidate_sha256": caller.candidate_sha256,
        "original_text": composed["original_brief"],
        "original_sha256": caller.original_sha256,
        "record_json_sha256": caller.prior_record_sha256,
        "record_sha256": mapping["record_sha256"],
        "supplement": composed["supplement"],
        "supplement_sha256": mapping["supplement_sha256"],
        "source_mapping": _fresh(mapping),
        "consumption_id": contracts.consumption_id(
            caller.stream.stream_id, caller.prior_revision, mapping["supplement_sha256"],
        ),
        "unresolved_questions": _fresh([state for state in states if state["state"] != "answered"]),
    }
