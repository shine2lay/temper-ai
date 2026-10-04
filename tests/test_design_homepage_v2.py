"""Model-free contracts for Design's homepage workflow v2 and its HTML->Penpot converter.

No models, accounts, browsers or Penpot server: a recorded browser scene of a fixture page
(tests/design_homepage_v2_scenes/, captured from configs/design/testpages/html-fixtures/
atlas.html) stands in for the browser, and a fake Penpot client applies the changes in
memory. The live proofs (real Penpot, real editor, fidelity) are evidence in Design's
results folder, not unit tests.
"""
import importlib.util
import json
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
BASE = "http://172.21.0.1:42727"  # the recorded scenes' page address


def scenes(widths=(390, 1440)):
    return {w: json.loads((SCENES / f"scene-{w}.json").read_text()) for w in widths}


# --------------------------------------------------------------------------- workflows


def workflow(name):
    raw = yaml.safe_load((BIN.parent / "workflows" / f"{name}.yaml").read_text())["workflow"]
    assert WorkflowConfig.from_dict(raw).name == name
    return raw, {n["name"]: n for n in raw["nodes"]}


@pytest.mark.parametrize("name", ["design_homepage_v2", "design_homepage_v2_fixture"])
def test_workflow_native_gates_and_bounded_loops(name):
    raw, nodes = workflow(name)
    gates = sorted(n for n, v in nodes.items() if v.get("gate"))
    assert gates == ["direction", "final"]
    looping = {n: v for n, v in nodes.items() if v.get("loop_to")}
    assert set(looping) == {"concepts_next", "next_round", "after_final"}
    for node in looping.values():
        assert node["max_loops"] <= 3 and node["on_max_loops"] == "fail"
        assert node["agent"] == "design_homepage_stage_v2"  # loop control never sits on a model or gate node
    assert nodes["next_round"]["loop_to"] == nodes["after_final"]["loop_to"] == "plan_round"
    assert nodes["after_final"]["loop_condition"] == {"source": "final.structured.verdict", "operator": "equals",
                                                      "value": "request_changes"}
    assert nodes["revise"]["condition"] == {"source": "plan_round.structured.action", "operator": "equals",
                                            "value": "revise"}
    assert not {"approval", "final_json", "mode"} & set(raw["inputs"])
    order = [n["name"] for n in raw["nodes"]]
    assert order.index("direction") < order.index("build") < order.index("convert") < order.index("verify") \
        < order.index("handoff") < order.index("final")


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
    assert set(nodes["combine"]["depends_on"]) == {"merge", "craft"}
    script = [v for v in nodes.values() if v["agent"] == "design_homepage_stage_v2"]
    assert all(v["input_map"]["mode"] == "real" for v in script)


def test_fixture_workflow_is_model_free():
    _, nodes = workflow("design_homepage_v2_fixture")
    assert all(v["agent"] == "design_homepage_stage_v2" for v in nodes.values())
    assert all(v["input_map"]["mode"] == "fixture" for v in nodes.values())
    stages = {v["input_map"]["stage"] for v in nodes.values()}
    assert stages <= set(v2.STAGES)
    assert {"concepts_fixture", "build_fixture", "revise_fixture", "review_fixture", "convert", "verify"} <= stages


def test_agents_use_claude_opus_and_script_wrapper_holds_no_secret():
    for name in ("art_director", "designer", "craft_critic", "reviser"):
        agent = yaml.safe_load((BIN.parent / "agents" / f"design_homepage_{name}_v2.yaml").read_text())["agent"]
        assert agent["type"] == "llm" and agent["provider"] == "claude" and agent["model"] == "opus"
        assert "tools" not in agent  # the Claude CLI's own Read shows PNGs; a tools: block breaks the provider
        assert "```json" in agent["system_prompt"]
    stage = yaml.safe_load((BIN.parent / "agents/design_homepage_stage_v2.yaml").read_text())["agent"]
    assert stage["type"] == "script"
    template = stage["script_template"]
    assert "gate is defined" in template and "design_homepage_v2.py" in template
    assert "PASSWORD" not in template and "--fixture" in template
    craft = (BIN.parent / "agents/design_homepage_craft_critic_v2.yaml").read_text()
    assert "review/craft/" in craft  # never review/critic/: design_merge would reject taste findings


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


def fake_convert(tmp_path, monkeypatch, client):
    recorded = scenes()
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


@pytest.mark.parametrize("raw, error", [
    ("not json", "saved JSON"), ('{"concept": "D", "approval": "fixture-test"}', "concept A, B or C"),
    ('{"concept": "A", "approval": "owner-direction"}', "fixture-test")])
def test_fixture_direction_gate_never_records_owner_approval(tmp_path, raw, error):
    job = fixture_job(tmp_path)
    ready_for_direction(job)
    with pytest.raises(ValueError, match=error):
        job.direction(raw)


def test_direction_needs_a_passed_check_and_prepares_the_site(tmp_path):
    job = fixture_job(tmp_path)
    ready_for_direction(job, verdict="retry")
    with pytest.raises(ValueError, match="not passed"):
        job.direction('{"concept": "B", "approval": "fixture-test"}')
    ready_for_direction(job)
    out = job.direction('{"concept": "B", "approval": "fixture-test", "notes": "warmer"}')
    assert out["owner_direction_approved"] is False and job.site.is_dir()
    assert job.direction('{"concept": "B", "approval": "fixture-test", "notes": "warmer"}')["reused"]
    with pytest.raises(ValueError, match="inputs changed"):
        job.direction('{"concept": "C", "approval": "fixture-test"}')


def test_real_direction_needs_owner_label(tmp_path):
    job = v2.Job(str(tmp_path), fixture=False)
    ready_for_direction(job)
    with pytest.raises(ValueError, match="owner-direction"):
        job.direction('{"concept": "A", "approval": "fixture-test"}')


def test_concepts_next_reports_only_the_final_check(tmp_path):
    job = fixture_job(tmp_path)
    ready_for_direction(job, verdict="retry")
    assert job.concepts_next()["verdict"] == "retry"
    v2.save(job.concepts_dir / "check.json", {"phase": "draft", "verdict": "ok"})
    with pytest.raises(ValueError, match="not the final"):
        job.concepts_next()


def review_round(job, usability_sev, craft_sev, status="confirmed"):
    review = job.root / "review"
    (review / "craft").mkdir(parents=True, exist_ok=True)
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
        job.final('{"approval": "fixture-test"}')
    job.state["stages"]["handoff-1"] = {"fingerprint": "x", "completed_at": "t", "output": {}}
    with pytest.raises(ValueError, match="notes"):
        job.final('{"verdict": "request_changes", "notes": []}')
    with pytest.raises(ValueError, match="fixture-test"):
        job.final('{"approval": "owner-final"}')
    out = job.final('{"verdict": "request_changes", "notes": ["bigger headline"]}')
    assert out["verdict"] == "request_changes" and job.state["fix_list"][0]["problem"] == "bigger headline"
    assert job.plan_round()["action"] == "revise" and job.state["owner_changes"] == 1
    job.state["owner_changes"] = v2.MAX_OWNER_CHANGES
    job.state["stages"]["handoff-2"] = job.state["stages"]["handoff-1"]
    with pytest.raises(ValueError, match="two owner change rounds"):
        job.final('{"verdict": "request_changes", "notes": ["again"]}')
    done = job.final('{"approval": "fixture-test"}')
    assert done["verdict"] == "approved" and done["final_owner_approved"] is False


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
    assert job.concepts_fixture()["reused"]
