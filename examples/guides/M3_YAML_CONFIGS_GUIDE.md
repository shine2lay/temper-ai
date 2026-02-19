# M3 YAML Configuration Guide

**Date**: 2026-01-27
**Purpose**: Complete guide to YAML configs for M3 multi-agent workflows

---

## Overview

M3 (Multi-Agent Collaboration) workflows can be configured via YAML files. This guide shows:

1. **Existing M3 configs** in the repository
2. **LLM-powered debate config** (for the demo)
3. **Configuration structure** and options
4. **How to create your own** M3 workflows

---

## Table of Contents

- [Workflow Configs](#workflow-configs)
  - [debate_decision.yaml](#1-debate_decisionyaml)
  - [multi_agent_research.yaml](#2-multi_agent_researchyaml)
  - [llm_debate_demo.yaml](#3-llm_debate_demoyaml-new)
- [Stage Configs](#stage-configs)
  - [debate_stage.yaml](#1-debate_stageyaml)
  - [parallel_research_stage.yaml](#2-parallel_research_stageyaml)
  - [llm_debate_stage.yaml](#3-llm_debate_stageyaml-new)
- [Key Concepts](#key-concepts)
- [Creating Your Own](#creating-your-own-m3-workflow)

---

## Workflow Configs

Workflow configs define the high-level flow and orchestration.

**Location**: `configs/workflows/`

---

### 1. debate_decision.yaml

**Purpose**: Multi-round debate for high-quality decision making

**File**: `configs/workflows/debate_decision.yaml`

```yaml
workflow:
  name: debate_decision
  description: "Multi-round debate for high-quality decision making"
  version: "1.0"

  # Workflow metadata
  lifecycle_type: decision_making
  product_type: reasoned_decision

  # Single stage: debate and decide
  stages:
    - name: debate_and_decide
      config_path: configs/stages/debate_stage.yaml
      inputs:
        decision_prompt: "{{ workflow.inputs.decision_prompt }}"
        context: "{{ workflow.inputs.context }}"
        options: "{{ workflow.inputs.options }}"

      on_success:
        action: continue

      on_failure:
        action: escalate  # Escalate if no convergence

  # Workflow inputs
  inputs:
    required:
      - decision_prompt  # What needs to be decided
      - options  # Available choices
    optional:
      - context  # Additional context
      - max_rounds  # Max debate rounds (default: 3)

  # Workflow outputs
  outputs:
    - name: final_decision
      description: "Consensus decision after debate"
      source: debate_and_decide.decision

    - name: debate_transcript
      description: "Complete debate history"
      source: debate_and_decide.debate_history

    - name: convergence_info
      description: "Convergence metrics"
      fields:
        - converged
        - rounds_to_convergence
        - final_confidence
        - remaining_conflicts

  # Execution settings
  execution:
    timeout_seconds: 1800  # 30 minutes
    parallel_execution: false  # Debate is sequential
    allow_early_termination: true  # Stop if converged

  # Observability (M3)
  observability:
    trace_all_decisions: true
    track_collaboration_events: true
    track_convergence: true  # M3 feature
    log_level: DEBUG

  # Use cases
  use_cases:
    - "Architecture decisions (microservices vs monolith)"
    - "Technology selection (React vs Vue vs Angular)"
    - "Strategic planning (build vs buy)"
```

**Key M3 Features**:
- ✅ Multi-round debate
- ✅ Convergence detection
- ✅ Collaboration events tracking
- ✅ Early termination on consensus

**Usage**:
```bash
python3 examples/run_workflow.py \
  --config configs/workflows/debate_decision.yaml \
  --input decision_prompt="Should we launch now or wait?" \
  --input options="Launch Now,Wait 1 Month,Launch Beta"
```

---

### 2. multi_agent_research.yaml

**Purpose**: Parallel multi-agent research with consensus synthesis

**File**: `configs/workflows/multi_agent_research.yaml`

```yaml
workflow:
  name: multi_agent_research
  description: "Parallel multi-agent research with consensus synthesis"
  version: "1.0"

  # Workflow metadata
  lifecycle_type: research
  product_type: comprehensive_analysis

  # Single stage: parallel research
  stages:
    - name: parallel_research
      config_path: configs/stages/parallel_research_stage.yaml
      inputs:
        topic: "{{ workflow.inputs.topic }}"
        focus_areas: "{{ workflow.inputs.focus_areas }}"
        depth: "{{ workflow.inputs.depth | default('comprehensive') }}"

      on_success:
        action: continue

      on_failure:
        action: halt  # Strict: require all insights

  # Workflow inputs
  inputs:
    required:
      - topic  # Research topic
    optional:
      - focus_areas  # Specific areas
      - depth  # Analysis depth

  # Workflow outputs
  outputs:
    - name: synthesized_insights
      description: "Consensus insights from all agents"
      source: parallel_research.synthesized_decision

    - name: agent_perspectives
      description: "Individual agent outputs"
      source: parallel_research.agent_outputs

    - name: consensus_metadata
      description: "Synthesis details"
      source: parallel_research.synthesis_metadata

  # Multi-agent execution (M3)
  execution:
    timeout_seconds: 1200  # 20 minutes
    parallel_execution: true  # M3 feature
    max_concurrent_agents: 3

  # Observability (M3)
  observability:
    trace_all_decisions: true
    track_collaboration_events: true  # M3
    log_level: DEBUG
    metrics_enabled: true

  # Use cases
  use_cases:
    - "Market + Competitor + User research in parallel"
    - "Multi-perspective analysis"
    - "Comprehensive insights from diverse agents"
```

**Key M3 Features**:
- ✅ Parallel agent execution
- ✅ Consensus synthesis
- ✅ Conflict detection
- ✅ Performance metrics (speedup tracking)

**Usage**:
```bash
python3 examples/run_workflow.py \
  --config configs/workflows/multi_agent_research.yaml \
  --input topic="AI-powered chatbot market analysis"
```

---

### 3. llm_debate_demo.yaml (NEW)

**Purpose**: Real LLM-powered debate (for the demo we created)

**File**: `configs/workflows/llm_debate_demo.yaml`

```yaml
workflow:
  name: llm_debate_demo
  description: "Real LLM agents debating product launch timing"
  version: "1.0"

  # Workflow metadata
  lifecycle_type: decision_making
  product_type: llm_powered_decision

  # Single stage: LLM debate
  stages:
    - name: llm_debate
      config_path: configs/stages/llm_debate_stage.yaml
      inputs:
        scenario: "{{ workflow.inputs.scenario }}"
        initial_positions: "{{ workflow.inputs.initial_positions }}"
        agent_personas: "{{ workflow.inputs.agent_personas }}"

      on_success:
        action: continue

      on_failure:
        action: escalate

  # LLM provider configuration
  llm_provider:
    provider: ollama
    base_url: http://localhost:11434
    model: llama3.2:3b
    temperature: 0.7
    max_tokens: 512
    timeout: 60

  # Workflow outputs
  outputs:
    - name: final_decision
      description: "Consensus decision after LLM debate"
      source: llm_debate.decision

    - name: debate_transcript
      description: "Complete debate with LLM prompts and responses"
      source: llm_debate.debate_history

    - name: convergence_metrics
      description: "Convergence and performance metrics"
      fields:
        - converged
        - rounds_to_convergence
        - total_llm_calls
        - total_tokens
        - total_latency_ms

    - name: llm_traces
      description: "Full LLM call traces"
      source: llm_debate.llm_traces

  # Observability
  observability:
    trace_all_decisions: true
    trace_llm_calls: true  # Log full prompts/responses
    track_collaboration_events: true
    track_convergence: true
    track_token_usage: true
    track_latency: true
    log_level: DEBUG

  # Cost tracking
  cost_tracking:
    enabled: true
    estimate_only: true  # For local models
    track_per_agent: true
    track_per_round: true

  use_cases:
    - "Product launch timing with real reasoning"
    - "Architecture decisions with autonomous agents"
    - "Strategic planning with genuine debate"
```

**Key Features**:
- ✅ Real LLM calls (not simulated)
- ✅ Autonomous mind-changing
- ✅ Full prompt/response tracing
- ✅ Token and cost tracking
- ✅ Latency metrics

**Usage**:
```bash
PYTHONPATH=/home/shinelay/meta-autonomous-framework \
  python3 examples/m3_llm_debate_demo.py --verbose
```

---

## Stage Configs

Stage configs define agent execution and collaboration strategies.

**Location**: `configs/stages/`

---

### 1. debate_stage.yaml

**Purpose**: Multi-round structured debate with convergence

**File**: `configs/stages/debate_stage.yaml`

```yaml
stage:
  name: debate_stage
  description: "Multi-round debate with convergence detection"
  version: "1.0"

  # Stage type
  type: multi_agent_debate  # M3 feature

  # Debating agents
  agents:
    - name: agent_advocate
      config_path: configs/agents/simple_researcher.yaml
      role: advocate
      description: "Argues for the proposed option"

    - name: agent_skeptic
      config_path: configs/agents/simple_researcher.yaml
      role: skeptic
      description: "Challenges and questions the proposal"

    - name: agent_analyst
      config_path: configs/agents/simple_researcher.yaml
      role: analyst
      description: "Provides objective analysis"

  # Execution: Debate rounds
  execution:
    agent_mode: sequential  # Sequential per round
    max_iterations: 3  # Max 3 rounds
    timeout_seconds: 600  # 10 minutes

  # Collaboration: Debate strategy (M3)
  collaboration:
    strategy: debate_and_synthesize  # M3 strategy
    config:
      max_rounds: 3
      convergence_threshold: 0.8  # 80% unchanged
      require_unanimous: false
      min_rounds: 1
      debate_structure: round_robin

  # Convergence detection (M3)
  convergence:
    enabled: true
    threshold: 0.8
    early_termination: true
    track_position_changes: true

  # Error handling
  error_handling:
    min_successful_agents: 2  # Need 2/3
    on_agent_failure: continue
    on_no_convergence: escalate

  # Input/output
  inputs:
    required:
      - decision_prompt
      - options
    optional:
      - context

  outputs:
    - decision
    - debate_history
    - convergence_info
    - conflicts
```

**Key Configuration**:
- `strategy: debate_and_synthesize` - Uses debate strategy
- `convergence_threshold: 0.8` - Stop when 80% agents unchanged
- `early_termination: true` - Stop early if converged
- `track_position_changes: true` - Track mind changes

---

### 2. parallel_research_stage.yaml

**Purpose**: Parallel agent execution with consensus

**File**: `configs/stages/parallel_research_stage.yaml`

```yaml
stage:
  name: parallel_research_stage
  description: "Multi-agent parallel research with consensus"
  version: "1.0"

  # Stage type
  type: multi_agent_parallel  # M3 feature

  # Agents (execute in parallel)
  agents:
    - name: market_researcher
      config_path: configs/agents/simple_researcher.yaml
      role: market_analysis
      description: "Analyzes market trends"

    - name: competitor_researcher
      config_path: configs/agents/simple_researcher.yaml
      role: competitor_analysis
      description: "Analyzes competitive landscape"

    - name: user_researcher
      config_path: configs/agents/simple_researcher.yaml
      role: user_research
      description: "Analyzes user needs"

  # Parallel execution (M3)
  execution:
    agent_mode: parallel  # Execute concurrently
    max_concurrent: 3  # All 3 at once
    timeout_seconds: 600

  # Error handling
  error_handling:
    min_successful_agents: 2  # Need 2/3
    on_agent_failure: continue
    on_stage_failure: halt

  # Collaboration: Consensus (M3)
  collaboration:
    strategy: consensus  # Simple voting
    config:
      threshold: 0.5  # Majority
      require_unanimous: false
      conflict_threshold: 0.3

  # Quality gates (M3)
  quality_gates:
    enabled: false  # Disabled for basic example
    min_confidence: 0.7
    on_failure: proceed_with_warning

  # Outputs
  outputs:
    - synthesized_decision
    - agent_outputs
    - synthesis_metadata
    - agent_metrics
```

**Key Configuration**:
- `agent_mode: parallel` - Concurrent execution
- `strategy: consensus` - Majority voting
- `conflict_threshold: 0.3` - Flag conflicts >30%
- `quality_gates` - Optional output validation

---

### 3. llm_debate_stage.yaml (NEW)

**Purpose**: LLM-powered debate with real reasoning

**File**: `configs/stages/llm_debate_stage.yaml`

```yaml
stage:
  name: llm_debate_stage
  description: "LLM-powered debate with real agent reasoning"
  version: "1.0"

  # Stage type
  type: llm_multi_agent_debate  # M3 + LLM

  # LLM-powered agents
  agents:
    - name: optimist
      role: Product Manager
      persona: "You're optimistic and business-focused..."
      initial_position: "Launch Now"
      initial_reasoning: "Market window closing..."
      llm_config:
        temperature: 0.7
        max_tokens: 512

    - name: realist
      role: Engineering Lead
      persona: "You're cautious and technical..."
      initial_position: "Wait 1 Month"
      initial_reasoning: "Critical bugs..."
      llm_config:
        temperature: 0.7
        max_tokens: 512

    - name: analyst
      role: Data Scientist
      persona: "You're data-driven..."
      initial_position: "Launch Beta"
      initial_reasoning: "Limited beta controls risk..."
      llm_config:
        temperature: 0.7
        max_tokens: 512

  # Execution: LLM calls
  execution:
    agent_mode: sequential_llm
    max_iterations: 3
    timeout_seconds: 180
    retry_on_llm_error: true
    max_llm_retries: 2

  # Collaboration: LLM debate
  collaboration:
    strategy: llm_debate_and_synthesize
    config:
      max_rounds: 3
      convergence_threshold: 0.8
      temperature: 0.7
      structured_output: true
      include_debate_history: true

  # LLM prompt configuration
  prompt_config:
    format: structured_json
    include_persona: true
    include_other_positions: true
    include_debate_history: true
    enforce_json_schema: true

  # Error handling
  error_handling:
    min_successful_agents: 2
    on_llm_parse_error: retry
    on_no_convergence: return_majority
    max_parse_retries: 2

  # Performance tracking
  performance:
    track_latency: true
    track_tokens: true
    track_costs: true
    per_agent_metrics: true
    per_round_metrics: true

  # Outputs
  outputs:
    - decision
    - debate_history
    - convergence_info
    - llm_traces
    - token_usage
    - latency_metrics
    - agent_mind_changes
```

**Key Configuration**:
- `agent_mode: sequential_llm` - Sequential LLM calls
- `persona` - LLM personality for each agent
- `prompt_config` - Control prompt structure
- `structured_output: true` - Require JSON
- `track_tokens: true` - Track token usage
- `track_latency: true` - Track LLM latency

---

## Key Concepts

### Workflow vs Stage

| Level | Purpose | Example |
|-------|---------|---------|
| **Workflow** | High-level orchestration | `debate_decision.yaml` |
| **Stage** | Execution details | `debate_stage.yaml` |

**Relationship**: Workflow references stage via `config_path`

### Agent Modes

| Mode | Description | Use Case |
|------|-------------|----------|
| `parallel` | Concurrent execution | Research, analysis |
| `sequential` | One at a time | Debate rounds |
| `sequential_llm` | Sequential LLM calls | LLM debate |

### Collaboration Strategies

| Strategy | Description | Config |
|----------|-------------|--------|
| `consensus` | Majority voting | `threshold: 0.5` |
| `debate_and_synthesize` | Multi-round debate | `max_rounds: 3` |
| `merit_weighted` | Expert weighting | `merit_weights` |
| `llm_debate_and_synthesize` | LLM-powered debate | `temperature: 0.7` |

### Convergence Settings

```yaml
convergence:
  enabled: true
  threshold: 0.8  # 80% unchanged
  early_termination: true
  track_position_changes: true
```

**How it works**:
- Track which agents changed positions
- Calculate % unchanged vs previous round
- If % ≥ threshold → converged → stop

### Quality Gates

```yaml
quality_gates:
  enabled: true
  min_confidence: 0.7
  min_findings: 5
  require_citations: true
  on_failure: retry_stage | escalate | proceed_with_warning
  max_retries: 2
```

**Validation checks**:
- Confidence threshold
- Minimum findings count
- Citation requirements

---

## Creating Your Own M3 Workflow

### Step 1: Create Workflow Config

**File**: `configs/workflows/my_workflow.yaml`

```yaml
workflow:
  name: my_workflow
  description: "My custom M3 workflow"
  version: "1.0"

  lifecycle_type: decision_making | research | analysis
  product_type: decision | insights | recommendation

  stages:
    - name: my_stage
      config_path: configs/stages/my_stage.yaml
      inputs:
        param1: "{{ workflow.inputs.param1 }}"

  inputs:
    required:
      - param1
    optional:
      - param2

  outputs:
    - name: result
      source: my_stage.output

  execution:
    timeout_seconds: 600
    parallel_execution: true | false

  observability:
    trace_all_decisions: true
    track_collaboration_events: true
    track_convergence: true
```

### Step 2: Create Stage Config

**File**: `configs/stages/my_stage.yaml`

```yaml
stage:
  name: my_stage
  description: "My custom stage"
  version: "1.0"

  type: multi_agent_parallel | multi_agent_debate

  agents:
    - name: agent1
      role: role1
      persona: "Agent 1 persona..."

  execution:
    agent_mode: parallel | sequential
    max_iterations: 3

  collaboration:
    strategy: consensus | debate_and_synthesize
    config:
      # Strategy-specific config

  convergence:
    enabled: true
    threshold: 0.8

  outputs:
    - output_field
```

### Step 3: Run Workflow

```bash
python3 examples/run_workflow.py \
  --config configs/workflows/my_workflow.yaml \
  --input param1="value"
```

---

## Examples Repository

| Config | Location | Purpose |
|--------|----------|---------|
| **Debate Decision** | `configs/workflows/debate_decision.yaml` | Multi-round debate |
| **Multi-Agent Research** | `configs/workflows/multi_agent_research.yaml` | Parallel research |
| **LLM Debate Demo** | `configs/workflows/llm_debate_demo.yaml` | Real LLM debate |
| **Debate Stage** | `configs/stages/debate_stage.yaml` | Debate execution |
| **Parallel Research Stage** | `configs/stages/parallel_research_stage.yaml` | Parallel execution |
| **LLM Debate Stage** | `configs/stages/llm_debate_stage.yaml` | LLM-powered debate |

---

## Summary

### M3 YAML Configs Enable

✅ **Declarative workflows** - No code required
✅ **Reusable stages** - Compose workflows from stages
✅ **Flexible strategies** - Consensus, debate, merit-weighted
✅ **Convergence detection** - Automatic termination
✅ **Quality gates** - Output validation
✅ **Observability** - Full tracking and metrics
✅ **LLM integration** - Real agent reasoning

### Next Steps

1. **Review examples**: Study existing configs
2. **Customize**: Modify for your use case
3. **Test**: Run with `run_workflow.py`
4. **Iterate**: Tune convergence thresholds, strategies
5. **Production**: Deploy with monitoring

---

## Related Files

- **Workflow configs**: `configs/workflows/*.yaml`
- **Stage configs**: `configs/stages/*.yaml`
- **Schema definitions**: `temper_ai/compiler/schemas.py`
- **Strategy implementations**: `temper_ai/strategies/*.py`
- **Demo scripts**: `examples/m3_*.py`

---

**M3 Status**: 16/16 tasks complete (100%)
**YAML Configs**: Production-ready
**Documentation**: Complete
