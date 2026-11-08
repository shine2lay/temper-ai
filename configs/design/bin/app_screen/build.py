"""Stage 5, build: the clickable prototype for the chosen direction (05-build/index.html, shell/, screens/,
styles/tokens.css, fixture.json, build.json), one file per screen and every state.

Stage 5a (deterministic half, rule 17):
- Validates 03-ground/ and 04-directions/ inputs at the boundary (build_scaffold.validate_inputs).
- Writes the contract-valid prototype skeleton with data-build-placeholder="<screen-id>" per screen
  (build_scaffold.write_scaffold).
- Verifies the written build with deterministic checks (build_check.check_workspace).
"""
from __future__ import annotations

import json
import re

from . import build_check, build_scaffold, contracts, model_step
from .build_scaffold import BuildInputError
from .workspace import Workspace


class BuildError(BuildInputError):
    """Stage 5 build failed input validation or deterministic build checks."""


def _parse_draft(raw: str) -> dict:
    cleaned = (raw or "").strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    parsed = model_step.parse_reply(cleaned)
    if not isinstance(parsed, dict) or "unreadable" in parsed:
        reason = parsed.get("unreadable", "not a JSON object") if isinstance(parsed, dict) else "not a JSON object"
        raise BuildError(f"05-build/draft.json: {reason}")
    errs = contracts.check_json("build_draft", parsed, "05-build/draft.json")
    if errs:
        raise BuildError("; ".join(errs[:5]))
    return parsed


def check(ws: Workspace, raw: str = "") -> dict:
    """Run deterministic Stage 5a/5b checks on 05-build/."""
    folder = ws.folder("build")
    if (folder / f"prebuilt-round-{ws.round}").is_dir():
        return {
            "verdict": "ok",
            "problems": [],
            "counts": {"screens": 0, "states": 0, "views": 0, "problems": 0},
            "revise_task": "",
        }
    if not raw or not raw.strip():
        seeded = folder / f"draft-round-{ws.round}.json"
        if seeded.is_file():
            raw = seeded.read_text(encoding="utf-8")
        else:
            return build_check.check_workspace(ws, pass_name="final")
    try:
        draft = _parse_draft(raw)
    except BuildError as exc:
        prob = {"check": "build_draft_schema", "where": "05-build/draft.json", "detail": str(exc)}
        found = {
            "stage": "build",
            "pass": "draft",
            "verdict": "retry",
            "problems": [prob],
            "checks": ["build_draft_schema"],
            "counts": {"screens": 0, "states": 0, "views": 0, "problems": 1},
        }
        model_step.write_json(folder / "check.json", found)
        task_path = folder / "task.md"
        task_text = task_path.read_text(encoding="utf-8") if task_path.is_file() else build_scaffold.build_task(ws)
        revise_task = model_step.revise_text(
            task_text,
            (raw or "")[:4000],
            [prob],
            "Return ONE valid JSON object matching schema `build_draft` (`{\"screens\": [...], \"notes\": [...]}`) with keys `id`, `title`, `lead`, `layout`, `states`, `shows`, `actions`.",
            shown=5,
        )
        return {
            "verdict": "retry",
            "problems": [prob],
            "counts": found["counts"],
            "revise_task": revise_task,
        }
    model_step.write_json(folder / "draft-first.json", draft)
    model_step.write_json(folder / "draft.json", draft)
    build_scaffold.render_draft(ws, draft)
    found = build_check.check_workspace(ws, pass_name="draft", require_built=True, draft=draft)
    model_step.write_json(folder / "check.json", found)
    revise_task = ""
    if found["verdict"] == "retry":
        task_path = folder / "task.md"
        task_text = task_path.read_text(encoding="utf-8") if task_path.is_file() else build_scaffold.build_task(ws)
        bad_ids = {
            m.group(1)
            for p in found["problems"]
            for m in [re.search(r"screens\[([a-z0-9-]+)\]|screens/([a-z0-9-]+)\.js", p.get("where", ""))]
            if m and (m.group(1) or m.group(2))
        }
        bad_ids = {
            (m.group(1) or m.group(2))
            for p in found["problems"]
            for m in [re.search(r"screens\[([a-z0-9-]+)\]|screens/([a-z0-9-]+)\.js", p.get("where", ""))]
            if m
        }
        subset_screens = [
            s for s in (draft.get("screens") or [])
            if isinstance(s, dict) and (not bad_ids or s.get("id") in bad_ids)
        ]
        revise_task = model_step.revise_text(
            task_text,
            json.dumps({"screens": subset_screens}, indent=1, ensure_ascii=False),
            found["problems"],
            "Return ONE JSON object `{\"screens\": [...]}` containing the corrected screen object(s) for the broken screen(s) (remove any digits or literal numbers from prose and bind figures via fields[] paths).",
            shown=12,
        )
    return {
        "verdict": found["verdict"],
        "problems": found["problems"],
        "counts": found["counts"],
        "revise_task": revise_task,
    }


