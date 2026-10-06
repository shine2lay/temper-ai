"""SW-86: a Pi self-stop closes the run-wide start door, not just dependent edges.

Real in-process runs, the Pi ledger, approvals, checkpoints and Resume; only the Pi
workers are scripted. Each of E18's four endings has brief -> talk -> audit alongside
an independent three-step branch. Neither reports, approvals nor setup releases start
past the stop, under either failure policy. SQLite and Postgres (tests/pgtier.py).
"""

from __future__ import annotations

import os
import threading
from dataclasses import asdict

import pytest

from temper_ai.pi_agent.host import PiHost
from temper_ai.shared.clock import utcnow
from temper_ai.shared.types import NodeResult, Status
from temper_ai.stage.executor import execute_graph
from temper_ai.stage.failure import FailurePolicy
from temper_ai.stage.models import NodeConfig
from temper_ai.stage.node import Node
from tests.test_pi_agent import support as sup
from tests.test_pi_agent import test_team as tt
from tests.test_runner.pi_parking import support as pw
from tests.test_runner.pi_parking import test_team_runs as runs

team_on = tt.team_on
tr = runs.tr

SKIPPED = ("audit", "side_next", "approval", "report", "cleanup")


@pytest.fixture(params=["sqlite", "database_tier"])
def _stop_backend(request, monkeypatch):
    """Both backends in one full gate; the tier is SQLite when Postgres wasn't requested."""
    if request.param == "sqlite":
        monkeypatch.delenv("TEMPER_TEST_DATABASE_URL", raising=False)
    return request.param


@pytest.fixture(autouse=True)
def _test_db(_stop_backend, _test_db, request):
    """Reuse the parent's database fixture, after choosing this scenario's backend."""
    from tests.conftest import TEST_DATABASE_URL
    url = request.node.stash[TEST_DATABASE_URL]
    expected = "postgresql" if _stop_backend == "database_tier" and os.getenv(
        "TEMPER_TEST_DATABASE_URL") else "sqlite"
    assert url.startswith(expected)
    yield


def after_stop() -> list:
    nodes = [sup.step("audit", ["talk"]),
             sup.step("side_first"), sup.step("side_second", ["side_first"]),
             sup.step("side_next", ["side_second"]),
             sup.step("approval", ["talk"]), sup.step("report", ["talk"]),
             sup.step("cleanup", ["audit", "side_next", "approval", "report"])]
    by_name = {n.name: n for n in nodes}
    by_name["approval"].config.gate = True
    by_name["report"].config.run_after_failure = True
    by_name["cleanup"].config.undoes = ["brief"]
    by_name["cleanup"].config.run_after_failure = True
    return nodes


def node_events(eid: str, name: str) -> list[dict]:
    return [e for e in sup.events(eid, event_type="stage.started")
            if (e.get("data") or {}).get("name") == name
            and (e.get("data") or {}).get("type")]


def stopped(pw_run, eid: str, n: int, path: str) -> str:
    from temper_ai.checkpoint.service import CheckpointService
    from temper_ai.runner import holds
    from temper_ai.runner.pickup import candidates_from, choose

    attempt = pw.wait_ended(eid, n)[-1]
    assert attempt["status"] == "cancelled"
    data = attempt["data"]
    reason = data["error"]
    assert data["stopped"]["kind"] == "cancelled"
    assert (data["stopped"]["path"], data["stopped"]["reason"]) == (path, reason)
    assert "Workflow cancelled by user" not in reason
    assert pw.listed(pw_run.client, eid)["status"] == "cancelled"
    for name in SKIPPED:
        assert pw.RAN[name] == 0, name
        rows = node_events(eid, name)
        assert len(rows) == 1, name
        assert rows[0]["status"] == "skipped", name
        assert rows[0]["data"]["skip_reason"] == f"not started: the run was stopped at '{path}'"
        assert "gate_status" not in rows[0]["data"], name
    assert pw.RAN["side_first"] == pw.RAN["side_second"] == 1
    assert holds.waiting(eid) is None, "no deadline can start setup releases later"
    assert not [e for e in sup.events(eid, event_type="stage.started")
                if (e.get("data") or {}).get("name") == "approval"
                and (e.get("data") or {}).get("gate_status")]
    cp = CheckpointService(eid)
    assert cp.resume_state()["self_cancelled"] == {"path": path, "reason": reason}
    assert set(cp.resume_state()["skipped"]) >= set(SKIPPED)
    assert not cp.resume_state()["undone"], "skipped setup release is not successful release"
    assert not [c for c in cp._load_full_history() if c.event_type in ("cleanup_ran", "cleanup_held")]
    assert node_events(eid, "cleanup")[0]["data"]["type"] == "agent"
    picks = choose(candidates_from([{"execution_id": eid, "workflow_name": "sw86",
                                     "status_before": "running", "timestamp": utcnow()}]))
    assert not picks.picked
    assert picks.left[0].why == "it was cancelled"
    return reason


