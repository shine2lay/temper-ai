"""Finite known-answer PHOST stages, synthetic custody and throwaway PG only.

FixtureControls is NOT an operational adapter or authority. No provider, model,
Temper instance, key, collector store, protected header/journal or real restore.
"""

from __future__ import annotations

import importlib.util
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest
from sqlalchemy import delete, event, select, text

from temper_ai.database import get_database, get_session
from temper_ai.observability import recorder
from temper_ai.observability import usage_feed_cursor as codec
from temper_ai.observability import usage_feed_epoch_journal as journal
from temper_ai.observability import usage_feed_epoch_transition as host
from temper_ai.observability import usage_feed_epochs as core
from temper_ai.observability import usage_rows as writer
from temper_ai.observability.usage_rows import UsageCallRow, ensure_instance

STAMP = "2026-01-01T00:00:00.000000Z"
SOURCE = "00000000-0000-4000-8000-000000000001"
READER = "00000000-0000-4000-8000-000000000002"
IDENTITY = core.PrivateIdentity("123456789", 1234, 1)
OTHER_IDENTITY = core.PrivateIdentity("234567890", 4321, 2)


def uid(n):
    return f"00000000-0000-4000-8000-{n:012x}"


class FixtureControls:
    """Known-answer model of the MISSING Ops APIs, never a production import."""

    def __init__(self):
        self.approved = set()
        self.off = self.settled = self.native_available = self.authority_available = True
        self.generation = 0
        self.current_header = None
        self.journal_path = None
        self.retained = set()
        self.checked = []

    def admit(self, a, handoff):
        self.approved.add(journal.digest(a.payload()))
        self.generation = handoff.header.generation
        self.current_header = handoff.header_digest
        if type(handoff.header) is host.QuiescentHeader:
            self.retained = set(handoff.header.q.evidence_refs)

    def verify(self, a, handoff, journal_path):
        self.checked.append(a.action)
        assert journal_path == self.journal_path
        assert self.authority_available and journal.digest(a.payload()) in self.approved
        assert self.off and self.settled and self.native_available
        assert handoff.header.generation == self.generation and handoff.header_digest == self.current_header
        if type(handoff.header) is host.QuiescentHeader:
            assert set(handoff.header.q.evidence_refs) <= self.retained
            assert handoff.header.q.witness == handoff.header.w


class FixtureDatabase:
    """Protocol-stage oracle. Real SQL/fence/target tests follow independently."""

    def __init__(self):
        self.source, self.identity, self.phases, self.rows = SOURCE, IDENTITY, [], []
        self.fault = None
        self.calls = []
        self.sequence_highwater = 999999  # never consulted by the protocol

    def snapshot(self):
        self.calls.append("snapshot")
        return host.DatabaseView(self.source, self.identity, tuple(self.phases))

    def interrupt(self, where):
        if self.fault == where:
            self.fault = None
            raise host.HostProtocolError("epoch-fixture-commit-unknown")

    def prepare(self, intent):
        self.calls.append("prepare")
        self.interrupt("prepare-before")
        view = self.snapshot()
        host._check(view.source_instance == intent.authorization.source_instance and view.identity == intent.new_identity
                    and view.maximum == intent.db_max and view.checksum == intent.db_digest)
        operation = core.EpochOperation(intent.epoch, intent.authorization.transition_id, self.source,
                                       self.identity, intent.authorization.reason, self.rows[-1] if self.rows else None)
        self.phases.append(host.DatabasePhase(operation, "PREPARED", STAMP))
        self.interrupt("prepare-after")

    def ready(self, intent, receipt):
        self.calls.append("ready")
        self.interrupt("ready-before")
        view = self.validate_operation(intent)
        prepared, ready = view.operation_phases(intent)
        host._check(prepared == receipt.prepared and view.maximum == intent.epoch)
        if ready is None:
            self.phases.append(host.DatabasePhase(prepared.operation, "READY", STAMP))
        self.interrupt("ready-after")

    def validate_operation(self, intent):
        view = self.snapshot()
        host._check(view.source_instance == intent.authorization.source_instance and view.identity == intent.new_identity)
        prepared, _ = view.operation_phases(intent)
        if prepared:
            host._check(view.maximum == intent.epoch)
            host._check(prepared.operation.target is None or prepared.operation.target in self.rows)
        return view


def handoff_for(header):
    return host.ClosedHandoff(header, uid(900), uid(901), journal.digest(header.payload()))


def virgin(source=SOURCE):
    return handoff_for(host.VirginAdmission(1, READER, host.PRINCIPAL, source, "VIRGIN-ADMITTED", 1,
                                          uid(800), "none-attested"))


def history_bytes(store):
    return journal.validate_bytes(store.path.read_bytes(), store.source_instance, host.validate_history)


