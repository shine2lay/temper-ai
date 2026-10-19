"""design_word_checks.py (H7, W4d): the countable word rules of the content critic, checked by script.

Every rule has a case it must catch, a case at its line and a false-alarm trap, all on made-up
decks and pages (a tide planner called Tidebook), so the sealed words-v1 cases stay unseen:

- cta_length: 41 characters caught, 40 passes, an arrow at the end is not counted.
- cta_verb: "Your first paddle" and "Pricing" caught; verb forms ("Let's", "Sign-up", title case) pass;
  links in the header, inside a sentence or starting with a question word are not calls to action.
- unsourced_name: a name mid-sentence caught; a name the facts hold passes, one word more is caught;
  a capital starting a sentence, the product name, title-case headings and common words pass.
- long_paragraph: 271 characters caught, 270 passes, headings are not paragraphs, a paragraph
  split by a link is joined again.
- renamed_term: a term with one word changed, or another phrase in its place, caught; plural and
  hyphen forms pass; a synonym inside quotation marks is not a rename.

The rules table quotes the critic and craft configs word for word, and BAR.md when it is on the host.
"""

import copy
import importlib.util
import json
import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
BIN = ROOT / "configs" / "design" / "bin"
VERBS = ROOT / "configs" / "design" / "knowledge" / "cta-verbs.txt"
BAR = pathlib.Path.home() / "design-lab" / "homepage-workflow" / "BAR.md"
sys.path.insert(0, str(BIN))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, BIN / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


wc = _load("design_word_checks")

BRIEF = {
    "product": "Tidebook",
    "fictional": True,
    "category": "tide planner app",
    "audience": "sea kayakers who plan their own trips",
    "purpose": "get a paddler to plan a first trip",
    "cta": "Plan your first paddle",
    "disclosure": "Tidebook is a made-up product for a design exercise.",
    "facts": [
        "Tidebook shows tide times for 1,200 harbours",
        "Plans sync between phone and watch",
        "Free for 30 days, then 4 pounds a month",
        "Tide data comes from the Coastal Survey Office",
    ],
}

DECK = {
    "promise": "Know the tide before you launch.",
    "headlines": ["Plan around the tide, not against it"],
    "subhead": "Tidebook shows tide times for 1,200 harbours, so you pick a safe window in a minute.",
    "proof_points": [
        {"title": "Tide windows", "text": "See when the water is slack at your launch spot."},
        {"title": "On your wrist", "text": "Plans sync between phone and watch."},
        {"title": "Survey data", "text": "Tide data comes from the Coastal Survey Office."},
    ],
    "ctas": {"primary": "Plan your first paddle", "secondary": "See a sample plan"},
    "faq": [
        {"q": "What does it cost?", "a": "Free for 30 days, then 4 pounds a month."},
        {"q": "What is a tide window?", "a": "The hours when the current is weak enough to paddle."},
    ],
    "terms": [{"term": "tide window", "meaning": "the hours when the current is weak enough to paddle"}],
    "worked_examples": [{"topic": "A morning trip",
                         "example": "High water at 9:10 gives a tide window from 8:30 to 9:50."}],
    "notices": [{"id": "disclosure", "text": "Tidebook is a made-up product for a design exercise."}],
    "voice": "calm, practical",
}

PAGE_MD = """# Page text at 1440 px (made up for these tests)

## header
- [a] Tidebook
- [a] Pricing
- [a] Log in
## hero
- [h1] Plan around the tide, not against it
- [p] Tidebook shows tide times for 1,200 harbours, so you pick a safe window in a minute.
- [a] Plan your first paddle
- [a] See a sample plan
- [a] How it works
## proof
- [h3] Tide windows
- [p] See when the water is slack at your launch spot.
- [h3] On your wrist
- [p] Plans sync between phone and watch.
- [h3] Survey data
- [p] Tide data comes from the Coastal Survey Office.
## example
- [h2] A morning trip
- [p] High water at 9:10 gives a tide window from 8:30 to 9:50.
## faq
- [h2] Questions
- [summary] What does it cost?
- [p] Free for 30 days, then 4 pounds a month.
- [summary] What is a tide window?
- [p] The hours when the current is weak enough to paddle.
## closing
- [h2] Know the tide before you launch.
- [a] Plan your first paddle
## footer
- [small] Tidebook is a made-up product for a design exercise.
- [a] Privacy
"""

