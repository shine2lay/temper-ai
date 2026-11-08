"""design_app_screen_v1 Stage 4 (directions): unit and planted-fault tests.

Tests cover:
1. Agent and workflow YAML contracts (design_app_screen_directions_v1.yaml, design_app_screen_v1_directions.yaml,
   design_app_screen_v1.yaml).
2. Fixture-mode and real-mode 5-node Stage 4 pipeline (directions_collect -> directions_read ->
   directions_check -> directions_revise -> directions).
3. Compilation of clickable prototypes in 04-directions/<id>/ (reusing build_scaffold.py) and quick measured
   checks in 04-directions/<id>/checks.json (reusing checks_rules.py + checks.py) with 0 blockers.
4. Every planted fault in directions_check.py caught by its named rule:
   - directions_draft_schema (single direction < 2, duplicate direction id, invalid id)
   - distinct_directions (duplicate name, duplicate idea, duplicate primary layout, duplicate normal headline)
   - entry_screen_coverage (missing target entry screen, missing required state)
   - show_and_field_grounding (missing show ref S2, ungrounded fixture field path)
   - state_and_action_quality (duplicate state headline, missing primary action, missing error recovery action,
     hardcoded figures, banned filler copy)
5. Stage 5 build_scaffold.build_task(ws) reading the chosen direction from Stage 4 (04-directions/).
"""
from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "configs/design/bin"
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

from app_screen import (  # noqa: E402
    build_scaffold,
    contracts,
    directions,
    directions_check,
    gates,
)
from app_screen.workspace import Workspace  # noqa: E402

CASE_NAME = "rollcall-20261104"
REPO_CASE = ROOT / "tests/design_app_screen_case" / CASE_NAME
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
HTML = "<!doctype html><title>placeholder</title>\n"


