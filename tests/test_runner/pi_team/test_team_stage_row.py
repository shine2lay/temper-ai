"""A team stage's row follows its team node (M2-roles P2, R2 B13), every way the node can end.

The workflow-level test (pi_parking/test_team_runs.py) proves the failed case through a real run.
Here the stage's final result is built straight from each ending, including the two a run makes
only by timing: the run cancelled under the team, and the run stopped at a failure elsewhere
before the team started (once seen as a race: the stage row showed completed). Ordinary stages
keep the tolerant rule.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from temper_ai.shared.types import Status
from temper_ai.stage.executor import _build_final_result
from temper_ai.stage.node import NodeResult


class _Recorder:
    def __init__(self) -> None:
        self.updates: list[dict] = []

    def update_event(self, event_id, status=None, data=None):
        self.updates.append({"id": event_id, "status": status, "data": data or {}})


def _node(name: str, fails_stage: bool):
    return SimpleNamespace(name=name, fails_stage=fails_stage, depends_on=[])


def _stage(results: dict[str, NodeResult], team: bool = True):
    ctx = SimpleNamespace(event_recorder=_Recorder(), run_only=None)
    nodes = [_node(name, team and name == "team") for name in ("team", *[
        n for n in results if n != "team"])]
    out = _build_final_result(nodes, results, {}, time.monotonic(), "stage-ev", ctx)
    return out, ctx.event_recorder.updates[-1]


@pytest.mark.parametrize(("team_status", "stage_status"), [
    (Status.COMPLETED, Status.COMPLETED),
    (Status.FAILED, Status.FAILED),
    (Status.CANCELLED, Status.CANCELLED),
    (Status.SKIPPED, Status.SKIPPED),
])
def test_b13_a_team_stage_row_follows_its_team_node(team_status, stage_status):
    error = None if team_status == Status.COMPLETED else {
        Status.FAILED: "design (architecture) turn 1 failed",
        Status.CANCELLED: "Run cancelled",
        Status.SKIPPED: "Run stopped: 'review/bad' failed",
    }[team_status]
    out, event = _stage({"team": NodeResult(status=team_status, error=error)})
    assert out.status == stage_status and event["status"] == stage_status.value
    if error:
        assert error in out.error and event["data"]["error"] == out.error


def test_b13_a_team_stage_never_completes_over_a_team_that_never_ran():
    out, event = _stage({})
    assert out.status == Status.FAILED and event["status"] == "failed"
    assert "team: it never ran" in out.error


def test_a_skipped_team_stage_passes_the_failure_on_downstream():
    """Its reason still ends "... failed", so a stage after it is skipped for that failure,
    never run as after a condition's skip."""
    from temper_ai.stage.executor import _skipped_for_failure

    out, _ = _stage({"team": NodeResult(status=Status.SKIPPED,
                                        error="Run stopped: 'review/bad' failed")})
    assert _skipped_for_failure(out)


def _workflow(results: dict[str, NodeResult]):
    ctx = SimpleNamespace(event_recorder=_Recorder(), run_only=None)
    nodes = [_node(name, False) for name in results]
    out = _build_final_result(nodes, results, {}, time.monotonic(), "wf-ev", ctx,
                              is_workflow=True)
    return out, ctx.event_recorder.updates[-1]


STOP = "stopped at the pause after round 2"


def test_e18_a_stage_that_ended_cancelled_by_itself_ends_the_run_cancelled_with_its_reason():
    """M3 E18: an owner's stop at a team's pause (or a Pi conversation another attempt
    cancelled) ends its stage cancelled while the run's own cancel signal is unset. Nothing
    failed, so the run ends cancelled with the stage's own reason -- not "completed", and
    never "Workflow cancelled by user"."""
    out, event = _workflow({"brief": NodeResult(status=Status.COMPLETED),
                            "build": NodeResult(status=Status.CANCELLED, error=STOP)})
    assert out.status == Status.CANCELLED and event["status"] == "cancelled"
    assert out.error == STOP and event["data"]["error"] == STOP
    assert "failed_nodes" not in event["data"]


