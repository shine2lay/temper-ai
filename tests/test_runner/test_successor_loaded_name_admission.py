"""M1 REF-NAME-TAKEOVER: a fork or resume is refused under the name its workflow loads as,
before its source's held clean-ups are ended.

The request names a workflow; the loader reads the store key (a folder part is dropped:
"team/W" reads "W"), and Studio stores any config under any key. The successor is queued and
run under the loaded config's own name, which the worker and the run thread check. A fence
on the request's name alone let a fork or resume end the source's hold as "taken_over" for a
successor that was refused later: the held clean-ups were lost.

Real router, Studio router, ConfigStore and loader (the name a config loads as) on a fresh
test database, with T2's test-only SyntheticBindings designation; FWS-HOLD-1's seeds and
parked-claim readers. No box, workflow thread, provider or model starts.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from temper_ai.api import routes, studio
from temper_ai.config import ConfigStore
from temper_ai.database import get_database
from temper_ai.runner import cleanup_dispatch, holds, parked
from temper_ai.stage.loader import GraphLoader
from tests.test_runner.test_candidate_admission_transport import SyntheticBindings
from tests.test_runner.test_parked_claim_atomic import (
    _attempt,
    _hold,
    _hold_state,
    _row,
    _state,
)
from tests.test_runner.test_parked_claim_atomic import (
    _shared_database as _shared_database,
)
from tests.test_runner.test_parked_claim_atomic import resume_rig as resume_rig
from tests.test_runner.test_workspace_hold_admission import _mutate, _queued, _seed

WORKSPACE = "/workspaces/ws"
ORDINARY = "ordinary-loaded"
REFUSED = (409, {"detail": "admission_required"})
FORK_LANES = ("pi", "plain", "inprocess")
RESUME_LANES = ("pi", "pi-parked", "plain", "inprocess")


@pytest.fixture
def rig(resume_rig, monkeypatch):
    """The parked-claim route rig with a real store and loader for the loaded name; the
    rig's own nodes keep choosing the lane (a Pi step or none)."""
    bindings = SyntheticBindings()
    store = ConfigStore()
    real_loader = GraphLoader(store)

    def load_workflow(ref, *args, **kwargs):
        _nodes, config = real_loader.load_workflow(ref, *args, **kwargs)
        return resume_rig.nodes, config

    resume_rig.state.candidate_bindings = bindings
    resume_rig.state.config_store = store
    resume_rig.state.graph_loader = SimpleNamespace(load_workflow=load_workflow)
    resume_rig.threads = []

    class RecordedThread:
        def __init__(self, *, args, **kwargs):
            self.run = args[4]

        def start(self):
            resume_rig.threads.append(self.run)  # No target called: nothing runs.

    monkeypatch.setattr(routes, "threading", SimpleNamespace(Thread=RecordedThread))
    for module in (routes, studio):
        monkeypatch.setattr(module, "require_caller_may", lambda *args, **kwargs: None)
    monkeypatch.setattr(routes, "record_action", lambda *args, **kwargs: None)
    app = FastAPI()
    app.include_router(routes.router)
    app.include_router(studio.router)
    with TestClient(app) as client:
        resume_rig.client = client
        resume_rig.designated = bindings.descriptor["workflow_name"]
        resume_rig.bindings = bindings
        yield resume_rig


def _lane(rig, monkeypatch, lane):
    if lane in ("plain", "inprocess"):
        rig.nodes.clear()
        monkeypatch.delenv("TEMPER_LANE", raising=False)
    if lane == "inprocess":
        monkeypatch.setenv("TEMPER_EXECUTION_MODE", "inprocess")


def _store_config(rig, shape, inner):
    """Write the config through Studio (a supported writer) and return the name a request
    gives for it: a folder part over the config's own key, or a Studio key of another name."""
    key = {"folder": inner, "studio-key": "studio-renamed", "recorded": "wf"}[shape]
    reply = rig.client.post(f"/api/studio/configs/workflow/{key}",
                            json={"config": {"workflow": {"name": inner, "nodes": []}}})
    assert reply.status_code == 201, reply.text
    return {"folder": f"team/{inner}", "studio-key": key, "recorded": None}[shape]


def _seed_source(run, lane):
    if lane == "pi-parked":
        _attempt(run)
        _row(run, "orphaned", handle="old-box")
        _hold(run)
        return None
    return _seed(run, WORKSPACE, pi=lane == "pi")


def _fork(rig, run, ref, sequence):
    return rig.client.post("/api/runs/fork", json={"workflow": ref, "source_execution_id": run,
                                                   "sequence": sequence, "workspace_path": WORKSPACE})


