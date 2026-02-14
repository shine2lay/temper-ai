# Tool Configuration

Tools extend agent capabilities with external functions (calculators, web search, file operations, etc.).

**Location:** `configs/tools/*.yaml`
**Schema:** `src/compiler/schemas.py` (ToolConfig)

## Example

```yaml
tool:
  name: Calculator
  description: "Basic calculator for arithmetic operations"
  version: "1.0"

  implementation:
    type: builtin
    module: src.tools.calculator
    class: CalculatorTool

  safety:
    risk_level: low
    require_approval: false
    max_calls_per_execution: 10
    timeout_seconds: 1

  rate_limits:
    max_calls_per_minute: 10
    max_calls_per_hour: 100
    max_concurrent_requests: 10
    cooldown_on_failure_seconds: 60

  error_handling:
    max_retries: 3
    backoff_strategy: ExponentialBackoff

  requirements:
    requires_network: false
    requires_credentials: false
    requires_sandbox: false
```

## Complete Field Reference

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `name` | string | Yes | — | Tool identifier |
| `description` | string | Yes | — | Human-readable purpose |
| `version` | string | No | `"1.0"` | Version |
| `category` | string | No | null | Tool category |
| `implementation` | string/dict | Yes | — | Python class path or object |
| `default_config` | dict | No | `{}` | Default tool configuration |
| `safety_checks` | list | No | `[]` | Safety check list |
| `rate_limits` | RateLimits | No | defaults | Rate limiting |
| `error_handling` | ToolErrorHandlingConfig | No | defaults | Error handling |
| `observability` | ToolObservabilityConfig | No | defaults | Logging/metrics |
| `requirements` | ToolRequirements | No | defaults | Runtime requirements |

---

## Implementation

### String Format (module path)

```yaml
implementation: "src.tools.calculator.CalculatorTool"
```

### Object Format

```yaml
implementation:
  type: builtin
  module: src.tools.calculator
  class: CalculatorTool
```

---

## Rate Limits

```yaml
rate_limits:
  max_calls_per_minute: 10       # default: 10
  max_calls_per_hour: 100        # default: 100
  max_concurrent_requests: 10    # default: 10
  cooldown_on_failure_seconds: 60  # default: 60
```

---

## Error Handling

```yaml
error_handling:
  retry_on_status_codes: []      # HTTP status codes to retry on
  max_retries: 3
  backoff_strategy: ExponentialBackoff
  timeout_is_retry: false        # treat timeouts as retryable
```

---

## Observability

```yaml
observability:
  log_inputs: true
  log_outputs: true
  log_full_response: false
  track_latency: true
  track_success_rate: true
  metrics: []                    # custom metric names
```

---

## Requirements

```yaml
requirements:
  requires_network: false        # needs internet access
  requires_credentials: false    # needs API keys
  requires_sandbox: false        # needs sandboxed execution
```

---

## Referencing Tools in Agents

Tools are referenced by name in agent configs:

```yaml
# In agent config
agent:
  tools:
    - Calculator              # matches tool.name

  # Or with config overrides
  tools:
    - name: Calculator
      config:
        precision: 10
```

The framework discovers tools from `configs/tools/` and loads them into a `ToolRegistry`.
