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
  context_policy: compress  # What happens at the window: compress (default) | truncate
  fallback:                 # Where calls go when the model is out of capacity
    - claude-sonnet-5
  tools: [Bash, FileWriter] # see tools/
  memory:
    enabled: true
    store_observations: true
    recall_limit: 10
```

## Context Policy

A long tool-calling run outgrows `max_context_tokens`. `context_policy`
chooses what the agent does about it. It is per agent; an agent that says
nothing gets `compress`.

**`compress`** (default) — the model manages its own context. Every user
message and tool result it sees ends with a ref tag
(`<acp tokens="9.3K">m00004</acp>`), and it has four extra tools, appended
after its own:

| Tool | Does |
|---|---|
| `compress` | Replace one or more contiguous ranges (`m00003`–`m00006`, or block ids `b1`–`b3` to fold blocks into a higher tier) with a summary the model writes. All ranges apply or none. |
| `decompress` | Return a block's original content one tier up. The block stays compressed. |
| `search_context` | Keyword search across the whole transcript, including compressed and harness-hidden content. |
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

If the model does not act and the hard limit is reached, the harness hides
the oldest turns, whole, behind a block of its own — the same mechanism as
`compress`, but with a listing for a summary (`[Compressed b1 — hidden by
the harness] … 8 turn(s): Read ×8. decompress b1 to read it`), so nothing
is summarized and the model is told so in the next `[context]` message. The
block grows at its end as more has to go, so a model that never compresses
costs one rendered block, not a stub per hidden result; the model can fold
it into a block of its own later, and a summary that does is marked in its
header as covering that content from memory only. Blocks the model wrote
are never put under a harness block. Verified to 1,200 turns (~2,400
messages) in a 10K window with a scripted model, a fuzzed one and one that
never compresses: the view never exceeds the limit and every message is
visible, summarized or hidden exactly once (`tests/test_llm/test_context_longrun.py`).

Two things `compress` does not do. A run without tools makes one provider
call and returns — there is nothing to compact — so it is sent as it is,
without the tags, the guidance or the four tools: a prompt that never
carried tools does not start carrying them. And once the iteration budget's
wrap-up note has told the model to answer from what it knows (the last
three turns), the `[context]` usage nudge stays out of the same view: a
compress call is a turn, and asking for one alongside a final answer costs
a turn the budget does not have. What the harness had to hide is still
reported. A compress turn counts against `max_iterations` like any other;
an agent that reads a lot on a short budget should be given a longer one.

**`truncate`** — mechanical, and what every agent had before `compress`
became the default. Once the estimate passes the limit, the message list is
windowed and every tool result is cut to its first 5000/2000/1000
characters. Silent — the model is not told anything was removed — and it
keeps the head of each result, which for a build log is the wrong half. It
also edits the transcript in place. For an agent whose model cannot be
trusted with the tools, or whose provider does not accept them.

An unknown value fails at construction:
`context_policy must be one of truncate, compress, not 'evict'`.

Measured on a four-file read task (~35K tokens of results against a 24K
window, claude-haiku-4-5): `compress` finished in 6 iterations with one
model-written summary and nothing hidden by the harness, 56K tokens total;
all four answers correct, two of them from the model's own summary after the
raw content was gone.

## Fallback

When the agent's model is out of capacity, the call goes to the next entry
of `fallback`, and so on down the list. An entry is a model name, which
stays on the agent's provider, or a mapping that can change the provider
and its settings:

```yaml
agent:
  provider: anthropic
  model: claude-opus-5-5
  provider_config: {effort: max}
  fallback:
    - claude-sonnet-5              # same provider; provider_config still applies
    - provider: openai             # another provider; its own settings only
      model: gpt-5.6-luna
      provider_config: {effort: medium}
```

**What counts as out of capacity:**
- a 429 (rate or usage limit);
- a 529 (Anthropic overloaded);
- Anthropic's 400 for an API account out of credit;
- a token pool with every subscription cooling;
- the same failures when a provider reports them as text, e.g. the Codex
  transport's `HTTP 429`.

Anything else is raised as before: a bad request, an auth failure or a
timeout would fail the same way on the next model, or is a fault worth
seeing. With no list, a limit fails the call as it always did.

**What moves with the call:**
- The whole transcript and the tools go to the new model.
- On the agent's own provider, the agent's `provider_config` still applies,
  with the entry's laid over it key by key.
- On another provider only the entry's `provider_config` is sent. The
  agent's was written for a provider it is no longer talking to.
- An entry without `model` uses that provider's default model.

**Which entries are passed over.** An entry is skipped, and the skip
recorded with its reason, when:
- its provider isn't configured on this server;
- the agent has tools and the provider can't offer them;
- it names the model already in use.

**How long a move lasts.** For the rest of the run, not the turn. Switching
back would throw away the new model's warm prompt cache, and the limit
behind the move resets in hours or days. The agent's next run starts on its
own model again.

**Where a pooled provider fits.** Its own rollover comes first: an Anthropic
call that is rate limited moves to the next pooled subscription. The list
takes over when that has run out, which in practice means one model
family's weekly allowance spent on every account at once. A provider
without a pool retries a 429 itself a few times (a few seconds) before the
list is used.

**The record.** Each move is an `llm.fallback` event carrying `from`, `to`,
`reason`, `skipped` and `remaining`. When the list runs out, the event has
status `failed` and `to: null`, and the last limit is raised. The failed
call's `llm.call.failed` names the model that failed. Each
`llm.call.started` names the model actually asked.

A workflow can give every agent the same list with `defaults: {fallback:
[...]}`. An agent's own `fallback` replaces it. Agents that call no LLM
(Jev, script) aren't given it. A malformed list fails when the agent is
loaded, e.g. `fallback[0] has unknown key(s) modle; allowed: provider,
model, provider_config`, not on the day a limit is finally hit.

## Related

- [LLM Providers](../providers/index.md) — provider backends this agent calls
- [Tools](../tools/index.md) — tools available via `tools:` config
- [Safety Policies](../policies/index.md) — enforce constraints on tool calls
- [Topology Strategies](../strategies/index.md) — how agents are wired in stages
