"""design_app_screen_v1 Stage 5a: deterministic build scaffold and checks (Design #219).

Tests:
- Workflow YAML parity between design_app_screen_v1_build.yaml and design_app_screen_v1.yaml.
- Scaffold generation on fixed ground+direction inputs and on the frozen rollcall-20261104 case.
- Input boundary validation (rule 36 fail loud and fast) when ground or direction files/fields are missing.
- All six planted faults caught by build_check.py with named check, location and message.
- Byte-identical determinism across two runs on the same inputs.
- Stage 6a structural families over the generated Stage 5a skeleton.
"""
from __future__ import annotations

import hashlib
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
    build_check,
    build_scaffold,
    checks,
    checks_views,
    contracts,
    known_case,
)
from app_screen.build_scaffold import BuildInputError  # noqa: E402
from app_screen.workspace import Workspace  # noqa: E402

CASE_DIR = ROOT / "tests/design_app_screen_case/rollcall-20261104"
MAIN_WF = ROOT / "configs/design/workflows/design_app_screen_v1.yaml"
BUILD_WF = ROOT / "configs/design/workflows/design_app_screen_v1_build.yaml"

FIXED_INVENTORY = {
    "design_files": "defined",
    "source": {"product": "parcelly-build"},
    "screens": [
        {
            "id": "parcels",
            "name": "Parcels",
            "states": ["normal", "loading", "empty", "error", "partial"],
            "widths": [1440, 390, 320],
            "sources": ["req:R1"],
            "shows": [{"what": "Track active shipments and delivery exceptions.", "sources": ["req:R1"]}],
            "actions": [
                {
                    "id": "refresh-parcels",
                    "what": "Refresh shipment status",
                    "states": ["normal", "partial"],
                    "sources": ["req:R1"],
                }
            ],
        },
        {
            "id": "account",
            "name": "Account",
            "states": ["normal", "loading", "empty", "error", "partial"],
            "widths": [1440, 390, 320],
            "sources": ["req:R2"],
            "shows": [{"what": "Review billing plan and monthly parcel spend.", "sources": ["req:R2"]}],
            "actions": [
                {
                    "id": "export-statement",
                    "what": "Export monthly statement",
                    "states": ["normal"],
                    "sources": ["req:R2"],
                }
            ],
        },
    ],
}

FIXED_FIXTURE = {
    "product": "parcelly-build",
    "parcels": [{"id": "PK-1", "worth": 42.5, "weight_kg": 2.4}],
    "account": {"spend": 167.75, "share": 0.125, "open_shipments": 3},
}

FIXED_TOKENS = {
    "product": "parcelly-build",
    "color": {
        "paper-50": {"hex": "#fcfaf6", "use": "canvas"},
        "surface": {"hex": "#ffffff", "use": "cards"},
        "ink-950": {"hex": "#0c121d", "use": "primary text"},
        "ink-600": {"hex": "#434e5e", "use": "secondary text"},
        "tide-600": {"hex": "#03657d", "use": "primary accent"},
    },
    "font": {
        "display": {"family": "Fraunces, Georgia, serif"},
        "body": {"family": "Plus Jakarta Sans, sans-serif"},
        "mono": {"family": "JetBrains Mono, monospace"},
    },
    "type": {
        "display": {"size_px": 36, "line_height": 1.15, "weight": 600},
        "title": {"size_px": 20, "line_height": 1.3, "weight": 600},
        "body": {"size_px": 16, "line_height": 1.5, "weight": 400},
    },
    "space": {"base_px": 8, "scale_px": [4, 8, 12, 16, 24, 32]},
    "radius": {"card_px": 12, "control_px": 8},
}

FIXED_DIRECTIONS = {
    "directions": [
        {
            "id": "a",
            "name": "Warm Ledger",
            "idea": "Calm paper surfaces with clear shipment status hierarchy.",
            "page": "a/index.html",
        },
        {
            "id": "b",
            "name": "Depot Board",
            "idea": "Compact dispatch board for high-volume tracking.",
            "page": "b/index.html",
        },
    ]
}

FIXED_GATE_DIRECTION = {
    "gate": "direction",
    "choice": "a",
    "decided_by": "design",
    "owner_words": "",
    "source": "fixed test case",
    "reason": "Direction A passes all quick checks.",
    "prediction": "a",
    "taste": "not-taste",
    "at": "2026-11-06T00:00:00+00:00",
}

FIXED_REQUIREMENTS = {
    "product": "parcelly-build",
    "items": [
        {"id": "R1", "kind": "feature", "owner_words": "show active parcels", "source": "req:R1"},
        {"id": "R2", "kind": "feature", "owner_words": "show monthly account spend", "source": "req:R2"},
    ],
}


