# YAML Configuration Reference

This reference covers the YAML configuration format for Temper AI. For working examples, see the `configs/` directory. For safety system configuration (approval workflows, rollback, circuit breakers), see `docs/security/`.

---

## Overview

Three config types control every workflow:

| Type | Location | Purpose |
|---|---|---|
| Agent | `configs/agents/*.yaml` | Defines a single LLM agent — its prompt, model, tools, and safety settings |
| Stage | `configs/stages/*.yaml` | Groups agents into a named execution unit with a collaboration strategy |
| Workflow | `configs/workflows/*.yaml` | Chains stages together and defines inputs, outputs, and error handling |

The top-level key matches the type: `agent:`, `stage:`, or `workflow:`. All files also accept an optional `schema_version: "1.0"` key for migration support.

---

## Agent Config

### Required Fields

| Field | Type | Description |
|---|---|---|
| `name` | string | Unique agent name |
| `description` | string | What the agent does |
| `prompt` | object | Inline text or file path (see below) |
| `inference` | object | LLM provider settings |
| `error_handling` | object | Retry and fallback behavior |

### Full Reference

```yaml
agent:
  name: researcher              # Required
  description: "..."            # Required
  version: "1.0"
  type: standard                # standard | script | crewai | langgraph | openai_agents | autogen

  prompt:
    inline: |                   # Jinja2 template; use {{ variable }} placeholders
      You are a {{ role }}.
      Task: {{ task }}
    # OR use an external file:
    # template: prompts/researcher.j2
    variables:                  # Default variable values (optional)
      role: researcher

  inference:
    provider: ollama             # Required: ollama | vllm | openai | anthropic | custom
    model: llama3.2:3b           # Required: model name
    base_url: http://localhost:11434   # Required for ollama and vllm
    api_key_ref: ${env:OPENAI_API_KEY} # Secret ref — use ${env:VAR} not inline secrets
    temperature: 0.7             # 0.0–2.0, default 0.7
    max_tokens: 16384            # Default 16384
    top_p: 0.9                   # 0.0–1.0, default 0.9
    timeout_seconds: 1800        # Default 1800 (30 min)
    max_retries: 3               # Default 3
    retry_delay_seconds: 2       # Default 2

  tools:                         # null = auto-discover, [] = none, list = exact set
    - Bash
    - HTTP
    - JSON
    - FileWriter
    - CodeExecutor
    - Git
    - WebScraper
    - Calculator

  safety:
    mode: execute                # execute | dry_run | require_approval (default: execute)
    require_approval_for_tools: []   # Tool names that require human approval
    max_tool_calls_per_execution: 50
    max_execution_time_seconds: 3600
    risk_level: medium           # low | medium | high (default: medium)

  memory:
    enabled: false
    type: vector                 # vector | episodic | procedural | semantic | cross_session
    scope: session               # session | project | cross_session | permanent
    provider: in_memory          # in_memory | mem0
    retrieval_k: 5
    relevance_threshold: 0.8

  error_handling:                # Required
    retry_strategy: ExponentialBackoff   # ExponentialBackoff | LinearBackoff | FixedDelay
    max_retries: 3
    fallback: GracefulDegradation        # GracefulDegradation | ReturnDefault | RaiseError | LogAndContinue
    escalate_to_human_after: 3

  reasoning:
    enabled: false
    inject_as: context_section   # system_prefix | context_section
    max_planning_tokens: 1024

  context_management:
    enabled: false
    strategy: truncate           # truncate | summarize | sliding_window
    reserved_output_tokens: 2048

  merit_tracking:
    enabled: true
    domain_expertise: []         # Domain tags for weighted conflict resolution
    decay_enabled: true
    half_life_days: 90

  observability:
    log_inputs: true
    log_outputs: true
    log_full_llm_responses: false
    track_latency: true
    track_token_usage: true

  # M9: persistent agent identity across workflow runs
  persistent: false
  agent_id: null                 # Auto-assigned on registration

  metadata:
    tags: []
    owner: null
```

### Notes

