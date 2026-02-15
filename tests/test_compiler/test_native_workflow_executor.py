"""Tests for WorkflowExecutor (native engine workflow executor).

Tests DAG walking, condition evaluation, loop handling, parallel stage
execution, and negotiation protocol.
"""
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from src.compiler.condition_evaluator import ConditionEvaluator
from src.compiler.engines.workflow_executor import (
    WorkflowExecutor,
    _build_ref_lookup,
    _group_by_depth,
    _is_conditional,
    _parse_text_retry_signal,
    _ref_attr,
)
from src.compiler.state_manager import StateManager


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

        merged = WorkflowExecutor._merge_stage_result(state, result)
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
        from src.compiler.context_provider import ContextResolutionError

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
        from src.compiler.context_provider import ContextResolutionError

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

    def test_upstream_retry_reruns_target_then_current(self):
        """Test dynamic stage calling: stage B retries stage A with feedback."""
        call_log = []

        builder = MagicMock()
        builder.extract_stage_name.side_effect = lambda ref: (
            ref if isinstance(ref, str) else ref.get("name", str(ref))
        )

        def create_node(stage_name, workflow_config):
            def node_fn(state):
                call_log.append(stage_name)
                if stage_name == "triage":
                    # On retry, produce better output
                    feedback = state.get("_upstream_feedback")
                    output = "detailed specs" if feedback else "vague"
                    return {
                        "stage_outputs": {"triage": {
                            "stage_status": "completed",
                            "output": output,
                        }},
                        "current_stage": "triage",
                    }
                if stage_name == "design":
                    triage_out = state.get("stage_outputs", {}).get(
                        "triage", {},
                    ).get("output", "")
                    if triage_out == "vague":
                        # Signal: retry triage with feedback
                        return {
                            "stage_outputs": {"design": {
                                "stage_status": "completed",
                                "output": "needs more detail",
                                "_retry_upstream": {
                                    "target": "triage",
                                    "feedback": "need endpoint specs",
                                },
                            }},
                            "current_stage": "design",
                        }
                    return {
                        "stage_outputs": {"design": {
                            "stage_status": "completed",
                            "output": "design done",
                        }},
                        "current_stage": "design",
                    }
                return {
                    "stage_outputs": {stage_name: {
                        "stage_status": "completed",
                    }},
                    "current_stage": stage_name,
                }
            return node_fn

        builder.create_stage_node.side_effect = create_node

        evaluator = ConditionEvaluator()
        manager = StateManager()
        executor = WorkflowExecutor(builder, evaluator, manager)

        stage_refs = [
            "triage",
            {"name": "design", "depends_on": ["triage"]},
        ]
        state = {"stage_outputs": {}, "current_stage": ""}
        result = executor.run(stage_refs, {}, state)

        # triage: initial + retry = 2 calls
        assert call_log.count("triage") == 2
        # design: rejected first time + accepted second = 2 calls
        assert call_log.count("design") == 2
        # Final triage output should be the improved version
        assert result["stage_outputs"]["triage"]["output"] == "detailed specs"
        # Final design output should be accepted
        assert result["stage_outputs"]["design"]["output"] == "design done"

    def test_upstream_retry_respects_max_rounds(self):
        """Test that upstream retry stops after max rounds."""
        call_log = []

        builder = MagicMock()
        builder.extract_stage_name.side_effect = lambda ref: (
            ref if isinstance(ref, str) else ref.get("name", str(ref))
        )

        def create_node(stage_name, workflow_config):
            def node_fn(state):
                call_log.append(stage_name)
                if stage_name == "upstream":
                    return {
                        "stage_outputs": {"upstream": {
                            "stage_status": "completed",
                            "output": "still vague",
                        }},
                        "current_stage": "upstream",
                    }
                # Always reject
                return {
                    "stage_outputs": {"downstream": {
                        "stage_status": "completed",
                        "_retry_upstream": {
                            "target": "upstream",
                            "feedback": "not good enough",
                        },
                    }},
                    "current_stage": "downstream",
                }
            return node_fn

        builder.create_stage_node.side_effect = create_node

        executor = WorkflowExecutor(
            builder, ConditionEvaluator(), StateManager(),
        )

        stage_refs = [
            "upstream",
            {
                "name": "downstream",
                "depends_on": ["upstream"],
                "max_upstream_retries": 2,
            },
        ]
        state = {"stage_outputs": {}, "current_stage": ""}
        result = executor.run(stage_refs, {}, state)

        # upstream: initial + 2 retries = 3
        assert call_log.count("upstream") == 3
        # downstream: initial + 2 retries = 3 (max_upstream_retries=2)
        assert call_log.count("downstream") == 3
        assert "downstream" in result["stage_outputs"]

    def test_text_based_retry_signal(self):
        """Test that RETRY_UPSTREAM/RETRY_FEEDBACK text pattern triggers retry."""
        call_log = []

        builder = MagicMock()
        builder.extract_stage_name.side_effect = lambda ref: (
            ref if isinstance(ref, str) else ref.get("name", str(ref))
        )

        def create_node(stage_name, workflow_config):
            def node_fn(state):
                call_log.append(stage_name)
                if stage_name == "analyze":
                    feedback = state.get("_upstream_feedback")
                    output = "Detailed 5-point analysis" if feedback else "Brief summary"
                    return {
                        "stage_outputs": {"analyze": {
                            "stage_status": "completed",
                            "output": output,
                        }},
                        "current_stage": "analyze",
                    }
                if stage_name == "evaluate":
                    analysis = state.get("stage_outputs", {}).get(
                        "analyze", {},
                    ).get("output", "")
                    if "Brief" in analysis:
                        return {
                            "stage_outputs": {"evaluate": {
                                "stage_status": "completed",
                                "output": (
                                    "Analysis is too vague.\n"
                                    "RETRY_UPSTREAM: analyze\n"
                                    "RETRY_FEEDBACK: Need at least 5 technical points"
                                ),
                            }},
                            "current_stage": "evaluate",
                        }
                    return {
                        "stage_outputs": {"evaluate": {
                            "stage_status": "completed",
                            "output": "EVALUATION: PASS\nREASONING: Good detail",
                        }},
                        "current_stage": "evaluate",
                    }
                return {
                    "stage_outputs": {stage_name: {"stage_status": "completed"}},
                    "current_stage": stage_name,
                }
            return node_fn

        builder.create_stage_node.side_effect = create_node

        executor = WorkflowExecutor(
            builder, ConditionEvaluator(), StateManager(),
        )

        stage_refs = [
            "analyze",
            {"name": "evaluate", "depends_on": ["analyze"]},
        ]
        state = {"stage_outputs": {}, "current_stage": ""}
        result = executor.run(stage_refs, {}, state)

        # analyze: initial + 1 retry = 2
        assert call_log.count("analyze") == 2
        # evaluate: rejected once + accepted = 2
        assert call_log.count("evaluate") == 2
        assert "PASS" in result["stage_outputs"]["evaluate"]["output"]