def resume_starts_none(pw_run, eid: str, n: int, reason: str) -> None:
    before = pw.attempts(eid)
    assert len(before) == n - 1
    r = pw_run.client.post(f"/api/runs/{eid}/resume", json={})
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"
    after = pw.attempts(eid)
    assert [a["id"] for a in after] == [a["id"] for a in before], "state-only, not a new attempt"
    attempt = after[-1]
    assert (attempt["status"], attempt["data"]["error"]) == ("cancelled", reason)
    assert all(pw.RAN[name] == 0 for name in SKIPPED)
    assert pw.RAN["brief"] == pw.RAN["side_first"] == pw.RAN["side_second"] == 1
    assert all(e["status"] == "skipped" for name in SKIPPED for e in node_events(eid, name))


@pytest.mark.parametrize("ending", ["pause", "stalled"])
@pytest.mark.parametrize("mode", ["hold", "cleanup"])
def test_sw86_team_stop_starts_no_dependents_branch_reports_gate_or_cleanup(tr, ending, mode):
    from temper_ai.stage.loader import GraphLoader
    from tests.test_runner.pi_team import support as ts

    config = runs.PAUSE_1 if ending == "pause" else tt.RUNNABLE
    team = tt.team_stage("talk", depends_on=["brief"], strategy_config=config)
    extras = {"workflow:team_wf": {"name": "team_wf", "on_failure": mode,
               "nodes": [runs.BRIEF_NODE, team, *[asdict(n.config) for n in after_stop()]]},
              **runs.BRIEF}
    for node in after_stop():
        extras[f"agent:{node.name}"] = {"name": node.name, "type": sup.STEP_TYPE}
    for node in extras["workflow:team_wf"]["nodes"][2:]:
        node["agent"] = node["name"]
    tr.state.graph_loader = GraphLoader(tt.store(team, extra=extras))
    if ending == "pause":
        runs.script(tr.led, ["keep_going", "done"])
    else:
        ts.SCRIPTS["design"] = [[{"say": "nothing to do"}]]
    eid = runs.start(tr, {"goal": runs.GOAL})
    pw.wait_parked(tr.state, eid, 1)
    (row,) = tr.led.open_waits(eid, "talk.team")
    assert row["kind"] == ending
    r = pw.approve(tr.client, eid, row["gate_name"], event_id=pw.parked(pw.attempts(eid)[-1])["event_id"],
                   response="stop")
    assert r.status_code == 200
    reason = stopped(tr, eid, 2, "talk.team")
    expected = ("stopped at the pause after round 1" if ending == "pause"
                else "stopped when the team had nothing left to do")
    assert reason == expected
    turns = len(ts.rows(tr.led, eid, "talk.team")["turns"])
    counts = runs.prompts()
    resume_starts_none(tr, eid, 3, reason)
    assert runs.prompts() == counts
    assert len(ts.rows(tr.led, eid, "talk.team")["turns"]) == turns


def install_single(monkeypatch, mode: str) -> dict:
    cfg = {"thinking": "medium"}
    monkeypatch.setitem(sup.WORKFLOWS, "sw86_pi", lambda: [
        sup.step("brief"), sup.pi_node(**cfg), *after_stop()])
    real_load = sup.StubLoader.load_workflow

    def load(self, *args, **kwargs):
        nodes, workflow = real_load(self, *args, **kwargs)
        workflow.on_failure = mode
        return nodes, workflow

    monkeypatch.setattr(sup.StubLoader, "load_workflow", load)
    return cfg


