"""M4 supplied-input, identity, reference and explicit-effect boundaries."""

import json
from copy import deepcopy
from dataclasses import asdict, replace

import pytest

from configs.architecture.bin import context_profile_clarification_caller as m1
from configs.architecture.bin.context_profile_clarified_check import (
    check_clarified_profile,
)
from temper_ai.clarifications import contracts as c
from temper_ai.clarifications import models as m
from temper_ai.clarifications import preparation_adapter as adapter
from temper_ai.clarifications.caller import ClarificationCoordinator
from temper_ai.integrations.telegram import poller
from tests.test_clarifications import composition_scenarios as s
from tests.test_clarifications import composition_vectors as v
from tests.test_clarifications.test_caller_integration import Composition
from tests.test_clarifications.test_caller_integration import db as db
from tests.test_clarifications.test_composed_history import cases


@pytest.mark.parametrize("case", cases("V02"), ids=lambda case: case.name)
@pytest.mark.parametrize("entry", ("prepare", "compose_supplement"))
def test_V02_real_complete_check_precedes_state(db, monkeypatch, case, entry):
    rig = Composition(db, monkeypatch)
    before = db.dump()
    if "injected_error" in case.inputs:
        failure = case.inputs["injected_error"]("synthetic checker failure")

        def fail(*args, **kwargs):
            raise failure

        monkeypatch.setattr(m1.checker, "check", fail)
        candidate = s.composition_profile()
        if case.inputs["malformed"]:
            candidate["unknowns"][0]["field"] = []
        with pytest.raises(type(failure)) as caught:
            getattr(adapter, entry)(s.inputs(candidate))
        assert caught.value is failure
    elif case.name == "clean":
        rig.coordinator.prepare(s.inputs(case.inputs["candidate"]))
        result = getattr(adapter, entry)(rig.context())
        assert result["meaning_status"] == "NOT_EVALUATED"
        return
    else:
        caller = s.inputs(case.inputs["candidate"])
        with pytest.raises(m1.CallerRefusal) as caught:
            getattr(adapter, entry)(caller)
        assert caught.value.guard == "candidate.complete" and caught.value.errors
        with pytest.raises(m1.CallerRefusal) as coordinated:
            rig.coordinator.prepare(caller)
        assert coordinated.value.guard == "candidate.complete"
    assert db.dump() == before and rig.provider.sent == [] and rig.authority.calls == []


@pytest.mark.parametrize("case", cases("V03"), ids=lambda case: case.name)
def test_V03_canonical_binding_and_explicit_authority(db, monkeypatch, case):
    rig = Composition(db, monkeypatch)
    before = db.dump()
    if "caller_changes" in case.inputs:
        with pytest.raises(c.ContractRefusal) as caught:
            s.inputs(case.inputs["candidate"], **case.inputs["caller_changes"])
        assert caught.value.guard == case.expected["guard"]
    elif case.name == "exact_type":
        supplied = case.inputs["caller"]
        with pytest.raises(m1.CallerRefusal) as caught:
            m1.prepare(supplied)
        assert caught.value.guard == "caller.type"
        original = m1.prepare
        seen = []

        def observe(local):
            seen.append(asdict(local))
            return original(local)

        monkeypatch.setattr(m1, "prepare", observe)
        assert adapter.prepare(supplied)["meaning_status"] == "NOT_EVALUATED"
        assert seen == [asdict(supplied)]
    elif case.name == "other_namespace":
        rig.ready()
        before = db.dump()
        other = replace(rig.initial, stream=case.inputs["stream"])
        with pytest.raises(c.ContractRefusal) as caught:
            rig.coordinator.recover(other)
        assert caught.value.code == c.RefusalCode.MISSING_RECORD
    else:
        operation = case.inputs["authority_denies"]
        if operation == "send":
            rig.coordinator.prepare(rig.initial)
            before = db.dump()
        rig.authority.denied.add(operation)
        with pytest.raises(PermissionError):
            rig.present() if operation == "send" else rig.coordinator.prepare(rig.initial)
        assert rig.provider.sent == []
    assert db.dump() == before


