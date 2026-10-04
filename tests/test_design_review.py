"""Model-free contracts for Design's reviewer (design_review v2, queue #7).

No models, accounts or browsers. The target-size geometry in design_measure.js is a pure
function between two markers, run here in node on hand-made generic layouts (among them a
spaced pair of small buttons and a small checkbox inside a tall label). The facts lines and the
claim check (design_review_verify.py) run on small hand-made facts and critic files.
"""

import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from temper_ai.config.importer import parse_yaml
from temper_ai.stage.models import WorkflowConfig

ROOT = Path(__file__).resolve().parents[1]
DESIGN = ROOT / "configs/design"
BIN = DESIGN / "bin"
sys.path.insert(0, str(BIN))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, BIN / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------- configs

REVIEW_AGENTS = [
    "design_capture",
    "design_critic",
    "design_verify",
    "design_merge",
]


def test_review_workflow_runs_verify_between_critics_and_merge():
    raw = yaml.safe_load((DESIGN / "workflows/design_review.yaml").read_text())[
        "workflow"
    ]
    assert WorkflowConfig.from_dict(raw).name == "design_review"
    nodes = {n["name"]: n for n in raw["nodes"]}
    assert {name: n["agent"] for name, n in nodes.items()} == {
        "capture": "design_capture",
        "critic_a": "design_critic",
        "critic_b": "design_critic",
        "verify": "design_verify",
        "merge": "design_merge",
    }
    assert set(nodes["verify"]["depends_on"]) == {"critic_a", "critic_b"}
    assert nodes["merge"]["depends_on"] == ["verify"]
    assert set(raw["inputs"]) == {"brief", "pages", "site", "base_url", "viewports"}
    assert raw["outputs"]["dropped_by_facts"] == "merge.structured.dropped_by_facts"
    assert raw["outputs"]["contradicted_claims"] == "verify.structured.contradicted"


@pytest.mark.parametrize("name", REVIEW_AGENTS)
def test_review_agents_import(name):
    parsed = parse_yaml(DESIGN / "agents" / f"{name}.yaml")
    assert parsed["name"] == name and parsed["config_type"] == "agent"


def test_review_steps_run_the_promoted_scripts():
    """No candidate (_next) copy is left behind: the live steps run the graded scripts."""
    capture = yaml.safe_load((DESIGN / "agents/design_capture.yaml").read_text())[
        "agent"
    ]
    assert "/app/configs/design/bin/design_capture.py" in capture["script_template"]
    verify = yaml.safe_load((DESIGN / "agents/design_verify.yaml").read_text())["agent"]
    assert "design_review_verify.py --review review" in verify["script_template"]
    assert _load("design_capture").MEASURE.name == "design_measure.js"
    leftovers = [
        p.name
        for p in DESIGN.rglob("*")
        if p.is_file()
        and re.search(
            r"design_(review|capture|critic|verify|merge|measure)\w*_next", p.name
        )
    ]
    assert leftovers == []


def test_merge_works_without_a_verify_step():
    """The homepage workflows reuse design_critic and design_merge without design_verify."""
    merge = yaml.safe_load((DESIGN / "agents/design_merge.yaml").read_text())["agent"]
    assert (
        "If verify.json is missing, do those checks yourself from facts.md"
        in (merge["system_prompt"])
    )
    for workflow in (
        "design_homepage_v1",
        "design_homepage_v2",
        "design_homepage_pilot_v1",
    ):
        raw = yaml.safe_load((DESIGN / f"workflows/{workflow}.yaml").read_text())[
            "workflow"
        ]
        agents = {n["name"]: n.get("agent") for n in raw["nodes"]}
        assert agents["merge"] == "design_merge", workflow
        assert "design_verify" not in agents.values(), workflow


def test_review_prompts_name_no_benchmark_site():
    """Answer keys stay host-only; prompts carry no test-site names or their page content."""
    for name in ("design_critic", "design_merge"):
        text = (DESIGN / "agents" / f"{name}.yaml").read_text().lower()
        for site in sorted(p.stem for p in (DESIGN / "testpages").glob("*.json")):
            assert site.split("-")[0] not in text, (name, site)
        prompt = yaml.safe_load((DESIGN / "agents" / f"{name}.yaml").read_text())[
            "agent"
        ]["system_prompt"]
        for anchor in (
            "4 catastrophe",
            "3 major",
            "2 minor",
            "1 cosmetic",
            "When torn between two levels",
        ):
            assert anchor in prompt


# --------------------------------------------------------------------------- target geometry (node)

NODE = shutil.which("node")