CTA_40 = "Plan a safe first paddle around the tide"
CTA_41 = "Plan a safe first paddle around the tides"
NO_TERM = ("Tide windows", "Launch times")  # a page swap: the proof title that holds the deck's term, swapped out


def deck(**changes):
    d = copy.deepcopy(DECK)
    for path, value in changes.items():
        node = d
        keys = path.split("__")
        for k in keys[:-1]:
            node = node[int(k)] if isinstance(node, list) else node[k]
        last = keys[-1]
        if isinstance(node, list):
            node[int(last)] = value
        else:
            node[last] = value
    return d


def page(*swaps, md=PAGE_MD):
    """The clean page with whole lines swapped: (old line text, new line text or None to drop it)."""
    lines = wc.parse_page_md(md)
    for old, new in swaps:
        hits = [i for i, ln in enumerate(lines) if ln["text"] == old]
        assert hits, f"no line {old!r}"
        for i in reversed(hits):
            if new is None:
                del lines[i]
            else:
                lines[i] = {**lines[i], "text": new}
    return lines


def lines_of(*rows, section="body"):
    """Page lines from (tag, text) pairs, all in one section unless the pair has a third item."""
    return [{"section": r[2] if len(r) > 2 else section, "tag": r[0], "text": r[1]} for r in rows]


def rules(report, rule=None):
    return [f for f in report["findings"] if rule is None or f["rule"] == rule]


def texts(report, rule):
    return [f["text"] for f in rules(report, rule)]


def test_cta_boundary_strings_are_40_and_41_characters():
    assert (len(CTA_40), len(CTA_41)) == (40, 41)


# ---------------------------------------------------------------- clean cases


def test_clean_deck_gives_no_findings():
    report = wc.check_deck(DECK, BRIEF)
    assert report["findings"] == []
    assert report["counts"] == {"Must": 0, "Should": 0, "Could": 0}


def test_clean_page_gives_no_findings():
    assert wc.check_page(page(), DECK, BRIEF)["findings"] == []


# ---------------------------------------------------------------- cta_length


def test_cta_length_catch_deck_41_characters():
    found = rules(wc.check_deck(deck(ctas__secondary=CTA_41), BRIEF), "cta_length")
    assert [(f["field"], f["severity"], f["grade"]) for f in found] == [("ctas.secondary", 2, "Must")]
    assert found[0]["evidence"].startswith("41 characters")


def test_cta_length_catch_page_hero_and_closing_give_one_finding():
    lines = page(("Plan your first paddle", "Plan your first paddle with tide times for 1,200 harbours"))
    found = rules(wc.check_page(lines, DECK, BRIEF), "cta_length")
    assert len(found) == 1
    assert found[0]["element"] == "hero [a]" and found[0]["line"] == 6
    assert found[0]["evidence"].endswith("also at line 23 (closing [a])")


def test_cta_length_boundary_40_characters_pass_deck_and_page():
    assert rules(wc.check_deck(deck(ctas__primary=CTA_40), BRIEF)) == []
    lines = page(("Plan your first paddle", CTA_40))
    assert rules(wc.check_page(lines, deck(ctas__primary=CTA_40), BRIEF)) == []


@pytest.mark.parametrize("label", [CTA_40 + " \u2192", "\u2192 " + CTA_40, CTA_40.replace(" ", "   ")])
def test_cta_length_trap_arrows_and_spaces_are_not_counted(label):
    assert rules(wc.check_deck(deck(ctas__primary=label), BRIEF), "cta_length") == []


# ---------------------------------------------------------------- cta_verb


def test_cta_verb_catch_deck_primary_level_3_other_level_2():
    report = wc.check_deck(deck(ctas__primary="Your first paddle", ctas__secondary="Pricing"), BRIEF)
    found = [(f["field"], f["severity"], f["grade"]) for f in rules(report, "cta_verb")]
    assert found == [("ctas.primary", 3, "Must"), ("ctas.secondary", 2, "Must")]


@pytest.mark.parametrize("label", ["Free trial", "Tidebook for teams", "Next", "More tide times", "\u2192"])
def test_cta_verb_catch_labels_that_are_not_actions(label):
    assert texts(wc.check_deck(deck(ctas__secondary=label), BRIEF), "cta_verb") == [label]


