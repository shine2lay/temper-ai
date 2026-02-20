"""Tests for PredecessorResolver and predecessor injection wiring."""
from unittest.mock import MagicMock, patch

import pytest

from temper_ai.workflow.context_provider import (
    PredecessorResolver,
    PassthroughResolver,
    SourceResolver,
)
from temper_ai.stage.executors.state_keys import StateKeys


# ---------------------------------------------------------------------------
# PredecessorResolver unit tests
# ---------------------------------------------------------------------------

class TestPredecessorResolverNoDag:
    """PredecessorResolver with no DAG set."""

    def test_no_dag_returns_workflow_inputs(self):
        """Root-like behavior: returns workflow_inputs when no DAG."""
        resolver = PredecessorResolver()
        state = {
            StateKeys.WORKFLOW_INPUTS: {"topic": "AI"},
            StateKeys.STAGE_OUTPUTS: {},
        }
        stage_config = {"stage": {"name": "s1"}}
        result = resolver.resolve(stage_config, state)

        assert result["topic"] == "AI"
        assert result["_context_meta"]["mode"] == "predecessor"
        assert result["_context_meta"]["predecessors"] == []

    def test_no_dag_empty_inputs(self):
        """No DAG and no workflow_inputs returns empty resolved."""
        resolver = PredecessorResolver()
        state = {StateKeys.STAGE_OUTPUTS: {}}
        stage_config = {"stage": {"name": "s1"}}
        result = resolver.resolve(stage_config, state)

        assert "_context_meta" in result
        assert result["_context_meta"]["predecessors"] == []


class TestPredecessorResolverWithDag:
    """PredecessorResolver with DAG set."""

    @staticmethod
    def _make_dag(predecessors):
        """Create a minimal StageDAG-like object."""
        dag = MagicMock()
        dag.predecessors = predecessors
        return dag

    def test_root_stage_gets_workflow_inputs(self):
        """Root stage (no predecessors) receives workflow_inputs."""
        resolver = PredecessorResolver()
        dag = self._make_dag({"s1": [], "s2": ["s1"]})
        resolver.set_dag(dag)

        state = {
            StateKeys.WORKFLOW_INPUTS: {"topic": "AI"},
            StateKeys.STAGE_OUTPUTS: {},
        }
        result = resolver.resolve({"stage": {"name": "s1"}}, state)

        assert result["topic"] == "AI"
        assert result["_context_meta"]["predecessors"] == []

    def test_downstream_stage_gets_predecessor_outputs(self):
        """Downstream stage receives outputs from its predecessors."""
        resolver = PredecessorResolver()
        dag = self._make_dag({"s1": [], "s2": ["s1"]})
        resolver.set_dag(dag)

        state = {
            StateKeys.WORKFLOW_INPUTS: {"topic": "AI"},
            StateKeys.STAGE_OUTPUTS: {
                "s1": {"structured": {"recommendation": "React"}},
            },
        }
        result = resolver.resolve({"stage": {"name": "s2"}}, state)

        assert "s1" in result
        assert result["s1"]["structured"]["recommendation"] == "React"
        assert result["_context_meta"]["predecessors"] == ["s1"]

    def test_skipped_predecessor_excluded(self):
        """Predecessors without recorded output are excluded."""
        resolver = PredecessorResolver()
        dag = self._make_dag({"s3": ["s1", "s2"]})
        resolver.set_dag(dag)

        state = {
            StateKeys.WORKFLOW_INPUTS: {},
            StateKeys.STAGE_OUTPUTS: {
                "s1": {"output": "done"},
                # s2 not in stage_outputs → skipped
            },
        }
        result = resolver.resolve({"stage": {"name": "s3"}}, state)

        assert "s1" in result
        assert "s2" not in result
        assert result["_context_meta"]["predecessors"] == ["s1"]

    def test_multiple_predecessors_merged(self):
        """Fan-in: stage gets outputs from all completed predecessors."""
        resolver = PredecessorResolver()
        dag = self._make_dag({"s3": ["s1", "s2"]})
        resolver.set_dag(dag)

        state = {
            StateKeys.WORKFLOW_INPUTS: {},
            StateKeys.STAGE_OUTPUTS: {
                "s1": {"output": "alpha"},
                "s2": {"output": "beta"},
            },
        }
        result = resolver.resolve({"stage": {"name": "s3"}}, state)

        assert result["s1"]["output"] == "alpha"
        assert result["s2"]["output"] == "beta"
        assert set(result["_context_meta"]["predecessors"]) == {"s1", "s2"}


