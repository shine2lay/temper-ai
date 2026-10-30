"""M3 clarification store (Temper #207, plan #202 unit M3).

The combined happy path comes first, then #202's ACCEPTANCE.json M3 cases
(T03, T05-T13, T16, T17), then one case for every guard and every retry
branch in store.py, each with its bite: the guard or branch is removed in
memory (an AST or text copy of store.py, never a file) and its case must then
fail.

Every test runs on SQLite (a file, so separate connections really contend)
and on PostgreSQL where TEMPER_TEST_DATABASE_URL is set (the remote CI's
tests (postgres) leg), in that worker's throwaway schema. Bites run on
SQLite. Synthetic data only: no model, network, live database or real person.
"""

import ast
import builtins
import hashlib
import io
import json
import os
import socket
import subprocess
import sys
import threading
import types
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from sqlalchemy import delete, false, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, select

from temper_ai.clarifications import contracts as C
from temper_ai.clarifications import models as M
from temper_ai.clarifications import store as S
from temper_ai.database.engine import create_app_engine, create_test_engine
from tests.pgtier import database_tier_url

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path(S.__file__).read_text(encoding="utf-8")
F = S._shared_foundation()  # the unchanged #308 foundation, as the store loads it


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canon(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


BRIEF = "A synthetic booking tool.\r\n  Keep this exact: café, 東京, trailing space. \n"
BRIEF_SHA = sha(BRIEF)
BRIEF_B = "Another synthetic brief.\n"
UNKNOWN = {
    "question": "Must it work offline?", "why_it_matters": "Changes storage and sync.",
    "decisions_affected": ["client storage", "sync design"], "material": True, "field": "constraints",
}
UNKNOWN_2 = {
    "question": "Who may approve refunds?", "why_it_matters": "Changes roles and audit.",
    "decisions_affected": ["permissions"], "material": False, "field": "goals",
}
UNKNOWN_3 = {
    "question": "Which currencies at launch?", "why_it_matters": "Changes pricing and tax.",
    "decisions_affected": ["pricing"], "material": True, "field": "constraints",
}
PROFILE = {"contract": "context_profile/v2", "brief_sha256": BRIEF_SHA, "unknowns": [UNKNOWN, UNKNOWN_2]}
PROFILE_13 = {**PROFILE, "unknowns": [UNKNOWN, UNKNOWN_3]}
PROFILE_3 = {**PROFILE, "unknowns": [UNKNOWN, UNKNOWN_2, UNKNOWN_3]}
ANSWER = "  Yes: offline first.\r\nSync later — café 東京.  "
TYPED = "Not sure yet;\nask me after the pilot.\n"
NAMESPACE = "temper-clarify:synthetic/arch-stage-context"
POLICY = "responder-policy:synthetic/owner-only"
AUTHORITY = "authority:synthetic/m3-tests"
CANDIDATE_REF = "temper-run:synthetic/stage1"
# Synthetic Telegram IDs: numbers, as the provider gives them (a group chat's ID is negative).
BOT = "7001"
CHAT = "-1001"
OWNER = "5001"
OTHER = "5002"

QID = C.question_id(BRIEF_SHA, UNKNOWN)
QID2 = C.question_id(BRIEF_SHA, UNKNOWN_2)
QID3 = C.question_id(BRIEF_SHA, UNKNOWN_3)
STREAM = C.StreamKey(NAMESPACE, BRIEF_SHA)
SID = STREAM.stream_id
TRANSPORT = C.TransportNamespace("telegram", BOT)
NO_EVENT = "e-" + "0" * 64


# --- synthetic inputs ------------------------------------------------------------------


def present(question=QID, unknown=UNKNOWN, generation=1, stream=STREAM):
    return C.Presentation(stream, question, C.metadata_sha256(unknown), generation, POLICY, TRANSPORT, CHAT)


P1 = present()
P2 = present(QID2, UNKNOWN_2)


def binding(p=P1, message_id="500"):
    return C.PresentationBinding(
        stream_id=p.stream.stream_id, question_id=p.question_id, presentation_id=p.presentation_id,
        generation=p.generation, message_id=message_id,
    )


def receipt(sender=OWNER, action_id="501", text=ANSWER, *, kind="message", p=P1, message_id="500", **changes):
    """A verified human answer to question 1, delivered as message 500."""
    fields = {
        "ingress": "provider_pull",
        "action": C.ActionIdentity(transport=TRANSPORT, chat_id=CHAT, kind=kind, action_id=action_id),
        "update_id": 9001, "sender_id": sender, "sender_is_bot": False, "forwarded": False, "text": text,
        "text_sha256": sha(text), "binding": binding(p, message_id),
        "responder": C.ResponderDecision(
            policy_ref=POLICY, sender_id=sender, decision="authorised", basis="responder_policy",
        ),
        "intent": "answer", "disposition": "answered",
    }
    return C.ActionReceipt(**{**fields, **changes})


def typed(sender=OWNER, action_id="601", **changes):
    """A typed reply with no disposition: retained, and the exact text a later press confirms."""
    return receipt(sender, action_id, TYPED, disposition=None, update_id=9002, **changes)


def press(confirmed, sender=OWNER, action_id="cb-701", **changes):
    """A button press confirming one typed reply's exact text."""
    confirms = C.ConfirmedText(action=confirmed.action, author_id=confirmed.sender_id, text_sha256=confirmed.text_sha256)
    return receipt(
        sender, action_id, "", kind="callback", callback_data="clar:answered", confirms=confirms, update_id=9003,
        **changes,
    )


def fix(sender, targets, action_id="503", text="No: online only.", **changes):
    """A correction by sender of the answers it names."""
    return receipt(sender, action_id, text, intent="correct", supersedes=tuple(targets), reason="Typo.", **changes)


def reopen(seen_revision, seen_active=(), sender=OWNER, action_id="cb-702", **changes):
    return receipt(
        sender, action_id, "", kind="callback", intent="reopen", disposition=None, callback_data="clar:reopen",
        reason="Plans changed; ask again.", seen_revision=seen_revision, seen_active_event_ids=tuple(seen_active),
        update_id=9004, **changes,
    )


def caller(candidate=PROFILE, prior=None, **changes):
    """The stage's input: prior is None for a first creation, else the (revision, record_json) it last saw."""
    candidate_json = canon(candidate)
    revision, record_json = prior or (0, None)
    fields = {
        "stream": STREAM, "original_text": BRIEF, "original_sha256": BRIEF_SHA, "candidate_json": candidate_json,
        "candidate_sha256": sha(candidate_json), "candidate_ref": CANDIDATE_REF, "candidate_brief_sha256": BRIEF_SHA,
        "prior_revision": revision, "prior_record_json": record_json,
        "prior_record_sha256": None if record_json is None else sha(record_json),
        "question_ids": tuple(C.question_id(BRIEF_SHA, unknown) for unknown in candidate["unknowns"]),
        "source_authority_ref": AUTHORITY, "transport": TRANSPORT, "chat_id": CHAT, "responder_policy_ref": POLICY,
        "affected_decisions": ("client storage",),
    }
    return C.CallerInput(**{**fields, **changes})


def refuses(*args, **kwargs):
    raise F.ClarificationError("synthetic refusal")


def stub(**changes):
    """The foundation with some functions replaced: for branches only a broken foundation reaches."""
    names = ("CONTRACT", "ClarificationError", "create_record", "validate_record", "append_event", "project_states",
             "compose_supplement")
    return types.SimpleNamespace(**{**{name: getattr(F, name) for name in names}, **changes})


def states(record):
    return {state["question_id"]: state for state in F.project_states(record)}


# --- throwaway databases ------------------------------------------------------------------


class Db:
    """One throwaway database: the store's seven tables, emptied first. restart() is a new engine and store."""

    def __init__(self, url):
        self.url = url
        self.engines = []
        self.engine = self.new_engine()
        SQLModel.metadata.create_all(self.engine, tables=list(M.TABLES))
        self.clear()
        self.store = S.ClarificationStore(self.engine)

    def new_engine(self):
        if self.url.startswith("sqlite"):
            engine = create_test_engine(self.url)
        else:
            engine = create_app_engine(self.url, pool_size=4)
        self.engines.append(engine)
        return engine

    def store_of(self, m, **kwargs):
        return m.ClarificationStore(self.engine, **kwargs)

    def other(self, **kwargs):
        """A real store on its own engine: another process's connections."""
        return S.ClarificationStore(self.new_engine(), **kwargs)

    def restart(self):
        self.engine.dispose()
        self.engine = self.new_engine()
        self.store = S.ClarificationStore(self.engine)
        return self.store

    def clear(self):
        self.run(*(table.delete() for table in reversed(M.TABLES)))

    def run(self, *statements):
        with self.engine.begin() as connection:
            for statement in statements:
                connection.execute(statement)

    def rows(self, model):
        with Session(self.engine) as session:
            return list(session.exec(select(model)).all())

    def dump(self, skip=()):
        """Every kept row of every store table, as plain tuples."""
        with self.engine.connect() as connection:
            return {
                table.name: sorted((tuple(row) for row in connection.execute(table.select())), key=repr)
                for table in M.TABLES if table.name not in skip
            }

    def close(self):
        for engine in self.engines:
            engine.dispose()


def _database_url(dialect, tmp_path):
    if dialect == "sqlite":
        return f"sqlite:///{tmp_path / 'clarifications.db'}"
    url = database_tier_url()
    if url is None:
        pytest.skip("the PostgreSQL leg runs where TEMPER_TEST_DATABASE_URL is set (the remote CI's tests (postgres))")
    return url


@pytest.fixture(params=["sqlite", "postgresql"])
def db(request, tmp_path):
    database = Db(_database_url(request.param, tmp_path))
    yield database
    database.close()


@pytest.fixture
def lite(tmp_path):
    database = Db(_database_url("sqlite", tmp_path))
    yield database
    database.close()


def deliver(store, presentation, message_id):
    assert store.save_presentation(presentation) is True
    assert store.record_copy(binding(presentation, message_id)) is True


def ready(store):
    """A new stream (revision 1) with question 1 presented and delivered as message 500."""
    first = store.merge_candidate(caller())
    deliver(store, P1, "500")
    return first


def history(store):
    """A stream with every kind of row: revision 1, both questions delivered, a retained typed reply,
    the owner's answer (revision 2), another person's same answer (revision 3), revision 3 consumed."""
    store.merge_candidate(caller())
    deliver(store, P1, "500")
    deliver(store, P2, "510")
    assert store.append_receipt(typed()).status == "retained"
    assert store.append_receipt(receipt()).revision == 2
    assert store.append_receipt(receipt(OTHER, "502")).revision == 3
    assert store.mark_consumed(STREAM, revision=3, original_brief=BRIEF) is True


def diag(db):
    return sorted((row.code, row.guard) for row in db.rows(M.ClarificationRefusal))


def before_first(mp, cls, method, rival):
    """Run rival() once, just before the first call of cls.method: another writer commits at that point."""
    original = getattr(cls, method)
    done = []

    def wrapped(self, *args, **kwargs):
        if not done:
            done.append(True)
            rival()
        return original(self, *args, **kwargs)

    mp.setattr(cls, method, wrapped)


def at_once(mp, cls, method, parties=2):
    """Hold each thread's first call of cls.method until all parties reach it: they decided on the same state."""
    barrier = threading.Barrier(parties, timeout=20)
    local = threading.local()
    seen = []
    original = getattr(cls, method)

    def gated(self, *args, **kwargs):
        if not getattr(local, "passed", False):
            local.passed = True
            seen.append(args)
            barrier.wait()
        return original(self, *args, **kwargs)

    mp.setattr(cls, method, gated)
    return seen


def race(*calls):
    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        futures = [pool.submit(call) for call in calls]
        return [future.result(timeout=30) for future in futures]


# --- the combined happy path ----------------------------------------------------------------


def test_happy_path_keeps_answers_across_a_restart_and_consumes_each_revision_once(db):
    """T01 + T05 + T16: create, present, deliver, two answers, replay, restart, supplement, consume once."""
    store = db.store
    record = F.create_record(PROFILE, BRIEF)
    first = store.merge_candidate(caller())
    assert first == S.RecordResult(SID, 1, canon(record), sha(canon(record)), changed=True)
    assert store.merge_candidate(caller(prior=(1, first.record_json))) == S.RecordResult(
        SID, 1, first.record_json, first.record_sha256, changed=False,
    )
    assert store.save_presentation(P1) is True and store.save_presentation(P1) is False
    assert store.save_presentation(P2) is True
    assert store.record_copy(binding(P1)) is True and store.record_copy(binding(P1)) is False
    assert store.record_copy(binding(P2, "510")) is True

    owner, other = receipt(), receipt(OTHER, "502")
    kept = store.append_receipt(owner)
    assert kept == C.AppendResult("applied", SID, owner.action.key, C.receipt_sha256(owner), 1, 2, C.event_id(owner))
    second = store.append_receipt(other)
    assert (second.status, second.expected_revision, second.revision) == ("applied", 2, 3)
    before = db.dump()
    assert store.append_receipt(owner) == kept  # the provider delivered it again
    assert db.dump() == before

    store = db.restart()  # a new process: everything comes back from the tables
    stored = store.load(STREAM)
    assert (stored.stream, stored.revision, stored.pending_revision, stored.source_authority_ref) == (
        STREAM, 3, 3, AUTHORITY,
    )
    assert stored.presentations == tuple(sorted((P1, P2), key=lambda p: p.question_id))
    assert set(stored.copies) == {binding(P1), binding(P2, "510")}
    state = states(stored.record())[QID]
    assert (state["state"], state["answer"]) == ("answered", ANSWER)  # the exact text, spaces and all
    assert sorted(state["active_event_ids"]) == sorted([kept.event_id, second.event_id])  # two attributions
    assert [event["actor"]["ref"] for event in stored.record()["events"]] == [
        "telegram-user:5001", "telegram-user:5002",
    ]
    assert store.append_receipt(owner) == kept  # the same result and IDs after the restart (T05)

    supplement = store.supplement(STREAM, revision=3, original_brief=BRIEF)
    composed = F.compose_supplement(stored.record(), BRIEF)
    assert (supplement.supplement, supplement.source_mapping) == (composed["supplement"], composed["source_mapping"])
    assert supplement.consumption_id == C.consumption_id(SID, 3, composed["source_mapping"]["supplement_sha256"])
    assert (supplement.consumed, supplement.original_brief, supplement.record_sha256) == (
        False, BRIEF, stored.record_sha256,
    )
    assert store.load(STREAM).pending_revision == 3  # kept and composed, but nothing consumed it (T16)
    store = db.restart()  # the consumer died after composing: it composes again, with the same identity
    assert store.supplement(STREAM, revision=3, original_brief=BRIEF) == supplement
    assert store.mark_consumed(STREAM, revision=3, original_brief=BRIEF) is True
    assert store.mark_consumed(STREAM, revision=3, original_brief=BRIEF) is False
    assert store.load(STREAM).pending_revision is None
    assert store.supplement(STREAM, revision=3, original_brief=BRIEF).consumed is True
    assert len(db.rows(M.ClarificationConsumption)) == 1


def test_keeping_an_answer_resumes_nothing():
    """T16: the store records; it has no way to signal, wake or resume anything."""
    public = {name for name in vars(S.ClarificationStore) if not name.startswith("_")}
    assert public == {
        "merge_candidate", "save_presentation", "record_copy", "append_receipt", "load", "supplement", "mark_consumed",
    }
    assert {table.name for table in M.TABLES} <= set(SQLModel.metadata.tables)
    assert all(table.name.startswith("clarification_") for table in M.TABLES)


# --- ACCEPTANCE.json M3 cases ---------------------------------------------------------------


FORGED = {
    "unverified_ingress": {"ingress": "caller_label"},
    "model_not_human": {"ingress": "model_output"},
    "bot_sender": {"sender_is_bot": True},
    "forwarded_message": {"forwarded": True},
    "responder_not_authorised": {"responder": C.ResponderDecision(
        policy_ref=POLICY, sender_id=OWNER, decision="denied", basis="responder_policy",
    )},
}


def test_only_a_verified_human_receipt_takes_its_key(db):
    """T03 + Security #176 N1: refused receipts leave a diagnostic and never take the action key."""
    ready(db.store)
    for code, changes in FORGED.items():
        result = db.store.append_receipt(receipt(**changes))
        assert (result.status, result.code, result.revision) == ("refused", C.RefusalCode(code), 1), code
    assert db.rows(M.ClarificationReceipt) == []
    assert sorted(code for code, _ in diag(db)) == sorted(FORGED)
    assert set(M.ClarificationRefusal.__table__.columns.keys()) == {
        "id", "receipt_sha256", "action_key", "stream_id", "code", "guard", "created_at",
    }  # a diagnostic keeps no text and no sender
    genuine = db.store.append_receipt(receipt())  # the same action key, now from the verified provider pull
    assert (genuine.status, genuine.revision) == ("applied", 2)


def test_a_press_applies_the_exact_typed_text_only_for_its_author(db):
    """T06: the typed text is kept, a stranger's press is refused, the author's press applies it once."""
    ready(db.store)
    words = typed()
    held = db.store.append_receipt(words)
    assert (held.status, held.code, held.revision) == ("retained", C.RefusalCode.NO_EXPLICIT_DISPOSITION, 1)
    stranger = db.store.append_receipt(press(words, OTHER))
    assert (stranger.status, stranger.code) == ("refused", C.RefusalCode.CONFIRMER_NOT_AUTHOR)
    applied = db.store.append_receipt(press(words))  # the key the stranger's press never took
    assert (applied.status, applied.revision) == ("applied", 2)
    event = db.store.load(STREAM).record()["events"][-1]
    assert (event["answer"], event["actor"]["ref"]) == (TYPED, "telegram-user:5001")
    again = db.store.append_receipt(press(words, action_id="cb-702"))
    assert (again.status, again.code, again.revision) == ("retained", C.RefusalCode.ALREADY_CONFIRMED, 2)


def test_only_explicit_dispositions_apply(db):
    """T07: blank text is retained; an explicit deferral applies as itself."""
    ready(db.store)
    blank = db.store.append_receipt(receipt(text=" \u200b\u2060\ufeff "))
    assert (blank.status, blank.code, blank.revision) == ("retained", C.RefusalCode.BLANK_TEXT, 1)
    later = db.store.append_receipt(receipt(action_id="504", text="Ask me next week.", disposition="deferred"))
    assert (later.status, later.revision) == ("applied", 2)
    assert states(db.store.load(STREAM).record())[QID]["state"] == "deferred"


def test_identical_replay_changes_nothing_and_a_changed_body_is_refused(db):
    """T08: the action key answers a replay; other content under it is refused and history stays as it was."""
    ready(db.store)
    kept = db.store.append_receipt(receipt())
    held = db.store.append_receipt(typed())
    before = db.dump()
    history_before = db.dump(skip=("clarification_refusals",))
    assert db.store.append_receipt(receipt()) == kept
    assert db.store.append_receipt(typed()) == held
    assert db.dump() == before
    changed = receipt(text="  Yes: offline first.  ")  # the same provider action with other text
    refused = db.store.append_receipt(changed)
    assert (refused.status, refused.code, refused.revision) == ("refused", C.RefusalCode.CHANGED_BODY, 2)
    assert db.dump(skip=("clarification_refusals",)) == history_before
    assert [(row.code, row.guard, row.receipt_sha256) for row in db.rows(M.ClarificationRefusal)] == [
        ("changed_body", "replay.body", C.receipt_sha256(changed)),
    ]
    assert db.store.append_receipt(changed) == refused  # refused again, with no second diagnostic
    assert len(db.rows(M.ClarificationRefusal)) == 1


CONCURRENT = {
    "same text": (receipt(OTHER, "502"), "answered"),
    "different text": (receipt(OTHER, "502", "No: online only."), "conflicting"),
    "mixed dispositions": (receipt(OTHER, "502", disposition="deferred"), "conflicting"),
}


@pytest.mark.parametrize("case", sorted(CONCURRENT))
def test_two_concurrent_answers_are_both_kept(db, monkeypatch, case):
    """T09 + T10: two connections answer at once; the loser recomputes on the winner's record."""
    second, state = CONCURRENT[case]
    ready(db.store)
    one, two = db.other(), db.other()
    seen = at_once(monkeypatch, S.ClarificationStore, "_cas")
    results = race(lambda: one.append_receipt(receipt()), lambda: two.append_receipt(second))
    assert [args[2] for args in seen] == [1, 1]  # both decided on revision 1 before either wrote: a real race
    assert sorted((r.status, r.expected_revision, r.revision) for r in results) == [
        ("applied", 1, 2), ("applied", 2, 3),
    ]
    stored = db.restart().load(STREAM)
    projected = states(stored.record())[QID]
    assert projected["state"] == state
    assert sorted(projected["active_event_ids"]) == sorted(r.event_id for r in results)
    assert sorted(event["actor"]["ref"] for event in stored.record()["events"]) == [
        "telegram-user:5001", "telegram-user:5002",
    ]


def test_a_first_create_race_is_settled_by_the_unique_key(db, monkeypatch):
    """T09: two connections create the same stream at once; the loser merges onto the winner's record."""
    one, two = db.other(), db.other()
    seen = at_once(monkeypatch, S.ClarificationStore, "_create")
    results = race(lambda: one.merge_candidate(caller()), lambda: two.merge_candidate(caller(PROFILE_13)))
    assert len(seen) == 2  # both found no stream and tried to create it
    assert sorted((r.revision, r.changed) for r in results) == [(1, True), (2, True)]
    stored = db.restart().load(STREAM)
    assert stored.revision == 2
    assert {question["question_id"] for question in stored.record()["questions"]} == {QID, QID2, QID3}


def test_corrections_and_reopens_follow_the_plan(db):
    """T11: own corrections apply, others' are retained, unknown targets are refused with evidence;
    a stale reopen is retained, a fresh one applies, old retries are no-ops, a retired copy is stale."""
    store = db.store
    ready(store)
    deliver(store, P2, "510")
    first = store.append_receipt(receipt())  # revision 2: the owner's answer e1
    e1 = first.event_id
    stranger = store.append_receipt(fix(OTHER, [e1], action_id="505"))
    assert (stranger.status, stranger.code, stranger.revision) == (
        "retained", C.RefusalCode.CROSS_ACTOR_CORRECTION, 2,
    )
    unknown = store.append_receipt(fix(OWNER, [NO_EVENT], action_id="506"))
    assert (unknown.status, unknown.code) == ("refused", C.RefusalCode.MISSING_RECORD)
    assert ("missing_record", "correction.known") in diag(db)  # Architecture N3 / Security N6: evidence kept
    words = typed(OTHER, "602")
    store.append_receipt(words)
    pressed = store.append_receipt(press(words, OTHER, "cb-703", intent="correct", supersedes=(e1,), reason="Typo."))
    assert (pressed.status, pressed.code) == ("retained", C.RefusalCode.CROSS_ACTOR_CORRECTION)  # Architecture N2
    own = store.append_receipt(fix(OWNER, [e1]))
    assert (own.status, own.revision) == ("applied", 3)
    state = states(store.load(STREAM).record())[QID]
    assert (state["state"], state["answer"], state["active_event_ids"]) == ("answered", "No: online only.", [own.event_id])

    stale = store.append_receipt(reopen(2, [e1]))  # shown before the correction
    assert (stale.status, stale.code, stale.revision) == ("retained", C.RefusalCode.STALE_REOPEN, 3)
    assert states(store.load(STREAM).record())[QID]["active_event_ids"] == [own.event_id]  # nothing swept
    elsewhere = store.append_receipt(receipt(OTHER, "511", p=P2, message_id="510"))  # revision 4, question 2
    assert elsewhere.revision == 4
    fresh = store.append_receipt(reopen(3, [own.event_id], action_id="cb-704"))  # another question moved on
    assert (fresh.status, fresh.revision) == ("applied", 5)
    assert states(store.load(STREAM).record())[QID]["state"] == "reopened"
    assert store.append_receipt(receipt()) == first  # an old duplicate retry is a no-op
    assert store.load(STREAM).revision == 5

    deliver(store, present(generation=2), "520")  # asked again: generation 2 retires generation 1
    late = store.append_receipt(receipt(OTHER, "507"))
    assert (late.status, late.code, late.revision) == ("retained", C.RefusalCode.STALE_PRESENTATION, 5)
    answer = store.append_receipt(receipt(OTHER, "508", p=present(generation=2), message_id="520"))
    assert (answer.status, answer.revision) == ("applied", 6)


# Security #180: check correction targets even when another condition would retain the action.
CORRECTION_STATES = {
    "message": None,
    "no_disposition": ("no_explicit_disposition", "disposition.explicit"),
    "blank_text": ("blank_text", "text.blank"),
    "retired": ("stale_presentation", "binding.stale"),
    "press": None,
    "press_no_disposition": ("no_explicit_disposition", "disposition.explicit"),
    "press_blank_text": ("blank_text", "text.blank"),
    "press_retired": ("stale_presentation", "binding.stale"),
    "press_already_confirmed": None,  # accepted validation; correction must still precede confirmation
}


def correction_candidate(store, state, targets, **changes):
    """Compose retained/accepted validation with a correction, using actual persisted answers/copies."""
    if state.startswith("press"):
        words = typed() if state != "press_blank_text" else receipt(action_id="601", text=" \u200b ", disposition=None)
        assert store.append_receipt(words).status == "retained"
        if state == "press_already_confirmed":
            assert store.append_receipt(press(words, action_id="cb-700")).status == "applied"
        attempt = press(words, intent="correct", supersedes=tuple(targets), reason="Typo.", **{
            **({"disposition": None} if state == "press_no_disposition" else {}), **changes,
        })
    else:
        fields = {"disposition": None} if state == "no_disposition" else {}
        if state == "blank_text":
            fields["text"] = " \u200b "
        attempt = fix(OWNER, targets, **{**fields, **changes})
    if state in ("retired", "press_retired"):
        deliver(store, present(generation=2), "520")
    return attempt


def assert_unknown_correction_diagnostic_only(db, store, attempt):
    """No authoritative row/text/key changes; the diagnostic is linkable but non-reserving."""
    before = db.dump(skip=("clarification_refusals",))
    result = store.append_receipt(attempt)
    assert (result.status, result.code) == ("refused", C.RefusalCode.MISSING_RECORD), "unknown correction retained"
    assert diag(db) == [("missing_record", "correction.known")]
    assert db.dump(skip=("clarification_refusals",)) == before  # includes whole foundation history and exact sidecars
    assert attempt.action.key not in {row.action_key for row in db.rows(M.ClarificationReceipt)}
    diagnostic, = db.rows(M.ClarificationRefusal)
    assert (diagnostic.receipt_sha256, diagnostic.action_key, diagnostic.stream_id) == (
        C.receipt_sha256(attempt), attempt.action.key, SID,
    )
    assert diagnostic.id is not None and diagnostic.created_at is not None
    after = db.dump()
    assert store.append_receipt(attempt) == result  # still refused, same diagnostic, no replay authority
    assert db.dump() == after


@pytest.mark.parametrize("state", CORRECTION_STATES)
@pytest.mark.parametrize("targets", ["unknown", "other_then_unknown", "unknown_then_other"])
def test_unknown_correction_never_retains_and_same_key_recovers(db, state, targets):
    """Combined regression: real answers, mixed targets, retained validation, diagnostic/replay and recovery."""
    store = db.store
    ready(store)
    own = store.append_receipt(receipt())
    other = store.append_receipt(receipt(OTHER, "502"))
    named = {
        "unknown": [NO_EVENT], "other_then_unknown": [other.event_id, NO_EVENT],
        "unknown_then_other": [NO_EVENT, other.event_id],
    }[targets]
    attempt = correction_candidate(store, state, named)
    assert_unknown_correction_diagnostic_only(db, store, attempt)
    store = db.restart()
    current = store.load(STREAM).presentations[0]
    copy_id = "520" if current.generation == 2 else "500"
    if attempt.action.kind == "callback":
        words = typed(action_id="622", p=current, message_id=copy_id)
        assert store.append_receipt(words).status == "retained"
        genuine = press(words, action_id=attempt.action.action_id, p=current, message_id=copy_id,
                        intent="correct", supersedes=(own.event_id,), reason="Typo.")
    else:
        genuine = fix(OWNER, [own.event_id], action_id=attempt.action.action_id, p=current, message_id=copy_id)
    assert genuine.action.key == attempt.action.key
    applied = store.append_receipt(genuine)
    assert applied.status == "applied"  # an earlier unknown-target diagnostic never poisons this key
    before = db.dump()
    assert store.append_receipt(genuine) == applied
    assert db.dump() == before


@pytest.mark.parametrize("state", CORRECTION_STATES)
@pytest.mark.parametrize("target_actor", ["own", "other"])
def test_known_corrections_preserve_prior_retained_outcomes(db, state, target_actor):
    ready(db.store)
    own = db.store.append_receipt(receipt())
    other = db.store.append_receipt(receipt(OTHER, "502"))
    target = own.event_id if target_actor == "own" else other.event_id
    attempt = correction_candidate(db.store, state, [target])
    before = db.store.load(STREAM)
    result = db.store.append_receipt(attempt)
    expected = CORRECTION_STATES[state]
    if expected is None and target_actor == "other":
        expected = ("cross_actor_correction", "correction.same_actor")
    if expected is None and state == "press_already_confirmed":
        expected = ("already_confirmed", "confirmation.once")
    kept = next(row for row in db.rows(M.ClarificationReceipt) if row.action_key == attempt.action.key)
    assert kept.receipt_json == C.receipt_json(attempt)
    if expected is None:
        assert result.status == "applied"
        assert result.revision == before.revision + 1
    else:
        assert (result.status, kept.code, kept.guard) == ("retained", *expected), "prior retained outcome changed"
        assert db.store.load(STREAM).record_json == before.record_json
        assert result.revision == before.revision
    assert diag(db) == []
    assert db.store.append_receipt(attempt) == result


CORRECTION_REFUSALS = {
    "unverified": (FORGED["unverified_ingress"], "unverified_ingress", "provenance.ingress"),
    "model": (FORGED["model_not_human"], "model_not_human", "provenance.model"),
    "bot": (FORGED["bot_sender"], "bot_sender", "provenance.bot"),
    "forwarded": (FORGED["forwarded_message"], "forwarded_message", "provenance.forwarded"),
    "denied": (FORGED["responder_not_authorised"], "responder_not_authorised", "responder.decision"),
    "unknown_copy": ({"message_id": "999"}, "binding_mismatch", "binding.copy"),
}


@pytest.mark.parametrize("state", CORRECTION_STATES)
@pytest.mark.parametrize("refusal", CORRECTION_REFUSALS)
def test_unknown_correction_preserves_earlier_provenance_and_binding_refusals(db, state, refusal):
    ready(db.store)
    changes, code, guard = CORRECTION_REFUSALS[refusal]
    attempt = correction_candidate(db.store, state, [NO_EVENT], **changes)
    before = db.dump(skip=("clarification_refusals",))
    result = db.store.append_receipt(attempt)
    assert (result.status, result.code) == ("refused", C.RefusalCode(code)), "earlier refusal replaced"
    assert diag(db) == [(code, guard)]  # not reclassified as a correction or retained outcome
    assert db.dump(skip=("clarification_refusals",)) == before


def test_unused_copy_and_authority_metadata_are_not_authenticated(db):
    """Pin the documented trusted-writer limit; these changes need no coordinated hash-chain rewrite."""
    history(db.store)
    before = db.store.load(STREAM)
    assert db.store.record_copy(binding(P1, "599")) is True  # unused: no applied receipt depends on this copy
    db.run(update(M.ClarificationCopy).where(M.ClarificationCopy.message_id == "599").values(message_id="598"))
    after_copy = db.restart().load(STREAM)
    assert binding(P1, "598") in after_copy.copies and binding(P1, "599") not in after_copy.copies
    assert after_copy.record_json == before.record_json
    changed_authority = "authority:synthetic/replaced"
    db.run(update(M.ClarificationStream).values(source_authority_ref=changed_authority))
    after_authority = db.restart().load(STREAM)
    assert after_authority.source_authority_ref == changed_authority
    assert after_authority.record_json == before.record_json
    with pytest.raises(C.ContractRefusal) as refused:
        db.store.merge_candidate(caller())
    assert (refused.value.code, refused.value.guard) == (C.RefusalCode.CROSS_CONTEXT, "store.authority")
    assert db.store.merge_candidate(caller(source_authority_ref=changed_authority)).changed is False


CHILD = r"""
import os
import sys

from temper_ai.clarifications import contracts as C
from temper_ai.clarifications import store as S
from temper_ai.database.engine import create_app_engine, create_test_engine

url, when = sys.argv[1], sys.argv[2]
engine = create_test_engine(url) if url.startswith("sqlite") else create_app_engine(url, pool_size=2)
original = S.ClarificationStore._commit


def crash(session, explained):
    if when == "before":
        session.flush()  # every row written inside the transaction; the process dies before COMMIT
        os._exit(17)
    original(session, explained)
    os._exit(17)  # committed; the process dies before anything is acknowledged or signalled


S.ClarificationStore._commit = staticmethod(crash)
S.ClarificationStore(engine).append_receipt(C.receipt_from_json(sys.stdin.read()))
os._exit(3)
"""


@pytest.mark.parametrize("when", ["before", "after"])
def test_a_process_killed_at_commit_recovers_idempotently(db, when):
    """T12: a real process dies just before or just after its commit; the next one recovers."""
    ready(db.store)
    before = db.dump()
    answer = receipt()
    child = subprocess.run(
        [sys.executable, "-c", CHILD, db.url, when], input=C.receipt_json(answer), text=True, cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT)}, capture_output=True, timeout=90,
    )
    assert child.returncode == 17, child.stderr[-3000:]
    store = db.restart()
    if when == "before":
        assert db.dump() == before  # nothing of the dead transaction was kept
        result = store.append_receipt(answer)  # the provider delivers it again: applied once
        assert (result.status, result.expected_revision, result.revision) == ("applied", 1, 2)
    else:
        stored = store.load(STREAM)
        assert (stored.revision, stored.pending_revision) == (2, 2)  # kept before anything was signalled
        after = db.dump()
        result = store.append_receipt(answer)  # delivered again after the crash: the kept result
        assert (result.status, result.expected_revision, result.revision) == ("applied", 1, 2)
        assert db.dump() == after
    assert store.mark_consumed(STREAM, revision=2, original_brief=BRIEF) is True
    assert store.mark_consumed(STREAM, revision=2, original_brief=BRIEF) is False


