[Home](../index.md) | [Tools](../tools/index.md) | [LLM Providers](../providers/index.md) | [Agent Types](../agents/index.md) | **Safety Policies** | [Topology Strategies](../strategies/index.md)

# `file_access` Policy

[Back to Safety Policies](index.md)

Restrict file operations to allowed paths and block denied paths.

Config:
    type: file_access
    allowed_paths: ["/workspace"]        # only these paths allowed (if set)
    denied_paths: [".env", "credentials"] # these patterns always blocked

- **Evaluates on:** `tool_call`

Applies to file-modifying tools: [Bash](../tools/bash.md), [FileWriter](../tools/filewriter.md).

## Required Config

- FileAccessPolicy needs 'denied_paths' or 'allowed_paths'

## Evaluation Logic

Evaluate whether an action should be allowed.

Args:
    action_type: What kind of action (TOOL_CALL, WORKFLOW_START, etc.)
    action_data: Action-specific data (e.g., tool_name, tool_params for TOOL_CALL)
    context: Execution context (run_id, agent_name, accumulated cost, etc.)

Returns:
    PolicyDecision with action="allow", "deny", or "modify".

## YAML Example

```yaml
safety:
  policies:
    - type: file_access
      denied_paths: [".env", "credentials", "/etc/"]
      allowed_paths: ["/workspace"]  # optional
```

## Related

- [Tools](../tools/index.md) — actions gated by policies
- [LLM Agent](../agents/llm.md) — agents whose tool calls are checked