def _setup_fixed_workspace(tmp_path: Path, name: str = "ws") -> Workspace:
    ws_dir = tmp_path / name
    ws_dir.mkdir(parents=True, exist_ok=True)
    ws = Workspace(ws_dir)
    ws.start("parcelly-build", "real")

    intake_dir = ws.folder("intake")
    intake_dir.mkdir(parents=True, exist_ok=True)
    (intake_dir / "requirements.json").write_text(json.dumps(FIXED_REQUIREMENTS, indent=2) + "\n")

    ground_dir = ws.folder("ground")
    design_files_dir = ground_dir / "design-files"
    design_files_dir.mkdir(parents=True, exist_ok=True)
    (ground_dir / "inventory.json").write_text(json.dumps(FIXED_INVENTORY, indent=2) + "\n")
    (ground_dir / "fixture.json").write_text(json.dumps(FIXED_FIXTURE, indent=2) + "\n")
    (design_files_dir / "tokens.json").write_text(json.dumps(FIXED_TOKENS, indent=2) + "\n")
    (design_files_dir / "DESIGN.md").write_text("# Parcelly Design\n\nWarm paper ledger direction.\n")

    directions_dir = ws.folder("directions")
    directions_dir.mkdir(parents=True, exist_ok=True)
    (directions_dir / "directions.json").write_text(json.dumps(FIXED_DIRECTIONS, indent=2) + "\n")
    (directions_dir / "gate_direction.json").write_text(json.dumps(FIXED_GATE_DIRECTION, indent=2) + "\n")
    return ws


def _setup_frozen_case_workspace(tmp_path: Path, name: str = "ws-rollcall") -> Workspace:
    ws_dir = tmp_path / name
    ws_dir.mkdir(parents=True, exist_ok=True)
    ws = Workspace(ws_dir)
    ws.start("rollcall", "real")
    shutil.copytree(CASE_DIR / "01-request", ws.folder("intake"))
    shutil.copytree(CASE_DIR / "03-ground", ws.folder("ground"))
    shutil.copytree(CASE_DIR / "04-directions", ws.folder("directions"))
    shutil.copyfile(CASE_DIR / "gates/gate_direction.json", ws.folder("directions") / "gate_direction.json")
    return ws


def _hash_directory(directory: Path) -> tuple[str, dict[str, str]]:
    per_file: dict[str, str] = {}
    overall = hashlib.sha256()
    for p in sorted(f for f in directory.rglob("*") if f.is_file()):
        rel = p.relative_to(directory).as_posix()
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
        per_file[rel] = digest
        overall.update(f"{rel}:{digest}\n".encode())
    return overall.hexdigest(), per_file


def test_build_workflow_yaml_matches_main_workflow():
    """The per-stage trial workflow design_app_screen_v1_build.yaml matches all 5 build nodes in main workflow."""
    assert BUILD_WF.is_file()
    main_doc = yaml.safe_load(MAIN_WF.read_text())["workflow"]
    build_doc = yaml.safe_load(BUILD_WF.read_text())["workflow"]

    expected_names = ["build", "build_read", "build_check", "build_revise", "build_finish"]
    trial_names = [n["name"] for n in build_doc["nodes"]]
    assert trial_names == expected_names

    main_by_name = {n["name"]: n for n in main_doc["nodes"]}
    build_stage = main_by_name["build"]
    assert build_stage["type"] == "stage"
    assert build_stage["depends_on"] == ["gate_direction"]
    child_by_name = {n["name"]: n for n in build_stage["nodes"]}
    assert list(child_by_name) == ["build_collect", "build_read", "build_check", "build_revise", "build_finish"]
    for trial_node in build_doc["nodes"]:
        name = "build_collect" if trial_node["name"] == "build" else trial_node["name"]
        assert name in child_by_name
        main_node = child_by_name[name]
        assert trial_node["type"] == main_node["type"] == "agent"
        assert trial_node["agent"] == main_node["agent"]
        if name == "build_read":
            assert main_node["input_map"] == {"task": "build_collect.structured.task"}
            assert trial_node["input_map"] == {"task": "build.structured.task"}
        else:
            assert trial_node["input_map"] == main_node["input_map"]
        if "condition" in main_node:
            expected_cond = dict(main_node["condition"])
            if expected_cond.get("source") == "build_collect.structured.model":
                expected_cond["source"] = "build.structured.model"
            assert trial_node["condition"] == expected_cond

    checks_node = main_by_name["checks"]
    assert checks_node["depends_on"] == ["build"]


