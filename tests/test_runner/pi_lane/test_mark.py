"""Every way a run is created or re-queued carries the lane mark (Architecture rm-0b46a085).

A Pi workflow's run (any Pi step, or a team stage of Pi members) is written with
``spawner_metadata`` ``{"lane": "pi"}`` by the two run-row writers -- runner/queue.py's
``queue_run``, on insert and on every re-queue, and the server's direct spawn -- and only the
Pi lane's claim takes it. An ordinary run is written as before, with no mark, and only the
main watcher's claim takes it. One test per entry point, both ways (docs/pi-lane.md). The
team trial's start is in tests/test_runner/pi_parking/test_team_api.py, beside its fixture.
"""

from __future__ import annotations

import io
import re
from datetime import timedelta
from pathlib import Path

import pytest

from temper_ai.runner.lanes import LANE_KEY, PI_LANE
from tests.test_runner.pi_lane import support as ls

PI_WORKFLOWS = ("lane_pi", "lane_pi_gate", "lane_team")
REPO = Path(__file__).resolve().parents[3]
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

#: Both ways: a Pi workflow and an ordinary one.
BOTH = pytest.mark.parametrize("workflow,pi", [("lane_pi", True), ("lane_plain", False)])


def _post(srv, workflow: str) -> dict:
    r = srv.client.post("/api/runs", json={"workflow": workflow, "inputs": {"topic": "lane"},
                                           "workspace_path": str(srv.ws)})
    assert r.status_code == 200, r.text
    return r.json()


def _lands(execution_id: str, pi: bool) -> None:
    if pi:
        ls.only_the_pi_lane_claims(execution_id)
    else:
        ls.only_the_main_lane_claims(execution_id)


def _earlier_attempt(monkeypatch, srv, workflow: str) -> None:
    """What the events say about the run being resumed (as tests/test_api does)."""
    from temper_ai.api import routes

    monkeypatch.setattr(routes, "get_workflow_execution", lambda eid: {
        "workflow_name": workflow, "status": "interrupted", "input_data": {"topic": "lane"},
        "workspace_path": str(srv.ws)})


def _checkpoint(execution_id: str, node: str) -> int:
    from temper_ai.checkpoint.service import CheckpointService
    from temper_ai.stage.executor import NodeResult, Status

    service = CheckpointService(execution_id)
    service.save_node_completed(node, NodeResult(status=Status.COMPLETED, output=f"{node} done"))
    return service.get_latest_sequence()


def _ended_row(execution_id: str, workflow: str, pi: bool, **over) -> None:
    """A run that ran in a box and stopped: claimed once, with its box's metadata."""
    fields = {"status": "failed", "spawner_kind": "subprocess", "handle": "4242",
              "metadata": {"pid": 4242, "start": "resume"}}
    fields.update(over)
    ls.make_row(execution_id, workflow, pi=pi, **fields)


# --- POST /api/runs, in each of the server's modes ---------------------------------------------


@pytest.mark.parametrize("workflow", PI_WORKFLOWS)
def test_post_api_runs_queues_a_pi_run_for_the_pi_lane_only(srv, workflow):
    got = _post(srv, workflow)
    assert got["status"] == "queued"
    ls.only_the_pi_lane_claims(got["execution_id"])
    assert ls.row(got["execution_id"]).spawner_metadata == {LANE_KEY: PI_LANE}


def test_post_api_runs_writes_an_ordinary_run_as_before_with_no_mark(srv):
    got = _post(srv, "lane_plain")
    assert got["status"] == "queued"
    ls.only_the_main_lane_claims(got["execution_id"])
    assert ls.row(got["execution_id"]).spawner_metadata == {}


def test_a_server_running_runs_itself_still_queues_a_pi_run_for_the_pi_lane(srv, monkeypatch):
    """TEMPER_EXECUTION_MODE=inprocess: an ordinary run would run on a thread here; a Pi run
    is never started anywhere but the Pi lane."""
    monkeypatch.setenv("TEMPER_EXECUTION_MODE", "inprocess")
    got = _post(srv, "lane_pi")
    assert got["status"] == "queued"
    assert got["execution_id"] not in srv.state.running
    ls.only_the_pi_lane_claims(got["execution_id"])


