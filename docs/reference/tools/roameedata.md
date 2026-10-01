[Home](../index.md) | **Tools** | [LLM Providers](../providers/index.md) | [Agent Types](../agents/index.md) | [Safety Policies](../policies/index.md) | [Topology Strategies](../strategies/index.md)

# `RoameeData` Tool

[Back to Tools](index.md)

> Read roamee's staging database (never change it). what='tables' lists every table with a row estimate and its size; what='columns' with table= gives one table's columns and types; what='read' with sql= runs ONE plain SELECT and returns at most 50 rows — use it for counts and shapes, e.g. "select count(*) from trips" or "select status, count(*) from trips group by 1 order by 2 desc". It connects as a login that may only read, under a 5-second limit, so anything that writes, or that takes too long, is refused and nothing changes. Columns whose name sounds like a secret come back blanked.

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
| `what` | `tables` \| `columns` \| `read` | Yes | 'tables', 'columns' (with table=), or 'read' (with sql=). |
| `table` | string | No | Table name, for what='columns'. |
| `sql` | string | No | One SELECT, for what='read'. No writes, one statement. |

## Usage

Add `RoameeData` to an [LLM agent](../agents/llm.md)'s tools list:

```yaml
agent:
  name: my_agent
  type: llm
  tools: [RoameeData]
```

## Related

- [LLM Agent](../agents/llm.md) — agents that use tools
- [Safety Policies](../policies/index.md) — gate tool execution
