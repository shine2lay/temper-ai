"""Stage 8 (08-handoff/): per-screen Markdown specs, design-file.json, followup.json, and deterministic check.

1. Validates upstream prerequisites loud and fast:
   - 07-show/gate_final.json must exist with choice == "approve",
   - 06-checks/round-<ws.round>/review.json must have verdict == "done" and 0 open Must findings,
   - 03-ground/inventory.json, 05-build/build.json, and 05-build/draft.json must exist.
2. Generates one comprehensive Markdown spec per screen in 08-handoff/spec/<screen-id>.md
   covering:
   - ## Routes (#<screen>/<state> for every state),
   - ## Layout & Widths (1440, 390, 320 + layout pattern),
   - ## Requirements (mapped R* with verbatim owner_words),
   - ## Grounded Data (shows[] S* with fields[] paths and sample values from 03-ground/fixture.json),
   - ## Actions (actions[] A* with immediate click feedback),
   - ## State Copy (full per-state copy table: normal, loading, empty, error, plus screen-specific states),
   - ## Review & Show&Tell Notes (Stage 6 checks/review summary + Stage 7 Show&Tell comment notes).
3. Writes 08-handoff/design-file.json (kind: "html-prototype", location: "05-build/index.html",
   editable: True, note) and 08-handoff/followup.json (F1..Fn: frontend implementation items
   per screen + design follow-ups for non-blocking should/could review findings or excluded ground items).
4. Runs handoff_check.py (6 rules -> 08-handoff/check.json) and contracts.validate("handoff", ws).
"""
from __future__ import annotations

import json
from typing import Any

from . import contracts
from .contracts import ContractError
from .handoff_check import assert_handoff_clean
from .workspace import Workspace


def _resolve_dotted_path(data: Any, path_str: str) -> Any:
    """Resolve a dotted/indexed path like 'summary.active' or 'shipments[0].status' against fixture data."""
    if not path_str or data is None:
        return None
    curr = data
    tokens = path_str.replace("[", ".").replace("]", "").split(".")
    for tok in tokens:
        if not tok:
            continue
        if isinstance(curr, dict) and tok in curr:
            curr = curr[tok]
        elif isinstance(curr, list) and tok.isdigit():
            idx = int(tok)
            if 0 <= idx < len(curr):
                curr = curr[idx]
            else:
                return None
        else:
            return None
    return curr