def test_build_fixture_mode_preserved(tmp_path: Path):
    """Fixture mode continues to copy the known case's 05-build/ output and increment the round."""
    case = tmp_path / "case" / "rollcall-20261104"
    shutil.copytree(CASE_DIR, case)
    html = "<!doctype html><title>placeholder for the known case's page</title>\n"
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
    for s in json.loads((case / "02-existing/audit.json").read_text())["screens"]:
        p = case / "02-existing" / s["capture"]
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(png)
    for d in json.loads((case / "04-directions/directions.json").read_text())["directions"]:
        (case / "04-directions" / d["page"]).write_text(html)
    bdoc = json.loads((case / "05-build/build.json").read_text())
    (case / "05-build" / bdoc["page"]).write_text(html)
    (case / "05-build/shell").mkdir(parents=True, exist_ok=True)
    (case / "05-build/shell/page.html").write_text(html)
    for s in bdoc["screens"]:
        p = case / "05-build" / s["file"]
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("// placeholder for the known case's screen script\n")
    known_case.freeze(case, "rollcall", "test copy of the RollCall known case")

    ws_dir = tmp_path / "fixture-ws"
    ws_dir.mkdir()
    known_case.pack(case, ws_dir)
    out = cli.run_step("build", str(ws_dir), None, "fixture", "")
    assert out["valid"] is True
    assert out["round"] == 1
    assert (ws_dir / "05-build/build.json").is_file()


def test_build_real_mode_on_fixed_inputs(tmp_path: Path):
    """Real mode writes shell, tokens.css, fixture.json, build.json and one screen JS per screen."""
    ws = _setup_fixed_workspace(tmp_path)
    out = cli.run_step("build", str(ws.path), None, "real", "")

    assert out["valid"] is True
    assert out["verdict"] == "ok"
    assert out["direction"] == "a"
    assert out["placeholder"] is True
    assert out["screens"] == 2
    assert out["views"] == 10
    assert out["problems"] == 0

    build_dir = ws.folder("build")
    assert (build_dir / "index.html").is_file()
    assert (build_dir / "build.json").is_file()
    assert (build_dir / "fixture.json").is_file()
    assert (build_dir / "styles/tokens.css").is_file()
    assert (build_dir / "shell/router.js").is_file()
    assert (build_dir / "screens/parcels.js").is_file()
    assert (build_dir / "screens/account.js").is_file()

    for sid in ("parcels", "account"):
        js_text = (build_dir / f"screens/{sid}.js").read_text()
        assert f'data-screen="{sid}"' in js_text
        assert f'data-build-placeholder="{sid}"' in js_text
        assert 'data-view-state="' in js_text
        assert 'data-action="' in js_text
        assert 'data-req="' in js_text

    check_res = build_check.check_workspace(ws)
    assert check_res["verdict"] == "ok"
    assert check_res["problems"] == []


def test_build_real_mode_on_frozen_rollcall_case(tmp_path: Path):
    """Real mode on the frozen rollcall-20261104 case writes all 17 screen files and 85 views."""
    ws = _setup_frozen_case_workspace(tmp_path)
    out = cli.run_step("build", str(ws.path), None, "real", "")

    assert out["valid"] is True
    assert out["verdict"] == "ok"
    assert out["direction"] == "a"
    assert out["screens"] == 17
    assert out["views"] == 85
    assert out["problems"] == 0

    contracts.validate("build", ws)
    check_res = build_check.check_workspace(ws)
    assert check_res["verdict"] == "ok"
    assert check_res["problems"] == []


