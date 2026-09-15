# MCP — let agents run and inspect workflows

Temper speaks [MCP](https://modelcontextprotocol.io), so a coding agent can
start a workflow, wait for it, and read what happened inside it — the same
data the dashboard shows, through the same code paths the REST API uses.

## Connecting

The server exposes MCP at **`/mcp`** whenever it is running:

```json
{ "mcpServers": { "temper": { "url": "http://localhost:8420/mcp" } } }
```

Clients that only speak stdio can use the bridge, which proxies to that
same endpoint (so it can never report on a different engine than the one
running):

```json
{
  "mcpServers": {
    "temper": { "command": "temper", "args": ["mcp", "--url", "http://localhost:8420/mcp"] }
  }
}
```

Check it without a client:

```bash
curl -s -X POST http://localhost:8420/mcp \
  -H 'content-type: application/json' \
  -H 'accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"probe","version":"1"}}}'
```

## The tools

| Tool | Use it for |
|---|---|
| `list_workflows` | What can be run, and which inputs each declares |
| `list_runs` | Recent runs, filtered by workflow or status |
| `run_workflow` | Start a run; returns an `execution_id` immediately |
| `wait_for_run` | Block until a run finishes (returns `timed_out` rather than failing) |
| `get_run` | Status plus one line per node |
| `get_node_output` | What one node produced |
| `get_llm_call` | The prompt, response and thinking of one call |
| `cancel_run` | Stop a running workflow |
| `list_gates` / `approve_gate` | See and release approval gates |

## Why inspection is layered

A real run's full detail payload is big: a `blog_writer` run measured
**92 KB — about 23,500 tokens**. Returning that from one tool call would
consume a large share of the calling agent's context before it has done
any work.

So the tools are summary-first. The same run through `get_run`:

```
raw REST payload : 92.0 KB  (~23,540 tokens)
MCP get_run      :  1.2 KB  (~298 tokens)     99% smaller
```

…while still answering the questions that matter:

```json
{
  "workflow": "blog_writer", "status": "completed",
  "total_cost_usd": 0.322, "total_tokens": 238151,
  "nodes": [
    {"name": "research", "status": "completed", "duration_seconds": 41.6, "tokens": 84021},
    {"name": "draft",    "status": "completed", "duration_seconds": 73.2, "tokens": 96334},
    {"name": "edit",     "status": "completed", "duration_seconds": 30.9, "tokens": 57796}
  ],
  "failed_nodes": []
}
```

The heavy material is one deliberate call away: `get_node_output` for what
a node produced, `get_llm_call` for a prompt and response. Every free-text
field is truncated at `max_chars` (4000 by default) and says how much it
dropped, so a surprise costs a few thousand tokens rather than a hundred
thousand.

## A typical loop

```python
list_workflows()                                  # what can I run?
run_workflow("blog_writer", {"topic": "otters"})  # -> execution_id
wait_for_run(execution_id, timeout_seconds=120)   # -> status + node lines
get_node_output(execution_id, "draft")            # only if you need detail
```

When something fails, `get_run` names the failed nodes (including nested
ones inside dispatch or parallel stages), so the drill-down is one call
rather than a search.

## Notes

- **No authentication.** The MCP endpoint inherits the API's posture, so
  expose the server only on a trusted network.
- `run_workflow` really does spend money — it runs the same engine as the
  dashboard's New Run button.
- Omitting `workspace_path` uses the server's default, exactly as the REST
  API does.
