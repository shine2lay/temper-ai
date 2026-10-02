[Home](../index.md) | [Tools](../tools/index.md) | [LLM Providers](../providers/index.md) | **Agent Types** | [Safety Policies](../policies/index.md) | [Topology Strategies](../strategies/index.md)

# `script` Agent

[Back to Agent Types](index.md)

Script agent — executes a Jinja-rendered bash script.

No LLM calls. Renders a script template with input_data,
executes via tool_executor (Bash tool), returns stdout as output.

Agent that executes a Jinja-rendered bash script.

`strict_undefined: true` in the agent config turns an undefined reference into a failed node
instead of a blank. It is opt-in rather than the default because 82 configs use this agent type
with 26 distinct bare references between them: flipping the default would fail those nodes at run
time, deep in a pipeline, after the stages before them had already been paid for. New glue — where
a blank argument is dangerous — should set it.

## Execution Pipeline

Execute the script agent pipeline.

1. Render Jinja template from config["script_template"] with input_data
2. Execute via context.tool_executor (Bash tool with workspace + timeout), saving what the
   script prints to this attempt's log as it arrives (agent/script_log.py)
3. Return AgentResult with stdout as output; the log's figures go on the completion
   event beside it, never into it

## Validation

Return list of config validation errors. Empty = valid.

## Config Options

```yaml
agent:
  name: "my_agent"
  type: "script"
  script_template: |        # Jinja2 bash template
    echo "Hello {{ name }}"
  timeout_seconds: 30
  log_max_bytes: 10000000   # Saved output per attempt, UTF-8 bytes (the default)
```

## Output while it runs, and its saved log

What the script prints to stdout and stderr is saved while it runs, a few
times a second, and shown as it arrives. Each attempt has a log of its own
(a retry, or two agents with the same name running side by side, never
share one), and it stays with the run's results.

**Where to read it.**
- The run page: select the agent in the live panel. A script agent shows
  its output there instead of a story, each line timed to the millisecond,
  with stderr lines marked `err`. It follows new lines unless you scroll up
  to read; "Load older output" reads further back.
- The agent's full-screen view: the *Output, live* fold (*Output log* once
  it has ended) shows the same log.
- The API: `GET /api/runs/<run id>/agents/<agent id>/log`, the agent id
  being its `agent.started` event's id. With neither cursor it returns the
  newest page; `before_seq=N` pages back, `after_seq=N` reads on from row
  N. A page holds `max_bytes` of output (256 KB unless asked, 4 MB at most)
  and says whether there is more either side. Same token as the rest of
  the API.

The saved rows are `script.log` events of the run, numbered from 1 within
the attempt. The run's detail (what the run page loads) and the MCP
`get_events` listing leave them out, so a long log never slows either; ask
for them by type, or use the route above.

**How it ends.** The last line of a log is a note saying how the attempt
ended: `[finished: exit code 0]`, `[failed: exit code 3]`,
`[timed out after 30s: ...]` or `[cancelled: the run was stopped]`. A script
that fails, times out or is stopped keeps everything it printed until then.
A log without that note did not finish saving (the worker died, or the
database was down), and the page marks it *log incomplete*.

**The limit.** An attempt saves up to `log_max_bytes` of output, 10,000,000
UTF-8 bytes unless set (`0` saves none). Past it, one note in the log says
the limit was reached; the rest is counted but not saved, and the script
runs on as before: its output is still read, so it never stalls on a full
pipe. The page shows what was saved against the limit. The limit is only on
the saved log: the agent's result and its JSON hand-off are built as they
always were, and nothing from the log (labels, times, notes) is ever put
into them.

**Buffering.** A line shows once the program has written it, and many
programs hold their output back when it isn't going to a terminal, so it
arrives in one lump at the end. Make the script flush as it goes:
`python3 -u` or `PYTHONUNBUFFERED=1`, `print(..., flush=True)`,
`stdbuf -oL some-command` for programs built on C stdio, or an explicit
flush after each line. Shell builtins such as `echo` and `printf` write
straight away.

## Related

- [Bash Tool](../tools/bash.md) — executes the rendered script
