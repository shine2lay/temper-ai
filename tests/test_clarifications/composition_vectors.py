"""Fixed M4 inputs/observations, NOT_RUN composition vectors, not pytest placeholders.

Only constructors and pure identity/source formatting run here. No coordinator,
store, checker, provider call or test runner is implemented. Import works on A
alone. Each call to vectors() returns fresh data; consumers must not overwrite
expected values with results from the system being tested. See integration.md.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from itertools import combinations, product
from typing import Any, Literal

from configs.architecture.bin import context_profile_clarifications as foundation
from temper_ai.clarifications import contracts as c
from tests.test_clarifications import composition_scenarios as s

BOT, CHAT, OWNER, OTHER = "7001", "-1001", "5001", "5002"
QUESTION_COPY, PROMPT_COPY, LOST_COPY = "500", "600", "503"
QUESTION = "Must it work offline?"
QUESTION_TEXT = "Must it work offline?\nReply to this message with your answer."
ANSWER = " Yes \n"
NO_EVENT = "e-" + "0" * 64
WRONG_HASH = "f" * 64
Q = c.question_id(s.BRIEF_SHA, s.COMPOSITION_UNKNOWN)
TRANSPORT = c.TransportNamespace("telegram", BOT)
POLICY = "responder-policy:synthetic/owner-only"
AUTHORITY = "authority:synthetic/clinic"
DIALECTS = ("sqlite-file", "postgres-isolated-schema")
PUBLIC_STORE_PATHS = (
    "load", "supplement", "merge_candidate", "save_presentation", "record_copy", "append_receipt", "mark_consumed",
)


@dataclass(frozen=True)
class Case:
    """Input data and independent expectations; setup is NOT an executed result."""

    name: str
    inputs: dict[str, Any]
    expected: dict[str, Any]
    schedule: tuple[str, ...] = ()


@dataclass(frozen=True)
class Control:
    change: str
    assertion: str


@dataclass(frozen=True)
class Vector:
    id: str
    sealed_cases: tuple[str, ...]
    cases: tuple[Case, ...]
    observations: tuple[str, ...]
    controls: tuple[Control, ...]
    execution_status: Literal["NOT_RUN"] = "NOT_RUN"
    meaning_status: Literal["NOT_EVALUATED"] = "NOT_EVALUATED"


# Logical test seams, NOT claims that a production hook with this name exists.
# E binds these to B/C's actual operations. Events/barriers, never sleeps, order them.
SCHEDULES = {
    "whole_path": (
        "parent: prepare commits revision 1; save presentation and immutable question intent",
        "parent: attempt.commit precedes provider.send; delivery.commit keeps 500",
        "parent: edge.pull typed 1001; ingress+retained receipt commit before prompt/offset",
        "parent: prompt attempt.commit precedes send; delivery.commit keeps 600",
        "parent: edge.pull callback 1002; ingress+applied event/revision 2 commit before ack/offset",
        "parent: dispose engines; construct fresh engines/edge/coordinator on the same isolated database",
        "parent: recover; check independent F1; acknowledge True then False; re-pull both original actions",
    ),
    "attempt_race": (
        "parent: save one immutable send intent; start two child processes, each with its own engine",
        "A,B: read the same expected_attempts outside admission; signal attempt.read_count barrier",
        "parent: release both; A,B call real start_attempt; only won=True may call fake provider",
        "parent: join children; fresh engine reads one increment, one winner and one provider call",
    ),
    "reverse_deliveries": (
        "A: commit attempt 1; block provider.return_id before returning 501",
        "B: explicitly resend with expected_attempts=1 while no delivery is recorded; commit attempt 2",
        "B: return 502 and commit delivery; A: return 501 and commit delivery",
        "parent: restart; inspect both delivery lookups and presentation copies; ordinary retry sends nothing",
    ),
    "append_race": (
        "parent: two child processes with independent engines and the same committed revision",
        "A,B: signal append.before_revision_cas on first attempt only; parent releases both",
        "loser: reload latest state and retry its same action identity, not a new receipt",
        "parent: join; fresh engine reads both events/receipts and the latest projected state",
    ),
    "first_create": (
        "A,B: independent processes/engines observe missing stream; stop before first-create insert",
        "parent: release both; losing insert reloads latest and merges its additional question",
        "parent: fresh engine reads union of both question sets; no empty-history replacement",
    ),
    "before_admission": (
        "A: finish edge current/answered read; stop at attempt.before_transaction",
        "B: commit answer or generation 2; A: enter real admission and lose without increment/send",
    ),
    "after_admission": (
        "A: commit winning admission; stop at provider.before_send",
        "B: commit generation 2 or confirm typed action; A: send may finish",
        "parent: fresh genuine pull of stale/second-confirmation action; append transaction decides application",
    ),
    "stale_reopen": (
        "A: construct reopen for revision 2 and its exact active IDs; stop before append transaction",
        "B: commit independent answer 602; A: append saved reopen; unseen answer must survive",
    ),
    "stale_consumption": (
        "A: obtain checked snapshot at revision 2; stop before return recheck or current acknowledgement CAS",
        "B: commit independent answer 602; A: continue; new old-revision acknowledgement must refuse",
    ),
    "lost_copy": (
        "provider: deliver 503; child dies before delivery.commit; start fresh engine/edge",
        "parent: new provider pull replies to 503; ordinary route records submission, no clarification receipt",
        "trusted adapter: explicit verified record_delivery for 503; do not replay an ordinary stored dict",
        "provider: new pull/redelivery of the action; only now may M2 bind it",
    ),
    "crash": (
        "parent: child has its own engine; event pipe signals the named real transaction/effect boundary",
        "parent: terminate child at that boundary and join; no success asserted from a child-local object",
        "parent: fresh engine/edge reads committed rows and offset; genuine provider redelivery retries the same identity",
    ),
}


def initial_input(**changes):
    """A's actual canonical factory; invalid changes fail at their real boundary."""
    return s.inputs(s.composition_profile(), ask=(Q,), **changes)