@pytest.mark.parametrize("mode", ["hold", "cleanup"])
def test_sw86_settings_stop_starts_no_dependents_branch_reports_gate_or_cleanup(
        pw_run, monkeypatch, mode):
    cfg = install_single(monkeypatch, mode)
    eid = sup.start(pw_run.client, "sw86_pi", pw_run.ws)
    pw.wait_parked(pw_run.state, eid, 1)
    owner = sup.open_wait(eid, "owner")
    cfg["thinking"] = "high"
    assert pw.approve(pw_run.client, eid, owner["gate_name"], event_id=owner["ask_event_id"],
                      response="look once more").status_code == 200
    pw.wait_parked(pw_run.state, eid, 2)
    wait = sup.open_wait(eid, "settings")
    assert pw.approve(pw_run.client, eid, wait["gate_name"], event_id=wait["ask_event_id"],
                      response="stop").status_code == 200
    reason = stopped(pw_run, eid, 3, "talk")
    assert reason.startswith("the Pi step was stopped: its settings changed")
    starts = len(sup.FakeBox.STARTS)
    resume_starts_none(pw_run, eid, 4, reason)
    assert len(sup.FakeBox.STARTS) == starts


@pytest.mark.parametrize("mode", ["hold", "cleanup"])
def test_sw86_settled_meanwhile_starts_no_dependents_branch_reports_gate_or_cleanup(
        pw_run, monkeypatch, mode):
    import temper_ai.pi_agent.host as host_module

    install_single(monkeypatch, mode)
    eid = sup.start(pw_run.client, "sw86_pi", pw_run.ws)
    pw.wait_parked(pw_run.state, eid, 1)
    wait = sup.open_wait(eid, "owner")
    real_ask = host_module.ask_owner_for_wait
    real_settled = PiHost._settled_meanwhile
    called: list[str] = []

    def closed_meanwhile(context, led, wait_id, **kwargs):
        assert not context.cancel_event.is_set()
        led.end_team(eid, "talk", "run_cancelled", "other-attempt")
        return real_ask(context, led, wait_id, **kwargs)

    def settled(self, wait, state, decision):
        called.append(state)
        return real_settled(self, wait, state, decision)

    monkeypatch.setattr(host_module, "ask_owner_for_wait", closed_meanwhile)
    monkeypatch.setattr(PiHost, "_settled_meanwhile", settled)
    assert pw.approve(pw_run.client, eid, wait["gate_name"], event_id=wait["ask_event_id"],
                      response="look once more").status_code == 200
    reason = stopped(pw_run, eid, 2, "talk")
    assert called == ["cancelled"], "the real _settled_meanwhile ending ran"
    assert reason == "cancelled", "E18's existing run-list sentence is unchanged"
    starts = len(sup.FakeBox.STARTS)
    resume_starts_none(pw_run, eid, 3, reason)
    assert len(sup.FakeBox.STARTS) == starts


class ScriptedNode(Node):
    """Controlled nodes exercise the scheduler's concurrent/nested cases, not Pi itself."""

    def __init__(self, name, run, **config):
        super().__init__(NodeConfig(name=name, **config))
        self.script = run

    def run(self, input_data, context):
        return self.script(context)


def test_sw86_a_running_sibling_finishes_but_its_next_nested_step_never_starts(pw_run):
    from dataclasses import replace

    from temper_ai.checkpoint.service import CheckpointService
    from temper_ai.observability import recorder
    from temper_ai.shared.types import ExecutionContext
    from temper_ai.stage.stage_node import StageNode

    entered, stop_visible = threading.Event(), threading.Event()
    ran: list[str] = []

    def stop(context):
        assert entered.wait(5), "sibling already running"
        return NodeResult(status=Status.CANCELLED, error="stopped at the pause after round 1")

    def running(context):
        entered.set()
        assert stop_visible.wait(5), "stop was visible before the parallel batch joined"
        ran.append("running")
        assert not context.cancel_event.is_set()
        return NodeResult(status=Status.FAILED, error="an already-running sibling broke")

    talk = ScriptedNode("talk", stop)
    talk.cancelled_ends_stage = True
    first = ScriptedNode("running", running)
    next_ = ScriptedNode("next", lambda context: ran.append("next") or NodeResult(status=Status.COMPLETED),
                         depends_on=["running"], run_after_failure=True, gate=True)
    side = StageNode(NodeConfig(name="side", type="stage"), [first, next_])
    context = ExecutionContext(run_id="sw86_nested", workflow_name="sw86_nested",
                               node_path="", agent_name="", event_recorder=recorder, tool_executor=None,
                               checkpoint_service=CheckpointService("sw86_nested"),
                               cancel_event=threading.Event(), failure_policy=FailurePolicy())
    # Signal only once the shared RunStop records cancellation, without timing/sleep races.
    from temper_ai.stage.failure import RunStop
    stop_state = RunStop()
    real_note = stop_state.note_cancelled

    def note(path, reason):
        real_note(path, reason)
        stop_visible.set()

    stop_state.note_cancelled = note
    context = replace(context, run_stop=stop_state)
    result = execute_graph([talk, side], {}, context, graph_name="sw86_nested", is_workflow=True)
    assert result.status == Status.CANCELLED
    assert result.error == "stopped at the pause after round 1"
    assert ran == ["running"]
    assert result.node_results["side"].node_results["next"].status == Status.SKIPPED
    assert result.node_results["side"].node_results["next"].error == (
        "not started: the run was stopped at 'talk'")