class TestPredecessorResolverConvergence:
    """PredecessorResolver with dynamic convergence predecessors."""

    def test_convergence_predecessors_override_dag(self):
        """Dynamic convergence predecessors take priority over DAG."""
        resolver = PredecessorResolver()
        dag = MagicMock()
        dag.predecessors = {"s3": ["s1"]}
        resolver.set_dag(dag)

        state = {
            StateKeys.WORKFLOW_INPUTS: {},
            StateKeys.STAGE_OUTPUTS: {
                "s1": {"output": "from_s1"},
                "s2": {"output": "from_s2"},
            },
            "_convergence_predecessors": {
                "s3": ["s1", "s2"],
            },
        }
        result = resolver.resolve({"stage": {"name": "s3"}}, state)

        assert "s1" in result
        assert "s2" in result
        assert set(result["_context_meta"]["predecessors"]) == {"s1", "s2"}


class TestPredecessorResolverInfraKeys:
    """PredecessorResolver copies infrastructure keys."""

    def test_infrastructure_keys_copied(self):
        """Infrastructure keys from state are included in resolved context."""
        resolver = PredecessorResolver()
        tracker = MagicMock()
        state = {
            StateKeys.WORKFLOW_INPUTS: {"x": 1},
            StateKeys.STAGE_OUTPUTS: {},
            StateKeys.TRACKER: tracker,
            StateKeys.WORKFLOW_ID: "wf-123",
        }
        result = resolver.resolve({"stage": {"name": "s1"}}, state)

        assert result[StateKeys.TRACKER] is tracker
        assert result[StateKeys.WORKFLOW_ID] == "wf-123"


# ---------------------------------------------------------------------------
# SourceResolver fallback integration tests
# ---------------------------------------------------------------------------

class TestSourceResolverFallback:
    """SourceResolver with PredecessorResolver as fallback."""

    def test_no_inputs_uses_predecessor_fallback(self):
        """Stage without declared inputs falls back to PredecessorResolver."""
        predecessor = PredecessorResolver()
        dag = MagicMock()
        dag.predecessors = {"s2": ["s1"]}
        predecessor.set_dag(dag)

        resolver = SourceResolver(fallback=predecessor)

        state = {
            StateKeys.WORKFLOW_INPUTS: {"topic": "AI"},
            StateKeys.STAGE_OUTPUTS: {
                "s1": {"output": "research_done"},
            },
        }
        # No inputs declared → fallback
        result = resolver.resolve({"stage": {"name": "s2"}}, state)

        assert result["_context_meta"]["mode"] == "predecessor"
        assert "s1" in result

    def test_with_inputs_uses_source_resolver(self):
        """Stage with declared inputs uses SourceResolver, not fallback."""
        predecessor = PredecessorResolver()
        resolver = SourceResolver(fallback=predecessor)

        state = {
            StateKeys.WORKFLOW_INPUTS: {"topic": "AI"},
            StateKeys.STAGE_OUTPUTS: {
                "s1": {"structured": {"decision": "yes"}},
            },
        }
        stage_config = {
            "stage": {
                "name": "s2",
                "inputs": {
                    "decision": {"source": "s1.decision"},
                },
            },
        }
        result = resolver.resolve(stage_config, state)

        assert result["_context_meta"]["mode"] == "source-resolved"
        assert result["decision"] == "yes"

    def test_no_fallback_uses_passthrough(self):
        """Without fallback, SourceResolver falls back to PassthroughResolver."""
        resolver = SourceResolver()

        state = {
            StateKeys.WORKFLOW_INPUTS: {"topic": "AI"},
            StateKeys.STAGE_OUTPUTS: {},
        }
        result = resolver.resolve({"stage": {"name": "s1"}}, state)

        assert result["_context_meta"]["mode"] == "passthrough"
        assert result["topic"] == "AI"


# ---------------------------------------------------------------------------
# NodeBuilder.wire_dag_context tests
# ---------------------------------------------------------------------------