def presentation(generation=1):
    return initial_input().presentation(Q, c.metadata_sha256(s.COMPOSITION_UNKNOWN), generation)


def answer_receipt(action_id="602", text=ANSWER, *, sender=OWNER, generation=1, message_id=QUESTION_COPY, **changes):
    """Trusted-port synthetic input only; never evidence of provider capture."""
    p = presentation(generation)
    fields = {
        "ingress": "provider_pull", "action": c.ActionIdentity(TRANSPORT, CHAT, "message", action_id),
        "update_id": 1003, "sender_id": sender, "sender_is_bot": False, "forwarded": False,
        "text": text, "text_sha256": s.sha(text),
        "binding": c.PresentationBinding(p.stream.stream_id, Q, p.presentation_id, generation, message_id),
        "responder": c.ResponderDecision(POLICY, sender, "authorised", "responder_policy"),
        "intent": "answer", "disposition": "answered",
    }
    return c.ActionReceipt(**{**fields, **changes})


def typed_receipt(text=ANSWER):
    return answer_receipt("601", text, update_id=1001, disposition=None)


def confirmation_receipt(words=None, *, sender=OWNER, action_id="cb-701", **changes):
    words = typed_receipt() if words is None else words
    fields = {
        "action": c.ActionIdentity(TRANSPORT, CHAT, "callback", action_id), "update_id": 1002,
        "callback_data": "clar:answered",
        "confirms": c.ConfirmedText(words.action, words.sender_id, words.text_sha256),
    }
    return answer_receipt(text="", sender=sender, message_id=PROMPT_COPY, **{**fields, **changes})


def pulled_updates(text=ANSWER, *, sender=OWNER, reply_to=QUESTION_COPY, callback_sender=OWNER, payload="clar:answered"):
    """Fixed provider-fixture data. Must go through SyntheticTelegram -> edge.pull.

    Passing these dicts straight to a handler is the negative control, not the
    supported ingress. Dates are fixed, not wall-clock-derived.
    """
    chat = {"id": int(CHAT), "type": "supergroup", "title": "Synthetic group"}
    bot = {"id": int(BOT), "is_bot": True, "first_name": "Synthetic bot"}
    return (
        {"update_id": 1001, "message": {
            "message_id": 601, "date": 1700000000, "chat": dict(chat),
            "from": {"id": int(sender), "is_bot": False, "first_name": "Synthetic"}, "text": text,
            "reply_to_message": {"message_id": int(reply_to), "date": 1700000000, "chat": dict(chat),
                                 "from": dict(bot), "text": QUESTION_TEXT},
        }},
        {"update_id": 1002, "callback_query": {
            "id": "cb-701", "from": {"id": int(callback_sender), "is_bot": False, "first_name": "Synthetic"},
            "chat_instance": "-1", "data": payload,
            "message": {"message_id": 600, "date": 1700000000, "chat": dict(chat), "from": dict(bot)},
        }},
    )


def expected_answer_event(receipt, text):
    """Literal expected human event, not validate_receipt(...).event() output."""
    event = {
        "event_id": c.event_id(receipt), "question_id": Q, "kind": "answer",
        "actor": {"kind": "human", "ref": f"telegram-user:{receipt.sender_id}"},
        "source": {"kind": "human_response", "ref": f"clarification-receipt:{c.receipt_sha256(receipt)}"},
        "answer": text, "disposition": receipt.disposition, "supersedes": list(receipt.supersedes),
    }
    if receipt.reason is not None:
        event["reason"] = receipt.reason
    return event


def reference_inputs(*events):
    """Independent expected record -> existing source formatter -> A's F1 builder.

    Supply literal expected events, NEVER events or a report returned by the
    coordinator under test. The formatter is reused, not a second validator.
    """
    record = foundation.create_record(s.composition_profile(), s.BRIEF)
    for event in events:
        record = foundation.append_event(record, event)
    source = foundation.compose_supplement(record, s.BRIEF)
    ids = tuple(event["event_id"] for event in events)
    candidate = s.clarified_candidate(
        s.composition_profile(), source_mapping=source["source_mapping"], question_id=Q,
        question=QUESTION, answer=events[-1]["answer"], event_ids=ids,
    )
    return {"record": record, "source": source, "candidate": candidate, "active_event_ids": ids}


def happy_path_inputs():
    words, press = typed_receipt(), confirmation_receipt()
    event = expected_answer_event(press, ANSWER)
    return {
        "caller": initial_input(), "presentation": presentation(), "display_text": QUESTION_TEXT,
        "provider_ids": (500, 600), "policy_allowed": {(POLICY, CHAT, OWNER)},
        "updates": pulled_updates(), "typed_receipt": words, "confirmed_receipt": press,
        "expected_event": event, **reference_inputs(event),
    }


def _v01():
    data = happy_path_inputs()
    return Vector("V01", ("T01",), (Case("combined_happy_first", data, {
        "prepare_revision": 1, "typed_status": "retained", "typed_code": "no_explicit_disposition",
        "typed_events": 0, "answer_revision": 2, "answer_status": "applied", "human_events": 1,
        "answer": ANSWER, "event_ids": data["active_event_ids"], "original": s.BRIEF,
        "copies": frozenset({QUESTION_COPY, PROMPT_COPY}), "references_ok": True,
        "meaning_status": "NOT_EVALUATED", "ack_results": (True, False), "run_signals": 0,
        "replay_new_events": 0, "replay_new_prompts": 0, "replay_revision": 2,
        "unrelated_unresolved": len(s.BASE_FIELDS),
    }, SCHEDULES["whole_path"]),), (
        "Query actual durable rows after each commit and after engine/edge reconstruction.",
        "Compare original, record, supplement, action bindings and ordered event IDs with the independent input bundle.",
        "Observe ingress/result commit before prompt, callback acknowledgement and poll offset; recovery sends nothing.",
    ), (
        Control("Replace F1's event ID with NO_EVENT", "references_ok is False, not a setup exception"),
        Control("Hand caller-crafted update directly to intake", "unverified ingress; zero authoritative receipts"),
        Control("Replace original_text with BRIEF + space without its hash", "caller.original_hash refuses"),
        Control("Suppress application commit", "answer_revision == 2 and persisted expected event assertion fail"),
    ))