@BOTH
def test_a_server_that_starts_boxes_itself_queues_a_pi_run_and_spawns_only_others(
        srv, monkeypatch, workflow, pi):
    """TEMPER_EXECUTION_MODE=subprocess: the direct-spawn writer is for the server's own runs;
    a Pi run goes to the queue with its mark instead."""
    import temper_ai.spawner as spawner_pkg

    fake = ls.FakeSpawner()
    monkeypatch.setenv("TEMPER_EXECUTION_MODE", "subprocess")
    monkeypatch.setattr(spawner_pkg, "get_spawner", lambda *a, **k: fake)
    got = _post(srv, workflow)
    eid = got["execution_id"]
    if pi:
        assert got["status"] == "queued" and fake.spawned == []
        ls.only_the_pi_lane_claims(eid)
    else:
        assert got["status"] == "running" and fake.spawned == [eid]
        found = ls.row(eid)
        assert found.spawner_kind == "subprocess" and found.spawner_metadata == {"pid": 4242}


def test_the_direct_spawn_writer_marks_a_pi_run_and_its_stamp_keeps_the_mark(srv, monkeypatch):
    """The other run-row writer (routes._start_run_subprocess): reached for a Pi run only where
    the process is the Pi lane itself, which starts it there."""
    import temper_ai.spawner as spawner_pkg

    fake = ls.FakeSpawner()
    ls.as_the_pi_lane(monkeypatch)
    monkeypatch.setenv("TEMPER_EXECUTION_MODE", "subprocess")
    monkeypatch.setattr(spawner_pkg, "get_spawner", lambda *a, **k: fake)
    got = _post(srv, "lane_pi")
    assert got["status"] == "running" and fake.spawned == [got["execution_id"]]
    assert ls.row(got["execution_id"]).spawner_metadata == {"pid": 4242, LANE_KEY: PI_LANE}


# --- the other ways in that start a run --------------------------------------------------------


@BOTH
def test_the_cli_temper_run_posts_to_the_server_and_the_run_lands_in_its_lane(
        srv, monkeypatch, workflow, pi):
    from temper_ai.cli import run_on_server

    class _Http:
        def request(self, method, path, json=None, timeout=None):
            return srv.client.request(method, path, json=json)

        def close(self):
            return None

    def _server(self, url, token=None):
        self.url = url
        self._http = _Http()

    monkeypatch.setattr(run_on_server.Server, "__init__", _server)
    out = io.StringIO()
    code = run_on_server.run(workflow, {"topic": "lane"}, workspace=str(srv.ws),
                             server="http://temper.test", ui="http://ui.test", detach=True,
                             out=out, sleep=lambda s: None)
    assert code == 0, out.getvalue()
    (eid,) = UUID.findall(out.getvalue().split("\n")[0])
    _lands(eid, pi)


@BOTH
def test_the_mcp_tool_temper_start_run_lands_the_run_in_its_lane(srv, workflow, pi):
    from temper_ai.mcp.tools import TemperTools

    got = TemperTools().run_workflow(workflow, inputs={"topic": "lane"},
                                     workspace_path=str(srv.ws))
    assert got["status"] == "queued"
    _lands(got["execution_id"], pi)


@BOTH
def test_a_schedule_rule_s_run_lands_in_its_lane(srv, workflow, pi):
    from temper_ai.triggers import scheduler as sched
    from temper_ai.triggers.rules import Trigger

    plan = sched.plan(Trigger(name=f"lane_every_{workflow}", source=sched.SCHEDULE,
                              on={"every": "5m"}, workflow=workflow))
    decision = sched.Scheduler(srv.tmp)._fire(plan, "k1", {})
    assert decision is not None and decision["outcome"] == "started", decision
    _lands(decision["execution_id"], pi)


@BOTH
def test_a_slack_start_lands_the_run_in_its_lane(srv, workflow, pi):
    from temper_ai.integrations.slack.ops import TemperOps

    _lands(TemperOps().start(workflow, {"topic": "lane"}), pi)