def test_cta_verb_catch_page_hero_button_that_drifted_from_the_deck():
    lines = page(("Plan your first paddle", "Your first paddle"))
    found = rules(wc.check_page(lines, DECK, BRIEF), "cta_verb")
    assert [(f["element"], f["severity"]) for f in found] == [("hero [a]", 3)]
    assert found[0]["evidence"].endswith("also at line 23 (closing [a])")


@pytest.mark.parametrize("label", ["Let's plan your trip", "Let\u2019s plan your trip", "Sign-up for free",
                                   "Start Your Free Trial", "RSVP for the open day", "\u2192 Plan a trip",
                                   "Get started", "Try it free", "Book a demo", "Download for iOS"])
def test_cta_verb_boundary_verb_forms_pass(label):
    assert rules(wc.check_deck(deck(ctas__secondary=label), BRIEF), "cta_verb") == []


def test_cta_trap_links_that_are_not_calls_to_action():
    # Each of these would be a finding if it counted as a call to action.
    lines = page()
    assert lines[7]["text"] == "How it works"  # the hero's last line
    lines[8:8] = lines_of(
        ("p", "Tide data comes from the"), ("a", "Coastal Survey Office"), ("p", ", checked every day."),  # in a sentence
        ("button", "What is slack water?"),  # a question
        ("a", "Tidebook"),  # the logo link
        section="hero")
    lines += lines_of(("p", "Before you go,"), ("a", "read the tide guide for every harbour on the south coast"),
                      ("p", "first."), section="closing")  # a long link inside a sentence
    lines += lines_of(("a", "Download the full tide table for every harbour in the country"),
                      section="site-footer")  # the footer
    report = wc.check_page(lines, DECK, BRIEF)
    assert report["findings"] == []
    # Control: the same links as stand-alone hero buttons are findings.
    alone = page()
    alone[8:8] = lines_of(("a", "Coastal Survey Office"),
                          ("a", "Download the full tide table for every harbour in the country"), section="hero")
    assert [f["rule"] for f in wc.check_page(alone, DECK, BRIEF)["findings"]] == ["cta_verb", "cta_length"]


def test_cta_verb_trap_page_without_named_sections_has_no_hero():
    # Without data-section names every line falls in one fallback section; its links are not all hero CTAs.
    rows = lines_of(("h1", "Plan around the tide, not against it"), ("a", "Plan your first paddle"),
                    ("a", "Pricing"), ("p", "See when the water is slack at your launch spot."), ("a", "Tide tables"),
                    section="page")
    assert wc.check_page(rows, DECK, BRIEF)["findings"] == []
    rows[1] = {**rows[1], "text": "Your first paddle"}  # the deck's primary CTA, drifted: still caught
    found = rules(wc.check_page(rows, DECK, BRIEF), "cta_verb")
    assert [(f["line"], f["severity"]) for f in found] == [(2, 3)]


def test_cta_verb_trap_page_hero_link_starting_with_a_question_word():
    report = wc.check_page(page(("How it works", "How Tidebook reads the tide")), DECK, BRIEF)
    assert rules(report, "cta_verb") == []


# ---------------------------------------------------------------- unsourced_name


def test_unsourced_name_catch_deck_name_mid_sentence():
    d = deck(proof_points__1__text="Plans sync between phone and watch, and the Kayak Club of Wales uses it.")
    found = rules(wc.check_deck(d, BRIEF), "unsourced_name")
    assert [(f["field"], f["text"], f["severity"], f["grade"]) for f in found] == [
        ("proof_points[2].text", "Kayak Club of Wales", 4, "Must")]


def test_unsourced_name_catch_page_brand_and_person():
    lines = page(("Plans sync between phone and watch.", "Plans sync between phone and Garmin watches."),
                 ("The hours when the current is weak enough to paddle.",
                  "\u201cThe best tide app I have used\u201d says Ana Silva."))
    found = rules(wc.check_page(lines, DECK, BRIEF), "unsourced_name")
    assert [(f["text"], f["element"]) for f in found] == [("Garmin", "proof [p]"), ("Ana Silva", "faq [p]")]


@pytest.mark.parametrize("sentence, name", [
    ("Dr. Ada Lovelace planned her trips with it.", "Ada Lovelace"),
    ("Paddlers at Porthleven love it.", "Porthleven"),
    ("It works on iPhone.", "iPhone"),
    ("Our RYA-approved plans keep you safe.", "RYA-approved"),
])
def test_unsourced_name_catch_kinds_of_names(sentence, name):
    found = texts(wc.check_deck(deck(subhead=sentence), BRIEF), "unsourced_name")
    assert found == [name]


