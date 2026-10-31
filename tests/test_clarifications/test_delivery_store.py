"""M4 B actual-database controls. Synthetic only; no fake lock or live DB.

Fixtures reuse M3's isolated per-dialect databases and original receipt cases.
Assertions inspect durable rows, not provider/model request logs. The real-edge
combined path lives first in test_telegram_store_binding.py.
"""

from __future__ import annotations

import inspect
import json
import multiprocessing
import os
import subprocess
import sys
import textwrap
from dataclasses import asdict, fields, replace
from functools import partial

import pytest
from sqlalchemy import delete, update
from sqlmodel import Session

from temper_ai.clarifications import delivery_models as D
from temper_ai.clarifications import delivery_store as L
from temper_ai.clarifications import models as M
from temper_ai.clarifications import store as S
from temper_ai.database.engine import create_app_engine, create_test_engine
from temper_ai.integrations.telegram import clarifications as E
from tests.test_clarifications import composition_scenarios as shared
from tests.test_clarifications import test_store as R

# Reuse the original isolated per-dialect database fixtures without re-exporting tests.
db, lite = R.db, R.lite


def intent_ready(store, *, delivery=False):
    store.merge_candidate(R.caller())
    store.save_presentation(R.P1)
    ledger = L.ClarificationDeliveryStore(store)
    intent = E.SendIntent(R.P1.presentation_id, R.P1, "Synthetic question")
    ledger.save_send(intent)
    if delivery:
        ledger.record_delivery(intent.send_id, "500")
    return ledger, intent


def captured(receipt, store=None):
    p = R.P1
    generation = p.generation
    confirmed = None
    if store is not None:
        view = store.protocol_view(R.STREAM)
        generation = max(p.generation for p in view.presentations if p.question_id == R.QID)
        if receipt.confirms is not None:
            confirmed = next((r for r in view.receipts if r.action.key == receipt.confirms.action.key), None)
    validation = R.C.validate_receipt(receipt, presentation=p, copies={"500"}, current_generation=generation,
                                     question_ids={R.QID, R.QID2}, confirmed=confirmed)
    return E.PulledIngress(R.TRANSPORT, receipt.update_id, "1" * 64, None), validation


def append(store, receipt):
    ingress, validation = captured(receipt, store)
    return store.append_receipt_with_ingress(ingress, receipt, validation)


def current_ack(store, revision=None):
    loaded = store.load(R.STREAM)
    supplement = store.supplement(R.STREAM, revision=revision or loaded.revision, original_brief=R.BRIEF)
    return dict(revision=supplement.revision, record_sha256=supplement.record_sha256,
                consumption_id=supplement.consumption_id, original_brief=R.BRIEF)


def test_combined_durable_copy_ingress_and_current_ack_across_restart(db):
    ledger, intent = intent_ready(db.store)
    first, won = ledger.start_attempt(intent.send_id, expected_attempts=0, resend=False)
    assert won and first.attempts == 1 and first.state == "uncertain"
    ledger.record_delivery(intent.send_id, "502")
    ledger.record_delivery(intent.send_id, "500")
    result = append(db.store, R.receipt())
    assert result.new and result.result.status == "applied" and result.result.revision == 2
    assert result.held == R.receipt()
    assert len(db.rows(D.ClarificationIngress)) == len(db.rows(M.ClarificationReceipt)) == 1
    db.restart()
    ledger = L.ClarificationDeliveryStore(db.store)
    assert {ledger.delivery(R.TRANSPORT, R.CHAT, mid).intent for mid in ("500", "502")} == {intent}
    assert {b.message_id for b in db.store.protocol_view(R.STREAM).copies} == {"500", "502"}
    before = db.dump()
    replay = append(db.store, R.receipt())
    assert (replay.result, replay.held, replay.new) == (result.result, result.held, False)
    assert db.dump() == before
    ack = current_ack(db.store)
    assert db.store.mark_current_consumed(R.STREAM, **ack) is True
    before = db.dump()
    assert db.store.mark_current_consumed(R.STREAM, **ack) is False
    assert db.dump() == before
    assert db.store.load(R.STREAM).pending_revision is None


def ingress_crash_receipt(operation):
    """Fixed inputs for the distinct applied, retained and diagnostic-only commits."""
    return {
        "ingress": R.receipt,
        "ingress-retained": R.typed,
        "ingress-refused": partial(R.fix, R.OWNER, [R.NO_EVENT]),
    }[operation]()


def _process(url, barrier, sink, operation, expected=0, resend=False, crash=None, split=False):
    """Real independent engine; returns only closed outcomes, never a traceback/payload."""
    engine = create_test_engine(url) if url.startswith("sqlite") else create_app_engine(url)
    store = S.ClarificationStore(engine)
    ledger = L.ClarificationDeliveryStore(store)
    original = store._cas
    passed = False

    def gated(*args, **kwargs):
        nonlocal passed
        if not passed and barrier is not None:
            passed = True
            barrier.wait(timeout=30)
        return original(*args, **kwargs)

    store._cas = gated
    if split:
        # Deliberately broken read/check/write variant: no stream lock. Both
        # processes see the same attempts before either may commit.
        store._cas = original
        L._locked = lambda owner, session, stream_id: owner._existing(session, stream_id)
        original_commit = store._commit

        def split_commit(session, explained):
            barrier.wait(timeout=30)
            original_commit(session, explained)

        store._commit = split_commit
    if crash is not None:
        original_commit = store._commit

        def cut(session, explained):
            if crash == "before":
                os._exit(17)
            original_commit(session, explained)
            os._exit(17)

        store._commit = cut
    try:
        if operation in ("attempt", "prompt"):
            send_id = R.P1.presentation_id if operation == "attempt" else "synthetic-prompt"
            record, won = ledger.start_attempt(send_id, expected_attempts=expected, resend=resend)
            provider = shared.SyntheticTelegram()
            if won:
                provider.send(int(R.CHAT), record.intent.text)
            sink.send(("attempt", won, record.attempts, record.state, len(provider.sent)))
        elif operation in ("answer-a", "answer-b"):
            receipt = R.receipt() if operation == "answer-a" else R.receipt(R.OTHER, "502", "Different answer")
            outcome = append(store, receipt)
            sink.send(("append", outcome.result.status, outcome.result.revision))
        elif operation in ("ingress", "ingress-retained", "ingress-refused"):
            append(store, ingress_crash_receipt(operation))
        elif operation == "delivery":
            ledger.record_delivery(R.P1.presentation_id, "500")
        elif operation == "intent":
            ledger.save_send(E.SendIntent(R.P1.presentation_id, R.P1, "Synthetic question"))
        elif operation == "ack":
            store.mark_current_consumed(R.STREAM, **current_ack(store))
    except Exception as error:  # safe projection to parent; parent assertion names the failure
        sink.send(("error", type(error).__name__, getattr(error, "guard", None)))
    finally:
        sink.close()
        engine.dispose()


