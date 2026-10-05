"""desk_check judges each assumption by the bar it was given (configs/workflows/desk_check.yaml, product role,
queue #24).

Run 2a2f6850 held an assumption at unknown under check_desk.py's own rule that a pass needs a primary source
from a neutral party, although its pass bar counted an operator's or a quiz vendor's case-study figure. The bar
governs now. The run's input.md lists the evidence rules: fixed F1-F3, and the defaults D1 (two sources), D2 (a
neutral source) and D3 (a primary source), which hold only where an assumption's own pass_if or kill_if is
silent on them. A verdict sets a default aside only by quoting at least 3 of the bar's own words
(rules.set_aside), and an unknown that a default held back names it (rules.decided_by), which must really fail on
the decisive claims. No model and no network.
"""

import hashlib
import json
import os
import re
import subprocess

import pytest

from temper_ai.agent.script_agent import _rewrite_interpolations, _ValueStash
from tests.test_desk_check.test_a_lost_part_fails_the_desk_check import (
    WORKFLOW,
    by_name,
    final,
    helper,
    jinja,
    run,
    served,
    write,
)

PAGES = {
    "https://business.example.com/success-stories/swiss-tourism/":
        "Switzerland Tourism's destination quiz had an 80% completion rate across six European markets.",
    "https://quizvendor.example.com/blog/swiss-tourism-quiz":
        "Of the people who started the quiz, 80% completed it, and many went on to plan a trip.",
}
# Who is speaking on each page (queue #28): the platform's success story and the quiz vendor's blog.
SPEAKERS = [("Example Business, the quiz platform", "sells the platform the success story promotes"),
            ("QuizVendor", "sells the quiz software")]
# The bar of run 2a2f6850's A2, cut short: it counts the operator's and the vendor's own figures.
SAYS_SO = ("At least one named travel destination quiz has an operator-stated or case-study-stated completion rate "
           "of 50% or more. A quiz-software vendor's case study is primary for its stated figure but tag it party: "
           "interested.")
# The same bar, silent on who may state the figure.
SILENT = "At least one named travel destination quiz has a completion rate of 50% or more, dated 2019 or later."
KILL = "Figures for named travel destination quizzes show completion under 25%."
HYPOTHESIS = ("Travelers want a destination matcher. A quiz vendor's case study is primary for its stated figure "
              "but tag it party: interested.")
NONE = {"decided_by": [], "set_aside": []}
D2_ASIDE = {"decided_by": [], "set_aside": [
    {"rule": "D2", "bar_words": "operator-stated or case-study-stated completion rate",
     "why": "The bar counts the operator's or the quiz vendor's own stated figure."}]}
D2_HELD = {"decided_by": ["D2"], "set_aside": []}
D2_SILENT = "- A1: no decisive claim read with cite.py or counted from data is from a neutral party and primary (default D2)"


def claims(how="cite"):
    """Both decisive claims come from interested parties: the operator's platform and the quiz vendor."""
    return [{"id": f"A1-{n}", "claim": "The Switzerland Tourism quiz finished at 80%.", "quote": text.split(",")[0],
             "url": url, "date": "2020", "fetched": "2026-10-05", "kind": "count", "quality": "primary",
             "party": "interested", "stake": stake, "source": source, "signal": "does", "how": how}
            for n, ((url, text), (source, stake)) in enumerate(zip(PAGES.items(), SPEAKERS, strict=True), 1)]


def findings(verdict, rules, how="cite"):
    data = {"id": "A1", "assumption": "Most travelers who start a destination quiz finish it.", "verdict": verdict,
            "why": "The operator's platform and the quiz vendor both state an 80% completion rate for the quiz.",
            "against_bar": "80% is above the pass bar's 50%; nothing near the kill bar's 25% was found.",
            "decisive": ["A1-1", "A1-2"], "counter": [], "confidence": "med", "carried_by": "does",
            "next_test": "Ask the operator for the quiz's completion rate by market.", "claims": claims(how),
            "searched": ["travel quiz completion rate"], "not_found": ["a neutral source for the quiz's figure"]}
    if rules is not None:
        data["rules"] = rules
    return data


