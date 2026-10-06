"""SW-86's refused ATTEMPT envelope: real entry points, no model or service.

Stage-door proofs are in test_stop_starts_nothing.py. These prove earlier admission:
no full bootstrap, registration, tools/MCP, terminal writer, hold transfer, wait,
viewer cleanup or automatic retry when authority is unknown. Both database tiers.
"""

from __future__ import annotations

import argparse
import os
from collections import Counter
from contextlib import contextmanager
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlmodel import select

from temper_ai.checkpoint.models import Checkpoint
from temper_ai.checkpoint.service import CheckpointService
from temper_ai.database import get_session
from temper_ai.observability.models import Event
from temper_ai.runner import resume_authority as admission
from temper_ai.runner.models import CleanupHold, ResumeClaim, WorkflowRun
from temper_ai.runner.queue import queue_run
from temper_ai.shared.clock import utcnow
from temper_ai.spawner.reaper import CLAIMING, Reaper
from temper_ai.worker_proto import SpawnerKind
from tests.test_runner.resume_support import install_launch_token


@pytest.fixture(params=["sqlite", "database_tier"])
def _envelope_backend(request, monkeypatch):
    if request.param == "sqlite":
        monkeypatch.delenv("TEMPER_TEST_DATABASE_URL", raising=False)
    return request.param


@pytest.fixture(autouse=True)
def _test_db(_envelope_backend, _test_db, request):
    from tests.conftest import TEST_DATABASE_URL

    url = request.node.stash[TEST_DATABASE_URL]
    expected = "postgresql" if _envelope_backend == "database_tier" and os.getenv(
        "TEMPER_TEST_DATABASE_URL") else "sqlite"
    assert url.startswith(expected)
    yield


@pytest.fixture
def saved(pw_run):
    """Canonical payload is deliberately richer than event totals: never reconstruct it."""
    eid = f"sw86-envelope-{uuid4().hex}"
    start = utcnow() - timedelta(minutes=2)
    with get_session() as session:
        session.add(Event(id=f"original-{eid}", execution_id=eid, type="workflow.started",
                          status="failed", timestamp=start,
                          data={"workflow_name": "plain_fails_first", "error": "fixture failure",
                                "cost_usd": 9.125, "total_tokens": 57}))
        session.add(WorkflowRun(
            execution_id=eid, workflow_name="plain_fails_first", workspace_path=str(pw_run.ws),
            inputs={"original": [1, {"value": "retained"}]}, status="failed",
            created_at=start - timedelta(seconds=1), started_at=start,
            completed_at=start + timedelta(seconds=1),
            result={"cost_usd": 9.125, "total_tokens": 57, "output": {"kept": ["original"]}},
            error={"message": "fixture failure", "kind": "fixture"},
            spawner_metadata={"original": "kept", "box_profile": {"history": [{"generation": 1}]}}))
        session.add(CleanupHold(execution_id=eid, workflow_name="plain_fails_first",
                               workspace_path=str(pw_run.ws), node_paths=[{"path": "cleanup", "label": "cleanup"}],
                               deadline=utcnow() + timedelta(hours=1)))
    return SimpleNamespace(eid=eid, original=projection(eid), pw=pw_run)


def projection(eid):
    with get_session() as session:
        row = session.get(WorkflowRun, eid)
        result = admission.capture_projection(row)
        result["metadata"] = deepcopy(row.spawner_metadata)
        return result


def canonical(proj):
    return {k: v for k, v in proj.items() if k != "metadata"}


def update_row(eid, **values):
    with get_session() as session:
        row = session.get(WorkflowRun, eid)
        for key, value in values.items():
            setattr(row, key, value)
        session.add(row)


def token(eid):
    return admission.reservation(projection(eid)["metadata"])["token"]


def enqueue(saved, *, lane=None):
    queue_run(saved.eid, "plain_fails_first", str(saved.pw.ws), {"new": "inputs"},
              start="resume", extra={"rerun": ["plain_first"]}, lane=lane)
    assert projection(saved.eid)["status"] == "queued"
    return token(saved.eid)


def original_event(eid):
    with get_session() as session:
        e = session.get(Event, f"original-{eid}")
        return e.status, deepcopy(e.data)