def _resume(rig, run, ref):
    body = {"workspace_path": WORKSPACE} | ({"workflow": ref} if ref is not None else {})
    return rig.client.post(f"/api/runs/{run}/resume", json=body)


def _queued_view():
    return sorted((row["execution_id"], row["workflow_name"],
                   (row["spawner_metadata"] or {}).get("start")) for row in _queued())


def _fork_metadata(run):
    with get_database().engine.connect() as conn:
        rows = conn.execute(text("select data from events where type = 'fork.metadata'")).all()
    data = [json.loads(row[0]) if isinstance(row[0], str) else row[0] for row in rows]
    return [item for item in data if item["source_execution_id"] == run]


def _before(run):
    return SimpleNamespace(hold=_hold_state(run), row=_state(run), queued=_queued_view(),
                           metadata=_fork_metadata(run))


def _assert_refused_with_the_hold_kept(rig, reply, run, before, *, queued=None):
    """The refusal comes before the source's hold is ended: every hold field is as it was."""
    assert _hold_state(run) == before.hold, "M1-HOLD-KEPT"
    assert (reply.status_code, reply.json()) == REFUSED, "M1-STATUS"
    assert holds.waiting(run) is not None
    assert _queued_view() == (before.queued if queued is None else queued), "M1-NOTHING-QUEUED"
    assert rig.took == [] and rig.threads == [], "M1-NO-TAKEOVER-OR-START"
    assert _fork_metadata(run) == before.metadata, "M1-NO-FORK-METADATA"


@pytest.mark.parametrize("shape", ["folder", "studio-key"])
@pytest.mark.parametrize("lane", FORK_LANES)
def test_a_fork_of_a_designated_config_under_another_name_keeps_the_hold(
        rig, monkeypatch, lane, shape):
    _lane(rig, monkeypatch, lane)
    run = f"m1-fork-{lane}-{shape}"
    sequence = _seed_source(run, lane)
    ref = _store_config(rig, shape, rig.designated)
    assert not rig.bindings.designated(ref), "the request's own name is not designated"
    before = _before(run)
    reply = _fork(rig, run, ref, sequence)
    _assert_refused_with_the_hold_kept(rig, reply, run, before)
    assert _state(run) == before.row


@pytest.mark.parametrize("shape", ["folder", "studio-key", "recorded"])
@pytest.mark.parametrize("lane", RESUME_LANES)
def test_a_resume_of_a_designated_config_under_another_name_keeps_the_hold(
        rig, monkeypatch, lane, shape):
    _lane(rig, monkeypatch, lane)
    run = f"m1-resume-{lane}-{shape}"
    _seed_source(run, lane)
    ref = _store_config(rig, shape, rig.designated)
    assert not rig.bindings.designated(ref or "wf"), "the request's own name is not designated"
    before = _before(run)
    reply = _resume(rig, run, ref)
    _assert_refused_with_the_hold_kept(rig, reply, run, before)
    assert _state(run) == before.row, "M1-NO-CLAIM-OR-QUEUE"


@pytest.mark.parametrize("shape", ["folder", "studio-key"])
@pytest.mark.parametrize("lane", FORK_LANES)
def test_an_ordinary_fork_under_another_name_takes_the_hold_over_as_before(
        rig, monkeypatch, lane, shape):
    _lane(rig, monkeypatch, lane)
    run = f"m1-fork-twin-{lane}-{shape}"
    sequence = _seed_source(run, lane)
    ref = _store_config(rig, shape, ORDINARY)
    before = _before(run)
    reply = _fork(rig, run, ref, sequence)
    assert reply.status_code == 200, "M1-TWIN-STATUS"
    fork = reply.json()["execution_id"]
    hold = _hold_state(run)
    assert (hold["status"], hold["ended_by"]) == ("taken_over", fork), "M1-TWIN-HOLD"
    assert hold["deadline"] == before.hold["deadline"]
    if lane == "inprocess":
        assert reply.json()["status"] == "running" and rig.threads == [fork]
        assert _queued_view() == before.queued
    else:
        assert _queued_view() == sorted([*before.queued, (fork, ORDINARY, "fork")]), "M1-TWIN-QUEUED"
    assert len(_fork_metadata(run)) == len(before.metadata) + 1