def current_head(store):
    return history_bytes(store)[-1].head if store.path.exists() and store.path.stat().st_size else journal.EMPTY_HEAD


def authority(protocol, handoff, n, action="begin", reason=None):
    a = host.HostAuthorization(uid(n), handoff.header.source_instance, READER, action,
        reason or ("activation" if type(handoff.header) is host.VirginAdmission else "restore"),
        journal.digest(["fixture-plan", n, action]), journal.digest(["fixture-consent", n, action]),
        current_head(protocol.journal))
    protocol.controls.admit(a, handoff)
    if protocol.controls.journal_path is None:
        protocol.controls.journal_path = protocol.journal.path
    return a


def initialized_handoff(protocol, outcome, anchor=None):
    item = host.histories(history_bytes(protocol.journal))[outcome.transition_id]
    w = host.NativeWitness(protocol.journal.source_instance, anchor.event_id, anchor.revision) if anchor else None
    # This opaque G is supplied by the fixture's native receipt, never decoded
    # or resolved by any host operator. W comes from the public DTO identity.
    g = codec.encode_row_cursor(codec.RowCursor(protocol.journal.source_instance, outcome.epoch, anchor)) if anchor else None
    refs = (journal.digest(w.payload()),) if w else ()
    q = host.NativeCheckpoint(uid(2000 + outcome.epoch), refs, w)
    header = host.QuiescentHeader(1, READER, host.PRINCIPAL, protocol.journal.source_instance, "QUIESCENT",
        outcome.epoch, outcome.transition_id, outcome.epoch + 1, "committed" if w else "no-progress", g, w, q,
        item.receipt.target, item.receipt.target is None, (outcome.head.checksum,))
    return handoff_for(header)


@pytest.fixture
def protocol(tmp_path):
    tmp_path.chmod(0o700)
    store = journal.HostJournal(tmp_path / "synthetic-history", SOURCE, host.validate_history)
    return host.HostEpochProtocol(store, FixtureDatabase(), FixtureControls())


def seed_seven(protocol, anchor=None):
    handoff = virgin(protocol.journal.source_instance)
    snapshots = {}
    for epoch in range(1, 8):
        a = authority(protocol, handoff, 100 + epoch)
        outcome = protocol.start(a, handoff)
        assert outcome.epoch == epoch and outcome.status == "COMPLETE"
        if isinstance(protocol.database, FixtureDatabase):
            snapshots[epoch] = tuple(protocol.database.phases)
        handoff = initialized_handoff(protocol, outcome, anchor)
    return handoff, snapshots


def assert_closed(outcome):
    assert outcome.server_admission == "OFF" and outcome.collector_mode == "QUIESCENT"
    assert outcome.release == "NOT-AUTHORIZED"


def test_00_combined_both_histories_h7_d6_to8_distinct_native_witness_target_and_closed_restart(protocol, monkeypatch):
    first, last = codec.FinalRowAnchor(2, "native-old-public", 1), codec.FinalRowAnchor(8, "new-fixed-target", 2)
    protocol.database.rows = [first, last]
    handoff, snapshots = seed_seven(protocol, first)
    protocol.database.phases = list(snapshots[6])  # fixed synthetic retained-older history
    old = handoff.header
    # Any old-G decoder/resolver call would be a failure, including a real row.
    monkeypatch.setattr(codec, "decode_row_cursor", Mock(side_effect=AssertionError("no old-G decoder")))
    monkeypatch.setattr(core, "validate_row_cursor", Mock(side_effect=AssertionError("no old-G resolver")))
    a = authority(protocol, handoff, 108)
    outcome = protocol.start(a, handoff)
    assert outcome.epoch == 8
    item = host.histories(history_bytes(protocol.journal))[a.transition_id]
    assert item.intent.host_max == 7 and item.intent.db_max == 6
    assert item.intent.handoff.header == old and old.w.event_id == first.event_id
    assert item.receipt.prepared.operation.target == last
    assert item.receipt.target != old.g and old.q.witness != host.NativeWitness(SOURCE, last.event_id, last.revision)
    assert item.receipt.prepared.operation.target.seq != protocol.database.sequence_highwater
    assert_closed(outcome)
    assert_closed(protocol.reconcile(authority(protocol, handoff, 108, "reconcile"), handoff))
    assert [r.kind for r in history_bytes(protocol.journal)][-3:] == ["INTENT", "PREPARED-RECEIPT", "COMPLETE"]
    assert outcome.head.sequence == 25
    # No consumer/key/route installer, re-add or release collaborator exists.
    assert set(vars(protocol)) == {"journal", "database", "controls"}