@pytest.mark.parametrize("case", cases("V16"), ids=lambda case: case.name)
def test_V16_metadata_identity_never_aliases_or_discards_history(db, monkeypatch, case):
    rig = Composition(db, monkeypatch)
    rig.answer()
    initial = db.store.load(rig.initial.stream).record()
    candidates = case.inputs.get("candidates", (case.inputs.get("candidate"),))
    for candidate in candidates:
        current = rig.context()
        supplied = s.inputs(candidate, revision=current.prior_revision, record=current.prior_record_json)
        result = rig.coordinator.prepare(supplied)
        assert json.loads(result.record.record_json)["events"] == initial["events"]
        assert result.meaning_status == "NOT_EVALUATED"
    old = s.row(result.display, v.Q)
    assert old["answer"] == v.ANSWER
    if case.name not in ("reorder", "drop_reintroduce"):
        new = s.row(result.display, case.expected["question_id"])
        assert new["question_id"] != v.Q and new["state"] == "unanswered" and new["active_event_ids"] == []
    assert len(rig.provider.sent) == 2


@pytest.mark.parametrize("case", cases("V17"), ids=lambda case: case.name)
def test_V17_real_source_checker_is_not_meaning_acceptance(db, monkeypatch, case):
    if case.name == "model_only_reference":
        # This is the supplied-record checker boundary: M0 never authenticates a
        # model event as a human receipt. No manufactured persistent history.
        report = check_clarified_profile(case.inputs["candidate"], s.BRIEF, case.inputs["record"], s.clarified_validator())
        assert report["references_ok"] is False and report["meaning_status"] == "NOT_EVALUATED"
        return
    rig = Composition(db, monkeypatch)
    if case.name == "unresolved_reference":
        rig.ready()
        candidate = case.inputs["candidate"]
    elif case.name == "negative_answer_reference_only":
        rig.ready()
        assert rig.append(v.answer_receipt("606", "no")).result.status == "applied"
        candidate = case.inputs["candidate"]
    else:
        rig.answer()
        assert rig.append(v.answer_receipt("602")).result.status == "applied"
        candidate = deepcopy(case.inputs.get("candidate", case.inputs.get("base", {}).get("candidate")))
        if case.name == "old_answer_after_correction":
            correction = v.answer_receipt("603", "No: online only.", intent="correct", reason="Typo.",
                                           supersedes=(c.event_id(v.confirmation_receipt()), c.event_id(v.answer_receipt("602"))))
            assert rig.append(correction).result.status == "applied"
        if "replace_path" in case.inputs:
            keys = case.inputs["replace_path"].split(".")
            target = candidate
            for key in keys[:-1]:
                target = target[int(key)] if isinstance(target, list) else target[key]
            target[keys[-1]] = deepcopy(case.inputs["value"])
    if case.name == "v2_validator":
        rig.coordinator._validator = m1.VALIDATOR
    if case.name == "missing_validator":
        with pytest.raises(c.ContractRefusal) as caught:
            ClarificationCoordinator(store=db.store, transport=rig.edge, authority=rig.authority, clarified_validator=None)
        assert caught.value.guard == "coordinator.ports" and db.rows(m.ClarificationConsumption) == []
        return
    before = db.dump()
    checked = rig.check(candidate)
    assert checked.report["meaning_status"] == "NOT_EVALUATED" and checked.original_text == s.BRIEF
    assert checked.report["references_ok"] is case.expected.get("references_ok", False)
    assert db.dump() == before
    if checked.report["references_ok"]:
        assert rig.coordinator.acknowledge_consumption(rig.context(), checked=checked)
        assert len(db.rows(m.ClarificationConsumption)) == 1
    else:
        assert checked.report["errors"]
        with pytest.raises(c.ContractRefusal) as caught:
            rig.coordinator.acknowledge_consumption(rig.context(), checked=checked)
        assert caught.value.guard == "coordinator.checked_report"
        assert db.dump() == before