def test_a_failure_before_commit_keeps_nothing(db, monkeypatch):
    """T12: an error inside the transaction rolls all of it back; the retry applies once."""
    ready(db.store)
    before = db.dump()
    real = Session.commit

    def power_cut(self):
        monkeypatch.setattr(Session, "commit", real)
        raise RuntimeError("power cut")

    monkeypatch.setattr(Session, "commit", power_cut)
    with pytest.raises(RuntimeError, match="power cut"):
        db.store.append_receipt(receipt())
    assert db.dump() == before
    assert db.store.append_receipt(receipt()).revision == 2


def edit_receipt(db, key, text):
    db.run(update(M.ClarificationReceipt).where(M.ClarificationReceipt.action_key == key).values(
        receipt_json=text, receipt_sha256=sha(text),
    ))


def rewrite_record(db, revision, text):
    db.run(update(M.ClarificationRevision).where(M.ClarificationRevision.revision == revision).values(
        record_json=text, record_sha256=sha(text),
    ))


def kept_record(db, revision):
    row = next(row for row in db.rows(M.ClarificationRevision) if row.revision == revision)
    return json.loads(row.record_json)


TYPED_KEY = typed().action.key
OWNER_KEY = receipt().action.key
TAMPERS = {
    "stream.missing": lambda db: db.run(delete(M.ClarificationStream)),
    "history.ahead": lambda db: db.run(update(M.ClarificationStream).values(revision=2)),
    "stream.identity": lambda db: db.run(update(M.ClarificationStream).values(namespace="temper-clarify:synthetic/x")),
    "history.revisions": lambda db: db.run(delete(M.ClarificationRevision).where(M.ClarificationRevision.revision == 2)),
    "history.digest": lambda db: db.run(update(M.ClarificationRevision).where(
        M.ClarificationRevision.revision == 2).values(record_json=canon(kept_record(db, 2)).replace("Yes", "Yep"))),
    "history.chain": lambda db: db.run(update(M.ClarificationRevision).where(
        M.ClarificationRevision.revision == 2).values(previous_record_sha256="f" * 64)),
    "history.json": lambda db: rewrite_record(db, 3, json.dumps(kept_record(db, 3), sort_keys=True, indent=1)),
    "history.record": lambda db: rewrite_record(db, 3, canon({**kept_record(db, 3), "contract": "x/v0"})),
    "history.first": lambda db: db.run(update(M.ClarificationRevision).where(
        M.ClarificationRevision.revision == 1).values(change="event")),
    "history.record_step": lambda db: db.run(update(M.ClarificationRevision).where(
        M.ClarificationRevision.revision == 2).values(change="record", event_id=None, action_key=None)),
    "history.event_step": lambda db: db.run(update(M.ClarificationRevision).where(
        M.ClarificationRevision.revision == 2).values(event_id=NO_EVENT)),
    "history.latest": lambda db: db.run(update(M.ClarificationStream).values(record_sha256="f" * 64)),
    "presentation.count": lambda db: db.run(delete(M.ClarificationPresentation).where(
        M.ClarificationPresentation.presentation_id == P2.presentation_id)),
    "presentation.identity": lambda db: db.run(update(M.ClarificationPresentation).where(
        M.ClarificationPresentation.presentation_id == P1.presentation_id).values(chat_id="-1002")),
    "copy.count": lambda db: db.run(delete(M.ClarificationCopy).where(M.ClarificationCopy.message_id == "510")),
    "copy.identity": lambda db: db.run(update(M.ClarificationCopy).where(
        M.ClarificationCopy.message_id == "510").values(presentation_id="p-" + "0" * 64)),
    "receipt.count": lambda db: db.run(delete(M.ClarificationReceipt).where(M.ClarificationReceipt.action_key == TYPED_KEY)),
    "receipt.digest": lambda db: db.run(update(M.ClarificationReceipt).where(
        M.ClarificationReceipt.action_key == OWNER_KEY).values(receipt_json=C.receipt_json(receipt()).replace("Yes", "Yep"))),
    "receipt.sidecar": lambda db: edit_receipt(db, OWNER_KEY, canon({"contract": "x/v0"})),
    "receipt.identity": lambda db: db.run(update(M.ClarificationReceipt).where(
        M.ClarificationReceipt.action_key == TYPED_KEY).values(action_key="a-" + "0" * 64)),
    "receipt.missing": lambda db: db.run(
        delete(M.ClarificationReceipt).where(M.ClarificationReceipt.action_key == OWNER_KEY),
        update(M.ClarificationStream).values(receipt_count=M.ClarificationStream.receipt_count - 1),
    ),
    "receipt.event": lambda db: edit_receipt(db, OWNER_KEY, C.receipt_json(receipt(text="Other text."))),
    "receipt.applied": lambda db: db.run(update(M.ClarificationReceipt).where(
        M.ClarificationReceipt.action_key == TYPED_KEY).values(
        status="applied", event_id=NO_EVENT, revision=2, code=None, guard=None)),
    "consumption.count": lambda db: db.run(delete(M.ClarificationConsumption)),
    "consumption.identity": lambda db: db.run(update(M.ClarificationConsumption).values(record_sha256="f" * 64)),
}
DAMAGE = [*TAMPERS.items(), (
    "history.revisions", lambda db: db.run(delete(M.ClarificationRevision).where(M.ClarificationRevision.revision == 3)),
)]