@pytest.mark.parametrize("ready_stamp", [STAMP, "2026-01-01T00:00:01.000000Z"])
def test_complete_replay_requires_exact_saved_ready_timestamp_without_any_data_write(protocol, monkeypatch, ready_stamp):
    handoff = virgin()
    outcome = protocol.start(authority(protocol, handoff, 101), handoff)
    item = host.histories(history_bytes(protocol.journal))[outcome.transition_id]
    saved = host.DatabasePhase.parse(item.terminal.data["ready"])
    original = protocol.database.phases[-1]
    assert original == saved and original.phase == "READY"
    protocol.database.phases[-1] = replace(original, created_at=ready_stamp)
    actual = protocol.database.phases[-1]
    assert actual.operation == saved.operation and actual.phase == saved.phase
    # Only the canonical READY timestamp differs; all other fields are exact.
    assert {k: v for k, v in actual.payload().items() if k != "created_at"} == {
        k: v for k, v in saved.payload().items() if k != "created_at"}
    before_bytes, before_phases = protocol.journal.path.read_bytes(), tuple(protocol.database.phases)
    recovery = authority(protocol, handoff, 101, "reconcile")
    append = Mock(side_effect=AssertionError("COMPLETE replay cannot append"))
    prepare = Mock(side_effect=AssertionError("COMPLETE replay cannot PREPARE"))
    ready = Mock(side_effect=AssertionError("COMPLETE replay cannot write READY"))
    monkeypatch.setattr(journal.JournalSession, "append", append)
    monkeypatch.setattr(protocol.database, "prepare", prepare)
    monkeypatch.setattr(protocol.database, "ready", ready)
    if ready_stamp == STAMP:
        replay = protocol.reconcile(recovery, handoff)
        assert replay.status == "COMPLETE" and replay.head == outcome.head
        assert_closed(replay)
    else:
        def must_refuse():
            with pytest.raises(host.HostProtocolError, match="^epoch-history-diverged$"):
                protocol.reconcile(recovery, handoff)

        must_refuse()
        # The existing PREPARED equality still has identical input; bypassing
        # phase equality changes only the newly meaningful READY comparison.
        with monkeypatch.context() as mutation:
            mutation.setattr(host.DatabasePhase, "__eq__", lambda *_: True)
            with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
                must_refuse()
    append.assert_not_called()
    prepare.assert_not_called()
    ready.assert_not_called()
    assert protocol.journal.path.read_bytes() == before_bytes
    assert tuple(protocol.database.phases) == before_phases
    assert protocol.controls.off and protocol.controls.settled


def test_explicit_virgin_empty_target_and_initialized_null_are_not_missing_state(protocol):
    handoff = virgin()
    a = authority(protocol, handoff, 101)
    outcome = protocol.start(a, handoff)
    item = host.histories(history_bytes(protocol.journal))[a.transition_id]
    assert item.receipt.target is None and item.receipt.prepared.operation.target is None
    initialized = initialized_handoff(protocol, outcome)
    assert initialized.header.g is None and initialized.header.w is None
    assert initialized.header.q.witness is None and initialized.header.progress == "no-progress"
    assert initialized.header.epoch == 1
    assert_closed(protocol.start(authority(protocol, initialized, 102), initialized))


@pytest.mark.parametrize("boundary", ["prepare-before", "prepare-after", "ready-before", "ready-after",
                                    "intent-before", "intent-after", "receipt-before", "receipt-after",
                                    "complete-before", "complete-after"])
def test_every_phase_split_requires_new_exact_authority_no_guess_and_stays_closed(protocol, monkeypatch, boundary):
    handoff = virgin()
    a = authority(protocol, handoff, 101)
    original = journal.JournalSession.append
    labels = {"INTENT": "intent", "PREPARED-RECEIPT": "receipt", "COMPLETE": "complete"}

    def append(session, kind, data):
        if boundary == labels.get(kind, "-") + "-before":
            raise journal.JournalError("epoch-fixture-interruption")
        result = original(session, kind, data)
        if boundary == labels.get(kind, "-") + "-after":
            raise journal.JournalError("epoch-fixture-interruption")
        return result

    if boundary.startswith(("prepare-", "ready-")):
        protocol.database.fault = boundary
    with monkeypatch.context() as patch:
        patch.setattr(journal.JournalSession, "append", append)
        with pytest.raises(journal.JournalError):
            protocol.start(a, handoff)
    assert protocol.controls.off and protocol.controls.settled
    # Exact old authorization is stale after a reservation/receipt write.
    with pytest.raises(journal.JournalError):
        protocol.start(a, handoff)
    records = history_bytes(protocol.journal)
    item = host.histories(records).get(a.transition_id)
    recovery = authority(protocol, handoff, 101, "reconcile")
    if item is None:
        with pytest.raises(host.HostProtocolError, match="epoch-operation-missing"):
            protocol.reconcile(recovery, handoff)
    else:
        result = protocol.reconcile(recovery, handoff)
        assert_closed(result)
        assert result.epoch == 1 and result.status == "COMPLETE"
        assert len([p for p in protocol.database.phases if p.phase == "PREPARED"]) == 1
        assert len([p for p in protocol.database.phases if p.phase == "READY"]) == 1


