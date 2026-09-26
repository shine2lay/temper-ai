"""Which workflows the @temper picker reads in full before it proposes one."""

from __future__ import annotations

from temper_ai.integrations.slack.picker import PICK_WORKFLOW, TOP, candidates_for

from .conftest import FakeOps

ENTRIES = [
    {"name": "code_review", "description": "Several specialists review code; a leader merges their findings.",
     "inputs": {"task": {"type": "string", "required": True, "description": "What to review"}}},
    {"name": "trigger_probe", "description": "Echo a note back; a cheap probe for triggers.",
     "inputs": {"note": {"type": "string", "required": False}}},
    {"name": "gate_demo", "description": "Ask a person to approve before the last step.", "inputs": {}},
    {"name": PICK_WORKFLOW, "description": "Pick a workflow to review for a Slack request.", "inputs": {}},
]
THREAD = ("U1: <@UBOT> review a PR\n"
          "temper: I'd use *code_review*, but: Which PR would you like reviewed?")
LINK = "<https://github.com/shine2lay/temper-ai/pull/19>"


def names(found):
    return [e["name"] for e in found]


def test_a_reply_in_a_thread_keeps_the_workflow_already_proposed():
    ops = FakeOps(ENTRIES)
    # the bare link matches nothing by itself
    assert "code_review" not in names(ops.search(LINK)["results"])
    found = candidates_for(ops, ops.catalog(), LINK, THREAD)
    assert names(found)[0] == "code_review"
    assert found[0]["inputs"]["task"]["required"] is True


def test_the_thread_words_count_too():
    ops = FakeOps(ENTRIES)
    found = candidates_for(ops, ops.catalog(), LINK, "U1: <@UBOT> please approve something before the last step")
    assert "gate_demo" in names(found)


def test_no_duplicates_no_picker_and_at_most_top():
    many = ENTRIES + [{"name": f"review_{i}", "description": "Review code.", "inputs": {}} for i in range(20)]
    ops = FakeOps(many)
    found = candidates_for(ops, ops.catalog(), "review code", THREAD + " (code_review again)")
    assert len(names(found)) == len(set(names(found))) <= TOP
    assert PICK_WORKFLOW not in names(found)
    assert names(found)[0] == "code_review"


def test_without_a_thread_only_the_request_is_searched():
    ops = FakeOps(ENTRIES)
    assert names(candidates_for(ops, ops.catalog(), "echo a note")) == names(ops.search("echo a note", limit=TOP)["results"])
