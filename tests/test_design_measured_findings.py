"""design_measured_findings.py (H5, W4b): measured problems become findings by coded rules.

- Each rule on small made-up inputs, with its boundary values (4.49 and 4.5:1, 2.99 and 3:1,
  1.99 and 2:1, 1.2 and 1.5 screens, 23 and 24 px, the 844 px first phone screen).
- The rules table quotes the critic, merge and craft prompts word for word at the lines it cites.
- The keyed sites quarry-v1, morrow-v2 and fernway-v1, from public-safe copies of stored review
  folders (tests/fixtures/design_measured_findings): plants of a type this script measures are
  found at the key's level or within its range (H5 is wrong if more than 10% disagree); quarry's
  clean controls get no measured finding; every measured problem design_capture lists becomes a
  finding; two runs give byte-identical files.

The answer keys stay on the host (~/design-lab/answers, or DESIGN_ANSWERS); without them the
keyed tests skip. Nothing here names a plant, its page or its level.
"""

import collections
import importlib.util
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
BIN = ROOT / "configs" / "design" / "bin"
FIX = ROOT / "tests" / "fixtures" / "design_measured_findings"
ANSWERS = pathlib.Path(os.environ.get("DESIGN_ANSWERS", pathlib.Path.home() / "design-lab" / "answers"))
SITES = ("quarry-v1", "morrow-v2", "fernway-v1")
sys.path.insert(0, str(BIN))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, BIN / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mf = _load("design_measured_findings")


# ---------------------------------------------------------------- made-up review folders


def _review(folder, views, primary=""):
    """A review folder: views maps (page, viewport) to that view's facts."""
    folder = pathlib.Path(folder)
    (folder / "facts").mkdir(parents=True, exist_ok=True)
    pages = {}
    for (page, vp), facts in views.items():
        pages.setdefault(page, []).append((vp, facts))
    cap = {"pages": [], "page_checks": {"primary_action": primary},
           "viewports": {"desktop": [1280, 800], "mobile": [390, 844]}}
    for page, vps in pages.items():
        name = re.sub(r"[^a-z0-9]+", "-", page.replace(".html", "")).strip("-")
        entry = {"page": page, "name": name, "views": []}
        for vp, facts in vps:
            facts = {"viewport": [390, 844] if vp == "mobile" else [1280, 800], **facts}
            rel = f"facts/{name}-{vp}.json"
            (folder / rel).write_text(json.dumps(facts))
            entry["views"].append({"viewport": vp, "facts": rel})
        cap["pages"].append(entry)
    (folder / "capture.json").write_text(json.dumps(cap))
    return folder


def _findings(folder, facts, vp="desktop", primary="", page="index.html"):
    return mf.measured_findings(_review(folder, {(page, vp): facts}, primary))["findings"]


def _text(contrast, needs=4.5, **kw):
    t = {"sel": "main > section.plans > p", "tag": "p", "text": "Pick a plan to start your weekly pickup",
         "size": 24 if needs == 3 else 16, "weight": 400, "color": "rgb(150,150,150)",
         "background": "rgb(255,255,255)", "contrast": contrast, "needs": needs, "inactive": False}
    return {**t, **kw}


def _ring(sel, name):
    return {"sel": sel, "name": name, "ring": False, "outline": "none", "box_shadow": "none", "box": [0, 0, 90, 40]}


def _field(sel, name_from, type_="text"):
    return {"sel": sel, "type": type_, "name": "you@company.com", "name_from": name_from}


@pytest.fixture
def fired(monkeypatch):
    """Page checks that fire, set by the test (design_page_checks has its own tests)."""
    state = {"judge": [], "copy": []}
    monkeypatch.setattr(mf.pc, "judge", lambda vp, raw, t, pixels=None: ([(c, "") for c in state["judge"]], []))
    monkeypatch.setattr(mf.pc, "copy_problems",
                        lambda raw, t: ([("repeated-copy", "")] if state["copy"] else [], []))
    monkeypatch.setattr(mf.pc, "repeated_copy", lambda copy, t: state["copy"])
    return state


def _levels(found):
    return [(f["check"], f["severity"], f["grade"]) for f in found]


# ---------------------------------------------------------------- rule A


@pytest.mark.parametrize("contrast,needs,level", [
    (4.49, 4.5, 2), (4.5, 4.5, None), (3.0, 4.5, 2), (2.99, 4.5, 3),  # normal text
    (3.0, 3, None), (2.99, 3, 2), (2.0, 3, 2), (1.99, 3, 3),  # large text
])
def test_text_contrast_levels(tmp_path, contrast, needs, level):
    found = _findings(tmp_path, {"contrast_failures": [_text(contrast, needs)]})
    if level is None:
        assert found == []
        return
    assert _levels(found) == [("text-contrast", level, "Must")]  # a measured WCAG AA failure is Must
    f = found[0]
    assert f["rule"] == "A-text-contrast" and f["criterion"] == "WCAG 1.4.3"
    assert f["evidence"]["contrast"] == contrast and f["evidence"]["needs"] == needs


