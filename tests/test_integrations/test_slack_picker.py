"""Which workflows the @temper picker reads in full before it proposes one."""

from __future__ import annotations

from temper_ai.integrations.slack.picker import (
    PICK_WORKFLOW,
    TOP,
    candidates_for,
    narrow,
)

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


# -- a role's interpreter: the picker with blinkers on ------------------------

def test_a_role_sees_only_its_own_workflows():
    assert names(narrow(ENTRIES, ["gate_demo"])) == ["gate_demo"]
    assert names(narrow(ENTRIES, [])) == []
    assert names(narrow(ENTRIES, None)) == names(ENTRIES), "no role means every workflow"


def test_a_workflow_the_role_lacks_cannot_be_reached_by_naming_it():
    ops = FakeOps(ENTRIES)
    mine = narrow(ops.catalog(), ["trigger_probe"])
    found = candidates_for(ops, mine, "run code_review on this", THREAD + " code_review please")
    assert "code_review" not in names(found), "not through the search, the thread, or its name"


def test_the_narrowed_catalog_still_finds_what_the_role_has():
    ops = FakeOps(ENTRIES)
    mine = narrow(ops.catalog(), ["trigger_probe", "gate_demo"])
    assert "trigger_probe" in names(candidates_for(ops, mine, "echo a note"))