@pytest.mark.parametrize("kind", ["INTENT", "PREPARED-RECEIPT", "COMPLETE"])
def test_actual_file_sync_uncertainty_requires_exact_approved_resync_before_continuing(protocol, monkeypatch, kind):
    handoff, original = virgin(), journal.JournalSession.append
    a = authority(protocol, handoff, 101)

    def append(session, current, data):
        if current != kind:
            return original(session, current, data)
        real_sync = os.fsync

        def fail(fd):
            if fd == session._fd:
                raise OSError("fixture-sync-canary")
            real_sync(fd)

        with monkeypatch.context() as patch:
            patch.setattr(os, "fsync", fail)
            return original(session, current, data)

    with monkeypatch.context() as patch:
        patch.setattr(journal.JournalSession, "append", append)
        with pytest.raises(journal.JournalError, match="epoch-history-sync-failed"):
            protocol.start(a, handoff)
    ready = [p for p in protocol.database.phases if p.phase == "READY"]
    assert bool(ready) == (kind == "COMPLETE")
    assert protocol.controls.off and protocol.controls.settled
    recovery = authority(protocol, handoff, 101, "reconcile")
    assert_closed(protocol.reconcile(recovery, handoff))


@pytest.mark.parametrize("visible_prepared", [False, True])
def test_explicit_abandonment_burns_reservation_and_next_distinct_operation_is_higher(protocol, visible_prepared):
    initial, _ = seed_seven(protocol)
    a = authority(protocol, initial, 108)
    protocol.database.fault = "prepare-after" if visible_prepared else "prepare-before"
    with pytest.raises(host.HostProtocolError):
        protocol.start(a, initial)
    result = protocol.abandon(authority(protocol, initial, 108, "abandon"), initial)
    assert result.epoch == 8 and result.status == "ABANDONED"
    assert_closed(result)
    with pytest.raises(host.HostProtocolError):
        protocol.reconcile(authority(protocol, initial, 108, "reconcile"), initial)
    next_result = protocol.start(authority(protocol, initial, 109), initial)
    assert next_result.epoch == 9
    history = host.histories(history_bytes(protocol.journal))
    assert history[a.transition_id].intent.epoch == 8 and history[a.transition_id].terminal.kind == "ABANDONED"
    assert history[next_result.transition_id].intent.epoch == 9


def test_ready_cannot_be_abandoned_or_different_operation_relabelled(protocol):
    handoff = virgin()
    protocol.database.fault = "ready-after"
    with pytest.raises(host.HostProtocolError):
        protocol.start(authority(protocol, handoff, 101), handoff)
    for action, number in (("abandon", 101), ("reconcile", 102)):
        with pytest.raises(host.HostProtocolError):
            getattr(protocol, action)(authority(protocol, handoff, number, action), handoff)
    assert not any(r.kind == "COMPLETE" for r in history_bytes(protocol.journal))
    assert protocol.controls.off


def test_restored_empty_never_init_but_explicit_restore_burns_above_host_max(protocol):
    initialized, _ = seed_seven(protocol)
    protocol.database.phases.clear()
    prior = protocol.journal.path.read_bytes()
    with pytest.raises(journal.JournalError):
        protocol.start(authority(protocol, virgin(), 108, reason="activation"), virgin())
    assert protocol.journal.path.read_bytes() == prior
    result = protocol.start(authority(protocol, initialized, 108, reason="restore"), initialized)
    assert result.epoch == 8 and protocol.database.phases[0].operation.epoch == 8
    assert_closed(result)


@pytest.mark.parametrize("bad_control", ["off", "settled", "native_available", "authority_available", "generation", "retained"])
def test_real_ops_prerequisites_cannot_be_replaced_by_structurally_valid_receipts(protocol, bad_control):
    protocol.database.rows = [codec.FinalRowAnchor(1, "consumed-native", 0)]
    initialized, _ = seed_seven(protocol, protocol.database.rows[0])
    a = authority(protocol, initialized, 108)
    if bad_control == "generation":
        protocol.controls.generation += 1
    elif bad_control == "retained":
        protocol.controls.retained.clear()
    else:
        setattr(protocol.controls, bad_control, False)
    before = protocol.journal.path.read_bytes()
    with pytest.raises(host.HostProtocolError, match="^epoch-control-unavailable$"):
        protocol.start(a, initialized)
    assert protocol.journal.path.read_bytes() == before