@pytest.mark.parametrize(
    ("mutate_fn", "expected_substring"),
    [
        (
            lambda ws: shutil.rmtree(ws.folder("ground")),
            "03-ground/",
        ),
        (
            lambda ws: (ws.folder("ground") / "inventory.json").unlink(),
            "03-ground/inventory.json",
        ),
        (
            lambda ws: (ws.folder("ground") / "fixture.json").unlink(),
            "03-ground/fixture.json",
        ),
        (
            lambda ws: (ws.folder("ground") / "design-files/tokens.json").unlink(),
            "03-ground/design-files/tokens.json",
        ),
        (
            lambda ws: (ws.folder("ground") / "design-files/DESIGN.md").unlink(),
            "03-ground/design-files/DESIGN.md",
        ),
        (
            lambda ws: (ws.folder("ground") / "inventory.json").write_text(
                json.dumps({**FIXED_INVENTORY, "screens": []})
            ),
            "inventory.screens",
        ),
        (
            lambda ws: (ws.folder("ground") / "inventory.json").write_text(
                json.dumps({
                    **FIXED_INVENTORY,
                    "screens": [{**FIXED_INVENTORY["screens"][0], "id": ""}],
                })
            ),
            "inventory.screens[0].id",
        ),
        (
            lambda ws: (ws.folder("ground") / "inventory.json").write_text(
                json.dumps({
                    **FIXED_INVENTORY,
                    "screens": [{**FIXED_INVENTORY["screens"][0], "states": []}],
                })
            ),
            "inventory.screens[0].states",
        ),
        (
            lambda ws: shutil.rmtree(ws.folder("directions")),
            "04-directions/",
        ),
        (
            lambda ws: (ws.folder("directions") / "directions.json").unlink(),
            "04-directions/directions.json",
        ),
        (
            lambda ws: (ws.folder("directions") / "gate_direction.json").unlink(),
            "chosen direction",
        ),
        (
            lambda ws: (ws.folder("directions") / "gate_direction.json").write_text(
                json.dumps({**FIXED_GATE_DIRECTION, "choice": "z"})
            ),
            "not in directions",
        ),
    ],
)
def test_build_input_boundary_guards_fail_loud(tmp_path: Path, mutate_fn, expected_substring: str):
    """Rule 36: missing or incomplete ground/direction inputs fail loud naming the missing file or field."""
    ws = _setup_fixed_workspace(tmp_path)
    mutate_fn(ws)
    with pytest.raises(BuildInputError) as exc_info:
        build.run(ws)
    assert expected_substring in str(exc_info.value)


def test_planted_fault_1_missing_screen_file(tmp_path: Path):
    """Planted fault 1: a screen file missing from the inventory is caught by screen_file_per_inventory_screen."""
    ws = _setup_fixed_workspace(tmp_path)
    build_scaffold.write_scaffold(ws)
    (ws.folder("build") / "screens/account.js").unlink()

    res = build_check.check_workspace(ws)
    assert res["verdict"] == "retry"
    caught = [p for p in res["problems"] if p["check"] == "screen_file_per_inventory_screen"]
    assert caught, f"expected screen_file_per_inventory_screen, got {res['problems']}"
    assert "05-build/screens/account.js" in caught[0]["where"]
    assert "account" in caught[0]["problem"]


def test_planted_fault_2_view_with_no_routing_target(tmp_path: Path):
    """Planted fault 2: a build.json view with no routing target is caught by view_has_routing_target."""
    ws = _setup_fixed_workspace(tmp_path)
    build_scaffold.write_scaffold(ws)
    bpath = ws.folder("build") / "build.json"
    bdoc = json.loads(bpath.read_text())
    bdoc["views"][0]["open"]["hash"] = "#parcels/nonexistent-route"
    bpath.write_text(json.dumps(bdoc, indent=2) + "\n")

    res = build_check.check_workspace(ws)
    assert res["verdict"] == "retry"
    caught = [p for p in res["problems"] if p["check"] == "view_has_routing_target"]
    assert caught, f"expected view_has_routing_target, got {res['problems']}"
    assert "05-build/build.json:views[0]" in caught[0]["where"]


def test_planted_fault_3_data_req_absent_from_fixture(tmp_path: Path):
    """Planted fault 3: a data-req naming a field absent from fixture.json is caught by data_req_in_fixture."""
    ws = _setup_fixed_workspace(tmp_path)
    build_scaffold.write_scaffold(ws)
    spath = ws.folder("build") / "screens/parcels.js"
    text = spath.read_text()
    spath.write_text(text.replace('data-req="parcels.0.worth"', 'data-req="parcels.0.invented_metric"', 1))

    res = build_check.check_workspace(ws)
    assert res["verdict"] == "retry"
    caught = [p for p in res["problems"] if p["check"] == "data_req_in_fixture"]
    assert caught, f"expected data_req_in_fixture, got {res['problems']}"
    assert "parcels.0.invented_metric" in caught[0]["problem"]


def test_planted_fault_4_hardcoded_figure_in_screen_file(tmp_path: Path):
    """Planted fault 4: a hardcoded figure in a screen file is caught by no_hardcoded_figures."""
    ws = _setup_fixed_workspace(tmp_path)
    build_scaffold.write_scaffold(ws)
    spath = ws.folder("build") / "screens/parcels.js"
    text = spath.read_text()
    spath.write_text(text.replace("Placeholder: ", "Placeholder ($14,820.50): ", 1))

    res = build_check.check_workspace(ws)
    assert res["verdict"] == "retry"
    caught = [p for p in res["problems"] if p["check"] == "no_hardcoded_figures"]
    assert caught, f"expected no_hardcoded_figures, got {res['problems']}"
    assert "$14,820.50" in caught[0]["problem"]