def geometry(targets):
    js = (BIN / "design_measure.js").read_text()
    block = re.search(r"// BEGIN target-geometry.*?// END target-geometry", js, re.S)
    assert block, "geometry markers missing"
    code = (
        block.group(0)
        + "\nconsole.log(JSON.stringify(targetGeometry("
        + json.dumps(targets)
        + ")));\n"
    )
    out = subprocess.run(
        [NODE, "-e", code], capture_output=True, text=True, timeout=30, check=True
    )
    return {r["id"]: r for r in json.loads(out.stdout)}


def t(i, x, y, w, h, **kw):
    return {"id": i, "rect": [x, y, w, h]} | kw


needs_node = pytest.mark.skipif(NODE is None, reason="node not installed")


@needs_node
def test_touching_small_buttons_fail():
    r = geometry([t(0, 100, 100, 20, 20), t(1, 120, 100, 20, 20)])
    assert r[0]["passes"] is None and r[1]["passes"] is None
    assert r[0]["nearest"] == {"id": 1, "edge": 10.0, "centre": 20.0, "hit": "target"}


@needs_node
def test_spaced_small_buttons_pass_by_spacing():
    # Two 20x20 buttons 12 px apart (centres 32 px): each 24 px circle clears the other.
    r = geometry(
        [t(0, 100, 100, 20, 20), t(1, 132, 100, 20, 20), t(2, 100, 200, 200, 44)]
    )
    assert r[0]["passes"] == r[1]["passes"] == "spacing"
    assert r[0]["nearest"]["id"] == 1 and r[0]["nearest"]["edge"] == 22.0
    assert r[2]["passes"] == "size" and not r[2]["undersized"]


@needs_node
def test_checkbox_passes_through_its_label():
    # A 12x12 checkbox inside a 44 px tall label: the label is part of the target.
    r = geometry([t(0, 16, 16, 12, 12, labels=[[0, 0, 300, 44]]), t(1, 0, 46, 120, 44)])
    assert r[0]["passes"] == "label" and r[0]["by"] == [0, 0, 300, 44]


@needs_node
def test_small_label_does_not_rescue_a_crowded_checkbox():
    # Checkbox 12x12 with an 18 px tall label; the next row's label starts 2 px below.
    r = geometry(
        [
            t(0, 0, 0, 12, 12, labels=[[16, 0, 100, 18]]),
            t(1, 0, 20, 12, 12, labels=[[16, 20, 100, 18]]),
        ]
    )
    assert r[0]["passes"] is None and r[0]["nearest"]["id"] == 1


@needs_node
def test_circles_too_close_fail_even_when_boxes_are_clear():
    # 10x10 targets, centres 22 px apart: box edge 17 px away (fine), circles overlap.
    r = geometry([t(0, 0, 0, 10, 10), t(1, 22, 0, 10, 10)])
    assert r[0]["passes"] is None and r[0]["nearest"]["hit"] == "circle"


@needs_node
def test_circles_that_only_touch_pass():
    r = geometry([t(0, 0, 0, 10, 10), t(1, 24, 0, 10, 10)])
    assert r[0]["passes"] == r[1]["passes"] == "spacing"


@needs_node
def test_small_icon_next_to_a_big_button_fails():
    # 16x16 icon whose centre is 10 px from a big button's edge: its circle reaches the button.
    r = geometry([t(0, 2, 12, 16, 16), t(1, 20, 0, 100, 40)])
    assert (
        r[0]["passes"] is None
        and r[0]["nearest"]["hit"] == "target"
        and r[0]["nearest"]["edge"] == 10.0
    )
    assert r[1]["passes"] == "size"


@needs_node
def test_circle_that_just_reaches_a_big_button_passes():
    # Centre exactly 12 px from the button's edge: the circle touches it, which WCAG allows.
    r = geometry([t(0, 0, 12, 16, 16), t(1, 20, 0, 100, 40)])
    assert r[0]["passes"] == "spacing" and r[0]["nearest"]["edge"] == 12.0


@needs_node
def test_inline_link_is_exempt_but_still_a_neighbour():
    r = geometry([t(0, 0, 0, 16, 16), t(1, 18, 0, 40, 16, exempt="inline")])
    assert r[1]["passes"] == "inline"
    assert r[0]["passes"] is None and r[0]["nearest"]["id"] == 1


@needs_node
def test_nested_targets_skip_each_other():
    r = geometry([t(0, 0, 0, 300, 120, skip=[1]), t(1, 10, 10, 16, 16, skip=[0])])
    assert r[1]["passes"] == "spacing" and r[1]["nearest"] is None


# --------------------------------------------------------------------------- facts lines