- `prompt.inline` and `prompt.template` are mutually exclusive. Exactly one must be set.
- `tools: null` triggers auto-discovery. `tools: []` disables all tools. Provide a list to pin specific tools.
- `api_key` (bare string) is deprecated. Use `api_key_ref: ${env:VAR_NAME}` instead.
- `type: script` agents require a `script:` field (Jinja2 bash template) and no `prompt` or `inference`.

---

## Stage Config

### Required Fields

| Field | Type | Description |
|---|---|---|
| `name` | string | Unique stage name |
| `description` | string | What the stage does |
| `agents` | list | At least one agent name (resolved from `configs/agents/`) |

### Full Reference

```yaml
stage:
  name: analysis                # Required
  description: "..."            # Required
  version: "1.0"

  agents:                       # Required: one or more agent names
    - researcher
    - analyst

  execution:
    agent_mode: parallel        # parallel | sequential | adaptive (default: parallel)
    timeout_seconds: 1800       # Default 1800 (30 min)

  inputs:
    required:
      - topic
    optional:
      - context

  outputs:
    summary: "Final summary output"
    confidence: "Confidence score"

  collaboration:                # Optional: enables multi-round agent interaction
    strategy: multi_round       # Strategy name (e.g., multi_round, debate)
    max_rounds: 3
    convergence_threshold: 0.8  # 0.0–1.0
    dialogue_mode: false        # Enable multi-turn dialogue
    roles:                      # Optional agent role assignments
      researcher: proposer
      analyst: critic
    context_window_rounds: 3

  conflict_resolution:          # Optional: how to resolve agent disagreements
    strategy: HighestConfidenceResolver   # HighestConfidenceResolver | MajorityVote | merit_weighted
    metrics:
      - confidence
    metric_weights:             # Custom weights (normalized at runtime)
      confidence: 1.0
    auto_resolve_threshold: 0.8  # 0.0–1.0; auto-resolve if winning option exceeds this
    escalation_threshold: 0.5   # 0.0–1.0; escalate if no option meets this

  safety:
    mode: execute               # execute | dry_run | require_approval
    dry_run_first: false
    require_approval: false

  error_handling:
    on_agent_failure: continue_with_remaining  # halt_stage | retry_agent | skip_agent | continue_with_remaining
    min_successful_agents: 1
    retry_failed_agents: true
    max_agent_retries: 2

  quality_gates:                # Optional output quality enforcement
    enabled: false
    min_confidence: 0.8
    require_citations: true
    on_failure: retry_stage     # retry_stage | escalate | proceed_with_warning
    max_retries: 2

  convergence:                  # Optional: re-run until outputs stabilize
    enabled: false
    max_iterations: 5
    similarity_threshold: 0.95
    method: exact_hash          # exact_hash | semantic

  metadata:
    tags: []
    owner: null
```

### `on_agent_failure` Values

| Value | Behavior |
|---|---|
| `halt_stage` | Fail the stage immediately |
| `retry_agent` | Retry the failed agent |
| `skip_agent` | Skip the failed agent, continue with others |
| `continue_with_remaining` | Default — skip failed agents silently |

---

## Workflow Config

### Required Fields

| Field | Type | Description |
|---|---|---|
| `name` | string | Unique workflow name |
| `description` | string | What the workflow does |
| `stages` | list | At least one stage reference |
| `error_handling` | object | Stage failure policy |

### Full Reference

