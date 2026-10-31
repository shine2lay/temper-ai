"""Actual M1/M3 store + actual M2 edge/poller, synthetic provider and authority.

This proves the binding, not a human observer or a release. Update builders and
provider behavior are reused; World.__init__ (the old fake store) is never used.
"""

from __future__ import annotations

import itertools
from dataclasses import replace

import pytest
from sqlalchemy import event, update

from temper_ai.clarifications import contracts as C
from temper_ai.clarifications import delivery_models as D
from temper_ai.clarifications import delivery_store as L
from temper_ai.clarifications import models as M
from temper_ai.clarifications import preparation_adapter
from temper_ai.clarifications.delivery_store import ClarificationDeliveryStore
from temper_ai.clarifications.store import ClarificationIntegrityError
from temper_ai.integrations.telegram import clarification_store as binding_module
from temper_ai.integrations.telegram import clarifications as E
from temper_ai.integrations.telegram import poller
from temper_ai.integrations.telegram.clarification_store import (
    TelegramClarificationStore,
)
from tests.test_clarifications import composition_scenarios as shared
from tests.test_clarifications import test_store as store_cases
from tests.test_clarifications.test_delivery_store import replace_method
from tests.test_integrations import test_telegram_clarifications as original
from tests.test_integrations.conftest import TG_BOT, TG_GROUP, TG_OTHER, TG_OWNER

db = store_cases.db  # actual per-dialect isolated fixture, not the original M2 fake


class Authority:
    def __init__(self):
        self.denied = set()
        self.calls = []

    def require(self, **scope):
        self.calls.append(scope)
        if scope["operation"] in self.denied:
            raise PermissionError("synthetic authority denied")


class BoundWorld(original.World):
    """Reuse M2's synthetic update constructors with the real durable store port."""

    def __init__(self, db):
        self.db = db
        self.caller = shared.inputs(shared.composition_profile(), transport=original.BOT, chat_id=str(TG_GROUP))
        self.question = C.question_id(shared.BRIEF_SHA, shared.COMPOSITION_UNKNOWN)
        self.caller = replace(self.caller, question_ids=(self.question,))
        self.prepared = preparation_adapter.prepare(self.caller)
        db.store.merge_candidate(self.caller)
        row = shared.row(self.prepared, self.question)
        self.presentation_value = self.caller.presentation(self.question, row["metadata_sha256"], 1)
        db.store.save_presentation(self.presentation_value)
        self.authority = Authority()
        self.telegram = shared.SyntheticTelegram(bot_id=TG_BOT, message_ids=range(500, 1000))
        self._updates, self._messages, self._queries = itertools.count(1), itertools.count(5000), itertools.count(1)
        self.P = poller
        self.policy = shared.SyntheticResponderPolicy({(self.caller.responder_policy_ref, str(TG_GROUP), str(TG_OWNER))})
        self.got = []
        self.committed_before_effect = []
        self.rebind()
        send, answer = self.telegram.send, self.telegram.answer_callback

        def observed_send(*args, **kwargs):
            # Independent durable read before the provider effect (not a fake-store log).
            view = self.db.store.protocol_view(self.caller.stream)
            assert any(self.store.ledger.send(row.send_id, stream=self.caller.stream).state == "uncertain"
                       for row in self.db.rows(D.ClarificationSend))
            if kwargs.get("keyboard"):
                assert len(self.db.rows(D.ClarificationIngress)) >= 1 and len(view.receipts) >= 1
            self.committed_before_effect.append(("send", self.offset()))
            return send(*args, **kwargs)

        def observed_answer(*args, **kwargs):
            assert len(self.db.rows(D.ClarificationIngress)) >= 1
            self.committed_before_effect.append(("ack", self.offset()))
            return answer(*args, **kwargs)

        self.telegram.send, self.telegram.answer_callback = observed_send, observed_answer

    def rebind(self):
        self.store = TelegramClarificationStore(
            self.db.store, ClarificationDeliveryStore(self.db.store), authority=self.authority,
            stream=self.caller.stream, source_authority_ref=self.caller.source_authority_ref,
            responder_policy_ref=self.caller.responder_policy_ref,
        )
        self.edge = E.ClarificationEdge(self.telegram, self.store, self.policy)
        self.poller = poller.Poller(self.telegram, self.got.append, timeout=0, clarifications=self.edge)

    def ask(self):
        sent = self.edge.present(self.presentation_value, shared.COMPOSITION_UNKNOWN, original.QUESTION)
        assert sent.state == "sent"
        return int(sent.message_id)

    def poll(self):
        return self.poller.poll_once()

    def held(self, update):
        return self.store.receipt(self.key(update))