def test_planted_fault_5_screen_missing_data_screen_root(tmp_path: Path):
    """Planted fault 5: a screen with no data-screen root is caught by screen_has_data_screen_root."""
    ws = _setup_fixed_workspace(tmp_path)
    build_scaffold.write_scaffold(ws)
    spath = ws.folder("build") / "screens/parcels.js"
    text = spath.read_text()
    spath.write_text(text.replace('data-screen="parcels"', 'data-missing-screen="parcels"'))

    res = build_check.check_workspace(ws)
    assert res["verdict"] == "retry"
    caught = [p for p in res["problems"] if p["check"] == "screen_has_data_screen_root"]
    assert caught, f"expected screen_has_data_screen_root, got {res['problems']}"
    assert 'data-screen="parcels"' in caught[0]["problem"]


def test_planted_fault_6_state_unreachable_by_route_hash(tmp_path: Path):
    """Planted fault 6: a state unreachable by #<screen>/<state> is caught by routing_reaches_every_view."""
    ws = _setup_fixed_workspace(tmp_path)
    build_scaffold.write_scaffold(ws)
    spath = ws.folder("build") / "screens/parcels.js"
    text = spath.read_text()
    spath.write_text(text.replace('href="#parcels/error"', 'href="#parcels/broken"'))

    res = build_check.check_workspace(ws)
    assert res["verdict"] == "retry"
    caught = [p for p in res["problems"] if p["check"] == "routing_reaches_every_view"]
    assert caught, f"expected routing_reaches_every_view, got {res['problems']}"
    assert "#parcels/error" in caught[0]["problem"]


def test_planted_fault_shell_missing_screen_script_tag(tmp_path: Path):
    """Removing a screen script tag from index.html is caught by shell_loads_every_screen_file."""
    ws = _setup_fixed_workspace(tmp_path)
    build_scaffold.write_scaffold(ws)
    ipath = ws.folder("build") / "index.html"
    ipath.write_text(ipath.read_text().replace('<script src="screens/account.js"></script>', ""))

    res = build_check.check_workspace(ws)
    assert res["verdict"] == "retry"
    caught = [p for p in res["problems"] if p["check"] == "shell_loads_every_screen_file"]
    assert caught, f"expected shell_loads_every_screen_file, got {res['problems']}"
    assert "screens/account.js" in caught[0]["problem"]


def test_planted_fault_missing_view_in_build_json(tmp_path: Path):
    """Removing a state view from build.json is caught by view_per_screen_state."""
    ws = _setup_fixed_workspace(tmp_path)
    build_scaffold.write_scaffold(ws)
    bpath = ws.folder("build") / "build.json"
    bdoc = json.loads(bpath.read_text())
    bdoc["views"] = [v for v in bdoc["views"] if not (v["screen"] == "account" and v["state"] == "partial")]
    bpath.write_text(json.dumps(bdoc, indent=2) + "\n")

    res = build_check.check_workspace(ws)
    assert res["verdict"] == "retry"
    caught = [p for p in res["problems"] if p["check"] == "view_per_screen_state"]
    assert caught, f"expected view_per_screen_state, got {res['problems']}"
    assert "account" in caught[0]["problem"] and "partial" in caught[0]["problem"]


def test_planted_fault_missing_token_in_tokens_css(tmp_path: Path):
    """Omitting a product token from styles/tokens.css is caught by tokens_from_product_file."""
    ws = _setup_fixed_workspace(tmp_path)
    build_scaffold.write_scaffold(ws)
    tpath = ws.folder("build") / "styles/tokens.css"
    tpath.write_text(tpath.read_text().replace("--color-tide-600: #03657d;", ""))

    res = build_check.check_workspace(ws)
    assert res["verdict"] == "retry"
    caught = [p for p in res["problems"] if p["check"] == "tokens_from_product_file"]
    assert caught, f"expected tokens_from_product_file, got {res['problems']}"
    assert "--color-tide-600" in caught[0]["problem"]


def test_build_determinism_byte_identical_across_two_runs(tmp_path: Path):
    """Two runs on identical inputs write byte-identical 05-build/ directories."""
    ws1 = _setup_frozen_case_workspace(tmp_path, "run-1")
    ws2 = _setup_frozen_case_workspace(tmp_path, "run-2")

    out1 = build.run(ws1)
    out2 = build.run(ws2)
    assert out1 == out2

    digest1, files1 = _hash_directory(ws1.folder("build"))
    digest2, files2 = _hash_directory(ws2.folder("build"))

    assert files1 == files2
    assert digest1 == digest2
    assert len(files1) == 23  # index.html, build.json, fixture.json, task.md, styles/tokens.css, shell/router.js + 17 screens


