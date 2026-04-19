"""Declarative dispatch — agent-config driven DAG mutation (tier 1).

After an agent completes, the engine checks whether the agent's config has a
`dispatch:` block. If so, this module renders that block (Jinja over the
agent's output and input) into a list of concrete DAG operations — primarily
`add` to insert new nodes into the running graph.

Tier 1 scope (this module):
  - op: add   — insert one or more nodes into the pending DAG
  - op: remove — remove a pending node by name

Out of scope here:
  - Tool-call dispatch (tier 2 — imperative add_node / remove_node)
  - Safety-cap enforcement (executor concern, not renderer concern)
  - Engine-side mutation of batches (executor concern)
  - Cycle/conflict detection (validator concern)

This module is purely the renderer. Given an agent config + its run-time
result, it returns a list of resolved operations for the executor to apply.

Config shape in agent YAML:

    agent:
      name: day_allocator
      type: llm
      system_prompt: "..."
      dispatch:
        - op: add
          for_each: output.structured.cities   # resolves to a list
          as: item                              # loop-var name (default: "item")
          node:                                  # single node per iteration
            name: "{{ item.city }}_research"
            type: stage
            strategy: parallel
            agents: [activity_researcher]
            input_map:
              city: "{{ item.city }}"

        - op: add
          node:                                 # no for_each — single op
            name: "summary"
            type: agent
            agent: summarizer
            depends_on: [day_allocator]

        - op: remove
          target: placeholder_node              # target can itself be Jinja

Jinja render scope:
  input       — the input_data the agent received (dict)
  output      — the agent's text output (str)
  structured  — the agent's structured_output (dict or None)
  <as>        — loop variable during for_each iteration (default name: "item")
  i           — integer loop index during for_each iteration
"""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from typing import Any

from temper_ai.stage.template_expansion import (
    TemplateExpansionError,
    _render_strings,
)

logger = logging.getLogger(__name__)


class DispatchRenderError(Exception):
    """Raised when an agent's dispatch block can't be rendered.

    The failure is the agent's (or the config author's) — surfaces as a normal
    runtime error so the failing node is visible and the run doesn't silently
    swallow a bad dispatch.
    """


@dataclass
class DispatchOp:
    """A single resolved DAG operation — ready for the executor to apply."""

    op: str                                   # "add" | "remove"
    node: dict[str, Any] | None = None        # for op=add (single-node dispatch)
    nodes: list[dict[str, Any]] = field(default_factory=list)  # for op=add (subgraph)
    target: str | None = None                 # for op=remove

    def all_added_nodes(self) -> list[dict[str, Any]]:
        """Return the node dicts added by this op. Empty list for remove ops."""
        if self.op != "add":
            return []
        if self.node is not None:
            return [self.node]
        return list(self.nodes)


def render_dispatch(
    agent_config: dict[str, Any],
    *,
    agent_output: str = "",
    agent_structured: dict[str, Any] | None = None,
    agent_input_data: dict[str, Any] | None = None,
) -> list[DispatchOp]:
    """Render an agent's dispatch block into concrete operations.

    Returns [] when the agent has no dispatch block (the common case).
    Raises DispatchRenderError for malformed blocks or Jinja errors.
    """
    raw_ops = agent_config.get("dispatch")
    if not raw_ops:
        return []
    if not isinstance(raw_ops, list):
        raise DispatchRenderError(
            f"`dispatch:` must be a list, got {type(raw_ops).__name__}"
        )

    base_scope: dict[str, Any] = {
        "input": agent_input_data or {},
        "output": agent_output,
        "structured": agent_structured or {},
    }

    resolved: list[DispatchOp] = []
    for op_idx, raw_op in enumerate(raw_ops):
        if not isinstance(raw_op, dict):
            raise DispatchRenderError(
                f"dispatch[{op_idx}] must be a dict, got {type(raw_op).__name__}"
            )
        resolved.extend(_render_one_op(raw_op, op_idx, base_scope))
    return resolved


def _render_one_op(
    raw_op: dict[str, Any], op_idx: int, base_scope: dict[str, Any]
) -> list[DispatchOp]:
    """Render a single op entry. for_each expands to N ops, no for_each = 1 op."""
    op_name = raw_op.get("op")
    if op_name not in ("add", "remove"):
        raise DispatchRenderError(
            f"dispatch[{op_idx}].op must be 'add' or 'remove', got {op_name!r}"
        )

    for_each_spec = raw_op.get("for_each")
    if for_each_spec is None:
        return [_render_single_op(raw_op, op_name, base_scope, op_idx)]

    loop_items = _resolve_for_each_list(for_each_spec, base_scope, op_idx)
    loop_var = raw_op.get("as", "item")
    if not isinstance(loop_var, str) or not loop_var.isidentifier():
        raise DispatchRenderError(
            f"dispatch[{op_idx}].as must be a valid identifier, got {loop_var!r}"
        )

    out: list[DispatchOp] = []
    for i, item in enumerate(loop_items):
        scope = {**base_scope, loop_var: item, "i": i}
        out.append(_render_single_op(raw_op, op_name, scope, op_idx, loop_idx=i))
    return out


