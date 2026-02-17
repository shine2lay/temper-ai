"""Integration tests for DAG-based parallel stage compilation.

Verifies that StageCompiler correctly builds LangGraph graphs with
fan-out/fan-in edges when stages declare depends_on.
"""
from typing import Dict
from unittest.mock import Mock, patch

import pytest

from src.workflow.condition_evaluator import ConditionEvaluator
from src.workflow.config_loader import ConfigLoader
from src.workflow.node_builder import NodeBuilder
from src.stage.executors.state_keys import StateKeys
from src.stage.stage_compiler import StageCompiler
from src.workflow.state_manager import StateManager
from src.tools.registry import ToolRegistry


def _make_compiler():
    """Create a StageCompiler with real components."""
    state_manager = StateManager()
    config_loader = ConfigLoader()
    tool_registry = ToolRegistry()
    executors = {
        "sequential": Mock(),
        "parallel": Mock(),
        "adaptive": Mock(),
    }
    node_builder = NodeBuilder(config_loader, tool_registry, executors)
    compiler = StageCompiler(state_manager, node_builder)
    return compiler, node_builder


def _make_stage_node(stage_name):
    """Create a stage node that returns partial state updates.

    Returns only changed fields so LangGraph reducers can merge
    concurrent writes from parallel fan-out branches.
    """

    def node(state):
        return {
            "stage_outputs": {stage_name: f"output_{stage_name}"},
            "current_stage": stage_name,
        }

    return node


class TestBackwardCompatibility:
    """No depends_on -> identical to sequential execution."""

    def test_sequential_when_no_depends_on(self):
        """Stages without depends_on execute sequentially."""
        compiler, node_builder = _make_compiler()
        execution_order = []

        def _tracker(name, _cfg):
            def node(state):
                execution_order.append(name)
                return {
                    "stage_outputs": {name: f"out_{name}"},
                }
            return node

        with patch.object(node_builder, "create_stage_node", side_effect=_tracker):
            stages = ["A", "B", "C"]
            config = {"workflow": {"stages": ["A", "B", "C"]}}
            graph = compiler.compile_stages(stages, config)

            result = graph.invoke({"workflow_id": "test-seq", "version": "1.0"})

        assert execution_order == ["A", "B", "C"]
        assert result[StateKeys.STAGE_OUTPUTS]["A"] == "out_A"
        assert result[StateKeys.STAGE_OUTPUTS]["C"] == "out_C"


class TestDAGFanOut:
    """A -> [B, C]: B and C both execute after A."""

    def test_fanout_both_execute(self):
        """Both branches execute and produce outputs."""
        compiler, node_builder = _make_compiler()

        def _node_factory(name, _cfg):
            return _make_stage_node(name)

        with patch.object(node_builder, "create_stage_node", side_effect=_node_factory):
            stages = ["A", "B", "C"]
            config = {
                "workflow": {
                    "stages": [
                        {"name": "A", "stage_ref": "a.yaml"},
                        {"name": "B", "stage_ref": "b.yaml", "depends_on": ["A"]},
                        {"name": "C", "stage_ref": "c.yaml", "depends_on": ["A"]},
                    ]
                }
            }
            graph = compiler.compile_stages(stages, config)
            result = graph.invoke({"workflow_id": "test-fan", "version": "1.0"})

        # Both B and C should have executed
        assert "A" in result[StateKeys.STAGE_OUTPUTS]
        assert "B" in result[StateKeys.STAGE_OUTPUTS]
        assert "C" in result[StateKeys.STAGE_OUTPUTS]
        assert result[StateKeys.STAGE_OUTPUTS]["B"] == "output_B"
        assert result[StateKeys.STAGE_OUTPUTS]["C"] == "output_C"


class TestDAGFanIn:
    """[B, C] -> D: D waits for both B and C."""

    def test_fanin_sees_both_predecessors(self):
        """D sees outputs from both B and C."""
        compiler, node_builder = _make_compiler()

        def _node_factory(name, _cfg):
            return _make_stage_node(name)

        with patch.object(node_builder, "create_stage_node", side_effect=_node_factory):
            stages = ["B", "C", "D"]
            config = {
                "workflow": {
                    "stages": [
                        {"name": "B", "stage_ref": "b.yaml"},
                        {"name": "C", "stage_ref": "c.yaml"},
                        {"name": "D", "stage_ref": "d.yaml", "depends_on": ["B", "C"]},
                    ]
                }
            }
            graph = compiler.compile_stages(stages, config)
            result = graph.invoke({"workflow_id": "test-fanin", "version": "1.0"})

        assert result[StateKeys.STAGE_OUTPUTS]["B"] == "output_B"
        assert result[StateKeys.STAGE_OUTPUTS]["C"] == "output_C"
        assert result[StateKeys.STAGE_OUTPUTS]["D"] == "output_D"