def finish(ws: Workspace, raw: str = "") -> dict:
    """Apply revised draft if needed, run final Stage 5b check, and fail loud on any remaining problem."""
    folder = ws.folder("build")
    if (folder / f"prebuilt-round-{ws.round}").is_dir():
        contracts.validate("build", ws)
        return {"verdict": "ok", "retried": False}
    check_path = folder / "check.json"
    if not check_path.is_file():
        raise BuildError("05-build/check.json is missing; run build_check before build_finish")
    first = json.loads(check_path.read_text(encoding="utf-8"))
    if first.get("verdict") == "retry":
        if not raw or not raw.strip():
            raise BuildError(
                model_step.failure(first.get("problems") or [], "05-build/draft.json (no revised draft)")
            )
        revised = _parse_draft(raw)
        first_path = folder / "draft-first.json"
        if first_path.is_file():
            base_draft = json.loads(first_path.read_text(encoding="utf-8"))
            rev_by_id = {
                s["id"]: s
                for s in (revised.get("screens") or [])
                if isinstance(s, dict) and isinstance(s.get("id"), str)
            }
            merged_screens: list[dict] = []
            seen_ids: set[str] = set()
            for s in base_draft.get("screens") or []:
                if isinstance(s, dict) and isinstance(s.get("id"), str):
                    sid = s["id"]
                    merged_screens.append(rev_by_id.get(sid, s))
                    seen_ids.add(sid)
            for sid, s in rev_by_id.items():
                if sid not in seen_ids:
                    merged_screens.append(s)
            draft = {"screens": merged_screens}
            if "notes" in revised:
                draft["notes"] = revised["notes"]
        else:
            draft = revised
        model_step.write_json(folder / "draft.json", draft)
        build_scaffold.render_draft(ws, draft)
    else:
        draft_path = folder / "draft.json"
        if not draft_path.is_file():
            raise BuildError("05-build/draft.json is missing")
        draft = json.loads(draft_path.read_text(encoding="utf-8"))
    final = build_check.check_workspace(ws, pass_name="final", require_built=True, draft=draft)
    model_step.write_json(folder / "check-final.json", final)
    if final["problems"]:
        raise BuildError(model_step.failure(final["problems"], "05-build/draft.json"))
    return {
        "verdict": "ok",
        "retried": first.get("verdict") == "retry",
        **final["counts"],
    }


def run(ws: Workspace, data: str = "") -> dict:
    """Run Stage 5 build: writes and checks the Stage 5a skeleton."""
    prebuilt_next = ws.folder("build") / f"prebuilt-round-{ws.round + 1}"
    if prebuilt_next.is_dir():
        import shutil  # noqa: PLC0415

        r = ws.next_round()
        folder = ws.folder("build")
        for item in prebuilt_next.iterdir():
            dest = folder / item.name
            if item.is_dir():
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(item, dest, copy_function=shutil.copyfile)
            else:
                if dest.exists():
                    dest.unlink()
                shutil.copyfile(item, dest)
        path = folder / "build.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["round"] = r
        path.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        contracts.validate("build", ws)
        return {
            "direction": doc.get("direction", "a"),
            "round": r,
            "placeholder": False,
            "model": "no",
            "task": "",
            "verdict": "ok",
        }
    scaffold = build_scaffold.write_scaffold(ws)
    found = build_check.check_workspace(ws, pass_name="final")
    if found["problems"]:
        raise BuildError(model_step.failure(found["problems"], "05-build/build.json"))
    task = build_scaffold.build_task(ws)
    seeded = (ws.folder("build") / f"draft-round-{scaffold['round']}.json").is_file()
    return {
        "direction": scaffold["chosen_direction"],
        "round": scaffold["round"],
        "placeholder": True,
        "model": "no" if seeded else "yes",
        "task": task,
        "verdict": found["verdict"],
        **found["counts"],
    }