@pytest.mark.parametrize("mode", ["hold", "cleanup"])
def test_sw86_self_stop_keeps_the_run_neutral_even_after_an_earlier_sibling_failure(
    pw_run, monkeypatch, mode,
):
    from temper_ai.observability import recorder
    from temper_ai.shared.types import ExecutionContext
    from temper_ai.stage.failure import RunStop

    started = threading.Event()
    failed = threading.Event()
    original = RunStop.note_failure
    observed = []

    def record_failure(stop, path, reason):
        original(stop, path, reason)
        if path == "side.fail":
            failed.set()

    def stopped(context):
        started.set()
        assert failed.wait(5), "the failure was recorded before the self-stop"
        observed.append((context.run_stop.kind, context.run_stop.path))
        return NodeResult(status=Status.CANCELLED, error="stopped at the pause")

    def broken(context):
        assert started.wait(5), "the Pi-shaped sibling had already started"
        return NodeResult(status=Status.FAILED, error="an earlier sibling failure")

    from temper_ai.stage.stage_node import StageNode
    child = ScriptedNode("fail", broken)
    child.fails_stage = True
    side = StageNode(NodeConfig(name="side", type="stage"), [child])

    talk = ScriptedNode("talk", stopped)
    talk.cancelled_ends_stage = True
    after = ScriptedNode("after", lambda context: pytest.fail("a later report ran"),
                        depends_on=["side"], run_after_failure=True)
    monkeypatch.setattr(RunStop, "note_failure", record_failure)
    context = ExecutionContext(run_id="sw86_earlier_failure", workflow_name="earlier_failure",
        node_path="", agent_name="", tool_executor=None, event_recorder=recorder,
        cancel_event=threading.Event(), failure_policy=FailurePolicy(mode=mode))
    result = execute_graph([talk, side, after], {}, context, is_workflow=True)
    assert observed == [("failed", "side.fail")]
    assert result.status == Status.CANCELLED
    assert result.error == "stopped at the pause"
    assert result.node_results["side"].status == Status.FAILED
    assert result.node_results["side"].node_results["fail"].error == "an earlier sibling failure"
    assert result.node_results["after"].status == Status.SKIPPED
    assert result.node_results["after"].error == "not started: the run was stopped at 'talk'"
    assert not context.cancel_event.is_set()


def test_sw86_multiple_self_stops_keep_the_first_source_reason_and_both_results(pw_run, monkeypatch):
    from temper_ai.checkpoint.service import CheckpointService
    from temper_ai.observability import recorder
    from temper_ai.shared.types import ExecutionContext
    from temper_ai.stage.failure import RunStop

    entered, first_recorded = threading.Event(), threading.Event()
    original = RunStop.note_cancelled

    def note(stop, path, reason):
        original(stop, path, reason)
        if path == "first":
            first_recorded.set()

    def first(context):
        assert entered.wait(5)
        return NodeResult(status=Status.CANCELLED, error="first pause stop", cost_usd=2)

    def second(context):
        entered.set()
        assert first_recorded.wait(5)
        return NodeResult(status=Status.CANCELLED, error="later stalled stop", cost_usd=3)

    first_node, second_node = ScriptedNode("first", first), ScriptedNode("second", second)
    first_node.cancelled_ends_stage = second_node.cancelled_ends_stage = True
    next_ = ScriptedNode("next", lambda context: pytest.fail("another step started"),
                         depends_on=["first", "second"], run_after_failure=True, gate=True)
    cp = CheckpointService("sw86_multiple_stops")
    context = ExecutionContext(run_id="sw86_multiple_stops", workflow_name="multiple_stops",
        node_path="", agent_name="", tool_executor=None, event_recorder=recorder,
        checkpoint_service=cp, cancel_event=threading.Event())
    monkeypatch.setattr(RunStop, "note_cancelled", note)
    result = execute_graph([first_node, second_node, next_], {}, context, is_workflow=True)
    assert (result.status, result.error, result.cost_usd) == (Status.CANCELLED, "first pause stop", 5)
    assert result.node_results["second"].error == "later stalled stop"
    assert cp.resume_state()["self_cancelled"] == {"path": "first", "reason": "first pause stop"}
    for _ in range(2):
        resumed_context = ExecutionContext(run_id=context.run_id, workflow_name="multiple_stops",
            node_path="", agent_name="", tool_executor=None, event_recorder=recorder,
            checkpoint_service=cp, cancel_event=threading.Event())
        # No source executes again: in particular the first one must not await a new sibling.
        first_node.script = second_node.script = lambda context: pytest.fail("a stopped source reopened")
        resumed = execute_graph([first_node, second_node, next_], {}, resumed_context,
                                is_workflow=True, initial_outputs=cp.reconstruct())
        assert (resumed.status, resumed.error, resumed.cost_usd) == (Status.CANCELLED, "first pause stop", 5)
        assert resumed.node_results["second"].error == "later stalled stop"
        assert resumed.node_results["next"].status == Status.SKIPPED