def _v02():
    variants = []
    defects = ("missing_budget", "unknown_field_list", "constraint_id_list", "goal_id_object")
    for size in range(1, len(defects) + 1):
        for selected in combinations(defects, size):
            candidate = s.composition_profile()
            if "missing_budget" in selected:
                del candidate["budget"]
            if "unknown_field_list" in selected:
                candidate["unknowns"][0]["field"] = []
            source = {"kind": "assumption", "why": "Synthetic assumption"}
            if "constraint_id_list" in selected:
                candidate["constraints"] = [{"id": [], "text": "Use the clinic tool", "source": dict(source)}]
            if "goal_id_object" in selected:
                candidate["goals"] = [{"id": {}, "criterion": "cost", "rank": 1,
                                       "note": "Keep costs low", "source": dict(source)}]
            variants.append(Case("+".join(selected), {"candidate": candidate, "entries": ("prepare", "compose_supplement")},
                                 {"guard": "candidate.complete", "diagnostics": "actual schema paths/details",
                                  "store_reads": 0, "store_writes": 0, "presentations": 0}))
    variants.append(Case("invalid_quote_anchor", {"candidate": s.profile(s.COMPOSITION_UNKNOWN, quote="Invented original quote")},
                         {"guard": "candidate.complete", "store_calls": 0, "presentations": 0}))
    variants.append(Case("clean", {"candidate": s.composition_profile()}, {"meaning_status": "NOT_EVALUATED"}))
    for error, malformed in ((TypeError, False), (ValueError, False), (ValueError, True)):
        variants.append(Case(f"propagate_{error.__name__}_{malformed}",
                             {"injected_error": error, "malformed": malformed}, {"propagate_same_exception": True}))
    return Vector("V02", ("T02",), tuple(variants), ("Real full checker first through both adapter public entries.",), (
        Control("Remove schema-invalid TypeError recovery", "candidate.complete real diagnostic assertion fails"),
        Control("Catch schema-valid TypeError or ValueError", "same exception propagation assertion fails"),
    ))


def _v03():
    prior = foundation.create_record(s.composition_profile(), s.BRIEF)
    cases = [Case("exact_type", {"caller": initial_input()}, {"adapter_fields_equal": True, "direct_m1_guard": "caller.type"})]
    for name, changes, guard in (
        ("original", {"original_text": s.BRIEF + " "}, "caller.original_hash"),
        ("candidate", {"candidate_sha256": WRONG_HASH}, "caller.candidate_hash"),
        ("prior", {"revision": 1, "record": prior, "prior_record_sha256": WRONG_HASH}, "caller.record_hash"),
        ("missing_prior", {"revision": 1}, "caller.record_missing"),
        ("missing_authority", {"source_authority_ref": None}, "caller.authority_missing"),
    ):
        cases.append(Case(name, {"candidate": s.composition_profile(), "caller_changes": changes},
                          {"guard": guard, "replacement_history": False, "store_calls": 0}))
    cases.append(Case("other_namespace", {"stream": c.StreamKey("project:synthetic-other", s.BRIEF_SHA)},
                      {"cross_context_access": False, "inherits_authority": False}))
    for operation in ("read", "write", "send"):
        cases.append(Case(f"deny_{operation}", {"authority_denies": operation}, {"corresponding_port_calls": 0}))
    return Vector("V03", ("T02", "T17"), tuple(cases), (
        "Constructor refusals occur when E applies caller_changes with A's inputs factory, not while importing vectors.",
        "Read/write/send denial is exercised at its operation boundary, including the scoped adapter's own calls.",
    ), (Control("Bypass adapter/exact-type guard", "field preservation or direct caller.type assertion fails"),
        Control("Open candidate_ref or source_authority_ref", "opaque-reference open spy fails")))


def _v04():
    cases = tuple(Case(name, {"kind": kind, "expected_attempts": attempts, "resend": resend,
                              "processes": 2, "dialects": DIALECTS},
                       {"wins": (False, True), "attempts": attempts + 1, "provider_calls": 1},
                       SCHEDULES["attempt_race"])
                  for name, kind, attempts, resend in (
                      ("question", "question", 0, False), ("duplicate_prompt", "prompt", 0, False),
                      ("explicit_resend", "question", 1, True)))
    controls = tuple(Case(name, data, {"won": False, "attempt_delta": 0, "provider_calls": 0}) for name, data in (
        ("stale_count", {"attempts": 1, "expected_attempts": 0, "resend": True}),
        ("delivered", {"attempts": 1, "expected_attempts": 1, "resend": True, "delivery": "500"}),
        ("implicit_resend", {"attempts": 1, "expected_attempts": 1, "resend": False}),
    ))
    return Vector("V04", ("T14",), cases + controls + (
        Case("single", {"expected_attempts": 0, "resend": False}, {"won": True, "attempts": 1, "provider_calls": 1}),
    ), ("One committed winner across processes, including prompt/retry admission; a locked fake cannot discharge this.",), (
        Control("Split read/check/increment into separate transactions", "wins count == 1 and provider_calls == 1 fail"),
    ))


