# Timeout Hierarchy

Timeouts cascade from workflow down to individual LLM calls. Each level caps the one below it.

## Hierarchy

```
Workflow timeout (default: 3600s / 1 hour)
  └── Stage timeout (default: 1800s / 30 min)
       └── Agent safety timeout (default: 300s / 5 min)
            └── LLM inference timeout (default: 1800s / 30 min)
                 └── HTTP connect timeout (default: 30s)
```

## Configuration at Each Level

### Workflow Level

```yaml
workflow:
  config:
    timeout_seconds: 3600      # total workflow timeout
```

### Stage Level

```yaml
stage:
  execution:
    timeout_seconds: 1800      # per-stage timeout
```

### Agent Level (Safety)

```yaml
agent:
  safety:
    max_execution_time_seconds: 300   # agent execution timeout
```

### Agent Level (Inference)

```yaml
agent:
  inference:
    timeout_seconds: 1800     # LLM call timeout
```

### HTTP Level (Internal)

The underlying HTTP client uses:
- `httpx.Timeout(timeout=600, connect=30)` — 600s total, 30s connect

## Retry Delays

Retries add delay between attempts:

### Agent-Level Retries

```yaml
agent:
  inference:
    max_retries: 3
    retry_delay_seconds: 2

  error_handling:
    retry_strategy: ExponentialBackoff
    retry_config:
      initial_delay_seconds: 1
      max_delay_seconds: 30
      exponential_base: 2.0    # delays: 1s, 2s, 4s, 8s, ...
```

### Stage-Level Retries

```yaml
stage:
  error_handling:
    retry_failed_agents: true
    max_agent_retries: 2
```

### Workflow-Level Retries

```yaml
workflow:
  error_handling:
    on_stage_failure: retry
    max_stage_retries: 3
```

## Budget Timeouts

Cost-based timeouts can halt execution before time runs out:

```yaml
workflow:
  config:
    budget:
      max_cost_usd: 10.0
      max_tokens: 100000
      action_on_exceed: halt   # halt | continue | notify
```

Per-round cost budgets in collaboration:

```yaml
stage:
  collaboration:
    config:
      cost_budget_usd: 5.0    # stop dialogue if exceeded
```

## Recommendations

| Scenario | Workflow | Stage | Inference |
|----------|---------|-------|-----------|
| Quick demo | 600s | 300s | 600s |
| Research workflow | 3600s | 1800s | 1800s |
| Multi-round debate | 3600s | 1800s | 1800s |
| Code generation (with loops) | 7200s | 1800s | 1800s |
| Large parallel pipeline | 12000s | 1800s | 1800s |
