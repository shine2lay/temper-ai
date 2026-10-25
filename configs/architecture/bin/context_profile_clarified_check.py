"""Opt-in clarified-profile reference checks, never semantic/Stage 1 acceptance.

The caller supplies the exact original text, record and preloaded validator.
No loading, source fetching, runtime, persistence or candidate rewriting occurs.
See docs/architecture/context-profile-clarified.md for the check-preservation audit.
"""

from __future__ import annotations

from configs.architecture.bin import context_profile_check as v2
from configs.architecture.bin import context_profile_clarifications as clarifications

CONTRACT = "context_profile_clarified/v1"
SCHEMA_ID = "temper:architecture/stages/context_profile/contract.clarified.v1.schema.json"


def _error(errors: list[dict], reason: str, path: str, detail: str) -> None:
    errors.append({"reason": reason, "path": path, "detail": detail})


def _json_error(value: object, errors: list[dict], reason: str, path: str) -> bool:
    # Share #308's strict plain-JSON/finite/UTF-8/cycle boundary, not a loader.
    try:
        clarifications._json_data(value)
    except clarifications.ClarificationError as exc:
        _error(errors, reason, path, str(exc))
        return True
    return False


def _clarification_pair(item: v2.Item, mapping: dict | None, states: dict, errors: list[dict]) -> tuple[str, str] | None:
    """Resolve only exact current human-attributed evidence; never normalize it."""
    if mapping is None:
        return None  # The record/original binding already has an explicit error.
    source = item.source
    where = f"{item.path}.source"
    before = len(errors)
    if source.get("source_id") != mapping["source_id"]:
        _error(errors, "clarification_source_mismatch", f"{where}.source_id", "not the supplied record's supplement identity")
    question_id = source.get("question_id")
    if not isinstance(question_id, str):
        return None  # Schema diagnostic, not an unhashable dictionary lookup.
    state = states.get(question_id)
    if state is None:
        _error(errors, "clarification_question_missing", f"{where}.question_id", "question is not in the supplied record")
        return None
    if state["state"] != "answered":
        _error(errors, "clarification_unresolved", where, f"question state is {state['state']}; no answered evidence")
        return None
    for field, expected, reason in (
        ("event_ids", state["active_event_ids"], "clarification_events_mismatch"),
        ("question", state["question"], "clarification_question_mismatch"),
        ("answer", state["answer"], "clarification_answer_mismatch"),
    ):
        if source.get(field) != expected:
            _error(errors, reason, f"{where}.{field}", f"not the exact current {field} from the supplied record")
    if len(errors) != before:
        return None
    return state["question"], state["answer"]


def _missing_numbers(texts: list[str], pair: tuple[str, str]) -> list[str]:
    # Tokenize separately: do not accidentally form a new number across the Q/A
    # boundary. A value's presence says nothing about units, negation or meaning.
    available = set()
    for part in pair:
        for _token, values in v2.number_tokens(part, quote_side=True):
            available.update(values)
    return [token.strip() for text in texts for token, values in v2.number_tokens(text, quote_side=False)
            if not values & available]


def _original_quote(item: v2.Item, brief: str, errors: list[dict]) -> None:
    """The frozen v2 quote checks, with no supplemental-source search."""
    quote = v2.norm(item.quote)
    words = len(quote.split())
    where = f"{item.path}.source.quote"
    if words < v2.QUOTE_WORDS[0]:
        _error(errors, "quote_too_short", where, f"a quote needs at least {v2.QUOTE_WORDS[0]} words")
    elif words > v2.QUOTE_WORDS[1]:
        _error(errors, "quote_too_long", where, f"{words} words; quote at most {v2.QUOTE_WORDS[1]}")
    elif quote not in brief:
        _error(errors, "quote_not_in_brief", where, "not one span of the original brief")
    else:
        missing = v2.unsupported_numbers(item.texts, item.quote)
        if missing:
            _error(errors, "number_not_in_quote", item.path,
                   f"{', '.join(missing)} not in its quote; a derived number is an assumption")
        if item.section == "external_systems" and v2.norm(item.texts[0]) not in quote:
            _error(errors, "system_name_not_in_quote", item.path, "system name is not in its original quote")