class TestNodeBuilderWireDag:
    """Tests for NodeBuilder.wire_dag_context()."""

    def test_wire_dag_sets_dag_on_predecessor_resolver(self):
        """wire_dag_context passes DAG to PredecessorResolver in executors."""
        from unittest.mock import patch

        predecessor = PredecessorResolver()
        source_resolver = SourceResolver(fallback=predecessor)

        executor = MagicMock()
        executor.context_provider = source_resolver

        from temper_ai.workflow.node_builder import NodeBuilder
        builder = NodeBuilder(
            config_loader=MagicMock(),
            tool_registry=MagicMock(),
            executors={"sequential": executor},
        )

        dag = MagicMock()
        with patch.object(predecessor, "set_dag", wraps=predecessor.set_dag) as spy:
            builder.wire_dag_context(dag)
            spy.assert_called_once_with(dag)

    def test_wire_dag_no_predecessor_resolver_no_error(self):
        """wire_dag_context is safe when no PredecessorResolver exists."""
        executor = MagicMock()
        executor.context_provider = SourceResolver()

        from temper_ai.workflow.node_builder import NodeBuilder
        builder = NodeBuilder(
            config_loader=MagicMock(),
            tool_registry=MagicMock(),
            executors={"sequential": executor},
        )

        dag = MagicMock()
        builder.wire_dag_context(dag)  # Should not raise

        # SourceResolver without fallback should not gain a DAG reference
        assert not hasattr(executor.context_provider, "_dag")

    def test_wire_dag_no_context_provider_no_error(self):
        """wire_dag_context is safe when executor has no context_provider."""
        executor = MagicMock(spec=[])  # No context_provider attribute

        from temper_ai.workflow.node_builder import NodeBuilder
        builder = NodeBuilder(
            config_loader=MagicMock(),
            tool_registry=MagicMock(),
            executors={"sequential": executor},
        )

        dag = MagicMock()
        builder.wire_dag_context(dag)  # Should not raise

        # Executor without context_provider attribute is unchanged
        assert not hasattr(executor, "context_provider")


# ---------------------------------------------------------------------------
# DynamicExecutionEngine predecessor injection tests
# ---------------------------------------------------------------------------

class TestDynamicEnginePredecessorInjection:
    """Tests for DynamicExecutionEngine predecessor injection setup."""

    @patch("temper_ai.workflow.engines.dynamic_engine.create_safety_stack")
    def test_predecessor_injection_flag_false_by_default(self, mock_safety):
        """Engine starts with predecessor injection disabled."""
        mock_safety.return_value = MagicMock()
        from temper_ai.workflow.engines.dynamic_engine import DynamicExecutionEngine
        engine = DynamicExecutionEngine(tool_executor=MagicMock())
        assert engine._predecessor_injection is False

    @patch("temper_ai.workflow.engines.dynamic_engine.create_safety_stack")
    def test_setup_predecessor_injection(self, mock_safety):
        """_setup_predecessor_injection creates PredecessorResolver fallback."""
        mock_safety.return_value = MagicMock()
        from temper_ai.workflow.engines.dynamic_engine import DynamicExecutionEngine
        engine = DynamicExecutionEngine(tool_executor=MagicMock())
        engine._setup_predecessor_injection()

        assert engine._predecessor_injection is True
        assert isinstance(engine.context_provider, SourceResolver)
        assert isinstance(engine.context_provider._predecessor, PredecessorResolver)

    @patch("temper_ai.workflow.engines.dynamic_engine.create_safety_stack")
    def test_predecessor_injection_injected_into_executors(self, mock_safety):
        """_setup_predecessor_injection re-injects context_provider into executors."""
        mock_safety.return_value = MagicMock()
        from temper_ai.workflow.engines.dynamic_engine import DynamicExecutionEngine
        engine = DynamicExecutionEngine(tool_executor=MagicMock())

        original_provider = engine.context_provider
        engine._setup_predecessor_injection()

        # Context provider should be new instance
        assert engine.context_provider is not original_provider

        # All executors should have the new context_provider
        for executor in engine.executors.values():
            assert executor.context_provider is engine.context_provider


# ---------------------------------------------------------------------------
# Schema field test
# ---------------------------------------------------------------------------

class TestWorkflowConfigPredecessorInjection:
    """Test predecessor_injection field in WorkflowConfigInner."""

    def test_default_false(self):
        """predecessor_injection defaults to False."""
        from temper_ai.workflow._schemas import WorkflowConfigInner
        config = WorkflowConfigInner(
            name="test",
            description="test",
            stages=[{
                "name": "s1",
                "stage_ref": "research",
            }],
            error_handling={
                "on_stage_failure": "halt",
                "escalation_policy": "test.policy",
            },
        )
        assert config.predecessor_injection is False

    def test_can_enable(self):
        """predecessor_injection can be set to True."""
        from temper_ai.workflow._schemas import WorkflowConfigInner
        config = WorkflowConfigInner(
            name="test",
            description="test",
            predecessor_injection=True,
            stages=[{
                "name": "s1",
                "stage_ref": "research",
            }],
            error_handling={
                "on_stage_failure": "halt",
                "escalation_policy": "test.policy",
            },
        )
        assert config.predecessor_injection is True