FIXED_BUILD_DRAFT = {
    "screens": [
        {
            "id": "parcels",
            "title": "Parcels",
            "layout": "ledger",
            "lead": "Track active shipments and delivery exceptions in one calm view.",
            "shows": [
                {
                    "ref": "S1",
                    "heading": "Active shipments and exceptions",
                    "copy": "Live parcel worth and weight figures bound from the grounded shipment fixture.",
                    "fields": ["parcels.0.worth", "parcels.0.weight_kg"],
                }
            ],
            "actions": [
                {
                    "id": "refresh-parcels",
                    "label": "Refresh shipments",
                    "kind": "primary",
                    "states": ["normal", "partial"],
                    "feedback": "Refreshing shipment ledger from carrier feed.",
                }
            ],
            "states": {
                "normal": {
                    "headline": "Active shipments on schedule",
                    "summary": "Review current parcel worth and weight before the afternoon pickup window.",
                    "badge": "On schedule",
                },
                "loading": {
                    "headline": "Fetching latest shipment updates",
                    "summary": "Syncing carrier scans and depot handoffs for your active parcels.",
                    "badge": "Syncing",
                },
                "empty": {
                    "headline": "No parcels in transit right now",
                    "summary": "New shipments appear here automatically as soon as a label is scanned.",
                    "badge": "Clear",
                },
                "error": {
                    "headline": "Carrier feed temporarily unavailable",
                    "summary": "We could not refresh live scans. Use Refresh shipments to retry.",
                    "badge": "Needs retry",
                },
                "partial": {
                    "headline": "Depot scans loaded with delayed courier feed",
                    "summary": "Showing last verified parcel worth and weight while live courier scans catch up.",
                    "badge": "Partial feed",
                },
            },
        },
        {
            "id": "account",
            "title": "Account",
            "layout": "split",
            "lead": "Review your billing plan, monthly spend, and open shipment allocation.",
            "shows": [
                {
                    "ref": "S1",
                    "heading": "Billing plan and monthly parcel spend",
                    "copy": "Current monthly spend, plan share, and open shipment count from your account ledger.",
                    "fields": ["account.spend", "account.share", "account.open_shipments"],
                }
            ],
            "actions": [
                {
                    "id": "export-statement",
                    "label": "Export statement",
                    "kind": "primary",
                    "states": ["normal"],
                    "feedback": "Preparing statement export for download.",
                }
            ],
            "states": {
                "normal": {
                    "headline": "Monthly account statement ready",
                    "summary": "Your billing plan and parcel spend are balanced for the current cycle.",
                    "badge": "Current",
                },
                "loading": {
                    "headline": "Loading billing ledger",
                    "summary": "Gathering monthly spend and shipment allocation totals.",
                    "badge": "Loading",
                },
                "empty": {
                    "headline": "No billing activity recorded yet",
                    "summary": "Your first statement will appear once a shipment completes delivery.",
                    "badge": "New account",
                },
                "error": {
                    "headline": "Statement service could not be reached",
                    "summary": "Billing figures are temporarily unavailable. Retry from the account bar.",
                    "badge": "Offline",
                },
                "partial": {
                    "headline": "Statement loaded with pending carrier charges",
                    "summary": "Core spend totals are visible while recent depot surcharges settle.",
                    "badge": "Pending settlement",
                },
            },
        },
    ]
}


def test_stage_5b_build_task_check_and_finish_end_to_end(tmp_path: Path):
    """Stage 5b pipeline (`build` -> `build_check` -> `build_finish`) compiles draft.json and leaves 0 placeholders."""
    ws = _setup_fixed_workspace(tmp_path)
    out_build = cli.run_step("build", str(ws.path), None, "real", "")
    assert out_build["model"] == "yes"
    assert "parcels" in out_build["task"]
    assert "S1" in out_build["task"]
    assert (ws.folder("build") / "task.md").is_file()

    out_check = cli.run_step("build_check", str(ws.path), None, "real", json.dumps(FIXED_BUILD_DRAFT))
    assert out_check["valid"] is True
    assert out_check["verdict"] == "ok"
    assert out_check["problems"] == []
    assert out_check["revise_task"] == ""

    out_finish = cli.run_step("build_finish", str(ws.path), None, "real", "")
    assert out_finish["valid"] is True
    assert out_finish["verdict"] == "ok"

    bdoc = json.loads((ws.folder("build") / "build.json").read_text())
    assert bdoc["placeholder"] is False
    for sid in ("parcels", "account"):
        js_text = (ws.folder("build") / f"screens/{sid}.js").read_text()
        assert "data-build-placeholder" not in js_text
        assert 'data-built-screen="' in js_text


