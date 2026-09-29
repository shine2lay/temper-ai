"""Picking a stopped run up again, whatever shape it has and however it stopped.

A resume runs the failed step and what had not finished, plus anything that used a failed
result; everything else keeps what it made. If the clean-ups did run -- because the workflow
says "cleanup", or because the wait ran out -- the steps they undid are made again first, with
the inputs they had, so the failed step has the same setup under it as before.

Every shape is here because each used to break in its own way: a chain, parallel branches, a
stage inside a stage, a loop that must keep its round count, agents a dispatcher added part way
through, a condition's skip and a gate.
"""

import threading

from temper_ai.checkpoint.service import CheckpointService
from temper_ai.shared.types import NodeResult, Status
from temper_ai.stage.executor import execute_graph
from temper_ai.stage.failure import FailurePolicy
from temper_ai.stage.models import NodeConfig
from temper_ai.stage.plan import KEEP, RERUN, build_restore, resume_plan
from temper_ai.stage.stage_node import StageNode
from tests.test_stage.test_executor import _make_agent_node, _make_context


def _ran(by_name):
    return {name for name, node in by_name.items() if node.run.call_count}


def _run(nodes, run_id, cp, *, cancel=None, restore=None, policy=None):
    ctx = _make_context(run_id=run_id, checkpoint_service=cp,
                        cancel_event=cancel or threading.Event())
    if policy is not None:
        ctx.failure_policy = policy
    if restore is not None:
        # What a resumed run is handed: the plan's Restore, as the server hands it over.
        ctx.restore = restore
    result = execute_graph(nodes, {"task": "x"}, ctx, graph_name="wf", is_workflow=True,
                           initial_outputs={} if restore is not None else None)
    return result, ctx


def _resume(nodes, run_id, cp, *, rerun=(), policy=None):
    """Pick the run up the way the server does: a plan, then the Restore built from it."""
    restore, plan = build_restore(nodes, cp, cp.reconstruct(), rerun=rerun)
    return _run(nodes, run_id, cp, restore=restore, policy=policy), plan


def _cleanup(name, *, undone, depends_on=None):
    node = _make_agent_node(name, depends_on=depends_on)
    node.config.run_after_failure = True
    node.config.undoes = list(undone)
    return node


class TestAChain:
    """setup -> work (fails) -> check, with a clean-up that undoes the setup."""

    def _graph(self, *, fail_work=True):
        setup = _make_agent_node("setup")
        work = _make_agent_node("work", depends_on=["setup"],
                                status=Status.FAILED if fail_work else Status.COMPLETED)
        check = _make_agent_node("check", depends_on=["work"])
        teardown = _cleanup("teardown", undone=["setup"], depends_on=["check"])
        nodes = [setup, work, check, teardown]
        return nodes, {n.name: n for n in nodes}

    def test_only_the_failed_step_and_what_follows_run_again(self):
        cp = CheckpointService("chain-hold")
        nodes, _ = self._graph()
        first, _ = _run(nodes, "chain-hold", cp)
        assert first.status == Status.FAILED

        nodes, by_name = self._graph(fail_work=False)
        (result, _), plan = _resume(nodes, "chain-hold", cp)

        assert result.status == Status.COMPLETED
        assert _ran(by_name) == {"work", "check", "teardown"}
        assert plan.keep == {"setup"}

    def test_when_the_cleanup_ran_the_setup_is_made_again_first(self):
        cp = CheckpointService("chain-cleanup")
        nodes, by_name = self._graph()
        first, _ = _run(nodes, "chain-cleanup", cp, policy=FailurePolicy.parse("cleanup"))
        assert first.status == Status.FAILED
        assert "teardown" in _ran(by_name)

        nodes, by_name = self._graph(fail_work=False)
        (result, _), plan = _resume(nodes, "chain-cleanup", cp)

        assert result.status == Status.COMPLETED
        # setup was undone, so it is made again before the step that needs it
        assert "setup" in plan.redo
        assert _ran(by_name) == {"setup", "work", "check", "teardown"}

    def test_the_setup_is_made_again_with_the_inputs_it_had(self):
        cp = CheckpointService("chain-inputs")
        nodes, _ = self._graph()
        _run(nodes, "chain-inputs", cp, policy=FailurePolicy.parse("cleanup"))

        nodes, by_name = self._graph(fail_work=False)
        _resume(nodes, "chain-inputs", cp)

        called_with = by_name["setup"].run.call_args[0][0]
        assert called_with == {"task": "x"}