@pytest.mark.parametrize("shape", ["folder", "studio-key", "recorded"])
@pytest.mark.parametrize("lane", RESUME_LANES)
def test_an_ordinary_resume_under_another_name_takes_the_hold_over_as_before(
        rig, monkeypatch, lane, shape):
    _lane(rig, monkeypatch, lane)
    run = f"m1-resume-twin-{lane}-{shape}"
    _seed_source(run, lane)
    ref = _store_config(rig, shape, ORDINARY)
    before = _before(run)
    reply = _resume(rig, run, ref)
    assert reply.status_code == 200, "M1-TWIN-STATUS"
    hold = _hold_state(run)
    assert (hold["status"], hold["ended_by"]) == ("taken_over", run), "M1-TWIN-HOLD"
    assert [eid for eid, _seen in rig.took] == [run]
    if lane == "inprocess":
        assert reply.json()["status"] == "resuming" and rig.threads == [run]
        assert _queued_view() == before.queued
    else:
        assert reply.json()["status"] == "queued"
        assert _queued_view() == sorted([*before.queued, (run, ORDINARY, "resume")]), "M1-TWIN-QUEUED"


# Windows: the ordinary config becomes designated after the loaded-name check and before the
# hold is ended. Process state, not a database lock, decides designation, so these are
# controlled interleavings on one thread, not concurrent registry-revocation proof.


def _designate_ordinary_when(rig, monkeypatch, module, name, *, after=False):
    real = getattr(module, name)
    landed = []

    def designate_then_call(*args, **kwargs):
        if not after:
            landed.append(name)
            monkeypatch.setattr(rig.bindings, "designated", lambda workflow: workflow == ORDINARY)
        result = real(*args, **kwargs)
        if after:
            landed.append(name)
            monkeypatch.setattr(rig.bindings, "designated", lambda workflow: workflow == ORDINARY)
        return result

    monkeypatch.setattr(module, name, designate_then_call)
    return landed


FORK_WINDOWS = {
    # Before the fork's hold-then-queue transaction opens, and inside it once the hold ended.
    "pi-before-transaction": ("pi", routes, "_record_fork_metadata", False),
    "plain-after-hold-end": ("plain", holds, "end_in", True),
    "inprocess-before-takeover": ("inprocess", routes, "_refuse_unboxed", False),
}


@pytest.mark.parametrize("window", FORK_WINDOWS)
def test_a_designation_landing_in_the_forks_window_keeps_the_hold(rig, monkeypatch, window):
    lane, module, name, after = FORK_WINDOWS[window]
    _lane(rig, monkeypatch, lane)
    run = f"m1-fork-window-{window}"
    sequence = _seed_source(run, lane)
    ref = _store_config(rig, "studio-key", ORDINARY)
    before = _before(run)
    landed = _designate_ordinary_when(rig, monkeypatch, module, name, after=after)
    reply = _fork(rig, run, ref, sequence)
    assert landed == [name], "M1-WINDOW-REACHED"
    expected_metadata = len(before.metadata) + (lane != "inprocess")
    assert _hold_state(run) == before.hold, "M1-HOLD-KEPT"
    assert (reply.status_code, reply.json()) == REFUSED, "M1-STATUS"
    assert _queued_view() == before.queued, "M1-NOTHING-QUEUED"
    assert rig.took == [] and rig.threads == [], "M1-NO-TAKEOVER-OR-START"
    # The queued branch records its metadata before the transaction (P3, pre-existing).
    assert len(_fork_metadata(run)) == expected_metadata


RESUME_WINDOWS = {
    # Resumes commit their queue before their own-commit takeover (#375 LATE-TAKEOVER shape):
    # the refused successor's row stays queued for the worker, which refuses it by the same
    # designation; the hold is kept.
    "pi-after-queue": ("pi", routes, "_queue_run", True),
    "plain-after-queue": ("plain", routes, "_queue_run", True),
    "pi-parked-after-claim": ("pi-parked", parked, "claim_and_queue", True),
    "inprocess-before-claim": ("inprocess", routes, "_refuse_unboxed", False),
}


@pytest.mark.parametrize("window", RESUME_WINDOWS)
def test_a_designation_landing_in_the_resumes_window_keeps_the_hold(rig, monkeypatch, window):
    lane, module, name, after = RESUME_WINDOWS[window]
    _lane(rig, monkeypatch, lane)
    run = f"m1-resume-window-{window}"
    _seed_source(run, lane)
    ref = _store_config(rig, "studio-key", ORDINARY)
    before = _before(run)
    landed = _designate_ordinary_when(rig, monkeypatch, module, name, after=after)
    reply = _resume(rig, run, ref)
    assert landed == [name], "M1-WINDOW-REACHED"
    queued = (before.queued if lane == "inprocess"
              else sorted([*before.queued, (run, ORDINARY, "resume")]))
    _assert_refused_with_the_hold_kept(rig, reply, run, before, queued=queued)


# Bites: each guard dropped alone fails its own control.

FORK_LOADED_NAME = ("        raise HTTPException(status_code=400, detail=str(exc)) from exc\n"
                    "    _refuse_designated_successor(config)\n"
                    "\n    # Each declared default")