@pytest.mark.parametrize("field,value", [("state_version", 2), ("mode", "ACTIVE"), ("principal", "other"),
    ("source_instance", "not-canonical"), ("logical_reader_id", "bad"), ("epoch", 0), ("generation", True),
    ("progress", "cursorless"), ("w", None), ("q", None), ("g", "t1.not-a-row"), ("reached", 1)])
def test_closed_quiescent_header_rejects_missing_or_mixed_consumed_links(protocol, field, value):
    protocol.database.rows = [codec.FinalRowAnchor(1, "consumed-native", 0)]
    initialized, _ = seed_seven(protocol, protocol.database.rows[0])
    with pytest.raises(journal.JournalError):
        replace(initialized.header, **{field: value})


def test_q_missing_cannot_be_reconstructed_from_target_or_real_row_no_old_g_resolver(protocol):
    protocol.database.rows = [codec.FinalRowAnchor(1, "native-consumed", 0), codec.FinalRowAnchor(8, "target-only", 2)]
    handoff, _ = seed_seven(protocol, protocol.database.rows[0])
    row = handoff.payload()
    row["header"].pop("q")
    with pytest.raises(journal.JournalError):
        host.ClosedHandoff.parse(row)
    wrong_w = host.NativeWitness(SOURCE, "target-only", 2)
    with pytest.raises(journal.JournalError):
        replace(handoff.header, w=wrong_w)
    with pytest.raises(journal.JournalError):
        replace(handoff.header.q, evidence_refs=())
    q = handoff.header.q.payload()
    q["seq"] = 8
    with pytest.raises(journal.JournalError):
        host.NativeCheckpoint.parse(q)


def test_recovery_rechecks_original_handoff_identity_target_and_exact_receipts(protocol):
    protocol.database.rows = [codec.FinalRowAnchor(8, "fixed-target", 1)]
    handoff = virgin()
    protocol.database.fault = "ready-before"
    with pytest.raises(host.HostProtocolError):
        protocol.start(authority(protocol, handoff, 101), handoff)
    item = host.histories(history_bytes(protocol.journal))[uid(101)]
    recovery = authority(protocol, handoff, 101, "reconcile")
    wrong = replace(handoff, off_ref=uid(999))
    protocol.controls.admit(recovery, wrong)
    with pytest.raises(host.HostProtocolError, match="epoch-handoff-changed"):
        protocol.reconcile(recovery, wrong)
    protocol.controls.admit(recovery, handoff)
    protocol.database.identity = OTHER_IDENTITY
    with pytest.raises(host.HostProtocolError):
        protocol.reconcile(recovery, handoff)
    protocol.database.identity = IDENTITY
    protocol.database.rows.clear()
    with pytest.raises(host.HostProtocolError):
        protocol.reconcile(recovery, handoff)
    protocol.database.rows = [item.receipt.prepared.operation.target]
    protocol.database.phases[0] = replace(protocol.database.phases[0],
        operation=replace(protocol.database.phases[0].operation, reason="migration"))
    with pytest.raises(host.HostProtocolError, match="epoch-operation-mismatch"):
        protocol.reconcile(recovery, handoff)
    assert protocol.controls.off and all(p.phase != "READY" for p in protocol.database.phases)


def test_newer_database_phase_and_occupied_operation_cannot_be_mixed_into_recovery(protocol):
    handoff = virgin()
    protocol.database.fault = "prepare-after"
    with pytest.raises(host.HostProtocolError):
        protocol.start(authority(protocol, handoff, 101), handoff)
    original = protocol.database.phases[0]
    protocol.database.phases.append(replace(original, operation=replace(original.operation, epoch=2, transition_id=uid(102))))
    with pytest.raises(host.HostProtocolError):
        protocol.reconcile(authority(protocol, handoff, 101, "reconcile"), handoff)
    assert protocol.controls.off


def test_intent_pins_entire_db_basis_before_prepare_not_only_maximum(protocol, monkeypatch):
    initial, _ = seed_seven(protocol)
    original = protocol.database.prepare

    def changed(intent):
        prior = protocol.database.phases[0]
        protocol.database.phases[0] = replace(prior, created_at="2026-01-01T00:00:01.000000Z")
        original(intent)

    monkeypatch.setattr(protocol.database, "prepare", changed)
    with pytest.raises(host.HostProtocolError):
        protocol.start(authority(protocol, initial, 108), initial)
    item = host.histories(history_bytes(protocol.journal))[uid(108)]
    assert item.intent.epoch == 8 and item.receipt is None and item.terminal is None