def test_stage_5b_planted_fault_leftover_placeholder(tmp_path: Path):
    """Leaving data-build-placeholder in a built screen is caught by no_placeholder_left."""
    ws = _setup_fixed_workspace(tmp_path)
    build.run(ws)
    build.check(ws, json.dumps(FIXED_BUILD_DRAFT))
    spath = ws.folder("build") / "screens/parcels.js"
    spath.write_text(spath.read_text() + '\n// <div data-build-placeholder="parcels"></div>\n')

    res = build_check.check_workspace(ws, require_built=True)
    assert res["verdict"] == "retry"
    caught = [p for p in res["problems"] if p["check"] == "no_placeholder_left"]
    assert caught, f"expected no_placeholder_left, got {res['problems']}"


def test_stage_5b_planted_fault_missing_show_item(tmp_path: Path):
    """Omitting a shows[] item from draft.json is caught by every_show_covered."""
    ws = _setup_fixed_workspace(tmp_path)
    build.run(ws)
    bad_draft = json.loads(json.dumps(FIXED_BUILD_DRAFT))
    bad_draft["screens"][0]["shows"] = []

    res = build.check(ws, json.dumps(bad_draft))
    assert res["verdict"] == "retry"
    caught = [p for p in res["problems"] if p["check"] == "every_show_covered"]
    assert caught, f"expected every_show_covered, got {res['problems']}"
    assert "S1" in caught[0]["problem"]


def test_stage_5b_planted_fault_missing_state_design(tmp_path: Path):
    """Omitting a state design from draft.json is caught by every_screen_state_designed."""
    ws = _setup_fixed_workspace(tmp_path)
    build.run(ws)
    bad_draft = json.loads(json.dumps(FIXED_BUILD_DRAFT))
    del bad_draft["screens"][1]["states"]["partial"]

    res = build.check(ws, json.dumps(bad_draft))
    assert res["verdict"] == "retry"
    caught = [p for p in res["problems"] if p["check"] == "every_screen_state_designed"]
    assert caught, f"expected every_screen_state_designed, got {res['problems']}"
    assert "partial" in caught[0]["problem"]


def test_stage_5b_planted_fault_two_primary_actions(tmp_path: Path):
    """Two primary actions on one screen in draft.json is caught by single_primary_action."""
    ws = _setup_fixed_workspace(tmp_path)
    inv_path = ws.folder("ground") / "inventory.json"
    inv = json.loads(inv_path.read_text())
    inv["screens"][0]["actions"].append(
        {"id": "archive-parcels", "what": "Archive delivered parcels", "states": ["normal"], "sources": ["req:R1"]}
    )
    inv_path.write_text(json.dumps(inv, indent=2) + "\n")

    build.run(ws)
    bad_draft = json.loads(json.dumps(FIXED_BUILD_DRAFT))
    bad_draft["screens"][0]["actions"].append(
        {
            "id": "archive-parcels",
            "label": "Archive parcels",
            "kind": "primary",
            "states": ["normal"],
            "feedback": "Archiving delivered parcels.",
        }
    )

    res = build.check(ws, json.dumps(bad_draft))
    assert res["verdict"] == "retry"
    caught = [p for p in res["problems"] if p["check"] == "single_primary_action"]
    assert caught, f"expected single_primary_action, got {res['problems']}"


def test_stage_5b_planted_fault_hardcoded_figure_in_draft_copy(tmp_path: Path):
    """A hardcoded figure in draft.json prose is caught by no_hardcoded_figures."""
    ws = _setup_fixed_workspace(tmp_path)
    build.run(ws)
    bad_draft = json.loads(json.dumps(FIXED_BUILD_DRAFT))
    bad_draft["screens"][0]["states"]["normal"]["summary"] = "Total parcel worth is $9,999.99 across 450 items."

    res = build.check(ws, json.dumps(bad_draft))
    assert res["verdict"] == "retry"
    caught = [p for p in res["problems"] if p["check"] == "no_hardcoded_figures"]
    assert caught, f"expected no_hardcoded_figures, got {res['problems']}"


def test_stage_5b_broken_draft_retry_and_revise_finish(tmp_path: Path):
    """A broken first draft triggers retry + revise_task, and build_finish succeeds with the revised draft."""
    ws = _setup_fixed_workspace(tmp_path)
    build.run(ws)

    bad_draft = json.loads(json.dumps(FIXED_BUILD_DRAFT))
    del bad_draft["screens"][0]["states"]["error"]
    check_out = build.check(ws, json.dumps(bad_draft))
    assert check_out["verdict"] == "retry"
    assert "every_screen_state_designed" in check_out["revise_task"]

    with pytest.raises(build.BuildError, match="every_screen_state_designed"):
        build.finish(ws, "")

    finish_out = cli.run_step("build_finish", str(ws.path), None, "real", json.dumps(FIXED_BUILD_DRAFT))
    assert finish_out["valid"] is True
    assert finish_out["verdict"] == "ok"
    final_check = json.loads((ws.folder("build") / "check-final.json").read_text())
    assert final_check["verdict"] == "ok"
    assert final_check["problems"] == []


