[Home](../index.md) | **Tools** | [LLM Providers](../providers/index.md) | [Agent Types](../agents/index.md) | [Safety Policies](../policies/index.md) | [Topology Strategies](../strategies/index.md)

# `LinearMoveIssue` Tool

[Back to Tools](index.md)

> Move a Linear issue to another workflow state, e.g. 'In Progress' when you start work and 'In Review' when its pull request is open. Changes the issue's state and nothing else.

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

- **Modifies state:** Yes

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `issue` | string | Yes | The issue's id or identifier, e.g. ROA-5 |
| `state` | string | Yes | Name of the state to move it to: 'In Progress' or 'In Review' |

## Usage

Add `LinearMoveIssue` to an [LLM agent](../agents/llm.md)'s tools list:

```yaml
agent:
  name: my_agent
  type: llm
  tools: [LinearMoveIssue]
```

## Related

- [LLM Agent](../agents/llm.md) — agents that use tools
- [Safety Policies](../policies/index.md) — gate tool execution
