"""design_app_screen_v1 Stage 6b: fenced design, UX & language review + loop proof (Design #222).

Tests:
- Agent config validation (design_app_screen_review_v1.yaml passes image_config_errors, no temperature, anthropic-2).
- Workflow YAML parity between design_app_screen_v1_review.yaml and design_app_screen_v1.yaml, preserving review loop_to: build.
- All 7 planted faults caught by review_check.py with their exact check ID, location, and message:
  1. review_draft_schema
  2. every_measured_item_covered
  3. demoted_blocker_has_reason
  4. wont_has_reason
  5. must_has_suggestion
  6. no_invented_measurement
  7. valid_location_and_evidence
- End-to-end Stage 6b pipeline (review_collect -> review_check -> review) in fixture and real modes,
  including contact sheet inline-PNG validation and retry/revision recovery.
- Round-2 loop handoff: build_scaffold.build_task(ws) injects Must findings from round n-1 into 05-build/task.md.
- Deterministic grader (review_grade.py) for clean-parcelly, measured-inkflow, taste-planted, and loop-round-2.
"""
from __future__ import annotations

import copy
import json
import shutil
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "configs/design/bin"
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

import design_app_screen as cli  # noqa: E402
from app_screen import (  # noqa: E402
    build,
    build_scaffold,
    contracts,
    known_case,
    review,
    review_check,
    review_grade,
)
from app_screen.workspace import Workspace  # noqa: E402

from temper_ai.agent.image_input import (  # noqa: E402
    image_config_errors,
    parse_inline_png,
)

MAIN_WF = ROOT / "configs/design/workflows/design_app_screen_v1.yaml"
REVIEW_WF = ROOT / "configs/design/workflows/design_app_screen_v1_review.yaml"
REVIEW_AGENT = ROOT / "configs/design/agents/design_app_screen_review_v1.yaml"
CASE_DIR = ROOT / "tests/design_app_screen_case/rollcall-20261104"


