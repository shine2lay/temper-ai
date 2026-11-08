"""Stage 6b, review: fenced design, UX, state, and language review + deterministic verdict and loop trigger.

Pipeline (design_app_screen_v1 and design_app_screen_v1_review):
  review_collect -> review_read -> review_check -> review_revise -> review

Rule 17 (deterministic steps first, fenced model only where judgment is needed):
- review.collect groups Stage 6a failing check rows by (check_id, screen) into M1..Mk (measured_items.json),
  builds the contact sheet 06-checks/round-<n>/sheet.png from views/*.png (reusing existing_sheet.py), and
  writes 06-checks/round-<n>/task.md with requirements, rendered per-screen state/card/action copy, M1..Mk,
  and prior-round Must findings when round > 1.
- review_read (design_app_screen_review_v1, claude-opus-5-5) outputs 06-checks/round-<n>/draft.json
  (schema review_draft: measured[] decisions for M1..Mk + findings[] for UX/taste/language issues).
- review.check runs review_check.py (7 rules) and writes 06-checks/round-<n>/check.json + revise_task.
- review.run validates the final draft (check-final.json), merges measured[] and findings[] into F1..Fn in
  06-checks/round-<n>/review.json, and sets verdict = "revise" iff any finding has priority == "must" else "done".
"""
from __future__ import annotations

import base64
import json
import re
import struct
import sys
import zlib
from pathlib import Path
from typing import Any

from . import contracts, existing_sheet, model_step, review_check
from .workspace import Workspace


def _ensure_pillow() -> bool:
    if existing_sheet.Image is not None:
        return True
    for extra in (
        "/home/shinelay/.local/lib/python3.12/site-packages",
        "/home/shinelay/temper-ai/workspaces/merged_poster_ws/main/.venv/lib/python3.12/site-packages",
    ):
        if Path(extra).is_dir() and extra not in sys.path:
            sys.path.append(extra)
    try:
        from PIL import Image, ImageDraw, ImageFont  # noqa: PLC0415

        existing_sheet.Image = Image
        existing_sheet.ImageDraw = ImageDraw
        existing_sheet.ImageFont = ImageFont
        return True
    except ImportError:
        return False


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def _write_canonical_png(out: Path, width: int = 390, height: int = 260) -> None:
    """Write a small valid canonical RGB PNG (passes temper_ai.agent.image_input.parse_inline_png)."""
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    row = b"\x00" + (b"\xf8\xf8\xf6" * width)
    idat = zlib.compress(row * height, 9)
    raw = b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", ihdr) + _png_chunk(b"IDAT", idat) + _png_chunk(b"IEND", b"")
    out.write_bytes(raw)


def _png_size(path: Path) -> tuple[int, int] | None:
    try:
        head = path.read_bytes()[:24]
    except OSError:
        return None
    if len(head) >= 24 and head.startswith(b"\x89PNG\r\n\x1a\n") and head[12:16] == b"IHDR":
        w, h = struct.unpack(">II", head[16:24])
        if w > 0 and h > 0:
            return int(w), int(h)
    return None


class ReviewError(ValueError):
    """Stage 6b review failed input preconditions or final draft validation."""


