"""Model-free contracts for Design's craft-critic benchmark (design_craft_bench, queue #10).

The benchmark copies one page of configs/design/testpages/craft-v1 into a run's workspace, writes
what the homepage craft critic reads through the same code as design_homepage_v2's measure stage,
runs the live critic unchanged and summarises its verdict. Which pages carry which planted problems
is kept on the host with the answer key, so nothing here may hint at it. No browser or model: the
capture is replaced by a stub, and the live runs are graded on the host.
"""
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest
import yaml

from temper_ai.stage.models import WorkflowConfig

ROOT = Path(__file__).resolve().parents[1]
DESIGN = ROOT / "configs/design"
BIN = DESIGN / "bin"
SITE = DESIGN / "testpages/craft-v1"
sys.path.insert(0, str(BIN))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, BIN / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bench = _load("design_craft_bench")
v2 = bench.v2
MANIFEST = json.loads((DESIGN / "testpages/craft-v1.json").read_text())
# Words a page, its manifest or the site's styles must not carry: they would tell the critic what to look for.
HINTS = re.compile(r"plant(?!er)|flaw|control|clean|wrong|answer|bench|craft|competing|misalign|off-grid|"
                   r"low-contrast|too many|<!--|type_sizes|scale_contrast|spacing_scale|cta_contrast|"
                   r"section_rhythm|grid_alignment|competing_primaries", re.I)


def test_workflow_runs_the_live_craft_critic_between_two_script_steps():
    raw = yaml.safe_load((DESIGN / "workflows/design_craft_bench.yaml").read_text())["workflow"]
    assert WorkflowConfig.from_dict(raw).name == "design_craft_bench"
    nodes = {n["name"]: n for n in raw["nodes"]}
    assert list(nodes) == ["prepare", "craft", "collect"]
    assert nodes["craft"]["agent"] == "design_homepage_craft_critic_v2"  # the live critic, unchanged
    assert nodes["prepare"]["agent"] == nodes["collect"]["agent"] == "design_craft_bench_stage"
    assert nodes["prepare"]["input_map"] == {"stage": "prepare", "site": "input.site", "page": "input.page"}
    assert nodes["collect"]["input_map"] == {"stage": "collect"}
    assert not [n for n, v in nodes.items() if v.get("gate") or v.get("loop_to")]
    assert raw["inputs"]["site"]["required"] and raw["inputs"]["page"]["required"]


def test_stage_agent_is_a_model_free_script():
    text = (DESIGN / "agents/design_craft_bench_stage.yaml").read_text()
    agent = yaml.safe_load(text)["agent"]
    assert agent["type"] == "script" and "${" not in text
    assert "/app/configs/design/bin/design_craft_bench.py" in agent["script_template"]
    assert '("prepare", "collect")' in agent["script_template"]


def test_site_has_nine_contract_pages_for_two_fictional_products():
    assert MANIFEST["site"] == "craft-v1" and MANIFEST["key"].startswith("~/design-lab/")  # the key is off the box
    assert MANIFEST["pages"] == [f"page-{n:02d}" for n in range(1, 10)]
    assert sorted(set(MANIFEST["page_product"].values())) == sorted(MANIFEST["products"])
    for name, product in MANIFEST["products"].items():
        assert product["brief"]["fictional"] is True and product["brief"]["disclosure"], name
        assert {"product", "audience", "purpose", "cta"} <= set(product["brief"]), name
        assert {"id", "name", "brief", "signature_move", "motion", "imagery"} <= set(product["concept"]), name
    fonts = (SITE / MANIFEST["fonts_css"]).read_text()
    for name in MANIFEST["font_dirs"]:
        assert (DESIGN / "testpages/html-fixtures/fonts" / name).is_dir() and f'url("{name}/' in fonts
    for page in MANIFEST["pages"]:
        html = SITE / page / "index.html"
        assert v2.html_problems(html) == [], page
        assert 'href="fonts/fonts.css"' in html.read_text(), page
    assert sorted(p.name for p in SITE.iterdir() if p.is_dir()) == MANIFEST["pages"]


def test_nothing_on_the_box_hints_at_the_planted_problems():
    texts = {str(p.relative_to(SITE)): p.read_text() for p in SITE.rglob("*") if p.is_file()}
    texts["what the manifest says per page"] = json.dumps([MANIFEST[k] for k in ("pages", "page_product", "products")])
    for name, text in texts.items():
        assert not HINTS.search(text), (name, HINTS.search(text).group(0))
    prompt = (DESIGN / "agents/design_homepage_craft_critic_v2.yaml").read_text().lower()
    for product in MANIFEST["products"]:
        assert product not in prompt
    assert not list(ROOT.rglob("craft-v1.yaml"))  # the answer key lives in ~/design-lab/answers only


