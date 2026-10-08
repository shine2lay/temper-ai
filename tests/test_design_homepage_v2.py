"""Model-free contracts for Design's homepage workflow v2 and its HTML->Penpot converter.

No models, accounts, browsers or Penpot server: a recorded browser scene of a fixture page
(tests/design_homepage_v2_scenes/, captured from configs/design/testpages/html-fixtures/
atlas.html) stands in for the browser, and a fake Penpot client applies the changes in
memory. The live proofs (real Penpot, real editor, fidelity) are evidence in Design's
results folder, not unit tests.
"""
import importlib.util
import json
import re
import shutil
import sys
from pathlib import Path

import pytest
import yaml

from temper_ai.stage.models import WorkflowConfig

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "configs/design/bin"
SCENES = Path(__file__).resolve().parent / "design_homepage_v2_scenes"
SITE = ROOT / "configs/design/testpages/html-fixtures"
sys.path.insert(0, str(BIN))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, BIN / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


h2p = _load("html_to_penpot")
v2 = _load("design_homepage_v2")
BASE = "http://172.21.0.1:39385"  # the recorded scenes' page address
RUNTIME_SCENES = Path(__file__).resolve().parent / "design_runtime_scenes"  # recorded runtime-check results


def scenes(widths=(390, 1440)):
    return {w: json.loads((SCENES / f"scene-{w}.json").read_text()) for w in widths}


# --------------------------------------------------------------------------- workflows


def workflow(name):
    raw = yaml.safe_load((BIN.parent / "workflows" / f"{name}.yaml").read_text())["workflow"]
    assert WorkflowConfig.from_dict(raw).name == name
    return raw, {n["name"]: n for n in raw["nodes"]}


@pytest.mark.parametrize("name", ["design_homepage_v2", "design_homepage_v2_fixture", "design_homepage_v2_pilot",
                                  "design_homepage_v2_bench"])
def test_run_result_says_who_decided_each_gate(name):
    # The run's outputs carry both gate flags ({approved, decided_by}), so a result never needs job.json to say
    # who decided; no output is named for the owner.
    raw, _ = workflow(name)
    assert raw["outputs"]["direction_approved"] == "final.structured.direction_approved"
    assert raw["outputs"]["final_approved"] == "final.structured.final_approved"
    assert not [k for k in raw["outputs"] if "owner" in k]


RESEARCH_OUTPUTS = {"research_path", "research_board", "research_direction", "research_decided_by", "design_status",
                    "design_files", "design_files_approved_by"}


def pre_research():
    """design_homepage_v2 as it was before the research step (queue #38): what the pilot and bench twins keep.
    The research nodes and save_files go, the copywriter and art director are the pre-research prompts, and
    the copy follows the taste file directly. tests/test_design_research_step.py covers the research nodes."""
    raw, nodes = workflow("design_homepage_v2")
    raw = {**raw, "inputs": {k: v for k, v in raw["inputs"].items() if k != "research_json"},
           "outputs": {k: v for k, v in raw["outputs"].items() if k not in RESEARCH_OUTPUTS}}
    kept = {}
    for name, node in nodes.items():
        if name.startswith("research") or name == "save_files":
            continue
        node = dict(node)
        if node["agent"] in ("design_homepage_copywriter_v2", "design_homepage_art_director_v2"):
            node["agent"] += "_no_research"
        if name == "copy":
            assert node["depends_on"] == ["research_decision"]
            node["depends_on"] = ["taste"]
        kept[name] = node
    return raw, kept


@pytest.mark.parametrize("name", ["design_homepage_v2", "design_homepage_v2_fixture", "design_homepage_v2_pilot"])
def test_workflow_native_gates_and_bounded_loops(name):
    raw, nodes = workflow(name)
    research = name != "design_homepage_v2_pilot"
    gates = sorted(n for n, v in nodes.items() if v.get("gate"))
    assert gates == ["direction", "final"] + (["research_gate"] if research else [])
    looping = {n: v for n, v in nodes.items() if v.get("loop_to")}
    assert set(looping) == {"copy_next", "concepts_next", "next_round", "after_final"} \
        | ({"research_check_next", "research_assemble_next"} if research else set())
    for node in looping.values():
        assert node["max_loops"] <= 3 and node["on_max_loops"] == "fail"
        # loop control never sits on a model or gate node
        assert node["agent"] in ("design_homepage_stage_v2", "design_research_stage_v1")
    assert nodes["copy_next"]["loop_to"] == "copy_revise" and nodes["copy_next"]["max_loops"] == 2
    assert nodes["copy_next"]["loop_condition"] == {"source": "copy_next.structured.verdict", "operator": "equals",
                                                    "value": "retry"}
    assert nodes["next_round"]["loop_to"] == nodes["after_final"]["loop_to"] == "plan_round"
    assert nodes["after_final"]["loop_condition"] == {"source": "final.structured.verdict", "operator": "equals",
                                                      "value": "request_changes"}
    assert nodes["revise"]["condition"] == {"source": "plan_round.structured.action", "operator": "equals",
                                            "value": "revise"}
    assert not {"approval", "final_json", "mode"} & set(raw["inputs"])
    assert raw["inputs"]["taste_md"] == {"type": "string", "default": ""}  # optional: v2 launches keep working
    assert nodes["taste"]["input_map"]["data"] == "input.taste_md"
    order = [n["name"] for n in raw["nodes"]]
    assert order.index("taste") < order.index("copy") < order.index("copy_check") < order.index("concepts")
    assert "copy_next" in nodes["concepts"]["depends_on"]  # no concept is drawn before the words pass
    assert order.index("direction") < order.index("build") < order.index("convert") < order.index("verify") \
        < order.index("handoff") < order.index("final")
    assert nodes["runtime"]["depends_on"] == ["measure"] and nodes["content"]["depends_on"] == ["runtime"]
    assert {"runtime", "content"} <= set(nodes["combine"]["depends_on"])
    assert nodes["copy_check"]["input_map"]["phase"] == "final" and nodes["copy_check_draft"]["input_map"]["phase"] == "draft"


def test_real_workflow_reuses_unchanged_critics_and_new_model_agents():
    _, nodes = workflow("design_homepage_v2")
    assert nodes["critic_a"]["agent"] == nodes["critic_b"]["agent"] == "design_critic"
    assert nodes["merge"]["agent"] == "design_merge"
    assert nodes["craft"]["agent"] == "design_homepage_craft_critic_v2"
    assert nodes["concepts"]["agent"] == nodes["refine"]["agent"] == "design_homepage_art_director_v2"
    assert nodes["concepts"]["input_map"] == {"phase": "draft"} and nodes["refine"]["input_map"] == {"phase": "refine"}
    assert nodes["check"]["input_map"]["phase"] == "final" and nodes["concepts_next"]["loop_to"] == "refine"
    assert nodes["build"]["agent"] == "design_homepage_designer_v2"
    assert nodes["revise"]["agent"] == "design_homepage_reviser_v2"
    assert set(nodes["combine"]["depends_on"]) == {"merge", "craft", "runtime", "content"}
    assert nodes["copy"]["agent"] == nodes["copy_revise"]["agent"] == "design_homepage_copywriter_v2"
    assert nodes["copy"]["input_map"] == {"phase": "draft"} and nodes["copy_revise"]["input_map"] == {"phase": "revise"}
    assert nodes["copy_review"]["agent"] == nodes["content"]["agent"] == "design_homepage_content_critic_v2"
    assert nodes["copy_review"]["input_map"] == {"target": "deck"} and nodes["content"]["input_map"] == {"target": "page"}
    assert nodes["runtime"]["input_map"]["stage"] == "runtime"  # deterministic browser checks, no model
    script = [v for v in nodes.values() if v["agent"] == "design_homepage_stage_v2"]
    assert all(v["input_map"]["mode"] == "real" for v in script)


def test_fixture_workflow_is_model_free():
    _, nodes = workflow("design_homepage_v2_fixture")
    research = {n for n in nodes if n.startswith("research") or n == "save_files"}
    assert all(nodes[n]["agent"] == "design_research_stage_v1" for n in research)
    nodes = {n: v for n, v in nodes.items() if n not in research}
    assert all(v["agent"] == "design_homepage_stage_v2" for v in nodes.values())
    assert all(v["input_map"]["mode"] == "fixture" for v in nodes.values())
    stages = {v["input_map"]["stage"] for v in nodes.values()}
    assert stages <= set(v2.STAGES)
    assert {"concepts_fixture", "build_fixture", "revise_fixture", "review_fixture", "convert", "verify"} <= stages
    assert {"taste", "copy_fixture", "copy_check", "copy_next", "runtime", "content_fixture"} <= stages
    assert set(nodes["combine"]["depends_on"]) == {"review", "runtime", "content"}


def test_agents_use_claude_opus_and_script_wrapper_holds_no_secret():
    for name in ("art_director", "designer", "craft_critic", "reviser", "copywriter", "content_critic"):
        agent = yaml.safe_load((BIN.parent / "agents" / f"design_homepage_{name}_v2.yaml").read_text())["agent"]
        assert agent["type"] == "llm" and agent["provider"] == "claude" and agent["model"] == "opus"
        assert "tools" not in agent  # the Claude CLI's own Read shows PNGs; a tools: block breaks the provider
        assert "```json" in agent["system_prompt"]
    stage = yaml.safe_load((BIN.parent / "agents/design_homepage_stage_v2.yaml").read_text())["agent"]
    assert stage["type"] == "script"
    template = stage["script_template"]
    assert "gate is defined" in template and "design_homepage_v2.py" in template
    assert "PASSWORD" not in template and '("real", "fixture", "pilot", "bench")' in template
    assert 'if mode in ("fixture", "pilot", "bench"):\n    cmd.append("--" + mode)' in template
    craft = (BIN.parent / "agents/design_homepage_craft_critic_v2.yaml").read_text()
    assert "review/craft/" in craft  # never review/critic/: design_merge would reject taste findings
    content = (BIN.parent / "agents/design_homepage_content_critic_v2.yaml").read_text()
    assert "review/content/content.json" in content and "homepage/copy/review.json" in content
    assert "review/critic/" not in content
    for name in ("art_director", "designer"):  # both work from the deck's words and the taste file
        text = (BIN.parent / "agents" / f"design_homepage_{name}_v2.yaml").read_text()
        assert "COPY.md" in text
    art = (BIN.parent / "agents/design_homepage_art_director_v2.yaml").read_text()
    assert "TASTE.md" in art and "taste_use" in art and "headline" in art
    assert '"recommended": {"concept": "A", "reason": "..."}' in art and "advice only" in art


# --------------------------------------------------------------------------- converter


def built(widths=(390, 1440)):
    fonts = h2p.Fonts()
    for scene in scenes(widths).values():
        for f in scene["fonts"]:
            fonts.add(f["family"], int(float(f["weight"])), f["style"], "11111111-1111-4111-8111-" + str(len(fonts.faces)).zfill(12))
    media = {}
    for scene in scenes(widths).values():
        for n in h2p.walk_scene(scene["nodes"]):
            for fill in n.get("fills", []):
                if fill.get("type") == "image":
                    media[fill["src"]] = {"id": "22222222-2222-4222-8222-222222222222", "width": 1200, "height": 800,
                                          "mtype": "image/jpeg", "name": "atlas-landscape.jpg"}
    return h2p.build(scenes(widths), "file", "page", fonts, media, "Atlas")


def test_build_makes_named_boards_per_width_with_live_text_and_library():
    b = built()
    assert [(x["name"], x["width"]) for x in b["boards"]] == [("Atlas — 390", 390), ("Atlas — 1440", 1440)]
    assert b["sections"] and any(s.startswith("Section") for s in b["sections"])
    texts = [o for o in b["objects"] if o["type"] == "text"]
    assert texts and all(o.get("position-data") for o in texts)
    for o in texts:
        if o["id"] in b["plain"]:
            assert " ".join(h2p.content_text(o["content"]).split()) == b["plain"][o["id"]]
    leaves = [leaf for o in texts for ps in o["content"]["children"] for para in ps["children"] for leaf in para["children"]]
    assert all(leaf["font-id"].startswith("custom-") for leaf in leaves)  # every face was uploaded: no fallback
    assert all(leaf.get("typography-ref-id") for leaf in leaves)
    assert {c["name"] for c in b["colors"]} >= {"paper", "ink"}
    assert sum(b["color_uses"].values()) > 10
    assert any("fill-color-gradient" in f for o in b["objects"] for f in o.get("fills", []))
    assert any("fill-image" in f for o in b["objects"] for f in o.get("fills", []))
    paths = [o for o in b["objects"] if o["type"] == "path"]
    assert paths and all(o["content"].startswith("M") and "x" not in o for o in paths)


