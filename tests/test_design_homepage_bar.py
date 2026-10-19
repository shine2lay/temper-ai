"""Model-free tests for Design's homepage A-bar meter, part 1 (queue #78).

configs/design/bin/design_homepage_bar.js measures a page in temper's playwright-mcp browser;
design_homepage_bar.py scores the raw measurements against BAR.md's A bars. No browser here:
configs/design/testpages/bar-v1/raw/*.json were recorded from the bar-v1 fixture pages
(`design_homepage_bar.py --fixture-proof --record`), and expected.json, written before the meter,
lists each page's exact failing (bar, check, width) rows. Definitions: docs/design-homepage-bar.md.
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
sys.path.insert(0, str(BIN))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, BIN / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


hb = _load("design_homepage_bar")
KEY = json.loads((FIX / "expected.json").read_text(encoding="utf-8"))
BRIEF = json.loads((FIX / "brief.json").read_text(encoding="utf-8"))
PAGES = sorted(KEY["pages"])


def _raw(page):
    return json.loads((FIX / "raw" / f"{Path(page).stem}.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------------ the fixture key


@pytest.mark.parametrize("page", PAGES)
def test_recorded_page_scores_exactly_the_key(page):
    raw = _raw(page)
    rows = hb.score(raw, BRIEF)
    got = hb.failing(rows)
    want = {tuple(x) for x in KEY["pages"][page]}
    assert sorted(want - got) == [], "missing failing rows"
    assert sorted(got - want) == [], "extra failing rows"


@pytest.mark.parametrize("page", PAGES)
def test_recorded_raw_is_of_the_current_page(page):
    raw = _raw(page)
    html = ROOT / KEY["site"] / page
    assert raw["page_sha256"] == hashlib.sha256(html.read_bytes()).hexdigest()
    assert sorted(raw["widths"]) == sorted(hb.WIDTHS)
    assert all("error" not in v for v in raw["widths"].values())


def test_clean_page_passes_every_row():
    rows = hb.score(_raw("bar-v1/clean.html"), BRIEF)
    assert rows and all(r["pass"] is True for r in rows)


def test_planted_pages_break_every_check_at_least_once():
    broken = {(b, c) for page in PAGES for b, c, _ in KEY["pages"][page]}
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
    assert every["cta-length"] is True and every["cta-verb"] is True
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