@pytest.mark.parametrize("guard, tamper", DAMAGE, ids=[f"{guard}-{index}" for index, (guard, _) in enumerate(DAMAGE)])
def test_damaged_history_is_an_integrity_failure_never_a_fresh_record(db, guard, tamper):
    """T13: lost, cut short or changed history stops every reader and writer, naming what is wrong."""
    history(db.store)
    tamper(db)
    damaged = db.dump()
    attempts = (
        lambda: db.store.load(STREAM),
        lambda: db.store.append_receipt(receipt(action_id="509")),
        lambda: db.store.merge_candidate(caller(PROFILE_3)),
        lambda: db.store.mark_consumed(STREAM, revision=1, original_brief=BRIEF),
    )
    for attempt in attempts:
        with pytest.raises(S.ClarificationIntegrityError) as error:
            attempt()
        assert error.value.guard == guard
    assert db.dump() == damaged


def test_streams_are_kept_apart_and_no_reference_is_opened(db):
    """T17: a key from another context binds nothing; another or absent authority is refused; refs stay closed."""
    store = db.store
    ready(store)
    away = C.StreamKey("temper-clarify:synthetic/another-context", BRIEF_SHA)
    assert away.stream_id != SID
    p_away = present(stream=away)
    with pytest.raises(C.ContractRefusal) as refusal:
        caller(source_authority_ref=None)
    assert refusal.value.code is C.RefusalCode.MISSING_AUTHORITY  # refused before any store sees it

    def no_io(*args, **kwargs):
        raise AssertionError(f"the store opened something: {args!r}")

    with pytest.MonkeyPatch.context() as mp:
        for target, name in ((builtins, "open"), (io, "open"), (os, "open"), (socket.socket, "connect")):
            mp.setattr(target, name, no_io)
        created = store.merge_candidate(caller(
            stream=away, candidate_ref="file:///nonexistent/candidate.json",
            source_authority_ref="https://authority.invalid/synthetic",
        ))
        assert created.stream_id == away.stream_id
        deliver(store, p_away, "530")
        crossed = receipt(action_id="540", binding=C.PresentationBinding(
            stream_id=away.stream_id, question_id=QID, presentation_id=P1.presentation_id, generation=1,
            message_id="500",
        ))
        result = store.append_receipt(crossed)
        assert (result.status, result.code, result.stream_id) == (
            "refused", C.RefusalCode.BINDING_MISMATCH, away.stream_id,
        )
        assert ("binding_mismatch", "store.presentation") in diag(db)
        applied = store.append_receipt(receipt(action_id="531", p=p_away, message_id="530"))
        assert (applied.status, applied.stream_id, applied.revision) == ("applied", away.stream_id, 2)
        with pytest.raises(C.ContractRefusal) as refusal:
            store.merge_candidate(caller(stream=away))
        assert (refusal.value.code, refusal.value.guard) == (C.RefusalCode.CROSS_CONTEXT, "store.authority")
        assert store.load(STREAM).revision == 1  # the first context is untouched
        assert store.supplement(away, revision=2, original_brief=BRIEF).revision == 2


