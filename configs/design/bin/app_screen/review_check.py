"""Stage 6b deterministic draft checker (review_check.py): validate 06-checks/round-<n>/draft.json.

Runs 7 deterministic checks over the fenced review model's draft before review.json is written:
1. review_draft_schema: valid JSON matching schema review_draft in contracts.py.
2. every_measured_item_covered: every M1..Mk item in measured_items.json appears in measured[] exactly once.
3. demoted_blocker_has_reason: any blocker M* item given priority != "must" has a reason >= 15 chars.
4. wont_has_reason: every priority == "wont" item (in measured[] or findings[]) has a non-empty reason.
5. must_has_suggestion: every priority == "must" item (in measured[] or findings[]) has a non-empty suggestion.
6. no_invented_measurement: no model finding in findings[] claims a script-measured metric failure
   (contrast ratio, px font floor, 24x24 target size, axe violation, horizontal scroll) that passed in checks.json.
7. valid_location_and_evidence: every finding in findings[] names a valid screen from 05-build/build.json in
   location and quotes grounded text or elements from that screen in evidence.
"""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

from . import contracts
from .workspace import Workspace

RULES = (
    "review_draft_schema",
    "every_measured_item_covered",
    "demoted_blocker_has_reason",
    "wont_has_reason",
    "must_has_suggestion",
    "no_invented_measurement",
    "valid_location_and_evidence",
)

MIN_DEMOTE_REASON_LEN = 15

# Script-measured failure patterns that belong to Stage 6a checks.json, not model-invented taste findings.
_INVENTED_METRIC_PATTERNS: list[tuple[str, tuple[str, ...], re.Pattern[str]]] = [
    (
        "contrast_ratio",
        ("contrast_text", "contrast_ui"),
        re.compile(
            r"(\b\d+(?:\.\d+)?\s*:\s*1\b|\bcontrast\s+ratio\b|\bfails?\s+(?:wcag\s+|aa\s+)?contrast\b"
            r"|\bbelow\s+(?:wcag\s+|aa\s+)?contrast\b|\bcontrast_(?:text|ui)\b)",
            re.IGNORECASE,
        ),
    ),
    (
        "px_font_floor",
        ("type_floor",),
        re.compile(
            r"(\b(?:1[0-5]|[1-9])\s*px\b|\bfont[- ]size\s+(?:is\s+|of\s+|under\s+|below\s+)?\d+\s*px\b"
            r"|\bbelow\s+16\s*px\b|\btype_floor\b)",
            re.IGNORECASE,
        ),
    ),
    (
        "target_size_24x24",
        ("target_size",),
        re.compile(
            r"(\b24\s*[x×]\s*24\b|\b\d+\s*[x×]\s*\d+\s*px\b"
            r"|\b(?:tap|touch)\s+target\s+(?:is\s+)?(?:too\s+small|under|below|\d+\s*px)\b|\btarget_size\b)",
            re.IGNORECASE,
        ),
    ),
    (
        "axe_violation",
        ("axe_serious",),
        re.compile(
            r"(\baxe(?:-core)?\s+(?:violation|error|failure|serious|critical|rule)\b|\baxe_serious\b)",
            re.IGNORECASE,
        ),
    ),
    (
        "horizontal_scroll",
        ("horizontal_scroll",),
        re.compile(
            r"(\bhorizontal\s+(?:scroll(?:bar|ing)?|overflow)\b|\bscrollwidth\b|\bhorizontal_scroll\b)",
            re.IGNORECASE,
        ),
    ),
]


def _problem(check: str, where: str, message: str) -> dict[str, str]:
    return {"check": check, "where": where, "message": message}


def _norm(text: str) -> str:
    return " ".join((text or "").split()).lower()


def _extract_screen_from_location(location: str, valid_screens: list[str]) -> str | None:
    raw = (location or "").strip()
    if not raw:
        return None
    head = re.split(r"[/:\s@(),]+", raw)[0].strip()
    if head in valid_screens:
        return head
    tokens = [t.strip() for t in re.split(r"[/:\s@(),]+", raw) if t.strip()]
    for tok in tokens:
        if tok in valid_screens:
            return tok
    return None


