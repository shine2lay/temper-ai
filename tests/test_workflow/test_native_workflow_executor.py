"""Tests for WorkflowExecutor (native engine workflow executor).

Tests DAG walking, condition evaluation, loop handling, parallel stage
execution, and negotiation protocol.
"""
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from src.workflow.condition_evaluator import ConditionEvaluator
from src.workflow.engines.workflow_executor import (
    DEFAULT_MAX_DYNAMIC_HOPS,
    WorkflowExecutor,
    _build_ref_lookup,
    _extract_next_stage_signal,
    _group_by_depth,
    _is_conditional,
    _parse_next_stage_from_text,
    _ref_attr,
    _try_parse_json,
)
from src.workflow.state_manager import StateManager


def _make_mock_node_builder(stage_results: Dict[str, Dict[str, Any]]):
    """Create a mock NodeBuilder that returns canned stage results."""
    builder = MagicMock()

    def extract_name(ref):
        if isinstance(ref, str):
            return ref
        if isinstance(ref, dict):
            return ref.get("name", str(ref))
        return getattr(ref, "name", str(ref))

    builder.extract_stage_name.side_effect = extract_name
    builder.extract_agent_name.side_effect = lambda x: x if isinstance(x, str) else x.get("name")

    def create_node(stage_name, workflow_config):
        def node_fn(state):
            return stage_results.get(stage_name, {
                "stage_outputs": {stage_name: {"stage_status": "completed"}},
                "current_stage": stage_name,
            })
        return node_fn

    builder.create_stage_node.side_effect = create_node
    return builder


class TestRefAttr:
    """Test _ref_attr helper."""

    def test_dict_ref(self):
        assert _ref_attr({"name": "A", "max_loops": 3}, "max_loops") == 3

    def test_dict_ref_default(self):
        assert _ref_attr({"name": "A"}, "max_loops", 2) == 2

    def test_object_ref(self):
        obj = MagicMock()
        obj.name = "B"
        assert _ref_attr(obj, "name") == "B"


class TestIsConditional:
    """Test _is_conditional helper."""

    def test_dict_skip_if(self):
        assert _is_conditional({"name": "A", "skip_if": "{{ True }}"}) is True

    def test_dict_condition(self):
        assert _is_conditional({"name": "A", "condition": "{{ True }}"}) is True

    def test_dict_not_conditional(self):
        assert _is_conditional({"name": "A"}) is False

    def test_string_ref(self):
        assert _is_conditional("A") is False


class TestBuildRefLookup:
    """Test _build_ref_lookup helper."""

    def test_builds_lookup(self):
        refs = [
            "simple_stage",
            {"name": "stage_a", "condition": "{{ True }}"},
            {"name": "stage_b"},
        ]
        lookup = _build_ref_lookup(refs)
        assert "stage_a" in lookup
        assert "stage_b" in lookup
        assert "simple_stage" not in lookup  # strings skipped


class TestGroupByDepth:
    """Test _group_by_depth helper."""

    def test_single_depth(self):
        dag = MagicMock()
        dag.topo_order = ["A", "B", "C"]
        depths = {"A": 0, "B": 0, "C": 0}
        groups = _group_by_depth(dag, depths)
        assert groups == {0: ["A", "B", "C"]}

    def test_multiple_depths(self):
        dag = MagicMock()
        dag.topo_order = ["A", "B", "C"]
        depths = {"A": 0, "B": 1, "C": 2}
        groups = _group_by_depth(dag, depths)
        assert groups == {0: ["A"], 1: ["B"], 2: ["C"]}


