"""LangGraph implementation of ParallelRunner.

Provides the concrete graph-building logic that uses LangGraph StateGraph
for parallel node execution. This is the only file in the executors package
that imports from langgraph.
"""
from typing import Any, Callable, Dict, Optional

from langgraph.graph import END, START, StateGraph
from typing_extensions import Annotated, TypedDict

from src.compiler.executors.base import ParallelRunner


def _merge_dicts(left: Dict[str, Any], right: Dict[str, Any]) -> Dict[str, Any]:
    """Merge two dicts, right wins on conflict."""
    merged = left.copy()
    merged.update(right)
    return merged


class _ParallelState(TypedDict, total=False):
    """Internal state schema for parallel subgraphs."""
    agent_outputs: Annotated[Dict[str, Any], _merge_dicts]
    agent_statuses: Annotated[Dict[str, str], _merge_dicts]
    agent_metrics: Annotated[Dict[str, Any], _merge_dicts]
    errors: Annotated[Dict[str, str], _merge_dicts]
    stage_input: Dict[str, Any]


class LangGraphParallelRunner(ParallelRunner):
    """Runs parallel nodes using a LangGraph StateGraph subgraph."""

    def run_parallel(
        self,
        nodes: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]],
        initial_state: Dict[str, Any],
        *,
        init_node: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
        collect_node: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Execute parallel tasks using LangGraph."""
        graph: StateGraph[Any] = StateGraph(_ParallelState)

        # Add init node
        if init_node is not None:
            graph.add_node("init", init_node)  # type: ignore[call-overload]
            graph.add_edge(START, "init")
        else:
            graph.add_edge(START, "init")
            graph.add_node("init", lambda s: {})  # type: ignore[call-overload]

        # Add parallel nodes
        for name, fn in nodes.items():
            graph.add_node(name, fn)  # type: ignore[call-overload]
            graph.add_edge("init", name)
            if collect_node is not None:
                graph.add_edge(name, "collect")
            else:
                graph.add_edge(name, END)

        # Add collect node
        if collect_node is not None:
            graph.add_node("collect", collect_node)  # type: ignore[call-overload]
            graph.add_edge("collect", END)

        graph.set_entry_point("init")
        compiled = graph.compile()
        return compiled.invoke(initial_state)  # type: ignore[arg-type]