def test_whole_actual_store_and_real_edge_happy_path_before_edges(db):
    w = BoundWorld(db)
    question = w.ask()
    typed = w.reply(question, original.EXACT)
    assert w.poll() == 0 and w.got == []
    held = w.held(typed)
    assert held.text == original.EXACT and held.disposition is None
    assert db.store.load(w.caller.stream).revision == 1
    assert len(db.rows(D.ClarificationIngress)) == 1
    prompt = w.prompts()[0]["message_id"]
    press = w.press(prompt, "clar:answered")
    before_offset = w.offset()
    assert w.poll() == 0 and w.offset() == str(press["update_id"] + 1)
    assert w.committed_before_effect[-1] == ("ack", before_offset)
    assert w.telegram.callbacks[-1][1] == "Received."
    loaded = db.store.load(w.caller.stream)
    assert loaded.revision == 2 and loaded.record()["events"][0]["answer"] == original.EXACT
    assert w.store.answered(w.caller.stream.stream_id, w.question)
    assert w.store.copies(w.presentation_value.presentation_id) == frozenset({str(question), str(prompt)})
    assert all(w.store.delivery(original.BOT, str(TG_GROUP), str(mid)) is not None for mid in (question, prompt))
    supplement = db.store.supplement(w.caller.stream, revision=2, original_brief=shared.BRIEF)
    assert supplement.original_brief == shared.BRIEF
    ack = dict(revision=2, record_sha256=supplement.record_sha256, consumption_id=supplement.consumption_id,
               original_brief=shared.BRIEF)
    assert db.store.mark_current_consumed(w.caller.stream, **ack)
    db.restart()
    w.rebind()
    before = db.dump()
    w.rewind(press)
    assert w.poll() == 0 and w.edge.counts["repeat"] == 1
    # Offset is observation metadata: a replay under another pull offset may
    # add one non-body observation, but never another receipt/event/ack/send.
    after = db.dump()
    assert {k: v for k, v in after.items() if k not in ("clarification_streams", "clarification_ingresses")} == {
        k: v for k, v in before.items() if k not in ("clarification_streams", "clarification_ingresses")}
    assert db.store.mark_current_consumed(w.caller.stream, **ack) is False
    assert len(w.prompts()) == 1 and len(db.rows(M.ClarificationReceipt)) == 2


@pytest.mark.parametrize("operation", ["read", "write", "send"])
def test_denied_authority_blocks_before_side_effects(db, operation):
    w = BoundWorld(db)
    w.authority.denied.add(operation)
    before = db.dump()
    with pytest.raises(PermissionError):
        w.ask()
    assert db.dump() == before and w.telegram.sent == []
    assert w.authority.calls[-1]["operation"] == operation
    assert all(call["stream"] == w.caller.stream and call["source_authority_ref"] == w.caller.source_authority_ref
               and call["responder_policy_ref"] == w.caller.responder_policy_ref for call in w.authority.calls)


@pytest.mark.parametrize("method", ["delivery", "copies", "generation", "questions", "answered", "receipt",
                                   "save", "admit", "complete", "receipt_write", "refuse"])