class TestWorkflowExecutor:
    """Test WorkflowExecutor execution."""

    def _make_executor(self, stage_results=None, negotiation_config=None):
        """Create WorkflowExecutor with mock dependencies."""
        results = stage_results or {}
        builder = _make_mock_node_builder(results)
        evaluator = ConditionEvaluator()
        manager = StateManager()
        return WorkflowExecutor(
            node_builder=builder,
            condition_evaluator=evaluator,
            state_manager=manager,
            negotiation_config=negotiation_config,
        )

    def test_single_stage_sequential(self):
        """Test executing a single stage."""
        executor = self._make_executor({
            "stage_a": {
                "stage_outputs": {"stage_a": {"stage_status": "completed", "output": "hello"}},
                "current_stage": "stage_a",
            },
        })

        state = {"stage_outputs": {}, "current_stage": ""}
        result = executor.run(["stage_a"], {}, state)

        assert "stage_a" in result["stage_outputs"]
        assert result["stage_outputs"]["stage_a"]["stage_status"] == "completed"

    def test_multiple_stages_sequential(self):
        """Test executing multiple stages in sequence."""
        executor = self._make_executor({
            "stage_a": {
                "stage_outputs": {"stage_a": {"stage_status": "completed"}},
                "current_stage": "stage_a",
            },
            "stage_b": {
                "stage_outputs": {"stage_b": {"stage_status": "completed"}},
                "current_stage": "stage_b",
            },
        })

        state = {"stage_outputs": {}, "current_stage": ""}
        result = executor.run(["stage_a", "stage_b"], {}, state)

        assert "stage_a" in result["stage_outputs"]
        assert "stage_b" in result["stage_outputs"]
        assert result["current_stage"] == "stage_b"

    def test_conditional_skip_if(self):
        """Test stage with skip_if condition is skipped when true."""
        executor = self._make_executor({
            "stage_a": {
                "stage_outputs": {"stage_a": {"stage_status": "completed"}},
                "current_stage": "stage_a",
            },
            "stage_b": {
                "stage_outputs": {"stage_b": {"stage_status": "completed"}},
                "current_stage": "stage_b",
            },
        })

        stage_refs = [
            "stage_a",
            {"name": "stage_b", "skip_if": "{{ True }}"},
        ]
        state = {"stage_outputs": {}, "current_stage": ""}
        result = executor.run(stage_refs, {}, state)

        assert "stage_a" in result["stage_outputs"]
        assert "stage_b" not in result["stage_outputs"]

    def test_conditional_condition_met(self):
        """Test stage with condition executes when condition is true."""
        executor = self._make_executor({
            "stage_a": {
                "stage_outputs": {"stage_a": {"stage_status": "completed"}},
                "current_stage": "stage_a",
            },
            "stage_b": {
                "stage_outputs": {"stage_b": {"stage_status": "completed"}},
                "current_stage": "stage_b",
            },
        })

        stage_refs = [
            "stage_a",
            {"name": "stage_b", "condition": "{{ True }}"},
        ]
        state = {"stage_outputs": {}, "current_stage": ""}
        result = executor.run(stage_refs, {}, state)

        assert "stage_a" in result["stage_outputs"]
        assert "stage_b" in result["stage_outputs"]

    def test_conditional_condition_not_met(self):
        """Test stage with condition is skipped when false."""
        executor = self._make_executor({
            "stage_a": {
                "stage_outputs": {"stage_a": {"stage_status": "completed"}},
                "current_stage": "stage_a",
            },
            "stage_b": {
                "stage_outputs": {"stage_b": {"stage_status": "completed"}},
                "current_stage": "stage_b",
            },
        })

        stage_refs = [
            "stage_a",
            {"name": "stage_b", "condition": "{{ False }}"},
        ]
        state = {"stage_outputs": {}, "current_stage": ""}
        result = executor.run(stage_refs, {}, state)

        assert "stage_a" in result["stage_outputs"]
        assert "stage_b" not in result["stage_outputs"]

    def test_parallel_stages_at_same_depth(self):
        """Test stages at the same depth execute (potentially parallel)."""
        executor = self._make_executor({
            "root": {
                "stage_outputs": {"root": {"stage_status": "completed"}},
                "current_stage": "root",
            },
            "branch_a": {
                "stage_outputs": {"branch_a": {"stage_status": "completed"}},
                "current_stage": "branch_a",
            },
            "branch_b": {
                "stage_outputs": {"branch_b": {"stage_status": "completed"}},
                "current_stage": "branch_b",
            },
        })

        stage_refs = [
            "root",
            {"name": "branch_a", "depends_on": ["root"]},
            {"name": "branch_b", "depends_on": ["root"]},
        ]
        state = {"stage_outputs": {}, "current_stage": ""}
        result = executor.run(stage_refs, {}, state)

        assert "root" in result["stage_outputs"]
        assert "branch_a" in result["stage_outputs"]
        assert "branch_b" in result["stage_outputs"]

    def test_loop_executes_max_times(self):
        """Test loop-back stage respects max_loops."""
        call_count = {"count": 0}

        def make_node_builder():
            builder = MagicMock()
            builder.extract_stage_name.side_effect = lambda ref: (
                ref if isinstance(ref, str) else ref.get("name", str(ref))
            )

            def create_node(stage_name, workflow_config):
                def node_fn(state):
                    call_count["count"] += 1
                    return {
                        "stage_outputs": {
                            stage_name: {
                                "stage_status": "failed",
                                "output": f"attempt_{call_count['count']}",
                            }
                        },
                        "current_stage": stage_name,
                    }
                return node_fn

            builder.create_stage_node.side_effect = create_node
            return builder

        builder = make_node_builder()
        evaluator = ConditionEvaluator()
        manager = StateManager()
        executor = WorkflowExecutor(builder, evaluator, manager)

        stage_refs = [
            {
                "name": "loopy",
                "loops_back_to": "loopy",
                "max_loops": 2,
                "loop_condition": "{{ stage_outputs.get('loopy', {}).get('stage_status') == 'failed' }}",
            },
        ]
        state = {"stage_outputs": {}, "current_stage": ""}
        result = executor.run(stage_refs, {}, state)

        # Should execute 1 initial + up to 2 loops = 3 total
        assert call_count["count"] >= 2
        assert "loopy" in result["stage_outputs"]

    def test_merge_stage_result(self):
        """Test _merge_stage_result properly merges outputs."""
        state = {
            "stage_outputs": {"existing": {"out": "data"}},
            "current_stage": "existing",
        }
        result = {
            "stage_outputs": {"new_stage": {"out": "new_data"}},
            "current_stage": "new_stage",
        }

        from src.workflow.engines.workflow_executor import _merge_stage_result
        merged = _merge_stage_result(state, result)
        assert "existing" in merged["stage_outputs"]
        assert "new_stage" in merged["stage_outputs"]
        assert merged["current_stage"] == "new_stage"

    def test_skip_to_end_halts_workflow(self):
        """Test skip_to=end stops all remaining stages."""
        executor = self._make_executor({
            "triage": {
                "stage_outputs": {"triage": {
                    "stage_status": "completed",
                    "decision": "DECISION: REJECT",
                }},
                "current_stage": "triage",
            },
            "design": {
                "stage_outputs": {"design": {"stage_status": "completed"}},
                "current_stage": "design",
            },
            "code": {
                "stage_outputs": {"code": {"stage_status": "completed"}},
                "current_stage": "code",
            },
        })

        stage_refs = [
            "triage",
            {
                "name": "design",
                "depends_on": ["triage"],
                "conditional": True,
                "condition": "{{ 'APPROVE' in (stage_outputs.triage.decision | default('')) }}",
                "skip_to": "end",
            },
            {"name": "code", "depends_on": ["design"]},
        ]
        state = {"stage_outputs": {}, "current_stage": ""}
        result = executor.run(stage_refs, {}, state)

        assert "triage" in result["stage_outputs"]
        assert "design" not in result["stage_outputs"]
        assert "code" not in result["stage_outputs"]
        assert result.get("_skip_to_end") == "design"

    def test_skip_to_end_not_set_when_condition_met(self):
        """Test skip_to=end does NOT trigger when condition passes."""
        executor = self._make_executor({
            "triage": {
                "stage_outputs": {"triage": {
                    "stage_status": "completed",
                    "decision": "DECISION: APPROVE",
                }},
                "current_stage": "triage",
            },
            "design": {
                "stage_outputs": {"design": {"stage_status": "completed"}},
                "current_stage": "design",
            },
            "code": {
                "stage_outputs": {"code": {"stage_status": "completed"}},
                "current_stage": "code",
            },
        })

        stage_refs = [
            "triage",
            {
                "name": "design",
                "depends_on": ["triage"],
                "conditional": True,
                "condition": "{{ 'APPROVE' in (stage_outputs.triage.decision | default('')) }}",
                "skip_to": "end",
            },
            {"name": "code", "depends_on": ["design"]},
        ]
        state = {"stage_outputs": {}, "current_stage": ""}
        result = executor.run(stage_refs, {}, state)

        assert "triage" in result["stage_outputs"]
        assert "design" in result["stage_outputs"]
        assert "code" in result["stage_outputs"]
        assert "_skip_to_end" not in result

    def test_negotiation_disabled_raises(self):
        """Test that without negotiation, ContextResolutionError propagates."""
        from src.workflow.context_provider import ContextResolutionError

        builder = MagicMock()
        builder.extract_stage_name.side_effect = lambda ref: (
            ref if isinstance(ref, str) else ref.get("name", str(ref))
        )

        def create_node(stage_name, workflow_config):
            def node_fn(state):
                raise ContextResolutionError("test_stage", "input_field", "producer.field")
            return node_fn

        builder.create_stage_node.side_effect = create_node

        evaluator = ConditionEvaluator()
        manager = StateManager()
        executor = WorkflowExecutor(builder, evaluator, manager)

        state = {"stage_outputs": {}, "current_stage": ""}
        with pytest.raises(ContextResolutionError):
            executor.run(["test_stage"], {}, state)

    def test_negotiation_enabled_reruns_producer(self):
        """Test that with negotiation enabled, producer is re-run on ContextResolutionError."""
        from src.workflow.context_provider import ContextResolutionError

        call_log = []

        builder = MagicMock()
        builder.extract_stage_name.side_effect = lambda ref: (
            ref if isinstance(ref, str) else ref.get("name", str(ref))
        )

        def create_node(stage_name, workflow_config):
            def node_fn(state):
                call_log.append(stage_name)
                if stage_name == "consumer" and len([c for c in call_log if c == "consumer"]) == 1:
                    # First call to consumer raises
                    raise ContextResolutionError("consumer", "data", "producer.output")
                return {
                    "stage_outputs": {stage_name: {"stage_status": "completed", "output": "ok"}},
                    "current_stage": stage_name,
                }
            return node_fn

        builder.create_stage_node.side_effect = create_node

        evaluator = ConditionEvaluator()
        manager = StateManager()
        executor = WorkflowExecutor(
            builder, evaluator, manager,
            negotiation_config={"enabled": True, "max_stage_rounds": 2},
        )

        state = {"stage_outputs": {}, "current_stage": ""}
        result = executor.run(
            [
                "producer",
                {"name": "consumer", "depends_on": ["producer"]},
            ],
            {},
            state,
        )

        # Producer should have been called twice (initial + negotiation re-run)
        assert call_log.count("producer") == 2
        # Consumer should have been called twice (fail + retry)
        assert call_log.count("consumer") == 2
        assert "consumer" in result["stage_outputs"]


