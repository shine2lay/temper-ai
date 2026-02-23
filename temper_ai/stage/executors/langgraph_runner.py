"""LangGraph implementation of ParallelRunner.

Provides the concrete graph-building logic that uses LangGraph StateGraph
for parallel node execution. This is the only file in the executors package
that imports from langgraph.
"""

from collections.abc import Callable
from typing import Annotated, Any

from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from temper_ai.stage.executors.base import ParallelRunner


def _merge_dicts(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    """Merge two dicts, right wins on conflict."""
    merged = left.copy()
    merged.update(right)
    return merged


class _ParallelState(TypedDict, total=False):
    """Internal state schema for parallel subgraphs."""

    agent_outputs: Annotated[dict[str, Any], _merge_dicts]
    agent_statuses: Annotated[dict[str, str], _merge_dicts]
    agent_metrics: Annotated[dict[str, Any], _merge_dicts]
    errors: Annotated[dict[str, str], _merge_dicts]
    stage_input: dict[str, Any]


class LangGraphParallelRunner(ParallelRunner):
    """Runs parallel nodes using a LangGraph StateGraph subgraph."""

    def run_parallel(
        self,
        nodes: dict[str, Callable[[dict[str, Any]], dict[str, Any]]],
        initial_state: dict[str, Any],
        *,
        init_node: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        collect_node: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Execute parallel tasks using LangGraph."""
        graph: StateGraph[Any] = StateGraph(_ParallelState)

        # Add init node
        if init_node is not None:
            graph.add_node("init", init_node)  # type: ignore[call-overload]
            graph.add_edge(START, "init")
        else:
            graph.add_edge(START, "init")
            graph.add_node("init", lambda s: {})

        # Add parallel nodes
        for name, fn in nodes.items():
            graph.add_node(name, fn)  # type: ignore[arg-type]
            graph.add_edge("init", name)
            if collect_node is not None:
                graph.add_edge(name, "collect")
            else:
                graph.add_edge(name, END)

        # Add collect node
        if collect_node is not None:
            graph.add_node("collect", collect_node)  # type: ignore[arg-type]
            graph.add_edge("collect", END)

        graph.set_entry_point("init")
        compiled = graph.compile()
        return compiled.invoke(initial_state)  # type: ignore[arg-type]