# --- every guard and every retry branch, with its bite ----------------------------------------


def norm(m, value):
    if isinstance(value, C.AppendResult):
        code = None if value.code is None else value.code.value
        return ("result", value.status, code, value.expected_revision, value.revision)
    if isinstance(value, m.RecordResult):
        return ("record", value.revision, value.changed)
    if isinstance(value, tuple):
        return tuple(norm(m, item) for item in value)
    return value


def outcome(m, case, db, mp):
    """What one case does against a store module: its result, its refusal, its integrity failure, or an error."""
    try:
        return norm(m, case(m, db, mp))
    except m.ClarificationIntegrityError as error:
        return ("integrity", error.guard)
    except C.ContractRefusal as refusal:
        return ("raised", refusal.code.value, refusal.guard)
    except Exception as error:  # a mutant may break in any way; that also fails its case
        return ("error", type(error).__name__)


def raised(code, guard):
    return ("raised", code, guard)


def integrity(guard):
    return ("integrity", guard)


GUARD_CASES = {}


def guard_case(guard, expected):
    def register(case):
        GUARD_CASES[guard] = (case, expected)
        return case
    return register


def tampered(tamper):
    def case(m, db, mp):
        history(db.store)
        tamper(db)
        return db.store_of(m).load(STREAM)
    return case


