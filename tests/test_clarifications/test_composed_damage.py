"""V15 damages real isolated rows, then uses actual composed read/write ports."""

from dataclasses import replace

import pytest
from sqlalchemy import delete, update

from temper_ai.clarifications import contracts as c
from temper_ai.clarifications import delivery_models as dm
from temper_ai.clarifications import models as m
from temper_ai.clarifications.store import ClarificationIntegrityError
from tests.test_clarifications import composition_vectors as v
from tests.test_clarifications import test_store as persistence
from tests.test_clarifications.test_caller_integration import Composition
from tests.test_clarifications.test_caller_integration import db as db
from tests.test_clarifications.test_composed_history import cases


@pytest.mark.parametrize("case", cases("V15"), ids=lambda case: case.name)
def test_V15_damage_refuses_without_replacement_history(db, monkeypatch, case):
    rig = Composition(db, monkeypatch)
    rig.answer()
    context = rig.context()
    key = v.confirmation_receipt().action.key
    operations = {
        "load": lambda: db.store.load(context.stream),
        "supplement": lambda: db.store.supplement(context.stream, revision=2, original_brief=context.original_text),
        "merge_candidate": lambda: db.store.merge_candidate(context),
        "save_presentation": lambda: db.store.save_presentation(v.presentation(2)),
        "record_copy": lambda: db.store.record_copy(replace(v.answer_receipt().binding, message_id="599")),
        "append_receipt": lambda: rig.append(v.answer_receipt()),
        "mark_consumed": lambda: db.store.mark_consumed(context.stream, revision=2, original_brief=context.original_text),
        "delivery": lambda: rig.transport_store.delivery(v.TRANSPORT, v.CHAT, "500"),
        "copies": lambda: rig.transport_store.copies(v.presentation().presentation_id),
        "start_attempt": lambda: rig.transport_store.start_attempt(v.presentation().presentation_id,
                                                                    expected_attempts=1, resend=True),
        "current_generation": lambda: rig.transport_store.current_generation(context.stream.stream_id, v.Q),
        "question_ids": lambda: rig.transport_store.question_ids(context.stream.stream_id),
        "answered": lambda: rig.transport_store.answered(context.stream.stream_id, v.Q),
        "receipt": lambda: rig.transport_store.receipt(key),
    }
    if case.name == "fork_remapped_gate_ids":
        fork = replace(context, stream=case.inputs["other_stream"], prior_revision=0,
                       prior_record_json=None, prior_record_sha256=None)
        with pytest.raises(c.ContractRefusal) as caught:
            rig.coordinator.recover(fork)
        assert caught.value.code == c.RefusalCode.MISSING_RECORD
        assert case.inputs["remapped_gate_event"] not in rig.row()["active_event_ids"]
        assert len(db.rows(m.ClarificationStream)) == 1
        return
    if case.name == "clean":
        before = db.dump()
        rig.coordinator.recover(context)
        rig.check()
        assert db.dump() == before
        return
    if case.name.startswith("applied_event_"):
        if case.inputs["recompute_result_digest"]:
            persistence.rewrite_result(db, key, **case.inputs["receipt_columns"])
        else:
            db.run(update(m.ClarificationReceipt).where(m.ClarificationReceipt.action_key == key)
                   .values(**case.inputs["receipt_columns"]))
    elif case.name.startswith("retained_"):
        db.run(update(m.ClarificationReceipt).where(m.ClarificationReceipt.action_key == v.typed_receipt().action.key)
               .values(**case.inputs["receipt_columns"]))
    elif case.name == "unused_copy":
        db.store.record_copy(replace(v.answer_receipt().binding, message_id="598"))
        db.run(update(m.ClarificationCopy).where(m.ClarificationCopy.message_id == "598")
               .values(**case.inputs["copy_columns"]))
        operations["load"] = lambda: rig.append(v.answer_receipt(message_id="599"))
    elif "new_read_path" in case.inputs:
        damage = case.inputs["damage"]
        if damage == "substitute_send_binding":
            db.run(update(dm.ClarificationSend).values(presentation_id="p-" + "f" * 64))
        elif damage == "substitute_delivery_lookup":
            db.run(update(dm.ClarificationDelivery).where(dm.ClarificationDelivery.message_id == "500")
                   .values(message_id="599"))
        else:
            db.run(delete(dm.ClarificationDelivery).where(dm.ClarificationDelivery.message_id == "500"))
    elif case.name in ("delete_required_prior_receipt", "retention_missing_required_receipt"):
        if case.name.startswith("retention"):
            assert rig.coordinator.acknowledge_consumption(context, checked=rig.check())
        db.run(delete(m.ClarificationReceipt).where(m.ClarificationReceipt.action_key == v.typed_receipt().action.key))
    elif case.name == "alter_record_hash":
        db.run(update(m.ClarificationRevision).where(m.ClarificationRevision.revision == 2)
               .values(record_sha256="f" * 64))
    elif case.name == "truncate_history":
        db.run(delete(m.ClarificationRevision).where(m.ClarificationRevision.revision == 1))
    else:
        assert case.name == "remove_required_revision"
        db.run(delete(m.ClarificationRevision).where(m.ClarificationRevision.revision == 2))
    before = db.dump()
    sends = len(rig.provider.sent)
    with pytest.raises(ClarificationIntegrityError) as caught:
        operations[case.inputs.get("path", case.inputs.get("new_read_path", "load"))]()
    if "guard" in case.expected:
        assert caught.value.guard == case.expected["guard"]
    with pytest.raises(ClarificationIntegrityError):
        rig.coordinator.recover(context)
    assert db.dump() == before and len(rig.provider.sent) == sends
