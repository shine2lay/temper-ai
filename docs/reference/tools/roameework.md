[Home](../index.md) | **Tools** | [LLM Providers](../providers/index.md) | [Agent Types](../agents/index.md) | [Safety Policies](../policies/index.md) | [Topology Strategies](../strategies/index.md)

# `RoameeWork` Tool

[Back to Tools](index.md)

> What is open and what has landed on roamee (shine2lay/roamee on GitHub, team ROA in Linear). what='pulls' lists the open pull requests; what='commits' the most recent commits on the staging branch; what='checks' how the checks on that branch's latest commit went (failing ones first); what='issues' the open Linear issues. Read-only: it opens, closes, comments on and changes nothing.

The ``roamee_answer`` workflow already reads a fresh read-only copy of the
repository. These add the three other places a question about roamee can
only be answered from, and each is read-only by construction:

* :class:`RoameeStack` — the three staging containers: up or down, healthy or
  not, which build, since when, how many restarts, the tail of a log.
* :class:`RoameeData`  — staging's database: its tables, one table's shape, or
  one plain read.
* :class:`RoameeWork`  — roamee's open pull requests, recent commits, failing
  checks (GitHub) and open issues (Linear's ROA team).

How the first two reach anything at all: a run happens inside its own
container, with no docker socket and no route to roamee's network, so they
ask ``roamee-reader`` — a small service on the host, over a unix socket in a
folder temper's containers have mounted read-only (scripts/roamee_reader.py,
docs/roamee.md). The fence lives in that service: the three container names,
an allowlist of fields that leaves out the environment, the command line and
the mounts, a login that may only read, a row cap, a statement timeout, and
every answer blanked of anything shaped like a key.

None of the three has a parameter that takes a shell command, and none can
write: there is no endpoint on the other side that would.

- **Modifies state:** No (read-only)

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `what` | `pulls` \| `commits` \| `checks` \| `issues` | Yes | Which list you want. |
| `limit` | integer | No | How many, 1-30. Default 10. |
| `branch` | string | No | Branch for 'commits' and 'checks'. Default staging. |

## Usage

Add `RoameeWork` to an [LLM agent](../agents/llm.md)'s tools list:

```yaml
agent:
  name: my_agent
  type: llm
  tools: [RoameeWork]
```

## Related

- [LLM Agent](../agents/llm.md) — agents that use tools
- [Safety Policies](../policies/index.md) — gate tool execution