def _run_children(url, operations, *, expected=0, resend=False, crash=None, split=False):
    """Own the spawn tracker in a short-lived driver, never the pytest worker."""
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(len(operations)) if len(operations) > 1 else None
    processes, receivers = [], []
    for operation in operations:
        receiver, sender = context.Pipe(duplex=False)
        process = context.Process(target=_process, args=(url, barrier, sender, operation, expected, resend, crash, split))
        process.start()
        sender.close()
        processes.append(process)
        receivers.append(receiver)
    results = []
    try:
        for process, receiver in zip(processes, receivers, strict=True):
            process.join(60)
            assert not process.is_alive(), "independent transaction did not finish"
            assert process.exitcode == (17 if crash else 0)
            if crash is None:
                assert receiver.poll(), "independent process did not return a closed result"
                results.append(receiver.recv())
        return results
    finally:
        for process, receiver in zip(processes, receivers, strict=True):
            if process.is_alive():
                process.kill()
                process.join()
            receiver.close()
            process.close()


def children(db, operations, *, expected=0, resend=False, crash=None, split=False):
    # Reuse the same resource observation as the original parking regressions.
    # The DB URL goes over stdin, not argv; neither it nor child stderr is exposed.
    from tests.test_runner.pi_parking.step_support import child_processes

    before = set(child_processes())
    result = subprocess.run(
        [sys.executable, "-m", "tests.test_clarifications.test_delivery_store"],
        input=json.dumps(dict(url=db.url, operations=operations, expected=expected,
                             resend=resend, crash=crash, split=split)),
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, "isolated transaction driver failed"
    assert not (set(child_processes()) - before), "transaction harness left a child process"
    return [tuple(row) for row in json.loads(result.stdout)]


@pytest.mark.parametrize("kind", ["question", "prompt", "resend"])
def test_cross_process_atomic_admission_has_exactly_one_winner(db, kind):
    ledger, intent = intent_ready(db.store, delivery=kind == "prompt")
    operation = "attempt"
    if kind == "prompt":
        typed = R.typed()
        append(db.store, typed)
        intent = E.SendIntent("synthetic-prompt", R.P1, E.PROMPT_TEXT, reply_to=typed.action.action_id,
                              payloads=E.PAYLOADS,
                              confirms=R.C.ConfirmedText(typed.action, typed.sender_id, typed.text_sha256))
        ledger.save_send(intent)
        operation = "prompt"
    if kind == "resend":
        assert ledger.start_attempt(intent.send_id, expected_attempts=0, resend=False)[1]
    expected = int(kind == "resend")
    results = children(db, [operation, operation], expected=expected, resend=kind == "resend")
    assert sorted(results) == [("attempt", False, expected + 1, "uncertain", 0),
                               ("attempt", True, expected + 1, "uncertain", 1)]
    assert ledger.send(intent.send_id, stream=R.STREAM).attempts == expected + 1


def test_transaction_harness_releases_its_resource_tracker(db):
    from tests.test_runner.pi_parking.step_support import child_processes

    before = set(child_processes())
    test_cross_process_atomic_admission_has_exactly_one_winner(db, "question")
    assert not (set(child_processes()) - before), "transaction harness leaked its resource tracker"


def test_reverse_completions_explicit_resend_and_all_history_lookup(db):
    ledger, intent = intent_ready(db.store)
    assert ledger.start_attempt(intent.send_id, expected_attempts=0, resend=False)[1]
    before = db.dump()
    assert not ledger.start_attempt(intent.send_id, expected_attempts=1, resend=False)[1]
    assert not ledger.start_attempt(intent.send_id, expected_attempts=0, resend=True)[1]
    assert db.dump() == before
    assert ledger.start_attempt(intent.send_id, expected_attempts=1, resend=True)[1]
    assert ledger.record_delivery(intent.send_id, "502").message_id == "502"
    assert ledger.record_delivery(intent.send_id, "501").message_id == "501"
    before = db.dump()
    assert ledger.record_delivery(intent.send_id, "502").message_id == "501"
    assert not ledger.start_attempt(intent.send_id, expected_attempts=2, resend=True)[1]
    assert db.dump() == before
    db.store.save_presentation(R.present(generation=2))
    db.restart()
    ledger = L.ClarificationDeliveryStore(db.store)
    assert all(ledger.delivery(R.TRANSPORT, R.CHAT, mid).intent == intent for mid in ("501", "502"))
    assert {b.message_id for b in db.store.protocol_view(R.STREAM).copies} == {"501", "502"}
    assert db.store.load(R.STREAM).copies == ()  # legacy current-only API unchanged
    assert ledger.delivery(R.C.TransportNamespace("telegram", "7002"), R.CHAT, "501") is None
    assert ledger.delivery(R.TRANSPORT, "-1002", "501") is None


@pytest.mark.parametrize("change", ["answered", "generation"])
@pytest.mark.parametrize("kind", ["question", "prompt", "resend"])
def test_every_admission_rechecks_current_state_without_a_write(db, change, kind):
    ledger, intent = intent_ready(db.store)
    db.store.record_copy(R.binding())  # legacy copying remains valid; not a verified delivery mapping
    if kind == "prompt":
        typed = R.typed()
        append(db.store, typed)
        intent = E.SendIntent("synthetic-prompt", R.P1, E.PROMPT_TEXT, reply_to=typed.action.action_id,
                              payloads=E.PAYLOADS,
                              confirms=R.C.ConfirmedText(typed.action, typed.sender_id, typed.text_sha256))
        ledger.save_send(intent)
    if kind == "resend":
        ledger.start_attempt(intent.send_id, expected_attempts=0, resend=False)
    if change == "answered":
        append(db.store, R.receipt())
    else:
        db.store.save_presentation(R.present(generation=2))
    before = db.dump()
    record, won = ledger.start_attempt(intent.send_id, expected_attempts=int(kind == "resend"), resend=kind == "resend")
    assert not won and record.attempts == int(kind == "resend")
    assert db.dump() == before


def test_in_flight_send_may_complete_but_late_receipt_is_retained(db):
    ledger, intent = intent_ready(db.store)
    assert ledger.start_attempt(intent.send_id, expected_attempts=0, resend=False)[1]
    db.store.save_presentation(R.present(generation=2))
    ledger.record_delivery(intent.send_id, "500")
    result = append(db.store, R.receipt())
    assert (result.result.status, result.result.code, result.new) == ("retained", R.C.RefusalCode.STALE_PRESENTATION, True)
    assert db.store.load(R.STREAM).revision == 1


def test_distinct_real_process_answers_survive_cas(db):
    intent_ready(db.store, delivery=True)
    results = children(db, ["answer-a", "answer-b"])
    assert sorted(results) == [("append", "applied", 2), ("append", "applied", 3)]
    record = db.restart().load(R.STREAM).record()
    assert len(record["events"]) == 2
    assert R.states(record)[R.QID]["state"] == "conflicting"
    assert len(db.rows(D.ClarificationIngress)) == 2


@pytest.mark.parametrize("state", ["plain", "no_disposition", "blank", "retired", "press"])
@pytest.mark.parametrize("targets", ["unknown", "other_then_unknown", "unknown_then_other"])
def test_unknown_targets_are_diagnostic_only_and_same_key_can_recover(db, state, targets):
    intent_ready(db.store, delivery=True)
    first = append(db.store, R.receipt()).result
    other = append(db.store, R.receipt(R.OTHER, "502")).result
    names = {"unknown": [R.NO_EVENT], "other_then_unknown": [other.event_id, R.NO_EVENT],
             "unknown_then_other": [R.NO_EVENT, other.event_id]}[targets]
    receipt = R.fix(R.OWNER, names)
    if state == "no_disposition":
        receipt = replace(receipt, disposition=None)
    elif state == "blank":
        receipt = replace(receipt, text="", text_sha256=R.sha(""))
    elif state == "retired":
        db.store.save_presentation(R.present(generation=2))
    elif state == "press":
        words = R.typed()
        append(db.store, words)
        receipt = R.press(words, intent="correct", supersedes=tuple(names), reason="Synthetic correction")
    before_keys = {r.action_key for r in db.rows(M.ClarificationReceipt)}
    outcome = append(db.store, receipt)
    assert (outcome.result.status, outcome.result.code, outcome.guard, outcome.held) == (
        "refused", R.C.RefusalCode.MISSING_RECORD, "correction.known", None)
    assert {r.action_key for r in db.rows(M.ClarificationReceipt)} == before_keys
    rows = db.rows(D.ClarificationIngress)
    assert any(row.receipt_sha256 == R.C.receipt_sha256(receipt) for row in rows)
    assert "receipt_json" not in D.ClarificationIngress.model_fields
    recovered = replace(receipt, supersedes=(first.event_id,))
    repaired = append(db.store, recovered)
    assert repaired.result.status in ("applied", "retained") and repaired.new
    assert db.store.protocol_view(R.STREAM).receipts[-1] is not None


def test_known_other_actor_and_provenance_refusal_keep_their_precedence(db):
    intent_ready(db.store, delivery=True)
    first = append(db.store, R.receipt(R.OTHER)).result
    known = append(db.store, R.fix(R.OWNER, [first.event_id]))
    assert known.result.code == R.C.RefusalCode.CROSS_ACTOR_CORRECTION and known.held is not None
    forged = R.fix(R.OWNER, [R.NO_EVENT], action_id="599", ingress="caller_label")
    result = append(db.store, forged)
    assert result.result.status == "refused" and result.guard != "correction.known"
    assert result.held is None


def test_capture_validation_never_replaces_latest_application_command(db):
    intent_ready(db.store, delivery=True)
    receipt = R.receipt()
    ingress, validation = captured(receipt)
    assert validation.status == "accepted"
    db.store.save_presentation(R.present(generation=2))
    outcome = db.store.append_receipt_with_ingress(ingress, receipt, validation)
    assert (outcome.result.status, outcome.result.code) == ("retained", R.C.RefusalCode.STALE_PRESENTATION)
    row = db.rows(D.ClarificationIngress)[0]
    assert row.capture_status == "accepted" and row.result_guard == outcome.guard
    assert db.store.load(R.STREAM).revision == 1


def test_confirmation_once_reopen_and_immutable_replay(db):
    intent_ready(db.store, delivery=True)
    words = R.typed()
    append(db.store, words)
    press = R.press(words)
    applied = append(db.store, press)
    second = append(db.store, R.press(words, action_id="cb-second"))
    assert second.result.code == R.C.RefusalCode.ALREADY_CONFIRMED
    opened = append(db.store, R.reopen(2, [applied.result.event_id]))
    assert opened.result.status == "applied" and opened.result.revision == 3
    newest = append(db.store, R.receipt(R.OTHER, "604", "Another answer"))
    stale = append(db.store, R.reopen(3, [], action_id="cb-stale"))
    assert stale.result.code == R.C.RefusalCode.STALE_REOPEN
    assert append(db.store, press).result == applied.result
    assert db.store.load(R.STREAM).revision == newest.result.revision
    changed = append(db.store, replace(press, disposition="unknown"))
    assert changed.result.code == R.C.RefusalCode.CHANGED_BODY and changed.held is None


def assert_nonapplied_ingress_commit(db, operation):
    """Inspect the committed child state BEFORE replay can create any missing row."""
    receipt = ingress_crash_receipt(operation)
    retained = operation == "ingress-retained"
    code = R.C.RefusalCode.NO_EXPLICIT_DISPOSITION if retained else R.C.RefusalCode.MISSING_RECORD
    guard = "disposition.explicit" if retained else "correction.known"
    expected = R.C.AppendResult(
        status="retained" if retained else "refused", stream_id=R.STREAM.stream_id,
        action_key=receipt.action.key, receipt_sha256=R.C.receipt_sha256(receipt),
        expected_revision=1, revision=1, code=code,
    )
    loaded = db.store.load(R.STREAM)
    assert loaded.revision == 1 and loaded.record()["events"] == []
    assert len(db.rows(M.ClarificationRevision)) == 1
    stream, = db.rows(M.ClarificationStream)
    assert (stream.revision, stream.receipt_count, stream.ingress_count) == (1, int(retained), 1)
    assert (stream.send_count, stream.delivery_count, stream.copy_count, stream.consumption_count) == (1, 1, 1, 0)
    ingress, = db.rows(D.ClarificationIngress)
    assert (ingress.stream_id, ingress.transport, ingress.bot_id, ingress.update_id,
            ingress.update_sha256, ingress.offset, ingress.action_key, ingress.receipt_sha256) == (
        R.STREAM.stream_id, R.TRANSPORT.transport, R.TRANSPORT.bot_id, receipt.update_id,
        "1" * 64, None, receipt.action.key, expected.receipt_sha256)
    assert json.loads(ingress.result_json) == asdict(expected)
    assert ingress.result_guard == guard
    assert (ingress.capture_status, ingress.capture_code, ingress.capture_guard) == (
        ("retained", code.value, guard) if retained else ("accepted", None, None))
    if retained:
        saved, = db.rows(M.ClarificationReceipt)
        assert S.ClarificationStore._result(saved) == expected
        assert (saved.guard, saved.receipt_json) == (guard, R.C.receipt_json(receipt))
        assert (ingress.refusal_id, ingress.diagnostic_code, ingress.diagnostic_guard) == (None, None, None)
        assert db.rows(M.ClarificationRefusal) == []
    else:
        assert db.rows(M.ClarificationReceipt) == []
        diagnostic, = db.rows(M.ClarificationRefusal)
        assert (diagnostic.stream_id, diagnostic.action_key, diagnostic.receipt_sha256,
                diagnostic.code, diagnostic.guard) == (
            R.STREAM.stream_id, receipt.action.key, expected.receipt_sha256, code.value, guard)
        assert (ingress.refusal_id, ingress.diagnostic_code, ingress.diagnostic_guard) == (
            diagnostic.id, code.value, guard)
    assert db.store.protocol_view(R.STREAM).receipts == ((receipt,) if retained else ())
    committed = db.dump()
    replay = append(db.store, receipt)
    assert (replay.result, replay.guard, replay.held, replay.new) == (
        expected, guard, receipt if retained else None, False)
    assert db.dump() == committed
    db.restart()
    assert db.dump() == committed and db.store.load(R.STREAM).revision == 1
    if not retained:
        # A refused action is still available to a genuine answer; preserve its
        # old diagnostic/ingress rather than overwrite them on recovery.
        genuine = R.receipt(action_id=receipt.action.action_id)
        assert R.C.receipt_sha256(genuine) != expected.receipt_sha256
        recovered = append(db.store, genuine)
        assert (recovered.result.status, recovered.result.revision, recovered.held, recovered.new) == (
            "applied", 2, genuine, True)
        saved, = db.rows(M.ClarificationReceipt)
        assert (saved.action_key, saved.receipt_sha256) == (receipt.action.key, R.C.receipt_sha256(genuine))
        assert db.dump()["clarification_refusals"] == committed["clarification_refusals"]
        assert len(db.rows(D.ClarificationIngress)) == 2
        assert next(row for row in db.rows(D.ClarificationIngress)
                    if row.ingress_id == ingress.ingress_id).model_dump() == ingress.model_dump()
        db.restart()
        assert db.store.load(R.STREAM).revision == 2
        assert db.store.protocol_view(R.STREAM).receipts == (genuine,)


@pytest.mark.parametrize("operation", ["intent", "attempt", "delivery", "ingress", "ingress-retained", "ingress-refused", "ack"])
@pytest.mark.parametrize("when", ["before", "after"])
def test_process_crash_at_real_commit_has_no_partial_transaction(db, operation, when):
    if operation == "intent":
        db.store.merge_candidate(R.caller())
        db.store.save_presentation(R.P1)
    else:
        intent_ready(db.store, delivery=operation in ("ingress", "ingress-retained", "ingress-refused", "ack"))
    before = db.dump()
    children(db, [operation], crash=when)
    db.restart()
    if when == "before":
        assert db.dump() == before
        if operation in ("ingress-retained", "ingress-refused"):
            retry = append(db.store, ingress_crash_receipt(operation))
            assert retry.new is (operation == "ingress-retained")
            assert_nonapplied_ingress_commit(db, operation)
    else:
        ledger = L.ClarificationDeliveryStore(db.store)
        if operation == "attempt":
            record, won = ledger.start_attempt(R.P1.presentation_id, expected_attempts=0, resend=False)
            assert not won and record.state == "uncertain" and record.attempts == 1
        elif operation == "delivery":
            assert ledger.delivery(R.TRANSPORT, R.CHAT, "500") is not None
            saved = db.dump()
            ledger.record_delivery(R.P1.presentation_id, "500")
            assert db.dump() == saved
        elif operation == "ingress":
            assert db.store.load(R.STREAM).revision == 2
            assert len(db.rows(D.ClarificationIngress)) == len(db.rows(M.ClarificationReceipt)) == 1
            assert append(db.store, R.receipt()).new is False
        elif operation in ("ingress-retained", "ingress-refused"):
            assert_nonapplied_ingress_commit(db, operation)
        elif operation == "intent":
            assert ledger.send(R.P1.presentation_id, stream=R.STREAM).state == "pending"
        else:
            assert db.store.mark_current_consumed(R.STREAM, **current_ack(db.store)) is False


def test_current_consumption_kept_replay_first_and_new_stale_refuses(db):
    intent_ready(db.store, delivery=True)
    first = current_ack(db.store)
    assert db.store.mark_current_consumed(R.STREAM, **first)
    append(db.store, R.receipt())
    second = current_ack(db.store)
    append(db.store, R.receipt(R.OTHER, "503"))
    before = db.dump()
    assert db.store.mark_current_consumed(R.STREAM, **first) is False
    with pytest.raises(R.C.ContractRefusal) as stale:
        db.store.mark_current_consumed(R.STREAM, **second)
    assert stale.value.code == R.C.RefusalCode.REVISION_CONFLICT
    assert db.dump() == before
    # Historical API retains its pre-extension behavior.
    assert db.store.mark_consumed(R.STREAM, revision=2, original_brief=R.BRIEF)
    with pytest.raises(R.C.ContractRefusal) as wrong:
        db.store.mark_current_consumed(R.STREAM, **{**first, "consumption_id": "c-wrong"})
    assert wrong.value.guard == "consume.identity"


DAMAGE = [
    (D.ClarificationSend, {"intent_sha256": "0" * 64}, "send.digest"),
    (D.ClarificationSend, {"attempt_count": 44}, "send.state"),
    (D.ClarificationSend, {"message_id": "909"}, "send.state"),
    (D.ClarificationDelivery, {"send_id": "foreign"}, "delivery.digest"),
    (D.ClarificationDelivery, {"message_id": "909"}, "delivery.digest"),
    (D.ClarificationIngress, {"capture_status": "refused"}, "ingress.digest"),
    (D.ClarificationIngress, {"result_guard": "other"}, "ingress.digest"),
    (M.ClarificationCopy, {"message_id": "909"}, "copy.digest"),
    (M.ClarificationReceipt, {"event_id": R.NO_EVENT}, "receipt.result"),
]


@pytest.mark.parametrize("model,values,guard", DAMAGE, ids=[d[2] + str(i) for i, d in enumerate(DAMAGE)])
@pytest.mark.parametrize("path", ["load", "view", "send", "delivery", "admit", "append", "consume"])
def test_every_new_read_path_uses_common_integrity_loader(db, model, values, guard, path):
    ledger, intent = intent_ready(db.store, delivery=True)
    append(db.store, R.receipt())
    ack = current_ack(db.store)
    db.run(update(model).values(**values))
    operations = {
        "load": lambda: db.store.load(R.STREAM), "view": lambda: db.store.protocol_view(R.STREAM),
        "send": lambda: ledger.send(intent.send_id, stream=R.STREAM),
        "delivery": lambda: ledger.delivery(R.TRANSPORT, R.CHAT, "500", stream=R.STREAM),
        "admit": lambda: ledger.start_attempt(intent.send_id, expected_attempts=0, resend=True),
        "append": lambda: append(db.store, R.receipt()),
        "consume": lambda: db.store.mark_current_consumed(R.STREAM, **ack),
    }
    with pytest.raises(S.ClarificationIntegrityError) as damaged:
        operations[path]()
    assert damaged.value.guard == guard


@pytest.mark.parametrize("model", [D.ClarificationSend, D.ClarificationDelivery, D.ClarificationIngress])
def test_partial_loss_never_resets_send_state(db, model):
    intent_ready(db.store, delivery=True)
    append(db.store, R.receipt())
    db.run(delete(model))
    with pytest.raises(S.ClarificationIntegrityError) as damaged:
        db.store.load(R.STREAM)
    assert damaged.value.guard == "delivery.count"


def test_recomputed_lookup_digest_cannot_hide_wrong_copy_or_representative(db):
    ledger, _ = intent_ready(db.store, delivery=True)
    with Session(db.engine) as session:
        row = session.get(D.ClarificationDelivery, ("telegram", R.BOT, R.CHAT, "500"))
        row.message_id = "909"
        row.delivery_sha256 = L._delivery_digest(row)
        session.add(row)
        session.commit()
    with pytest.raises(S.ClarificationIntegrityError) as damaged:
        ledger.delivery(R.TRANSPORT, R.CHAT, "909", stream=R.STREAM)
    assert damaged.value.guard == "delivery.copy"


def test_immutable_intents_and_copy_collisions_refuse_without_a_write(db):
    ledger, intent = intent_ready(db.store, delivery=True)
    before = db.dump()
    with pytest.raises(R.C.ContractRefusal) as changed:
        ledger.save_send(replace(intent, text="Other question text"))
    assert changed.value.guard == "send.changed"
    assert db.dump() == before
    db.store.save_presentation(R.P2)
    another = E.SendIntent(R.P2.presentation_id, R.P2, "Another question")
    ledger.save_send(another)
    before = db.dump()
    with pytest.raises(R.C.ContractRefusal) as occupied:
        ledger.record_delivery(another.send_id, "500")
    assert occupied.value.guard == "delivery.occupied"
    assert db.dump() == before


def test_cross_process_split_read_check_increment_bite(db):
    intent_ready(db.store)
    broken = children(db, ["attempt", "attempt"], split=True)
    # This named mutation must actually produce two admitted effects, not fail
    # from a broken fixture, a timeout or an unrelated database exception.
    assert broken == [("attempt", True, 1, "uncertain", 1)] * 2
    with pytest.raises(AssertionError, match="one admitted effect"):
        assert sum(result[-1] for result in broken) == 1, "one admitted effect"


ADMISSION_BITES = {
    "delivery": ("not delivered", "True"),
    "attempts": ("record.attempts == expected_attempts", "True"),
    "explicit": ("(record.attempts == 0 or resend)", "True"),
    "generation": ("p.generation == loaded.generation(p.question_id)", "True"),
    "answered": ("not answered", "True"),
}


def replace_method(monkeypatch, cls, method, old, new):
    """Remove one named condition from the actual method; never edit source on disk."""
    function = getattr(cls, method)
    source = textwrap.dedent(inspect.getsource(function))
    assert source.count(old) == 1
    names = dict(vars(inspect.getmodule(function)))
    exec(compile(source.replace(old, new), "<named-method-bite>", "exec"), names)
    monkeypatch.setattr(cls, method, names[method])


@pytest.mark.parametrize("guard", ADMISSION_BITES)
def test_each_admission_predicate_bites_its_forbidden_attempt(db, monkeypatch, guard):
    ledger, intent = intent_ready(db.store, delivery=guard == "delivery")
    if guard in ("attempts", "explicit"):
        ledger.start_attempt(intent.send_id, expected_attempts=0, resend=False)
    elif guard == "generation":
        db.store.save_presentation(R.present(generation=2))
    elif guard == "answered":
        db.store.record_copy(R.binding())
        append(db.store, R.receipt())
    expected, resend = (0, True) if guard == "attempts" else (int(guard == "explicit"), False)
    before = db.dump()
    assert not ledger.start_attempt(intent.send_id, expected_attempts=expected, resend=resend)[1]
    assert db.dump() == before
    old, new = ADMISSION_BITES[guard]
    replace_method(monkeypatch, L.ClarificationDeliveryStore, "start_attempt", old, new)
    assert ledger.start_attempt(intent.send_id, expected_attempts=expected, resend=resend)[1] is True


def test_current_ack_revision_fence_bites_after_controlled_race(db, monkeypatch):
    intent_ready(db.store, delivery=True)
    ack = current_ack(db.store)
    original, first = db.store._cas, True

    def race(*args, **kwargs):
        nonlocal first
        if first:
            first = False
            append(db.other(), R.receipt())
        return original(*args, **kwargs)

    monkeypatch.setattr(db.store, "_cas", race)
    with pytest.raises(R.C.ContractRefusal) as stale:
        db.store.mark_current_consumed(R.STREAM, **ack)
    assert stale.value.code is R.C.RefusalCode.REVISION_CONFLICT
    assert db.rows(M.ClarificationConsumption) == []
    monkeypatch.setattr(L, "check_expected_revision", lambda expected, committed: None)
    assert db.store.mark_current_consumed(R.STREAM, **ack) is True
    assert db.rows(M.ClarificationConsumption)[0].revision == 1  # exact forbidden stale write


@pytest.mark.parametrize("remove_fence", [False, True])
def test_non_revision_read_fence_bites_stale_attempt_snapshot(db, monkeypatch, remove_fence):
    ledger, intent = intent_ready(db.store)
    original, first = db.store._history, True

    def race(session, stream_id):
        nonlocal first
        history = original(session, stream_id)
        if first:
            first = False
            other = L.ClarificationDeliveryStore(db.other())
            assert other.start_attempt(intent.send_id, expected_attempts=0, resend=False)[1]
        return history

    monkeypatch.setattr(db.store, "_history", race)
    if remove_fence:
        monkeypatch.setattr(L, "check_read_version", lambda *args: None)
    record = ledger.send(intent.send_id, stream=R.STREAM)
    assert record.attempts == (0 if remove_fence else 1)


def derived(value):
    subclass = type("SyntheticSubtype", (type(value),), {})
    return subclass(**{field.name: getattr(value, field.name) for field in fields(value) if field.init})


INPUT_GUARDS = ["send.type", "send.presentation_type", "send.text", "send.payloads", "send.confirms_type",
                "send.prompt", "send.admission_input", "ingress.type", "ingress.numbers", "ingress.update_digest",
                "ingress.receipt_type", "ingress.receipt", "ingress.refusal_type", "ingress.refusal_receipt",
                "ingress.refusal_digest", "consume.identity"]


@pytest.mark.parametrize("guard", INPUT_GUARDS)
def test_each_new_input_guard_bites_its_specific_contract(db, monkeypatch, guard):
    ledger, intent = intent_ready(db.store, delivery=True)
    receipt = R.receipt()
    ingress, validation = captured(receipt)
    prompt = replace(intent, send_id="synthetic-prompt", reply_to=receipt.action.action_id, payloads=E.PAYLOADS,
                     confirms=R.C.ConfirmedText(receipt.action, receipt.sender_id, receipt.text_sha256))
    bad_intents = {
        "send.type": derived(intent), "send.presentation_type": replace(intent, presentation=derived(R.P1)),
        "send.text": replace(intent, text=" "),
        "send.payloads": replace(prompt, payloads=(("clar:other", "not-a-disposition"),)),
        "send.confirms_type": replace(prompt, confirms=derived(prompt.confirms)),
        "send.prompt": replace(intent, reply_to="123"),
    }
    if guard in bad_intents:
        invoke = partial(L._intent_text, bad_intents[guard])
    elif guard == "send.admission_input":
        invoke = partial(ledger.start_attempt, intent.send_id, expected_attempts=True, resend=False)
    elif guard in ("ingress.type", "ingress.numbers", "ingress.update_digest"):
        bad = {"ingress.type": derived(ingress), "ingress.numbers": replace(ingress, update_id=-1),
               "ingress.update_digest": replace(ingress, update_sha256="not-a-digest")}[guard]
        invoke = partial(L._ingress_fields, bad)
    elif guard == "ingress.receipt_type":
        invoke = partial(L._capture, ingress, receipt, derived(validation))
    elif guard == "ingress.receipt":
        invoke = partial(L._capture, replace(ingress, update_id=111), receipt, validation)
    elif guard.startswith("ingress.refusal"):
        refusal = E.Refusal(ingress, R.C.RefusalCode.UNVERIFIED_INGRESS, "synthetic")
        if guard == "ingress.refusal_type":
            refusal = derived(refusal)
        elif guard == "ingress.refusal_receipt":
            refusal = replace(refusal, receipt=receipt, receipt_sha256="0" * 64)
        else:
            refusal = replace(refusal, receipt_sha256="0" * 64)
        invoke = partial(L.keep_refusal, db.store, R.STREAM, refusal)
    else:
        ack = {**current_ack(db.store), "consumption_id": "c-wrong"}
        invoke = partial(db.store.mark_current_consumed, R.STREAM, **ack)
    before = db.dump()
    with pytest.raises(R.C.ContractRefusal) as refusal:
        invoke()
    assert refusal.value.guard == guard and db.dump() == before
    require = L._require
    monkeypatch.setattr(L, "_require", lambda ok, code, name, where: None if name == guard
                        else require(ok, code, name, where))
    invoke()  # the exact input formerly refused is now allowed; no unrelated exception counts


INTEGRITY_GUARDS = ["delivery.count", "send.binding", "send.digest", "send.state", "delivery.digest",
                    "delivery.copy", "delivery.representative", "ingress.digest", "ingress.shape", "ingress.result_shape",
                    "ingress.result", "ingress.refused_result", "ingress.refusal"]


@pytest.mark.parametrize("guard", INTEGRITY_GUARDS)
def test_each_delivery_integrity_guard_bites_a_specific_corruption(db, monkeypatch, guard):
    ledger, intent = intent_ready(db.store, delivery=True)
    append(db.store, R.receipt())
    if guard in ("ingress.refused_result", "ingress.refusal"):
        append(db.store, R.fix(R.OWNER, [R.NO_EVENT]))
    if guard == "delivery.count":
        db.run(delete(D.ClarificationIngress))
    else:
        with Session(db.engine) as session:
            send = session.get(D.ClarificationSend, intent.send_id)
            delivery = session.get(D.ClarificationDelivery, ("telegram", R.BOT, R.CHAT, "500"))
            ingresses = list(session.exec(S.select(D.ClarificationIngress)).all())
            ingress = next((r for r in ingresses if r.refusal_id is not None), ingresses[0])
            if guard == "send.binding":
                value = S.json.loads(send.intent_json)
                value["send_id"] = "different-send"
                send.intent_json = S._canonical(value)
                send.intent_sha256 = R.sha(send.intent_json)
                send.state_sha256 = L._send_state(send)
            elif guard == "send.digest":
                send.intent_sha256 = "0" * 64
                send.state_sha256 = L._send_state(send)
            elif guard == "send.state":
                send.attempt_count = 44
            elif guard == "delivery.digest":
                delivery.delivery_sha256 = "0" * 64
            elif guard == "delivery.copy":
                delivery.message_id = "909"
                delivery.delivery_sha256 = L._delivery_digest(delivery)
                send.message_id = "909"
                send.state_sha256 = L._send_state(send)
            elif guard == "delivery.representative":
                send.message_id = "909"
                send.state_sha256 = L._send_state(send)
            elif guard == "ingress.digest":
                ingress.update_sha256 = "0" * 64
            elif guard == "ingress.shape":
                ingress.result_json = None
                ingress.ingress_id = L._ingress_digest(ingress)
            elif guard == "ingress.result_shape":
                ingress.action_key = R.receipt(R.OTHER, "555").action.key
                ingress.ingress_id = L._ingress_digest(ingress)
            elif guard in ("ingress.result", "ingress.refused_result"):
                value = S.json.loads(ingress.result_json)
                value["event_id" if guard == "ingress.result" else "code"] = (
                    R.NO_EVENT if guard == "ingress.result" else R.C.RefusalCode.HASH_MISMATCH.value)
                ingress.result_json = S._canonical(value)
                ingress.ingress_id = L._ingress_digest(ingress)
            else:
                diagnostic = session.get(M.ClarificationRefusal, ingress.refusal_id)
                diagnostic.guard = "different-diagnostic"
                session.add(diagnostic)
            session.add_all([send, delivery, ingress])
            session.commit()
    with pytest.raises(S.ClarificationIntegrityError) as damaged:
        ledger.send(intent.send_id, stream=R.STREAM)
    assert damaged.value.guard == guard
    intact = L._intact
    monkeypatch.setattr(L, "_intact", lambda ok, stream, name, detail: None if name == guard
                        else intact(ok, stream, name, detail))
    assert ledger.send(intent.send_id, stream=R.STREAM).intent is not None  # named corrupt read now succeeds


@pytest.mark.parametrize("field,guard", [("stream", "ingress.result_shape"), ("transport", "ingress.result"),
                                         ("update", "ingress.result"), ("diagnostic_stream", "ingress.refusal"),
                                         ("extra_diagnostic", "ingress.result")])
def test_ingress_result_namespace_and_diagnostic_bindings_bite(db, monkeypatch, field, guard):
    ledger, intent = intent_ready(db.store, delivery=True)
    refused = field in ("stream", "diagnostic_stream")
    append(db.store, R.fix(R.OWNER, [R.NO_EVENT]) if refused else R.receipt())
    foreign = R.C.StreamKey("synthetic:other", R.BRIEF_SHA).stream_id
    with Session(db.engine) as session:
        ingress = session.exec(S.select(D.ClarificationIngress)).one()
        if field == "stream":
            value = S.json.loads(ingress.result_json)
            value["stream_id"] = foreign
            ingress.result_json = S._canonical(value)
        elif field == "transport":
            ingress.bot_id = "7002"
        elif field == "update":
            ingress.update_id += 1
        elif field == "diagnostic_stream":
            diagnostic = session.get(M.ClarificationRefusal, ingress.refusal_id)
            diagnostic.stream_id = foreign
            session.add(diagnostic)
        else:
            ingress.diagnostic_code = "malformed"
            ingress.diagnostic_guard = "synthetic.extra"
        ingress.ingress_id = L._ingress_digest(ingress)
        session.add(ingress)
        session.commit()
    with pytest.raises(S.ClarificationIntegrityError) as damaged:
        ledger.send(intent.send_id, stream=R.STREAM)
    assert damaged.value.guard == guard
    intact = L._intact
    monkeypatch.setattr(L, "_intact", lambda ok, stream, name, detail: None if name == guard
                        else intact(ok, stream, name, detail))
    assert ledger.send(intent.send_id, stream=R.STREAM).intent == intent


def test_retention_code_is_not_a_diagnostic_only_refusal(db, monkeypatch):
    intent_ready(db.store, delivery=True)
    ingress, _ = captured(R.receipt())
    refusal = E.Refusal(ingress, R.C.RefusalCode.BLANK_TEXT, "synthetic")
    before = db.dump()
    with pytest.raises(R.C.ContractRefusal) as wrong:
        L.keep_refusal(db.store, R.STREAM, refusal)
    assert wrong.value.guard == "ingress.refusal_type" and db.dump() == before
    require = L._require
    monkeypatch.setattr(L, "_require", lambda ok, code, name, where: None if name == "ingress.refusal_type"
                        else require(ok, code, name, where))
    L.keep_refusal(db.store, R.STREAM, refusal)
    assert db.rows(D.ClarificationIngress)[0].capture_code == R.C.RefusalCode.BLANK_TEXT


@pytest.mark.parametrize("guard", ["send.binding", "send.changed", "delivery.occupied", "send.missing"])
def test_ledger_write_contract_guards_have_specific_bites(db, monkeypatch, guard):
    ledger, intent = intent_ready(db.store, delivery=True)
    incoming = replace(intent, text="Changed intent")
    if guard == "send.binding":
        incoming = replace(intent, send_id="unregistered-presentation", presentation=R.present(generation=2))
        invoke = partial(ledger.save_send, incoming)
    elif guard == "send.changed":
        invoke = partial(ledger.save_send, incoming)
    elif guard == "delivery.occupied":
        db.store.save_presentation(R.P2)
        incoming = E.SendIntent(R.P2.presentation_id, R.P2, "Another question")
        ledger.save_send(incoming)
        invoke = partial(ledger.record_delivery, incoming.send_id, "500")
    else:
        invoke = partial(ledger.send, "synthetic-missing", stream=R.STREAM)
    before = db.dump()
    with pytest.raises(R.C.ContractRefusal) as refused:
        invoke()
    assert refused.value.guard == guard and db.dump() == before
    require = L._require
    monkeypatch.setattr(L, "_require", lambda ok, code, name, where: None if name == guard
                        else require(ok, code, name, where))
    if guard == "send.missing":
        # A diagnostic guard: its removal leaks the exact production KeyError,
        # not a security bypass or a fixture/setup error.
        with pytest.raises(KeyError) as missing:
            invoke()
        assert missing.value.args == ("synthetic-missing",)
    else:
        returned = invoke()  # a previously refused request is incorrectly accepted
        if guard == "send.binding":
            assert returned.intent == incoming
            assert any(row.presentation_id == incoming.presentation.presentation_id for row in db.rows(D.ClarificationSend))
        elif guard == "send.changed":
            assert returned.intent != incoming and db.dump() == before
        else:
            assert returned.intent == incoming and returned.message_id is None and db.dump() == before


def test_capture_linkage_mismatch_and_unexpected_commit_error_propagate(db, monkeypatch):
    intent_ready(db.store, delivery=True)
    receipt = R.receipt()
    ingress, validation = captured(receipt)
    before = db.dump()
    with pytest.raises(R.C.ContractRefusal) as bad:
        db.store.append_receipt_with_ingress(replace(ingress, update_id=111), receipt, validation)
    assert bad.value.guard == "ingress.receipt" and db.dump() == before

    def fail(*args):
        raise OSError("synthetic storage outage")

    monkeypatch.setattr(db.store, "_commit", fail)
    with pytest.raises(OSError):
        db.store.append_receipt_with_ingress(ingress, receipt, validation)
    assert db.dump() == before


if __name__ == "__main__":
    print(json.dumps(_run_children(**json.load(sys.stdin))))
