"""LinearMoveIssue -- move a Linear issue to one of a few named workflow states. Nothing else.

Linear's own MCP tool for this, ``save_issue``, rewrites anything on an issue: its
title, description, labels, assignee, relations. An agent that reads issue text
written by people should not hold that, so the one change the Linear work agents
need -- "In Progress" when work starts, "In Review" when the PR is open -- is this
tool, which can make that change and no other:

* the target is a state NAME from a short allowlist (``TEMPER_LINEAR_STATES``,
  default "In Progress" and "In Review"); the tool looks the name up among the
  issue's own team's states, so a state id from elsewhere cannot be passed in;
* it changes ``stateId`` and nothing else, as temper's Linear app.

Moving an issue to the state it is already in is reported, not an error.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from temper_ai.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

STATES_ENV = "TEMPER_LINEAR_STATES"
DEFAULT_STATES = ("In Progress", "In Review")

_ISSUE_QUERY = """
query($id: String!) {
  issue(id: $id) {
    id identifier
    state { id name }
    team { key states { nodes { id name } } }
  }
}
"""

_MOVE = """
mutation($id: String!, $stateId: String!) {
  issueUpdate(id: $id, input: {stateId: $stateId}) {
    success
    issue { id identifier state { name } }
  }
}
"""


def allowed_states() -> list[str]:
    raw = os.environ.get(STATES_ENV, "").strip()
    names = [s.strip() for s in raw.split(",")] if raw else list(DEFAULT_STATES)
    return [s for s in names if s]


class LinearMoveIssue(BaseTool):
    name = "LinearMoveIssue"
    description = (
        "Move a Linear issue to another workflow state, e.g. 'In Progress' when you start work "
        "and 'In Review' when its pull request is open. Changes the issue's state and nothing else."
    )
    parameters = {
        "type": "object",
        "properties": {
            "issue": {"type": "string", "description": "The issue's id or identifier, e.g. ROA-5"},
            "state": {
                "type": "string",
                "description": "Name of the state to move it to: " + " or ".join(f"'{s}'" for s in DEFAULT_STATES),
            },
        },
        "required": ["issue", "state"],
    }
    modifies_state = True
    local_paths = False

    def execute(self, **params: Any) -> ToolResult:
        from temper_ai.triggers import linear

        issue_ref = str(params.get("issue") or "").strip()
        wanted = str(params.get("state") or "").strip()
        allowed = allowed_states()
        if not issue_ref or not wanted:
            return ToolResult(success=False, result="", error="issue and state are both required")
        match = next((s for s in allowed if s.lower() == wanted.lower()), None)
        if match is None:
            return ToolResult(success=False, result="",
                              error=f"'{wanted}' is not a state this tool moves issues to "
                                    f"(allowed: {', '.join(allowed)})")
        try:
            issue = (linear.graphql(_ISSUE_QUERY, {"id": issue_ref}).get("issue")) or None
            if issue is None:
                return ToolResult(success=False, result="", error=f"Linear has no issue {issue_ref}")
            states = ((issue.get("team") or {}).get("states") or {}).get("nodes") or []
            target = next((s for s in states if str(s.get("name", "")).lower() == match.lower()), None)
            if target is None:
                team = (issue.get("team") or {}).get("key")
                return ToolResult(success=False, result="",
                                  error=f"team {team} has no state named '{match}' "
                                        f"(it has: {', '.join(str(s.get('name')) for s in states)})")
            before = (issue.get("state") or {}).get("name")
            if (issue.get("state") or {}).get("id") == target["id"]:
                outcome = {"issue": issue.get("identifier"), "state": before, "changed": False}
                return ToolResult(success=True, result=json.dumps(outcome), metadata=outcome)
            moved = linear.graphql(_MOVE, {"id": issue["id"], "stateId": target["id"]}).get("issueUpdate") or {}
        except Exception as exc:  # noqa: BLE001 - transport, HTTP or GraphQL: the agent is told
            return ToolResult(success=False, result="", error=f"{type(exc).__name__}: {exc}")
        if not moved.get("success"):
            return ToolResult(success=False, result="", error=f"Linear did not move {issue_ref}: {moved}")
        after = ((moved.get("issue") or {}).get("state") or {}).get("name")
        outcome = {"issue": issue.get("identifier"), "from": before, "state": after, "changed": True}
        logger.info("LinearMoveIssue: %s %s -> %s", outcome["issue"], before, after)
        return ToolResult(success=True, result=json.dumps(outcome), metadata=outcome)
