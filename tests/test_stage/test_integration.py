"""Integration tests — full workflow execution with YAML configs and mock LLM.

Tests the complete pipeline:
    YAML config → ConfigStore → GraphLoader → execute_graph → AgentNode → LLMAgent → result
"""

import pytest
from unittest.mock import MagicMock

from temper_ai.config.store import ConfigStore
from temper_ai.llm.models import LLMResponse
from temper_ai.shared.types import ExecutionContext, Status
from temper_ai.stage.executor import execute_graph
from temper_ai.stage.loader import GraphLoader
from temper_ai.tools.executor import ToolExecutor


def _mock_llm(response_text="Mock LLM response"):
    """Create a mock LLM provider that returns a fixed response.

    Must return a proper LLMResponse dataclass (not MagicMock attributes)
    because the LLM service records token counts to the DB as JSON.
    """
    llm = MagicMock()
    llm.provider_name = "mock"
    llm.model = "mock-model"
    llm.temperature = 0.7
    llm.max_tokens = 4096

    response = LLMResponse(
        content=response_text,
        tool_calls=None,
        model="mock-model",
        provider="mock",
        prompt_tokens=100,
        completion_tokens=50,
        total_tokens=150,
        finish_reason="stop",
    )
    llm.complete.return_value = response
    # stream() returns an empty iterator
    llm.stream.return_value = iter([])
    # count_tokens returns a fixed count
    llm.count_tokens.return_value = 100
    return llm


class _InMemoryRecorder:
    """Thread-safe in-memory event recorder for tests.

    Avoids SQLite threading issues that occur when parallel nodes
    try to write events from different threads.
    """

    def __init__(self):
        import threading
        self.events: list[dict] = []
        self._lock = threading.Lock()
        self._counter = 0

    def record(self, event_type, data=None, parent_id=None, execution_id=None,
               status=None, event_id=None):
        import uuid
        eid = event_id or str(uuid.uuid4())
        with self._lock:
            self.events.append({
                "id": eid,
                "type": str(event_type),
                "parent_id": parent_id,
                "execution_id": execution_id,
                "status": status,
                "data": data or {},
            })
        return eid

    def update_event(self, event_id, status=None, data=None):
        with self._lock:
            for event in self.events:
                if event["id"] == event_id:
                    if status:
                        event["status"] = status
                    if data:
                        event["data"].update(data)
                    return
        # Event not found — OK in tests


def _make_context(llm_response="Mock response", **overrides):
    """Create ExecutionContext with in-memory recorder and mock LLM."""
    llm = _mock_llm(llm_response)

    defaults = {
        "run_id": "test-run-1",
        "workflow_name": "test",
        "node_path": "",
        "agent_name": "",
        "event_recorder": _InMemoryRecorder(),
        "tool_executor": ToolExecutor(),
        "llm_providers": {"mock": llm},
        "stream_callback": None,
    }
    defaults.update(overrides)
    return ExecutionContext(**defaults)


@pytest.fixture(autouse=True)
def _patch_observability_record(monkeypatch):
    """Patch module-level record/update_event functions used by LLMAgent and LLMService.

    These modules import record() directly from temper_ai.observability,
    bypassing context.event_recorder. We redirect them to a thread-safe
    in-memory implementation to avoid SQLite threading issues.
    """
    recorder = _InMemoryRecorder()

    def patched_record(event_type, data=None, parent_id=None, execution_id=None,
                       status=None, event_id=None):
        return recorder.record(event_type, data=data, parent_id=parent_id,
                               execution_id=execution_id, status=status, event_id=event_id)

    def patched_update(event_id, status=None, data=None):
        return recorder.update_event(event_id, status=status, data=data)

    monkeypatch.setattr("temper_ai.agent.llm_agent._default_record", patched_record)
    monkeypatch.setattr("temper_ai.llm.service.record", patched_record)


def _setup_configs(store: ConfigStore, workflow_config: dict,
                   agent_configs: dict[str, dict] | None = None):
    """Import workflow and agent configs into the store."""
    store.put(workflow_config["name"], "workflow", workflow_config)
    for name, config in (agent_configs or {}).items():
        store.put(name, "agent", config)