def test_every_protocol_operation_requires_explicit_authority(db, method):
    w = BoundWorld(db)
    question = w.ask()
    typed = w.reply(question, original.EXACT)
    w.poll()
    receipt = w.held(typed)
    ingress = E.PulledIngress(original.BOT, typed["update_id"], original.digest(typed), None)
    validation = C.validate_receipt(receipt, presentation=w.presentation_value, copies={str(question)},
                                    current_generation=1, question_ids={w.question})
    intent = E.SendIntent(w.presentation_value.presentation_id, w.presentation_value, original.QUESTION)
    operations = {
        "delivery": lambda: w.store.delivery(original.BOT, str(TG_GROUP), str(question)),
        "copies": lambda: w.store.copies(intent.send_id),
        "generation": lambda: w.store.current_generation(w.caller.stream.stream_id, w.question),
        "questions": lambda: w.store.question_ids(w.caller.stream.stream_id),
        "answered": lambda: w.store.answered(w.caller.stream.stream_id, w.question),
        "receipt": lambda: w.store.receipt(receipt.action.key),
        "save": lambda: w.store.save_send(intent),
        "admit": lambda: w.store.start_attempt(intent.send_id, expected_attempts=0, resend=True),
        "complete": lambda: w.store.record_delivery(intent.send_id, "555"),
        "receipt_write": lambda: w.store.keep_receipt(ingress, receipt, validation),
        "refuse": lambda: w.store.keep_refusal(E.Refusal(ingress, C.RefusalCode.MALFORMED, "synthetic")),
    }
    w.authority.denied.add("read")
    before = db.dump()
    with pytest.raises(PermissionError):
        operations[method]()
    assert db.dump() == before


def test_other_source_policy_stream_and_engine_are_not_implicit_authority(db):
    w = BoundWorld(db)
    question = w.ask()
    before = db.dump()
    with pytest.raises(C.ContractRefusal) as same:
        TelegramClarificationStore(db.store, ClarificationDeliveryStore(db.other()), authority=w.authority,
                                   stream=w.caller.stream, source_authority_ref=w.caller.source_authority_ref,
                                   responder_policy_ref=w.caller.responder_policy_ref)
    assert same.value.guard == "telegram_store.same_store"
    w.store.source_authority_ref = "authority:synthetic/other"
    with pytest.raises(C.ContractRefusal) as source:
        w.store.copies(w.presentation_value.presentation_id)
    assert source.value.guard == "telegram_store.source"
    w.store.source_authority_ref = w.caller.source_authority_ref
    w.store.responder_policy_ref = "policy:synthetic/other"
    with pytest.raises(C.ContractRefusal) as policy:
        w.store.delivery(original.BOT, str(TG_GROUP), str(question))
    assert policy.value.guard == "telegram_store.policy"
    with pytest.raises(C.ContractRefusal) as stream:
        w.store.question_ids("s-foreign")
    assert stream.value.guard == "telegram_store.stream" and db.dump() == before


@pytest.mark.parametrize("where", ["before", "after"])
def test_commit_failure_holds_offset_and_successful_replay_keeps_one_receipt(db, monkeypatch, where):
    w = BoundWorld(db)
    question = w.ask()
    typed = w.reply(question, original.EXACT)
    commit = db.store._commit

    def interrupted(session, explained):
        if where == "after":
            commit(session, explained)
        raise OSError("synthetic storage interruption")

    monkeypatch.setattr(db.store, "_commit", interrupted)
    with pytest.raises(OSError):
        w.poll()
    assert w.offset() is None and w.telegram.callbacks == [] and w.prompts() == []
    assert len(db.rows(D.ClarificationIngress)) == int(where == "after")
    assert len(db.rows(M.ClarificationReceipt)) == int(where == "after")
    monkeypatch.setattr(db.store, "_commit", commit)
    assert w.poll() == 0 and w.held(typed).text == original.EXACT
    assert len(db.rows(M.ClarificationReceipt)) == 1 and len(db.rows(D.ClarificationIngress)) == 1
    assert w.offset() == str(typed["update_id"] + 1)


