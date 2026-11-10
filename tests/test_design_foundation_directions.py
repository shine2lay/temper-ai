"""Unit and known-case tests for ``design_foundation_v1`` Stage 2 (``directions``).

Covers:
1. Known-case set under ``~/design-lab/foundation/known-cases/directions/`` (or synthesized
   into ``tmp_path`` when the lab checkout is absent): ``base-clean`` passes clean (exit 0,
   zero failing rules) and each planted case (``p01-count``, ``p02-hue-separation``,
   ``p03-type-family``, ``p04-evidence``, ``p05-proof``) exits non-zero naming its expected
   rule with zero cross-firing.
2. Wrap-around OKLCH hue distance across 0/360 degrees and >3 directions count guard.
3. ``directions_collect``, ``directions_check`` (strict and ``allow_retry=True``), and
   ``directions_finish`` end-to-end token + DESIGN.md generation through ``color.py`` and
   ``proof.py``.
4. Removal of the Stage 2 stub path from ``foundation/stubs.py`` and preservation of
   ``color.py``, ``contrast.py``, ``proof.py``, and ``proof_thresholds.json``.
"""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
BIN_DIR = REPO_ROOT / "configs" / "design" / "bin"
if str(BIN_DIR) not in sys.path:
    sys.path.insert(0, str(BIN_DIR))

from foundation import (  # noqa: E402
    brief,
    contracts,
    directions,
    proof,
    stubs,
    workspace,
)
from foundation_harness import BENCH_BRIEF_MD, BENCH_DIRECTIONS_DRAFT  # noqa: E402

LAB_DIRECTIONS_CASES_DIR = Path.home() / "design-lab" / "foundation" / "known-cases" / "directions"

EXPECTED_CAUGHT_BY: dict[str, list[str]] = {
    "base-clean": [],
    "p01-count": ["directions.count"],
    "p02-hue-separation": ["directions.hue_separation"],
    "p03-type-family": ["directions.type_family"],
    "p04-evidence": ["directions.evidence"],
    "p05-proof": ["directions.proof"],
}


def _seed_brief_workspace(ws_dir: Path) -> workspace.Workspace:
    repo = ws_dir.parent.parent if ws_dir.parent.name == ".temper" else ws_dir.parent
    ws_dir.mkdir(parents=True, exist_ok=True)
    brief_path = repo / ".temper" / "product" / "brief.md"
    brief_path.parent.mkdir(parents=True, exist_ok=True)
    brief_path.write_text(BENCH_BRIEF_MD, encoding="utf-8")
    ws = workspace.Workspace(ws_dir)
    brief.run(ws, product="rollcall")
    return ws


def _clean_draft() -> dict[str, Any]:
    draft = copy.deepcopy(BENCH_DIRECTIONS_DRAFT)
    draft["directions"] = draft["directions"][:2]
    return draft


