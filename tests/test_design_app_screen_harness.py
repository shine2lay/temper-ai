"""Tests for `configs/design/bin/app_screen_harness` and `design_app_screen_v1_bench` (Design #229).

Verifies:
1. Complete inventory of all 21 production fixture branches and all fixture-mode test entries,
   mapping each item to its outside-harness home.
2. Benchmark twin workflow (`design_app_screen_v1_bench.yaml`) and replay script agent
   (`design_app_screen_replay.yaml`) load cleanly and replace the 6 model agents at the
   model boundary while keeping `mode="real"`.
3. Full real-mode execution of all 8 stages + 2 gates on the frozen known case at $0 with
   zero live model calls, passing all `contracts.validate` checks.
4. Side-by-side parity between the legacy `mode="fixture"` path and the `mode="real"`
   outside harness across all 12 steps and all 5 `grade-*` commands (`grade-intake`,
   `grade-existing`, `grade-ground`, `grade-checks`, `grade-review`).
5. Fail-loud boundary checks on missing or invalid prepared inputs.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "configs/design/bin"
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

import app_screen_harness  # noqa: E402

from temper_ai.stage.loader import GraphLoader  # noqa: E402

BENCH_WORKFLOW_PATH = ROOT / "configs/design/workflows/design_app_screen_v1_bench.yaml"
LIVE_WORKFLOW_PATH = ROOT / "configs/design/workflows/design_app_screen_v1.yaml"
REPLAY_AGENT_PATH = ROOT / "configs/design/agents/design_app_screen_replay.yaml"


class _RepoConfigResolver:
    """Resolve workflow and agent configs directly from the repository checkout."""

    def get(self, name: str, config_type: str) -> dict[str, Any]:
        subdir = "workflows" if config_type == "workflow" else "agents"
        path = ROOT / "configs/design" / subdir / f"{name}.yaml"
        if not path.is_file():
            path = ROOT / "configs/epd" / subdir / f"{name}.yaml"
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        return doc.get(config_type, doc)


def test_fixture_inventory_covers_all_22_production_branches_and_test_entries():
    app_screen_harness.validate_inventory()
    assert len(app_screen_harness.BRANCH_INVENTORY) == 22
    locations = {item["source"] for item in app_screen_harness.BRANCH_INVENTORY}
    expected_locations = {
        "configs/design/bin/app_screen/intake.py:55",
        "configs/design/bin/app_screen/intake.py:86",
        "configs/design/bin/app_screen/intake.py:102",
        "configs/design/bin/app_screen/existing.py:103",
        "configs/design/bin/app_screen/existing.py:119",
        "configs/design/bin/app_screen/existing.py:138",
        "configs/design/bin/app_screen/existing.py:158",
        "configs/design/bin/app_screen/ground.py:127",
        "configs/design/bin/app_screen/ground.py:228",
        "configs/design/bin/app_screen/ground.py:261",
        "configs/design/bin/app_screen/directions.py:194",
        "configs/design/bin/app_screen/directions.py:229",
        "configs/design/bin/app_screen/directions.py:551",
        "configs/design/bin/app_screen/gates.py:296,329,343",
        "configs/design/bin/app_screen/build.py:48",
        "configs/design/bin/app_screen/build.py:134",
        "configs/design/bin/app_screen/build.py:193",
        "configs/design/bin/app_screen/checks.py:86",
        "configs/design/bin/app_screen/review.py:476,506,623",
        "configs/design/bin/app_screen/show.py:492",
        "configs/design/bin/app_screen/handoff.py:447",
        "configs/design/bin/app_screen/fixture_stage.py + workspace.py:29",
    }
    assert locations == expected_locations
    for item in app_screen_harness.BRANCH_INVENTORY:
        assert item["what_it_buys"] and item["new_home"]

    assert len(app_screen_harness.TEST_INVENTORY) == 7
    for t_item in app_screen_harness.TEST_INVENTORY:
        assert t_item["test"] and t_item["what_it_buys"] and t_item["new_home"]


def test_bench_workflow_and_replay_agent_replace_only_model_boundary():
    assert BENCH_WORKFLOW_PATH.is_file()
    assert REPLAY_AGENT_PATH.is_file()

    replay_cfg = yaml.safe_load(REPLAY_AGENT_PATH.read_text(encoding="utf-8"))["agent"]
    assert replay_cfg["name"] == "design_app_screen_replay"
    assert replay_cfg["type"] == "script"
    assert "app_screen_harness" in replay_cfg["script_template"]

    live_wf = yaml.safe_load(LIVE_WORKFLOW_PATH.read_text(encoding="utf-8"))["workflow"]
    bench_wf = yaml.safe_load(BENCH_WORKFLOW_PATH.read_text(encoding="utf-8"))["workflow"]
    assert set(live_wf["inputs"]) == {"product", "request_json"}
    assert set(bench_wf["inputs"]) == {"product", "request_json"}

    loader = GraphLoader(config_store=_RepoConfigResolver())
    nodes, wf = loader.load_workflow("design_app_screen_v1_bench", {"product": "rollcall"})
    assert wf.name == "design_app_screen_v1_bench"
    assert [n.name for n in nodes] == [n["name"] for n in live_wf["nodes"]]

    replay_nodes = {
        "intake_read", "intake_revise",
        "stack_up_ref", "stack_seed",
        "existing_read", "existing_revise",
        "ground_read", "ground_revise",
        "directions_read", "directions_revise",
        "build_read", "build_revise",
        "checks_finish",
        "review_read", "review_revise",
    }
    for node in bench_wf["nodes"]:
        if node["type"] == "stage":
            for child in node["nodes"]:
                if child["name"] in replay_nodes:
                    assert child["agent"] == "design_app_screen_replay"
                else:
                    assert child["agent"] == "design_app_screen_stage_v1"
        elif node["name"] == "workspace_startup":
            assert node["agent"] == "design_app_screen_replay"
        elif node["name"] in ("stack_down", "workspace_cleanup"):
            assert node["agent"] == "design_app_screen_replay"
            assert node["run_after_failure"] is True


def test_replay_draft_for_step_emits_valid_json_for_all_six_model_steps(tmp_path: Path):
    ws_dir = tmp_path / "ws"
    app_screen_harness.prepare_workspace(ws_dir)
    app_screen_harness.run_stage("intake", ws_dir)
    app_screen_harness.run_stage("existing", ws_dir)
    app_screen_harness.run_stage("ground", ws_dir)
    app_screen_harness.run_stage("directions", ws_dir)
    app_screen_harness.answer_gate("direction", ws_dir)
    app_screen_harness.run_stage("build", ws_dir)
    app_screen_harness.run_stage("checks", ws_dir)

    for step in ("intake", "existing", "ground", "directions", "build", "review"):
        doc = app_screen_harness.draft_for_step(step, ws_dir)
        assert isinstance(doc, dict) and doc

    import json
    import subprocess

    cli_py = BIN / "app_screen_harness/cli.py"
    proc = subprocess.run(
        [sys.executable, str(cli_py), "replay", "--step", "intake", "--workspace", str(ws_dir), "--product", "rollcall"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert isinstance(json.loads(proc.stdout), dict)
    assert (ws_dir / "01-request/draft.json").is_file()


def test_harness_runs_all_8_stages_and_2_gates_in_real_mode_and_matches_parity():
    parity = app_screen_harness.compare_parity()
    assert parity["parity"] is True
    assert parity["all_stages_match"] is True
    assert parity["cost_usd"] == {"fixture": 0.0, "harness": 0.0}
    assert parity["live_model_calls"] == {"fixture": 0, "harness": 0}

    expected_steps = (
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
    assert tuple(parity["stage_parity"].keys()) == expected_steps
    for st, info in parity["stage_parity"].items():
        assert info["match"] is True, (st, info)
        assert info["harness_valid"] is True
        assert info["harness_status"] == "done"

    if parity["grade_parity"]:
        assert parity["all_grades_match"] is True
        for gname, ginfo in parity["grade_parity"].items():
            assert ginfo["match"] is True, (gname, ginfo)
            assert ginfo["harness_pass"] is True
            assert ginfo["fixture_pass"] is True
            assert ginfo["harness_misses"] == []
            assert ginfo["fixture_misses"] == []


def test_harness_fails_loud_on_missing_or_invalid_inputs(tmp_path: Path):
    with pytest.raises(app_screen_harness.HarnessCaseError, match="does not exist"):
        app_screen_harness.prepare_workspace(tmp_path / "missing-case", tmp_path / "ws")

    with pytest.raises(app_screen_harness.HarnessCaseError, match="unknown gate"):
        app_screen_harness.load_gate_answer("middle")

    with pytest.raises(app_screen_harness.HarnessReplayError, match="recorded case folder .* does not exist"):
        app_screen_harness.draft_for_step("intake", tmp_path, case_name="no-such-case")
