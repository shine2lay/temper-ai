"""A resumed run goes on inside a stage from the stage's own last finished step.

Before: a resume handed the top-level graph its finished nodes and nothing else. A stage that was
running when the run stopped (the EPD build, interrupted by a restart in its review) ran again
from its first step, and a stage in which a step had failed (its stack deploy) had "finished" to
the graph above it, so a resume skipped it whole and the failed step never ran again. The EPD
driver forked before the stage instead and redid the whole build round: hours, $15-30 each time.

These run real graphs against real checkpoints (the test database), stop them part way, and
resume them the two ways temper does: the same run (POST /resume) and a fork at its latest
checkpoint (what the EPD driver's `resume` does now).
"""

import threading

from temper_ai.checkpoint.service import CheckpointService
from temper_ai.shared.types import NodeResult, Status
from temper_ai.stage.executor import execute_graph
from temper_ai.stage.models import NodeConfig
from temper_ai.stage.restore import Restore
from temper_ai.stage.stage_node import StageNode
from tests.test_stage.test_executor import _make_agent_node, _make_context

STEPS = ("s1", "s2", "s3", "s4", "s5")


def _stop_after(node, cancel: threading.Event):
    """The node finishes, and the run is stopped before the next step starts (a restart)."""
    result = node.run.return_value

    def run(*_a, **_k):
        cancel.set()
        return result

    node.run.side_effect = run


def _graph(*, fail: str | None = None, after_failure: bool = False):
    """tasks -> build (s1..s5, a chain) -> ship. ``fail`` names a step that fails;
    ``after_failure`` adds `final` at the end of the build, run after a failure too (epd_task's)."""
    tasks = _make_agent_node("tasks")
    steps = [_make_agent_node(s, depends_on=[STEPS[i - 1]] if i else None,
                              status=Status.FAILED if s == fail else Status.COMPLETED)
             for i, s in enumerate(STEPS)]
    children = list(steps)
    if after_failure:
        final = _make_agent_node("final", depends_on=["s5"])
        final.config.run_after_failure = True
        children.append(final)
    build = StageNode(NodeConfig(name="build", depends_on=["tasks"]), children)
    ship = _make_agent_node("ship", depends_on=["build"])
    return [tasks, build, ship], {n.name: n for n in [tasks, ship, *children]}


def _run(nodes, run_id, cp, cancel=None, initial_outputs=None):
    ctx = _make_context(run_id=run_id, checkpoint_service=cp, cancel_event=cancel or threading.Event())
    result = execute_graph(nodes, {}, ctx, graph_name="wf", is_workflow=True,
                           initial_outputs=initial_outputs)
    return result, ctx


def _ran(by_name) -> set[str]:
    return {name for name, node in by_name.items() if node.run.called}


class TestAStageInterruptedPartWay:
    def _interrupt(self, run_id):
        """The first attempt: tasks, then s1-s3 of the build, then the run stops."""
        cp = CheckpointService(run_id)
        cancel = threading.Event()
        nodes, by_name = _graph()
        _stop_after(by_name["s3"], cancel)
        first, _ = _run(nodes, run_id, cp, cancel)
        assert first.status == Status.CANCELLED
        assert _ran(by_name) == {"tasks", "s1", "s2", "s3"}
        return cp

    def test_the_resume_runs_only_the_steps_that_had_not_finished(self):
        cp = self._interrupt("run-interrupted")

        nodes, by_name = _graph()
        result, ctx = _run(nodes, "run-interrupted", cp, initial_outputs=cp.reconstruct())

        assert result.status == Status.COMPLETED
        assert _ran(by_name) == {"s4", "s5", "ship"}, "the finished steps of the build ran again"
        for name in ("s4", "s5", "ship"):
            by_name[name].run.assert_called_once()
        # the stage's graph says which steps it kept, for whoever reads the run
        stage_starts = [c.kwargs["data"] for c in ctx.event_recorder.record.call_args_list
                        if c.kwargs.get("data", {}).get("name") == "build"
                        and "node_count" in c.kwargs["data"]]
        assert stage_starts[0]["restored_node_names"] == ["s1", "s2", "s3"]

    def test_a_fork_at_the_latest_checkpoint_does_the_same(self):
        """The EPD driver's resume: a new run, forked at the old one's last checkpoint."""
        cp = self._interrupt("run-to-fork")
        fork = CheckpointService.fork("run-to-fork", cp.get_latest_sequence(), "run-forked")

        nodes, by_name = _graph()
        result, _ = _run(nodes, "run-forked", fork, initial_outputs=fork.reconstruct())

        assert result.status == Status.COMPLETED
        assert _ran(by_name) == {"s4", "s5", "ship"}

    def test_the_stage_hands_on_the_kept_steps_results(self):
        """What comes after reads the finished steps as if they had run now."""
        cp = self._interrupt("run-outputs")

        nodes, by_name = _graph()
        result, _ = _run(nodes, "run-outputs", cp, initial_outputs=cp.reconstruct())

        build = result.node_results["build"]
        assert set(build.node_results) == set(STEPS)
        assert build.node_results["s1"].output == "ok"


