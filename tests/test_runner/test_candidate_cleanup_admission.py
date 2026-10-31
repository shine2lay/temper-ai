"""D7 / Architecture F1: refused cleanup must retain the waiting obligation.

Real API/deadline callers, holds and queue; T2's test-only designation/admission.
No worker or provider starts. The row fingerprint keeps fixture bodies out of
assertion diagnostics; the full persisted hold is compared, including end fields.
"""
from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from temper_ai.api import routes
from temper_ai.config.admission_contract import RESERVED_KEY
from temper_ai.database import get_session
from temper_ai.runner import cleanup_dispatch, hold_sweeper, holds, queue
from temper_ai.runner.models import WorkflowRun
from tests.test_runner.test_candidate_admission_transport import (
    EXECUTION,
    SyntheticBindings,
)
from tests.test_runner.test_parked_claim_atomic import _attempt, _hold_state, _row, at
from tests.test_runner.test_parked_claim_atomic import (
    _shared_database as _shared_database,
)
from tests.test_runner.test_workspace_hold_admission import _mutate


@pytest.fixture
def cleanup_rig(monkeypatch, tmp_path):
    """Reuse the real HTTP router; no server lifespan, worker, or workflow loading."""
    bindings = SyntheticBindings()
    state = SimpleNamespace(candidate_bindings=bindings)
    monkeypatch.setattr(routes, "_state", lambda: state)
    monkeypatch.setattr(routes, "require_caller_may", lambda *args, **kwargs: None)
    monkeypatch.setattr(routes, "record_action", lambda *args, **kwargs: None)
    monkeypatch.setenv("TEMPER_EXECUTION_MODE", "external")
    # A legacy cleanup pass gets a folder strictly inside WORKSPACE_DIR (#228, 369d1af0).
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path))
    workspace = tmp_path / "ws"
    workspace.mkdir()

    queued = []
    original_queue = queue.queue_run_in

    def count_queue(*args, **kwargs):
        result = original_queue(*args, **kwargs)
        queued.append(args[1])
        return result

    monkeypatch.setattr(queue, "queue_run_in", count_queue)
    app = FastAPI()
    app.include_router(routes.router)
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, bindings=bindings, queued=queued, workspace=str(workspace))


def _seed(rig, kind):
    _attempt(EXECUTION, status="failed", note={})
    if kind == "admitted":
        rig.bindings.submit()
        rig.bindings.dispatch()
    else:
        _row(EXECUTION, "failed", lane=None)
    with get_session() as session:
        row = session.get(WorkflowRun, EXECUTION)
        assert row is not None
        # The row/event may have an ordinary name while the hold keeps a designated
        # workflow. A protected slot must still fence after a rename, too.
        row.workflow_name = "ordinary-cleanup"
        row.workspace_path = rig.workspace
        row.status = "failed"
        if kind == "null-slot":
            row.spawner_metadata = {RESERVED_KEY: None}
        session.add(row)
    held_name = rig.bindings.descriptor["workflow_name"] if kind == "designated" else "ordinary-cleanup"
    holds.record(EXECUTION, workflow_name=held_name, workspace_path=rig.workspace,
                 inputs={}, held=[{"path": "teardown", "undoes": ["setup"]}],
                 deadline=at("11:00:00"))
    assert EXECUTION in [hold["execution_id"] for hold in holds.due()]
    return _hold_state(EXECUTION)


