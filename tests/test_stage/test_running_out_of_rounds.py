"""A loop that runs out of rounds under ``on_max_loops: fail`` is a failed step.

The step's own run went well, but its loop still wanted another round and none was left.
Before, the step was written down as done and only turned failed in memory: the run failed,
yet its event and checkpoint said "completed" with no error, so a resume restored the step as
done and the run finished green. Now the failure is stored with its reason -- the step's event,
its checkpoint, the run's first failure -- and a resume runs the step again with the loop's
count kept: it passes now, or it fails the same way. ``silent`` and ``ship_with_open_issues``
loops are as they were.
"""

import threading

from temper_ai.checkpoint.service import CheckpointService
from temper_ai.shared.types import NodeResult, Status
from temper_ai.stage.executor import execute_graph
from temper_ai.stage.models import NodeConfig
from temper_ai.stage.plan import RERUN, build_restore
from temper_ai.stage.stage_node import StageNode
from tests.test_stage.test_executor import _make_agent_node, _make_context

REASON_2_OF_2 = "ran out of rounds: 2 of 2 (it still wanted to go back to 'implement')"


def _loop(*, wants_more, max_loops=2, policy="fail", fail_itself=False):
    """implement -> review (sends it back while ``wants_more()``) -> ship."""
    implement = _make_agent_node("implement")
    review = _make_agent_node("review", depends_on=["implement"], loop_to="implement",
                              max_loops=max_loops)
    review.config.loop_condition = {"source": "review.structured.again",
                                    "operator": "equals", "value": True}
    review.config.on_max_loops = policy

    def verdict(*_a, **_k):
        if fail_itself:
            return NodeResult(status=Status.FAILED, error="the reviewer fell over")
        return NodeResult(status=Status.COMPLETED, output="r",
                          structured_output={"again": wants_more()})

    review.run.side_effect = verdict
    ship = _make_agent_node("ship", depends_on=["review"])
    return implement, review, ship


def _graph(*, wants_more=lambda: True, **kw):
    nodes = list(_loop(wants_more=wants_more, **kw))
    return nodes, {n.name: n for n in nodes}


def _run(nodes, run_id, cp, *, restore=None):
    ctx = _make_context(run_id=run_id, checkpoint_service=cp, cancel_event=threading.Event())
    if restore is not None:
        ctx.restore = restore
    result = execute_graph(nodes, {"task": "x"}, ctx, graph_name="wf", is_workflow=True,
                           initial_outputs={} if restore is not None else None)
    return result, ctx


def _resume(nodes, run_id, cp):
    restore, plan = build_restore(nodes, cp, cp.reconstruct())
    return _run(nodes, run_id, cp, restore=restore), plan


def _last(cp, path):
    """The last node_completed checkpoint written for ``path``."""
    rows = [h for h in cp.get_history() if h["event_type"] == "node_completed" and h["node_name"] == path]
    return rows[-1]


def _stopped_at(ctx):
    return ctx.run_stop.path, ctx.run_stop.reason


def _failed_event_updates(ctx):
    return [c for c in ctx.event_recorder.update_event.call_args_list
            if c.kwargs.get("status") == "failed" and "ran_out_of_rounds" in (c.kwargs.get("data") or {})]