def action_rows(eid):
    with get_session() as session:
        return [deepcopy(e.data) for e in session.exec(select(Event).where(
            Event.execution_id == eid, Event.type == "caller.action")).all()]


def assert_preserved(saved):
    assert canonical(projection(saved.eid)) == canonical(saved.original)
    assert original_event(saved.eid)[0] == saved.original["status"]
    with get_session() as session:
        assert session.get(CleanupHold, saved.eid).status == "waiting"
        assert len(session.exec(select(Event).where(
            Event.execution_id == saved.eid, Event.type == "workflow.started")).all()) == 1


def break_checkpoint(monkeypatch):
    def unreadable(*_args, **_kwargs):
        raise OSError("fixture authority fault")
    monkeypatch.setattr(CheckpointService, "resume_snapshot", unreadable)


@pytest.fixture
def forbidden(monkeypatch, pw_run):
    """Count ATTEMPTS even when the attempted operation raises or gets swallowed."""
    from temper_ai.api import routes
    from temper_ai.cli import run_workflow
    from temper_ai.observability.composite_notifier import CompositeNotifier
    from temper_ai.runner import bootstrap, execute, holds

    calls = Counter()

    class NoRegistration(dict):
        def __setitem__(self, key, value):
            calls["runtime_registration"] += 1
            raise AssertionError("forbidden runtime registration")

    monkeypatch.setattr(pw_run.state, "running", NoRegistration(pw_run.state.running))

    def no(name):
        def forbidden_call(*_args, **_kwargs):
            calls[name] += 1
            raise AssertionError(f"forbidden envelope attempt: {name}")
        return forbidden_call

    monkeypatch.setattr(bootstrap, "bootstrap_runner_context_from_env", no("full_bootstrap"))
    monkeypatch.setattr(execute, "ToolExecutor", no("tools"))
    monkeypatch.setattr(execute, "preconnect_mcp_servers", no("preconnect"))
    monkeypatch.setattr(pw_run.state.graph_loader, "load_workflow", no("load_workflow"))
    monkeypatch.setattr(holds, "take_over", no("hold_takeover"))
    monkeypatch.setattr(run_workflow, "_safe_mark_failed", no("mark_failed"))
    monkeypatch.setattr(run_workflow, "_update_run_row", no("terminal_writer"))
    monkeypatch.setattr(run_workflow, "_start_mcp_manager", no("mcp_start"))
    monkeypatch.setattr(routes, "_see_to_parked", no("see_to_parked"))
    monkeypatch.setattr(routes.ws_manager, "cleanup", no("viewer_cleanup"))
    monkeypatch.setattr(CompositeNotifier, "cleanup", no("terminal_sentinel"))
    from temper_ai.spawner import box_guard, box_view
    monkeypatch.setattr(box_view, "check_box", lambda: None)
    monkeypatch.setattr(box_guard, "activate", lambda _doc: None)
    monkeypatch.delenv(admission.RESERVATION_ENV, raising=False)
    monkeypatch.delenv("TEMPER_RUN_CONTAINER", raising=False)
    return calls


def call_runner(saved, **kwargs):
    from temper_ai.runner.context import RunnerContext
    from temper_ai.runner.execute import execute_workflow
    return execute_workflow(execution_id=saved.eid, workflow_name="plain_fails_first",
                            workspace_path=str(saved.pw.ws), inputs={},
                            runner_ctx=RunnerContext(config_store=saved.pw.state.config_store,
                                                     graph_loader=saved.pw.state.graph_loader,
                                                     llm_providers=saved.pw.state.llm_providers,
                                                     memory_service=saved.pw.state.memory_service),
                            initial_outputs={}, **kwargs)


def call_cli(eid):
    from temper_ai.cli.run_workflow import cmd_run_workflow
    return cmd_run_workflow(argparse.Namespace(execution_id=eid, config_dir=None))


