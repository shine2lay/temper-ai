"""A failure stops the run where it happened, and what it was standing on is kept.

Before: a failure only stopped what came after it. Everything on another branch carried on
starting new agents -- a review of a build that never built, an hour of model time spent on
work already thrown away -- and the clean-ups at the end tore the dev stack and the worktree
down, so there was nothing left to pick up. A resume then had to start from the beginning.

Now: nothing new starts once the run has stopped, except the steps that are marked to run
after a failure (the reports and pitches). Agents already running finish and keep their
results. The clean-ups are held back, with a deadline, so the failed step can be tried again
in the same place.
"""

import threading
import time
from unittest.mock import MagicMock

from temper_ai.checkpoint.service import CheckpointService
from temper_ai.shared.types import NodeResult, Status
from temper_ai.stage.executor import execute_graph
from temper_ai.stage.failure import FailurePolicy, is_cleanup, undoes
from temper_ai.stage.models import NodeConfig
from temper_ai.stage.stage_node import StageNode
from tests.test_stage.test_executor import _make_agent_node, _make_context


def _cleanup_node(name, *, undone, depends_on=None):
    node = _make_agent_node(name, depends_on=depends_on)
    node.config.run_after_failure = True
    node.config.undoes = list(undone)
    return node


def _ran(by_name):
    return {name for name, node in by_name.items() if node.run.call_count}


class TestNothingNewStarts:
    def test_a_parallel_branch_starts_nothing_after_the_failure(self):
        """The shape that cost the most: two branches, one fails, the other keeps going."""
        start = _make_agent_node("start")
        left = _make_agent_node("left", depends_on=["start"], status=Status.FAILED)
        right = _make_agent_node("right", depends_on=["start"])
        after_right = _make_agent_node("after_right", depends_on=["right"])
        far = _make_agent_node("far", depends_on=["start"])

        result = execute_graph([start, left, right, after_right, far], {}, _make_context(),
                               graph_name="wf", is_workflow=True)

        # left and right are in the same batch: right was already running, so it finishes.
        right.run.assert_called_once()
        # Nothing that had not started yet starts.
        after_right.run.assert_not_called()
        assert result.status == Status.FAILED
        assert result.node_results["right"].status == Status.COMPLETED

    def test_a_step_that_was_running_keeps_its_result(self):
        a = _make_agent_node("a", status=Status.FAILED)
        b = _make_agent_node("b")  # no dependency: same batch as the failure

        result = execute_graph([a, b], {}, _make_context(), graph_name="wf", is_workflow=True)

        b.run.assert_called_once()
        assert result.node_results["b"].status == Status.COMPLETED
        assert result.node_results["b"].output == "ok"

    def test_the_run_says_where_it_stopped(self):
        a = _make_agent_node("a")
        b = _make_agent_node("b", depends_on=["a"], status=Status.FAILED)
        ctx = _make_context()

        execute_graph([a, b], {}, ctx, graph_name="wf", is_workflow=True)

        update = ctx.event_recorder.update_event.call_args
        stopped = update.kwargs["data"]["stopped"]
        assert stopped["path"] == "b"
        assert stopped["reason"]
        assert stopped["at"]  # when it stopped

    def test_inside_a_stage_the_run_above_stops_too(self):
        """A stage used to finish past a failed step, so the run above went on."""
        inner_ok = _make_agent_node("s1")
        inner_bad = _make_agent_node("s2", depends_on=["s1"], status=Status.FAILED)
        build = StageNode(NodeConfig(name="build"), [inner_ok, inner_bad])
        ship = _make_agent_node("ship", depends_on=["build"])

        result = execute_graph([build, ship], {}, _make_context(),
                               graph_name="wf", is_workflow=True)

        ship.run.assert_not_called()
        assert result.status == Status.FAILED


