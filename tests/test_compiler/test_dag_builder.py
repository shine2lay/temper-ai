"""Tests for DAG builder — stage dependency graph construction."""
import pytest

from src.compiler.dag_builder import (
    StageDAG,
    build_stage_dag,
    compute_depths,
    has_dag_dependencies,
)


class TestHasDagDependencies:
    """Test the backward-compatibility gate."""

    def test_no_depends_on_returns_false(self):
        """Stages without depends_on -> sequential mode."""
        refs = [
            {"name": "A", "stage_ref": "a.yaml"},
            {"name": "B", "stage_ref": "b.yaml"},
        ]
        assert has_dag_dependencies(refs) is False

    def test_empty_depends_on_returns_false(self):
        """Stages with empty depends_on lists -> sequential mode."""
        refs = [
            {"name": "A", "stage_ref": "a.yaml", "depends_on": []},
            {"name": "B", "stage_ref": "b.yaml", "depends_on": []},
        ]
        assert has_dag_dependencies(refs) is False

    def test_with_depends_on_returns_true(self):
        """At least one depends_on -> DAG mode."""
        refs = [
            {"name": "A", "stage_ref": "a.yaml"},
            {"name": "B", "stage_ref": "b.yaml", "depends_on": ["A"]},
        ]
        assert has_dag_dependencies(refs) is True

    def test_string_refs_ignored(self):
        """Plain string refs (no depends_on) -> sequential mode."""
        refs = ["A", "B", "C"]
        assert has_dag_dependencies(refs) is False


class TestBuildStageDAGLinear:
    """Test linear chain (A -> B -> C)."""

    def test_linear_chain(self):
        """A -> B -> C produces correct predecessors/successors."""
        refs = [
            {"name": "A", "stage_ref": "a.yaml"},
            {"name": "B", "stage_ref": "b.yaml", "depends_on": ["A"]},
            {"name": "C", "stage_ref": "c.yaml", "depends_on": ["B"]},
        ]
        dag = build_stage_dag(["A", "B", "C"], refs)

        assert dag.predecessors["A"] == []
        assert dag.predecessors["B"] == ["A"]
        assert dag.predecessors["C"] == ["B"]
        assert dag.successors["A"] == ["B"]
        assert dag.successors["B"] == ["C"]
        assert dag.successors["C"] == []
        assert dag.roots == ["A"]
        assert dag.terminals == ["C"]
        assert dag.topo_order == ["A", "B", "C"]


class TestBuildStageDAGFanOut:
    """Test fan-out: A -> [B, C]."""

    def test_single_fanout(self):
        """A -> [B, C] produces correct structure."""
        refs = [
            {"name": "A", "stage_ref": "a.yaml"},
            {"name": "B", "stage_ref": "b.yaml", "depends_on": ["A"]},
            {"name": "C", "stage_ref": "c.yaml", "depends_on": ["A"]},
        ]
        dag = build_stage_dag(["A", "B", "C"], refs)

        assert dag.roots == ["A"]
        assert set(dag.successors["A"]) == {"B", "C"}
        assert dag.terminals == ["B", "C"]
        assert dag.topo_order[0] == "A"
        assert set(dag.topo_order[1:]) == {"B", "C"}


class TestBuildStageDAGFanIn:
    """Test fan-in: [B, C] -> D."""

    def test_fan_in(self):
        """[B, C] -> D produces correct predecessors."""
        refs = [
            {"name": "B", "stage_ref": "b.yaml"},
            {"name": "C", "stage_ref": "c.yaml"},
            {"name": "D", "stage_ref": "d.yaml", "depends_on": ["B", "C"]},
        ]
        dag = build_stage_dag(["B", "C", "D"], refs)

        assert set(dag.predecessors["D"]) == {"B", "C"}
        assert dag.roots == ["B", "C"]
        assert dag.terminals == ["D"]


class TestBuildStageDAGDiamond:
    """Test diamond: A -> [B, C] -> D."""

    def test_diamond(self):
        """A -> [B, C] -> D produces valid topo order."""
        refs = [
            {"name": "A", "stage_ref": "a.yaml"},
            {"name": "B", "stage_ref": "b.yaml", "depends_on": ["A"]},
            {"name": "C", "stage_ref": "c.yaml", "depends_on": ["A"]},
            {"name": "D", "stage_ref": "d.yaml", "depends_on": ["B", "C"]},
        ]
        dag = build_stage_dag(["A", "B", "C", "D"], refs)

        assert dag.roots == ["A"]
        assert dag.terminals == ["D"]
        # A must come before B, C; B and C must come before D
        order = dag.topo_order
        assert order.index("A") < order.index("B")
        assert order.index("A") < order.index("C")
        assert order.index("B") < order.index("D")
        assert order.index("C") < order.index("D")