@pytest.mark.parametrize("change,level", [
    ({}, 3), ({"sel": "footer.site > div.wrap > p"}, 2), ({"tag": "small"}, 2), ({"size": 12}, 2),
    ({"size": 13}, 3), ({"text": "\u00a9 2026 Loamwise. All rights reserved."}, 2),
    ({"text": "Photos by Ana Ruiz"}, 2), ({"text": "We never sell your data: your privacy comes first"}, 3),
])
def test_text_contrast_under_3_is_2_on_incidental_text(tmp_path, change, level):
    found = _findings(tmp_path, {"contrast_failures": [_text(2.5, **change)]})
    assert [f["severity"] for f in found] == [level]
    assert ("note" in found[0]) == (level == 2)


def test_disabled_text_is_exempt(tmp_path):
    assert _findings(tmp_path, {"contrast_failures": [_text(1.5, inactive=True)]}) == []


@pytest.mark.parametrize("ratio,level", [(3.0, None), (2.99, 2), (2.0, 2), (1.99, 3), (1.24, 3)])
def test_non_text_contrast_levels(tmp_path, ratio, level):
    facts = {"weak_boundaries": [{"sel": "div.billing > button", "name": "Yearly billing", "boundary_contrast": ratio}]}
    found = _findings(tmp_path, facts)
    assert _levels(found) == ([] if level is None else [("non-text-contrast", level, "Must")])


@pytest.mark.parametrize("scroll,level", [(390, None), (468, 2), (584, 2), (585, 3), (1064, 3)])
def test_reflow_levels(tmp_path, scroll, level):
    """Up to a fifth wider is 2, one and a half screens or more is 3, and in between the lower."""
    facts = {"page_width": {"scroll": scroll, "viewport": 390, "overflows": scroll > 390},
             "overflowing": [{"sel": "div.steps", "box": [16, 900, scroll - 16, 300]}] if scroll > 390 else []}
    found = _findings(tmp_path, facts, vp="mobile")
    assert _levels(found) == ([] if level is None else [("reflow", level, "Must")])
    if found:
        assert found[0]["element"] == "div.steps" and found[0]["evidence"]["ratio"] == round(scroll / 390, 2)


def test_target_size_follows_the_measured_lists_at_23_and_24_px(tmp_path):
    """design_measure.js decides 2.5.8 (24x24 px on the unrounded size, and the spacing
    exception): a listed 23 px failure is 2; a 24 px control and a listed pass are no finding."""
    facts = {
        "small_targets": [{"sel": "div.date-stepper > button:nth-of-type(1)", "name": "Previous day",
                           "box": [430, 287, 23, 23], "hit": "target",
                           "too_close_to": {"sel": "div.date-stepper > button:nth-of-type(2)", "name": "Next day",
                                            "edge": 10, "centre": 23}}],
        "controls": [{"sel": "div.date-stepper > button:nth-of-type(2)", "tag": "button", "role": "button",
                      "name": "Next day", "name_from": "aria", "box": [453, 287, 24, 24]}],
        "targets_pass": [{"sel": "a.week-next", "name": "Next week", "box": [900, 120, 16, 16],
                          "passes": "spacing", "nearest": {"edge": 30.4}}],
    }
    found = _findings(tmp_path, facts)
    assert _levels(found) == [("target-size", 2, "Must")]
    assert found[0]["evidence"]["size"] == [23, 23] and found[0]["evidence"]["too_close_to"]["edge"] == 10


@pytest.mark.parametrize("fields,levels", [
    ([_field("#guest-email", "placeholder only", "email"), _field("#meeting-date", "label", "date")], [2]),
    ([_field("#first", "placeholder only"), _field("#last", "placeholder only")], [3, 3]),
    ([_field("#q", "placeholder only", "search")], [2]),  # a lone field is not a main form
    ([_field("#a", "none"), _field("#b", "title"), _field("#c", "aria")], [3, 3]),
    ([_field("#agree", "none", "checkbox"), _field("#email", "label", "email")], [2]),
    ([_field("#a", "label"), _field("#b", "aria")], []),
])
def test_label_levels(tmp_path, fields, levels):
    found = _findings(tmp_path, {"fields": fields})
    assert [f["severity"] for f in found] == levels
    assert all(f["check"] == "labels" and f["grade"] == "Must" for f in found)


def test_text_alternative_levels(tmp_path):
    facts = {"unnamed_graphics": [
        {"sel": "tbody > tr:nth-of-type(1) > td.c:nth-of-type(1) > svg", "tag": "svg", "src": "", "box": [0, 0, 16, 16]},
        {"sel": "#customers > div.wrap > img:nth-of-type(1)", "tag": "img", "src": "logo-acme.svg", "box": [0, 0, 120, 40]},
    ]}
    found = {f["element"].split(" > ")[0]: f for f in _findings(tmp_path, facts)}
    assert (found["tbody"]["severity"], "note" in found["tbody"]) == (3, False)
    assert (found["#customers"]["severity"], "note" in found["#customers"]) == (2, True)


# ---------------------------------------------------------------- rule B