def test_unsourced_name_catch_repeated_name_is_one_finding():
    d = deck(subhead="Paddlers at Porthleven love it.", proof_points__0__text="Slack water at Porthleven lasts an hour.")
    found = rules(wc.check_deck(d, BRIEF), "unsourced_name")
    assert len(found) == 1 and "also in proof_points[1].text" in found[0]["evidence"]


def test_unsourced_name_boundary_names_the_facts_hold_pass_one_more_word_is_caught():
    passes = ["Data from the Coastal Survey Office covers every harbour.",
              "The Survey Office updates it daily.",
              "Tidebook's plans sync between phone and watch.",
              "Plans made in Tidebook sync between phone and watch."]  # the product name mid-sentence
    for s in passes:
        assert rules(wc.check_deck(deck(subhead=s), BRIEF), "unsourced_name") == [], s
    caught = wc.check_deck(deck(subhead="Data from the Coastal Survey Office Wales covers it."), BRIEF)
    assert texts(caught, "unsourced_name") == ["Coastal Survey Office Wales"]
    other = wc.check_deck(deck(subhead="Plans made in Tidelog sync between phone and watch."), BRIEF)
    assert texts(other, "unsourced_name") == ["Tidelog"]  # a product name the brief does not give


def test_unsourced_name_boundary_deck_names_are_sources_on_the_page():
    d = deck(proof_points__1__text="Built with the Kayak Club of Wales.")
    lines = page(("Plans sync between phone and watch.", "Built with the Kayak Club of Wales."))
    assert texts(wc.check_deck(d, BRIEF), "unsourced_name") == ["Kayak Club of Wales"]
    assert rules(wc.check_page(lines, d, BRIEF), "unsourced_name") == []


@pytest.mark.parametrize("field, text", [
    ("subhead", "Tides change fast. Weather changes faster."),
    ("subhead", "Tidebook shows tide times for 1,200 harbours."),
    ("headlines__0", "Plan Around the Tide, Not Against It"),
    ("proof_points__0__title", "Real-Time Tide Windows"),
    ("proof_points__1__title", "Works Offline"),
    ("worked_examples__0__topic", "A Morning Trip"),
    ("subhead", "Open every Monday in June, with a FAQ and GPS export."),
    ("subhead", "NEW FEATURE: offline maps."),
    ("subhead", "Pick a launch time. Paddle back on the flood."),
    ("proof_points__0__text", "See when the water is Slack at your launch spot, as sea kayakers say slack."),
])
def test_unsourced_name_trap_capitals_that_are_not_names(field, text):
    assert rules(wc.check_deck(deck(**{field: text}), BRIEF), "unsourced_name") == []


# W4e screen (2026-10-19): the v2.2 morrow deck and page said "Shortest Cedar booking: 1 hour x $18 = $18." and
# "Shortest Atlas booking: ...", where the brief lists the rooms ("Three demo rooms: Cedar (4 people, ...), Oak
# (...) and Atlas (...)"). The sentence's first word joined the room name in one run, and "Shortest Cedar" was
# flagged as a name no fact holds: a false alarm. The same shape, made up for Tidebook:
HARBOURS = {**BRIEF, "facts": BRIEF["facts"] + ["Example harbours: Falmouth (12 moorings) and Looe (6 moorings)"]}


@pytest.mark.parametrize("text", [
    "Shortest Falmouth trip: 40 minutes on the ebb.",
    "Busiest Looe weekend: plan two tide windows.",
    "Plans sync between phone and watch. Shortest Falmouth trip: 40 minutes.",
])
def test_unsourced_name_trap_sentence_opening_word_before_a_name_the_brief_holds(text):
    assert rules(wc.check_deck(deck(subhead=text), HARBOURS), "unsourced_name") == []
    lines = page(("Plans sync between phone and watch.", text))
    assert rules(wc.check_page(lines, DECK, HARBOURS), "unsourced_name") == []


@pytest.mark.parametrize("text, name", [
    ("Shortest Penzance trip: 40 minutes on the ebb.", "Shortest Penzance"),  # the rest is no name the brief holds
    ("Our Shortest Falmouth trip takes 40 minutes.", "Shortest Falmouth"),  # mid-sentence capitals: a name
    ("Trips from Falmouth Quay take 40 minutes.", "Falmouth Quay"),  # one word more than the brief holds
])
def test_unsourced_name_boundary_sentence_opening_rule_keeps_other_names(text, name):
    assert texts(wc.check_deck(deck(subhead=text), HARBOURS), "unsourced_name") == [name]