cap = _load("design_capture")


def test_facts_lines_name_failures_and_passes():
    f = {
        "small_targets": [
            {
                "sel": "div.pager > button:nth-of-type(1)",
                "name": "Earlier",
                "box": [0, 0, 20, 20],
                "too_close_to": {
                    "sel": "div.pager > button:nth-of-type(2)",
                    "name": "Later",
                    "edge": 10.0,
                    "centre": 20.0,
                },
                "hit": "target",
            }
        ],
        "targets_pass": [
            {
                "sel": "label.opt > input",
                "name": "Send me tips",
                "box": [0, 0, 12, 12],
                "passes": "label",
                "label_box": [0, 0, 300, 44],
            },
            {
                "sel": "div.more > button",
                "name": "Next page",
                "box": [0, 0, 20, 20],
                "passes": "spacing",
                "nearest": {
                    "sel": "a.home",
                    "name": "Home",
                    "edge": 22.0,
                    "centre": None,
                },
            },
        ],
        "contrast_exempt": [
            {"sel": "button.ghost", "text": "Export PDF", "contrast": 1.6, "needs": 4.5}
        ],
    }
    problems = [line for _k, line in cap._items(f)]
    assert problems == [
        "target smaller than 24x24 px without the 24 px spacing (WCAG 2.5.8): "
        '`div.pager > button:nth-of-type(1)` "Earlier" 20x20 px; '
        '`div.pager > button:nth-of-type(2)` "Later" is 10.0 px from its centre (needs 12)'
    ]
    passes = [line for _k, line in cap._passes(f)]
    assert (
        passes[0].startswith("meets WCAG 2.5.8 through its label")
        and "label 300x44 px" in passes[0]
    )
    assert (
        "by the spacing exception" in passes[1]
        and "22.0 px from its centre" in passes[1]
    )
    assert "no contrast requirement" in passes[2] and '"Export PDF" 1.6:1' in passes[2]


# --------------------------------------------------------------------------- claim check

ver = _load("design_review_verify")


def _review(tmp_path, critic_findings):
    review = tmp_path / "review"
    (review / "facts").mkdir(parents=True)
    (review / "shots").mkdir()
    (review / "critic").mkdir()
    pages = {
        "search.html": {
            "small_targets": [
                {
                    "sel": "div.pager > button:nth-of-type(1)",
                    "name": "Earlier",
                    "box": [0, 0, 20, 20],
                }
            ]
        },
        "done.html": {
            "targets_pass": [
                {
                    "sel": "section.again > div.pager > button:nth-of-type(1)",
                    "name": "Earlier",
                    "box": [0, 0, 20, 20],
                    "passes": "spacing",
                    "nearest": {"sel": "a", "name": "x", "edge": 22.0, "centre": None},
                }
            ],
            "controls": [
                {
                    "sel": "button.ghost",
                    "name": "Export PDF",
                    "disabled": True,
                    "box": [0, 0, 120, 44],
                }
            ],
            "contrast_failures": [
                {
                    "sel": "p.note",
                    "text": "Exports are ready the next day",
                    "contrast": 3.1,
                    "needs": 4.5,
                }
            ],
        },
        "form.html": {
            "targets_pass": [
                {
                    "sel": "label.opt > input",
                    "name": "Send me tips",
                    "box": [0, 0, 12, 12],
                    "passes": "label",
                    "label_box": [0, 0, 300, 44],
                }
            ]
        },
    }
    index = {"pages": []}
    for page, facts in pages.items():
        name = page.split(".")[0]
        views = []
        for vp in ("desktop", "mobile"):
            (review / "facts" / f"{name}-{vp}.json").write_text(json.dumps(facts))
            (review / "shots" / f"{name}-{vp}-1.png").write_bytes(b"png")
            views.append({"viewport": vp, "facts": f"facts/{name}-{vp}.json"})
        index["pages"].append({"page": page, "name": name, "views": views})
    (review / "capture.json").write_text(json.dumps(index))
    (review / "critic" / "c1.json").write_text(
        json.dumps({"critic": "c1", "findings": critic_findings})
    )
    return review


def finding(
    i,
    page,
    element,
    problem,
    criterion,
    evidence="shots/search-desktop-1.png",
    viewport="all",
):
    return {
        "id": i,
        "page": page,
        "viewport": viewport,
        "element": element,
        "problem": problem,
        "evidence": evidence,
        "criterion": criterion,
        "kind": "judged",
        "severity": 2,
    }