@pytest.mark.parametrize("entry", ["api", "queue"])
def test_checkpoint_without_original_records_refuses_missing_projection_and_starts_nothing(
        pw_run, forbidden, monkeypatch, entry):
    """A viewer and a saved node aren't the missing original run's authority."""
    from fastapi import HTTPException

    from temper_ai.api import routes
    from temper_ai.shared.types import NodeResult, Status

    eid = f"sw86-no-original-{uuid4().hex}"
    cp = CheckpointService(eid)
    cp.save_node_completed("plain_first", NodeResult(status=Status.COMPLETED, output="fixture"))
    before = cp.resume_snapshot()
    monkeypatch.setenv("TEMPER_EXECUTION_MODE", "external")
    monkeypatch.setattr(routes, "get_workflow_execution", lambda _eid: {
        "workflow_name": "plain_fails_first", "status": "interrupted",
        "input_data": {}, "workspace_path": str(pw_run.ws),
    })
    # Pure configuration reads are permitted; all runtime/producer tripwires stay armed.
    loader = pw_run.state.graph_loader
    monkeypatch.setattr(loader, "load_workflow", type(loader).load_workflow.__get__(loader))
    if entry == "api":
        with pytest.raises(HTTPException) as refused:
            routes.resume_run(eid)
        assert refused.value.status_code == 503
        assert refused.value.detail == "Resume attempt refused: resume_original_projection_missing"
    else:
        with pytest.raises(admission.ResumeAuthorityUnreadable) as refused:
            queue_run(eid, "plain_fails_first", str(pw_run.ws), {}, start="resume")
        assert refused.value.code == "resume_original_projection_missing"
    assert cp.resume_snapshot() == before
    with get_session() as session:
        assert session.get(WorkflowRun, eid) is None
        rows = session.exec(select(Event).where(Event.execution_id == eid)).all()
        assert rows and all(row.type == "caller.action" and row.status is None for row in rows)
    assert admission.automatic_resume_refused(eid)
    assert pw_run.state.running == {}
    assert forbidden == Counter()
    # Quarantine belongs to the observed (even empty) original-attempt/claim identity,
    # not a later real Start. No diagnostic may pin that newer owner.
    from tests.test_runner.resume_support import seed_legacy_interrupted_run

    seed_legacy_interrupted_run(eid, "plain_fails_first", str(pw_run.ws), {})
    assert not admission.automatic_resume_refused(eid)
    queue_run(eid, "plain_fails_first", str(pw_run.ws), {}, start="resume")
    with get_session() as session:
        row = session.get(WorkflowRun, eid)
        assert row.status == "queued"
        assert admission.reservation(row.spawner_metadata)["phase"] == "reserved"
    assert forbidden == Counter()


@pytest.mark.parametrize("entry", ["runner", "cli", "api", "answered_api", "queue", "pi_pickup"])
def test_unreadable_before_enqueue_refuses_attempt_without_mutation_or_runtime(saved, forbidden,
                                                                             monkeypatch, entry):
    break_checkpoint(monkeypatch)
    if entry == "runner":
        with pytest.raises(admission.ResumeAuthorityUnreadable):
            call_runner(saved)
    elif entry == "cli":
        update_row(saved.eid, spawner_metadata={**saved.original["metadata"], "start": "resume"})
        # An unreserved resume is refused too; it cannot go through a generic bootstrap failure.
        assert call_cli(saved.eid) == admission.RESUME_ATTEMPT_REFUSED_EXIT
    elif entry in ("api", "answered_api"):
        if entry == "api":
            response = saved.pw.client.post(f"/api/runs/{saved.eid}/resume", json={})
            assert response.status_code == 503
            assert response.json()["detail"] == "Resume attempt refused: resume_authority_unreadable"
        else:
            from fastapi import HTTPException

            from temper_ai.api.routes import resume_answered_parked_run
            with pytest.raises(HTTPException) as error:
                resume_answered_parked_run(saved.eid)
            assert error.value.status_code == 503
    elif entry == "pi_pickup":
        from temper_ai.runner.pi_lane import resume_in_the_lane
        with pytest.raises(admission.ResumeAuthorityUnreadable):
            resume_in_the_lane(saved.eid)
    else:
        with pytest.raises(admission.ResumeAuthorityUnreadable):
            enqueue(saved)
    assert_preserved(saved)
    assert forbidden == Counter()
    assert saved.eid not in saved.pw.state.running
    assert action_rows(saved.eid)[-1]["action"] == "resume_attempt_refused"


