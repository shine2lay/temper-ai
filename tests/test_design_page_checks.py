"""Model-free tests for Design's page checks and the critic candidate that reads them (queue #39).

configs/design/bin/design_page_checks.js measures a page in the shared browser; design_page_checks.py
judges the raw facts against the frozen thresholds and writes what a critic reads in facts.md.
No browser here: tests/design_page_checks_scenes/*.raw.json were recorded from planted.html (one
problem per check) and control.html (none) next to them, with the real shared browser
(~/design-lab/tools/page_checks_record_scenes.py). The critic-v2 bench (testpages/quarry-v1) keeps its
answer key on the host, so nothing on the box may hint at which page carries which problem.
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
SCENES = Path(__file__).resolve().parent / "design_page_checks_scenes"
SITE = DESIGN / "testpages/quarry-v1"
sys.path.insert(0, str(BIN))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, BIN / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pc = _load("design_page_checks")
T = pc.thresholds()
CHECKS = ("repeated-copy", "first-screen-action", "nav-fit", "empty-column", "signifier", "text-over-image",
          "dark-small-text")


def raw(name):
    return json.loads((SCENES / f"{name}.raw.json").read_text())


def judged(name):
    """{check: [(view, line)]} for problems and for passes over every recorded view."""
    views = raw(name)
    problems, passes = {}, {}
    for vp, r in views.items():
        p, o = pc.judge(vp, r, T, r.get("pixels"))
        for check, line in p:
            problems.setdefault(check, []).append((vp, line))
        for check, line in o:
            passes.setdefault(check, []).append((vp, line))
    p, o = pc.copy_problems(views["desktop"], T)
    for check, line in p:
        problems.setdefault(check, []).append(("desktop", line))
    for check, line in o:
        passes.setdefault(check, []).append(("desktop", line))
    return problems, passes


# --------------------------------------------------------------------------- thresholds


def test_thresholds_were_frozen_before_the_candidate_runs():
    assert T["status"] == "frozen" and T["frozen"].startswith("2026-10-05T17:15")
    assert T["first_screen_action"] == {"viewport": "mobile", "screen_height": 844}
    assert T["nav_fit"] == {"viewport": "mobile", "max_lines": 1}
    assert T["empty_column"]["min_share"] == 0.3 and T["empty_column"]["min_height"] == 300
    assert T["dark_small_text"]["max_px"] == 14
    assert T["text_over_image"] == {"cell": 8, "normal": 4.5, "large": 3.0}
    assert T["visuals"]["icon_max"] == 48
    assert T["repeated_copy"]["min_words"] == 5 and T["repeated_copy"]["min_sections"] == 3


def test_browser_code_takes_the_thresholds_and_measures_every_check():
    src = pc.source(T, "Borrow a tool", copy=True, columns=True, visuals=True)
    assert "__OPTS__" not in src and '"Borrow a tool"' in src
    for key in ("copy", "action", "nav", "columns", "cues", "overlays", "small_dark", "visuals", "dark"):
        assert f"out.{key}" in src or f"{key}:" in src, key
    js = (BIN / "design_page_checks.js").read_text()
    assert "prefers-color-scheme" in js and "getComputedStyle" in js
    code = pc.pixel_code([{"id": 0, "rect": [0, 0, 10, 10]}], T)
    assert "__ARGS__" not in code and '"cell": 8' in code


# --------------------------------------------------------------------------- the recorded pages


def test_planted_page_fails_every_check_and_the_control_none():
    problems, _ = judged("planted")
    assert set(problems) == set(CHECKS)
    problems, passes = judged("control")
    assert problems == {}
    assert set(passes) == set(CHECKS) - {"dark-small-text"}  # no small dark text: nothing to pass


def test_problems_name_their_check_view_element_and_measure():
    problems, _ = judged("planted")
    for check, found in problems.items():
        for _vp, line in found:
            assert line.endswith(f"(page check: {check})"), line
    assert [vp for vp, _ in problems["nav-fit"]] == ["mobile"]
    assert "3 lines" in problems["nav-fit"][0][1]
    action = problems["first-screen-action"][0][1]
    assert '"Borrow a tool"' in action and "below the first screen (390x844" in action
    assert [vp for vp, _ in problems["empty-column"]] == ["desktop"]
    assert "Questions" in problems["empty-column"][0][1]
    assert "4 of 6 interactive elements show no visible cue" in problems["signifier"][0][1]
    assert {vp for vp, _ in problems["text-over-image"]} == {"desktop", "mobile", "desktop-dark"}
    assert all("measured from the screenshot" in line for _, line in problems["text-over-image"])
    assert [vp for vp, _ in problems["dark-small-text"]] == ["desktop-dark"]
    assert "under 14 px in the dark colour scheme" in problems["dark-small-text"][0][1]
    assert '"drills ladders and garden shears for the whole street" in Hero, How it works, Join' in (
        problems["repeated-copy"][0][1])


def test_text_over_a_picture_is_judged_on_its_pixels_not_its_declared_colours():
    views = raw("planted")
    lede = next(c for c in views["desktop"]["overlays"] if "lede" in c["sel"])
    px = views["desktop"]["pixels"][str(lede["id"])]
    assert px["ratio"] < lede["needs"]  # white text over the light end of the gradient
    flipped = json.loads(json.dumps(views["desktop"]))
    flipped["pixels"][str(lede["id"])] = {"bg": "rgb(20,30,30)", "ratio": 12.0}
    problems, passes = pc.judge("desktop", flipped, T, flipped["pixels"])
    assert "text-over-image" not in [c for c, _ in problems]
    assert "text-over-image" in [c for c, _ in passes]
    unmeasured = dict(flipped, pixels={})
    problems, passes = pc.judge("desktop", unmeasured, T, {})
    assert "text-over-image" not in [c for c, _ in problems + passes]  # not measured is not a pass


def test_pictures_by_section_are_facts_not_verdicts():
    lines = pc.info_lines(raw("planted"), True, True)
    text = "\n".join(lines)
    assert "- Hero: 1 picture(s), 30% of the section: svg 504x360 \"A pegboard of hand tools\"" in text
    assert "First screen covered by pictures: desktop 18%, mobile 66%" in text
    assert "Sections with no picture: Tools on the shelves, Questions, Join" in text
    assert "icons under 48 px left out" in text and "(page chrome)" in text
    assert "captured as view desktop-dark" in text
    control = "\n".join(pc.info_lines(raw("control"), True, True))
    assert "First screen covered by pictures: desktop 19%, mobile 27%" in control
    assert "border 3, fill 2, underline 1" in control
    for line in lines:
        assert "page check:" not in line  # never a pass or a failure


def test_repeated_copy_counts_prose_runs_across_sections_only():
    long = "the caddy is picked up from your doorstep every tuesday morning"
    copy = [{"name": "Hero", "blocks": ["Fresh soil.", f"{long}."]},
            {"name": "How it works", "blocks": [f"Each week {long} and swapped."]},
            {"name": "Start", "blocks": [f"Book now: {long}."]},
            {"name": "Questions", "blocks": ["Does it smell? No, the lid seals."]}]
    found = pc.repeated_copy(copy, T)
    assert found and found[0]["sections"] == ["Hero", "How it works", "Start"]
    assert pc.repeated_copy(copy[:1] + copy[3:], T) == []
    short = [{"name": n, "blocks": ["Book a pickup today"]} for n in ("A", "B", "C")]
    assert pc.repeated_copy(short, T) == []  # under five words is a label, not padding


def test_brief_lines_feed_the_action_and_the_context():
    brief = "Loamy is a made-up thing.\nPrimary action: **Book a pickup**\nDesign context: rollcall-trader-workspace\n"
    assert pc.primary_action(brief) == "Book a pickup"
    assert pc.design_context(brief) == "rollcall-trader-workspace"
    assert pc.primary_action("No action named here.") == "" and pc.design_context("") == ""


def test_context_file_lists_the_avoid_items_and_never_rules_pictures_by_audience():
    text = pc.context_md("rollcall-trader-workspace")
    assert "gamified rewards (confetti, badges, streaks)" in text and "(E127, E128)" in text
    assert "attention lists like 'top movers' as the main entry point" in text
    assert "fees and costs visible before any action" in text
    assert 'check "context"' in text
    assert "not set by this context (not by audience or page type): the section's purpose decides" in text
    unknown = pc.context_md("no-such-context")
    assert "not in the playbook" in unknown and "not_checked" in unknown


# --------------------------------------------------------------------------- the critics that read them
# (graded as _next candidates beside live, then promoted to the live names: design_review v4 and
# craft critic v2, queue #39)

# Product and site names of every test page set and fixture: a prompt naming one would hint.
# (Unpublished benchmark briefs are checked on the host, not named here: this repo is public.)
TEST_NAMES = {"quarry", "loamwise", "ledgerline", "tidewell", "morrow", "fernway", "claybird", "signalbox",
              "craft-v1", "critic-v2"}
CRITICS = ["design_critic", "design_merge", "design_homepage_craft_critic_v2"]


def _prompt(name):
    return yaml.safe_load((DESIGN / "agents" / f"{name}.yaml").read_text())["agent"]["system_prompt"]


def _flat(text):
    return " ".join(text.split())


@pytest.mark.parametrize("name", CRITICS)
def test_critic_prompts_name_no_test_site(name):
    text = (DESIGN / "agents" / f"{name}.yaml").read_text().lower()
    names = set(TEST_NAMES)
    for manifest in (DESIGN / "testpages").glob("*.json"):
        data = json.loads(manifest.read_text())
        names |= {manifest.stem.split("-")[0], *(p.lower() for p in data.get("products") or {})}
    assert not [n for n in names if n in text and n != "craft"], name


def test_critic_carries_every_research_and_page_check_with_its_evidence():
    critic = _flat(_prompt("design_critic"))
    for check in ("signifier", "text-over-image", "dark-small-text", "repeated-copy", "first-screen-action",
                  "nav-fit", "typicality", "context"):
        assert f'"{check}"' in critic, check
    for eid in ("E055", "E056", "E067", "E068", "E100", "E002", "E025", "E167", "E061"):
        assert eid in critic, eid
    assert "review/context.md" in critic and '"conventions"' in critic and '"breaks"' in critic
    assert "WORKED EXAMPLE FINDINGS (other, made-up products" in critic
    assert critic.count('"check": "') >= 4  # four worked examples, each with element, place and evidence


def test_critic_and_merge_keep_one_rule_text_with_rule_e():
    def block(p):
        return p[p.index("\nSEVERITY RULES."):p.index("rules above say when it is.")]

    critic, merge = _prompt("design_critic"), _prompt("design_merge")
    assert block(critic) == block(merge)
    rules = _flat(block(critic))
    assert "E. The research and page checks" in rules
    assert "game-like rewards for trading or spending" in rules
    for live_anchor in ("A. How far below the threshold", "B. The main navigation and the page's main task",
                        "C. How many pages", "D. A target that meets 2.5.8"):
        assert live_anchor in rules


def test_merge_keeps_checked_research_findings_and_rejects_pictures_by_audience():
    merge = _flat(_prompt("design_merge"))
    assert '"check": "", "evidence_ids": []' in merge
    assert "is a problem, not taste: judge it on its evidence" in merge
    assert "A finding that asks for or against pictures only because of the audience or page type is rejected" in merge


def test_craft_critic_anchors_severity_and_judges_pictures_by_section_purpose():
    craft = _flat(_prompt("design_homepage_craft_critic_v2"))
    assert "spacing share on a 4 px grid below 0.6" in craft and "From 0.6 to below 0.9: 2" in craft
    assert "an empty column measured by facts.md (empty-column): 2 (space)" in craft
    assert "VISUAL PURPOSE" in craft and '"visual_purpose"' in craft
    assert "Never by audience or page type" in craft
    for purpose in ("explain how it works", "show the product or the result", "prove a claim",
                    "guide to the key action", "set the mood", "make data visible"):
        assert purpose in craft, purpose
    # Styled type is words, so a typographic page can't pass as an illustrated one.
    assert "What counts as showing: a picture" in craft
    assert "a section whose only visual is styled type is words only" in craft
    assert "look up or compare exact values" in craft
    assert craft.count('"check": "visual-purpose"') >= 2


def test_live_workflows_run_the_page_checks_and_leave_no_candidate_copy():
    review = yaml.safe_load((DESIGN / "workflows/design_review.yaml").read_text())["workflow"]
    assert WorkflowConfig.from_dict(review).name == "design_review"
    agents = {n["name"]: n["agent"] for n in review["nodes"]}
    assert agents["capture"] == "design_capture" and agents["merge"] == "design_merge"
    assert agents["critic_a"] == agents["critic_b"] == "design_critic"
    capture = yaml.safe_load((DESIGN / "agents/design_capture.yaml").read_text())["agent"]
    assert '"--page-checks"' in capture["script_template"]
    bench = yaml.safe_load((DESIGN / "workflows/design_craft_bench.yaml").read_text())["workflow"]
    assert WorkflowConfig.from_dict(bench).name == "design_craft_bench"
    nodes = {n["name"]: n["agent"] for n in bench["nodes"]}
    assert nodes == {"prepare": "design_craft_bench_stage", "craft": "design_homepage_craft_critic_v2",
                     "collect": "design_craft_bench_stage"}
    stage = (DESIGN / "agents/design_craft_bench_stage.yaml").read_text()
    assert '"--page-checks"' in stage
    leftovers = sorted(p.name for p in DESIGN.rglob("*_next.yaml")
                       if re.match(r"design_(review|capture|critic|merge|homepage_craft_critic|craft_bench)", p.name))
    assert leftovers == []


def test_live_homepage_rounds_give_the_critics_the_page_checks():
    """A design_homepage_v2 review round captures with the page checks and its primary action."""
    source = (DESIGN / "bin/design_homepage_v2.py").read_text()
    call = source[source.index("metrics = write_review_inputs("):]
    assert "page_checks=True" in call[:call.index(")\n")]


# --------------------------------------------------------------------------- the critic-v2 bench pages

MANIFEST = json.loads((DESIGN / "testpages/quarry-v1.json").read_text())
HINTS = re.compile(r"plant(?!er)|flaw|control|clean|wrong|answer|bench|craft|competing|misalign|off-grid|"
                   r"low-contrast|too many|<!--|signifier|typical|words.only|empty.col|dead.col|first.screen|"
                   r"nav.fit|small.text|no.cue|no job|gamif|streak.badge", re.I)


def test_bench_has_fourteen_contract_pages_for_two_fictional_products():
    v2 = _load("design_homepage_v2")
    assert MANIFEST["site"] == "quarry-v1" and MANIFEST["key"].startswith("~/design-lab/")
    assert MANIFEST["pages"] == [f"page-{n:02d}" for n in range(1, 15)]
    assert sorted(set(MANIFEST["page_product"].values())) == sorted(MANIFEST["products"]) == ["ledgerline", "loamwise"]
    for name, product in MANIFEST["products"].items():
        assert product["brief"]["fictional"] is True and product["brief"]["disclosure"], name
        assert {"product", "audience", "purpose", "cta"} <= set(product["brief"]), name
    for page in MANIFEST["pages"]:
        html = SITE / page / "index.html"
        assert v2.html_problems(html) == [], page
        assert 'href="/fonts/fonts.css"' in html.read_text(), page  # the site root is served, as for a review
    assert sorted(p.name for p in SITE.iterdir() if p.is_dir() and p.name != "fonts") == MANIFEST["pages"]
    fonts = (SITE / MANIFEST["fonts_css"]).read_text()
    for name in MANIFEST["font_dirs"]:
        assert any((SITE / "fonts" / name).glob("*.ttf")) and f'url("{name}/' in fonts, name


def test_nothing_on_the_bench_hints_at_which_page_carries_what():
    texts = {str(p.relative_to(SITE)): p.read_text() for p in SITE.rglob("*") if p.is_file() and p.suffix in (".html", ".css")}
    texts["what the manifest says per page"] = json.dumps([MANIFEST[k] for k in ("pages", "page_product", "products")])
    for name, text in texts.items():
        found = HINTS.search(text)
        assert not found, (name, found and found.group(0))
    assert not list(ROOT.rglob("quarry-v1.yaml"))  # the answer key lives in ~/design-lab/answers only