def _v05():
    return Vector("V05", ("T12", "T14"), (
        Case("reverse_completion", {"returns": ("502", "501"), "explicit_resend": True, "dialects": DIALECTS},
             {"copies_include": frozenset({"501", "502"}), "lookups_same_intent": True, "intents": 1,
              "ordinary_retry_calls": 0, "duplicate_delivery_new_rows": 0}, SCHEDULES["reverse_deliveries"]),
        Case("attempt_commit_then_raise", {"fault": "attempt.after_commit_before_return"},
             {"attempts": 1, "state": "uncertain", "ordinary_retry_calls": 0}, SCHEDULES["crash"]),
        Case("delivery_commit_then_raise", {"fault": "delivery.after_commit_before_return", "copy": "501"},
             {"lookup_survives": "501", "replay_new_rows": 0}, SCHEDULES["crash"]),
        Case("prompt_retired_copies", {"kind": "prompt", "returns": ("502", "501"),
                                       "generation_after_delivery": 2, "dialects": DIALECTS},
             {"retired_copies_include": frozenset({"501", "502"}), "all_history_lookups_same_intent": True},
             SCHEDULES["reverse_deliveries"]),
    ), ("Check all-history copies and lookup after restart, including prompt and retired presentation variants.",
        "Explicit resend can produce two network deliveries; representative message_id is not the membership set."), (
        Control("Overwrite older copy on completion", "exact lookup/copy membership for both 501 and 502 fails"),
        Control("Split delivery lookup and copy binding commits", "no partially visible delivery assertion fails"),
    ))


def _v06():
    return Vector("V06", ("T03", "T12", "T14"), (
        Case("K1_lost_copy", {"updates": pulled_updates(reply_to=LOST_COPY), "copy": LOST_COPY},
             {"claimed_before_mapping": False, "ordinary_submissions": 1, "clarification_receipts": 0,
              "human_events": 0, "new_pull_after_mapping_may_bind": True}, SCHEDULES["lost_copy"]),
        Case("ordinary_dict_replay", {"update": pulled_updates(reply_to=LOST_COPY)[0], "origin": "saved ordinary inbox"},
             {"authoritative_receipts": 0, "unverified_ingress": True}),
        Case("wrong_mapping", {"other_bot": "7002", "other_chat": "-1002", "other_send": "different immutable intent"},
             {"cross_binding_refused": True}),
    ), ("Ordinary submit spy records real ordinary-route behavior; unclaimed is not guaranteed to be a no-op.",
        "Only explicitly authorized, verified reconciliation may record 503; raw ID alone is not evidence."), (
        Control("Treat an ordinary inbox dict as provider ingress", "zero clarification receipts from saved dict fails"),
        Control("Pretend unknown delivery is a safe no-op", "ordinary_submissions == 1 fails"),
    ))


def _v07():
    cases = [
        Case("answered_before_present", {"setup": "V01 through answer"}, {"m1_guard": "ask.unresolved", "sends": 0}),
        Case("generation_before_present", {"current_generation": 2, "supplied": presentation(1)},
             {"stale_coordinator_refusal": True, "edge_state": "not_current", "sends": 0}),
    ]
    for kind, change in product(("question", "prompt", "retry"), ("answered", "generation_2")):
        cases.append(Case(f"{kind}_before_{change}", {"kind": kind, "rival_commit": change},
                          {"won": False, "attempt_delta": 0, "provider_calls": 0,
                           "admission_state_can_be_pending": True}, SCHEDULES["before_admission"]))
    for change, code in (("generation_2", "stale_presentation"), ("confirmed_typed_action", "already_confirmed")):
        cases.append(Case(f"after_{change}", {"rival_commit": change},
                          {"network_send_may_complete": True, "application": "retained", "code": code,
                           "new_human_events": 0}, SCHEDULES["after_admission"]))
    return Vector("V07", ("T05", "T14"), tuple(cases), (
        "K5: final application is checked under the real append transaction, not trusted capture validation.",
        "A distinct current genuine answer remains admissible; this must not turn into first-answer-wins (V11).",
    ), (Control("Remove atomic answered or generation admission check", "forbidden send/attempt delta becomes nonzero"),
        Control("Remove final generation/confirmation fence", "stale or duplicate action incorrectly adds a human event")))


def _v08():
    cases = [Case("own_pull", {"updates": pulled_updates()}, {"text": ANSWER, "callback_data": "clar:answered"})]
    for ingress in c.UNVERIFIED_INGRESSES + (c.MODEL_INGRESS,):
        cases.append(Case(ingress, {"trusted_port_receipt": replace(typed_receipt(), ingress=ingress)},
                          {"authoritative_receipts": 0, "provenance_refusal": True}))
    for mutation in ("nested_text", "nested_sender", "nested_callback_data", "append_foreign_object", "different_edge", "different_client"):
        cases.append(Case(mutation, {"updates": pulled_updates(), "after_capture_change": mutation,
                                     "altered_text": "No", "altered_sender": OTHER, "altered_data": "clar:deferred"},
                          {"own_capture_unchanged": True, "foreign_receipts": 0, "original_text": ANSWER}))
    for name, change in (
        ("wrong_bot", {"reply_bot_id": 7002}), ("wrong_chat", {"chat_id": -1002}),
        ("denied_sender", {"sender_id": 5002}), ("bot_sender", {"is_bot": True}),
        ("forwarded", {"forward_origin": {"type": "user"}}),
        ("wrong_question", {"question_id": c.question_id(s.BRIEF_SHA, s.base_unknown("goals"))}),
    ):
        cases.append(Case(name, {"update_changes": change, "policy_allowed": {(POLICY, CHAT, OWNER)}},
                          {"applied_answers": 0, "precise_provenance_or_binding_outcome": True}))
    return Vector("V08", ("T03", "T04", "T06"), tuple(cases), (
        "Expose/mutate PulledBatch contents only after capture; assert original captured digest and body are retained.",
        "No claim of a sandbox against hostile Python; earlier provenance/binding refusals retain precedence.",
    ), (Control("Use exposed mutable objects or remove membership check", "specific altered body/foreign receipt is admitted"),))


