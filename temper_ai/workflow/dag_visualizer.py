"""DAG visualization: export workflow DAGs as Mermaid, DOT, or ASCII.

Usage:
    >>> from temper_ai.workflow.dag_builder import build_stage_dag
    >>> dag = build_stage_dag(names, refs)
    >>> print(export_mermaid(dag))
"""

import logging
from collections import defaultdict

from temper_ai.workflow.dag_builder import StageDAG, compute_depths
from temper_ai.workflow.dag_visualizer_constants import (
    ASCII_ARROW,
    DOT_NODE_SHAPE,
    DOT_RANKDIR,
    DOT_ROOT_COLOR,
    DOT_TERMINAL_COLOR,
    MERMAID_DIRECTION,
    MERMAID_ROOT_STYLE,
    MERMAID_TERMINAL_STYLE,
)

logger = logging.getLogger(__name__)


def export_mermaid(dag: StageDAG) -> str:
    """Generate Mermaid flowchart from a StageDAG.

    Args:
        dag: The DAG to render.

    Returns:
        Mermaid diagram string.
    """
    lines = [f"graph {MERMAID_DIRECTION}"]
    for stage in dag.topo_order:
        for pred in dag.predecessors[stage]:
            lines.append(f"    {pred} --> {stage}")
    for root in dag.roots:
        lines.append(f"    style {root} {MERMAID_ROOT_STYLE}")
    for terminal in dag.terminals:
        lines.append(f"    style {terminal} {MERMAID_TERMINAL_STYLE}")
    return "\n".join(lines)


def export_dot(dag: StageDAG) -> str:
    """Generate Graphviz DOT format from a StageDAG.

    Args:
        dag: The DAG to render.

    Returns:
        DOT diagram string.
    """
    lines = [
        "digraph workflow {",
        f"    rankdir={DOT_RANKDIR};",
        f"    node [shape={DOT_NODE_SHAPE}];",
    ]
    for stage in dag.topo_order:
        color = _dot_node_color(stage, dag)
        lines.append(f'    "{stage}" [fillcolor="{color}", style=filled];')
    for stage in dag.topo_order:
        for pred in dag.predecessors[stage]:
            lines.append(f'    "{pred}" -> "{stage}";')
    lines.append("}")
    return "\n".join(lines)


def _dot_node_color(stage: str, dag: StageDAG) -> str:
    """Return DOT fill color for a node based on its role.

    Args:
        stage: Stage name.
        dag: The StageDAG.

    Returns:
        Hex color string.
    """
    if stage in dag.roots:
        return DOT_ROOT_COLOR
    if stage in dag.terminals:
        return DOT_TERMINAL_COLOR
    return "#ffffff"


def render_console_dag(dag: StageDAG) -> str:
    """Render ASCII tree of workflow DAG grouped by depth level.

    Args:
        dag: The DAG to render.

    Returns:
        Multi-line ASCII string for terminal display.
    """
    depths = compute_depths(dag)
    by_depth: dict[int, list[str]] = defaultdict(list)
    for stage, depth in depths.items():
        by_depth[depth].append(stage)

    lines = ["Workflow DAG:"]
    max_depth = max(depths.values()) if depths else 0
    for level in range(max_depth + 1):
        stages = by_depth.get(level, [])
        suffixes = _stage_suffixes(stages, dag)
        stage_labels = ", ".join(f"{s}{suffixes[s]}" for s in stages)
        lines.append(f"  Level {level}: {stage_labels}")
        all_successors = _collect_successors(stages, dag)
        for succ in all_successors:
            lines.append(f"    {ASCII_ARROW}{succ}")
    return "\n".join(lines)


def _stage_suffixes(stages: list[str], dag: StageDAG) -> dict[str, str]:
    """Return display suffix per stage (' (root)', ' (terminal)', or '').

    Args:
        stages: List of stage names.
        dag: The StageDAG.

    Returns:
        Dict mapping stage name to suffix string.
    """
    result = {}
    for stage in stages:
        if stage in dag.roots:
            result[stage] = " (root)"
        elif stage in dag.terminals:
            result[stage] = " (terminal)"
        else:
            result[stage] = ""
    return result


def _collect_successors(stages: list[str], dag: StageDAG) -> list[str]:
    """Collect unique successors across a list of stages in topo order.

    Args:
        stages: List of stage names.
        dag: The StageDAG.

    Returns:
        Ordered unique list of successor stage names.
    """
    seen = set()
    result = []
    for stage in stages:
        for succ in dag.successors.get(stage, []):
            if succ not in seen:
                seen.add(succ)
                result.append(succ)
    return result