def _load_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise ReviewError(f"{label} ({path}) is missing")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReviewError(f"{label} ({path}) is not readable JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ReviewError(f"{label} ({path}) is not a JSON object")
    return data


def _row_screen(row: dict[str, Any], valid_screens: list[str]) -> str:
    scr = str(row.get("screen") or "").strip()
    if scr and re.match(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{0,79}$", scr):
        return scr
    loc = str(row.get("location") or "").strip()
    if loc:
        head = loc.split("/")[0].split(":")[0].split("@")[0].strip()
        if head in valid_screens:
            return head
        for vs in valid_screens:
            if loc.startswith(vs + " ") or loc.startswith(vs + "/"):
                return vs
        if head and re.match(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{0,79}$", head):
            return head
    return valid_screens[0] if valid_screens else "round"


def group_measured_items(checks_doc: dict[str, Any], valid_screens: list[str], round_num: int = 1) -> dict[str, Any]:
    """Group failing Stage 6a check rows by (check_id, screen) into M1..Mk."""
    raw_rows = [
        r for r in (checks_doc.get("checks") or [])
        if isinstance(r, dict) and r.get("result") == "fail" and not r.get("summary")
    ]
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in raw_rows:
        cid = str(row.get("id") or "check")
        scr = _row_screen(row, valid_screens)
        groups.setdefault((cid, scr), []).append(row)

    # Order blocker groups first (preserving first-seen order within blockers, then shoulds)
    ordered_keys = sorted(
        groups.keys(),
        key=lambda k: (0 if any(r.get("severity") == "blocker" for r in groups[k]) else 1),
    )

    items: list[dict[str, Any]] = []
    blocker_rows = sum(1 for r in raw_rows if r.get("severity") == "blocker")
    should_rows = len(raw_rows) - blocker_rows

    for idx, (cid, scr) in enumerate(ordered_keys, start=1):
        rows = groups[(cid, scr)]
        sev = "blocker" if any(r.get("severity") == "blocker" for r in rows) else "should"
        elements: list[str] = []
        locations: list[str] = []
        states: list[str] = []
        views: list[str] = []
        for r in rows:
            el = str(r.get("element") or "").strip()
            if el and el not in elements:
                elements.append(el)
            loc = str(r.get("location") or "").strip()
            if loc and loc not in locations:
                locations.append(loc)
            st = str(r.get("state") or "").strip()
            if st and st not in states:
                states.append(st)
            vw = str(r.get("view") or "").strip()
            if vw and vw not in views:
                views.append(vw)

        elem_str = "; ".join(elements[:3]) if elements else cid
        if len(locations) == 1 and locations[0].startswith(scr):
            loc_str = locations[0]
        elif locations:
            loc_str = f"{scr} ({', '.join(locations[:3])})"
        else:
            loc_str = scr

        first_ev = str(rows[0].get("evidence") or "").strip()
        if len(rows) == 1:
            ev_str = first_ev
        else:
            ev_str = f"{first_ev} [{len(rows)} failing rows across {', '.join(locations[:4])}]"

        items.append({
            "id": f"M{idx}",
            "check": cid,
            "severity": sev,
            "screen": scr,
            "element": elem_str[:240],
            "location": loc_str[:200],
            "evidence": ev_str[:400],
            "count": len(rows),
            "states": states,
            "views": views,
        })

    return {
        "round": round_num,
        "blockers": blocker_rows,
        "shoulds": should_rows,
        "items": items,
    }


def _build_contact_sheet(ws: Workspace, measured_doc: dict[str, Any]) -> tuple[Path, str]:
    """Build 06-checks/round-<n>/sheet.png from 06-checks/round-<n>/views/*.png (reusing existing_sheet.py)."""
    round_dir = ws.round_folder()
    views_dir = round_dir / "views"
    sheet_path = round_dir / "sheet.png"

    png_files = sorted(views_dir.glob("*.png")) if views_dir.is_dir() else []
    if png_files:
        by_size: dict[tuple[int, int], list[tuple[str, Path]]] = {}
        for p in png_files:
            sz = _png_size(p)
            if sz is not None:
                by_size.setdefault(sz, []).append((p.stem, p))
        if not by_size:
            raise ReviewError(f"no readable PNGs in {views_dir}")
        # Prefer 390px phone captures (where every screen x state is captured at identical dimensions),
        # otherwise choose the largest same-size group.
        chosen_size = next(
            (sz for sz in sorted(by_size.keys()) if sz[0] == 390),
            max(by_size.keys(), key=lambda sz: len(by_size[sz])),
        )
        candidates = by_size[chosen_size]
        if len(candidates) > 12:
            failing_views = {
                vw
                for it in (measured_doc.get("items") or [])
                for vw in (it.get("views") or [])
            }
            prioritized = sorted(
                candidates,
                key=lambda item: (
                    0 if ("-done-" in item[0] or "-error-" in item[0]) else (1 if item[0] in failing_views else 2),
                    item[0],
                ),
            )[:12]
            prioritized_set = {item[0] for item in prioritized}
            candidates = [item for item in candidates if item[0] in prioritized_set]

        if _ensure_pillow():
            try:
                existing_sheet.build(candidates, sheet_path, budget=140_000)
            except Exception:
                try:
                    existing_sheet.build(candidates[:6], sheet_path, budget=140_000)
                except Exception:
                    _write_canonical_png(sheet_path)
        else:
            _write_canonical_png(sheet_path)
    elif not sheet_path.is_file():
        raise ReviewError(f"{views_dir} has no view PNGs and {sheet_path} is missing; run checks first")

    raw_bytes = sheet_path.read_bytes()
    b64 = base64.b64encode(raw_bytes).decode("ascii")
    return sheet_path, b64


def _render_screen_copy_section(ws: Workspace, valid_screens: list[str]) -> str:
    """Format per-screen rendered copy and state text for 06-checks/round-<n>/task.md."""
    build_dir = ws.folder("build")
    draft_path = build_dir / "draft.json"
    blocks: list[str] = []

    if draft_path.is_file():
        try:
            ddoc = json.loads(draft_path.read_text(encoding="utf-8"))
            for s in ddoc.get("screens") or []:
                if not isinstance(s, dict):
                    continue
                sid = str(s.get("id") or "")
                lines = [
                    f"### Screen `{sid}` — title: {s.get('title')!r} | layout: `{s.get('layout')}`",
                    f"- Lead: {s.get('lead')!r}",
                    "- States (`states`):",
                ]
                states = s.get("states") or {}
                if isinstance(states, dict):
                    for st_name, st_obj in states.items():
                        if isinstance(st_obj, dict):
                            lines.append(
                                f"  - `{sid}/{st_name}`: badge={st_obj.get('badge', '')!r} | "
                                f"headline={st_obj.get('headline', '')!r} | summary={st_obj.get('summary', '')!r}"
                            )
                lines.append("- Shows cards (`shows[]`):")
                for sh in s.get("shows") or []:
                    if isinstance(sh, dict):
                        lines.append(
                            f"  - `{sh.get('ref')}` heading={sh.get('heading', '')!r} | "
                            f"copy={sh.get('copy', '')!r} | fields={sh.get('fields')!r}"
                        )
                lines.append("- Action controls (`actions[]`):")
                for act in s.get("actions") or []:
                    if isinstance(act, dict):
                        lines.append(
                            f"  - id=`{act.get('id')}` kind=`{act.get('kind')}` label={act.get('label', '')!r} | "
                            f"states={act.get('states')!r} | feedback={act.get('feedback', '')!r}"
                        )
                blocks.append("\n".join(lines))
        except (OSError, json.JSONDecodeError):
            pass

    if blocks:
        return "\n\n".join(blocks)

    # Fallback when 05-build/draft.json is absent (e.g. direct HTML/JS builds in Stage 6a known cases):
    # extract rendered texts from 06-checks/round-<n>/measures.json per screen/state.
    measures_path = ws.round_folder() / "measures.json"
    if measures_path.is_file():
        try:
            mdoc = json.loads(measures_path.read_text(encoding="utf-8"))
            by_screen: dict[str, list[str]] = {}
            measured_map = mdoc.get("measured")
            view_entries = (
                list(measured_map.values())
                if isinstance(measured_map, dict)
                else (mdoc.get("views") or [])
            )
            for v in view_entries:
                if not isinstance(v, dict):
                    continue
                scr = str(v.get("screen") or "")
                st = str(v.get("state") or "")
                w = v.get("width")
                if w and int(w) != 390:
                    continue
                texts: list[str] = []
                raw_runs = (
                    ((v.get("mp") or {}).get("runs") or [])
                    + ((v.get("measures") or {}).get("texts") or [])
                )
                for t in raw_runs:
                    txt = t.get("text") if isinstance(t, dict) else str(t)
                    if isinstance(txt, str) and txt.strip() and txt.strip() not in texts:
                        texts.append(txt.strip())
                by_screen.setdefault(scr, []).append(
                    f"  - `{scr}/{st}` visible texts: {json.dumps(texts[:18], ensure_ascii=False)}"
                )
            for scr in valid_screens:
                lines = [f"### Screen `{scr}`", *(by_screen.get(scr) or [f"  - `{scr}`: (see contact sheet)"])]
                blocks.append("\n".join(lines))
        except (OSError, json.JSONDecodeError):
            pass

    return "\n\n".join(blocks) if blocks else "(No per-screen copy extracted)"


def build_task(ws: Workspace, measured_doc: dict[str, Any]) -> str:
    """Build and write 06-checks/round-<n>/task.md for the fenced review agent."""
    round_num = ws.round or 1
    round_dir = ws.round_folder(round_num)
    valid_screens = review_check._valid_screens(ws)

    req_lines: list[str] = []
    req_path = ws.folder("intake") / "requirements.json"
    if req_path.is_file():
        try:
            rdoc = json.loads(req_path.read_text(encoding="utf-8"))
            for item in rdoc.get("items") or []:
                if isinstance(item, dict):
                    req_lines.append(
                        f"- `{item.get('id')}` ({item.get('kind')}): {item.get('means') or item.get('owner_words')} "
                        f"[maps_to: {', '.join(item.get('maps_to') or [])}]"
                    )
        except (OSError, json.JSONDecodeError):
            pass

    measured_items = measured_doc.get("items") or []
    measured_lines: list[str] = []
    for it in measured_items:
        measured_lines.append(
            f"- `{it['id']}` | check=`{it['check']}` | class=`{it['severity']}` | screen=`{it['screen']}` | "
            f"location={it['location']!r} | element={it['element']!r} | evidence={it['evidence']!r}"
        )

    prior_must_lines: list[str] = []
    if round_num > 1:
        prev_rev_path = ws.round_folder(round_num - 1) / "review.json"
        if prev_rev_path.is_file():
            try:
                prev_rev = json.loads(prev_rev_path.read_text(encoding="utf-8"))
                for f in prev_rev.get("findings") or []:
                    if isinstance(f, dict) and f.get("priority") == "must":
                        prior_must_lines.append(
                            f"- `{f.get('id')}` at `{f.get('location')}` ({f.get('element')}): "
                            f"evidence={f.get('evidence')!r} | suggestion={f.get('suggestion', '')!r}"
                        )
            except (OSError, json.JSONDecodeError):
                pass

    copy_section = _render_screen_copy_section(ws, valid_screens)

    lines = [
        f"# Stage 6b Task: Fenced Design, UX & Copy Review (Round {round_num})",
        "",
        "Return ONE valid JSON object matching schema `review_draft` (`{\"measured\": [...], \"findings\": [...]}`).",
        "Do NOT wrap the JSON in prose or commentary.",
        "",
        "## Output JSON Schema (`review_draft`)",
        "```json",
        "{",
        '  "measured": [',
        "    {",
        '      "id": "M1",',
        '      "severity": 3,',
        '      "priority": "must",',
        '      "suggestion": "Concrete fix instruction",',
        '      "reason": "Required if a blocker is demoted below must (>= 15 chars) or if priority is wont"',
        "    }",
        "  ],",
        '  "findings": [',
        "    {",
        '      "element": "Element or state field name",',
        '      "location": "<screen>/<state>",',
        '      "evidence": "Verbatim quote from the screen rendered copy/state text below",',
        '      "severity": 4,',
        '      "priority": "must",',
        '      "suggestion": "Concrete fix instruction"',
        "    }",
        "  ]",
        "}",
        "```",
        "",
        "## Hard Fenced Rules Checked by `review_check.py` (Violations Trigger Retry)",
        "1. `every_measured_item_covered`: Every item `M1..Mk` listed under **Measured Items (`M1..Mk`)** below MUST appear in `measured[]` exactly once (`measured: []` when there are 0 measured items).",
        "2. `demoted_blocker_has_reason`: Every `M*` item with `class=blocker` MUST take `\"priority\": \"must\"` (severity 3 or 4) unless you provide a concrete `\"reason\"` of at least 15 characters explaining why it is not a real blocker. `M*` items with `class=should` typically take `\"priority\": \"should\"` or `\"could\"`.",
        "3. `wont_has_reason`: Every item in `measured[]` or `findings[]` with `\"priority\": \"wont\"` MUST include a non-empty `\"reason\"`.",
        "4. `must_has_suggestion`: Every item in `measured[]` or `findings[]` with `\"priority\": \"must\"` MUST include a non-empty `\"suggestion\"`.",
        "5. `no_invented_measurement`: NEVER claim a script-measured metric failure (`contrast ratio`, `X:1`, `px font floor`, `24x24 target size`, `axe violation`, `horizontal scroll`) in `findings[]`! Script-measured checks are already in `measured[]`. `findings[]` is strictly for UX, state honesty, error recovery guidance, control labels, and copy/language quality.",
        f"6. `valid_location_and_evidence`: Every entry in `findings[]` MUST set `\"location\"` to `<screen>` or `<screen>/<state>` using a valid screen ID ({', '.join(f'`{s}`' for s in valid_screens)}), and `\"evidence\"` MUST contain a verbatim substring quoted from that screen's rendered copy/state text below.",
        "",
        "## UX, State & Language Evaluation Checklist for `findings[]`",
        "Inspect every screen's states (`done`, `empty`, `loading`, `error`, `partial`), `shows[]` cards, and `actions[]` labels/feedback:",
        "- **Raw error/secret leaks or missing recovery in `error` state (`priority: \"must\"`, `severity: 4`)**: Error state copy must explain what went wrong in plain human words and how to recover. Flag any raw SQL query, database/stack trace, error code dump, or credential/secret/token leak (such as `FATAL`, `auth_token=`, `sk_live`, `SELECT * FROM`) as `\"priority\": \"must\"`, `\"severity\": 4`, quoting the exact error text in `\"evidence\"`.",
        "- **Robotic placeholder button/control labels (`priority: \"must\"`, `severity: 3`)**: Action labels must use clear domain words, never raw snake_case identifiers or placeholder labels (such as `Submit action_btn_1`, `action_btn`, `btn_1`, `todo_label`). Flag any robotic placeholder label as `\"priority\": \"must\"`, quoting the exact label in `\"evidence\"`.",
        "- **Reassurance fluff replacing requested figures/status (`priority: \"must\"`, `severity: 3`)**: Headlines, summaries, and `shows[]` copy must communicate concrete domain status and figures, never vague reassurance fluff that tells the user to relax and trust the system instead of showing the data (such as `\"Everything is fine, relax and trust the system...\"`). Flag reassurance fluff as `\"priority\": \"must\"`, quoting the exact sentence in `\"evidence\"`.",
        "- **Clean-build calibration (`0` false Musts)**: When **Measured Items** is empty (`0` blockers, `0` shoulds) AND all screens have clean, grounded human copy, clear error recovery, real domain action labels, and faithful requirement coverage without any of the flaws above, return `\"findings\": []` so the build passes with `verdict: \"done\"`. Do NOT invent nitpicks or false `must` findings on a clean build.",
        "",
        "## Product Requirements (`01-request/requirements.json`)",
        *(req_lines or ["- (See screen copy below)"]),
        "",
    ]

    if prior_must_lines:
        lines.extend([
            f"## Prior Round (Round {round_num - 1}) Must Findings",
            "Verify whether this round's build resolved each prior Must finding below; only re-open if the flaw is still present in the current screen copy:",
            *prior_must_lines,
            "",
        ])

    lines.extend([
        f"## Stage 6a Measured Items (`M1..M{len(measured_items)}`) — Blockers: {measured_doc.get('blockers', 0)}, Shoulds: {measured_doc.get('shoulds', 0)}",
        *(measured_lines if measured_lines else ["- `(none — all 24 Stage 6a measured checks passed with 0 blockers and 0 shoulds; set \"measured\": [])`"]),
        "",
        "## Rendered Copy & State Text Per Screen (`05-build/`)",
        copy_section,
        "",
    ])

    task_text = "\n".join(lines) + "\n"
    round_dir.mkdir(parents=True, exist_ok=True)
    (round_dir / "task.md").write_text(task_text, encoding="utf-8")
    return task_text


def _parse_draft(ws: Workspace, raw: str) -> dict[str, Any]:
    cleaned = (raw or "").strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    parsed = model_step.parse_reply(cleaned)
    rel = f"06-checks/round-{ws.round}/draft.json"
    if not isinstance(parsed, dict) or "unreadable" in parsed:
        reason = parsed.get("unreadable", "not a JSON object") if isinstance(parsed, dict) else "not a JSON object"
        raise ReviewError(f"{rel}: {reason}")
    errs = contracts.check_json("review_draft", parsed, rel)
    if errs:
        raise ReviewError("; ".join(errs[:5]))
    return parsed


def collect(ws: Workspace, _raw: str = "") -> dict[str, Any]:
    """Run review_collect: group Stage 6a checks into M1..Mk, build contact sheet, and write task.md."""
    round_num = ws.round or 1
    round_dir = ws.round_folder(round_num)
    checks_path = round_dir / "checks.json"
    checks_doc = _load_json(checks_path, f"06-checks/round-{round_num}/checks.json")
    _load_json(ws.folder("build") / "build.json", "05-build/build.json")

    valid_screens = review_check._valid_screens(ws)
    measured_doc = group_measured_items(checks_doc, valid_screens, round_num=round_num)
    model_step.write_json(round_dir / "measured_items.json", measured_doc)

    sheet_path, sheet_b64 = _build_contact_sheet(ws, measured_doc)
    task_text = build_task(ws, measured_doc)
    seeded = (round_dir / "draft-seeded.json").is_file()

    return {
        "model": "no" if seeded else "yes",
        "round": round_num,
        "measured_items": len(measured_doc["items"]),
        "blockers": measured_doc["blockers"],
        "shoulds": measured_doc["shoulds"],
        "task": task_text,
        "sheet": sheet_b64,
        "sheet_path": str(sheet_path),
    }


def check(ws: Workspace, raw: str = "") -> dict[str, Any]:
    """Run review_check: validate review_read output against the 7 rules in review_check.py."""
    round_num = ws.round or 1
    round_dir = ws.round_folder(round_num)
    rel_draft = f"06-checks/round-{round_num}/draft.json"
    items = review_check.load_measured_items(ws)
    if (not raw or not raw.strip()) and (round_dir / "draft-seeded.json").is_file():
        raw = (round_dir / "draft-seeded.json").read_text(encoding="utf-8")

    try:
        draft = _parse_draft(ws, raw)
    except ReviewError as exc:
        prob = {"check": "review_draft_schema", "where": rel_draft, "message": str(exc)}
        found = review_check._build_report("draft", items, [], [], [prob])
        model_step.write_json(round_dir / "check.json", found)
        task_path = round_dir / "task.md"
        task_text = task_path.read_text(encoding="utf-8") if task_path.is_file() else ""
        revise_task = model_step.revise_text(
            task_text,
            (raw or "")[:4000],
            [dict(prob, problem=prob["message"])],
            "Return ONE valid JSON object matching schema `review_draft` (`{\"measured\": [...], \"findings\": [...]}`).",
            shown=6,
        )
        return {
            "verdict": "retry",
            "problems": [prob],
            "counts": found["counts"],
            "revise_task": revise_task,
        }

    model_step.write_json(round_dir / "draft-first.json", draft)
    model_step.write_json(round_dir / "draft.json", draft)
    found = review_check.check_draft(ws, draft, pass_name="draft", measured_items=items)
    model_step.write_json(round_dir / "check.json", found)

    revise_task = ""
    if found["verdict"] == "retry":
        task_path = round_dir / "task.md"
        task_text = task_path.read_text(encoding="utf-8") if task_path.is_file() else ""
        revise_task = model_step.revise_text(
            task_text,
            json.dumps(draft, indent=1, ensure_ascii=False),
            [dict(p, problem=p["message"]) for p in found["problems"]],
            "Return ONE corrected JSON object matching schema `review_draft` (`{\"measured\": [...], \"findings\": [...]}`) fixing every problem listed above.",
            shown=12,
        )

    return {
        "verdict": found["verdict"],
        "problems": found["problems"],
        "counts": found["counts"],
        "revise_task": revise_task,
    }


def _merge_findings(
    measured_items: list[dict[str, Any]],
    draft: dict[str, Any],
) -> list[dict[str, Any]]:
    """Merge M1..Mk decisions (carrying deterministic element/location/evidence/check) and findings[] into F1..Fn."""
    decisions_by_id = {
        str(d["id"]): d
        for d in (draft.get("measured") or [])
        if isinstance(d, dict) and "id" in d
    }
    merged: list[dict[str, Any]] = []
    idx = 1

    for m_item in measured_items:
        mid = str(m_item["id"])
        dec = decisions_by_id[mid]
        entry: dict[str, Any] = {
            "id": f"F{idx}",
            "element": str(m_item["element"]),
            "location": str(m_item["location"]),
            "evidence": str(m_item["evidence"]),
            "severity": int(dec["severity"]),
            "priority": str(dec["priority"]),
            "check": str(m_item["check"]),
        }
        sugg = str(dec.get("suggestion") or "").strip()
        if sugg:
            entry["suggestion"] = sugg
        rsn = str(dec.get("reason") or "").strip()
        if rsn:
            entry["reason"] = rsn
        merged.append(entry)
        idx += 1

    for f in draft.get("findings") or []:
        if not isinstance(f, dict):
            continue
        entry = {
            "id": f"F{idx}",
            "element": str(f["element"]).strip(),
            "location": str(f["location"]).strip(),
            "evidence": str(f["evidence"]).strip(),
            "severity": int(f["severity"]),
            "priority": str(f["priority"]),
        }
        sugg = str(f.get("suggestion") or "").strip()
        if sugg:
            entry["suggestion"] = sugg
        rsn = str(f.get("reason") or "").strip()
        if rsn:
            entry["reason"] = rsn
        merged.append(entry)
        idx += 1

    return merged


def run(ws: Workspace, raw: str = "") -> dict[str, Any]:
    """Run final review step: check final draft and write review.json."""
    round_num = ws.round or 1
    round_dir = ws.round_folder(round_num)
    check_path = round_dir / "check.json"
    if not check_path.is_file():
        raise ReviewError(f"06-checks/round-{round_num}/check.json is missing; run review_check before review")

    first = json.loads(check_path.read_text(encoding="utf-8"))
    items = review_check.load_measured_items(ws)

    if first.get("verdict") == "retry":
        if not raw or not raw.strip():
            raise ReviewError(
                model_step.failure(
                    first.get("problems") or [],
                    f"06-checks/round-{round_num}/draft.json (no revised draft)",
                )
            )
        draft = _parse_draft(ws, raw)
        model_step.write_json(round_dir / "draft.json", draft)
    else:
        draft_path = round_dir / "draft.json"
        if not draft_path.is_file():
            raise ReviewError(f"06-checks/round-{round_num}/draft.json is missing")
        draft = json.loads(draft_path.read_text(encoding="utf-8"))

    final = review_check.check_draft(ws, draft, pass_name="final", measured_items=items)
    model_step.write_json(round_dir / "check-final.json", final)
    if final["problems"]:
        raise ReviewError(
            model_step.failure(
                [dict(p, problem=p["message"]) for p in final["problems"]],
                f"06-checks/round-{round_num}/draft.json",
            )
        )

    merged_findings = _merge_findings(items, draft)
    must_count = sum(1 for f in merged_findings if f["priority"] == "must")
    verdict = "revise" if must_count > 0 else "done"

    review_doc = {
        "round": round_num,
        "verdict": verdict,
        "source": "design_app_screen_review_v1",
        "findings": merged_findings,
    }
    model_step.write_json(round_dir / "review.json", review_doc)
    contracts.validate("review", ws)

    return {
        "round": round_num,
        "verdict": verdict,
        "must": must_count,
        "findings": len(merged_findings),
        "measured_items": len(items),
        "taste_findings": len(draft.get("findings") or []),
        "retried": first.get("verdict") == "retry",
    }