def _render_single_op(
    raw_op: dict[str, Any],
    op_name: str,
    scope: dict[str, Any],
    op_idx: int,
    loop_idx: int | None = None,
) -> DispatchOp:
    """Render one op against a given scope (either base or loop-iteration)."""
    if op_name == "remove":
        target_raw = raw_op.get("target")
        if not isinstance(target_raw, str) or not target_raw:
            raise DispatchRenderError(
                f"dispatch[{op_idx}].target must be a non-empty string"
            )
        target = _render_string_leaf(target_raw, scope, op_idx)
        return DispatchOp(op="remove", target=target)

    # op == "add" — must carry exactly one of `node` or `nodes`
    node_spec = raw_op.get("node")
    nodes_spec = raw_op.get("nodes")
    if (node_spec is None) == (nodes_spec is None):
        raise DispatchRenderError(
            f"dispatch[{op_idx}] with op=add must carry exactly one of "
            f"`node:` (single) or `nodes:` (list) — got both or neither"
        )

    if node_spec is not None:
        if not isinstance(node_spec, dict):
            raise DispatchRenderError(
                f"dispatch[{op_idx}].node must be a dict"
            )
        rendered = _deep_render(node_spec, scope, op_idx)
        _require_node_shape(rendered, op_idx, loop_idx)
        return DispatchOp(op="add", node=rendered)

    if not isinstance(nodes_spec, list) or not nodes_spec:
        raise DispatchRenderError(
            f"dispatch[{op_idx}].nodes must be a non-empty list"
        )
    rendered_list: list[dict[str, Any]] = []
    for n_idx, n in enumerate(nodes_spec):
        if not isinstance(n, dict):
            raise DispatchRenderError(
                f"dispatch[{op_idx}].nodes[{n_idx}] must be a dict"
            )
        rendered = _deep_render(n, scope, op_idx)
        _require_node_shape(rendered, op_idx, loop_idx)
        rendered_list.append(rendered)
    return DispatchOp(op="add", nodes=rendered_list)


def _deep_render(value: dict[str, Any], scope: dict[str, Any], op_idx: int) -> dict[str, Any]:
    """Deep-copy then render every string leaf through Jinja. Reuses the
    template_expansion substrate so behavior is identical to load-time `for_each`."""
    cloned = copy.deepcopy(value)
    try:
        return _render_strings(cloned, scope)
    except TemplateExpansionError as exc:
        raise DispatchRenderError(
            f"dispatch[{op_idx}] Jinja render failed: {exc}"
        ) from exc


def _render_string_leaf(value: str, scope: dict[str, Any], op_idx: int) -> str:
    """Render a single string through Jinja. Used for `target:` strings."""
    try:
        rendered = _render_strings(value, scope)
    except TemplateExpansionError as exc:
        raise DispatchRenderError(
            f"dispatch[{op_idx}] Jinja render failed: {exc}"
        ) from exc
    return str(rendered)


def _require_node_shape(node: dict[str, Any], op_idx: int, loop_idx: int | None) -> None:
    """Minimal structural check on a dispatched node dict.

    Engine-side validation (agent registry, input_map refs, cycles) happens
    in the executor when the node is actually added. Here we just catch the
    obvious "agent forgot the name field" case so errors are legible.
    """
    loc = f"dispatch[{op_idx}]" + (f" loop[{loop_idx}]" if loop_idx is not None else "")
    name = node.get("name")
    if not isinstance(name, str) or not name.strip():
        raise DispatchRenderError(f"{loc}: rendered node is missing `name`")
    if "type" not in node and "agent" not in node and "agents" not in node:
        # type=agent+agent=X or type=stage+agents=[...] — at least one signal required
        raise DispatchRenderError(
            f"{loc}: rendered node {name!r} has no `type`, `agent`, or `agents` field"
        )


def _resolve_for_each_list(
    spec: Any, scope: dict[str, Any], op_idx: int
) -> list[Any]:
    """Resolve a `for_each:` spec to a concrete list of items to iterate over.

    Accepts:
      - list literal:          for_each: [a, b, c]
      - scope path:            for_each: output.structured.cities
      - int literal (rare):    for_each: 3        → [0, 1, 2]
      - path to int (rare):    for_each: output.structured.count → range(N)
    """
    if isinstance(spec, list):
        return list(spec)

    if isinstance(spec, int):
        if spec < 0:
            raise DispatchRenderError(
                f"dispatch[{op_idx}].for_each int must be non-negative, got {spec}"
            )
        return list(range(spec))

    if not isinstance(spec, str):
        raise DispatchRenderError(
            f"dispatch[{op_idx}].for_each must be list, int, or scope path, "
            f"got {type(spec).__name__}"
        )

    # Scope-path form: output.structured.cities, input.briefs, etc.
    parts = spec.strip().split(".")
    if not parts or parts[0] not in scope:
        raise DispatchRenderError(
            f"dispatch[{op_idx}].for_each path {spec!r} must start with a valid "
            f"scope key: {sorted(scope.keys())}"
        )
    cursor: Any = scope[parts[0]]
    for key in parts[1:]:
        if isinstance(cursor, dict):
            if key not in cursor:
                raise DispatchRenderError(
                    f"dispatch[{op_idx}].for_each path {spec!r} not found"
                )
            cursor = cursor[key]
        elif isinstance(cursor, list):
            try:
                cursor = cursor[int(key)]
            except (ValueError, IndexError):
                raise DispatchRenderError(
                    f"dispatch[{op_idx}].for_each path {spec!r} "
                    f"bad index {key!r}"
                ) from None
        else:
            raise DispatchRenderError(
                f"dispatch[{op_idx}].for_each path {spec!r} "
                f"can't descend into {type(cursor).__name__}"
            )

    if isinstance(cursor, list):
        return list(cursor)
    if isinstance(cursor, bool):
        raise DispatchRenderError(
            f"dispatch[{op_idx}].for_each {spec!r} resolved to bool"
        )
    if isinstance(cursor, int):
        if cursor < 0:
            raise DispatchRenderError(
                f"dispatch[{op_idx}].for_each {spec!r} resolved to negative int"
            )
        return list(range(cursor))

    raise DispatchRenderError(
        f"dispatch[{op_idx}].for_each {spec!r} resolved to {type(cursor).__name__}; "
        f"expected list or int"
    )


__all__ = ["render_dispatch", "DispatchOp", "DispatchRenderError"]
