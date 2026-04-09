[Home](../index.md) | [Tools](../tools/index.md) | [LLM Providers](../providers/index.md) | [Agent Types](../agents/index.md) | **Safety Policies** | [Topology Strategies](../strategies/index.md)

# `budget` Policy

[Back to Safety Policies](index.md)

Enforce cost and token limits for a workflow run.

Checks accumulated cost/tokens from context before allowing
further tool calls. The executor passes running totals in context.

Config:
    type: budget
    max_cost_usd: 1.00     # max total cost for the run
    max_tokens: 100000     # max total tokens for the run

- **Evaluates on:** `tool_call`, `llm_call`, `workflow_start`

Tracks cumulative cost across all [LLM provider](../providers/index.md) calls in a run.

## Required Config

- BudgetPolicy needs 'max_cost_usd' or 'max_tokens' (or both)

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
    - type: budget
      max_cost_usd: 5.00
      max_tokens: 500000
```

## Related

- [Tools](../tools/index.md) — actions gated by policies
- [LLM Agent](../agents/llm.md) — agents whose tool calls are checked
