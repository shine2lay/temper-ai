[Home](../index.md) | [Tools](../tools/index.md) | [LLM Providers](../providers/index.md) | **Agent Types** | [Safety Policies](../policies/index.md) | [Topology Strategies](../strategies/index.md)

# `script` Agent

[Back to Agent Types](index.md)

Script agent — executes a Jinja-rendered bash script.

No LLM calls. Renders a script template with input_data,
executes via tool_executor (Bash tool), returns stdout as output.

Agent that executes a Jinja-rendered bash script.

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