for _guard, _tamper in TAMPERS.items():
    GUARD_CASES[_guard] = (tampered(_tamper), integrity(_guard))


@guard_case("store.caller_type", raised("malformed", "store.caller_type"))
def case_caller_type(m, db, mp):
    return db.store_of(m).merge_candidate("caller")


@guard_case("store.presentation_type", raised("malformed", "store.presentation_type"))
def case_presentation_type(m, db, mp):
    return db.store_of(m).save_presentation("presentation")


@guard_case("store.binding_type", raised("malformed", "store.binding_type"))
def case_binding_type(m, db, mp):
    return db.store_of(m).record_copy("binding")


@guard_case("store.receipt_type", raised("malformed", "store.receipt_type"))
def case_receipt_type(m, db, mp):
    return db.store_of(m).append_receipt("receipt")


@guard_case("store.stream_type", raised("malformed", "store.stream_type"))
def case_stream_type(m, db, mp):
    return db.store_of(m).load("stream")


@guard_case("store.utf8", raised("malformed", "store.utf8"))
def case_utf8(m, db, mp):
    return db.store_of(m).load(C.StreamKey("temper-clarify:synthetic/\ud800", BRIEF_SHA))  # a lone surrogate


@guard_case("store.record_missing", raised("missing_record", "store.record_missing"))
def case_record_missing(m, db, mp):
    return db.store_of(m).merge_candidate(caller(prior=(1, canon(F.create_record(PROFILE, BRIEF)))))