@pytest.fixture
def no_browser(monkeypatch):
    calls = []

    def fake_inputs(review, site, brief, number, chosen, notes, references):
        calls.append({"review": review, "site": site, "brief": brief, "number": number, "chosen": chosen,
                      "notes": notes, "references": references})
        for sub in ("critic", "craft", "content"):
            (review / sub).mkdir(parents=True, exist_ok=True)
        return {"1440": {"scale_ratio": 4.2}, "390": {"scale_ratio": 3.1}}

    monkeypatch.setattr(v2, "write_review_inputs", fake_inputs)
    return calls


def test_prepare_copies_one_page_with_its_fonts_and_writes_the_critics_inputs(tmp_path, no_browser):
    out = bench.prepare(tmp_path, SITE, "page-04")
    product = MANIFEST["products"][MANIFEST["page_product"]["page-04"]]
    site = tmp_path / "homepage/site"
    assert (site / "index.html").read_bytes() == (SITE / "page-04/index.html").read_bytes()
    assert (site / "fonts/fonts.css").read_bytes() == (SITE / "fonts.css").read_bytes()
    assert all(any((site / "fonts" / name).glob("*.ttf")) for name in MANIFEST["font_dirs"])
    call = no_browser[0]
    assert call["site"] == site and call["review"] == tmp_path / "review" and call["number"] == 1
    assert call["brief"] == product["brief"] and call["chosen"] == product["concept"]
    assert call["notes"] == "" and call["references"] is None
    assert "None for this review" in (tmp_path / "review/references.md").read_text()
    saved = json.loads((tmp_path / "homepage/bench.json").read_text())
    assert saved["page"] == "page-04" and saved["site"] == "craft-v1" and saved["scale_ratio"]["390"] == 3.1
    assert out["status"] == "completed" and out["product"] == product["brief"]["product"]
    with pytest.raises(ValueError, match="fresh workspace"):
        bench.prepare(tmp_path, SITE, "page-05")


def test_prepare_copies_a_saved_run_page_with_its_own_fonts(tmp_path, no_browser):
    """Concept pages saved from a run (queue #34) bring their own fonts/ folder: the whole page folder is copied."""
    site = tmp_path / "saved" / "concepts-x"
    page = site / "p01"
    (page / "fonts" / "fraunces").mkdir(parents=True)
    page_html = (SITE / "page-04/index.html").read_text()
    (page / "index.html").write_text(page_html)
    (page / "fonts" / "fonts.css").write_text('@font-face { font-family: "Fraunces"; src: url("fraunces/F.ttf"); }\n')
    (page / "fonts" / "fraunces" / "F.ttf").write_bytes(b"ttf")
    product = MANIFEST["products"][MANIFEST["page_product"]["page-04"]]
    (site.parent / "concepts-x.json").write_text(json.dumps({"pages": ["p01"], "page_product": {"p01": "one"},
                                                             "products": {"one": product}, "font_dirs": [], "fonts_css": ""}))
    ws = tmp_path / "ws"
    out = bench.prepare(ws, site, "p01")
    copied = ws / "homepage/site"
    assert (copied / "index.html").read_text() == page_html
    assert (copied / "fonts/fraunces/F.ttf").read_bytes() == b"ttf" and "Fraunces" in (copied / "fonts/fonts.css").read_text()
    assert no_browser[0]["chosen"] == product["concept"] and out["page"] == "p01"


@pytest.mark.parametrize("page, error", [("page-10", "is not a page"), ("../page-01", "short lowercase"),
                                         ("Page-01", "short lowercase")])
def test_prepare_refuses_pages_outside_the_site(tmp_path, no_browser, page, error):
    with pytest.raises(ValueError, match=re.escape(error)):
        bench.prepare(tmp_path, SITE, page)
    assert not no_browser and not (tmp_path / "homepage").exists()


def test_collect_summarises_the_verdict_and_refuses_a_missing_one(tmp_path, no_browser):
    with pytest.raises(ValueError, match="no prepared"):
        bench.collect(tmp_path)
    bench.prepare(tmp_path, SITE, "page-02")
    with pytest.raises(ValueError, match="wrote no"):
        bench.collect(tmp_path)
    craft = tmp_path / "review/craft/craft.json"
    craft.write_text("{not json")
    with pytest.raises(ValueError, match="not valid JSON"):
        bench.collect(tmp_path)
    craft.write_text(json.dumps({"critic": "craft"}))
    with pytest.raises(ValueError, match="no findings list"):
        bench.collect(tmp_path)
    findings = [{"check": "scale", "severity": 3}, {"check": "rhythm", "severity": 2}, {"check": "scale", "severity": 1}]
    craft.write_text(json.dumps({"findings": findings, "template_test": {"verdict": "distinct"}}))
    out = bench.collect(tmp_path)
    assert out["page"] == "page-02" and out["findings"] == 3 and out["template_verdict"] == "distinct"
    assert out["severity_counts"] == {"4": 0, "3": 1, "2": 1, "1": 1} and out["checks"] == {"scale": 2, "rhythm": 1}