def test_unfinished_transition_blocks_new_operator_even_with_fresh_pin(protocol):
    initial = virgin()
    protocol.database.fault = "prepare-before"
    with pytest.raises(host.HostProtocolError):
        protocol.start(authority(protocol, initial, 101), initial)
    with pytest.raises(host.HostProtocolError):
        protocol.start(authority(protocol, initial, 102), initial)
    assert len(host.histories(history_bytes(protocol.journal))) == 1


def test_closed_schema_and_immutable_receipt_grammar_rejects_checksumming_a_lie(protocol):
    handoff = virgin()
    outcome = protocol.start(authority(protocol, handoff, 101), handoff)
    records = history_bytes(protocol.journal)
    receipt = next(r for r in records if r.kind == "PREPARED-RECEIPT")
    data = receipt.data
    data["target"] = "t1.not-the-fixed-target"
    body = {**receipt.body(), "data": data}
    altered = replace(receipt, checksum=journal.digest(body), _payload=journal.canonical_bytes(data))
    with pytest.raises(journal.JournalError):
        host.validate_history(tuple(altered if r is receipt else r for r in records))
    # Independent semantic guard bite: envelope checks alone would accept a
    # freshly linked/checksummed false receipt; protocol parsing must not.
    invalid = receipt.data
    invalid["intent_checksum"] = "f" * 64
    changed = replace(receipt, _payload=journal.canonical_bytes(invalid))
    with pytest.raises(journal.JournalError):
        host.validate_history(tuple(changed if r is receipt else r for r in records))
    assert outcome.status == "COMPLETE"


def test_off_rechecked_after_last_durable_step_before_ready(protocol, monkeypatch):
    handoff, original = virgin(), journal.JournalSession.append

    def append(session, kind, data):
        result = original(session, kind, data)
        if kind == "PREPARED-RECEIPT":
            protocol.controls.off = False
        return result

    monkeypatch.setattr(journal.JournalSession, "append", append)
    with pytest.raises(host.HostProtocolError, match="epoch-control-unavailable"):
        protocol.start(authority(protocol, handoff, 101), handoff)
    assert [p.phase for p in protocol.database.phases] == ["PREPARED"]


def test_racing_operator_pins_serialize_one_success_one_closed_conflict(protocol):
    handoff, _ = seed_seven(protocol)
    first, second = authority(protocol, handoff, 108), authority(protocol, handoff, 109)
    assert first.expected_head == second.expected_head

    def attempt(a):
        try:
            return protocol.start(a, handoff)
        except journal.JournalError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, (first, second)))
    completed = [result for result in results if isinstance(result, host.ClosedOutcome)]
    refused = [result for result in results if isinstance(result, str)]
    assert len(completed) == len(refused) == 1
    assert completed[0].epoch == 8 and refused[0] in ("epoch-history-head-changed", "epoch-host-busy")
    assert len([item for item in host.histories(history_bytes(protocol.journal)).values() if item.intent.epoch == 8]) == 1
    assert_closed(completed[0])


def test_ready_without_any_host_receipt_is_not_reconstructed_or_released(protocol):
    handoff = virgin()
    protocol.database.fault = "ready-after"
    with pytest.raises(host.HostProtocolError):
        protocol.start(authority(protocol, handoff, 101), handoff)
    records = history_bytes(protocol.journal)
    # A fixed known split: DB READY but the retained host fixture has INTENT only.
    # A new exact head pin does not make absence of a matching receipt a pass.
    protocol.journal.path.write_bytes(b"".join(record.wire() for record in records if record.kind != "PREPARED-RECEIPT"))
    with pytest.raises(host.HostProtocolError, match="epoch-receipt-missing"):
        protocol.reconcile(authority(protocol, handoff, 101, "reconcile"), handoff)
    assert protocol.controls.off and not any(r.kind == "COMPLETE" for r in history_bytes(protocol.journal))


def test_old_consumed_reference_and_installed_target_must_bind_retained_complete(protocol):
    handoff, _ = seed_seven(protocol)
    for header in (replace(handoff.header, prior_refs=()), replace(handoff.header, target="t1.not-installed")):
        changed = handoff_for(header)
        before = protocol.journal.path.read_bytes()
        with pytest.raises(journal.JournalError):
            protocol.start(authority(protocol, changed, 108), changed)
        assert protocol.journal.path.read_bytes() == before


def test_guard_bite_actual_control_and_same_receipt_predicate_not_just_error_setup(protocol, monkeypatch):
    handoff = virgin()
    a = authority(protocol, handoff, 101)
    protocol.controls.off = False

    def must_refuse():
        with pytest.raises(host.HostProtocolError, match="epoch-control-unavailable"):
            protocol._verify(a, handoff)

    must_refuse()
    with monkeypatch.context() as mutation:
        mutation.setattr(protocol.controls, "verify", lambda *args: None)
        with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
            must_refuse()
    protocol.controls.off = True
    outcome = protocol.start(a, handoff)
    item = host.histories(history_bytes(protocol.journal))[outcome.transition_id]
    mixed = replace(item.receipt.prepared.operation, transition_id=uid(999))
    assert not item.intent.matches(mixed)
    with monkeypatch.context() as mutation:
        mutation.setattr(host.Intent, "matches", lambda *args: True)
        with pytest.raises(AssertionError):
            assert not item.intent.matches(mixed)