def test_focus_levels(tmp_path):
    facts = {"no_focus_ring": [
        _ring("header.site > div.wrap > nav.nav > a:nth-of-type(1)", "Product"),
        _ring("footer.site > nav.links > a:nth-of-type(1)", "Privacy"),
        _ring("#choose-cedar", "Choose Cedar"),
        _ring("main > section.hero > a.button", "Book a pickup \u2192"),
    ]}
    found = {f["evidence"]["name"]: f for f in _findings(tmp_path / "a", facts, primary="Book a pickup")}
    assert {n: f["severity"] for n, f in found.items()} == {"Product": 3, "Privacy": 2, "Choose Cedar": 2,
                                                          "Book a pickup \u2192": 3}
    assert '"Book a pickup"' in found["Choose Cedar"]["note"]
    assert not any("ask" in f for f in found.values())  # the brief names the primary action: nothing to ask
    bare = {f["evidence"]["name"]: f for f in _findings(tmp_path / "b", facts)}
    assert bare["Book a pickup \u2192"]["severity"] == 2 and "names none" in bare["Book a pickup \u2192"]["note"]
    # W4e (H5): the brief names none, so the merge answers a fenced yes/no and a script applies the level
    assert {n: f.get("ask", {}).get("if_yes") for n, f in bare.items()} == {
        "Product": None, "Privacy": 3, "Choose Cedar": 3, "Book a pickup \u2192": 3}
    assert bare["Choose Cedar"]["ask"] == {"question": 'Is "Choose Cedar" (#choose-cedar) the page\'s primary action?',
                                         "answers": ["yes", "no"], "if_yes": 3}


def test_focus_in_the_navigation_the_page_checks_found(tmp_path, fired):
    """A link's selector keeps its nav's own part even when the header above it is cut off."""
    facts = {"no_focus_ring": [_ring("header.bar > div.wrap > ul.menu > li:nth-of-type(2) > a", "Team"),
                               _ring("ul.menu > li:nth-of-type(3) > span > a", "Reports"),
                               _ring("footer.site > ul.menu > li:nth-of-type(1) > a", "Help"),
                               _ring("main > nav.tabs > a:nth-of-type(2)", "Week")],
             "page_checks": {"nav": {"found": True, "sel": "header.bar > div.wrap > ul.menu"}}}
    found = {f["evidence"]["name"]: f["severity"] for f in _findings(tmp_path, facts)}
    assert found == {"Team": 3, "Reports": 3, "Help": 2, "Week": 2}


# ---------------------------------------------------------------- rule C, long lines, axe


def test_rule_c_raises_a_problem_on_most_pages(tmp_path):
    ring = {"no_focus_ring": [_ring("main > a.more", "Learn more")]}
    views = {(f"p{i}.html", "desktop"): ring for i in range(3)}
    views[("p3.html", "desktop")] = {}
    found = mf.measured_findings(_review(tmp_path / "most", views))["findings"]
    assert [(f["severity"], f["raised"]) for f in found] == [(3, "C-pages: measured on 3 of 4 reviewed pages")] * 3
    assert not any("ask" in f for f in found)  # raised to 3 already: a yes would change nothing
    two = mf.measured_findings(_review(tmp_path / "two", {k: v for k, v in list(views.items())[1:]}))["findings"]
    assert [f["severity"] for f in two] == [2, 2]  # one or two pages: no change
    assert [f["ask"]["if_yes"] for f in two] == [3, 3]
    half = {**views, **{(f"q{i}.html", "desktop"): {} for i in range(2)}}
    assert {f["severity"] for f in mf.measured_findings(_review(tmp_path / "half", half))["findings"]} == {2}  # 3 of 6 is not most


def test_rule_c_needs_the_same_problem(tmp_path, fired, monkeypatch):
    """Repeated copy on three of four pages, each with its own phrase, is three problems: no raise."""
    phrases = iter([[{"phrase": f"phrase number {i} again here", "sections": ["Hero", "FAQ"]}] for i in range(3)])
    fired["copy"] = True
    monkeypatch.setattr(mf.pc, "repeated_copy", lambda copy, t: next(phrases))
    views = {(f"p{i}.html", "desktop"): {"page_checks": {"copy": []}} for i in range(3)}
    views[("p3.html", "desktop")] = {}
    found = mf.measured_findings(_review(tmp_path, views))["findings"]
    assert [(f["check"], f["severity"], "raised" in f) for f in found] == [("repeated-copy", 1, False)] * 3


def test_long_lines_are_cosmetic(tmp_path):
    facts = {"long_lines": [{"sel": "section.why > div.wrap > p", "text": "Fernway " * 30, "chars_per_line": 104,
                             "lines": 3, "width": 1040}]}
    assert _levels(_findings(tmp_path, facts)) == [("long-lines", 1, "Could")]


