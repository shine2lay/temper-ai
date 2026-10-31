"""Captured provider input and committed application are different boundaries."""

from copy import deepcopy
from dataclasses import replace

import pytest

from temper_ai.clarifications import contracts as c
from temper_ai.clarifications import delivery_models as dm
from temper_ai.clarifications import models as m
from temper_ai.integrations.telegram import clarifications as e
from temper_ai.integrations.telegram import poller
from tests.test_clarifications import composition_scenarios as s
from tests.test_clarifications import composition_vectors as v
from tests.test_clarifications.test_caller_integration import Composition
from tests.test_clarifications.test_caller_integration import db as db
from tests.test_clarifications.test_composed_history import cases


def pull_batch(rig, update):
    rig.provider.updates = [deepcopy(update)]
    return rig.edge.pull(rig.provider, None, timeout=0, allowed=poller.ALLOWED)


@pytest.mark.parametrize("case", cases("V08"), ids=lambda case: case.name)
def test_V08_real_capture_provenance_and_independent_snapshot(db, monkeypatch, case):
    rig = Composition(db, monkeypatch)
    rig.ready()
    words, press = v.pulled_updates()
    if "trusted_port_receipt" in case.inputs:
        result = rig.append(case.inputs["trusted_port_receipt"]).result
        assert result.status == "refused" and result.code in (c.RefusalCode.UNVERIFIED_INGRESS, c.RefusalCode.MODEL_NOT_HUMAN)
        assert rig.receipts() == {}
    elif "after_capture_change" in case.inputs:
        name = case.name
        if name == "nested_callback_data":
            rig.pull(words)
            batch = pull_batch(rig, press)
            pulled = batch.updates[0]
            pulled["callback_query"]["data"] = case.inputs["altered_data"]
            assert batch.claim(pulled)
            assert rig.transport_store.receipt(v.confirmation_receipt().action.key) == v.confirmation_receipt()
        else:
            batch = pull_batch(rig, words)
            pulled = batch.updates[0]
            if name == "nested_text":
                pulled["message"]["text"] = case.inputs["altered_text"]
            elif name == "nested_sender":
                pulled["message"]["from"]["id"] = int(case.inputs["altered_sender"])
            elif name in ("append_foreign_object", "different_edge"):
                foreign = deepcopy(pulled)
                if name == "different_edge":
                    another = e.ClarificationEdge(rig.provider, rig.transport_store, rig.policy)
                    rig.provider.updates = [foreign]
                    other_batch = another.pull(rig.provider, None, timeout=0, allowed=poller.ALLOWED)
                    foreign = other_batch.updates[0]
                with pytest.raises(c.ContractRefusal) as caught:
                    batch.claim(foreign)
                assert caught.value.guard == "edge.pulled" and rig.receipts() == {}
            else:
                with pytest.raises(c.ContractRefusal) as caught:
                    rig.edge.pull(s.SyntheticTelegram(), None, timeout=0, allowed=poller.ALLOWED)
                assert caught.value.guard == "edge.client" and rig.receipts() == {}
            assert batch.claim(pulled)
            assert rig.transport_store.receipt(v.typed_receipt().action.key) == v.typed_receipt()
    elif "update_changes" in case.inputs:
        if case.name == "wrong_question":
            result = rig.append(replace(v.answer_receipt(), binding=replace(v.answer_receipt().binding,
                                    question_id=case.inputs["update_changes"]["question_id"]))).result
            assert result.status == "refused" and result.code == c.RefusalCode.BINDING_MISMATCH
        elif case.name == "wrong_bot":
            # M2 takes its bot from the provider's own getMe, never from the
            # message: a reply reaches another bot only through that bot's own
            # pull, whose namespace holds no copy of ours.
            other = s.SyntheticTelegram(bot_id=case.inputs["update_changes"]["reply_bot_id"])
            other_edge = e.ClarificationEdge(other, rig.transport_store, rig.policy)
            other.updates = [deepcopy(words)]
            routed = []
            assert poller.Poller(other, routed.append, timeout=0, clock=lambda: 1700000001,
                                 clarifications=other_edge).poll_once() == 1
            assert len(routed) == 1 and other.sent == [] and len(rig.provider.sent) == 1
        else:
            message = words["message"]
            if case.name == "wrong_chat":
                message["chat"]["id"] = -1002
            elif case.name == "denied_sender":
                message["from"]["id"] = 5002
            elif case.name == "bot_sender":
                message["from"]["is_bot"] = True
            else:
                message["forward_origin"] = {"type": "user"}
            rig.pull(words)
        assert rig.context().prior_revision == 1 and rig.receipts() == {}
    else:
        rig.pull(words)
        rig.pull(press)
        assert rig.transport_store.receipt(v.typed_receipt().action.key).text == v.ANSWER
        assert rig.transport_store.receipt(v.confirmation_receipt().action.key).callback_data == "clar:answered"
    assert rig.coordinator.recover(rig.initial).meaning_status == "NOT_EVALUATED"


