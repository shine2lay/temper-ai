"""A product's design files, the registry and the model-free inventory (Design queue #38).

docs/design-files.md: DESIGN.md + tokens.json (DTCG 2025.10) with a status per part, the registry
configs/design/products.yaml (locations and statuses only), and the inventory that tells a design
workflow whether a product is defined, partial or none for a job. No model, browser or network.
"""
import importlib
import json
import re
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "configs/design/bin"
sys.path.insert(0, str(BIN))
df = importlib.import_module("design_files")

DAY = "2026-10-05"


def approved(by="fixture-test", date=DAY):
    return {"status": "approved", "approved_by": by, "date": date}


def tokens_for(statuses: dict) -> dict:
    """A full DTCG token set; each part's group carries the given status (parts without one are left out)."""
    groups = {
        "colour": {"$type": "color", "ink": df.color_token("#1A1A17"), "paper": df.color_token("#F7F5EF"),
                   "accent": df.color_token("#2E7D4F")},
        "type": {"family": {"$type": "fontFamily", "text": {"$value": ["Source Sans 3", "sans-serif"]}},
                 "size": {"$type": "dimension", "body": {"$value": {"value": 16, "unit": "px"}},
                          "display": {"$value": {"value": 48, "unit": "px"}}},
                 "weight": {"$type": "fontWeight", "bold": {"$value": 700}}},
        "spacing": {"$type": "dimension", "s": {"$value": {"value": 8, "unit": "px"}},
                    "m": {"$value": {"value": 16, "unit": "px"}}},
        "radius": {"$type": "dimension", "control": {"$value": {"value": 6, "unit": "px"}}},
        "elevation": {"$type": "shadow", "card": {"$value": {
            "color": {"colorSpace": "srgb", "components": [0, 0, 0], "hex": "#000000", "alpha": 0.12},
            "offsetX": {"value": 0, "unit": "px"}, "offsetY": {"value": 2, "unit": "px"},
            "blur": {"value": 8, "unit": "px"}, "spread": {"value": 0, "unit": "px"}}}},
        "motion": {"fast": {"$type": "duration", "$value": {"value": 150, "unit": "ms"}},
                   "ease": {"$type": "cubicBezier", "$value": [0.2, 0, 0, 1]}},
    }
    return {part: df.token_group(part, groups[part], st) for part, st in statuses.items() if part in df.TOKEN_PARTS}


