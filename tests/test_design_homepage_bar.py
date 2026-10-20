"""Model-free tests for Design's homepage A-bar meter (part 1, queue #78; version 2, queue #91; version 3, queue #112).

configs/design/bin/design_homepage_bar.js measures a page in temper's playwright-mcp browser;
design_homepage_bar.py scores the raw measurements against BAR.md's A bars. No browser here:
configs/design/testpages/bar-v1/raw/*.json, bar-v2/raw/*.json and bar-a11-v1/raw/*.json were recorded from
the fixture pages (`design_homepage_bar.py --fixture-proof --record [SET ...]`). bar-v1/expected.json, written
before part 1, lists each bar-v1 page's exact failing (bar, check, width) rows; bar-v2/expected.json, written
before version 2's code, keys version 2's cases and the two rows it added; bar-a11-v1/expected.json, written
and sealed before version 3's code, keys the A11 rows. Definitions: docs/design-homepage-bar.md.
"""
import copy
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "configs/design/bin"
FIX = ROOT / "configs/design/testpages/bar-v1"
FIX2 = ROOT / "configs/design/testpages/bar-v2"
sys.path.insert(0, str(BIN))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, BIN / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


hb = _load("design_homepage_bar")
KEY = json.loads((FIX / "expected.json").read_text(encoding="utf-8"))
KEY2 = json.loads((FIX2 / "expected.json").read_text(encoding="utf-8"))
BRIEF = json.loads((FIX / "brief.json").read_text(encoding="utf-8"))
PAGES = sorted(KEY["pages"])
PAGES2 = sorted(KEY2["pages"])
# bar-v1/expected.json as #78 committed it (45b8bd7d); version 2 never edits it.
KEY_V1_SHA256 = "05436368c8276b6d3ac1bcb7a5306711508bfa61c4586f1caed8481c6ffcebed"


def _raw(page):
    return json.loads((FIX / "raw" / f"{Path(page).stem}.json").read_text(encoding="utf-8"))


def _raw2(page):
    return json.loads((FIX2 / "raw" / f"{hb.raw_name(page)}.json").read_text(encoding="utf-8"))


def _brief2(page):
    return json.loads((ROOT / KEY2["site"] / KEY2["pages"][page]["brief"]).read_text(encoding="utf-8"))


# ------------------------------------------------------------------ the fixture keys


def test_bar_v1_key_is_unchanged():
    assert hashlib.sha256((FIX / "expected.json").read_bytes()).hexdigest() == KEY_V1_SHA256


@pytest.mark.parametrize("page", PAGES)
def test_recorded_page_scores_exactly_the_key(page):
    """bar-v1's key for the rows it covers; bar-v2's key (its bar-v1 section) for the rows version 2 added."""
    res = hb.key_match(page, hb.score(_raw(page), BRIEF), KEY, KEY2)
    assert res["missing"] == [], "missing failing rows"
    assert res["extra"] == [], "extra failing rows"


@pytest.mark.parametrize("page", PAGES2)
def test_bar_v2_recorded_case_matches_its_key(page):
    res = hb.key_match(page, hb.score(_raw2(page), _brief2(page)), KEY, KEY2)
    assert res["missing"] == [], "missing failing rows"
    assert res["extra"] == [], "extra failing rows"
    assert res["rows"] == [], "keyed rows differ"


@pytest.mark.parametrize("page", PAGES2)
def test_bar_v2_recorded_raw_is_of_the_current_page(page):
    raw = _raw2(page)
    html = ROOT / KEY2["site"] / page
    assert raw["page_sha256"] == hashlib.sha256(html.read_bytes()).hexdigest()
    assert sorted(raw["widths"]) == sorted(hb.WIDTHS)
    assert all("error" not in v for v in raw["widths"].values())
    deriv = html.parent / "derivations.json"
    if deriv.is_file():
        assert raw["derivations"]["sha256"] == hashlib.sha256(deriv.read_bytes()).hexdigest()
    else:
        assert "derivations" not in raw


@pytest.mark.parametrize("page", PAGES)
def test_recorded_raw_is_of_the_current_page(page):
    raw = _raw(page)
    html = ROOT / KEY["site"] / page
    assert raw["page_sha256"] == hashlib.sha256(html.read_bytes()).hexdigest()
    assert sorted(raw["widths"]) == sorted(hb.WIDTHS)
    assert all("error" not in v for v in raw["widths"].values())


def test_clean_page_passes_every_row():
    """Every row but A11's: the recorded raw predates version 3 (see the next test)."""
    rows = [r for r in hb.score(_raw("bar-v1/clean.html"), BRIEF) if r["bar"] != "A11"]
    assert rows and all(r["pass"] is True for r in rows)


def test_a_raw_from_before_version_3_reads_not_measured_on_a11():
    raw = _raw("bar-v1/clean.html")
    assert raw["version"] == 2
    rows = [r for r in hb.score(raw, BRIEF) if r["bar"] == "A11"]
    assert len(rows) == 12
    assert all(r["value"] == "not measured" and r["pass"] is None and r["evidence"] == [] for r in rows)


def test_planted_pages_break_every_check_at_least_once():
    broken = {(b, c) for page in PAGES for b, c, _ in KEY["pages"][page]}
    broken |= {(b, c) for rows in KEY2["bar-v1"]["pages"].values() for b, c, _ in rows}
    broken |= {(b, c) for page in PAGES2 for b, c, _ in KEY2["pages"][page]["failing"]}
    broken |= {(b, c) for page in PAGES3 for b, c, _ in KEY3["pages"][page]["failing"]}
    every = {(b, c) for b, c, _, _ in hb.CHECKS}
    assert every - broken == set()
    assert broken - every == set()


