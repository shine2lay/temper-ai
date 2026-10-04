#!/usr/bin/env python3
"""Score one shape_mvp benchmark pass (queue #11) from the runs' workspaces, mechanically.

    python3 score.py CASE=WORKSPACE [CASE=WORKSPACE ...] [--out score.json]

For each case it reads WORKSPACE/state/shape/ and checks the expected final status and the "must
also" items that can be checked by machine (expected.json). It does not replace the manual review
(M1-M7 in criteria.md): a case passes the bar only when this score and my reading both pass.
Standard library only.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODEL_FILES = ("draft/pitch.json", "critique.json", "pitch.json", "grade.json")


def load(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def rows(value) -> list[dict]:
    return [r for r in value if isinstance(r, dict)] if isinstance(value, list) else []


def score_case(case: dict, workspace: Path) -> dict:
    shape = workspace / "state" / "shape"
    result, setup = load(shape / "result.json"), load(shape / "setup.json")
    fails: list[str] = []
    out = {"case": case["case"], "workspace": str(workspace), "expected": case["expected_final_status"],
           "final_status": (result or {}).get("final_status"), "fails": fails}
    if not isinstance(result, dict) or not isinstance(setup, dict):
        fails.append("result.json or setup.json missing")
        return out
    if result.get("final_status") != case["expected_final_status"]:
        fails.append(f"final status {result.get('final_status')!r}, expected {case['expected_final_status']!r}")
    if result.get("case_id") != case["id"]:
        fails.append(f"case id {result.get('case_id')!r}, expected {case['id']!r}")

    if case["blocked_at"] == "setup":
        codes = {p.get("code") for p in rows(setup.get("problems"))}
        if setup.get("status") != "blocked":
            fails.append("setup did not block")
        for code in case.get("setup_problem_codes", []):
            if code not in codes:
                fails.append(f"setup problems lack {code!r} (got {sorted(codes)})")
        ran = [f for f in MODEL_FILES if (shape / f).exists()]
        if ran:
            fails.append(f"model steps wrote files after a setup block: {ran}")
        return out

    pitch, check, grade = load(shape / "pitch.json"), load(shape / "check.json"), load(shape / "grade.json")
    if setup.get("status") != "ready_to_shape":
        fails.append(f"setup status {setup.get('status')!r}, expected ready_to_shape")
    if not isinstance(pitch, dict):
        fails.append("no final pitch")
        return out
    if (check or {}).get("verdict") != "pass":
        fails.append("deterministic check did not pass")
    if (grade or {}).get("verdict") != "pass" or (grade or {}).get("status_view") != "agree":
        fails.append(f"grade {(grade or {}).get('verdict')!r} / {(grade or {}).get('status_view')!r}")
    elements = rows((pitch.get("solution") or {}).get("elements"))

    if case["blocked_at"] == "model":
        if pitch.get("status") != "blocked":
            fails.append(f"model status {pitch.get('status')!r}, expected blocked")
        if elements:
            fails.append("a blocked record carries solution elements")
        return out

    if pitch.get("status") != "shaped":
        fails.append(f"model status {pitch.get('status')!r}, expected shaped")
    assumptions = rows(pitch.get("assumptions"))
    steps = sorted(rows(pitch.get("verification_plan")), key=lambda s: s.get("order") if isinstance(s.get("order"), int) else 999)
    rank = {s.get("id"): i + 1 for i, s in enumerate(steps)}
    fatal = case.get("fatal_unknowns", [])
    early = max(2, len(fatal) + 1)  # "tested early": within the first max(2, fatal + 1) steps (criteria.md)

    def tested_at(assumption: dict) -> int:
        """Rank of the earliest step that tests it: its `test` pointer or any step listing it (D6)."""
        ids = {assumption.get("test")} | {s.get("id") for s in steps if assumption.get("id") in (s.get("tests") or [])}
        return min(rank.get(i, 999) for i in ids)

    for uid in fatal:
        carried = [a for a in assumptions if uid in (a.get("from_unknowns") or []) and a.get("fatal") is True]
        if not carried:
            fails.append(f"fatal unknown {uid} not kept as a fatal assumption")
        elif min(tested_at(a) for a in carried) > early:
            fails.append(f"fatal unknown {uid} is not tested within the first {early} steps")
    gaps = {g.get("id") for g in rows(pitch.get("owner_input_gaps"))}
    for gap in case.get("owner_gaps", []):
        if gap not in gaps:
            fails.append(f"owner gap {gap} missing")
    for term in case.get("unresolved_prerequisite_terms", []):
        hits = [p for p in rows(pitch.get("prerequisites"))
                if p.get("status") == "unresolved" and term.lower() in json.dumps(p).lower()]
        if not hits:
            fails.append(f"no unresolved prerequisite mentions {term}")
    capacity = (setup.get("capacity") or 0)
    total = sum(float(e.get("estimate_builder_weeks") or 0) for e in elements)
    out["estimate_total"] = round(total, 3)
    out["capacity"] = capacity
    if total > capacity + 1e-9:
        fails.append(f"estimates {total} over capacity {capacity}")
    if case.get("core_features"):
        kept = {f for e in elements for f in (e.get("from_features") or [])}
        for feature in case["core_features"]:
            if feature not in kept:
                fails.append(f"core feature {feature} not kept")
        cut = {c.get("feature") for c in rows(pitch.get("scope_cuts"))} & set(case["cut_from"])
        if len(cut) < case["min_features_cut"]:
            fails.append(f"only {len(cut)} of {case['cut_from']} cut and named (need {case['min_features_cut']})")
        if "P3" in kept:
            fails.append("the Tebra API sync (P3) is kept despite constraint C4")
    if case.get("no_fatal_assumptions") and any(a.get("fatal") is True for a in assumptions):
        fails.append("a fatal assumption without a fatal unknown in the input")
    if case.get("human_steps_required") and not (pitch.get("solution") or {}).get("human_steps"):
        fails.append("no human steps kept")
    if math.isnan(total):
        fails.append("estimate total is not a number")
    return out


def main(argv: list[str]) -> int:
    out_path = None
    if "--out" in argv:
        i = argv.index("--out")
        out_path = Path(argv[i + 1])
        argv = argv[:i] + argv[i + 2:]
    expected = {c["case"]: c for c in json.loads((HERE / "expected.json").read_text())["cases"]}
    scores = []
    for arg in argv:
        name, _, path = arg.partition("=")
        if name not in expected or not path:
            raise SystemExit(f"bad argument {arg!r}: use CASE=WORKSPACE with CASE in {sorted(expected)}")
        scores.append(score_case(expected[name], Path(path)))
    for s in scores:
        print(f"{s['case']}: {'PASS' if not s['fails'] else 'FAIL'} final={s['final_status']} expected={s['expected']}"
              + "".join(f"\n    - {f}" for f in s["fails"]))
    if out_path:
        out_path.write_text(json.dumps(scores, indent=2) + "\n")
    return 0 if all(not s["fails"] for s in scores) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