class TestDAGDiamond:
    """A -> [B, C] -> D end-to-end."""

    def test_diamond_execution(self):
        """Diamond topology executes all four stages."""
        compiler, node_builder = _make_compiler()

        def _node_factory(name, _cfg):
            return _make_stage_node(name)

        with patch.object(node_builder, "create_stage_node", side_effect=_node_factory):
            stages = ["A", "B", "C", "D"]
            config = {
                "workflow": {
                    "stages": [
                        {"name": "A", "stage_ref": "a.yaml"},
                        {"name": "B", "stage_ref": "b.yaml", "depends_on": ["A"]},
                        {"name": "C", "stage_ref": "c.yaml", "depends_on": ["A"]},
                        {"name": "D", "stage_ref": "d.yaml", "depends_on": ["B", "C"]},
                    ]
                }
            }
            graph = compiler.compile_stages(stages, config)
            result = graph.invoke({"workflow_id": "test-diamond", "version": "1.0"})

        for name in ["A", "B", "C", "D"]:
            assert name in result[StateKeys.STAGE_OUTPUTS], f"{name} should have output"
            assert result[StateKeys.STAGE_OUTPUTS][name] == f"output_{name}"


class TestDAGConditionalSkip:
    """A -> conditional B + C: B skipped, C runs, D gets C output."""

    def test_conditional_skip_in_dag(self):
        """Conditional stage is skipped; non-conditional sibling runs."""
        compiler, node_builder = _make_compiler()

        def _node_factory(name, _cfg):
            return _make_stage_node(name)

        with patch.object(node_builder, "create_stage_node", side_effect=_node_factory):
            stages = ["A", "B", "C", "D"]
            config = {
                "workflow": {
                    "stages": [
                        {"name": "A", "stage_ref": "a.yaml"},
                        {
                            "name": "B",
                            "stage_ref": "b.yaml",
                            "depends_on": ["A"],
                            "conditional": True,
                            "skip_if": "{{ true }}",
                        },
                        {"name": "C", "stage_ref": "c.yaml", "depends_on": ["A"]},
                        {"name": "D", "stage_ref": "d.yaml", "depends_on": ["B", "C"]},
                    ]
                }
            }
            graph = compiler.compile_stages(stages, config)
            result = graph.invoke({"workflow_id": "test-cond", "version": "1.0"})

        # A and C should execute; B should be skipped (skip_if=true)
        assert "A" in result[StateKeys.STAGE_OUTPUTS]
        assert "C" in result[StateKeys.STAGE_OUTPUTS]
        # D should execute (fan-in from B's skip target + C)
        assert "D" in result[StateKeys.STAGE_OUTPUTS]


class TestDAGGraphStructure:
    """Verify graph node and edge counts for DAG topologies."""

    def test_fanout_graph_edges(self):
        """A -> [B, C]: graph has correct number of edges."""
        compiler, node_builder = _make_compiler()

        with patch.object(
            node_builder, "create_stage_node", return_value=Mock()
        ):
            stages = ["A", "B", "C"]
            config = {
                "workflow": {
                    "stages": [
                        {"name": "A", "stage_ref": "a.yaml"},
                        {"name": "B", "stage_ref": "b.yaml", "depends_on": ["A"]},
                        {"name": "C", "stage_ref": "c.yaml", "depends_on": ["A"]},
                    ]
                }
            }
            graph = compiler.compile_stages(stages, config)

        structure = graph.get_graph()
        node_ids = {n.id for n in structure.nodes.values()}

        # Nodes: __start__, init, A, B, C, __end__
        assert "A" in node_ids
        assert "B" in node_ids
        assert "C" in node_ids
        assert "init" in node_ids

        # Edges: start->init, init->A, A->B, A->C, B->end, C->end = 6
        edge_pairs = [(e.source, e.target) for e in structure.edges]
        assert ("__start__", "init") in edge_pairs
        assert ("init", "A") in edge_pairs
        assert ("A", "B") in edge_pairs
        assert ("A", "C") in edge_pairs
        assert ("B", "__end__") in edge_pairs
        assert ("C", "__end__") in edge_pairs

    def test_diamond_graph_edges(self):
        """A -> [B, C] -> D: correct edge structure."""
        compiler, node_builder = _make_compiler()

        with patch.object(
            node_builder, "create_stage_node", return_value=Mock()
        ):
            stages = ["A", "B", "C", "D"]
            config = {
                "workflow": {
                    "stages": [
                        {"name": "A", "stage_ref": "a.yaml"},
                        {"name": "B", "stage_ref": "b.yaml", "depends_on": ["A"]},
                        {"name": "C", "stage_ref": "c.yaml", "depends_on": ["A"]},
                        {"name": "D", "stage_ref": "d.yaml", "depends_on": ["B", "C"]},
                    ]
                }
            }
            graph = compiler.compile_stages(stages, config)

        structure = graph.get_graph()
        edge_pairs = [(e.source, e.target) for e in structure.edges]

        # start->init, init->A, A->B, A->C, B->D, C->D, D->end = 7
        assert ("init", "A") in edge_pairs
        assert ("A", "B") in edge_pairs
        assert ("A", "C") in edge_pairs
        assert ("B", "D") in edge_pairs
        assert ("C", "D") in edge_pairs
        assert ("D", "__end__") in edge_pairs


