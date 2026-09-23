"""Tests for Delegate tool.

The validation guards were already covered; everything past them — loading
the agent, putting it on the graph, running it, closing its event — was not.
These tests drive the real execution path with in-memory infrastructure so
the assertions are about what Delegate actually records and returns, not
about which mocks it touched.
"""

import json
import threading
from dataclasses import dataclass, field
from unittest.mock import MagicMock

import pytest

from temper_ai.shared.types import AgentResult, ExecutionContext, Status, TokenUsage
from temper_ai.tools.delegate import Delegate


class TestDelegateValidation:
    def test_no_context_bound(self):
        d = Delegate()
        r = d.execute(tasks=[{"agent": "test", "inputs": {}}])
        assert r.success is False
        assert "context" in r.error.lower() or "bound" in r.error.lower()

    def test_empty_tasks(self):
        d = Delegate()
        d._execution_context = MagicMock()
        r = d.execute(tasks=[])
        assert r.success is False

    def test_no_tasks_param(self):
        d = Delegate()
        d._execution_context = MagicMock()
        r = d.execute()
        assert r.success is False


class TestDelegateBindContext:
    def test_bind_context(self):
        d = Delegate()
        ctx = MagicMock()
        d.bind_context(ctx)
        assert d._execution_context is ctx

    def test_bind_context_overrides(self):
        d = Delegate()
        ctx1 = MagicMock()
        ctx2 = MagicMock()
        d.bind_context(ctx1)
        d.bind_context(ctx2)
        assert d._execution_context is ctx2


# ── harness ──────────────────────────────────────────────────────────────


@dataclass
class FakeRecorder:
    """Records events in memory the way ObservabilityRecorder does on a run."""

    events: list = field(default_factory=list)
    updates: list = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def record(self, event_type: str, **kw) -> str:
        with self._lock:
            event_id = f"ev{len(self.events)}"
            self.events.append({"id": event_id, "type": event_type, **kw})
        return event_id

    def update_event(self, event_id: str, **kw) -> None:
        with self._lock:
            self.updates.append({"id": event_id, **kw})

    def started(self) -> list[dict]:
        return [e for e in self.events if e["type"] == "stage.started"]

    def update_for(self, event_id: str) -> dict:
        matches = [u for u in self.updates if u["id"] == event_id]
        assert matches, f"no update recorded for {event_id}; updates={self.updates}"
        return matches[-1]


class FakeAgent:
    """Stands in for whatever create_agent returns."""

    def __init__(self, result=None, raises=None, on_run=None):
        self._result = result
        self._raises = raises
        self._on_run = on_run
        self.calls: list[tuple[dict, ExecutionContext]] = []

    def run(self, inputs, ctx):
        self.calls.append((inputs, ctx))
        if self._on_run is not None:
            self._on_run()
        if self._raises is not None:
            raise self._raises
        return self._result if self._result is not None else ok_result()


def ok_result(output="done", status=Status.COMPLETED, **kw) -> AgentResult:
    return AgentResult(
        status=status,
        output=output,
        tokens=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        cost_usd=0.25,
        duration_seconds=1.5,
        **kw,
    )


@pytest.fixture
def wire(monkeypatch):
    """Patch the two things Delegate imports inside execute().

    Returns a callable: wire(agents={...}, configs={...}) -> created agents.
    Config values are stored wrapped, the way the YAML importer stores them,
    so the real _unwrap_config runs.
    """

    def _wire(agents: dict, configs: dict | None = None, workflow_raises: bool = False):
        configs = configs if configs is not None else {}
        created: list[dict] = []

        class FakeStore:
            def get(self, name, config_type):
                if config_type == "workflow":
                    if workflow_raises:
                        raise RuntimeError("no such workflow")
                    return {"workflow": configs.get("__workflow__", {})}
                if name not in configs:
                    raise KeyError(f"agent config '{name}' not found")
                return {"agent": configs[name]}

        def fake_create_agent(config):
            created.append(config)
            return agents[config.get("name", "")]

        monkeypatch.setattr("temper_ai.config.ConfigStore", FakeStore)
        monkeypatch.setattr("temper_ai.agent.create_agent", fake_create_agent)
        return created

    return _wire


def make_ctx(recorder: FakeRecorder, **over) -> ExecutionContext:
    base = dict(
        run_id="run-1",
        workflow_name="wf",
        node_path="caller",
        agent_name="caller_agent",
        event_recorder=recorder,
        tool_executor=None,
        graph_event_id="graph-1",
        parent_event_id="parent-1",
    )
    base.update(over)
    return ExecutionContext(**base)


def bound(ctx, **config) -> Delegate:
    d = Delegate(config or None)
    d.bind_context(ctx)
    return d