@BOTH
def test_a_linear_hook_s_run_lands_in_its_lane(srv, monkeypatch, workflow, pi):
    import time

    from temper_ai.api import hooks

    monkeypatch.setattr(hooks, "_run_still_going", lambda eid: None)
    folder = srv.tmp / "rules" / "triggers"
    folder.mkdir(parents=True)
    (folder / "lane_linear.yaml").write_text(
        "trigger:\n  name: lane_linear\n  source: linear\n  on:\n    type: Issue\n"
        f"    label_added: temper\n  workflow: {workflow}\n  ignore_self: false\n"
        "  inputs:\n    issue_id: \"{{ data.id }}\"\n")
    event = {"type": "Issue", "action": "create", "actor": {"id": "person-1", "name": "Ada"},
             "data": {"id": "iss-1", "identifier": "ENG-1",
                      "labels": [{"id": "l1", "name": "temper"}]},
             "url": "https://linear.app/acme/issue/ENG-1",
             "webhookTimestamp": int(time.time() * 1000)}
    hooks.reset_state()
    try:
        record = hooks.dispatch(event, {"delivery": "d", "type": "Issue", "action": "create",
                                        "outcome": "received", "runs": []},
                                config_dir=srv.tmp / "rules")
    finally:
        hooks.reset_state()
    (run,) = record["runs"]
    _lands(run["execution_id"], pi)


@BOTH
def test_a_github_hook_s_run_lands_in_its_lane(srv, monkeypatch, workflow, pi):
    """The committed rules start github_work for a labelled issue; here it's a Pi workflow or
    an ordinary one."""
    from temper_ai.api import hooks
    from tests.test_pi_agent import support as sup

    monkeypatch.setitem(sup.WORKFLOWS, "github_work", ls.WORKFLOWS[workflow])
    monkeypatch.setattr(hooks, "_run_still_going", lambda eid: None)
    payload = {"action": "labeled",
               "issue": {"number": 12, "title": "Fix the typo", "body": "In the README",
                         "state": "open", "user": {"login": "shine2lay"},
                         "labels": [{"name": "temper"}]},
               "label": {"name": "temper"},
               "repository": {"full_name": "shine2lay/temper-ai", "private": False,
                              "default_branch": "master"},
               "sender": {"login": "shine2lay", "type": "User"}}
    hooks.reset_state()
    try:
        record = hooks.github_dispatch("issues", payload, {"delivery": "d", "runs": []},
                                       config_dir=REPO / "configs")
    finally:
        hooks.reset_state()
    started = [r for r in record["runs"] if r.get("execution_id")]
    assert len(started) == 1, record
    _lands(started[0]["execution_id"], pi)


# --- the ways a run is queued again ------------------------------------------------------------


@BOTH
def test_resume_sets_the_lane_again_from_the_workflow(srv, monkeypatch, workflow, pi):
    """queue_run's re-queue replaced spawner_metadata wholesale: the mark is set again there."""
    eid = f"resume-{workflow}"
    _ended_row(eid, workflow, pi)
    _checkpoint(eid, "brief")
    _earlier_attempt(monkeypatch, srv, workflow)
    r = srv.client.post(f"/api/runs/{eid}/resume", json={})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "queued"
    _lands(eid, pi)
    reservation = ls.row(eid).spawner_metadata["resume_reservation"]
    assert ls.row(eid).spawner_metadata == (
        {"start": "resume", LANE_KEY: PI_LANE, "resume_reservation": reservation} if pi else
        {"start": "resume", "resume_reservation": reservation})


def test_a_pi_run_from_before_the_lane_gets_its_mark_when_it_is_resumed(srv, monkeypatch):
    """A row written before the lane existed has no mark: the resume sets it from the
    workflow, so the main watcher never claims it."""
    _ended_row("resume-old-pi", "lane_pi", pi=False)
    _earlier_attempt(monkeypatch, srv, "lane_pi")
    r = srv.client.post("/api/runs/resume-old-pi/resume", json={})
    assert r.status_code == 200, r.text
    ls.only_the_pi_lane_claims("resume-old-pi")