class TestDAGLoopBack:
    """Loop-back stage in DAG context."""

    def test_loop_back_creates_gate_node(self):
        """Stage with loops_back_to gets a loop gate node."""
        compiler, node_builder = _make_compiler()

        with patch.object(
            node_builder, "create_stage_node", return_value=Mock()
        ):
            stages = ["A", "B", "C"]
            config = {
                "workflow": {
                    "stages": [
                        {"name": "A", "stage_ref": "a.yaml"},
                        {"name": "B", "stage_ref": "b.yaml", "depends_on": ["A"]},
                        {
                            "name": "C",
                            "stage_ref": "c.yaml",
                            "depends_on": ["B"],
                            "loops_back_to": "A",
                            "max_loops": 2,
                            "loop_condition": "{{ false }}",
                        },
                    ]
                }
            }
            graph = compiler.compile_stages(stages, config)

        structure = graph.get_graph()
        node_ids = {n.id for n in structure.nodes.values()}

        # Should have a loop gate node for C
        assert "_loop_gate_C" in node_ids
        # C connects to gate, gate routes to A or END
        edge_pairs = [(e.source, e.target) for e in structure.edges]
        assert ("C", "_loop_gate_C") in edge_pairs


class TestDAGBarrierNodes:
    """Barrier nodes for asymmetric fan-in equalization."""

    def test_asymmetric_fanin_inserts_barrier(self):
        """A → [B, C], B → D, [C, D] → E: barrier on C→E edge."""
        compiler, node_builder = _make_compiler()

        with patch.object(
            node_builder, "create_stage_node", return_value=Mock()
        ):
            stages = ["A", "B", "C", "D", "E"]
            config = {
                "workflow": {
                    "stages": [
                        {"name": "A"},
                        {"name": "B", "depends_on": ["A"]},
                        {"name": "C", "depends_on": ["A"]},
                        {"name": "D", "depends_on": ["B"]},
                        {"name": "E", "depends_on": ["C", "D"]},
                    ]
                }
            }
            graph = compiler.compile_stages(stages, config)

        structure = graph.get_graph()
        node_ids = {n.id for n in structure.nodes.values()}
        edge_pairs = [(e.source, e.target) for e in structure.edges]

        # Should have a barrier node on the C→E edge
        barrier = "_barrier_C_to_E_0"
        assert barrier in node_ids
        assert ("C", barrier) in edge_pairs
        assert (barrier, "E") in edge_pairs
        # D→E should be direct (already at correct depth)
        assert ("D", "E") in edge_pairs
        # No direct C→E edge
        assert ("C", "E") not in edge_pairs

    def test_asymmetric_fanin_execution_order(self):
        """Barrier ensures E runs only after both C and D complete."""
        compiler, node_builder = _make_compiler()
        execution_order = []

        def _node_factory(name, _cfg):
            def node(state):
                execution_order.append(name)
                return {
                    "stage_outputs": {name: f"output_{name}"},
                    "current_stage": name,
                }
            return node

        with patch.object(node_builder, "create_stage_node", side_effect=_node_factory):
            stages = ["A", "B", "C", "D", "E"]
            config = {
                "workflow": {
                    "stages": [
                        {"name": "A"},
                        {"name": "B", "depends_on": ["A"]},
                        {"name": "C", "depends_on": ["A"]},
                        {"name": "D", "depends_on": ["B"]},
                        {"name": "E", "depends_on": ["C", "D"]},
                    ]
                }
            }
            graph = compiler.compile_stages(stages, config)
            result = graph.invoke({"workflow_id": "test-barrier", "version": "1.0"})

        # E should run after D (and D after B)
        assert execution_order.index("D") > execution_order.index("B")
        assert execution_order.index("E") > execution_order.index("D")
        # All stages should have output
        for name in ["A", "B", "C", "D", "E"]:
            assert name in result[StateKeys.STAGE_OUTPUTS]

    def test_symmetric_fanin_no_barrier(self):
        """A → [B, C] → D: no barrier needed (B and C at same depth)."""
        compiler, node_builder = _make_compiler()

        with patch.object(
            node_builder, "create_stage_node", return_value=Mock()
        ):
            stages = ["A", "B", "C", "D"]
            config = {
                "workflow": {
                    "stages": [
                        {"name": "A"},
                        {"name": "B", "depends_on": ["A"]},
                        {"name": "C", "depends_on": ["A"]},
                        {"name": "D", "depends_on": ["B", "C"]},
                    ]
                }
            }
            graph = compiler.compile_stages(stages, config)

        structure = graph.get_graph()
        node_ids = {n.id for n in structure.nodes.values()}

        # No barrier needed for symmetric fan-in
        barriers = [n for n in node_ids if n.startswith("_barrier_")]
        assert len(barriers) == 0