def test_sw86_resume_cannot_start_a_skipped_step_moved_before_the_stopped_source(pw_run):
    from temper_ai.checkpoint.service import CheckpointService
    from temper_ai.observability import recorder
    from temper_ai.shared.types import ExecutionContext

    cp = CheckpointService("sw86_changed_graph")
    cp.save_node_completed("talk", NodeResult(status=Status.CANCELLED, error="stopped at the pause",
        metadata={"self_cancelled": {"path": "talk", "reason": "stopped at the pause"}}))
    ran: list[str] = []
    earlier = ScriptedNode("earlier", lambda context: ran.append("earlier") or NodeResult(
        status=Status.COMPLETED), run_after_failure=True, gate=True, undoes=["brief"])
    talk = ScriptedNode("talk", lambda context: pytest.fail("the ended source ran again"),
                        depends_on=["earlier"])
    talk.cancelled_ends_stage = True
    context = ExecutionContext(run_id="sw86_changed_graph", workflow_name="changed_graph",
        node_path="", agent_name="", tool_executor=None, event_recorder=recorder,
        checkpoint_service=cp, cancel_event=threading.Event(), failure_policy=FailurePolicy())
    result = execute_graph([earlier, talk], {}, context, is_workflow=True, initial_outputs={})
    assert result.status == Status.CANCELLED
    assert result.error == "stopped at the pause"
    assert result.node_results["earlier"].status == Status.SKIPPED
    assert not ran
    assert cp.resume_state()["self_cancelled"]["reason"] == "stopped at the pause"


@pytest.mark.parametrize("topology", ["replacement", "missing", "renamed", "nested"])
def test_sw86_changed_topology_and_repeated_resumes_start_no_new_work(pw_run, topology):
    from temper_ai.checkpoint.service import CheckpointService
    from temper_ai.observability import recorder
    from temper_ai.shared.types import ExecutionContext
    from temper_ai.stage.stage_node import StageNode

    cp = CheckpointService("sw86_topology")
    source = "talk.child" if topology == "nested" else "talk"
    cp.save_node_completed(source, NodeResult(status=Status.CANCELLED, error="original pause stop",
        cost_usd=7, metadata={"self_cancelled": {"path": source, "reason": "original pause stop"}}))
    def forbidden(context):
        pytest.fail("changed config started model/tool work or opened a new wait")
    fresh = ScriptedNode("fresh", forbidden, gate=True, run_after_failure=True, undoes=["setup"])
    if topology == "replacement":
        nodes = [ScriptedNode("talk", forbidden), fresh]  # ordinary replacement at the same path
    elif topology == "missing":
        nodes = [fresh]  # no source at all
    elif topology == "renamed":
        nodes = [ScriptedNode("new_talk", forbidden, renamed_from=["talk"]), fresh]
    else:
        nodes = [StageNode(NodeConfig(name="talk", type="stage"),
                           [ScriptedNode("child", forbidden), fresh])]
    for _ in range(2):
        context = ExecutionContext(run_id="sw86_topology", workflow_name="changed_topology",
            node_path="", agent_name="", tool_executor=None, event_recorder=recorder,
            checkpoint_service=cp, cancel_event=threading.Event())
        result = execute_graph(nodes, {}, context, is_workflow=True, initial_outputs=cp.reconstruct())
        assert (result.status, result.error) == (Status.CANCELLED, "original pause stop")
        if topology == "nested":
            assert result.node_results["talk"].status == Status.CANCELLED
            assert result.node_results["talk"].node_results["fresh"].status == Status.SKIPPED
            assert result.cost_usd == 7
        else:
            assert result.node_results["fresh"].status == Status.SKIPPED
        assert cp.resume_state()["self_cancelled"] == {"path": source, "reason": "original pause stop"}
        saved = cp.self_cancelled_result(source)
        assert saved.cost_usd == 7
        assert saved.metadata["self_cancelled"] == {"path": source, "reason": "original pause stop"}
    cp.save_node_reset(source)
    assert cp.resume_state()["self_cancelled"]["reason"] == "original pause stop"