class TestExtractNextStageSignal:
    """Test _extract_next_stage_signal static method."""

    def test_top_level_signal(self):
        """Test extraction from top-level _next_stage dict."""
        state = {"stage_outputs": {"stage_a": {
            "stage_status": "completed",
            "_next_stage": {"name": "stage_b", "inputs": {"key": "val"}},
        }}}
        result = _extract_next_stage_signal("stage_a", state)
        assert result == {"name": "stage_b", "inputs": {"key": "val"}}

    def test_structured_signal(self):
        """Test extraction from structured compartment."""
        state = {"stage_outputs": {"stage_a": {
            "stage_status": "completed",
            "structured": {
                "_next_stage": {"name": "stage_c", "inputs": {"x": 1}},
            },
        }}}
        result = _extract_next_stage_signal("stage_a", state)
        assert result == {"name": "stage_c", "inputs": {"x": 1}}

    def test_no_signal(self):
        """Test returns None when no _next_stage present."""
        state = {"stage_outputs": {"stage_a": {
            "stage_status": "completed",
            "output": "hello",
        }}}
        assert _extract_next_stage_signal("stage_a", state) is None

    def test_missing_name(self):
        """Test returns None when _next_stage has no name."""
        state = {"stage_outputs": {"stage_a": {
            "_next_stage": {"inputs": {"key": "val"}},
        }}}
        assert _extract_next_stage_signal("stage_a", state) is None

    def test_inputs_default_empty(self):
        """Test inputs defaults to empty dict when not provided."""
        state = {"stage_outputs": {"stage_a": {
            "_next_stage": {"name": "stage_b"},
        }}}
        result = _extract_next_stage_signal("stage_a", state)
        assert result == {"name": "stage_b", "inputs": {}}


