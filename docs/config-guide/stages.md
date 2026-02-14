# Stage Configuration

A stage groups one or more agents and defines **how** they execute and collaborate.

**Location:** `configs/stages/*.yaml`
**Schema:** `src/compiler/schemas.py` (StageConfigInner)

## Minimal Stage

```yaml
stage:
  name: research_stage
  description: "Research and analysis"
  agents:
    - simple_researcher

  execution:
    timeout_seconds: 600

  collaboration:
    strategy: "sequential"
    max_rounds: 1
```

## Top-Level Structure

```yaml
stage:            # Required: all stage fields nested here
  # ... fields below
schema_version:   # Optional, default "1.0"
```

## Complete Field Reference

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `name` | string | Yes | — | Stage identifier |
| `description` | string | Yes | — | Purpose |
| `version` | string | No | `"1.0"` | Version |
| `agents` | list | Yes (min 1) | — | Agent names or extended objects |
| `inputs` | dict | No | `{}` | Input schema |
| `outputs` | dict | No | `{}` | Output schema |
| `execution` | StageExecutionConfig | No | defaults | Execution mode/timeout |
| `collaboration` | CollaborationConfig | No | null | Multi-agent strategy |
| `conflict_resolution` | ConflictResolutionConfig | No | null | Conflict handling |
| `error_handling` | StageErrorHandlingConfig | No | defaults | Error policy |
| `safety` | StageSafetyConfig | No | defaults | Safety mode |
| `quality_gates` | QualityGatesConfig | No | disabled | Quality validation |
| `metadata` | MetadataConfig | No | defaults | Tags, owner |

---

## Agent Assignment

### Simple Names (loads from `configs/agents/{name}.yaml`)

```yaml
agents:
  - optimist
  - skeptic
  - pragmatist
```

### Extended Objects (with role assignment)

```yaml
agents:
  - name: market_researcher
    config_path: configs/agents/simple_researcher.yaml
    role: market_analysis
    description: "Analyzes market trends"
```

---

## Execution Config

Controls how agents within a stage are run.

```yaml
execution:
  agent_mode: parallel       # parallel | sequential | adaptive
  timeout_seconds: 1800      # 30 minutes default
  adaptive_config: {}        # config for adaptive mode
```

### Execution Modes

| Mode | Behavior |
|------|----------|
| **parallel** | All agents run concurrently (via LangGraph). **Default.** |
| **sequential** | Agents run in list order; each sees prior agent outputs. |
| **adaptive** | Starts parallel, switches to sequential if needed. |

### Sequential Execution Flow

1. Agents run one-by-one in list order
2. Each agent receives full workflow state + prior agent outputs
3. Final output from last agent (or synthesis if `collaboration` is configured)
4. Agent cache prevents re-instantiation across stages

### Parallel Execution Flow

1. All agents run concurrently via LangGraph
2. Uses `ParallelRunner` abstraction (default: LangGraphParallelRunner)
3. Init node -> Parallel agent nodes -> Collect node
4. Synthesis coordinator combines outputs
5. Quality gate validation with retry support

---

## Collaboration Config

This is where multi-agent strategy is configured.

```yaml
collaboration:
  strategy: multi_round        # strategy name (required)
  max_rounds: 3                # max collaboration rounds
  convergence_threshold: 0.85  # agreement threshold (0.0-1.0)
  config:                      # strategy-specific options
    mode: debate
    max_rounds: 3
    convergence_threshold: 0.80
    context_strategy: full
```

### Available Strategies

| Strategy | Rounds | Description |
|----------|--------|-------------|
| `multi_round` | 1-N | **Recommended.** Unified strategy with 3 modes. |
| `consensus` | 1 | Simple majority voting, no re-invocation. |
| `debate` | 3 | Legacy wrapper — use `multi_round` with `mode: debate`. |
| `dialogue` | 3 | Legacy wrapper — use `multi_round` with `mode: dialogue`. |
| `sequential` | 1 | Agents run in sequence. |

### `multi_round` Strategy Config

The unified strategy supporting three modes:

```yaml
collaboration:
  strategy: multi_round
  config:
    mode: debate               # debate | dialogue | consensus
    max_rounds: 3
    min_rounds: 1
    convergence_threshold: 0.85
    use_semantic_convergence: true
    context_strategy: full     # full | recent | relevant
    context_window_size: 2     # for "recent" strategy
    cost_budget_usd: 5.0       # optional cost cap
    use_merit_weighting: false
    merit_domain: null
    require_unanimous: false
```

### Mode Comparison

| Property | dialogue | debate | consensus |
|----------|----------|--------|-----------|
| Default convergence | 0.85 | 0.80 | 1.0 (no detection) |
| Max rounds | 3 | 3 | 1 |
| Agent interaction | Collaborative | Adversarial | Vote-only |
| Context injection | "Build on insights" | "Challenge positions" | None |
| Stance extraction | No | Yes (AGREE/DISAGREE/PARTIAL) | No |

### Dialogue-Specific Fields

```yaml
collaboration:
  strategy: multi_round
  config:
    mode: dialogue

  # Additional dialogue fields
  dialogue_mode: true
  max_dialogue_rounds: 3
  round_budget_usd: 2.0
  context_window_rounds: 3
  roles:
    optimist: "proposer"
    skeptic: "critic"
    pragmatist: "synthesizer"
```

### Multi-Round Execution Flow