def _v09():
    cases = []
    for name, text in (("exact", ANSWER), ("unicode", "  café 東京 🙂\r\n"), ("yes", "yes"), ("no", "no")):
        cases.append(Case(name, {"updates": pulled_updates(text), "typed": typed_receipt(text)},
                          {"retained_text": text, "typed_only_state": "unanswered", "confirmed_answer": text,
                           "active_events_after_confirm": 1}))
    for disposition in ("deferred", "unknown"):
        cases.append(Case(disposition, {"updates": pulled_updates(payload=f"clar:{disposition}")},
                          {"state": disposition, "unresolved": True, "exact_text": ANSWER}))
    cases.extend((
        Case("empty_defer", {"typed": typed_receipt(""),
                             "press": confirmation_receipt(typed_receipt(""), disposition="deferred", callback_data="clar:deferred")},
             {"human_events": 0, "unresolved": True, "exact_text": ""}),
        Case("denied_confirmer_pull", {"updates": pulled_updates(callback_sender=OTHER)},
             {"code": "responder_not_authorised", "applied_answers": 0}),
        Case("other_confirmer_trusted_port", {"words": typed_receipt(), "press": confirmation_receipt(sender=OTHER)},
             {"code": "confirmer_not_author", "applied_answers": 0}),
        Case("changed_digest", {"confirms": replace(confirmation_receipt().confirms, text_sha256=WRONG_HASH)},
             {"guard": "confirm.digest", "applied_answers": 0}),
        Case("second_press", {"presses": (confirmation_receipt(), confirmation_receipt(action_id="cb-702"))},
             {"second_status": "retained", "second_guard": "confirmation.once", "human_events": 1}),
        Case("unrecognised_payload", {"updates": pulled_updates(payload="approve")},
             {"unresolved": True, "applied_answers": 0}),
        Case("model_suggestion", {"suggested_text": "Must work offline", "actor_kind": "model"},
             {"human_events": 0, "unresolved": True, "suggestions_separate": True}),
    ))
    return Vector("V09", ("T06", "T07"), tuple(cases), ("Compare exact UTF-8 bytes; do not strip, pad or rewrite yes/no.",), (
        Control("Remove confirmer-author or confirmation-once guard", "foreign/repeated press adds an event"),
        Control("Trim answer text", "exact UTF-8 comparison fails"),
    ))


def _v10():
    words, press = typed_receipt(), confirmation_receipt()
    correction = answer_receipt("603", "No: online only.", intent="correct", supersedes=(c.event_id(press),), reason="Typo.")
    return Vector("V10", ("T08",), (
        Case("replays", {"receipts": (words, press), "correction": correction, "replay_at": ("before", "after correction")},
             {"saved_results_identical": True, "new_revision": False, "new_events": 0, "old_answer_resurrected": False}),
        Case("changed_body", {"receipt": press, "variants": (
            replace(press, disposition="deferred"), replace(press, binding=replace(press.binding, message_id="599")),
            replace(words, text="No", text_sha256=s.sha("No")),
        )}, {"diagnostic_only": True, "original_result_unchanged": True}),
        Case("forged_then_genuine", {"forged": replace(words, ingress="caller_label"), "genuine": words},
             {"refusal_reserves_key": False, "genuine_retained": True}),
    ), ("Replay saved result/event/revision, never mint an action identity to hide a collision.",), (
        Control("Reserve authoritative action key on refusal", "same-key genuine receipt recovery fails"),
        Control("Reapply old replay after correction", "old answer resurrection/new revision assertion fails"),
    ))


def _v11():
    first = answer_receipt("602")
    cases = []
    for name, text, disposition, state in (
        ("same_text", ANSWER, "answered", "answered"), ("different_text", "No", "answered", "conflicting"),
        ("mixed_dispositions", ANSWER, "deferred", "conflicting"),
    ):
        second = answer_receipt("604", text, sender=OTHER, disposition=disposition, update_id=1004)
        cases.append(Case(name, {"receipts": (first, second), "policy_allowed": {(POLICY, CHAT, OWNER), (POLICY, CHAT, OTHER)},
                                 "dialects": DIALECTS},
                          {"event_set": frozenset({c.event_id(first), c.event_id(second)}), "revision": 3,
                           "actors": ("telegram-user:5001", "telegram-user:5002"), "state": state}, SCHEDULES["append_race"]))
    extra = s.base_unknown("constraints")
    extra["question"] = "Must it support refunds?"
    cases.append(Case("first_create", {"candidates": (s.composition_profile(), s.profile(s.COMPOSITION_UNKNOWN, extra)),
                                        "dialects": DIALECTS},
                      {"question_ids_include": (Q, c.question_id(s.BRIEF_SHA, extra)), "revisions": (1, 2)},
                      SCHEDULES["first_create"]))
    return Vector("V11", ("T09", "T10"), tuple(cases), (
        "Both distinct genuine actions survive. Assert set membership independently of nondeterministic commit order.",
        "Ordered F1 IDs must then follow the actual persisted order, checked against one of the two legal schedules.",
    ), (Control("Commit stale whole JSON or keep only first winner", "one of the two named event IDs/actors is missing"),))