class TestBuildStageDAGMultipleRoots:
    """Test multiple root stages."""

    def test_multiple_roots(self):
        """Two independent roots with a shared dependent."""
        refs = [
            {"name": "X", "stage_ref": "x.yaml"},
            {"name": "Y", "stage_ref": "y.yaml"},
            {"name": "Z", "stage_ref": "z.yaml", "depends_on": ["X", "Y"]},
        ]
        dag = build_stage_dag(["X", "Y", "Z"], refs)

        assert set(dag.roots) == {"X", "Y"}
        assert dag.terminals == ["Z"]


class TestBuildStageDAGSingleStage:
    """Test trivial single-stage DAG."""

    def test_single_stage(self):
        """One stage, no deps."""
        refs = [{"name": "only", "stage_ref": "only.yaml"}]
        dag = build_stage_dag(["only"], refs)

        assert dag.roots == ["only"]
        assert dag.terminals == ["only"]
        assert dag.topo_order == ["only"]


class TestBuildStageDAGErrors:
    """Test error conditions."""

    def test_unknown_dependency_raises(self):
        """depends_on referencing unknown stage -> ValueError."""
        refs = [
            {"name": "A", "stage_ref": "a.yaml"},
            {"name": "B", "stage_ref": "b.yaml", "depends_on": ["UNKNOWN"]},
        ]
        with pytest.raises(ValueError, match="unknown stage 'UNKNOWN'"):
            build_stage_dag(["A", "B"], refs)

    def test_cycle_raises(self):
        """Circular dependency -> ValueError."""
        refs = [
            {"name": "A", "stage_ref": "a.yaml", "depends_on": ["C"]},
            {"name": "B", "stage_ref": "b.yaml", "depends_on": ["A"]},
            {"name": "C", "stage_ref": "c.yaml", "depends_on": ["B"]},
        ]
        with pytest.raises(ValueError, match="Cycle detected"):
            build_stage_dag(["A", "B", "C"], refs)

    def test_self_dependency_raises(self):
        """Stage depending on itself -> ValueError (cycle)."""
        refs = [
            {"name": "A", "stage_ref": "a.yaml", "depends_on": ["A"]},
        ]
        with pytest.raises(ValueError, match="Cycle detected"):
            build_stage_dag(["A"], refs)


class TestBuildStageDAGDeclarationOrder:
    """Test that topo sort preserves declaration order for ties."""

    def test_declaration_order_tiebreak(self):
        """Independent stages appear in declaration order."""
        refs = [
            {"name": "Z", "stage_ref": "z.yaml"},
            {"name": "A", "stage_ref": "a.yaml"},
            {"name": "M", "stage_ref": "m.yaml"},
        ]
        dag = build_stage_dag(["Z", "A", "M"], refs)
        # All are roots with no deps, should respect declaration order
        assert dag.topo_order == ["Z", "A", "M"]


class TestComputeDepths:
    """Test depth computation for barrier insertion."""

    def test_linear_depths(self):
        """A -> B -> C: depths 0, 1, 2."""
        refs = [
            {"name": "A"},
            {"name": "B", "depends_on": ["A"]},
            {"name": "C", "depends_on": ["B"]},
        ]
        dag = build_stage_dag(["A", "B", "C"], refs)
        depths = compute_depths(dag)
        assert depths == {"A": 0, "B": 1, "C": 2}

    def test_diamond_depths(self):
        """A -> [B, C] -> D: B and C at depth 1, D at depth 2."""
        refs = [
            {"name": "A"},
            {"name": "B", "depends_on": ["A"]},
            {"name": "C", "depends_on": ["A"]},
            {"name": "D", "depends_on": ["B", "C"]},
        ]
        dag = build_stage_dag(["A", "B", "C", "D"], refs)
        depths = compute_depths(dag)
        assert depths == {"A": 0, "B": 1, "C": 1, "D": 2}

    def test_asymmetric_depths(self):
        """A -> [B, C], B -> D, [C, D] -> E: depths reveal asymmetry."""
        refs = [
            {"name": "A"},
            {"name": "B", "depends_on": ["A"]},
            {"name": "C", "depends_on": ["A"]},
            {"name": "D", "depends_on": ["B"]},
            {"name": "E", "depends_on": ["C", "D"]},
        ]
        dag = build_stage_dag(["A", "B", "C", "D", "E"], refs)
        depths = compute_depths(dag)
        # E's predecessors: C at depth 1, D at depth 2 → E at depth 3
        assert depths["A"] == 0
        assert depths["B"] == 1
        assert depths["C"] == 1
        assert depths["D"] == 2
        assert depths["E"] == 3

    def test_roots_have_depth_zero(self):
        """Multiple roots all have depth 0."""
        refs = [
            {"name": "X"},
            {"name": "Y"},
            {"name": "Z", "depends_on": ["X", "Y"]},
        ]
        dag = build_stage_dag(["X", "Y", "Z"], refs)
        depths = compute_depths(dag)
        assert depths["X"] == 0
        assert depths["Y"] == 0
        assert depths["Z"] == 1
