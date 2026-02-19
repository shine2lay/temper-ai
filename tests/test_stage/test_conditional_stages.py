"""Integration tests for conditional stages and loops in StageCompiler."""
from unittest.mock import Mock, patch

import pytest

from temper_ai.workflow.condition_evaluator import ConditionEvaluator
from temper_ai.stage.executors.state_keys import StateKeys
from temper_ai.workflow.node_builder import NodeBuilder
from temper_ai.workflow._schemas import WorkflowStageReference
from temper_ai.stage.stage_compiler import StageCompiler


class TestConditionalStageSkip:
    """Test that conditional stages are skipped when appropriate."""

    def test_conditional_stage_skipped_when_tests_pass(self):
        """Integration: fix stage skipped when test stage succeeds."""
        config_loader = Mock()
        tool_registry = Mock()
        executors = {"sequential": Mock(), "parallel": Mock(), "adaptive": Mock()}
        node_builder = NodeBuilder(config_loader, tool_registry, executors)
        evaluator = ConditionEvaluator()
        compiler = StageCompiler(node_builder, evaluator)

        execution_order = []

        def make_node(stage_name, _wf_config):
            def node(state):
                execution_order.append(stage_name)
                if not hasattr(state, "stage_outputs") or state.stage_outputs is None:
                    state.stage_outputs = {}
                state.stage_outputs[stage_name] = {
                    "stage_status": "success",
                    "output": f"output_{stage_name}",
                }
                return state
            return node

        # Build workflow config with conditional fix stage
        workflow_config = {
            "workflow": {
                "stages": [
                    {"name": "test", "stage_ref": "configs/stages/test.yaml"},
                    {
                        "name": "fix",
                        "stage_ref": "configs/stages/fix.yaml",
                        "conditional": True,
                    },
                ]
            }
        }

        with patch.object(node_builder, "create_stage_node", side_effect=make_node):
            graph = compiler.compile_stages(["test", "fix"], workflow_config)
            result = graph.invoke({
                "workflow_id": "wf-test-cond",
                "current_stage": "",
                "version": "1.0",
            })

        # fix should be skipped because test succeeded
        assert execution_order == ["test"]
        assert "test" in result[StateKeys.STAGE_OUTPUTS]
        assert result[StateKeys.STAGE_OUTPUTS]["test"]["stage_status"] == "success"

    def test_conditional_stage_executes_when_tests_fail(self):
        """Integration: fix stage runs when test stage fails."""
        config_loader = Mock()
        tool_registry = Mock()
        executors = {"sequential": Mock(), "parallel": Mock(), "adaptive": Mock()}
        node_builder = NodeBuilder(config_loader, tool_registry, executors)
        evaluator = ConditionEvaluator()
        compiler = StageCompiler(node_builder, evaluator)

        execution_order = []

        def make_node(stage_name, _wf_config):
            def node(state):
                execution_order.append(stage_name)
                if not hasattr(state, "stage_outputs") or state.stage_outputs is None:
                    state.stage_outputs = {}
                if stage_name == "test":
                    state.stage_outputs[stage_name] = {"stage_status": "failed"}
                else:
                    state.stage_outputs[stage_name] = {"stage_status": "success"}
                return state
            return node

        workflow_config = {
            "workflow": {
                "stages": [
                    {"name": "test", "stage_ref": "configs/stages/test.yaml"},
                    {
                        "name": "fix",
                        "stage_ref": "configs/stages/fix.yaml",
                        "conditional": True,
                    },
                ]
            }
        }

        with patch.object(node_builder, "create_stage_node", side_effect=make_node):
            graph = compiler.compile_stages(["test", "fix"], workflow_config)
            result = graph.invoke({
                "workflow_id": "wf-test-cond-fail",
                "current_stage": "",
                "version": "1.0",
            })

        # fix should execute because test failed
        assert execution_order == ["test", "fix"]
        assert result[StateKeys.STAGE_OUTPUTS]["fix"]["stage_status"] == "success"