def test_rows_follow_the_contract_in_a_fixed_order():
    rows = hb.score(_raw("bar-v1/p-access.html"), BRIEF)
    want = [(b, c, w) for b, c, spec, _ in hb.CHECKS for w in hb.widths_of(spec)]
    assert [(r["bar"], r["check"], r["width"]) for r in rows] == want
    limits = {(b, c): lim for b, c, _, lim in hb.CHECKS}
    for r in rows:
        assert set(r) == {"bar", "check", "width", "value", "limit", "pass", "evidence"}
        assert r["limit"] == limits[(r["bar"], r["check"])]
        assert r["pass"] in (True, False, None)
        assert len(r["evidence"]) <= 5
        for e in r["evidence"]:
            assert set(e) == {"selector", "text", "box"}
            assert len(e["text"]) <= 80 and len(e["box"]) == 4


def test_bars_json_is_byte_identical_across_writes(tmp_path):
    raw = _raw("bar-v1/p-structure.html")
    hb.write_outputs(tmp_path / "a", raw, BRIEF, "brief.json")
    hb.write_outputs(tmp_path / "b", copy.deepcopy(raw), BRIEF, "brief.json")
    a, b = (tmp_path / "a" / "bars.json").read_bytes(), (tmp_path / "b" / "bars.json").read_bytes()
    assert a == b
    doc = json.loads(a)
    assert set(doc) == {"meter", "version", "page", "page_sha256", "brief", "widths", "rows"}
    assert doc["meter"] == "design_homepage_bar" and doc["widths"] == hb.WIDTHS
    md = (tmp_path / "a" / "bars.md").read_text(encoding="utf-8")
    assert "| bar | check | width | value | limit | pass |" in md
    assert "| A7 | not met |" in md and "| A3 | met |" in md


def test_a_width_that_could_not_be_measured_is_null_not_a_pass():
    raw = _raw("bar-v1/clean.html")
    raw["widths"]["768x1024"] = {"error": "RuntimeError: page crashed"}
    rows = hb.score(raw, BRIEF)
    at = [r for r in rows if r["width"] == "768x1024"]
    assert at and all(r["pass"] is None for r in at)
    every = {r["check"]: r["pass"] for r in rows if r["width"] == "all"}
    assert every["disclosure"] is None and every["placeholders"] is None and every["numbers"] is None
    assert every["cta-length"] is True and every["cta-verb"] is True and every["cta-wording"] is True
    assert ("A4", "axe", "1440x900") not in hb.failing(rows)


def test_a_brief_that_is_not_fictional_needs_no_disclosure():
    raw = _raw("bar-v1/p-reading.html")
    brief = dict(BRIEF, fictional=False)
    rows = hb.score(raw, brief)
    assert next(r for r in rows if r["check"] == "disclosure")["pass"] is True


# ------------------------------------------------------------------ syllables and Flesch-Kincaid


@pytest.mark.parametrize("word,n", [
    ("cat", 1), ("the", 1), ("eye", 1), ("it's", 1), ("12", 1), ("free", 1), ("bills", 1),
    ("make", 1), ("whole", 1), ("jumped", 1),
    ("table", 2), ("simple", 2), ("money", 2), ("ledger", 2), ("garden", 2), ("minutes", 2),
    ("spending", 2), ("every", 3), ("comparison", 4), ("Ledger,", 2),
])
def test_syllable_rule(word, n):
    assert hb.syllables(word) == n


def test_sentences_end_at_marks_before_a_space_or_the_end():
    assert hb.sentences_of("One. Two! Three?") == 3
    assert hb.sentences_of("No mark at the end") == 1
    assert hb.sentences_of("It costs 4.5 a month. Then more") == 2
    assert hb.sentences_of("   ") == 0


def test_fk_grade_formula():
    # 6 words, 1 sentence, 6 syllables: 0.39 * 6 + 11.8 * 1 - 15.59
    assert hb.fk_grade(["The cat sat on the mat."]) == pytest.approx(0.39 * 6 + 11.8 - 15.59)
    # Each text ends a sentence even without a mark: 2 sentences of 3 words.
    assert hb.fk_grade(["The cat sat", "The dog ran"]) == pytest.approx(0.39 * 3 + 11.8 - 15.59)
    assert hb.fk_grade([]) is None
    hard = ("Comprehensive reconciliation of heterogeneous expenditure classifications necessitates "
            "considerable organisational sophistication and administrative perseverance.")
    assert hb.fk_grade([hard]) > 9
    assert hb.fk_grade(["Setup takes about five minutes. You see each bill in one place."]) <= 9


def test_words_hold_a_letter_or_digit():
    assert hb.words_of("It's 12 — a free, plain ledger!") == ["It's", "12", "a", "free", "plain", "ledger"]


# ------------------------------------------------------------------ the frozen lists


def test_verb_list_is_frozen_and_used():
    verbs = hb.load_verbs()
    assert {"start", "get", "try", "book", "join"} <= verbs
    assert not {"our", "the", "your", "ledger", "free"} & verbs
    assert all(v == v.lower() and v.isalpha() for v in verbs)
    assert hb.cta_verb_ok("Start a free ledger", verbs)
    assert hb.cta_verb_ok("  Get started →", verbs)
    assert not hb.cta_verb_ok("Our ledger keeps every household bill sorted for you", verbs)
    assert not hb.cta_verb_ok("", verbs)


@pytest.mark.parametrize("text", [
    "Lorem ipsum dolor sit amet", "TODO: write this", "Hi {{ first_name }}", "mail help@example.com",
    "Your company here", "[Insert headline]", "Price: NaN", "[object Object]", "Coming soon",
])
def test_placeholder_patterns_catch(text):
    assert any(p.search(text) for p in hb.load_patterns())


