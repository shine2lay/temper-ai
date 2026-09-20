[Home](../index.md) | [Tools](../tools/index.md) | [LLM Providers](../providers/index.md) | [Agent Types](../agents/index.md) | **Safety Policies** | [Topology Strategies](../strategies/index.md)

# `forbidden_ops` Policy

[Back to Safety Policies](index.md)

Block shell commands matching dangerous patterns.

Config:
    type: forbidden_ops
    forbidden_patterns: ["rm -rf", "DROP TABLE", ...]  # optional, has defaults
    forbidden_regexes: ["/proc/\S+/environ"]           # optional, case-insensitive

A pattern matches the command text case-insensitively as a substring,
except that a bare word (letters, digits, underscore only: TRUNCATE,
mkfs) must match a whole word. The first `platform_baseline` blocked
every epd_task run at stack_up because that agent's script has a
comment saying a long name is "silently truncated"; "truncated" is not
a TRUNCATE. Patterns with spaces or punctuation ("rm -rf /", "> /dev/sd")
keep matching as prefixes/substrings, since that is what they are for.

- **Evaluates on:** `tool_call`

Applies to [Bash](../tools/bash.md) tool commands.

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
    - type: forbidden_ops
      # Uses safe defaults. Override with:
      # forbidden_patterns: ["rm -rf /", "DROP TABLE"]
```

## Related

- [Tools](../tools/index.md) — actions gated by policies
- [LLM Agent](../agents/llm.md) — agents whose tool calls are checked