class TestParallelBranches:
    def test_the_branch_that_finished_keeps_its_result(self):
        cp = CheckpointService("branches")

        def graph(fail=True):
            start = _make_agent_node("start")
            left = _make_agent_node("left", depends_on=["start"],
                                    status=Status.FAILED if fail else Status.COMPLETED)
            right = _make_agent_node("right", depends_on=["start"])
            join = _make_agent_node("join", depends_on=["left", "right"])
            nodes = [start, left, right, join]
            return nodes, {n.name: n for n in nodes}

        nodes, _ = graph()
        first, _ = _run(nodes, "branches", cp)
        assert first.status == Status.FAILED

        nodes, by_name = graph(fail=False)
        (result, _), plan = _resume(nodes, "branches", cp)

        assert result.status == Status.COMPLETED
        # `right` is a sibling of the failure, not a user of it: it keeps its result.
        assert _ran(by_name) == {"left", "join"}
        assert plan.keep == {"start", "right"}


class TestAStageInsideAStage:
    def _graph(self, *, fail=True):
        inner_a = _make_agent_node("a")
        inner_b = _make_agent_node("b", depends_on=["a"],
                                   status=Status.FAILED if fail else Status.COMPLETED)
        inner = StageNode(NodeConfig(name="inner"), [inner_a, inner_b])
        outer_first = _make_agent_node("first")
        outer = StageNode(NodeConfig(name="outer"), [outer_first, inner])
        inner.config.depends_on = ["first"]
        ship = _make_agent_node("ship", depends_on=["outer"])
        nodes = [outer, ship]
        return nodes, {n.name: n for n in (outer_first, inner_a, inner_b, ship)}

    def test_it_goes_on_from_the_step_that_failed_deep_inside(self):
        cp = CheckpointService("nested")
        nodes, by_name = self._graph()
        first, _ = _run(nodes, "nested", cp)
        assert first.status == Status.FAILED
        assert _ran(by_name) == {"first", "a", "b"}

        nodes, by_name = self._graph(fail=False)
        (result, _), _ = _resume(nodes, "nested", cp)

        assert result.status == Status.COMPLETED
        assert _ran(by_name) == {"b", "ship"}


class TestALoop:
    def test_it_keeps_its_round_count_and_what_it_was_sent_back_with(self):
        """implement -> review, review sending it back once; then the step after fails."""
        cp = CheckpointService("loop-run")

        def graph(rounds, fail_ship=True):
            implement = _make_agent_node("implement")
            review = _make_agent_node("review", depends_on=["implement"], loop_to="implement",
                                      max_loops=3, structured_output={"again": True})
            review.config.loop_condition = {"source": "review.structured.again",
                                            "operator": "equals", "value": True}
            calls = {"n": 0}

            def verdict(*_a, **_k):
                calls["n"] += 1
                again = calls["n"] < rounds
                return NodeResult(status=Status.COMPLETED, output="r",
                                  structured_output={"again": again})

            review.run.side_effect = verdict
            ship = _make_agent_node("ship", depends_on=["review"],
                                    status=Status.FAILED if fail_ship else Status.COMPLETED)
            nodes = [implement, review, ship]
            return nodes, {n.name: n for n in nodes}

        nodes, by_name = graph(2)
        first, _ = _run(nodes, "loop-run", cp)
        assert first.status == Status.FAILED
        assert by_name["implement"].run.call_count == 2  # it went round once

        nodes, by_name = graph(1, fail_ship=False)
        (result, _), _ = _resume(nodes, "loop-run", cp)

        assert result.status == Status.COMPLETED
        # the loop is over: only the failed step runs again
        assert _ran(by_name) == {"ship"}