class TestDynamicEdgeRouting:
    """Test dynamic edge routing in WorkflowExecutor."""

    def _make_executor(self, stage_results=None):
        """Create WorkflowExecutor with mock dependencies."""
        results = stage_results or {}
        builder = _make_mock_node_builder(results)
        evaluator = ConditionEvaluator()
        manager = StateManager()
        return WorkflowExecutor(
            node_builder=builder,
            condition_evaluator=evaluator,
            state_manager=manager,
        )

    def test_dynamic_edge_runs_target_stage(self):
        """Test that _next_stage signal causes target stage to run."""
        call_log = []

        builder = MagicMock()
        builder.extract_stage_name.side_effect = lambda ref: (
            ref if isinstance(ref, str) else ref.get("name", str(ref))
        )

        def create_node(stage_name, workflow_config):
            def node_fn(state):
                call_log.append(stage_name)
                if stage_name == "analyze":
                    return {
                        "stage_outputs": {"analyze": {
                            "stage_status": "completed",
                            "_next_stage": {"name": "fix"},
                        }},
                        "current_stage": "analyze",
                    }
                return {
                    "stage_outputs": {stage_name: {"stage_status": "completed"}},
                    "current_stage": stage_name,
                }
            return node_fn

        builder.create_stage_node.side_effect = create_node
        executor = WorkflowExecutor(builder, ConditionEvaluator(), StateManager())

        stage_refs = ["analyze", {"name": "fix", "depends_on": ["analyze"]}]
        state = {"stage_outputs": {}, "current_stage": ""}
        result = executor.run(stage_refs, {}, state)

        assert "analyze" in call_log
        assert "fix" in call_log
        # fix called twice: once via dynamic edge, once via normal DAG walk
        assert call_log.count("fix") == 2
        assert "fix" in result["stage_outputs"]

    def test_no_signal_continues_normally(self):
        """Test that without _next_stage, DAG proceeds normally."""
        executor = self._make_executor({
            "stage_a": {
                "stage_outputs": {"stage_a": {"stage_status": "completed"}},
                "current_stage": "stage_a",
            },
            "stage_b": {
                "stage_outputs": {"stage_b": {"stage_status": "completed"}},
                "current_stage": "stage_b",
            },
        })

        state = {"stage_outputs": {}, "current_stage": ""}
        result = executor.run(["stage_a", "stage_b"], {}, state)

        assert "stage_a" in result["stage_outputs"]
        assert "stage_b" in result["stage_outputs"]

    def test_chain_two_hops(self):
        """Test chaining: A → B → C via dynamic edges."""
        call_log = []

        builder = MagicMock()
        builder.extract_stage_name.side_effect = lambda ref: (
            ref if isinstance(ref, str) else ref.get("name", str(ref))
        )

        def create_node(stage_name, workflow_config):
            def node_fn(state):
                call_log.append(stage_name)
                if stage_name == "a":
                    return {
                        "stage_outputs": {"a": {
                            "stage_status": "completed",
                            "_next_stage": {"name": "b"},
                        }},
                        "current_stage": "a",
                    }
                if stage_name == "b":
                    return {
                        "stage_outputs": {"b": {
                            "stage_status": "completed",
                            "_next_stage": {"name": "c"},
                        }},
                        "current_stage": "b",
                    }
                return {
                    "stage_outputs": {stage_name: {"stage_status": "completed"}},
                    "current_stage": stage_name,
                }
            return node_fn

        builder.create_stage_node.side_effect = create_node
        executor = WorkflowExecutor(builder, ConditionEvaluator(), StateManager())

        state = {"stage_outputs": {}, "current_stage": ""}
        result = executor.run(["a", "b", "c"], {}, state)

        # a triggers b, b triggers c (via dynamic edges)
        assert "a" in call_log
        assert "b" in call_log
        assert "c" in call_log
        assert "c" in result["stage_outputs"]

    def test_respects_max_hops(self):
        """Test that dynamic edge chain stops at DEFAULT_MAX_DYNAMIC_HOPS."""
        call_log = []

        builder = MagicMock()
        builder.extract_stage_name.side_effect = lambda ref: (
            ref if isinstance(ref, str) else ref.get("name", str(ref))
        )

        def create_node(stage_name, workflow_config):
            def node_fn(state):
                call_log.append(stage_name)
                # Always point to "loop" creating an infinite chain
                return {
                    "stage_outputs": {stage_name: {
                        "stage_status": "completed",
                        "_next_stage": {"name": "loop"},
                    }},
                    "current_stage": stage_name,
                }
            return node_fn

        builder.create_stage_node.side_effect = create_node
        executor = WorkflowExecutor(builder, ConditionEvaluator(), StateManager())

        state = {"stage_outputs": {}, "current_stage": ""}
        result = executor.run(["loop"], {}, state)

        # Initial call + DEFAULT_MAX_DYNAMIC_HOPS dynamic calls
        assert call_log.count("loop") == 1 + DEFAULT_MAX_DYNAMIC_HOPS

    def test_unknown_target_ignored(self):
        """Test that _next_stage pointing to unknown stage is ignored."""
        call_log = []

        builder = MagicMock()
        builder.extract_stage_name.side_effect = lambda ref: (
            ref if isinstance(ref, str) else ref.get("name", str(ref))
        )

        def create_node(stage_name, workflow_config):
            def node_fn(state):
                call_log.append(stage_name)
                return {
                    "stage_outputs": {stage_name: {
                        "stage_status": "completed",
                        "_next_stage": {"name": "nonexistent"},
                    }},
                    "current_stage": stage_name,
                }
            return node_fn

        builder.create_stage_node.side_effect = create_node
        executor = WorkflowExecutor(builder, ConditionEvaluator(), StateManager())

        state = {"stage_outputs": {}, "current_stage": ""}
        result = executor.run(["stage_a"], {}, state)

        assert call_log == ["stage_a"]
        assert "stage_a" in result["stage_outputs"]

    def test_from_structured_compartment(self):
        """Test dynamic edge from structured compartment."""
        call_log = []

        builder = MagicMock()
        builder.extract_stage_name.side_effect = lambda ref: (
            ref if isinstance(ref, str) else ref.get("name", str(ref))
        )

        def create_node(stage_name, workflow_config):
            def node_fn(state):
                call_log.append(stage_name)
                if stage_name == "analyze":
                    return {
                        "stage_outputs": {"analyze": {
                            "stage_status": "completed",
                            "structured": {
                                "_next_stage": {"name": "fix", "inputs": {"issue": "bug"}},
                            },
                        }},
                        "current_stage": "analyze",
                    }
                return {
                    "stage_outputs": {stage_name: {"stage_status": "completed"}},
                    "current_stage": stage_name,
                }
            return node_fn

        builder.create_stage_node.side_effect = create_node
        executor = WorkflowExecutor(builder, ConditionEvaluator(), StateManager())

        state = {"stage_outputs": {}, "current_stage": ""}
        result = executor.run(["analyze", "fix"], {}, state)

        assert "analyze" in call_log
        assert "fix" in call_log

    def test_inputs_delivered_to_target(self):
        """Test that _next_stage inputs are available as _dynamic_inputs."""
        captured_inputs = {}

        builder = MagicMock()
        builder.extract_stage_name.side_effect = lambda ref: (
            ref if isinstance(ref, str) else ref.get("name", str(ref))
        )

        def create_node(stage_name, workflow_config):
            def node_fn(state):
                if stage_name == "analyze":
                    return {
                        "stage_outputs": {"analyze": {
                            "stage_status": "completed",
                            "_next_stage": {
                                "name": "fix",
                                "inputs": {"issue": "null pointer", "file": "main.py"},
                            },
                        }},
                        "current_stage": "analyze",
                    }
                if stage_name == "fix":
                    # Capture dynamic inputs visible in state
                    captured_inputs.update(state.get("_dynamic_inputs", {}))
                return {
                    "stage_outputs": {stage_name: {"stage_status": "completed"}},
                    "current_stage": stage_name,
                }
            return node_fn

        builder.create_stage_node.side_effect = create_node
        executor = WorkflowExecutor(builder, ConditionEvaluator(), StateManager())

        state = {"stage_outputs": {}, "current_stage": ""}
        executor.run(["analyze", "fix"], {}, state)

        assert captured_inputs == {"issue": "null pointer", "file": "main.py"}

    def test_after_parallel_stages(self):
        """Test dynamic edges are processed after parallel stages complete."""
        call_log = []

        builder = MagicMock()
        builder.extract_stage_name.side_effect = lambda ref: (
            ref if isinstance(ref, str) else ref.get("name", str(ref))
        )

        def create_node(stage_name, workflow_config):
            def node_fn(state):
                call_log.append(stage_name)
                if stage_name == "branch_a":
                    return {
                        "stage_outputs": {"branch_a": {
                            "stage_status": "completed",
                            "_next_stage": {"name": "merge"},
                        }},
                        "current_stage": "branch_a",
                    }
                return {
                    "stage_outputs": {stage_name: {"stage_status": "completed"}},
                    "current_stage": stage_name,
                }
            return node_fn

        builder.create_stage_node.side_effect = create_node
        executor = WorkflowExecutor(builder, ConditionEvaluator(), StateManager())

        stage_refs = [
            "root",
            {"name": "branch_a", "depends_on": ["root"]},
            {"name": "branch_b", "depends_on": ["root"]},
            {"name": "merge", "depends_on": ["branch_a", "branch_b"]},
        ]
        state = {"stage_outputs": {}, "current_stage": ""}
        result = executor.run(stage_refs, {}, state)

        assert "merge" in call_log
        assert "merge" in result["stage_outputs"]

    def test_dynamic_inputs_cleaned_up(self):
        """Test that _dynamic_inputs is removed from state after target runs."""
        builder = MagicMock()
        builder.extract_stage_name.side_effect = lambda ref: (
            ref if isinstance(ref, str) else ref.get("name", str(ref))
        )

        def create_node(stage_name, workflow_config):
            def node_fn(state):
                if stage_name == "analyze":
                    return {
                        "stage_outputs": {"analyze": {
                            "stage_status": "completed",
                            "_next_stage": {
                                "name": "fix",
                                "inputs": {"data": "test"},
                            },
                        }},
                        "current_stage": "analyze",
                    }
                return {
                    "stage_outputs": {stage_name: {"stage_status": "completed"}},
                    "current_stage": stage_name,
                }
            return node_fn

        builder.create_stage_node.side_effect = create_node
        executor = WorkflowExecutor(builder, ConditionEvaluator(), StateManager())

        state = {"stage_outputs": {}, "current_stage": ""}
        result = executor.run(["analyze", "fix"], {}, state)

        assert "_dynamic_inputs" not in result