def test_sw86_pi_source_reconciliation_never_enters_a_revised_producer_or_gate(pw_run, monkeypatch):
    from temper_ai.checkpoint.service import CheckpointService
    from temper_ai.observability import recorder
    from temper_ai.shared.types import ExecutionContext
    from temper_ai.stage.agent_node import AgentNode

    cp = CheckpointService("sw86_pi_reconciliation")
    marker = {"path": "talk", "reason": "original settings stop"}
    cp.save_node_completed("talk", NodeResult(status=Status.CANCELLED, error=marker["reason"],
        cost_usd=7, total_tokens=19, metadata={"self_cancelled": marker}))
    def forbidden(*args, **kwargs):
        pytest.fail("resumed Pi entered settings, tools, turns or a new wait")
    monkeypatch.setattr(PiHost, "_run", forbidden)
    # Revised config would fail validation or ask for a new gate if the producer entered.
    talk = AgentNode(NodeConfig(name="talk", gate=True),
                     {"name": "revised", "type": "pi", "role": "missing", "thinking": "high"})
    after = ScriptedNode("after", forbidden, depends_on=["talk"], run_after_failure=True)
    for _ in range(2):
        context = ExecutionContext(run_id="sw86_pi_reconciliation", workflow_name="reconcile",
            node_path="", agent_name="", tool_executor=None, event_recorder=recorder,
            checkpoint_service=cp, cancel_event=threading.Event())
        result = execute_graph([talk, after], {}, context, is_workflow=True, initial_outputs={})
        assert (result.status, result.error, result.cost_usd, result.total_tokens) == (
            Status.CANCELLED, marker["reason"], 7, 19)
        assert result.node_results["after"].status == Status.SKIPPED
        assert not [e for e in sup.events(context.run_id, event_type="stage.started")
                    if (e.get("data") or {}).get("gate_status")]
        assert not context.cancel_event.is_set()


def test_sw86_failed_state_only_reconciliation_cannot_replace_the_saved_outcome(pw_run, monkeypatch):
    from temper_ai.checkpoint.service import CheckpointService
    from temper_ai.observability import recorder
    from temper_ai.shared.types import ExecutionContext

    cp = CheckpointService("sw86_reconcile")
    marker = {"path": "talk", "reason": "original pause stop"}
    cp.save_node_completed("talk", NodeResult(status=Status.CANCELLED, error=marker["reason"],
                                            metadata={"self_cancelled": marker}))
    # A failed inspection of persisted state, not permission to run the producer/agent again.
    monkeypatch.setattr(cp, "self_cancelled_result", lambda path: (
        NodeResult(status=Status.FAILED, error="saved source unavailable",
                   metadata={"self_cancelled": marker}) if path == "talk" else None))
    talk = ScriptedNode("talk", lambda context: pytest.fail("a stopped source ran"))
    after = ScriptedNode("after", lambda context: pytest.fail("a report ran"),
                        depends_on=["talk"], run_after_failure=True, gate=True)
    context = ExecutionContext(run_id="sw86_reconcile", workflow_name="reconcile",
        node_path="", agent_name="", tool_executor=None, event_recorder=recorder,
        checkpoint_service=cp, cancel_event=threading.Event())
    result = execute_graph([talk, after], {}, context, is_workflow=True, initial_outputs={})
    assert (result.status, result.error) == (Status.CANCELLED, "original pause stop")
    assert result.node_results["talk"].error == "saved source unavailable"
    assert node_events(context.run_id, "talk")[-1]["status"] == "failed"
    assert result.node_results["after"].status == Status.SKIPPED
    assert cp.resume_state()["self_cancelled"] == marker


