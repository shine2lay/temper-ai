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
    task = (ws / "research/TASK.md").read_text()  # the caps are stated before the first check, not only after
    assert "a claim's text 5-400 characters" in task and "a context's why 10-400 characters" in task
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


def test_a_changed_rule_rejudges_the_same_files(tmp_path, fake_browser, monkeypatch):
    ws = packed(tmp_path)
    j = research_through_decision(ws, "homepage", monkeypatch)
    first = j.check("final")
    assert first.get("reused")  # same files, same rules: the verdict is replayed
    real = dr.file_digest
    monkeypatch.setattr(dr, "file_digest", lambda p: "changed" if Path(p) == Path(dr.rc.__file__) else real(p))
    again = dr.Job(str(ws), fixture=True).check("final")
    assert not again.get("reused") and again["attempt"] == first["attempt"] + 1


GATE_D1 = {"decided_by": "fixture-test", "direction": "D1", "users": "confirm",
           "reasons": "fixture run: the recommended direction"}


def test_a_fork_with_new_research_asks_the_gate_again_and_decides_again(tmp_path, fake_browser, monkeypatch):
    """A fork that assembles the research again gets a fresh gate answer and decision: no refusal, and no
    answer on file that was given to the earlier research (#38 fork 9d2df739 kept a 09:48Z answer)."""
    ws = packed(tmp_path)
    j = research_through_decision(ws, "homepage", monkeypatch)
    assert j.decision()["direction"] == "D1"
    first = json.loads((ws / "research/gate.json").read_text())
    assert first["answered"] == {"research_sha256": dr.file_digest(ws / "research/research.json"),
                                 "users_sha256": dr.file_digest(ws / "research/USERS.md")}
    research = json.loads((ws / "research/research.json").read_text())
    research["directions"][0]["axes"]["density"] = "medium"  # as a re-assembly under new rules would
    (ws / "research/research.json").write_text(json.dumps(research))
    again = dr.Job(str(ws), fixture=True)
    with pytest.raises(ValueError, match="answer it again"):
        again.decision()  # the answer on file was given to the earlier research
    assert not again.gate(json.dumps(GATE_D1)).get("reused")  # the same answer to new research is recorded anew
    gate = json.loads((ws / "research/gate.json").read_text())
    assert gate["answered"]["research_sha256"] == dr.file_digest(ws / "research/research.json")
    assert json.loads((ws / "research/gate-superseded-1.json").read_text())["answered"] == first["answered"]
    out = again.decision()
    assert not out.get("reused") and out["direction"] == "D1" and out["decided_by"] == "fixture-test"
    assert json.loads((ws / "research/fixed.json").read_text())["axes"]["density"] == "medium"
    state = json.loads((ws / "research/state.json").read_text())
    assert [s["stage"] for s in state["superseded"]] == ["gate", "decision"]
    assert again.gate(json.dumps(GATE_D1)).get("reused") and again.decision().get("reused")
    # A gate record from before this rule (no "answered") is still read.
    (ws / "research/gate.json").write_text(json.dumps({k: v for k, v in gate.items() if k != "answered"}))
    assert dr.Job(str(ws), fixture=True).decision()["direction"] == "D1"


def test_a_new_research_gate_answer_is_recorded_and_the_earlier_one_kept(tmp_path, fake_browser, monkeypatch):
    ws = packed(tmp_path)
    j = research_through_decision(ws, "homepage", monkeypatch)
    j.decision()
    again = dr.Job(str(ws), fixture=True)
    out = again.gate(json.dumps({**GATE_D1, "direction": "D2", "reasons": "fixture run: a fork answered again"}))
    assert out["direction"] == "D2" and again.decision()["direction"] == "D2"
    assert json.loads((ws / "research/gate.json").read_text())["direction"] == "D2"
    earlier = json.loads((ws / "research/gate-superseded-1.json").read_text())
    assert earlier["direction"] == "D1" and earlier["decided_by"] == "fixture-test" and earlier["reasons"]
    state = json.loads((ws / "research/state.json").read_text())
    assert [s["stage"] for s in state["superseded"]] == ["gate", "decision"]
    assert state["superseded"][0]["record"] == "research/gate-superseded-1.json"