def test_components_have_one_main_and_linked_instances_at_every_width():
    b = built()
    names = {c["name"] for c in b["components"]}
    assert {"Button", "RouteCard"} <= names
    by_id = {o["id"]: o for o in b["objects"]}
    roots = [o for o in b["objects"] if o.get("component-root") and not o.get("main-instance")]
    assert len(roots) == len(b["instances"]) >= 6
    for o in b["objects"]:
        if o.get("shape-ref"):
            assert o["shape-ref"] in by_id  # every instance layer points at a main layer in this file
    changes = [c for chunk in b["chunks"] for c in chunk["changes"]]
    added = [c for c in changes if c["type"] == "add-component"]
    assert len(added) == len(b["components"])
    first_obj = {c["id"]: i for i, c in enumerate(changes) if c["type"] == "add-obj"}
    for i, c in enumerate(changes):
        if c["type"] == "add-component":
            assert first_obj[c["main-instance-id"]] < i  # the main exists before it is declared a component


def test_recorded_page_becomes_penpot_layouts_that_pass_text_growth_up_to_the_page():
    """Task #9: every board reflows (flex, grid or a measured column/row) and a longer text grows
    its boards up to the page, because every board on the way hugs its content."""
    b = built()
    layout = b["layout"]
    assert not layout["fallbacks"] and layout["texts"]["fixed"] == 0 and layout["texts"]["auto-width"] > 0
    for w in (390, 1440):
        kinds = layout["widths"][w]["boards"]
        assert layout["widths"][w]["positioned"] == 0 and kinds["grid"] == 2 and kinds["flex row"] >= 6
    by_id = {o["id"]: o for o in b["objects"]}
    pages = {x["id"] for x in b["boards"]}
    for page in pages:  # a designer sets the page's width; its height follows the content
        o = by_id[page]
        assert (o["layout"], o["layout-flex-dir"], o["layout-item-h-sizing"], o["layout-item-v-sizing"]) == (
            "flex", "column", "fix", "auto")
    grown = 0
    for o in b["objects"]:
        if o["type"] != "text" or o["grow-type"] != "auto-height":
            continue
        chain, cur = [], by_id.get(o["parent-id"])
        while cur is not None and cur["id"] not in pages:
            chain.append(cur)
            cur = by_id.get(cur["parent-id"])
        if cur is None:
            continue  # inside a component main, beside the pages
        assert all(c.get("layout") and c["layout-item-v-sizing"] == "auto" for c in chain), o["name"]
        grown += 1
    assert grown >= 30
    for g in (o for o in b["objects"] if o.get("layout") == "grid"):
        placed = [s for c in g["layout-grid-cells"].values() for s in c["shapes"]]
        assert placed and len(set(placed)) == len(placed) and all(by_id[s]["parent-id"] == g["id"] for s in placed)


def test_inset_ring_becomes_inner_stroke_and_other_inset_shadows_hidden():
    lib = h2p.Library("file")
    builder = h2p.Builder("file", "page", lib, h2p.Fonts(), {})
    obj = {}
    builder.decorate(obj, {"name": "Card", "strokes": [], "radius": [8, 8, 8, 8], "opacity": 1, "shadows": [
        {"style": "drop-shadow", "x": 0, "y": 8, "blur": 24, "spread": 0, "color": "#000000", "opacity": .2},
        {"style": "inner-shadow", "x": 0, "y": 0, "blur": 0, "spread": 2, "color": "#E2AA5A", "opacity": 1},
        {"style": "inner-shadow", "x": 0, "y": 2, "blur": 6, "spread": 0, "color": "#000000", "opacity": .3}]})
    assert obj["strokes"][0]["stroke-width"] == 2 and obj["strokes"][0]["stroke-alignment"] == "inner"
    assert [s["hidden"] for s in obj["shadow"]] == [True, False]  # Penpot order: last CSS shadow first
    assert [i["kind"] for i in builder.issues] == ["inset-shadow-hidden"]
    assert obj["r1"] == obj["r4"] == 8


def test_fonts_fall_back_visibly_and_approximate_variants():
    fonts = h2p.Fonts()
    fonts.add("Figtree", 400, "normal", "f1")
    assert fonts.resolve({"family": "Figtree", "weight": "400", "style": "normal"})["font-id"] == "custom-f1"
    near = fonts.resolve({"family": "Figtree", "weight": "500", "style": "normal"})
    assert near["font-variant-id"] == "normal-400"
    missing = fonts.resolve({"family": "Unknown Face", "weight": "700", "style": "italic"})
    assert missing["font-id"] == "sourcesanspro" and missing["font-variant-id"] == "bolditalic"
    assert [i["kind"] for i in fonts.issues] == ["font-variant-approximated", "font-fallback"]


def test_shift_path_translates_absolute_commands_only():
    assert h2p.shift_path("M1 2L3 4C5 6 7 8 9 10Z", 10, 100) == "M11 102L13 104C15 106 17 108 19 110Z"


def test_svg_export_embeds_only_same_host_assets():
    svg = (b'<svg><style>@font-face{src:url("/assets/by-id/abc")}</style>'
           b'<image href="https://pen.example/assets/by-id/img"/><image href="https://evil.example/x.png"/></svg>')
    fetched = []

    def fetch(url):
        fetched.append(url)
        return b"wOFFdata" if url.endswith("abc") else b"\x89PNG\r\n\x1a\n" + b"\0" * 20

    out, n = h2p.embed_assets(svg, "https://pen.example", fetch)
    assert n == 2 and fetched == ["https://pen.example/assets/by-id/abc", "https://pen.example/assets/by-id/img"]
    assert b"data:font/woff;base64," in out and b"data:image/png;base64," in out
    assert b"https://evil.example/x.png" in out


@pytest.mark.parametrize("change, ok", [({}, True), ({"overall_pct": 2.5}, False), ({"text_pct": 13.0}, False),
                                        ({"tile_max_pct": 25.0}, False), ({"penpot": [390, 900]}, False)])
def test_fidelity_bar(change, ok):
    base = {"browser": [390, 1000], "penpot": [390, 1000], "overall_pct": 0.3, "nontext_pct": 0.2, "text_pct": 0.7,
            "tile_max_pct": 6.0, "tile_mean_max": 20.0}
    assert h2p.judge({**base, **change})["passed"] is ok


class FakePenpot:
    """In-memory Penpot: records uploads and applies add-* changes for the reopen check."""

    base = "https://penpot.test"

    def __init__(self, drop=None, existing=()):
        self.profile = {"id": "p", "default-team-id": "t"}
        self.objects, self.colors, self.typos, self.comps = {}, {}, {}, {}
        self.fonts, self.media, self.revn = [], [], 0
        self.drop, self.existing = drop, list(existing)

    def team(self):
        return "t"

    def create(self, name):
        return {"id": "file-1", "name": name, "data": {"pages": ["page-1"]}}

    def font_variants(self):
        return self.existing

    def upload_font(self, face, font_id):
        assert face["data"][:4] in (b"\x00\x01\x00\x00", b"true", b"OTTO") and face["licence"]["file"]
        self.fonts.append((face["family"], face["weight"], face["style"], font_id))
        return {"id": f"v{len(self.fonts)}", "woff1-file-id": "w"}

    def upload_media(self, file_id, image):
        self.media.append(image["name"])
        return {"id": f"m{len(self.media)}", "width": 1200, "height": 800, "mtype": image["mtype"], "name": image["name"]}

    def update(self, file_id, changes):
        self.revn += 1
        for c in changes:
            if c["type"] == "add-obj" and c["obj"]["name"] != self.drop:
                self.objects[c["id"]] = c["obj"]
            elif c["type"] == "add-color":
                self.colors[c["color"]["id"]] = c["color"]
            elif c["type"] == "add-typography":
                self.typos[c["typography"]["id"]] = c["typography"]
            elif c["type"] == "add-component":
                self.comps[c["id"]] = c

    def get(self, file_id):
        return {"revn": self.revn, "data": {"pages-index": {"page-1": {"objects": self.objects}},
                                            "colors": self.colors, "typographies": self.typos, "components": self.comps}}

    def export_board(self, state, board, kind, destination):
        destination.write_bytes(b"export")
        return {"path": str(destination), "bytes": 6}


def fake_convert(tmp_path, monkeypatch, client, scene_fn=None):
    recorded = scenes()
    if scene_fn:
        recorded = {w: scene_fn(s) for w, s in recorded.items()}
    for w, s in recorded.items():
        (tmp_path / f"scene-{w}.json").write_text(json.dumps(s))
    monkeypatch.setattr(h2p, "capture", lambda *a, **k: {"base": BASE, "summary": {}, "scenes": recorded})
    bar = {"overall_pct": 0.3, "nontext_pct": 0.2, "text_pct": 0.7, "tile_max_pct": 6.0, "tile_mean_max": 20.0}
    monkeypatch.setattr(h2p, "compare", lambda out, sc, *a: {w: h2p.judge({"browser": [w, 1], "penpot": [w, 1], **bar}) for w in sc})
    return h2p.convert(SITE, "atlas.html", tmp_path, "Atlas fixture", widths=(390, 1440), client=client, label="Atlas")


def test_convert_with_mock_penpot_uploads_licensed_fonts_and_passes_reopen(tmp_path, monkeypatch):
    client = FakePenpot()
    report = fake_convert(tmp_path, monkeypatch, client)
    assert report["passed"] and report["verify"]["passed"], report["verify"]["checks"]
    assert len(client.fonts) == 4 and len({f[3] for f in client.fonts}) == 2  # one font id per family
    assert all(f["licence"]["file"].endswith("OFL.txt") for f in report["fonts"])
    assert sorted(client.media) == ["atlas-landscape.jpg", "badge.png"]  # each image uploaded once, not per width
    assert not (tmp_path / "pending.json").exists() and (tmp_path / "conversion.json").exists()
    assert set(report["fidelity"]) == {"390", "1440"}
    assert all("data" not in f for f in report["fonts"])  # font bytes never land in the report


def test_convert_reuses_team_fonts_already_uploaded(tmp_path, monkeypatch):
    existing = [{"font-id": "known", "font-family": "Fraunces", "font-weight": 600, "font-style": "normal"}]
    client = FakePenpot(existing=existing)
    report = fake_convert(tmp_path, monkeypatch, client)
    reused = [f for f in report["fonts"] if f["reused"]]
    assert [(f["family"], f["weight"]) for f in reused] == [("Fraunces", 600)]
    assert ("Fraunces", 800, "normal", "known") in client.fonts  # new weight joins the existing family


class LayoutLosingPenpot(FakePenpot):
    """Saves everything but the grid cells, like a server that dropped an attribute."""

    def update(self, file_id, changes):
        super().update(file_id, changes)
        for k, o in list(self.objects.items()):
            if "layout-grid-cells" in o:
                self.objects[k] = {a: v for a, v in o.items() if a != "layout-grid-cells"}


def test_reopen_checks_layouts_text_growth_and_variants(tmp_path, monkeypatch):
    report = fake_convert(tmp_path, monkeypatch, FakePenpot())
    checks = report["verify"]["checks"]
    assert checks["layouts_kept"] and checks["text_growth_kept"] and checks["variants_kept"]
    assert report["verify"]["counts"]["frames_with_layout"] == report["layout"]["frames_with_layout"] > 50
    assert report["layout"]["fallbacks"] == [] and set(report["layout"]["widths"]) == {390, 1440}
    (tmp_path / "lost").mkdir()
    lost = fake_convert(tmp_path / "lost", monkeypatch, LayoutLosingPenpot())
    assert not lost["passed"] and not lost["verify"]["checks"]["layouts_kept"]
    assert all(": layout-grid-cells " in p and p.endswith("-> None") for p in lost["verify"]["problems"]["layout"])


def without_components(scene):
    """The recorded page as if it marked no data-component (a states sheet, a report list)."""
    scene = json.loads(json.dumps(scene))
    for n in h2p.walk_scene(scene["nodes"]):
        n.pop("component", None)
    return scene