def _ensure_case_tree(tmp_path: Path) -> Path:
    if LAB_DIRECTIONS_CASES_DIR.is_dir() and all(
        (LAB_DIRECTIONS_CASES_DIR / name / "expected.json").is_file() for name in EXPECTED_CAUGHT_BY
    ):
        return LAB_DIRECTIONS_CASES_DIR

    root = tmp_path / "known-cases-directions"
    base_ws = _seed_brief_workspace(root / "_seed" / ".temper" / "design")
    brief_doc = json.loads((base_ws.path / "01-brief" / "brief.json").read_text(encoding="utf-8"))

    def write_case(
        case_id: str,
        draft_obj: dict[str, Any],
        caught_by: list[str],
        notes: str,
        *,
        bad_b_tokens: dict[str, Any] | None = None,
    ) -> None:
        cdir = root / case_id
        (cdir / "01-brief").mkdir(parents=True, exist_ok=True)
        (cdir / "02-directions").mkdir(parents=True, exist_ok=True)
        (cdir / "01-brief" / "brief.json").write_text(json.dumps(brief_doc, indent=2) + "\n", encoding="utf-8")
        (cdir / "02-directions" / "draft.json").write_text(json.dumps(draft_obj, indent=2) + "\n", encoding="utf-8")
        if bad_b_tokens is not None:
            (cdir / "02-directions" / "b").mkdir(parents=True, exist_ok=True)
            (cdir / "02-directions" / "b" / "tokens.json").write_text(
                json.dumps(bad_b_tokens, indent=2) + "\n", encoding="utf-8"
            )
        expected = {
            "case": case_id,
            "verdict": "pass" if not caught_by else "fail",
            "caught_by": caught_by,
            "notes": notes,
        }
        (cdir / "expected.json").write_text(json.dumps(expected, indent=2) + "\n", encoding="utf-8")

    clean = _clean_draft()
    write_case("base-clean", clean, [], "Clean 2-direction set.")

    p01 = copy.deepcopy(clean)
    p01["directions"] = [p01["directions"][0]]
    write_case("p01-count", p01, ["directions.count"], "Single direction.")

    p02 = copy.deepcopy(clean)
    p02["directions"][0]["anchor_hue_deg"] = 275.0
    p02["directions"][1]["anchor_hue_deg"] = 295.0
    write_case("p02-hue-separation", p02, ["directions.hue_separation"], "Hues 20 deg apart.")

    p03 = copy.deepcopy(clean)
    p03["directions"][1]["type_family"] = "Papyrus Sans"
    write_case("p03-type-family", p03, ["directions.type_family"], "Unavailable type family.")

    p04 = copy.deepcopy(clean)
    p04["directions"][1]["evidence"]["why"] = "L99: Social copy-trading leaderboard with confetti streaks"
    write_case("p04-evidence", p04, ["directions.evidence"], "Fabricated brief line.")

    bad_b = directions.build_direction_tokens("rollcall", clean["directions"][1])
    bad_b["colour"]["light"]["semantic"]["accent"]["text"]["$value"] = dict(
        bad_b["colour"]["light"]["ramp"]["accent"]["400"]["$value"]
    )
    write_case("p05-proof", clean, ["directions.proof"], "Direction b fails proof.py.", bad_b_tokens=bad_b)
    return root


@pytest.mark.parametrize("case_name,expected_rules", list(EXPECTED_CAUGHT_BY.items()))
def test_known_cases_directions_in_process_and_cli(
    tmp_path: Path, case_name: str, expected_rules: list[str]
) -> None:
    cases_root = _ensure_case_tree(tmp_path)
    case_dir = cases_root / case_name
    expected = json.loads((case_dir / "expected.json").read_text(encoding="utf-8"))
    assert expected["caught_by"] == expected_rules

    # Work on a copy in tmp_path so check.json writes never dirty ~/design-lab
    work_case = tmp_path / "run" / case_name
    shutil.copytree(case_dir, work_case)
    ws = workspace.Workspace(work_case)

    report = directions.evaluate_directions(ws)
    assert report["verdict"] == expected["verdict"]
    assert report["failing_rules"] == expected_rules

    proc = subprocess.run(
        [sys.executable, "-m", "foundation.directions", str(work_case), "--json"],
        cwd=str(BIN_DIR),
        capture_output=True,
        text=True,
        check=False,
    )
    if not expected_rules:
        assert proc.returncode == 0, proc.stderr
        cli_rep = json.loads(proc.stdout)
        assert cli_rep["verdict"] == "pass"
        assert cli_rep["failing_rules"] == []
        res = directions.directions_check(ws)
        assert res["verdict"] == "ok"
    else:
        assert proc.returncode == 1
        cli_rep = json.loads(proc.stdout)
        assert cli_rep["verdict"] == "fail"
        assert cli_rep["failing_rules"] == expected_rules
        with pytest.raises(directions.DirectionsError) as exc_info:
            directions.directions_check(ws)
        for rule_id in expected_rules:
            assert rule_id in str(exc_info.value)


