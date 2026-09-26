"""@temper in plain words: pick a workflow and its inputs, to propose.

The search narrows the field; an LLM (the ``slack_pick`` workflow) reads
the request against the best matches' descriptions and every workflow's
one-line summary, and answers with a workflow, inputs, and a question when
something it needs is missing. Nothing here starts the picked workflow: the
person confirms first.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

from temper_ai.config.search import first_line
from temper_ai.integrations.slack.ops import OpsError, TemperOps

PICK_WORKFLOW = "slack_pick"
PICK_NODE = "pick"
PICK_TIMEOUT_S = 180.0
POLL_S = 2.0
TOP = 8
END = ("completed", "failed", "cancelled", "interrupted")


@dataclass
class Pick:
    workflow: str | None
    inputs: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    question: str = ""
    problems: list[str] = field(default_factory=list)
    execution_id: str = ""


def _spec(entry: dict[str, Any]) -> str:
    lines = [f"## {entry['name']}", (entry.get("description") or "(no description)").strip()]
    for name, spec in (entry.get("inputs") or {}).items():
        spec = spec or {}
        bits = [str(spec.get("type") or "string"), "required" if spec.get("required") else "optional"]
        desc = f" — {spec['description']}" if spec.get("description") else ""
        lines.append(f"- input `{name}` ({', '.join(bits)}){desc}")
    return "\n".join(lines)


def candidates_for(ops: Any, catalog: list[dict[str, Any]], request: str,
                   conversation: str = "") -> list[dict[str, Any]]:
    """The workflows whose full description and inputs the picker reads.

    A reply in a thread often says little on its own ("<a PR link>"), so the
    thread counts too: every workflow it already named comes first (the one
    temper proposed a message ago), then the best matches for the reply, then
    for the whole thread. Without the thread, the picker named code_review
    from memory, didn't see its inputs, and asked again instead of offering
    Start (2026-09-26).
    """
    found = list(ops.search(request, limit=TOP).get("results") or [])
    if conversation:
        named = [e for e in catalog
                 if re.search(rf"(?<![\w-]){re.escape(e['name'])}(?![\w-])", conversation)]
        thread = ops.search(f"{conversation}\n{request}", limit=TOP).get("results") or []
        found = named + found + list(thread)
    seen: set[str] = set()
    out = []
    for e in found:
        if e.get("name") != PICK_WORKFLOW and e.get("name") not in seen:
            seen.add(e["name"])
            out.append(e)
    return out[:TOP]


def wait_for(ops: Any, execution_id: str, timeout_s: float, poll_s: float = POLL_S,
             sleep: Any = time.sleep) -> dict[str, Any]:
    """Poll a run until it ends or ``timeout_s`` passes; its last summary."""
    deadline = time.monotonic() + timeout_s
    while True:
        summary = ops.summary(execution_id)
        if str(summary.get("status") or "running") in END or time.monotonic() >= deadline:
            return summary
        sleep(poll_s)


def check(pick: Pick, catalog: list[dict[str, Any]]) -> Pick:
    """Hold the pick to what the workflow really takes."""
    if not pick.workflow:
        return pick
    entry = next((e for e in catalog if e.get("name") == pick.workflow), None)
    if entry is None:
        pick.problems.append(f"there is no workflow `{pick.workflow}`")
        pick.workflow = None
        return pick
    declared = entry.get("inputs") or {}
    if declared:
        unknown = [k for k in pick.inputs if k not in declared]
        for k in unknown:
            pick.inputs.pop(k)
        missing = [k for k, s in declared.items()
                   if (s or {}).get("required") and (s or {}).get("default") is None
                   and pick.inputs.get(k) in (None, "", [], {})]
        if missing and not pick.question:
            pick.question = "What should I use for " + ", ".join(f"`{m}`" for m in missing) + "?"
        if missing:
            pick.problems.append("missing " + ", ".join(f"`{m}`" for m in missing))
    return pick


class Picker:
    def __init__(self, ops: TemperOps | None = None, timeout_s: float = PICK_TIMEOUT_S,
                 poll_s: float = POLL_S, sleep: Any = time.sleep) -> None:
        self.ops = ops or TemperOps()
        self.timeout_s = timeout_s
        self.poll_s = poll_s
        self._sleep = sleep

    def pick(self, request: str, conversation: str = "") -> Pick:
        catalog = [e for e in self.ops.catalog() if e.get("name") != PICK_WORKFLOW]
        if not catalog:
            raise OpsError("temper has no workflows to pick from.")
        found = candidates_for(self.ops, catalog, request, conversation)
        inputs = {
            "request": request,
            "conversation": conversation,
            "candidates": "\n\n".join(_spec(e) for e in found) or "(no workflow matched their words)",
            "catalog": "\n".join(f"- {e['name']}: {first_line(e.get('description') or '', 120) or '(no description)'}"
                                 for e in catalog),
        }
        execution_id = self.ops.start(PICK_WORKFLOW, inputs)
        summary = wait_for(self.ops, execution_id, self.timeout_s, self.poll_s, self._sleep)
        status = str(summary.get("status") or "running")
        if status != "completed":
            raise OpsError(f"I couldn't work out a workflow (the pick run {execution_id[:8]} is {status}).")
        out = self.ops.structured_output(execution_id, PICK_NODE)
        if not isinstance(out, dict):
            raise OpsError(f"I couldn't read my own pick (run {execution_id[:8]} gave no JSON answer).")
        raw = out.get("inputs")
        raw_inputs: dict[str, Any] = raw if isinstance(raw, dict) else {}
        pick = Pick(
            workflow=(str(out["workflow"]).strip() or None) if out.get("workflow") else None,
            inputs=dict(raw_inputs),
            reason=str(out.get("reason") or "").strip(),
            question=str(out.get("question") or "").strip(),
            execution_id=execution_id,
        )
        return check(pick, catalog)


def conversation_text(messages: list[dict[str, Any]], bot_user: str, names: dict[str, str] | None = None,
                      limit: int = 20) -> str:
    """Earlier thread messages as "name: text" lines, oldest first."""
    lines = []
    for m in messages[-limit:]:
        who = "temper" if (m.get("user") == bot_user or m.get("bot_id")) else (names or {}).get(
            str(m.get("user")), str(m.get("user") or "someone"))
        text = str(m.get("text") or "").strip()
        if text:
            lines.append(f"{who}: {text[:1000]}")
    return "\n".join(lines)


def pick_value(pick: Pick, requester: str) -> str:
    return json.dumps({"workflow": pick.workflow, "inputs": pick.inputs, "by": requester}, separators=(",", ":"))