def write_files(folder: Path, product: str, statuses: dict, *, groups=("Dispatchers",), logo=False,
                owner_words=None) -> Path:
    """A product's design files with the given part statuses (missing parts left out)."""
    folder.mkdir(parents=True, exist_ok=True)
    approvals = []
    for part, st in statuses.items():
        if st["status"] != "approved":
            continue
        if st["approved_by"] == "owner":
            approvals.append({"part": part, **st, "words": owner_words or "yes, that one", "source": "home chat m00001"})
        else:
            approvals.append({"part": part, **st, "reasons": "fits the users the research found"})
    users_lines = []
    for g in groups:
        users_lines += [f"### {g}", "Also called: planners", "- Work long shifts on two monitors. [source/docs/interviews.md]", ""]
    model = {"name": product.title(), "product": product, "updated": DAY, "status": statuses,
             "users_lines": users_lines if "users" in statuses else [],
             "direction_lines": ["Contexts: marketing-landing-general (page)", "Family: flat 2.0"] if "direction" in statuses else [],
             "logo_lines": ["Files: logo/mark.svg"] if logo else [], "approvals": approvals}
    (folder / "DESIGN.md").write_text(df.render_design_md(model))
    toks = tokens_for(statuses)
    if toks:
        (folder / "tokens.json").write_text(json.dumps(toks, indent=2) + "\n")
    if logo:
        (folder / "logo").mkdir(exist_ok=True)
        (folder / "logo/mark.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 8 8"><rect width="8" height="8"/></svg>\n')
    return folder


HOMEPAGE_PARTS = ("users", "direction", "colour", "type", "spacing", "radius", "elevation", "motion")


def fixture_registry(tmp: Path) -> Path:
    """Three fictional products: fully approved, partial (logo + palette), none (only current CSS)."""
    lab = tmp / "lab"
    write_files(lab / "products/harbourline", "harbourline", {p: approved() for p in HOMEPAGE_PARTS})
    write_files(lab / "products/partial-co", "partial-co", {"colour": approved(), "logo": approved()}, logo=True)
    (tmp / "app/frontend").mkdir(parents=True)
    (tmp / "app/frontend/tokens.css").write_text(":root { --brand: #7c3aed; }\n")
    reg = {"version": 1, "fixture": True, "repos": {"app": str(tmp / "app")}, "products": {
        "harbourline": {"name": "Harbourline", "location": {"kind": "lab", "path": "products/harbourline"},
                        "parts": {p: approved() for p in HOMEPAGE_PARTS}},
        "partial-co": {"name": "Partial Co", "location": {"kind": "lab", "path": "products/partial-co"},
                       "parts": {"colour": approved(), "logo": approved()}},
        "bare-app": {"name": "Bare App", "location": {"kind": "repo", "repo": "app", "path": "design"},
                     "current_state": ["frontend/tokens.css"], "parts": {}}}}
    path = tmp / "products.yaml"
    path.write_text("# fixture registry\n" + yaml.safe_dump(reg, sort_keys=False))
    return path


def files_for(tmp: Path, product: str):
    reg = df.load_registry(tmp / "products.yaml")
    entry = reg["products"][product]
    return entry, df.read_files(df.location_dir(reg, entry, tmp / "lab"))


# ---------------------------------------------------------------- the real registry and docs

def test_real_registry_is_valid_and_holds_locations_and_statuses_only():
    reg = df.load_registry(df.REGISTRY)
    assert reg["version"] == 1 and not reg.get("fixture")
    for pid, entry in reg["products"].items():
        assert set(entry) <= {"name", "location", "parts", "current_state", "force_research", "note"}, pid
        for part, st in (entry.get("parts") or {}).items():
            assert st["approved_by"] in ("design", "owner") if st["status"] == "approved" else True
    temper = reg["products"]["temper"]
    assert temper["location"] == {"kind": "lab", "path": "products/temper"}
    assert {p for p, s in temper["parts"].items() if s["status"] == "approved"} == {"logo", "colour"}
    rollcall = reg["products"]["rollcall"]
    assert rollcall["parts"] == {} and rollcall["current_state"] == ["frontend/src/styles/tokens.css"]


def test_registry_text_has_no_design_content():
    text = df.REGISTRY.read_text()
    body = "\n".join(ln for ln in text.splitlines() if not ln.startswith("#"))
    assert not re.search(r"#[0-9A-Fa-f]{6}\b", body)
    for word in ("hex", "font", "users:", "direction:", "words", "reasons"):
        assert word not in body, word


def test_docs_cover_parts_statuses_and_commands():
    doc = (ROOT / "docs/design-files.md").read_text()
    for word in (*df.PARTS, "defined", "partial", "none", "products.yaml", "DTCG", "decided_by", "fixture-test",
                 "pack", "apply", "approve", "inventory", "RESEARCH.md", "research.json", "board"):
        assert word in doc, word


# ---------------------------------------------------------------- statuses and registry checks

def test_status_rules_real_and_fixture():
    assert df.check_status("colour", approved("design"), fixture=False) == []
    assert df.check_status("colour", approved("owner"), fixture=False) == []
    assert df.check_status("colour", approved("fixture-test"), fixture=False)
    assert df.check_status("colour", approved("design"), fixture=True), "a fixture never claims a Design decision"
    assert df.check_status("colour", {"status": "draft", "date": DAY}, fixture=False) == []
    assert df.check_status("colour", {"status": "draft", "approved_by": "design", "date": DAY}, fixture=False)
    assert df.check_status("colour", {"status": "approved", "approved_by": "design", "date": "Oct 5"}, fixture=False)


@pytest.mark.parametrize("change, needle", [
    (lambda e: e.update(palette={"ink": "#000000"}), "unknown keys"),
    (lambda e: e["location"].update(path="../elsewhere"), "relative"),
    (lambda e: e["location"].update(kind="repo", repo="nowhere"), "repositor"),
    (lambda e: e["parts"].update(fonts=approved()), "unknown part"),
    (lambda e: e.update(force_research="yes"), "force_research"),
])
def test_registry_entry_problems(change, needle):
    entry = {"name": "X", "location": {"kind": "lab", "path": "products/x"}, "parts": {}}
    change(entry)
    problems = df.check_registry({"version": 1, "fixture": True, "repos": {}, "products": {"x": entry}})
    assert any(needle in p for p in problems), problems


# ---------------------------------------------------------------- DESIGN.md and tokens.json

def test_rendered_files_round_trip(tmp_path):
    folder = write_files(tmp_path / "f", "harbourline", {**{p: approved() for p in HOMEPAGE_PARTS}, "logo": approved()},
                         groups=("Dispatchers", "Fleet owners"), logo=True)
    found = df.read_files(folder)
    assert found["problems"] == []
    assert all(found["parts"][p] == approved() for p in (*HOMEPAGE_PARTS, "logo"))
    assert found["parts"]["library"] is None
    assert [g["name"] for g in found["groups"]] == ["Dispatchers", "Fleet owners"]
    assert df.token_hexes(found["tokens"], ("colour",)) == ["#1A1A17", "#2E7D4F", "#F7F5EF"]
    assert df.token_fonts(found["tokens"]) == ["Source Sans 3", "sans-serif"]


def test_mirror_and_approval_lines_must_agree(tmp_path):
    folder = write_files(tmp_path / "f", "harbourline", {"colour": approved()})
    text = (folder / "DESIGN.md").read_text()
    (folder / "DESIGN.md").write_text(text.replace("- colour: approved by fixture-test on 2026-10-05", "- colour: draft"))
    assert any("Tokens line for colour" in p for p in df.read_files(folder)["problems"])
    (folder / "DESIGN.md").write_text("\n".join(ln for ln in text.splitlines() if not ln.startswith("- colour: fixture-test")) + "\n")
    assert any("Approvals" in p for p in df.read_files(folder)["problems"])


def test_owner_approval_quotes_his_words_with_source(tmp_path):
    folder = write_files(tmp_path / "f", "harbourline", {"colour": approved("owner")}, owner_words="keep the green")
    found = df.read_files(folder)
    assert found["problems"] == []
    assert found["design"]["approvals"]["colour"] == {"approved_by": "owner", "date": DAY, "words": "keep the green",
                                                      "source": "home chat m00001"}
    text = (folder / "DESIGN.md").read_text().replace('"keep the green" (home chat m00001)', "he liked it")
    (folder / "DESIGN.md").write_text(text)
    assert any("own words" in p for p in df.read_files(folder)["problems"])


@pytest.mark.parametrize("bad, needle", [
    ({"colour": {"$type": "color", "x": {"$value": "#FFFFFF"}}}, "colour"),
    ({"colour": {"$type": "color", "x": {"$value": {"colorSpace": "srgb", "components": [1, 1, 1], "hex": "#000000"}}}}, "disagree"),
    ({"type": {"x": {"$type": "fontSize", "$value": 16}}}, "$type is one of"),
    ({"spacing": {"$type": "dimension", "x": {"$value": "8px"}}}, "dimension"),
    ({"palette": {"$type": "color"}}, "part"),
])
def test_token_problems(bad, needle):
    problems = df.check_tokens(bad)
    assert any(needle in p for p in problems), problems


def test_temper_style_partial_files_parse(tmp_path):
    """The shape of Temper's lab files (logo + palette approved by the owner, the rest missing)."""
    folder = write_files(tmp_path / "t", "temper", {"colour": approved("owner", "2026-10-03"),
                                                    "logo": approved("owner", "2026-10-03")}, logo=True)
    found = df.read_files(folder)
    assert found["problems"] == []
    reg_entry = {"name": "Temper", "location": {"kind": "lab", "path": "products/temper"},
                 "parts": {"colour": approved("owner", "2026-10-03"), "logo": approved("owner", "2026-10-03")}}
    inv = df.inventory(reg_entry, found, "logo")
    assert inv["status"] == "partial" and inv["fixed"] == ["logo", "colour"] and inv["missing"] == ["users", "direction"]


# ---------------------------------------------------------------- inventory: defined, partial, none

def test_inventory_three_fixtures_take_the_right_branch(tmp_path):
    fixture_registry(tmp_path)
    entry, files = files_for(tmp_path, "harbourline")
    inv = df.inventory(entry, files, "homepage", fixture=True)
    assert inv["status"] == "defined" and inv["missing"] == [] and inv["research"]["any"] is False
    entry, files = files_for(tmp_path, "partial-co")
    inv = df.inventory(entry, files, "homepage", fixture=True)
    assert inv["status"] == "partial"
    assert inv["fixed"] == ["colour", "logo"] and "colour" not in inv["missing"]
    assert inv["research"] == {"users": "full", "direction": True, "category": True, "any": True}
    entry, files = files_for(tmp_path, "bare-app")
    assert files is None
    inv = df.inventory(entry, files, "homepage", fixture=True)
    assert inv["status"] == "none" and inv["missing"] == list(HOMEPAGE_PARTS) and inv["fixed"] == []


def test_inventory_logo_job_on_partial_product(tmp_path):
    fixture_registry(tmp_path)
    entry, files = files_for(tmp_path, "partial-co")
    inv = df.inventory(entry, files, "logo", fixture=True)
    assert inv["status"] == "partial" and inv["missing"] == ["users", "direction"]
    assert inv["research"]["category"] is True  # direction research needs the category


def test_inventory_audience_gap_researches_that_audience_only(tmp_path):
    fixture_registry(tmp_path)
    entry, files = files_for(tmp_path, "harbourline")
    same = df.inventory(entry, files, "homepage", audience="dispatch planners at regional carriers", fixture=True)
    assert same["status"] == "defined" and same["audience"]["group"] == "Dispatchers" and same["research"]["any"] is False
    gap = df.inventory(entry, files, "homepage", audience="insurance brokers", fixture=True)
    assert gap["status"] == "defined" and gap["audience"]["gap"] is True
    assert gap["research"] == {"users": "audience", "direction": False, "category": False, "any": True}


def test_inventory_force_and_disagreement(tmp_path):
    fixture_registry(tmp_path)
    entry, files = files_for(tmp_path, "harbourline")
    forced = df.inventory(entry, files, "homepage", force=["direction"], fixture=True)
    assert forced["status"] == "partial" and forced["missing"] == ["direction"] and forced["forced"] == ["direction"]
    assert df.inventory(entry, files, "homepage", force=True, fixture=True)["status"] == "none"
    entry = {**entry, "parts": {**entry["parts"], "colour": approved(date="2026-10-01")}}
    with pytest.raises(ValueError, match="disagree"):
        df.inventory(entry, files, "homepage", fixture=True)


def test_inventory_refuses_fixture_approvals_in_real_runs(tmp_path):
    fixture_registry(tmp_path)
    entry, files = files_for(tmp_path, "harbourline")
    with pytest.raises(ValueError, match="this run accepts design or owner"):
        df.inventory(entry, files, "homepage", fixture=False)


def test_inventory_drafts_are_missing(tmp_path):
    folder = write_files(tmp_path / "d", "draft-co", {"users": {"status": "draft", "date": DAY}})
    entry = {"name": "D", "location": {"kind": "lab", "path": "x"}, "parts": {"users": {"status": "draft", "date": DAY}}}
    inv = df.inventory(entry, df.read_files(folder), "homepage")
    assert inv["status"] == "none" and inv["drafts"] == ["users"]


# ---------------------------------------------------------------- pack, apply, approve

def test_pack_copies_and_pins_hashes(tmp_path):
    reg = fixture_registry(tmp_path)
    src = tmp_path / "src"
    (src / "docs").mkdir(parents=True)
    (src / "README.md").write_text("# Partial Co\n")
    (src / "docs/notes.md").write_text("notes\n")
    (src / ".secret").write_text("x\n")
    ws = tmp_path / "ws"
    manifest = df.pack(reg, "partial-co", src, ws, lab_root=tmp_path / "lab")
    assert set(manifest["files"]) == {"README.md", "docs/notes.md"}
    assert set(manifest["design_files"]) == {"DESIGN.md", "tokens.json", "logo/mark.svg"}
    assert manifest["fixture"] is True
    assert df.verify_pack(ws)["product"] == "partial-co"
    (ws / "design-files/tokens.json").write_text("{}\n")
    with pytest.raises(ValueError, match="changed after packing"):
        df.verify_pack(ws)
    with pytest.raises(ValueError, match="already holds a pack"):
        df.pack(reg, "partial-co", src, ws, lab_root=tmp_path / "lab")


def test_pack_current_state_is_audited_not_followed(tmp_path):
    reg = fixture_registry(tmp_path)
    manifest = df.pack(reg, "bare-app", None, tmp_path / "ws", lab_root=tmp_path / "lab")
    assert manifest["design_files"] == {} and set(manifest["current_state"]) == {"frontend/tokens.css"}
    assert (tmp_path / "ws/source/current-state/frontend/tokens.css").is_file()
    assert not (tmp_path / "ws/design-files").exists()


def saved_run(tmp: Path, reg: Path, product: str, statuses: dict, keep: dict | None = None) -> Path:
    """A run's saved design files: the parts it decided plus the approved parts it kept unchanged."""
    ws = tmp / f"ws-{product}"
    df.pack(reg, product, None, ws, lab_root=tmp / "lab")
    write_files(ws / "design-files-out", product, {**(keep or {}), **statuses}, logo="logo" in (keep or {}))
    (ws / "design-files-out/registry-update.json").write_text(json.dumps({"product": product, "parts": statuses}))
    return ws


def test_apply_lab_product_keeps_history_and_updates_registry(tmp_path):
    reg = fixture_registry(tmp_path)
    statuses = {p: approved() for p in HOMEPAGE_PARTS}
    dropped = saved_run(tmp_path, reg, "partial-co", statuses)
    with pytest.raises(ValueError, match="drop or change approved part logo"):
        df.apply(dropped, reg, lab_root=tmp_path / "lab")
    import shutil
    shutil.rmtree(dropped)
    ws = saved_run(tmp_path, reg, "partial-co", statuses, keep={"logo": approved()})
    result = df.apply(ws, reg, lab_root=tmp_path / "lab")
    assert result["registry_updated"] is True
    entry, files = files_for(tmp_path, "partial-co")
    assert all(entry["parts"][p] == approved() for p in HOMEPAGE_PARTS)
    assert files["problems"] == [] and files["parts"]["users"] == approved()
    assert list((tmp_path / "lab/products/partial-co/.history").iterdir())
    assert df.inventory(entry, files, "homepage", fixture=True)["status"] == "defined"


def test_apply_repo_product_hands_off_and_leaves_registry(tmp_path):
    reg = fixture_registry(tmp_path)
    before = reg.read_text()
    ws = saved_run(tmp_path, reg, "bare-app", {"users": approved()})
    result = df.apply(ws, reg, lab_root=tmp_path / "lab")
    assert result["registry_updated"] is False and Path(result["handoff"]).is_dir()
    assert reg.read_text() == before


def test_apply_refuses_mismatched_update(tmp_path):
    reg = fixture_registry(tmp_path)
    ws = saved_run(tmp_path, reg, "partial-co", {"users": approved()})
    (ws / "design-files-out/registry-update.json").write_text(json.dumps({"product": "partial-co",
                                                                          "parts": {"users": approved(date="2026-10-04")}}))
    with pytest.raises(ValueError, match="disagree"):
        df.apply(ws, reg, lab_root=tmp_path / "lab")


def test_approve_needs_reasons_or_owner_words(tmp_path):
    reg = fixture_registry(tmp_path)
    with pytest.raises(ValueError, match="reasons"):
        df.approve(reg, "partial-co", "colour", "fixture-test", lab_root=tmp_path / "lab")
    real = tmp_path / "real.yaml"
    data = yaml.safe_load(reg.read_text())
    data["fixture"] = False
    data["products"] = {"partial-co": {**data["products"]["partial-co"], "parts": {}}}
    real.write_text(yaml.safe_dump(data))
    folder = tmp_path / "lab/products/partial-co"
    write_files(folder, "partial-co", {"colour": {"status": "draft", "date": DAY}})
    with pytest.raises(ValueError, match="own words"):
        df.approve(real, "partial-co", "colour", "owner", lab_root=tmp_path / "lab")
    out = df.approve(real, "partial-co", "colour", "owner", lab_root=tmp_path / "lab", words="use this green",
                     source="home chat m02900")
    assert out["approved_by"] == "owner"
    found = df.read_files(folder)
    assert found["problems"] == [] and found["parts"]["colour"]["approved_by"] == "owner"
    assert found["design"]["approvals"]["colour"]["words"] == "use this green"
    assert df.load_registry(real)["products"]["partial-co"]["parts"]["colour"]["approved_by"] == "owner"


def test_cli_inventory_and_checks(tmp_path, capsys):
    reg = fixture_registry(tmp_path)
    assert df.main(["registry-check", "--registry", str(reg)]) == 0
    assert df.main(["inventory", "--registry", str(reg), "--product", "partial-co", "--job", "logo",
                    "--lab", str(tmp_path / "lab")]) == 0
    out = capsys.readouterr().out
    assert '"status": "partial"' in out
