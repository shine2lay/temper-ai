# Agent Configuration

An agent wraps an LLM with a prompt, optional tools, and safety/observability settings.

**Location:** `configs/agents/*.yaml`
**Schema:** `src/schemas/agent_config.py`

## Minimal Agent

```yaml
agent:
  name: simple_researcher
  description: "Basic research agent"

  prompt:
    inline: |
      You are a research analyst. Analyze: {{ topic }}

  inference:
    provider: ollama
    model: llama3.2:3b
    base_url: http://localhost:11434
    temperature: 0.7
    max_tokens: 4096
    timeout_seconds: 1800

  tools: []

  error_handling:
    retry_strategy: ExponentialBackoff
    max_retries: 3
    fallback: GracefulDegradation
    escalate_to_human_after: 3
```

## Top-Level Structure

```yaml
agent:            # Required: all agent fields nested here
  # ... fields below
schema_version:   # Optional, default "1.0"
```

## Complete Field Reference

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `name` | string | Yes | — | Unique identifier |
| `description` | string | Yes | — | Purpose/role |
| `version` | string | No | `"1.0"` | Config version |
| `type` | string | No | `"standard"` | `standard`, `debate`, `human`, `custom` |
| `prompt` | PromptConfig | Yes | — | Prompt configuration |
| `inference` | InferenceConfig | Yes | — | LLM inference settings |
| `tools` | list or null | No | `null` | Tool names or references |
| `safety` | SafetyConfig | No | defaults | Safety constraints |
| `memory` | MemoryConfig | No | disabled | Memory settings |
| `error_handling` | ErrorHandlingConfig | Yes | — | Error/retry policy |
| `merit_tracking` | MeritTrackingConfig | No | enabled | Merit tracking |
| `observability` | ObservabilityConfig | No | all on | Logging/metrics |
| `metadata` | MetadataConfig | No | — | Tags, owner, docs |
| `dialogue_aware` | bool | No | `true` | Auto-inject dialogue context |
| `max_dialogue_context_chars` | int | No | `8000` | Max dialogue context size |

---

## Prompt Config

Exactly **one** of `inline` or `template` must be set.

### Inline Prompt (most common)

```yaml
prompt:
  inline: |
    You are a {{ role }} agent.
    Topic: {{ topic }}
```

### External Template File

```yaml
prompt:
  template: "prompts/researcher_base.txt"   # relative to configs/
  variables:
    role: "analyst"
```

### Template Features (Jinja2 Sandboxed)

| Feature | Syntax | Example |
|---------|--------|---------|
| Variables | `{{ var }}` | `{{ topic }}` |
| Defaults | `{{ var \| default('x') }}` | `{{ depth \| default('medium') }}` |
| Conditionals | `{% if ... %} ... {% endif %}` | `{% if dialogue_history %}...{% endif %}` |
| Loops | `{% for x in list %} ... {% endfor %}` | `{% for entry in dialogue_history %}...{% endfor %}` |
| Filters | `{{ var \| filter }}` | `{{ text \| length }}` |

### Auto-Injected Variables

These variables are automatically available in agent prompts at runtime:

- `agent_name` — the agent's name
- `tools` — list of available tools
- `dialogue_history` — prior round outputs (multi-round stages)
- `stage_outputs` — outputs from prior stages
- `round_number` — current round (multi-round stages)
- `max_rounds` — max rounds configured
- `agent_role` — role assigned in stage collaboration

---

## Inference Config

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `provider` | enum | — (required) | `ollama`, `vllm`, `openai`, `anthropic`, `custom` |
| `model` | string | — (required) | Model ID (e.g. `llama3.2:3b`, `gpt-4`) |
| `base_url` | string | provider default | API endpoint |
| `api_key_ref` | string | null | Secret ref: `${env:VAR}`, `${vault:path}`, `${aws:id}` |
| `api_key` | string | null | **Deprecated** — use `api_key_ref` |
| `temperature` | float | `0.7` | Randomness (0.0–2.0) |
| `max_tokens` | int | `2048` | Max response tokens |
| `top_p` | float | `0.9` | Nucleus sampling (0.0–1.0) |
| `timeout_seconds` | int | `1800` | Request timeout (30 min) |
| `max_retries` | int | `3` | Retry attempts |
| `retry_delay_seconds` | int | `2` | Delay between retries |

### Provider Defaults

| Provider | Default Base URL | API Key Required |
|----------|-----------------|-----------------|
| `ollama` | `http://localhost:11434` | No |
| `vllm` | Must set explicitly | No |
| `openai` | `https://api.openai.com/v1` | Yes |
| `anthropic` | `https://api.anthropic.com/v1` | Yes |

### Example

```yaml
inference:
  provider: ollama
  model: qwen3-next:latest
  base_url: http://localhost:11434
  temperature: 0.7
  max_tokens: 4096
  top_p: 0.9
  timeout_seconds: 1800
  max_retries: 3
  retry_delay_seconds: 2
```

---

## Tools Config

```yaml
# No tools (explicit)
tools: []

# Named tools
tools:
  - Calculator
  - WebSearch

# Tools with config overrides
tools:
  - name: Calculator
    config:
      precision: 10
```