@pytest.mark.parametrize("entry", ["runner", "cli"])
def test_enqueue_success_then_worker_read_fault_restores_exact_before_clear_projection(
        saved, forbidden, monkeypatch, entry):
    lease = enqueue(saved)
    # The worker appended a newer box audit; restoration must not discard it.
    meta = projection(saved.eid)["metadata"]
    update_row(saved.eid, spawner_metadata={**meta, "box_profile": {
        "history": [{"generation": 1}, {"generation": 2}]}})
    install_launch_token(saved.eid, monkeypatch)
    assert os.environ[admission.RESERVATION_ENV] == lease
    break_checkpoint(monkeypatch)
    if entry == "runner":
        with pytest.raises(admission.ResumeAuthorityUnreadable):
            call_runner(saved)
    else:
        assert call_cli(saved.eid) == admission.RESUME_ATTEMPT_REFUSED_EXIT
    assert_preserved(saved)
    assert projection(saved.eid)["metadata"]["box_profile"]["history"] == [
        {"generation": 1}, {"generation": 2}]
    assert admission.reservation(projection(saved.eid)["metadata"])["phase"] == "recovered"
    assert admission.automatic_resume_refused(saved.eid)
    assert forbidden == Counter()


class GoneSpawner:
    kind = SpawnerKind.subprocess

    def __init__(self):
        self.calls = Counter()

    def is_alive(self, _handle):
        self.calls["is_alive"] += 1
        return False

    def is_gone(self, _handle):
        return True

    def reap(self, _handle):
        self.calls["reap"] += 1
        return 7

    def spawn(self, _eid):
        self.calls["spawn"] += 1
        raise AssertionError("refused resume must not spawn automatically")


@pytest.mark.parametrize("lane", [None, "pi"])
def test_dispatch_claim_is_not_admission_real_cli_refuses_without_producing(saved, forbidden,
                                                                           monkeypatch, lane):
    from temper_ai.cli import watch_queue
    from temper_ai.database import get_database
    from temper_ai.runner import pi_lane
    from temper_ai.runner.lanes import mark_lane

    if lane is not None:
        update_row(saved.eid, spawner_metadata=mark_lane(saved.original["metadata"], lane))
        saved.original = projection(saved.eid)
    lease = enqueue(saved, lane=lane)

    from temper_ai.spawner.subprocess_spawner import SubprocessSpawner

    worker = SubprocessSpawner()
    calls = Counter()

    def create_process(*_args, **kwargs):
        calls["spawn"] += 1
        # The real watcher binds its observed reservation; the real spawner
        # writes this environment. Neither token nor baseline is hand-made.
        assert admission.launch_resume_token(saved.eid) == lease
        if lane is not None:
            assert pi_lane.lane_status(get_database().engine)["active"] == [
                {"run_id": saved.eid, "why": "claimed"}]
        monkeypatch.setenv(admission.RESERVATION_ENV, kwargs["env"][admission.RESERVATION_ENV])
        break_checkpoint(monkeypatch)
        assert call_cli(saved.eid) == admission.RESUME_ATTEMPT_REFUSED_EXIT
        return SimpleNamespace(pid=43111, wait=lambda: admission.RESUME_ATTEMPT_REFUSED_EXIT)

    monkeypatch.setattr("temper_ai.spawner.subprocess_spawner.subprocess.Popen", create_process)
    monkeypatch.setattr("temper_ai.spawner.subprocess_spawner.threading.Thread.start", lambda _self: None)
    assert watch_queue._scan_and_dispatch(worker, lane) == 1
    assert calls["spawn"] == 1  # A box/claim, not a workflow or model start.
    assert_preserved(saved)
    assert watch_queue._scan_and_dispatch(worker, lane) == 0
    if lane is not None:
        assert pi_lane.lane_status(get_database().engine)["active"] == []
    assert forbidden == Counter()


