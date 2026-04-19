"""Template expansion for workflow DAGs.

At workflow-load time, expands any node with `type: template` into N
concrete nodes by cloning the template body N times and rendering string
fields through Jinja with `{i: <loop_var>, input: <inputs>}` in scope.

Designed for the "user picked N posts" use case: N is known at POST time
(via inputs), but not baked into the YAML. Not for runtime-dynamic spawning
where N depends on upstream node output — that needs the executor to
grow the DAG mid-run, which is out of scope here.

Usage:

    raw_workflow = yaml.safe_load(text)      # plain dict form
    inputs = {...}                            # POST body's `inputs` field
    raw_workflow = expand_templates(raw_workflow, inputs)
    config = WorkflowConfig.from_dict(raw_workflow)

Template node shape:

    - name: lanes           # optional label — discarded after expansion
      type: template
      for_each: input.knobs.post_count   # int literal or `input.*` path
      as: i                 # loop var name in Jinja context (default: "i")
      template:
        - name: "drafter_{{ i }}"
          type: agent
          agent: post_drafter
          depends_on: [planner]
          input_map:
            post_brief: "planner.structured.post_{{ i }}"
        - ...

After expansion the `lanes` node disappears and is replaced by
`for_each × len(template)` concrete nodes.
"""

from __future__ import annotations

import copy
import logging
from typing import Any

import jinja2

logger = logging.getLogger(__name__)


class TemplateExpansionError(Exception):
    """Raised when a template node can't be expanded (bad for_each, etc.)."""


# Isolated Jinja environment. `autoescape=False` because we're rendering into
# YAML strings, not HTML; `undefined=StrictUndefined` so missing variables
# raise at render time rather than silently producing empty strings.
_JINJA_ENV = jinja2.Environment(
    autoescape=False,
    undefined=jinja2.StrictUndefined,
    keep_trailing_newline=True,
)


def _resolve_for_each(spec: Any, inputs: dict[str, Any]) -> int:
    """Resolve a template's `for_each` to a concrete non-negative int count.

    Accepts:
      - int literal:    for_each: 3
      - int-as-string:  for_each: "3"
      - input path:     for_each: input.knobs.post_count
    """
    if isinstance(spec, int):
        if spec < 0:
            raise TemplateExpansionError(f"for_each must be non-negative, got {spec}")
        return spec
    if not isinstance(spec, str):
        raise TemplateExpansionError(
            f"for_each must be int or input-path string, got {type(spec).__name__}"
        )

    stripped = spec.strip()
    if stripped.isdigit():
        return int(stripped)

    parts = stripped.split(".")
    if parts[0] != "input":
        raise TemplateExpansionError(
            f"for_each path must start with 'input.', got {spec!r}"
        )

    cursor: Any = inputs
    for key in parts[1:]:
        if not isinstance(cursor, dict) or key not in cursor:
            raise TemplateExpansionError(
                f"for_each path {spec!r} not found in inputs"
            )
        cursor = cursor[key]

    if isinstance(cursor, bool):
        raise TemplateExpansionError(
            f"for_each path {spec!r} resolved to bool; expected int"
        )
    if isinstance(cursor, int):
        if cursor < 0:
            raise TemplateExpansionError(
                f"for_each {spec!r} resolved to negative int {cursor}"
            )
        return cursor
    if isinstance(cursor, str) and cursor.strip().isdigit():
        return int(cursor.strip())

    raise TemplateExpansionError(
        f"for_each path {spec!r} resolved to {cursor!r} (not an int)"
    )


