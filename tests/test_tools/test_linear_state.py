"""LinearMoveIssue changes an issue's state, to an allowed name, and nothing else."""

import pytest

from temper_ai.tools import TOOL_CLASSES
from temper_ai.tools.linear_state import LinearMoveIssue
from temper_ai.triggers import linear

STATES = [
    {"id": "s-todo", "name": "Todo"},
    {"id": "s-prog", "name": "In Progress"},
    {"id": "s-rev", "name": "In Review"},
    {"id": "s-done", "name": "Done"},
]


@pytest.fixture
def fake_linear(monkeypatch):
    calls = []
    issue = {"id": "uuid-5", "identifier": "ROA-5", "state": {"id": "s-todo", "name": "Todo"},
             "team": {"key": "ROA", "states": {"nodes": STATES}}}

    def fake(query, variables=None, creds=None):
        calls.append((query, variables))
        if "issueUpdate" in query:
            name = next(s["name"] for s in STATES if s["id"] == variables["stateId"])
            issue["state"] = {"id": variables["stateId"], "name": name}
            return {"issueUpdate": {"success": True, "issue": {"id": "uuid-5", "identifier": "ROA-5",
                                                                "state": {"name": name}}}}
        if variables["id"] in ("ROA-5", "uuid-5"):
            return {"issue": issue}
        return {"issue": None}

    monkeypatch.setattr(linear, "graphql", fake)
    monkeypatch.delenv("TEMPER_LINEAR_STATES", raising=False)
    return calls


def test_registered():
    assert TOOL_CLASSES["LinearMoveIssue"] is LinearMoveIssue


def test_moves_by_name_within_the_issue_s_team(fake_linear):
    result = LinearMoveIssue().execute(issue="ROA-5", state="in progress")
    assert result.success, result.error
    assert result.metadata == {"issue": "ROA-5", "from": "Todo", "state": "In Progress", "changed": True}
    update = [c for c in fake_linear if "issueUpdate" in c[0]]
    assert update == [(update[0][0], {"id": "uuid-5", "stateId": "s-prog"})]
    # the mutation sets the state and nothing else
    assert "input: {stateId: $stateId}" in update[0][0]


def test_a_state_off_the_list_is_refused_before_linear_is_asked(fake_linear):
    result = LinearMoveIssue().execute(issue="ROA-5", state="Done")
    assert not result.success
    assert "not a state this tool moves issues to" in result.error
    assert fake_linear == []


def test_the_list_comes_from_the_environment(fake_linear, monkeypatch):
    monkeypatch.setenv("TEMPER_LINEAR_STATES", "Done")
    assert LinearMoveIssue().execute(issue="ROA-5", state="Done").success
    assert not LinearMoveIssue().execute(issue="ROA-5", state="In Review").success


def test_already_there_is_not_a_change(fake_linear):
    LinearMoveIssue().execute(issue="ROA-5", state="In Review")
    again = LinearMoveIssue().execute(issue="ROA-5", state="In Review")
    assert again.success
    assert again.metadata["changed"] is False
    assert sum("issueUpdate" in c[0] for c in fake_linear) == 1


def test_a_team_without_that_state(fake_linear, monkeypatch):
    monkeypatch.setenv("TEMPER_LINEAR_STATES", "Shipped")
    result = LinearMoveIssue().execute(issue="ROA-5", state="Shipped")
    assert not result.success
    assert "team ROA has no state named 'Shipped'" in result.error


def test_an_unknown_issue_and_linear_down(fake_linear, monkeypatch):
    assert "no issue ROA-404" in LinearMoveIssue().execute(issue="ROA-404", state="In Review").error

    def down(*args, **kwargs):
        raise RuntimeError("503")

    monkeypatch.setattr(linear, "graphql", down)
    result = LinearMoveIssue().execute(issue="ROA-5", state="In Review")
    assert not result.success
    assert "503" in result.error