class TestSimpleAgentWorkflow:
    """Single agent node — the simplest possible workflow."""

    def test_single_agent_runs(self):
        store = ConfigStore()
        _setup_configs(store, {
            "name": "simple",
            "nodes": [
                {"name": "greeter", "type": "agent", "agent": "agents/greeter"},
            ],
        }, {
            "greeter": {
                "name": "greeter",
                "type": "llm",
                "provider": "mock",
                "model": "mock-model",
                "system_prompt": "You are a friendly greeter.",
                "task_template": "Say hello to {{ name }}.",
            },
        })

        loader = GraphLoader(store)
        nodes, config = loader.load_workflow("simple")
        ctx = _make_context(llm_response="Hello there!")

        result = execute_graph(nodes, {"name": "World"}, ctx,
                               graph_name="simple", is_workflow=True)

        assert result.status == Status.COMPLETED
        assert result.output == "Hello there!"
        assert len(result.agent_results) == 1
        assert result.cost_usd > 0

    def test_agent_with_task_override(self):
        store = ConfigStore()
        _setup_configs(store, {
            "name": "override_test",
            "nodes": [{
                "name": "reviewer",
                "type": "agent",
                "agent": "agents/engineer",
                "task_template": "Review this code: {{ code }}",
                "model": "mock-override",
            }],
        }, {
            "engineer": {
                "name": "engineer",
                "type": "llm",
                "provider": "mock",
                "model": "mock-base",
                "system_prompt": "You are an engineer.",
                "task_template": "Default task: {{ task }}",
            },
        })

        loader = GraphLoader(store)
        nodes, _ = loader.load_workflow("override_test")

        # Verify the override was applied
        agent_config = nodes[0].agent_config
        assert agent_config["model"] == "mock-override"
        assert "Review this code" in agent_config["task_template"]
        # Base preserved
        assert agent_config["system_prompt"] == "You are an engineer."


class TestSequentialWorkflow:
    """Two agents in sequence — B depends on A."""

    def test_sequential_chain(self):
        store = ConfigStore()
        _setup_configs(store, {
            "name": "sequential",
            "nodes": [
                {"name": "planner", "type": "agent", "agent": "agents/planner"},
                {"name": "coder", "type": "agent", "agent": "agents/coder",
                 "depends_on": ["planner"]},
            ],
        }, {
            "planner": {
                "name": "planner", "type": "llm", "provider": "mock",
                "system_prompt": "Plan the work.",
                "task_template": "Plan: {{ task }}",
            },
            "coder": {
                "name": "coder", "type": "llm", "provider": "mock",
                "system_prompt": "Write code.",
                "task_template": "Code: {{ task }}",
            },
        })

        loader = GraphLoader(store)
        nodes, _ = loader.load_workflow("sequential")
        ctx = _make_context(llm_response="Done coding")

        result = execute_graph(nodes, {"task": "build a thing"}, ctx,
                               graph_name="sequential", is_workflow=True)

        assert result.status == Status.COMPLETED
        assert len(result.agent_results) == 2
        assert "planner" in result.node_results
        assert "coder" in result.node_results


class TestParallelStageWorkflow:
    """Stage with parallel strategy — two coders run concurrently."""

    def test_parallel_coders(self):
        store = ConfigStore()
        _setup_configs(store, {
            "name": "parallel_test",
            "nodes": [{
                "name": "code",
                "type": "stage",
                "strategy": "parallel",
                "agents": ["agents/coder_a", "agents/coder_b"],
            }],
        }, {
            "coder_a": {
                "name": "coder_a", "type": "llm", "provider": "mock",
                "system_prompt": "Code agent A",
                "task_template": "{{ task }}",
            },
            "coder_b": {
                "name": "coder_b", "type": "llm", "provider": "mock",
                "system_prompt": "Code agent B",
                "task_template": "{{ task }}",
            },
        })

        loader = GraphLoader(store)
        nodes, _ = loader.load_workflow("parallel_test")
        ctx = _make_context(llm_response="Coded!")

        result = execute_graph(nodes, {"task": "build"}, ctx,
                               graph_name="parallel_test", is_workflow=True)

        assert result.status == Status.COMPLETED
        # Stage node contains 2 agents internally
        assert len(result.agent_results) >= 2


