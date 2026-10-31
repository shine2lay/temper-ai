"""M4 E: actual composed library on isolated real persistence, fake network only.

V01 is deliberately first. Input/expected records come from A/D, never from
checker output. The offset uses the ordinary Telegram store on the SAME isolated
engine. No default engine, running poller, provider, model or application is used.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace

import pytest
from sqlmodel import Session, SQLModel

from temper_ai import database
from temper_ai.clarifications import contracts as c
from temper_ai.clarifications import delivery_models as dm
from temper_ai.clarifications import models as m
from temper_ai.clarifications.caller import ClarificationCoordinator
from temper_ai.clarifications.caller_contracts import PresentationRequest
from temper_ai.clarifications.delivery_store import ClarificationDeliveryStore
from temper_ai.integrations.telegram import clarifications as edge_module
from temper_ai.integrations.telegram import poller
from temper_ai.integrations.telegram import store as telegram_store
from temper_ai.integrations.telegram.clarification_store import (
    TelegramClarificationStore,
)
from temper_ai.integrations.telegram.models import TelegramState
from tests.test_clarifications import composition_scenarios as s
from tests.test_clarifications import composition_vectors as v
from tests.test_clarifications import test_store as persistence
from tests.test_integrations.test_telegram_store_binding import Authority

db = persistence.db


class Composition:
    """Real components; observations wrap effects, never supply store results."""

    def __init__(self, db, monkeypatch, *, initialize=True):
        self.db = db
        self.data = v.happy_path_inputs()
        self.initial = self.data["caller"]
        self.authority = Authority()
        self.provider = s.SyntheticTelegram(message_ids=range(500, 2000, 100))
        self.policy = s.SyntheticResponderPolicy(self.data["policy_allowed"])
        self.ordinary = []
        self.effects = []
        self.before_send = lambda: None
        self.before_ack = lambda: None
        self.observer_errors = []
        if initialize:
            SQLModel.metadata.create_all(db.engine, tables=[TelegramState.__table__])
            db.run(TelegramState.__table__.delete())

        @contextmanager
        def session():
            # Ordinary Telegram offset persistence, explicitly scoped to this fixture.
            with Session(self.db.engine) as held:
                yield held

        monkeypatch.setattr(database, "get_session", session)
        send, answer = self.provider.send, self.provider.answer_callback

        def observed_send(*args, **kwargs):
            self.observe(self.before_send)
            self.effects.append(("send", self.offset()))
            return send(*args, **kwargs)

        def observed_ack(*args, **kwargs):
            self.observe(self.before_ack)
            self.effects.append(("ack", self.offset()))
            return answer(*args, **kwargs)

        self.provider.send = observed_send
        self.provider.answer_callback = observed_ack
        self.bind()

    def observe(self, check):
        try:
            check()
        except Exception as error:
            self.observer_errors.append(error)
            raise

    def checked_observers(self, result):
        if self.observer_errors:
            raise self.observer_errors[0]
        return result

    def assert_typed_committed(self):
        retained = self.receipts()[self.data["typed_receipt"].action.key]
        assert (retained.status, retained.code, retained.revision) == ("retained", "no_explicit_disposition", 1)
        assert c.receipt_from_json(retained.receipt_json).text == v.ANSWER
        assert len(self.db.rows(dm.ClarificationIngress)) == 1
        assert self.db.other().load(self.initial.stream).record()["events"] == []
        assert sorted(row.attempt_count for row in self.db.rows(dm.ClarificationSend)) == [1, 1]
        assert self.offset() is None, "typed offset advanced before prompt"

    def assert_confirmed_committed(self):
        """Observed before the confirming press is acknowledged, on an independent connection."""
        loaded = self.db.other().load(self.initial.stream)
        assert loaded.revision == 2, "application commit before ack"
        assert loaded.record() == self.data["record"]
        confirmed = self.data["confirmed_receipt"]
        applied = self.receipts()[confirmed.action.key]
        assert (applied.status, applied.event_id, applied.revision) == ("applied", c.event_id(confirmed), 2)
        ingress = next(row for row in self.db.rows(dm.ClarificationIngress) if row.update_id == 1002)
        assert json.loads(ingress.result_json)["status"] == "applied"
        assert self.offset() == "1002"  # append+ingress commit before callback acknowledgement

    def bind(self):
        self.ledger = ClarificationDeliveryStore(self.db.store)
        self.transport_store = TelegramClarificationStore(
            self.db.store, self.ledger, authority=self.authority, stream=self.initial.stream,
            source_authority_ref=self.initial.source_authority_ref,
            responder_policy_ref=self.initial.responder_policy_ref,
        )
        self.edge = edge_module.ClarificationEdge(self.provider, self.transport_store, self.policy)
        self.coordinator = ClarificationCoordinator(
            store=self.db.store, transport=self.edge, authority=self.authority,
            clarified_validator=s.clarified_validator(),
        )
        self.poller = poller.Poller(self.provider, self.ordinary.append, timeout=0,
                                    clock=lambda: 1700000001, clarifications=self.edge)

    def restart(self):
        self.db.restart()
        self.bind()

    def offset(self):
        return telegram_store.get_state(poller.OFFSET_KEY)

    def context(self, *, ask=()):
        loaded = self.db.store.load(self.initial.stream)
        return replace(self.initial, prior_revision=loaded.revision, prior_record_json=loaded.record_json,
                       prior_record_sha256=loaded.record_sha256, question_ids=tuple(ask))

    def present(self, caller=None):
        return self.checked_observers(self.coordinator.present(
            self.context(ask=(v.Q,)) if caller is None else caller,
            presentations=(PresentationRequest(self.data["presentation"], self.data["display_text"]),),
        ))

    def pull(self, update, *, replay=False):
        self.provider.updates = [deepcopy(update)]
        if replay:
            telegram_store.set_state(poller.OFFSET_KEY, str(update["update_id"]))
        return self.checked_observers(self.poller.poll_once())

    def receipts(self):
        return {row.action_key: row for row in self.db.rows(m.ClarificationReceipt)}

    def ready(self):
        self.coordinator.prepare(self.initial)
        self.present()

    def append(self, receipt, *, after_capture=None):
        """Trusted-port control, NOT proof of provider capture or an invented UI.

        after_capture runs between capture validation and the store's append,
        where a rival commit lands in a K5 race.
        """
        view = self.db.store.protocol_view(self.initial.stream)
        presentation = next(p for p in view.presentations if p.presentation_id == receipt.binding.presentation_id)
        confirmed = next((r for r in view.receipts if receipt.confirms and
                          r.action.key == receipt.confirms.action.key), None)
        validation = c.validate_receipt(
            receipt, presentation=presentation,
            copies={b.message_id for b in view.copies if b.presentation_id == presentation.presentation_id},
            current_generation=max(p.generation for p in view.presentations if p.question_id == presentation.question_id),
            question_ids=view.question_ids,
            confirmed=confirmed,
        )
        ingress = edge_module.PulledIngress(v.TRANSPORT, receipt.update_id, c.receipt_sha256(receipt), None)
        if after_capture is not None:
            after_capture()
        return self.db.store.append_receipt_with_ingress(ingress, receipt, validation)

    def row(self):
        return s.row(self.coordinator.recover(self.initial).display, v.Q)

    def answer(self, *, text=v.ANSWER, payload="clar:answered", sender=v.OWNER):
        self.ready()
        words, press = v.pulled_updates(text, payload=payload, callback_sender=sender)
        assert self.pull(words) == 0
        assert self.pull(press) == 0
        return words, press

    def check(self, candidate=None):
        return self.coordinator.check_candidate(
            self.context(), profile=self.data["candidate"] if candidate is None else candidate,
            candidate_ref="candidate:synthetic/clarified",
        )


def test_V01_combined_happy_first(db, monkeypatch):
    rig = Composition(db, monkeypatch)
    expected = rig.data
    assert rig.provider.sent == [] and rig.effects == [] and rig.offset() is None
    prepared = rig.coordinator.prepare(rig.initial)
    assert prepared.record.revision == 1
    assert prepared.meaning_status == "NOT_EVALUATED"
    assert prepared.display["ask"] == []
    assert len(prepared.display["questions"]) == len(s.BASE_FIELDS) + 1

    def before_question():
        # Independent connection, before the fake provider receives the request.
        durable = db.other().load(rig.initial.stream)
        sends = db.rows(dm.ClarificationSend)
        assert durable.revision == 1 and len(sends) == 1
        assert sends[0].attempt_count == 1 and sends[0].message_id is None
        assert rig.offset() is None and db.rows(dm.ClarificationDelivery) == []

    rig.before_send = before_question
    result, = rig.present()
    assert result.state == "sent" and result.message_id == v.QUESTION_COPY
    assert rig.transport_store.copies(expected["presentation"].presentation_id) == frozenset({v.QUESTION_COPY})

    rig.before_send = rig.assert_typed_committed
    words, press = expected["updates"]
    assert rig.pull(words) == 0 and rig.offset() == "1002"
    assert rig.transport_store.receipt(expected["typed_receipt"].action.key) == expected["typed_receipt"]
    assert len(rig.provider.sent) == 2

    rig.before_ack = rig.assert_confirmed_committed
    assert rig.pull(press) == 0 and rig.offset() == "1003"
    assert rig.transport_store.receipt(expected["confirmed_receipt"].action.key) == expected["confirmed_receipt"]
    assert rig.provider.callbacks[-1][1] == "Received."
    assert rig.effects == [("send", None), ("send", None), ("ack", "1002")]
    assert rig.ordinary == [] and not rig.poller.running

    rig.restart()
    assert rig.offset() == "1003"
    before_recovery = db.dump()
    recovered = rig.coordinator.recover(rig.initial)
    assert recovered.stored.revision == 2 and recovered.stored.record() == expected["record"]
    assert recovered.supplement.original_brief == s.BRIEF and not recovered.supplement.consumed
    assert recovered.supplement.source_mapping == expected["source"]["source_mapping"]
    row = s.row(recovered.display, v.Q)
    assert row["answer"] == v.ANSWER and tuple(row["active_event_ids"]) == expected["active_event_ids"]
    assert rig.transport_store.copies(expected["presentation"].presentation_id) == frozenset({"500", "600"})
    for message_id in ("500", "600"):
        assert rig.transport_store.delivery(v.TRANSPORT, v.CHAT, message_id) is not None
    checked = rig.check()
    assert checked.report["references_ok"] is True and checked.report["errors"] == []
    assert checked.report["meaning_status"] == "NOT_EVALUATED"
    assert checked.original_text == s.BRIEF and json.loads(checked.candidate_json) == expected["candidate"]
    assert len(checked.report["unresolved_questions"]) == len(s.BASE_FIELDS)
    assert db.dump() == before_recovery  # check/recover never consume or execute
    context = rig.context()
    assert rig.coordinator.acknowledge_consumption(context, checked=checked) is True
    assert rig.coordinator.acknowledge_consumption(context, checked=checked) is False
    assert len(db.rows(m.ClarificationConsumption)) == 1

    stable = db.dump(skip=("clarification_streams", "clarification_ingresses"))
    rig.before_send = lambda: pytest.fail("replay sent a new question or prompt")
    rig.before_ack = lambda: None  # repeated callback receipt acknowledgement is allowed, not a new send
    assert rig.pull(words, replay=True) == 0 and rig.pull(press) == 0
    assert db.dump(skip=("clarification_streams", "clarification_ingresses")) == stable
    assert rig.context().prior_revision == 2 and len(rig.provider.sent) == 2
    assert rig.ordinary == [] and not rig.poller.running
    assert rig.coordinator.acknowledge_consumption(context, checked=checked) is False