def _valid_screens(ws: Workspace) -> list[str]:
    ws_step = ws if ws.step else ws.for_step("review")
    screens: list[str] = []
    build_file = ws_step.folder("build") / "build.json"
    if build_file.is_file():
        try:
            bdoc = json.loads(ws_step.read_text(build_file))
        except (OSError, json.JSONDecodeError) as exc:
            raise contracts.ContractError(f"cannot read {build_file}: {exc}") from exc
        for s in bdoc.get("screens") or []:
            if isinstance(s, dict) and isinstance(s.get("id"), str) and s["id"] not in screens:
                screens.append(s["id"])
    inv_file = ws_step.folder("ground") / "inventory.json"
    if inv_file.is_file():
        try:
            idoc = json.loads(ws_step.read_text(inv_file))
        except (OSError, json.JSONDecodeError) as exc:
            raise contracts.ContractError(f"cannot read {inv_file}: {exc}") from exc
        for s in idoc.get("screens") or []:
            if isinstance(s, dict) and isinstance(s.get("id"), str) and s["id"] not in screens:
                screens.append(s["id"])
    return screens


def _screen_ground_phrases(ws: Workspace, screen_id: str) -> tuple[str, list[str]]:
    """Collect grounded strings for a screen from 05-build/draft.json, screens/<id>.js, index.html, and measures.json."""
    ws_step = ws if ws.step else ws.for_step("review")
    phrases: list[str] = []
    build_dir = ws_step.folder("build")

    draft_file = build_dir / "draft.json"
    if draft_file.is_file():
        try:
            ddoc = json.loads(ws_step.read_text(draft_file))
        except (OSError, json.JSONDecodeError) as exc:
            raise contracts.ContractError(f"cannot read {draft_file}: {exc}") from exc
        for s in ddoc.get("screens") or []:
            if isinstance(s, dict) and s.get("id") == screen_id:
                for key in ("id", "title", "lead", "layout"):
                    val = s.get(key)
                    if isinstance(val, str) and val.strip():
                        phrases.append(val.strip())
                states = s.get("states") or {}
                if isinstance(states, dict):
                    for st_name, st_obj in states.items():
                        phrases.append(str(st_name))
                        if isinstance(st_obj, dict):
                            for k in ("headline", "summary", "badge"):
                                v = st_obj.get(k)
                                if isinstance(v, str) and v.strip():
                                    phrases.append(v.strip())
                for sh in s.get("shows") or []:
                    if isinstance(sh, dict):
                        for k in ("ref", "heading", "copy"):
                            v = sh.get(k)
                            if isinstance(v, str) and v.strip():
                                phrases.append(v.strip())
                        for fp in sh.get("fields") or []:
                            if isinstance(fp, str) and fp.strip():
                                phrases.append(fp.strip())
                for act in s.get("actions") or []:
                    if isinstance(act, dict):
                        for k in ("id", "label", "feedback"):
                            v = act.get(k)
                            if isinstance(v, str) and v.strip():
                                phrases.append(v.strip())

    js_file = build_dir / "screens" / f"{screen_id}.js"
    if js_file.is_file():
        try:
            js_text = ws_step.read_text(js_file)
        except OSError as exc:
            raise contracts.ContractError(f"cannot read {js_file}: {exc}") from exc
        phrases.append(js_text)
        for m in re.finditer(r'"([^"\\]*(?:\\.[^"\\]*)*)"|\'([^\'\\]*(?:\\.[^\'\\]*)*)\'', js_text):
            lit = (m.group(1) or m.group(2) or "").strip()
            if len(lit) >= 4:
                phrases.append(lit)

    html_file = build_dir / "index.html"
    if html_file.is_file():
        try:
            phrases.append(ws_step.read_text(html_file))
        except OSError as exc:
            raise contracts.ContractError(f"cannot read {html_file}: {exc}") from exc

    measures_file = ws_step.round_folder() / "measures.json"
    if measures_file.is_file():
        try:
            mdoc = json.loads(ws_step.read_text(measures_file))
        except (OSError, json.JSONDecodeError) as exc:
            raise contracts.ContractError(f"cannot read {measures_file}: {exc}") from exc
        measured_map = mdoc.get("measured")
        view_entries = (
            list(measured_map.values())
            if isinstance(measured_map, dict)
            else (mdoc.get("views") or [])
        )
        for v in view_entries:
            if isinstance(v, dict) and v.get("screen") == screen_id:
                m = v.get("measures") or {}
                mp = v.get("mp") or {}
                for t in (m.get("texts") or []) + (mp.get("runs") or []):
                    if isinstance(t, dict) and isinstance(t.get("text"), str) and t["text"].strip():
                        phrases.append(t["text"].strip())
                    elif isinstance(t, str) and t.strip():
                        phrases.append(t.strip())
                for b in (m.get("Interactive") or m.get("controls") or []) + (v.get("tab_stops") or []):
                    if isinstance(b, dict):
                        for key in ("text", "name"):
                            if isinstance(b.get(key), str) and b[key].strip():
                                phrases.append(b[key].strip())

    corpus_norm = _norm(" ".join(phrases))
    distinct_phrases = []
    seen: set[str] = set()
    for p in phrases:
        np = _norm(p)
        if len(np) >= 4 and np not in seen:
            seen.add(np)
            distinct_phrases.append(np)
    return corpus_norm, distinct_phrases