class ComponentLosingPenpot(FakePenpot):
    def update(self, file_id, changes):
        super().update(file_id, changes)
        self.comps.clear()


class LinkLosingPenpot(FakePenpot):
    def update(self, file_id, changes):
        super().update(file_id, changes)
        for k, o in list(self.objects.items()):
            self.objects[k] = {a: v for a, v in o.items() if a != "shape-ref"}


def test_page_without_components_passes_component_checks_as_not_applicable_with_a_warning(tmp_path, monkeypatch):
    report = fake_convert(tmp_path, monkeypatch, FakePenpot(), without_components)
    v = report["verify"]
    assert report["components"] == [] and report["instances"] == []
    assert report["passed"] and v["checks"]["components"] and v["checks"]["instances_linked"]
    assert v["not_applicable"] == {"components": "no components marked", "instances_linked": "no components marked"}
    assert v["warnings"] == ["components not applicable (no components marked)",
                             "instances_linked not applicable (no components marked)"]
    saved = json.loads((tmp_path / "conversion.json").read_text())["verify"]
    assert saved["warnings"] == v["warnings"]  # a reviewer reads it in the saved report, never a silent pass


@pytest.mark.parametrize("client, failed", [(ComponentLosingPenpot, "components"), (LinkLosingPenpot, "instances_linked")])
def test_page_with_components_still_fails_a_missing_component_or_link(tmp_path, monkeypatch, client, failed):
    report = fake_convert(tmp_path, monkeypatch, client())
    v = report["verify"]
    assert not report["passed"] and not v["checks"][failed]
    assert v["not_applicable"] == {} and v["warnings"] == []


def test_marked_components_that_were_never_built_fail():
    b = built()
    file = {"data": {"pages-index": {"page": {"objects": {o["id"]: o for o in b["objects"]}}},
                     "components": {c["id"]: {"id": c["id"]} for c in b["components"]}}}
    assert b["marked_components"] and h2p.verify(file, "page", b)["checks"]["components"]
    lost = {**b, "components": [], "instances": []}  # the page marked components, none became one
    checked = h2p.verify(file, "page", lost)
    assert not checked["checks"]["components"] and not checked["checks"]["instances_linked"]
    assert checked["warnings"] == []


def test_lost_layer_fails_reopen_visibly(tmp_path, monkeypatch):
    client = FakePenpot(drop="Atlas — 390")
    report = fake_convert(tmp_path, monkeypatch, client)
    assert not report["passed"]
    assert not report["verify"]["checks"]["all_layers_present"] and not report["verify"]["checks"]["boards"]


# --------------------------------------------------------------------------- stages


def concept(cid, display, dominant, signature, words=300, text="Figtree"):
    return {"id": cid, "name": f"Direction {cid}", "brief": " ".join(["word"] * words),
            "fonts": {"display": {"family": display, "weights": [700]}, "text": {"family": text, "weights": [400, 600]}},
            "palette": {"dominant": dominant, "accent": "#FF5C48", "ink": "#18163A", "surface": "#FFFFFF",
                        "on_dominant": "#FFFFFF", "on_accent": "#18163A"},
            "imagery": "code-made diagrams", "signature_move": "giant numerals", "motion": "staggered reveal",
            "layout_signature": signature, "page": f"homepage/concepts/{cid}/index.html"}


def test_concept_contract_rejects_overused_fonts_low_contrast_and_thin_briefs():
    good = concept("A", "Fraunces", "#5B4BDB", ["a", "b", "c"])
    assert v2.concept_contract(good, set()) == []
    bad = concept("B", "Inter", "#5B4BDB", ["a", "b"], words=40)
    bad["palette"]["on_dominant"] = "#6A5AE0"
    problems = " ".join(v2.concept_contract(bad, set()))
    for needle in ("overused", "contrast", "words", "layout_signature"):
        assert needle in problems
    assert not any("overused" in p for p in v2.concept_contract(concept("C", "Inter", "#5B4BDB", ["a", "b", "c"]), {"inter"}))


def test_distinctness_measures():
    assert v2.delta_e("#5B4BDB", "#5B4BDB") == 0
    assert v2.delta_e("#5B4BDB", "#B8482A") > v2.DISTINCT["min_dominant_delta_e"]
    assert v2.jaccard(["Grid", "serif"], ["grid", "photo"]) == round(1 / 3, 3)


@pytest.mark.parametrize("html, needle", [('<img src="https://cdn.example/x.png">', "outside URL"),
                                          ("<style>@import url(x.css)</style>", "outside URL"),
                                          ("<script>alert(1)</script>", "<script>"),
                                          ("<iframe src=a.html></iframe>", "iframe")])
def test_page_contract_keeps_pages_local_and_static(tmp_path, html, needle):
    page = tmp_path / "index.html"
    page.write_text(f"<!doctype html><title>x</title>{html}")
    assert any(needle in p for p in v2.html_problems(page))


def test_outside_sites_run_one_session_each_and_a_failure_stays_local(tmp_path, monkeypatch):
    calls = []

    def fake_run(url, codes, timeout=None):
        args = json.loads(codes[0].split("const A = ", 1)[1].split(";\n", 1)[0])
        calls.append(([j["name"] for j in args["jobs"]], timeout))
        if any("bad" in j.get("url", "") for j in args["jobs"]):
            raise TimeoutError("stuck")
        return [[{"name": j["name"], "ok": True} for j in args["jobs"]]]

    monkeypatch.setattr(v2.h2p, "browser_run", fake_run)
    monkeypatch.setattr(v2.h2p, "serve", lambda *a: ("http://x:1", type("S", (), {"shutdown": lambda self: None})()))
    jobs = [{"name": f"{n}-{w}", "external": True, "url": f"https://{n}.example/", "width": w, "height": 900}
            for n in ("good", "bad") for w in (1440, 390)]
    out = {r["name"]: r for r in v2.browser_jobs(tmp_path, tmp_path / "o", jobs)}
    assert calls == [(["good-1440", "good-390"], 2 * v2.EXTERNAL_TIMEOUT), (["bad-1440", "bad-390"], 2 * v2.EXTERNAL_TIMEOUT)]
    assert out["good-390"]["ok"] and not out["bad-1440"]["ok"] and "TimeoutError" in out["bad-1440"]["error"]
    assert "BLOCKED.test" in v2.RENDER_CODE  # bot walls and error pages are failed, not counted


def fixture_job(tmp_path):
    job = v2.Job(str(tmp_path), fixture=True)
    job.brief("")
    return job


def test_parallel_stages_keep_each_others_receipts(tmp_path):
    """taste runs beside references (and runtime beside the fixture review): both save job.json."""
    fixture_job(tmp_path)
    first = v2.Job(str(tmp_path), fixture=True)  # both stages load the same state before either saves
    second = v2.Job(str(tmp_path), fixture=True)
    first.receipt("references", "fp-references", {"status": "completed"})
    second.receipt("taste", "fp-taste", {"status": "completed"})
    saved = v2.load(tmp_path / "homepage/job.json")["stages"]
    assert {"brief", "references", "taste"} <= set(saved)
    assert v2.Job(str(tmp_path), fixture=True).cached("references", "fp-references")["reused"]
    assert not list((tmp_path / "homepage").glob(".job.json.*.tmp"))  # written in one step, nothing left over


def converter_copy(tmp_path, monkeypatch):
    """The converter's source files copied aside, so a test can change one without touching the real ones."""
    src = tmp_path / "converter"
    src.mkdir()
    for name in v2.CONVERTER_FILES:
        shutil.copyfile(BIN / name, src / name)
    monkeypatch.setattr(v2, "CONVERTER_DIR", src)
    return src


def converted_round(tmp_path, monkeypatch):
    """A fixture workspace at round 1 with a stand-in converter that counts its Penpot conversions."""
    job = fixture_job(tmp_path)
    job.site.mkdir(parents=True, exist_ok=True)
    (job.site / "index.html").write_text("<!doctype html><title>Atlas</title><h1>Atlas</h1>")
    job.state["round"] = 1
    job.commit()
    calls = []

    def fake_convert(site, page, out, name, **kw):
        calls.append(name)
        out.mkdir(parents=True, exist_ok=True)
        report = {"passed": True, "file": {"file_id": f"file-{len(calls)}", "url": "https://pen.example/x"},
                  "fidelity_passed": True, "verify": {"passed": True}, "issue_counts": {}}
        v2.save(out / "conversion.json", report)
        return report

    monkeypatch.setattr(v2.h2p, "convert", fake_convert)
    return job, calls


def test_convert_reuses_its_receipt_while_the_converter_is_unchanged(tmp_path, monkeypatch):
    src = converter_copy(tmp_path, monkeypatch)
    job, calls = converted_round(tmp_path / "ws", monkeypatch)
    first = job.convert()
    assert first["converter"] == v2.converter_digest(src) and len(calls) == 1
    again = v2.Job(str(tmp_path / "ws"), fixture=True).convert()  # a resume or fork re-enters the stage
    assert again["reused"] is True and again["file_id"] == "file-1" and len(calls) == 1


@pytest.mark.parametrize("changed", ["html_to_penpot.py", "html_dom_extract.js", "penpot_layout.py",
                                     "penpot_homepage_source.py"])
def test_convert_refuses_a_saved_conversion_made_by_another_converter(tmp_path, monkeypatch, changed):
    src = converter_copy(tmp_path, monkeypatch)
    job, calls = converted_round(tmp_path / "ws", monkeypatch)
    job.convert()
    (src / changed).write_text((src / changed).read_text() + "\n// changed\n")
    with pytest.raises(ValueError, match=r"converter changed since this conversion of round 1 .*use a fresh workspace"):
        v2.Job(str(tmp_path / "ws"), fixture=True).convert()
    assert len(calls) == 1  # never silently reused, never silently repeated


def test_convert_refuses_a_receipt_saved_before_converter_digests(tmp_path, monkeypatch):
    converter_copy(tmp_path, monkeypatch)
    job, calls = converted_round(tmp_path / "ws", monkeypatch)
    job.convert()
    state = v2.load(tmp_path / "ws/homepage/job.json")
    del state["stages"]["convert-1"]["output"]["converter"]  # how receipts looked before queue #43
    v2.save(tmp_path / "ws/homepage/job.json", state)
    with pytest.raises(ValueError, match=r"converter changed .*saved not recorded.*use a fresh workspace"):
        v2.Job(str(tmp_path / "ws"), fixture=True).convert()
    assert len(calls) == 1


def test_fixture_and_real_workspaces_never_mix(tmp_path):
    job = fixture_job(tmp_path)
    assert (tmp_path / "homepage/BRIEF.md").exists() and (tmp_path / "homepage/PAGE_RULES.md").exists()
    with pytest.raises(ValueError, match="other workflow"):
        v2.Job(str(tmp_path), fixture=False)
    with pytest.raises(ValueError, match="refuses real briefs"):
        v2.Job(str(tmp_path / "x"), fixture=True).brief(json.dumps({**v2.FIXTURE_BRIEF, "fixture": False}))
    with pytest.raises(ValueError, match="refuses fixture briefs"):
        v2.Job(str(tmp_path / "y"), fixture=False).brief(json.dumps(v2.FIXTURE_BRIEF))
    assert job.brief("")["reused"] is True


def test_pilot_workflow_is_v2_with_only_the_mode_changed():
    real_raw, real = pre_research()
    pilot_raw, pilot = workflow("design_homepage_v2_pilot")
    assert list(pilot) == list(real)
    assert pilot_raw["inputs"] == real_raw["inputs"] and pilot_raw["outputs"] == real_raw["outputs"]
    for name, node in real.items():
        twin = pilot[name]
        assert {k: v for k, v in twin.items() if k != "input_map"} == {k: v for k, v in node.items() if k != "input_map"}
        mine, theirs = dict(node.get("input_map") or {}), dict(twin.get("input_map") or {})
        if node["agent"] == "design_homepage_stage_v2":
            assert mine.pop("mode") == "real" and theirs.pop("mode") == "pilot"
        assert theirs == mine