@pytest.mark.parametrize("recovery", ["reaper", "restart"])
def test_db_outage_preserves_durable_reservation_and_token_fenced_recovery(saved, forbidden,
                                                                         monkeypatch, recovery):
    from temper_ai.cli import watch_queue
    lease = enqueue(saved)
    install_launch_token(saved.eid, monkeypatch)
    assert os.environ[admission.RESERVATION_ENV] == lease
    handle = "fixture-pid" if recovery == "reaper" else CLAIMING
    update_row(saved.eid, spawner_kind="subprocess", spawner_handle=handle)
    with monkeypatch.context() as fault:
        def unavailable():
            raise OSError("fixture database unavailable")
        fault.setattr(admission, "get_session", unavailable)
        assert call_cli(saved.eid) == admission.RESUME_ATTEMPT_REFUSED_EXIT
    assert admission.reservation(projection(saved.eid)["metadata"])["phase"] == "reserved"
    worker = GoneSpawner()
    if recovery == "reaper":
        reaper = Reaper(worker)
        monkeypatch.setattr(reaper, "_mark_orphaned", lambda *_a, **_k: pytest.fail("orphan attempt"))
        monkeypatch.setattr(reaper, "_end_unstarted", lambda *_a, **_k: pytest.fail("failed attempt"))
        reaper.tick()
    else:
        # Actual startup adapter, not only its internal recovery helper.
        monkeypatch.setattr(watch_queue, "init_database", lambda _url: None)
        assert watch_queue._try_watcher_startup(saved.pw.url, worker, None)
    assert_preserved(saved)
    assert watch_queue._scan_and_dispatch(worker) == 0
    assert worker.calls["spawn"] == worker.calls["reap"] == 0
    assert forbidden == Counter()


def test_lost_admission_ack_without_permission_recovers_only_after_own_box_gone(saved, forbidden,
                                                                            monkeypatch):
    lease = enqueue(saved)
    update_row(saved.eid, spawner_kind="subprocess", spawner_handle="fixture-pid")
    real_session = admission.get_session
    calls = 0

    @contextmanager
    def lost_ack():
        nonlocal calls
        calls += 1
        outer = calls == 1
        with real_session() as session:
            yield session
        if outer:
            raise OSError("fixture commit acknowledgement lost")

    with monkeypatch.context() as fault:
        fault.setattr(admission, "get_session", lost_ack)
        with pytest.raises(admission.ResumeAuthorityUnreadable) as error:
            admission.admit_resume(saved.eid, expected_token=lease)
    assert error.value.code == "resume_admission_unconfirmed"
    assert admission.reservation(projection(saved.eid)["metadata"])["phase"] == "admitted"
    assert error.value.allow_admitted_restore
    Reaper(GoneSpawner()).tick()
    assert_preserved(saved)
    assert forbidden == Counter()


@pytest.mark.parametrize("race", ["new_token", "new_attempt", "new_claim", "cancel"])
def test_refusal_and_recovery_never_overwrite_new_owner_or_independent_cancel(saved, monkeypatch, race):
    lease = enqueue(saved)
    refused = admission.ResumeAuthorityUnreadable(execution_id=saved.eid, token=lease)
    if race == "cancel":
        update_row(saved.eid, cancel_requested=True)
    elif race == "new_token":
        meta = projection(saved.eid)["metadata"]
        update_row(saved.eid, spawner_metadata={**meta, admission.RESERVATION_KEY: {
            **meta[admission.RESERVATION_KEY], "token": "fixture-new-owner"}})
    elif race == "new_claim":
        with get_session() as session:
            session.add(ResumeClaim(execution_id=saved.eid, from_attempt=f"original-{saved.eid}",
                                    token="fixture-new-claim"))
    else:
        with get_session() as session:
            session.add(Event(execution_id=saved.eid, type="workflow.started", status="running",
                              data={"workflow_name": "plain_fails_first"}))
    before = canonical(projection(saved.eid))
    assert not admission.refuse_resume(saved.eid, refused)
    assert not admission.recover_resume_reservation(saved.eid, expected_token=lease,
                                                     box_proved_gone=True)
    assert canonical(projection(saved.eid)) == before
    assert original_event(saved.eid)[0] == "failed"
    if race == "new_claim":
        with get_session() as session:
            assert session.get(ResumeClaim, saved.eid).token == "fixture-new-claim"


