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


@pytest.mark.parametrize("lane", [Status.FAILED, Status.CANCELLED, Status.SKIPPED])
def test_other_stages_keep_the_tolerant_rule(lane):
    out, event = _stage({"team": NodeResult(status=Status.COMPLETED),
                         "bad": NodeResult(status=lane, error="bad failed")}, team=False)
    assert out.status == Status.COMPLETED and event["status"] == "completed"