class TestDAGLoopGateFanOut:
    """Loop gate with multiple exit targets."""

    def test_loop_gate_fans_out_to_all_successors(self):
        """Loop stage with 2 successors: gate exits to both."""
        compiler, node_builder = _make_compiler()

        with patch.object(
            node_builder, "create_stage_node", return_value=Mock()
        ):
            stages = ["A", "B", "C", "D"]
            config = {
                "workflow": {
                    "stages": [
                        {"name": "A"},
                        {
                            "name": "B",
                            "depends_on": ["A"],
                            "loops_back_to": "A",
                            "max_loops": 2,
                            "loop_condition": "{{ false }}",
                        },
                        {"name": "C", "depends_on": ["B"]},
                        {"name": "D", "depends_on": ["B"]},
                    ]
                }
            }
            graph = compiler.compile_stages(stages, config)

        structure = graph.get_graph()
        edge_pairs = [(e.source, e.target) for e in structure.edges]

        # Gate should have edges to both C and D (exit) and A (loop)
        gate = "_loop_gate_B"
        gate_exits = [t for s, t in edge_pairs if s == gate]
        assert "A" in gate_exits, "Gate should route to loop target A"
        assert "C" in gate_exits, "Gate should fan-out to successor C"
        assert "D" in gate_exits, "Gate should fan-out to successor D"