class TestSkipIfStage:
    """Test skip_if conditional logic."""

    def test_skip_if_true_skips_stage(self):
        config_loader = Mock()
        tool_registry = Mock()
        executors = {"sequential": Mock(), "parallel": Mock(), "adaptive": Mock()}
        node_builder = NodeBuilder(config_loader, tool_registry, executors)
        evaluator = ConditionEvaluator()
        compiler = StageCompiler(node_builder, evaluator)

        execution_order = []

        def make_node(stage_name, _wf_config):
            def node(state):
                execution_order.append(stage_name)
                if not hasattr(state, "stage_outputs") or state.stage_outputs is None:
                    state.stage_outputs = {}
                state.stage_outputs[stage_name] = {"stage_status": "success"}
                return state
            return node

        workflow_config = {
            "workflow": {
                "stages": [
                    {"name": "setup", "stage_ref": "configs/stages/setup.yaml"},
                    {
                        "name": "optional",
                        "stage_ref": "configs/stages/optional.yaml",
                        "skip_if": "{{ stage_outputs.setup.stage_status == 'success' }}",
                    },
                    {"name": "final", "stage_ref": "configs/stages/final.yaml"},
                ]
            }
        }

        with patch.object(node_builder, "create_stage_node", side_effect=make_node):
            graph = compiler.compile_stages(
                ["setup", "optional", "final"], workflow_config
            )
            result = graph.invoke({
                "workflow_id": "wf-skip-if",
                "current_stage": "",
                "version": "1.0",
            })

        # optional skipped, final still runs
        assert execution_order == ["setup", "final"]


class TestLoopExecution:
    """Test loop-back execution patterns."""

    def test_loop_executes_correct_iterations(self):
        """Integration: fix→test loop runs until tests pass."""
        config_loader = Mock()
        tool_registry = Mock()
        executors = {"sequential": Mock(), "parallel": Mock(), "adaptive": Mock()}
        node_builder = NodeBuilder(config_loader, tool_registry, executors)
        evaluator = ConditionEvaluator()
        compiler = StageCompiler(node_builder, evaluator)

        call_counts = {"test": 0, "fix": 0}

        def make_node(stage_name, _wf_config):
            def node(state):
                call_counts[stage_name] = call_counts.get(stage_name, 0) + 1
                if not hasattr(state, "stage_outputs") or state.stage_outputs is None:
                    state.stage_outputs = {}
                if not hasattr(state, "stage_loop_counts") or state.stage_loop_counts is None:
                    state.stage_loop_counts = {}

                if stage_name == "test":
                    # Fail first 2 times, succeed on 3rd
                    if call_counts["test"] < 3:
                        state.stage_outputs[stage_name] = {"stage_status": "failed"}
                    else:
                        state.stage_outputs[stage_name] = {"stage_status": "success"}
                elif stage_name == "fix":
                    # Fix always reports degraded (needs more fixing)
                    state.stage_outputs[stage_name] = {"stage_status": "degraded"}
                return state
            return node

        workflow_config = {
            "workflow": {
                "stages": [
                    {"name": "test", "stage_ref": "configs/stages/test.yaml"},
                    {
                        "name": "fix",
                        "stage_ref": "configs/stages/fix.yaml",
                        "conditional": True,
                        "loops_back_to": "test",
                        "max_loops": 3,
                    },
                ]
            }
        }

        with patch.object(node_builder, "create_stage_node", side_effect=make_node):
            graph = compiler.compile_stages(["test", "fix"], workflow_config)
            result = graph.invoke({
                "workflow_id": "wf-loop",
                "current_stage": "",
                "version": "1.0",
            })

        # test runs 3x (initial + 2 loops), fix runs 2x (fails trigger loop)
        assert call_counts["test"] == 3
        assert call_counts["fix"] == 2

    def test_max_loops_prevents_infinite_loop(self):
        """Integration: max_loops caps iterations even if condition stays true."""
        config_loader = Mock()
        tool_registry = Mock()
        executors = {"sequential": Mock(), "parallel": Mock(), "adaptive": Mock()}
        node_builder = NodeBuilder(config_loader, tool_registry, executors)
        evaluator = ConditionEvaluator()
        compiler = StageCompiler(node_builder, evaluator)

        call_counts = {"test": 0, "fix": 0}

        def make_node(stage_name, _wf_config):
            def node(state):
                call_counts[stage_name] = call_counts.get(stage_name, 0) + 1
                if not hasattr(state, "stage_outputs") or state.stage_outputs is None:
                    state.stage_outputs = {}
                if not hasattr(state, "stage_loop_counts") or state.stage_loop_counts is None:
                    state.stage_loop_counts = {}
                # Always fail — tests never pass
                state.stage_outputs[stage_name] = {"stage_status": "failed"}
                return state
            return node

        workflow_config = {
            "workflow": {
                "stages": [
                    {"name": "test", "stage_ref": "configs/stages/test.yaml"},
                    {
                        "name": "fix",
                        "stage_ref": "configs/stages/fix.yaml",
                        "conditional": True,
                        "loops_back_to": "test",
                        "max_loops": 2,
                    },
                ]
            }
        }

        with patch.object(node_builder, "create_stage_node", side_effect=make_node):
            graph = compiler.compile_stages(["test", "fix"], workflow_config)
            result = graph.invoke({
                "workflow_id": "wf-max-loop",
                "current_stage": "",
                "version": "1.0",
            })

        # test: 1 initial + 2 loops = 3, fix: 1 initial + 2 loops = 3
        # But max_loops=2 caps at 2 loop-backs from fix
        assert call_counts["test"] == 3  # initial + 2 loop-backs
        assert call_counts["fix"] <= 3  # max 2 loops + initial