def _v12():
    own, other = answer_receipt("602"), answer_receipt("604", sender=OTHER)
    targets = {"own": (c.event_id(own),), "other": (c.event_id(other),), "unknown": (NO_EVENT,),
               "other_unknown": (c.event_id(other), NO_EVENT), "unknown_other": (NO_EVENT, c.event_id(other))}
    states = {
        "message": None, "no_disposition": ("no_explicit_disposition", "disposition.explicit"),
        "blank_text": ("blank_text", "text.blank"), "retired": ("stale_presentation", "binding.stale"),
        "press": None, "press_no_disposition": ("no_explicit_disposition", "disposition.explicit"),
        "press_blank_text": ("blank_text", "text.blank"), "press_retired": ("stale_presentation", "binding.stale"),
        "press_already_confirmed": None,
    }
    cases = []
    for state, target in product(states, targets):
        words = typed_receipt(" \u200b " if state == "press_blank_text" else ANSWER)
        changes = {"intent": "correct", "supersedes": targets[target], "reason": "Typo."}
        if "no_disposition" in state:
            changes["disposition"] = None
        attempt = (confirmation_receipt(words, **changes) if state.startswith("press") else
                   answer_receipt("603", " \u200b " if state == "blank_text" else "No: online only.", **changes))
        unknown = "unknown" in target
        reason = states[state]
        if reason is None and target == "other":
            reason = ("cross_actor_correction", "correction.same_actor")
        if reason is None and state == "press_already_confirmed":
            reason = ("already_confirmed", "confirmation.once")
        status = "refused" if unknown else "retained" if reason else "applied"
        cases.append(Case(f"{state}_{target}", {
            "setup_receipts": (own, other), "words": words, "attempt": attempt,
            "current_generation": 2 if "retired" in state else 1,
            "already_confirmed": state == "press_already_confirmed",
        }, {"status": status, "code_guard": ("missing_record", "correction.known") if unknown else reason,
            "authoritative_key_kept": not unknown, "history_edited": False,
            "same_key_genuine_recovery": unknown}))
    for state, (name, changes, code, guard) in product(states, (
        ("unverified", {"ingress": "caller_label"}, "unverified_ingress", "provenance.ingress"),
        ("model", {"ingress": "model_output"}, "model_not_human", "provenance.model"),
        ("bot", {"sender_is_bot": True}, "bot_sender", "provenance.bot"),
        ("forwarded", {"forwarded": True}, "forwarded_message", "provenance.forwarded"),
        ("denied", {"responder": c.ResponderDecision(POLICY, OWNER, "denied", "responder_policy")},
         "responder_not_authorised", "responder.decision"),
        ("unknown_copy", {"message_id": "999"}, "binding_mismatch", "binding.copy"),
    )):
        cases.append(Case(f"precedence_{state}_{name}", {"state": state, "targets": (NO_EVENT,), "changes": changes},
                          {"status": "refused", "code_guard": (code, guard), "authoritative_key_kept": False}))
    return Vector("V12", ("T11",), tuple(cases), (
        "Unknown targets are diagnostic-only even when validation would retain; known cross-actor evidence stays unapplied.",
        "Keep correction -> confirmation-once -> reopen order and earlier provenance/binding refusal precedence.",
    ), (Control("Remove retained-path correction precondition", "unknown correction leaves a forbidden authoritative row/text/key"),
        Control("Check confirmation before unknown correction", "correction.known precedence assertion fails")))


def _v13():
    press = confirmation_receipt()
    reopen = answer_receipt(text="", action=c.ActionIdentity(TRANSPORT, CHAT, "callback", "cb-703"),
                            update_id=1005, callback_data="clar:reopen", intent="reopen", disposition=None,
                            reason="Plans changed; ask again.", seen_revision=2, seen_active_event_ids=(c.event_id(press),))
    return Vector("V13", ("T11", "T14"), (
        Case("fresh_reopen", {"setup": "V01 through answer", "receipt": reopen},
             {"status": "applied", "state": "reopened", "unresolved": True, "history_edited": False}),
        Case("stale_reopen", {"receipt": reopen, "rival": answer_receipt("602")},
             {"status": "retained", "unseen_answer_preserved": True}, SCHEDULES["stale_reopen"]),
        Case("late_generation", {"receipt": answer_receipt(), "current_generation": 2},
             {"status": "retained", "code": "stale_presentation", "new_events": 0}),
        Case("second_confirmation", {"presses": (press, confirmation_receipt(action_id="cb-702"))},
             {"second_status": "retained", "guard": "confirmation.once", "human_events": 1}),
        Case("answer_after_reopen", {"reopen": reopen, "next": answer_receipt("605")}, {"state": "answered"}),
    ), ("Reopen/correction are trusted M0/M3 port controls, not an invented Telegram UI.",), (
        Control("Bypass active-set, generation or confirmation precondition", "named stale action applies or clears unseen answer"),
    ))


def _v14():
    cases = []
    for point, expected in (
        ("ingress.before_commit", {"receipt_present": False, "event_present": False, "offset_advanced": False}),
        ("ingress.after_commit_before_return", {"receipt_present": True, "event_present": True, "exact_replay": True}),
        ("intent.after_commit", {"intent_present": True, "attempts": 0}),
        ("attempt.after_commit_before_return", {"attempts": 1, "state": "uncertain", "automatic_send": False}),
        ("delivery.after_commit_before_return", {"copy_lookup_and_binding_present": True, "exact_replay": True}),
        ("callback.before_ack", {"receipt_present": True, "event_present": True, "offset_advanced": False}),
        ("poller.before_offset", {"receipt_present": True, "event_present": True, "exact_replay": True}),
        ("consumption.before_commit", {"ack_present": False, "pending_consumption": True}),
        ("consumption.after_commit_before_return", {"ack_present": True, "replay_result": False}),
        ("consumer.after_effect_before_ack", {"external_effect_may_have_happened": True, "pending_consumption": True}),
    ):
        cases.append(Case(point, {"fault": point, "dialects": DIALECTS}, expected, SCHEDULES["crash"]))
    return Vector("V14", ("T12",), tuple(cases), (
        "Kill a real child at each committed/uncommitted boundary; observe through a new engine, not process-local state.",
        "Receipt/result/ingress are one commit. No run wake is supplied by this library, before or after commit.",
    ), (Control("Move offset/ack before commit", "no pre-commit success/offset ordering assertion fails"),
        Control("Split ingress and append commits", "atomic presence of ingress, receipt and result/event fails")))