def test_exact_final_refusal_is_committed_then_not_applied(db, monkeypatch):
    w = BoundWorld(db)
    question = w.ask()
    typed = w.reply(question, original.EXACT)
    w.poll()
    prompt = w.prompts()[0]["message_id"]
    press = w.press(prompt, "clar:answered")
    before = w.offset()
    original_append = db.store.append_receipt_with_ingress

    def changed_after_capture(ingress, receipt, validation):
        # A genuine action key/body race, after the edge's accepted validation.
        assert validation.status == "accepted"
        other = replace(receipt, disposition="unknown", callback_data="clar:unknown")
        other_validation = C.validate_receipt(other, presentation=w.presentation_value,
                                              copies=w.store.copies(w.presentation_value.presentation_id),
                                              current_generation=1, question_ids={w.question}, confirmed=w.held(typed))
        original_append(ingress, other, other_validation)
        return original_append(ingress, receipt, validation)

    monkeypatch.setattr(db.store, "append_receipt_with_ingress", changed_after_capture)
    assert w.poll() == 0
    assert w.telegram.callbacks[-1] == (press["callback_query"]["id"], "Not applied.", False)
    assert w.committed_before_effect[-1] == ("ack", before)
    assert w.edge.counts["refused"] == 1 and w.offset() == str(press["update_id"] + 1)
    assert len(db.rows(M.ClarificationRefusal)) == 1
    assert any(row.diagnostic_code == C.RefusalCode.CHANGED_BODY.value for row in db.rows(D.ClarificationIngress))
    assert db.store.load(w.caller.stream).revision == 2


@pytest.mark.parametrize("error", [OSError, C.ContractRefusal])
def test_only_committed_refusal_subtype_is_caught(db, monkeypatch, error):
    w = BoundWorld(db)
    question = w.ask()
    typed = w.reply(question, original.EXACT)
    w.poll()
    w.press(w.prompts()[0]["message_id"], "clar:answered")
    before = w.offset()

    def fail(*args):
        if error is C.ContractRefusal:
            raise error(C.RefusalCode.MALFORMED, "synthetic.uncommitted", "receipt")
        raise error("synthetic outage")

    monkeypatch.setattr(db.store, "append_receipt_with_ingress", fail)
    with pytest.raises(error):
        w.poll()
    assert w.offset() == before and w.telegram.callbacks == []
    assert len(db.rows(M.ClarificationReceipt)) == 1 and len(db.rows(M.ClarificationRefusal)) == 0
    assert w.held(typed).text == original.EXACT


@pytest.mark.parametrize("kind", ["missing_sender", "denied_responder"])
def test_refusal_linkage_distinguishes_unconstructible_and_denied_receipt(db, kind):
    w = BoundWorld(db)
    question = w.ask()
    update = w.reply(question, original.EXACT, user=TG_OTHER)
    if kind == "missing_sender":
        del update["message"]["from"]
    assert w.poll() == 0
    assert db.rows(M.ClarificationReceipt) == [] and w.prompts() == []
    rows = db.rows(D.ClarificationIngress)
    assert len(rows) == 1
    if kind == "missing_sender":
        assert rows[0].receipt_sha256 is None and rows[0].action_key is None and rows[0].refusal_id is None
        assert rows[0].diagnostic_code == C.RefusalCode.MALFORMED.value
    else:
        assert rows[0].receipt_sha256 is not None and rows[0].action_key == w.key(update)
        assert rows[0].refusal_id is not None
        assert rows[0].diagnostic_code == C.RefusalCode.RESPONDER_NOT_AUTHORISED.value
    assert db.store.load(w.caller.stream).revision == 1


def test_unknown_copy_ordinary_fallback_then_explicit_reconciliation(db):
    w = BoundWorld(db)
    question = w.ask()
    lost_copy = 503
    update = w.reply(lost_copy, original.EXACT)
    assert w.poll() == 1 and w.got == [update]  # ordinary path is not claimed to be a no-op
    assert db.rows(M.ClarificationReceipt) == []
    w.store.record_delivery(w.presentation_value.presentation_id, str(lost_copy))
    batch = w.edge.pull(w.telegram, update["update_id"], timeout=0, allowed=poller.ALLOWED)
    with pytest.raises(C.ContractRefusal) as forged:
        batch.claim(dict(update))  # not that pull's object; saved ordinary data is not authentication
    assert forged.value.code == C.RefusalCode.UNVERIFIED_INGRESS
    assert batch.claim(batch.updates[0])
    assert w.held(update).text == original.EXACT
    assert {str(question), str(lost_copy)} <= w.store.copies(w.presentation_value.presentation_id)