@pytest.mark.parametrize("text", [
    "Know where your household money goes", "Fictional demo — no real accounts or payments.",
    "Setup takes about 5 minutes.", "Today you can see every bill", "Explore an example month",
    "© 2026 Lumen Ledger",
])
def test_placeholder_patterns_pass_real_copy(text):
    assert not any(p.search(text) for p in hb.load_patterns())


# ------------------------------------------------------------------ numbers against the brief's facts


FACTS = BRIEF["facts"]


@pytest.mark.parametrize("text,unsourced", [
    ("Plans cost $4 a month", []),
    ("12 groups and a 30-day trial", []),
    ("Setup takes about 5 minutes", []),
    ("Plans cost $5 a month", ["$5"]),
    ("Trusted by 40,000 households", ["40,000"]),
    ("Save 4% each month", ["4%"]),
    ("3x faster", ["3x"]),
    ("5k users", ["5k"]),
    ("4 groups", []),
    ("Version 2.5", ["2.5"]),
])
def test_number_matching(text, unsourced):
    assert hb.unsourced_numbers(text, FACTS) == unsourced


def test_number_tokens_normalise_commas_decimals_and_marks():
    toks = hb.number_tokens("$1,200.50 and 4.50 and 30% and 3x and 7 extra")
    assert [(c, n, s) for _, c, n, s in toks] == [("$", "1200.5", ""), ("", "4.5", ""), ("", "30", "%"),
                                                   ("", "3", "x"), ("", "7", "")]
    assert hb.unsourced_numbers("1,200 bills", ["We sort 1200 bills"]) == []


def test_footer_years_and_the_disclosure_line_are_exempt():
    raw = _raw("bar-v1/clean.html")
    rows = hb.score(raw, BRIEF)
    assert next(r for r in rows if r["check"] == "numbers")["pass"] is True
    assert "2026" in raw["widths"]["1440x900"]["bar"]["footer_text"]


# ------------------------------------------------------------------ OKLab and the window scan


def test_oklab_distance():
    assert hb.oklab_distance([29, 78, 216], [29, 78, 216]) == 0
    assert hb.oklab_distance([255, 255, 255], [0, 0, 0]) == pytest.approx(1.0, abs=1e-3)
    assert hb.oklab_distance([29, 78, 216], [30, 78, 217]) < 0.02
    assert hb.oklab_distance([29, 78, 216], [220, 38, 38]) > 0.02
    assert hb.oklab_distance([29, 78, 216], [37, 99, 235]) > 0.02


def test_window_scan_steps_half_a_screen():
    assert hb.window_max([100, 500], 900, 2000) == (2, 0)
    assert hb.window_max([100, 1000], 900, 2000) == (1, 0)
    assert hb.window_max([500, 1100], 900, 2000) == (2, 450)
    assert hb.window_max([], 900, 2000) == (0, 0)
    # The last window starts at the page's end or before it, never after.
    assert hb.window_max([1990], 900, 2000) == (1, 1350)


# ------------------------------------------------------------------ version 2 (queue #91), change by change


def _view(**bar):
    m = {"viewport": [1440, 900], "texts": [], "pictures": [], "html_pictures": [], "controls": [],
         "sections": [], "content_boxes": [], "body": []}
    m.update(bar)
    return {"bar": m}


# 1. A5 numbers: step labels, number words, pictures exposed as an image, derivations


def test_number_words_restate_brief_facts():
    assert hb.number_words("a one-hour slot, a ten-year history, twenty-one rooms, seven days") == [1, 10, 21, 7]
    assert hb.number_words("Someone often waits") == []
    fact = ["Rooms are booked in one-hour slots."]
    assert hb.unsourced_numbers("Book a 1 hour slot", fact) == []
    # A word number is a plain number: it does not source the same value with a currency or a suffix.
    assert hb.unsourced_numbers("$1 an hour, 1% off", fact) == ["$1", "1%"]


def test_step_labels_and_exposed_pictures_leave_the_claims():
    claims = {"drop": [{"kind": "step-label", "text": "01"}, {"kind": "step-label", "text": "02"},
                       {"kind": "image", "text": "$1,240 Rent"}],
              "names": [{"text": "Bills sorted into 12 groups"}]}
    text = "01 Link your bank 02 Name your groups $1,240 Rent $97 a year"
    shown = [t[0] for t in hb.page_number_tokens(text, claims)]
    assert shown == ["$97", "12"]
    # Each dropped number takes out one number shown the same way; a second one stays a claim.
    assert [t[0] for t in hb.page_number_tokens("01 and 01", {"drop": [{"text": "01"}]})] == ["01"]
    # A version 1 raw file has no claims: every number counts.
    assert [t[0] for t in hb.page_number_tokens(text, None)] == ["01", "02", "$1,240", "$97"]


DERIV_FACTS = ["Plans cost $4 a month after a 30-day free trial.",
               "The family add-on is $6 a month for up to four people."]


@pytest.mark.parametrize("entry,ok,why", [
    ({"shown": "$10", "operation": "add", "operands": ["$4", "$6"], "facts": DERIV_FACTS}, True, ""),
    ({"shown": "$10", "operation": "multiply", "operands": ["$4", "$6"], "facts": DERIV_FACTS}, False,
     "derivations.json: multiply gives $24, not $10"),
    ({"shown": "$24", "operation": "multiply", "operands": ["$6", "4"], "facts": DERIV_FACTS[1:]}, True, ""),
    ({"shown": "$10", "operation": "add", "operands": ["$4", "$6"], "facts": ["Plans cost $4 a month."]}, False,
     "derivations.json: $10 lists a fact not in the brief"),
    ({"shown": "$11", "operation": "add", "operands": ["$5", "$6"], "facts": DERIV_FACTS}, False,
     "derivations.json: operand $5 is not in its facts"),
    ({"shown": "$34", "operation": "add", "operands": ["30", "4"], "facts": DERIV_FACTS[:1]}, False,
     "derivations.json: operand 4 is not in its facts"),
    ({"shown": "$10", "operation": "concat", "operands": ["$4", "$6"], "facts": DERIV_FACTS}, False,
     "derivations.json: $10 has no known operation"),
])
def test_a_derivation_sources_its_number_only_when_it_recomputes(entry, ok, why):
    facts = DERIV_FACTS + ["Setup takes about 5 minutes."]
    assert hb.check_derivation(entry, facts) == (ok, why)