class TestASkipAndAGate:
    def test_a_step_its_condition_skipped_is_not_run_again(self):
        cp = CheckpointService("skipped")

        def graph(fail=True):
            a = _make_agent_node("a", structured_output={"go": False})
            skipped = _make_agent_node(
                "skipped", depends_on=["a"],
                condition={"source": "a.structured.go", "operator": "equals", "value": True})
            c = _make_agent_node("c", depends_on=["a"],
                                 status=Status.FAILED if fail else Status.COMPLETED)
            nodes = [a, skipped, c]
            return nodes, {n.name: n for n in nodes}

        nodes, _ = graph()
        first, _ = _run(nodes, "skipped", cp)
        assert first.status == Status.FAILED

        nodes, by_name = graph(fail=False)
        (result, _), plan = _resume(nodes, "skipped", cp)

        assert result.status == Status.COMPLETED
        assert _ran(by_name) == {"c"}
        assert "skipped" in plan.keep


class TestThePlan:
    def _graph(self):
        setup = _make_agent_node("setup")
        work = _make_agent_node("work", depends_on=["setup"], status=Status.FAILED)
        other = _make_agent_node("other", depends_on=["setup"])
        nodes = [setup, work, other]
        return nodes, {n.name: n for n in nodes}

    def test_it_says_what_happens_to_every_step_and_why(self):
        cp = CheckpointService("plan-why")
        nodes, _ = self._graph()
        _run(nodes, "plan-why", cp)

        plan = resume_plan(nodes, cp)
        by_path = {s.path: s for s in plan.steps}

        assert by_path["setup"].action == KEEP
        assert by_path["work"].action == RERUN
        assert by_path["work"].reason
        assert by_path["other"].action == KEEP

    def test_ticking_a_step_takes_what_used_it_along(self):
        cp = CheckpointService("plan-ticked")
        nodes, _ = self._graph()
        _run(nodes, "plan-ticked", cp)

        plan = resume_plan(nodes, cp, rerun=["setup"])

        assert plan.rerun >= {"setup", "work", "other"}

    def test_what_the_plan_says_is_what_runs(self):
        cp = CheckpointService("plan-matches")
        nodes, _ = self._graph()
        _run(nodes, "plan-matches", cp)

        def graph_ok():
            setup = _make_agent_node("setup")
            work = _make_agent_node("work", depends_on=["setup"])
            other = _make_agent_node("other", depends_on=["setup"])
            nodes = [setup, work, other]
            return nodes, {n.name: n for n in nodes}

        nodes, by_name = graph_ok()
        (result, _), plan = _resume(nodes, "plan-matches", cp)

        assert result.status == Status.COMPLETED
        assert _ran(by_name) == plan.rerun | plan.redo

    def test_it_is_grouped_by_stage_for_the_page(self):
        cp = CheckpointService("plan-groups")
        inner = _make_agent_node("a", status=Status.FAILED)
        build = StageNode(NodeConfig(name="build"), [inner])
        top = _make_agent_node("top")
        _run([top, build], "plan-groups", cp)

        out = resume_plan([top, build], cp).as_dict()

        stages = [g["stage"] for g in out["groups"]]
        assert "" in stages and "build" in stages
        assert out["counts"][RERUN] >= 1


class TestAnOldRun:
    def test_a_run_saved_before_any_of_this_still_resumes(self):
        """Its checkpoints have no stop, no held clean-ups and no dispatch paths."""
        cp = CheckpointService("old-run")
        a = _make_agent_node("a")
        b = _make_agent_node("b", depends_on=["a"], status=Status.FAILED)
        _run([a, b], "old-run", cp)
        # what an older temper left behind: the rows exist, the new keys do not
        state = cp.resume_state()
        assert state["dispatches"] == []
        assert state["undone"] == {}

        a2 = _make_agent_node("a")
        b2 = _make_agent_node("b", depends_on=["a"])
        (result, _), _ = _resume([a2, b2], "old-run", cp)

        assert result.status == Status.COMPLETED
        assert a2.run.call_count == 0
        assert b2.run.call_count == 1
