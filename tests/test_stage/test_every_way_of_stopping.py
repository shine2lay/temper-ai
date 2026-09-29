"""However a run stopped, it can be picked up: failed, stopped by hand, or cut off.

Three ways a run ends without finishing, and each leaves a different trail:

* it *failed* -- the run wrote down where it stopped, and its clean-ups are held;
* someone *stopped* it -- the executor throws, so nothing after the stop was written at all;
* it was *cut off* -- temper restarted or the box died, so there is no final event either,
  and even the step that was running has no result.

The last two look the same from the outside: the run's checkpoints simply stop. What matters
is that a resume works from what *is* written down, and never treats a step that never got its
turn as one that finished.
"""

import threading

import pytest

from temper_ai.checkpoint.service import CheckpointService
from temper_ai.shared.types import NodeResult, Status
from temper_ai.stage.executor import execute_graph
from temper_ai.stage.models import NodeConfig
from temper_ai.stage.plan import KEEP, RERUN, build_restore, resume_plan
from temper_ai.stage.stage_node import StageNode
from tests.test_stage.test_executor import _make_agent_node, _make_context


def _ctx(run_id, cp, **kw):
    kw.setdefault("cancel_event", threading.Event())
    return _make_context(run_id=run_id, checkpoint_service=cp, **kw)


def _resume(nodes, run_id, cp):
    ctx = _ctx(run_id, cp)
    restore, plan = build_restore(nodes, cp, cp.reconstruct())
    ctx.restore = restore
    result = execute_graph(nodes, {"task": "x"}, ctx, graph_name="wf", is_workflow=True,
                           initial_outputs={})
    return result, plan


class TestStoppedByHand:
    def test_what_had_finished_is_kept_and_the_rest_runs(self):
        run_id = "stop-by-hand"
        cp = CheckpointService(run_id)
        cancel = threading.Event()
        first = _make_agent_node("first")
        second = _make_agent_node("second", depends_on=["first"])
        second.run.side_effect = lambda *a, **k: cancel.set() or NodeResult(
            status=Status.CANCELLED, error="stopped")
        third = _make_agent_node("third", depends_on=["second"])
        nodes = [first, second, third]
        execute_graph(nodes, {"task": "x"}, _ctx(run_id, cp, cancel_event=cancel),
                      graph_name="wf", is_workflow=True)

        assert not third.run.called

        first.run.reset_mock()
        second.run.reset_mock()
        second.run.side_effect = None
        second.run.return_value = NodeResult(status=Status.COMPLETED, output="ok")
        result, _ = _resume(nodes, run_id, cp)

        assert not first.run.called
        assert second.run.called
        assert third.run.called
        assert result.status == Status.COMPLETED

    def test_a_step_that_never_got_its_turn_is_not_taken_for_finished(self):
        run_id = "stop-untouched"
        cp = CheckpointService(run_id)
        cancel = threading.Event()
        first = _make_agent_node("first")
        first.run.side_effect = lambda *a, **k: cancel.set() or NodeResult(
            status=Status.COMPLETED, output="ok")
        later = _make_agent_node("later", depends_on=["first"])
        nodes = [first, later]
        result = execute_graph(nodes, {"task": "x"}, _ctx(run_id, cp, cancel_event=cancel),
                               graph_name="wf", is_workflow=True)

        assert result.status == Status.CANCELLED
        plan = resume_plan(nodes, cp)

        assert plan.action_for("later") == RERUN
        assert "never finished" in plan.reason_for("later")


class TestCutOff:
    def test_a_run_with_no_ending_at_all_picks_up_where_its_writing_stops(self):
        """A crash or a restart: no workflow event, no result for the step that was running."""
        run_id = "cut-off"
        cp = CheckpointService(run_id)
        cp.save_node_completed("setup", NodeResult(status=Status.COMPLETED, output="made"))
        # "work" was running when the box died: nothing was ever written for it
        setup = _make_agent_node("setup")
        work = _make_agent_node("work", depends_on=["setup"])
        after = _make_agent_node("after", depends_on=["work"])
        nodes = [setup, work, after]

        result, plan = _resume(nodes, run_id, cp)

        assert plan.action_for("setup") == KEEP
        assert plan.action_for("work") == RERUN
        assert not setup.run.called
        assert work.run.called
        assert after.run.called
        assert result.status == Status.COMPLETED

    def test_a_stage_cut_off_half_way_keeps_the_steps_that_did_finish(self):
        run_id = "cut-off-stage"
        cp = CheckpointService(run_id)
        cp.save_node_completed("build.compile", NodeResult(status=Status.COMPLETED, output="ok"))
        compile_ = _make_agent_node("compile")
        test = _make_agent_node("test", depends_on=["compile"])
        stage = StageNode(NodeConfig(name="build"), [compile_, test])

        result, plan = _resume([stage], run_id, cp)

        assert not compile_.run.called
        assert test.run.called
        assert plan.action_for("build.compile") == KEEP
        assert result.status == Status.COMPLETED

    def test_a_run_that_wrote_nothing_at_all_starts_over(self):
        run_id = "cut-off-empty"
        cp = CheckpointService(run_id)
        first = _make_agent_node("first")
        second = _make_agent_node("second", depends_on=["first"])

        result, _ = _resume([first, second], run_id, cp)

        assert first.run.called
        assert second.run.called
        assert result.status == Status.COMPLETED


class TestAGate:
    def test_a_gate_that_was_answered_is_not_asked_again(self):
        """Its answer is part of the step's result, and the step is kept."""
        run_id = "gate-answered"
        cp = CheckpointService(run_id)
        answered = NodeResult(status=Status.COMPLETED, output="ok",
                              metadata={"gate_response": {"approved": True}})
        cp.save_node_completed("review", answered)
        review = _make_agent_node("review")
        after = _make_agent_node("after", depends_on=["review"])

        _resume([review, after], run_id, cp)

        assert not review.run.called
        assert after.run.called

    def test_a_gate_left_waiting_is_asked_again(self):
        """Nothing was written for it: a restart cut it off mid-question."""
        run_id = "gate-waiting"
        cp = CheckpointService(run_id)
        cp.save_node_completed("build", NodeResult(status=Status.COMPLETED, output="ok"))
        build = _make_agent_node("build")
        review = _make_agent_node("review", depends_on=["build"])

        _resume([build, review], run_id, cp)

        assert not build.run.called
        assert review.run.called


class TestAllThreeGiveTheSamePlan:
    @pytest.mark.parametrize("how", ["failed", "stopped", "cut off"])
    def test_the_step_that_did_not_get_through_runs_again(self, how):
        run_id = f"same-plan-{how.replace(' ', '-')}"
        cp = CheckpointService(run_id)
        cp.save_node_completed("setup", NodeResult(status=Status.COMPLETED, output="made"))
        if how == "failed":
            cp.save_node_completed("work", NodeResult(status=Status.FAILED, error="boom"))
        elif how == "stopped":
            cp.save_node_completed("work", NodeResult(status=Status.CANCELLED, error="stopped"))
        # "cut off": nothing written for work at all
        nodes = [_make_agent_node("setup"),
                 _make_agent_node("work", depends_on=["setup"]),
                 _make_agent_node("after", depends_on=["work"])]

        plan = resume_plan(nodes, cp)

        assert plan.action_for("setup") == KEEP
        assert plan.action_for("work") == RERUN
        assert plan.action_for("after") == RERUN