@guard_case("store.authority", raised("cross_context", "store.authority"))
def case_authority(m, db, mp):
    db.store.merge_candidate(caller())
    return db.store_of(m).merge_candidate(caller(source_authority_ref="authority:synthetic/someone-else"))


@guard_case("store.prior_revision", raised("missing_record", "store.prior_revision"))
def case_prior_revision(m, db, mp):
    first = db.store.merge_candidate(caller())
    return db.store_of(m).merge_candidate(caller(prior=(2, first.record_json)))


@guard_case("store.prior_record", raised("hash_mismatch", "store.prior_record"))
def case_prior_record(m, db, mp):
    db.store.merge_candidate(caller())
    return db.store_of(m).merge_candidate(caller(prior=(1, canon(F.create_record(PROFILE_13, BRIEF)))))


@guard_case("store.candidate", raised("malformed", "store.candidate"))
def case_candidate(m, db, mp):
    return db.store_of(m, foundation=stub(create_record=refuses)).merge_candidate(caller())


@guard_case("presentation.stream", raised("missing_record", "presentation.stream"))
def case_presentation_stream(m, db, mp):
    return db.store_of(m).save_presentation(P1)


@guard_case("presentation.question", raised("unknown_question", "presentation.question"))
def case_presentation_question(m, db, mp):
    db.store.merge_candidate(caller())
    return db.store_of(m).save_presentation(present(QID3, UNKNOWN_3))


@guard_case("presentation.metadata", raised("hash_mismatch", "presentation.metadata"))
def case_presentation_metadata(m, db, mp):
    db.store.merge_candidate(caller())
    return db.store_of(m).save_presentation(present(QID, UNKNOWN_2))


@guard_case("presentation.generation", raised("binding_mismatch", "presentation.generation"))
def case_presentation_generation(m, db, mp):
    db.store.merge_candidate(caller())
    return db.store_of(m).save_presentation(present(generation=2))


@guard_case("copy.presentation", raised("missing_record", "copy.presentation"))
def case_copy_presentation(m, db, mp):
    db.store.merge_candidate(caller())
    return db.store_of(m).record_copy(binding(P1))


@guard_case("copy.binding", raised("binding_mismatch", "copy.binding"))
def case_copy_binding(m, db, mp):
    db.store.merge_candidate(caller())
    db.store.save_presentation(P1)
    return db.store_of(m).record_copy(C.PresentationBinding(
        stream_id=SID, question_id=QID2, presentation_id=P1.presentation_id, generation=1, message_id="500",
    ))


@guard_case("consume.stream", raised("missing_record", "consume.stream"))
def case_consume_stream(m, db, mp):
    return db.store_of(m).supplement(STREAM, revision=1, original_brief=BRIEF)


@guard_case("consume.revision", raised("missing_record", "consume.revision"))
def case_consume_revision(m, db, mp):
    db.store.merge_candidate(caller())
    return db.store_of(m).supplement(STREAM, revision=5, original_brief=BRIEF)


@guard_case("consume.brief_type", raised("malformed", "consume.brief_type"))
def case_consume_brief_type(m, db, mp):
    db.store.merge_candidate(caller())
    return db.store_of(m).supplement(STREAM, revision=1, original_brief=None)


