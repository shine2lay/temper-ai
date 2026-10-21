[Home](../index.md) | [Tools](../tools/index.md) | [LLM Providers](../providers/index.md) | **Agent Types** | [Safety Policies](../policies/index.md) | [Topology Strategies](../strategies/index.md)

# `single_call` Agent

[Back to Agent Types](index.md)

A fixed-input, write-once call. No service, tools, memory, templates or repair.

Controls use, not credential isolation. Admission, root provisioning/durable parent,
process containment and experiment-wide accounting belong to the later workflow.

The generic snippet below is schematic, not a runnable configuration.

Required provider, model and fixed inputs are specified in the
[full single_call contract](../../single-call.md). No workflow is activated.

## Execution Pipeline

Execute the agent's task. Must be implemented by subclasses.

## Validation

Return list of config validation errors. Empty = valid.

## Config Options

```yaml
agent:
  name: "my_agent"
  type: "single_call"
```

## Related