class TestRunningOut:
    def test_the_step_is_stored_failed_with_its_reason_and_the_run_fails(self):
        cp = CheckpointService("ran-out")
        nodes, by_name = _graph()

        result, ctx = _run(nodes, "ran-out", cp)

        assert result.status == Status.FAILED
        assert by_name["implement"].run.call_count == 2  # it went round once, then ran out
        assert by_name["ship"].run.call_count == 0
        stored = _last(cp, "review")
        assert stored["status"] == "failed"
        assert stored["error"] == REASON_2_OF_2
        # ...and its event says the same, so the run page shows it red with the reason
        (update,) = _failed_event_updates(ctx)
        assert update.kwargs["data"]["error"] == REASON_2_OF_2
        assert update.kwargs["data"]["ran_out_of_rounds"] == {"count": 2, "max": 2, "loop_to": "implement"}
        # ...and it is the run's first failure: the stop says which step, and why
        assert _stopped_at(ctx) == ("review", REASON_2_OF_2)

    def test_a_replay_no_longer_counts_it_as_done(self):
        cp = CheckpointService("ran-out-replay")
        nodes, _ = _graph()
        _run(nodes, "ran-out-replay", cp)

        assert "review" not in cp.reconstruct()
        assert "implement" in cp.reconstruct()
        assert "review" in cp.resume_state()["failed"]

    def test_resume_runs_it_again_with_the_count_kept_and_does_not_go_green(self):
        cp = CheckpointService("ran-out-resume")
        nodes, _ = _graph()
        _run(nodes, "ran-out-resume", cp)

        nodes, by_name = _graph()  # it still wants another round
        (result, ctx), plan = _resume(nodes, "ran-out-resume", cp)

        assert {s.path: s.action for s in plan.steps}["review"] == RERUN
        assert result.status == Status.FAILED
        # the count was kept: no new round, so implement is not run again
        assert by_name["implement"].run.call_count == 0
        assert by_name["review"].run.call_count == 1
        assert by_name["ship"].run.call_count == 0
        assert _last(cp, "review")["error"] == REASON_2_OF_2
        assert _stopped_at(ctx) == ("review", REASON_2_OF_2)

    def test_resume_goes_on_when_the_step_now_passes(self):
        cp = CheckpointService("ran-out-passes")
        nodes, _ = _graph()
        _run(nodes, "ran-out-passes", cp)

        nodes, by_name = _graph(wants_more=lambda: False)
        (result, _), _ = _resume(nodes, "ran-out-passes", cp)

        assert result.status == Status.COMPLETED
        assert {n for n, node in by_name.items() if node.run.call_count} == {"review", "ship"}
        assert _last(cp, "review")["status"] == "completed"

    def test_a_longer_budget_keeps_its_count_too(self):
        cp = CheckpointService("ran-out-3")
        nodes, by_name = _graph(max_loops=3)
        _run(nodes, "ran-out-3", cp)
        assert by_name["implement"].run.call_count == 3

        nodes, by_name = _graph(max_loops=3)
        (result, _), _ = _resume(nodes, "ran-out-3", cp)

        assert result.status == Status.FAILED
        assert by_name["implement"].run.call_count == 0
        assert _last(cp, "review")["error"] == (
            "ran out of rounds: 3 of 3 (it still wanted to go back to 'implement')")

    def test_a_step_that_failed_by_itself_fails_the_run_with_its_own_error(self):
        """Its loop would send it round again, but the failure stops the run first: nothing
        more starts. That used to retire the failed attempt and report the run completed."""
        cp = CheckpointService("failed-itself")
        nodes, by_name = _graph(fail_itself=True)

        result, ctx = _run(nodes, "failed-itself", cp)

        assert result.status == Status.FAILED
        assert result.error == "1 node(s) failed: review"
        assert _stopped_at(ctx) == ("review", "the reviewer fell over")
        assert by_name["ship"].run.call_count == 0
        assert _failed_event_updates(ctx) == []

        nodes, by_name = _graph(wants_more=lambda: False)
        (result, _), _ = _resume(nodes, "failed-itself", cp)
        assert result.status == Status.COMPLETED
        assert by_name["ship"].run.call_count == 1


class TestOtherPoliciesAreUnchanged:
    def test_silent_goes_on_as_before(self):
        cp = CheckpointService("silent")
        nodes, by_name = _graph(policy="silent")

        result, ctx = _run(nodes, "silent", cp)

        assert result.status == Status.COMPLETED
        assert by_name["ship"].run.call_count == 1
        assert _last(cp, "review")["status"] == "completed"
        assert _failed_event_updates(ctx) == []
        assert not ctx.run_stop.stopped

    def test_ship_with_open_issues_goes_on_as_before(self):
        cp = CheckpointService("ship-open")
        nodes, by_name = _graph(policy="ship_with_open_issues")

        result, ctx = _run(nodes, "ship-open", cp)

        assert result.status == Status.COMPLETED
        assert by_name["ship"].run.call_count == 1
        assert _last(cp, "review")["status"] == "completed"
        assert _failed_event_updates(ctx) == []


class TestInsideAStage:
    def _graph(self, wants_more=lambda: True):
        implement, review, ship = _loop(wants_more=wants_more)
        build = StageNode(NodeConfig(name="build"), [implement, review])
        after = _make_agent_node("after", depends_on=["build"])
        return [build, after], {"implement": implement, "review": review, "after": after}

    def test_it_fails_the_same_way_and_resume_reruns_only_that_step(self):
        cp = CheckpointService("stage-ran-out")
        nodes, by_name = self._graph()

        result, ctx = _run(nodes, "stage-ran-out", cp)

        assert result.status == Status.FAILED
        assert by_name["after"].run.call_count == 0
        assert _last(cp, "build.review")["status"] == "failed"
        assert _last(cp, "build.review")["error"] == REASON_2_OF_2
        assert _stopped_at(ctx) == ("build.review", REASON_2_OF_2)

        nodes, by_name = self._graph()
        (result, _), _ = _resume(nodes, "stage-ran-out", cp)
        assert result.status == Status.FAILED
        assert by_name["implement"].run.call_count == 0
        assert by_name["review"].run.call_count == 1

        nodes, by_name = self._graph(wants_more=lambda: False)
        (result, _), _ = _resume(nodes, "stage-ran-out", cp)
        assert result.status == Status.COMPLETED
        assert by_name["implement"].run.call_count == 0
        assert by_name["after"].run.call_count == 1