def test_possible_derivations_are_evidence_only():
    seat = ["Each seat is $18 a month."]
    assert hb.possible_derivation(hb.number_tokens("$36")[0], hb.fact_token_list(seat), hb.number_tokens("2 seats")) \
        == "$36 = 2 x $18"
    assert hb.possible_derivation(hb.number_tokens("$10")[0], hb.fact_token_list(DERIV_FACTS), []) == "$10 = $4 + $6"
    assert hb.possible_derivation(hb.number_tokens("$97")[0], hb.fact_token_list(DERIV_FACTS), []) is None
    # Neither number from the brief: no derivation is offered.
    assert hb.possible_derivation(hb.number_tokens("$36")[0], [], hb.number_tokens("2 seats at $18")) is None
    assert hb.unsourced_numbers("$36 for two", seat) == ["$36"]


def test_a_derived_number_needs_a_valid_derivations_file():
    raw = _raw2("bar-v2/c-derived-ok/index.html")
    brief = _brief2("bar-v2/c-derived-ok/index.html")
    row = next(r for r in hb.score(raw, brief) if r["check"] == "numbers")
    assert (row["value"], row["pass"]) == (0, True)
    bare = copy.deepcopy(raw)
    del bare["derivations"]
    row = next(r for r in hb.score(bare, brief) if r["check"] == "numbers")
    assert (row["value"], row["pass"]) == (1, False)
    assert row["evidence"][0]["text"] == "$10 = $4 + $6"


# 2. A1 visual anchor: pictures built in HTML


def _html_pic(cells, box=(100, 100, 400, 300), exposed=True, why="", anc=(), pics=()):
    return {"sel": "#mock", "kind": "role=img", "name": "A ledger", "exposed": exposed, "why": why,
            "cells": list(cells), "box": list(box), "sec": 0, "anc": list(anc), "pics": list(pics)}


def test_an_exposed_painted_html_picture_is_an_anchor():
    value, ok, evid = hb.check_width("visual-anchor", _view(html_pictures=[_html_pic([40, 100])]), BRIEF)
    assert (value, ok) == (1, True)
    assert evid[0]["selector"] == "#mock" and evid[0]["text"] == "html picture (role=img), painted 40%"
    # Exactly a third painted is enough.
    assert hb.check_width("visual-anchor", _view(html_pictures=[_html_pic([1, 3])]), BRIEF)[1] is True


@pytest.mark.parametrize("pic,text", [
    (_html_pic([60, 100], exposed=False, why="figure without figcaption or aria-labelledby"),
     "not exposed as an image: figure without figcaption or aria-labelledby"),
    (_html_pic([0, 100]), "painted 0% of its box, needs a third"),
    (_html_pic([32, 100]), "painted 32% of its box, needs a third"),
    (_html_pic([60, 100], box=(100, 100, 110, 300)), "110x300, needs 120x120 with half in the first screen"),
])
def test_an_html_picture_that_is_not_an_anchor_says_why(pic, text):
    value, ok, evid = hb.check_width("visual-anchor", _view(html_pictures=[pic]), BRIEF)
    assert (value, ok) == (0, False)
    assert evid == [hb.ev("#mock", text, pic["box"])]


def test_an_html_picture_below_the_first_screen_is_not_an_anchor():
    pic = _html_pic([60, 100], box=(100, 1200, 400, 300))
    assert hb.check_width("visual-anchor", _view(html_pictures=[pic]), BRIEF) == (0, False, [])


def test_one_anchor_counts_once():
    svg = {"sel": "svg.art", "kind": "svg", "box": [600, 100, 400, 400]}
    # An HTML picture around a counted picture adds nothing.
    view = _view(pictures=[svg], html_pictures=[_html_pic([90, 100], box=(560, 80, 480, 440), pics=[0])])
    assert hb.check_width("visual-anchor", view, BRIEF)[:2] == (1, True)
    # Nor does a painted HTML picture inside a counted one.
    view = _view(html_pictures=[_html_pic([50, 100]), _html_pic([90, 100], box=(120, 120, 200, 200), anc=[0])])
    assert hb.check_width("visual-anchor", view, BRIEF)[:2] == (1, True)


# 3. A1 call to action: normalised wording, else the most prominent filled button in the first screen


@pytest.mark.parametrize("text,want", [
    ("Explore demo rooms \u2193", "explore demo rooms"),
    ("  START a free   ledger! ", "start a free ledger"),
    ("\u203a Next steps\u2026", "next steps"),
    ("Book now \u2192 .", "book now"),
    ("> Go", "go"),
    ("Don't wait, book now!", "don't wait, book now"),
])
def test_cta_wording_is_normalised(text, want):
    assert hb.cta_norm(text) == want


def _ctl(i, text, y, w=200, h=50, filled=True):
    return {"i": i, "sel": f"#c{i}", "tag": "a", "role": None, "text": text, "box": [100, y, w, h],
            "bg": [29, 78, 216, 1] if filled else [0, 0, 0, 0], "bg_ratio": 6.2 if filled else 1.0}