def _render_strings(value: Any, ctx: dict[str, Any]) -> Any:
    """Walk a YAML-derived structure, rendering every string leaf through Jinja.

    Non-string leaves (int, float, bool, None) pass through untouched.
    Dicts and lists are traversed recursively and returned as fresh objects.

    If a rendered string starts with `[`/`{` and parses as valid JSON, it's
    returned as the parsed list/dict rather than the raw string. This lets
    dispatch YAML use `depends_on: "{{ structured.names | tojson }}"` to
    produce a proper list from Jinja (rather than a string that NodeConfig
    would reject). Failed JSON parses fall back to the raw string.
    """
    if isinstance(value, str):
        # Fast path: no Jinja markers means no render needed.
        if "{{" not in value and "{%" not in value:
            return value
        try:
            template = _JINJA_ENV.from_string(value)
            rendered = template.render(**ctx)
        except jinja2.TemplateError as exc:
            raise TemplateExpansionError(
                f"Jinja error rendering {value!r}: {exc}"
            ) from exc
        # If the render produced what looks like JSON for a list or dict,
        # coerce it. Opt-in by leading char so scalar Jinja (agent names,
        # sentences) keeps its str type.
        stripped = rendered.lstrip()
        if stripped and stripped[0] in ("[", "{"):
            import json
            try:
                return json.loads(rendered)
            except (json.JSONDecodeError, ValueError):
                pass
        return rendered
    if isinstance(value, dict):
        return {k: _render_strings(v, ctx) for k, v in value.items()}
    if isinstance(value, list):
        return [_render_strings(v, ctx) for v in value]
    return value


def _expand_one_template(
    template_node: dict[str, Any], inputs: dict[str, Any]
) -> list[dict[str, Any]]:
    """Expand a single `type: template` node into its concrete children."""
    body = template_node.get("template")
    if not isinstance(body, list) or not body:
        raise TemplateExpansionError(
            f"template node {template_node.get('name', '<unnamed>')!r} "
            "has empty or missing `template` list"
        )

    for_each_spec = template_node.get("for_each")
    if for_each_spec is None:
        raise TemplateExpansionError(
            f"template node {template_node.get('name', '<unnamed>')!r} "
            "is missing `for_each`"
        )
    n_times = _resolve_for_each(for_each_spec, inputs)

    loop_var = template_node.get("as", "i")
    if not isinstance(loop_var, str) or not loop_var.isidentifier():
        raise TemplateExpansionError(
            f"template `as` must be a valid identifier, got {loop_var!r}"
        )

    expanded: list[dict[str, Any]] = []
    for i in range(n_times):
        ctx = {"input": inputs, loop_var: i}
        for item in body:
            # Deep-copy first so Jinja never mutates the source template, then
            # render every string leaf under this loop's context.
            cloned = copy.deepcopy(item)
            rendered = _render_strings(cloned, ctx)
            expanded.append(rendered)
    return expanded


def expand_templates(
    raw_workflow: dict[str, Any], inputs: dict[str, Any] | None
) -> dict[str, Any]:
    """Expand template nodes in a raw workflow dict, returning a new dict.

    Accepts both shapes the loader may pass:
      - wrapped:   {"workflow": {"nodes": [...], ...}}
      - unwrapped: {"nodes": [...], ...}
    and preserves the input shape in the return value.

    - Non-templated workflows pass through unchanged.
    - Workflows with template nodes require inputs; passing inputs=None when
      a template exists raises TemplateExpansionError.
    - Nested `type: stage` with explicit `nodes:` lists are also walked, so
      templates can live inside a stage.
    """
    wrapped = isinstance(raw_workflow.get("workflow"), dict)
    wf = raw_workflow["workflow"] if wrapped else raw_workflow

    nodes = wf.get("nodes") if isinstance(wf, dict) else None
    if not isinstance(nodes, list):
        return raw_workflow

    def _walk(node_list: list[Any]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for node in node_list:
            if not isinstance(node, dict):
                out.append(node)
                continue
            if node.get("type") == "template":
                if inputs is None:
                    raise TemplateExpansionError(
                        "template node found but no inputs provided to loader"
                    )
                out.extend(_expand_one_template(node, inputs))
                continue
            # Recurse into stage-with-explicit-nodes
            if isinstance(node.get("nodes"), list):
                node = {**node, "nodes": _walk(node["nodes"])}
            out.append(node)
        return out

    new_nodes = _walk(nodes)
    if new_nodes is nodes:
        return raw_workflow   # Nothing changed — preserve identity

    new_wf = {**wf, "nodes": new_nodes}
    if wrapped:
        return {**raw_workflow, "workflow": new_wf}
    return new_wf


__all__ = ["expand_templates", "TemplateExpansionError"]