def desk(ws, bar, verdict, rules, how="cite", row=None):
    """A desk check of one assumption with two kept pages; with row, also the reviewer's report."""
    d = ws / "state" / "desk"
    write(d / "check_desk.py", helper())
    write(d / "assumptions" / "A1.json", {"id": "A1", "assumption": "Most travelers who start a destination quiz "
                                          "finish it.", "pass_if": bar, "kill_if": KILL, "fatal": False})
    for url, text in PAGES.items():
        name = hashlib.sha1(url.encode()).hexdigest()[:16] + ".txt"
        write(d / "pages" / name, json.dumps({"url": url, "http": "200"}) + "\n" + text)
    write(d / "checks" / "A1.json", findings(verdict, rules, how))
    write(d / "checks" / "A1.md", "# A1\nThe quiz's completion rate, its sources and what they mean.\n")
    if row is not None:
        write(d / "report.json", {
            "verdicts": [{"id": "A1", "assumption": "Most travelers who start a destination quiz finish it.",
                          "researcher_verdict": verdict, "why": "Both the operator and the vendor state 80%.",
                          "decisive": ["A1-1", "A1-2"], "confidence": "med", "carried_by": "does",
                          "next_test": "Ask the operator for the quiz's completion rate by market.", **row}],
            "hypothesis_status": "holds" if row["verdict"] == "pass" else "open",
            "status_why": "The only assumption is judged against its own bar as written.",
            "next_steps": ["Ask the operator for the quiz's completion rate by market."]})
        write(d / "report.md", "# Desk check\n")
    return ws


def problems(ws):
    done = run(ws, "A1")
    return done.returncode, done.stdout.splitlines()[:-1]


# ---- the run's input and the workflow ------------------------------------------------------------


def test_the_run_input_lists_the_evidence_rules_before_the_bars(tmp_path):
    cfg = by_name("desk_setup")
    stash = _ValueStash()
    assumptions = json.dumps([{"id": "A1", "assumption": "Most travelers finish a destination quiz.",
                               "pass_if": SILENT, "kill_if": KILL, "fatal": False}])
    script = jinja(stash).from_string(_rewrite_interpolations(cfg["script_template"], cfg["name"])).render(
        workspace_path=str(tmp_path), hypothesis=HYPOTHESIS, assumptions=assumptions)
    done = subprocess.run(["sh", "-c", script], capture_output=True, text=True, timeout=120, cwd=tmp_path,
                          env={**os.environ, **stash.env})
    assert done.returncode == 0, done.stderr
    text = (tmp_path / "state" / "desk" / "input.md").read_text()
    assert text.index("## Hypothesis") < text.index("## Evidence rules") < text.index("## Assumptions")
    for rule in ("F1", "F2", "F3"):
        assert f"\n- {rule} " in text, f"input.md lists the fixed rule {rule}"
    defaults = re.findall(r'"(D\d)"', re.search(r"DEFAULT_RULES = \(([^)]*)\)", helper()).group(1))
    assert defaults == ["D1", "D2", "D3"]
    for rule in defaults:
        assert f"\n- {rule} " in text, f"input.md lists the default {rule} that check_desk.py applies"
    assert "Defaults, held only where an assumption's own bar is silent on them:" in text
    assert "A bar sets a default aside only by saying so in its own pass or kill words" in text
    assert "The hypothesis, the pointers and a researcher's or reviewer's judgement never set a default aside" in text


def test_the_bars_author_sees_the_rules_and_the_run_reports_them():
    workflow = served(WORKFLOW)["workflow"]
    shown = " ".join(workflow["inputs"]["assumptions"]["description"].split())
    for words in ("D1 at least 2 sources", "D2 one checked claim from a neutral party", "D3 that claim primary",
                  "say so in pass_if or kill_if", "The hypothesis text never sets one aside"):
        assert words in shown, "the run form shows the evidence rules next to the assumptions"
    assert workflow["outputs"]["rules"] == "final.structured.rules"


# ---- a researcher's verdict -----------------------------------------------------------------------


def test_a_bar_silent_on_who_states_the_figure_keeps_the_neutral_source_default(tmp_path):
    code, found = problems(desk(tmp_path, SILENT, "pass", NONE))
    assert code == 1 and found == [D2_SILENT]


def test_an_unknown_held_back_by_the_default_names_it(tmp_path):
    code, found = problems(desk(tmp_path, SILENT, "unknown", D2_HELD))
    assert code == 0, found


def test_a_bar_that_counts_the_operators_own_figure_sets_the_neutral_source_default_aside(tmp_path):
    code, found = problems(desk(tmp_path, SAYS_SO, "pass", D2_ASIDE))
    assert code == 0, found


def aside(rule="D2", words="operator-stated or case-study-stated completion rate", why="The bar counts it so."):
    return {"decided_by": [], "set_aside": [{"rule": rule, "bar_words": words, "why": why * 2}]}


NOT_THE_BARS = [
    ("words from the hypothesis", SILENT, aside(words="A quiz vendor's case study is primary"),
     "- A1: setting D2 aside needs bar_words: at least 3 words exactly as this assumption's pass_if or kill_if"),
    ("one word", SAYS_SO, aside(words="operator-stated"),
     "- A1: setting D2 aside needs bar_words: at least 3 words exactly as this assumption's pass_if or kill_if"),
    ("a fixed rule", SAYS_SO, aside(rule="F3"),
     "- A1: rules.set_aside names 'F3': only the defaults D1, D2 and D3 can be set aside"),
    ("no why", SAYS_SO, aside(why=""), "- A1: setting D2 aside needs its why"),
]


