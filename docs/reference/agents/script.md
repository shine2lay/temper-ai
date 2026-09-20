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
2. Execute via context.tool_executor (Bash tool with workspace + timeout)
3. Return AgentResult with stdout as output

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
```

## Related

- [Bash Tool](../tools/bash.md) — executes the rendered script
