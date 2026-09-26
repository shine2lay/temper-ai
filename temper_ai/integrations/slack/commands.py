"""``/temper …``: the exact commands, parsed without an LLM.

    /temper ask <question>
    /temper run <workflow> key=value …
    /temper status [run id]
    /temper stop <run id>
    /temper list
    /temper search <words>
    /temper help

Values with spaces go in quotes. Values are strings here; the handler turns
them into what the workflow's input declares (a number, a list, …).
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from typing import Any

VERBS = ("ask", "run", "status", "stop", "list", "search", "help")
ALIASES = {"start": "run", "cancel": "stop", "ls": "list", "find": "search", "runs": "status", "?": "help"}

# Slack turns straight quotes into curly ones on some keyboards, and wraps
# links as <https://…|label>.
_QUOTES = str.maketrans({"\u201c": '"', "\u201d": '"', "\u2018": "'", "\u2019": "'"})
_LINK = re.compile(r"<((?:https?|mailto):[^|>]+)(?:\|[^>]*)?>")
_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")
RUN_ID = re.compile(r"^[0-9a-f][0-9a-f-]{3,35}$")


@dataclass
class Command:
    verb: str
    workflow: str = ""
    inputs: dict[str, str] = field(default_factory=dict)
    run_id: str = ""
    query: str = ""
    error: str = ""


def clean(text: str) -> str:
    return _LINK.sub(r"\1", (text or "").translate(_QUOTES)).strip()


def parse(text: str) -> Command:
    text = clean(text)
    if not text:
        return Command("help")
    # A question is prose: taken as typed, not split like key=value words
    # (an apostrophe would read as an unclosed quote).
    first = text.split(None, 1)
    if first[0].lower() == "ask":
        question = first[1].strip() if len(first) > 1 else ""
        if not question:
            return Command("ask", error="Ask what? e.g. `/temper ask can roamee export a trip?`")
        return Command("ask", query=question)
    try:
        words = shlex.split(text)
    except ValueError as exc:
        return Command("help", error=f"I couldn't read that: {exc} (a quote is not closed?)")
    head, rest = words[0].lower(), words[1:]
    verb = ALIASES.get(head, head)
    if verb not in VERBS:
        return Command("help", error=f"I don't know `{words[0]}`.", workflow=words[0])

    if verb == "help":
        return Command("help")
    if verb == "list":
        return Command("list", query=" ".join(rest))
    if verb == "search":
        if not rest:
            return Command("search", error="Search for what? e.g. `/temper search linear issue`")
        return Command("search", query=" ".join(rest))
    if verb == "status":
        if len(rest) > 1:
            return Command("status", error="`/temper status` takes at most one run id.")
        run_id = rest[0].lower() if rest else ""
        if run_id and not RUN_ID.match(run_id):
            return Command("status", error=f"`{rest[0]}` doesn't look like a run id.")
        return Command("status", run_id=run_id)
    if verb == "stop":
        if len(rest) != 1 or not RUN_ID.match(rest[0].lower()):
            return Command("stop", error="Which run? e.g. `/temper stop 3f2a9c1e`")
        return Command("stop", run_id=rest[0].lower())

    # run
    if not rest:
        return Command("run", error="Run which workflow? e.g. `/temper run trigger_probe note=hi`")
    workflow, pairs = rest[0], rest[1:]
    inputs: dict[str, str] = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not _KEY.match(key):
            return Command("run", workflow=workflow,
                           error=f"Inputs go as `key=value`; I got `{pair}`. Quote values with spaces.")
        if key in inputs:
            return Command("run", workflow=workflow, error=f"`{key}` is given twice.")
        inputs[key] = value
    return Command("run", workflow=workflow, inputs=inputs)


def coerce_inputs(raw: dict[str, str], declared: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], list[str]]:
    """Strings from the command line as the types the workflow declares.

    Returns the inputs and a list of problems; any problem means "don't
    start". A name the workflow does not declare is a problem (a typo would
    otherwise start a run without the input it meant), unless the workflow
    declares no inputs at all.
    """
    import json

    out: dict[str, Any] = {}
    problems: list[str] = []
    for key, value in raw.items():
        if declared and key not in declared:
            problems.append(f"`{key}` is not one of its inputs ({', '.join(f'`{k}`' for k in declared)})")
            continue
        kind = str((declared.get(key) or {}).get("type") or "string").lower()
        try:
            if kind in ("integer", "int"):
                out[key] = int(value)
            elif kind in ("number", "float"):
                out[key] = float(value)
            elif kind in ("boolean", "bool"):
                low = value.strip().lower()
                if low not in ("true", "false", "yes", "no", "1", "0"):
                    raise ValueError("expected true or false")
                out[key] = low in ("true", "yes", "1")
            elif kind in ("array", "list", "object", "dict", "json"):
                parsed = json.loads(value) if value.strip()[:1] in "[{" else None
                if parsed is None and kind in ("array", "list"):
                    parsed = [v.strip() for v in value.split(",") if v.strip()]
                if parsed is None:
                    raise ValueError("expected JSON")
                out[key] = parsed
            else:
                out[key] = value
        except (ValueError, json.JSONDecodeError) as exc:
            problems.append(f"`{key}` should be {kind}: {exc}")
    missing = [k for k, spec in declared.items() if (spec or {}).get("required") and k not in raw
               and (spec or {}).get("default") is None]
    if missing:
        problems.append("missing required input(s): " + ", ".join(f"`{m}`" for m in missing))
    return out, problems