@pytest.mark.parametrize(("bar", "rules", "problem"), [x[1:] for x in NOT_THE_BARS], ids=[x[0] for x in NOT_THE_BARS])
def test_only_the_bars_own_words_set_a_default_aside(tmp_path, bar, rules, problem):
    code, found = problems(desk(tmp_path, bar, "pass", rules))
    assert code == 1
    assert found[0].startswith(problem), found
    assert found[1:] == [D2_SILENT], "a default not set aside still holds the pass back"


DECIDED_WRONGLY = [
    ("on a pass", SAYS_SO, "pass", {"decided_by": ["D2"], "set_aside": D2_ASIDE["set_aside"]},
     "- A1: rules.decided_by names a default that held the verdict back, so it belongs to an unknown, not a pass"),
    ("a default the claims meet", SILENT, "unknown", {"decided_by": ["D1"], "set_aside": []},
     "- A1: rules.decided_by names D1, but the decisive claims meet it"),
    ("a default the bar sets aside", SAYS_SO, "unknown", {"decided_by": ["D2"], "set_aside": D2_ASIDE["set_aside"]},
     "- A1: rules.decided_by names D2, which the bar sets aside"),
    ("a fixed rule", SILENT, "unknown", {"decided_by": ["F1"], "set_aside": []},
     "- A1: rules.decided_by names 'F1': only D1, D2 or D3"),
]


@pytest.mark.parametrize(("bar", "verdict", "rules", "problem"), [x[1:] for x in DECIDED_WRONGLY],
                         ids=[x[0] for x in DECIDED_WRONGLY])
def test_decided_by_names_only_a_default_that_really_held_the_verdict_back(tmp_path, bar, verdict, rules, problem):
    code, found = problems(desk(tmp_path, bar, verdict, rules))
    assert code == 1 and found == [problem]


def test_a_verdict_states_its_rules(tmp_path):
    code, found = problems(desk(tmp_path, SAYS_SO, "unknown", None))
    assert code == 1 and found == ['- A1: rules is missing: {"decided_by": [...], "set_aside": [...]} (each may be '
                                   'an empty list)']


def test_no_bar_sets_aside_the_checked_claim(tmp_path):
    code, found = problems(desk(tmp_path, SAYS_SO, "pass", D2_ASIDE, how="webfetch"))
    assert code == 1
    assert found == ["- A1: no usable decisive claim is read with cite.py or counted from data (fixed rule F3: a "
                     "pass or a kill always needs one)"]


# ---- the reviewer's report ------------------------------------------------------------------------


def test_the_reviewer_passes_what_a_default_held_back_when_the_bar_sets_it_aside(tmp_path):
    """Run 2a2f6850's A2 as it should have gone: the researcher held it at unknown under the neutral-source
    default; the bar counts the operator's and the vendor's own figures, so the reviewer passes it."""
    row = {"verdict": "pass", "changed_because": "The bar counts the operator's and the vendor's stated figures.",
           "rules": D2_ASIDE}
    result = final(desk(tmp_path, SAYS_SO, "unknown", D2_HELD, row=row))
    assert result["verdict"] == "pass", result["problems"]
    assert result["hypothesis_status"] == "holds"
    a1 = result["assumptions"]["A1"]
    assert (a1["researcher_verdict"], a1["verdict"]) == ("unknown", "pass")
    assert a1["rules"] == result["rules"]["A1"] == D2_ASIDE, "the hand check sees the default set aside and the words"
    assert [c["party"] for c in a1["decisive"]] == ["interested", "interested"]


def test_the_reviewer_cannot_set_aside_a_default_the_bar_is_silent_on(tmp_path):
    row = {"verdict": "pass", "changed_because": "The hypothesis says a vendor's case study is primary.",
           "rules": aside(words="A quiz vendor's case study is primary")}
    result = final(desk(tmp_path, SILENT, "unknown", D2_HELD, row=row))
    assert result["verdict"] == "fail"
    assert [p for p in result["problems"] if p.startswith("report: A1: ")] == [
        "report: A1: setting D2 aside needs bar_words: at least 3 words exactly as this assumption's pass_if or "
        "kill_if has them (only the bar's own words set a default aside)",
        D2_SILENT.replace("- A1: ", "report: A1: ")]


def test_a_report_row_states_its_rules(tmp_path):
    result = final(desk(tmp_path, SILENT, "unknown", D2_HELD, row={"verdict": "unknown"}))
    assert result["verdict"] == "fail"
    assert result["problems"] == ['report: A1: rules is missing: {"decided_by": [...], "set_aside": [...]} (each '
                                  'may be an empty list)']
    assert result["rules"]["A1"] == D2_HELD, "the hand check falls back on the researcher's rules"