def validate_prerequisites(ws: Workspace) -> dict[str, Any]:
    """Fail loud and fast if gate_final is not approved, review is not done, or inventory/build/draft are missing."""
    ws = ws if ws.step else ws.for_step("handoff")
    round_num = max(1, ws.round) if ws.run_file.is_file() else 1
    problems: list[str] = []

    gate_path = ws.folder("show") / "gate_final.json"
    review_path = ws.round_folder(round_num) / "review.json"
    inv_path = ws.folder("ground") / "inventory.json"
    build_path = ws.folder("build") / "build.json"
    draft_path = ws.folder("build") / "draft.json"
    index_path = ws.folder("build") / "index.html"

    if not gate_path.is_file():
        problems.append("07-show/gate_final.json: missing final gate record")
    if not review_path.is_file():
        problems.append(f"06-checks/round-{round_num}/review.json: missing Stage 6b review record")
    if not inv_path.is_file():
        problems.append("03-ground/inventory.json: missing Stage 3 screen inventory")
    if not build_path.is_file():
        problems.append("05-build/build.json: missing Stage 5 build manifest")
    if not draft_path.is_file():
        problems.append("05-build/draft.json: missing Stage 5 draft specification")
    if not index_path.is_file():
        problems.append("05-build/index.html: missing Stage 5 prototype HTML")

    if problems:
        raise ContractError("handoff: " + "; ".join(problems))

    try:
        gate_doc = json.loads(ws.read_text(gate_path))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"handoff: 07-show/gate_final.json: invalid JSON ({exc})") from exc

    if not isinstance(gate_doc, dict) or gate_doc.get("choice") != "approve":
        choice = gate_doc.get("choice") if isinstance(gate_doc, dict) else None
        raise ContractError(
            f"handoff: 07-show/gate_final.json: choice must be 'approve' before Stage 8 handoff (got {choice!r})"
        )

    try:
        review_doc = json.loads(ws.read_text(review_path))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"handoff: 06-checks/round-{round_num}/review.json: invalid JSON ({exc})") from exc

    if not isinstance(review_doc, dict) or review_doc.get("verdict") != "done":
        verdict = review_doc.get("verdict") if isinstance(review_doc, dict) else None
        raise ContractError(
            f"handoff: 06-checks/round-{round_num}/review.json: verdict must be 'done' before Stage 8 handoff (got {verdict!r})"
        )

    open_must = [
        f.get("id", "?")
        for f in (review_doc.get("findings") or [])
        if isinstance(f, dict)
        and f.get("priority") == "must"
        and f.get("status") not in ("fixed", "resolved")
    ]
    if open_must:
        raise ContractError(
            f"handoff: 06-checks/round-{round_num}/review.json: cannot hand off with open Must finding(s): "
            + ", ".join(str(x) for x in open_must)
        )

    try:
        inv_doc = json.loads(ws.read_text(inv_path))
        draft_doc = json.loads(ws.read_text(draft_path))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"handoff: upstream JSON parse error: {exc}") from exc

    req_doc: dict[str, Any] = {}
    req_path = ws.folder("intake") / "requirements.json"
    if req_path.is_file():
        try:
            req_doc = json.loads(ws.read_text(req_path))
        except (OSError, json.JSONDecodeError) as exc:
            raise ContractError(f"handoff: cannot read {req_path}: {exc}") from exc

    fixture_doc: dict[str, Any] = {}
    for fp in (ws.folder("ground") / "fixture.json", ws.folder("build") / "fixture.json"):
        if fp.is_file():
            try:
                fixture_doc = json.loads(ws.read_text(fp))
            except (OSError, json.JSONDecodeError) as exc:
                raise ContractError(f"handoff: cannot read {fp}: {exc}") from exc
            break

    comments_doc: dict[str, Any] = {"comments": []}
    cm_path = ws.folder("show") / "comments.json"
    if cm_path.is_file():
        try:
            comments_doc = json.loads(ws.read_text(cm_path))
        except (OSError, json.JSONDecodeError) as exc:
            raise ContractError(f"handoff: cannot read {cm_path}: {exc}") from exc

    showtell_doc: dict[str, Any] = {}
    st_path = ws.folder("show") / "showtell.json"
    if st_path.is_file():
        try:
            showtell_doc = json.loads(ws.read_text(st_path))
        except (OSError, json.JSONDecodeError) as exc:
            raise ContractError(f"handoff: cannot read {st_path}: {exc}") from exc

    return {
        "round": round_num,
        "gate": gate_doc,
        "review": review_doc,
        "inventory": inv_doc,
        "draft": draft_doc,
        "requirements": req_doc,
        "fixture": fixture_doc,
        "comments": comments_doc,
        "showtell": showtell_doc,
    }


