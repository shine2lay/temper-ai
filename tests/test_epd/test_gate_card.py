"""The card the owner decides a PR on: what it says, and that the dashboard can show it.

The card is built by the question block at the end of configs/epd/agents/epd_ship.yaml. These
tests run that block itself -- extracted from the shipped YAML, not copied into the test -- so a
change to the wording that breaks its shape is caught here rather than at a gate someone is
waiting on.

The bug that motivated them: the brief was written to a `detail` key, and the dashboard reads
prose out of the keys in temper_ai.stage.gate.PROSE_KEYS, which does not include `detail`. The
panel above the buttons was empty for three bets and nobody noticed, because the text was still
in the JSON -- just nowhere anyone looked.
"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from temper_ai.stage.gate import questions_from, summarise_output

AGENT = Path(__file__).resolve().parents[2] / "configs" / "epd" / "agents" / "epd_ship.yaml"

BUILD = {
    "branch": "epd-b005",
    "implement_commit": "a1b2c3d4e5f6a7b8",
    "implement_summary": "Made the simulated broker fill an order and say when.",
    "review_verdict": "approve",
    "verify_verdict": "pass",
    "security_verdict": "pass",
    "deploy_url": "https://epd-b005.dev.rollcall.example.com",
    "verify_threshold_checks": [
        {"clause": "A market order fills within 2 seconds", "status": "met", "evidence": "0.8s"},
        {"clause": "A closed market says when it will fill", "status": "unverified", "evidence": ""},
        {"clause": "A rejected order says why", "status": "unmet", "evidence": "Row stayed blank"},
    ],
}
STATE = {"stages": {"ship": {"pr": "https://github.com/o/r/pull/9", "pr_number": 9,
                             "title": "b005: The sim broker fills, and says when it will"}}}


def question_block() -> str:
    """The python the ship agent runs to build the card, taken out of the shipped YAML."""
    text = AGENT.read_text()
    start = text.index('python3 - "$BET_DIR/state.json" "$BET_DIR/build.json" <<\'PY\'')
    body = text[text.index("\n", start) + 1:]
    body = body[:body.index("\n    PY\n")]
    return "\n".join(line[4:] if line.startswith("    ") else line for line in body.split("\n"))


def card(tmp_path, build=None, state=None) -> tuple[dict, str]:
    """The card for these files: the parsed document, and the raw text the node would print."""
    (tmp_path / "state.json").write_text(json.dumps(state or STATE))
    (tmp_path / "build.json").write_text(json.dumps({**BUILD, **(build or {})}))
    run = subprocess.run([sys.executable, "-c", question_block(),
                          str(tmp_path / "state.json"), str(tmp_path / "build.json")],
                         capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout), run.stdout


def test_the_dashboard_shows_the_brief_above_the_buttons(tmp_path):
    """The panel is fed from PROSE_KEYS; a brief under any other key is a brief nobody sees."""
    doc, raw = card(tmp_path)
    shown = summarise_output(raw, questions_from(doc, raw))
    assert shown.strip(), "the panel above the buttons would be empty"
    assert shown == doc["summary"], "what the dashboard shows is the brief, and only the brief"
    assert "questions_for_owner" not in shown, "the form is rendered below; it is not read out twice"


def test_the_brief_answers_what_who_decides_needs(tmp_path):
    doc, _ = card(tmp_path)
    s = doc["summary"]
    assert "https://github.com/o/r/pull/9" in s, "the PR"
    assert "Made the simulated broker fill an order" in s, "what it does"
    assert "https://epd-b005.dev.rollcall.example.com" in s, "where to try it"
    assert "`epd-b005`" in s and "`a1b2c3d4e5f6`" in s, "the branch and commit, short"
    # Blocks are separated by a blank line: a single newline is not a line break in markdown,
    # and without it the whole card renders as one paragraph.
    assert "\n\n" in s and "### PR #9" in s.split("\n\n")[0]


def test_the_checks_are_in_words_and_a_failing_one_is_marked(tmp_path):
    doc, _ = card(tmp_path)
    assert "Code review: passed" in doc["summary"], "not the pipeline's word 'approve'"
    assert "Clicked through in a browser: passed" in doc["summary"], "not 'verify'"
    assert "\u26a0" not in doc["summary"], "nothing is flagged when everything passed"

    doc, _ = card(tmp_path, build={"security_verdict": "request_changes", "review_verdict": ""})
    assert "Security check: asked for changes \u26a0" in doc["summary"], "the one that did not pass is marked"
    assert "Code review: not run \u26a0" in doc["summary"], "so is one that never ran"


def test_what_qa_checked_says_which_promises_it_could_not_reach(tmp_path):
    doc, _ = card(tmp_path)
    s = doc["summary"]
    assert "\u2713 A market order fills within 2 seconds" in s
    assert "\u2717 A rejected order says why" in s
    assert "? A closed market says when it will fill \u2014 nothing in the app reached this" in s, (
        "an unverified clause is the owner's to judge, so it says so rather than looking checked"
    )


@pytest.mark.parametrize("label,must_say", [
    ("Merge", "live"),
    ("Request changes", "note"),
    ("Close", "closed without merging"),
])
def test_each_button_says_what_it_does_before_it_is_pressed(tmp_path, label, must_say):
    doc, _ = card(tmp_path)
    opt = next(o for o in doc["questions_for_owner"][0]["options"] if o["label"] == label)
    assert opt["description"], "a button with no description is a button you press to find out"
    assert must_say in opt["preview"], f"{label} does not say what happens"


def test_the_labels_are_the_ones_the_driver_acts_on(tmp_path):
    """The driver matches these strings exactly (PR_DECISIONS); a reworded label is a dropped answer."""
    spec = importlib.util.spec_from_file_location(
        "epd_loop_labels", Path(__file__).resolve().parents[2] / "configs" / "epd" / "bin" / "epd_loop.py")
    doc, _ = card(tmp_path)
    labels = [o["label"] for o in doc["questions_for_owner"][0]["options"]]
    source = spec.origin and Path(spec.origin).read_text() or ""
    for label in labels:
        assert f'"{label}"' in source, f"the driver does not know the label {label!r}"


def test_no_pr_means_nothing_to_decide(tmp_path):
    doc, _ = card(tmp_path, state={"stages": {"ship": {}}})
    assert doc["status"] == "incomplete"
    assert doc["questions_for_owner"] == [], "no PR, no buttons"
    assert "nothing to decide" in doc["summary"]
