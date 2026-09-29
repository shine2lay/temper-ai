"""Agents added part way through a run come back where they were added.

A dispatcher adds agents while the run is going. They were written down by name alone, and a
resume put every one of them back at the top level -- so an agent added inside a stage came
back as ``worker_1`` when it had run as ``build.worker_1``. Nothing matched, so all of them
ran again on every resume, and "re-run from here" after the dispatcher lost them altogether.

Now each dispatch is written down with the graph it added to, and every graph takes back its
own as it starts.
"""

import threading

from temper_ai.checkpoint.service import CheckpointService
from temper_ai.shared.types import NodeResult, Status
from temper_ai.stage.executor import execute_graph
from temper_ai.stage.models import NodeConfig
from temper_ai.stage.stage_node import StageNode
from tests.test_stage.test_executor import (
    _make_agent_node,
    _make_context,
    _make_dispatcher_node,
    _StubGraphLoader,
)


def _ctx(run_id, cp, loader, **kw):
    return _make_context(run_id=run_id, checkpoint_service=cp, graph_loader=loader,
                         cancel_event=threading.Event(), **kw)


def _adds(*names):
    return [{"op": "add", "node": {"name": n, "agent": "x"}} for n in names]


def _dispatcher_with_workers(worker_names, *, worker_status=Status.COMPLETED):
    """A dispatcher that adds one agent per name, and a loader that can build them."""
    dispatcher = _make_dispatcher_node("splitter", _adds(*worker_names))
    workers = {n: _make_agent_node(n, status=worker_status) for n in worker_names}
    return dispatcher, workers, _StubGraphLoader(workers)


class TestInsideAStage:
    def test_an_agent_added_inside_a_stage_comes_back_inside_it(self):
        """Its result is kept: on the resume it is not asked to run a second time."""
        run_id = "dispatch-in-stage"
        cp = CheckpointService(run_id)
        dispatcher, workers, loader = _dispatcher_with_workers(["worker_1", "worker_2"])
        # the failure comes after the stage, so the agents it added did finish
        gate = _make_agent_node("gate", depends_on=["build"], status=Status.FAILED)
        stage = StageNode(NodeConfig(name="build"), [dispatcher])
        execute_graph([stage, gate], {"task": "x"}, _ctx(run_id, cp, loader),
                      graph_name="wf", is_workflow=True)

        assert cp.reconstruct().get("build.worker_1") is not None

        for w in workers.values():
            w.run.reset_mock()
        dispatcher.run.reset_mock()
        execute_graph([StageNode(NodeConfig(name="build"), [dispatcher]), gate], {"task": "x"},
                      _ctx(run_id, cp, loader), graph_name="wf", is_workflow=True,
                      initial_outputs=cp.reconstruct())

        assert not workers["worker_1"].run.called
        assert not workers["worker_2"].run.called
        assert not dispatcher.run.called

    def test_it_is_written_down_with_the_stage_it_was_added_to(self):
        run_id = "dispatch-path"
        cp = CheckpointService(run_id)
        dispatcher, _, loader = _dispatcher_with_workers(["worker_1"])
        stage = StageNode(NodeConfig(name="build"), [dispatcher])
        execute_graph([stage], {"task": "x"}, _ctx(run_id, cp, loader),
                      graph_name="wf", is_workflow=True)

        entry = cp.resume_state()["dispatches"][0]
        assert entry["dispatcher"] == "build.splitter"
        assert entry["graph_path"] == "build"

    def test_a_stage_does_not_take_back_another_stage_s_agents(self):
        """Two stages, each with its own dispatcher: neither ends up with the other's."""
        run_id = "dispatch-two-stages"
        cp = CheckpointService(run_id)
        first = _make_dispatcher_node("splitter", _adds("alpha_1"))
        second = _make_dispatcher_node("splitter", _adds("beta_1"))
        loader = _StubGraphLoader({n: _make_agent_node(n) for n in ("alpha_1", "beta_1")})
        stages = [StageNode(NodeConfig(name="alpha"), [first]),
                  StageNode(NodeConfig(name="beta", depends_on=["alpha"]), [second])]
        execute_graph(stages, {"task": "x"}, _ctx(run_id, cp, loader),
                      graph_name="wf", is_workflow=True)

        done = cp.reconstruct()
        assert "alpha.alpha_1" in done
        assert "beta.beta_1" in done
        assert "alpha.beta_1" not in done