def _is_evidence_grounded(evidence: str, corpus_norm: str, distinct_phrases: list[str]) -> bool:
    ev_norm = _norm(evidence)
    if len(ev_norm) < 3 or not corpus_norm:
        return False
    if ev_norm in corpus_norm:
        return True
    # Check any quoted span inside evidence ("..." or '...')
    for m in re.finditer(r'"([^"]{4,})"|\'([^\']{4,})\'', evidence):
        span = _norm(m.group(1) or m.group(2) or "")
        if len(span) >= 4 and span in corpus_norm:
            return True
    # Check if any grounded phrase (>= 5 chars) from the screen appears verbatim in evidence
    for gp in distinct_phrases:
        if len(gp) >= 5 and gp in ev_norm:
            return True
    # Check clauses separated by punctuation
    for clause in re.split(r"[:;—–|()\[\]]+", evidence):
        cn = _norm(clause)
        if len(cn) >= 8 and cn in corpus_norm:
            return True
    return False


def _failed_checks_by_screen(ws: Workspace) -> tuple[set[str], dict[str, set[str]]]:
    """Return (all_failed_check_families, failed_check_families_by_screen) from 06-checks/round-<n>/checks.json."""
    ws_step = ws if ws.step else ws.for_step("review")
    all_failed: set[str] = set()
    by_screen: dict[str, set[str]] = {}
    checks_file = ws_step.round_folder() / "checks.json"
    if not checks_file.is_file():
        return all_failed, by_screen
    try:
        cdoc = json.loads(ws_step.read_text(checks_file))
    except (OSError, json.JSONDecodeError) as exc:
        raise contracts.ContractError(f"cannot read {checks_file}: {exc}") from exc
    for row in cdoc.get("checks") or []:
        if isinstance(row, dict) and row.get("result") == "fail":
            cid = str(row.get("id") or "")
            fam = cid.split(".")[0]
            all_failed.add(cid)
            all_failed.add(fam)
            scr = str(row.get("screen") or "")
            if not scr and isinstance(row.get("location"), str):
                scr = row["location"].split("/")[0].split(":")[0].strip()
            if scr:
                by_screen.setdefault(scr, set()).update({cid, fam})
    return all_failed, by_screen


def load_measured_items(ws: Workspace) -> list[dict[str, Any]]:
    ws_step = ws if ws.step else ws.for_step("review")
    path = ws_step.round_folder() / "measured_items.json"
    if not path.is_file():
        return []
    try:
        doc = json.loads(ws_step.read_text(path))
    except (OSError, json.JSONDecodeError) as exc:
        raise contracts.ContractError(f"cannot read {path}: {exc}") from exc
    items = doc.get("items")
    return [it for it in items if isinstance(it, dict)] if isinstance(items, list) else []