def test_name_runs_at_gives_the_rest_only_for_a_run_opening_its_sentence():
    assert wc.name_runs_at("Shortest Falmouth trip. We met the Kayak Club of Wales.") == [
        ("Shortest Falmouth", "Falmouth"), ("Kayak Club of Wales", None)]
    assert wc.name_runs_at("Kayak Club of Wales trips") == [("Kayak Club of Wales", "Club of Wales")]
    assert wc.name_runs("Shortest Falmouth trip.") == ["Shortest Falmouth"]
    assert ("falmouth",) in wc.source_names(HARBOURS["facts"]) and ("looe",) in wc.source_names(HARBOURS["facts"])


def test_unsourced_name_trap_title_case_heading_keeps_a_name_inside_it():
    found = texts(wc.check_deck(deck(proof_points__0__title="Trusted by Harbour Masters"), BRIEF), "unsourced_name")
    assert found == ["Harbour Masters"]


# ---------------------------------------------------------------- long_paragraph


def _para(n):
    """A made-up paragraph of exactly n characters that ends a sentence."""
    text = ("slack water lasts about an hour at most harbours and the flood runs fast after it " * 10)[:n - 1]
    return (text[:-1] + "s" if text.endswith(" ") else text) + "."


def test_paragraph_helper_lengths():
    for n in (120, 150, 200, 270, 271, 300, 400):
        assert len(_para(n)) == n and _para(n).endswith("."), n


def test_long_paragraph_catch_271_and_400_characters():
    report = wc.check_page(lines_of(("p", _para(271)), ("li", _para(400))), DECK, BRIEF)
    found = [(f["line"], f["severity"], f["grade"]) for f in rules(report, "long_paragraph")]
    assert found == [(1, 2, "Should"), (2, 2, "Should")]
    assert rules(report, "long_paragraph")[1]["evidence"].startswith("400 characters: 5 lines")


def test_long_paragraph_boundary_270_characters_pass():
    assert rules(wc.check_page(lines_of(("p", _para(270))), DECK, BRIEF), "long_paragraph") == []


def test_long_paragraph_catch_pieces_split_by_a_link_are_joined():
    rows = lines_of(("p", _para(150)[:-1]), ("a", "the tide guide"), ("p", "before you go, " + _para(120)))
    found = rules(wc.check_page(rows, DECK, BRIEF), "long_paragraph")
    assert [f["line"] for f in found] == [1] and len(found[0]["text"]) > 270


def test_long_paragraph_trap_headings_and_separate_paragraphs():
    rows = lines_of(("h2", _para(300)), ("summary", _para(300)), ("p", _para(200)), ("a", "See a sample plan"),
                    ("p", "Tide " + _para(200)))
    assert rules(wc.check_page(rows, DECK, BRIEF), "long_paragraph") == []


# ---------------------------------------------------------------- renamed_term


def test_renamed_term_catch_one_word_changed_in_the_hero_is_level_3():
    lines = page(("Tidebook shows tide times for 1,200 harbours, so you pick a safe window in a minute.",
                  "Tidebook shows tide times for 1,200 harbours, so you pick a slack window in a minute."),
                 ("Tide windows", "Slack windows"),
                 ("High water at 9:10 gives a tide window from 8:30 to 9:50.",
                  "High water at 9:10 gives a slack window from 8:30 to 9:50."),
                 ("What is a tide window?", "What is a slack window?"))
    found = rules(wc.check_page(lines, DECK, BRIEF), "renamed_term")
    assert len(found) == 1
    f = found[0]
    assert (f["term"], f["text"], f["element"], f["severity"], f["grade"]) == (
        "tide window", "slack window", "hero [p]", 3, "Must")
    assert f["line"] == 5
    assert f["evidence"].endswith("also at line 9 (proof [h3]), line 16 (example [p]), line 20 (faq [summary])")


def test_renamed_term_boundary_the_decks_own_phrase_is_not_a_rename():
    # The deck itself writes "safe window" (subhead), so the page may too, with the term gone.
    lines = page(NO_TERM, ("High water at 9:10 gives a tide window from 8:30 to 9:50.", "High water at 9:10."),
                 ("What is a tide window?", "When should I launch?"))
    assert rules(wc.check_page(lines, DECK, BRIEF), "renamed_term") == []