1. **Round 0:** Initial agent invocations
2. **Convergence check:** After `min_rounds`, compare outputs (semantic or exact)
3. **Re-invocation:** Agents receive `dialogue_history`, `round_number`, `max_rounds`, `agent_role`, and mode-specific context
4. **Stance extraction** (debate mode): AGREE/DISAGREE/PARTIAL via regex or LLM
5. **Budget check:** Stop if `cost_budget_usd` exceeded
6. **Early termination:** Stop if converged or max rounds reached
7. **Final synthesis:** Synthesize final-round outputs

---

## Conflict Resolution Config

Resolves disagreements between agents.

```yaml
conflict_resolution:
  strategy: highest_confidence
  metrics: ["confidence"]
  metric_weights: {}
  auto_resolve_threshold: 0.9
  escalation_threshold: 0.5      # must be <= auto_resolve_threshold
  config: {}
```

### Available Resolvers

| Resolver | Deterministic | Description |
|----------|--------------|-------------|
| `highest_confidence` | Yes | Pick agent with highest confidence |
| `merit_weighted` | Yes | Weight votes by historical merit |
| `random_tiebreaker` | No | Random selection |
| `human_escalation` | — | Escalate to human |

---

## Error Handling Config

```yaml
error_handling:
  on_agent_failure: continue_with_remaining   # halt_stage | retry_agent | skip_agent | continue_with_remaining
  min_successful_agents: 2                    # minimum agents needed for stage success
  fallback_strategy: null                     # fallback strategy name
  retry_failed_agents: true
  max_agent_retries: 2
```

### Error Handling Flow

1. Agent fails -> check `on_agent_failure`
2. If `continue_with_remaining` -> continue with successful agents
3. Check `min_successful_agents` -> fail stage if below threshold
4. If `retry_failed_agents: true` -> retry up to `max_agent_retries`
5. If stage fails -> check workflow-level `error_handling.on_stage_failure`

---

## Safety Config

```yaml
safety:
  mode: execute              # execute | dry_run | require_approval
  dry_run_first: false
  require_approval: false
  approval_required_when:
    - condition: "risk_score > 0.8"
      action: require_approval
```

---

## Quality Gates Config

```yaml
quality_gates:
  enabled: true
  min_confidence: 0.8         # minimum confidence threshold (0.0-1.0)
  min_findings: 5             # minimum findings required
  require_citations: true
  on_failure: retry_stage     # retry_stage | escalate | proceed_with_warning
  max_retries: 2
```

### Quality Gate Flow

1. Synthesis completes -> validate via quality gate validator
2. Check `min_confidence`, `min_findings`, `require_citations`
3. If failed:
   - `retry_stage` -> retry entire stage
   - `escalate` -> escalate to human
   - `proceed_with_warning` -> continue with warning
4. Max retries tracked in `state['stage_retry_counts']`

---

## Input/Output Schemas

### Input Schema

```yaml
# Detailed format
inputs:
  topic:
    type: string
    required: true
  focus_areas:
    type: array
    required: false
  depth:
    type: string
    required: false
    default: medium

# Simple format
inputs:
  required: [topic]
  optional: [context, constraints]
```

### Output Schema

```yaml
# Descriptive format
outputs:
  insights:
    type: string
    description: "Research findings"
  recommendations:
    type: string
    description: "Action recommendations"
  confidence_score:
    type: number
    description: "Confidence in the analysis"

# Simple list format
outputs:
  - decision
  - debate_history
  - convergence_info
```

---

## Full Examples

### Single-Agent Stage

```yaml
stage:
  name: research_stage
  description: "Research using a single agent"
  agents:
    - simple_researcher

  execution:
    timeout_seconds: 600

  collaboration:
    strategy: "sequential"
    max_rounds: 1

  inputs:
    required: [topic]
    optional: [context]

  outputs:
    insights:
      type: string
      description: "Research findings"
```

### Parallel Consensus Stage

```yaml
stage:
  name: problem_analysis_parallel
  description: "Parallel analysis with consensus"
  agents:
    - problem_analyzer
    - systems_thinker
    - requirements_engineer

  execution:
    agent_mode: parallel
    timeout_seconds: 1800

  collaboration:
    strategy: consensus
    config:
      threshold: 0.5
      require_unanimous: false
      conflict_threshold: 0.3

  error_handling:
    on_agent_failure: continue_with_remaining
    min_successful_agents: 2
```

### Multi-Round Debate Stage

```yaml
stage:
  name: quick_debate
  description: "3-agent debate with convergence"
  agents:
    - optimist
    - skeptic
    - pragmatist

  execution:
    agent_mode: sequential
    timeout_seconds: 1800

  collaboration:
    strategy: multi_round
    config:
      mode: debate
      max_rounds: 3
      convergence_threshold: 0.80
      context_strategy: full

  error_handling:
    on_agent_failure: continue_with_remaining
    min_successful_agents: 2
```

### Collaborative Dialogue Stage

```yaml
stage:
  name: collaborative_dialogue
  description: "Multi-round collaborative dialogue"
  agents:
    - dialogue_proposer
    - dialogue_critic
    - dialogue_synthesizer

  execution:
    agent_mode: sequential
    timeout_seconds: 1800

  collaboration:
    strategy: multi_round
    dialogue_mode: true
    max_dialogue_rounds: 3
    context_window_rounds: 3
    config:
      mode: dialogue
      max_rounds: 3
      convergence_threshold: 0.85
      context_strategy: full
    roles:
      dialogue_proposer: "proposer"
      dialogue_critic: "critic"
      dialogue_synthesizer: "synthesizer"

  error_handling:
    on_agent_failure: continue_with_remaining
    min_successful_agents: 2
```