def test_axe_rules_a_direct_measure_covers_are_not_counted_twice(tmp_path):
    contrast = {"id": "color-contrast", "impact": "serious", "help": "Elements must meet minimum color contrast",
                "wcag": ["wcag2aa", "wcag143"], "nodes": [{"target": ".intro-note", "summary": ""}]}
    name = {"id": "button-name", "impact": "critical", "help": "Buttons must have discernible text",
            "wcag": ["wcag2a", "wcag412"], "nodes": [{"target": ["button.menu"], "summary": ""}]}
    region = {"id": "region", "impact": "moderate", "help": "All page content should be contained by landmarks",
              "wcag": [], "nodes": [{"target": "div.promo", "summary": ""}]}
    found = _findings(tmp_path / "a", {"axe": [contrast, name, region], "contrast_failures": [_text(4.23)]})
    assert [(f["check"], f["severity"], f["grade"], f["criterion"]) for f in found] == [
        ("text-contrast", 2, "Must", "WCAG 1.4.3"), ("axe:button-name", 2, "Must", "WCAG 4.1.2"),
        ("axe:region", 2, "Should", "axe region")]
    alone = _findings(tmp_path / "b", {"axe": [contrast]})  # no direct measure listed: axe's own finding
    assert [(f["check"], f["element"]) for f in alone] == [("axe:color-contrast", ".intro-note")]


# ---------------------------------------------------------------- page checks (rule E, craft)


@pytest.mark.parametrize("overflow,grade", [([], "Should"), (["Book a pickup"], "Must")])
def test_nav_fit_is_2(tmp_path, fired, overflow, grade):
    """Links pushed past the screen edge are a broken layout at a required width: Must."""
    fired["judge"] = ["nav-fit"]
    raw = {"nav": {"found": True, "sel": "header > div.wrap > nav.site-nav", "lines": 2,
                   "rows": [["Home", "How it works"], ["Book a pickup"]], "wrapped": ["Book a pickup"],
                   "overflow": overflow, "header_height": 120}}
    found = _findings(tmp_path, {"page_checks": raw}, vp="mobile")
    assert _levels(found) == [("nav-fit", 2, grade)] and found[0]["element"] == "header > div.wrap > nav.site-nav"


@pytest.mark.parametrize("heading_top,level", [(200, 2), (843, 2), (844, 3), (None, 3)])
def test_first_screen_action_levels(tmp_path, fired, heading_top, level):
    fired["judge"] = ["first-screen-action"]
    raw = {"action": {"label": "Book a pickup", "first": {"top": 1210, "bottom": 1258, "sel": "a.btn",
                                                          "text": "Book a pickup", "section": "Hero"}}}
    heads = [] if heading_top is None else [{"level": 1, "text": "Compost pickup, weekly", "size": 40, "weight": 700,
                                             "box": [16, heading_top, 358, 96]}]
    found = _findings(tmp_path, {"page_checks": raw, "headings": heads}, vp="mobile")
    assert _levels(found) == [("first-screen-action", level, "Must")]  # content past a required first screen
    assert found[0]["evidence"]["top"] == 1210


@pytest.mark.parametrize("top,beside,level", [
    (3014, "What can go in?", 2), (799, "What can go in?", 3), (800, "What can go in?", 2), (3014, "Book a pickup", 3),
])
def test_empty_column_is_a_craft_candidate_never_a_measured_finding(tmp_path, fired, top, beside, level):
    """W4e (H5, home's decision): the page check fires on purposeful layouts too (the W4b screen's three false
    alarms), so an empty column goes to the craft critic as a fenced yes/no, at the craft rule's fixed level."""
    fired["judge"] = ["empty-column"]
    raw = {"columns": [{"width": 477, "share": 0.43, "side": "left", "height": 560, "beside": beside,
                        "section": "Questions", "top": top}], "frame": [80, 1200]}
    review = _review(tmp_path, {("index.html", "desktop"): {"page_checks": raw}}, "Book a pickup")
    assert mf.measured_findings(review)["findings"] == []
    cands = mf.craft_candidates(review)
    assert [(c["check"], c["severity"], c["if_yes"], c["answers"]) for c in cands] == [
        ("empty-column", level, level, ["yes", "no"])]
    assert cands[0]["evidence"]["content_width"] == 1120 and cands[0]["question"] == mf.CANDIDATE_QUESTION
    assert "dead space" in mf.CANDIDATE_QUESTION and "purposeful layout" in mf.CANDIDATE_QUESTION