def _v15():
    cases = []
    for path, recompute in product(PUBLIC_STORE_PATHS, (False, True)):
        cases.append(Case(f"applied_event_{path}_{recompute}",
                          {"path": path, "receipt_columns": {"event_id": NO_EVENT}, "recompute_result_digest": recompute},
                          {"exception": "ClarificationIntegrityError", "guard": "receipt.event_identity" if recompute else "receipt.result",
                           "durable_changes": 0}))
    for name, columns in (
        ("reason", {"code": "already_confirmed"}), ("guard", {"guard": "confirmation.once"}),
        ("revision", {"expected_revision": 2, "revision": 2}),
    ):
        cases.append(Case(f"retained_{name}", {"path": "append_receipt", "receipt_columns": columns},
                          {"exception": "ClarificationIntegrityError", "guard": "receipt.result", "durable_changes": 0}))
    cases.append(Case("unused_copy", {"copy_columns": {"message_id": "599"}, "new_answer_copy": "599"},
                      {"exception": "ClarificationIntegrityError", "guard": "copy.digest", "new_receipts": 0}))
    for path in ("delivery", "copies", "start_attempt", "current_generation", "question_ids", "answered", "receipt"):
        for damage in ("substitute_send_binding", "substitute_delivery_lookup", "delete_required_delivery_row"):
            cases.append(Case(f"{path}_{damage}", {"new_read_path": path, "damage": damage},
                              {"exception": "ClarificationIntegrityError", "new_receipts": 0, "attempt_delta": 0}))
    for damage in ("delete_required_prior_receipt", "alter_record_hash", "truncate_history", "remove_required_revision"):
        cases.append(Case(damage, {"setup": "V01 through answer", "damage": damage},
                          {"exception": "ClarificationIntegrityError", "replacement_history": False,
                           "new_prompt": False, "durable_changes": 0}))
    cases.append(Case("fork_remapped_gate_ids", {"other_stream": c.StreamKey("project:synthetic-fork", s.BRIEF_SHA),
                                               "remapped_gate_event": "event:synthetic-fork/1"},
                      {"source_authority_inherited": False, "clarification_identity_is_gate_id": False}))
    cases.append(Case("retention_missing_required_receipt", {"delete_after_ack": "authoritative receipt sidecar"},
                      {"exception": "ClarificationIntegrityError", "fabricated_history": False}))
    cases.append(Case("clean", {"damage": None}, {"exact_replay": True, "durable_changes": 0}))
    return Vector("V15", ("T13",), tuple(cases), (
        "The original nine damage vectors are seven applied-result paths, retained-result replay and unused-copy-before-new-receipt.",
        "Recomputed digest control must reach event-identity equality, not merely fail the outer checksum.",
        "No replacement history/hash repair; coherent trusted rewrite, whole rollback/erasure remain unauthenticated.",
    ), (Control("Remove corresponding result/copy/binding check", "specific wrong replay or application passes, not an arbitrary exception"),))


def _v16():
    cases = [Case("reorder", {"candidate": s.profile(s.COMPOSITION_UNKNOWN, reverse=True)},
                  {"question_id": Q, "history_reused": True, "new_prompt": False})]
    for name, change in (
        ("question", {"question": "Must it work offline today?"}),
        ("decisions_ab", {"decisions_affected": ["offline storage", "sync design"]}),
        ("decisions_ba", {"decisions_affected": ["sync design", "offline storage"]}),
        ("field_absent", {}),
    ):
        unknown = {**s.COMPOSITION_UNKNOWN, **change}
        if name == "field_absent":
            del unknown["field"]
        cases.append(Case(name, {"candidate": s.profile(unknown)},
                          {"question_id": c.question_id(s.BRIEF_SHA, unknown), "old_history_kept": True,
                           "old_answer_migrated": False}))
    cases.append(Case("drop_reintroduce", {"candidates": (s.profile(), s.composition_profile())},
                      {"question_id": Q, "answered_on_reintroduction": True, "new_prompt": False}))
    return Vector("V16", ("T05",), tuple(cases), ("Only exact metadata identity is reused; no inferred equivalence/model call.",), (
        Control("Bind by text alone or discard absent history", "changed-metadata ID or reintroduced-answer assertion fails"),
    ))


def _v17():
    first, second = confirmation_receipt(), answer_receipt("602")
    bundle = reference_inputs(expected_answer_event(first, ANSWER), expected_answer_event(second, ANSWER))
    cases = [Case("exact", bundle, {"references_ok": True, "meaning_status": "NOT_EVALUATED"})]
    for name, location, value in (
        ("source", "clarification_source.source_id", "clarifications-sha256:" + WRONG_HASH),
        ("record", "clarification_source.record_sha256", WRONG_HASH),
        ("missing_ids", "constraints.0.source.event_ids", []),
        ("reordered_ids", "constraints.0.source.event_ids", list(reversed(bundle["active_event_ids"]))),
        ("duplicate_ids", "constraints.0.source.event_ids", [c.event_id(first), c.event_id(first)]),
        ("wrong_answer", "constraints.0.source.answer", "Yes"),
        ("wrong_question", "constraints.0.source.question", "Must it work offline today?"),
        ("old_v2_quote", "constraints.0.source", {"kind": "quote", "quote": ANSWER}),
    ):
        cases.append(Case(name, {"base": bundle, "replace_path": location, "value": value},
                          {"references_ok": False, "source_or_reference_path_errors": True, "original_unchanged": True}))
    correction = answer_receipt("603", "No: online only.", intent="correct", reason="Typo.",
                                supersedes=(c.event_id(first), c.event_id(second)))
    corrected = foundation.append_event(bundle["record"], expected_answer_event(correction, "No: online only."))
    unresolved = foundation.create_record(s.composition_profile(), s.BRIEF)
    model_event = {**expected_answer_event(answer_receipt("607"), ANSWER),
                   "actor": {"kind": "model", "ref": "model:synthetic"},
                   "source": {"kind": "model_output", "ref": "candidate:synthetic/1"}}
    model_only = foundation.append_event(unresolved, model_event)
    for name, record in (("old_answer_after_correction", corrected), ("unresolved_reference", unresolved),
                         ("model_only_reference", model_only)):
        # Rebind only the source header so the intended answer/active-event check is reached.
        mapping = foundation.compose_supplement(record, s.BRIEF)["source_mapping"]
        candidate = s.clarified_candidate(s.composition_profile(), source_mapping=mapping, question_id=Q,
                                          question=QUESTION, answer=ANSWER, event_ids=bundle["active_event_ids"])
        cases.append(Case(name, {"record": record, "candidate": candidate},
                          {"references_ok": False, "source_consumption_allowed": False, "meaning_status": "NOT_EVALUATED"}))
    for name, schema in (("v2_validator", "contract.v2.schema.json"), ("missing_validator", None)):
        cases.append(Case(name, {"base": bundle, "validator_schema": schema},
                          {"source_consumption_allowed": False, "meaning_status": "NOT_EVALUATED"}))
    negative = answer_receipt("606", "no")
    cases.append(Case("negative_answer_reference_only", reference_inputs(expected_answer_event(negative, "no")),
                      {"references_ok": True, "meaning_status": "NOT_EVALUATED", "adoption_proven": False}))
    return Vector("V17", ("T15",), tuple(cases), (
        "Use A's actual shipped clarified validator, never a same-labelled substitute; no conversion of original v2 candidate.",
        "Matching source references can accompany an unjustified C1; meaning stays NOT_EVALUATED, frozen score NOT_MEASURED.",
    ), (Control("Omit an active ID or reuse old answer after correction", "real reference check fails at its deciding source path"),))