def test_a_reused_workspace_still_refuses_a_changed_inventory(tmp_path, fake_browser, monkeypatch):
    ws = packed(tmp_path)
    research_through_decision(ws, "homepage", monkeypatch)
    with pytest.raises(ValueError, match="use a fresh workspace"):
        dr.Job(str(ws), fixture=True).inventory(json.dumps({"job": "logo"}))


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


def test_logo_brief_without_a_brief_fails_at_this_step(tmp_path, fake_browser, monkeypatch):
    ws = packed(tmp_path)
    j = research_through_decision(ws, "logo", monkeypatch)
    j.decision()
    with pytest.raises(ValueError):
        j.logo_brief("")


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
    b = brief_with(fixed_palette={"ink": "#142e34", "accent": "#277F88", "muted": "#52616A",
                                  "surface": "#F1F4F2"})
    lc.fixed_palette_check(shortlist(base), b)
    with pytest.raises(ValueError, match="outside the approved"):
        lc.fixed_palette_check(shortlist({**base, "accent": "#AA0000"}), b)
    other = brief_with(fixed_palette={"brand.teal": "#277F88", "brand.night": "#142E34", "white": "#FFFFFF"})
    with pytest.raises(ValueError, match="outside the approved"):
        lc.fixed_palette_check(shortlist(base), other)
    lc.fixed_palette_check(shortlist(base), brief_with())  # no approved palette: nothing to keep


def test_an_approved_accent_without_a_4_5_partner_takes_large_text_only():
    # #38 partial fork 40bd86e9: the approved accent #C76A12 reaches 4.5:1 with no approved colour, so the
    # concept check's 4.5:1 rule and the fixed palette could not both be met; the run looped until it failed.
    hv = importlib.import_module("design_homepage_v2")
    approved = {"#14202B", "#5A6672", "#C76A12", "#EEF1F4", "#FFFFFF"}
    concept = {"id": "A", "palette": {"dominant": "#14202B", "accent": "#C76A12", "ink": "#14202B",
                                      "surface": "#EEF1F4", "on_dominant": "#FFFFFF", "on_accent": "#FFFFFF"}}

    def contrast_problems(c, fixed=frozenset()):
        return [p for p in hv.concept_contract(c, set(), fixed) if "contrast" in p]

    assert contrast_problems(concept, approved) == []  # large text only; axe checks the page's text on it
    assert any("on_accent on accent contrast 3.8" in p for p in contrast_problems(concept))  # nothing approved: 4.5:1
    muted = {**concept, "palette": {**concept["palette"], "on_accent": "#5A6672"}}
    assert any("use the approved #14202B" in p and "large text" in p for p in contrast_problems(muted, approved))
    # Where an approved colour does reach 4.5:1 on the background, the concept must use one that does.
    teal = {**concept, "palette": {**concept["palette"], "accent": "#277F88", "on_accent": "#EEF1F4"}}
    assert any("the approved #FFFFFF reaches" in p for p in contrast_problems(teal, approved | {"#277F88"}))
    lines = dr.text_limits({"ink": "#14202B", "paper": "#FFFFFF", "accent": "#C76A12", "accent_on": "#FFFFFF"})
    assert lines == ["- accent #C76A12: no approved colour reaches 4.5:1 on it (best #14202B, 4.33:1): "
                     "only large text on it (24 px, or 19 px bold)"]
    assert dr.text_limits({"ink": "#142E34", "paper": "#FFFFFF"}) == []


def test_fit_fixed_palette_uses_approved_colours_that_pass_contrast():
    # Token names unlike the logo roles: a dark "accent" must not become the logo accent.
    fixed = {"dominant": "#B8482A", "accent": "#3E5B4A", "ink": "#1F1A17", "surface": "#FBF6EE",
             "on-dominant": "#FFFFFF", "on-accent": "#FFFFFF"}
    p = lc.fit_fixed_palette(fixed)
    lc.palette_contract(p)
    assert set(p.values()) <= set(fixed.values())
    assert p["ink"] == "#1F1A17" and p["accent"] == "#B8482A"
    lc.fixed_palette_check(shortlist(p), brief_with(fixed_palette=fixed))
    with pytest.raises(ValueError, match="cannot meet"):
        lc.fit_fixed_palette({"a": "#777777", "b": "#888888"})


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