@pytest.mark.xfail(strict=True, reason="H12 (queue #114): the measured vacancy rule is not built yet")
@pytest.mark.parametrize("answer,reason,evidence", [
    ("yes", "vacant_track", {"track": 1, "track_x": [80, 566], "cover": 0.98}),
    ("no", "in_item", {"item": "div.label", "overlap": 477}),
])
def test_a_measured_vacancy_settles_the_candidate_and_moves_no_measured_finding(tmp_path, fired, answer, reason,
                                                                               evidence):
    """H12: on the candidate path the page check measures whether the run is a vacant slot; that answer settles
    the craft candidate instead of the critic's yes/no, at the craft rule's same fixed level."""
    fired["judge"] = ["empty-column"]
    vacancy = {"answer": answer, "reason": reason, "evidence": evidence,
               "container": {"sel": "section.faq > div.grid", "display": "grid", "tracks": [[80, 566], [630, 1200]],
                             "placed": [0 if answer == "yes" else 1, 1], "items": 2}}
    col = {"width": 477, "share": 0.43, "side": "left", "height": 560, "beside": "What can go in?",
           "section": "Questions", "top": 3014}
    views = {}
    for name, c in (("plain", col), ("measured", {**col, "vacancy": vacancy})):
        raw = {"columns": [c], "frame": [80, 1200]}
        views[name] = _review(tmp_path / name, {("index.html", "desktop"): {"page_checks": raw}}, "Book a pickup")
    assert mf.measured_findings(views["measured"]) == mf.measured_findings(views["plain"])
    (c,) = mf.craft_candidates(views["measured"])
    assert (c["answer"], c["reason"], c["if_yes"], c["vacancy"]) == (answer, reason, 2, vacancy)
    assert "question" not in c and "answers" not in c  # settled by the measure: nothing left to ask
    assert reason in mf.vacancy_text(vacancy) and evidence.get("item", "track 1") in mf.vacancy_text(vacancy)
    (p,) = mf.craft_candidates(views["plain"])  # measured without the vacancy pass: the old question stays
    assert p["answers"] == ["yes", "no"] and "answer" not in p and "vacancy" not in p


@pytest.mark.parametrize("bare,primary,level", [(14, "", 2), (15, "", 3), (1, "Review roll order", 3), (1, "Export", 2)])
def test_signifier_levels(tmp_path, fired, bare, primary, level):
    fired["judge"] = ["signifier"]
    without = [{"sel": "div.table-head > a", "text": "Review roll order", "section": "Roll order"}]
    without += [{"sel": f"td > a:nth-of-type({i})", "text": f"Row {i}", "section": "Positions"} for i in range(1, bare)]
    raw = {"cues": {"checked": 15, "nav_links": 3, "without": without, "without_count": bare, "by_cue": {}}}
    found = _findings(tmp_path, {"page_checks": raw}, primary=primary)
    assert [(f["check"], f["severity"]) for f in found] == [("signifier", level)]
    # W4e (H5): a 2 that the primary action would raise asks the merge, only when the brief names none
    assert ("ask" in found[0]) == (level == 2 and not primary)
    if "ask" in found[0]:
        assert found[0]["ask"]["if_yes"] == 3 and "evidence.elements" in found[0]["ask"]["question"]


@pytest.mark.parametrize("ratio,needs,level", [(4.5, 4.5, None), (4.49, 4.5, 2), (3.0, 4.5, 2), (2.99, 4.5, 3),
                                               (2.75, 3, 2), (1.99, 3, 3)])
def test_text_over_image_takes_rule_a_on_the_pixels(tmp_path, fired, ratio, needs, level):
    fired["judge"] = ["text-over-image"]
    raw = {"overlays": [{"id": 0, "sel": "div.hero-text > p.lede", "text": "Your scraps, picked up weekly",
                         "size": 24 if needs == 3 else 18, "weight": 400, "needs": needs, "declared": 5.6,
                         "kind": "image", "section": "Hero"}],
           "pixels": {"0": {"ratio": ratio, "bg": "rgb(120,140,90)"}}}
    found = _findings(tmp_path, {"page_checks": raw})
    assert _levels(found) == ([] if level is None else [("text-over-image", level, "Must")])


def test_dark_small_text_is_one_finding_of_2(tmp_path, fired):
    fired["judge"] = ["dark-small-text"]
    small = [{"sel": f"#how > div.wrap > p:nth-of-type({i})", "size": 13, "words": 24, "color": "rgb(200,200,200)",
              "background": "rgb(20,20,20)"} for i in (1, 2)]
    found = _findings(tmp_path, {"page_checks": {"small_dark": small}}, vp="desktop-dark")
    assert _levels(found) == [("dark-small-text", 2, "Should")] and found[0]["evidence"]["blocks"] == 2


@pytest.mark.parametrize("phrases,level", [
    ([{"phrase": "weekly pickup right at your door", "sections": ["Hero", "How it works"]}], 1),
    ([{"phrase": "weekly pickup right at your door", "sections": ["Hero", "How it works", "Pricing"]}], 2),
    ([{"phrase": "weekly pickup right at your door", "sections": ["Hero", "FAQ"]},
      {"phrase": "no bins to wash ever again", "sections": ["Hero", "FAQ"]}], 2),
])
def test_repeated_copy_levels(tmp_path, fired, phrases, level):
    fired["copy"] = phrases
    found = mf.measured_findings(_review(tmp_path, {("index.html", "desktop"): {"page_checks": {"copy": []}},
                                                    ("index.html", "mobile"): {"page_checks": {"copy": []}}}))["findings"]
    assert [(f["check"], f["viewport"], f["severity"]) for f in found] == [("repeated-copy", "desktop", level)]


# ---------------------------------------------------------------- the rules table