```yaml
workflow:
  name: my_workflow             # Required
  description: "..."            # Required
  version: "1.0"

  stages:                       # Required: at least one
    - name: research            # Instance name (used in depends_on, outputs.source)
      stage_ref: configs/stages/research.yaml   # Required

    - name: writing
      stage_ref: configs/stages/writing.yaml
      depends_on:
        - research              # DAG dependency — waits for research to complete
      optional: false           # If true, stage failure does not fail workflow
      conditional: false
      condition: null           # Jinja2 expression evaluated at runtime
      skip_if: null             # Mutually exclusive with condition
      loops_back_to: null       # Stage name to loop back to
      loop_condition: null      # Jinja2 expression: loop continues while true
      max_loops: 3              # Default 3

  inputs:
    required:
      - question
      - options
    optional:
      - context

  outputs:
    - name: decision
      description: "The recommended choice"
      source: decision.final_decision  # Format: <stage_name>.<output_field>

    - name: confidence
      description: "Confidence score"
      source: decision.confidence

  config:
    timeout_seconds: 3600       # Default 3600 (1 hour)
    max_iterations: 10
    convergence_detection: false
    tool_cache_enabled: false   # Cache read-only tool results
    budget:
      max_cost_usd: null
      max_tokens: null
      action_on_exceed: halt    # halt | continue | notify
    rate_limit:
      enabled: false
      max_rpm: 60
      block_on_limit: true
      max_wait_seconds: 60.0

  error_handling:               # Required
    on_stage_failure: halt      # halt | skip | retry
    max_stage_retries: 2
    escalation_policy: GracefulDegradation   # GracefulDegradation | FailFast
    enable_rollback: true
    rollback_on: []             # List of stage names that trigger rollback on failure

  safety:
    global_mode: execute        # execute | dry_run | require_approval
    composition_strategy: MostRestrictive
    approval_required_stages: []
    dry_run_stages: []

  observability:
    console_mode: standard      # minimal | standard | verbose
    trace_everything: true
    export_format:
      - json
    generate_dag_visualization: true
    waterfall_in_console: true
    alert_on: []

  predecessor_injection: false  # When true, stages receive only DAG predecessor outputs, not full state

  metadata:
    tags: []
    owner: null
```

### Stage Dependencies and Loops

By default, stages run sequentially in declaration order. Use `depends_on` to model a DAG. Event-triggered stages (using `trigger:`) cannot have `depends_on`.

Loop stages require both `loops_back_to` (the target stage name) and `loop_condition` (a Jinja2 boolean expression). `max_loops` caps iterations to prevent infinite loops.

---

## Environment Variables

| Variable | Description | Default |
|---|---|---|
| `TEMPER_LLM_PROVIDER` | Default LLM provider for agents that do not specify one | `ollama` |
| `TEMPER_LLM_MODEL` | Default model name | `llama3.2` |
| `TEMPER_LLM_BASE_URL` | Provider API endpoint | `http://localhost:11434` |
| `TEMPER_DATABASE_URL` | PostgreSQL connection string | SQLite fallback |
| `TEMPER_LOG_LEVEL` | Log verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR` | `INFO` |
| `TEMPER_CONFIG_ROOT` | Root directory for config file resolution | `./configs` |
| `OPENAI_API_KEY` | Referenced via `api_key_ref: ${env:OPENAI_API_KEY}` | — |
| `ANTHROPIC_API_KEY` | Referenced via `api_key_ref: ${env:ANTHROPIC_API_KEY}` | — |

---

## Examples

The `configs/` directory contains ready-to-run examples:

| Path | What it shows |
|---|---|
| `configs/agents/researcher.yaml` | Minimal agent with vLLM and no tools |
| `configs/agents/calculator_agent.yaml` | Agent with Calculator tool enabled |
| `configs/stages/quick_debate.yaml` | Three-agent sequential debate with convergence |
| `configs/stages/problem_analysis_parallel.yaml` | Parallel multi-agent analysis |
| `configs/workflows/quick_decision_demo.yaml` | Single-stage decision workflow |
| `configs/workflows/technical_problem_solving_parallel.yaml` | Four-stage parallel workflow with DAG deps |
| `configs/workflows/multi_agent_research.yaml` | End-to-end research pipeline |

Run any workflow via the HTTP API (after starting the server with `temper-ai serve`):

```bash
curl -X POST http://localhost:8000/api/runs \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "workflow_name": "quick_decision_demo",
    "input_file": "examples/vcs_suggestion_input.yaml"
  }'
```

Validate a config by importing it (the server validates on import):

```bash
curl -X POST http://localhost:8000/api/configs/import \
  -H "Authorization: Bearer $API_KEY" \
  -F "file=@configs/workflows/quick_decision_demo.yaml"
```