ROOMS = {"cta": "Explore demo rooms"}


@pytest.mark.parametrize("controls,sel,rule", [
    ([_ctl(0, "Explore demo rooms \u2193", 400)], "#c0", "brief wording"),
    ([_ctl(0, "Try a sample booking", 400), _ctl(1, "Explore demo rooms", 2000)], "#c0",
     "most prominent filled button in the first screen"),
    ([_ctl(0, "Sign in", 20, 90, 40), _ctl(1, "Try a sample booking", 400)], "#c1",
     "most prominent filled button in the first screen"),
    ([_ctl(0, "See pricing", 400, filled=False), _ctl(1, "Explore demo rooms", 2000)], "#c1",
     "brief wording, outside the first screen"),
    ([_ctl(0, "See pricing", 400, filled=False), _ctl(1, "Book", 1500), _ctl(2, "Book a room today", 2500, 300)],
     "#c2", "largest filled button on the page"),
])
def test_the_primary_cta_and_the_rule_that_picked_it(controls, sel, rule):
    c, why = hb.pick_cta({"viewport": [1440, 900], "controls": controls}, ROOMS)
    assert (c["sel"], why) == (sel, rule)


def test_cta_wording_flags_a_primary_cta_other_than_the_briefs():
    def raw_of(controls):
        return {"widths": {"1440x900": {"bar": {"viewport": [1440, 900], "controls": controls}}}}
    row = hb.check_all("cta-wording", raw_of([_ctl(0, "Explore demo rooms \u2193", 400)]), ROOMS, set(), [])
    assert row[:2] == ("Explore demo rooms \u2193", True)
    value, ok, evid = hb.check_all("cta-wording", raw_of([_ctl(0, "Try a sample booking", 400),
                                                          _ctl(1, "Explore demo rooms", 2000)]), ROOMS, set(), [])
    assert (value, ok) == ("Try a sample booking", False)
    assert [e["text"] for e in evid] == ["Try a sample booking", "most prominent filled button in the first screen",
                                         "Explore demo rooms"]
    assert hb.check_all("cta-wording", raw_of([_ctl(0, "Go", 400)]), {}, set(), [])[:2] == \
        ("brief has no call to action", None)


# 4. A2 rhythm: the gap under the page header


def test_the_gap_under_the_banner_is_not_a_section_gap():
    sections = [{"sel": "header.site-head", "banner": True}, {"sel": "section.hero"}, {"sel": "section.features"}]
    boxes = [[[0, 40, 0], [50, 70, 0]], [[70, 200, 1], [216, 400, 1]], [[464, 600, 2], [616, 800, 2]]]
    value, ok, evid = hb.check_width("rhythm", _view(sections=sections, content_boxes=boxes), BRIEF)
    assert ok is True and value == "smallest gap between sections 64px, median inside 16px"
    # Without the banner flag the header's flush gap is a section gap, as in version 1.
    sections[0].pop("banner")
    value, ok, evid = hb.check_width("rhythm", _view(sections=sections, content_boxes=boxes), BRIEF)
    assert ok is False and evid[0]["selector"] == "header.site-head | section.hero"


def test_header_flush_case_passes_only_because_of_the_banner_rule():
    raw = _raw2("bar-v2/i-header-flush.html")
    for wk in hb.FIRST:
        assert hb.check_width("rhythm", raw["widths"][wk], BRIEF)[1] is True
    for v in raw["widths"].values():
        for s in v["bar"]["sections"]:
            s.pop("banner", None)
    for wk in hb.FIRST:
        assert hb.check_width("rhythm", raw["widths"][wk], BRIEF)[1] is False


# 5. A3 measure: running text only


def _block(line_chars, sel="p"):
    return {"sel": sel, "text": "x", "lines": len(line_chars), "line_chars": line_chars, "box": [0, 0, 10, 10]}


def test_measure_counts_running_text_only():
    cells = [_block([1], f"span.cell-{k}") for k in range(14)]
    label = _block([12], "span.label")
    para = _block([70, 72, 30])
    one_line = _block([60], "p.one-line")
    body = [{"blocks": cells + [label, para, one_line]}]
    assert hb.check_width("measure", _view(body=body), BRIEF)[:2] == (100.0, True)
    # A one-line block of 60 or more characters counts with its one line.
    body = [{"blocks": [para, _block([95], "p.wide")]}]
    value, ok, evid = hb.check_width("measure", _view(body=body), BRIEF)
    assert (value, ok) == (50.0, False) and evid[0]["selector"] == "p.wide"
    # Under 60 characters on one line is a label, not running text.
    assert hb.check_width("measure", _view(body=[{"blocks": [_block([59])]}]), BRIEF) == ("no running text", True, [])


def test_flap_cells_case_passes_only_because_of_the_running_text_rule():
    raw = _raw2("bar-v2/j-flap-cells.html")
    view = raw["widths"]["1440x900"]
    assert hb.check_width("measure", view, BRIEF)[1] is True
    for b in view["bar"]["body"]:
        b.pop("blocks", None)
    assert hb.check_width("measure", view, BRIEF)[1] is False


# 6. A7 word-split


def test_word_split_counts_words_broken_without_a_hyphen():
    split = {"sel": "#split-heading", "text": "Telecommunicatio / ns", "box": [24, 300, 272, 76]}
    assert hb.check_width("word-split", _view(word_splits=[]), BRIEF) == (0, True, [])
    assert hb.check_width("word-split", _view(word_splits=[split]), BRIEF) == \
        (1, False, [hb.ev("#split-heading", "Telecommunicatio / ns", [24, 300, 272, 76])])
    # A raw file measured before version 2 has no word boxes: not measured, never a pass.
    assert hb.check_width("word-split", _view(), BRIEF) == ("not measured", None, [])


