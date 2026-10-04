#!/usr/bin/env python3
"""Score finished signal_grade runs against the frozen benchmark (queue #12).

    python3 score.py KEY=WORKSPACE [KEY=WORKSPACE ...] [--out FILE.json]
    python3 score.py --originals      only compare the originals on disk with SOURCES.json

WORKSPACE is one graded run's workspace: it holds state/signal_grade/ (setup.json, check.json,
quality.json) and the report folder setup.json names. For each case this prints, against
expected.json and its matching rule (never edited to fit a grade):

- each required defect: detected or missed, with the finding and the passage that matched;
- forbidden allegations (a failure), allowed items, and every other verified, material
  finding, which the PM adjudicates by hand against the files under the rubric;
- the overall status against the expected one, criteria that ended unknown, the
  required-player result, the deterministic rows (controls must reproduce unflagged), the
  integrity of the graded report files, the counted findings' fields, and the limitations;
- whether the graded report files are byte for byte the case build.py makes from the frozen
  sources.

With every case of expected.json given, it also checks the bar's totals (B1 all 15 required,
B4 23 control rows). A pass here is the mechanical part only: B2 (hand adjudication), B7 cost,
B8 server ids, B9 the PM's manual review and B10 the integration run are recorded apart.
Standard library only; reads, never writes, except the --out file.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("signal_grade_bench_build", HERE / "build.py")
build = importlib.util.module_from_spec(_spec)  # the same frozen sources and mutations
_spec.loader.exec_module(build)

FIELDS = ("criterion", "candidate", "kind", "severity", "claim", "problem")
CONTROL_ROWS = 23


def norm(text: str) -> str:
    """The matching rule's normalisation: markdown emphasis removed, whitespace collapsed."""
    return re.sub(r"\s+", " ", str(text).replace("*", "")).strip()


def same_candidate(item: dict, finding: dict) -> bool:
    return item["candidate"] == "*" or str(finding.get("candidate")) == item["candidate"]


def counts(finding: dict) -> bool:
    return bool(finding.get("verified")) and finding.get("severity") == "material"


def marker_hit(item: dict, finding: dict) -> dict | None:
    markers = [norm(m) for m in item.get("markers", [])]
    for p in finding.get("passages") or []:
        text = norm(p.get("text", ""))
        for m in markers:
            if m and m in text:
                return {"file": p.get("file"), "line": p.get("line"), "marker": m}
    return None


def detects(item: dict, finding: dict) -> dict | None:
    if not counts(finding) or finding.get("criterion") not in item["criteria"]:
        return None
    if not same_candidate(item, finding):
        return None
    return marker_hit(item, finding)


def hits(items: list[dict], finding: dict) -> list[str]:
    return [i["id"] for i in items
            if counts(finding) and finding.get("criterion") in i["criteria"] and same_candidate(i, finding)]


def check_originals() -> list[str]:
    """Originals on disk against the frozen hashes: a changed or missing original is reported."""
    sources = build.frozen()
    problems = []
    for base, info in sources["bases"].items():
        for rel, origin in info["origin"].items():
            path = Path(origin).expanduser()
            want = sources["sha256"].get(f"{base}/{rel}")
            if not path.is_file():
                problems.append(f"original missing: {origin}")
            elif hashlib.sha256(path.read_bytes()).hexdigest() != want:
                problems.append(f"original changed: {origin}")
    return problems


def fixture_problems(case: dict, workspace: Path, setup: dict) -> list[str]:
    report = workspace / setup.get("report_dir", ".")
    problems = []
    for rel, data in build.case_files(case).items():
        path = report / rel
        if not path.is_file():
            problems.append(f"graded report lacks {rel}")
        elif path.read_bytes() != data:
            problems.append(f"graded {rel} differs from the frozen case")
    return problems


def load(workspace: Path) -> tuple[dict, dict]:
    grade = workspace / "state" / "signal_grade"
    setup = json.loads((grade / "setup.json").read_text())
    quality = json.loads((grade / "quality.json").read_text())
    return setup, quality


