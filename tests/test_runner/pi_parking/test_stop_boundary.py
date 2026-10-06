"""Sealed regressions for unreadable stop authority and delayed producer entry.

All effects are synthetic. The Pi-parking fixtures prohibit real model/tool/box
work, and the inherited backend fixture asserts SQLite/throwaway PostgreSQL.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from temper_ai.checkpoint.service import CheckpointService
from temper_ai.observability import recorder
from temper_ai.observability.event_recorder import EventRecorder
from temper_ai.pi_agent.host import PiHost
from temper_ai.shared.types import ExecutionContext, NodeResult, Status
from temper_ai.stage import executor as ex
from temper_ai.stage.agent_node import AgentNode
from temper_ai.stage.failure import FailurePolicy, RunStop
from temper_ai.stage.models import NodeConfig
from temper_ai.stage.stage_node import StageNode
from tests.test_runner.pi_parking.test_stop_starts_nothing import (
    ScriptedNode,
    _stop_backend,  # noqa: F401 -- inherited two-backend fixture
    _test_db,  # noqa: F401 -- inherited autouse backend assertion
    node_events,
)

REASON = "synthetic original pause stop"


def context_for(cp, mode="hold", stop=None):
    return ExecutionContext(
        run_id=cp.execution_id, workflow_name="stop_boundary", node_path="",
        agent_name="", tool_executor=None, event_recorder=EventRecorder(cp.execution_id),
        checkpoint_service=cp, cancel_event=threading.Event(), run_stop=stop,
        failure_policy=FailurePolicy(mode=mode),
    )


def save_stop(cp, path="talk"):
    marker = {"path": path, "reason": REASON}
    cp.save_node_completed(path, NodeResult(
        status=Status.CANCELLED, error=REASON, output="synthetic saved output",
        cost_usd=7, total_tokens=19, metadata={"self_cancelled": marker},
    ))
    return marker


def forbidden(*args, **kwargs):
    pytest.fail("a stopped run entered a new producer, model, tool or owner wait")


@pytest.mark.parametrize("mode", ["hold", "cleanup"])
@pytest.mark.parametrize("topology", ["missing", "renamed", "nested"])
def test_sw86_unreadable_stop_authority_refuses_replacement_work(
        pw_run, monkeypatch, mode, topology):
    cp = CheckpointService("sw86_unreadable_authority")
    marker = save_stop(cp)
    initial_outputs = cp.reconstruct()
    read = cp.resume_state
    assert read()["self_cancelled"] == marker
    ran = []
    fresh = ScriptedNode("fresh", lambda context: ran.append("fresh") or NodeResult(
        status=Status.COMPLETED), run_after_failure=True)
    if topology == "renamed":
        nodes = [ScriptedNode("replacement", forbidden, renamed_from=["talk"]), fresh]
    elif topology == "nested":
        nodes = [StageNode(NodeConfig(name="replacement", type="stage"), [fresh])]
    else:
        nodes = [fresh]

    def unavailable():
        raise OSError("synthetic stop-marker read unavailable")

    monkeypatch.setattr(cp, "resume_state", unavailable)
    for _ in range(2):
        # A refusal precedes even the new attempt's event; unreadable is never empty.
        with pytest.raises(OSError, match="synthetic stop-marker read unavailable"):
            ex.execute_graph(nodes, {}, context_for(cp, mode), is_workflow=True,
                             initial_outputs=initial_outputs)
        assert ran == []
        assert not recorder.gate_events(cp.execution_id)
        assert read()["self_cancelled"] == marker
        assert read()["self_cancelled_results"]["talk"].cost_usd == 7


@pytest.mark.parametrize("mode", ["hold", "cleanup"])
@pytest.mark.parametrize("phase", ["inspection", "pi_reconciliation", "stage_reconciliation",
                                   "stage_child_only"])
def test_sw86_throwing_reconciliation_retains_cancelled_state_and_costs(
        pw_run, monkeypatch, caplog, mode, phase):
    cp = CheckpointService("sw86_inspection_fault")
    nested = phase.startswith("stage_")
    marker = save_stop(cp, "talk.child" if nested else "talk")
    if phase == "stage_reconciliation":
        cp.save_node_completed("talk", NodeResult(
            status=Status.CANCELLED, error=REASON, cost_usd=7, total_tokens=19,
            metadata={"self_cancelled": marker},
        ))
    calls = []

    def unavailable(*args, **kwargs):
        calls.append("inspection")
        raise OSError("synthetic ended-record inspection unavailable")

    if nested:
        talk = StageNode(NodeConfig(name="talk", type="stage", gate=True,
                                    condition="False"), [ScriptedNode("child", forbidden)])
        monkeypatch.setattr(talk, "run", unavailable)
    elif phase == "pi_reconciliation":
        talk = AgentNode(NodeConfig(name="talk", gate=True),
                         {"name": "revised", "type": "pi", "role": "missing"})
        monkeypatch.setattr(PiHost, "_run", forbidden)
        monkeypatch.setattr(talk, "run", unavailable)
    else:
        talk = ScriptedNode("talk", forbidden, gate=True)
        monkeypatch.setattr(cp, "self_cancelled_result", unavailable)
    report = ScriptedNode("report", forbidden, depends_on=["talk"],
                          run_after_failure=True, gate=True)
    for _ in range(2):
        context = context_for(cp, mode)
        result = ex.execute_graph([talk, report], {}, context, is_workflow=True, initial_outputs={})
        assert (result.status, result.error, result.cost_usd, result.total_tokens) == (
            Status.CANCELLED, REASON, 7, 19)
        assert result.node_results["talk"].status == Status.CANCELLED
        assert result.node_results["report"].status == Status.SKIPPED
        assert result.node_results["report"].error == (
            f"not started: the run was stopped at '{marker['path']}'")
        assert not recorder.gate_events(cp.execution_id)
        assert not context.cancel_event.is_set()
        assert cp.resume_state()["self_cancelled"] == marker
        assert node_events(cp.execution_id, "talk")[-1]["data"]["reconciliation_error"] == (
            "synthetic ended-record inspection unavailable")
    assert calls == ["inspection", "inspection"], "no recursive inspection from _end_graph"
    assert "retaining its cancellation" in caplog.text
    # Neither diagnostics nor a later resume can replace the originally paid-for row.
    source = cp.resume_state()["self_cancelled_results"][marker["path"]]
    assert (source.status, source.error, source.cost_usd, source.total_tokens) == (
        Status.CANCELLED, REASON, 7, 19)


@pytest.mark.parametrize("mode", ["hold", "cleanup"])
def test_sw86_ending_a_faulted_attempt_does_not_retry_the_inspection_door(
        pw_run, monkeypatch, mode):
    cp = CheckpointService("sw86_end_graph_fault")
    marker = save_stop(cp)
    calls = []

    def unavailable(*args, **kwargs):
        calls.append("inspection")
        raise OSError("synthetic ended-record inspection unavailable")

    def batch_fault(*args, **kwargs):
        raise OSError("synthetic graph reconciliation unavailable")

    monkeypatch.setattr(cp, "self_cancelled_result", unavailable)
    monkeypatch.setattr(ex, "_run_batches", batch_fault)
    talk = ScriptedNode("talk", forbidden)
    report = ScriptedNode("report", forbidden, depends_on=["talk"],
                          run_after_failure=True, gate=True)
    result = ex.execute_graph([talk, report], {}, context_for(cp, mode),
                              is_workflow=True, initial_outputs={})
    assert (result.status, result.error, result.cost_usd, result.total_tokens) == (
        Status.CANCELLED, REASON, 7, 19)
    assert result.node_results["report"].status == Status.SKIPPED
    assert calls == []
    assert cp.resume_state()["self_cancelled"] == marker
    assert not recorder.gate_events(cp.execution_id)


@pytest.mark.parametrize("mode", ["hold", "cleanup"])
@pytest.mark.parametrize("phase,gated", [
    ("record", False), ("record", True),
    ("running_update", False), ("running_update", True),
    ("timeout_submission", False), ("timeout_submission", True),
    ("input_resolution", False), ("input_resolution", True),
    ("gate_response", True), ("gate_used_record", True),
])
def test_sw86_stop_winning_delayed_admission_never_enters_the_producer(
        pw_run, monkeypatch, mode, phase, gated):
    reached_preflight, stop_visible = threading.Event(), threading.Event()
    ran = []
    stop = RunStop()
    cp = CheckpointService("sw86_start_boundary")
    context = context_for(cp, mode, stop)
    note = stop.note_cancelled
    events = context.event_recorder
    record, update, event_data = events.record, events.update_event, events.event_data
    resolve, submit = ex._resolve_inputs, ThreadPoolExecutor.submit
    fresh_event = []

    def delayed():
        reached_preflight.set()
        assert stop_visible.wait(5), "stop must win while fresh is still preflight"

    def note_stop(path, reason):
        note(path, reason)
        stop_visible.set()

    def recording(event_type, *args, **kwargs):
        data = kwargs.get("data") or {}
        preflight = data.get("name") == "fresh" and data.get("type") and not (
            data.get("gate") or data.get("skip_reason"))
        if phase == "record" and preflight:
            delayed()
        event_id = record(event_type, *args, **kwargs)
        if preflight:
            fresh_event.append(event_id)
        return event_id

    def updating(event_id, *args, **kwargs):
        data = kwargs.get("data") or {}
        if phase == "running_update" and event_id in fresh_event and kwargs.get("status") == "running":
            delayed()
        if phase == "gate_used_record" and data.get("gate_used_at"):
            delayed()
        return update(event_id, *args, **kwargs)

    def resolving(node, *args, **kwargs):
        if phase == "input_resolution" and node.name == "fresh":
            delayed()
        return resolve(node, *args, **kwargs)

    def submitting(pool, fn, *args, **kwargs):
        if phase == "timeout_submission" and getattr(fn, "__name__", "") == "enter_producer":
            delayed()
        return submit(pool, fn, *args, **kwargs)

    def approving(gate_event, event_recorder, ctx, event_id, path):
        won, _ = recorder.decide_event(event_id, expect=("waiting",), status="approved",
            data={"gate_status": "approved", "gate_response": {"text": "synthetic go on"}})
        assert won

    def reading_event(event_id):
        if phase == "gate_response":
            delayed()
        return event_data(event_id)

    def stopped_source(ctx):
        assert reached_preflight.wait(5), "fresh reached the controlled admission gap"
        return NodeResult(status=Status.CANCELLED, error=REASON, cost_usd=1, total_tokens=2)

    talk = ScriptedNode("talk", stopped_source)
    talk.cancelled_ends_stage = True
    fresh = ScriptedNode("fresh", lambda ctx: ran.append("fresh") or NodeResult(
        status=Status.COMPLETED), gate=gated, type="agent", undoes=["setup"],
        run_after_failure=True, timeout_seconds=20 if phase == "timeout_submission" else None)
    after = ScriptedNode("after", forbidden, depends_on=["fresh"], gate=True,
                         run_after_failure=True, undoes=["setup"])
    monkeypatch.setattr(stop, "note_cancelled", note_stop)
    monkeypatch.setattr(events, "record", recording)
    monkeypatch.setattr(events, "update_event", updating)
    monkeypatch.setattr(events, "event_data", reading_event)
    monkeypatch.setattr(ex, "_resolve_inputs", resolving)
    monkeypatch.setattr(ex, "_wait_for_approval", approving)
    monkeypatch.setattr(ThreadPoolExecutor, "submit", submitting)
    result = ex.execute_graph([talk, fresh, after], {}, context, is_workflow=True)
    assert reached_preflight.is_set() and stop_visible.is_set()
    assert ran == [], "a producer began after the self-stop won admission"
    assert (result.status, result.error, result.cost_usd, result.total_tokens) == (
        Status.CANCELLED, REASON, 1, 2)
    for name in ("fresh", "after"):
        assert result.node_results[name].status == Status.SKIPPED
        bodies = [e for e in node_events(cp.execution_id, name) if not e["data"].get("gate")]
        assert len(bodies) == 1, "a rejected provisional start becomes the sole skip record"
        assert bodies[0]["status"] == "skipped"
        assert bodies[0]["data"]["skip_reason"] == "not started: the run was stopped at 'talk'"
    waits = recorder.gate_events(cp.execution_id)
    assert not [e for e in waits if e["status"] == "waiting"]
    assert not [e for e in waits if (e.get("data") or {}).get("name") == "after"]
    if waits:
        assert len(waits) == 1 and waits[0]["status"] == "approved"
        assert waits[0]["data"]["gate_response"] == {"text": "synthetic go on"}
        assert not waits[0]["data"].get("gate_used_at"), "a skipped producer consumed no answer"
    assert not context.cancel_event.is_set()
    assert not cp.resume_state()["undone"]
    resumed = ex.execute_graph([talk, fresh, after], {}, context_for(cp, mode),
                               is_workflow=True, initial_outputs=cp.reconstruct())
    assert (resumed.status, resumed.error) == (Status.CANCELLED, REASON)
    assert ran == [] and cp.resume_state()["self_cancelled"]["path"] == "talk"