@pytest.mark.parametrize("case", cases("V18"), ids=lambda case: case.name)
def test_V18_current_only_consumption_and_no_automatic_effect(db, monkeypatch, case):
    rig = Composition(db, monkeypatch)
    rig.answer()
    if case.name == "moved_before_return":
        real = rig.coordinator._composed

        def moved(context):
            result = real(context)
            rig.append(case.inputs["new_answer"])
            return result

        monkeypatch.setattr(rig.coordinator, "_composed", moved)
        with pytest.raises(c.ContractRefusal) as caught:
            rig.check()
        assert caught.value.guard == "coordinator.current"
    elif case.name == "new_stale_ack":
        checked, context = rig.check(), rig.context()
        real = db.store.mark_current_consumed

        def moved(stream, **kwargs):
            rig.append(case.inputs["new_answer"])
            return real(stream, **kwargs)

        monkeypatch.setattr(db.store, "mark_current_consumed", moved)
        with pytest.raises(c.ContractRefusal) as caught:
            rig.coordinator.acknowledge_consumption(context, checked=checked)
        assert caught.value.code == c.RefusalCode.REVISION_CONFLICT
    elif case.name == "kept_ack_after_move":
        checked, context = rig.check(), rig.context()
        assert rig.coordinator.acknowledge_consumption(context, checked=checked)
        rig.append(v.answer_receipt())
        monkeypatch.setattr(adapter, "prepare", lambda *_: pytest.fail("saved acknowledgement revalidated candidate"))
        assert rig.coordinator.acknowledge_consumption(context, checked=checked) is False
        return
    elif case.name == "paused_off_cancelled":
        checked = rig.check()
        rig.authority.denied.update(case.inputs["denied"])
        before = db.dump()
        for _state in case.inputs["caller_states"]:
            with pytest.raises(PermissionError):
                rig.coordinator.acknowledge_consumption(rig.context(), checked=checked)
            assert rig.coordinator.recover(rig.initial).meaning_status == "NOT_EVALUATED"
        assert db.dump() == before and len(rig.provider.sent) == 2
    elif case.name == "unrelated_unknown":
        checked = rig.check()
        assert checked.report["references_ok"] is True and checked.report["unresolved_questions"]
        assert rig.coordinator.acknowledge_consumption(rig.context(), checked=checked)
        return
    else:
        candidate = deepcopy(rig.data["candidate"])
        candidate["constraints"][0]["source"]["event_ids"] = [v.NO_EVENT]
        checked = rig.check(candidate)
        assert checked.report["references_ok"] is False
        checked.report["references_ok"] = True
        with pytest.raises(c.ContractRefusal) as caught:
            rig.coordinator.acknowledge_consumption(rig.context(), checked=checked)
        assert caught.value.guard == "coordinator.checked_report"
    assert db.rows(m.ClarificationConsumption) == []
    assert rig.ordinary == [] and not rig.poller.running


@pytest.mark.parametrize("case", cases("V20"), ids=lambda case: case.name)
def test_V20_explicit_binding_stays_operationally_off(db, monkeypatch, case):
    before = db.dump()
    rig = Composition(db, monkeypatch)
    assert rig.effects == [] and rig.authority.calls == [] and rig.ordinary == []
    assert db.dump() == before and not rig.poller.running
    if case.name == "ordinary_unbound":
        words = v.pulled_updates()[0]
        rig.provider.updates = [words]
        ordinary = poller.Poller(rig.provider, rig.ordinary.append, timeout=0, clock=lambda: 1700000001)
        assert ordinary.clarifications is None
        assert ordinary.poll_once() == 1 and rig.ordinary == [words]
        assert db.dump() == before and rig.provider.sent == []
    elif case.name == "explicit_present":
        rig.ready()
        assert len(rig.provider.sent) == 1 and rig.ordinary == []
        assert all(call["stream"] == rig.initial.stream for call in rig.authority.calls)
    elif case.name == "missing_or_denied_authority":
        with pytest.raises(c.ContractRefusal) as caught:
            ClarificationCoordinator(store=db.store, transport=rig.edge, authority=None, clarified_validator=s.clarified_validator())
        assert caught.value.guard == "coordinator.authority"
        rig.authority.denied.add("read")
        with pytest.raises(PermissionError):
            rig.coordinator.prepare(rig.initial)
        assert db.dump() == before and rig.provider.sent == []