class TestTheCleanupsAreHeld:
    def _graph(self):
        setup = _make_agent_node("setup")
        work = _make_agent_node("work", depends_on=["setup"], status=Status.FAILED)
        report = _make_agent_node("report", depends_on=["work"])
        report.config.run_after_failure = True
        teardown = _cleanup_node("teardown", undone=["setup"], depends_on=["work"])
        return [setup, work, report, teardown], {n.name: n for n in (setup, work, report, teardown)}

    def test_a_cleanup_does_not_run_and_the_marked_report_does(self):
        nodes, by_name = self._graph()

        execute_graph(nodes, {}, _make_context(), graph_name="wf", is_workflow=True)

        assert _ran(by_name) == {"setup", "work", "report"}

    def test_what_is_held_is_written_down_with_what_it_undoes(self):
        nodes, _ = self._graph()
        ctx = _make_context()

        execute_graph(nodes, {}, ctx, graph_name="wf", is_workflow=True)

        stopped = ctx.event_recorder.update_event.call_args.kwargs["data"]["stopped"]
        assert stopped["held"] == [{"path": "teardown", "undoes": ["setup"]}]

    def test_with_the_cleanup_setting_they_run_at_the_failure(self):
        nodes, by_name = self._graph()
        ctx = _make_context(failure_policy=FailurePolicy.parse("cleanup"))

        execute_graph(nodes, {}, ctx, graph_name="wf", is_workflow=True)

        assert "teardown" in _ran(by_name)
        stopped = ctx.event_recorder.update_event.call_args.kwargs["data"]["stopped"]
        assert stopped["held"] == []

    def test_a_stage_can_hold_them_when_its_workflow_does_not(self):
        inner_fail = _make_agent_node("s1", status=Status.FAILED)
        inner_cleanup = _cleanup_node("s2", undone=["s1"], depends_on=["s1"])
        build = StageNode(NodeConfig(name="build", on_failure="hold"), [inner_fail, inner_cleanup])

        execute_graph([build], {}, _make_context(failure_policy=FailurePolicy.parse("cleanup")),
                      graph_name="wf", is_workflow=True)

        inner_cleanup.run.assert_not_called()

    def test_a_cleanup_inside_a_stage_is_held_by_its_full_path(self):
        inner_fail = _make_agent_node("s1", status=Status.FAILED)
        inner_cleanup = _cleanup_node("s2", undone=["s1"], depends_on=["s1"])
        build = StageNode(NodeConfig(name="build"), [inner_fail, inner_cleanup])
        ctx = _make_context()

        execute_graph([build], {}, ctx, graph_name="wf", is_workflow=True)

        stopped = ctx.event_recorder.update_event.call_args.kwargs["data"]["stopped"]
        assert stopped["held"] == [{"path": "build.s2", "undoes": ["s1"]}]

    def test_a_run_stopped_by_hand_still_owes_its_cleanups(self):
        """Nothing ran them, so the setup is still standing: they are owed all the same."""
        cancel = threading.Event()
        setup = _make_agent_node("setup")
        setup.run.side_effect = lambda *a, **k: (cancel.set(), setup.run.return_value)[1]
        work = _make_agent_node("work", depends_on=["setup"])
        teardown = _cleanup_node("teardown", undone=["setup"], depends_on=["work"])
        ctx = _make_context(cancel_event=cancel)

        execute_graph([setup, work, teardown], {}, ctx, graph_name="wf", is_workflow=True)

        stopped = ctx.event_recorder.update_event.call_args.kwargs["data"]["stopped"]
        assert [h["path"] for h in stopped["held"]] == ["teardown"]


class TestWhatCountsAsACleanup:
    def test_a_step_that_names_what_it_undoes(self):
        node = _cleanup_node("stack_down", undone=["environment", "deploy"])
        assert is_cleanup(node)
        assert undoes(node) == ["environment", "deploy"]

    def test_a_step_that_names_nothing_is_not_one(self):
        node = _make_agent_node("report")
        node.config.run_after_failure = True
        assert not is_cleanup(node)

    def test_temper_never_guesses_from_the_name(self):
        """`cleanup` in the name means nothing: the workflow has to say what it undoes."""
        node = _make_agent_node("cleanup")
        node.config.run_after_failure = True
        assert not is_cleanup(node)


class TestTheFailureSetting:
    def test_hold_is_the_default(self):
        assert FailurePolicy.parse(None).holds
        assert FailurePolicy.parse({}).holds

    def test_cleanup_runs_them(self):
        assert not FailurePolicy.parse("cleanup").holds

    def test_a_time_limit_can_be_set(self):
        policy = FailurePolicy.parse({"mode": "hold", "hold_hours": 2})
        deadline = policy.deadline()
        assert deadline is not None
        left = (deadline - _now()).total_seconds()
        assert 7000 < left < 7300

    def test_the_default_limit_is_a_day(self):
        left = (FailurePolicy.parse(None).deadline() - _now()).total_seconds()
        assert 86000 < left < 86500


def _now():
    from datetime import UTC, datetime
    return datetime.now(UTC)


class TestWhatTheRunWroteDown:
    def test_a_held_cleanup_is_checkpointed_so_a_restart_still_knows(self, tmp_path):
        cp = CheckpointService("run-held-cp")
        setup = _make_agent_node("setup")
        work = _make_agent_node("work", depends_on=["setup"], status=Status.FAILED)
        teardown = _cleanup_node("teardown", undone=["setup"], depends_on=["work"])

        execute_graph([setup, work, teardown], {},
                      _make_context(run_id="run-held-cp", checkpoint_service=cp),
                      graph_name="wf", is_workflow=True)

        state = cp.resume_state()
        assert "work" in state["failed"]
        assert state["undone"] == {}

    def test_a_cleanup_that_ran_says_what_it_undid(self):
        cp = CheckpointService("run-undone-cp")
        setup = _make_agent_node("setup")
        work = _make_agent_node("work", depends_on=["setup"], status=Status.FAILED)
        teardown = _cleanup_node("teardown", undone=["setup"], depends_on=["work"])

        execute_graph([setup, work, teardown], {},
                      _make_context(run_id="run-undone-cp", checkpoint_service=cp,
                                    failure_policy=FailurePolicy.parse("cleanup")),
                      graph_name="wf", is_workflow=True)

        assert cp.resume_state()["undone"] == {"teardown": ["setup"]}


class TestAgentsRunningAlongsideAFailure:
    def test_a_slow_neighbour_finishes_and_is_kept(self):
        """The failure lands while the neighbour is still working: it is not cut off."""
        slow_done = threading.Event()

        def slow(*_a, **_k):
            time.sleep(0.05)
            slow_done.set()
            return NodeResult(status=Status.COMPLETED, output="slow-ok")

        a = _make_agent_node("a", status=Status.FAILED)
        b = _make_agent_node("b")
        b.run = MagicMock(side_effect=slow)
        after = _make_agent_node("after", depends_on=["b"])

        result = execute_graph([a, b, after], {}, _make_context(),
                               graph_name="wf", is_workflow=True)

        assert slow_done.is_set()
        assert result.node_results["b"].output == "slow-ok"
        after.run.assert_not_called()