def test_bench_workflow_is_v2_with_mode_bench_and_no_gates():
    real_raw, real = pre_research()
    bench_raw, bench = workflow("design_homepage_v2_bench")
    assert list(bench) == list(real)
    assert bench_raw["inputs"] == real_raw["inputs"] and bench_raw["outputs"] == real_raw["outputs"]
    assert not [n for n, v in bench.items() if v.get("gate")]  # nobody is asked: the owner judges blind later
    for name, node in real.items():
        twin = bench[name]
        assert {k: v for k, v in twin.items() if k not in ("input_map", "gate")} == \
            {k: v for k, v in node.items() if k not in ("input_map", "gate")}
        mine, theirs = dict(node.get("input_map") or {}), dict(twin.get("input_map") or {})
        if node["agent"] == "design_homepage_stage_v2":
            assert mine.pop("mode") == "real" and theirs.pop("mode") == "bench"
        if name == "direction":
            assert mine.pop("data") == "input.direction_json"  # the art director's pick, never gate data
        assert theirs == mine
    looping = {n for n, v in bench.items() if v.get("loop_to")}
    assert looping == {"copy_next", "concepts_next", "next_round", "after_final"}


def bench_job(tmp_path):
    job = v2.Job(str(tmp_path), fixture=False, bench=True)
    job.brief(json.dumps({**v2.FIXTURE_BRIEF, "fixture": False}))  # fictional, but not the fixture
    return job


def recommend(job, rec):
    spec = v2.load(job.concepts_dir / "concepts.json")
    v2.save(job.concepts_dir / "concepts.json", {**spec, "recommended": rec})


def test_bench_builds_the_recommended_concept_never_an_approval_or_taste(tmp_path):
    with pytest.raises(ValueError, match="benchmark workflow refuses real deliverables"):
        v2.Job(str(tmp_path / "real"), fixture=False, bench=True).brief(
            json.dumps({**v2.FIXTURE_BRIEF, "fixture": False, "fictional": False}))
    with pytest.raises(ValueError, match="not more than one"):
        v2.Job(str(tmp_path / "both"), fixture=False, pilot=True, bench=True)
    job = bench_job(tmp_path / "b")
    with pytest.raises(ValueError, match="another workflow"):
        v2.Job(str(tmp_path / "b"), fixture=False, pilot=True)
    ready_for_direction(job)
    with pytest.raises(ValueError, match="no valid recommended"):
        job.direction("")
    recommend(job, {"concept": "D", "reason": "The strongest hierarchy of the three at both widths, by far."})
    assert v2.recommendation(v2.load(job.concepts_dir / "concepts.json")) is None
    recommend(job, {"concept": "C", "reason": "too short"})
    with pytest.raises(ValueError, match="no valid recommended"):
        job.direction("")
    why = "The strongest hierarchy of the three at both widths, and the most specific imagery."
    recommend(job, {"concept": "C", "reason": why})
    with pytest.raises(ValueError, match="no direction gate"):  # no gate answer is taken here
        job.direction(json.dumps({"concept": "A", "decided_by": "owner", "reasons": "x"}))
    out = job.direction("")
    assert out["concept"] == "C" and out["benchmark"] is True and out["decided_by"] == "design"
    assert out["direction_approved"] == {"approved": False, "decided_by": "design"}
    saved = v2.load(job.packet / "direction.json")
    assert saved["decided_by"] == "design" and saved["benchmark"] and saved["direction_approved"]["approved"] is False
    assert why in saved["reasons"] and "benchmark run" in saved["notes"]
    assert not [k for k in saved if k.startswith("owner")] and "approval" not in saved
    assert not (job.packet / "taste" / "entries.json").exists()  # the art director's pick is not a gate answer
    real = v2.Job(str(tmp_path / "r"), fixture=False)
    real.brief(json.dumps({**v2.FIXTURE_BRIEF, "fixture": False}))
    ready_for_direction(real)
    recommend(real, {"concept": "C", "reason": why})
    with pytest.raises(ValueError, match="needs decided_by design or owner"):  # the real gate needs an answer
        real.direction("{}")


def test_bench_final_is_skipped_and_labelled_not_approved(tmp_path):
    job = bench_job(tmp_path)
    job.state["round"] = 1
    with pytest.raises(ValueError, match="no verified handoff"):
        job.final("")
    job.state["stages"]["handoff-1"] = {"fingerprint": "x", "completed_at": "t", "output": {}}
    with pytest.raises(ValueError, match="no final gate"):
        job.final('{"decided_by": "design", "verdict": "approve", "reasons": "x"}')
    out = job.final("")
    assert out["verdict"] == "benchmark_skipped" and out["final_approved"] == {"approved": False, "decided_by": None}
    assert "not approved" in out["label"]
    saved = v2.load(job.packet / "final-benchmark.json")
    assert saved["final_approved"]["approved"] is False and saved["verdict"] == "benchmark_skipped"
    assert not (job.packet / "final.json").exists() and not (job.packet / "taste" / "entries.json").exists()
    state = v2.load(job.packet / "job.json")
    assert state["final_approved"]["approved"] is False and not [k for k in state if k.startswith("owner")]