class TestAtTheTopLevel:
    def test_agents_added_at_the_top_come_back_at_the_top(self):
        run_id = "dispatch-top"
        cp = CheckpointService(run_id)
        dispatcher, workers, loader = _dispatcher_with_workers(["worker_1"])
        later = _make_agent_node("later", depends_on=["splitter"], status=Status.FAILED)
        execute_graph([dispatcher, later], {"task": "x"}, _ctx(run_id, cp, loader),
                      graph_name="wf", is_workflow=True)

        workers["worker_1"].run.reset_mock()
        execute_graph([dispatcher, later], {"task": "x"}, _ctx(run_id, cp, loader),
                      graph_name="wf", is_workflow=True, initial_outputs=cp.reconstruct())

        assert not workers["worker_1"].run.called

    def test_an_added_agent_that_failed_runs_again_and_the_others_do_not(self):
        run_id = "dispatch-one-failed"
        cp = CheckpointService(run_id)
        dispatcher = _make_dispatcher_node("splitter", _adds("worker_1", "worker_2"))
        good = _make_agent_node("worker_1")
        bad = _make_agent_node("worker_2", status=Status.FAILED)
        loader = _StubGraphLoader({"worker_1": good, "worker_2": bad})
        execute_graph([dispatcher], {"task": "x"}, _ctx(run_id, cp, loader),
                      graph_name="wf", is_workflow=True)

        good.run.reset_mock()
        bad.run.reset_mock()
        bad.run.return_value = NodeResult(status=Status.COMPLETED, output="ok")
        result = execute_graph([dispatcher], {"task": "x"}, _ctx(run_id, cp, loader),
                               graph_name="wf", is_workflow=True,
                               initial_outputs=cp.reconstruct())

        assert bad.run.called
        assert not good.run.called
        assert result.status == Status.COMPLETED


class TestADispatcherThatRunsAgain:
    def test_its_agents_are_not_put_back_because_it_adds_them_itself(self):
        """Otherwise it would come to add names that are already in the graph."""
        run_id = "dispatch-rerun"
        cp = CheckpointService(run_id)
        dispatcher = _make_dispatcher_node("splitter", _adds("worker_1"))
        worker = _make_agent_node("worker_1")
        loader = _StubGraphLoader({"worker_1": worker})
        execute_graph([dispatcher], {"task": "x"}, _ctx(run_id, cp, loader),
                      graph_name="wf", is_workflow=True)

        # the dispatcher itself is being run again (the plan says so)
        from temper_ai.stage.restore import Restore
        state = cp.resume_state()
        ctx = _ctx(run_id, cp, loader)
        ctx.restore = Restore(cp.reconstruct(), state["loops"], rerun=["splitter"],
                              dispatches=state["dispatches"])
        dispatcher.run.reset_mock()
        worker.run.reset_mock()
        result = execute_graph([dispatcher], {"task": "x"}, ctx, graph_name="wf",
                               is_workflow=True, initial_outputs={})

        assert dispatcher.run.called
        assert worker.run.called  # added afresh by the dispatcher, and run
        assert result.status == Status.COMPLETED


class TestARewind:
    def test_a_loop_rewind_drops_the_agents_of_the_pass_it_throws_away(self):
        """The next pass dispatches for itself; without this the agents come back twice."""
        run_id = "dispatch-rewind"
        cp = CheckpointService(run_id)
        cp.save_dispatch_applied(
            dispatcher_name="splitter", added_nodes=[{"name": "worker_1", "agent": "x"}],
            removed_targets=[], dispatcher_depth=0, dispatcher_fingerprint=("a", "b"),
            dispatched_count_delta=1, graph_path="",
        )
        cp.save_loop_rewind(trigger_node="checker", target_node="splitter",
                            cleared_nodes=["splitter", "worker_1"])

        assert cp.resume_state()["dispatches"] == []

    def test_agents_added_before_the_rewind_elsewhere_are_kept(self):
        run_id = "dispatch-rewind-other"
        cp = CheckpointService(run_id)
        cp.save_dispatch_applied(
            dispatcher_name="other", added_nodes=[{"name": "kept_1", "agent": "x"}],
            removed_targets=[], dispatcher_depth=0, dispatcher_fingerprint=("a", "b"),
            dispatched_count_delta=1, graph_path="",
        )
        cp.save_loop_rewind(trigger_node="checker", target_node="splitter",
                            cleared_nodes=["splitter"])

        assert [d["dispatcher"] for d in cp.resume_state()["dispatches"]] == ["other"]


class TestARunSavedBeforeThisChange:
    def test_a_dispatch_kept_by_name_alone_finds_its_graph(self):
        """Rows written by the temper before this have no graph of their own."""
        run_id = "dispatch-old-record"
        cp = CheckpointService(run_id)
        dispatcher = _make_dispatcher_node("splitter", _adds("worker_1"))
        worker = _make_agent_node("worker_1")
        loader = _StubGraphLoader({"worker_1": worker})
        cp.save_node_completed("splitter", NodeResult(status=Status.COMPLETED, output="done"))
        cp.save_node_completed("worker_1", NodeResult(status=Status.COMPLETED, output="ok"))
        cp._save(  # what the older temper wrote: no graph_path at all
            event_type="dispatch_applied", node_name="splitter",
            metadata_={"added_nodes": [{"name": "worker_1", "agent": "x"}],
                       "removed_targets": [], "dispatcher_depth": 0,
                       "dispatcher_fingerprint": ["a", "b"], "dispatched_count_delta": 1},
        )
        later = _make_agent_node("later", depends_on=["splitter"])

        execute_graph([dispatcher, later], {"task": "x"}, _ctx(run_id, cp, loader),
                      graph_name="wf", is_workflow=True, initial_outputs=cp.reconstruct())

        assert not worker.run.called  # found, and kept


