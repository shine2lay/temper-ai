"""STATIC wording/wiring only: no model answer, request, browser, box, or Project.

Fixed inputs and expected-language checklists below describe later behavior tests; here
we check only that the instructions needed for those distinctions reach every framing.
Never print generated framing or put it in assertion diagnostics.
"""

from __future__ import annotations

import ast
import inspect
import textwrap

import pytest

from temper_ai.pi_agent.team_flow import FlowTeam, flow_framing
from temper_ai.pi_agent.team_leader import (
    EVIDENCE_HANDOFF_NOTE,
    LeaderTeam,
    framing,
    tools_note,
)

PRODUCERS = {"flow": flow_framing, "leader": framing}
ROSTER = ["lead", "verifier", "builder"]
GUIDANCE_CUES = (
    "actually run", "code review", "fixtures", "proposed checks",
    "Name each executed check, its result, and artifact/reference when available.",
    "NOT CHECKED means not run", "BLOCKED means missing access or prerequisites",
    "FAILED means an observed failed check",
    "A screenshot alone does not prove interactions or persistence.",
    "Keep the final handoff concise: what works (observed versus inferred), "
    "what was checked, and what remains unknown.",
    "Leads: preserve verifier limitations; do not turn code review or missing evidence "
    "into verified success.",
)
PRESERVED_CUES = {
    ("flow", True): ("You are the team's leader.", "As the leader: split the goal into parts",
                     "call done with a short summary", "nobody shared after your done call"),
    ("flow", False): ("The team's leader is lead.", "Work on what is asked of you",
                      "it is done or if you are stuck, and share your work."),
    ("leader", True): ("You lead.", "request_review:", "decide, naming the review",
                       "Done counts only if your copy is still exactly the reviewed version."),
    ("leader", False): ("You review lead's work.", "call give_view naming the review",
                        "satisfied, or changes with a short note"),
}


def _check(condition: bool, label: str) -> None:
    # Plain labels/booleans only, including on failure; no prompt assertion expansion.
    if not condition:
        pytest.fail(label, pytrace=False)


def test_whole_feature_guidance_reaches_all_members_and_keeps_framing_and_tool_notes():
    """Opening combined happy path: both modes, lead/verifier/ordinary member, tool variants."""
    _check(0 < len(EVIDENCE_HANDOFF_NOTE.split()) <= 120, "guidance word budget")
    for mode, producer in PRODUCERS.items():
        for member in ROSTER:
            for tools in ([], ["send_message", "Read"]):
                text = producer(member, "lead", ROSTER, tools)
                label = f"{mode}/{member}/tools-{len(tools)}"
                _check(text.count(EVIDENCE_HANDOFF_NOTE) == 1, f"{label}: shared note once")
                _check(all(cue in text for cue in GUIDANCE_CUES), f"{label}: evidence cues")
                _check(text.endswith("\n" + tools_note(tools)), f"{label}: tools unchanged")
                _check(text.startswith(f"[Temper] You are {member},"), f"{label}: identity")
                _check(all(cue in text for cue in PRESERVED_CUES[mode, member == "lead"]),
                       f"{label}: existing role and completion wording")
                if mode == "flow":
                    _check("Everyone works at the same time, each in their own copy" in text
                           and "Only you wait for the answer; the other members carry on." in text
                           and "only after your turn finishes." in text,
                           f"{label}: existing work, waits and delivery wording")
                else:
                    _check("Temper delivers it at their next turn." in text,
                           f"{label}: existing delivery wording")


# No fixture below is a generated/model-produced answer or an executed acceptance case.
# The expected-language checklist is a human-readable future behavior expectation;
# this test checks only its corresponding source instructions, not agent compliance.
KNOWN_CASES = (
    pytest.param({
        "input": "unit-check was executed, exit 0; reference results/unit-check.txt",
        "expected_language": (
            "Name unit-check as observed, with exit 0 and results/unit-check.txt.",
            "Separate that observation from inferred functionality and unknown browser behavior.",
        ),
        "guidance_cues": (
            "checks you actually run", "Name each executed check, its result, and "
            "artifact/reference when available.", "observed versus inferred",
            "what remains unknown",
        ),
    }, id="executed-clean-result-reference"),
    pytest.param({
        "input": "Required app access is missing; no app check was executed.",
        "expected_language": (
            "BLOCKED: required app access is missing; app check was not run.",
            "Keep the verifier limitation in the lead's handoff; do not claim verified success.",
        ),
        "guidance_cues": (
            "BLOCKED means missing access or prerequisites", "NOT CHECKED means not run",
            "preserve verifier limitations", "missing evidence into verified success",
            "what remains unknown",
        ),
    }, id="missing-access-no-execution"),
    pytest.param({
        "input": "Code review and a fixture suggest a fix; a proposed app check was not run.",
        "expected_language": (
            "NOT CHECKED: proposed app check was not run; only code/fixture review exists.",
            "Label functionality inferred, not observed or verified; identify the unknowns.",
        ),
        "guidance_cues": (
            "code review, fixtures, and proposed checks", "NOT CHECKED means not run",
            "observed versus inferred", "do not turn code review or missing evidence "
            "into verified success", "what remains unknown",
        ),
    }, id="unexecuted-review-proposed-check"),
)


@pytest.mark.parametrize("case", KNOWN_CASES)
@pytest.mark.parametrize("mode", ("flow", "leader"))
@pytest.mark.parametrize("member", ("lead", "verifier"))
def test_fixed_case_language_checklist_is_stated_in_guidance(case, mode, member):
    text = PRODUCERS[mode](member, "lead", ROSTER, [])
    _check(all(cue in text for cue in case["guidance_cues"]),
           f"{mode}/{member}: static case guidance missing")


@pytest.mark.parametrize("team,producer_name", ((FlowTeam, "flow_framing"), (LeaderTeam, "framing")))
def test_existing_prompt_for_still_calls_its_framing_seam(team, producer_name):
    # Inspect our own producer code only. Do not invoke prompt_for or render a model request.
    tree = ast.parse(textwrap.dedent(inspect.getsource(team.prompt_for)))
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Name) and node.func.id == producer_name]
    _check(len(calls) == 1, f"{producer_name}: one existing call site")
    _check(len(calls[0].args) == 4 and not calls[0].keywords,
           f"{producer_name}: existing four-argument wiring")