def score_case(case: dict, workspace: Path) -> dict:
    out = {"case": case["case"], "key": case["key"], "workspace": str(workspace), "problems": []}
    try:
        setup, q = load(workspace)
    except (OSError, ValueError) as exc:
        out["problems"].append(f"no finished grade: {exc}")
        out["ok_mechanical"] = False
        return out
    findings = [f for f in q.get("findings", []) if counts(f)]

    required = []
    detected_by = {}
    for item in case["required"]:
        matches = []
        for f in findings:
            hit = detects(item, f)
            if hit:
                matches.append({"finding": f.get("id"), "source": f.get("source"), "kind": f.get("kind"), **hit})
                detected_by.setdefault(f.get("id"), []).append(item["id"])
        required.append({"id": item["id"], "criteria": item["criteria"], "candidate": item["candidate"],
                         "detected": bool(matches), "matches": matches})

    forbidden, allowed, adjudicate = [], [], []
    for f in findings:
        if f.get("id") in detected_by:
            continue
        row = {"finding": f.get("id"), "source": f.get("source"), "criterion": f.get("criterion"),
               "candidate": f.get("candidate"), "kind": f.get("kind"), "problem": f.get("problem")}
        bad = hits(case["forbidden"], f)
        if bad:
            forbidden.append({**row, "forbidden": bad})
            continue
        ok = hits(case["allowed"], f)
        if ok:
            allowed.append({**row, "allowed": ok})
        else:
            adjudicate.append(row)

    status = q.get("status")
    want = case["expect"]["status"]
    if status == want:
        status_ok = True
    elif want == "pass" and status == "revise" and not forbidden:
        # B3: a control may end revise only through allowed or adjudicated-true findings.
        status_ok = "adjudicate" if adjudicate else True
    else:
        status_ok = False
    unknown = sorted(c for c, v in (q.get("criteria") or {}).items() if v.get("status") == "unknown")
    players = q.get("players")
    missing = None if not players else players.get("missing")
    expect_missing = case["expect"]["players_missing"]
    players_ok = (missing is None and expect_missing is None) or (
        missing is not None and expect_missing is not None and sorted(missing) == sorted(expect_missing))

    rows = (q.get("deterministic") or {}).get("rows") or []
    flagged = [r.get("id") for r in rows if r.get("problems")]
    fields_bad = []
    for f in q.get("findings", []):
        lacking = [k for k in FIELDS if not f.get(k)]
        if not f.get("passages"):
            lacking.append("passages")
        if lacking:
            fields_bad.append(f"{f.get('id')}: {', '.join(lacking)}")
    unverified_counted = [f.get("id") for f in q.get("findings", []) if not f.get("verified")]

    out.update({
        "status": status, "expected_status": want, "status_ok": status_ok,
        "criteria": {c: v.get("status") for c, v in (q.get("criteria") or {}).items()},
        "unknown_criteria": unknown,
        "players_missing": missing, "expected_players_missing": expect_missing, "players_ok": players_ok,
        "required": required, "forbidden": forbidden, "allowed": allowed, "adjudicate": adjudicate,
        "unverified": [{"id": f.get("id"), "criterion": f.get("criterion"), "candidate": f.get("candidate"),
                        "why": f.get("why")} for f in q.get("unverified", [])],
        "rows": len(rows), "flagged_rows": flagged,
        "integrity_unchanged": bool((q.get("integrity") or {}).get("unchanged")),
        "fields_bad": fields_bad, "unverified_counted": unverified_counted,
        "limitations": len(q.get("limitations") or []),
        "rubric_sha256": q.get("rubric_sha256"), "checker_sha256": q.get("checker_sha256"),
    })
    out["problems"] += fixture_problems(case, workspace, setup)
    if case.get("mutant") is None and flagged:
        out["problems"].append(f"control rows flagged: {flagged}")
    out["ok_mechanical"] = bool(
        all(r["detected"] for r in required) and not forbidden and status_ok is True and not unknown
        and players_ok and out["integrity_unchanged"] and not fields_bad and not unverified_counted
        and out["limitations"] > 0 and not out["problems"])
    return out


