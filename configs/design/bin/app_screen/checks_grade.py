"""Grade a checks run against its known case: did it catch every planted fault, and nothing it invented?

One grade per case (rule 16): a planted copy is caught when a failing row names the planted check at the
planted screen, state and width; a row whose rule the case does not allow is a false finding. The digest
is what three runs of the same case are compared by (determinism), taken over the rows only, so times,
screenshots and paths cannot hide a difference.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .checks_host import read_case
from .checks_rules import RULES
from .workspace import Workspace

ANY = "*"


def _rows(checks: dict) -> list[dict]:
    return [r for r in checks["checks"] if not r.get("summary")]


def digest(checks: dict) -> str:
    """The rows as three runs are compared by: rule, place, element, value and evidence."""
    rows = [[r["id"], r.get("screen", ""), r.get("state", ""), r.get("width", 0), r["element"],
             json.dumps(r["value"], sort_keys=True, ensure_ascii=False), r["evidence"]] for r in _rows(checks)]
    rows.sort()
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode()).hexdigest()[:16]


def _matches(row: dict, planted: dict) -> bool:
    if row["id"] != planted["check"] and row["id"].split(".")[0] != planted["check"]:
        return False
    for field in ("screen", "state"):
        want = planted.get(field)
        if want and row.get(field) and row[field] != want:
            return False
    width = planted.get("width")
    return not (width and row.get("width") and int(row["width"]) != int(width))


def grade(case_dir: Path | str, workspace: Path | str) -> dict:
    expected = read_case(case_dir)
    ws = Workspace(workspace)
    path = ws.round_folder(1) / "checks.json"
    if not path.is_file():
        return {"case": expected["case"], "pass": False, "misses": [f"{path} is missing: the run wrote no checks"]}
    checks = json.loads(path.read_text())
    rows = _rows(checks)
    planted = expected.get("planted") or []
    allow = set(expected["expect"].get("allow") or [])
    misses, notes = [], []

    caught = []
    for fault in planted:
        hits = [r for r in rows if _matches(r, fault)]
        caught.append(bool(hits))
        if hits:
            notes.append(f"{fault['id']} {fault['check']}: {len(hits)} row(s), e.g. {hits[0]['evidence'][:140]}")
        else:
            near = sorted({r["id"] for r in rows if r["id"].split(".")[0] == fault["check"].split(".")[0]})
            misses.append(f"{fault['id']} not caught: {fault['check']} at "
                          f"{fault.get('screen', 'any')}/{fault.get('state', 'any')}@{fault.get('width', 'any')} "
                          f"({fault['what'][:90]}); rows of that check: {', '.join(near) or 'none'}")
    planted_checks = {f["check"] for f in planted}

    read = expected.get("read") or {}
    false_rows = []
    if read:
        # A real prototype has nothing planted: the bar is a hand read of every failing rule, recorded in
        # the case as real or false, with no Must-class row read as false.
        for rule in sorted({r["id"] for r in rows}):
            if rule not in read:
                sample = next(r for r in rows if r["id"] == rule)
                misses.append(f"{rule}: not read; {sum(1 for r in rows if r['id'] == rule)} row(s), "
                              f"e.g. {sample['evidence'][:140]}")
        for row in rows:
            if (read.get(row["id"]) or {}).get("verdict") == "false":
                false_rows.append(row)
        false_musts = [r for r in false_rows if r.get("severity") == "blocker"]
        for rule in sorted({r["id"] for r in false_musts}):
            misses.append(f"{rule}: read as a false Must ({sum(1 for r in false_musts if r['id'] == rule)} "
                          f"row(s)): {read[rule].get('why', '')[:140]}")
        for rule, entry in sorted(read.items()):
            notes.append(f"{rule} read as {entry.get('verdict')}: "
                         f"{sum(1 for r in rows if r['id'] == rule)} row(s); {entry.get('why', '')[:160]}")
    elif ANY not in allow:
        for row in rows:
            if row["id"] in allow or row["id"] in planted_checks or row["id"].split(".")[0] in planted_checks:
                continue
            if any(_matches(row, f) for f in planted):
                continue
            false_rows.append(row)
        for row in false_rows[:25]:
            misses.append(f"not allowed: {row['id']} {row.get('screen', '')}/{row.get('state', '')}"
                          f"@{row.get('width', '')} {row['element'][:60]}: {row['evidence'][:140]}")

    by_rule: dict[str, int] = {}
    for row in rows:
        by_rule[row["id"]] = by_rule.get(row["id"], 0) + 1
    blockers = [r for r in rows if r.get("severity") == "blocker"]
    want_blockers = expected["expect"].get("blockers")
    if want_blockers is not None and len(blockers) != want_blockers:
        misses.append(f"{len(blockers)} blocker row(s), the case expects {want_blockers}")
    for family in expected["expect"].get("clean_checks") or []:
        hit = [r for r in rows if r["check"] == family or r["id"].split(".")[0] == family]
        if hit:
            misses.append(f"{family} should be clean here: {len(hit)} row(s), e.g. {hit[0]['evidence'][:120]}")
    for family in expected["expect"].get("must_skip") or []:
        entry = next((r for r in checks["checks"] if r.get("summary") and r["id"] == family), None)
        if not entry or entry["result"] != "skipped":
            misses.append(f"{family} should be skipped here, it is {entry['result'] if entry else 'missing'}")

    recall = sum(caught) / len(caught) if caught else 1.0
    if read:
        real_rows = len(rows) - len(false_rows)
        notes.append(f"precision {real_rows}/{len(rows)} rows real "
                     f"({round(100 * real_rows / len(rows)) if rows else 100}%)")
    unknown = sorted(set(by_rule) - set(RULES))
    if unknown:
        misses.append(f"rows of unknown rule(s): {', '.join(unknown)}")
    return {"case": expected["case"], "pass": not misses,
            "measures": {"planted": len(planted), "caught": sum(caught), "recall": round(recall, 3),
                         "rows": len(rows), "blockers": len(blockers), "false_rows": len(false_rows),
                         "views": checks.get("views"), "digest": digest(checks)},
            "by_rule": dict(sorted(by_rule.items())), "misses": misses, "notes": notes}
