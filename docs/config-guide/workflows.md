# Workflow Configuration

A workflow is a pipeline of stages with dependencies, inputs, outputs, and global settings.

**Location:** `configs/workflows/*.yaml`
**Schema:** `temper_ai/compiler/schemas.py` (WorkflowConfig)

## Minimal Workflow

```yaml
workflow:
  name: simple_research
  description: "Single-stage research workflow"

  stages:
    - name: research
      stage_ref: configs/stages/research_stage.yaml

  error_handling:
    on_stage_failure: retry
    max_stage_retries: 2
    escalation_policy: "default"
    enable_rollback: false

  inputs:
    required:
      - topic
```

## Top-Level Structure

```yaml
workflow:          # Required: all workflow fields nested here
  # ... fields below
schema_version:    # Optional, default "1.0"
```

## Complete Field Reference

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `name` | string | Yes | — | Workflow identifier |
| `description` | string | Yes | — | Purpose |
| `version` | string | No | `"1.0"` | Version |
| `product_type` | enum | No | null | `web_app`, `mobile_app`, `api`, `data_product` |
| `stages` | list | Yes (min 1) | — | Stage references |
| `inputs` | dict | No | `{}` | Required/optional inputs |
| `outputs` | list | No | `[]` | Output mappings |
| `config` | WorkflowConfigOptions | No | defaults | Timeout, budget, convergence |
| `error_handling` | WorkflowErrorHandlingConfig | Yes | — | Error policy |
| `safety` | WorkflowSafetyConfig | No | defaults | Safety controls |
| `observability` | WorkflowObservabilityConfig | No | defaults | Logging/tracing |
| `optimization` | OptimizationConfig | No | null | Optimization goals |
| `metadata` | MetadataConfig | No | — | Tags, owner |

---

## Stage References

Each entry in `stages` is a `WorkflowStageReference`:

```yaml
stages:
  - name: research              # name within this workflow (required)
    stage_ref: configs/stages/research_stage.yaml   # path to stage YAML (required)
    depends_on: []              # stages that must complete first
    optional: false             # if true, failure won't halt workflow
    conditional: false          # only runs when condition met
    condition: null             # condition expression
    skip_if: null               # expression to skip stage
    loops_back_to: null         # stage name to loop back to
    max_loops: 2                # max loop iterations
```

### Stage Input Templating

Pass workflow inputs to stages using Jinja2:

```yaml
stages:
  - name: parallel_research
    stage_ref: configs/stages/parallel_research_stage.yaml
    inputs:
      topic: "{{ workflow.inputs.topic }}"
      focus_areas: "{{ workflow.inputs.focus_areas }}"
      depth: "{{ workflow.inputs.depth | default('comprehensive') }}"
```

### Stage Dependencies

Stages run in order by default. Use `depends_on` to create DAG execution:

```yaml
stages:
  - name: research
    stage_ref: configs/stages/research.yaml

  - name: analysis
    stage_ref: configs/stages/analysis.yaml
    depends_on: [research]       # waits for research to complete

  - name: design
    stage_ref: configs/stages/design.yaml
    depends_on: [research]       # also waits for research (parallel with analysis)

  - name: synthesis
    stage_ref: configs/stages/synthesis.yaml
    depends_on: [analysis, design]   # waits for both
```

### Conditional Stages and Loops

Stages can be conditionally executed or looped using `condition`, `skip_if`, `conditional`, and `loops_back_to` fields on `WorkflowStageReference`. Conditions are Jinja2 expressions evaluated against the current workflow state.

#### Condition Fields

| Field | Type | Description |
|-------|------|-------------|
| `conditional` | bool | Marks the stage as conditional. When `true` without an explicit `condition`, defaults to checking if the previous stage failed/degraded |
| `condition` | string | Jinja2 expression. If it evaluates to truthy, the stage **executes**. Mutually exclusive with `skip_if` |
| `skip_if` | string | Jinja2 expression. If it evaluates to truthy, the stage is **skipped**. Mutually exclusive with `condition` |
| `loops_back_to` | string | Name of a prior stage to loop back to after this stage completes |
| `max_loops` | int | Maximum loop iterations (default: 2). Prevents infinite loops |

#### How Conditions Work

