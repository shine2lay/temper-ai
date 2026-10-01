[Home](../index.md) | **Tools** | [LLM Providers](../providers/index.md) | [Agent Types](../agents/index.md) | [Safety Policies](../policies/index.md) | [Topology Strategies](../strategies/index.md)

# `RoameeStack` Tool

[Back to Tools](index.md)

> Look at roamee's staging stack on the box: the three containers (roamee-staging-frontend-1, roamee-staging-backend-1, roamee-staging-postgres-1). what='status' says, for each one, whether it is running, whether its health check passes, which build (commit) it is running, when it started, how long it has been up and how many times it has restarted. what='logs' gives the tail of one container's log (name it in container=, up to 200 lines). Read-only: it cannot start, stop, change or run anything, and it looks at no other project's containers. Environment variables, command lines and mounts are never returned.

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
| `what` | `status` \| `logs` | Yes | 'status' for all three containers, 'logs' for one container's log tail. |
| `container` | `roamee-staging-frontend-1` \| `roamee-staging-backend-1` \| `roamee-staging-postgres-1` | No | Which container's log to read. Only for what='logs'. |
| `lines` | integer | No | Log lines from the end, 1-200. Default 40. |

## Usage

Add `RoameeStack` to an [LLM agent](../agents/llm.md)'s tools list:

```yaml
agent:
  name: my_agent
  type: llm
  tools: [RoameeStack]
```

## Related

- [LLM Agent](../agents/llm.md) — agents that use tools
- [Safety Policies](../policies/index.md) — gate tool execution