def test_write_review_inputs_writes_what_the_critics_read(tmp_path, monkeypatch):
    """The measure stage and the craft benchmark share this, so a benchmark shows the critic what a round does."""
    calls = []

    def fake_capture(cmd, **kw):
        calls.append(cmd)
        return type("Done", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    metrics = {"1440": {"body_px": 18, "display_px": 76, "scale_ratio": 4.22, "text_sizes": 5, "weights": 3,
                        "families": ["Figtree"], "unloaded_families": [], "text_colors": 4, "background_colors": 5,
                        "gradients": 0, "background_images": 0, "images": 0, "svgs": 1, "animated_elements": 3,
                        "section_count": 7, "distinct_section_layouts": 7, "consecutive_repeats": 0, "spacing_values": 12,
                        "spacing_on_4px": 1.0, "hero_height": 720, "page_height": 3600, "overflow_x": False,
                        "sections": [{"name": "hero", "signature": "2 | cream | left | tall"}]}}
    monkeypatch.setattr(v2.subprocess, "run", fake_capture)
    monkeypatch.setattr(v2, "craft_metrics", lambda site: metrics)
    review = tmp_path / "review"
    review.mkdir()
    refs = tmp_path / "REFERENCES.md"
    refs.write_text("# References\n")
    brief = {"product": "Claybird Studio", "audience": "beginners", "purpose": "book a class", "cta": "Book",
             "fictional": True, "disclosure": "Fictional study."}
    chosen = {"id": "A", "name": "Studio noticeboard", "brief": "Warm and calm.", "signature_move": "pots",
              "motion": "rise", "imagery": "svg"}
    out = v2.write_review_inputs(review, tmp_path / "site", brief, 2, chosen, "warmer", refs)
    assert out == metrics and "design_capture.py" in calls[0][1] and "--site" in calls[0]
    assert "Claybird Studio (round 2)" in (review / "brief.md").read_text()
    assert "Fictional study: Fictional study." in (review / "brief.md").read_text()
    facts = (review / "craft-facts.md").read_text()
    assert "scale ratio 4.22x (aim >= 3x)" in facts and "share on a 4 px grid 1.0" in facts
    assert "Studio noticeboard" in (review / "concept.md").read_text() and "Direction notes: warmer" in (review / "concept.md").read_text()
    assert (review / "references.md").read_text() == "# References\n"
    assert all((review / sub).is_dir() for sub in ("critic", "craft", "content"))
    (tmp_path / "r2").mkdir()
    v2.write_review_inputs(tmp_path / "r2", tmp_path / "site", brief, 1, chosen, "", None)  # no references: none copied
    assert not (tmp_path / "r2" / "references.md").exists()


def pilot_job(tmp_path):
    job = v2.Job(str(tmp_path), fixture=False, pilot=True)
    job.brief(json.dumps({**v2.FIXTURE_BRIEF, "fixture": False}))  # fictional, but not the fixture
    return job


def test_pilot_takes_a_provisional_design_pick_never_an_approval_or_taste(tmp_path):
    real_brief = json.dumps({**v2.FIXTURE_BRIEF, "fixture": False, "fictional": False})
    with pytest.raises(ValueError, match="refuses real deliverables"):
        v2.Job(str(tmp_path / "real"), fixture=False, pilot=True).brief(real_brief)
    with pytest.raises(ValueError, match="fixture or the pilot"):
        v2.Job(str(tmp_path / "both"), fixture=True, pilot=True)
    job = pilot_job(tmp_path / "p")
    with pytest.raises(ValueError, match="another workflow"):
        v2.Job(str(tmp_path / "p"), fixture=False)
    ready_for_direction(job)
    why = "Clearest hierarchy and the most legible type at 390, so the build tests the deck best."
    with pytest.raises(ValueError, match="approval is retired"):  # the old answer shape is refused
        job.direction(json.dumps({"concept": "B", "approval": "provisional-fictional", "notes": why}))
    with pytest.raises(ValueError, match="needs decided_by design"):  # never the owner's, never a fixture's
        job.direction(json.dumps({"concept": "B", "decided_by": "owner", "reasons": why, "notes": why, "source": "m1"}))
    with pytest.raises(ValueError, match="needs reasons"):
        job.direction('{"concept": "B", "decided_by": "design", "reasons": "looks good"}')
    out = job.direction(json.dumps({"concept": "B", "decided_by": "design", "reasons": why}))
    assert out["direction_approved"] == {"approved": False, "decided_by": "design"} and out["provisional"] is True
    saved = v2.load(job.packet / "direction.json")
    assert saved["direction_approved"]["approved"] is False and saved["provisional"] is True
    assert saved["decided_by"] == "design" and saved["reasons"] == why
    assert not (job.packet / "taste" / "entries.json").exists()  # the worker's pick is not a gate answer
    real = v2.Job(str(tmp_path / "r"), fixture=False)
    real.brief(json.dumps({**v2.FIXTURE_BRIEF, "fixture": False}))
    ready_for_direction(real)
    with pytest.raises(ValueError, match="needs decided_by design or owner"):  # a fixture answer never fits a real run
        real.direction(json.dumps({"concept": "B", "decided_by": "fixture-test", "reasons": why}))


def test_completed_stage_with_changed_inputs_is_refused_not_repeated(tmp_path):
    job = fixture_job(tmp_path)
    with pytest.raises(ValueError, match="inputs changed"):
        job.brief(json.dumps({**v2.FIXTURE_BRIEF, "cta": "Something else"}))


def ready_for_direction(job, verdict="ok"):
    job.concepts_dir.mkdir(parents=True, exist_ok=True)
    v2.save(job.concepts_dir / "concepts.json", {"concepts": [
        concept("A", "Fraunces", "#B8482A", ["a", "b", "c"]), concept("B", "Bricolage Grotesque", "#5B4BDB", ["d", "e", "f"]),
        concept("C", "DM Serif Display", "#0E1626", ["g", "h", "i"])]})
    v2.save(job.concepts_dir / "check.json", {"phase": "final", "verdict": verdict, "problems": []})


FIX = '"decided_by": "fixture-test", "reasons": "fixture pass-through"'


@pytest.mark.parametrize("raw, error", [
    ("not json", "saved JSON"), ('{"concept": "D", ' + FIX + '}', "concept A, B or C"),
    ('{"concept": "A", "decided_by": "owner", "reasons": "x", "notes": "x", "source": "m1"}', "fixture-test"),
    ('{"concept": "A", "decided_by": "design", "reasons": "x"}', "fixture-test"),
    ('{"concept": "A", "approval": "fixture-test"}', "approval is retired"),
    ('{"concept": "A", "decided_by": "fixture-test"}', "needs reasons")])
def test_fixture_direction_gate_takes_only_fixture_test_answers(tmp_path, raw, error):
    job = fixture_job(tmp_path)
    ready_for_direction(job)
    with pytest.raises(ValueError, match=error):
        job.direction(raw)


def test_direction_needs_a_passed_check_and_prepares_the_site(tmp_path):
    job = fixture_job(tmp_path)
    ready_for_direction(job, verdict="retry")
    with pytest.raises(ValueError, match="not passed"):
        job.direction('{"concept": "B", ' + FIX + '}')
    ready_for_direction(job)
    out = job.direction('{"concept": "B", ' + FIX + ', "notes": "warmer"}')
    assert out["direction_approved"] == {"approved": True, "decided_by": "fixture-test"} and job.site.is_dir()
    assert out["decided_by"] == "fixture-test" and not [k for k in out if "owner" in k]
    saved = v2.load(job.packet / "direction.json")
    assert saved["decided_by"] == "fixture-test" and saved["reasons"] == "fixture pass-through"
    assert job.state["direction_approved"]["decided_by"] == "fixture-test"
    assert job.direction('{"concept": "B", ' + FIX + ', "notes": "warmer"}')["reused"]
    with pytest.raises(ValueError, match="inputs changed"):
        job.direction('{"concept": "C", ' + FIX + '}')


def test_real_direction_is_answered_by_design_or_by_the_owner_with_his_words(tmp_path):
    job = v2.Job(str(tmp_path), fixture=False)
    job.brief(json.dumps({**v2.FIXTURE_BRIEF, "fixture": False}))
    ready_for_direction(job)
    with pytest.raises(ValueError, match="needs decided_by design or owner"):
        job.direction('{"concept": "A", ' + FIX + '}')
    with pytest.raises(ValueError, match="his own words in notes and source"):  # never an owner answer without his words
        job.direction('{"concept": "A", "decided_by": "owner", "reasons": "he likes it"}')
    with pytest.raises(ValueError, match="only decided_by owner"):
        job.direction('{"concept": "A", "decided_by": "design", "reasons": "x", "source": "m1"}')
    out = job.direction('{"concept": "A", "decided_by": "design", "reasons": "Fits TASTE.md T3: warm serif, calm space."}')
    assert out["direction_approved"] == {"approved": True, "decided_by": "design"}
    entry = v2.load(job.packet / "taste" / "entries.json")["entries"][-1]
    assert entry["decided_by"] == "design" and entry["reasons"].startswith("Fits TASTE.md")
    other = v2.Job(str(tmp_path / "o"), fixture=False)
    other.brief(json.dumps({**v2.FIXTURE_BRIEF, "fixture": False}))
    ready_for_direction(other)
    words = {"concept": "B", "decided_by": "owner", "reasons": "the owner picked B", "notes": "B, but warmer",
             "source": "home chat m100"}
    assert other.direction(json.dumps(words))["direction_approved"] == {"approved": True, "decided_by": "owner"}
    assert v2.load(other.packet / "direction.json")["source"] == "home chat m100"


def test_concepts_next_reports_only_the_final_check(tmp_path):
    job = fixture_job(tmp_path)
    ready_for_direction(job, verdict="retry")
    assert job.concepts_next()["verdict"] == "retry"
    v2.save(job.concepts_dir / "check.json", {"phase": "draft", "verdict": "ok"})
    with pytest.raises(ValueError, match="not the final"):
        job.concepts_next()


PAGE_TEXT = "# Page text\n\n## hero\n- [h1] Book a room in two taps\n- [p] Rooms for four to twelve people.\n"


def review_round(job, usability_sev, craft_sev, status="confirmed", runtime=(), content=()):
    review = job.root / "review"
    (review / "craft").mkdir(parents=True, exist_ok=True)
    v2.save(review / "runtime" / "runtime.json", {"checks": {c: {"status": "pass"} for c in ("focus", "reflow")},
                                                 "findings": list(runtime), "errors": []})
    v2.save(review / "content" / "content.json", {"target": "page", "findings": list(content)})
    (review / "page-text.md").write_text(PAGE_TEXT)
    v2.save(review / "findings.json", {"findings": [{"id": "D1", "status": status, "severity": usability_sev,
                                                     "element": "hero", "problem": "p", "evidence": "e"}]})
    v2.save(review / "craft" / "craft.json", {"findings": [{"id": "C1", "severity": craft_sev, "check": "scale",
                                                            "element": "h1", "problem": "small"}],
                                              "template_test": {"verdict": "distinctive"}})


def test_review_loop_revises_at_most_twice_then_hands_off_unresolved(tmp_path):
    job = fixture_job(tmp_path)
    job.site.mkdir(parents=True)
    (job.site / "index.html").write_text("<title>x</title>")
    job.state["direction"] = {"concept": "A", "concept_name": "x"}
    assert job.plan_round()["action"] == "build"
    again = job.plan_round()  # no new decision yet: the plan is reused, never re-numbered
    assert again["reused"] and job.state["round"] == 1
    verdicts = []
    for _ in range(3):
        review_round(job, usability_sev=3, craft_sev=2)
        verdicts.append(job.combine()["verdict"])
        if verdicts[-1] == "revise":
            assert job.plan_round()["action"] == "revise"
    assert verdicts == ["revise", "revise", "done"]
    last = v2.load(job.packet / "rounds/r03/decision.json")
    assert len(last["unresolved_blocking"]) == 1 and job.state["revisions"] == 2
    with pytest.raises(ValueError, match="no revision"):
        job.state["decision_seq"] += 1
        job.plan_round()


def test_craft_severity_three_blocks_and_unconfirmed_usability_three_does_not(tmp_path):
    job = fixture_job(tmp_path)
    job.state["round"] = 1
    review_round(job, usability_sev=3, craft_sev=1, status="possible")
    assert job.combine()["verdict"] == "done"
    job.state["round"] = 2
    review_round(job, usability_sev=1, craft_sev=3)
    assert job.combine()["verdict"] == "revise"


def test_final_gate_request_changes_needs_notes_and_is_bounded(tmp_path):
    job = fixture_job(tmp_path)
    job.site.mkdir(parents=True)
    (job.site / "index.html").write_text("<title>x</title>")
    job.state["round"] = 1
    with pytest.raises(ValueError, match="no verified handoff"):
        job.final('{"verdict": "approve", ' + FIX + '}')
    job.state["stages"]["handoff-1"] = {"fingerprint": "x", "completed_at": "t", "output": {}}
    with pytest.raises(ValueError, match="notes"):
        job.final('{"verdict": "request_changes", "notes": [], ' + FIX + '}')
    with pytest.raises(ValueError, match="fixture-test"):
        job.final('{"verdict": "approve", "decided_by": "design", "reasons": "x"}')
    with pytest.raises(ValueError, match="approval is retired"):
        job.final('{"approval": "fixture-test"}')
    with pytest.raises(ValueError, match="verdict approve or request_changes"):
        job.final('{' + FIX + '}')
    out = job.final('{"verdict": "request_changes", "notes": ["bigger headline"], ' + FIX + '}')
    assert out["verdict"] == "request_changes" and job.state["fix_list"][0]["problem"] == "bigger headline"
    assert out["final_approved"] == {"approved": False, "decided_by": "fixture-test"} and "direction_approved" in out
    assert job.state["fix_list"][0]["source"] == "final_gate" and job.state["fix_list"][0]["decided_by"] == "fixture-test"
    assert job.plan_round()["action"] == "revise" and job.state["change_rounds"] == 1
    job.state["change_rounds"] = v2.MAX_CHANGE_ROUNDS
    job.state["stages"]["handoff-2"] = job.state["stages"]["handoff-1"]
    with pytest.raises(ValueError, match="two final-gate change rounds"):
        job.final('{"verdict": "request_changes", "notes": ["again"], ' + FIX + '}')
    done = job.final('{"verdict": "approve", ' + FIX + '}')
    assert done["verdict"] == "approved" and done["decided_by"] == "fixture-test"
    assert done["final_approved"] == {"approved": True, "decided_by": "fixture-test"} and "direction_approved" in done
    saved = v2.load(job.packet / "final.json")
    assert saved["final_approved"]["decided_by"] == "fixture-test" and saved["reasons"] == "fixture pass-through"
    assert not [k for k in v2.load(job.packet / "job.json") if k.startswith("owner")]


def test_job_saved_before_the_rename_still_loads(tmp_path):
    """A job.json from before 2026-10-05 (owner_changes, owner_*_approved, approval labels) reads unchanged."""
    job = fixture_job(tmp_path)
    state = v2.load(job.packet / "job.json")
    for k in ("change_rounds", "direction_approved", "final_approved"):
        state.pop(k)
    state.update({"owner_changes": 1, "owner_direction_approved": False, "owner_final_approved": False,
                  "direction": {"concept": "B", "approval": "fixture-test", "notes": "warmer", "concept_name": "x"}})
    v2.save(job.packet / "job.json", state)
    before = (job.packet / "job.json").read_bytes()
    again = v2.Job(str(tmp_path), fixture=True)
    assert again.state["change_rounds"] == 1 and again.state["owner_changes"] == 1
    assert again.state["direction_approved"] == {"approved": False, "decided_by": "fixture-test"}
    assert again.state["final_approved"] == {"approved": False, "decided_by": None}
    assert (job.packet / "job.json").read_bytes() == before  # loading never rewrites the past record
    assert v2.gate_decided_by({"approval": "owner-final"}) == "owner"
    assert v2.gate_decided_by({"approval": "provisional-fictional"}) == "design"
    assert v2.taste_words({"owner_words": "warmer"}) == "warmer"
    assert v2.GATE_FIX_SOURCES == ("final_gate", "owner")
    old = dict(again.state, verdict="owner_changes", decision_seq=again.state["decision_seq"] + 1)
    assert old["verdict"] in v2.CHANGE_VERDICTS


def test_fixture_only_stages_refuse_real_runs(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "argv", ["design_homepage_v2.py", "build_fixture", "--workspace", str(tmp_path)])
    with pytest.raises(SystemExit, match="fixture-only"):
        v2.main()


def test_fixture_concepts_pass_the_offline_contract(tmp_path):
    job = fixture_job(tmp_path)
    job.concepts_fixture()
    spec = v2.load(job.concepts_dir / "concepts.json")
    assert [c["id"] for c in spec["concepts"]] == ["A", "B", "C"]
    for c in spec["concepts"]:
        assert v2.concept_contract(c, set()) == []
        assert v2.html_problems(job.concepts_dir / c["id"] / "index.html") == []
        assert v2.concept_words_problems(c, v2.FIXTURE_DECK, []) == []
    assert job.concepts_fixture()["reused"]


# --------------------------------------------------------------------------- v2.1: words


def test_copy_contract_catches_what_the_morrow_run_got_wrong():
    assert v2.copy_contract(v2.FIXTURE_DECK, v2.FIXTURE_BRIEF) == []
    bad = json.loads(json.dumps(v2.FIXTURE_DECK))
    bad["ctas"] = {"primary": "Learn more"}
    bad["subhead"] = "In the proposed room demo, rooms cost $45 per hour."
    bad["proof_points"][0]["text"] = "Teams save 12 hours a week."
    bad["notices"].append({"id": "fictional", "text": "Again: not a real product.", "placement": "header"})
    problems = "\n".join(v2.copy_contract(bad, v2.FIXTURE_BRIEF))
    assert "does not say what happens" in problems
    assert "'proposed' belongs only in the single notice" in problems
    assert "add a worked example" in problems
    assert "the number 12 is not in the brief's facts" in problems
    assert "each notice is stated once" in problems
    real = {**v2.FIXTURE_BRIEF, "fictional": False}
    honest = {**v2.FIXTURE_DECK, "notices": [], "subhead": "The proposed schedule is shared before anyone books."}
    assert v2.copy_contract(honest, real) == []  # a real product may say "proposed" plainly


@pytest.mark.parametrize("text, bad", [("2 x 45 min = 90 min", False), ("2 x 45 min = 80 min", True),
                                       ("6 x $12 = $72", False), ("$45 + $10 = $55", False),
                                       ("4 \u00d7 $30 = $100", True), ("rooms for 4-6 = small", False),
                                       # any number of terms, read from the first (queue #38: the check
                                       # used to read '1 + 1 + 1 = 4' out of the line below)
                                       ("screen: 1 + 1 + 1 + 1 = 4 places", False), ("1 + 1 + 1 = 4", True),
                                       ("3 boxes + 2 boxes = 5 boxes", False), ("10 + 2 x 5 = 20", False),
                                       ("2 x 3 x 4 = 25", True), ("10 - 3 = 7", False), ("10 - 3 = 6", True)])
def test_worked_example_sums_are_checked(text, bad):
    assert bool(v2.arithmetic_problems(text)) is bad


def test_copy_deck_is_reviewed_revised_and_kept_before_and_after(tmp_path):
    job = fixture_job(tmp_path)
    job.taste("")
    job.copy_fixture("draft")
    first = job.copy_check("draft")
    assert first["verdict"] == "ok", v2.load(job.copy_dir / "check.json")["problems"]
    assert (job.copy_dir / "copy-draft.json").exists() and "Promise" in (job.copy_dir / "COPY.md").read_text()
    job.copy_fixture("review")
    early = job.copy_check("final")  # nothing revised yet: K1 (severity 3) is still in the deck, unanswered
    assert early["verdict"] == "retry" and job.copy_next()["verdict"] == "retry"
    job.copy_fixture("revise")
    done = job.copy_check("final")
    assert done["verdict"] == "ok" and done["attempt"] == 1
    assert done["verified_findings"] == 1 and done["dropped_findings"] == 1  # K2 quoted words the deck never had
    checked = v2.load(job.copy_dir / "review-checked.json")
    assert checked["answers"]["K1"]["quote_gone"] is True and checked["dropped"][0]["id"] == "K2"
    diff = (job.copy_dir / "COPY-DIFF.md").read_text()
    assert "DROPPED K2" in diff and "| subhead |" in diff and v2.FIXTURE_SUBHEAD_AFTER in diff
    assert v2.FIXTURE_DECK["subhead"] in (job.copy_dir / "COPY-draft.md").read_text()  # the before stays
    assert job.copy_next()["verdict"] == "ok" and job.copy_check("final")["reused"]


def test_page_shows_each_notice_once_and_no_hedges_elsewhere():
    deck, head = v2.FIXTURE_DECK, v2.FIXTURE_DECK["headlines"][0]["text"]
    notice = deck["notices"][0]["text"]
    good = f"<h1>{head}</h1><p>Body.</p><footer>{notice}</footer>"
    assert v2.page_copy_problems(good, deck, head, True, "page") == []
    twice = f"<header>{notice}</header><h1>Other</h1><p>A proposed concept study.</p><footer>{notice}</footer>"
    problems = " ".join(v2.page_copy_problems(twice, deck, head, True, "page"))
    assert "appears 2 times" in problems and "'proposed'" in problems and "is not on the page" in problems
    assert "missing" in " ".join(v2.page_copy_problems("<h1>x</h1>", deck, None, True, "page"))
    hidden = f"<style>p{{}}</style><title>{notice}</title><h1>{head}</h1><footer>{notice}</footer>"
    assert v2.page_copy_problems(hidden, deck, head, True, "page") == []  # only visible words count


def test_concepts_use_a_deck_headline_and_say_how_they_use_the_taste_file():
    deck = v2.FIXTURE_DECK
    c = {"id": "A", "headline": deck["headlines"][0]["text"],
         "taste_use": "Follows T1: a warm serif display and generous space, as the owner chose last time."}
    assert v2.concept_words_problems(c, deck, ["T1"]) == []
    empty = {**c, "taste_use": "No entries yet, so this concept sets its own direction from the brief."}
    assert v2.concept_words_problems(empty, deck, []) == []
    wrong = " ".join(v2.concept_words_problems({**c, "headline": "A brand new line",
                                                "taste_use": "Uses T7 heavily with a lot more words here"}, deck, ["T1"]))
    assert "headline must be one of" in wrong and "T7" in wrong
    uncited = {**c, "taste_use": "A warm serif display and generous space, like the last pick."}
    assert "must cite" in " ".join(v2.concept_words_problems(uncited, deck, ["T1"]))
    assert "taste_use must say" in " ".join(v2.concept_words_problems({**c, "taste_use": ""}, deck, []))


# --------------------------------------------------------------------------- v2.1: the owner's taste


def test_taste_file_is_passed_in_and_every_gate_answer_is_saved(tmp_path):
    job = fixture_job(tmp_path)
    text = ("# Fixture taste file\n\n## T1 \u2014 2026-10-04 \u00b7 direction gate \u00b7 X\nChose: A\n\n"
            "## T2 \u2014 2026-10-04 \u00b7 final gate \u00b7 X\nChose: approve\n")
    out = job.taste(text)
    assert out["entries"] == 2 and not out["truncated"] and job.taste_list() == ["T1", "T2"]
    assert "## T2" in (job.packet / "TASTE.md").read_text() and job.taste(text)["reused"]
    with pytest.raises(ValueError, match="inputs changed"):
        job.taste("")
    ready_for_direction(job)
    answer = '{"concept": "B", ' + FIX + ', "notes": "warmer, less grey"}'
    job.direction(answer)
    job.direction(answer)  # a resumed gate reuses its receipt: no second entry
    entries = v2.load(job.packet / "taste/entries.json")["entries"]
    assert len(entries) == 1
    e = entries[0]
    assert e["key"] == "direction" and e["gate"] == "direction" and e["choice"] == "B: Direction B"
    assert e["fixture"] is True and e["words"] == "warmer, less grey" and "owner_words" not in e
    assert e["decided_by"] == "fixture-test" and e["reasons"] == "fixture pass-through"
    assert [r["option"] for r in e["rejected"]] == ["A: Direction A", "C: Direction C"]
    assert "Bricolage Grotesque" in e["choice_summary"] and "Fraunces" in e["rejected"][0]["summary"]
    job.state["round"] = 1
    job.state["stages"]["handoff-1"] = {"fingerprint": "x", "completed_at": "t", "output": {}}
    job.final('{"verdict": "request_changes", "notes": ["bigger headline"], ' + FIX + '}')
    final = v2.load(job.packet / "taste/entries.json")["entries"][-1]
    assert final["key"] == "final-r01" and final["choice"] == "request changes"
    assert final["words"] == ["bigger headline"] and "direction B" in final["about"]
    assert final["decided_by"] == "fixture-test"
    assert final["rejected"] == [{"option": "approve as it is"}]


def test_long_taste_files_keep_the_newest_whole_entries(monkeypatch):
    monkeypatch.setattr(v2, "MAX_TASTE_CHARS", 200)
    entries = "".join(f"## T{i} \u2014 entry\n" + "x" * 60 + "\n\n" for i in range(1, 6))
    kept, cut = v2.trim_taste("# head\n\n" + entries)
    assert cut and len(kept) <= 200 and kept.startswith("# head") and "## T5" in kept and "## T1 " not in kept
    assert v2.trim_taste("short") == ("short", False)


# --------------------------------------------------------------------------- v2.1: runtime checks and content review


def runtime_ready(tmp_path, fixture=True):
    job = fixture_job(tmp_path) if fixture else v2.Job(str(tmp_path), fixture=False)
    job.site.mkdir(parents=True)
    (job.site / "index.html").write_text("<title>x</title><h1>Lantern Desk</h1>")
    job.state["round"] = 1
    return job


def test_runtime_stage_measures_once_and_feeds_the_content_review(tmp_path, monkeypatch):
    job = runtime_ready(tmp_path)
    with pytest.raises(ValueError, match="not been measured"):
        job.runtime()
    job.state["stages"]["measure-1"] = {"fingerprint": "x", "completed_at": "t", "output": {}}
    planted = json.loads((RUNTIME_SCENES / "planted.raw.json").read_text())
    calls = []
    monkeypatch.setattr(v2.rtc, "measure", lambda site, page, browser, host: calls.append(page) or planted)
    out = job.runtime()
    assert out["failures"] == 9 and out["checks"]["motion"] == "fail" and calls == ["index.html"]
    assert job.runtime()["reused"] and len(calls) == 1  # the same page is never measured twice
    review = job.root / "review"
    assert (review / "runtime/RUNTIME.md").exists() and (job.packet / "rounds/r01/runtime.json").exists()
    assert "- [h1] " in (review / "page-text.md").read_text()
    quoted = job.content_fixture()["quoted"]
    assert quoted and quoted in (review / "page-text.md").read_text()
    review_kept = {k: (review / k).read_text() for k in ("runtime/runtime.json", "content/content.json", "page-text.md")}
    v2.save(review / "findings.json", {"findings": []})
    v2.save(review / "craft" / "craft.json", {"findings": [], "template_test": {"verdict": "fixture"}})
    combined = job.combine()
    assert combined["verdict"] == "done" and combined["blocking"] == 0  # fixture pages: advisory only
    assert combined["by_source"]["runtime"] == 10 and combined["by_source"]["content"] == 1
    decision = v2.load(job.packet / "rounds/r01/decision.json")
    assert [d["id"] for d in decision["content_dropped"]] == ["K2"] and decision["runtime_checks"]["focus"] == "fail"
    assert all((review / k).read_text() == v for k, v in review_kept.items())


def test_runtime_stage_refuses_a_browser_that_measured_nothing(tmp_path, monkeypatch):
    job = runtime_ready(tmp_path)
    job.state["stages"]["measure-1"] = {"fingerprint": "x", "completed_at": "t", "output": {}}
    monkeypatch.setattr(v2.rtc, "measure", lambda *a: {"errors": ["browser unreachable"]})
    with pytest.raises(ValueError, match="could not run: browser unreachable"):
        job.runtime()
    assert "runtime-1" not in job.state["stages"]


def test_combine_needs_runtime_and_content_results(tmp_path):
    job = fixture_job(tmp_path)
    job.state["round"] = 1
    review_round(job, usability_sev=1, craft_sev=1)
    (job.root / "review/content/content.json").unlink()
    with pytest.raises(ValueError, match="content/content.json missing"):
        job.combine()


def test_real_runs_block_on_runtime_failures_and_verified_content_findings(tmp_path):
    job = v2.Job(str(tmp_path), fixture=False)
    no_ring = {"id": "R1", "check": "focus", "criterion": "2.4.7", "severity": 3, "element": 'a "Book" (hero)',
               "problem": "Keyboard focus is not visible", "evidence": "#1", "suggestion": "add a ring", "viewport": "desktop"}
    no_hover = {**no_ring, "id": "R2", "check": "hover", "criterion": "none (usability/craft)", "severity": 2}
    job.state["round"] = 1
    review_round(job, usability_sev=1, craft_sev=1, runtime=[no_ring, no_hover])
    first = job.combine()
    assert first["verdict"] == "revise" and first["blocking"] == 1 and first["by_source"]["runtime"] == 2
    vague = {"id": "K1", "check": "clarity", "element": "hero heading", "quote": "book a room in TWO taps",
             "problem": "which two taps?", "suggestion": "name them", "severity": 3}
    job.state["round"] = 2
    review_round(job, usability_sev=1, craft_sev=1, content=[vague])
    second = job.combine()
    assert second["verdict"] == "revise" and second["by_source"]["content"] == 1
    assert v2.load(job.packet / "rounds/r02/decision.json")["fixes"][0]["evidence"].startswith('quote: "book a room')
    invented = {**vague, "quote": "Words the page never shows"}
    job.state["round"] = 3
    review_round(job, usability_sev=1, craft_sev=1, content=[invented, {"id": "K9", "check": "tone"}])
    third = job.combine()
    assert third["verdict"] == "done" and third["blocking"] == 0 and third["content_dropped"] == 2


# ---------------------------------------------------------------- queue #32: the signature, repeats, kept text

CONCEPT = {"id": "A", "signature_move": "A split-flap room board as the hero: rooms listed on flap tiles with their seats.",
           "layout_signature": ["split-flap-board", "monospace-display"]}


def sig_raw(v390, v1440, height=500, first=True, found=True):
    def screen(top, visible):
        return {"found": found, "shown": True, "how": "data-signature", "matched": [], "name": "Room board", "section": "Hero",
                "in_first_section": first, "top": top, "height": height, "cover": 0, "visible_px": visible}
    return {"screens": {"390": screen(844 - v390, v390), "1440": screen(900 - v1440, v1440)}}


def test_signature_is_found_by_its_words_and_measured_against_the_first_screen():
    words = v2.signature_words(CONCEPT)
    assert words == ["split", "flap", "room", "board"]
    below = v2.judge_signature(sig_raw(0, 193), CONCEPT, words)
    assert below["status"] == "fail" and below["expected_first_screen"]
    assert below["screens"]["390x844"]["needs_px"] == 211 and below["screens"]["1440x900"]["needs_px"] == 225
    finding = v2.signature_finding(below)
    assert finding["source"] == "measure" and finding["severity"] == 3 and finding["section"] == "Hero"
    assert "0 of the 211 px" in finding["problem"] and "193 of the 225 px" in finding["problem"]
    assert "at least 211 px of it at 390x844" in finding["suggestion"]
    shown = v2.judge_signature(sig_raw(211, 225), CONCEPT, words, previous=below)
    assert shown["status"] == "pass" and v2.signature_finding(shown) is None
    assert shown["previous_round"]["390x844"] == {"visible_px": 0, "needs_px": 211}
    assert "previous round: 0 of 211 px" in v2.signature_md(shown, 2)
    short = v2.judge_signature(sig_raw(120, 120, height=120), CONCEPT, words)  # a short signature shown whole passes
    assert short["status"] == "pass"
    later = {"signature_move": "Rooms on flap tiles, read like a station board."}  # not meant for the first screen
    assert v2.judge_signature(sig_raw(0, 0, first=False), later, words)["status"] == "not meant for the first screen"
    missing = v2.judge_signature(sig_raw(0, 0, found=False), CONCEPT, words)
    assert missing["status"] == "not found" and v2.signature_finding(missing)["severity"] == 2


def test_page_rules_and_reviser_carry_the_signature_mark_and_the_kept_text_rule():
    assert "data-signature" in v2.PAGE_RULES and "data-signature" in v2.SIGNATURE_CODE
    reviser = yaml.safe_load((ROOT / "configs/design/agents/design_homepage_reviser_v2.yaml").read_text())
    prompt = json.dumps(reviser)
    for needle in ("REDESIGN", "REWRITE", "RAISED BEFORE", "aria-hidden", "data-signature", "review/signature.md", "REVISION.md"):
        assert needle in prompt, needle


def signature_review(job, number, visible, craft=()):
    job.state["round"] = number
    review_round(job, usability_sev=1, craft_sev=1)
    review = job.root / "review"
    v2.save(review / "craft" / "craft.json", {"findings": list(craft), "template_test": {"verdict": "distinctive"}})
    v2.save(review / "signature.json", v2.judge_signature(sig_raw(*visible), CONCEPT, v2.signature_words(CONCEPT)))
    return job.combine()


def test_a_blocker_raised_again_sends_its_section_back_for_a_redesign(tmp_path):
    job = v2.Job(str(tmp_path), fixture=False)
    job.state["direction"] = {"concept": "A"}
    v2.save(job.concepts_dir / "concepts.json", {"concepts": [CONCEPT]})
    first = signature_review(job, 1, (0, 120))
    assert first["verdict"] == "revise" and first["by_source"]["measure"] == 1
    m1 = next(f for f in v2.load(job.packet / "rounds/r01/decision.json")["fixes"] if f["id"] == "M1")
    assert m1["severity"] == 3 and "0 of the 211 px" in m1["problem"] and "repeat" not in m1
    # The reviser answers M1 with a tweak that does not bring the board up; a critic words it differently.
    job.site.mkdir(parents=True, exist_ok=True)
    (job.site / "REVISION.md").write_text("# Revision \u2014 round 2\n\n- M1 (measure, 3) \u2014 fixed: tightened the hero padding.\n")
    job.state["revisions"] = 1
    again = {"id": "C4", "severity": 3, "check": "direction", "element": "Room board",
             "problem": "The signature board still does not make it into the first mobile screen."}
    other = {"id": "C5", "severity": 3, "check": "rhythm", "element": "FAQ list", "problem": "Answers sit too close together.",
             "suggestion": "Add 24 px between answers."}
    assert signature_review(job, 2, (90, 300), craft=[again, other])["verdict"] == "revise"
    decision = v2.load(job.packet / "rounds/r02/decision.json")
    blockers = {b["id"]: b for b in decision["blockers"]}
    assert blockers["M1"]["seen_in"] == [1, 2] and blockers["M1"]["action"] == "redesign"
    assert blockers["C4"]["seen_in"] == [1, 2] and blockers["C4"]["action"] == "redesign"  # same problem, other words
    assert blockers["C5"]["seen_in"] == [2] and blockers["C5"]["action"] == "fix"
    fixes = {f["id"]: f for f in decision["fixes"]}
    assert fixes["M1"]["suggestion"].startswith("REDESIGN, not a tweak") and "the Hero section" in fixes["M1"]["suggestion"]
    assert fixes["M1"]["repeat"]["earlier"][0]["answer"].startswith("M1 (measure, 3)")
    assert fixes["C5"]["suggestion"] == "Add 24 px between answers."  # raised once: a normal fix
    # No revision left: a blocker still there is handed off with its history, never silently dropped.
    job.state["revisions"] = 2
    last = signature_review(job, 3, (90, 300))
    assert last["verdict"] == "done" and last["unresolved_blocking"] == 1
    unresolved = v2.load(job.packet / "rounds/r03/decision.json")["unresolved_blocking"][0]
    assert unresolved["id"] == "M1" and unresolved["repeat"]["seen_in"] == [1, 2, 3] and unresolved["action"] == "no revision left"
    lines = v2.round_by_round(job.packet / "rounds", 3)
    assert lines[1].startswith("- Round 2: verdict revise; blockers: measure M1 (also round 1; redesign)")
    assert "signature fail 390x844 90/211 px" in lines[2]


def test_a_content_finding_raised_again_joins_the_fix_list_past_the_cap(tmp_path):
    """Only the top six minor items reach the reviser, so a low-severity content finding could come back every round."""
    job = v2.Job(str(tmp_path), fixture=False)
    text = PAGE_TEXT + "".join(f"- [p] Line number {i} says something about room {i} here.\n" for i in range(1, 15))
    text += "- [p] Cedar for 1 hour: 1 hour x $18 = $18. Oak for 2 hours: 2 hours x $30 = $60.\n"

    def finding(i, sev, quote, element):
        return {"id": f"K{i}", "check": "clarity", "element": element, "quote": quote, "problem": "unclear",
                "suggestion": "say it plainly", "severity": sev}

    def content_round(number, others, bases_element):
        job.state["round"] = number
        bases = finding(9, 1, "Oak for 2 hours: 2 hours x $30 = $60.", bases_element)
        review_round(job, usability_sev=1, craft_sev=1, content=others + [bases])
        (job.root / "review" / "page-text.md").write_text(text)
        return job.combine()

    content_round(1, [finding(i, 2, f"Line number {i} says something", f"paragraph {i}") for i in range(1, 8)], "card examples")
    assert "K9" not in [f["id"] for f in v2.load(job.packet / "rounds/r01/decision.json")["fixes"]]  # past the cap
    content_round(2, [finding(i, 2, f"Line number {i + 7} says something", f"paragraph {i + 7}") for i in range(1, 8)],
                  "Oak card example")
    decision = v2.load(job.packet / "rounds/r02/decision.json")
    assert [(c["id"], c["seen_in"]) for c in decision["content_repeats"]] == [("K9", [1, 2])]
    k9 = next(f for f in decision["fixes"] if f["id"] == "K9" and f["source"] == "content")
    assert k9["suggestion"].startswith("RAISED BEFORE in round 1") and k9["action"] == "fix or explain"
    assert len(decision["fixes"]) == 7  # the repeat plus the usual six minor items


@pytest.mark.parametrize("a, b, same", [
    ({"quote": "Explore demo rooms", "element": "Hero button"},
     {"quote": "Pick a room, then explore demo rooms with the team before you book", "element": "Footer note"}, False),
    ({"quote": "Tell us who is coming", "element": "How it works: step 1"},
     {"quote": "Pick a time that suits", "element": "How it works: step 3"}, False),
    ({"quote": "Start by picking a room.", "element": "FAQ: How do I start? answer"},
     {"quote": "Choose a room first.", "element": "FAQ answer: How do I start?"}, True),
    ({"quote": "Oak for 2 hours: 2 hours x $30 = $60.", "element": "Oak card"},
     {"quote": "Oak for 2 hours: 2 hours x $30 = $60.", "element": "card examples"}, True),
])
def test_content_findings_are_the_same_problem_by_their_words_not_a_shared_label(a, b, same):
    a, b = {"source": "content", **a}, {"source": "content", **b}
    assert v2.same_problem(a, b) is same


# --------------------------------------------------------------------------- queue #34: fresh type pairings, concept axe


@pytest.fixture(autouse=True)
def pairing_log_file(tmp_path, monkeypatch):
    """Every test logs pairings to its own file, never to the shared log beside real run workspaces."""
    log = tmp_path / "pairing-log" / "type-pairings.jsonl"
    monkeypatch.setenv("DESIGN_PAIRING_LOG", str(log))
    return log


SEED = json.loads((ROOT / "configs/design/knowledge/type-pairings.json").read_text())
FRESH = [("Gloock", "Hanken Grotesk"), ("Young Serif", "Public Sans"), ("Rubik Mono One", "Karla")]


def test_pairing_record_holds_the_fixture_pairings_with_generic_sources(tmp_path):
    keys = {v2.pairing_key(p["display"], p["text"]) for p in SEED["pairings"]}
    assert len(keys) == len(SEED["pairings"])  # no pairing twice
    job = fixture_job(tmp_path)
    job.concepts_fixture()
    for c in v2.load(job.concepts_dir / "concepts.json")["concepts"]:
        assert v2.pairing_key(*v2.concept_pairing(c)) in keys, c["id"]
    for p in SEED["pairings"]:  # temper-ai is public: sources name fixtures or say "a fictional brief", never a product
        assert re.fullmatch(r"(converter fixtures? [a-z ]+|craft-v1 benchmark pages|converter fixture \w+; craft-v1 benchmark pages|"
                            r"homepage (benchmark )?run on a fictional brief, 2026-\d\d-\d\d)", p["source"]), p
    assert all(fresh not in keys for fresh in (v2.pairing_key(*f) for f in FRESH))


def test_a_recorded_pairing_is_rejected_either_way_round_and_a_brand_owned_one_is_kept(pairing_log_file):
    recorded = v2.recorded_pairings(pairing_log_file, "mine")
    fresh = concept("A", "Gloock", "#B8482A", ["a"], text="Hanken Grotesk")
    repeat = concept("B", "Fraunces", "#5B4BDB", ["b"], text="Instrument Sans")  # a converter fixture's pairing
    swapped = concept("C", "Atkinson Hyperlegible", "#0E1626", ["c"], text="Bricolage Grotesque")
    problems = v2.pairing_problems([fresh, repeat, swapped], recorded, set())
    assert len(problems) == 2
    assert problems[0].startswith("concept B: the type pairing Fraunces + Instrument Sans was already used (converter fixture atlas)")
    assert problems[1].startswith("concept C: the type pairing Atkinson Hyperlegible + Bricolage Grotesque was already used")
    assert "homepage/PAIRINGS.md" in problems[0]
    assert v2.pairing_problems([fresh, repeat], recorded, {"fraunces", "instrument sans"}) == []  # the brand owns both
    assert len(v2.pairing_problems([repeat], recorded, {"fraunces"})) == 1  # owning one face is not enough


def test_runs_log_their_pairings_and_a_run_never_blocks_its_own(pairing_log_file):
    fresh = concept("A", *FRESH[0][:1], "#B8482A", ["a"], text=FRESH[0][1])
    assert v2.record_pairings(pairing_log_file, "run-1", "offered", [fresh, {"id": "B"}]) == 1  # no fonts, no row
    row = json.loads(pairing_log_file.read_text().splitlines()[0])
    assert (row["display"], row["text"], row["kind"], row["concept"], row["workspace"]) == (*FRESH[0], "offered", "A", "run-1")
    assert v2.pairing_problems([fresh], v2.recorded_pairings(pairing_log_file, "run-1"), set()) == []
    other = v2.pairing_problems([fresh], v2.recorded_pairings(pairing_log_file, "run-2"), set())
    assert len(other) == 1 and "(offered in run run-1)" in other[0]
    with pairing_log_file.open("a") as fh:
        fh.write("not json\n")
    assert len(v2.recorded_pairings(pairing_log_file, "run-2")) == len(SEED["pairings"]) + 1  # a broken line is skipped


def test_pairings_stage_lists_the_used_pairings_for_the_art_director(tmp_path, pairing_log_file):
    job = pilot_job(tmp_path)
    v2.record_pairings(pairing_log_file, "elsewhere", "chosen", [concept("A", FRESH[0][0], "#B8482A", ["a"], text=FRESH[0][1])])
    out = job.pairings()
    text = (job.packet / "PAIRINGS.md").read_text()
    assert "- Fraunces + Instrument Sans (converter fixture atlas)" in text
    assert "- Gloock + Hanken Grotesk (chosen in run elsewhere)" in text
    assert "## Faces earlier runs reached for most" in text and "- Instrument Sans: " in text
    assert out["used_pairings"] == len(SEED["pairings"]) + 1 and out["path"] == "homepage/PAIRINGS.md"
    assert "pairings" in v2.STAGES
    ad = (ROOT / "configs/design/agents/design_homepage_art_director_v2.yaml").read_text()
    assert "homepage/PAIRINGS.md" in ad and "prefers-reduced-motion" in ad and "axe" in ad
    for name in ("design_homepage_v2", "design_homepage_v2_pilot", "design_homepage_v2_bench", "design_homepage_v2_fixture"):
        nodes = {n["name"]: n for n in yaml.safe_load((ROOT / f"configs/design/workflows/{name}.yaml").read_text())["workflow"]["nodes"]}
        assert nodes["pairings"]["input_map"]["stage"] == "pairings" and "pairings" in nodes["concepts"]["depends_on"], name


def test_direction_adds_the_picked_pairing_to_the_record(tmp_path, pairing_log_file):
    job = fixture_job(tmp_path)
    ready_for_direction(job)
    job.direction('{"concept": "B", ' + FIX + ', "notes": "warmer"}')
    rows = [json.loads(line) for line in pairing_log_file.read_text().splitlines()]
    assert [(r["display"], r["text"], r["kind"], r["concept"]) for r in rows] == [("Bricolage Grotesque", "Figtree", "chosen", "B")]


AXE_OK = {"ok": True, "settle": {"ms": 900, "unfinished": 0, "loops_stopped": 0}, "violations": []}
LOW_CONTRAST = {"id": "color-contrast", "impact": "serious", "nodes": 1, "wcag": ["wcag2aa", "wcag143"],
                "help": "Elements must meet minimum color contrast ratio thresholds",
                "targets": [{"target": ".planted-note", "summary": "Fix any of the following:\n  Element has insufficient color contrast of 2.6"}]}


def clean_axe(ids="ABC"):
    return {f"{cid}-{w}-{s}": dict(AXE_OK) for cid in ids for w in (1440, 390) for s in ("reduced", "settled")}


def test_axe_failures_become_concept_problems_with_where_and_an_example():
    results = clean_axe()
    assert v2.axe_problems(results, ["A", "B", "C"]) == []
    results["B-1440-reduced"] = {**AXE_OK, "violations": [LOW_CONTRAST]}
    results["B-390-settled"] = {**AXE_OK, "violations": [LOW_CONTRAST]}
    results["C-390-reduced"] = {"ok": False, "error": "Timeout 20000ms exceeded"}
    problems = v2.axe_problems(results, ["A", "B", "C"])
    assert problems == [
        "concept B: axe color-contrast (serious, wcag2aa, wcag143): Elements must meet minimum color contrast ratio thresholds; "
        "1 element(s) at 1440 reduced motion, 390 after its animations; e.g. .planted-note: Fix any of the following: "
        "Element has insufficient color contrast of 2.6",
        "concept C: the accessibility check could not run at 390 with reduced motion: Timeout 20000ms exceeded"]
    # measured as people meet the page: reduced motion, or after the load animations end (never mid-animation)
    assert "reducedMotion: job.state === 'reduced'" in v2.AXE_CODE and "getAnimations" in v2.AXE_CODE
    assert v2.AXE_SRC.is_file() and "wcag22aa" in v2.AXE_TAGS


def test_planted_contrast_concept_is_a_valid_page_with_one_real_failure_and_two_motion_decoys():
    page = SITE / "planted-contrast.html"
    text = page.read_text()
    assert v2.html_problems(page) == []
    assert v2.v1.contrast("#A39A91", "#FBF6EE") < 3 and ".planted-note { font-size: 15px; color: #A39A91;" in text
    assert "animation: rise 1.6s" in text and "infinite" in text  # a fade-in and a loop the measure must wait out


@pytest.fixture
def concept_browser(monkeypatch):
    """Renders and axe without a browser; axe answers from a dict the test edits."""
    state = {"axe": clean_axe(), "families": set(), "axe_calls": []}

    def fake_render(root, out, jobs):
        out.mkdir(parents=True, exist_ok=True)
        for j in jobs:
            (out / f"{j['name']}.png").write_bytes(b"png")
        return [{"name": j["name"], "ok": True, "scrollWidth": j["width"], "loadedFamilies": sorted(state["families"])} for j in jobs]

    def fake_axe(root, ids):
        state["axe_calls"].append((root, list(ids)))
        return {k: dict(v) for k, v in state["axe"].items()}

    monkeypatch.setattr(v2, "browser_jobs", fake_render)
    monkeypatch.setattr(v2, "concept_axe", fake_axe)
    monkeypatch.setattr(v2, "thumbnail_diffs", lambda out, names: {})
    monkeypatch.setattr(v2, "font_files", lambda family, weights, italic, dest, issues: [
        {"family": family, "weight": w, "style": "normal"} for w in weights])
    monkeypatch.setattr(v2, "copy_fonts", lambda faces, src, dest: None)
    return state


def test_concept_check_blocks_an_axe_failure_and_keeps_the_drafts_as_checked(tmp_path, concept_browser):
    job = fixture_job(tmp_path)
    job.concepts_fixture()
    concept_browser["families"] = {"Fraunces", "Instrument Sans", "Bricolage Grotesque", "Atkinson Hyperlegible", "DM Serif Display", "Figtree"}
    concept_browser["axe"]["B-390-settled"]["violations"] = [LOW_CONTRAST]
    out = job.concepts_check("draft")
    check = v2.load(job.concepts_dir / "check.json")
    assert out["verdict"] == "retry" and out["axe_violations"] == 1 and out["drafts"] == "homepage/concept-drafts"
    assert [p for p in check["problems"] if "axe" in p] == check["problems"]  # the axe failure is the only problem
    assert check["problems"][0].startswith("concept B: axe color-contrast")
    assert concept_browser["axe_calls"] == [(job.concepts_dir, ["A", "B", "C"])]
    assert check["axe"]["B-390-settled"]["violations"][0]["id"] == "color-contrast"
    assert check["pairings"]["A"] == "Fraunces + Instrument Sans"
    drafts = job.packet / "concept-drafts"  # refine rewrites the concepts: the drafts stay as they were checked
    assert (drafts / "B" / "index.html").read_bytes() == (job.concepts_dir / "B" / "index.html").read_bytes()
    assert (drafts / "shots" / "b-1440.png").is_file() and v2.load(drafts / "check.json")["verdict"] == "retry"
    assert v2.load(drafts / "concepts.json")["concepts"][1]["id"] == "B"
    concept_browser["axe"] = clean_axe()
    (job.concepts_dir / "B" / "index.html").write_text((job.concepts_dir / "B" / "index.html").read_text() + "\n")
    assert job.concepts_check("final")["verdict"] == "ok"
    assert (drafts / "B" / "index.html").read_text() != (job.concepts_dir / "B" / "index.html").read_text()  # final keeps no copy


def test_a_real_runs_concepts_that_repeat_recorded_pairings_must_pick_fresh_ones(tmp_path, concept_browser, pairing_log_file):
    job = pilot_job(tmp_path)
    fixture = fixture_job(tmp_path / "fx")
    fixture.concepts_fixture()
    shutil.copytree(fixture.concepts_dir, job.concepts_dir, dirs_exist_ok=True)
    spec = v2.load(job.concepts_dir / "concepts.json")
    spec.pop("fixture")  # the fixture pages offered as a real run's concepts: every pairing is already recorded
    v2.save(job.concepts_dir / "concepts.json", spec)
    concept_browser["families"] = {"Fraunces", "Instrument Sans", "Bricolage Grotesque", "Atkinson Hyperlegible", "DM Serif Display",
                                   "Figtree", *(face for pair in FRESH for face in pair)}
    out = job.concepts_check("final")
    repeats = [p for p in v2.load(job.concepts_dir / "check.json")["problems"] if "was already used" in p]
    assert out["verdict"] == "retry" and len(repeats) == 3 and not pairing_log_file.exists()  # nothing recorded on a retry
    for c, (display, text) in zip(spec["concepts"], FRESH, strict=True):
        c["fonts"]["display"]["family"], c["fonts"]["text"]["family"] = display, text
    v2.save(job.concepts_dir / "concepts.json", spec)
    out = job.concepts_check("final")
    assert out["verdict"] == "ok", v2.load(job.concepts_dir / "check.json")["problems"]
    rows = [json.loads(line) for line in pairing_log_file.read_text().splitlines()]  # offered: later runs pick others
    assert [(r["display"], r["text"], r["kind"]) for r in rows] == [(*f, "offered") for f in FRESH]
    assert {r["workspace"] for r in rows} == {job.root.name} and out["pairings_recorded"] == 3


@pytest.mark.parametrize("name", ["design_homepage_v2", "design_homepage_v2_pilot", "design_homepage_v2_bench"])
def test_refine_runs_only_when_the_draft_check_fails(name):
    _, nodes = workflow(name)  # queue #34: refining drafts that passed did not pay
    assert nodes["refine"]["condition"] == {"source": "check_draft.structured.verdict", "operator": "equals", "value": "retry"}
    assert nodes["refine"]["depends_on"] == ["check_draft"] and nodes["check"]["depends_on"] == ["refine"]
    assert nodes["concepts_next"]["loop_to"] == "refine"  # a final check that fails after a refine sends it round again


def passing_pilot_concepts(tmp_path, concept_browser):
    """A pilot run's three concepts (the fixture pages) with fresh pairings: a check passes them."""
    job = pilot_job(tmp_path)
    fixture = fixture_job(tmp_path / "fx")
    fixture.concepts_fixture()
    shutil.copytree(fixture.concepts_dir, job.concepts_dir, dirs_exist_ok=True)
    spec = v2.load(job.concepts_dir / "concepts.json")
    spec.pop("fixture")
    for c, (display, text) in zip(spec["concepts"], FRESH, strict=True):
        c["fonts"]["display"]["family"], c["fonts"]["text"]["family"] = display, text
    v2.save(job.concepts_dir / "concepts.json", spec)
    concept_browser["families"] = {face for pair in FRESH for face in pair}
    return job


def test_the_final_check_after_a_skipped_refine_is_the_passed_draft_check(tmp_path, concept_browser, pairing_log_file):
    job = passing_pilot_concepts(tmp_path, concept_browser)
    assert job.concepts_check("draft")["verdict"] == "ok" and len(concept_browser["axe_calls"]) == 1
    out = job.concepts_check("final")  # refine skipped: the same pages and spec as the passed draft check
    check = v2.load(job.concepts_dir / "check.json")
    assert out["verdict"] == "ok" and out["reused_draft_check"] == "check-draft-0.json" and out["axe_violations"] == 0
    assert len(concept_browser["axe_calls"]) == 1  # nothing rendered or measured twice
    assert check["phase"] == "final" and check["reused_draft_check"] == "check-draft-0.json"
    assert check["axe"] == v2.load(job.concepts_dir / "check-draft-0.json")["axe"] and check["problems"] == []
    assert out["pairings_recorded"] == 3 and out["questions"][0]["id"] == "direction"  # offered at the gate as before
    rows = [json.loads(line) for line in pairing_log_file.read_text().splitlines()]
    assert [(r["display"], r["text"], r["kind"]) for r in rows] == [(*f, "offered") for f in FRESH]
    assert job.concepts_next()["verdict"] == "ok" and job.concepts_check("final")["reused"] is True


def test_the_final_check_measures_again_when_the_pages_changed_after_a_passed_draft(tmp_path, concept_browser, pairing_log_file):
    job = passing_pilot_concepts(tmp_path, concept_browser)
    assert job.concepts_check("draft")["verdict"] == "ok"
    page = job.concepts_dir / "B" / "index.html"
    page.write_text(page.read_text() + "\n")
    out = job.concepts_check("final")
    assert out["verdict"] == "ok" and "reused_draft_check" not in out and len(concept_browser["axe_calls"]) == 2


def test_the_final_check_measures_again_after_drafts_that_failed(tmp_path, concept_browser, pairing_log_file):
    job = passing_pilot_concepts(tmp_path, concept_browser)
    concept_browser["axe"]["A-390-settled"]["violations"] = [LOW_CONTRAST]
    assert job.concepts_check("draft")["verdict"] == "retry"
    concept_browser["axe"] = clean_axe()
    out = job.concepts_check("final")  # refine ran: never the failed draft check, whatever the pages
    assert out["verdict"] == "ok" and "reused_draft_check" not in out and len(concept_browser["axe_calls"]) == 2