def test_rules_quote_the_prompts_at_the_lines_they_cite():
    norm = lambda s: " ".join(s.split())  # noqa: E731
    for rid, rule in mf.RULES.items():
        parts = [norm(p) for p in rule["says"].split(" | ")]
        texts = [norm(" ".join((ROOT / path).read_text(encoding="utf-8").splitlines()[a - 1:b]))
                 for path, a, b in rule["cites"]]
        for p in parts:
            assert any(p in t for t in texts), (rid, p)
        for (path, a, b), t in zip(rule["cites"], texts, strict=True):
            assert any(p in t for p in parts), (rid, path, a, b)
        assert rule["script"]


def test_critic_and_merge_carry_the_same_severity_rules():
    critic = (ROOT / mf.CRITIC).read_text(encoding="utf-8").splitlines()
    merge = (ROOT / mf.MERGE).read_text(encoding="utf-8").splitlines()
    assert critic[146:246] == merge[111:211]  # the A/B rules are cited in both, 35 lines apart


# ---------------------------------------------------------------- keyed sites


def _folders():
    """(site, run, review folder) for every fixture folder."""
    out = []
    for site in SITES:
        base = FIX / site
        runs = sorted(d for d in base.iterdir() if d.is_dir() and (d / "capture.json").is_file())
        out += [(site, d.name, d) for d in runs] if runs else [(site, "", base)]
    return out


def _key(site):
    """An answer key. fernway-v1.yaml holds unquoted values that start with a quoted phrase and go
    on (where: "Why teams switch" paragraphs (desktop)), which YAML refuses; those lines are
    re-quoted whole before loading."""
    text = (ANSWERS / f"{site}.yaml").read_text(encoding="utf-8")
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError:
        pass
    lines = []
    for line in text.splitlines():
        m = re.match(r'^(\s*(?:- )?[A-Za-z_]+): (".*)$', line)
        if m and not re.fullmatch(r'"(?:[^"\\]|\\.)*"\s*(#.*)?', m.group(2)):
            line = f"{m.group(1)}: '" + m.group(2).replace("'", "''") + "'"
        lines.append(line)
    return yaml.safe_load("\n".join(lines))


def _plants(key):
    pl = key.get("plants") or []
    return [dict(p, id=k) for k, p in pl.items()] if isinstance(pl, dict) else [dict(p) for p in pl]


def _wcag(text):
    return set(re.findall(r"\d\.\d\.\d+", text or ""))


def _matches(plant, f):
    """A finding answers a plant: quarry's by check name, the others' by WCAG criterion number,
    or line length; on the plant's viewports where the key names them."""
    if plant.get("viewports") and f["viewport"] not in plant["viewports"]:
        return False
    if plant.get("check"):
        return f["check"] == plant["check"]
    if _wcag(plant.get("criterion")):
        return bool(_wcag(plant["criterion"]) & _wcag(f["criterion"]))
    return "line length" in (plant.get("criterion") or "") and f["check"] == "long-lines"


def _in_scope(plant):
    """Plants of a type this script measures: measured plants on a check it makes (quarry's craft
    spacing plant is measured by the craft metrics, W4c). Since W4e an empty column is a craft
    candidate the craft critic confirms (H5), not a measured finding: its plants are tested below."""
    return plant.get("kind") == "measured" and (not plant.get("check") or (
        plant["check"] in mf.CHECK_ORDER and plant["check"] not in mf.CANDIDATE_CHECKS))


def _agreement():
    results = {(site, run): mf.measured_findings(folder)["findings"] for site, run, folder in _folders()}
    rows, skipped = [], []
    for site in SITES:
        key = _key(site)
        for plant in _plants(key):
            if not _in_scope(plant):
                if plant.get("kind") == "measured":
                    skipped.append((site, plant["id"], plant.get("check")))
                continue
            if site == "quarry-v1":
                page = next(p for p, v in key["pages"].items() if v.get("plant") == plant["id"])
                found = [f for (s, run), fs in results.items() if s == site and run.endswith("-" + page) for f in fs]
            else:
                found = [f for (s, run), fs in results.items() if s == site for f in fs if f["page"] == plant["page"]]
            hits = [f for f in found if _matches(plant, f)]
            level = max((f["severity"] for f in hits), default=None)
            accept = plant.get("accept_severity") or [plant["severity"], plant["severity"]]
            rows.append({"site": site, "plant": plant["id"], "key": plant["severity"], "accept": accept,
                         "level": level, "agree": level is not None and accept[0] <= level <= accept[1],
                         "findings": [f["id"] for f in hits]})
    return rows, skipped


needs_keys = pytest.mark.skipif(not all((ANSWERS / f"{s}.yaml").is_file() for s in SITES),
                                reason="the answer keys live on the host only")