def _structure(profile: dict, errors: list[dict]) -> None:
    """Preserve non-source v2 checks, safely even when schema errors coexist."""
    system = profile.get("current_system")
    if isinstance(system, dict) and system.get("state") in ("none", "exists") and "source" not in system:
        _error(errors, "current_system_not_quoted", "$.current_system", "known system state needs original or clarification evidence")

    named = {u["field"] for u in v2._dicts(profile.get("unknowns")) if isinstance(u.get("field"), str)}
    empty_lists = ("external_systems", *(f for f in v2.LIST_FACTS if f != "maturity.evidence"),
                   *v2.MEASURES, "constraints", "goals")
    if isinstance(system, dict) and system.get("state") == "exists":
        empty_lists = (*empty_lists, "current_system.items")
    open_fields = [f for f in v2.UNKNOWN_SCALARS if v2.at(profile, f) == "unknown"]
    open_fields += [f for f in empty_lists if v2.at(profile, f) == []]
    for field in open_fields:
        if field not in named:
            _error(errors, "unknown_field_unnamed", f"$.{field}", f"{field} is unknown or empty: name it in unknowns")

    maturity = profile.get("maturity")
    if (isinstance(maturity, dict) and maturity.get("stage") in v2.STAGES and maturity.get("stage") != "unknown"
            and not maturity.get("evidence")):
        _error(errors, "maturity_without_evidence", "$.maturity.evidence", "a known stage must name its evidence")

    for section in ("constraints", "goals"):
        nodes = profile.get(section)
        seen = {}
        for index, node in enumerate(nodes if isinstance(nodes, list) else []):
            if not isinstance(node, dict) or not isinstance(node.get("id"), str):
                continue  # Malformed IDs have schema errors; never hash them.
            ident = node["id"]
            if ident in seen:
                _error(errors, "duplicate_id", f"$.{section}[{index}].id", f"{ident} is also {section}[{seen[ident]}]")
            else:
                seen[ident] = index

    goals = v2._dicts(profile.get("goals"))
    ranks = [g["rank"] for g in goals if v2._is_type(g.get("rank"), "integer")]
    repeated = sorted({rank for rank in ranks if ranks.count(rank) > 1})
    if repeated:
        _error(errors, "rank_duplicate", "$.goals", f"rank {', '.join(map(str, repeated))} given to more than one goal")
    elif sorted(ranks) != list(range(1, len(ranks) + 1)):
        _error(errors, "rank_gap", "$.goals", f"ranks {sorted(ranks)}; expected 1 to {len(ranks)}, each once")


def _overlap(items: list, errors: list[dict]) -> None:
    # Entries have separate domains. Identical 'yes' answers to different
    # questions, or identical words in original and clarification, are not aliases.
    for constraint, domain, evidence in (entry for entry in items if entry[0].section == "constraints"):
        for goal, goal_domain, goal_evidence in (entry for entry in items if entry[0].section == "goals"):
            if domain != goal_domain:
                continue
            same = (evidence in goal_evidence or goal_evidence in evidence) if domain == "quote" else evidence == goal_evidence
            if same:
                _error(errors, "constraint_goal_overlap", goal.path,
                       f"stands on the same evidence as constraint {constraint.node.get('id')}: a must-hold is never also a tradeable goal")


