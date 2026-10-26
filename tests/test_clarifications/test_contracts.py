"""Frozen M0 clarification contracts (Temper #204).

The combined happy path comes first, then the M0 refusal cases from #202's
ACCEPTANCE.json (T03, T06, T08, T11, T13, T17), then one literal case for every
guard, field check and argument check, each with its bite: the check is removed
in memory (an AST copy, never a file) and its case must then fail. Synthetic
data only: no model, network, database, clock, environment or real person.
"""

import ast
import builtins
import dataclasses
import hashlib
import importlib
import importlib.util
import io
import json
import os
import socket
import sqlite3
import subprocess
import time
import types
from pathlib import Path

import pytest

from temper_ai.clarifications import contracts as C

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path(C.__file__).read_text(encoding="utf-8")
DOC = ROOT / "docs" / "clarifications" / "contract.md"
FOUNDATION = ROOT / "configs" / "architecture" / "bin" / "context_profile_clarifications.py"


def _foundation():
    spec = importlib.util.spec_from_file_location("m0_foundation_clarifications", FOUNDATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


F = _foundation()  # the unchanged #308 foundation, loaded by path as configs/ scripts are


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canon(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def cyclic():
    loop = []
    loop.append(loop)
    return loop


BRIEF = "A synthetic booking tool.\r\n  Keep this exact: café, 東京, trailing space. \n"
BRIEF_SHA = sha(BRIEF)
UNKNOWN = {
    "question": "Must it work offline?", "why_it_matters": "Changes storage and sync.",
    "decisions_affected": ["client storage", "sync design"], "material": True, "field": "constraints",
}
UNKNOWN_2 = {
    "question": "Who may approve refunds?", "why_it_matters": "Changes roles and audit.",
    "decisions_affected": ["permissions"], "material": False, "field": "goals",
}
PROFILE = {"contract": "context_profile/v2", "brief_sha256": BRIEF_SHA, "unknowns": [UNKNOWN, UNKNOWN_2]}
RECORD = F.create_record(PROFILE, BRIEF)
ANSWER = "  Yes: offline first.\r\nSync later — café 東京.  "
TYPED = "Not sure yet;\nask me after the pilot.\n"
NAMESPACE = "temper-clarify:synthetic/arch-stage-context"
POLICY = "responder-policy:synthetic/owner-only"
AUTHORITY = "authority:synthetic/m0-tests"
CANDIDATE_REF = "temper-run:synthetic/stage1"
BOT = "synthetic-bot-1"
CHAT = "synthetic-chat-1"
OWNER = "synthetic-user-1"
OTHER = "synthetic-user-2"
DROP = object()
WRONG = type("Wrong", (), {"__repr__": lambda self: "WRONG"})()


class World:
    """Valid synthetic objects built from one contracts module: the real one or a mutant."""

    def __init__(self, m):
        self.m = m
        self.qid = m.question_id(BRIEF_SHA, UNKNOWN)
        self.qid2 = m.question_id(BRIEF_SHA, UNKNOWN_2)
        self.stream = m.StreamKey(NAMESPACE, BRIEF_SHA)
        self.transport = m.TransportNamespace("telegram", BOT)
        self.presentation = self.present(self.qid, UNKNOWN)
        self.presentation2 = self.present(self.qid2, UNKNOWN_2)

    def present(self, question, unknown, generation=1):
        m = self.m
        return m.Presentation(self.stream, question, m.metadata_sha256(unknown), generation, POLICY, self.transport, CHAT)

    def action(self, action_id="501", kind="message", **changes):
        fields = {"transport": self.transport, "chat_id": CHAT, "kind": kind, "action_id": action_id}
        return self.m.ActionIdentity(**{**fields, **changes})

    def binding(self, presentation=None, message_id="500", **changes):
        p = presentation or self.presentation
        fields = {
            "stream_id": p.stream.stream_id, "question_id": p.question_id, "presentation_id": p.presentation_id,
            "generation": p.generation, "message_id": message_id,
        }
        return self.m.PresentationBinding(**{**fields, **changes})

    def responder(self, sender=OWNER, **changes):
        fields = {"policy_ref": POLICY, "sender_id": sender, "decision": "authorised", "basis": "responder_policy"}
        return self.m.ResponderDecision(**{**fields, **changes})

    def receipt(self, sender=OWNER, **changes):
        text = changes.get("text", ANSWER)
        fields = {
            "ingress": "provider_pull", "action": self.action(), "update_id": 9001, "sender_id": sender,
            "sender_is_bot": False, "forwarded": False, "text": ANSWER,
            "text_sha256": sha(text) if type(text) is str else sha(ANSWER),
            "binding": self.binding(), "responder": self.responder(sender), "intent": "answer", "disposition": "answered",
        }
        return self.m.ActionReceipt(**{**fields, **changes})

    def typed(self, sender=OWNER, **changes):
        """A typed reply without a disposition: the exact text a later button press confirms."""
        return self.receipt(sender, **{"action": self.action("601"), "update_id": 9002, "text": TYPED,
                                       "disposition": None, **changes})

    def confirms(self, typed=None, **changes):
        typed = typed or self.typed()
        fields = {"action": typed.action, "author_id": typed.sender_id, "text_sha256": typed.text_sha256}
        return self.m.ConfirmedText(**{**fields, **changes})

    def callback(self, sender=OWNER, **changes):
        return self.receipt(sender, **{"action": self.action("cb-701", "callback"), "update_id": 9003, "text": "",
                                       "callback_data": "clar:answered", **changes})

    def reopen(self, **changes):
        return self.callback(**{"intent": "reopen", "disposition": None, "callback_data": "clar:reopen",
                                "reason": "Plans changed; ask again.", "seen_revision": 1, **changes})

    def validate(self, receipt, **changes):
        fields = {"presentation": self.presentation, "copies": {"500"}, "current_generation": 1,
                  "question_ids": [self.qid, self.qid2]}
        return self.m.validate_receipt(receipt, **{**fields, **changes})

    def accepted(self):
        return self.validate(self.receipt())

    def validation(self, **changes):
        return dataclasses.replace(self.accepted(), **changes)

    def event_json(self, **changes):
        return canon({**json.loads(self.accepted().event_json), **changes})

    def applied(self):
        r = self.receipt()
        m = self.m
        return m.AppendResult("applied", self.stream.stream_id, r.action.key, m.receipt_sha256(r), 0, 1, m.event_id(r))

    def result(self, status, code=None, expected=0, revision=0):
        r = self.receipt()
        m = self.m
        code = None if code is None else m.RefusalCode(code)
        return m.AppendResult(status, self.stream.stream_id, r.action.key, m.receipt_sha256(r), expected, revision, None, code)

    def caller(self, candidate=PROFILE, record=RECORD, **changes):
        record_json = None if record is None else canon(record)
        fields = {
            "stream": self.stream, "original_text": BRIEF, "original_sha256": BRIEF_SHA,
            "candidate_json": canon(candidate), "candidate_sha256": sha(canon(candidate)), "candidate_ref": CANDIDATE_REF,
            "prior_revision": 0 if record is None else 1, "prior_record_json": record_json,
            "prior_record_sha256": None if record_json is None else sha(record_json),
            "question_ids": (self.qid, self.qid2), "source_authority_ref": AUTHORITY, "transport": self.transport,
            "chat_id": CHAT, "responder_policy_ref": POLICY, "affected_decisions": ("client storage",),
        }
        return self.m.CallerInput(**{**fields, **changes})

    def sidecar(self, path=(), value=None, receipt=None):
        data = json.loads(self.m.receipt_json(receipt or self.receipt()))
        if path:
            node = data
            for key in path[:-1]:
                node = node[key]
            if value is DROP:
                del node[path[-1]]
            else:
                node[path[-1]] = value
        return canon(data)


def states(record):
    return {state["question_id"]: state for state in F.project_states(record)}


def outcome(m, case):
    """What one literal case does against a module: raised, a validation status, ok, or an error."""
    try:
        result = case(World(m))
    except m.ContractRefusal as refusal:
        return ("raised", refusal.code.value, refusal.guard, refusal.where)
    except Exception as error:  # a mutant may break in any way; that also fails the case
        return ("error", type(error).__name__, None, None)
    if isinstance(result, m.ReceiptValidation) and result.status != "accepted":
        return (result.status, result.code.value, result.guard, None)
    return ("ok", None, None, None)


# --- the combined happy path ----------------------------------------------------


def test_happy_path_from_caller_to_supplement_through_the_unchanged_foundation():
    w = World(C)
    # The caller is handed exact data, never paths. A first creation is revision 0.
    caller = w.caller(record=None)
    assert caller.candidate() == PROFILE and caller.prior_record() is None
    record = F.create_record(caller.candidate(), caller.original_text)
    assert [q["question_id"] for q in record["questions"]] == sorted([w.qid, w.qid2])
    # One persisted presentation per selected question, bound to stream, responders and chat.
    first = caller.presentation(w.qid, C.metadata_sha256(UNKNOWN), 1)
    second = caller.presentation(w.qid2, C.metadata_sha256(UNKNOWN_2), 1)
    assert (first, second) == (w.presentation, w.presentation2)
    known = {"current_generation": 1, "question_ids": caller.question_ids}

    # 1. A typed reply with an explicit disposition is accepted with its exact text.
    typed = w.receipt()
    one = C.validate_receipt(typed, presentation=first, copies={"500"}, **known)
    assert (one.status, one.code, one.guard) == ("accepted", None, None)
    actor = {"kind": "human", "ref": "telegram-user:" + OWNER}
    source = {"kind": "human_response", "ref": "clarification-receipt:" + C.receipt_sha256(typed)}
    assert one.event() == {
        "event_id": C.event_id(typed), "question_id": w.qid, "kind": "answer", "answer": ANSWER,
        "disposition": "answered", "supersedes": [], "actor": actor, "source": source,
    }

    # 2. Typed text without a disposition is kept, not applied; its author's button press applies it.
    draft = w.typed(binding=w.binding(second, "600"))
    kept = C.validate_receipt(draft, presentation=second, copies={"600"}, **known)
    assert (kept.status, kept.code, kept.event()) == ("retained", C.RefusalCode.NO_EXPLICIT_DISPOSITION, None)
    press = w.callback(binding=w.binding(second, "600"), disposition="deferred", callback_data="clar:deferred",
                       confirms=w.confirms(draft))
    two = C.validate_receipt(press, presentation=second, copies={"600"}, confirmed=draft, **known)
    assert two.status == "accepted" and two.event()["answer"] == TYPED and two.event()["actor"] == actor
    assert C.receipt_from_json(C.receipt_json(press)).confirms.action == draft.action  # both actions linked

    # 3. The store appends through the unchanged foundation; each applied append moves the revision by one.
    after = F.append_event(F.append_event(record, one.event()), two.event())
    applied = C.AppendResult("applied", w.stream.stream_id, typed.action.key, one.receipt_sha256, 0, 1, one.event_id)
    assert (applied.revision, applied.event_id) == (1, C.event_id(typed))

    # 4. An exact replay keeps its ID and changes nothing; a changed body under that identity is refused.
    assert C.validate_receipt(typed, presentation=first, copies={"500"}, **known) == one
    assert C.check_replay(typed, typed) is True and F.append_event(after, one.event()) == after
    edited = dataclasses.replace(typed, text="No.", text_sha256=sha("No."))
    assert C.event_id(edited) == one.event_id
    with pytest.raises(C.ContractRefusal) as changed:
        C.check_replay(typed, edited)
    assert changed.value.code is C.RefusalCode.CHANGED_BODY

    # 5. Projection and supplement keep the exact text and name each receipt as its source.
    now = states(after)
    assert (now[w.qid]["state"], now[w.qid]["answer"]) == ("answered", ANSWER)
    assert (now[w.qid2]["state"], now[w.qid2]["answer"]) == ("deferred", None)
    output = F.compose_supplement(after, BRIEF)
    assert output["original_brief"] == BRIEF
    answers = json.loads(output["supplement"])["answers"]
    assert [(a["answer"], a["attributions"]) for a in answers] == [
        (ANSWER, [{"event_id": one.event_id, "actor": actor, "source": source}]),
    ]

    # 6. The sidecar text is what source.ref names, and it decodes to the same receipt.
    for receipt in (typed, draft, press):
        assert C.receipt_from_json(C.receipt_json(receipt)) == receipt
        assert C.receipt_sha256(receipt) == sha(C.receipt_json(receipt))

    # 7. The next run is handed the stored record and reuses it without asking again.
    later = w.caller(record=after, prior_revision=2)
    assert later.prior_record() == after
    assert F.create_record(later.candidate(), BRIEF, previous=later.prior_record()) == after
    supplement_sha256 = output["source_mapping"]["supplement_sha256"]
    consumed = C.consumption_id(w.stream.stream_id, 2, supplement_sha256)
    assert consumed == C.consumption_id(w.stream.stream_id, 2, supplement_sha256)
    assert consumed.startswith("c-") and consumed != C.consumption_id(w.stream.stream_id, 1, supplement_sha256)


# --- identities -----------------------------------------------------------------


def known_answers(w):
    m = w.m
    receipt = w.receipt()
    return {
        "question_id": w.qid,
        "stream_id": w.stream.stream_id,
        "presentation_id": w.presentation.presentation_id,
        "action_key": receipt.action.key,
        "event_id": m.event_id(receipt),
        "receipt_sha256": m.receipt_sha256(receipt),
        "consumption_id": m.consumption_id(w.stream.stream_id, 1, BRIEF_SHA),
    }


KNOWN_ANSWERS = {
    "question_id": "q-9518697a1297774edca1a275563fea6ee94cfc9f4611463124cf81be445a0bcb",
    "stream_id": "s-8c3a3ec2d0f829e9eabb9da81eeeae433fbb5123c02ebbd3ef24a843cc239219",
    "presentation_id": "p-d81eb44f95f4d7b7b9404f2a787e462ea0dc4ed0ba27a4330e0b10448c4d7269",
    "action_key": "a-ab50674b2b765e0bd2e9253fc1ea42312454f0a11d331e8995ebe72368e5d6a1",
    "event_id": "e-e3a2fec91ac9dccc82be934a0e9a5866a1e9ecbc247a04a395b0e390ba9e3134",
    "receipt_sha256": "cc79f8a6ac6f40370c262fc7a944c89e3d15d7bbccbb426fcd61cfce23ec9fd7",
    "consumption_id": "c-8ba138065014e94f5d0748996acdc7d2fcf2673309dba1e94dc9c7e64056341c",
}


def test_ids_follow_the_documented_recipes_and_known_answers():
    w = World(C)

    def digest(identity, body):
        return sha(canon({"contract": "temper_clarification_loop/v1", "identity": identity, "body": body}))

    transport = {"transport": "telegram", "bot_id": BOT}
    action = {"transport": transport, "chat_id": CHAT, "kind": "message", "action_id": "501"}
    question = sha(canon({"contract": "context_profile_clarifications/v1", "brief_sha256": BRIEF_SHA, "unknown": UNKNOWN}))
    stream = digest("stream", {"namespace": NAMESPACE, "brief_sha256": BRIEF_SHA})
    presentation = digest("presentation", {
        "stream_id": "s-" + stream, "question_id": "q-" + question, "metadata_sha256": sha(canon(UNKNOWN)),
        "generation": 1, "responder_policy_ref": POLICY, "transport": transport, "chat_id": CHAT,
    })
    binding = {"stream_id": "s-" + stream, "question_id": "q-" + question, "presentation_id": "p-" + presentation}
    receipt = w.receipt()
    assert w.qid == "q-" + question
    assert w.stream.stream_id == "s-" + stream
    assert w.presentation.presentation_id == "p-" + presentation
    assert receipt.action.key == "a-" + digest("action", action)
    assert C.event_id(receipt) == "e-" + digest("event", {"action": action, "binding": binding})
    assert C.consumption_id("s-" + stream, 1, BRIEF_SHA) == "c-" + digest(
        "consumption", {"stream_id": "s-" + stream, "revision": 1, "supplement_sha256": BRIEF_SHA})
    assert known_answers(w) == KNOWN_ANSWERS


def test_question_ids_match_the_foundation_and_the_namespace_stays_in_the_stream_key():
    derived = [question["question_id"] for question in F.derive_questions(PROFILE, BRIEF)]
    assert derived == sorted(C.question_id(BRIEF_SHA, unknown) for unknown in (UNKNOWN, UNKNOWN_2))
    reordered = {**UNKNOWN, "decisions_affected": list(reversed(UNKNOWN["decisions_affected"]))}
    assert C.question_id(BRIEF_SHA, reordered) != C.question_id(BRIEF_SHA, UNKNOWN)
    assert C.metadata_sha256(reordered) != C.metadata_sha256(UNKNOWN)
    other = C.StreamKey("temper-clarify:synthetic/another-project", BRIEF_SHA)
    assert other.stream_id != World(C).stream.stream_id  # same brief, other authority: separate history


def test_event_ids_are_stable_under_exact_replay_and_distinct_per_genuine_action():  # T08, T10
    w = World(C)
    first = w.receipt()
    second = w.receipt(action=w.action("502"), update_id=9010)
    assert first.text == second.text and C.event_id(first) != C.event_id(second)
    assert C.check_replay(first, second) is False
    assert C.event_id(w.receipt()) == C.event_id(first) == w.validate(w.receipt()).event_id
    both = F.append_event(F.append_event(RECORD, w.validate(first).event()), w.validate(second).event())
    assert states(both)[w.qid]["state"] == "answered"
    assert sorted(states(both)[w.qid]["active_event_ids"]) == sorted([C.event_id(first), C.event_id(second)])
    for changes in (
        {"text": "Changed.", "text_sha256": sha("Changed.")}, {"disposition": "deferred"}, {"update_id": 9999},
        {"binding": w.binding(message_id="502")}, {"binding": w.binding(w.presentation2, "600")},
    ):
        with pytest.raises(C.ContractRefusal) as refused:
            C.check_replay(first, dataclasses.replace(first, **changes))
        assert refused.value.code is C.RefusalCode.CHANGED_BODY


# --- the M0 refusal cases (ACCEPTANCE.json) ---------------------------------------


@pytest.mark.parametrize("ingress", C.INGRESSES)
def test_only_the_verified_provider_ingress_yields_a_human_event(ingress):  # T03, T07
    w = World(C)
    result = w.validate(w.receipt(ingress=ingress))
    if ingress == C.VERIFIED_INGRESS:
        assert result.status == "accepted" and result.event()["actor"]["kind"] == "human"
        return
    code = C.RefusalCode.MODEL_NOT_HUMAN if ingress == C.MODEL_INGRESS else C.RefusalCode.UNVERIFIED_INGRESS
    assert (result.status, result.code, result.event()) == ("refused", code, None)


ORDINALS = [1, "1", "#2", "Q3", "q-4", "question 5.", "6)"]
ORDINAL_SITES = {
    "presentation": lambda w, ordinal: w.present(ordinal, UNKNOWN),
    "binding": lambda w, ordinal: w.binding(question_id=ordinal),
    "caller": lambda w, ordinal: w.caller(question_ids=(ordinal,)),
    "caller.presentation": lambda w, ordinal: w.caller().presentation(ordinal, BRIEF_SHA, 1),
    "validate": lambda w, ordinal: w.validate(w.receipt(), question_ids=[ordinal]),
}


@pytest.mark.parametrize("ordinal", ORDINALS)
@pytest.mark.parametrize("site", sorted(ORDINAL_SITES))
def test_a_displayed_ordinal_is_never_a_question_id(site, ordinal):
    with pytest.raises(C.ContractRefusal) as refused:
        ORDINAL_SITES[site](World(C), ordinal)
    assert refused.value.code is C.RefusalCode.ORDINAL_AS_QUESTION_ID


def test_a_confirmer_never_becomes_the_author_of_someone_elses_text():  # T06
    w = World(C)
    typed = w.typed()  # written by OWNER
    other = w.validate(w.callback(OTHER, confirms=w.confirms(typed)), confirmed=typed)
    assert (other.status, other.code, other.event()) == ("refused", C.RefusalCode.CONFIRMER_NOT_AUTHOR, None)
    claimed = w.validate(w.callback(OTHER, confirms=w.confirms(typed, author_id=OTHER)), confirmed=typed)
    assert (claimed.status, claimed.code) == ("refused", C.RefusalCode.BINDING_MISMATCH)
    own = w.validate(w.callback(confirms=w.confirms(typed)), confirmed=typed)
    assert own.status == "accepted"
    assert (own.event()["actor"]["ref"], own.event()["answer"]) == ("telegram-user:" + OWNER, TYPED)


def test_missing_original_record_or_authority_is_refused_never_replaced():  # T13, T17
    w = World(C)
    truncated = canon({**RECORD, "questions": RECORD["questions"][:1]})
    for code, changes in {
        C.RefusalCode.MISSING_ORIGINAL: {"original_text": None},
        C.RefusalCode.MISSING_RECORD: {"prior_revision": 3, "prior_record_json": None, "prior_record_sha256": None},
        C.RefusalCode.MISSING_AUTHORITY: {"source_authority_ref": None},
        C.RefusalCode.HASH_MISMATCH: {"prior_record_json": truncated},
    }.items():
        with pytest.raises(C.ContractRefusal) as refused:
            w.caller(**changes)
        assert refused.value.code is code
    unlinked = w.validate(w.callback(confirms=w.confirms()))
    assert (unlinked.status, unlinked.code) == ("refused", C.RefusalCode.MISSING_RECORD)


@pytest.mark.parametrize("text", ["y", "  padded both sides  ", "line one\r\nline two\n", "café 東京 ok",
                                  "zero\u200bwidth", "tab\tinside\n"])
def test_exact_text_is_kept_byte_for_byte(text):  # T06
    w = World(C)
    receipt = w.receipt(text=text)
    result = w.validate(receipt)
    assert result.status == "accepted" and result.event()["answer"] == text
    assert C.receipt_from_json(C.receipt_json(receipt)).text == text
    assert states(F.append_event(RECORD, result.event()))[w.qid]["answer"] == text


@pytest.mark.parametrize("text", ["", " ", "\r\n\t", "\u00a0"])
def test_blank_text_is_kept_as_evidence_but_never_applied(text):  # T06, T07
    w = World(C)
    result = w.validate(w.receipt(text=text))
    assert (result.status, result.code, result.event()) == ("retained", C.RefusalCode.BLANK_TEXT, None)
    with pytest.raises(F.ClarificationError):  # the unchanged foundation agrees
        F.append_event(RECORD, {**w.accepted().event(), "answer": text})


def test_correction_and_reopen_follow_the_foundation_and_the_seen_snapshot():  # T11
    w = World(C)
    first = w.accepted()
    fix = w.receipt(action=w.action("503"), update_id=9020, intent="correct", supersedes=(first.event_id,),
                    reason="Typo.", text="No: online only.")
    fixed = w.validate(fix)
    assert fixed.event()["supersedes"] == [first.event_id] and fixed.event()["reason"] == "Typo."
    after = F.append_event(F.append_event(RECORD, first.event()), fixed.event())
    assert states(after)[w.qid]["answer"] == "No: online only."
    assert states(after)[w.qid]["active_event_ids"] == [fixed.event_id]
    # Another question moved the revision since; the answers the person saw are unchanged.
    seen = w.reopen(seen_revision=2, seen_active_event_ids=(fixed.event_id,))
    assert C.check_reopen_precondition(seen, revision=3, active_event_ids=[fixed.event_id]) is None
    opened = w.validate(seen).event()
    assert opened["kind"] == "reopen" and "answer" not in opened
    assert states(F.append_event(after, opened))[w.qid]["state"] == "reopened"
    unseen = C.event_id(w.receipt(action=w.action("504"), update_id=9030))
    with pytest.raises(C.ContractRefusal) as stale:
        C.check_reopen_precondition(seen, revision=3, active_event_ids=[fixed.event_id, unseen])
    assert stale.value.code is C.RefusalCode.STALE_REOPEN and stale.value.code in C.RETAINED_CODES


def test_append_results_say_what_happened_to_the_stream():  # T09, T12
    w = World(C)
    r = w.receipt()
    ids = (w.stream.stream_id, r.action.key, C.receipt_sha256(r))
    assert C.AppendResult("applied", *ids, 4, 5, C.event_id(r)).revision == 5
    assert C.AppendResult("retained", *ids, 4, 4, None, C.RefusalCode.STALE_PRESENTATION).event_id is None
    assert C.AppendResult("refused", *ids, 4, 4, None, C.RefusalCode.CHANGED_BODY).revision == 4
    assert C.AppendResult("refused", *ids, 4, 6, None, C.RefusalCode.REVISION_CONFLICT).revision == 6
    assert C.check_expected_revision(4, 4) is None
    with pytest.raises(C.ContractRefusal) as moved:
        C.check_expected_revision(4, 6)
    assert moved.value.code is C.RefusalCode.REVISION_CONFLICT


SIDECAR_PATHS = [
    (), ("receipt",), ("receipt", "action"), ("receipt", "action", "transport"), ("receipt", "binding"),
    ("receipt", "responder"), ("receipt", "confirms"), ("receipt", "confirms", "action"),
    ("receipt", "confirms", "action", "transport"),
]


@pytest.mark.parametrize("path", SIDECAR_PATHS, ids=lambda path: ".".join(("sidecar",) + path))
def test_the_sidecar_is_closed_at_every_level(path):
    w = World(C)
    text = w.sidecar((*path, "extra"), 1, receipt=w.callback(confirms=w.confirms()))
    with pytest.raises(C.ContractRefusal) as refused:
        C.receipt_from_json(text)
    assert (refused.value.code, refused.value.guard) == (C.RefusalCode.MALFORMED, "shape.closed")
    assert refused.value.where == ".".join(("sidecar",) + path)


def test_refusal_codes_are_a_closed_frozen_set():
    assert [code.value for code in C.RefusalCode] == [
        "malformed", "missing_original", "missing_record", "missing_authority", "hash_mismatch", "cross_context",
        "ordinal_as_question_id", "unknown_question", "binding_mismatch", "transport_mismatch",
        "unverified_ingress", "model_not_human", "bot_sender", "forwarded_message", "responder_not_authorised",
        "confirmer_not_author", "changed_body", "revision_conflict", "no_explicit_disposition", "blank_text",
        "stale_presentation", "stale_reopen",
    ]
    assert sorted(C.RETAINED_CODES) == ["blank_text", "no_explicit_disposition", "stale_presentation", "stale_reopen"]
    assert C.RETAINED_CODES | C.REFUSED_CODES == frozenset(C.RefusalCode)
    assert not C.RETAINED_CODES & C.REFUSED_CODES


# --- one literal case per guard, with its bite ------------------------------------

M = "malformed"
GUARDS = {
    # Shared shape checks.
    "shape.instance": ("raised", M, lambda w: w.m.ActionIdentity({"transport": "telegram"}, CHAT, "message", "501")),
    "shape.text": ("raised", M, lambda w: w.receipt(text=7)),
    "shape.utf8": ("raised", M, lambda w: w.m.metadata_sha256({"question": "\ud800"})),
    "shape.nonblank": ("raised", M, lambda w: w.receipt(intent="correct", supersedes=("e-prior",), reason=" \n")),
    "shape.pattern": ("raised", M, lambda w: w.m.StreamKey("no-scheme", BRIEF_SHA)),
    "shape.member": ("raised", M, lambda w: w.m.TransportNamespace("slack", BOT)),
    "shape.integer": ("raised", M, lambda w: w.present(w.qid, UNKNOWN, generation=0)),
    "shape.flag": ("raised", M, lambda w: w.receipt(sender_is_bot=0)),
    "shape.code": ("raised", M, lambda w: w.m.AppendResult(
        "refused", w.stream.stream_id, w.receipt().action.key, BRIEF_SHA, 1, 1, None, "changed_body")),
    "shape.tuple": ("raised", M, lambda w: w.receipt(intent="correct", supersedes=["e-prior"], reason="Fix.")),
    "shape.unique": ("raised", M, lambda w: w.receipt(intent="correct", supersedes=("e-prior", "e-prior"), reason="Fix.")),
    "shape.collection": ("raised", M, lambda w: w.validate(w.receipt(), copies="500")),
    "shape.closed": ("raised", M, lambda w: w.m.receipt_from_json(w.sidecar(("receipt",), DROP))),
    "shape.list": ("raised", M, lambda w: w.m.receipt_from_json(w.sidecar(("receipt", "supersedes"), {}))),
    "question.ordinal": ("raised", "ordinal_as_question_id", lambda w: w.binding(question_id="2")),
    # Plain JSON data and strict JSON text.
    "json.finite": ("raised", M, lambda w: w.m.metadata_sha256({"x": float("nan")})),
    "json.type": ("raised", M, lambda w: w.m.metadata_sha256({"x": {1, 2}})),
    "json.cycle": ("raised", M, lambda w: w.m.metadata_sha256({"x": cyclic()})),
    "json.key": ("raised", M, lambda w: w.m.metadata_sha256({1: "x"})),
    "json.object": ("raised", M, lambda w: w.m.metadata_sha256(["x"])),
    "json.syntax": ("raised", M, lambda w: w.m.receipt_from_json("{")),
    "json.duplicate_key": ("raised", M, lambda w: w.m.receipt_from_json('{"contract":"a","contract":"b"}')),
    "json.constant": ("raised", M, lambda w: w.m.receipt_from_json('{"contract":NaN}')),
    # Receipt shape.
    "confirms.kind": ("raised", M, lambda w: w.m.ConfirmedText(w.action("cb-1", "callback"), OWNER, sha(TYPED))),
    "receipt.text_sha256": ("raised", "hash_mismatch", lambda w: w.receipt(text_sha256=sha("other text"))),
    "receipt.callback_text": ("raised", M, lambda w: w.callback(text="typed")),
    "receipt.callback_payload": ("raised", M, lambda w: w.receipt(callback_data="clar:answered")),
    "receipt.confirms_callback": ("raised", M, lambda w: w.receipt(confirms=w.confirms())),
    "receipt.confirms_intent": ("raised", M, lambda w: w.reopen(confirms=w.confirms())),
    "receipt.correct_targets": ("raised", M, lambda w: w.receipt(intent="correct", reason="Fix.")),
    "receipt.targets_correct": ("raised", M, lambda w: w.receipt(supersedes=("e-prior",))),
    "receipt.reason_required": ("raised", M, lambda w: w.receipt(intent="correct", supersedes=("e-prior",))),
    "receipt.reopen_disposition": ("raised", M, lambda w: w.reopen(disposition="answered")),
    "receipt.reopen_snapshot": ("raised", M, lambda w: w.reopen(seen_revision=None)),
    "receipt.snapshot_reopen": ("raised", M, lambda w: w.receipt(seen_revision=1)),
    # The caller's input boundary (T13, T17).
    "caller.original_missing": ("raised", "missing_original", lambda w: w.caller(original_text=None)),
    "caller.original_hash": ("raised", "hash_mismatch", lambda w: w.caller(original_text=BRIEF.strip())),
    "caller.stream_brief": ("raised", "hash_mismatch", lambda w: w.caller(stream=w.m.StreamKey(NAMESPACE, sha("other")))),
    "caller.candidate_hash": ("raised", "hash_mismatch", lambda w: w.caller(candidate_sha256=sha("{}"))),
    "caller.candidate_contract": ("raised", M, lambda w: w.caller(candidate={**PROFILE, "contract": "context_profile/v1"})),
    "caller.candidate_brief": ("raised", "hash_mismatch", lambda w: w.caller(candidate={**PROFILE, "brief_sha256": sha("x")})),
    "caller.record_missing": ("raised", "missing_record", lambda w: w.caller(
        prior_revision=2, prior_record_json=None, prior_record_sha256=None)),
    "caller.record_unexpected": ("raised", M, lambda w: w.caller(prior_revision=0)),
    "caller.record_hash": ("raised", "hash_mismatch", lambda w: w.caller(prior_record_sha256=sha("{}"))),
    "caller.record_contract": ("raised", M, lambda w: w.caller(record={**RECORD, "contract": "other/v1"})),
    "caller.record_brief": ("raised", "hash_mismatch", lambda w: w.caller(record={**RECORD, "brief_sha256": sha("x")})),
    "caller.authority_missing": ("raised", "missing_authority", lambda w: w.caller(source_authority_ref=None)),
    "caller.question_selected": ("raised", "unknown_question", lambda w: w.caller().presentation(
        w.m.question_id(BRIEF_SHA, {**UNKNOWN, "material": False}), BRIEF_SHA, 1)),
    # Result objects are closed: an inconsistent one cannot be built.
    "validation.accepted": ("raised", M, lambda w: w.validation(code=w.m.RefusalCode.BLANK_TEXT, guard="text.blank")),
    "validation.unaccepted": ("raised", M, lambda w: w.validation(status="refused", event_id=None, event_json=None)),
    "validation.retained_code": ("raised", M, lambda w: w.validation(
        status="retained", code=w.m.RefusalCode.CHANGED_BODY, guard="replay.body", event_id=None, event_json=None)),
    "validation.refused_code": ("raised", M, lambda w: w.validation(
        status="refused", code=w.m.RefusalCode.BLANK_TEXT, guard="text.blank", event_id=None, event_json=None)),
    "validation.event_id": ("raised", "hash_mismatch", lambda w: w.validation(event_id="e-other")),
    "validation.event_source": ("raised", "hash_mismatch", lambda w: w.validation(event_json=w.event_json(
        source={"kind": "human_response", "ref": "clarification-receipt:" + sha("x")}))),
    "validation.event_human": ("raised", "model_not_human", lambda w: w.validation(event_json=w.event_json(
        actor={"kind": "model", "ref": "model:synthetic"}))),
    "validation.event_canonical": ("raised", M, lambda w: w.validation(
        event_json=json.dumps(json.loads(w.accepted().event_json)))),
    "append.applied": ("raised", M, lambda w: dataclasses.replace(w.applied(), revision=2)),
    "append.unapplied": ("raised", M, lambda w: w.result("refused")),
    "append.retained_code": ("raised", M, lambda w: w.result("retained", "changed_body")),
    "append.refused_code": ("raised", M, lambda w: w.result("refused", "blank_text")),
    "append.conflict_revision": ("raised", M, lambda w: w.result("refused", "revision_conflict", 3, 3)),
    "append.unchanged_revision": ("raised", M, lambda w: w.result("refused", "changed_body", 3, 4)),
    "sidecar.contract": ("raised", M, lambda w: w.m.receipt_from_json(w.sidecar(("contract",), "temper_clarification_loop/v0"))),
    "sidecar.canonical": ("raised", M, lambda w: w.m.receipt_from_json(json.dumps(json.loads(w.m.receipt_json(w.receipt()))))),
    # Provenance and responder authority (T03, T04): refused, only the diagnostic is kept.
    "provenance.model": ("refused", "model_not_human", lambda w: w.validate(w.receipt(ingress="model_output"))),
    "provenance.ingress": ("refused", "unverified_ingress", lambda w: w.validate(w.receipt(ingress="caller_label"))),
    "provenance.bot": ("refused", "bot_sender", lambda w: w.validate(w.receipt(sender_is_bot=True))),
    "provenance.forwarded": ("refused", "forwarded_message", lambda w: w.validate(w.receipt(forwarded=True))),
    "provenance.transport": ("refused", "transport_mismatch", lambda w: w.validate(w.receipt(
        action=w.action(transport=w.m.TransportNamespace("telegram", "synthetic-bot-2"))))),
    "provenance.chat": ("refused", "transport_mismatch", lambda w: w.validate(w.receipt(
        action=w.action(chat_id="synthetic-chat-2")))),
    "responder.subject": ("refused", "responder_not_authorised", lambda w: w.validate(w.receipt(responder=w.responder(OTHER)))),
    "responder.policy": ("refused", "responder_not_authorised", lambda w: w.validate(w.receipt(
        responder=w.responder(policy_ref="responder-policy:synthetic/anyone")))),
    "responder.basis": ("refused", "responder_not_authorised", lambda w: w.validate(w.receipt(
        responder=w.responder(basis="chat_membership")))),
    "responder.decision": ("refused", "responder_not_authorised", lambda w: w.validate(w.receipt(
        responder=w.responder(decision="denied")))),
    # Question and presentation binding (T04, T14, T17).
    "binding.stream": ("refused", "cross_context", lambda w: w.validate(w.receipt(binding=w.binding(
        stream_id=w.m.StreamKey("temper-clarify:synthetic/other", BRIEF_SHA).stream_id)))),
    "binding.question": ("refused", "binding_mismatch", lambda w: w.validate(w.receipt(binding=w.binding(question_id=w.qid2)))),
    "binding.presentation": ("refused", "binding_mismatch", lambda w: w.validate(w.receipt(binding=w.binding(
        presentation_id=w.presentation2.presentation_id)))),
    "binding.generation": ("refused", "binding_mismatch", lambda w: w.validate(w.receipt(binding=w.binding(generation=2)))),
    "binding.copy": ("refused", "binding_mismatch", lambda w: w.validate(w.receipt(binding=w.binding(message_id="999")))),
    "binding.known_question": ("refused", "unknown_question", lambda w: w.validate(w.receipt(), question_ids=[w.qid2])),
    "binding.future_generation": ("refused", "binding_mismatch", lambda w: w.validate(
        w.receipt(binding=w.binding(w.present(w.qid, UNKNOWN, 2))), presentation=w.present(w.qid, UNKNOWN, 2))),
    "binding.stale": ("retained", "stale_presentation", lambda w: w.validate(w.receipt(), current_generation=2)),
    # Confirmation of a typed message (T06).
    "confirm.missing": ("refused", "missing_record", lambda w: w.validate(w.callback(confirms=w.confirms()))),
    "confirm.unexpected": ("refused", M, lambda w: w.validate(w.receipt(), confirmed=w.typed())),
    "confirm.identity": ("refused", "binding_mismatch", lambda w: w.validate(
        w.callback(confirms=w.confirms(action=w.action("602"))), confirmed=w.typed())),
    "confirm.digest": ("refused", "hash_mismatch", lambda w: w.validate(
        w.callback(confirms=w.confirms(text_sha256=sha("other"))), confirmed=w.typed())),
    "confirm.author_recorded": ("refused", "binding_mismatch", lambda w: w.validate(
        w.callback(confirms=w.confirms(author_id=OTHER)), confirmed=w.typed())),
    "confirm.author": ("refused", "confirmer_not_author", lambda w: w.validate(
        w.callback(OTHER, confirms=w.confirms()), confirmed=w.typed())),
    # Explicit disposition and exact text (T06, T07): kept as evidence, never applied.
    "disposition.explicit": ("retained", "no_explicit_disposition", lambda w: w.validate(w.receipt(disposition=None))),
    "text.blank": ("retained", "blank_text", lambda w: w.validate(w.receipt(text=" \r\n\t"))),
    # Replay, reopen snapshot and CAS (T08, T09, T11).
    "replay.body": ("raised", "changed_body", lambda w: w.m.check_replay(w.receipt(), w.receipt(text="Changed."))),
    "reopen.intent": ("raised", M, lambda w: w.m.check_reopen_precondition(w.receipt(), revision=1, active_event_ids=[])),
    "reopen.revision": ("raised", "stale_reopen", lambda w: w.m.check_reopen_precondition(
        w.reopen(seen_revision=5), revision=3, active_event_ids=[])),
    "reopen.active_set": ("raised", "stale_reopen", lambda w: w.m.check_reopen_precondition(
        w.reopen(seen_active_event_ids=("e-a",)), revision=1, active_event_ids=["e-a", "e-b"])),
    "cas.revision": ("raised", "revision_conflict", lambda w: w.m.check_expected_revision(2, 3)),
}

FIELD_PREFIX = {
    "StreamKey": "stream", "TransportNamespace": "transport", "ActionIdentity": "action",
    "Presentation": "presentation", "PresentationBinding": "binding", "ResponderDecision": "responder",
    "ConfirmedText": "confirms", "ActionReceipt": "receipt", "CallerInput": "caller",
    "ReceiptValidation": "validation", "AppendResult": "append",
}
FIELD_BASES = {
    "StreamKey": lambda w: w.stream, "TransportNamespace": lambda w: w.transport,
    "ActionIdentity": lambda w: w.action(), "Presentation": lambda w: w.presentation,
    "PresentationBinding": lambda w: w.binding(), "ResponderDecision": lambda w: w.responder(),
    "ConfirmedText": lambda w: w.confirms(), "ActionReceipt": lambda w: w.receipt(),
    "CallerInput": lambda w: w.caller(), "ReceiptValidation": lambda w: w.accepted(),
    "AppendResult": lambda w: w.applied(),
}
FIELDS = [(name, field.name) for name in FIELD_PREFIX for field in dataclasses.fields(getattr(C, name))]

ARGS = {
    ("_match", "question_id.brief_sha256"): ("shape.pattern", lambda w: w.m.question_id("A" * 64, UNKNOWN)),
    ("_json_object", "question_id.unknown"): ("json.object", lambda w: w.m.question_id(BRIEF_SHA, [UNKNOWN])),
    ("_json_object", "metadata_sha256.unknown"): ("json.object", lambda w: w.m.metadata_sha256("Must it work offline?")),
    ("_instance", "receipt_json.receipt"): ("shape.instance", lambda w: w.m.receipt_json({"receipt": {}})),
    ("_instance", "event_id.receipt"): ("shape.instance", lambda w: w.m.event_id({"action": {}})),
    ("_parse_object", "sidecar"): ("shape.text", lambda w: w.m.receipt_from_json(b"{}")),
    ("_closed", "sidecar"): ("shape.closed", lambda w: w.m.receipt_from_json(w.sidecar(("note",), "extra"))),
    ("_closed", "sidecar.receipt"): ("shape.closed", lambda w: w.m.receipt_from_json(w.sidecar(("receipt", "intent"), DROP))),
    ("_closed", "sidecar.receipt.binding"): ("shape.closed", lambda w: w.m.receipt_from_json(
        w.sidecar(("receipt", "binding", "extra"), 1))),
    ("_closed", "sidecar.receipt.responder"): ("shape.closed", lambda w: w.m.receipt_from_json(
        w.sidecar(("receipt", "responder", "extra"), 1))),
    ("_closed", "sidecar.receipt.confirms"): ("shape.closed", lambda w: w.m.receipt_from_json(
        w.sidecar(("receipt", "confirms", "extra"), 1, receipt=w.callback(confirms=w.confirms())))),
    ("_listed", "sidecar.receipt.supersedes"): ("shape.list", lambda w: w.m.receipt_from_json(
        w.sidecar(("receipt", "supersedes"), "e-prior"))),
    ("_listed", "sidecar.receipt.seen_active_event_ids"): ("shape.list", lambda w: w.m.receipt_from_json(
        w.sidecar(("receipt", "seen_active_event_ids"), "e-prior"))),
    ("_instance", "validate.receipt"): ("shape.instance", lambda w: w.m.validate_receipt(
        {"text": ANSWER}, presentation=w.presentation, copies=["500"], current_generation=1, question_ids=[w.qid])),
    ("_instance", "validate.presentation"): ("shape.instance", lambda w: w.validate(
        w.receipt(), presentation={"question_id": w.qid})),
    ("_string_set", "validate.copies"): ("shape.collection", lambda w: w.validate(w.receipt(), copies=500)),
    ("_integer", "validate.current_generation"): ("shape.integer", lambda w: w.validate(w.receipt(), current_generation=0)),
    ("_string_set", "validate.question_ids"): ("question.ordinal", lambda w: w.validate(w.receipt(), question_ids=["1"])),
    ("_instance", "validate.confirmed"): ("shape.instance", lambda w: w.validate(
        w.callback(confirms=w.confirms()), confirmed=w.confirms())),
    ("_instance", "replay.stored"): ("shape.instance", lambda w: w.m.check_replay(w.receipt().action, w.receipt())),
    ("_instance", "replay.incoming"): ("shape.instance", lambda w: w.m.check_replay(w.receipt(), w.receipt().action)),
    ("_instance", "reopen.receipt"): ("shape.instance", lambda w: w.m.check_reopen_precondition(
        w.reopen().action, revision=1, active_event_ids=[])),
    ("_integer", "reopen.current_revision"): ("shape.integer", lambda w: w.m.check_reopen_precondition(
        w.reopen(), revision=-1, active_event_ids=[])),
    ("_string_set", "reopen.active_event_ids"): ("shape.pattern", lambda w: w.m.check_reopen_precondition(
        w.reopen(), revision=1, active_event_ids=["x"])),
    ("_integer", "cas.expected"): ("shape.integer", lambda w: w.m.check_expected_revision(-1, -1)),
    ("_integer", "cas.current"): ("shape.integer", lambda w: w.m.check_expected_revision(1, True)),
    ("_match", "consumption.stream_id"): ("shape.pattern", lambda w: w.m.consumption_id("s-1", 1, BRIEF_SHA)),
    ("_integer", "consumption.revision"): ("shape.integer", lambda w: w.m.consumption_id(w.stream.stream_id, 0, BRIEF_SHA)),
    ("_match", "consumption.supplement_sha256"): ("shape.pattern", lambda w: w.m.consumption_id(
        w.stream.stream_id, 1, BRIEF_SHA.upper())),
    ("_question_ref", "caller.presentation.question_id"): ("question.ordinal", lambda w: w.caller().presentation(
        "#1", BRIEF_SHA, 1)),
    ("_parse_object", "caller.candidate_json"): ("json.syntax", lambda w: w.caller(
        candidate_json="not json", candidate_sha256=sha("not json"))),
    ("_parse_object", "caller.prior_record_json"): ("json.object", lambda w: w.caller(
        prior_record_json="[1]", prior_record_sha256=sha("[1]"))),
}
ARG_CODES = {"question.ordinal": "ordinal_as_question_id"}

HELPERS = frozenset({
    "_instance", "_text", "_nonblank", "_match", "_opaque", "_event_ref", "_question_ref", "_member", "_integer",
    "_flag", "_code", "_string_tuple", "_string_set", "_closed", "_listed", "_json_object", "_parse_object",
})


def _helper_calls(node):
    calls = [n for n in ast.walk(node) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in HELPERS]
    return sorted(calls, key=lambda call: (call.lineno, call.col_offset))


def _guard_calls(tree):
    """Guard label -> its one _refuse_unless call."""
    calls = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_refuse_unless":
            label = node.args[2].value
            assert label not in calls, f"guard label used twice: {label}"
            calls[label] = node
    return calls


def _field_calls(tree):
    """(class, field) -> the first shape check on self.<field> in that class's __post_init__."""
    calls = {}
    for cls in (node for node in tree.body if isinstance(node, ast.ClassDef)):
        for method in cls.body:
            if isinstance(method, ast.FunctionDef) and method.name == "__post_init__":
                for call in _helper_calls(method):
                    target = call.args[0]
                    if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "self":
                        calls.setdefault((cls.name, target.attr), call)
    return calls


def _arg_calls(tree):
    """(helper, location) -> every other shape check with a literal location in public code."""
    fields = {id(call) for call in _field_calls(tree).values()}
    scopes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and not node.name.startswith("_")]
    for cls in (node for node in tree.body if isinstance(node, ast.ClassDef)):
        scopes += [m for m in cls.body if isinstance(m, ast.FunctionDef) and m.name in ("__post_init__", "presentation")]
    calls = {}
    for scope in scopes:
        for call in _helper_calls(scope):
            where = call.args[-1]
            if id(call) in fields or not (isinstance(where, ast.Constant) and isinstance(where.value, str)):
                continue
            key = (call.func.id, where.value)
            assert key not in calls, f"check site used twice: {key}"
            calls[key] = call
    return calls


class _Unwrap(ast.NodeTransformer):
    def __init__(self, call):
        self.call = call

    def visit_Call(self, node):
        if node is self.call:
            return self.visit(node.args[0])
        return self.generic_visit(node)


def mutant(kind, key):
    """Compile the module IN MEMORY with one check removed; never touch a file."""
    tree = ast.parse(SOURCE)
    if kind == "guard":
        _guard_calls(tree)[key].args[0] = ast.Constant(True)
    else:
        call = (_field_calls if kind == "field" else _arg_calls)(tree)[key]
        tree = _Unwrap(call).visit(tree)
    module = types.ModuleType(f"clarification_contracts_without_{kind}")
    exec(compile(ast.fix_missing_locations(tree), f"<contracts without {kind} {key}>", "exec"), module.__dict__)
    return module


@pytest.mark.parametrize("label", sorted(GUARDS))
def test_each_guard_has_a_literal_case_and_bites(label):
    kind, code, case = GUARDS[label]
    assert outcome(C, case)[:3] == (kind, code, label)
    assert outcome(mutant("guard", label), case)[:3] != (kind, code, label)


@pytest.mark.parametrize(("cls", "field"), FIELDS, ids=[f"{cls}.{field}" for cls, field in FIELDS])
def test_each_field_refuses_a_wrong_value_and_its_check_bites(cls, field):
    def case(w):
        return dataclasses.replace(FIELD_BASES[cls](w), **{field: WRONG})

    found = outcome(C, case)
    assert found[:2] == ("raised", M) and found[3] == f"{FIELD_PREFIX[cls]}.{field}"
    assert outcome(mutant("field", (cls, field)), case) != found


@pytest.mark.parametrize("key", sorted(ARGS), ids=[f"{helper}:{where}" for helper, where in sorted(ARGS)])
def test_each_argument_check_has_a_literal_case_and_bites(key):
    guard, case = ARGS[key]
    expected = ("raised", ARG_CODES.get(guard, M), guard, key[1])
    assert outcome(C, case) == expected
    assert outcome(mutant("arg", key), case) != expected


def test_every_check_site_has_exactly_one_literal_case():
    tree = ast.parse(SOURCE)
    assert sorted(_guard_calls(tree)) == sorted(GUARDS)
    dataclass_names = {node.name for node in tree.body
                       if isinstance(node, ast.ClassDef) and dataclasses.is_dataclass(getattr(C, node.name))}
    assert dataclass_names == set(FIELD_PREFIX) == set(FIELD_BASES)
    assert sorted(_field_calls(tree)) == sorted(FIELDS)
    assert sorted(_arg_calls(tree)) == sorted(ARGS)


def test_every_refusal_code_is_reached_and_each_status_matches_its_code():
    assert {code for _, code, _ in GUARDS.values()} == {code.value for code in C.RefusalCode}
    retained = {code.value for code in C.RETAINED_CODES}
    for kind, code, _ in GUARDS.values():
        if kind in ("retained", "refused"):
            assert (kind == "retained") == (code in retained)


# --- purity, frozen interface and docs ------------------------------------------------


def test_import_and_every_public_operation_need_no_ambient_access(monkeypatch):
    imports = set()
    for node in ast.walk(ast.parse(SOURCE)):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add(node.module)
    allowed = {"collections.abc", "dataclasses", "enum", "hashlib", "json", "math", "re", "typing"}
    assert imports == allowed
    loaded = {name: importlib.import_module(name) for name in allowed}
    code = compile(SOURCE, "pure-clarification-contracts", "exec")
    module = types.ModuleType("pure_clarification_contracts")
    module.__file__ = "must-not-resolve-this-path"

    def deny(*args, **kwargs):
        raise AssertionError("pure contracts attempted ambient access")

    def only_preloaded(name, globals=None, locals=None, fromlist=(), level=0):
        assert name in loaded and level == 0, f"unexpected import: {name}"
        return loaded[name]

    class NoEnvironment:
        __getitem__ = __iter__ = __contains__ = get = deny

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", deny)
        patch.setattr(io, "open", deny)
        for name in ("open", "stat", "listdir", "scandir", "getenv", "getcwd", "urandom", "system"):
            patch.setattr(os, name, deny)
        patch.setattr(os, "environ", NoEnvironment())
        for name in ("open", "read_text", "read_bytes", "resolve", "exists", "stat"):
            patch.setattr(Path, name, deny)
        for name in ("time", "monotonic", "perf_counter", "time_ns", "sleep"):
            patch.setattr(time, name, deny)
        patch.setattr(socket, "socket", deny)
        patch.setattr(socket, "create_connection", deny)
        patch.setattr(subprocess, "Popen", deny)
        patch.setattr(subprocess, "run", deny)
        patch.setattr(sqlite3, "connect", deny)
        patch.setattr(builtins, "__import__", only_preloaded)  # last, so setup imports are not mistaken
        exec(code, module.__dict__)
        w = World(module)
        accepted = w.accepted()
        typed = w.typed()
        caller = w.caller()
        results = [
            known_answers(w), accepted.event(), w.validate(w.receipt(sender_is_bot=True)).status,
            w.validate(w.receipt(disposition=None)).status,
            w.validate(w.callback(confirms=w.confirms(typed)), confirmed=typed).status,
            module.receipt_from_json(module.receipt_json(typed)) == typed,
            module.check_replay(typed, typed), module.check_replay(typed, w.receipt()),
            module.check_reopen_precondition(w.reopen(), revision=1, active_event_ids=[]),
            module.check_expected_revision(1, 1), caller.candidate(), caller.prior_record(),
            caller.presentation(w.qid, module.metadata_sha256(UNKNOWN), 1) == w.presentation, w.applied().revision,
        ]
        refused = []
        for operation in (lambda: module.check_replay(typed, w.typed(text="Edited.")),
                          lambda: module.check_expected_revision(1, 2), lambda: w.caller(original_text=None)):
            try:
                operation()
            except module.ContractRefusal as refusal:
                refused.append(refusal.code.value)
    assert results[0] == KNOWN_ANSWERS and results[2:5] == ["refused", "retained", "accepted"]
    assert results[5:9] == [True, True, False, None] and results[-2:] == [True, 1]
    assert refused == ["changed_body", "revision_conflict", "missing_original"]


def interface():
    """The public surface as stable data: names, fields, signatures, constants and known answers."""
    tree = ast.parse(SOURCE)

    def segment(node):
        return None if node is None else ast.get_source_segment(SOURCE, node)

    def signature(function):
        args = function.args
        positional = args.posonlyargs + args.args
        defaults = [None] * (len(positional) - len(args.defaults)) + [segment(d) for d in args.defaults]
        return {
            "args": [[arg.arg, segment(arg.annotation), default] for arg, default in zip(positional, defaults, strict=True)],
            "kwonly": [[arg.arg, segment(arg.annotation), segment(default)]
                       for arg, default in zip(args.kwonlyargs, args.kw_defaults, strict=True)],
            "returns": segment(function.returns),
            "decorators": [segment(d) for d in function.decorator_list],
        }

    nodes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef | ast.FunctionDef)}
    surface = {}
    for name in sorted(C.__all__):
        node = nodes.get(name)
        if isinstance(node, ast.FunctionDef):
            surface[name] = signature(node)
        elif isinstance(node, ast.ClassDef):
            surface[name] = {
                "bases": [segment(base) for base in node.bases],
                "decorators": [segment(d) for d in node.decorator_list],
                "fields": [[s.target.id, segment(s.annotation), segment(s.value)]
                           for s in node.body if isinstance(s, ast.AnnAssign)],
                "members": [[s.targets[0].id, segment(s.value)] for s in node.body if isinstance(s, ast.Assign)],
                "methods": {m.name: signature(m) for m in node.body
                            if isinstance(m, ast.FunctionDef) and (m.name == "__init__" or not m.name.startswith("_"))},
            }
        else:
            value = getattr(C, name)
            surface[name] = sorted(value) if isinstance(value, frozenset) else value
    return {"surface": surface, "known_answers": known_answers(World(C))}


INTERFACE_SHA256 = "e7ed854ede93ba9407e398e8c34d58d4858014d670724e28dc6877edfa39b685"


def test_the_public_interface_is_frozen():
    # Changing any public name, field, signature, constant, code or ID recipe changes this
    # hash: update the pin, docs/clarifications/contract.md and the reviewers' receipts together.
    assert len(set(C.__all__)) == len(C.__all__) and all(hasattr(C, name) for name in C.__all__)
    assert sha(canon(interface())) == INTERFACE_SHA256


def test_the_doc_names_every_public_name_code_and_the_interface_hash_and_its_example_runs():
    text = DOC.read_text(encoding="utf-8")
    missing = [name for name in C.__all__ if f"`{name}`" not in text]
    missing += [code.value for code in C.RefusalCode if f"`{code.value}`" not in text]
    assert missing == [] and INTERFACE_SHA256 in text
    example = text.split("```python\n", 1)[1].split("```", 1)[0]
    namespace = {}
    exec(compile(example, "contract-doc-example", "exec"), namespace)
    assert namespace["result"].status == "accepted"