class TestADispatchThatTookANodeOut:
    def test_what_it_removed_stays_out_on_the_resume(self):
        """The "replace" shape: a kept dispatcher will not take it out a second time."""
        run_id = "dispatch-removed"
        cp = CheckpointService(run_id)
        dispatcher = _make_dispatcher_node(
            "picker",
            [{"op": "remove", "target": "placeholder"},
             {"op": "add", "node": {"name": "real", "agent": "x"}}],
        )
        placeholder = _make_agent_node("placeholder", depends_on=["picker"])
        real = _make_agent_node("real")
        loader = _StubGraphLoader({"real": real})
        execute_graph([dispatcher, placeholder], {"task": "x"}, _ctx(run_id, cp, loader),
                      graph_name="wf", is_workflow=True)

        assert not placeholder.run.called

        placeholder.run.reset_mock()
        real.run.reset_mock()
        execute_graph([dispatcher, placeholder], {"task": "x"}, _ctx(run_id, cp, loader),
                      graph_name="wf", is_workflow=True, initial_outputs=cp.reconstruct())

        assert not placeholder.run.called
        assert not real.run.called


class TestWithNoLoader:
    def test_a_resume_that_cannot_build_them_says_so_and_carries_on(self, caplog):
        run_id = "dispatch-no-loader"
        cp = CheckpointService(run_id)
        cp.save_node_completed("splitter", NodeResult(status=Status.COMPLETED, output="done"))
        cp.save_dispatch_applied(
            dispatcher_name="splitter", added_nodes=[{"name": "worker_1", "agent": "x"}],
            removed_targets=[], dispatcher_depth=0, dispatcher_fingerprint=("a", "b"),
            dispatched_count_delta=1, graph_path="",
        )
        dispatcher = _make_dispatcher_node("splitter", _adds("worker_1"))
        ctx = _make_context(run_id=run_id, checkpoint_service=cp, graph_loader=None,
                            cancel_event=threading.Event())

        result = execute_graph([dispatcher], {"task": "x"}, ctx, graph_name="wf",
                               is_workflow=True, initial_outputs=cp.reconstruct())

        assert result.status == Status.COMPLETED
        assert "no graph loader" in caplog.text


class TestManyAgentsAtOnce:
    def test_a_dozen_come_back_and_only_the_failed_one_runs_again(self):
        """Twelve added at once, one of them chained after the rest, and it fails."""
        run_id = "dispatch-twelve"
        cp = CheckpointService(run_id)
        names = [f"worker_{i}" for i in range(12)]
        dispatcher = _make_dispatcher_node("splitter", [
            *_adds(*names),
            {"op": "add", "node": {"name": "rollup", "agent": "x", "depends_on": names}},
        ])
        workers = {n: _make_agent_node(n) for n in names}
        rollup = _make_agent_node("rollup", depends_on=names, status=Status.FAILED)
        loader = _StubGraphLoader({**workers, "rollup": rollup})
        execute_graph([dispatcher], {"task": "x"}, _ctx(run_id, cp, loader),
                      graph_name="wf", is_workflow=True)

        assert all(f"worker_{i}" in cp.reconstruct() for i in range(12))

        for w in workers.values():
            w.run.reset_mock()
        rollup.run.reset_mock()
        rollup.run.return_value = NodeResult(status=Status.COMPLETED, output="ok")
        result = execute_graph([dispatcher], {"task": "x"}, _ctx(run_id, cp, loader),
                               graph_name="wf", is_workflow=True,
                               initial_outputs=cp.reconstruct())

        assert not any(w.run.called for w in workers.values())
        assert rollup.run.called
        assert result.status == Status.COMPLETED

    def test_one_that_never_finished_is_the_only_one_that_runs(self):
        """A crash left one of them with no result at all."""
        run_id = "dispatch-unfinished"
        cp = CheckpointService(run_id)
        names = ["worker_0", "worker_1", "worker_2"]
        dispatcher, workers, loader = _dispatcher_with_workers(names)
        execute_graph([dispatcher], {"task": "x"}, _ctx(run_id, cp, loader),
                      graph_name="wf", is_workflow=True)

        done = {k: v for k, v in cp.reconstruct().items() if k != "worker_2"}
        for w in workers.values():
            w.run.reset_mock()
        execute_graph([dispatcher], {"task": "x"}, _ctx(run_id, cp, loader),
                      graph_name="wf", is_workflow=True, initial_outputs=done)

        assert workers["worker_2"].run.called
        assert not workers["worker_0"].run.called
        assert not workers["worker_1"].run.called