class TestLeaderStageWorkflow:
    """Stage with leader strategy — workers + synthesizer."""

    def test_leader_synthesis(self):
        store = ConfigStore()
        _setup_configs(store, {
            "name": "leader_test",
            "nodes": [{
                "name": "review",
                "type": "stage",
                "strategy": "leader",
                "agents": [
                    "agents/security",
                    "agents/quality",
                    {"agent": "agents/decider", "role": "leader"},
                ],
            }],
        }, {
            "security": {
                "name": "security", "type": "llm", "provider": "mock",
                "system_prompt": "Security review",
                "task_template": "{{ task }}",
            },
            "quality": {
                "name": "quality", "type": "llm", "provider": "mock",
                "system_prompt": "Quality review",
                "task_template": "{{ task }}",
            },
            "decider": {
                "name": "decider", "type": "llm", "provider": "mock",
                "system_prompt": "Synthesize reviews",
                "task_template": "Reviews: {{ other_agents }}",
            },
        })

        loader = GraphLoader(store)
        nodes, _ = loader.load_workflow("leader_test")
        ctx = _make_context(llm_response="Approved")

        result = execute_graph(nodes, {"task": "review code"}, ctx,
                               graph_name="leader_test", is_workflow=True)

        assert result.status == Status.COMPLETED
        assert len(result.agent_results) == 3


class TestConditionalWorkflow:
    """Conditional node — ship only runs if review passes."""

    def test_condition_skips_node(self):
        store = ConfigStore()
        _setup_configs(store, {
            "name": "conditional",
            "nodes": [
                {"name": "review", "type": "agent", "agent": "agents/reviewer"},
                {"name": "ship", "type": "agent", "agent": "agents/shipper",
                 "depends_on": ["review"],
                 "condition": {
                     "source": "review.structured.verdict",
                     "operator": "equals",
                     "value": "PASS",
                 }},
            ],
        }, {
            "reviewer": {
                "name": "reviewer", "type": "llm", "provider": "mock",
                "system_prompt": "Review", "task_template": "{{ task }}",
            },
            "shipper": {
                "name": "shipper", "type": "llm", "provider": "mock",
                "system_prompt": "Ship", "task_template": "{{ task }}",
            },
        })

        loader = GraphLoader(store)
        nodes, _ = loader.load_workflow("conditional")

        # Mock LLM returns FAIL verdict
        ctx = _make_context(llm_response='{"verdict": "FAIL", "reason": "bugs"}')

        result = execute_graph(nodes, {"task": "ship it"}, ctx,
                               graph_name="conditional", is_workflow=True)

        assert result.status == Status.COMPLETED
        assert result.node_results["review"].status == Status.COMPLETED
        assert result.node_results["ship"].status == Status.SKIPPED

    def test_condition_passes_node(self):
        store = ConfigStore()
        _setup_configs(store, {
            "name": "conditional",
            "nodes": [
                {"name": "review", "type": "agent", "agent": "agents/reviewer"},
                {"name": "ship", "type": "agent", "agent": "agents/shipper",
                 "depends_on": ["review"],
                 "condition": {
                     "source": "review.structured.verdict",
                     "operator": "equals",
                     "value": "PASS",
                 }},
            ],
        }, {
            "reviewer": {
                "name": "reviewer", "type": "llm", "provider": "mock",
                "system_prompt": "Review", "task_template": "{{ task }}",
            },
            "shipper": {
                "name": "shipper", "type": "llm", "provider": "mock",
                "system_prompt": "Ship", "task_template": "{{ task }}",
            },
        })

        loader = GraphLoader(store)
        nodes, _ = loader.load_workflow("conditional")

        # Mock LLM returns PASS verdict
        ctx = _make_context(llm_response='{"verdict": "PASS"}')

        result = execute_graph(nodes, {"task": "ship it"}, ctx,
                               graph_name="conditional", is_workflow=True)

        assert result.node_results["review"].status == Status.COMPLETED
        assert result.node_results["ship"].status == Status.COMPLETED


