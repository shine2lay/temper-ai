"""design_app_screen_v1 stage 6a, the measured checks (Design #216): the view plan, every rule on fixed
measures, the step over a stubbed browser, the known-case host and the grader.

The browser is never driven here: the rules take measures in and give rows out, so each rule is tested on a
measure whose right answer is known, and a clean set of measures must give no row at all (the false-positive
test in code). The real browser is proven by the trial runs on temper-dev, recorded in
docs/design-app-screen.md, "Stage 6a: checks".

The product, screens and words are invented test data; the repository is public.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "configs/design/bin"
sys.path.insert(0, str(BIN))

from app_screen import (  # noqa: E402
    checks,
    checks_grade,
    checks_host,
    checks_rules,
    checks_views,
    contracts,
)
from app_screen.workspace import Workspace  # noqa: E402

TH = checks_rules.load_thresholds()
PNG = bytes.fromhex("89504e470d0a1a0a")

INVENTORY = {
    "product": "parcelly-checks",
    "design_files": "defined",
    "screens": [
        {"id": "parcels", "name": "Parcels", "states": ["normal", "empty"], "sources": ["req:R1"],
         "actions": [{"id": "refresh-parcels", "what": "ask the depot again", "states": ["normal"],
                      "sources": ["page:/parcels"]}]},
        {"id": "account", "name": "Account", "states": ["normal"], "sources": ["req:R2"], "actions": []},
    ],
}
REQUIREMENTS = {"product": "parcelly-checks",
                "items": [{"id": "R1", "kind": "feature", "owner_words": "show what is on the way",
                           "source": "req:R1"},
                          {"id": "R2", "kind": "feature", "owner_words": "show the plan", "source": "req:R2"}]}
FIXTURE = {"parcels": [{"id": "PK-1", "worth": 42.5}], "account": {"spend": 167.75, "share": 0.125,
                                                                   "name": "Sam Oduya"}}
# the tokens the cases use, in the DTCG shape design_files reads (part "colour", colours as {hex})
TOKENS = {"colour": {"$type": "color",
                     "primary": {"$value": {"colorSpace": "srgb", "hex": "#17458F"}},
                     "ink": {"$value": {"colorSpace": "srgb", "hex": "#1A2230"}}},
          "type": {"family": {"$type": "fontFamily", "$value": ["Verdana", "sans-serif"]},
                   "body": {"$type": "dimension", "$value": "16px"},
                   "title": {"$type": "dimension", "$value": "24px"}}}


def view(screen="parcels", state="normal", width=1440, walk=False) -> dict:
    return {"id": checks_views.view_id(screen, state, width), "screen": screen, "state": state,
            "width": width, "height": checks_views.height_for(width), "open": {"hash": f"#{screen}/{state}"},
            "walk": walk}


def clean_measure(v: dict, **over) -> dict:
    """What a view that is right in every way measures; each rule test breaks one piece of it."""
    m = {
        "view": v["id"], "screen": v["screen"], "state": v["state"], "width": v["width"], "opened": True,
        "why": "", "console": [], "failed_requests": [], "capture": f"views/{v['id']}.png",
        "dm": {"viewport": [v["width"], 900], "page_width": {"scroll": v["width"], "overflows": False},
               "overflowing": [], "contrast_failures": [], "weak_boundaries": [], "small_targets": [],
               "controls": [{"sel": "button.btn"}]},
        "mp": {"viewport": {"w": v["width"], "h": 900}, "horizontalScroll": 0,
               "type": {"smallest": [{"size": 16, "cls": "p", "text": "Due today"}], "bodyLikeUnder16": 0},
               "overflow": {"outside": []}, "truncated": {"items": []}, "runs": [],
               "fontsLoaded": True, "errors": []},
        "cm": {"contract": {"marked": True, "screens": [v["screen"]], "shown": [v["screen"]],
                            "states": [v["state"]], "banned_state_attr": []},
               "actions": [{"action": "refresh-parcels", "sel": "button.btn", "label": "Refresh",
                            "visible": True, "tag": "button"}],
               "reqs": {"R1": {"visible": True}, "R2": {"visible": True}},
               "figures": [{"kind": "money", "raw": "42.50", "suffix": "", "token": "$42.50",
                            "sel": "span.meta", "context": "Due today, $42.50"}],
               "used": {"colours": [{"value": "rgb(23,69,143)", "count": 3, "sel": "button.btn"}],
                        "fonts": [{"value": "Verdana", "count": 9, "sel": "body"}],
                        "sizes": [{"value": "16", "count": 9, "sel": "p"}]},
               "hierarchy": {"text_sizes": [24, 16],
                             "text_levels": [{"level": "strongest", "runs": 9,
                                              "colours": ["rgb(26,34,48)"]}],
                             "text_colours": [{"colour": "rgb(26,34,48)", "runs": 9}]},
               "solid_fills": [{"colour": "rgb(23,69,143)", "count": 1, "sel": "button.btn.primary",
                                "label": "Refresh"}],
               "wrapped_labels": [], "duplicate_ids": [], "dead_links": []},
        "axe": [],
    }
    if v.get("walk"):
        m["tab_stops"] = [{"sel": "button.btn", "name": "Refresh", "ring": True, "outline": "solid 3px",
                           "box_shadow": "none"}]
        m["action_feedback"] = [{"action": "refresh-parcels", "sel": "button.btn", "label": "Refresh",
                                 "found": True, "clicked": True, "feedback": True, "why": ""}]
    m.update(over)
    return m


def round_of(views: list[dict], measures: dict, inventory=None, requirements=None, fixture=FIXTURE,
             tokens=TOKENS, design_files="defined") -> dict:
    plan = {"page": "index.html", "widths": sorted({v["width"] for v in views}), "declared": False,
            "main": "#app", "areas": {}, "inventory": (inventory or INVENTORY)["screens"], "views": views}
    ctx = checks_rules.context(plan, plan["inventory"],
                               (requirements or REQUIREMENTS)["items"], fixture, tokens, design_files,
                               measures)
    return checks_rules.evaluate(plan, measures, ctx, TH)


def rows_of(result: dict, rule: str) -> list[dict]:
    return [r for r in result["rows"] if r["id"] == rule]


def one_view(breakage: dict | None = None, walk=True, **kw) -> dict:
    """Evaluate a single view whose measures are clean but for `breakage` (a deep-ish update)."""
    v = view(walk=walk)
    m = clean_measure(v)
    for key, value in (breakage or {}).items():
        if isinstance(value, dict) and isinstance(m.get(key), dict):
            for inner, deep in value.items():
                if isinstance(deep, dict) and isinstance(m[key].get(inner), dict):
                    m[key][inner].update(deep)
                else:
                    m[key][inner] = deep
        else:
            m[key] = value
    views = [v] + [view(state="empty", width=1440), view(screen="account", width=1440)]
    measures = {v["id"]: m}
    for other in views[1:]:
        measures[other["id"]] = clean_measure(other, cm={**clean_measure(other)["cm"]})
    measures[views[1]["id"]]["cm"]["contract"]["states"] = ["empty"]
    measures[views[2]["id"]]["cm"]["contract"]["shown"] = ["account"]
    measures[views[2]["id"]]["cm"]["actions"] = []
    return round_of(views, measures, **kw)


# ---------------------------------------------------------------- the view plan

def workspace_with_build(tmp_path: Path, build: dict, page: str = "<!doctype html><title>x</title>",
                         inventory: dict | None = INVENTORY) -> Workspace:
    ws = Workspace(tmp_path)
    ws.start("parcelly-checks", "real")
    ws.next_round()
    (ws.folder("build")).mkdir(parents=True, exist_ok=True)
    (ws.folder("build") / "build.json").write_text(json.dumps(build))
    if build.get("page") != "missing.html":
        (ws.folder("build") / (build.get("page") or "index.html")).write_text(page)
    if inventory:
        ws.folder("ground").mkdir(parents=True, exist_ok=True)
        (ws.folder("ground") / "inventory.json").write_text(json.dumps(inventory))
    return ws


def test_plan_follows_the_hash_convention_when_the_build_names_no_views(tmp_path):
    ws = workspace_with_build(tmp_path, {"page": "index.html", "widths": [1440, 390, 320]})
    plan = checks_views.plan(ws)
    assert len(plan["views"]) == 3 * 3                     # 3 screen-states x 3 widths
    assert plan["declared"] is False
    assert {v["open"]["hash"] for v in plan["views"]} == {"#parcels/normal", "#parcels/empty",
                                                          "#account/normal"}
    walked = [v for v in plan["views"] if v["walk"]]
    assert len(walked) == 3 and {v["width"] for v in walked} == {1440}
    assert [v["height"] for v in plan["views"] if v["width"] == 390][0] == 844


def test_plan_takes_the_builds_own_views_with_their_steps(tmp_path):
    ws = workspace_with_build(tmp_path, {
        "page": "app.html", "widths": [1440],
        "views": [{"screen": "parcels", "state": "normal", "open": {"steps": [{"goto": "#home"},
                                                                              {"click": "button.open"}]}},
                  {"screen": "parcels", "state": "empty", "open": {"hash": "#parcels/empty"},
                   "widths": [390]}]})
    plan = checks_views.plan(ws)
    assert plan["declared"] is True and plan["page"] == "app.html"
    assert [v["width"] for v in plan["views"]] == [390, 1440]
    assert plan["views"][1]["open"]["steps"][1]["click"] == "button.open"


@pytest.mark.parametrize("build,why", [
    ({"page": "index.html", "widths": []}, "widths"),
    ({"page": "missing.html", "widths": [1440]}, "missing.html"),
])
def test_plan_refuses_a_build_it_cannot_open(tmp_path, build, why):
    ws = workspace_with_build(tmp_path, build)
    with pytest.raises(checks_views.ViewError) as exc:
        checks_views.plan(ws)
    assert why in str(exc.value)


def test_plan_says_which_file_is_missing(tmp_path):
    ws = Workspace(tmp_path)
    ws.start("parcelly-checks", "real")
    with pytest.raises(checks_views.ViewError) as exc:
        checks_views.plan(ws)
    assert "build.json is missing" in str(exc.value)


# ---------------------------------------------------------------- the rules, on fixed measures

def test_clean_measures_give_no_row_at_all():
    result = one_view()
    assert result["rows"] == []
    assert result["verdict"] == "pass"
    assert {s["id"] for s in result["summary"]} == set(checks_rules.FAMILIES)
    assert all(s["result"] == "pass" for s in result["summary"])


@pytest.mark.parametrize("rule,breakage,in_evidence", [
    ("render.console", {"console": ["TypeError: missingHelper is not a function"]}, "missingHelper"),
    ("render.request", {"failed_requests": ["build/depot-photo.png HTTP 404"]}, "404"),
    ("contract.state_attr", {"cm": {"contract": {"banned_state_attr": [{"attr": "data-state",
                                                                        "sel": "div.card"}]}}},
     "Show&Tell helper hides it"),
    ("overflow.layout_width", {"mp": {"viewport": {"w": 1600}}}, "1600px"),
    ("overflow.horizontal", {"mp": {"horizontalScroll": 1670}}, "scrolls sideways"),
    ("overflow.element", {"dm": {"overflowing": [{"sel": "div.band", "box": [0, 0, 700, 10]}]}},
     "sticks out past"),
    ("overflow.truncated", {"mp": {"truncated": {"items": [{"how": "ellipsis", "text": "Due today, $42.50",
                                                            "shown": 120, "needs": 180, "cls": "span.meta"}]}}},
     "ellipsis cuts"),
    ("overflow.label", {"cm": {"wrapped_labels": [{"sel": "button.btn", "text": "Save note", "lines": 2,
                                                   "width": 64, "needed": 86, "free": 120}]}},
     "splits onto 2 lines"),
    ("type.floor", {"mp": {"type": {"smallest": [{"size": 10, "cls": "span.meta", "text": "Due today"}]}}},
     "floor 12"),
    ("type.body", {"mp": {"type": {"bodyLikeUnder16": 3}}}, "below 16"),
    ("contrast.text", {"dm": {"contrast_failures": [{"contrast": 2.4, "needs": 4.5, "size": 16,
                                                     "weight": 400, "color": "#9AA0A6",
                                                     "background": "#F4F6F8", "sel": "span.meta",
                                                     "text": "Due today"}]}}, "2.4:1 needs 4.5:1"),
    ("contrast.ui", {"dm": {"weak_boundaries": [{"sel": "input#note", "name": "Delivery note",
                                                 "boundary_contrast": 1.4}]}}, "1.4:1 boundary"),
    # hit is the measure's word for how the spacing exception fails ("target" or "circle"), not a number
    ("targets.size", {"dm": {"small_targets": [{"sel": "nav a", "name": "Account", "box": [0, 0, 18, 18],
                                                "hit": "target",
                                                "too_close_to": {"name": "Parcels", "edge": 2.0,
                                                                 "centre": 20.0}}]}},
     "18x18px"),
    ("focus.ring", {"tab_stops": [{"sel": "button.btn", "name": "Refresh", "ring": False,
                                   "outline": "none 0px", "box_shadow": "none"}]}, "no visible ring"),
    ("focus.none", {"tab_stops": []}, "Tab reached no control"),
    ("hierarchy.sizes", {"cm": {"hierarchy": {"text_sizes": [24, 16, 15, 14, 13]}}}, "5 text sizes"),
    ("hierarchy.levels", {"cm": {"hierarchy": {"text_levels": [{"level": lv, "runs": 2, "colours": [c]}
                                                               for lv, c in (("strongest", "rgb(26,34,48)"),
                                                                             ("strong", "rgb(76,86,104)"),
                                                                             ("normal", "rgb(92,102,120)"),
                                                                             ("soft", "rgb(154,160,166)"))]}}},
     "4 text contrast levels"),
    ("hierarchy.primary", {"cm": {"solid_fills": [{"colour": "rgb(23,69,143)", "sel": "button.a",
                                                   "label": "Refresh"},
                                                  {"colour": "rgb(138,28,19)", "sel": "button.b",
                                                   "label": "Open"}]}},
     "2 solid fills"),
    ("tokens.colour", {"cm": {"used": {"colours": [{"value": "rgb(29,78,216)", "count": 2,
                                                    "sel": "button.btn"}]}}}, "#1D4ED8 is not in tokens.json"),
    ("tokens.font", {"cm": {"used": {"fonts": [{"value": "Plus Jakarta Sans", "count": 9, "sel": "body"}]}}},
     "not a tokens.json font"),
    ("tokens.size", {"cm": {"used": {"sizes": [{"value": "13", "count": 4, "sel": "p.hint"}]}}},
     "13.0px is not a tokens.json text size"),
    ("figures.invented", {"cm": {"figures": [{"kind": "money", "raw": "2,480.00", "suffix": "",
                                              "token": "$2,480.00", "sel": "span",
                                              "context": "Spent $2,480.00"}]}},
     "not in fixture.json"),
    ("integration.duplicate_id", {"cm": {"duplicate_ids": [{"id": "note", "count": 2, "sel": "#note"}]}},
     "on 2 elements"),
    ("integration.dead_link", {"cm": {"dead_links": [{"href": "#returns/normal", "text": "Returns",
                                                      "sel": "nav a:nth-of-type(3)"}]}},
     "not a view of this build"),
    ("integration.two_screens", {"cm": {"contract": {"shown": ["parcels", "account"]}}},
     "2 screens are visible at once"),
    ("integration.handler", {"action_feedback": [{"action": "refresh-parcels", "sel": "button.btn",
                                                  "label": "Refresh", "found": True, "clicked": False,
                                                  "feedback": False, "why": "not clickable"}]},
     "could not be clicked"),
    ("coverage.feedback", {"action_feedback": [{"action": "refresh-parcels", "sel": "button.btn",
                                                "label": "Refresh", "found": True, "clicked": True,
                                                "feedback": False, "why": ""}]}, "changed nothing visible"),
])
def test_one_broken_measure_gives_its_own_row(rule, breakage, in_evidence):
    result = one_view(breakage)
    hits = rows_of(result, rule)
    assert hits, f"{rule} did not fire; rows: {[r['id'] for r in result['rows']]}"
    assert in_evidence in hits[0]["evidence"]
    assert hits[0]["severity"] == checks_rules.RULES[rule][1]
    assert hits[0]["screen"] == "parcels" and hits[0]["width"] == 1440
    assert "views/parcels-normal-1440.png" in hits[0]["location"]


def test_a_label_only_counts_as_split_when_its_row_has_the_room_to_unwrap():
    # H6a-8: a label wrapping in a column that is already full is the layout, not a flaw, so the browser
    # measure compares what the label needs with what the row has left beside the control.
    source = (ROOT / "configs/design/bin/app_screen/checks_measure.js").read_text()
    assert "range.selectNodeContents(el)" in source and "getClientRects()" in source
    assert "needed > content + 1 && needed <= content + free + 1" in source
    assert "columnGap" in source


def test_a_view_that_did_not_open_is_one_row_and_nothing_else():
    v = view(walk=True)
    result = round_of([v], {v["id"]: {"view": v["id"], "screen": "parcels", "state": "normal",
                                      "width": 1440, "opened": False, "why": "Timeout 30000ms exceeded"}})
    # the view itself is one row, and the state it should have shown is reported missing by coverage
    assert {r["id"] for r in result["rows"] if r["screen"] == "parcels"} == {"render.open", "coverage.view"}
    assert "Timeout" in rows_of(result, "render.open")[0]["evidence"]


def test_the_screen_and_state_marks_are_checked_against_what_opened():
    result = one_view({"cm": {"contract": {"shown": ["account"], "states": ["loading"]}}})
    assert rows_of(result, "contract.screen") and rows_of(result, "contract.state")
    assert "not parcels" in rows_of(result, "contract.screen")[0]["evidence"]


def test_a_build_with_no_marks_says_so_once_and_skips_the_contract_checks():
    v = view(walk=True)
    m = clean_measure(v)
    m["cm"]["contract"] = {"marked": False, "shown": [], "states": [], "banned_state_attr": []}
    result = round_of([v], {v["id"]: m})
    assert len(rows_of(result, "contract.marks")) == 1
    assert not rows_of(result, "contract.screen")
    assert "coverage" in result["totals"]["checks_skipped"]
    coverage = next(s for s in result["summary"] if s["id"] == "coverage")
    assert "no data-screen" in coverage["evidence"]


def test_coverage_misses_a_state_an_action_and_a_requirement():
    views = [view(), view(screen="account")]                  # parcels/empty is never opened
    measures = {}
    for v in views:
        m = clean_measure(v, cm={**clean_measure(v)["cm"]})
        m["cm"]["contract"]["shown"] = [v["screen"]]
        m["cm"]["actions"] = []                               # no data-action element anywhere
        m["cm"]["reqs"] = {"R1": {"visible": True}}           # R2 is nowhere
        measures[v["id"]] = m
    result = round_of(views, measures)
    assert [r["element"] for r in rows_of(result, "coverage.view")] == ["#parcels/empty"]
    assert rows_of(result, "coverage.action")[0]["element"] == "[data-action=refresh-parcels]"
    assert rows_of(result, "coverage.requirement")[0]["element"] == "[data-req~=R2]"
    assert result["verdict"] == "fail"


def test_a_state_that_opens_at_one_width_only_is_not_a_miss():
    wide, narrow = view(state="empty", width=1440), view(state="empty", width=390)
    measures = {}
    for v, opened in ((wide, True), (narrow, False)):
        m = clean_measure(v)
        m["cm"]["contract"]["states"] = ["empty"]
        m["opened"] = opened
        measures[v["id"]] = m
    result = round_of([wide, narrow, view(), view(screen="account")],
                      {**measures, view()["id"]: clean_measure(view()),
                       view(screen="account")["id"]: clean_measure(view(screen="account"),
                                                                   cm={**clean_measure(view(screen="account"))["cm"],
                                                                       "contract": {"marked": True,
                                                                                    "shown": ["account"],
                                                                                    "states": ["normal"],
                                                                                    "banned_state_attr": []}})})
    assert not rows_of(result, "coverage.view")
    assert rows_of(result, "render.open")                      # the width that failed is still a row


def test_figures_are_matched_against_the_fixture_and_its_derivations():
    values = checks_rules.fixture_values(FIXTURE)
    assert checks_rules.figure_matches({"token": "$42.50", "raw": "42.50", "kind": "money"}, values)
    assert checks_rules.figure_matches({"token": "12.5%", "raw": "12.5", "kind": "percent"}, values), \
        "a share shown as a percent is derived, not invented"
    assert checks_rules.figure_matches({"token": "$0.2k", "raw": "0.2", "suffix": "k", "kind": "money"},
                                       values), "167.75 rounded to 0.2k is the same number"
    assert not checks_rules.figure_matches({"token": "$2,480.00", "raw": "2,480.00", "kind": "money"},
                                           values)


def test_without_a_fixture_or_tokens_those_checks_are_skipped_not_passed():
    result = one_view(fixture=None, tokens=None, design_files="none")
    assert set(result["totals"]["checks_skipped"]) == {"figures", "tokens"}
    for family in ("figures", "tokens"):
        assert next(s for s in result["summary"] if s["id"] == family)["result"] == "skipped"


def test_rows_are_capped_per_check_and_the_summary_says_so():
    v = view(walk=False)
    m = clean_measure(v)
    m["console"] = [f"TypeError {i}" for i in range(200)]
    result = round_of([v], {v["id"]: m})
    assert len(rows_of(result, "render.console")) == TH["limits"]["rows_per_check_per_view"]


def test_every_rule_has_a_family_and_a_class_the_review_can_read():
    for rule, (family, severity, _what) in checks_rules.RULES.items():
        assert family in checks_rules.FAMILIES, rule
        assert severity in (checks_rules.BLOCKER, checks_rules.SHOULD), rule
    blockers = {r for r, (_f, s, _w) in checks_rules.RULES.items() if s == checks_rules.BLOCKER}
    assert {"axe.violation", "overflow.horizontal", "coverage.view", "coverage.action",
            "coverage.requirement", "figures.invented", "render.open"} <= blockers
    shoulds = {r for r, (_f, s, _w) in checks_rules.RULES.items() if s == checks_rules.SHOULD}
    # A label that wraps still reads in full, so it is craft, not a blocker (H6a-2).
    assert {"hierarchy.sizes", "hierarchy.levels", "hierarchy.primary", "overflow.label"} <= shoulds


def test_a_row_of_dots_is_not_text_below_the_floor():
    """H6a-5: a run with no letter or digit is decoration, not something to read."""
    v = view("home", "normal", 390)
    m = clean_measure(v)
    m["mp"]["type"]["smallest"] = [{"size": 11, "cls": ".step-dots", "text": "\u25cf \u25cf \u25cf"},
                                   {"size": 11, "cls": ".eyebrow", "text": "STEP 1 OF 5"}]
    rows = rows_of(round_of([v], {v["id"]: m}), "type.floor")
    assert len(rows) == 1 and "STEP 1 OF 5" in rows[0]["evidence"]


def test_a_control_already_shown_as_the_chosen_one_has_answered_the_click():
    """H6a-6: clicking the filter the view already shows as active cannot change anything."""
    v = view("home", "normal", 390)
    m = clean_measure(v)
    m["action_feedback"] = [
        {"action": "all-drafts", "sel": "button.chip", "label": "All drafts (3)", "found": True,
         "clicked": True, "feedback": False, "already_on": True, "why": ""},
        {"action": "send", "sel": "button.send", "label": "Send", "found": True,
         "clicked": True, "feedback": False, "already_on": False, "why": ""}]
    rows = rows_of(round_of([v], {v["id"]: m}), "coverage.feedback")
    assert len(rows) == 1 and "Send" in rows[0]["evidence"]


def test_a_control_the_click_step_could_not_find_says_why():
    v = view("home", "normal", 390)
    m = clean_measure(v)
    m["action_feedback"] = [{"action": "save", "sel": "button.save", "label": "Save", "found": False,
                             "clicked": False, "feedback": False, "why": ""}]
    rows = rows_of(round_of([v], {v["id"]: m}), "integration.handler")
    assert len(rows) == 1 and "the browser gave no reason" in rows[0]["evidence"]


def test_the_click_step_finds_the_control_by_its_data_action_mark():
    """H6a-3: a CSS path drifts when the page re-renders between the measure and the click."""
    from app_screen import checks_render

    sent = []

    class FakeBrowser:
        async def run(self, _session, code):
            sent.append(code)
            if "data-action" not in code:                      # the reopen between controls
                return {"opened": True}
            return {"found": True, "clicked": True, "why": "",
                    "before": {"cls": "btn", "style": "a", "text": 10, "hash": 1, "url": "#/home"},
                    "after": {"cls": "btn", "style": "a", "text": 10, "hash": 1, "url": "#/home"}}

    actions = [{"action": "send-draft", "idx": 2, "sel": "div:nth-of-type(9) > button.btn", "label": "Send"}]
    out = asyncio.run(checks_render._click_feedback(
        FakeBrowser(), None, "http://site/index.html",
        {"id": "home-normal-390", "width": 390, "height": 900, "open": {"hash": "#/home"}}, actions, 200))
    click_code = sent[0]
    assert '[data-action=\\"send-draft\\"]' in click_code or '[data-action="send-draft"]' in click_code
    assert "const idx = 2" in click_code and "nth(idx)" in click_code
    assert "div:nth-of-type(9)" not in click_code                # the fragile path is evidence only
    assert out == [{"action": "send-draft", "sel": "div:nth-of-type(9) > button.btn", "label": "Send",
                    "found": True, "clicked": True, "feedback": False, "already_on": False, "why": ""}]


def test_the_thresholds_are_the_numbers_the_bar_names():
    assert TH["contrast"]["text"] == 4.5 and TH["contrast"]["ui"] == 3.0
    assert TH["type"]["floor_px"] == 12 and TH["type"]["body_px"] == 16
    assert TH["hierarchy"]["max_text_sizes"] == 3 and TH["hierarchy"]["primary_per_view"] == 1
    assert TH["targets"]["min_px"] == 24
    assert "wcag22aa" in TH["axe"]["tags"]


# ---------------------------------------------------------------- the step, over a stubbed browser

def case_folder(tmp_path: Path, build_json: dict | None = None) -> Path:
    case = tmp_path / "case"
    (case / "01-request").mkdir(parents=True)
    (case / "03-ground/design-files").mkdir(parents=True)
    (case / "05-build").mkdir(parents=True)
    (case / "01-request/requirements.json").write_text(json.dumps(REQUIREMENTS))
    (case / "03-ground/inventory.json").write_text(json.dumps(INVENTORY))
    (case / "03-ground/fixture.json").write_text(json.dumps(FIXTURE))
    (case / "03-ground/design-files/tokens.json").write_text(json.dumps(TOKENS))
    (case / "05-build/index.html").write_text("<!doctype html><title>Parcelly</title>")
    (case / "05-build/build.json").write_text(json.dumps(build_json or {"page": "index.html",
                                                                        "widths": [1440, 390]}))
    (case / "expected.json").write_text(json.dumps({
        "case": "t-case", "product": "parcelly-checks", "planted": [],
        "expect": {"allow": [], "blockers": 0}}))
    return case


def stub_measure(result_for):
    def measure(ws, plan, thresholds):
        out = {}
        for v in plan["views"]:
            m = clean_measure(v)
            m["cm"]["contract"]["shown"] = [v["screen"]]
            m["cm"]["contract"]["states"] = [v["state"]]
            if v["screen"] != "parcels":
                m["cm"]["actions"] = []
            out[v["id"]] = result_for(v, m)
            shots = ws.round_folder() / "views"
            shots.mkdir(parents=True, exist_ok=True)
            (shots / f"{v['id']}.png").write_bytes(PNG)
        return out
    return measure


def test_the_step_writes_the_round_file_the_contract_asks_for(tmp_path, monkeypatch):
    case = case_folder(tmp_path)
    ws_path = tmp_path / "ws"
    prepped = checks_host.prep(case, ws_path)
    assert prepped["round"] == 1 and prepped["product"] == "parcelly-checks"
    monkeypatch.setattr(checks, "measure", stub_measure(lambda v, m: m))
    out = checks.run(Workspace(ws_path), "")
    assert out["verdict"] == "pass" and out["views"] == 6 and out["rows"] == 0
    record = json.loads((ws_path / "06-checks/round-1/checks.json").read_text())
    assert record["round"] == 1 and record["tool"]
    assert [c["id"] for c in record["checks"] if c.get("summary")] == list(checks_rules.FAMILIES)
    assert (ws_path / "06-checks/round-1/measures.json").is_file()
    assert contracts.validate("checks", Workspace(ws_path))


def test_the_step_fails_the_round_when_a_blocker_is_measured(tmp_path, monkeypatch):
    case = case_folder(tmp_path)
    ws_path = tmp_path / "ws"
    checks_host.prep(case, ws_path)

    def break_one(v, m):
        if v["id"] == "parcels-normal-390":
            m["console"] = ["TypeError: missingHelper is not a function"]
        return m
    monkeypatch.setattr(checks, "measure", stub_measure(break_one))
    out = checks.run(Workspace(ws_path), "")
    assert out["verdict"] == "fail" and out["blockers"] == 1
    record = json.loads((ws_path / "06-checks/round-1/checks.json").read_text())
    failing = [c for c in record["checks"] if not c.get("summary")]
    assert failing[0]["id"] == "render.console" and failing[0]["width"] == 390
    assert json.loads((ws_path / "run.json").read_text())["stages"]["checks"]["verdict"] == "fail"


def test_the_step_refuses_a_run_with_no_build_round(tmp_path):
    ws_path = tmp_path / "ws"
    ws_path.mkdir()
    ws = Workspace(ws_path)
    ws.start("parcelly-checks", "real")
    with pytest.raises(checks.ChecksError) as exc:
        checks.run(ws, "")
    assert "the build step runs before the checks step" in str(exc.value)


def test_the_step_says_which_file_the_run_is_missing(tmp_path, monkeypatch):
    # the build names its own views, so the step gets as far as the rules before the file is missed
    case = case_folder(tmp_path, {"page": "index.html", "widths": [1440],
                                  "views": [{"screen": "parcels", "state": "normal",
                                             "open": {"hash": "#parcels/normal"}}]})
    ws_path = tmp_path / "ws"
    checks_host.prep(case, ws_path)
    (ws_path / "03-ground/inventory.json").unlink()
    monkeypatch.setattr(checks, "measure", stub_measure(lambda v, m: m))
    with pytest.raises(checks.ChecksError) as exc:
        checks.run(Workspace(ws_path), "")
    assert "inventory.json is missing" in str(exc.value)


# ---------------------------------------------------------------- the known-case host and the grader

def test_a_case_goes_into_a_fresh_workspace_only(tmp_path):
    case = case_folder(tmp_path)
    ws_path = tmp_path / "ws"
    checks_host.prep(case, ws_path)
    with pytest.raises(checks_host.CaseError) as exc:
        checks_host.prep(case, ws_path)
    assert "fresh workspace" in str(exc.value)


def test_a_folder_without_expected_json_is_not_a_case(tmp_path):
    (tmp_path / "nope").mkdir()
    with pytest.raises(checks_host.CaseError):
        checks_host.read_case(tmp_path / "nope")


def graded(tmp_path, planted: list[dict], rows: list[dict], allow=None, extra_expect=None,
           run="1", read=None) -> dict:
    tmp_path = tmp_path / run
    tmp_path.mkdir(parents=True, exist_ok=True)
    case = case_folder(tmp_path)
    expected = json.loads((case / "expected.json").read_text())
    expected["planted"] = planted
    expected["expect"] = {"allow": allow or [], **(extra_expect or {})}
    if read is not None:
        expected["read"] = read
    (case / "expected.json").write_text(json.dumps(expected))
    ws_path = tmp_path / "ws"
    checks_host.prep(case, ws_path)
    (ws_path / "06-checks/round-1").mkdir(parents=True)
    (ws_path / "06-checks/round-1/checks.json").write_text(json.dumps({
        "round": 1, "tool": "stub", "views": 6, "blockers": sum(1 for r in rows
                                                                if r.get("severity") == "blocker"),
        "shoulds": 0, "checks": rows}))
    return checks_grade.grade(case, ws_path)


def row(rule="type.floor", screen="parcels", state="normal", width=390, element="span.meta") -> dict:
    family, severity, what = checks_rules.RULES[rule]
    return {"id": rule, "check": family, "severity": severity, "result": "fail", "value": 10,
            "evidence": what, "element": element, "location": f"{screen} / {state} @ {width}px",
            "screen": screen, "state": state, "width": width}


def test_the_grader_counts_a_planted_fault_caught_at_the_right_place(tmp_path):
    planted = [{"id": "F1", "check": "type.floor", "screen": "parcels", "state": "normal", "width": 390,
                "what": "10px meta lines"}]
    out = graded(tmp_path, planted, [row()])
    assert out["pass"] and out["measures"]["recall"] == 1.0 and out["measures"]["false_rows"] == 0


def test_the_grader_does_not_count_the_right_check_at_the_wrong_width(tmp_path):
    planted = [{"id": "F1", "check": "type.floor", "screen": "parcels", "state": "normal", "width": 390,
                "what": "10px meta lines"}]
    out = graded(tmp_path, planted, [row(width=1440)])
    assert not out["pass"] and out["measures"]["caught"] == 0
    assert "not caught" in out["misses"][0]


def test_the_grader_calls_an_unplanted_row_a_false_finding_unless_the_case_allows_it(tmp_path):
    planted = [{"id": "F1", "check": "type.floor", "screen": "parcels", "state": "normal", "width": 390,
                "what": "10px meta lines"}]
    out = graded(tmp_path, planted, [row(), row(rule="tokens.size")])
    assert not out["pass"] and out["measures"]["false_rows"] == 1
    allowed = graded(tmp_path, planted, [row(), row(rule="tokens.size")], allow=["tokens.size"], run="2")
    assert allowed["pass"] and allowed["measures"]["false_rows"] == 0


def test_the_grader_holds_a_case_to_its_blocker_count_and_its_clean_checks(tmp_path):
    out = graded(tmp_path, [], [row(rule="hierarchy.sizes")], allow=["hierarchy.sizes"],
                 extra_expect={"allow": ["hierarchy.sizes"], "blockers": 0, "clean_checks": ["hierarchy"]})
    assert not out["pass"] and any("should be clean here" in m for m in out["misses"])


def test_a_real_case_is_graded_by_its_hand_read_and_fails_on_an_unread_rule(tmp_path):
    # A real prototype has nothing planted: the bar is that every failing rule was read by hand and
    # recorded, and that no blocker row was read as false.
    rows = [row(), row(rule="hierarchy.sizes")]
    unread = graded(tmp_path, [], rows, read={"type.floor": {"verdict": "real", "why": "10px meta"}})
    assert not unread["pass"] and any("hierarchy.sizes: not read" in m for m in unread["misses"])
    all_real = graded(tmp_path, [], rows, run="2",
                      read={"type.floor": {"verdict": "real", "why": "10px meta"},
                            "hierarchy.sizes": {"verdict": "real", "why": "9 sizes in one view"}})
    assert all_real["pass"] and all_real["measures"]["false_rows"] == 0
    assert any("precision 2/2 rows real (100%)" in n for n in all_real["notes"])
    false_must = graded(tmp_path, [], rows, run="3",
                        read={"type.floor": {"verdict": "false", "why": "it is a decorative dot row"},
                              "hierarchy.sizes": {"verdict": "real", "why": "9 sizes in one view"}})
    assert not false_must["pass"] and any("false Must" in m for m in false_must["misses"])
    assert false_must["measures"]["false_rows"] == 1


def test_a_view_whose_state_is_not_an_id_is_refused_before_anything_opens(tmp_path):
    # The row contract holds a state as an id, so a build.json that names `not_sent` must be refused at
    # the start with the field named, not after every view has been rendered.
    ws = workspace_with_build(tmp_path, {"page": "index.html", "widths": [390],
                                         "views": [{"screen": "telegram", "state": "not_sent",
                                                    "open": {"hash": "#/telegram?state=not_sent"}}]})
    with pytest.raises(checks_views.ViewError) as problem:
        checks_views.plan(ws)
    assert "05-build/build.json: 1 problem(s): views/0/state: 'not_sent' is not an id" in str(problem.value)
    (tmp_path / "ok").mkdir()
    ok = workspace_with_build(tmp_path / "ok", {"page": "index.html", "widths": [390],
                                                "views": [{"screen": "telegram", "state": "not-sent",
                                                           "open": {"hash": "#/telegram?state=not_sent"}}]})
    assert checks_views.plan(ok)["views"][0]["open"]["hash"] == "#/telegram?state=not_sent"


def test_the_digest_is_the_rows_and_not_their_order(tmp_path):
    rows = [row(), row(rule="tokens.size", element="p.hint")]
    one = checks_grade.digest({"checks": rows})
    other = checks_grade.digest({"checks": list(reversed(rows))})
    assert one == other
    assert one != checks_grade.digest({"checks": rows[:1]})


# ---------------------------------------------------------------- the configs

def test_the_stage_alone_workflow_runs_the_checks_step_on_a_prepared_workspace():
    wf = yaml.safe_load((ROOT / "configs/design/workflows/design_app_screen_v1_checks.yaml"
                         ).read_text())["workflow"]
    assert [n["name"] for n in wf["nodes"]] == ["checks"]
    assert wf["inputs"]["mode"]["default"] == "real"
    assert wf["nodes"][0]["input_map"]["step"] == "checks"


def test_the_main_workflow_still_has_the_checks_step_in_the_review_loop():
    whole = yaml.safe_load((ROOT / "configs/design/workflows/design_app_screen_v1.yaml"
                            ).read_text())["workflow"]
    alone = yaml.safe_load((ROOT / "configs/design/workflows/design_app_screen_v1_checks.yaml"
                            ).read_text())["workflow"]
    names = [n["name"] for n in whole["nodes"]]
    assert "checks" in names and names.index("checks") < names.index("review")
    stage = next(n for n in whole["nodes"] if n["name"] == "checks")
    assert stage["type"] == "stage" and stage["depends_on"] == ["build"]
    mine = stage["nodes"][0]
    assert mine["name"] == "checks_finish"
    # the trial proves the stage only while the stage-alone node matches the whole workflow's
    assert mine["agent"] == alone["nodes"][0]["agent"]
    assert mine["input_map"]["step"] == alone["nodes"][0]["input_map"]["step"]


def test_the_tool_registry_points_at_the_checks_tools_that_exist():
    registry = yaml.safe_load((ROOT / "configs/design/knowledge/tools.yaml").read_text())
    entries = {t["id"]: t for t in registry["tools"]}
    for tool_id in ("checks_rules", "checks_render", "checks_measure", "design_measure"):
        assert tool_id in entries, f"{tool_id} is not in tools.yaml"
        assert (ROOT / entries[tool_id]["path"]).exists(), entries[tool_id]["path"]