Conditions are Jinja2 templates rendered against the workflow state. The result is coerced to boolean (`"true"`, `"1"`, `"yes"` are truthy). The state context includes all `stage_outputs`, `workflow_inputs`, and other non-infrastructure state fields.

Available in condition expressions:
- `stage_outputs.<stage_name>.<field>` — outputs from completed stages
- `stage_outputs.<stage_name>.stage_status` — `"success"`, `"failed"`, or `"degraded"`
- Any workflow input variables

#### Default Conditions

When `conditional: true` is set without an explicit `condition`, the framework generates a default:
- **For conditional stages:** checks if the previous stage's status is `"failed"` or `"degraded"`
- **For loop-back stages:** checks if the current stage's status is `"failed"` or `"degraded"`

This covers the common test-then-fix pattern without needing explicit condition strings.

#### Loop Mechanics

When a stage has `loops_back_to`, the execution graph includes a loop gate node that tracks iteration count in `stage_loop_counts`. The loop continues while:
1. The loop count has not exceeded `max_loops`
2. The loop condition evaluates to truthy (default: current stage failed/degraded)

If either condition is not met, execution proceeds to the next stage or ends.

#### Examples

**Conditional execution (skip_if):**
```yaml
stages:
  - name: research
    stage_ref: configs/stages/research.yaml

  - name: deep_analysis
    stage_ref: configs/stages/deep_analysis.yaml
    skip_if: "{{ stage_outputs.research.stage_status == 'success' }}"
```

**Conditional execution (condition):**
```yaml
stages:
  - name: test
    stage_ref: configs/stages/test.yaml

  - name: fix
    stage_ref: configs/stages/fix.yaml
    condition: "{{ stage_outputs.test.stage_status in ['failed', 'degraded'] }}"
```

**Default condition (previous stage failed):**
```yaml
stages:
  - name: test
    stage_ref: configs/stages/test.yaml

  - name: fix
    stage_ref: configs/stages/fix.yaml
    conditional: true            # runs only if 'test' failed/degraded
```

**Test-fix loop:**
```yaml
stages:
  - name: test
    stage_ref: configs/stages/test.yaml

  - name: fix
    stage_ref: configs/stages/fix.yaml
    conditional: true            # only runs if tests failed
    loops_back_to: test          # re-run tests after fix
    max_loops: 3                 # max fix-test cycles
```

**Custom loop condition:**
```yaml
stages:
  - name: validate
    stage_ref: configs/stages/validate.yaml

  - name: refine
    stage_ref: configs/stages/refine.yaml
    condition: "{{ stage_outputs.validate.errors|length > 0 }}"
    loops_back_to: validate
    max_loops: 5
```

---

## Inputs

Define required and optional workflow inputs:

```yaml
inputs:
  required:
    - topic
    - options
  optional:
    - context
    - constraints
```

---

## Outputs

Map stage results to workflow outputs:

```yaml
outputs:
  - name: final_decision
    description: "The recommended choice"
    source: decision.final_decision    # stage_name.field_name

  - name: metadata
    description: "Workflow execution metadata"
    fields:
      - execution_time
      - confidence_score
      - stages_completed

# Grouping
outputs:
  primary:
    - solution_design
    - implementation_plan
  secondary:
    - problem_analysis
    - technical_documentation
```

---

## Workflow Config Options

```yaml
config:
  max_iterations: 5              # max workflow iterations (default: 5)
  convergence_detection: false   # enable convergence detection
  timeout_seconds: 3600          # total workflow timeout (default: 1 hour)
  budget:
    max_cost_usd: 10.0           # cost cap in USD
    max_tokens: 100000           # token cap
    action_on_exceed: halt       # halt | continue | notify
```

---

## Error Handling Config

```yaml
error_handling:
  on_stage_failure: halt         # halt | skip | retry
  max_stage_retries: 3
  escalation_policy: "GracefulDegradation"   # required
  enable_rollback: true
  rollback_on: []                # error types triggering rollback
```

---

## Safety Config

```yaml
safety:
  composition_strategy: MostRestrictive    # how to merge stage safety configs
  global_mode: execute           # execute | dry_run | require_approval
  approval_required_stages:
    - production_deployment
  dry_run_stages:
    - code_generation
  custom_rules:
    - type: cost_limit
      threshold: 10.0
      action: halt
```

---

## Observability Config