def test_changed_checkpoint_version_refuses_before_runtime_and_preserves_projection(
        saved, forbidden, monkeypatch):
    lease = enqueue(saved)
    install_launch_token(saved.eid, monkeypatch)
    assert os.environ[admission.RESERVATION_ENV] == lease
    with get_session() as session:
        session.add(Checkpoint(execution_id=saved.eid, sequence=0, event_type="node_completed",
                               node_name="fixture-other", status="completed", output="fixture"))
    with pytest.raises(admission.ResumeAttemptRefused, match="resume_authority_changed"):
        call_runner(saved)
    assert_preserved(saved)
    assert forbidden == Counter()


@pytest.mark.parametrize("damage", ["missing_capsule", "missing_prior", "corrupt_prior"])
def test_missing_or_corrupt_baseline_never_manufactures_outcome_or_runs_work(
        saved, forbidden, monkeypatch, damage):
    lease = enqueue(saved)
    install_launch_token(saved.eid, monkeypatch)
    assert os.environ[admission.RESERVATION_ENV] == lease
    meta = projection(saved.eid)["metadata"]
    if damage == "missing_capsule":
        meta.pop(admission.RESERVATION_KEY)
    else:
        meta[admission.RESERVATION_KEY]["prior"] = None if damage == "missing_prior" else {"status": "cancelled"}
    update_row(saved.eid, spawner_metadata=meta, spawner_kind="subprocess", spawner_handle="fixture-pid")
    before = canonical(projection(saved.eid))
    assert call_cli(saved.eid) == admission.RESUME_ATTEMPT_REFUSED_EXIT
    Reaper(GoneSpawner()).tick()
    assert canonical(projection(saved.eid)) == before
    assert original_event(saved.eid)[0] == "failed"
    assert forbidden == Counter()


@pytest.mark.parametrize("key", admission.RESERVED_KEYS + ("start",))
def test_queue_extra_cannot_supply_baseline_or_permission(saved, key):
    with pytest.raises(ValueError, match="server-owned"):
        queue_run(saved.eid, "plain_fails_first", str(saved.pw.ws), {}, start="resume",
                  extra={key: {"status": "cancelled", "prior": saved.original}})
    assert_preserved(saved)


def test_explicit_new_reservation_supersedes_refusal_without_automatic_retry(saved):
    old = enqueue(saved)
    assert admission.refuse_resume(saved.eid, admission.ResumeAuthorityUnreadable(
        execution_id=saved.eid, token=old))
    assert admission.automatic_resume_refused(saved.eid)
    fresh = enqueue(saved)
    assert fresh != old
    assert not admission.automatic_resume_refused(saved.eid)
    assert admission.admit_resume(saved.eid, expected_token=fresh).authority.outputs == {}


def test_python_caller_cannot_forge_admitted_snapshot(saved, forbidden):
    authority = admission.read_resume_authority(saved.eid)
    fake = admission.ResumeAdmission(authority, None, saved.eid)
    with pytest.raises(admission.ResumeAttemptRefused, match="resume_admission_not_issued"):
        call_runner(saved, _resume_admission=fake)
    assert_preserved(saved)
    assert forbidden == Counter()


@pytest.mark.parametrize("fault", ["none", "checkpoint", "observation"])
def test_known_saved_stop_keeps_original_reason_costs_and_results_without_runtime(
        saved, forbidden, monkeypatch, fault):
    reason = "fixture owner stopped talk"
    data = original_event(saved.eid)[1]
    with get_session() as session:
        original = session.get(Event, f"original-{saved.eid}")
        original.status = "cancelled"
        original.data = {**data, "error": reason,
                         "stopped": {"kind": "cancelled", "path": "talk", "reason": reason}}
        session.add(original)
        session.add(Checkpoint(execution_id=saved.eid, sequence=0, event_type="node_completed",
                               node_name="talk", status="cancelled", error=reason,
                               cost_usd=9.125, total_tokens=57,
                               metadata_={"self_cancelled": {"path": "talk", "reason": reason}}))
    update_row(saved.eid, status="cancelled", error={"message": reason, "kind": "fixture"})
    saved.original = projection(saved.eid)
    if fault == "checkpoint":
        break_checkpoint(monkeypatch)
    elif fault == "observation":
        # Read remains healthy; its state-only diagnostic write cannot undo cancellation.
        real_session = admission.get_session

        @contextmanager
        def fail_observation():
            with real_session() as session:
                def unavailable(_event):
                    raise OSError("fixture observation unavailable")
                monkeypatch.setattr(session, "add", unavailable)
                yield session
        monkeypatch.setattr(admission, "get_session", fail_observation)
    result = call_runner(saved)
    assert (result.status, result.error, result.cost_usd, result.total_tokens) == (
        "cancelled", reason, 9.125, 57)
    assert saved.pw.client.post(f"/api/runs/{saved.eid}/resume", json={}).json()["status"] == "cancelled"
    assert queue_run(saved.eid, "invalid-revised-workflow", str(saved.pw.ws), {}, start="resume").stopped
    assert_preserved(saved)
    assert forbidden == Counter()