def test_renamed_term_catch_another_phrase_in_the_terms_place_is_level_2():
    lines = page(NO_TERM, ("High water at 9:10 gives a tide window from 8:30 to 9:50.",
                  "High water at 9:10 gives a safe slot from 8:30 to 9:50."),
                 ("What is a tide window?", "What is a safe slot?"))
    found = rules(wc.check_page(lines, DECK, BRIEF), "renamed_term")
    assert [(f["text"], f["element"], f["severity"], f["grade"]) for f in found] == [
        ("safe slot", "example [p]", 2, "Should")]


@pytest.mark.parametrize("variant", ["tide windows", "tide-window", "Tide Window"])
def test_renamed_term_boundary_plural_hyphen_and_case_count_as_the_term(variant):
    lines = page(("Tide windows", "Slack windows"), ("High water at 9:10 gives a tide window from 8:30 to 9:50.",
                  f"High water at 9:10 gives a {variant} from 8:30 to 9:50."),
                 ("What is a tide window?", "What is a slack window?"))
    assert rules(wc.check_page(lines, DECK, BRIEF), "renamed_term") == []


def test_renamed_term_trap_synonym_inside_quotation_marks():
    lines = page(NO_TERM, ("High water at 9:10 gives a tide window from 8:30 to 9:50.",
                  "High water at 9:10 gives a \u201cslack window\u201d from 8:30 to 9:50."),
                 ("What is a tide window?", "What does slack mean?"))
    lines.append({"section": "proof", "tag": "blockquote", "text": "My slack window was perfect, says a paddler."})
    assert rules(wc.check_page(lines, DECK, BRIEF), "renamed_term") == []


def test_renamed_term_trap_another_thing_sharing_a_word_with_the_term():
    # With the term gone, "tide tables" changes the term's last word: another thing, not the term renamed.
    lines = page(NO_TERM, ("High water at 9:10 gives a tide window from 8:30 to 9:50.", "High water at 9:10."),
                 ("What is a tide window?", "Where do the tide tables come from?"))
    lines.append({"section": "proof", "tag": "a", "text": "Tide tables"})
    assert rules(wc.check_page(lines, DECK, BRIEF), "renamed_term") == []
    # Control: the modifier changed, head kept, on the same link is a rename.
    lines[-1] = {**lines[-1], "text": "Slack windows"}
    assert texts(wc.check_page(lines, DECK, BRIEF), "renamed_term") == ["Slack windows"]


def test_renamed_term_catch_and_trap_a_phrase_with_of_keeps_its_last_word():
    # "law of thirds" keeps the last word: a rename. "rule of twelfths" changes it: another rule.
    d = deck(terms=[{"term": "rule of thirds", "meaning": "a way to place a launch time"}])
    base = page(NO_TERM)
    caught = base + lines_of(("p", "Use the law of thirds to pick a launch time."), section="example")
    assert texts(wc.check_page(caught, d, BRIEF), "renamed_term") == ["law of thirds"]
    other = base + lines_of(("p", "Use the rule of twelfths to pick a launch time."), section="example")
    assert rules(wc.check_page(other, d, BRIEF), "renamed_term") == []


def test_renamed_term_trap_definition_words_and_mid_sentence_capitals():
    lines = page(NO_TERM, ("High water at 9:10 gives a tide window from 8:30 to 9:50.", "High water at 9:10."),
                 ("What is a tide window?", "When should I launch?"),
                 ("The hours when the current is weak enough to paddle.",
                  "Pick the hours when the current is weak enough to paddle, in the Tidebook window."))
    assert rules(wc.check_page(lines, DECK, BRIEF), "renamed_term") == []


# ---------------------------------------------------------------- report shape, inputs, sources