@needs_keys
def test_keyed_sites_find_measured_plants_at_the_keys_level():
    rows, skipped = _agreement()
    print("\nsite        plant  key  accept  script  agree  findings")
    for r in rows:
        print(f"{r['site']:<11} {r['plant']:<6} {r['key']:<4} {str(r['accept']):<7} {str(r['level']):<7} "
              f"{'yes' if r['agree'] else 'NO':<6} {', '.join(r['findings'][:3])}{' ...' if len(r['findings']) > 3 else ''}")
    for site in SITES:
        mine = [r for r in rows if r["site"] == site]
        print(f"{site}: {sum(r['agree'] for r in mine)}/{len(mine)} at the key's level")
    bad = [r for r in rows if not r["agree"]]
    print(f"all: {len(rows) - len(bad)}/{len(rows)} agree, {len(bad)} disagree "
          f"({100 * len(bad) / len(rows):.1f}%; H5 is wrong above 10%)")
    print("measured plants outside this script (other modules):", skipped)
    if os.environ.get("W4B_AGREEMENT"):
        pathlib.Path(os.environ["W4B_AGREEMENT"]).write_text(json.dumps({"rows": rows, "skipped": skipped}, indent=1))
    # 21 rows at W4b; W4e (2026-10-19) took two out: the key fix made one fernway plant judged (the measure
    # lists it as passing WCAG 2.5.8 by the spacing exception), and empty columns went to the craft critic.
    assert len(rows) >= 19
    assert len(bad) <= 0.10 * len(rows)


@needs_keys
def test_keyed_empty_column_plants_wait_for_the_craft_critic_at_the_keys_level():
    """A planted empty column is a craft candidate on the plant's viewports, and a yes from the craft
    critic gives a level inside the key's range."""
    key = _key("quarry-v1")
    plants = [p for p in _plants(key) if p.get("kind") == "measured" and p.get("check") in mf.CANDIDATE_CHECKS]
    assert plants
    for plant in plants:
        folders = [d for site, run, d in _folders() if site == "quarry-v1" and run.endswith("-" + plant["page"])]
        assert folders
        lo, hi = plant.get("accept_severity") or [plant["severity"], plant["severity"]]
        for folder in folders:
            cands = [c for c in mf.craft_candidates(folder) if c["viewport"] in (plant.get("viewports") or [c["viewport"]])]
            assert cands and all(lo <= c["if_yes"] <= hi for c in cands), folder.name


@needs_keys
def test_keyed_measured_plants_are_not_listed_as_passing_by_a_wcag_exception():
    """The key fix (2026-10-19): a plant that design_measure.js lists as passing a WCAG criterion by its
    exception can't be a measured failure of it; such a plant is judged, with a dated note."""
    fixed = [(site, plant) for site in SITES for plant in _plants(_key(site))
             if "spacing exception" in str(plant.get("note") or "")]
    assert fixed  # the key fix is in
    for site, plant in fixed:
        assert plant["kind"] == "judged" and "2.5.8" in plant["note"], (site, plant["id"])
        assert re.search(r"\b2026-\d\d-\d\d\b", plant["note"]), (site, plant["id"])


def _reviewed(product):
    """The viewports a quarry product is reviewed at, from the key's product line."""
    return re.findall(r"desktop-dark|desktop|mobile", product.split("reviewed", 1)[1])


@needs_keys
def test_quarry_clean_controls_get_no_measured_finding():
    key = _key("quarry-v1")
    clean = [p for p, v in key["pages"].items() if not v.get("plant")]
    assert clean
    for page in clean:
        reviewed = _reviewed(key["products"][key["pages"][page]["base"]])
        runs = [(run, folder) for site, run, folder in _folders() if site == "quarry-v1" and run.endswith("-" + page)]
        assert runs
        for run, folder in runs:
            found = mf.measured_findings(folder)["findings"]
            outside = [f["id"] for f in found if f["viewport"] not in reviewed]
            if outside:
                print(f"\n{run}: on viewports the key leaves unreviewed: {outside}")
            assert [f["id"] for f in found if f["viewport"] in reviewed] == [], run


KIND = {"text-contrast": "contrast", "non-text-contrast": "boundary", "reflow": "reflow", "target-size": "target",
        "labels": "field", "text-alt": "graphic", "focus-visible": "focus", "long-lines": "lines"}
PAGE_CHECKS = {"nav-fit", "first-screen-action", "empty-column", "signifier", "text-over-image", "dark-small-text"}


def test_every_measured_problem_design_capture_lists_becomes_a_finding():
    cap = _load("design_capture")
    t = mf.pc.thresholds()
    for site, run, folder in _folders():
        out = mf.measured_findings(folder)["findings"] + mf.craft_candidates(folder)
        capture = json.loads((folder / "capture.json").read_text())
        for p in capture["pages"]:
            for v in p["views"]:
                facts = json.loads((folder / v["facts"]).read_text())
                mine = [f for f in out if f["page"] == p["page"] and f["viewport"] == v["viewport"]]
                listed = collections.Counter(k for k, _ in cap._items(facts))
                listed["axe"] -= sum(1 for a in facts.get("axe") or []
                                     if a["id"] in mf.AXE_COVERED and facts.get(mf.AXE_COVERED[a["id"]]))
                made = collections.Counter("axe" if f["check"].startswith("axe:") else KIND[f["check"]]
                                           for f in mine if f["check"] in KIND or f["check"].startswith("axe:"))
                assert +listed == +made, (site, run, p["page"], v["viewport"])
                raw = facts.get("page_checks")
                if isinstance(raw, dict):
                    checks = {c for c, _ in mf.pc.judge(v["viewport"], raw, t, raw.get("pixels"))[0]}
                    assert checks == {f["check"] for f in mine if f["check"] in PAGE_CHECKS}, (site, run, v["viewport"])
                    copy = v["viewport"] == "desktop" and bool(mf.pc.copy_problems(raw, t)[0])
                    assert copy == any(f["check"] == "repeated-copy" for f in mine)