def test_long_word_case_splits_at_320_only():
    raw = _raw2("bar-v2/k-long-word.html")
    got = {wk: hb.check_width("word-split", raw["widths"][wk], BRIEF)[0] for wk in hb.WIDTHS}
    assert got == {"1440x900": 0, "1024x768": 0, "768x1024": 0, "390x844": 0, "320x568": 1}


# The output contract only gains rows


# Part 1's rows (45b8bd7d), in order, with their widths.
V1_CHECKS = [
    ("A1", "product-name", "2"), ("A1", "h1-words", "2"), ("A1", "cta-in-view", "2"), ("A1", "visual-anchor", "2"),
    ("A2", "one-h1", "2"), ("A2", "h1-largest", "2"), ("A2", "primary-per-window", "5"), ("A2", "font-sizes", "5"),
    ("A2", "section-sizes", "5"), ("A2", "section-colours", "5"), ("A2", "spacing-grid", "5"), ("A2", "rhythm", "2"),
    ("A3", "body-size", "5"), ("A3", "line-height", "5"), ("A3", "measure", "1440"), ("A3", "fk-grade", "1440"),
    ("A4", "axe", "2"), ("A4", "text-contrast", "5"), ("A4", "targets", "5"), ("A4", "no-hscroll", "5"),
    ("A4", "headings", "2"), ("A4", "landmarks", "2"), ("A4", "lang", "2"), ("A4", "img-alt", "2"),
    ("A4", "svg-names", "2"), ("A5", "cta-length", "all"), ("A5", "cta-verb", "all"), ("A5", "disclosure", "all"),
    ("A5", "placeholders", "all"), ("A5", "numbers", "all"), ("A7", "overlap", "5"), ("A7", "clipped", "5"),
]


def test_version_2_adds_rows_and_renames_none():
    rows = [(b, c, s) for b, c, s, _ in hb.CHECKS if b != "A11"]
    assert [x for x in rows if (x[0], x[1]) not in hb.ADDED] == V1_CHECKS
    assert hb.ADDED == {("A5", "cta-wording"), ("A7", "word-split")}
    assert rows.index(("A5", "cta-wording", "all")) == rows.index(("A5", "numbers", "all")) + 1
    assert rows.index(("A7", "word-split", "5")) == rows.index(("A7", "clipped", "5")) + 1


def test_version_3_adds_the_a11_rows_after_a7():
    rows = [(b, c, s) for b, c, s, _ in hb.CHECKS]
    a11 = [x for x in rows if x[0] == "A11"]
    assert a11 == [("A11", "depth-levels", "2"), ("A11", "depth-overlap", "2"), ("A11", "layout-neighbours", "1440"),
                   ("A11", "layout-bento", "1440"), ("A11", "layout-runs", "2"), ("A11", "data-drawn", "2"),
                   ("A11", "display-type", "2")]
    assert rows[rows.index(("A7", "word-split", "5")) + 1:] == a11
    assert hb.A11_ROWS == {c for _, c, _ in a11}


# ------------------------------------------------------------------ A11, modern and dynamic (version 3, queue #112)
# bar-a11-v1/expected.json was written and sealed (~/design-lab/seals/bar-a11-v1.json) before the A11 code
# (d9c4d47c, where the tests that needed the code were xfail strict).

FIX3 = ROOT / "configs/design/testpages/bar-a11-v1"
KEY3 = json.loads((FIX3 / "expected.json").read_text(encoding="utf-8"))
PAGES3 = sorted(KEY3["pages"])
KEY_A11_SHA256 = "efd56660e0fbbf6807cabbc1f5ec91b81dd3556f6d09c4a3d09f931266fa3c01"


def _raw3(page):
    return json.loads((FIX3 / "raw" / f"{hb.raw_name(page)}.json").read_text(encoding="utf-8"))


def _brief3(page):
    return json.loads((ROOT / KEY3["site"] / KEY3["pages"][page]["brief"]).read_text(encoding="utf-8"))


def test_bar_a11_key_is_sealed():
    assert hashlib.sha256((FIX3 / "expected.json").read_bytes()).hexdigest() == KEY_A11_SHA256


def test_bar_a11_key_covers_every_a11_row_and_page():
    checks = {tuple(c) for c in KEY3["checks"]}
    assert len(checks) == 12 and {b for b, _, _ in checks} == {"A11"}
    assert {w for _, _, w in checks} == {"1440x900", "390x844"}
    assert {c for _, c, w in checks if w == "390x844"} == {"depth-levels", "depth-overlap", "layout-runs", "data-drawn",
                                                           "display-type"}
    assert sorted("bar-a11-v1/" + p.name for p in FIX3.glob("*.html")) == PAGES3
    broken = set()
    for page in PAGES3:
        k = KEY3["pages"][page]
        failing = {tuple(x) for x in k["failing"]}
        assert failing <= checks, page
        broken |= {(b, c) for b, c, _ in failing}
        for spec in k["rows"]:
            row = (spec["bar"], spec["check"], spec["width"])
            assert row in checks and (spec["pass"] is False) == (row in failing), (page, row)
    assert broken == {(b, c) for b, c, _ in checks}
    assert {tuple(x) for x in KEY3["pages"]["bar-a11-v1/flat.html"]["failing"]} == checks
    assert KEY3["pages"]["bar-a11-v1/clean-rich.html"]["failing"] == []


def test_the_meter_has_the_a11_rows():
    rows = {(b, c, w) for b, c, s, _ in hb.CHECKS if b == "A11" for w in hb.widths_of(s)}
    assert rows == {tuple(c) for c in KEY3["checks"]}
    assert hb.VERSION == 3