@guard_case("consume.brief", raised("hash_mismatch", "consume.brief"))
def case_consume_brief(m, db, mp):
    db.store.merge_candidate(caller())
    return db.store_of(m).mark_consumed(STREAM, revision=1, original_brief=BRIEF_B)


@guard_case("store.stream", (("result", "refused", "missing_record", 0, 0), (("missing_record", "store.stream"),)))
def case_store_stream(m, db, mp):
    return db.store_of(m).append_receipt(receipt()), tuple(diag(db))


@guard_case("store.presentation", (
    ("result", "refused", "binding_mismatch", 1, 1), (("binding_mismatch", "store.presentation"),),
))
def case_store_presentation(m, db, mp):
    ready(db.store)
    return db.store_of(m).append_receipt(receipt(p=present(generation=2))), tuple(diag(db))


@guard_case("store.foundation", (("result", "refused", "malformed", 1, 1), (("malformed", "store.foundation"),)))
def case_store_foundation(m, db, mp):
    ready(db.store)
    return db.store_of(m, foundation=stub(append_event=refuses)).append_receipt(receipt()), tuple(diag(db))


@guard_case("store.event_added", integrity("store.event_added"))
def case_event_added(m, db, mp):
    ready(db.store)
    return db.store_of(m, foundation=stub(append_event=lambda record, event: dict(record))).append_receipt(receipt())


@guard_case("history.brief", integrity("history.brief"))
def case_history_brief(m, db, mp):
    db.store.merge_candidate(caller())
    profile = {"contract": "context_profile/v2", "brief_sha256": sha(BRIEF_B), "unknowns": [UNKNOWN]}
    rewrite_record(db, 1, canon(F.create_record(profile, BRIEF_B)))
    return db.store_of(m).load(STREAM)


@guard_case("stream.cas", integrity("stream.cas"))
def case_stream_cas(m, db, mp):
    ready(db.store)
    mp.setattr(m, "update", lambda model: update(model).where(false()))  # the row is there but takes no change
    return db.store_of(m).append_receipt(receipt())


@guard_case("consume.record", integrity("consume.record"))
def case_consume_record(m, db, mp):
    db.store.merge_candidate(caller())

    def wrong(record, brief):
        composed = F.compose_supplement(record, brief)
        return {**composed, "source_mapping": {**composed["source_mapping"], "record_sha256": "f" * 64}}

    return db.store_of(m, foundation=stub(compose_supplement=wrong)).supplement(STREAM, revision=1, original_brief=BRIEF)


def case_retained_race(m, db, mp):
    """A retained decision made at revision 2 is decided again once a rival commits revision 3."""
    ready(db.store)
    first = db.store.append_receipt(receipt())
    other = receipt(OTHER, "502")
    rival = db.other()
    before_first(mp, m.ClarificationStore, "_cas", lambda: rival.append_receipt(other))
    return db.store_of(m).append_receipt(reopen(3, (first.event_id, C.event_id(other))))


def case_forced_miss(m, db, mp):
    """A rival commits between the decision and its compare-and-set: recomputed on the latest record."""
    ready(db.store)
    rival = db.other()
    before_first(mp, m.ClarificationStore, "_cas", lambda: rival.append_receipt(receipt(OTHER, "502")))
    result = db.store_of(m).append_receipt(receipt())
    return result, kept_record(db, 3)["events"][:-1] == kept_record(db, 2)["events"]


def case_row_gone(m, db, mp):
    ready(db.store)
    before_first(mp, m.ClarificationStore, "_cas", lambda: db.run(delete(M.ClarificationStream)))
    return db.store_of(m).append_receipt(receipt())


def case_rival_create(m, db, mp):
    rival = db.other()
    before_first(mp, m.ClarificationStore, "_create", lambda: rival.merge_candidate(caller()))
    return db.store_of(m).merge_candidate(caller(PROFILE_13))


def case_unexplained_clash(m, db, mp):
    """A unique-key clash no other writer explains is re-raised, with nothing kept."""
    ready(db.store)
    before = db.dump()
    real = Session.commit

    def clash(self):
        mp.setattr(Session, "commit", real)
        raise IntegrityError("COMMIT", {}, Exception("synthetic unique clash"))

    mp.setattr(Session, "commit", clash)
    try:
        db.store_of(m).append_receipt(receipt())
    except IntegrityError:
        return ("re-raised", db.dump() == before)
    return ("swallowed", None)


def case_fence(m, db, mp):
    ready(db.store)
    rival = db.other()
    before_first(mp, m.ClarificationStore, "_cas", lambda: rival.save_presentation(present(generation=2)))
    return db.store_of(m).append_receipt(receipt())


def case_created_between(m, db, mp):
    rival = db.other()
    before_first(mp, m.ClarificationStore, "_history", lambda: rival.merge_candidate(caller()))
    return db.store_of(m).merge_candidate(caller())


def case_ahead_between(m, db, mp):
    ready(db.store)
    rival = db.other()
    before_first(mp, m.ClarificationStore, "_history", lambda: rival.append_receipt(receipt()))
    return db.store_of(m).append_receipt(receipt(OTHER, "502"))


def case_kept_between(m, db, mp):
    ready(db.store)
    rival = db.other()
    before_first(mp, m.ClarificationStore, "_load", lambda: rival.append_receipt(receipt()))
    return db.store_of(m).append_receipt(receipt())


def case_replay(m, db, mp):
    ready(db.store)
    db.store.append_receipt(receipt())
    return db.store_of(m).append_receipt(receipt())


def case_replay_gone(m, db, mp):
    ready(db.store)
    db.store.append_receipt(receipt())
    before_first(mp, m.ClarificationStore, "_load", db.clear)
    return db.store_of(m).append_receipt(receipt())


def case_cross_actor(m, db, mp):
    ready(db.store)
    first = db.store.append_receipt(receipt())
    return db.store_of(m).append_receipt(fix(OTHER, [first.event_id]))


def case_second_press(m, db, mp):
    ready(db.store)
    words = typed()
    db.store.append_receipt(words)
    db.store.append_receipt(press(words))
    return db.store_of(m).append_receipt(press(words, action_id="cb-705"))


def case_stale_reopen(m, db, mp):
    ready(db.store)
    db.store.append_receipt(receipt())
    return db.store_of(m).append_receipt(reopen(1, ()))


def case_slow_caller(m, db, mp):
    """A caller behind the latest revision merges onto the latest record, never its stale prior."""
    first = ready(db.store)
    db.store.append_receipt(receipt())
    result = db.store_of(m).merge_candidate(caller(PROFILE_3, prior=(1, first.record_json)))
    return result, len(json.loads(result.record_json)["events"])