@pytest.mark.parametrize("disposition", ["answered", "deferred", "unknown"])
def test_capture_is_independent_and_only_exact_same_author_press_applies(db, disposition):
    w = BoundWorld(db)
    question = w.ask()
    typed = w.reply(question, original.EXACT)
    batch = w.edge.pull(w.telegram, None, timeout=0, allowed=poller.ALLOWED)
    pulled = batch.updates[0]
    pulled["message"]["text"] = "not the captured words"
    assert batch.claim(pulled)
    assert w.held(typed).text == original.EXACT
    prompt = w.prompts()[0]["message_id"]
    other = w.press(prompt, "clar:" + disposition, user=TG_OTHER)
    batch = w.edge.pull(w.telegram, other["update_id"], timeout=0, allowed=poller.ALLOWED)
    assert batch.claim(batch.updates[0]) and w.held(other) is None
    own = w.press(prompt, "clar:" + disposition)
    batch = w.edge.pull(w.telegram, own["update_id"], timeout=0, allowed=poller.ALLOWED)
    pulled = batch.updates[0]
    pulled["callback_query"]["data"] = "clar:other"
    assert batch.claim(pulled)
    assert w.held(own).disposition == disposition
    loaded = db.store.load(w.caller.stream)
    assert loaded.revision == 2 and loaded.record()["events"][0]["answer"] == original.EXACT
    assert w.store.answered(w.caller.stream.stream_id, w.question) == (disposition == "answered")


