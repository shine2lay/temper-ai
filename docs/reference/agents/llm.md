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
  tools: [Bash, FileWriter] # see tools/
  memory:
    enabled: true
    store_observations: true
    recall_limit: 10
```

## Related

- [LLM Providers](../providers/index.md) — provider backends this agent calls
- [Tools](../tools/index.md) — tools available via `tools:` config
- [Safety Policies](../policies/index.md) — enforce constraints on tool calls
- [Topology Strategies](../strategies/index.md) — how agents are wired in stages