def _row_fingerprint():
    with get_session() as session:
        row = session.get(WorkflowRun, EXECUTION)
        assert row is not None
        wire = json.dumps(row.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(wire).hexdigest()


def _call(rig, entry):
    if entry == "api":
        return rig.client.post(f"/api/runs/{EXECUTION}/cleanup")
    assert entry == "deadline"
    hold_sweeper._sweep()
    return None


def _assert_refusal(reply, entry, code, caplog):
    if entry == "api":
        assert reply.status_code == 409
        assert reply.json() == {"detail": code}
    else:
        errors = [record.exc_info[1] for record in caplog.records if record.exc_info]
        assert len(errors) == 1
        assert isinstance(errors[0], HTTPException)
        assert (errors[0].status_code, errors[0].detail) == (409, code)


@pytest.mark.parametrize("entry", ["api", "deadline"])
def test_ordinary_cleanup_releases_once_and_queues_one_real_pass(cleanup_rig, entry):
    """Combined clean twin first: route/sweep -> durable release + actual queue."""
    rig = cleanup_rig
    before = _seed(rig, "ordinary")
    reply = _call(rig, entry)
    if reply is not None:
        assert reply.status_code == 200
        assert reply.json() == {"execution_id": EXECUTION, "status": "queued", "cleanups": ["teardown"]}
    ended = _hold_state(EXECUTION)
    assert ended["status"] == "released"
    assert ended["ended_by"] == ("give_up" if entry == "api" else "deadline")
    assert ended["ended_at"] is not None
    assert {key: value for key, value in ended.items() if key not in {"status", "ended_at", "ended_by"}} == {
        key: value for key, value in before.items() if key not in {"status", "ended_at", "ended_by"}
    }
    with get_session() as session:
        row = session.get(WorkflowRun, EXECUTION)
        assert row is not None and row.status == "queued"
        assert row.spawner_metadata["start"] == "cleanup"
        assert row.spawner_metadata["only"] == ["teardown"]
    assert rig.queued == [EXECUTION]
    assert holds.waiting(EXECUTION) is None
    assert holds.due() == []
    committed = _row_fingerprint()
    if entry == "api":
        assert _call(rig, entry).status_code == 409
    else:
        _call(rig, entry)
    assert rig.queued == [EXECUTION]
    assert _hold_state(EXECUTION) == ended
    assert _row_fingerprint() == committed


@pytest.mark.parametrize("entry", ["api", "deadline"])
@pytest.mark.parametrize("kind,code", [
    ("admitted", "unsupported_mode"),
    ("null-slot", "unsupported_mode"),
    ("designated", "admission_required"),
])
def test_candidate_refusal_preserves_the_entire_waiting_hold(cleanup_rig, entry, kind, code, caplog):
    rig = cleanup_rig
    before = _seed(rig, kind)
    run_before = _row_fingerprint()
    caplog.clear()
    reply = _call(rig, entry)
    _assert_refusal(reply, entry, code, caplog)
    assert rig.queued == []
    assert _row_fingerprint() == run_before
    assert _hold_state(EXECUTION) == before, "F1-REFUSED-HOLD"
    assert holds.waiting(EXECUTION) is not None
    assert EXECUTION in [hold["execution_id"] for hold in holds.due()]
    # A refused deadline remains eligible for a later sweep, with its deadline intact.
    if entry == "deadline":
        caplog.clear()
        _call(rig, entry)
        _assert_refusal(None, entry, code, caplog)
        assert rig.queued == []
        assert _hold_state(EXECUTION) == before
        assert _row_fingerprint() == run_before


def _designate_the_ordinary_workflow(rig, monkeypatch):
    monkeypatch.setattr(rig.bindings, "designated", lambda name: name == "ordinary-cleanup")


def _protect_the_row():
    with get_session() as session:
        row = session.get(WorkflowRun, EXECUTION)
        assert row is not None
        row.spawner_metadata = {RESERVED_KEY: None}
        session.add(row)


@pytest.mark.parametrize("entry", ["api", "deadline"])
@pytest.mark.parametrize("change,moment,code", [
    ("row", "seam-entry", "unsupported_mode"),
    ("designation", "seam-entry", "admission_required"),
    ("designation", "after-hold-end", "admission_required"),
])
def test_late_candidate_change_before_cleanup_queue_keeps_the_hold(
    cleanup_rig, monkeypatch, entry, change, moment, code, caplog,
):
    """Controlled interleavings after every early route guard: at the release seam's
    entry, and inside its transaction once the hold is ended. Not concurrent
    registry-revocation proof. (A row write after the hold end would wait on SQLite's
    writer lock, so the row change is placed at the seam's entry only.)"""
    rig = cleanup_rig
    before = _seed(rig, "ordinary")
    changed = []

    def apply_change():
        if change == "row":
            _protect_the_row()
        else:
            _designate_the_ordinary_workflow(rig, monkeypatch)
        changed.append(_row_fingerprint())

    if moment == "seam-entry":
        release = cleanup_dispatch.queue_held_cleanups

        def change_then_release(*args, **kwargs):
            apply_change()
            return release(*args, **kwargs)

        monkeypatch.setattr(cleanup_dispatch, "queue_held_cleanups", change_then_release)
    else:
        end_in = holds.end_in

        def end_then_change(*args, **kwargs):
            ended = end_in(*args, **kwargs)
            apply_change()
            return ended

        monkeypatch.setattr(holds, "end_in", end_then_change)
    caplog.clear()
    reply = _call(rig, entry)
    _assert_refusal(reply, entry, code, caplog)
    assert len(changed) == 1
    assert rig.queued == []
    assert _row_fingerprint() == changed[0]
    assert _hold_state(EXECUTION) == before, "F1-LATE-REFUSAL-HOLD"
    assert holds.waiting(EXECUTION) is not None
    assert EXECUTION in [hold["execution_id"] for hold in holds.due()]


@pytest.mark.parametrize("entry", ["api", "deadline"])
def test_the_in_transaction_designation_check_has_a_bite(cleanup_rig, monkeypatch, entry, caplog):
    """Drop the held-workflow check from the release seam: a designated hold is released."""
    _mutate(monkeypatch, cleanup_dispatch, "queue_held_cleanups", "refuse_held(ended)", "None")
    with pytest.raises(AssertionError):
        test_candidate_refusal_preserves_the_entire_waiting_hold(
            cleanup_rig, entry, "designated", "admission_required", caplog)
    assert _hold_state(EXECUTION)["status"] == "released" and cleanup_rig.queued == [EXECUTION]


def test_the_refusal_code_mapping_has_a_bite(cleanup_rig, monkeypatch, caplog):
    """Without the 409 mapping a late row refusal is no refusal the deadline can report."""
    _mutate(monkeypatch, routes, "_queue_refusals_as_http",
            "    except AdmissionRefused as exc:\n"
            "        raise HTTPException(status_code=409, detail=exc.code.value) from None\n", "")
    with pytest.raises(AssertionError, match="isinstance"):
        test_late_candidate_change_before_cleanup_queue_keeps_the_hold(
            cleanup_rig, monkeypatch, "deadline", "row", "seam-entry", "unsupported_mode", caplog)


# D9: an in-process server (the default mode) ends the wait and queues nothing, so the
# queueing seam above never sees its release. The same in-transaction check must hold there.


@pytest.fixture
def inprocess_rig(cleanup_rig, monkeypatch):
    monkeypatch.setenv("TEMPER_EXECUTION_MODE", "inprocess")
    monkeypatch.delenv("TEMPER_LANE", raising=False)
    return cleanup_rig


@pytest.mark.parametrize("entry", ["api", "deadline"])
def test_inprocess_ordinary_cleanup_releases_and_queues_nothing(inprocess_rig, entry):
    """Clean twin first: an ordinary in-process wait is released as before, nothing queued."""
    rig = inprocess_rig
    before = _seed(rig, "ordinary")
    run_before = _row_fingerprint()
    reply = _call(rig, entry)
    if reply is not None:
        assert reply.status_code == 200
        assert reply.json() == {"execution_id": EXECUTION, "status": "queued", "cleanups": ["teardown"]}
    ended = _hold_state(EXECUTION)
    assert ended["status"] == "released"
    assert ended["ended_by"] == ("give_up" if entry == "api" else "deadline")
    assert ended["ended_at"] is not None
    assert {key: value for key, value in ended.items() if key not in {"status", "ended_at", "ended_by"}} == {
        key: value for key, value in before.items() if key not in {"status", "ended_at", "ended_by"}
    }
    assert rig.queued == []
    assert _row_fingerprint() == run_before
    assert holds.waiting(EXECUTION) is None
    assert holds.due() == []


@pytest.mark.parametrize("entry", ["api", "deadline"])
@pytest.mark.parametrize("kind,code", [
    ("admitted", "unsupported_mode"),
    ("null-slot", "unsupported_mode"),
    ("designated", "admission_required"),
])
def test_inprocess_candidate_refusal_preserves_the_entire_waiting_hold(
    inprocess_rig, entry, kind, code, caplog,
):
    test_candidate_refusal_preserves_the_entire_waiting_hold(inprocess_rig, entry, kind, code, caplog)


@pytest.mark.parametrize("entry", ["api", "deadline"])
def test_inprocess_late_designation_after_the_hold_end_keeps_the_hold(
    inprocess_rig, monkeypatch, entry, caplog,
):
    """Designation lands after the hold is ended inside the transaction: an early read of
    the hold would miss it; the in-transaction check refuses and rolls the end back."""
    test_late_candidate_change_before_cleanup_queue_keeps_the_hold(
        inprocess_rig, monkeypatch, entry, "designation", "after-hold-end", "admission_required", caplog)


@pytest.mark.parametrize("entry", ["api", "deadline"])
def test_the_inprocess_designation_check_has_a_bite(inprocess_rig, monkeypatch, entry, caplog):
    """Drop the held-workflow check from the in-process release: a designated hold is released."""
    _mutate(monkeypatch, cleanup_dispatch, "release_held_cleanups", "refuse_held(ended)", "None")
    with pytest.raises(AssertionError):
        test_candidate_refusal_preserves_the_entire_waiting_hold(
            inprocess_rig, entry, "designated", "admission_required", caplog)
    assert _hold_state(EXECUTION)["status"] == "released" and inprocess_rig.queued == []