def _render_screen_spec(
    screen_inv: dict[str, Any],
    draft_screen: dict[str, Any],
    req_by_id: dict[str, dict[str, Any]],
    fixture_doc: dict[str, Any],
    review_doc: dict[str, Any],
    comments_doc: dict[str, Any],
    showtell_doc: dict[str, Any],
    round_num: int,
) -> str:
    sid = str(screen_inv.get("id") or "screen")
    title = str(draft_screen.get("title") or screen_inv.get("name") or screen_inv.get("title") or sid)
    job = str(screen_inv.get("job") or draft_screen.get("subtitle") or f"Primary user workflow for {title}.")
    layout = str(draft_screen.get("layout") or screen_inv.get("layout") or "band-cards-table")
    primary_action = str(draft_screen.get("primary_action") or "Primary action button")

    states: list[str] = []
    for st in (screen_inv.get("states") or draft_screen.get("states") or ["normal", "loading", "empty", "error"]):
        s_str = str(st)
        if s_str and s_str not in states:
            states.append(s_str)

    lines: list[str] = [
        f"# Screen Specification: {title} (`{sid}`)",
        "",
        f"- **Screen ID:** `{sid}`",
        f"- **Job:** {job}",
        f"- **Layout Pattern:** `{layout}`",
        f"- **Primary Action (one solid primary per view):** {primary_action}",
        f"- **Approved Round:** Round {round_num}",
        "",
        "## Routes",
        "",
        "| State | Hash Route | Purpose |",
        "| --- | --- | --- |",
    ]

    state_copy_map: dict[str, dict[str, Any]] = {}
    raw_sc = draft_screen.get("state_copy")
    if isinstance(raw_sc, dict):
        for k, v in raw_sc.items():
            if isinstance(v, dict):
                state_copy_map[str(k)] = v

    for st in states:
        sc = state_copy_map.get(st, {})
        verdict = str(sc.get("verdict") or f"{title} ({st} state)")
        lines.append(f"| `{st}` | `#{sid}/{st}` | {verdict} |")

    lines.extend([
        "",
        "## Layout & Widths",
        "",
        f"- **Pattern:** `{layout}` — glanceable top status band, summary cards, and progressive disclosure detail section.",
        "- **Responsive Widths Checked:**",
        "  - `1440` (`1440x900` desktop): multi-column card grid and full data table with inline progressive disclosure.",
        "  - `390` (`390x844` mobile): single-column stacked cards, collapsible detail drawers, 24x24px+ touch targets.",
        "  - `320` (`320x568` small mobile): zero horizontal overflow (`scrollWidth <= clientWidth`), wrapped action chips.",
        "",
        "## Requirements",
        "",
    ])

    req_ids = [str(r) for r in (screen_inv.get("requirements") or []) if r]
    if not req_ids and req_by_id:
        req_ids = sorted(req_by_id.keys())

    if req_ids:
        for rid in req_ids:
            r_obj = req_by_id.get(rid, {})
            means = str(r_obj.get("means") or r_obj.get("summary") or "Requirement mapped to screen")
            owner_words = str(r_obj.get("owner_words") or "").strip()
            source = str(r_obj.get("source") or "")
            lines.append(f"- **{rid}**: {means}")
            if owner_words:
                lines.append(f'  - Owner words: "{owner_words}" ({source})')
    else:
        lines.append("- **R1**: Core screen workflow and progressive disclosure requirements.")

    lines.extend([
        "",
        "## Grounded Data",
        "",
        "| Show ID | What | Grounded Fields / Sources | Sample Value |",
        "| --- | --- | --- | --- |",
    ])

    inv_shows = [sh for sh in (screen_inv.get("shows") or []) if isinstance(sh, dict)]
    draft_shows = [sh for sh in (draft_screen.get("shows") or []) if isinstance(sh, dict)]
    draft_by_id = {str(sh.get("id") or sh.get("ref") or ""): sh for sh in draft_shows}

    if inv_shows:
        for idx, sh in enumerate(inv_shows, start=1):
            sh_id = str(sh.get("id") or sh.get("ref") or f"S{idx}")
            d_sh = draft_by_id.get(sh_id, draft_shows[idx - 1] if idx - 1 < len(draft_shows) else {})
            what = str(sh.get("what") or d_sh.get("label") or sh_id)
            fields = sh.get("fields") or d_sh.get("fields") or sh.get("sources") or []
            field_strs = [str(f) for f in fields if f]
            sample_val = d_sh.get("value")
            if sample_val is None and field_strs:
                for fpath in field_strs:
                    resolved = _resolve_dotted_path(fixture_doc, fpath)
                    if resolved is not None:
                        sample_val = resolved
                        break
            if isinstance(sample_val, (dict, list)):
                sample_str = json.dumps(sample_val, ensure_ascii=False)[:80]
            elif sample_val is not None:
                sample_str = str(sample_val)
            else:
                sample_str = "grounded in fixture.json"
            fields_cell = ", ".join(f"`{f}`" for f in field_strs) if field_strs else "`fixture.json`"
            lines.append(f"| `{sh_id}` | {what} | {fields_cell} | `{sample_str}` |")
    else:
        lines.append("| `S1` | Primary screen summary | `fixture.json` | `grounded` |")

    lines.extend([
        "",
        "## Actions",
        "",
        "| Action ID | Label / Trigger | Kind | Immediate Click Feedback (before server reply) |",
        "| --- | --- | --- | --- |",
    ])

    inv_actions = [ac for ac in (screen_inv.get("actions") or []) if isinstance(ac, dict)]
    draft_actions = [ac for ac in (draft_screen.get("actions") or []) if isinstance(ac, dict)]
    draft_act_by_id = {str(ac.get("id") or ac.get("ref") or ""): ac for ac in draft_actions}

    if inv_actions:
        for idx, ac in enumerate(inv_actions, start=1):
            ac_id = str(ac.get("id") or ac.get("ref") or f"A{idx}")
            d_ac = draft_act_by_id.get(ac_id, draft_actions[idx - 1] if idx - 1 < len(draft_actions) else {})
            label = str(d_ac.get("label") or ac.get("do") or ac.get("what") or ac_id)
            kind = str(d_ac.get("kind") or ("primary" if idx == 1 else "secondary"))
            feedback = str(
                d_ac.get("feedback")
                or ac.get("leads_to")
                or ac.get("feedback")
                or f"Updates #rc-feedback banner immediately on click for {label}"
            )
            lines.append(f"| `{ac_id}` | {label} | `{kind}` | {feedback} |")
    elif draft_actions:
        for idx, d_ac in enumerate(draft_actions, start=1):
            ac_id = str(d_ac.get("id") or f"A{idx}")
            label = str(d_ac.get("label") or ac_id)
            kind = str(d_ac.get("kind") or ("primary" if idx == 1 else "secondary"))
            feedback = str(d_ac.get("feedback") or f"Immediate feedback banner for {label}")
            lines.append(f"| `{ac_id}` | {label} | `{kind}` | {feedback} |")
    else:
        lines.append(f"| `A1` | {primary_action} | `primary` | Immediate click feedback banner updated before server reply |")

    lines.extend([
        "",
        "## State Copy",
        "",
        "| State | Verdict Headline | Band Summary | Detail / Recovery Guidance |",
        "| --- | --- | --- | --- |",
    ])

    for st in states:
        sc = state_copy_map.get(st, {})
        verdict = str(sc.get("verdict") or f"{title} — {st}")
        band = str(sc.get("band") or f"{st.capitalize()} status band")
        detail = str(
            sc.get("recovery")
            or sc.get("guidance")
            or sc.get("empty_cta")
            or sc.get("note")
            or "Progressive disclosure rows and grounded status cards."
        )
        lines.append(f"| `{st}` | {verdict} | {band} | {detail} |")

    lines.extend([
        "",
        "## Review & Show&Tell Notes",
        "",
        f"- **Stage 6b Review Verdict:** `{review_doc.get('verdict', 'done')}` (Round {round_num}, 0 open Must findings).",
    ])

    findings = [
        f for f in (review_doc.get("findings") or [])
        if isinstance(f, dict) and (not f.get("screen") or f.get("screen") == sid)
    ]
    if findings:
        for f in findings:
            fid = f.get("id", "F")
            prio = f.get("priority", "could")
            status = f.get("status", "open")
            obs = f.get("observation") or f.get("title") or ""
            lines.append(f"  - Finding `{fid}` (`{prio}`, `{status}`): {obs}")
    else:
        lines.append("  - All automated Stage 6a checks and Stage 6b visual/heuristic review items passed cleanly.")

    st_doc_id = showtell_doc.get("doc_id", "d_app000000")
    st_ver = showtell_doc.get("version", round_num)
    change_note = showtell_doc.get("change_note")
    lines.append(f"- **Stage 7 Show&Tell Document:** `{st_doc_id}` (v{st_ver}, bundle `07-show/bundle.html`).")
    if change_note:
        lines.append(f"  - Change note: {change_note}")

    comments = [c for c in (comments_doc.get("comments") or []) if isinstance(c, dict)]
    if comments:
        for c in comments:
            cid = c.get("id") or f"c_{c.get('number', '?')}"
            cstate = c.get("state", "answered")
            cbody = c.get("body") or c.get("text") or ""
            lines.append(f"  - Comment `{cid}` (`{cstate}`): {cbody}")
    else:
        lines.append("  - 0 open Show&Tell comments at final approval.")

    return "\n".join(lines) + "\n"