def test_e18_a_failed_stage_beside_a_cancelled_one_still_fails_the_run():
    out, event = _workflow({"a": NodeResult(status=Status.CANCELLED, error=STOP),
                            "b": NodeResult(status=Status.FAILED, error="b broke")})
    assert out.status == Status.FAILED and event["status"] == "failed"
    assert event["data"]["failed_nodes"] == ["b"]


def test_e18_ordinary_endings_are_unchanged():
    out, event = _workflow({"a": NodeResult(status=Status.COMPLETED),
                            "b": NodeResult(status=Status.COMPLETED)})
    assert (out.status, event["status"], out.error) == (Status.COMPLETED, "completed", None)
    out, event = _workflow({"a": NodeResult(status=Status.COMPLETED),
                            "b": NodeResult(status=Status.FAILED, error="b broke")})
    assert (out.status, event["status"]) == (Status.FAILED, "failed")
    assert out.error == "1 node(s) failed: b"


MEANWHILE = ("the Pi conversation ended while the step waited for the owner (its run was "
             "cancelled)")


def _pi_step_stage(pi: NodeResult):
    ctx = SimpleNamespace(event_recorder=_Recorder(), run_only=None)
    nodes = [SimpleNamespace(name="other", fails_stage=False, depends_on=[]),
             SimpleNamespace(name="pi", fails_stage=False, cancelled_ends_stage=True,
                             depends_on=[])]
    out = _build_final_result(nodes, {"other": NodeResult(status=Status.COMPLETED), "pi": pi},
                              {}, time.monotonic(), "stage-ev", ctx)
    return out, ctx.event_recorder.updates[-1]


def test_e18_a_pi_step_another_attempt_cancelled_ends_its_stage_and_run_cancelled():
    """M3 E18: a single Pi step whose conversation another attempt ended stops cancelled with
    the run's cancel signal unset. Its stage ends cancelled with that reason (not the tolerant
    "completed"), and so does the run, never "completed"."""
    out, event = _pi_step_stage(NodeResult(status=Status.CANCELLED, error=MEANWHILE))
    assert (out.status, event["status"], out.error) == (Status.CANCELLED, "cancelled", MEANWHILE)
    run, run_event = _workflow({"first": NodeResult(status=Status.COMPLETED), "pi_stage": out})
    assert (run.status, run_event["status"], run.error) == (
        Status.CANCELLED, "cancelled", MEANWHILE)


def test_a_failed_pi_step_keeps_its_stage_tolerant_as_before():
    out, event = _pi_step_stage(NodeResult(status=Status.FAILED, error="pi broke"))
    assert (out.status, event["status"]) == (Status.COMPLETED, "completed")


def test_only_a_pi_agent_step_may_end_its_stage_cancelled(monkeypatch):
    from temper_ai import agent as agent_pkg
    from temper_ai.pi_agent.host import PiHost
    from temper_ai.stage.agent_node import AgentNode
    from temper_ai.stage.models import NodeConfig

    monkeypatch.setitem(agent_pkg.AGENT_TYPES, "pi", PiHost)
    node = NodeConfig(name="s", type="agent", agent="s")
    assert AgentNode(node, {"name": "s", "type": "pi"}).cancelled_ends_stage is True
    assert AgentNode(node, {"name": "s", "type": "llm"}).cancelled_ends_stage is False
    assert AgentNode(node, {"name": "s"}).cancelled_ends_stage is False


@pytest.mark.parametrize("lane", [Status.FAILED, Status.CANCELLED, Status.SKIPPED])
def test_other_stages_keep_the_tolerant_rule(lane):
    out, event = _stage({"team": NodeResult(status=Status.COMPLETED),
                         "bad": NodeResult(status=lane, error="bad failed")}, team=False)
    assert out.status == Status.COMPLETED and event["status"] == "completed"
