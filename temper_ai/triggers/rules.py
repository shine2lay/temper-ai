"""Trigger rules: which event starts which workflow, with which inputs.

One YAML file per rule in ``configs/triggers/`` (and the gitignored
``configs/triggers/local/`` for rules that belong to one installation)::

    trigger:
      name: linear_work
      source: linear
      on:                       # what the source matches; see triggers.linear
        type: Issue
        label_added: temper
      workflow: linear_work
      inputs:                   # workflow input -> template over the event
        issue_id: "{{ data.id }}"
        identifier: "{{ data.identifier }}"

Rules are read from disk on every delivery, not cached, so adding or
changing one takes effect on the next event without a restart. The files
are small and deliveries are rare; the cost is a directory listing.

Templates are rendered in a sandbox with every field required: a rule that
names a field the event does not have is an error in the log, not a
workflow started with a blank input. A null field renders as an empty
string. The event's own text (an issue title, say) is data here and is
never evaluated as a template.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from jinja2 import BaseLoader, StrictUndefined
from jinja2.sandbox import SandboxedEnvironment

logger = logging.getLogger(__name__)

TRIGGERS_DIR = "triggers"


class TriggerConfigError(ValueError):
    """A rule file that cannot be used as written."""


@dataclass(frozen=True)
class Trigger:
    name: str
    source: str
    on: dict[str, Any]
    workflow: str
    inputs: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    # Skip events caused by temper itself (its own comment, its own edit), so
    # a workflow that writes back can never trigger itself in a loop.
    ignore_self: bool = True
    path: str = ""


def default_config_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "configs"


def parse_trigger(raw: Any, path: str = "") -> Trigger:
    """Build a Trigger from a parsed YAML document, or say what is wrong with it."""
    body = raw.get("trigger", raw) if isinstance(raw, dict) else None
    if not isinstance(body, dict):
        raise TriggerConfigError("expected a mapping under 'trigger:'")
    for key in ("name", "source", "workflow"):
        if not str(body.get(key) or "").strip():
            raise TriggerConfigError(f"'{key}' is required")
    on = body.get("on")
    # YAML 1.1 reads a bare `on:` key as the boolean True.
    if on is None and True in body:
        on = body[True]
    if not isinstance(on, dict) or not on:
        raise TriggerConfigError("'on' must be a non-empty mapping")
    inputs = body.get("inputs") or {}
    if not isinstance(inputs, dict):
        raise TriggerConfigError("'inputs' must be a mapping of input name to template")
    env = _env()
    for key, template in inputs.items():
        if not isinstance(template, str):
            raise TriggerConfigError(f"input '{key}' must be a template string")
        try:
            env.parse(template)
        except Exception as exc:  # jinja2.TemplateSyntaxError and friends
            raise TriggerConfigError(f"input '{key}': {exc}") from exc
    return Trigger(
        name=str(body["name"]).strip(),
        source=str(body["source"]).strip().lower(),
        on=dict(on),
        workflow=str(body["workflow"]).strip(),
        inputs={str(k): v for k, v in inputs.items()},
        enabled=bool(body.get("enabled", True)),
        ignore_self=bool(body.get("ignore_self", True)),
        path=path,
    )


def load_triggers(config_dir: str | Path | None = None, source: str | None = None) -> list[Trigger]:
    """Every usable rule, tracked files first; the first rule to claim a name keeps it.

    A file that cannot be parsed is logged and skipped: one bad rule must not
    stop the others from firing.
    """
    root = Path(config_dir) if config_dir else default_config_dir()
    folder = root / TRIGGERS_DIR
    if not folder.is_dir():
        return []
    files = sorted(folder.glob("*.yaml")) + sorted((folder / "local").glob("*.yaml"))
    triggers: list[Trigger] = []
    seen: set[str] = set()
    for path in files:
        try:
            with open(path, encoding="utf-8") as handle:
                trigger = parse_trigger(yaml.safe_load(handle), str(path))
        except Exception as exc:  # noqa: BLE001 - one bad file must not hide the rest
            logger.warning("Skipped trigger %s: %s", path, exc)
            continue
        if trigger.name in seen:
            logger.warning("Skipped trigger %s: the name '%s' is already taken", path, trigger.name)
            continue
        seen.add(trigger.name)
        if source is None or trigger.source == source:
            triggers.append(trigger)
    return triggers


def _finalize(value: Any) -> Any:
    return "" if value is None else value


def _env() -> SandboxedEnvironment:
    return SandboxedEnvironment(
        loader=BaseLoader(),
        undefined=StrictUndefined,
        finalize=_finalize,
        autoescape=False,
    )


def render_inputs(trigger: Trigger, event: dict[str, Any]) -> dict[str, str]:
    """The workflow inputs for one event; raises if a template names a missing field."""
    env = _env()
    inputs: dict[str, str] = {}
    for key, template in trigger.inputs.items():
        try:
            inputs[key] = env.from_string(template).render(**event)
        except Exception as exc:  # noqa: BLE001 - UndefinedError, TypeError from filters
            raise TriggerConfigError(f"trigger '{trigger.name}', input '{key}': {exc}") from exc
    return inputs