@BOTH
def test_a_slack_resume_lands_the_run_in_its_lane(srv, monkeypatch, workflow, pi):
    from temper_ai.integrations.slack.ops import TemperOps

    eid = f"slack-resume-{workflow}"
    _ended_row(eid, workflow, pi, status="orphaned")
    _checkpoint(eid, "brief")
    _earlier_attempt(monkeypatch, srv, workflow)
    assert TemperOps().resume(eid) == eid
    _lands(eid, pi)


@BOTH
def test_a_fork_lands_in_its_lane(srv, workflow, pi):
    source = f"fork-src-{workflow}"
    at = _checkpoint(source, "brief")
    r = srv.client.post("/api/runs/fork", json={"workflow": workflow,
                                                "source_execution_id": source, "sequence": at,
                                                "inputs": {"topic": "lane"},
                                                "workspace_path": str(srv.ws)})
    assert r.status_code == 200, r.text
    eid = r.json()["execution_id"]
    assert eid != source and r.json()["status"] == "queued"
    _lands(eid, pi)
    assert ls.row(eid).spawner_metadata == (
        {"start": "fork", LANE_KEY: PI_LANE} if pi else {"start": "fork"})


def _held(execution_id: str, workflow: str, srv, *, deadline_ago: timedelta) -> None:
    from temper_ai.runner import holds
    from temper_ai.shared.clock import utcnow

    holds.record(execution_id, workflow_name=workflow, workspace_path=str(srv.ws),
                 inputs={"topic": "lane"}, held=[{"path": "teardown"}],
                 deadline=utcnow() - deadline_ago, stopped_at="talk", stop_reason="failed")


@BOTH
def test_give_up_s_clean_up_pass_keeps_the_run_s_lane(srv, monkeypatch, workflow, pi):
    eid = f"give-up-{workflow}"
    _ended_row(eid, workflow, pi)
    _held(eid, workflow, srv, deadline_ago=timedelta(hours=-1))
    _earlier_attempt(monkeypatch, srv, workflow)
    r = srv.client.post(f"/api/runs/{eid}/cleanup")
    assert r.status_code == 200, r.text
    _lands(eid, pi)
    assert ls.row(eid).spawner_metadata.get("only") == ["teardown"]


@BOTH
def test_the_clean_up_deadline_sweep_keeps_the_run_s_lane(srv, workflow, pi):
    from temper_ai.runner import hold_sweeper

    eid = f"sweep-{workflow}"
    _ended_row(eid, workflow, pi)
    _held(eid, workflow, srv, deadline_ago=timedelta(minutes=5))
    hold_sweeper._sweep()
    _lands(eid, pi)
    assert ls.row(eid).spawner_metadata["start"] == "cleanup"


@BOTH
def test_carrying_a_parked_run_on_keeps_its_lane(srv, monkeypatch, workflow, pi):
    """runner/parked.py queue_resume, the worker's reaper's way after the owner's answer."""
    from temper_ai.runner import parked

    eid = f"parked-{workflow}"
    _ended_row(eid, workflow, pi, status=parked.WAITING)
    attempt = {"execution_id": eid, "attempt": 1}
    monkeypatch.setattr(parked, "parked_attempt", lambda e: attempt if e == eid else None)
    monkeypatch.setattr(parked, "claim", lambda a: a is attempt)
    parked.queue_resume(eid)
    _lands(eid, pi)


def _reaped(execution_id: str, workflow: str, pi: bool) -> None:
    """A run whose box was found dead: the row and the event the reaper writes, and a step
    that had finished (as tests/test_runner/test_pickup_after_a_crash.py does)."""
    from temper_ai.database import get_session
    from temper_ai.observability.models import Event
    from temper_ai.shared.clock import utcnow

    _ended_row(execution_id, workflow, pi, status="orphaned",
               completed_at=utcnow() - timedelta(seconds=5))
    with get_session() as session:
        session.add(Event(id=f"ev-{execution_id}", type="workflow.started",
                          execution_id=execution_id, status="interrupted",
                          data={"name": workflow, "error": "reaped: worker process gone"},
                          timestamp=utcnow() - timedelta(minutes=20)))
    _checkpoint(execution_id, "brief")


