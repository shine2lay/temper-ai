"""Stage 3's task text for the model (ground_read), and the revision text (ground_revise). Model-free.

task() lays out the product's job and design-file status, then every source item by kind with the id the model
cites: the capability map's pages and API routes (grouped as the map groups them), the screens stage 2
captured with their states and the words each shows, stage 1's requirements, stage 2's journeys, and the lines of the product's knowledge
files. The rules and the reply's shape are in the agent's system prompt; the facts are all here.
Over a stored ground (step 4's delta) the items are only the unplaced and changed ones, and an "Already placed,
keep" section (ground_delta.placed_section) lists what the stored inventory holds. The registry's existing
tools for the stage close the text (tools_registry.task_section).
revise() adds the previous draft and the check's problems for the one revision.
"""
from __future__ import annotations

from itertools import groupby

from . import model_step

SHOWN_PROBLEMS = 80
TITLES = {"page": "Pages of the app (capability map)", "api": "API routes (capability map)",
          "screen": "Screens captured today (stage 2)",
          "seen": "Words each captured screen shows today (stage 2; the app's frame left out; carry what a "
                  "screen shows, its states and its actions into that screen)",
          "req": "Requirements (stage 1)",
          "journey": "Journeys (stage 2)", "note": "Knowledge files (cite each line where it names something a "
                                                   "screen shows, a state or an action; exclude a line that names "
                                                   "none, with the reason)"}
ORDER = ("page", "api", "screen", "seen", "req", "journey", "note")


def _lines(kind: str, entries: list[dict]) -> list[str]:
    out = []
    if kind in ("page", "api"):
        for group, members in groupby(entries, key=lambda i: i.get("group", "")):
            out.append(f"\n### {group}" if group else "")
            out += [f"- {i['id']}: {i['text']}" for i in members]
        return out
    if kind == "note":
        for name, members in groupby(entries, key=lambda i: i["id"].split("#")[0]):
            out.append(f"\n### {name.removeprefix('note:')}")
            out += [f"- {i['id']}: {i['text']}" for i in members]
        return out
    return [f"- {i['id']}: {i['text']}" for i in entries]


PLACED_TITLE = "Already placed, keep"


def task(app: dict, status: str, sources: list[dict], questions: list[dict], placed: list[str] | None = None,
         tools: list[str] | None = None) -> str:
    counts = {k: sum(1 for i in sources if i["kind"] == k) for k in ORDER}
    widths = ", ".join(str(w) for w in sorted((int(w) for w in app.get("sizes", {})), reverse=True))
    parts = [f"# Ground: everything the {app['name']} design must cover",
             "", f"Product: {app['name']} ({app['product']}). {app.get('job', '')}",
             f"Design files: {status} (from the design-file registry; not yours to change).",
             f"Widths every screen is designed at: {widths}.",
             "", f"Sources: {counts['page']} pages, {counts['api']} API routes, {counts['screen']} captured screens, "
                 f"{counts['req']} requirements, {counts['journey']} journeys, {counts['note']} knowledge lines. "
                 "Every page, API route, requirement and knowledge line is cited by a screen or excluded with a "
                 "reason; every captured screen is cited by a screen."]
    if placed:
        parts += ["", f"## {PLACED_TITLE}"] + placed
    for kind in ORDER:
        entries = [i for i in sources if i["kind"] == kind]
        if entries:
            parts += ["", f"## {TITLES[kind]}"] + _lines(kind, entries)
    if questions:
        parts += ["", "## Open questions from stage 1 (context; do not answer them)"]
        parts += [f"- {q['id']}: {q['question']}" for q in questions if q.get("status") != "answered"]
    parts += tools or []
    return "\n".join(parts) + "\n"


HOW_TO_FIX = ("Fix every problem listed: cite only ids that appear in the task; place each uncovered item on the "
              "screen that uses it (or exclude a page, API route, requirement or knowledge line with a reason); give each screen "
              "loading, empty, error, partial and normal and each action pending, done and error; name each "
              "outcome a source names (refused with locker_full -> refused-locker-full) as a state of the "
              "action or screen citing it; cite the source of every other state; use each id once.")


def revise(task_text: str, draft_text: str, problems: list[dict]) -> str:
    return model_step.revise_text(task_text, draft_text, problems, HOW_TO_FIX, SHOWN_PROBLEMS)