@pytest.mark.parametrize("mode", ["hold", "cleanup"])
def test_sw86_without_a_self_stop_keeps_existing_failure_policy(pw_run, mode):
    from temper_ai.observability import recorder
    from temper_ai.shared.types import ExecutionContext

    ran = []
    fail = ScriptedNode("fail", lambda context: NodeResult(status=Status.FAILED, error="broken"))
    report = ScriptedNode("report", lambda context: ran.append("report") or NodeResult(
        status=Status.COMPLETED), depends_on=["fail"], run_after_failure=True)
    cleanup = ScriptedNode("cleanup", lambda context: ran.append("cleanup") or NodeResult(
        status=Status.COMPLETED), depends_on=["report"], run_after_failure=True, undoes=["setup"])
    context = ExecutionContext(run_id="sw86_ordinary_failure", workflow_name="ordinary_failure",
        node_path="", agent_name="", tool_executor=None, event_recorder=recorder,
        cancel_event=threading.Event(), failure_policy=FailurePolicy(mode=mode))
    result = execute_graph([fail, report, cleanup], {}, context, is_workflow=True)
    assert result.status == Status.FAILED
    assert context.run_stop.kind == "failed"
    assert context.run_stop.path == "fail"
    assert ran == (["report", "cleanup"] if mode == "cleanup" else ["report"])
    assert not context.cancel_event.is_set()


@pytest.mark.parametrize("qualified,signal", [(False, False), (True, True)])
def test_sw86_does_not_treat_an_unqualified_or_run_signal_cancel_as_a_self_stop(
        pw_run, qualified, signal):
    from temper_ai.checkpoint.service import CheckpointService
    from temper_ai.observability import recorder
    from temper_ai.shared.types import ExecutionContext
    from temper_ai.stage.failure import RunStop

    flag = threading.Event()
    if signal:
        flag.set()
    cp = CheckpointService("sw86_not_a_self_stop")
    stop = RunStop()
    context = ExecutionContext(run_id="sw86_not_a_self_stop", workflow_name="plain",
        node_path="", agent_name="", tool_executor=None, event_recorder=recorder,
        checkpoint_service=cp, cancel_event=flag, run_stop=stop)
    node = ScriptedNode("talk", lambda context: NodeResult(status=Status.CANCELLED))
    node.cancelled_ends_stage = qualified
    from temper_ai.stage.executor import _record_outcome
    _record_outcome(node, NodeResult(status=Status.CANCELLED), "", context, cp)
    assert not stop.stopped
    assert "self_cancelled" not in cp.resume_state()


@pytest.mark.parametrize("gated", [False, True])
def test_sw86_rechecks_the_same_door_before_work_or_opening_a_wait(pw_run, monkeypatch, gated):
    import temper_ai.stage.executor as ex
    from temper_ai.observability import recorder
    from temper_ai.shared.types import ExecutionContext
    from temper_ai.stage.failure import RunStop

    stop = RunStop()
    context = ExecutionContext(run_id="sw86_gate", workflow_name="gate", node_path="",
        agent_name="", tool_executor=None, event_recorder=recorder, run_stop=stop)
    gate = ScriptedNode("approval", lambda context: pytest.fail("stopped agent ran"), gate=gated)
    real_inputs = ex._resolve_inputs

    def inputs(*args, **kwargs):
        stop.note_cancelled("talk", "stopped at the pause")
        return real_inputs(*args, **kwargs)

    monkeypatch.setattr(ex, "_resolve_inputs", inputs)
    monkeypatch.setattr(ex, "_wait_for_gate", lambda *a, **k: pytest.fail("opened a stopped wait"))
    result = ex._execute_single_node(gate, {}, {}, context, "graph")
    assert result.status == Status.SKIPPED
    assert result.error == "not started: the run was stopped at 'talk'"
    assert len(node_events("sw86_gate", "approval")) == 1