def check_draft(
    ws: Workspace,
    draft: Any,
    *,
    pass_name: str = "draft",
    measured_items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run all 7 Stage 6b rules over draft and return the review_check report dict."""
    problems: list[dict[str, str]] = []
    rel_draft = f"06-checks/round-{ws.round}/draft.json"
    items = measured_items if measured_items is not None else load_measured_items(ws)
    items_by_id = {str(it["id"]): it for it in items if isinstance(it, dict) and "id" in it}
    expected_ids = [str(it["id"]) for it in items if isinstance(it, dict) and "id" in it]

    # Rule 1: review_draft_schema
    if not isinstance(draft, dict) or "unreadable" in draft:
        reason = draft.get("unreadable", "not a JSON object") if isinstance(draft, dict) else "not a JSON object"
        problems.append(_problem("review_draft_schema", rel_draft, str(reason)))
        return _build_report(pass_name, items, [], [], problems)

    schema_errs = contracts.check_json("review_draft", draft, rel_draft)
    for err in schema_errs:
        problems.append(_problem("review_draft_schema", rel_draft, err))

    raw_measured = draft.get("measured") if isinstance(draft.get("measured"), list) else []
    raw_findings = draft.get("findings") if isinstance(draft.get("findings"), list) else []

    # Rule 2: every_measured_item_covered
    seen_ids: set[str] = set()
    for idx, entry in enumerate(raw_measured):
        if not isinstance(entry, dict):
            continue
        mid = str(entry.get("id") or "")
        if not mid:
            continue
        if mid in seen_ids:
            problems.append(
                _problem(
                    "every_measured_item_covered",
                    f"measured[{idx}].id",
                    f"duplicate entry for measured item {mid}",
                )
            )
        seen_ids.add(mid)
        if mid not in items_by_id:
            problems.append(
                _problem(
                    "every_measured_item_covered",
                    f"measured[{idx}].id",
                    f"{mid} is not a measured item in measured_items.json (expected: {', '.join(expected_ids) or 'none'})",
                )
            )

    for mid in expected_ids:
        if mid not in seen_ids:
            it = items_by_id[mid]
            problems.append(
                _problem(
                    "every_measured_item_covered",
                    f"measured[{mid}]",
                    f"missing decision for measured item {mid} ({it.get('check')} on {it.get('screen')}, severity={it.get('severity')})",
                )
            )

    # Rules 3, 4, 5 on measured[]
    for idx, entry in enumerate(raw_measured):
        if not isinstance(entry, dict):
            continue
        mid = str(entry.get("id") or f"#{idx}")
        prio = str(entry.get("priority") or "")
        reason = str(entry.get("reason") or "").strip()
        suggestion = str(entry.get("suggestion") or "").strip()
        item = items_by_id.get(mid)

        # Rule 3: demoted_blocker_has_reason
        if item and item.get("severity") == "blocker" and prio and prio != "must":
            if len(reason) < MIN_DEMOTE_REASON_LEN:
                problems.append(
                    _problem(
                        "demoted_blocker_has_reason",
                        f"measured[{mid}].reason",
                        f"blocker {mid} ({item.get('check')} on {item.get('screen')}) demoted to {prio!r} "
                        f"requires a reason of at least {MIN_DEMOTE_REASON_LEN} characters",
                    )
                )

        # Rule 4: wont_has_reason
        if prio == "wont" and not reason:
            problems.append(
                _problem(
                    "wont_has_reason",
                    f"measured[{mid}].reason",
                    f"measured item {mid} rated 'wont' requires a non-empty reason",
                )
            )

        # Rule 5: must_has_suggestion
        if prio == "must" and not suggestion:
            problems.append(
                _problem(
                    "must_has_suggestion",
                    f"measured[{mid}].suggestion",
                    f"measured item {mid} rated 'must' requires a non-empty suggestion",
                )
            )

    # Rules 4, 5, 6, 7 on findings[]
    valid_screens = _valid_screens(ws)
    all_failed_checks, failed_by_screen = _failed_checks_by_screen(ws)
    ground_cache: dict[str, tuple[str, list[str]]] = {}

    for idx, f in enumerate(raw_findings):
        if not isinstance(f, dict):
            continue
        where_prefix = f"findings[{idx}]"
        prio = str(f.get("priority") or "")
        reason = str(f.get("reason") or "").strip()
        suggestion = str(f.get("suggestion") or "").strip()
        element = str(f.get("element") or "").strip()
        location = str(f.get("location") or "").strip()
        evidence = str(f.get("evidence") or "").strip()

        # Rule 4: wont_has_reason
        if prio == "wont" and not reason:
            problems.append(
                _problem(
                    "wont_has_reason",
                    f"{where_prefix}.reason",
                    f"finding at {location or where_prefix} rated 'wont' requires a non-empty reason",
                )
            )

        # Rule 5: must_has_suggestion
        if prio == "must" and not suggestion:
            problems.append(
                _problem(
                    "must_has_suggestion",
                    f"{where_prefix}.suggestion",
                    f"finding at {location or where_prefix} rated 'must' requires a non-empty suggestion",
                )
            )

        # Rule 7a: valid_location_and_evidence (location names a valid screen)
        screen_id = _extract_screen_from_location(location, valid_screens)
        if not screen_id:
            problems.append(
                _problem(
                    "valid_location_and_evidence",
                    f"{where_prefix}.location",
                    f"location {location!r} does not name a valid screen in 05-build/build.json "
                    f"(valid screens: {', '.join(valid_screens) or 'none'})",
                )
            )
        else:
            # Rule 7b: valid_location_and_evidence (evidence quotes grounded text/elements from that screen)
            if screen_id not in ground_cache:
                ground_cache[screen_id] = _screen_ground_phrases(ws, screen_id)
            corpus_norm, distinct_phrases = ground_cache[screen_id]
            if not _is_evidence_grounded(evidence, corpus_norm, distinct_phrases):
                problems.append(
                    _problem(
                        "valid_location_and_evidence",
                        f"{where_prefix}.evidence",
                        f"evidence {evidence[:100]!r} does not quote grounded text or elements from screen {screen_id!r}",
                    )
                )

        # Rule 6: no_invented_measurement
        combined_text = f"{element} {evidence} {suggestion} {reason}"
        screen_failed = failed_by_screen.get(screen_id, set()) if screen_id else all_failed_checks
        for metric_label, check_fams, pattern in _INVENTED_METRIC_PATTERNS:
            match = pattern.search(combined_text)
            if match and not any(cf in screen_failed for cf in check_fams):
                problems.append(
                    _problem(
                        "no_invented_measurement",
                        f"{where_prefix}.evidence",
                        f"finding claims script-measured failure ({metric_label}: {match.group(0)!r}) "
                        f"that passed in checks.json; script-measured checks belong in measured[]",
                    )
                )

    return _build_report(pass_name, items, raw_measured, raw_findings, problems)


def _build_report(
    pass_name: str,
    measured_items: list[dict[str, Any]],
    raw_measured: list[Any],
    raw_findings: list[Any],
    problems: list[dict[str, str]],
) -> dict[str, Any]:
    must_count = sum(
        1
        for x in (*raw_measured, *raw_findings)
        if isinstance(x, dict) and x.get("priority") == "must"
    )
    return {
        "stage": "review",
        "pass": pass_name,
        "verdict": "retry" if problems else "ok",
        "checked_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "checks": list(RULES),
        "counts": {
            "measured_items": len(measured_items),
            "measured_graded": len([x for x in raw_measured if isinstance(x, dict)]),
            "taste_findings": len([x for x in raw_findings if isinstance(x, dict)]),
            "must": must_count,
            "problems": len(problems),
        },
        "problems": problems,
    }
