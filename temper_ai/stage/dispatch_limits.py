"""Safety caps for runtime dispatch — configurable per-workflow.

Prevents a buggy dispatcher from:
  - emitting thousands of children in one shot (max_children_per_dispatch)
  - running up an unbounded number of dynamic nodes across a whole run
    (max_dynamic_nodes)
  - recursing without bound through nested dispatches
    (max_dispatch_depth)
  - dispatching the same (agent, input) fingerprint found in its own
    ancestor chain (cycle_detection)

All caps default to permissive-but-not-unbounded values. A workflow can
override them in `defaults.dispatch`:

    workflow:
      defaults:
        dispatch:
          max_children_per_dispatch: 50
          max_dynamic_nodes: 500
          max_dispatch_depth: 5
          cycle_detection: true

Breaches surface as DispatchCapExceeded — same surfacing path as any
failing node: the dispatcher's node fails, downstream cascades.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


DEFAULT_MAX_CHILDREN_PER_DISPATCH = 20
DEFAULT_MAX_DYNAMIC_NODES = 200
DEFAULT_MAX_DISPATCH_DEPTH = 3
DEFAULT_CYCLE_DETECTION = True


class DispatchCapExceeded(Exception):
    """Raised when a safety cap is exceeded during dispatch."""


@dataclass
class DispatchLimits:
    """Per-workflow limits on runtime DAG mutation via dispatch.

    All values are configurable per workflow via `defaults.dispatch` in the
    workflow YAML. Missing keys fall back to the module-level defaults above.
    """

    max_children_per_dispatch: int = DEFAULT_MAX_CHILDREN_PER_DISPATCH
    max_dynamic_nodes: int = DEFAULT_MAX_DYNAMIC_NODES
    max_dispatch_depth: int = DEFAULT_MAX_DISPATCH_DEPTH
    cycle_detection: bool = DEFAULT_CYCLE_DETECTION

    @classmethod
    def from_defaults(cls, defaults: dict[str, Any] | None) -> DispatchLimits:
        """Build DispatchLimits from a workflow's `defaults` dict.

        Reads `defaults.dispatch.*` and merges with module defaults. A missing
        `defaults` (None) or missing `dispatch` section returns full defaults.
        """
        if not defaults or not isinstance(defaults, dict):
            return cls()
        raw = defaults.get("dispatch")
        if not isinstance(raw, dict):
            return cls()

        def _int(key: str, default: int) -> int:
            v = raw.get(key)
            if v is None:
                return default
            try:
                iv = int(v)
            except (TypeError, ValueError):
                logger.warning(
                    "Invalid dispatch.%s=%r (expected int); using default %d",
                    key, v, default,
                )
                return default
            if iv < 0:
                logger.warning(
                    "dispatch.%s=%d must be non-negative; using default %d",
                    key, iv, default,
                )
                return default
            return iv

        def _bool(key: str, default: bool) -> bool:
            v = raw.get(key)
            return default if v is None else bool(v)

        return cls(
            max_children_per_dispatch=_int(
                "max_children_per_dispatch", DEFAULT_MAX_CHILDREN_PER_DISPATCH,
            ),
            max_dynamic_nodes=_int(
                "max_dynamic_nodes", DEFAULT_MAX_DYNAMIC_NODES,
            ),
            max_dispatch_depth=_int(
                "max_dispatch_depth", DEFAULT_MAX_DISPATCH_DEPTH,
            ),
            cycle_detection=_bool("cycle_detection", DEFAULT_CYCLE_DETECTION),
        )


@dataclass
class DispatchRunState:
    """Per-run bookkeeping for dispatch safety caps.

    Attached to ExecutionContext so the executor can enforce caps that
    span the whole run (not just one dispatcher). Mutable — updated as
    each dispatch fires.

    dispatched_count    Total number of nodes added via dispatch so far.
                        Enforced against max_dynamic_nodes.
    depths              Maps dispatched-node-name → dispatch depth.
                        Originally-in-workflow nodes aren't tracked
                        (implicit depth 0); first generation of
                        dispatched children = 1, their children = 2, etc.
                        Enforced against max_dispatch_depth.
    parents             Maps dispatched-node-name → dispatcher-node-name.
                        Used to walk the ancestor chain for cycle_detection.
    fingerprints        Maps node-name → (agent_name, input_hash).
                        Recorded for every node (including originals) so
                        cycle-detection can walk back to the workflow root.
    """

    dispatched_count: int = 0
    depths: dict[str, int] = field(default_factory=dict)
    parents: dict[str, str] = field(default_factory=dict)
    fingerprints: dict[str, tuple[str, str]] = field(default_factory=dict)


def fingerprint_node(agent_name: str, input_data: dict[str, Any] | None) -> tuple[str, str]:
    """Compute a (agent_name, input_hash) tuple for cycle detection.

    The input_hash is the SHA1 of the canonical JSON form of input_data;
    falls back to str(input_data) if JSON serialization fails (e.g. non-
    serializable inputs — rare but don't crash on it).
    """
    try:
        canonical = json.dumps(input_data or {}, sort_keys=True, default=str)
    except (TypeError, ValueError):
        canonical = str(input_data)
    digest = hashlib.sha1(canonical.encode("utf-8"), usedforsecurity=False).hexdigest()
    return (agent_name, digest)


def check_cycle(
    state: DispatchRunState,
    dispatcher_name: str,
    new_fingerprint: tuple[str, str],
) -> str | None:
    """Walk the ancestor chain from `dispatcher_name` upward, looking for
    an ancestor whose fingerprint matches `new_fingerprint`.

    Returns the ancestor's name if a cycle is detected, None otherwise.
    An ancestor is found via `state.parents` (nodes added through dispatch)
    or the chain ends when it hits a node originally in the workflow
    (no entry in `state.parents`).

    Also checks the dispatcher itself as the first ancestor — if agent A
    produces a dispatch that contains A with the same inputs, that's a
    one-step cycle.
    """
    if dispatcher_name in state.fingerprints:
        if state.fingerprints[dispatcher_name] == new_fingerprint:
            return dispatcher_name

    cursor = state.parents.get(dispatcher_name)
    visited: set[str] = set()
    while cursor is not None:
        if cursor in visited:
            # Shouldn't happen given how we insert, but be defensive
            return cursor
        visited.add(cursor)
        if state.fingerprints.get(cursor) == new_fingerprint:
            return cursor
        cursor = state.parents.get(cursor)
    return None
