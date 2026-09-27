"""A node renamed in the workflow file keeps what the run's checkpoints hold under its old name.

A resume or fork loads the workflow as it is now; the checkpoints name nodes as they were. The EPD
loop renamed its plan stage `tasks` to `plan` (queue task 15, 2026-09-27): without `renamed_from`,
every run from before the rename would plan again on resume -- an hour of model calls and a
different plan under a build that was made from the first one -- and a run parked at its merge
gate would plan again before the gate.
"""

import logging
import threading

from temper_ai.checkpoint.service import CheckpointService
from temper_ai.shared.types import NodeResult, Status
from temper_ai.stage.models import NodeConfig
from temper_ai.stage.restore import Restore
from temper_ai.stage.stage_node import StageNode
from tests.test_stage.test_executor import _make_agent_node
from tests.test_stage.test_resume_inside_a_stage import (
    STEPS,
    _graph,
    _ran,
    _run,
    _stop_after,
)


def _renamed_graph(*, stage: str = "build", renamed_stage: bool = False):
    """The same run after the rename: `tasks` is now `plan` (renamed_from tasks), and the build
    depends on it. ``renamed_stage`` also renames the build (to ``stage``), the node that was
    running when the run stopped."""
    plan = _make_agent_node("plan")
    plan.config.renamed_from = ["tasks"]
    steps = [_make_agent_node(s, depends_on=[STEPS[i - 1]] if i else None) for i, s in enumerate(STEPS)]
    build = StageNode(NodeConfig(name=stage, depends_on=["plan"],
                                 renamed_from=["build"] if renamed_stage else None), steps)
    ship = _make_agent_node("ship", depends_on=[stage])
    return [plan, build, ship], {n.name: n for n in [plan, ship, *steps]}


def _interrupted(run_id):
    """The first attempt, under the old names: tasks, then s1-s3 of the build, then a stop."""
    cp = CheckpointService(run_id)
    cancel = threading.Event()
    nodes, by_name = _graph()
    _stop_after(by_name["s3"], cancel)
    first, _ = _run(nodes, run_id, cp, cancel)
    assert first.status == Status.CANCELLED
    assert _ran(by_name) == {"tasks", "s1", "s2", "s3"}
    return cp


class TestAResumeAfterARename:
    def test_the_renamed_node_is_not_run_again(self):
        cp = _interrupted("run-renamed")

        nodes, by_name = _renamed_graph()
        result, ctx = _run(nodes, "run-renamed", cp, initial_outputs=cp.reconstruct())

        assert result.status == Status.COMPLETED
        assert _ran(by_name) == {"s4", "s5", "ship"}, "the plan ran again under its new name"
        assert result.node_results["plan"].output == "ok", "what the plan left is read under the new name"

    def test_a_fork_does_the_same(self):
        """The EPD driver's resume: a new run, forked from the old one's checkpoints."""
        cp = _interrupted("run-renamed-fork")
        fork = CheckpointService.fork("run-renamed-fork", cp.get_latest_sequence(), "run-renamed-forked")

        nodes, by_name = _renamed_graph()
        result, _ = _run(nodes, "run-renamed-forked", fork, initial_outputs=fork.reconstruct())

        assert result.status == Status.COMPLETED
        assert _ran(by_name) == {"s4", "s5", "ship"}

    def test_a_renamed_stage_goes_on_from_its_own_last_finished_step(self):
        """The stage that was running when the run stopped keeps its finished steps too."""
        cp = _interrupted("run-renamed-stage")

        nodes, by_name = _renamed_graph(stage="make", renamed_stage=True)
        result, _ = _run(nodes, "run-renamed-stage", cp, initial_outputs=cp.reconstruct())

        assert result.status == Status.COMPLETED
        assert _ran(by_name) == {"s4", "s5", "ship"}
        assert set(result.node_results["make"].node_results) == set(STEPS)

    def test_without_the_old_name_it_would_run_again(self):
        """What `renamed_from` is for: the same resume with the plain rename plans again."""
        cp = _interrupted("run-plain-rename")

        nodes, by_name = _renamed_graph()
        by_name["plan"].config.renamed_from = None
        _run(nodes, "run-plain-rename", cp, initial_outputs=cp.reconstruct())

        assert "plan" in _ran(by_name)


class TestRestoreRenames:
    """The move itself, without a database."""

    def _done(self, output="ok"):
        return NodeResult(status=Status.COMPLETED, output=output)

    def test_entries_under_the_old_name_and_inside_it_move_to_the_new_one(self):
        restore = Restore({"tasks": self._done("planned"), "build.s1": self._done()},
                          loops={"tasks.check": {"count": 2, "target": "tasks.lead", "feedback": None}},
                          failed=["tasks.check"])
        top = restore.claim("", {"plan": [], "build": ["plan"]}, {"plan": ["tasks"]})
        assert top.outputs == {}, "a plan with a failed step inside runs again, as before the rename"
        assert top.reset == ["plan"]
        inner = restore.claim("plan.", {"lead": [], "check": ["lead"]})
        assert inner.loop_counts == {"check->lead": 2}, "the loop's count and target follow the rename"

    def test_a_finished_renamed_node_is_restored(self):
        restore = Restore({"tasks": self._done("planned"), "build": self._done()})
        top = restore.claim("", {"plan": [], "build": ["plan"]}, {"plan": ["tasks"]})
        assert set(top.outputs) == {"plan", "build"}
        assert top.outputs["plan"].output == "planned"

    def test_the_new_name_wins_when_both_are_there(self):
        """A run resumed since the rename wrote under the new name: that is the later word."""
        restore = Restore({"tasks": self._done("old"), "plan": self._done("new")})
        top = restore.claim("", {"plan": []}, {"plan": ["tasks"]})
        assert top.outputs["plan"].output == "new"

    def test_a_graph_without_renames_claims_as_before(self):
        restore = Restore({"tasks": self._done()})
        assert set(restore.claim("", {"tasks": []}).outputs) == {"tasks"}


class TestTheConfig:
    def test_one_old_name_or_a_list(self, caplog):
        with caplog.at_level(logging.WARNING):
            one = NodeConfig.from_dict({"name": "plan", "renamed_from": "tasks"})
            two = NodeConfig.from_dict({"name": "plan", "renamed_from": ["tasks", "planning"]})
        assert one.renamed_from == ["tasks"]
        assert two.renamed_from == ["tasks", "planning"]
        assert "unknown fields" not in caplog.text

    def test_absent_by_default(self):
        assert NodeConfig.from_dict({"name": "plan"}).renamed_from is None