class TestParseTextRetrySignal:
    """Test _parse_text_retry_signal helper."""

    def test_valid_signal(self):
        text = "Some preamble\nRETRY_UPSTREAM: analyze\nRETRY_FEEDBACK: Need more detail\nSome other text"
        result = _parse_text_retry_signal(text)
        assert result == {"target": "analyze", "feedback": "Need more detail"}

    def test_no_signal(self):
        assert _parse_text_retry_signal("EVALUATION: PASS") is None

    def test_partial_signal_no_feedback(self):
        assert _parse_text_retry_signal("RETRY_UPSTREAM: analyze") is None

    def test_multiline_feedback(self):
        text = "RETRY_UPSTREAM: triage\nRETRY_FEEDBACK: Missing endpoint specs and auth details"
        result = _parse_text_retry_signal(text)
        assert result["target"] == "triage"
        assert "endpoint specs" in result["feedback"]

    def test_signal_with_surrounding_text(self):
        text = (
            "The analysis is insufficient.\n"
            "RETRY_UPSTREAM: gather\n"
            "RETRY_FEEDBACK: Add concrete implementation steps\n"
            "EVALUATION: FAIL"
        )
        result = _parse_text_retry_signal(text)
        assert result == {"target": "gather", "feedback": "Add concrete implementation steps"}