class TestDAGVCSPattern:
    """VCS-like: linear → static → [review, validate] → decision with fan-in + loop."""

    def test_vcs_pattern_execution(self):
        """VCS pattern executes all stages with correct fan-in."""
        compiler, node_builder = _make_compiler()

        def _node_factory(name, _cfg):
            return _make_stage_node(name)

        with patch.object(node_builder, "create_stage_node", side_effect=_node_factory):
            stages = [
                "code", "static",
                "review", "validate",
                "review_dec", "validate_dec",
            ]
            config = {
                "workflow": {
                    "stages": [
                        {"name": "code"},
                        {"name": "static", "depends_on": ["code"]},
                        {"name": "review", "depends_on": ["static"]},
                        {"name": "validate", "depends_on": ["static"]},
                        {"name": "review_dec", "depends_on": ["review"]},
                        {
                            "name": "validate_dec",
                            "depends_on": ["validate", "review_dec"],
                            "loops_back_to": "code",
                            "max_loops": 1,
                            "loop_condition": "{{ false }}",
                        },
                    ]
                }
            }
            graph = compiler.compile_stages(stages, config)
            result = graph.invoke({"workflow_id": "test-vcs", "version": "1.0"})

        # All stages should produce output
        for name in stages:
            assert name in result[StateKeys.STAGE_OUTPUTS], f"{name} missing"

    def test_vcs_pattern_barrier_present(self):
        """VCS pattern has barrier on validate→validate_dec edge."""
        compiler, node_builder = _make_compiler()

        with patch.object(
            node_builder, "create_stage_node", return_value=Mock()
        ):
            stages = [
                "code", "static",
                "review", "validate",
                "review_dec", "validate_dec",
            ]
            config = {
                "workflow": {
                    "stages": [
                        {"name": "code"},
                        {"name": "static", "depends_on": ["code"]},
                        {"name": "review", "depends_on": ["static"]},
                        {"name": "validate", "depends_on": ["static"]},
                        {"name": "review_dec", "depends_on": ["review"]},
                        {
                            "name": "validate_dec",
                            "depends_on": ["validate", "review_dec"],
                            "loops_back_to": "code",
                            "max_loops": 1,
                            "loop_condition": "{{ false }}",
                        },
                    ]
                }
            }
            graph = compiler.compile_stages(stages, config)

        structure = graph.get_graph()
        node_ids = {n.id for n in structure.nodes.values()}
        edge_pairs = [(e.source, e.target) for e in structure.edges]

        # Barrier should be on validate→validate_dec (short branch)
        barrier = "_barrier_validate_to_validate_dec_0"
        assert barrier in node_ids
        assert ("validate", barrier) in edge_pairs
        assert (barrier, "validate_dec") in edge_pairs
        # review_dec→validate_dec should be direct
        assert ("review_dec", "validate_dec") in edge_pairs

    def test_vcs_fan_in_no_double_fire(self):
        """Fan-in node runs once per loop iteration, not per predecessor.

        DAG: code → static(loop) → [review, validate(loop)]
        validate depends_on [static, review]; both static and validate
        loop_back_to code.

        With loop_condition={{ false }} (no loops), each stage runs exactly once.
        The loop gate for static should exit to review only (not validate),
        because validate is reachable via review → validate.
        """
        compiler, node_builder = _make_compiler()
        exec_counts: Dict[str, int] = {}

        def _counting_factory(name, _cfg):
            def node(state):
                exec_counts[name] = exec_counts.get(name, 0) + 1
                return {
                    "stage_outputs": {name: f"output_{name}"},
                    "current_stage": name,
                }
            return node

        with patch.object(
            node_builder, "create_stage_node", side_effect=_counting_factory
        ):
            stages = ["code", "static", "review", "validate"]
            config = {
                "workflow": {
                    "stages": [
                        {"name": "code"},
                        {
                            "name": "static",
                            "depends_on": ["code"],
                            "loops_back_to": "code",
                            "max_loops": 2,
                            "loop_condition": "{{ false }}",
                        },
                        {"name": "review", "depends_on": ["static"]},
                        {
                            "name": "validate",
                            "depends_on": ["static", "review"],
                            "loops_back_to": "code",
                            "max_loops": 2,
                            "loop_condition": "{{ false }}",
                        },
                    ]
                }
            }
            graph = compiler.compile_stages(stages, config)
            result = graph.invoke({"workflow_id": "test-no-double", "version": "1.0"})

        # Every stage should execute exactly once
        for name in stages:
            assert name in result[StateKeys.STAGE_OUTPUTS], f"{name} missing"
            assert exec_counts.get(name, 0) == 1, (
                f"{name} executed {exec_counts.get(name, 0)} times, expected 1"
            )

    def test_vcs_loop_gate_filters_reachable_targets(self):
        """Loop gate for static exits to review only, not validate.

        validate is reachable through review, so it should not appear
        as a direct exit target from static's loop gate.
        """
        compiler, node_builder = _make_compiler()

        with patch.object(
            node_builder, "create_stage_node", return_value=Mock()
        ):
            stages = ["code", "static", "review", "validate"]
            config = {
                "workflow": {
                    "stages": [
                        {"name": "code"},
                        {
                            "name": "static",
                            "depends_on": ["code"],
                            "loops_back_to": "code",
                            "max_loops": 2,
                            "loop_condition": "{{ false }}",
                        },
                        {"name": "review", "depends_on": ["static"]},
                        {
                            "name": "validate",
                            "depends_on": ["static", "review"],
                            "loops_back_to": "code",
                            "max_loops": 2,
                            "loop_condition": "{{ false }}",
                        },
                    ]
                }
            }
            graph = compiler.compile_stages(stages, config)

        structure = graph.get_graph()
        edge_pairs = [(e.source, e.target) for e in structure.edges]

        gate = "_loop_gate_static"
        gate_exits = [t for s, t in edge_pairs if s == gate]
        assert "code" in gate_exits, "Gate should loop back to code"
        assert "review" in gate_exits, "Gate should exit to review"
        # validate should NOT be a direct exit — it's reachable via review
        assert "validate" not in gate_exits, (
            "Gate should not exit directly to validate (reachable via review)"
        )
        # No barrier from static to validate (loop stage pred skipped)
        barrier = "_barrier_static_to_validate_0"
        node_ids = {n.id for n in structure.nodes.values()}
        assert barrier not in node_ids, (
            "No barrier should exist from loop stage static to validate"
        )
