"""Stage 2's task text for the model (existing_read), and the revision text (existing_revise). Model-free.

task() lays out, from what the host's capture wrote and stage 1's requirements: the product's job, the
requirements, the screens, every capture with its measures (a "!" after each value on the problem side of its
line, existing_measures.PROBLEM_WHEN), each screen state's visible text, and the per-width totals. The model
sees the contact sheet beside it; the words and numbers it may cite are all here.
The registry's existing tools for the stage close the text (tools_registry.task_section).
revise() adds the previous draft and the check's problems for the one revision.
"""
from __future__ import annotations

import json
from typing import Any

from . import existing_measures, model_step

TEXT_CHARS = 1500           # visible text per screen state (the sheet width's capture), in page order
SHOWN_PROBLEMS = 60


def _value(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False)


def _measure_line(cap: dict) -> str:
    parts = []
    for key, value in cap["measures"].items():
        if value is None or value == []:
            continue
        mark = "!" if existing_measures.shows_problem(key, value, cap) else ""
        parts.append(f"{key}={_value(value)}{mark}")
    return "  " + " ".join(parts)


def _text(runs: list[str], limit: int = TEXT_CHARS) -> str:
    out, used = [], 0
    for run in runs:
        if used + len(run) > limit:
            out.append("...")
            break
        out.append(run)
        used += len(run) + 3
    return " | ".join(out)


def task(audit: dict, texts: dict, app: dict, requirements: dict, tools: list[str] | None = None) -> str:
    lines = [f"# {app['name']} as it is today", "", f"Product's job: {app['job']}", "",
             "## Requirements (stage 1: the owner's words, verbatim, and what each means)"]
    for r in requirements.get("items", []):
        lines.append(f"{r['id']} ({r['kind']}): \"{r['owner_words']}\"" + (f" -> {r['means']}" if r.get("means") else "")
                     + (f" (maps to: {', '.join(r['maps_to'])})" if r.get("maps_to") else ""))
    lines += ["", "## Screens (id: name; states: what each shows; widths)"]
    for s in app["screens"]:
        states = "; ".join(f"{st} = {spec['what']} ({', '.join(str(w) for w in spec['widths'])})"
                           for st, spec in s["states"].items())
        lines.append(f"{s['id']}: {s['name']}; {states}")
    sizes = ", ".join(f"{w}x{s['height']}{' phone' if s['phone'] else ''}" for w, s in app["sizes"].items())
    lines += ["", f"Sizes: {sizes}. The image is the contact sheet of every capture at {app['sheet_width']} px, "
              "first view only, each tile labelled with its capture id.", "",
              "## Measure lines (a value on the problem side of its line gets a \"!\")"]
    for key, (words, _) in existing_measures.PROBLEM_WHEN.items():
        lines.append(f"{key}: problem when {words}")
    lines.append("<region>_screens_down: problem when 1 or more (the region starts below the first screen); "
                 "regions: the app's key parts, e.g. attention_list")
    lines += ["Context only (no line): " + ", ".join(k for k in audit["screens"][0]["measures"]
                                                    if existing_measures.rule(k) is None)]
    for key, note in existing_measures.NOTES.items():
        lines.append(f"note {key}: {note}")
    lines += ["", "## Captures and their measures"]
    for cap in audit["screens"]:
        lines.append(f"{cap['id']} ({cap.get('name', cap['id'])}, {cap['state']}: {cap.get('what', '')}; "
                     f"{cap['width']}x{cap.get('height', '?')})")
        lines.append(_measure_line(cap))
    lines += ["", "## Totals per width (captures on the problem side, of all captures at that width)"]
    for key, t in sorted(audit.get("totals", {}).items()):
        if t["value"]:
            lines.append(f"{key}: {t['value']} of {t['of']}")
    lines += ["", f"## Visible text of each screen state (its {app['sheet_width']} px capture, all text in page "
              "order, ' | ' between runs; [first view] marks the runs above the fold)"]
    seen = set()
    for cap in audit["screens"]:
        key = (cap.get("screen"), cap["state"])
        if key in seen or cap["width"] != app["sheet_width"]:
            continue
        seen.add(key)
        t = texts.get(cap["id"], {})
        lines.append(f"{cap['id']} [first view]: {_text(t.get('first_view', []), 600)}")
        lines.append(f"{cap['id']} [all]: {_text(t.get('all', []))}")
    lines += tools or []
    lines += ["", "Write the journeys and problems now, as one JSON object, exactly the shape you were given."]
    return "\n".join(lines) + "\n"


def revise(task_text: str, draft_text: str, problems: list[dict]) -> str:
    return model_step.revise_text(
        task_text, draft_text, problems,
        "Fix every one: correct a ref's value to the one the text gives, quote visible text exactly, cite a "
        "measure with a \"!\" or drop a problem no measure or text supports, drop numbers no ref shows.",
        SHOWN_PROBLEMS)