# ── the execution path ───────────────────────────────────────────────────


class TestDelegateRunsTheAgent:
    def test_single_task_returns_the_agents_output(self, wire):
        rec = FakeRecorder()
        agent = FakeAgent(ok_result(output="built it"))
        wire(agents={"impl": agent}, configs={"impl": {"name": "impl"}})

        r = bound(make_ctx(rec)).execute(tasks=[{"agent": "impl", "inputs": {"file": "a.py"}}])

        assert r.success is True
        assert r.error is None
        payload = json.loads(r.result)
        assert len(payload) == 1
        assert payload[0] == {
            "task_index": 0,
            "agent": "impl",
            "status": "completed",
            "output": "built it",
            "structured_output": None,
            "error": None,
            "cost_usd": 0.25,
            "tokens": 15,
        }
        assert r.metadata == {"task_count": 1, "completed": 1, "failed": 0}
        assert agent.calls[0][0] == {"file": "a.py"}

    def test_agent_config_wins_over_workflow_defaults(self, wire):
        """The merge direction is load-bearing: a workflow default must not
        clobber a setting the agent config states explicitly."""
        rec = FakeRecorder()
        created = wire(
            agents={"impl": FakeAgent()},
            configs={
                "__workflow__": {"defaults": {"model": "wf-model", "timeout": 30}},
                "impl": {"name": "impl", "model": "agent-model"},
            },
        )

        bound(make_ctx(rec)).execute(tasks=[{"agent": "impl"}])

        assert created[0]["model"] == "agent-model"  # agent overrides
        assert created[0]["timeout"] == 30  # default still inherited

    def test_a_delegated_jev_agent_is_not_given_the_workflows_llm(self, wire):
        """A jev agent's `model` is the Jev model: the workflow's default LLM model, merged in,
        would be sent to TypeSafe as one."""
        rec = FakeRecorder()
        created = wire(
            agents={"triage": FakeAgent(), "impl": FakeAgent()},
            configs={
                "__workflow__": {"defaults": {"provider": "vllm", "model": "qwen3", "timeout": 30}},
                "triage": {"name": "triage", "type": "jev"},
                "impl": {"name": "impl"},
            },
        )

        bound(make_ctx(rec)).execute(tasks=[{"agent": "triage"}, {"agent": "impl"}])

        jev, llm = sorted(created, key=lambda c: c["name"] != "triage")
        assert "model" not in jev and "provider" not in jev
        assert jev["timeout"] == 30  # what isn't an LLM setting still reaches it
        assert (llm["provider"], llm["model"]) == ("vllm", "qwen3")

    def test_an_unloadable_workflow_does_not_stop_delegation(self, wire):
        rec = FakeRecorder()
        wire(agents={"impl": FakeAgent()}, configs={"impl": {"name": "impl"}}, workflow_raises=True)

        r = bound(make_ctx(rec)).execute(tasks=[{"agent": "impl"}])

        assert r.success is True

    def test_missing_inputs_key_passes_an_empty_dict(self, wire):
        rec = FakeRecorder()
        agent = FakeAgent()
        wire(agents={"impl": agent}, configs={"impl": {"name": "impl"}})

        bound(make_ctx(rec)).execute(tasks=[{"agent": "impl"}])

        assert agent.calls[0][0] == {}


class TestDelegateAttachesToTheGraph:
    def test_delegated_node_is_a_sibling_on_the_graph(self, wire):
        rec = FakeRecorder()
        wire(agents={"impl": FakeAgent()}, configs={"impl": {"name": "impl"}})

        bound(make_ctx(rec)).execute(tasks=[{"agent": "impl"}])

        started = rec.started()
        assert len(started) == 1
        ev = started[0]
        assert ev["parent_id"] == "graph-1"
        assert ev["execution_id"] == "run-1"
        assert ev["status"] == "running"
        assert ev["data"]["name"] == "delegate:impl_0"
        assert ev["data"]["type"] == "delegate"
        assert ev["data"]["depends_on"] == ["caller"]
        assert ev["data"]["delegated_by"] == "caller_agent"
        assert ev["data"]["delegate_source"] == "caller"

    def test_without_a_graph_event_it_hangs_off_the_parent(self, wire):
        rec = FakeRecorder()
        wire(agents={"impl": FakeAgent()}, configs={"impl": {"name": "impl"}})

        bound(make_ctx(rec, graph_event_id=None)).execute(tasks=[{"agent": "impl"}])

        assert rec.started()[0]["parent_id"] == "parent-1"

    def test_the_child_runs_underneath_the_delegate_node(self, wire):
        """Events the delegated agent emits must nest under its own node, and
        its node_path must be distinct from the caller's."""
        rec = FakeRecorder()
        agent = FakeAgent()
        wire(agents={"impl": FakeAgent(), "worker": agent}, configs={"ref": {"name": "worker"}})

        bound(make_ctx(rec)).execute(tasks=[{"agent": "ref"}])

        stage_event_id = rec.started()[0]["id"]
        _, child_ctx = agent.calls[0]
        assert child_ctx.parent_event_id == stage_event_id
        assert child_ctx.agent_name == "worker"
        assert child_ctx.node_path == "caller.delegate.ref_0"
        assert child_ctx.run_id == "run-1"

    def test_completion_closes_the_event_with_the_agents_numbers(self, wire):
        rec = FakeRecorder()
        wire(agents={"impl": FakeAgent()}, configs={"impl": {"name": "impl"}})

        bound(make_ctx(rec)).execute(tasks=[{"agent": "impl"}])

        update = rec.update_for(rec.started()[0]["id"])
        assert update["status"] == "completed"
        assert update["data"]["cost_usd"] == 0.25
        assert update["data"]["total_tokens"] == 15
        assert update["data"]["duration_seconds"] == 1.5