def report(results: list[dict], totals: dict) -> str:
    lines = []
    for r in results:
        lines.append(f"== {r['case']} ({r['key']}) {r.get('status')} (expected {r.get('expected_status')}): "
                     f"{'OK' if r.get('ok_mechanical') else 'NOT OK'}"
                     + (" [adjudicate]" if r.get("adjudicate") else ""))
        for item in r.get("required", []):
            where = "; ".join(f"{m['finding']} ({m['source']}) {m['file']}:{m['line']} '{m['marker']}'"
                              for m in item["matches"])
            lines.append(f"  {item['id']} {'DETECTED' if item['detected'] else 'MISSED'} {where}")
        for f in r.get("forbidden", []):
            lines.append(f"  FORBIDDEN {f['finding']} {f['criterion']} {f['candidate']} {f['kind']} -> {f['forbidden']}")
        for f in r.get("allowed", []):
            lines.append(f"  allowed {f['finding']} {f['criterion']} {f['candidate']} {f['kind']} -> {f['allowed']}")
        for f in r.get("adjudicate", []):
            lines.append(f"  ADJUDICATE {f['finding']} {f['criterion']} {f['candidate']} {f['kind']}: {f['problem']}")
        if r.get("unknown_criteria"):
            lines.append(f"  unknown criteria: {r['unknown_criteria']}")
        if not r.get("players_ok", True):
            lines.append(f"  players missing {r.get('players_missing')} (expected {r.get('expected_players_missing')})")
        if r.get("unverified"):
            lines.append(f"  unverified (not counted): {[u['id'] for u in r['unverified']]}")
        lines.append(f"  rows {r.get('rows')} flagged {r.get('flagged_rows')}; integrity "
                     f"{'unchanged' if r.get('integrity_unchanged') else 'CHANGED'}; limitations {r.get('limitations')}")
        for p in r.get("problems", []) + [f"fields: {x}" for x in r.get("fields_bad", [])]:
            lines.append(f"  PROBLEM {p}")
    if totals:
        lines.append("== totals: " + json.dumps(totals))
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    if argv == ["--originals"]:
        problems = check_originals()
        print("\n".join(problems) or "originals match SOURCES.json")
        return 1 if problems else 0
    out_path = None
    if "--out" in argv:
        i = argv.index("--out")
        out_path = Path(argv[i + 1])
        argv = argv[:i] + argv[i + 2:]
    if not argv:
        raise SystemExit(__doc__)
    build.check_sources()
    by_key = {c["key"]: c for c in build.cases()}
    results = []
    for arg in argv:
        key, _, path = arg.partition("=")
        if key not in by_key or not path:
            raise SystemExit(f"unknown case key or no workspace: {arg}")
        results.append(score_case(by_key[key], Path(path).expanduser()))
    totals = {}
    if {r["key"] for r in results} == set(by_key):
        required = [i for r in results for i in r.get("required", [])]
        control_rows = sum(r.get("rows", 0) for r in results if by_key[r["key"]].get("mutant") is None)
        totals = {
            "required_detected": sum(1 for i in required if i["detected"]), "required": len(required),
            "forbidden": sum(len(r.get("forbidden", [])) for r in results),
            "adjudicate": sum(len(r.get("adjudicate", [])) for r in results),
            "control_rows": control_rows, "control_rows_expected": CONTROL_ROWS,
            "originals": check_originals() or "match SOURCES.json",
            "cases_ok_mechanical": sum(1 for r in results if r.get("ok_mechanical")), "cases": len(results),
        }
    print(report(results, totals))
    if out_path:
        out_path.write_text(json.dumps({"results": results, "totals": totals}, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