def test_epoch_exhaustion_and_control_path_alias_are_fixed_closed(protocol, monkeypatch):
    handoff, _ = seed_seven(protocol)
    a = authority(protocol, handoff, 108)
    with monkeypatch.context() as patch:
        patch.setattr(host, "MAX_EPOCH", 7)
        with pytest.raises(host.HostProtocolError, match="epoch-exhausted"):
            protocol.start(a, handoff)
    protocol.controls.journal_path = protocol.journal.path.with_name("unapproved-copy")
    with pytest.raises(host.HostProtocolError, match="epoch-control-unavailable"):
        protocol.start(a, handoff)


@pytest.mark.parametrize("field,value", [("actor", "application"), ("paper_sha256", "0" * 64),
    ("action", "enable"), ("reason", "reset"), ("plan_ref", "bad"), ("consent_ref", None),
    ("source_instance", "BAD"), ("logical_reader_id", "BAD"), ("transition_id", "BAD")])
def test_authority_contract_is_closed_not_a_release_or_reset_command(protocol, field, value):
    a = authority(protocol, virgin(), 101)
    with pytest.raises(journal.JournalError):
        replace(a, **{field: value})
    row = a.payload()
    row["auto_release"] = True
    with pytest.raises(journal.JournalError):
        host.HostAuthorization.parse(row)


def test_handoff_flags_native_null_and_db_phase_contract_refuse_mixed_shapes(protocol):
    handoff = virgin()
    for changed in ({"server_admission": "ON"}, {"registered_work": 1}, {"registered_work": False},
                    {"header_digest": "f" * 64}):
        with pytest.raises(journal.JournalError):
            replace(handoff, **changed)
    outcome = protocol.start(authority(protocol, handoff, 101), handoff)
    header = initialized_handoff(protocol, outcome).header
    with pytest.raises(journal.JournalError):
        replace(header, w=host.NativeWitness(SOURCE, "not-consumed", 0))
    item = host.histories(history_bytes(protocol.journal))[outcome.transition_id]
    for change in ({"phase": "COMPLETE"}, {"created_at": "not-time"}, {"created_at": "2026-01-01T00:00:00"},
                   {"target_seq": 0}, {"system_identifier": "not-identity"}):
        with pytest.raises(journal.JournalError):
            host.DatabasePhase.parse({**item.receipt.prepared.payload(), **change})
    with pytest.raises(journal.JournalError):
        host.NativeCheckpoint.parse({"transaction_id": uid(333), "evidence_refs": ["bad"], "witness": None})