RETAINED_UPDATE = (
    "session.exec(update(ClarificationStream).where(col(ClarificationStream.stream_id) == loaded.stream_id)"
    ".values(updated_at=utcnow(), receipt_count=col(ClarificationStream.receipt_count) + 1))"
)
# name: (text in store.py, its replacement, case, the case's outcome with the text in place)
SWAPS = {
    "cas.rowcount": ("if session.exec(statement).rowcount == 1:  # type: ignore[call-overload]",
                     "if session.exec(statement) is not None:", case_retained_race, ("result", "applied", None, 3, 4)),
    "cas.conflict": ("        check_expected_revision(expected, committed)\n", "", case_forced_miss,
                     (("result", "applied", None, 2, 3), True)),
    "cas.row_gone": ("raise _Retry  # the row is gone: the next read reports what is missing", "pass", case_row_gone,
                     integrity("stream.missing")),
    "attempt.retry": ("except _Retry:\n                    session.rollback()", "except _Retry:\n                    raise",
                      case_rival_create, ("record", 2, True)),
    "attempt.conflict": ("if refusal.code is not RefusalCode.REVISION_CONFLICT:", "if True:", case_forced_miss,
                         (("result", "applied", None, 2, 3), True)),
    "commit.explained": ("raise _Retry from None", "raise", case_rival_create, ("record", 2, True)),
    "commit.unexplained": ("if not explained(session):", "if False:", case_unexplained_clash, ("re-raised", True)),
    "fence": ("if self._generation(session, stream_id, question_id) != generation:", "if False:", case_fence,
              ("result", "retained", "stale_presentation", 1, 1)),
    "load.created_between": ("raise _Retry  # created between the two reads", "pass", case_created_between,
                             ("record", 1, False)),
    "load.ahead_between": ("raise _Retry  # another writer committed between the reads", "pass", case_ahead_between,
                           ("result", "applied", None, 2, 3)),
    "append.kept_between": ("raise _Retry  # kept between the two reads: answer it as a replay", "pass",
                            case_kept_between, ("result", "applied", None, 1, 2)),
    "append.replay": ("return self._replay(session, kept.stream_id, receipt, digest)", "pass", case_replay,
                      ("result", "applied", None, 1, 2)),
    "replay.gone": ("raise _Retry  # gone between the two reads: the next read reports it", "pass", case_replay_gone,
                    ("result", "refused", "missing_record", 0, 0)),
    "precondition.correction": ('if receipt.intent == "correct":', "if False:", case_cross_actor,
                                ("result", "retained", "cross_actor_correction", 2, 2)),
    "precondition.confirmation": ("if receipt.confirms is not None:\n                check_confirmation_precondition",
                                  "if False:\n                check_confirmation_precondition", case_second_press,
                                  ("result", "retained", "already_confirmed", 2, 2)),
    "precondition.reopen": ('if receipt.intent == "reopen":', "if False:", case_stale_reopen,
                            ("result", "retained", "stale_reopen", 2, 2)),
    "retain.cas": ('self._cas(session, loaded.stream_id, expected, adds="receipt")',
                   RETAINED_UPDATE, case_retained_race, ("result", "applied", None, 3, 4)),
    "merge.latest": ("record = self._candidate_record(caller, loaded.record)",
                     "record = self._candidate_record(caller, caller.prior_record())", case_slow_caller,
                     (("record", 3, True), 1)),
}

GUARD_ARG = {"_require": 2, "_intact": 2, "ContractRefusal": 1, "ClarificationIntegrityError": 1, "_refuse": 6}


def callee(call):
    return call.func.id if isinstance(call.func, ast.Name) else getattr(call.func, "attr", None)


def guard_of(call):
    """The literal guard name a refusal, integrity or diagnostic call carries, if any."""
    index = GUARD_ARG.get(callee(call))
    if index is None or len(call.args) <= index:
        return None
    argument = call.args[index]
    return argument.value if isinstance(argument, ast.Constant) and isinstance(argument.value, str) else None


class DropGuard(ast.NodeTransformer):
    """Remove one guard everywhere: its check passes, its raise or refusal is skipped."""

    def __init__(self, guard):
        self.guard = guard
        self.dropped = 0

    def visit_Call(self, node):
        self.generic_visit(node)
        if callee(node) in ("_require", "_intact") and guard_of(node) == self.guard:
            node.args[0] = ast.Constant(True)
            self.dropped += 1
        return node

    def visit_Raise(self, node):
        if isinstance(node.exc, ast.Call) and callee(node.exc) in GUARD_ARG and guard_of(node.exc) == self.guard:
            self.dropped += 1
            return ast.copy_location(ast.Pass(), node)
        return self.generic_visit(node)

    def visit_Return(self, node):
        if isinstance(node.value, ast.Call) and callee(node.value) == "_refuse" and guard_of(node.value) == self.guard:
            self.dropped += 1
            return ast.copy_location(ast.Pass(), node)
        return self.generic_visit(node)


def mutant(mp, code):
    """store.py built from changed source or tree, with a retry counter: a runaway retry loop is an error."""
    name = "clarification_store_mutant"
    module = types.ModuleType(name)
    module.__file__ = S.__file__
    mp.setitem(sys.modules, name, module)  # dataclasses look their module up while the classes are built
    exec(compile(code, S.__file__, "exec"), module.__dict__)
    module._shared_foundation = lambda: F
    opened = []

    class Counted(Session):
        def __init__(self, *args, **kwargs):
            opened.append(True)
            if len(opened) > 300:
                raise RuntimeError("runaway retries")
            super().__init__(*args, **kwargs)

    module.Session = Counted
    return module


@pytest.mark.parametrize("state", [state for state, outcome in CORRECTION_STATES.items() if outcome is not None])
def test_retained_unknown_correction_check_has_a_semantic_bite(lite, monkeypatch, state):
    """Bypass only the new retention check: the same named regression fails specifically on retention."""
    test_unknown_correction_never_retains_and_same_key_recovers(lite, state, "other_then_unknown")
    lite.clear()
    old = 'if validation.status == "retained":'
    assert SOURCE.count(old) == 1
    changed = mutant(monkeypatch, SOURCE.replace(old, "if False:"))
    lite.store = lite.store_of(changed)
    with pytest.raises(AssertionError, match="unknown correction retained"):
        test_unknown_correction_never_retains_and_same_key_recovers(lite, state, "other_then_unknown")
    key = press(typed()).action.key if state.startswith("press") else fix(OWNER, [NO_EVENT]).action.key
    kept = next(row for row in lite.rows(M.ClarificationReceipt) if row.action_key == key)
    assert (kept.status, kept.code, kept.guard) == ("retained", *CORRECTION_STATES[state])
    assert NO_EVENT in C.receipt_from_json(kept.receipt_json).supersedes
    assert diag(lite) == []  # exactly the old defect, not an unrelated exception


def test_retention_check_cannot_override_an_earlier_refusal(lite, monkeypatch):
    old = 'if validation.status == "retained":'
    assert SOURCE.count(old) == 1
    changed = mutant(monkeypatch, SOURCE.replace(old, 'if validation.status != "accepted":'))
    lite.store = lite.store_of(changed)
    with pytest.raises(AssertionError, match="earlier refusal replaced"):
        test_unknown_correction_preserves_earlier_provenance_and_binding_refusals(lite, "no_disposition", "model")
    assert diag(lite) == [("missing_record", "correction.known")]
    assert lite.rows(M.ClarificationReceipt) == []


def test_retention_check_changes_only_unknown_target_outcomes(lite, monkeypatch):
    old = "if refusal is not None and refusal.code is RefusalCode.MISSING_RECORD:"
    assert SOURCE.count(old) == 1
    changed = mutant(monkeypatch, SOURCE.replace(old, "if refusal is not None:"))
    lite.store = lite.store_of(changed)
    with pytest.raises(AssertionError, match="prior retained outcome changed"):
        test_known_corrections_preserve_prior_retained_outcomes(lite, "no_disposition", "other")
    kept = next(row for row in lite.rows(M.ClarificationReceipt) if row.action_key == fix(OWNER, [NO_EVENT]).action.key)
    assert (kept.status, kept.code) == ("retained", "cross_actor_correction")


def test_every_guard_in_the_store_has_a_case():
    found = {guard_of(node) for node in ast.walk(ast.parse(SOURCE)) if isinstance(node, ast.Call)} - {None}
    assert found == set(GUARD_CASES)


@pytest.mark.parametrize("guard", sorted(GUARD_CASES))
def test_every_guard_case_holds(db, guard):
    case, expected = GUARD_CASES[guard]
    with pytest.MonkeyPatch.context() as mp:
        assert outcome(S, case, db, mp) == expected


@pytest.mark.parametrize("guard", sorted(GUARD_CASES))
def test_every_guard_has_a_bite(lite, guard):
    case, expected = GUARD_CASES[guard]
    dropper = DropGuard(guard)
    tree = ast.fix_missing_locations(dropper.visit(ast.parse(SOURCE)))
    assert dropper.dropped >= 1
    with pytest.MonkeyPatch.context() as mp:
        assert outcome(mutant(mp, tree), case, lite, mp) != expected


@pytest.mark.parametrize("name", sorted(SWAPS))
def test_every_retry_branch_holds(db, name):
    _, _, case, expected = SWAPS[name]
    with pytest.MonkeyPatch.context() as mp:
        assert outcome(S, case, db, mp) == expected


@pytest.mark.parametrize("name", sorted(SWAPS))
def test_every_retry_branch_has_a_bite(lite, name):
    old, new, case, expected = SWAPS[name]
    assert SOURCE.count(old) == 1
    with pytest.MonkeyPatch.context() as mp:
        assert outcome(mutant(mp, SOURCE.replace(old, new)), case, lite, mp) != expected