@pytest.mark.parametrize("case", cases("V19"), ids=lambda case: case.name)
def test_V19_committed_final_refusal_is_not_a_successful_capture(db, monkeypatch, case):
    rig = Composition(db, monkeypatch)
    rig.ready()
    words, press = v.pulled_updates()
    if case.name == "accepted_capture_final_refusal":
        receipt = case.inputs["receipt"]
        validation = c.validate_receipt(receipt, presentation=v.presentation(), copies={"500"},
                                        current_generation=1, question_ids={v.Q})
        assert validation.status == "accepted"
        ingress = e.PulledIngress(v.TRANSPORT, receipt.update_id, c.receipt_sha256(receipt), None)
        # The trusted M0/M3 port can supply corrections. No Telegram correction
        # UI, forged PulledBatch or authoritative capture is manufactured here.
        assert rig.edge._keep(ingress, receipt, validation) == "refused"
        assert len(db.rows(dm.ClarificationIngress)) == len(db.rows(m.ClarificationRefusal)) == 1
        assert rig.receipts() == {} and rig.offset() is None
        assert len(rig.provider.sent) == 1 and rig.context().prior_revision == 1
        diagnostic = db.rows(dm.ClarificationIngress)[0]
        assert diagnostic.diagnostic_code == "missing_record"
        # Then exercise actual pull -> final changed-body refusal -> M2 ack /
        # offset ordering, with a real competing commit, not a fake store return.
        rig.pull(words)
        append = db.store.append_receipt_with_ingress

        def rival(ingress, receipt, validation):
            alternate = replace(receipt, disposition="unknown", callback_data="clar:unknown")
            judged = c.validate_receipt(alternate, presentation=v.presentation(), copies={"500", "600"},
                                        current_generation=1, question_ids={v.Q}, confirmed=v.typed_receipt())
            append(ingress, alternate, judged)
            return append(ingress, receipt, validation)

        monkeypatch.setattr(db.store, "append_receipt_with_ingress", rival)
        rig.before_ack = lambda: assert_refused_before_offset(rig)
        assert rig.pull(press) == 0 and rig.provider.callbacks[-1][1] == "Not applied."
        assert rig.offset() == "1003" and len(rig.provider.sent) == 2
    elif case.name == "existing_fake_protocol":
        # Existing fake protocol is run unchanged as an affected-stage suite;
        # this case proves actual-store successful behavior remains Received.
        rig.pull(words)
        rig.pull(press)
        assert rig.provider.callbacks[-1][1] == "Received." and len(rig.receipts()) == 2
    else:
        rig.pull(words)
        before, offset = db.dump(), rig.offset()
        def fail(*args, **kwargs):
            if case.name == "ordinary_contract_refusal":
                raise c.ContractRefusal(c.RefusalCode.MALFORMED, "synthetic.uncommitted", "receipt")
            raise RuntimeError("synthetic injected outage")
        target, method = {
            "database_down": (db.store, "_commit"),
            "policy_down": (rig.authority, "require"),
            "ordinary_contract_refusal": (rig.transport_store, "keep_receipt"),
        }[case.name]
        monkeypatch.setattr(target, method, fail)
        with pytest.raises(case.inputs["error"]):
            rig.pull(press)
        assert db.dump() == before and rig.offset() == offset and rig.provider.callbacks == []


def assert_refused_before_offset(rig):
    assert any(row.diagnostic_code == "changed_body" for row in rig.db.rows(dm.ClarificationIngress))
    assert rig.offset() == "1002"