def test_operation_cli_is_inert_for_every_argument_and_no_default_control_adapter(capsys):
    script = Path(__file__).parents[2] / "scripts" / "usage_feed_epoch.py"
    spec = importlib.util.spec_from_file_location("host_epoch_cli_fixture", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for arguments in ([], ["begin"], ["--operation", "restore"], ["private-path-canary"]):
        assert module.main(arguments) == 2
        captured = capsys.readouterr()
        assert captured.err == "epoch-operation-prerequisites-missing\n" and not captured.out
    assert module.main(["--describe"]) == 0
    assert '"operation": "unsupported"' in capsys.readouterr().out


@pytest.fixture(autouse=True)
def isolated_ordering_key(monkeypatch, _test_db):
    if get_database().engine.dialect.name == "postgresql":
        import hashlib

        with get_database().engine.connect() as connection:
            schema = connection.execute(text("SELECT current_schema()")).scalar_one()
        key = int.from_bytes(hashlib.sha256(schema.encode("ascii")).digest()[:8], "big", signed=True)
        monkeypatch.setattr(writer, "COMMIT_ORDER_LOCK", key)


def pg_protocol(tmp_path):
    engine = get_database().engine
    if engine.dialect.name != "postgresql":
        with pytest.raises(core.EpochError, match="^epoch-unsupported$"):
            host.PostgresEpochStore(engine).snapshot()
        return None
    with get_session() as session:
        source = ensure_instance(session)
    tmp_path.chmod(0o700)
    store = journal.HostJournal(tmp_path / "synthetic-pg-history", source, host.validate_history)
    return host.HostEpochProtocol(store, host.PostgresEpochStore(engine), FixtureControls())


def record():
    recorder.record("llm.call.completed", data={"prompt_tokens": 7, "completion_tokens": 3}, execution_id=uid(700))
    with get_session() as session:
        row = session.execute(select(UsageCallRow).order_by(UsageCallRow.seq.desc()).limit(1)).scalar_one()
        return codec.FinalRowAnchor(row.seq, row.event_id, row.revision)


def retain_older_throwaway_fixture(engine, maximum):
    # Emulates ONLY a known retained fixture history, not an external restore.
    # tests/pgtier.py has already forbidden live DB names/port and isolated schema.
    with engine.begin() as connection:
        connection.exec_driver_sql("ALTER TABLE usage_feed_epochs DISABLE TRIGGER USER")
        connection.execute(delete(core.EPOCHS).where(core.EPOCHS.c.epoch > maximum))
        connection.exec_driver_sql("ALTER TABLE usage_feed_epochs ENABLE TRIGGER USER")


def test_pg_combined_real_h7_d6_to8_fixed_target_newer_prepared_fence_and_closed_restart(tmp_path):
    protocol = pg_protocol(tmp_path)
    if protocol is None:
        return
    first, last = record(), record()
    handoff, _ = seed_seven(protocol, first)
    retain_older_throwaway_fixture(protocol.database.engine, 6)
    observed = []

    def before(connection, cursor, statement, parameters, context, executemany):
        observed.append(statement)

    event.listen(protocol.database.engine, "before_cursor_execute", before)
    try:
        outcome = protocol.start(authority(protocol, handoff, 108), handoff)
    finally:
        event.remove(protocol.database.engine, "before_cursor_execute", before)
    assert outcome.epoch == 8
    item = host.histories(history_bytes(protocol.journal))[outcome.transition_id]
    assert item.intent.host_max == 7 and item.intent.db_max == 6
    assert item.receipt.prepared.operation.target == last and handoff.header.w.event_id == first.event_id
    assert item.receipt.target != handoff.header.g
    # Every fresh owned host transaction locks BEFORE any SELECT/snapshot.
    locked = False
    for sql in observed:
        if sql == "SET TRANSACTION READ WRITE":
            locked = False
        if sql == core.HOST_LOCK_SQL:
            locked = True
        if sql.lstrip().upper().startswith("SELECT"):
            assert locked
    assert sum(sql == core.HOST_LOCK_SQL for sql in observed) >= 5
    assert not any("last_value" in sql.lower() or "nextval" in sql.lower() for sql in observed)
    assert_closed(protocol.reconcile(authority(protocol, handoff, 108, "reconcile"), handoff))
    assert protocol.database.snapshot().maximum == 8


@pytest.mark.parametrize("phase", ["prepare", "ready"])
def test_pg_unknown_real_commit_readback_uses_exact_operation_once(tmp_path, monkeypatch, phase):
    protocol = pg_protocol(tmp_path)
    if protocol is None:
        return
    record()
    handoff = virgin(protocol.journal.source_instance)
    actual = getattr(protocol.database, phase)

    def unknown(*args):
        actual(*args)
        raise host.HostProtocolError("epoch-fixture-commit-unknown")

    with monkeypatch.context() as patch:
        patch.setattr(protocol.database, phase, unknown)
        with pytest.raises(host.HostProtocolError):
            protocol.start(authority(protocol, handoff, 101), handoff)
    assert protocol.controls.off and protocol.controls.settled
    if phase == "prepare":
        with pytest.raises(core.EpochError, match="epoch-transition"):
            with core.reader_epoch_snapshot(protocol.database.engine) as reader:
                core.read_current_ready_epoch(reader)
    result = protocol.reconcile(authority(protocol, handoff, 101, "reconcile"), handoff)
    assert_closed(result)
    view = protocol.database.snapshot()
    assert [(p.operation.epoch, p.phase) for p in view.phases] == [(1, "PREPARED"), (1, "READY")]


def test_pg_restored_empty_does_not_reinitialize_and_sequence_allocation_is_not_target(tmp_path):
    protocol = pg_protocol(tmp_path)
    if protocol is None:
        return
    last = record()
    handoff, _ = seed_seven(protocol, last)
    retain_older_throwaway_fixture(protocol.database.engine, 0)
    # Advance test-only sequence without a FINAL row: T must still be last.
    with protocol.database.engine.begin() as connection:
        connection.execute(text("SELECT nextval(pg_get_serial_sequence('usage_call_rows', 'seq'))"))
    outcome = protocol.start(authority(protocol, handoff, 108, reason="restore"), handoff)
    assert outcome.epoch == 8
    item = host.histories(history_bytes(protocol.journal))[outcome.transition_id]
    assert item.intent.db_max == 0 and item.intent.host_max == 7 and item.receipt.prepared.operation.target == last
    assert_closed(outcome)
