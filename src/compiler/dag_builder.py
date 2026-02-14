"""DAG construction and topological sort for workflow stage dependencies.

Builds a directed acyclic graph (DAG) from ``depends_on`` declarations in
``WorkflowStageReference`` objects.  When no stage declares ``depends_on``,
callers fall back to the legacy sequential edge strategy.

Example:
    >>> dag = build_stage_dag(["A", "B", "C"], stage_refs)
    >>> dag.roots       # stages with no predecessors
    >>> dag.terminals   # stages with no successors
    >>> dag.topo_order  # valid execution order
"""
import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class StageDAG:
    """Immutable result of DAG construction.

    Attributes:
        predecessors: stage -> list of stages it depends on
        successors: stage -> list of stages that depend on it
        roots: stages with no predecessors (entry points)
        terminals: stages with no successors (exit points)
        topo_order: topologically sorted stage names
    """

    predecessors: Dict[str, List[str]] = field(default_factory=dict)
    successors: Dict[str, List[str]] = field(default_factory=dict)
    roots: List[str] = field(default_factory=list)
    terminals: List[str] = field(default_factory=list)
    topo_order: List[str] = field(default_factory=list)


def has_dag_dependencies(stage_refs: List[Any]) -> bool:
    """Return True if any stage declares ``depends_on``.

    Used as a backward-compatibility gate: when no stage uses ``depends_on``,
    the compiler falls back to sequential edge creation.

    Args:
        stage_refs: List of WorkflowStageReference (dict or object)

    Returns:
        True if at least one stage has a non-empty depends_on list
    """
    for ref in stage_refs:
        deps = _get_depends_on(ref)
        if deps:
            return True
    return False


def build_stage_dag(
    stage_names: List[str],
    stage_refs: List[Any],
) -> StageDAG:
    """Build a StageDAG from stage names and their references.

    Args:
        stage_names: Ordered list of stage names
        stage_refs: Corresponding WorkflowStageReference objects

    Returns:
        StageDAG with predecessors, successors, roots, terminals, topo_order

    Raises:
        ValueError: If depends_on references an unknown stage or a cycle exists
    """
    ref_lookup = _build_ref_lookup(stage_refs)
    name_set = set(stage_names)

    predecessors: Dict[str, List[str]] = {name: [] for name in stage_names}
    successors: Dict[str, List[str]] = {name: [] for name in stage_names}

    _populate_edges(stage_names, ref_lookup, name_set, predecessors, successors)

    cycle = _detect_cycle(predecessors, stage_names)
    if cycle is not None:
        raise ValueError(f"Cycle detected in stage dependencies: {' -> '.join(cycle)}")

    topo_order = _topological_sort(predecessors, stage_names)
    roots = [n for n in topo_order if not predecessors[n]]
    terminals = [n for n in topo_order if not successors[n]]

    return StageDAG(
        predecessors=predecessors,
        successors=successors,
        roots=roots,
        terminals=terminals,
        topo_order=topo_order,
    )


def _populate_edges(
    stage_names: List[str],
    ref_lookup: Dict[str, Any],
    name_set: set,
    predecessors: Dict[str, List[str]],
    successors: Dict[str, List[str]],
) -> None:
    """Fill predecessors and successors dicts from depends_on declarations.

    Args:
        stage_names: All stage names
        ref_lookup: stage name -> stage reference
        name_set: Set of valid stage names for fast lookup
        predecessors: Output dict: stage -> deps (mutated in place)
        successors: Output dict: stage -> dependents (mutated in place)

    Raises:
        ValueError: If a depends_on target is not a known stage
    """
    for name in stage_names:
        ref = ref_lookup.get(name)
        deps = _get_depends_on(ref) if ref else []
        for dep in deps:
            if dep not in name_set:
                raise ValueError(
                    f"Stage '{name}' depends_on unknown stage '{dep}'"
                )
            predecessors[name].append(dep)
            successors[dep].append(name)


def _detect_cycle(
    predecessors: Dict[str, List[str]],
    stage_names: List[str],
) -> Optional[List[str]]:
    """Detect a cycle using Kahn's algorithm.

    Args:
        predecessors: stage -> list of predecessor stages
        stage_names: All stage names

    Returns:
        List of stage names forming a cycle, or None if acyclic
    """
    in_degree = {n: len(predecessors[n]) for n in stage_names}
    queue: deque[str] = deque(n for n in stage_names if in_degree[n] == 0)
    visited_count = 0

    while queue:
        node = queue.popleft()
        visited_count += 1
        for child in stage_names:
            if node in predecessors[child]:
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    queue.append(child)

    if visited_count == len(stage_names):
        return None

    # Find one cycle for the error message
    remaining = [n for n in stage_names if in_degree[n] > 0]
    return remaining


def _topological_sort(
    predecessors: Dict[str, List[str]],
    stage_names: List[str],
) -> List[str]:
    """Kahn's algorithm topological sort preserving declaration order for ties.

    Args:
        predecessors: stage -> list of predecessor stages
        stage_names: All stage names (defines tie-break order)

    Returns:
        Topologically sorted list of stage names
    """
    in_degree = {n: len(predecessors[n]) for n in stage_names}
    # Use declaration order for deterministic tie-breaking
    order_index = {name: i for i, name in enumerate(stage_names)}
    queue: deque[str] = deque(
        sorted(
            (n for n in stage_names if in_degree[n] == 0),
            key=lambda n: order_index[n],
        )
    )
    result: List[str] = []

    while queue:
        node = queue.popleft()
        result.append(node)
        # Find children in declaration order
        children = sorted(
            (c for c in stage_names if node in predecessors[c]),
            key=lambda c: order_index[c],
        )
        for child in children:
            in_degree[child] -= 1
            if in_degree[child] == 0:
                queue.append(child)

    return result


def _build_ref_lookup(stage_refs: List[Any]) -> Dict[str, Any]:
    """Build name -> reference lookup from stage references.

    Args:
        stage_refs: List of WorkflowStageReference (dict or object)

    Returns:
        Dict mapping stage name to its reference
    """
    lookup: Dict[str, Any] = {}
    for ref in stage_refs:
        if isinstance(ref, str):
            continue
        name = ref.get("name") if isinstance(ref, dict) else getattr(ref, "name", None)
        if name:
            lookup[name] = ref
    return lookup


def compute_depths(dag: StageDAG) -> Dict[str, int]:
    """Compute the depth (longest path from any root) for each stage.

    Used to detect asymmetric fan-in where LangGraph's Pregel model
    would trigger a node before all predecessors complete.

    Args:
        dag: Built StageDAG with predecessors and topo_order

    Returns:
        Dict mapping stage name to its depth (0 for roots)
    """
    depths: Dict[str, int] = {}
    for stage in dag.topo_order:
        preds = dag.predecessors.get(stage, [])
        if not preds:
            depths[stage] = 0
        else:
            depths[stage] = max(depths[p] for p in preds) + 1
    return depths


def _get_depends_on(ref: Any) -> List[str]:
    """Extract depends_on list from a stage reference.

    Args:
        ref: Stage reference (dict, object, or string)

    Returns:
        List of dependency stage names (empty if none)
    """
    if ref is None or isinstance(ref, str):
        return []
    if isinstance(ref, dict):
        return ref.get("depends_on", [])
    return getattr(ref, "depends_on", [])