RESUME_LOADED_NAME = ("        raise HTTPException(status_code=400, detail=str(exc)) from exc\n"
                      "    _refuse_designated_successor(config)\n"
                      "\n    pi_run = is_pi_workflow(nodes)")


def _drop(monkeypatch, module, function, guarded):
    """Remove the guard's line from ``guarded`` (its neighbour lines locate it uniquely).
    The mutant reads the live module, so a window's later monkeypatch still reaches it."""
    _mutate(monkeypatch, module, function, guarded, "".join(
        line for line in guarded.splitlines(keepends=True)
        if "_refuse_designated_successor(config)" not in line), live_globals=True)


def test_dropping_every_loaded_name_refusal_loses_the_hold(rig, monkeypatch):
    """The mutant the fix answers: with no loaded-name refusal a designated fork ends the
    source's hold as taken over for a successor that only the worker refuses later."""
    monkeypatch.setattr(routes, "_refuse_designated_successor", lambda config: None)
    with pytest.raises(AssertionError, match="M1-HOLD-KEPT"):
        test_a_fork_of_a_designated_config_under_another_name_keeps_the_hold(
            rig, monkeypatch, "pi", "folder")
    assert _hold_state("m1-fork-pi-folder")["status"] == "taken_over"


def test_dropping_every_loaded_name_refusal_loses_a_resumes_hold(rig, monkeypatch):
    monkeypatch.setattr(routes, "_refuse_designated_successor", lambda config: None)
    with pytest.raises(AssertionError, match="M1-HOLD-KEPT"):
        test_a_resume_of_a_designated_config_under_another_name_keeps_the_hold(
            rig, monkeypatch, "plain", "studio-key")
    assert _hold_state("m1-resume-plain-studio-key")["status"] == "taken_over"


def test_the_forks_loaded_name_check_has_a_bite(rig, monkeypatch):
    """Without it the in-transaction refusal still keeps the hold, but the refused fork has
    recorded its fork metadata first."""
    _drop(monkeypatch, routes, "_fork_run", FORK_LOADED_NAME)
    with pytest.raises(AssertionError, match="M1-NO-FORK-METADATA"):
        test_a_fork_of_a_designated_config_under_another_name_keeps_the_hold(
            rig, monkeypatch, "pi", "folder")


def test_the_resumes_loaded_name_check_has_a_bite(rig, monkeypatch):
    """Without it the takeover check still keeps the hold, but the refused resume has queued."""
    _drop(monkeypatch, routes, "_resume_run", RESUME_LOADED_NAME)
    with pytest.raises(AssertionError, match="M1-NOTHING-QUEUED"):
        test_a_resume_of_a_designated_config_under_another_name_keeps_the_hold(
            rig, monkeypatch, "plain", "folder")


def test_the_in_transaction_fork_refusal_has_a_bite(rig, monkeypatch):
    _mutate(monkeypatch, cleanup_dispatch, "queue_fork_taking_over",
            "            refuse_successor()\n", "            pass\n")
    with pytest.raises(AssertionError, match="M1-HOLD-KEPT"):
        test_a_designation_landing_in_the_forks_window_keeps_the_hold(
            rig, monkeypatch, "plain-after-hold-end")


def test_the_in_process_fork_takeover_check_has_a_bite(rig, monkeypatch):
    _drop(monkeypatch, routes, "_fork_run",
          "    _refuse_designated_successor(config)\n"
          "    holds.take_over(body.source_execution_id, by=new_execution_id)\n")
    with pytest.raises(AssertionError, match="M1-HOLD-KEPT"):
        test_a_designation_landing_in_the_forks_window_keeps_the_hold(
            rig, monkeypatch, "inprocess-before-takeover")


@pytest.mark.parametrize("window,function,guarded", [
    ("plain-after-queue", "_resume_run",
     "        _refuse_designated_successor(config)\n"
     "        holds.take_over(execution_id, by=execution_id)\n    return response"),
    ("pi-parked-after-claim", "_start_resume",
     "            _refuse_designated_successor(config)\n"
     "            holds.take_over(execution_id, by=execution_id)\n"
     "        return RunResponse"),
    ("inprocess-before-claim", "_start_resume",
     "    _refuse_designated_successor(config)\n"
     "    if parked_attempt is not None:\n        try:\n            won"),
])
def test_each_resume_takeover_check_has_a_bite(rig, monkeypatch, window, function, guarded):
    _drop(monkeypatch, routes, function, guarded)
    with pytest.raises(AssertionError, match="M1-HOLD-KEPT"):
        test_a_designation_landing_in_the_resumes_window_keeps_the_hold(rig, monkeypatch, window)