def test_findings_are_complete_and_graded():
    for site, run, folder in _folders():
        res = mf.measured_findings(folder)
        ids = [f["id"] for f in res["findings"]]
        assert len(ids) == len(set(ids)), (site, run)
        assert res["counts"] == {g: sum(f["grade"] == g for f in res["findings"]) for g in ("Must", "Should", "Could")}
        for f in res["findings"]:
            assert {"id", "page", "viewport", "width", "element", "check", "criterion", "evidence", "rule",
                    "severity", "grade", "kind"} <= set(f)
            assert "level" not in f  # W4e (H5): one field name for the level, the one the critics use
            assert f["rule"] in mf.RULES and 0 <= f["severity"] <= 4 and f["kind"] == "measured"
            assert f["check"] not in mf.CANDIDATE_CHECKS
            assert f["grade"] == ("Must" if f["severity"] >= 3 or f["check"] in mf.HARD_RULE
                                  or f["criterion"].startswith("WCAG") else "Should" if f["severity"] == 2 else "Could")
            if "ask" in f:
                assert not res["primary_action"] and f["severity"] < f["ask"]["if_yes"]
                assert f["check"] in ("focus-visible", "signifier") and f["ask"]["answers"] == ["yes", "no"]


def test_two_runs_are_byte_identical(tmp_path):
    for site, run, folder in _folders():
        outs = []
        for i in (1, 2):
            out = tmp_path / f"{site}-{run or 'site'}-{i}.json"
            subprocess.run([sys.executable, str(BIN / "design_measured_findings.py"), str(folder), "--out", str(out)],
                           check=True, capture_output=True, text=True)
            outs.append(out.read_bytes())
        assert outs[0] == outs[1], (site, run)
        assert outs[0] == mf.dumps(mf.measured_findings(folder)).encode()


def test_cli_writes_review_measured_json_by_default(tmp_path):
    """W4e: outside review/critic/, where the merge and design_review_verify read every file as a critic's run."""
    review = shutil.copytree(FIX / "morrow-v2", tmp_path / "review")
    done = subprocess.run([sys.executable, str(BIN / "design_measured_findings.py"), str(review)],
                          capture_output=True, text=True, check=True)
    out = review / "measured.json"
    assert out.is_file() and str(out) in done.stdout
    assert not (review / "critic" / "measured.json").exists()
    assert json.loads(out.read_text())["findings"] == mf.measured_findings(review)["findings"]
    empty = subprocess.run([sys.executable, str(BIN / "design_measured_findings.py"), str(tmp_path / "none")],
                           capture_output=True, text=True)
    assert empty.returncode == 2 and "no capture.json" in empty.stderr


# ---------------------------------------------------------------- W4e (H5's stage results)


def test_findings_follow_the_viewports_the_review_captures(tmp_path):
    """Only the views the review's own capture.json lists are measured: a facts file left from another
    capture (a phone view the brief doesn't review) gives no finding."""
    ring = {"no_focus_ring": [_ring("main > a.more", "Learn more")]}
    review = _review(tmp_path, {("index.html", "desktop"): ring})
    (review / "facts" / "index-mobile.json").write_text(json.dumps({"viewport": [390, 844], **ring}))
    res = mf.measured_findings(review)
    assert res["viewports"] == {"index": ["desktop"]}
    assert [(f["viewport"], f["check"]) for f in res["findings"]] == [("desktop", "focus-visible")]


def test_keyed_sites_send_their_empty_columns_to_the_craft_critic():
    """The W4b screen's three empty-column false alarms (morrow rooms and settings, fernway signup: all
    purposeful layouts) are no longer measured findings; they wait for the craft critic's yes/no."""
    morrow, fernway = FIX / "morrow-v2", FIX / "fernway-v1"
    for folder in (morrow, fernway, *(d for _, _, d in _folders())):
        assert not [f for f in mf.measured_findings(folder)["findings"] if f["check"] == "empty-column"]
    assert [c["id"] for c in mf.craft_candidates(morrow)] == ["rooms-desktop-empty-column-1",
                                                            "settings-desktop-empty-column-1"]
    assert [c["id"] for c in mf.craft_candidates(fernway)] == ["signup-desktop-empty-column-1"]


def test_morrow_asks_the_merge_about_the_rooms_button_the_brief_does_not_name():
    """morrow-v2's brief names no primary action: the Choose Cedar focus finding stays at 2 and carries the
    merge's fenced question (a yes gives 3)."""
    res = mf.measured_findings(FIX / "morrow-v2")
    asked = {f["id"]: (f["severity"], f["ask"]["if_yes"]) for f in res["findings"] if "ask" in f}
    assert res["primary_action"] == "" and asked == {"rooms-desktop-focus-visible-1": (2, 3),
                                                    "rooms-mobile-focus-visible-1": (2, 3)}
