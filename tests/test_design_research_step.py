"""The research step's stages and the candidate workflows that use it (Design queue #38).

Runs design_research.py's stages on the fictional Lanternfish fixture with the browser replaced
(category capture and board render are faked), so no model, browser or network is used.
docs/design-files.md describes the step.
"""
import importlib
import json
import shutil
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "configs/design/bin"
sys.path.insert(0, str(BIN))
df = importlib.import_module("design_files")
dr = importlib.import_module("design_research")
lc = importlib.import_module("logo_contracts")

FIX = ROOT / "configs/design/fixtures/research"
WF = ROOT / "configs/design/workflows"
AGENTS = ROOT / "configs/design/agents"
PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 32

FACTS = {
    "viewport": [1440, 900], "first_items": 14, "first_words": 67, "first_fill": 0.31,
    "sizes": {"16": 231, "17": 97, "24": 66, "40": 97}, "display_px": 40, "h1_px": 40,
    "animated": 0, "loops": 0, "animation_seconds": 0, "transitions": 0, "arrival_animations": 0,
    "scroll_animations": 0, "colours": {"#1f1a17": 25, "#ffffff": 7, "#b8482a": 6}, "fonts": {"instrument sans": 615},
    "height": 1685, "pixels": {"mean_chroma": 0.026, "saturated_share": 0.05, "vivid_share": 0.007,
                               "lightness_mean": 0.88, "lightness_spread": 0.18},
    "text": "Keep the night log in order. " * 12,
}


@pytest.fixture
def fake_browser(monkeypatch):
    calls = {"measure": 0}

    def measure(root, jobs, timeout=120):
        calls["measure"] += 1
        root.mkdir(parents=True, exist_ok=True)
        out = []
        for j in jobs:
            (root / f"{j['name']}-first.png").write_bytes(PNG)
            out.append({"name": j["name"], "ok": True, "facts": dict(FACTS)})
        return out

    def board(self, research):
        (self.dir / "board").mkdir(parents=True, exist_ok=True)
        (self.dir / "board" / "index.html").write_text(dr.board_html(research))
        return {"png": "research/board/board.png", "height": 2000, "min_px": 16, "min_contrast": 8.0,
                "text_elements": 100, "problems": []}

    monkeypatch.setattr(dr, "measure_pages", measure)
    monkeypatch.setattr(dr.Job, "board", board)
    return calls


def packed(tmp_path: Path) -> Path:
    reg = tmp_path / "products.yaml"
    shutil.copyfile(FIX / "products.yaml", reg)
    ws = tmp_path / "ws"
    df.pack(reg, "lanternfish", FIX / "lanternfish/source", ws, lab_root=tmp_path / "lab")
    return ws


def research_through_decision(ws: Path, job: str, monkeypatch) -> "dr.Job":
    j = dr.Job(str(ws), fixture=True)
    inv = j.inventory(json.dumps({"job": job}))
    assert inv["status"] == "none" and inv["gate"] == "on" and inv["research_agent"] == "yes"
    j.fixture_stage("users")
    assert j.check("final")["verdict"] == "ok"
    assert j.capture()["captured"] == 6
    j.fixture_stage("direction")
    assert j.assemble("final")["verdict"] == "ok"
    with pytest.raises(ValueError):
        j.gate(json.dumps({"decided_by": "design", "direction": "D1", "users": "confirm", "reasons": "a fixture run"}))
    out = j.gate(json.dumps({"decided_by": "fixture-test", "direction": "D1", "users": "confirm",
                             "reasons": "fixture run: the recommended direction"}))
    assert out["decided_by"] == "fixture-test"
    return j


def test_none_branch_runs_every_research_stage(tmp_path, fake_browser, monkeypatch):
    ws = packed(tmp_path)
    j = research_through_decision(ws, "homepage", monkeypatch)
    d = j.decision()
    assert d["decided_by"] == "fixture-test" and d["direction"] == "D1" and d["gated"] is True
    research = json.loads((ws / "research/research.json").read_text())
    assert {c["id"] for c in research["contexts"]} == {"marketing-landing-general", "saas-b2b-settings"}
    assert len(research["category"]["sites"]) == 6
    users = json.loads((ws / "research/users.json").read_text())
    status = {c["id"]: c["status"] for c in users["claims"]}
    assert status["c5"] == "superseded" and status["c8"] == "rejected"
    for_design = (ws / "research/FOR_DESIGN.md").read_text()
    assert "decided_by fixture-test" in for_design and "Night Watch" in for_design
    gate = json.loads((ws / "research/gate.json").read_text())
    assert gate["decided_by"] == "fixture-test" and gate["gate"] == "research"
    fixed = json.loads((ws / "research/fixed.json").read_text())
    assert fixed["status"] == "none" and fixed["axes"]["density"] == "high"


def test_finished_stages_are_not_repeated(tmp_path, fake_browser, monkeypatch):
    ws = packed(tmp_path)
    j = research_through_decision(ws, "homepage", monkeypatch)
    again = dr.Job(str(ws), fixture=True)
    assert again.capture()["captured"] == 6
    assert again.assemble("final")["verdict"] == "ok"
    assert fake_browser["measure"] == 1
    assert j.decision() == again.decision()