class TestTryParseJson:
    """Test _try_parse_json helper."""

    def test_valid_dict(self):
        assert _try_parse_json('{"a": 1}') == {"a": 1}

    def test_valid_nested(self):
        result = _try_parse_json('{"x": {"y": [1, 2]}}')
        assert result == {"x": {"y": [1, 2]}}

    def test_not_dict(self):
        assert _try_parse_json("[1, 2, 3]") is None

    def test_invalid_json(self):
        assert _try_parse_json("not json") is None

    def test_empty_string(self):
        assert _try_parse_json("") is None


class TestParseNextStageFromText:
    """Test _parse_next_stage_from_text helper."""

    def test_full_json_with_next_stage(self):
        text = '{"evaluation": "FAIL", "_next_stage": {"name": "analyze", "inputs": {"feedback": "too brief"}}}'
        result = _parse_next_stage_from_text(text)
        assert result == {"name": "analyze", "inputs": {"feedback": "too brief"}}

    def test_json_without_next_stage(self):
        text = '{"evaluation": "PASS", "reasoning": "looks good"}'
        assert _parse_next_stage_from_text(text) is None

    def test_embedded_json_in_text(self):
        text = 'Here is my evaluation:\n{"evaluation": "FAIL", "_next_stage": {"name": "retry", "inputs": {}}}\nDone.'
        result = _parse_next_stage_from_text(text)
        assert result == {"name": "retry", "inputs": {}}

    def test_plain_text_no_json(self):
        assert _parse_next_stage_from_text("just plain text") is None

    def test_next_stage_without_name(self):
        text = '{"_next_stage": {"inputs": {"x": 1}}}'
        assert _parse_next_stage_from_text(text) is None

    def test_whitespace_around_json(self):
        text = '  \n  {"_next_stage": {"name": "fix"}}  \n  '
        result = _parse_next_stage_from_text(text)
        assert result == {"name": "fix", "inputs": {}}

    def test_next_stage_inputs_default_empty(self):
        text = '{"_next_stage": {"name": "stage_b"}}'
        result = _parse_next_stage_from_text(text)
        assert result == {"name": "stage_b", "inputs": {}}