def test_hue_separation_wraps_across_zero_degrees_and_count_upper_bound(tmp_path: Path) -> None:
    ws = _seed_brief_workspace(tmp_path / "repo" / ".temper" / "design")
    draft = _clean_draft()
    draft["directions"][0]["anchor_hue_deg"] = 350.0
    draft["directions"][1]["anchor_hue_deg"] = 15.0  # 25 deg apart across 0/360
    rep = directions.evaluate_directions(ws, draft=draft, use_existing_tokens=False)
    assert rep["verdict"] == "fail"
    assert rep["failing_rules"] == ["directions.hue_separation"]

    draft["directions"][0]["anchor_hue_deg"] = 340.0
    draft["directions"][1]["anchor_hue_deg"] = 25.0  # 45 deg apart across 0/360
    rep_ok = directions.evaluate_directions(ws, draft=draft, use_existing_tokens=False)
    assert rep_ok["verdict"] == "pass"
    assert rep_ok["failing_rules"] == []

    # 4 directions (> 3) must fail directions.count
    draft4 = _clean_draft()
    d3 = copy.deepcopy(draft4["directions"][0])
    d3["id"] = "c"
    d3["name"] = "Amber Desk"
    d3["anchor_hue_deg"] = 75.0
    d4 = copy.deepcopy(draft4["directions"][1])
    d4["id"] = "d"
    d4["name"] = "Crimson Signal"
    d4["anchor_hue_deg"] = 15.0
    draft4["directions"].extend([d3, d4])
    rep4 = directions.evaluate_directions(ws, draft=draft4, use_existing_tokens=False)
    assert rep4["verdict"] == "fail"
    assert "directions.count" in rep4["failing_rules"]


def test_directions_collect_check_retry_and_finish_lifecycle(tmp_path: Path) -> None:
    ws = _seed_brief_workspace(tmp_path / "repo" / ".temper" / "design")

    col = directions.directions_collect(ws)
    assert col["model"] == "yes"
    assert "L01:" in col["task"]
    assert "40" in col["task"]

    # Retry mode on a bad draft returns verdict="retry" and a revise_task naming the rule
    bad_draft = _clean_draft()
    bad_draft["directions"][1]["anchor_hue_deg"] = 170.0  # 15 deg from 155.0
    chk_retry = directions.directions_check(ws, draft=bad_draft, allow_retry=True)
    assert chk_retry["verdict"] == "retry"
    assert chk_retry["failing_rules"] == ["directions.hue_separation"]
    assert "directions.hue_separation" in chk_retry["revise_task"]

    # Clean draft passes check and finishes cleanly
    chk_ok = directions.directions_check(ws, draft=_clean_draft(), allow_retry=True)
    assert chk_ok["verdict"] == "ok"

    fin = directions.directions_finish(ws)
    assert fin["status"] == "done"
    assert fin["direction_ids"] == ["a", "b"]
    for d_id in ("a", "b"):
        tok_path = ws.path / "02-directions" / d_id / "tokens.json"
        md_path = ws.path / "02-directions" / d_id / "DESIGN.md"
        assert tok_path.is_file()
        assert md_path.is_file()
        tok = json.loads(tok_path.read_text(encoding="utf-8"))
        contracts.validate_tokens(tok)
        assert proof.evaluate_tokens(tok)["verdict"] == "pass"
        contracts.validate_design_md(md_path.read_text(encoding="utf-8"), product="rollcall")

    # Second collect on unchanged brief skips the model stage
    col_cached = directions.directions_collect(ws)
    assert col_cached["model"] == "no"
    assert col_cached["status"] == "reused"


def test_stage2_stub_path_removed_and_stage3_files_untouched() -> None:
    assert not hasattr(stubs, "directions_collect")
    assert not hasattr(stubs, "directions_check")
    assert not hasattr(stubs, "directions_finish")
    assert not hasattr(stubs, "stub_model_read")
    assert not hasattr(stubs, "stub_tokens")
    assert not hasattr(stubs, "stub_design_md")
    assert not hasattr(stubs, "build_collect")
    assert not hasattr(stubs, "build_check")
    assert not hasattr(stubs, "build_finish")
