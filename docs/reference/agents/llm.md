[Home](../index.md) | [Tools](../tools/index.md) | [LLM Providers](../providers/index.md) | **Agent Types** | [Safety Policies](../policies/index.md) | [Topology Strategies](../strategies/index.md)

# `llm` Agent

[Back to Agent Types](index.md)

LLM agent — uses LLM with Jinja2 prompt templates, tools, and memory.

All infrastructure comes from ExecutionContext at run time:
- LLM provider: context.get_llm(self.provider)
- Tools: context.tool_executor
- Memory: context.memory_service
- Events: context.event_recorder

Agent config drives per-call LLM behavior (model, temperature, etc.).

Agent that uses LLM with Jinja2 prompt templates, tools, and memory.

## Execution Pipeline

Execute the LLM agent pipeline.

1. Recall memories (if memory enabled in config)
2. Render prompt via PromptRenderer (Jinja2 template + variables)
3. Get LLM provider from context
4. Call LLM (tool-calling loop)
5. Extract structured output (best-effort JSON parse)
6. Store agent output to memory (mem0 extracts facts internally)
7. Return AgentResult with all tracking data

## Validation

Return list of config validation errors. Empty = valid.

## Config Options

```yaml
agent:
  name: "my_agent"
  type: "llm"
  provider: "openai"        # see providers/
  model: "gpt-4o"           # Model identifier
  system_prompt: "You are..."  # System message (plain string)
  task_template: "{{ task }}"  # Jinja2 user prompt template
  # Optional:
  temperature: 0.7
  max_tokens: 4096
  max_iterations: 10        # Tool-calling loop limit
  token_budget: 8000        # Prompt token budget
  max_context_tokens: 100000 # Window the tool-calling loop must stay under
  context_policy: truncate  # What happens at the window: truncate | compress
  tools: [Bash, FileWriter] # see tools/
  memory:
    enabled: true
    store_observations: true
    recall_limit: 10
```

## Context Policy

A long tool-calling run outgrows `max_context_tokens`. `context_policy`
chooses what the agent does about it. It is per agent; an agent that says
nothing gets `truncate`.

**`truncate`** (default) — mechanical. Once the estimate passes the limit,
the message list is windowed and every tool result is cut to its first
5000/2000/1000 characters. Silent, and it keeps the wrong half of a build
log, but it is what every existing agent has always had.

**`compress`** — the model manages its own context. Every user message and
tool result it sees ends with a ref tag (`<acp tokens="9.3K">m00004</acp>`),
and it has four extra tools:

| Tool | Does |
|---|---|
| `compress` | Replace one or more contiguous ranges (`m00003`–`m00006`, or block ids `b1`–`b3` to fold blocks into a higher tier) with a summary the model writes. All ranges apply or none. |
| `decompress` | Return a block's original content one tier up. The block stays compressed. |
| `search_context` | Keyword search across the whole transcript, including compressed and evicted content. |
| `context_status` | Usage, blocks, and the largest compressible ranges. |

The transcript itself is never edited. The provider gets a *view*: a
compressed range is replaced, where it stood, by one message headed
`[Compressed b1 — topic]` holding the model's summary, so the view stays in
chronological order and what the model remembers is exactly what it chose
to write down. Every summary is an ordinary tool call in the run's event
log, so it can be audited afterwards.

At 60% of the limit the harness adds a `[context]` message after the latest
tool result saying how full the window is and which ranges are largest. It
is a message of its own, not a line inside the tool result — models are
trained to discount instructions found in tool output, and one ignored the
inline form at 97% usage on every turn.

If the model does not act and the hard limit is reached, the oldest tool
results outside the current turn are evicted and replaced by a visible stub
(`[evicted to stay under the context limit: Read result, ~9.4K tokens.
Re-run the tool if you need it.]`). Receipts from the context tools are
never evicted — they are the model's only record of what it did to its own
context. A summary written over already-evicted content is marked as such
in the block header, since what it says about those messages is the
model's memory, not the content.

An unknown value fails at construction:
`context_policy must be one of truncate, compress, not 'evict'`.

Measured on a four-file read task (~35K tokens of results against a 24K
window, claude-haiku-4-5): `compress` finished in 6 iterations with one
model-written summary and zero evictions, 56K tokens total; all four answers
correct, two of them from the model's own summary after the raw content was
gone.

## Related

- [LLM Providers](../providers/index.md) — provider backends this agent calls
- [Tools](../tools/index.md) — tools available via `tools:` config
- [Safety Policies](../policies/index.md) — enforce constraints on tool calls
- [Topology Strategies](../strategies/index.md) — how agents are wired in stages