```yaml
observability:
  console_mode: standard         # minimal | standard | verbose
  trace_everything: true
  export_format: ["json", "sqlite"]
  generate_dag_visualization: true
  waterfall_in_console: true
  alert_on:
    - stage_failure
    - budget_exceeded
    - high_latency
```

---

## Optimization Config

```yaml
optimization:
  current_phase: growth          # growth | retention | efficiency | quality
  primary_metric: "user_satisfaction"
  secondary_metrics:
    - "response_time"
    - "accuracy"
  thresholds:
    user_satisfaction:
      min: 0.8
      target: 0.95
```

---

## Metadata Config

```yaml
metadata:
  tags:
    - research
    - multi-agent
    - parallel
  owner: "team-alpha"
  created: "2026-01-15"
  last_modified: "2026-02-10"
  documentation_url: "https://docs.example.com/workflows/research"
```

---

## Full Examples

### Simple Single-Stage Workflow

```yaml
workflow:
  name: simple_research
  description: "Single-stage research workflow"

  stages:
    - name: research
      stage_ref: configs/stages/research_stage.yaml

  inputs:
    required:
      - topic

  outputs:
    - name: research_results
      source: research.insights

  error_handling:
    on_stage_failure: retry
    max_stage_retries: 2
    escalation_policy: "default"
    enable_rollback: false
```

### Multi-Stage Pipeline with Dependencies

```yaml
workflow:
  name: technical_problem_solving
  description: "4-phase systematic problem solving"

  stages:
    - name: problem_analysis
      stage_ref: configs/stages/problem_analysis_parallel.yaml

    - name: solution_design
      stage_ref: configs/stages/solution_design_parallel.yaml
      depends_on: [problem_analysis]

    - name: implementation_strategy
      stage_ref: configs/stages/implementation_strategy_parallel.yaml
      depends_on: [solution_design]

    - name: validation_documentation
      stage_ref: configs/stages/validation_documentation_parallel.yaml
      depends_on: [implementation_strategy]

  inputs:
    required:
      - problem_description
      - technical_context
      - success_criteria

  config:
    timeout_seconds: 12000

  error_handling:
    on_stage_failure: halt
    max_stage_retries: 2
    escalation_policy: GracefulDegradation
    enable_rollback: true

  observability:
    console_mode: standard
    trace_everything: true
    waterfall_in_console: true
```

### Debate Workflow

```yaml
workflow:
  name: llm_debate_demo
  description: "Multi-round debate with convergence"

  stages:
    - name: llm_debate
      stage_ref: configs/stages/quick_debate.yaml

  inputs:
    required:
      - question
      - options
    optional:
      - context

  error_handling:
    on_stage_failure: retry
    max_stage_retries: 2
    escalation_policy: GracefulDegradation
    enable_rollback: false
```

### Code Generation with Test-Fix Loop

```yaml
workflow:
  name: erc721_generator
  description: "Generate, test, fix Solidity contracts"

  stages:
    - name: scaffold
      stage_ref: configs/stages/erc721_scaffold.yaml

    - name: code
      stage_ref: configs/stages/erc721_code.yaml

    - name: test
      stage_ref: configs/stages/erc721_test.yaml

    - name: fix
      stage_ref: configs/stages/erc721_fix.yaml
      conditional: true
      loops_back_to: test
      max_loops: 3

  inputs:
    required:
      - contract_name
      - token_name
      - token_symbol

  error_handling:
    on_stage_failure: retry
    max_stage_retries: 2
    escalation_policy: GracefulDegradation
    enable_rollback: true
```

### Parallel Multi-Agent Research

```yaml
workflow:
  name: multi_agent_research
  description: "Parallel research with consensus"

  stages:
    - name: parallel_research
      stage_ref: configs/stages/parallel_research_stage.yaml
      inputs:
        topic: "{{ workflow.inputs.topic }}"
        focus_areas: "{{ workflow.inputs.focus_areas }}"

  inputs:
    required:
      - topic
      - focus_areas

  config:
    timeout_seconds: 3600

  error_handling:
    on_stage_failure: retry
    max_stage_retries: 2
    escalation_policy: GracefulDegradation
    enable_rollback: false

  observability:
    console_mode: standard
    trace_everything: true
    export_format: ["json"]
    waterfall_in_console: true
```