class TestDelegateFailureIsolation:
    def test_an_unloadable_agent_fails_only_its_own_task(self, wire):
        rec = FakeRecorder()
        wire(agents={"impl": FakeAgent()}, configs={"impl": {"name": "impl"}})

        r = bound(make_ctx(rec)).execute(
            tasks=[{"agent": "nope"}, {"agent": "impl"}],
        )

        assert r.success is False
        assert r.error == "1/2 tasks failed"
        payload = json.loads(r.result)
        assert payload[0]["status"] == "failed"
        assert "Failed to load agent 'nope'" in payload[0]["error"]
        assert payload[1]["status"] == "completed"
        assert r.metadata == {"task_count": 2, "completed": 1, "failed": 1}

    def test_an_unloadable_agent_never_reaches_the_graph(self, wire):
        """It failed before it was a node; it must not leave one behind."""
        rec = FakeRecorder()
        wire(agents={}, configs={})

        bound(make_ctx(rec)).execute(tasks=[{"agent": "nope"}])

        assert rec.started() == []

    def test_a_failed_agent_makes_the_whole_call_unsuccessful(self, wire):
        rec = FakeRecorder()
        wire(
            agents={"impl": FakeAgent(ok_result(status=Status.FAILED, output="", error="blew up"))},
            configs={"impl": {"name": "impl"}},
        )

        r = bound(make_ctx(rec)).execute(tasks=[{"agent": "impl"}])

        assert r.success is False
        assert r.error == "1/1 tasks failed"
        assert json.loads(r.result)[0]["error"] == "blew up"
        assert rec.update_for(rec.started()[0]["id"])["status"] == "failed"

    def test_a_raising_agent_does_not_strand_its_node_as_running(self, wire):
        """A node put on the graph must always be closed. If the agent raises,
        the event stays 'running' for the life of the run unless we close it."""
        rec = FakeRecorder()
        wire(
            agents={"impl": FakeAgent(raises=RuntimeError("kaboom"))},
            configs={"impl": {"name": "impl"}},
        )

        r = bound(make_ctx(rec)).execute(tasks=[{"agent": "impl"}])

        stage_event_id = rec.started()[0]["id"]
        assert rec.update_for(stage_event_id)["status"] == "failed"
        assert r.success is False
        payload = json.loads(r.result)
        assert payload[0]["task_index"] == 0
        assert payload[0]["agent"] == "impl"
        assert payload[0]["status"] == "failed"
        assert "kaboom" in payload[0]["error"]

    def test_a_raising_agent_reports_the_same_way_alongside_others(self, wire):
        """One task or five, a raising agent must produce the same structured
        failure — not an exception on one path and JSON on the other."""
        rec = FakeRecorder()
        wire(
            agents={"bad": FakeAgent(raises=RuntimeError("kaboom")), "good": FakeAgent()},
            configs={"bad": {"name": "bad"}, "good": {"name": "good"}},
        )

        r = bound(make_ctx(rec)).execute(tasks=[{"agent": "bad"}, {"agent": "good"}])

        payload = json.loads(r.result)
        assert payload[0]["status"] == "failed"
        assert "kaboom" in payload[0]["error"]
        assert payload[1]["status"] == "completed"
        assert [u["status"] for u in rec.updates].count("failed") == 1

    @pytest.mark.parametrize("task_count", [1, 2])
    def test_a_recorder_that_cannot_write_fails_the_task_not_the_call(self, wire, task_count):
        """The failure happens before the node exists, so there is nothing to
        close — but it must still come back as a result, on either path."""
        rec = FakeRecorder()
        rec.record = MagicMock(side_effect=RuntimeError("recorder down"))
        wire(
            agents={"impl": FakeAgent(), "other": FakeAgent()},
            configs={"impl": {"name": "impl"}, "other": {"name": "other"}},
        )
        tasks = [{"agent": "impl"}, {"agent": "other"}][:task_count]

        r = bound(make_ctx(rec)).execute(tasks=tasks)

        payload = json.loads(r.result)
        assert len(payload) == task_count
        assert r.success is False
        assert all(p["status"] == "failed" for p in payload)
        assert all("recorder down" in p["error"] for p in payload)

    def test_a_failing_checkpoint_does_not_lose_a_finished_result(self, wire):
        """The agent completed; a checkpoint write failing afterwards must not
        turn a completed task into a failed one."""
        rec = FakeRecorder()
        wire(agents={"impl": FakeAgent()}, configs={"impl": {"name": "impl"}})
        checkpoint = MagicMock()
        checkpoint.save_agent_completed.side_effect = RuntimeError("disk full")

        r = bound(make_ctx(rec, checkpoint_service=checkpoint)).execute(
            tasks=[{"agent": "impl"}]
        )

        assert r.success is True
        assert json.loads(r.result)[0]["status"] == "completed"