def test_stage_6a_structural_checks_pass_over_scaffold(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Stage 6a structural families (contract, render, integration/routing, coverage, figures) pass on scaffold."""
    ws = _setup_fixed_workspace(tmp_path)
    build.run(ws)

    plan = checks_views.plan(ws)
    assert len(plan["views"]) == 30  # 2 screens x 5 states x 3 widths

    # Construct stubbed browser measures reflecting the scaffold DOM for each planned view
    def _fake_measure(ws_arg: Workspace, plan_arg: dict, thresholds_arg: dict) -> dict:
        out = {}
        png_dir = ws_arg.round_folder() / "views"
        png_dir.mkdir(parents=True, exist_ok=True)
        for v in plan_arg["views"]:
            vid = v["id"]
            sid = v["screen"]
            st = v["state"]
            w = v["width"]
            (png_dir / f"{vid}.png").write_bytes(bytes.fromhex("89504e470d0a1a0a"))
            act_id = "refresh-parcels" if sid == "parcels" else "export-statement"
            fig_val = "42.5" if sid == "parcels" else "167.75"
            out[vid] = {
                "view": vid,
                "screen": sid,
                "state": st,
                "width": w,
                "opened": True,
                "why": "",
                "console": [],
                "failed_requests": [],
                "capture": f"views/{vid}.png",
                "dm": {
                    "viewport": [w, v["height"]],
                    "page_width": {"scroll": w, "overflows": False},
                    "overflowing": [],
                    "contrast_failures": [],
                    "weak_boundaries": [],
                    "small_targets": [],
                    "controls": [{"sel": f"button[data-action='{act_id}']"}],
                },
                "mp": {
                    "viewport": {"w": w, "h": v["height"]},
                    "horizontalScroll": 0,
                    "type": {"smallest": [{"size": 16, "cls": "dd", "text": fig_val}], "bodyLikeUnder16": 0},
                    "overflow": {"outside": []},
                    "truncated": {"items": []},
                    "runs": [],
                    "fontsLoaded": True,
                    "errors": [],
                },
                "cm": {
                    "contract": {
                        "marked": True,
                        "screens": [sid],
                        "shown": [sid],
                        "states": [st],
                        "banned_state_attr": [],
                    },
                    "actions": [
                        {
                            "action": act_id,
                            "sel": f"button[data-action='{act_id}']",
                            "label": "Action",
                            "visible": True,
                            "tag": "button",
                        }
                    ],
                    "reqs": {"R1": {"visible": sid == "parcels"}, "R2": {"visible": sid == "account"}},
                    "figures": [
                        {
                            "kind": "number",
                            "raw": fig_val,
                            "suffix": "",
                            "token": fig_val,
                            "sel": "dd.rc-placeholder__value",
                            "context": fig_val,
                        }
                    ],
                    "used": {
                        "colours": [{"value": "rgb(12,18,29)", "count": 5, "sel": "body"}],
                        "fonts": [{"value": "Plus Jakarta Sans", "count": 5, "sel": "body"}],
                        "sizes": [{"value": "16", "count": 5, "sel": "body"}],
                    },
                    "duplicate_ids": [],
                    "dead_links": [],
                    "solid_fills": [{"sel": "button.rc-action-btn--primary", "bg": "rgb(3,101,125)", "around": "rgb(255,255,255)"}],
                    "groups": [],
                },
                "axe": [],
                "tab_stops": [{"sel": f"button[data-action='{act_id}']", "name": "Action", "ring": True, "outline": "2px solid", "box_shadow": "none"}],
                "click_feedback": [
                    {"action": act_id, "sel": f"button[data-action='{act_id}']", "changed": True, "errors": []}
                ] if v["walk"] else [],
            }
        return out

    monkeypatch.setattr(checks, "measure", _fake_measure)
    res = checks.run(ws, "")
    assert res["verdict"] == "pass"
    assert res["blockers"] == 0

    checks_doc = json.loads((ws.round_folder() / "checks.json").read_text())
    summary_by_id = {r["id"]: r["result"] for r in checks_doc["checks"] if r.get("summary")}
    for family in ("render", "contract", "coverage", "figures", "integration"):
        assert summary_by_id[family] == "pass"