class TestAStageWithAFailedStep:
    def _fail(self, run_id):
        """The first attempt: s3 fails; s4 and s5 are skipped for it, `final` runs after it, and
        the build finishes (a stage goes on past a failed step), so the run above goes on."""
        cp = CheckpointService(run_id)
        nodes, by_name = _graph(fail="s3", after_failure=True)
        first, _ = _run(nodes, run_id, cp)
        assert first.status == Status.FAILED
        assert _ran(by_name) == {"tasks", "s1", "s2", "s3", "final", "ship"}
        return cp

    def test_the_failed_step_runs_again_and_what_comes_after_it(self):
        cp = self._fail("run-failed")

        nodes, by_name = _graph(after_failure=True)
        result, _ = _run(nodes, "run-failed", cp, initial_outputs=cp.reconstruct())

        assert result.status == Status.COMPLETED
        # `final` had finished, on the failed attempt: it runs again, on this one; so does ship,
        # which came after the build
        assert _ran(by_name) == {"s3", "s4", "s5", "final", "ship"}

    def test_a_second_resume_does_not_bring_back_what_the_first_ran_again(self):
        """The first resume stops before `final` finishes again: its old result, made on the
        failed attempt, must not come back as finished, and neither may the old build."""
        cp = self._fail("run-twice")

        cancel = threading.Event()
        nodes, by_name = _graph(after_failure=True)
        _stop_after(by_name["s5"], cancel)
        second, _ = _run(nodes, "run-twice", cp, cancel, initial_outputs=cp.reconstruct())
        assert second.status == Status.CANCELLED
        assert _ran(by_name) == {"s3", "s4", "s5"}

        nodes, by_name = _graph(after_failure=True)
        third, _ = _run(nodes, "run-twice", cp, initial_outputs=cp.reconstruct())
        assert third.status == Status.COMPLETED
        assert _ran(by_name) == {"final", "ship"}


class TestAFinishedStage:
    def test_is_not_run_again(self):
        cp = CheckpointService("run-finished-stage")
        cancel = threading.Event()
        nodes, by_name = _graph()
        _stop_after(by_name["s5"], cancel)  # the build finishes; the run stops before ship
        first, _ = _run(nodes, "run-finished-stage", cp, cancel)
        assert first.status == Status.CANCELLED

        nodes, by_name = _graph()
        result, _ = _run(nodes, "run-finished-stage", cp, initial_outputs=cp.reconstruct())

        assert result.status == Status.COMPLETED
        assert _ran(by_name) == {"ship"}


class TestALoopInsideAStage:
    """implement -> review, review sending it back while it asks for changes (two rounds)."""

    def _graph(self, verdict: str):
        implement = _make_agent_node("implement", input_map={"findings": "review.structured.findings"})
        review = _make_agent_node("review", depends_on=["implement"], loop_to="implement", max_loops=2,
                                  structured_output={"verdict": verdict, "findings": [f"{verdict} finding"]})
        review.config.loop_condition = {"source": "review.structured.verdict", "operator": "equals",
                                        "value": "request_changes"}
        build = StageNode(NodeConfig(name="build"), [implement, review])
        return [build], implement, review

    def test_goes_on_with_its_count_and_the_findings_it_was_sent_back_with(self):
        cp = CheckpointService("run-loop")
        cancel = threading.Event()
        nodes, implement, review = self._graph("request_changes")
        _stop_after(review, cancel)  # round 1's review asks for changes; the run stops there
        first, _ = _run(nodes, "run-loop", cp, cancel)
        assert first.status == Status.CANCELLED
        assert implement.run.call_count == 1

        nodes, implement, review = self._graph("request_changes")
        _run(nodes, "run-loop", cp, initial_outputs=cp.reconstruct())

        # round 2: implement reads round 1's findings
        assert implement.run.call_count == 1, "round 2 ran more than once: the loop's count started over"
        seen = implement.run.call_args.args[0]
        assert seen["findings"] == ["request_changes finding"]
        review.run.assert_called_once()