def test_successful_empty_authority_allows_normal_resume_and_held_setup(saved):
    from tests.test_runner.pi_parking import support as pw
    authority = admission.read_resume_authority(saved.eid)
    assert authority.outputs == {} and not authority.stopped
    assert authority.version
    result = call_runner(saved)
    assert result.status == "failed"  # The unchanged fixture's first step genuinely fails.
    assert pw.RAN["plain_first"] == 1
    with get_session() as session:
        assert session.get(CleanupHold, saved.eid).status == "taken_over"
    assert not action_rows(saved.eid)


def test_existing_unclaimed_cancel_path_still_cancels_without_a_box(saved):
    from temper_ai.cli import watch_queue
    enqueue(saved)
    update_row(saved.eid, cancel_requested=True)
    worker = GoneSpawner()
    assert watch_queue._scan_and_dispatch(worker) == 0
    assert projection(saved.eid)["status"] == "cancelled"
    assert projection(saved.eid)["cancel_requested"]
    assert worker.calls["spawn"] == 0


@pytest.mark.parametrize("fault", ["database", "pi_authority"])
def test_watcher_stays_alive_during_db_startup_outage_without_dispatch(saved, monkeypatch, fault):
    from temper_ai.cli import watch_queue
    calls = Counter()
    worker = GoneSpawner()

    class Stop:
        ended = False

        def is_set(self):
            return self.ended

        def set(self):
            self.ended = True

        def wait(self, _seconds):
            calls["wait"] += 1
            self.set()

    def unavailable(_url):
        calls["db"] += 1
        raise OSError("fixture startup database unavailable")

    if fault == "database":
        monkeypatch.delenv("TEMPER_LANE", raising=False)
        monkeypatch.setattr(watch_queue, "init_database", unavailable)
    else:
        from temper_ai.runner import pi_lane
        monkeypatch.setenv("TEMPER_LANE", "pi")
        monkeypatch.setattr(watch_queue, "init_database", lambda _url: calls.update(db=1))
        monkeypatch.setattr(pi_lane, "worker_problem", lambda _spawner: None)
        monkeypatch.setattr(pi_lane, "eager_import", lambda: None)
        monkeypatch.setattr(pi_lane, "arm_drain_mark", lambda: None)
        monkeypatch.setattr(pi_lane, "start_up", lambda: {"authority_unavailable": True})
    monkeypatch.setattr(watch_queue, "get_spawner", lambda: worker)
    monkeypatch.setattr(watch_queue.threading, "Event", Stop)
    monkeypatch.setattr(watch_queue.signal, "signal", lambda *_a: None)
    monkeypatch.setattr(watch_queue.Reaper, "start", lambda _self: pytest.fail("reaper started during outage"))
    assert watch_queue.cmd_watch_queue(argparse.Namespace(poll_interval=0, reaper_interval=5)) == 0
    assert calls == Counter(db=1, wait=1)
    assert worker.calls["spawn"] == 0
    assert_preserved(saved)


