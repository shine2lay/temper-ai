#!/usr/bin/env python3
"""Score finished positioning_grade runs against the fixed benchmark (queue #1, Product marketing).

    python3 score.py [--json OUT] KEY=WORKSPACE ...
        Read WORKSPACE/state/positioning_grade/quality.json for each case key and print a table:
        each criterion's status against the expected one, the overall status and the bar items a
        single run settles (B1 controls pass, B2 the labelled criterion is revise with a counted
        material finding on a marked passage, B3 at most one false revise, B6 nothing changed).
        --json writes the per-case result, for --stable. Exit 0 when every given case meets them.
    python3 score.py --stable A.json B.json
        B4: two runs of one grader version give the same overall verdict for every case.

B5 (no web call by the reviewer) and the cost come from temper (events and GET
/api/workflows/ID), not from the workspace. Standard library only.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXPECTED = json.loads((HERE / "expected.json").read_text())
CRITERIA = EXPECTED["criteria"]
CASES = {c["key"]: c for c in EXPECTED["cases"]}


def norm(text: str) -> str:
    """Text as markers are matched: no emphasis marks, straight quotes, one space, any case."""
    text = text.translate(str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"'}))
    return re.sub(r"\s+", " ", re.sub(r"[*_`]", "", text)).strip().lower()


def expected_status(case: dict, criterion: str) -> str:
    if criterion == case["labelled"]:
        return "revise"
    return "pass/revise" if criterion in case["allowed"] else "pass"


def marked_findings(case: dict, quality: dict) -> list[str]:
    """Ids of counted material findings on the labelled criterion whose document passage holds a marker."""
    doc = (quality.get("files") or {}).get("doc")
    markers = [norm(m) for m in case["markers"]]
    hits = []
    for f in quality.get("findings") or []:
        if f.get("criterion") != case["labelled"] or f.get("severity") != "material" or not f.get("verified"):
            continue
        if any(p.get("file") == doc and any(m in norm(str(p.get("text") or "")) for m in markers)
               for p in f.get("passages") or []):
            hits.append(str(f.get("id")))
    return hits


def score_case(key: str, quality: dict | None) -> dict:
    case = CASES[key]
    out = {"key": key, "case": case["case"], "labelled": case["labelled"], "statuses": {}, "overall": None,
           "false_revise": [], "unknown": [], "marked": [], "ok": False, "why": []}
    if quality is None:
        out["why"].append("no quality.json")
        return out
    statuses = {c: (quality.get("criteria") or {}).get(c, {}).get("status") for c in CRITERIA}
    out["statuses"], out["overall"] = statuses, quality.get("status")
    out["unknown"] = [c for c in CRITERIA if statuses[c] == "unknown"]
    if not (quality.get("integrity") or {}).get("unchanged"):
        out["why"].append("B6: files changed while grading")
    if case["labelled"] is None:
        wrong = [c for c in CRITERIA if statuses[c] != "pass"]
        if wrong or out["overall"] != "pass":
            out["why"].append("B1: control not all pass (" + ", ".join(f"{c} {statuses[c]}" for c in wrong)
                              + f"; overall {out['overall']})")
    else:
        out["marked"] = marked_findings(case, quality)
        if statuses[case["labelled"]] != "revise":
            out["why"].append(f"B2: {case['labelled']} is {statuses[case['labelled']]}, not revise")
        elif not out["marked"]:
            out["why"].append(f"B2: no counted material {case['labelled']} finding on a marked document passage")
        out["false_revise"] = [c for c in CRITERIA
                               if statuses[c] == "revise" and c != case["labelled"] and c not in case["allowed"]]
        if len(out["false_revise"]) > 1:
            out["why"].append("B3: false revises " + ", ".join(out["false_revise"]))
    out["ok"] = not out["why"]
    return out


def load_quality(workspace: Path) -> dict | None:
    path = workspace / "state" / "positioning_grade" / "quality.json"
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def cell(case: dict, criterion: str, status: str | None) -> str:
    want = expected_status(case, criterion)
    status = status or "-"
    if status == "revise" and criterion == case["labelled"]:
        return "**revise**"
    return status if status in want.split("/") else f"{status}!"


def table(results: list[dict]) -> str:
    head = "| Case | Key | " + " | ".join(CRITERIA) + " | Overall | Marked finding | False revise | Unknown | Meets bar |"
    rows = [head, "|" + "---|" * (len(CRITERIA) + 7)]
    for r in results:
        case = CASES[r["key"]]
        cells = [cell(case, c, r["statuses"].get(c)) for c in CRITERIA]
        rows.append(f"| {r['case']} | {r['key']} | " + " | ".join(cells) + f" | {r['overall'] or '-'} | "
                    f"{', '.join(r['marked']) or '-'} | {', '.join(r['false_revise']) or '-'} | "
                    f"{', '.join(r['unknown']) or '-'} | {'yes' if r['ok'] else 'NO: ' + '; '.join(r['why'])} |")
    return "\n".join(rows)


def stable(a: Path, b: Path) -> int:
    first = {r["key"]: r for r in json.loads(a.read_text())}
    second = {r["key"]: r for r in json.loads(b.read_text())}
    if set(first) != set(second) or set(first) != set(CASES):
        print(f"B4: the runs cover different cases ({sorted(first)} / {sorted(second)})")
        return 1
    differ = [k for k in sorted(first) if first[k]["overall"] != second[k]["overall"]]
    for k in sorted(first, key=lambda k: CASES[k]["case"]):
        mark = "" if k not in differ else "  <- differs"
        print(f"{CASES[k]['case']} {k}: {first[k]['overall']} / {second[k]['overall']}{mark}")
    print("B4 holds: the same overall verdict for every case" if not differ else f"B4 fails on {len(differ)} cases")
    return 1 if differ else 0


def main(argv: list[str]) -> int:
    if len(argv) == 3 and argv[0] == "--stable":
        return stable(Path(argv[1]), Path(argv[2]))
    out = None
    if argv[:1] == ["--json"]:
        if len(argv) < 2:
            raise SystemExit(__doc__)
        out, argv = Path(argv[1]), argv[2:]
    if not argv:
        raise SystemExit(__doc__)
    results = []
    for arg in argv:
        key, sep, workspace = arg.partition("=")
        if not sep or key not in CASES:
            raise SystemExit(f"{arg}: expected KEY=WORKSPACE with KEY one of {sorted(CASES)}")
        results.append(score_case(key, load_quality(Path(workspace))))
    results.sort(key=lambda r: (CASES[r["key"]]["case"][0] != "C", CASES[r["key"]]["case"]))
    print(table(results))
    met = sum(r["ok"] for r in results)
    print(f"\n{met} of {len(results)} cases meet B1-B3 and B6.")
    if out:
        out.write_text(json.dumps(results, indent=1))
    return 0 if met == len(results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
