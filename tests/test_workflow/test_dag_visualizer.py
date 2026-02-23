"""Tests for DAG visualization (R3)."""

from temper_ai.workflow.dag_builder import StageDAG


def _make_dag(names, edges):
    """Build StageDAG from names and edge list [(from, to), ...]."""
    predecessors = {n: [] for n in names}
    successors = {n: [] for n in names}
    for src, dst in edges:
        predecessors[dst].append(src)
        successors[src].append(dst)
    roots = [n for n in names if not predecessors[n]]
    terminals = [n for n in names if not successors[n]]
    return StageDAG(
        predecessors=predecessors,
        successors=successors,
        roots=roots,
        terminals=terminals,
        topo_order=names,
    )


class TestExportMermaid:
    def test_mermaid_linear_chain(self):
        from temper_ai.workflow.dag_visualizer import export_mermaid

        dag = _make_dag(["A", "B", "C"], [("A", "B"), ("B", "C")])
        result = export_mermaid(dag)
        assert "graph TD" in result
        assert "A --> B" in result
        assert "B --> C" in result

    def test_mermaid_diamond(self):
        from temper_ai.workflow.dag_visualizer import export_mermaid

        dag = _make_dag(
            ["A", "B", "C", "D"],
            [("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")],
        )
        result = export_mermaid(dag)
        assert "A --> B" in result
        assert "A --> C" in result
        assert "B --> D" in result
        assert "C --> D" in result

    def test_mermaid_root_terminal_styling(self):
        from temper_ai.workflow.dag_visualizer import export_mermaid
        from temper_ai.workflow.dag_visualizer_constants import (
            MERMAID_ROOT_STYLE,
            MERMAID_TERMINAL_STYLE,
        )

        dag = _make_dag(["A", "B"], [("A", "B")])
        result = export_mermaid(dag)
        assert f"style A {MERMAID_ROOT_STYLE}" in result
        assert f"style B {MERMAID_TERMINAL_STYLE}" in result

    def test_mermaid_no_edges_single_node(self):
        from temper_ai.workflow.dag_visualizer import export_mermaid

        dag = _make_dag(["solo"], [])
        result = export_mermaid(dag)
        assert "graph TD" in result
        assert "solo" in result


class TestExportDot:
    def test_dot_output_valid(self):
        from temper_ai.workflow.dag_visualizer import export_dot

        dag = _make_dag(["A", "B", "C"], [("A", "B"), ("B", "C")])
        result = export_dot(dag)
        assert "digraph workflow" in result
        assert "rankdir=TB" in result
        assert '"A" -> "B"' in result
        assert '"B" -> "C"' in result

    def test_dot_root_terminal_colors(self):
        from temper_ai.workflow.dag_visualizer import export_dot
        from temper_ai.workflow.dag_visualizer_constants import (
            DOT_ROOT_COLOR,
            DOT_TERMINAL_COLOR,
        )

        dag = _make_dag(["A", "B"], [("A", "B")])
        result = export_dot(dag)
        assert DOT_ROOT_COLOR in result
        assert DOT_TERMINAL_COLOR in result

    def test_dot_node_shape(self):
        from temper_ai.workflow.dag_visualizer import export_dot
        from temper_ai.workflow.dag_visualizer_constants import DOT_NODE_SHAPE

        dag = _make_dag(["X"], [])
        result = export_dot(dag)
        assert f"shape={DOT_NODE_SHAPE}" in result


class TestRenderConsoleDAG:
    def test_ascii_linear(self):
        from temper_ai.workflow.dag_visualizer import render_console_dag

        dag = _make_dag(["A", "B", "C"], [("A", "B"), ("B", "C")])
        result = render_console_dag(dag)
        assert "Workflow DAG:" in result
        assert "Level 0" in result
        assert "Level 1" in result
        assert "Level 2" in result
        assert "A" in result
        assert "B" in result
        assert "C" in result

    def test_ascii_diamond(self):
        from temper_ai.workflow.dag_visualizer import render_console_dag

        dag = _make_dag(
            ["A", "B", "C", "D"],
            [("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")],
        )
        result = render_console_dag(dag)
        assert "Level 0" in result
        assert "Level 1" in result
        assert "B" in result
        assert "C" in result
        assert "D" in result

    def test_ascii_root_and_terminal_labels(self):
        from temper_ai.workflow.dag_visualizer import render_console_dag

        dag = _make_dag(["start", "end"], [("start", "end")])
        result = render_console_dag(dag)
        assert "(root)" in result
        assert "(terminal)" in result


class TestSingleStage:
    def test_single_stage_mermaid(self):
        from temper_ai.workflow.dag_visualizer import export_mermaid

        dag = _make_dag(["only"], [])
        result = export_mermaid(dag)
        assert "graph TD" in result
        assert "only" in result

    def test_single_stage_dot(self):
        from temper_ai.workflow.dag_visualizer import export_dot

        dag = _make_dag(["only"], [])
        result = export_dot(dag)
        assert "digraph workflow" in result
        assert '"only"' in result

    def test_single_stage_ascii(self):
        from temper_ai.workflow.dag_visualizer import render_console_dag

        dag = _make_dag(["only"], [])
        result = render_console_dag(dag)
        assert "only" in result
        assert "Level 0" in result