class TestSchemaValidation:
    """Test schema validation for conditional config."""

    def test_condition_and_skip_if_mutually_exclusive(self):
        with pytest.raises(ValueError, match="mutually exclusive"):
            WorkflowStageReference(
                name="bad",
                stage_ref="configs/stages/bad.yaml",
                condition="{{ true }}",
                skip_if="{{ false }}",
            )

    def test_loops_back_to_cannot_be_empty(self):
        with pytest.raises(ValueError, match="non-empty string"):
            WorkflowStageReference(
                name="bad",
                stage_ref="configs/stages/bad.yaml",
                loops_back_to="  ",
            )

    def test_valid_conditional_config(self):
        ref = WorkflowStageReference(
            name="fix",
            stage_ref="configs/stages/fix.yaml",
            conditional=True,
            loops_back_to="test",
            max_loops=3,
        )
        assert ref.conditional is True
        assert ref.loops_back_to == "test"
        assert ref.max_loops == 3

    def test_valid_skip_if_config(self):
        ref = WorkflowStageReference(
            name="optional",
            stage_ref="configs/stages/optional.yaml",
            skip_if="{{ skip }}",
        )
        assert ref.skip_if == "{{ skip }}"
        assert ref.condition is None


class TestPureSequentialUnchanged:
    """Verify pure sequential workflows still work unchanged."""

    def test_sequential_workflow_no_conditions(self):
        config_loader = Mock()
        tool_registry = Mock()
        executors = {"sequential": Mock(), "parallel": Mock(), "adaptive": Mock()}
        node_builder = NodeBuilder(config_loader, tool_registry, executors)
        evaluator = ConditionEvaluator()
        compiler = StageCompiler(node_builder, evaluator)

        execution_order = []

        def make_node(stage_name, _wf_config):
            def node(state):
                execution_order.append(stage_name)
                if not hasattr(state, "stage_outputs") or state.stage_outputs is None:
                    state.stage_outputs = {}
                state.stage_outputs[stage_name] = {"stage_status": "success"}
                return state
            return node

        # No conditions at all — pure sequential
        workflow_config = {
            "workflow": {
                "stages": [
                    {"name": "a", "stage_ref": "configs/stages/a.yaml"},
                    {"name": "b", "stage_ref": "configs/stages/b.yaml"},
                    {"name": "c", "stage_ref": "configs/stages/c.yaml"},
                ]
            }
        }

        with patch.object(node_builder, "create_stage_node", side_effect=make_node):
            graph = compiler.compile_stages(["a", "b", "c"], workflow_config)
            result = graph.invoke({
                "workflow_id": "wf-seq",
                "current_stage": "",
                "version": "1.0",
            })

        assert execution_order == ["a", "b", "c"]
        assert result[StateKeys.STAGE_OUTPUTS]["c"]["stage_status"] == "success"
