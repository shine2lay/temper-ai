"""Static validation for declarative `dispatch:` blocks.

Catches classes of bugs at workflow-load time that would otherwise only
surface at runtime when a dispatcher agent actually fires:

  - `dispatch:` not a list; an op not a dict
  - Unknown op name (must be 'add' or 'remove')
  - Missing / malformed `node` or `nodes` for op=add
  - Missing `target` for op=remove
  - Bad `for_each` shape (not a list, int, or scope-path string)
  - Added nodes missing `agent` / `agents` / `type`
  - Agent refs that don't resolve in the config store
  - `input_map` source nodes that don't exist in the parent DAG AND
    aren't siblings in the same dispatched subgraph — skipped when
    the source contains Jinja markers `{{ }}` since those only
    resolve at runtime against agent output

Out of scope (can't be validated statically):
  - Jinja template rendering — the agent's output isn't known yet
  - Dynamic agent refs computed via Jinja
  - Cap breaches — depend on runtime counts
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


_JINJA_RE = re.compile(r"\{\{|\{%")


def _has_jinja(value: Any) -> bool:
    """True if the string value contains Jinja markers and must be skipped
    by static validation — its final form is only knowable at render time."""
    return isinstance(value, str) and bool(_JINJA_RE.search(value))


def validate_dispatch_block(
    agent_name: str,
    agent_config: dict[str, Any],
    config_store: Any,
    known_node_names: set[str],
) -> list[str]:
    """Validate an agent's `dispatch:` block.

    Args:
        agent_name: Name of the agent whose config is being validated
            (used in error messages).
        agent_config: The agent's config dict.
        config_store: ConfigStore for looking up agent refs (may be None
            in tests — then agent-ref checks are skipped).
        known_node_names: Names of nodes currently in the DAG. Used to
            validate input_map source refs that don't contain Jinja.

    Returns:
        List of error strings. Empty list = all checks passed (or the
        block wasn't present).
    """
    raw_ops = agent_config.get("dispatch")
    if raw_ops is None:
        return []
    if not isinstance(raw_ops, list):
        return [
            f"agent '{agent_name}': `dispatch:` must be a list, "
            f"got {type(raw_ops).__name__}"
        ]

    errors: list[str] = []
    for i, op in enumerate(raw_ops):
        errors.extend(_validate_op(
            agent_name, i, op, config_store, known_node_names,
        ))
    return errors


def _validate_op(
    agent_name: str,
    op_idx: int,
    raw_op: Any,
    config_store: Any,
    known_node_names: set[str],
) -> list[str]:
    """Validate a single op entry in an agent's dispatch list."""
    loc = f"agent '{agent_name}' dispatch[{op_idx}]"
    if not isinstance(raw_op, dict):
        return [f"{loc} must be a dict, got {type(raw_op).__name__}"]

    errors: list[str] = []
    op_name = raw_op.get("op")
    if op_name not in ("add", "remove"):
        errors.append(
            f"{loc}: `op:` must be 'add' or 'remove', got {op_name!r}"
        )
        return errors  # no point checking further if op is unknown

    errors.extend(_validate_for_each(loc, raw_op.get("for_each")))

    if op_name == "add":
        errors.extend(_validate_add_op(
            loc, raw_op, config_store, known_node_names,
        ))
    else:  # remove
        errors.extend(_validate_remove_op(loc, raw_op))

    return errors


def _validate_for_each(loc: str, spec: Any) -> list[str]:
    """A `for_each` clause (when present) must be list, int, or scope-path str."""
    if spec is None:
        return []
    if isinstance(spec, list) or isinstance(spec, bool):
        # bool is a subclass of int — treat it as invalid rather than accepting
        if isinstance(spec, bool):
            return [f"{loc}: `for_each` must not be a bool"]
        return []
    if isinstance(spec, int):
        if spec < 0:
            return [f"{loc}: `for_each` int must be non-negative, got {spec}"]
        return []
    if isinstance(spec, str):
        if _has_jinja(spec):
            # Unusual but allowed — loop count rendered from Jinja
            return []
        parts = spec.split(".")
        if parts[0] not in ("input", "output", "structured"):
            return [
                f"{loc}: `for_each` string must start with 'input.', "
                f"'output.', or 'structured.' — got {spec!r}"
            ]
        return []
    return [
        f"{loc}: `for_each` must be list, int, or string path, "
        f"got {type(spec).__name__}"
    ]


def _validate_add_op(
    loc: str,
    raw_op: dict[str, Any],
    config_store: Any,
    known_node_names: set[str],
) -> list[str]:
    """Validate `op: add` — must have exactly one of `node:` or `nodes:`."""
    node_spec = raw_op.get("node")
    nodes_spec = raw_op.get("nodes")

    if (node_spec is None) == (nodes_spec is None):
        return [
            f"{loc} with op=add must carry exactly one of `node:` (single) "
            f"or `nodes:` (list)"
        ]

    # Collect child dicts into a list for uniform checking + build a local
    # known-names set so input_map refs within the subgraph can reference
    # sibling nodes that will be materialized together.
    if node_spec is not None:
        if not isinstance(node_spec, dict):
            return [f"{loc}: `node:` must be a dict"]
        children = [node_spec]
    else:
        if not isinstance(nodes_spec, list) or not nodes_spec:
            return [f"{loc}: `nodes:` must be a non-empty list"]
        non_dict = [
            j for j, n in enumerate(nodes_spec) if not isinstance(n, dict)
        ]
        if non_dict:
            return [f"{loc}: `nodes[{non_dict[0]}]` must be a dict"]
        children = list(nodes_spec)

    # Local subgraph names — siblings can depend_on each other, so include
    # them in the set we check input_map refs against.
    local_names: set[str] = set()
    for c in children:
        name = c.get("name")
        if isinstance(name, str) and name and not _has_jinja(name):
            local_names.add(name)
    merged_known = known_node_names | local_names

    errors: list[str] = []
    for j, child in enumerate(children):
        child_loc = f"{loc} child[{j}]" if node_spec is None else f"{loc} node"
        errors.extend(_validate_added_node(
            child_loc, child, config_store, merged_known,
        ))
    return errors


def _validate_added_node(
    loc: str,
    node: dict[str, Any],
    config_store: Any,
    known_node_names: set[str],
) -> list[str]:
    """Validate a single node dict inside an add op."""
    errors: list[str] = []

    name = node.get("name")
    if not isinstance(name, str) or not name.strip():
        errors.append(f"{loc}: `name` must be a non-empty string")

    node_type = node.get("type")
    agent_ref = node.get("agent")
    agents = node.get("agents")

    if node_type == "template":
        errors.append(
            f"{loc}: nested `type: template` inside a dispatch block is not "
            f"supported in v1 — use static workflow-level templates instead"
        )
    if node.get("loop_to"):
        errors.append(
            f"{loc}: `loop_to:` inside a dispatched node is not supported "
            f"in v1"
        )

    if not agent_ref and not agents and not node_type:
        errors.append(
            f"{loc}: needs `agent:`, `agents:`, or `type:` to specify what to run"
        )

    # Agent-ref resolution — skip if the ref is Jinja (will be rendered at
    # runtime) or if no config_store is available (test runs).
    if isinstance(agent_ref, str) and agent_ref and not _has_jinja(agent_ref):
        if config_store is not None and not _agent_ref_resolves(config_store, agent_ref):
            errors.append(
                f"{loc}: agent ref {agent_ref!r} not found in config store"
            )

    if isinstance(agents, list):
        for k, a in enumerate(agents):
            if isinstance(a, str) and a and not _has_jinja(a):
                if config_store is not None and not _agent_ref_resolves(config_store, a):
                    errors.append(
                        f"{loc}: agents[{k}] ref {a!r} not found in config store"
                    )

    # Validate input_map refs — only refs that don't contain Jinja and
    # that point to a node name (not a literal value we can't distinguish).
    input_map = node.get("input_map")
    if isinstance(input_map, dict):
        for key, source in input_map.items():
            if not isinstance(source, str) or _has_jinja(source):
                continue
            # A bare literal (no dots) is a literal value, not a node ref — skip.
            if "." not in source:
                continue
            source_node = source.split(".", 1)[0]
            if source_node in ("input", "workflow"):
                continue
            if source_node not in known_node_names:
                errors.append(
                    f"{loc}: input_map[{key!r}] references "
                    f"{source_node!r}.{source.split('.', 1)[1]} but no "
                    f"node {source_node!r} exists in the DAG or subgraph"
                )

    # depends_on refs — same rules as input_map, skip Jinja
    depends_on = node.get("depends_on")
    if isinstance(depends_on, list):
        for k, dep in enumerate(depends_on):
            if not isinstance(dep, str) or _has_jinja(dep):
                continue
            if dep not in known_node_names:
                errors.append(
                    f"{loc}: depends_on[{k}]={dep!r} but no such node exists"
                )

    return errors


def _validate_remove_op(loc: str, raw_op: dict[str, Any]) -> list[str]:
    """op: remove must carry a non-empty `target:` string."""
    target = raw_op.get("target")
    if not isinstance(target, str) or not target.strip():
        return [f"{loc}: op=remove requires a non-empty `target:` string"]
    return []


def _agent_ref_resolves(config_store: Any, ref: str) -> bool:
    """True if `ref` is registered as an agent in the config store.

    ConfigNotFoundError is the authoritative "not registered" signal.
    Any OTHER exception (DB transient, backend down) is treated as
    inconclusive — return True so a flaky store doesn't falsely fail
    validation. A genuinely missing agent surfaces at runtime in that
    case, which is the same failure mode we had before this check.
    """
    name = ref.split("/")[-1] if "/" in ref else ref
    try:
        from temper_ai.config.helpers import ConfigNotFoundError
    except ImportError:
        ConfigNotFoundError = None  # type: ignore[assignment,misc]
    try:
        return config_store.get(name, "agent") is not None
    except Exception as exc:  # noqa: BLE001
        if ConfigNotFoundError is not None and isinstance(exc, ConfigNotFoundError):
            return False
        # Also treat generic KeyError as "not registered" for easy mocking
        if isinstance(exc, KeyError):
            return False
        return True
