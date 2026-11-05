"""What every fenced model step of the workflow shares: reading the model's reply, the check record a check
step writes, the revision text that sends the problems back once, and the loud failure the final step raises.

Stages 1 to 3 (intake, existing, ground) all run read -> check -> one revise -> final check; the stage keeps
its own checks and its own fix instructions, and these helpers keep the files and messages the same shape.
"""
from __future__ import annotations

import json
from pathlib import Path

SHOWN_FAILURES = 12


def write_json(path: Path, data) -> None:
    """Write data (a JSON value, or text as it is) to path, making its folder."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = data if isinstance(data, str) else json.dumps(data, indent=1, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8")


def parse_reply(text: str):
    """The model's reply as JSON, or a marker the schema check reports."""
    if not (text or "").strip():
        return {"unreadable": "the model step returned nothing"}
    try:
        return json.loads(text)
    except ValueError as exc:
        return {"unreadable": f"not one JSON object ({exc})"}


def check_record(found: dict, pass_name: str) -> dict:
    """check.json / check-final.json: a check's verdict, pass (draft or final), counts and problems."""
    return {"verdict": found["verdict"], "pass": pass_name, "counts": found["counts"], "problems": found["problems"]}


def revise_text(task_text: str, draft_text: str, problems: list[dict], how_to_fix: str, shown: int) -> str:
    """The task again, the model's draft and the first `shown` problems, with the stage's fix instructions."""
    listed = [f"- {p['check']} at {p['where']}: {p['problem']}" for p in problems[:shown]]
    more = len(problems) - shown
    return (task_text + "\n# Your previous draft\n" + draft_text.strip() + "\n\n"
            f"# The check found {len(problems)} problem(s) in it\n" + "\n".join(listed)
            + (f"\n- and {more} more of the same kinds" if more > 0 else "") + "\n\n"
            + how_to_fix + " Keep everything else as it was. Reply with the whole corrected draft as ONE JSON "
            "object, no code fence.\n")


def failure(problems: list[dict], record: str) -> str:
    """The final step's loud message: how many checks broke, the first few, where the rest are."""
    listed = "; ".join(f"{p['check']} {p['where']}: {p['problem']}" for p in problems[:SHOWN_FAILURES])
    more = len(problems) - SHOWN_FAILURES
    return (f"the final draft breaks {len(problems)} check(s): {listed}"
            + (f"; and {more} more in {record}" if more > 0 else ""))