def _make_review_ws(tmp_path: Path, with_measured: bool = True, taste_planted: bool = False) -> Workspace:
    ws_dir = tmp_path / "ws"
    case_name = "taste-planted" if taste_planted else "clean-parcelly"
    review_grade.prepare_trial_workspace(case_name, ws_dir, run_browser_checks=False)
    ws = Workspace(ws_dir)
    round_dir = ws.round_folder(1)
    views_dir = round_dir / "views"
    views_dir.mkdir(parents=True, exist_ok=True)
    for st in ("done", "empty", "loading", "error", "partial"):
        review._write_canonical_png(views_dir / f"home-{st}-390.png", 390, 844)

    checks_rows = [
        {
            "id": "contrast_text",
            "value": {"failures": 1 if with_measured else 0},
            "result": "fail" if with_measured else "pass",
            "evidence": "1 text contrast failure" if with_measured else "0 failures",
            "element": "every view",
            "location": "all",
            "severity": "blocker",
            "summary": True,
            "count": 1 if with_measured else 0,
        },
        {
            "id": "group_spacing",
            "value": {"failures": 1 if with_measured else 0},
            "result": "fail" if with_measured else "pass",
            "evidence": "1 group spacing warning" if with_measured else "0 failures",
            "element": "every view",
            "location": "all",
            "severity": "should",
            "summary": True,
            "count": 1 if with_measured else 0,
        },
    ]
    if with_measured:
        checks_rows.extend([
            {
                "id": "contrast_text",
                "value": 3.1,
                "result": "fail",
                "evidence": "contrast 3.1:1 below 4.5:1 on badge",
                "element": ".state-badge",
                "location": "home/done@390",
                "screen": "home",
                "state": "done",
                "width": 390,
                "severity": "blocker",
            },
            {
                "id": "group_spacing",
                "value": 8,
                "result": "fail",
                "evidence": "gap between cards is 8px, equal to inner padding 8px",
                "element": ".shows-grid",
                "location": "home/done@390",
                "screen": "home",
                "state": "done",
                "width": 390,
                "severity": "should",
            },
        ])
    (round_dir / "checks.json").write_text(
        json.dumps(
            {
                "round": 1,
                "tool": "checks_render.mjs",
                "thresholds": {"contrast_body": 4.5},
                "checks": checks_rows,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (round_dir / "measures.json").write_text(
        json.dumps({"round": 1, "views": []}, indent=2) + "\n",
        encoding="utf-8",
    )
    return ws


def test_review_agent_and_workflow_parity():
    agent_cfg = yaml.safe_load(REVIEW_AGENT.read_text(encoding="utf-8"))["agent"]
    assert image_config_errors(agent_cfg) == []
    assert agent_cfg["provider"] == "anthropic"
    assert agent_cfg["token"] == "anthropic-2"
    assert agent_cfg["model"] == "claude-opus-5-5"
    assert agent_cfg["tools"] == []
    assert "temperature" not in agent_cfg
    assert "temperature" not in agent_cfg.get("provider_config", {})
    assert agent_cfg["image_input"] == {"key": "sheet", "media_type": "image/png"}

    main_nodes = yaml.safe_load(MAIN_WF.read_text(encoding="utf-8"))["workflow"]["nodes"]
    review_nodes = yaml.safe_load(REVIEW_WF.read_text(encoding="utf-8"))["workflow"]["nodes"]
    expected_names = ["review_collect", "review_read", "review_check", "review_revise", "review"]
    assert [n["name"] for n in review_nodes] == expected_names

    main_by_name = {n["name"]: n for n in main_nodes}
    review_stage = main_by_name["review"]
    assert review_stage["type"] == "stage"
    assert review_stage["depends_on"] == ["checks"]
    child_by_name = {n["name"]: n for n in review_stage["nodes"]}
    assert list(child_by_name) == ["review_collect", "review_read", "review_check", "review_revise", "review_finish"]
    assert review_stage["loop_to"] == "build"
    assert review_stage["max_loops"] == 2
    assert review_stage["loop_condition"] == {
        "source": "review.structured.verdict",
        "operator": "equals",
        "value": "revise",
    }


def _valid_measured_draft() -> dict:
    return {
        "measured": [
            {
                "id": "M1",
                "severity": 3,
                "priority": "must",
                "suggestion": "Darken the .state-badge text or background so contrast is at least 4.5:1.",
            },
            {
                "id": "M2",
                "severity": 2,
                "priority": "should",
                "suggestion": "Increase outer .shows-grid gap to 16px so group spacing exceeds inner padding.",
            },
        ],
        "findings": [],
    }


PLANTED_FAULTS = [
    (
        "review_draft_schema",
        lambda d: d.update({"unexpected_field": True}),
        "review_draft_schema",
        "Additional properties are not allowed",
    ),
    (
        "every_measured_item_covered",
        lambda d: d["measured"].pop(0),
        "every_measured_item_covered",
        "missing decision for measured item M1",
    ),
    (
        "demoted_blocker_has_reason",
        lambda d: d["measured"][0].update({"priority": "should", "reason": "too short"}),
        "demoted_blocker_has_reason",
        "blocker M1 (contrast_text on home) demoted to 'should' requires a reason of at least 15 characters",
    ),
    (
        "wont_has_reason",
        lambda d: d["measured"][1].update({"priority": "wont", "reason": ""}),
        "wont_has_reason",
        "requires a non-empty reason",
    ),
    (
        "must_has_suggestion",
        lambda d: d["measured"][0].update({"suggestion": "   "}),
        "must_has_suggestion",
        "requires a non-empty suggestion",
    ),
    (
        "no_invented_measurement",
        lambda d: d["findings"].append(
            {
                "element": "Heading",
                "location": "home/done",
                "evidence": "Evening dispatch ledger is balanced uses 12px font size below 16px",
                "severity": 3,
                "priority": "must",
                "suggestion": "Raise body text to 16px.",
            }
        ),
        "no_invented_measurement",
        "finding claims script-measured failure",
    ),
    (
        "valid_location_and_evidence_unknown_screen",
        lambda d: d["findings"].append(
            {
                "element": "Headline",
                "location": "nonexistent_screen/done",
                "evidence": "Evening dispatch ledger is balanced",
                "severity": 3,
                "priority": "must",
                "suggestion": "Rewrite headline.",
            }
        ),
        "valid_location_and_evidence",
        "does not name a valid screen in 05-build/build.json",
    ),
    (
        "valid_location_and_evidence_ungrounded_quote",
        lambda d: d["findings"].append(
            {
                "element": "Summary",
                "location": "home/done",
                "evidence": "Completely hallucinated copy that does not appear anywhere on the screen",
                "severity": 3,
                "priority": "must",
                "suggestion": "Replace hallucinated copy.",
            }
        ),
        "valid_location_and_evidence",
        "does not quote grounded text or elements from screen",
    ),
]


@pytest.mark.parametrize(
    "name,mutate,expected_check,expected_msg",
    PLANTED_FAULTS,
    ids=[p[0] for p in PLANTED_FAULTS],
)
def test_planted_faults_caught_by_review_check(tmp_path, name, mutate, expected_check, expected_msg):
    ws = _make_review_ws(tmp_path, with_measured=True)
    review.collect(ws)
    good = _valid_measured_draft()
    clean_res = review_check.check_draft(ws, good)
    assert clean_res["verdict"] == "ok" and clean_res["problems"] == []

    bad = copy.deepcopy(good)
    mutate(bad)
    res = review_check.check_draft(ws, bad)
    assert res["verdict"] == "retry", f"{name} was not caught"
    checks_hit = [p["check"] for p in res["problems"]]
    assert expected_check in checks_hit, f"expected {expected_check}, got {res['problems']}"
    assert any(expected_msg in p["message"] for p in res["problems"]), str(res["problems"])


def test_review_pipeline_clean_and_retry_and_loop_handoff(tmp_path):
    # 1. Clean workspace (0 measured items, clean copy) -> verdict "done", must == 0
    ws_clean = _make_review_ws(tmp_path / "clean", with_measured=False)
    col = review.collect(ws_clean)
    assert col["model"] == "yes" and col["measured_items"] == 0
    png_info = parse_inline_png(col["sheet"])
    assert png_info.width <= 1568 and png_info.height <= 1568 and png_info.byte_count <= 180_000

    clean_draft = {"measured": [], "findings": []}
    chk = review.check(ws_clean, json.dumps(clean_draft))
    assert chk["verdict"] == "ok"
    out = review.run(ws_clean, "")
    assert out["verdict"] == "done" and out["must"] == 0
    grade_clean = review_grade.grade("clean-parcelly", ws_clean.path)
    assert grade_clean["pass"], grade_clean

    # 2. Taste-planted workspace + retry recovery -> verdict "revise", then Round 2 build_task includes Must findings
    ws_taste = _make_review_ws(tmp_path / "taste", with_measured=False, taste_planted=True)
    review.collect(ws_taste)
    # First send an invalid draft (missing suggestion on must) -> retry
    broken_draft = {
        "measured": [],
        "findings": [
            {
                "element": "error summary",
                "location": "home/error",
                "evidence": "FATAL auth_token=sk_live_9981_parcelly: SELECT * FROM carrier_manifests WHERE hub_id=NULL failed",
                "severity": 4,
                "priority": "must",
                "suggestion": "",
            }
        ],
    }
    chk_retry = review.check(ws_taste, json.dumps(broken_draft))
    assert chk_retry["verdict"] == "retry" and "must_has_suggestion" in [p["check"] for p in chk_retry["problems"]]

    fixed_draft = {
        "measured": [],
        "findings": [
            {
                "element": "error state summary",
                "location": "home/error",
                "evidence": "FATAL auth_token=sk_live_9981_parcelly: SELECT * FROM carrier_manifests WHERE hub_id=NULL failed",
                "severity": 4,
                "priority": "must",
                "suggestion": "Replace raw SQL and auth_token leak with human recovery guidance.",
            },
            {
                "element": "action_assign label",
                "location": "home/done",
                "evidence": "Submit action_btn_1",
                "severity": 3,
                "priority": "must",
                "suggestion": "Rename button label to 'Assign courier route'.",
            },
            {
                "element": "done summary and S1 copy",
                "location": "home/done",
                "evidence": "Everything is fine, relax and trust the system while we handle things behind the scenes.",
                "severity": 3,
                "priority": "must",
                "suggestion": "Replace reassurance fluff with concrete dispatch ledger summary and parcel counts.",
            },
        ],
    }
    out_revise = review.run(ws_taste, json.dumps(fixed_draft))
    assert out_revise["verdict"] == "revise" and out_revise["must"] == 3 and out_revise["retried"] is True
    grade_taste = review_grade.grade("taste-planted", ws_taste.path)
    assert grade_taste["pass"] and grade_taste["measures"]["caught"] == 3, grade_taste

    # 3. Advance to Round 2 via build.run(ws_taste) (as loop_to: build does): verify Must findings appear in 05-build/task.md
    build.run(ws_taste)
    assert ws_taste.round == 2
    task_r2 = (ws_taste.folder("build") / "task.md").read_text(encoding="utf-8")
    assert "## Must Findings From Round 1 To Fix" in task_r2
    assert "FATAL auth_token=sk_live_9981_parcelly" in task_r2
    assert "Submit action_btn_1" in task_r2
    assert "Everything is fine, relax and trust the system" in task_r2

    # 4. Complete Round 2 clean build + checks + review -> grade("loop-round-2") passes
    clean_r2_draft = review_grade._clean_parcelly_draft()
    (ws_taste.folder("build") / "draft.json").write_text(
        json.dumps(clean_r2_draft, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    build_scaffold.render_draft(ws_taste, clean_r2_draft)
    round2_dir = ws_taste.round_folder(2)
    (round2_dir / "views").mkdir(parents=True, exist_ok=True)
    for st in ("done", "empty", "loading", "error", "partial"):
        review._write_canonical_png(round2_dir / "views" / f"home-{st}-390.png", 390, 844)
    (round2_dir / "checks.json").write_text(
        json.dumps(
            {
                "round": 2,
                "tool": "checks_render.mjs",
                "thresholds": {"contrast_body": 4.5},
                "checks": [
                    {
                        "id": "contrast_text",
                        "value": {"failures": 0},
                        "result": "pass",
                        "evidence": "0 failures",
                        "element": "every view",
                        "location": "all",
                        "severity": "blocker",
                        "summary": True,
                        "count": 0,
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (round2_dir / "measures.json").write_text(json.dumps({"round": 2, "views": []}) + "\n", encoding="utf-8")
    review.collect(ws_taste)
    review.check(ws_taste, json.dumps({"measured": [], "findings": []}))
    out_r2 = review.run(ws_taste, "")
    assert out_r2["verdict"] == "done" and out_r2["must"] == 0
    grade_loop = review_grade.grade("loop-round-2", ws_taste.path)
    assert grade_loop["pass"], grade_loop


def test_review_run_fails_loud_when_revised_draft_still_invalid(tmp_path):
    ws = _make_review_ws(tmp_path / "fail_loud", with_measured=True)
    review.collect(ws)
    broken = {"measured": [], "findings": []}
    chk = review.check(ws, json.dumps(broken))
    assert chk["verdict"] == "retry"
    with pytest.raises(review.ReviewError, match="every_measured_item_covered"):
        review.run(ws, json.dumps(broken))


def test_fixture_mode_review_pipeline(tmp_path):
    case_copy = tmp_path / "case"
    shutil.copytree(CASE_DIR, case_copy)
    known_case.freeze(case_copy, product="rollcall", source="test")
    ws_dir = tmp_path / "ws_fixture"
    ws_dir.mkdir()
    known_case.pack(case_copy, ws_dir)
    ws = Workspace(ws_dir)
    ws.next_round()
    assert cli.run_step("review_collect", str(ws_dir), None, "fixture", "")["model"] == "no"
    assert cli.run_step("review_check", str(ws_dir), None, "fixture", "")["verdict"] == "ok"
    res = cli.run_step("review", str(ws_dir), None, "fixture", "")
    assert res["verdict"] == "done" and res["round"] == 1


def test_group_measured_items_maps_round_level_location_to_valid_id():
    checks_doc = {
        "round": 1,
        "checks": [
            {
                "id": "contract.marks",
                "severity": "blocker",
                "result": "fail",
                "screen": None,
                "element": "[data-screen]",
                "location": "the round",
                "evidence": "no view carries a data-screen root",
            }
        ],
    }
    grouped = review.group_measured_items(checks_doc, ["tracker", "client", "settings"], round_num=1)
    assert len(grouped["items"]) == 1
    assert grouped["items"][0]["screen"] == "tracker"
    assert not contracts.check_json("measured_items", grouped, "06-checks/round-1/measured_items.json")

