"""ThreadPool-based parallel runner for the dynamic execution engine.

Pure-Python implementation using concurrent.futures.ThreadPoolExecutor.
No LangGraph dependency.

Used for parallel agent execution within a single stage (same role as
LangGraphParallelRunner in the LangGraph engine).
"""

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from temper_ai.stage.executors.base import ParallelRunner

logger = logging.getLogger(__name__)

# Default max workers for parallel agent execution within a stage
DEFAULT_MAX_WORKERS = 8


def _merge_dicts(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge two dicts; right wins on conflict for non-dict values.

    Matches LangGraph's Annotated[Dict, _merge_dicts] reducer semantics:
    when both sides have a dict value for the same key, merge recursively
    instead of replacing. This preserves all parallel agent outputs.
    """
    merged = left.copy()
    for key, value in right.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged


class ThreadPoolParallelRunner(ParallelRunner):
    """Runs parallel agent nodes using concurrent.futures.ThreadPoolExecutor.

    Drop-in replacement for LangGraphParallelRunner with identical semantics:
    1. Run optional init_node
    2. Fan-out: submit all node callables to ThreadPoolExecutor
    3. Collect results, merge dicts (right wins on conflict)
    4. Run optional collect_node
    5. Return merged state

    Args:
        max_workers: Maximum number of threads for parallel execution.
    """

    def __init__(self, max_workers: int = DEFAULT_MAX_WORKERS) -> None:
        self.max_workers = max_workers

    def run_parallel(
        self,
        nodes: dict[str, Callable[[dict[str, Any]], dict[str, Any]]],
        initial_state: dict[str, Any],
        *,
        init_node: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        collect_node: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Execute nodes in parallel and return collected results.

        Args:
            nodes: Mapping of node_name -> callable for parallel execution.
            initial_state: Starting state dict.
            init_node: Optional initialization callable (runs before parallel nodes).
            collect_node: Optional collection callable (runs after all parallel nodes).

        Returns:
            Final merged state after all nodes have completed.
        """
        state = dict(initial_state)

        # Step 1: Run init node if provided
        if init_node is not None:
            updates = init_node(state)
            if updates:
                state = _merge_dicts(state, updates)

        # Step 2: Fan-out parallel execution
        if not nodes:
            logger.warning("No nodes to execute in parallel")
        else:
            state = self._run_nodes_parallel(nodes, state)

        # Step 3: Run collect node if provided
        if collect_node is not None:
            updates = collect_node(state)
            if updates:
                state = _merge_dicts(state, updates)

        return state

    def _run_nodes_parallel(
        self,
        nodes: dict[str, Callable[[dict[str, Any]], dict[str, Any]]],
        state: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute nodes in parallel using ThreadPoolExecutor.

        Each node receives a copy of the current state.
        Results are merged in submission order (last write wins on conflict).
        """
        effective_workers = min(self.max_workers, len(nodes))
        merged = dict(state)

        with ThreadPoolExecutor(max_workers=effective_workers) as executor:
            future_to_name = {
                executor.submit(fn, dict(state)): name for name, fn in nodes.items()
            }

            for future in as_completed(future_to_name):
                name = future_to_name[future]
                try:
                    result = future.result()
                    if result:
                        merged = _merge_dicts(merged, result)
                except Exception:
                    logger.exception("Parallel node '%s' failed", name)
                    merged.setdefault("_failed_nodes", []).append(name)

        return merged
