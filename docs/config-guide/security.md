# Security Features

Security controls are applied at every layer — config loading, template rendering, agent execution, and tool invocation.

## Jinja2 Sandboxing

All prompt templates use `ImmutableSandboxedEnvironment` to prevent Server-Side Template Injection (SSTI):

- No access to `__class__`, `__subclasses__`, `__globals__`
- No arbitrary Python execution in templates
- Only safe built-in filters and functions
- Internal variables (`show_details`, `detail_console`, `visualizer`) are filtered before rendering

## Config Path Validation

Config file references are validated to prevent path traversal:

- **Absolute paths** — rejected
- **`..` in paths** — rejected
- **Null bytes** — rejected
- **Stage refs** must be relative paths within the config root

```yaml
# Valid
stage_ref: configs/stages/research.yaml

# Invalid (rejected)
stage_ref: /etc/passwd
stage_ref: ../../secrets/keys.yaml
```

## Config Size Limits

| Limit | Value | Purpose |
|-------|-------|---------|
| Max file size | 10 MB | Prevent memory exhaustion |
| Max nesting depth | 20 levels | Prevent stack overflow |
| Max total nodes | 10,000 | Prevent DoS |
| Max prompt length | 32,000 chars | Safety limit |

## Secret Management

Secrets are never stored in plaintext in configs. Use reference patterns:

```yaml
inference:
  # Environment variable
  api_key_ref: "${env:OPENAI_API_KEY}"

  # HashiCorp Vault
  api_key_ref: "${vault:secret/data/llm/openai}"

  # AWS Secrets Manager
  api_key_ref: "${aws:prod/llm/openai-key}"
```

Secrets are:
- Resolved at runtime (never written to disk)
- Redacted in logs and displays
- Not included in observability exports

## Safety Modes

Three safety modes can be set at any layer (agent, stage, workflow):

| Mode | Behavior |
|------|----------|
| `execute` | Normal execution (default) |
| `dry_run` | Simulate without actual LLM calls or tool execution |
| `require_approval` | Pause and wait for human approval before proceeding |

### Safety Composition

When multiple layers define safety modes, the `composition_strategy` determines the result:

```yaml
workflow:
  safety:
    composition_strategy: MostRestrictive   # strictest safety wins
```

With `MostRestrictive`:
- If any layer says `require_approval`, approval is required
- If any layer says `dry_run` (and none say `require_approval`), dry run is used
- Only if all layers say `execute` does normal execution proceed

## Agent Safety Controls

```yaml
agent:
  safety:
    mode: execute
    require_approval_for_tools:     # specific tools needing human OK
      - FileWriter
      - BashCommand
    max_tool_calls_per_execution: 20   # prevent runaway tool loops
    max_execution_time_seconds: 300    # hard timeout
    max_prompt_length: 32000           # reject oversized prompts
    max_tool_result_size: 100000       # truncate large tool results
    risk_level: low                    # low | medium | high
```

## Tool Safety

```yaml
tool:
  safety_checks:
    - input_validation
    - output_sanitization

  rate_limits:
    max_calls_per_minute: 10
    max_calls_per_hour: 100
    max_concurrent_requests: 10
    cooldown_on_failure_seconds: 60

  requirements:
    requires_network: false
    requires_credentials: false
    requires_sandbox: false
```

## Stage Safety

```yaml
stage:
  safety:
    mode: execute
    dry_run_first: false            # run dry-run before real execution
    require_approval: false
    approval_required_when:
      - condition: "risk_score > 0.8"
        action: require_approval

  error_handling:
    on_agent_failure: continue_with_remaining
    min_successful_agents: 2        # stage fails if fewer succeed
```

## Workflow Safety

```yaml
workflow:
  safety:
    global_mode: execute
    approval_required_stages:       # specific stages needing approval
      - production_deployment
    dry_run_stages:                 # stages to always dry-run
      - code_generation

  config:
    budget:
      max_cost_usd: 10.0           # cost cap
      max_tokens: 100000           # token cap
      action_on_exceed: halt       # halt | continue | notify
```

## Action Policy Engine

The framework includes a policy engine (`temper_ai/safety/action_policy_engine.py`) that validates actions at runtime:

- Validates tool calls against configured policies
- Supports sync and async validation
- Built-in policies in `temper_ai/safety/stub_policies.py`
- Custom policies via `configs/safety/action_policies.yaml`

## Security Checklist

- [ ] Use `api_key_ref` with `${env:...}`, never plaintext `api_key`
- [ ] Set appropriate `risk_level` per agent
- [ ] Configure `max_tool_calls_per_execution` to prevent loops
- [ ] Use `require_approval_for_tools` for dangerous tools
- [ ] Set `max_cost_usd` budget to prevent runaway costs
- [ ] Use `dry_run` mode for testing new workflows
- [ ] Review tool `rate_limits` for external APIs