class TestExtractNextStageSignalFromOutput:
    """Test _extract_next_stage_signal fallback to raw output text."""

    def test_signal_from_output_text(self):
        """Test extraction from raw output text when structured is empty."""
        state = {"stage_outputs": {"eval": {
            "stage_status": "completed",
            "structured": {},
            "output": '{"evaluation": "FAIL", "_next_stage": {"name": "analyze", "inputs": {"feedback": "needs detail"}}}',
        }}}
        result = _extract_next_stage_signal("eval", state)
        assert result == {"name": "analyze", "inputs": {"feedback": "needs detail"}}

    def test_top_level_takes_priority_over_output_text(self):
        """Test that top-level signal is preferred over output text."""
        state = {"stage_outputs": {"eval": {
            "_next_stage": {"name": "from_top"},
            "output": '{"_next_stage": {"name": "from_text"}}',
        }}}
        result = _extract_next_stage_signal("eval", state)
        assert result["name"] == "from_top"

    def test_structured_takes_priority_over_output_text(self):
        """Test that structured signal is preferred over output text."""
        state = {"stage_outputs": {"eval": {
            "structured": {"_next_stage": {"name": "from_structured"}},
            "output": '{"_next_stage": {"name": "from_text"}}',
        }}}
        result = _extract_next_stage_signal("eval", state)
        assert result["name"] == "from_structured"

    def test_output_text_with_surrounding_prose(self):
        """Test extraction from output with surrounding non-JSON text."""
        state = {"stage_outputs": {"eval": {
            "structured": {},
            "output": 'The analysis was weak.\n{"_next_stage": {"name": "redo", "inputs": {"reason": "vague"}}}\nEnd.',
        }}}
        result = _extract_next_stage_signal("eval", state)
        assert result == {"name": "redo", "inputs": {"reason": "vague"}}

    def test_output_text_no_signal(self):
        """Test no false positive from output text without _next_stage."""
        state = {"stage_outputs": {"eval": {
            "structured": {},
            "output": '{"evaluation": "PASS", "score": 95}',
        }}}
        assert _extract_next_stage_signal("eval", state) is None

    def test_output_text_not_json(self):
        """Test graceful handling of non-JSON output text."""
        state = {"stage_outputs": {"eval": {
            "structured": {},
            "output": "The analysis looks great. No issues found.",
        }}}
        assert _extract_next_stage_signal("eval", state) is None