class TestTheCheckpoints:
    def _history(self, run_id):
        cp = CheckpointService(run_id)
        done = NodeResult(status=Status.COMPLETED, output="ok")
        cp.save_node_completed("build.s1", done)
        cp.save_node_completed("build.s2", NodeResult(status=Status.FAILED, error="boom"))
        cp.save_node_completed("build.s3", NodeResult(status=Status.SKIPPED,
                                                      error="Dependency 's2' failed"))
        cp.save_node_completed("build.maybe", NodeResult(status=Status.SKIPPED,
                                                         error="condition not met"))
        cp.save_node_completed("build", done)
        return cp

    def test_resume_state_names_the_failures_not_the_condition_skips(self):
        cp = self._history("run-state")
        assert cp.resume_state()["failed"] == ["build.s2", "build.s3"]

    def test_a_step_that_finished_later_is_no_longer_failed(self):
        cp = self._history("run-state-later")
        cp.save_node_completed("build.s2", NodeResult(status=Status.COMPLETED, output="ok"))
        assert cp.resume_state()["failed"] == ["build.s3"]

    def test_a_reset_takes_a_finished_result_back(self):
        cp = self._history("run-reset")
        cp.save_node_reset("build")
        restored = cp.reconstruct()
        assert "build" not in restored
        assert "build.s1" in restored, "a stage run again keeps its own finished steps"

    def test_a_rewind_through_a_stage_clears_what_is_inside_it(self):
        cp = CheckpointService("run-rewind")
        done = NodeResult(status=Status.COMPLETED, output="ok")
        cp.save_node_completed("build.s1", done)
        cp.save_loop_rewind("build.gate", "build.s1", ["build.s1", "build.gate"],
                            NodeResult(status=Status.COMPLETED, structured_output={"verdict": "again"}))
        cp.save_node_completed("build", done)
        cp.save_loop_rewind("check", "build", ["build", "check"],
                            NodeResult(status=Status.COMPLETED, structured_output={"verdict": "again"}))

        assert cp.reconstruct() == {}
        loops = cp.resume_state()["loops"]
        assert set(loops) == {"check"}, "the stage's own loop starts over with the stage"
        assert loops["check"]["count"] == 1 and loops["check"]["target"] == "build"
        assert loops["check"]["feedback"].structured_output == {"verdict": "again"}


class TestRestore:
    """The claims themselves, without a database."""

    def _done(self, output="ok"):
        return NodeResult(status=Status.COMPLETED, output=output)

    def test_each_graph_takes_only_its_own_nodes_once(self):
        restore = Restore({"tasks": self._done(), "build.s1": self._done(), "build.s2": self._done()})
        top = restore.claim("", {"tasks": [], "build": ["tasks"]})
        assert set(top.outputs) == {"tasks"}
        stage = restore.claim("build.", {"s1": [], "s2": ["s1"], "s3": ["s2"]})
        assert set(stage.outputs) == {"s1", "s2"}
        again = restore.claim("build.", {"s1": [], "s2": ["s1"], "s3": ["s2"]})
        assert again.outputs == {}, "a stage run again by a loop starts over"

    def test_a_node_restored_whole_takes_its_insides_away(self):
        restore = Restore({"build": self._done(), "build.s1": self._done()})
        assert set(restore.claim("", {"build": []}).outputs) == {"build"}
        assert restore.claim("build.", {"s1": []}).outputs == {}

    def test_a_stage_with_a_failed_step_runs_again_and_so_does_what_follows(self):
        restore = Restore({"build": self._done(), "ship": self._done(), "other": self._done()},
                          failed=["build.environment.stack_up"])
        top = restore.claim("", {"build": [], "ship": ["build"], "other": []})
        assert set(top.outputs) == {"other"}
        assert top.reset == ["build", "ship"]

    def test_a_skip_by_condition_does_not_make_what_follows_run_again(self):
        restore = Restore({"after": self._done()})
        top = restore.claim("", {"maybe": [], "after": ["maybe"]})
        assert set(top.outputs) == {"after"}
        assert top.reset == []
