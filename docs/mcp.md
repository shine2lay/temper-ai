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
| `list_workflows` | What can be run (filter with `name_contains`) |
| `get_workflow` | One workflow's inputs, shape and models |
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
list_workflows(name_contains="blog")              # what can I run?
get_workflow("blog_writer")                       # what does it need?
run_workflow("blog_writer", {"topic": "otters"})  # -> execution_id
wait_for_run(execution_id, timeout_seconds=120)   # -> status + node lines
get_node_output(execution_id, "draft")            # only if you need detail
```

The second call matters more than it looks. Most workflows declare no
`inputs:` even when they need them, so `get_workflow` also reports
`inputs_referenced` — the names their templates actually use, minus the
ones the engine supplies and the ones another node maps in. It also names
the provider and model each agent asks for, which is what turns "provider
'openai' not configured" into something you can act on.

When something fails, `get_run` names the failed nodes (including nested
ones inside dispatch or parallel stages) and gives a `failure_summary`
that explains the run even when it died before any node existed — a bad
template expansion, say, where the list of failed nodes is empty.
Retried agents are labelled `attempt: "1 of 2"` rather than appearing
twice.

## Serving it beyond localhost

Agents rarely run on the same machine as temper, and two things have to be
right before a remote one can connect.

**1. Name the host.** The MCP SDK refuses any request whose `Host` header
it does not recognise — that is what stops a web page from driving a local
MCP server through a victim's browser (DNS rebinding). Reaching the
endpoint under a real hostname therefore means declaring it, otherwise the
server answers `421 Misdirected Request`, which reads like a network fault
rather than a configuration one:

```bash
TEMPER_MCP_ALLOWED_HOSTS=temper.example.com,host.tailnet.ts.net
```

localhost and 127.0.0.1 keep working without configuration.

**2. Put something in front of it.** Published ports bind to `127.0.0.1`
by default, because the dashboard and the MCP endpoint have no
authentication and should not be reachable from the LAN just because the
host has an address on it. Terminate TLS somewhere that also restricts who
can reach it — a private-network gateway, a reverse proxy, an SSH tunnel:

```json
{ "mcpServers": { "temper": { "url": "https://temper.example.com/mcp" } } }
```

Set `TEMPER_BIND=0.0.0.0` only when you have decided something else is
doing the restricting.

## Embedding the dashboard

The dashboard refuses to be framed by default — an embedded copy of an
unauthenticated UI is a clickjacking target, and every button here can
spend money. Naming the origins that may embed it lifts that for those
origins only:

```bash
TEMPER_FRAME_ANCESTORS=https://pi.example.com
TEMPER_FRAME_ANCESTORS="https://pi.example.com https://host.tailnet.ts.net:8787"
```

Space- or comma-separated, and each entry must be a full origin (scheme +
host + optional port). `*` is rejected rather than quietly trusted. When
the variable is set the server publishes
`Content-Security-Policy: frame-ancestors 'self' <origins>` and stops
sending `X-Frame-Options`, because that header cannot express an
allow-list and browsers honouring it would block the origin just allowed.
Unset, the responses are unchanged: `frame-ancestors 'none'` plus
`X-Frame-Options: DENY`.

The embedding page can still only reach temper if the network lets it —
this setting relaxes the browser's framing rule, not the reverse proxy's
access rules.

## Authentication

Set `TEMPER_API_TOKEN` and the server requires a bearer token on the API,
the MCP endpoint and the WebSocket. Unset, everything is open — which is
the default, so nothing changes on upgrade.

```json
{
  "mcpServers": {
    "temper": {
      "url": "https://temper.example.com/mcp",
      "headers": { "Authorization": "Bearer <TEMPER_API_TOKEN>" }
    }
  }
}
```

The stdio bridge picks the token up from the environment, or takes
`--token`:

```bash
temper mcp --url https://temper.example.com/mcp --token "$TEMPER_API_TOKEN"
```

### More than one client

`TEMPER_API_TOKEN` is a single shared secret: everyone who has it is
indistinguishable, and withdrawing it withdraws it from everyone. For
several clients, point `TEMPER_API_TOKENS_FILE` at a JSON file:

```json
{ "ci": "…", "laptop": "…", "bot": "…" }
```

In Docker, mount it yourself and point the variable at it — it is not
mounted by default, because a bind mount for a file that does not exist
makes Docker create a directory of that name:

```yaml
volumes: [./my-tokens.json:/app/tokens.json:ro]
environment: { TEMPER_API_TOKENS_FILE: /app/tokens.json }
```

Each name is accepted independently and the file is re-read when it changes,
so deleting a name stops that client on its **next request** rather than at
the next restart — which is the only behaviour that makes "revocable" mean
anything when a token has leaked. Both mechanisms can be used together; the
shared token reports as the client `shared`.

An unreadable or missing file grants nothing and is logged. It deliberately
does not fail open: a typo in a config file should not turn into an open
server.
```

The check lives in middleware rather than on the route handlers, because
the MCP tools call those handlers in-process: a route dependency would
have secured HTTP callers and let every MCP call through.

## Notes

- `run_workflow` really does spend money — it runs the same engine as the
  dashboard's New Run button.
- Omitting `workspace_path` uses the server's default, exactly as the REST
  API does.