def _load_cli():
    spec = importlib.util.spec_from_file_location("design_app_screen", BIN / "design_app_screen.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CLI = _load_cli()


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def _make_real_ws(tmp_path: Path) -> Workspace:
    """Create a real-mode workspace populated with stages 1..3 from the RollCall known case."""
    ws_dir = tmp_path / "ws"
    ws_dir.mkdir(parents=True, exist_ok=True)
    ws = Workspace(ws_dir)
    ws.start("rollcall", "real")
    for folder in ("01-request", "02-existing", "03-ground"):
        shutil.copytree(REPO_CASE / folder, ws_dir / folder, dirs_exist_ok=True)
    for s in _read(ws_dir / "02-existing/audit.json")["screens"]:
        cap = ws_dir / "02-existing" / s["capture"]
        cap.parent.mkdir(parents=True, exist_ok=True)
        cap.write_bytes(PNG)
    ws.mark("intake", "done")
    ws.mark("existing", "done")
    ws.mark("ground", "done")
    return ws


def _valid_directions_draft(ws: Workspace) -> dict[str, Any]:
    """Construct a clean 2-direction draft (a and b) covering the entry screens of ws."""
    inventory = _read(ws.folder("ground") / "inventory.json")
    fixture = _read(ws.folder("ground") / "fixture.json")
    entry_screens = build_scaffold.select_entry_screens(inventory)

    def make_screens(direction_id: str, primary_layout: str, alt_layout: str, tone_word: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for idx, inv_s in enumerate(entry_screens):
            base = build_scaffold.default_screen_draft(inv_s, fixture)
            base["layout"] = primary_layout if idx == 0 else alt_layout
            base["title"] = f"{base['title']} {tone_word}".strip()
            base["lead"] = f"{tone_word} view for {base['lead']}"
            for st, st_spec in base["states"].items():
                st_spec["headline"] = f"{tone_word}: {st_spec['headline']}"
                st_spec["summary"] = f"{tone_word} path — {st_spec['summary']}"
            for a in base["actions"]:
                if "error" not in a["states"]:
                    a["states"] = list(dict.fromkeys([*a["states"], "error"]))
            out.append(base)
        return out

    return {
        "directions": [
            {
                "id": "a",
                "name": "Morning Ledger Band",
                "idea": "Leads with a quiet scannable ledger band above compact row cards for fast morning triage.",
                "screens": make_screens("a", "ledger", "split", "Ledger"),
            },
            {
                "id": "b",
                "name": "Action Board Strip",
                "idea": "Groups urgent candidates into a board strip first and tucks safe positions into a secondary drawer.",
                "screens": make_screens("b", "board", "stack", "Board"),
            },
        ],
        "recommended": "a",
        "notes": [
            "Direction a optimizes dense vertical scanning; direction b highlights urgent candidates in a board strip."
        ],
    }


def test_agent_and_workflow_yaml_contracts():
    agent_path = ROOT / "configs/design/agents/design_app_screen_directions_v1.yaml"
    wf_stage_path = ROOT / "configs/design/workflows/design_app_screen_v1_directions.yaml"
    wf_main_path = ROOT / "configs/design/workflows/design_app_screen_v1.yaml"

    agent_cfg = yaml.safe_load(agent_path.read_text(encoding="utf-8"))["agent"]
    assert agent_cfg["name"] == "design_app_screen_directions_v1"
    assert agent_cfg["provider"] == "anthropic"
    assert agent_cfg["token"] == "anthropic-2"
    assert agent_cfg["model"] == "claude-opus-5-5"
    assert agent_cfg["tools"] == []
    assert "temperature" not in agent_cfg
    assert "temperature" not in (agent_cfg.get("provider_config") or {})
    assert agent_cfg["provider_config"]["max_tokens"] == 64000
    assert agent_cfg["total_timeout"] == 1800

    stage_wf = yaml.safe_load(wf_stage_path.read_text(encoding="utf-8"))["workflow"]
    stage_nodes = [n["name"] for n in stage_wf["nodes"]]
    assert stage_nodes == [
        "directions_collect",
        "directions_read",
        "directions_check",
        "directions_revise",
        "directions",
    ]

    main_wf = yaml.safe_load(wf_main_path.read_text(encoding="utf-8"))["workflow"]
    main_by_name = {n["name"]: n for n in main_wf["nodes"]}
    directions_stage = main_by_name["directions"]
    assert directions_stage["type"] == "stage"
    assert directions_stage["depends_on"] == ["ground"]
    child_by_name = {n["name"]: n for n in directions_stage["nodes"]}
    assert list(child_by_name) == [
        "directions_collect",
        "directions_read",
        "directions_check",
        "directions_revise",
        "directions_finish",
    ]
    assert child_by_name["directions_finish"]["depends_on"] == ["directions_revise"]
    assert main_by_name["gate_direction"]["depends_on"] == ["directions"]


def test_fixture_mode_directions_pipeline(tmp_path):
    import app_screen_harness

    case_dir = tmp_path / "case"
    app_screen_harness.ensure_playable_case(REPO_CASE, case_dir)

    ws_dir = tmp_path / "fixture-ws"
    ws_dir.mkdir()
    app_screen_harness.prepare_workspace(case_dir, ws_dir)

    c_out = app_screen_harness.run_step("directions_collect", str(ws_dir), None, "")
    assert c_out["valid"] and c_out["mode"] == "real" and c_out["model"] == "yes"
    chk_out = app_screen_harness.run_step("directions_check", str(ws_dir), None, "")
    assert chk_out["valid"] and chk_out["mode"] == "real" and chk_out["verdict"] == "ok"
    fin_out = app_screen_harness.run_step("directions", str(ws_dir), None, "")
    assert fin_out["valid"] and fin_out["mode"] == "real" and fin_out["step"] == "directions"


def test_real_mode_directions_pipeline_compiles_prototypes_and_passes_checks(tmp_path):
    ws = _make_real_ws(tmp_path)

    # 1. directions_collect
    collect_out = CLI.run_step("directions_collect", str(ws.path), None, "real", "")
    assert collect_out["valid"]
    assert collect_out["model"] == "yes"
    assert len(collect_out["entry_screens"]) == 2
    assert (ws.folder("directions") / "task.md").is_file()

    # 2. directions_check on valid draft
    draft = _valid_directions_draft(ws)
    check_out = CLI.run_step("directions_check", str(ws.path), None, "real", json.dumps(draft))
    assert check_out["valid"]
    assert check_out["verdict"] == "ok", check_out["problems"]
    assert check_out["problems"] == []
    assert (ws.folder("directions") / "draft.json").is_file()
    assert (ws.folder("directions") / "check.json").is_file()

    # 3. directions (final compile + quick measured checks)
    fin_out = CLI.run_step("directions", str(ws.path), None, "real", "")
    assert fin_out["valid"]
    assert fin_out["directions"] == ["a", "b"]
    assert fin_out["blockers"] == {"a": 0, "b": 0}
    assert fin_out["recommended"] == "a"

    directions_doc = _read(ws.folder("directions") / "directions.json")
    assert [d["id"] for d in directions_doc["directions"]] == ["a", "b"]
    for did in ("a", "b"):
        proto_dir = ws.folder("directions") / did
        assert (proto_dir / "index.html").is_file()
        assert (proto_dir / "styles/tokens.css").is_file()
        assert (proto_dir / "fixture.json").is_file()
        assert (proto_dir / "build.json").is_file()
        assert (proto_dir / "shell/router.js").is_file()
        checks_doc = _read(proto_dir / "checks.json")
        assert checks_doc["blockers"] == 0
        assert contracts.check_json("direction_checks", checks_doc, f"04-directions/{did}/checks.json") == []

    # 4. gate_direction + Stage 5 build_scaffold integration
    gate_ans = {
        "choice": "b",
        "decided_by": "design",
        "source": "unit test",
        "reason": "picked direction b for action board hierarchy",
    }
    gates.answer(ws, "direction", json.dumps(gate_ans))
    stage5_task = build_scaffold.build_task(ws)
    assert "- Direction ID: `b`" in stage5_task
    assert "- Name: Action Board Strip" in stage5_task
    assert "Groups urgent candidates into a board strip first" in stage5_task
    assert "Starting screen layout and copy from `04-directions/b/`" in stage5_task


def _break_single_direction(draft: dict[str, Any]) -> None:
    draft["directions"] = draft["directions"][:1]


def _break_duplicate_id(draft: dict[str, Any]) -> None:
    draft["directions"][1]["id"] = "a"


def _break_duplicate_name(draft: dict[str, Any]) -> None:
    draft["directions"][1]["name"] = draft["directions"][0]["name"]


def _break_duplicate_idea(draft: dict[str, Any]) -> None:
    draft["directions"][1]["idea"] = draft["directions"][0]["idea"]


def _break_duplicate_layout(draft: dict[str, Any]) -> None:
    draft["directions"][1]["screens"][0]["layout"] = draft["directions"][0]["screens"][0]["layout"]


def _break_duplicate_normal_headline(draft: dict[str, Any]) -> None:
    draft["directions"][1]["screens"][0]["states"]["normal"]["headline"] = (
        draft["directions"][0]["screens"][0]["states"]["normal"]["headline"]
    )


def _break_missing_entry_screen(draft: dict[str, Any]) -> None:
    draft["directions"][1]["screens"] = draft["directions"][1]["screens"][:1]


def _break_missing_state(draft: dict[str, Any]) -> None:
    del draft["directions"][0]["screens"][0]["states"]["error"]


def _break_missing_show_ref(draft: dict[str, Any]) -> None:
    draft["directions"][0]["screens"][0]["shows"] = []


def _break_ungrounded_field_path(draft: dict[str, Any]) -> None:
    draft["directions"][0]["screens"][0]["shows"][0]["fields"] = ["invented.nonexistent.field"]


def _break_duplicate_state_headline(draft: dict[str, Any]) -> None:
    st = draft["directions"][0]["screens"][0]["states"]
    st["loading"]["headline"] = st["normal"]["headline"]


def _break_missing_primary_action(draft: dict[str, Any]) -> None:
    for a in draft["directions"][0]["screens"][0]["actions"]:
        a["kind"] = "secondary"


def _break_missing_error_recovery_action(draft: dict[str, Any]) -> None:
    for a in draft["directions"][0]["screens"][0]["actions"]:
        a["states"] = ["normal"]


def _break_hardcoded_figure(draft: dict[str, Any]) -> None:
    draft["directions"][0]["screens"][0]["states"]["normal"]["summary"] = "Collected $500 across 12 contracts today."


def _break_banned_copy(draft: dict[str, Any]) -> None:
    draft["directions"][1]["screens"][0]["shows"][0]["copy"] = "TBD placeholder text coming soon."


PLANTED_FAULTS = [
    ("single_direction", _break_single_direction, "directions_draft_schema", "at least 2 distinct directions"),
    ("duplicate_direction_id", _break_duplicate_id, "directions_draft_schema", "duplicate direction id 'a'"),
    ("duplicate_direction_name", _break_duplicate_name, "distinct_directions", "repeats name"),
    ("duplicate_direction_idea", _break_duplicate_idea, "distinct_directions", "repeats idea of direction 'a'"),
    ("duplicate_primary_layout", _break_duplicate_layout, "distinct_directions", "primary screen layout 'ledger' duplicates direction 'a'"),
    ("duplicate_normal_headline", _break_duplicate_normal_headline, "distinct_directions", "normal-state headline"),
    ("missing_entry_screen", _break_missing_entry_screen, "entry_screen_coverage", "missing target entry screen"),
    ("missing_required_state", _break_missing_state, "entry_screen_coverage", "state 'error' is missing a non-empty headline or summary"),
    ("missing_show_ref", _break_missing_show_ref, "show_and_field_grounding", "missing shows[] refs"),
    ("ungrounded_field_path", _break_ungrounded_field_path, "show_and_field_grounding", "absent from fixture.json"),
    ("duplicate_state_headline", _break_duplicate_state_headline, "state_and_action_quality", "repeats headline of state"),
    ("missing_primary_action", _break_missing_primary_action, "state_and_action_quality", "has no primary action"),
    ("missing_error_recovery", _break_missing_error_recovery_action, "state_and_action_quality", "no error recovery action"),
    ("hardcoded_figure", _break_hardcoded_figure, "state_and_action_quality", "hardcoded figure"),
    ("banned_filler_copy", _break_banned_copy, "state_and_action_quality", "banned filler copy"),
]


@pytest.mark.parametrize(
    "fault_name,mutator,expected_check,expected_substr",
    PLANTED_FAULTS,
    ids=[pf[0] for pf in PLANTED_FAULTS],
)
def test_planted_fault_caught_by_directions_check(tmp_path, fault_name, mutator, expected_check, expected_substr):
    ws = _make_real_ws(tmp_path / fault_name)
    bad_draft = copy.deepcopy(_valid_directions_draft(ws))
    mutator(bad_draft)

    report = directions_check.check_workspace(ws, pass_name="draft", draft=bad_draft)
    assert report["verdict"] == "retry", f"Planted fault {fault_name} was not caught!"
    matching = [
        p for p in report["problems"]
        if p["check"] == expected_check and expected_substr.lower() in p["problem"].lower()
    ]
    assert matching, (
        f"Planted fault {fault_name}: expected check={expected_check!r} with {expected_substr!r}, "
        f"got problems={report['problems']}"
    )


def test_directions_revise_recovers_from_retry_and_final_step_rejects_broken_draft(tmp_path):
    ws = _make_real_ws(tmp_path)
    CLI.run_step("directions_collect", str(ws.path), None, "real", "")

    good_draft = _valid_directions_draft(ws)
    bad_draft = copy.deepcopy(good_draft)
    _break_duplicate_layout(bad_draft)

    # Initial check returns retry + revise_task
    chk_out = CLI.run_step("directions_check", str(ws.path), None, "real", json.dumps(bad_draft))
    assert chk_out["verdict"] == "retry"
    assert "Fix `04-directions/draft.json` Problems" in chk_out["revise_task"]

    # If directions runs without a fixed revision, it fails loud
    with pytest.raises(directions.DirectionsError, match="failed check-final.json"):
        directions.run(ws, "")

    # When directions receives the revised JSON from directions_revise, it succeeds
    fin_out = CLI.run_step("directions", str(ws.path), None, "real", json.dumps(good_draft))
    assert fin_out["valid"]
    assert fin_out["directions"] == ["a", "b"]
    assert fin_out["blockers"] == {"a": 0, "b": 0}


def test_measure_direction_checks_catches_broken_prototype_asset(tmp_path):
    ws = _make_real_ws(tmp_path)
    draft = _valid_directions_draft(ws)
    d_a = draft["directions"][0]
    proto_dir = ws.folder("directions") / "a"
    build_scaffold.compile_direction_prototype(ws, d_a, out_dir=proto_dir)

    # Plant a missing script asset in 04-directions/a/index.html
    idx_path = proto_dir / "index.html"
    idx_path.write_text(
        idx_path.read_text(encoding="utf-8") + '\n<script src="screens/missing-broken.js"></script>\n',
        encoding="utf-8",
    )
    inventory = _read(ws.folder("ground") / "inventory.json")
    entry_screens = build_scaffold.select_entry_screens(inventory)
    rec = directions.measure_direction_checks(ws, proto_dir, entry_screens)
    assert rec["blockers"] >= 1
    failed_ids = [c["id"] for c in rec["checks"] if c["result"] == "fail"]
    assert "render" in failed_ids and "render.request" in failed_ids