@pytest.mark.parametrize("entry", ["api", "parked_answer", "pickup", "pi_claim"])
def test_real_resume_paths_reserve_and_launch_without_hand_made_tokens(saved, monkeypatch, entry):
    """Actual public/automatic entry, actual enqueue and actual launcher transport.

    Old parked runs have no admission capsule. Only the new enqueue creates it;
    neither a fixture nor a caller reconstructs a baseline after fields are cleared.
    """
    from temper_ai.runner import parked, pi_lane, pickup
    from temper_ai.runner.lanes import PI_LANE, lane_of, mark_lane

    monkeypatch.setenv("TEMPER_EXECUTION_MODE", "external")
    status = "waiting" if entry == "parked_answer" else "interrupted"
    workflow = "pw_fails_first" if entry in ("parked_answer", "pi_claim") else "plain_fails_first"
    gate_id = f"owner-{saved.eid}"
    with get_session() as session:
        event = session.get(Event, f"original-{saved.eid}")
        event.status = status
        event.data = {**event.data, "name": workflow, "workflow_name": workflow,
                      "workspace_path": str(saved.pw.ws), "input_data": {"retained": "input"}}
        if entry == "parked_answer":
            event.data = {**event.data, "parked": {"event_id": gate_id, "path": "owner"}}
            session.add(Event(id=gate_id, execution_id=saved.eid, type="stage.started",
                              status="approved", data={"name": "owner", "gate": True,
                                                       "gate_path": "owner"}))
        session.add(event)
        session.add(Checkpoint(execution_id=saved.eid, sequence=0, event_type="node_completed",
                               node_name="plain_first", status="completed", output="fixture"))
    metadata = saved.original["metadata"]
    if entry in ("parked_answer", "pi_claim"):
        metadata = mark_lane(metadata, PI_LANE)
    update_row(saved.eid, status=status, workflow_name=workflow, spawner_metadata=metadata)
    saved.original = projection(saved.eid)
    assert admission.reservation(saved.original["metadata"]) is None

    if entry == "api":
        response = saved.pw.client.post(f"/api/runs/{saved.eid}/resume", json={})
        assert response.status_code == 200 and response.json()["status"] == "queued"
    elif entry == "parked_answer":
        from temper_ai.api.routes import resume_answered_parked_run
        assert parked.carry_on(saved.eid, start=resume_answered_parked_run, by="fixture answer")
    elif entry == "pickup":
        result = pickup.pick_up_interrupted([{
            "execution_id": saved.eid, "event_id": f"original-{saved.eid}",
            "workflow_name": workflow, "status_before": "running", "timestamp": utcnow(),
        }], settle_s=0, gap_s=0, tell=lambda _text: True)
        assert [choice.execution_id for choice in result.picked] == [saved.eid]
        assert not result.failed
    else:
        pi_lane.resume_in_the_lane(saved.eid)

    capsule = admission.reservation(projection(saved.eid)["metadata"])
    assert capsule["phase"] == "reserved"
    assert capsule["prior"] == saved.original
    assert capsule["from_attempt"] == f"original-{saved.eid}"
    if entry == "parked_answer":
        assert capsule["claims"]["parked"]["id"] == f"original-{saved.eid}"
    elif entry == "pi_claim":
        with get_session() as session:
            assert capsule["claims"]["resume"]["token"] == session.get(ResumeClaim, saved.eid).token
    assert lane_of(projection(saved.eid)["metadata"]) == lane_of(saved.original["metadata"])

    install_launch_token(saved.eid, monkeypatch, lane=lane_of(projection(saved.eid)["metadata"]))
    assert os.environ[admission.RESERVATION_ENV] == capsule["token"]
    break_checkpoint(monkeypatch)
    from temper_ai.runner import bootstrap
    calls = Counter()

    def forbidden_bootstrap(*_args, **_kwargs):
        calls["full_bootstrap"] += 1
        raise AssertionError("unreadable worker must not bootstrap")

    monkeypatch.setattr(bootstrap, "bootstrap_runner_context_from_env", forbidden_bootstrap)
    assert call_cli(saved.eid) == admission.RESUME_ATTEMPT_REFUSED_EXIT
    assert_preserved(saved)
    assert calls == Counter()
    assert admission.automatic_resume_refused(saved.eid)
    assert saved.eid not in saved.pw.state.running
    from tests.test_pi_agent.support import FakeBox
    from tests.test_runner.pi_parking.support import RAN
    assert RAN == Counter() and FakeBox.STARTS == []