> **Important:** `tools: []` (empty list) = no tools. `tools: null` or omitting the field = triggers auto-discovery. Always be explicit.

---

## Safety Config

```yaml
safety:
  mode: execute                    # execute | dry_run | require_approval
  require_approval_for_tools: []   # tools needing human OK
  max_tool_calls_per_execution: 20
  max_execution_time_seconds: 300  # 5 min
  max_prompt_length: 32000
  max_tool_result_size: 100000
  risk_level: medium               # low | medium | high
```

---

## Memory Config

```yaml
memory:
  enabled: true
  type: vector          # vector | episodic | procedural | semantic
  scope: session        # session | project | cross_session | permanent
  retrieval_k: 10
  relevance_threshold: 0.7
  embedding_model: "sentence-transformers/all-MiniLM-L6-v2"
  max_episodes: 100
  decay_factor: 0.95
```

> When `enabled: true`, both `type` and `scope` are **required**.

---

## Error Handling Config

```yaml
error_handling:
  retry_strategy: ExponentialBackoff   # ExponentialBackoff | LinearBackoff | FixedDelay
  max_retries: 3
  fallback: GracefulDegradation        # GracefulDegradation | ReturnDefault | RaiseError | LogAndContinue
  escalate_to_human_after: 3
  retry_config:
    initial_delay_seconds: 1
    max_delay_seconds: 30
    exponential_base: 2.0
```

---

## Merit Tracking Config

```yaml
merit_tracking:
  enabled: true
  track_decision_outcomes: true
  domain_expertise:
    - "healthcare"
    - "finance"
  decay_enabled: true
  half_life_days: 90
```

---

## Observability Config

```yaml
observability:
  log_inputs: true
  log_outputs: true
  log_reasoning: true
  log_full_llm_responses: false   # verbose
  track_latency: true
  track_token_usage: true
```

---

## Metadata Config

```yaml
metadata:
  tags:
    - research
    - analysis
  owner: "team-alpha"
  created: "2026-01-15"
  last_modified: "2026-02-10"
  documentation_url: "https://docs.example.com/agents/researcher"
```

---

## Full Examples

### Agent with Tools

```yaml
agent:
  name: calculator_agent
  description: "Agent with Calculator tool"

  prompt:
    inline: |
      Use the Calculator tool for math.
      <tool_call>
      {"name": "Calculator", "parameters": {"expression": "2+2"}}
      </tool_call>
      Query: {{ query }}

  inference:
    provider: ollama
    model: llama3.2:3b
    base_url: http://localhost:11434
    temperature: 0.3
    max_tokens: 4096
    timeout_seconds: 1800

  tools:
    - Calculator

  safety:
    mode: execute
    max_tool_calls_per_execution: 3
    risk_level: low

  error_handling:
    retry_strategy: ExponentialBackoff
    max_retries: 2
    fallback: GracefulDegradation
```

### Dialogue-Aware Agent (Manual Context)

```yaml
agent:
  name: dialogue_proposer
  description: "Proposer in multi-round dialogue"

  prompt:
    inline: |
      You are a PROPOSER.
      {% if dialogue_history %}
      ## Prior Rounds:
      {% for entry in dialogue_history %}
      Round {{ entry.round }} - {{ entry.agent }}:
      {{ entry.output }}
      {% endfor %}
      {% endif %}
      Task: {{ task_description }}

  inference:
    provider: ollama
    model: qwen3-next:latest
    base_url: http://localhost:11434
    temperature: 0.8
    max_tokens: 4096
    timeout_seconds: 1800

  tools: []
  dialogue_aware: false    # handles dialogue context manually in template

  error_handling:
    retry_strategy: ExponentialBackoff
    max_retries: 3
    fallback: GracefulDegradation
```

### Agent with Template Variables

```yaml
agent:
  name: erc721_architect
  description: "ERC721 contract architect"

  prompt:
    inline: |
      Contract name: {{ contract_name | default("SimpleNFT") }}
      Token name: {{ token_name | default("SimpleNFT") }}
      Token symbol: {{ token_symbol | default("SNFT") }}

      Plan the project structure...

  inference:
    provider: ollama
    model: "{{ llm_model | default('llama3:8b') }}"
    base_url: http://localhost:11434
    temperature: 0.3
    max_tokens: 4096
    timeout_seconds: 1800

  tools: []

  error_handling:
    retry_strategy: ExponentialBackoff
    max_retries: 3
    fallback: GracefulDegradation
```

### Agent with OpenAI Provider

```yaml
agent:
  name: gpt4_analyst
  description: "GPT-4 based analyst"

  prompt:
    inline: |
      Analyze the following topic: {{ topic }}

  inference:
    provider: openai
    model: gpt-4
    api_key_ref: "${env:OPENAI_API_KEY}"
    temperature: 0.5
    max_tokens: 4096
    timeout_seconds: 1800

  tools: []

  error_handling:
    retry_strategy: ExponentialBackoff
    max_retries: 3
    fallback: GracefulDegradation
```