@pytest.mark.parametrize("park", [False, True])
def test_sw86_a_gate_already_parked_cannot_keep_the_run_waiting_or_turn_it_failed(
        pw_run, monkeypatch, park):
    import temper_ai.stage.executor as ex
    from temper_ai.checkpoint.service import CheckpointService
    from temper_ai.observability import recorder
    from temper_ai.shared.types import ExecutionContext
    from temper_ai.stage.exceptions import RunParked

    opened = threading.Event()
    real_wait = ex._wait_for_gate
    real_approval = ex._wait_for_approval

    def approval(*args, **kwargs):
        opened.set()
        return real_approval(*args, **kwargs)

    def waiting(*args, **kwargs):
        try:
            return real_wait(*args, **kwargs)
        except RunParked:
            opened.set()
            raise

    def cancelled(context):
        assert opened.wait(5), "the other gate parked first"
        assert not context.cancel_event.is_set()
        return NodeResult(status=Status.CANCELLED, error="stopped at the pause after round 1")

    talk = ScriptedNode("talk", cancelled)
    talk.cancelled_ends_stage = True
    gate = ScriptedNode("approval", lambda context: pytest.fail("a parked gate ran"), gate=True)
    audit = ScriptedNode("audit", lambda context: pytest.fail("a dependent ran"), depends_on=["talk"])
    next_ = ScriptedNode("next", lambda context: pytest.fail("the gate's dependent ran"),
                         depends_on=["approval"])
    context = ExecutionContext(run_id="sw86_parked_gate", workflow_name="parked_gate", node_path="",
        agent_name="", tool_executor=None, event_recorder=recorder, park_at_gates=park,
        checkpoint_service=CheckpointService("sw86_parked_gate"), cancel_event=threading.Event())
    monkeypatch.setattr(ex, "_wait_for_gate", waiting)
    monkeypatch.setattr(ex, "_wait_for_approval", approval)
    result = execute_graph([talk, gate, audit, next_], {}, context, is_workflow=True)
    assert result.status == Status.CANCELLED
    assert result.error == "stopped at the pause after round 1"
    assert not context.cancel_event.is_set()
    assert result.node_results["audit"].status == result.node_results["next"].status == Status.SKIPPED
    assert len(node_events(context.run_id, "audit")) == len(node_events(context.run_id, "next")) == 1
    assert context.checkpoint_service.resume_state()["self_cancelled"]["path"] == "talk"
    (wait,) = recorder.gate_events(context.run_id)
    assert wait["status"] == "rejected"
    assert not wait["data"].get("gate_used_at")
    resumed_context = ExecutionContext(run_id=context.run_id, workflow_name="parked_gate",
        node_path="", agent_name="", tool_executor=None, event_recorder=recorder,
        park_at_gates=park, checkpoint_service=context.checkpoint_service,
        cancel_event=threading.Event())
    resumed = execute_graph([talk, gate, audit, next_], {}, resumed_context, is_workflow=True,
                            initial_outputs=context.checkpoint_service.reconstruct())
    assert (resumed.status, resumed.error) == (Status.CANCELLED, result.error)
    (same_wait,) = recorder.gate_events(context.run_id)
    assert same_wait["id"] == wait["id"]
    assert same_wait["status"] == "rejected"
    assert not same_wait["data"].get("gate_used_at")


def test_sw86_a_concurrent_gate_answer_stays_visible_but_unconsumed(pw_run, monkeypatch):
    import temper_ai.stage.executor as ex
    from temper_ai.observability import recorder
    from temper_ai.shared.types import ExecutionContext
    from temper_ai.stage.failure import RunStop

    stop = RunStop()
    context = ExecutionContext(run_id="sw86_answer", workflow_name="concurrent_answer",
        node_path="", agent_name="", tool_executor=None, event_recorder=recorder,
        cancel_event=threading.Event(), run_stop=stop)
    gate = ScriptedNode("approval", lambda context: pytest.fail("the gate ran"), gate=True)
    after = ScriptedNode("after", lambda context: pytest.fail("the dependent ran"),
                         depends_on=["approval"], run_after_failure=True)

    def answer_then_stop(gate_event, event_recorder, context, event_id, path):
        won, _ = recorder.decide_event(event_id, expect=("waiting",), status="approved",
            data={"gate_status": "approved", "gate_response": {"text": "go on"}})
        assert won
        stop.note_cancelled("talk", "stopped at the pause")

    monkeypatch.setattr(ex, "_wait_for_approval", answer_then_stop)
    result = execute_graph([gate, after], {}, context, is_workflow=True)
    assert (result.status, result.error) == (Status.CANCELLED, "stopped at the pause")
    assert all(result.node_results[n].status == Status.SKIPPED for n in ("approval", "after"))
    (wait,) = recorder.gate_events(context.run_id)
    assert wait["status"] == "approved", "the stop must not overwrite the owner's answer"
    assert wait["data"]["gate_response"] == {"text": "go on"}
    assert not wait["data"].get("gate_used_at")
    assert not context.cancel_event.is_set()