@pytest.mark.parametrize("page", PAGES3)
def test_bar_a11_recorded_page_matches_its_key(page):
    res = hb.key_match(page, hb.score(_raw3(page), _brief3(page)), KEY, KEY2, KEY3)
    assert res["missing"] == [], "missing failing rows"
    assert res["extra"] == [], "extra failing rows"
    assert res["rows"] == [], "keyed rows differ"


@pytest.mark.parametrize("page", PAGES3)
def test_bar_a11_recorded_raw_is_of_the_current_page(page):
    raw = _raw3(page)
    assert raw["version"] == 3
    assert raw["page_sha256"] == hashlib.sha256((ROOT / KEY3["site"] / page).read_bytes()).hexdigest()
    assert sorted(raw["widths"]) == sorted(hb.WIDTHS)
    assert all("error" not in v for v in raw["widths"].values())
    assert all(("a11" in v["bar"]) == (wk in hb.FIRST) for wk, v in raw["widths"].items())


# The doc's keyed cases for (c): each text and the figures found in it, as (kind, text).
A11_FIGURE_CASES = [
    ("Spending is up 12% this month", [("trend", "up 12%")]),
    ("3 of 5 rooms booked", [("part", "3 of 5")]),
    ("Rated 4/5 stars", [("part", "4/5")]),
    ("+8 bookings this week", [("trend", "+8")]),
    ("\u22123 days to pay", [("trend", "\u22123")]),
    ("down 2 hours a week", [("trend", "down 2 hours")]),
    ("\u25b2 4 new", [("trend", "\u25b2 4")]),
    ("Step 2 of 3", [("progress", "Step 2 of 3")]),
    ("40% saved", [("share", "40%")]),
    ("4 out of 5 households", [("part", "4 out of 5")]),
    ("12.5% back", [("share", "12.5%")]),
    ("-12% (down)", [("trend", "-12%")]),
    ("6 of 5,000 bills", [("part", "6 of 5,000")]),
    ("100% free", [("share", "100%")]),
    ("Tue 10/20", [("part", "10/20")]),
    ("7 of 9 paid \u00b7 Occupancy\n82%", [("part", "7 of 9"), ("share", "82%")]),
    ("$12 a month", []), ("$4/mo", []), ("\u20ac9.99 per month", []),
    ("Oct 19, 2026", []), ("19 October 2026", []), ("2026-10-19", []), ("10/19/2026", []), ("May 5 update", []),
    ("9:30 am", []), ("10 pm", []),
    ("v2.1", []), ("version 3.2", []), ("Release 4", []), ("2.1.0", []),
    ("+1 (555) 010-0100", []),
    ("24/7 support", []), ("5 of 3", []), ("0 of 0", []),
    ("ages 3-5", []), ("COVID-19", []), ("12 groups", []), ("2x faster", []), ("up 3 floors", []),
]


@pytest.mark.parametrize("text,want", A11_FIGURE_CASES)
def test_a11_figures_follow_the_docs_patterns(text, want):
    assert hb.a11_figures(text) == want


def test_a11_patterns_are_the_docs_in_its_order():
    doc = (ROOT / "docs/design-homepage-bar.md").read_text(encoding="utf-8")
    for p in (hb.A11_NUM, hb.A11_MONTH):
        assert f"`{p}`" in doc
    for name, p in hb.A11_LEFT_OUT:
        assert f"- {name}: `{p}`" in doc, name
    for group in (hb.A11_LEFT_OUT, hb.A11_FIGURES):
        at = [doc.index(f"`{p}`") for _, p in group]
        assert at == sorted(at)
    assert [k for k, _ in hb.A11_FIGURES] == ["progress", "trend", "trend", "trend", "part", "part", "share"]


@pytest.mark.parametrize("page", PAGES3)
def test_a11_rows_follow_the_contract(page):
    rows = [r for r in hb.score(_raw3(page), _brief3(page)) if r["bar"] == "A11"]
    assert [(r["bar"], r["check"], r["width"]) for r in rows] == [tuple(c) for c in KEY3["checks"]]
    for r in rows:
        assert r["pass"] in (True, False) and len(r["evidence"]) <= 5
        for e in r["evidence"]:
            assert set(e) == {"selector", "text", "box"} and len(e["text"]) <= 80 and len(e["box"]) == 4


# The scorer's A11 readings on hand-made raw facts (no browser), at the doc's numbers.


def _surface(up, colour, blur=0, box=(0, 0, 300, 200), ctl=False, layers=()):
    return {"sel": f"s{len(colour)}", "box": list(box), "up": up, "ctl": ctl, "base": list(colour),
            "layers": [list(x) for x in layers], "blur": blur}


def _levels(page, *cands):
    return hb.a11_levels({"page": {"base": list(page), "layers": []}, "cands": list(cands)})


@pytest.mark.parametrize("colour,step", [((0xEF, 0xF0, 0xEF), False), ((0xF0, 0xF0, 0xF0), True)])
def test_a_lightness_step_is_3_l_points(colour, step):
    info = _levels((0xE6, 0xE6, 0xE6), _surface(-1, colour))
    assert info[0]["step"] is step and info[0]["level"] == (2 if step else 1)


@pytest.mark.parametrize("blur,behind,level", [(3, 0, 2), (4, 0, 3), (4, 4, 2), (8, 4, 3)])
def test_a_shadow_step_needs_4_px_of_blur_over_less_behind(blur, behind, level):
    tint = (0xE0, 0xE7, 0xFF)
    info = _levels((255, 255, 255), _surface(-1, tint, blur=behind), _surface(0, tint, blur=blur))
    assert info[1]["level"] == level