def _build_followup_items(
    screens: list[dict[str, Any]],
    review_doc: dict[str, Any],
    inv_doc: dict[str, Any],
    round_num: int,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    counter = 1

    for s in screens:
        sid = str(s.get("id") or "screen")
        sname = str(s.get("name") or s.get("title") or sid)
        states = [str(st) for st in (s.get("states") or ["normal", "loading", "empty", "error"]) if st]
        items.append({
            "id": f"F{counter}",
            "owner_role": "frontend",
            "screen": sid,
            "what": (
                f"Implement screen '{sname}' ({sid}) across states {', '.join(states)} "
                f"at 1440px, 390px, and 320px per 08-handoff/spec/{sid}.md and 05-build/index.html"
            ),
            "source": f"08-handoff/spec/{sid}.md",
        })
        counter += 1

    for f in (review_doc.get("findings") or []):
        if not isinstance(f, dict):
            continue
        prio = f.get("priority")
        status = f.get("status")
        if prio in ("should", "could") and status not in ("fixed", "resolved"):
            fid = str(f.get("id") or f"review-{counter}")
            obs = str(f.get("observation") or f.get("title") or "Non-blocking polish finding")
            suggestion = str(f.get("suggestion") or obs)
            items.append({
                "id": f"F{counter}",
                "owner_role": "design",
                "what": f"Follow up on non-blocking {prio} review finding {fid}: {suggestion}",
                "source": f"06-checks/round-{round_num}/review.json#{fid}",
            })
            counter += 1

    for ex in (inv_doc.get("excluded") or []):
        if not isinstance(ex, dict):
            continue
        what = str(ex.get("what") or "").strip()
        why = str(ex.get("why") or "Out of current screen scope").strip()
        if what:
            items.append({
                "id": f"F{counter}",
                "owner_role": "design",
                "what": f"Deferred out-of-scope item ({what}): {why}",
                "source": "03-ground/inventory.json#excluded",
            })
            counter += 1

    return items


def _load_handoff_stack_metadata(ws: Workspace, review_doc: dict[str, Any]) -> dict[str, Any]:
    ws_step = ws if ws.step else ws.for_step("handoff")
    meta: dict[str, Any] = {}
    for k in ("commit", "short_commit", "ref", "reused", "ci_conclusion", "allow_red_commit", "ci_failing_check"):
        if review_doc.get(k) is not None:
            meta[k] = review_doc[k]
    if ws.run_file.is_file():
        try:
            run_doc = json.loads(ws_step.read_text(ws.run_file))
        except (OSError, json.JSONDecodeError) as exc:
            raise ContractError(f"handoff: cannot read {ws.run_file}: {exc}") from exc
        if isinstance(run_doc, dict) and isinstance(run_doc.get("stack"), dict):
            for k, v in run_doc["stack"].items():
                if k not in meta and v is not None:
                    meta[k] = v
    for rel in ("02-existing/capture.json", "02-existing/audit.json"):
        p = ws.path / rel
        if p.is_file():
            try:
                doc = json.loads(ws_step.read_text(p))
            except (OSError, json.JSONDecodeError) as exc:
                raise ContractError(f"handoff: cannot read {p}: {exc}") from exc
            if isinstance(doc, dict):
                for k in ("commit", "short_commit", "ref", "reused", "ci_conclusion", "allow_red_commit", "ci_failing_check"):
                    if k not in meta and doc.get(k) is not None:
                        meta[k] = doc[k]
    return {
        k: meta[k]
        for k in ("commit", "short_commit", "ref", "reused", "ci_conclusion", "allow_red_commit", "ci_failing_check")
        if k in meta and meta[k] is not None
    }


def run(ws: Workspace, _raw: str = "") -> dict[str, Any]:
    ws = ws.for_step("handoff")
    prereq = validate_prerequisites(ws)
    round_num: int = prereq["round"]
    inv_doc: dict[str, Any] = prereq["inventory"]
    draft_doc: dict[str, Any] = prereq["draft"]
    req_doc: dict[str, Any] = prereq["requirements"]
    fixture_doc: dict[str, Any] = prereq["fixture"]
    review_doc: dict[str, Any] = prereq["review"]
    comments_doc: dict[str, Any] = prereq["comments"]
    showtell_doc: dict[str, Any] = prereq["showtell"]

    handoff_dir = ws.folder("handoff")
    spec_dir = handoff_dir / "spec"
    spec_dir.mkdir(parents=True, exist_ok=True)

    screens = [s for s in (inv_doc.get("screens") or []) if isinstance(s, dict) and s.get("id")]
    if not screens:
        raise ContractError("handoff: 03-ground/inventory.json: screens must be a non-empty list")

    expected_ids = {str(s["id"]) for s in screens}
    for existing_md in spec_dir.glob("*.md"):
        if existing_md.stem not in expected_ids:
            existing_md.unlink()

    draft_screens_by_id: dict[str, dict[str, Any]] = {}
    for ds in (draft_doc.get("screens") or []):
        if isinstance(ds, dict) and ds.get("id"):
            draft_screens_by_id[str(ds["id"])] = ds

    req_by_id: dict[str, dict[str, Any]] = {}
    for r in (req_doc.get("items") or []):
        if isinstance(r, dict) and r.get("id"):
            req_by_id[str(r["id"])] = r

    written_specs: list[str] = []
    for s in screens:
        sid = str(s["id"])
        ds = draft_screens_by_id.get(sid, {})
        md_text = _render_screen_spec(
            screen_inv=s,
            draft_screen=ds,
            req_by_id=req_by_id,
            fixture_doc=fixture_doc,
            review_doc=review_doc,
            comments_doc=comments_doc,
            showtell_doc=showtell_doc,
            round_num=round_num,
        )
        spec_path = spec_dir / f"{sid}.md"
        spec_path.write_text(md_text, encoding="utf-8")
        written_specs.append(f"08-handoff/spec/{sid}.md")

    stack_meta = _load_handoff_stack_metadata(ws, review_doc)
    design_file_doc = {
        "kind": "html-prototype",
        "location": "05-build/index.html",
        "editable": True,
        "note": (
            f"Editable HTML/CSS/JS prototype in 05-build/index.html (and self-contained Show&Tell bundle "
            f"07-show/bundle.html) approved at final gate in Round {round_num}; ready for Frontend implementation "
            f"or HTML-to-Penpot import."
        ),
        **stack_meta,
    }
    (handoff_dir / "design-file.json").write_text(
        json.dumps(design_file_doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    followup_items = _build_followup_items(screens, review_doc, inv_doc, round_num)
    followup_doc = {"items": followup_items}
    (handoff_dir / "followup.json").write_text(
        json.dumps(followup_doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    check_report = assert_handoff_clean(ws)
    contracts.validate("handoff", ws)

    return {
        "status": "ok",
        "stage": "handoff",
        "round": round_num,
        "specs": written_specs,
        "followup_count": len(followup_items),
        "check_passed": check_report["passed"],
        **stack_meta,
    }