class TestDelegateConcurrency:
    def test_results_are_ordered_by_task_index_not_by_finish_order(self, wire):
        """as_completed yields in finish order; the output must not."""
        rec = FakeRecorder()
        last_finished = threading.Event()

        def wait_for_last():
            assert last_finished.wait(timeout=5), "third task never finished"

        agents = {
            "a0": FakeAgent(ok_result(output="first"), on_run=wait_for_last),
            "a1": FakeAgent(ok_result(output="second"), on_run=wait_for_last),
            "a2": FakeAgent(ok_result(output="third"), on_run=last_finished.set),
        }
        wire(agents=agents, configs={n: {"name": n} for n in agents})

        r = bound(make_ctx(rec)).execute(
            tasks=[{"agent": "a0"}, {"agent": "a1"}, {"agent": "a2"}]
        )

        payload = json.loads(r.result)
        assert [p["task_index"] for p in payload] == [0, 1, 2]
        assert [p["output"] for p in payload] == ["first", "second", "third"]

    def test_concurrency_is_capped_at_the_configured_maximum(self, wire):
        rec = FakeRecorder()
        lock = threading.Lock()
        live = 0
        peak = 0
        released = threading.Event()

        def occupy():
            nonlocal live, peak
            with lock:
                live += 1
                peak = max(peak, live)
            released.wait(timeout=0.2)
            with lock:
                live -= 1

        agents = {f"a{i}": FakeAgent(on_run=occupy) for i in range(4)}
        wire(agents=agents, configs={n: {"name": n} for n in agents})

        bound(make_ctx(rec), max_concurrency=2).execute(
            tasks=[{"agent": n} for n in agents]
        )

        assert peak <= 2, f"ran {peak} agents at once with max_concurrency=2"

    def test_each_task_gets_its_own_node_and_path(self, wire):
        rec = FakeRecorder()
        agents = {"a0": FakeAgent(), "a1": FakeAgent()}
        wire(agents=agents, configs={n: {"name": n} for n in agents})

        bound(make_ctx(rec)).execute(tasks=[{"agent": "a0"}, {"agent": "a1"}])

        names = sorted(e["data"]["name"] for e in rec.started())
        assert names == ["delegate:a0_0", "delegate:a1_1"]
        paths = sorted(a.calls[0][1].node_path for a in agents.values())
        assert paths == ["caller.delegate.a0_0", "caller.delegate.a1_1"]


class TestDelegateCheckpointing:
    def test_a_completed_agent_is_checkpointed(self, wire):
        rec = FakeRecorder()
        result = ok_result()
        wire(agents={"impl": FakeAgent(result)}, configs={"impl": {"name": "impl"}})
        checkpoint = MagicMock()

        bound(make_ctx(rec, checkpoint_service=checkpoint)).execute(
            tasks=[{"agent": "impl"}]
        )

        checkpoint.save_agent_completed.assert_called_once_with("caller", "impl_0", result)

    def test_without_a_checkpoint_service_nothing_is_persisted(self, wire):
        rec = FakeRecorder()
        wire(agents={"impl": FakeAgent()}, configs={"impl": {"name": "impl"}})

        r = bound(make_ctx(rec, checkpoint_service=None)).execute(tasks=[{"agent": "impl"}])

        assert r.success is True