def _v18():
    return Vector("V18", ("T16",), (
        Case("moved_before_return", {"barrier": "check.before_current_recheck", "new_answer": answer_receipt()},
             {"stale_refusal": True, "current_check_returned": False}, SCHEDULES["stale_consumption"]),
        Case("new_stale_ack", {"barrier": "consumption.before_current_cas", "checked_revision": 2,
                               "new_answer": answer_receipt()},
             {"code": "revision_conflict", "consumption_writes": 0}, SCHEDULES["stale_consumption"]),
        Case("kept_ack_after_move", {"ack_already_kept": True, "stream_has_moved": True},
             {"result": False, "consumption_writes": 0, "new_candidate_validation": False}),
        Case("paused_off_cancelled", {"caller_states": ("paused", "off", "cancelled"), "denied": ("send", "acknowledge")},
             {"denied_effects": 0, "run_signals": 0, "recording_can_continue_if_authorized": True}),
        Case("unrelated_unknown", {"unresolved_question": c.question_id(s.BRIEF_SHA, s.base_unknown("goals"))},
             {"blanket_refusal": False, "outstanding_visible": True}),
        Case("mutated_checked_report", {"edit": "references_ok=True on a failing checked snapshot"},
             {"new_ack_allowed": False, "real_checker_revalidated": True}),
    ), ("Acknowledgement records supplied consumption only; no wake/external effect or renewed acceptance on replay.",), (
        Control("Drop current-revision predicate", "old snapshot is incorrectly newly acknowledged"),
        Control("Trust mutable report success flag", "edited failing report incorrectly authorizes a new acknowledgement"),
    ))


def _v19():
    return Vector("V19", ("T03", "T12"), (
        Case("accepted_capture_final_refusal", {"capture_status": "accepted", "final_status": "refused",
                                               "point": "ingress.before_application", "boundary": "trusted M0/M3 port",
                                               "receipt": answer_receipt("603", intent="correct", supersedes=(NO_EVENT,), reason="Typo."),
                                               "ingress_update": pulled_updates()[0]},
             {"diagnostic_committed": True, "authoritative_key": False, "authoritative_text": False,
              "ack_text": "Not applied.", "prompts": 0, "offset_after_commit": True}),
        Case("database_down", {"raise_at": "ingress.before_commit", "error": RuntimeError},
             {"propagate": True, "offset_advanced": False, "success_ack": False}),
        Case("policy_down", {"raise_at": "authority.require", "error": RuntimeError},
             {"propagate": True, "offset_advanced": False, "success_ack": False}),
        Case("ordinary_contract_refusal", {"raise_at": "keep_receipt", "error": c.ContractRefusal},
             {"propagate": True, "offset_advanced": False}),
        Case("existing_fake_protocol", {"suite": "tests/test_integrations/test_telegram_clarifications.py"},
             {"original_assertions_unchanged": True}),
    ), ("Only the new typed committed-application refusal is caught; capture counters do not prove application.",
        "The unknown-target correction is a trusted-port test of the bridge, not a Telegram correction UI or a forged raw-update route."), (
        Control("Return a successful tuple for diagnostic-only refusal", "ack text, prompt count or key-reservation assertion fails"),
        Control("Catch all ContractRefusal/Exception", "outage propagation and held offset assertion fails"),
    ))


def _v20():
    return Vector("V20", ("T01", "T17"), (
        Case("unused_import_constructor", {"injected_spies": ("store", "transport", "authority", "validator")},
             {"client_constructions": 0, "get_me": 0, "pull": 0, "send": 0, "default_engine": 0,
              "model_calls": 0, "source_discovery": 0, "registrations": 0, "run_signals": 0}),
        Case("ordinary_unbound", {"Poller.clarifications": None, "TelegramService.clarifications": None},
             {"ordinary_behavior_unchanged": True}),
        Case("explicit_present", {"caller": initial_input(), "presentation": presentation()},
             {"only_supplied_ports_called": True}),
        Case("missing_or_denied_authority", {"authority_variants": (None, "deny")},
             {"enabled_implicitly": False, "effects": 0}),
    ), ("Separate ordinary import/schema dependency loading from operational purity; no cold-import purity claim.",), (
        Control("Use a default engine/provider/allow-all authority", "corresponding construction/effect spy becomes nonzero"),
    ))


def vectors() -> tuple[Vector, ...]:
    """Fresh, ordered source fixtures; this function executes no acceptance vector."""
    return (_v01(), _v02(), _v03(), _v04(), _v05(), _v06(), _v07(), _v08(), _v09(), _v10(),
            _v11(), _v12(), _v13(), _v14(), _v15(), _v16(), _v17(), _v18(), _v19(), _v20())