def test_logo_brief_carries_context_meaning_and_category_marks(tmp_path, fake_browser, monkeypatch):
    ws = packed(tmp_path)
    j = research_through_decision(ws, "logo", monkeypatch)
    j.decision()
    out = j.logo_brief((FIX / "lanternfish/logo-brief.json").read_text())
    brief = json.loads(out["brief"])
    assert brief["context"] == "saas-b2b-settings"  # the product's context, not the page's
    assert brief["meaning"].startswith("A small, steady light")
    assert out["marks"] == 6
    lc.brief_contract(brief, "fixture")
    files = brief["research"]["files"]
    assert "comparison.md" in files and len([f for f in files if f.endswith(".png")]) == 6
    comparison = (Path(brief["research"]["dir"]) / "comparison.md").read_text()
    for site in ("atlas", "harbor", "pulse", "rich", "contrast", "atlas-again"):
        assert f"| {site} |" in comparison
    assert "fixed_palette" not in brief


def test_research_gate_off_skips_the_gate(tmp_path, fake_browser):
    ws = packed(tmp_path)
    j = dr.Job(str(ws), fixture=True)
    inv = j.inventory(json.dumps({"job": "homepage", "gate": "off"}))
    assert inv["gate"] == "off"
    with pytest.raises(ValueError, match="gate is off"):
        j.gate(json.dumps({"decided_by": "fixture-test", "direction": "D1", "users": "confirm", "reasons": "x y z"}))


# ---------------------------------------------------------------- logo contracts


def brief_with(**extra):
    b = json.loads((FIX / "lanternfish/logo-brief.json").read_text())
    b.update(extra)
    return b


def test_brief_contract_accepts_research_keys_and_checks_them():
    lc.brief_contract(brief_with(context="saas-b2b-settings", meaning="A steady light.",
                                 fixed_palette={"ink": "#142E34", "accent": "#277F88"}), "fixture")
    with pytest.raises(ValueError, match="playbook context id"):
        lc.brief_contract(brief_with(context="Not An Id!"), "fixture")
    with pytest.raises(ValueError, match="fixed palette"):
        lc.brief_contract(brief_with(fixed_palette={"ink": "teal"}), "fixture")


def shortlist(palette):
    return {"shortlist": [{"id": f"s{i}", "palette": dict(palette)} for i in range(3)]}


def test_fixed_palette_keeps_approved_colours():
    base = {"ink": "#142E34", "paper": "#FFFFFF", "accent": "#277F88", "accent_on": "#FFFFFF",
            "muted": "#52616A", "surface": "#F1F4F2"}
    b = brief_with(fixed_palette={"ink": "#142e34", "accent": "#277F88"})
    lc.fixed_palette_check(shortlist(base), b)
    with pytest.raises(ValueError, match="changes an approved"):
        lc.fixed_palette_check(shortlist({**base, "accent": "#AA0000"}), b)
    other = brief_with(fixed_palette={"brand.teal": "#277F88", "brand.night": "#142E34", "white": "#FFFFFF"})
    with pytest.raises(ValueError, match="outside the approved"):
        lc.fixed_palette_check(shortlist(base), other)
    lc.fixed_palette_check(shortlist(base), brief_with())  # no approved palette: nothing to keep


# ---------------------------------------------------------------- candidate workflows


def nodes(name):
    wf = yaml.safe_load((WF / f"{name}.yaml").read_text())["workflow"]
    assert wf["name"] == name
    return wf, {n["name"]: n for n in wf["nodes"]}


@pytest.mark.parametrize("name", ["design_homepage_v2_next", "design_homepage_v2_next_fixture",
                                  "design_logo_v1_next", "design_logo_v1_next_fixture"])
def test_candidates_research_first_with_a_research_gate(name):
    wf, n = nodes(name)
    gate = n["research_gate"]
    assert gate["gate"] is True and gate["condition"]["source"] == "research.structured.gate"
    assert n["research"]["input_map"]["stage"] == "inventory"
    assert n["research_capture"]["condition"]["source"] == "research.structured.research_category"
    for node in wf["nodes"]:
        if node.get("gate"):
            assert node["name"] in {"research_gate", "direction", "final", "initial_budget", "refine_budget"}
        assert (AGENTS / f"{node['agent']}.yaml").is_file(), node["agent"]
    assert wf["outputs"]["research_decided_by"] == "research_decision.structured.decided_by"


@pytest.mark.parametrize("name", ["design_logo_v1_next", "design_logo_v1_next_fixture"])
def test_logo_candidates_brief_from_research(name):
    _, n = nodes(name)
    assert n["research_logo_brief"]["input_map"]["stage"] == "logo_brief"
    assert n["brief"]["input_map"]["brief_json"] == "research_logo_brief.structured.brief"
    assert n["brief"]["depends_on"] == ["research_logo_brief"]


def test_logo_candidate_palette_is_bound_by_the_approved_palette():
    _, n = nodes("design_logo_v1_next")
    assert n["palette"]["agent"] == "design_logo_palette_v1_next"
    prompt = yaml.safe_load((AGENTS / "design_logo_palette_v1_next.yaml").read_text())["agent"]["system_prompt"]
    assert "fixed_palette" in prompt
    assert all(m["input_map"]["mode"] == "input.mode" for k, m in n.items()
               if m["agent"] == "design_logo_stage_v1")


def test_homepage_candidate_saves_design_files_after_final():
    wf, n = nodes("design_homepage_v2_next")
    assert n["save_files"]["depends_on"] == ["after_final"] and n["after_final"]["depends_on"] == ["final"]
    assert n["save_files"]["condition"] == {"source": "final.structured.verdict", "operator": "equals",
                                           "value": "approved"}
    assert wf["outputs"]["design_files_approved_by"] == "save_files.structured.approved_by"
    assert n["copy"]["depends_on"] == ["research_decision"]


def test_live_workflows_unchanged_names():
    for name in ("design_homepage_v2", "design_logo_v1"):
        _, n = nodes(name)
        assert "research" not in n