@pytest.mark.parametrize("arrival", ["already_kept", "after_scope_check"])
def test_global_action_collision_is_scoped_without_foreign_body_or_history(db, monkeypatch, arrival):
    r = store_cases
    r.ready(db.store)
    foreign = r.C.StreamKey("synthetic:scoped-replay", r.BRIEF_SHA)
    caller = r.caller(stream=foreign)
    p = r.present(stream=foreign)
    db.store.merge_candidate(caller)
    db.store.save_presentation(p)
    db.store.record_copy(r.binding(p))
    collision = r.receipt(p=p)
    ingress = E.PulledIngress(r.TRANSPORT, collision.update_id, "1" * 64, None)
    validation = C.validate_receipt(collision, presentation=p, copies={"500"}, current_generation=1,
                                    question_ids={r.QID, r.QID2})
    assert validation.status == "accepted"
    adapter = TelegramClarificationStore(db.store, ClarificationDeliveryStore(db.store), authority=Authority(),
                                        stream=foreign, source_authority_ref=caller.source_authority_ref,
                                        responder_policy_ref=caller.responder_policy_ref)
    rival = db.other()
    if arrival == "already_kept":
        rival.append_receipt(r.receipt())
    else:
        original = db.store.append_receipt_with_ingress

        def arrives(*args):
            rival.append_receipt(r.receipt())
            return original(*args)

        monkeypatch.setattr(db.store, "append_receipt_with_ingress", arrives)
    load = db.store._load

    def scoped_load(session, stream_id):
        assert stream_id == foreign.stream_id, "foreign history read"
        return load(session, stream_id)

    def scoped_columns(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("SELECT") and "clarification_receipts.receipt_json" in statement:
            assert "WHERE clarification_receipts.stream_id =" in statement, "unscoped receipt body read"

    with monkeypatch.context() as scoped:
        scoped.setattr(db.store, "_load", scoped_load)
        event.listen(db.engine, "before_cursor_execute", scoped_columns)
        try:
            with pytest.raises(E.ReceiptApplicationRefusal) as refused:
                adapter.keep_receipt(ingress, collision, validation)
            assert (refused.value.code, refused.value.guard) == (C.RefusalCode.CROSS_CONTEXT, "replay.stream")
            append_decision = db.store._append

            def missing_scope(session, receipt, digest, **kwargs):
                return append_decision(session, receipt, digest, restrict_replay_to_receipt_stream=False)

            scoped.setattr(db.store, "_append", missing_scope)
            with pytest.raises(AssertionError, match="foreign history read"):
                adapter.keep_receipt(ingress, collision, validation)
        finally:
            event.remove(db.engine, "before_cursor_execute", scoped_columns)
    assert db.store.load(foreign).revision == 1 and rival.load(r.STREAM).revision == 2
    assert len(db.rows(M.ClarificationReceipt)) == 1
    diagnostic = db.rows(M.ClarificationRefusal)[0]
    observation = db.rows(D.ClarificationIngress)[0]
    assert diagnostic.stream_id == observation.stream_id == foreign.stream_id
    assert observation.diagnostic_code == C.RefusalCode.CROSS_CONTEXT and observation.result_json is not None
    # The trusted, unscoped legacy API keeps its historical global replay semantics.
    legacy = db.store.append_receipt(collision)
    assert (legacy.code, legacy.stream_id) == (C.RefusalCode.CHANGED_BODY, r.STREAM.stream_id)


def test_foreign_send_collision_checks_identity_without_reading_intent_body(db, monkeypatch):
    r = store_cases
    r.ready(db.store)
    ledger = ClarificationDeliveryStore(db.store)
    first = E.SendIntent("synthetic-collision", r.P1, original.QUESTION)
    ledger.save_send(first)
    bound = r.C.StreamKey("synthetic:send-scope", r.BRIEF_SHA)
    caller, presentation = r.caller(stream=bound), r.present(stream=bound)
    db.store.merge_candidate(caller)
    db.store.save_presentation(presentation)
    adapter = TelegramClarificationStore(db.store, ledger, authority=Authority(), stream=bound,
                                        source_authority_ref=caller.source_authority_ref,
                                        responder_policy_ref=caller.responder_policy_ref)
    incoming = replace(first, presentation=presentation)
    before = db.dump()

    def scoped_columns(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("SELECT") and "clarification_sends.intent_json" in statement:
            assert "WHERE clarification_sends.stream_id =" in statement, "foreign intent body read"

    event.listen(db.engine, "before_cursor_execute", scoped_columns)
    try:
        with pytest.raises(C.ContractRefusal) as collision:
            adapter.save_send(incoming)
        assert collision.value.guard == "send.changed"
        monkeypatch.setattr(L, "_has_send", lambda session, send_id: session.get(D.ClarificationSend, send_id) is not None)
        with pytest.raises(AssertionError, match="foreign intent body read"):
            adapter.save_send(incoming)
    finally:
        event.remove(db.engine, "before_cursor_execute", scoped_columns)
    assert db.dump() == before


@pytest.mark.parametrize("guard", ["authority", "binding", "same_store", "source", "policy", "stream", "ingress",
                                   "presentation"])
def test_adapter_scope_guards_have_specific_bites(db, monkeypatch, guard):
    w = BoundWorld(db)
    question = w.ask()
    typed = w.reply(question, original.EXACT)
    w.poll()
    receipt = w.held(typed)
    view = db.store.protocol_view(w.caller.stream)
    if guard in ("authority", "binding", "same_store"):
        parameters = dict(authority=w.authority, stream=w.caller.stream,
                          source_authority_ref=w.caller.source_authority_ref,
                          responder_policy_ref=w.caller.responder_policy_ref)
        ledger = w.store.ledger
        if guard == "authority":
            parameters["authority"] = None
        elif guard == "binding":
            parameters["source_authority_ref"] = ""
        else:
            ledger = ClarificationDeliveryStore(db.other())

        def invoke():
            return TelegramClarificationStore(db.store, ledger, **parameters)
    elif guard in ("source", "policy"):
        if guard == "source":
            w.store.source_authority_ref = "authority:other"
        else:
            w.store.responder_policy_ref = "policy:other"

        def invoke():
            return w.store.copies(w.presentation_value.presentation_id)
    elif guard == "stream":
        def invoke():
            return w.store.question_ids("s-foreign")
    elif guard == "ingress":
        ingress = E.PulledIngress(C.TransportNamespace("telegram", "7002"), 999, "0" * 64, None)

        def invoke():
            return w.store.keep_refusal(E.Refusal(ingress, C.RefusalCode.MALFORMED, "synthetic.other_bot"))
    else:
        missing = replace(w.presentation_value, generation=2)
        unbound = replace(receipt, binding=replace(receipt.binding, presentation_id=missing.presentation_id, generation=2))

        def invoke():
            return w.store._receipt_scope(view, unbound)
    name = "telegram_store." + guard
    before = db.dump()
    with pytest.raises(C.ContractRefusal) as refused:
        invoke()
    assert refused.value.guard == name and db.dump() == before
    require = binding_module._require
    monkeypatch.setattr(binding_module, "_require", lambda ok, code, label, where: None if label == name
                        else require(ok, code, label, where))
    if guard == "presentation":
        # Defined-diagnostic guard, not an effect-prevention claim: an absent
        # presentation must yield MISSING_BINDING, never leak a None dereference.
        with pytest.raises(AttributeError) as missing:
            invoke()
        assert missing.value.name == "stream" and missing.value.obj is None
    else:
        result = invoke()
        if guard in ("source", "policy"):
            assert str(question) in result  # forbidden checked membership was exposed
        elif guard == "stream":
            assert w.question in result  # wrong named stream silently read this binding
        elif guard == "ingress":
            assert any(row.bot_id == "7002" for row in db.rows(D.ClarificationIngress))
        else:
            assert isinstance(result, TelegramClarificationStore)  # invalid binding wrongly admitted


@pytest.mark.parametrize("operation", ["read", "write", "send"])
def test_authority_enforcement_removal_admits_the_forbidden_send(db, monkeypatch, operation):
    w = BoundWorld(db)
    w.authority.denied.add(operation)
    with pytest.raises(PermissionError):
        w.ask()
    assert w.telegram.sent == []
    replace_method(monkeypatch, TelegramClarificationStore, "_view", "self.authority.require", "(lambda **scope: None)")
    question = w.ask()
    assert len(w.telegram.sent) == 1
    assert w.store.delivery(original.BOT, str(TG_GROUP), str(question)) is not None  # forbidden effect really committed


@pytest.mark.parametrize("catch", ["ContractRefusal", "Exception"])
def test_broad_final_refusal_catch_wrongly_acknowledges_uncommitted_failure(db, monkeypatch, catch):
    w = BoundWorld(db)
    question = w.ask()
    w.reply(question, original.EXACT)
    w.poll()
    press = w.press(w.prompts()[0]["message_id"], "clar:answered")
    before = w.offset()

    def uncommitted(*args):
        raise C.ContractRefusal(C.RefusalCode.MALFORMED, "synthetic.uncommitted", "receipt")

    monkeypatch.setattr(db.store, "append_receipt_with_ingress", uncommitted)
    with pytest.raises(C.ContractRefusal):
        w.poll()
    assert w.offset() == before and w.telegram.callbacks == []
    replace_method(monkeypatch, E.ClarificationEdge, "_keep", "except ReceiptApplicationRefusal as refusal:",
                   "except " + catch + " as refusal:")
    assert w.poll() == 0
    assert w.offset() == str(press["update_id"] + 1)
    assert w.telegram.callbacks[-1][1] == "Not applied."  # exactly the forbidden ack of an uncommitted error


def test_suppressed_application_commit_bite_acknowledges_an_absent_answer(db, monkeypatch):
    w = BoundWorld(db)
    question = w.ask()
    w.reply(question, original.EXACT)
    w.poll()
    press = w.press(w.prompts()[0]["message_id"], "clar:answered")
    monkeypatch.setattr(db.store, "_commit_receipt", lambda session, outcome: session.rollback())
    assert w.poll() == 0
    assert w.offset() == str(press["update_id"] + 1) and w.telegram.callbacks[-1][1] == "Received."
    assert db.store.load(w.caller.stream).revision == 1 and len(db.rows(M.ClarificationReceipt)) == 1
    assert w.held(press) is None  # no result exists despite the success acknowledgement
    with pytest.raises(AssertionError, match="application commit before ack"):
        assert db.store.load(w.caller.stream).revision == 2, "application commit before ack"


def test_checked_delivery_refuses_damage_before_poller_offset_moves(db):
    w = BoundWorld(db)
    question = w.ask()
    w.reply(question, original.EXACT)
    db.run(update(D.ClarificationDelivery).values(delivery_sha256="0" * 64))
    with pytest.raises(ClarificationIntegrityError) as damaged:
        w.poll()
    assert damaged.value.guard == "delivery.digest" and w.offset() is None
    assert db.rows(M.ClarificationReceipt) == []