def rows(tmp_path, findings):
    review = _review(tmp_path, findings)
    assert ver.main(["--review", str(review)]) == 0
    data = json.loads((review / "verify.json").read_text())
    return data, {r["source_id"]: r for r in data["findings"]}


def test_spaced_target_on_one_page_is_dropped_from_a_two_page_claim(tmp_path):
    _, r = rows(
        tmp_path,
        [
            finding(
                "F1",
                "search.html, done.html",
                "'Earlier' / 'Later' arrows",
                "Tiny 20x20 px buttons, hard to tap.",
                "WCAG 2.5.8 target size (minimum)",
                "shots/search-desktop-1.png, done-mobile-1.png",
            )
        ],
    )
    row = r["c1:F1"]
    assert row["verdict"] == "partly contradicted"
    assert row["contradicted_pages"] == ["done.html"] and row["supported_pages"] == [
        "search.html"
    ]
    assert any("spacing exception" in line for line in row["contradicting_facts"])


def test_checkbox_in_a_tall_label_is_not_a_small_target(tmp_path):
    _, r = rows(
        tmp_path,
        [
            finding(
                "F2",
                "form.html",
                "'Send me tips' checkbox",
                "The checkbox is a small target on touch.",
                "Fitts / touch comfort",
                "form-mobile-1.png (box ~13 px)",
            )
        ],
    )
    assert r["c1:F2"]["verdict"] == "contradicted"
    assert "through its label: label 300x44 px" in r["c1:F2"]["contradicting_facts"][0]


def test_a_finding_that_grants_the_pass_makes_no_failure_claim(tmp_path):
    _, r = rows(
        tmp_path,
        [
            finding(
                "F3",
                "done.html",
                "'Earlier' arrow",
                "Small, though it meets 2.5.8 by spacing; hard to hit on a phone.",
                "usability: target size (Fitts)",
                "done-mobile-1.png",
            )
        ],
    )
    assert r["c1:F3"]["verdict"] == "not checked"


def test_disabled_control_contrast_is_exempt_unless_failing_text_is_named(tmp_path):
    _, r = rows(
        tmp_path,
        [
            finding(
                "F4",
                "done.html",
                "'Export PDF' button",
                "Its grey text is almost unreadable.",
                "WCAG 1.4.3 contrast (minimum)",
                "done-desktop-1.png",
            ),
            finding(
                "F5",
                "done.html",
                "'Export PDF' button and the note 'Exports are ready the next day'",
                "Both are pale.",
                "WCAG 1.4.3 contrast (minimum)",
                "done-desktop-1.png",
            ),
            finding(
                "F6",
                "done.html",
                "'Export PDF' button",
                "Disabled controls are exempt, but it is hard to read.",
                "WCAG 1.4.3 (inactive exemption)",
                "done-desktop-1.png",
            ),
        ],
    )
    assert r["c1:F4"]["verdict"] == "contradicted"
    assert "no contrast requirement" in r["c1:F4"]["contradicting_facts"][0]
    assert r["c1:F5"]["verdict"] == "supported"
    assert r["c1:F6"]["verdict"] == "not checked"


def test_checkable_needs_element_page_and_a_tile_or_value(tmp_path):
    data, r = rows(
        tmp_path,
        [
            finding(
                "F7",
                "search.html",
                "Results heading",
                "Says nothing about filters.",
                "Nielsen 1",
                evidence="seen on search-desktop-1",
            ),
            finding(
                "F8",
                "search.html",
                "Results heading",
                "Says nothing about filters.",
                "Nielsen 1",
                evidence="the heading reads 'Results'",
            ),
            finding(
                "F9",
                "other.html",
                "Results heading",
                "Says nothing about filters.",
                "Nielsen 1",
            ),
            finding("F10", "search.html", "", "Something is off.", "Nielsen 8"),
        ],
    )
    assert (
        r["c1:F7"]["checkable"]
        and "search-desktop-1.png" in r["c1:F7"]["checkable_why"]
    )
    assert not r["c1:F8"]["checkable"]
    assert (
        not r["c1:F9"]["checkable"]
        and r["c1:F9"]["checkable_why"] == "page not among the reviewed pages"
    )
    assert not r["c1:F10"]["checkable"]
    assert data["summary"]["not_checkable"] == 3


def test_selectors_match_with_child_or_descendant_steps():
    sel = "header.top > div.wrap > nav.nav > a:nth-of-type(2)"
    assert ver.selector_named(sel, ["header.top nav.nav > a:nth-of-type(1–4)"])
    assert ver.selector_named(sel, [".nav > a"])
    assert not ver.selector_named(sel, ["a"])
    assert not ver.selector_named(sel, ["footer nav.nav > a"])