def test_small_boxes_and_controls_are_not_surfaces():
    a = {"page": {"base": [255, 255, 255], "layers": []},
         "cands": [_surface(-1, (0, 0, 0), box=(0, 0, 119, 200)), _surface(-1, (0, 0, 0), box=(0, 0, 120, 47)),
                   _surface(-1, (0, 0, 0), ctl=True), _surface(-1, (0, 0, 0), box=(0, 0, 120, 48))]}
    assert hb.a11_surfaces(a) == {3}


def test_a_gradient_surface_takes_the_mean_l_of_its_layers():
    s = _surface(-1, (255, 255, 255), layers=[[(0, 0, 0, 1), (255, 255, 255, 1)]])
    assert _levels((255, 255, 255), s)[0]["light"] == pytest.approx(50.0)


@pytest.mark.parametrize("v,px,side", [
    ((0, -24, 100, 100), 24, "top"),    # 24 px out above, 76 px in
    ((0, -90, 100, 100), 10, "top"),    # 90 px out, 10 px in: the smaller
    ((0, 0, 100, 100), 0, ""),          # inside, touching the top edge
    ((380, 20, 100, 100), 20, "right"),  # 80 px out on the right, 20 px in
    ((420, 20, 100, 100), 0, ""),        # wholly outside, to the right
    ((0, 300, 100, 100), 0, ""),        # below, not touching
])
def test_a_crossing_is_the_smaller_reach_on_either_side_of_an_edge(v, px, side):
    assert hb.a11_cross(list(v), [0, 0, 400, 200]) == (px, side)


def _blk(x, y, w, h, kind="text"):
    return {"sel": "b", "box": [x, y, w, h], "visual": kind == "picture", "cover": 0, "text": kind == "text"}


def test_a_layout_signature_counts_columns_and_reads_kinds_in_order():
    split = [_blk(0, 0, 500, 300), _blk(540, 0, 500, 300, "picture")]
    assert hb.a11_signature(split) == "2:text-picture"
    stack = [_blk(100, 0, 800, 60), _blk(0, 80, 1000, 300), _blk(104, 400, 790, 60)]
    assert hb.a11_signature(stack) == "1:text"
    bento = [_blk(0, 0, 600, 500, "picture"), _blk(624, 0, 300, 238), _blk(948, 0, 300, 238), _blk(624, 262, 624, 238)]
    assert hb.a11_signature(bento) == "3:picture-text"


@pytest.mark.parametrize("shift,cols", [(8, 3), (9, 5)])
def test_columns_cluster_left_edges_within_8_px(shift, cols):
    row1 = [_blk(x, 0, 290, 100) for x in (0, 300, 600)]
    row2 = [_blk(x + shift, 120, 280, 100) for x in (0, 300)]
    assert hb.a11_signature(row1 + row2) == f"{cols}:text"


@pytest.mark.parametrize("w,ok", [(372, False), (375, True)])
def test_a_bento_grid_needs_widths_25_percent_apart(w, ok):
    blocks = [_blk(0, 0, w, 400), _blk(w + 24, 0, 300, 400), _blk(w + 348, 0, 300, 400)]
    assert hb.a11_bento(blocks)[0] is ok


def test_a_bento_grid_by_height_needs_two_blocks_side_by_side():
    tall = [_blk(0, 0, 300, 500), _blk(324, 0, 300, 400), _blk(648, 0, 300, 400)]
    assert hb.a11_bento(tall)[0] is True
    two = [_blk(0, 0, 300, 500), _blk(324, 0, 300, 400)]
    assert hb.a11_bento(two)[0] is False


def test_a_run_splits_where_a_size_moves_more_than_4_px():
    boxes = [[0, i * 60, 300, 50] for i in range(5)] + [[0, 300, 300, 55], [0, 360, 300, 55]]
    runs = hb.a11_runs({"runs": [{"sel": "li.row", "boxes": boxes}]})
    assert [n for n, _, _ in runs] == [5, 2]
    four = hb.a11_runs({"runs": [{"sel": "li.row", "boxes": boxes[:4]}]})
    assert four[0][0] == 4


def _fill(box, track, parent=0, flow=False):
    return {"sel": "f", "box": list(box), "track": list(track), "parent": parent, "flow": flow}


def test_a_bar_falls_short_of_its_track_on_the_long_side_only():
    fills = [_fill((0, 0, 226, 8), (0, 0, 301.34, 8), parent=1),     # a progress fill
             _fill((0, 0, 300, 1), (0, 0, 300, 1), parent=2),        # a divider as long as its parent
             _fill((0, 0, 300, 1), (0, 0, 300.8, 1), parent=3),      # within 1 px: not a bar
             _fill((0, 40, 8, 60), (0, 0, 8, 100), parent=4)]        # an upright fill
    assert hb.a11_bars(fills) == [0, 3]
    chart = [_fill((0, 50, 20, 50), (0, 0, 100, 100), parent=5, flow=True),
             _fill((24, 20, 20, 80), (0, 0, 100, 100), parent=5, flow=True)]
    assert hb.a11_bars(chart) == [0, 1]


@pytest.mark.parametrize("size,ok", [(52.2, False), (54, True)])
def test_display_type_is_met_at_3_times_the_body(size, ok):
    m = {"viewport": [1440, 900], "a11": {},
         "body": [{"size": 18, "text": "one two three four five six seven eight nine"},
                  {"size": 16, "text": "a b c"}],
         "texts": [{"sel": "h1", "text": "Big", "size": size, "lines": [[0, 100, 400, size * 1.1]]},
                   {"sel": "p.below", "text": "Far", "size": 90, "lines": [[0, 2000, 400, 99]]}]}
    value, passed, evid = hb.check_a11("display-type", m)
    assert passed is ok and value.endswith(" / 18px = " + ("2.9" if not ok else "3"))
    assert evid[0]["selector"] == "h1"
