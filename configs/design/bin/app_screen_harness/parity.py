"""Grader runner and side-by-side parity comparator between `app_screen_harness` (`mode="real"`) and `mode="fixture"`.

Runs the five existing deterministic graders (`grade-intake`, `grade-existing`, `grade-ground`,
`grade-checks`, `grade-review`) and compares stage verdicts, contract validations, gate decisions,
and grader verdicts across both paths.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from .cases import DEFAULT_CASE_DIR, load_gate_answer
from .runner import run_all

HERE = Path(__file__).resolve().parent
DESIGN_BIN = HERE.parent
DEFAULT_LAB_CASES = Path("~/design-lab/app-screen-workflow/known-cases").expanduser()


def _ensure_design_bin_on_path() -> None:
    if str(DESIGN_BIN) not in sys.path:
        sys.path.insert(0, str(DESIGN_BIN))


def grade_workspace(workspace_dir: str | Path, lab_cases_dir: str | Path = DEFAULT_LAB_CASES) -> dict[str, dict[str, Any]]:
    """Run all five `grade-*` commands on `workspace_dir`."""
    _ensure_design_bin_on_path()
    from app_screen import (
        checks_grade,
        existing_grade,
        ground_grade,
        intake_grade,
        review_grade,
    )

    ws_path = Path(workspace_dir).expanduser().resolve()
    lab = Path(lab_cases_dir).expanduser().resolve()

    res_intake = intake_grade.grade(lab / "intake/a-rollcall-v2", ws_path)

    with tempfile.TemporaryDirectory() as td:
        ex_case = Path(td) / "a-rollcall"
        shutil.copytree(lab / "existing/a-rollcall", ex_case)
        req_file = ws_path / "01-request/requirements.json"
        if req_file.is_file():
            shutil.copy2(req_file, ex_case / "requirements.json")
        res_existing = existing_grade.grade(ex_case, ws_path)

    design_md = ws_path / "03-ground/design-files/DESIGN.md"
    saved_design_md: bytes | None = None
    if design_md.is_file():
        saved_design_md = design_md.read_bytes()
        design_md.unlink()
    try:
        res_ground = ground_grade.grade(lab / "ground/a-rollcall-v3", ws_path)
    finally:
        if saved_design_md is not None:
            design_md.write_bytes(saved_design_md)

    res_checks = checks_grade.grade(lab / "checks/base-clean", ws_path)
    res_review = review_grade.grade("clean-parcelly", ws_path)

    return {
        "grade-intake": res_intake,
        "grade-existing": res_existing,
        "grade-ground": res_ground,
        "grade-checks": res_checks,
        "grade-review": res_review,
    }


def run_legacy_fixture_all(case_dir: str | Path, workspace_dir: str | Path) -> dict[str, Any]:
    """Run all 8 stages + 2 gates through the legacy `mode="fixture"` path for side-by-side comparison."""
    _ensure_design_bin_on_path()
    import design_app_screen as cli
    from app_screen import contracts, known_case, workspace

    ws_path = Path(workspace_dir).expanduser().resolve()
    ws_path.mkdir(parents=True, exist_ok=True)
    known_case.pack(case_dir, ws_path)

    ws = workspace.Workspace(ws_path)
    results: dict[str, Any] = {}
    for st in ("intake", "existing", "ground", "directions"):
        results[st] = cli.run_step(st, str(ws_path), None, "fixture", "")
    dir_ans = json.dumps(load_gate_answer("direction", case_dir=case_dir, workspace_dir=ws_path), ensure_ascii=False)
    results["gate_direction"] = cli.run_step("gate_direction", str(ws_path), None, "fixture", dir_ans)
    for st in ("build", "checks", "review", "show"):
        results[st] = cli.run_step(st, str(ws_path), None, "fixture", "")
    fin_ans = json.dumps(load_gate_answer("final", case_dir=case_dir, workspace_dir=ws_path), ensure_ascii=False)
    results["gate_final"] = cli.run_step("gate_final", str(ws_path), None, "fixture", fin_ans)
    results["gate_final_next"] = cli.run_step("gate_final_next", str(ws_path), None, "fixture", "")
    results["handoff"] = cli.run_step("handoff", str(ws_path), None, "fixture", "")
    contract_counts: dict[str, int] = {}
    for st in workspace.STAGES + ("gate_direction", "review", "gate_final"):
        contract_counts[st] = len(contracts.validate(st, ws))

    return {
        "ok": True,
        "mode": ws.mode,
        "workspace": str(ws_path),
        "cost_usd": 0.0,
        "live_model_calls": 0,
        "stages": results,
        "run_stages": ws.run().get("stages", {}),
        "contract_files": contract_counts,
    }


def compare_parity(
    case_dir: str | Path | None = None,
    lab_cases_dir: str | Path = DEFAULT_LAB_CASES,
) -> dict[str, Any]:
    """Run both `mode="fixture"` and `app_screen_harness` (`mode="real"`) on the known case and compare verdicts."""
    _ensure_design_bin_on_path()
    from app_screen import known_case

    src_case = Path(case_dir).expanduser().resolve() if case_dir else DEFAULT_CASE_DIR
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        ws_harness = td_path / "ws_harness"
        harness_run = run_all(src_case, ws_harness)

        # Build a complete frozen case from the real stage outputs so legacy fixture mode
        # copies complete stage folders (01-request..08-handoff) and both paths can be
        # compared side-by-side on all 11 stages AND all 5 grade-* commands.
        playable_case = td_path / "case" / src_case.name
        playable_case.mkdir(parents=True, exist_ok=True)
        for folder in (
            "01-request",
            "02-existing",
            "03-ground",
            "04-directions",
            "05-build",
            "06-checks",
            "07-show",
            "08-handoff",
        ):
            shutil.copytree(ws_harness / folder, playable_case / folder, dirs_exist_ok=True)
        if (src_case / "gates").is_dir():
            shutil.copytree(src_case / "gates", playable_case / "gates", dirs_exist_ok=True)
        known_case.freeze(playable_case, "rollcall", "tests/design_app_screen_case/rollcall-20261104")

        ws_fixture = td_path / "ws_fixture"
        fixture_run = run_legacy_fixture_all(playable_case, ws_fixture)
        # known_case.copy_stage("review") only copies review.json; copy check-final.json from known-case
        # so grade-review can inspect the frozen case's final check record as well.
        cf_src = playable_case / "06-checks/round-1/check-final.json"
        cf_dst = ws_fixture / "06-checks/round-1/check-final.json"
        if cf_src.is_file() and not cf_dst.is_file():
            shutil.copy2(cf_src, cf_dst)

        stage_names = (
            "intake",
            "existing",
            "ground",
            "directions",
            "gate_direction",
            "build",
            "checks",
            "review",
            "show",
            "gate_final",
            "gate_final_next",
            "handoff",
        )
        ws_f_run = json.loads((ws_fixture / "run.json").read_text(encoding="utf-8")).get("stages", {})
        ws_h_run = json.loads((ws_harness / "run.json").read_text(encoding="utf-8")).get("stages", {})

        stage_parity: dict[str, dict[str, Any]] = {}
        all_stages_match = True
        for st in stage_names:
            f_st = fixture_run["stages"][st]
            h_st = harness_run["stages"][st]
            f_valid = bool(f_st.get("valid", f_st.get("ok", False)))
            h_valid = bool(h_st.get("valid", h_st.get("ok", False)))
            f_status = ws_f_run.get(st, {}).get("status", "done" if f_valid else "failed")
            h_status = ws_h_run.get(st, {}).get("status", "done" if h_valid else "failed")
            if st in ("gate_direction", "gate_final", "gate_final_next"):
                f_verdict = f_st.get("choice") or f_st.get("verdict") or f_status
                h_verdict = h_st.get("choice") or h_st.get("verdict") or h_status
            elif st == "review":
                f_verdict = f_st.get("verdict", f_status)
                h_verdict = h_st.get("verdict", h_status)
            else:
                f_verdict = f_status
                h_verdict = h_status
            matched = bool(f_valid and h_valid) and (f_status == h_status == "done") and (f_verdict == h_verdict)
            if not matched:
                all_stages_match = False
            stage_parity[st] = {
                "fixture_valid": f_valid,
                "harness_valid": h_valid,
                "fixture_status": f_status,
                "harness_status": h_status,
                "fixture_verdict": f_verdict,
                "harness_verdict": h_verdict,
                "match": matched,
            }

        lab_path = Path(lab_cases_dir).expanduser().resolve()
        grades_harness: dict[str, Any] = {}
        grades_fixture: dict[str, Any] = {}
        grade_parity: dict[str, dict[str, Any]] = {}
        all_grades_match = True
        if lab_path.is_dir():
            grades_harness = grade_workspace(ws_harness, lab_path)
            grades_fixture = grade_workspace(ws_fixture, lab_path)
            for gname in grades_harness:
                gh = grades_harness[gname]
                gf = grades_fixture[gname]
                gmatch = (
                    bool(gh.get("pass")) is True
                    and bool(gf.get("pass")) is True
                    and gh.get("verdict") == gf.get("verdict")
                    and gh.get("misses", []) == gf.get("misses", []) == []
                )
                if not gmatch:
                    all_grades_match = False
                grade_parity[gname] = {
                    "fixture_pass": bool(gf.get("pass")),
                    "harness_pass": bool(gh.get("pass")),
                    "fixture_verdict": gf.get("verdict"),
                    "harness_verdict": gh.get("verdict"),
                    "fixture_misses": gf.get("misses", []),
                    "harness_misses": gh.get("misses", []),
                    "match": gmatch,
                }

        return {
            "parity": all_stages_match and all_grades_match,
            "all_stages_match": all_stages_match,
            "all_grades_match": all_grades_match,
            "fixture_mode": fixture_run["mode"],
            "harness_mode": harness_run["mode"],
            "cost_usd": {"fixture": 0.0, "harness": 0.0},
            "live_model_calls": {"fixture": 0, "harness": 0},
            "stage_parity": stage_parity,
            "grade_parity": grade_parity,
            "contract_files": {
                "fixture": fixture_run["contract_files"],
                "harness": harness_run["contract_files"],
            },
            "grades": {
                "harness": {
                    k: {"pass": v.get("pass"), "verdict": v.get("verdict"), "misses": v.get("misses", [])}
                    for k, v in grades_harness.items()
                },
                "fixture": {
                    k: {"pass": v.get("pass"), "verdict": v.get("verdict"), "misses": v.get("misses", [])}
                    for k, v in grades_fixture.items()
                },
            },
        }
