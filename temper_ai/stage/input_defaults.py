"""A declared input's ``default:``, filled in wherever a run's inputs are accepted.

    inputs:
      assets_dir:
        type: string
        default: /app/configs/agents/pmf_evidence_assets

An input the run leaves out, sends as null or sends as empty text gets its default. Any other value
is kept exactly as given: a list, an object, 0, false. An input with no default (or with
``default: null``) is left as the run sent it, and a required input that has a default always
counts as given: the Slack picker has long read both the same way (integrations/slack/picker.py).

The inputs are filled once at each place they are accepted, so every way a run starts sees the same
values:

* the run-start route (routes._start_run): the dashboard, the API, Slack, Telegram, the Linear,
  Notion and GitHub hooks, schedules and MCP all start runs there, and the run's saved inputs then
  show what was used;
* the runner (runner/execute.py): worker runs, resumes, forks, and runs queued before this existed;
* the loader (stage/loader.py), for what reads a run's inputs while its workflow loads: template
  expansion and the strategies' run-start checks (the Pi team's goal);
* a nested workflow's or stage's input gate (stage/stage_node.py), for the inputs it declares.

Filling twice changes nothing, because a filled value is no longer missing, so any later reader of
a run's inputs (a step that checks them again on a resume or a fork) can call
``fill_input_defaults`` itself and get the same answer.
"""

from __future__ import annotations

import copy
from typing import Any


def is_missing(value: Any) -> bool:
    """Left out, null or empty text: what a declared default stands in for."""
    return value is None or (isinstance(value, str) and value == "")


def declared_default(spec: Any) -> tuple[bool, Any]:
    """``(True, default)`` when an input's declaration gives a default; ``(False, None)`` when it
    gives none (``default: null`` included) or is not a declaration at all (a stage's
    ``inputs: {goal: goal_text}`` names a source, not a schema)."""
    if not isinstance(spec, dict):
        return False, None
    default = spec.get("default")
    if default is None:
        return False, None
    return True, default


def with_default(spec: Any, value: Any) -> Any:
    """``value``, or a copy of the declared default when the value is missing and ``spec`` (one
    input's declaration) gives a default."""
    has_default, default = declared_default(spec)
    if has_default and is_missing(value):
        return copy.deepcopy(default)
    return value


def fill_input_defaults(declared: Any, inputs: dict[str, Any] | None) -> dict[str, Any]:
    """A copy of ``inputs`` with each declared default in place of a missing value.

    ``declared`` is the workflow's (or stage's) ``inputs:`` mapping of name to declaration; any
    other shape declares no defaults. Inputs that are not declared pass through untouched, and an
    input with no default stays exactly as given (left out stays left out).
    """
    filled = dict(inputs or {})
    if not isinstance(declared, dict):
        return filled
    for name, spec in declared.items():
        value = with_default(spec, filled.get(name))
        if value is not None or name in filled:
            filled[name] = value
    return filled


__all__ = ["declared_default", "fill_input_defaults", "is_missing", "with_default"]