def test_the_server_s_pick_up_takes_only_main_lane_runs_and_queues_them_unmarked(
        srv, monkeypatch):
    from temper_ai.api import routes
    from temper_ai.runner import pickup
    from temper_ai.shared.clock import utcnow

    _reaped("cut-pi", "lane_pi", True)
    _reaped("cut-plain", "lane_plain", False)
    _earlier_attempt(monkeypatch, srv, "lane_plain")
    resumed: list[str] = []

    def resume(eid):
        resumed.append(eid)
        return routes._resume_run(eid)

    pickup.pick_up_interrupted([], since=utcnow() - timedelta(minutes=1), settle_s=0,
                               sleep=lambda s: None, resume=resume, tell=lambda t: True)
    assert resumed == ["cut-plain"]
    ls.only_the_main_lane_claims("cut-plain")
    assert ls.row("cut-pi").status == "orphaned"  # the Pi lane's own start-up picks it up


def test_the_pi_lane_s_start_up_picks_up_only_pi_runs_and_queues_them_marked(srv):
    from types import SimpleNamespace

    from temper_ai.runner import pi_lane
    from temper_ai.shared.clock import utcnow

    ls.empty_the_ledger()  # the sweep below would look at another test's unsettled turns
    _reaped("cut-pi", "lane_pi", True)
    _reaped("cut-plain", "lane_plain", False)
    seen: list[tuple] = []

    def docker(*args, timeout=None):
        seen.append(args)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    out = pi_lane.start_up(docker=docker, now=utcnow())
    assert out["picked_up"] == ["cut-pi"], out
    ls.only_the_pi_lane_claims("cut-pi")
    assert ls.row("cut-plain").status == "orphaned"  # the server's pick-up's
    assert seen == [("ps", "-a", "--filter", "label=temper.pi.box=1", "--format",
                     "{{.Names}}")]


# --- no other writer -----------------------------------------------------------------------


def test_only_the_two_writers_create_run_rows_and_every_metadata_write_keeps_the_mark():
    """A new ``WorkflowRun(`` writer, or a new ``spawner_metadata =`` assignment, must be
    looked at for the lane mark: this fails until it is listed here (rm-0b46a085). Studio
    (api/studio.py) starts no runs: it isn't here."""
    rows, metadata = [], []
    for path in sorted((REPO / "temper_ai").rglob("*.py")):
        rel = str(path.relative_to(REPO))
        for line in path.read_text().splitlines():
            code = line.split("#", 1)[0]
            if code.lstrip().startswith("class "):
                continue
            if re.search(r"\bWorkflowRun\(", code) and "select(" not in code:
                rows.append(rel)
            if re.search(r"\.spawner_metadata\s*=[^=]|\bspawner_metadata=", code):
                metadata.append(rel)
    assert sorted(rows) == ["temper_ai/api/routes.py", "temper_ai/runner/queue.py"]
    assert sorted(metadata) == [
        "temper_ai/api/routes.py",  # the direct spawn: mark_lane on insert and on the stamp
        "temper_ai/api/routes.py",
        "temper_ai/cli/watch_queue.py",  # _stamp_handle: mark_lane(merged, lane_of(old))
        "temper_ai/cli/watch_queue.py",  # owned resume SQL merge excludes LANE_RECORD_KEY
        "temper_ai/pi_agent/accounts.py",  # record_account: a copy of the row's own metadata
        "temper_ai/runner/pi_lane.py",  # record_commit: a copy of the row's own metadata
        "temper_ai/runner/queue.py",  # queue_run: mark_lane on insert and re-queue
        "temper_ai/runner/queue.py",
        "temper_ai/runner/queue.py",  # new-row resume reservation: mark_lane already applied
        "temper_ai/runner/resume_authority.py",  # admission copies metadata, preserving lane
        "temper_ai/runner/resume_authority.py",  # invalid capsule copies metadata, preserving lane
        "temper_ai/runner/resume_authority.py",  # owned restoration keeps before-clear lane
        "temper_ai/spawner/box_profile.py",  # the box profile: a copy of the row's own
    ]