def check_clarified_profile(profile: object, original_brief: str, record: dict, validator: v2.Validator) -> dict:
    """Check structure and references, returning NOT_EVALUATED for meaning always.

    The trusted caller supplies the shipped schema/validator and current record.
    Neither the truth of the attribution nor an answer's meaning is evaluated.
    Inputs are not mutated; returned containers do not alias caller containers.
    """
    errors: list[dict] = []
    counts = {"items": 0, "quoted": 0, "assumed": 0, "clarified": 0}
    states = []
    mapping = None
    bad_profile = _json_error(profile, errors, "invalid_profile", "$")
    bad_brief = _json_error(original_brief, errors, "invalid_brief", "original_brief")
    if not bad_brief and type(original_brief) is not str:
        _error(errors, "invalid_brief", "original_brief", "original_brief must be text")
        bad_brief = True
    try:
        states = clarifications.project_states(record)  # Validates imported records too.
    except clarifications.ClarificationError as exc:
        _error(errors, "invalid_record", "record", str(exc))
    else:
        if not bad_brief:
            try:
                mapping = clarifications.compose_supplement(record, original_brief)["source_mapping"]
            except clarifications.ClarificationError as exc:
                _error(errors, "record_brief_mismatch", "record.brief_sha256", str(exc))
    unresolved = [state for state in states if state["state"] != "answered"]

    correct_validator = (isinstance(validator, v2.Validator) and validator.schema.get("$id") == SCHEMA_ID
                         and validator.schema.get("properties", {}).get("contract") == {"const": CONTRACT})
    if not correct_validator:
        _error(errors, "validator_contract_mismatch", "validator", "supply the shipped clarified v1 schema, not a fallback")
    elif not bad_profile:
        for keyword, path, detail in validator.errors(profile):
            reason = ("missing_section" if keyword == "required" and path == "$"
                      else "bad_enum" if keyword == "enum" else "schema")
            _error(errors, reason, path, detail)

    if not bad_profile and isinstance(profile, dict):
        if not bad_brief:
            digest = v2.sha256_bytes(original_brief.encode("utf-8"))
            if profile.get("brief_sha256") != digest:
                _error(errors, "brief_hash_mismatch", "$.brief_sha256", "not the exact original UTF-8 brief hash")
        source = profile.get("clarification_source")
        if mapping is not None and isinstance(source, dict):
            for field, reason in (("source_id", "clarification_source_mismatch"), ("record_sha256", "record_hash_mismatch")):
                if source.get(field) != mapping[field]:
                    _error(errors, reason, f"$.clarification_source.{field}", "not the supplied record's source mapping")
        by_question = {state["question_id"]: state for state in states}
        overlapping = []
        brief = v2.norm(original_brief) if not bad_brief else ""
        for item in v2.iter_items(profile):
            counts["items"] += 1
            if item.kind == "quote" and item.quote is not None:
                counts["quoted"] += 1
                if not bad_brief:
                    _original_quote(item, brief, errors)
                if item.section in ("constraints", "goals") and item.quote:
                    overlapping.append((item, "quote", v2.norm(item.quote)))
            elif item.kind == "assumption":
                counts["assumed"] += 1
            elif item.kind == "clarification":
                counts["clarified"] += 1
                pair = _clarification_pair(item, mapping, by_question, errors)
                if pair is not None:
                    missing = _missing_numbers(item.texts, pair)
                    if missing:
                        _error(errors, "number_not_in_clarification", item.path, f"{', '.join(missing)} not in its exact question/answer pair")
                    if item.section == "external_systems" and not any(v2.norm(item.texts[0]) in v2.norm(part) for part in pair):
                        _error(errors, "system_name_not_in_clarification", item.path, "system name is not in its question or answer")
                    if item.section in ("constraints", "goals"):
                        overlapping.append((item, "clarification", (item.source["source_id"], item.source["question_id"], tuple(item.source["event_ids"]))))
            if item.section == "workload.observed" and item.kind not in ("quote", "clarification"):
                _error(errors, "observed_not_quoted", item.path, "observed workload needs original or clarification evidence, not an assumption")
            if (item.section == "current_system" and item.node.get("state") in ("none", "exists")
                    and item.kind not in ("quote", "clarification")):
                _error(errors, "current_system_not_quoted", item.path, "known system state needs original or clarification evidence, not an assumption")
        _structure(profile, errors)
        _overlap(overlapping, errors)

    return {"references_ok": not errors, "errors": errors, "counts": counts,
            "unresolved_questions": unresolved, "meaning_status": "NOT_EVALUATED"}