class TestFullPipeline:
    """Multi-stage workflow: plan → code (parallel) → review."""

    def test_plan_code_review(self):
        store = ConfigStore()
        _setup_configs(store, {
            "name": "pipeline",
            "nodes": [
                {"name": "plan", "type": "agent", "agent": "agents/planner"},
                {"name": "code", "type": "stage", "strategy": "parallel",
                 "agents": ["agents/coder_a", "agents/coder_b"],
                 "depends_on": ["plan"]},
                {"name": "review", "type": "agent", "agent": "agents/reviewer",
                 "depends_on": ["code"]},
            ],
        }, {
            "planner": {
                "name": "planner", "type": "llm", "provider": "mock",
                "system_prompt": "Plan", "task_template": "{{ task }}",
            },
            "coder_a": {
                "name": "coder_a", "type": "llm", "provider": "mock",
                "system_prompt": "Code A", "task_template": "{{ task }}",
            },
            "coder_b": {
                "name": "coder_b", "type": "llm", "provider": "mock",
                "system_prompt": "Code B", "task_template": "{{ task }}",
            },
            "reviewer": {
                "name": "reviewer", "type": "llm", "provider": "mock",
                "system_prompt": "Review", "task_template": "{{ task }}",
            },
        })

        loader = GraphLoader(store)
        nodes, _ = loader.load_workflow("pipeline")
        ctx = _make_context(llm_response="Done")

        result = execute_graph(nodes, {"task": "build feature"}, ctx,
                               graph_name="pipeline", is_workflow=True)

        assert result.status == Status.COMPLETED
        assert "plan" in result.node_results
        assert "code" in result.node_results
        assert "review" in result.node_results
        # plan (1 agent) + code (2 agents in stage) + review (1 agent) = 4 agents
        assert len(result.agent_results) == 4
        assert result.cost_usd > 0
        assert result.total_tokens > 0


class TestNestedStages:
    """Stage containing explicit child nodes with dependencies."""

    def test_stage_with_internal_deps(self):
        store = ConfigStore()
        _setup_configs(store, {
            "name": "nested",
            "nodes": [{
                "name": "review",
                "type": "stage",
                "nodes": [
                    {"name": "sec", "type": "agent", "agent": "agents/sec"},
                    {"name": "qual", "type": "agent", "agent": "agents/qual"},
                    {"name": "decider", "type": "agent", "agent": "agents/decider",
                     "depends_on": ["sec", "qual"]},
                ],
            }],
        }, {
            "sec": {"name": "sec", "type": "llm", "provider": "mock",
                    "system_prompt": "Security", "task_template": "{{ task }}"},
            "qual": {"name": "qual", "type": "llm", "provider": "mock",
                     "system_prompt": "Quality", "task_template": "{{ task }}"},
            "decider": {"name": "decider", "type": "llm", "provider": "mock",
                        "system_prompt": "Decide", "task_template": "{{ task }}"},
        })

        loader = GraphLoader(store)
        nodes, _ = loader.load_workflow("nested")
        ctx = _make_context(llm_response="Approved")

        result = execute_graph(nodes, {"task": "review"}, ctx,
                               graph_name="nested", is_workflow=True)

        assert result.status == Status.COMPLETED
        # 3 agents total (sec, qual, decider)
        assert len(result.agent_results) == 3


class TestAgentIdentityReuse:
    """Same agent config used in multiple nodes — different tasks, shared identity."""

    def test_same_agent_different_tasks(self):
        store = ConfigStore()
        _setup_configs(store, {
            "name": "reuse_test",
            "nodes": [
                {"name": "design_review", "type": "agent",
                 "agent": "agents/engineer",
                 "task_template": "Review design: {{ design }}"},
                {"name": "code_review", "type": "agent",
                 "agent": "agents/engineer",
                 "depends_on": ["design_review"],
                 "task_template": "Review code: {{ code }}"},
            ],
        }, {
            "engineer": {
                "name": "engineer", "type": "llm", "provider": "mock",
                "system_prompt": "You are a senior engineer.",
                "task_template": "Default: {{ task }}",
            },
        })

        loader = GraphLoader(store)
        nodes, _ = loader.load_workflow("reuse_test")

        # Both nodes reference same agent but have different task_templates
        assert nodes[0].agent_config["system_prompt"] == "You are a senior engineer."
        assert nodes[1].agent_config["system_prompt"] == "You are a senior engineer."
        assert "Review design" in nodes[0].agent_config["task_template"]
        assert "Review code" in nodes[1].agent_config["task_template"]

        ctx = _make_context(llm_response="LGTM")
        result = execute_graph(nodes, {"design": "...", "code": "..."}, ctx,
                               graph_name="reuse_test", is_workflow=True)

        assert result.status == Status.COMPLETED
        assert len(result.agent_results) == 2