@pytest.mark.parametrize("name", ["design_logo_v1_next", "design_logo_v1_next_fixture"])
def test_logo_candidates_save_design_files_after_final(name):
    wf, n = nodes(name)
    save = n["save_files"]
    assert save["agent"] == "design_research_stage_v1" and save["depends_on"] == ["final"]
    assert save["condition"] == {"source": "final.structured.verdict", "operator": "equals", "value": "approved"}
    assert save["input_map"]["stage"] == "save"
    assert wf["outputs"]["design_files_approved_by"] == "save_files.structured.approved_by"


# ---------------------------------------------------------------- saving a logo run's design files

LOGO_PALETTE = {"ink": "#1F1A17", "paper": "#FFFFFF", "accent": "#B8482A", "accent_on": "#FBF6EE",
                "muted": "#3E5B4A", "surface": "#FBF6EE"}
APPROVED = {"status": "approved", "approved_by": "fixture-test", "date": "2026-10-01"}


def logo_packet(ws: Path, palette: dict = LOGO_PALETTE) -> None:
    """What design_logo_v1's stages leave after the final gate approved (only the files the save reads)."""
    packet = ws / "logo"
    (packet / "exports").mkdir(parents=True, exist_ok=True)
    exports = []
    for board in ("primary", "symbol"):
        for kind, body in (("svg", b"<svg xmlns='http://www.w3.org/2000/svg'/>"), ("png", PNG)):
            path = packet / "exports" / f"selected-r01-{board}.{kind}"
            path.write_bytes(body + board.encode())
            exports.append({"path": f"logo/exports/{path.name}", "board": board, "kind": kind,
                            "sha256": df.sha256(path)})
    (packet / "BRAND.md").write_text("# Lanternfish mark\n\nUse on light surfaces.\n")
    (packet / "tokens.json").write_text(json.dumps({
        "product": "Lanternfish", "sRGB": palette, "font": {"family": "Source Sans Pro", "weight": "600",
                                                            "licence": "SIL OFL 1.1"},
        "clear_space_unit": "0.25 of the symbol box", "minimum_symbol_px": 24, "proposed_minimum_lockup_px": 160}))
    (packet / "selected.json").write_text(json.dumps({"concept": {
        "id": "c2", "name": "Steady lamp", "family": "symbol + wordmark", "idea": "A lamp that keeps its light."}}))
    final = {"gate": "final", "decided_by": "fixture-test", "decision": "approve",
             "reason": "Model-free fictional gate contract test; not a Design or owner decision."}
    (packet / "state.json").write_text(json.dumps({"final_approval": final}))
    (packet / "manifest.json").write_text(json.dumps({
        "final_approved": {"approved": True, "decided_by": "fixture-test"}, "exports": exports}))


def test_logo_save_writes_logo_palette_users_and_direction_then_the_next_run_follows_them(
        tmp_path, fake_browser, monkeypatch):
    ws = packed(tmp_path)
    j = research_through_decision(ws, "logo", monkeypatch)
    j.decision()
    with pytest.raises(ValueError, match="no final approval"):
        j.save_files()
    logo_packet(ws)
    out = j.save_files()
    assert out["approved_by"] == "fixture-test" and out["parts"] == ["colour", "direction", "logo", "users"]
    files = df.read_files(ws / "design-files-out")
    assert files["problems"] == []
    assert {p: (st or {}).get("approved_by") for p, st in files["parts"].items() if st} == {
        "users": "fixture-test", "direction": "fixture-test", "colour": "fixture-test", "logo": "fixture-test"}
    assert {h.upper() for h in df.token_hexes(files["tokens"], ("colour",))} == set(LOGO_PALETTE.values())
    assert sorted(files["design"]["logo_files"]) == ["logo/BRAND.md", "logo/primary.png", "logo/primary.svg",
                                                      "logo/symbol.png", "logo/symbol.svg"]
    design_md = (ws / "design-files-out/DESIGN.md").read_text()
    assert "Mark: Steady lamp" in design_md and "needs its own approval" in design_md
    assert j.save_files()["reused"]  # resumed after the save: nothing is written twice
    # Filed by the host, the next logo run for the product finds every part it needs approved
    df.apply(ws, tmp_path / "products.yaml", lab_root=tmp_path / "lab")
    ws2 = tmp_path / "ws2"
    df.pack(tmp_path / "products.yaml", "lanternfish", FIX / "lanternfish/source", ws2, lab_root=tmp_path / "lab")
    j2 = dr.Job(str(ws2), fixture=True)
    inv = j2.inventory(json.dumps({"job": "logo"}))
    assert inv["status"] == "defined" and inv["research_any"] == "no" and inv["gate"] == "off"
    j2.decision()
    with pytest.raises(ValueError, match="approved and fixed"):  # before any paid logo stage
        j2.logo_brief((FIX / "lanternfish/logo-brief.json").read_text())