def test_findings_have_the_workflow_shape_and_unique_ids():
    d = deck(ctas__primary="Your first paddle around every harbour in the land",
             subhead="Paddlers at Porthleven love it.")
    lines = page(("Plan your first paddle", "Your first paddle"), NO_TERM,
                 ("High water at 9:10 gives a tide window from 8:30 to 9:50.",
                  "High water at 9:10 gives a slack window from 8:30 to 9:50."),
                 ("What is a tide window?", "What is a slack window?"),
                 ("Plans sync between phone and watch.", "Plans sync between phone and Garmin watches."))
    lines += lines_of(("p", _para(300)), section="extra")
    for report, where in ((wc.check_deck(d, BRIEF), "field"), (wc.check_page(lines, DECK, BRIEF), "element")):
        assert report["findings"]
        ids = [f["id"] for f in report["findings"]]
        assert len(ids) == len(set(ids))
        for f in report["findings"]:
            assert {"id", "target", where, "rule", "check", "text", "evidence", "severity", "grade", "kind"} <= set(f)
            assert f["rule"] in wc.RULES and f["check"] == wc.RULES[f["rule"]]["check"]
            assert re.fullmatch(rf"{report['target']}-{f['rule']}-\d+", f["id"])
    page_rules = {f["rule"] for f in wc.check_page(lines, DECK, BRIEF)["findings"]}
    assert page_rules == {"cta_verb", "unsourced_name", "long_paragraph", "renamed_term"}


@pytest.mark.parametrize("d, b", [
    ({}, {}),
    ({"ctas": "Plan a trip", "terms": ["tide window", None], "faq": [{"q": None}], "proof_points": [None, "x"]},
     {"facts": None}),
    ({"ctas": {"primary": None, "secondary": 3}, "headlines": None}, {"product": None}),
])
def test_odd_shapes_give_no_findings_and_no_crash(d, b):
    assert wc.check_deck(d, b)["findings"] == []
    assert wc.check_page([], d, b)["findings"] == []
    assert wc.check_page(lines_of(("h1", "Tide times"), ("a", "Plan a trip"), section="hero"), d, b)["findings"] == []


def test_cli_writes_the_same_bytes_twice_and_reads_raw_json(tmp_path, capsys):
    (tmp_path / "copy.json").write_text(json.dumps(deck(ctas__secondary="Pricing")))
    (tmp_path / "brief.json").write_text(json.dumps(BRIEF))
    md = PAGE_MD.replace("- [a] See a sample plan", "- [a] Pricing plans for teams of every size and harbour")
    (tmp_path / "page-text.md").write_text(md)
    raw = {"focus": {"text": wc.parse_page_md(md)}}
    (tmp_path / "raw.json").write_text(json.dumps(raw))
    base = ["--copy", str(tmp_path / "copy.json"), "--brief", str(tmp_path / "brief.json")]
    outs = []
    for n, (mode, extra) in enumerate([("deck", []), ("deck", []), ("page", ["--text", str(tmp_path / "page-text.md")]),
                                       ("page", ["--text", str(tmp_path / "page-text.md")]),
                                       ("page", ["--text", str(tmp_path / "raw.json")])]):
        out = tmp_path / f"out{n}.json"
        assert wc.main([mode, *extra, *base, "--out", str(out)]) == 0
        outs.append(out.read_bytes())
    assert outs[0] == outs[1] and outs[2] == outs[3] == outs[4]
    assert json.loads(outs[0])["counts"]["Must"] == 1
    assert [f["rule"] for f in json.loads(outs[2])["findings"]] == ["cta_length", "cta_verb"]
    (tmp_path / "bad.json").write_text("{")
    assert wc.main(["deck", "--copy", str(tmp_path / "bad.json"), "--brief", str(tmp_path / "brief.json")]) == 2
    assert "design_word_checks:" in capsys.readouterr().err


def test_verb_list_is_sorted_unique_single_lowercase_words():
    words = [ln.strip() for ln in VERBS.read_text().splitlines() if ln.strip() and not ln.startswith("#")]
    assert words == sorted(set(words))
    assert all(re.fullmatch(r"[a-z]+(?:-[a-z]+)?", w) for w in words)
    assert 140 <= len(words) <= 170
    assert not {"free", "pricing", "more", "next", "back", "home", "help", "skip"} & set(words)
    assert wc.VERBS == frozenset(words)


def test_rules_table_covers_every_rule_and_quotes_its_sources_word_for_word():
    assert set(wc.RULES) == set(wc.RULE_ORDER)
    for name, rule in wc.RULES.items():
        assert rule["sources"], name
        for src in rule["sources"]:
            path = BAR if src["file"].startswith("~/design-lab") else ROOT / src["file"]
            if not path.exists():
                assert path == BAR, src["file"]
                continue
            text = " ".join(path.read_text().split())
            assert " ".join(src["quote"].split()) in text, (name, src)
    if not BAR.exists():
        pytest.skip("BAR.md is not on this host; the repo quotes were checked")