def test_logo_save_refuses_exports_changed_after_the_final_gate(tmp_path, fake_browser, monkeypatch):
    ws = packed(tmp_path)
    j = research_through_decision(ws, "logo", monkeypatch)
    j.decision()
    logo_packet(ws)
    (ws / "logo/exports/selected-r01-primary.svg").write_text("<svg/>")
    with pytest.raises(ValueError, match="changed after the final gate"):
        j.save_files()


def approved_colour_and_type(ws: Path, palette: dict) -> None:
    """Design files in the run with colour and type approved (fixture-test), as the inventory would find them."""
    folder = ws / "design-files"
    folder.mkdir(parents=True, exist_ok=True)
    tokens = {"$description": "Lanternfish", "$extensions": {df.EXT: {"product": "lanternfish", "format": df.FORMAT}},
              "colour": df.token_group("colour", {"$type": "color", **{k.replace("_", "-"): df.color_token(v)
                                                                       for k, v in palette.items()}}, APPROVED),
              "type": df.token_group("type", {"text-family": {"$type": "fontFamily", "$value": "Instrument Sans"},
                                              "text-weight-400": {"$type": "fontWeight", "$value": 400}}, APPROVED)}
    (folder / "tokens.json").write_text(json.dumps(tokens, indent=2))
    status = {"colour": APPROVED, "type": APPROVED}
    approvals = [{"part": p, "approved_by": "fixture-test", "date": "2026-10-01", "reasons": "trial fixture"}
                 for p in ("colour", "type")]
    (folder / "DESIGN.md").write_text(df.render_design_md({
        "name": "Lanternfish", "product": "lanternfish", "updated": "2026-10-01", "status": status,
        "approvals": approvals}))
    assert df.read_files(folder)["problems"] == []
    inv_path = ws / "research/inventory.json"
    inv = json.loads(inv_path.read_text())
    inv["approved"]["colour"] = {"approved_by": "fixture-test", "date": "2026-10-01"}  # type: the logo job's not
    inv_path.write_text(json.dumps(inv))


def test_logo_save_keeps_the_approved_palette_and_parts_the_job_does_not_use(tmp_path, fake_browser, monkeypatch):
    ws = packed(tmp_path)
    j = research_through_decision(ws, "logo", monkeypatch)
    j.decision()
    approved_colour_and_type(ws, LOGO_PALETTE)
    old = json.loads((ws / "design-files/tokens.json").read_text())
    logo_packet(ws, {**LOGO_PALETTE, "surface": "#FFFFFF"})  # a subset of the approved colours
    out = j.save_files()
    assert out["parts"] == ["direction", "logo", "users"] and out["kept"] == ["colour", "type"]
    saved = json.loads((ws / "design-files-out/tokens.json").read_text())
    assert saved["colour"] == old["colour"] and saved["type"] == old["type"]
    design_md = (ws / "design-files-out/DESIGN.md").read_text()
    assert "- colour: fixture-test on 2026-10-01: trial fixture" in design_md
    assert "- type: fixture-test on 2026-10-01: trial fixture" in design_md
    assert df.read_files(ws / "design-files-out")["problems"] == []


def test_logo_save_refuses_a_logo_colour_outside_the_approved_palette(tmp_path, fake_browser, monkeypatch):
    ws = packed(tmp_path)
    j = research_through_decision(ws, "logo", monkeypatch)
    j.decision()
    approved_colour_and_type(ws, LOGO_PALETTE)
    logo_packet(ws, {**LOGO_PALETTE, "accent": "#AA0000"})
    with pytest.raises(ValueError, match="outside the approved palette: #AA0000"):
        j.save_files()


def test_live_workflows_unchanged_names():
    for name in ("design_homepage_v2", "design_logo_v1"):
        _, n = nodes(name)
        assert "research" not in n
