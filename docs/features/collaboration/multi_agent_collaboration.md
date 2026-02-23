# Multi-Agent Collaboration Guide (M3)

**Milestone**: M3 - Multi-Agent Collaboration
**Status**: Complete
**Version**: 1.0

---

## Table of Contents

1. [Overview](#overview)
2. [Parallel vs Sequential Execution](#parallel-vs-sequential-execution)
3. [Collaboration Strategies](#collaboration-strategies)
4. [Conflict Resolution](#conflict-resolution)
5. [Convergence Detection](#convergence-detection)
6. [Quality Gates](#quality-gates)
7. [Configuration Guide](#configuration-guide)
8. [Examples](#examples)
9. [Troubleshooting](#troubleshooting)

---

## Overview

M3 introduces true multi-agent collaboration to Temper AI. Multiple agents can now:
- Execute tasks in parallel for 2-3x speedup
- Synthesize outputs via collaboration strategies
- Resolve conflicts through voting or debate
- Detect convergence automatically
- Validate output quality before proceeding

### Key Features

| Feature | Description | Benefits |
|---------|-------------|----------|
| **Parallel Execution** | Multiple agents run concurrently | 2-3x faster execution |
| **Consensus Synthesis** | Majority voting with confidence tracking | Democratic decision making |
| **Debate Strategy** | Multi-round argumentation | Higher quality decisions |
| **Merit-Weighted Resolution** | Weight votes by agent expertise | Expert opinions matter more |
| **Convergence Detection** | Automatic detection of agreement | Early termination saves cost |
| **Quality Gates** | Validate outputs before proceeding | Prevent low-quality propagation |

---

## Parallel vs Sequential Execution

### Sequential Execution (M2)

Agents execute one after another:

```
Stage: Research
  ├─ Agent 1: Market Research (15s)
  ├─ Agent 2: Competitor Research (15s)
  └─ Agent 3: User Research (15s)
Total: 45 seconds
```

**Use Cases**:
- Single agent per stage
- Tasks requiring sequential dependencies
- Lower resource consumption

### Parallel Execution (M3)

Agents execute concurrently:

```
Stage: Research (parallel)
  ├─ Agent 1: Market Research ──────┐
  ├─ Agent 2: Competitor Research ──┼─→ Synthesis (20s total)
  └─ Agent 3: User Research ────────┘
Total: 20 seconds (2.25x speedup)
```

**Use Cases**:
- Independent research tasks
- Multi-perspective analysis
- Time-critical workflows

### Configuration

**Sequential** (default):
```yaml
execution:
  agent_mode: sequential
```

**Parallel**:
```yaml
execution:
  agent_mode: parallel
  max_concurrent: 3
```

---

## Collaboration Strategies

Collaboration strategies define how multiple agent outputs are synthesized into a unified decision.

### 1. Consensus Strategy

**Description**: Simple majority voting with confidence tracking.

**Algorithm**:
1. Count votes for each decision
2. Select majority decision
3. Calculate confidence = (majority_count / total_agents) × avg_confidence

**Configuration**:
```yaml
collaboration:
  strategy: consensus
  config:
    threshold: 0.5  # 50% majority required
    require_unanimous: false
    conflict_threshold: 0.3  # Flag conflicts >30%
```

**Example**:
```python
# 3 agents vote
Agent 1: "Option A" (confidence: 0.9)
Agent 2: "Option A" (confidence: 0.8)
Agent 3: "Option B" (confidence: 0.7)

Result: "Option A"
Confidence: (2/3) × ((0.9 + 0.8)/2) = 0.567
Votes: {"Option A": 2, "Option B": 1}
```

**Use Cases**:
- Quick decisions with clear majority
- Democratic voting
- Low-stakes decisions

---

### 2. Debate and Synthesize Strategy

**Description**: Multi-round debate with convergence detection.

**Algorithm**:
1. Round 1: Agents state initial positions
2. Round 2+: Agents see others' arguments, refine positions
3. Check convergence: % of agents who didn't change
4. Terminate early if converged, or at max_rounds
5. Synthesize final decision from debate history

**Configuration**:
```yaml
collaboration:
  strategy: debate_and_synthesize
  config:
    max_rounds: 3
    convergence_threshold: 0.8  # Stop if 80% unchanged
    min_rounds: 1
    require_unanimous: false
```

**Example**:
```python
# Round 1: Initial positions
Agent 1: "Microservices" (conf: 0.7)
Agent 2: "Monolith" (conf: 0.8)
Agent 3: "Hybrid" (conf: 0.6)

# Round 2: After seeing arguments
Agent 1: "Hybrid" (changed!)
Agent 2: "Monolith" (unchanged)
Agent 3: "Hybrid" (changed!)

# Convergence: 1/3 unchanged = 33% → Continue

# Round 3: Further refinement
Agent 1: "Hybrid" (unchanged)
Agent 2: "Hybrid" (changed!)
Agent 3: "Hybrid" (unchanged)

# Convergence: 2/3 unchanged = 67% → Still below 80%, but unanimous!
Result: "Hybrid"
Converged: Round 3
Confidence: 0.9 (unanimous + convergence bonus)
```

**Use Cases**:
- High-stakes decisions
- Complex trade-offs
- Situations requiring deep reasoning

---

### 3. Merit-Weighted Resolution (Conflict Resolver)

**Description**: Weight votes by agent merit scores (expertise, success rate, recency).

**Algorithm**:
1. Calculate merit weights for each agent:
   - Domain merit (40%): Success in current domain
   - Overall merit (30%): Global success rate
   - Recent performance (30%): Time-decayed recent tasks
2. Weight each vote: vote_weight = merit × confidence
3. Select decision with highest weighted score

**Configuration**:
```yaml
collaboration:
  strategy: consensus  # Use consensus first
  conflict_resolver: merit_weighted  # Resolve conflicts with merit
  config:
    merit_weights:
      domain_merit: 0.4
      overall_merit: 0.3
      recent_performance: 0.3
    auto_resolve_threshold: 0.85  # Auto-resolve if >85% weighted
    escalation_threshold: 0.5  # Escalate if <50%
```

**Example**:
```python
# Expert vs Novice vote
Agent 1 (Expert): "Option A" (confidence: 0.9, merit: 0.85)
Agent 2 (Novice): "Option B" (confidence: 0.8, merit: 0.6)

Weighted Scores:
  Option A: 0.9 × 0.85 = 0.765
  Option B: 0.8 × 0.6 = 0.48

Result: "Option A" (expert wins)
Confidence: 0.765 / 1.0 = 76.5%
```

**Use Cases**:
- Conflicting expert opinions
- Agents with varying expertise
- Domain-specific decisions

---

## Conflict Resolution

Conflicts occur when agents disagree. The framework detects and resolves conflicts automatically.

### Conflict Detection

A conflict is detected when:
- Agents propose different decisions
- Disagreement score exceeds threshold

**Disagreement Score**:
```python
disagreement_score = 1.0 - (largest_group_size / total_agents)
```

**Example**:
```python
# 3 agents, 2 vote "Option A", 1 votes "Option B"
disagreement_score = 1.0 - (2 / 3) = 0.33 (33% disagreement)
```

### Resolution Strategies

| Resolver | When to Use | Confidence |
|----------|-------------|------------|
| **Consensus** | Clear majority exists | Based on majority size |
| **Merit-Weighted** | Expert opinions differ | Based on merit scores |
| **Debate** | Need deeper reasoning | Based on convergence |
| **Human Escalation** | Irreconcilable conflict | Manual decision |

### Configuration

```yaml
# In stage config
collaboration:
  strategy: consensus
  conflict_resolver: merit_weighted  # Fallback resolver
  config:
    conflict_threshold: 0.3  # Flag conflicts >30%
```

---

## Convergence Detection

Convergence occurs when agents reach agreement through iterative refinement.

### How It Works

1. Track agent decisions across rounds
2. Calculate convergence score:
   ```python
   convergence = unchanged_agents / total_agents
   ```
3. Terminate early if convergence ≥ threshold

### Configuration

```yaml
convergence:
  enabled: true
  threshold: 0.8  # 80% agents unchanged
  early_termination: true
  track_position_changes: true
```

### Example

```python
# Round 1 → Round 2
Agent 1: "A" → "B" (changed)
Agent 2: "B" → "B" (unchanged)
Agent 3: "C" → "B" (changed)

Convergence: 1/3 = 33% → Continue

# Round 2 → Round 3
Agent 1: "B" → "B" (unchanged)
Agent 2: "B" → "B" (unchanged)
Agent 3: "B" → "B" (unchanged)

Convergence: 3/3 = 100% → CONVERGED ✓
```

---

## Quality Gates

Quality gates validate output quality before allowing the workflow to proceed.

### Available Checks

| Check | Description | Failure Action |
|-------|-------------|----------------|
| **min_confidence** | Minimum synthesis confidence | Retry or escalate |
| **min_findings** | Minimum number of findings | Retry stage |
| **require_citations** | Check for citations/sources | Warn or block |
| **custom_validator** | Custom validation function | Configurable |

### Configuration

```yaml
quality_gates:
  enabled: true
  min_confidence: 0.7  # 70% minimum
  min_findings: 5  # At least 5 findings
  require_citations: true
  on_failure: retry_stage  # or escalate, proceed_with_warning
  max_retries: 2
```

### Example

```python
# Synthesis result
Result: "Option A"
Confidence: 0.65  # Below 0.7 threshold!
Findings: 3  # Below 5 minimum!

Quality Gate: FAILED ❌
Action: retry_stage (attempt 1/2)

# After retry
Confidence: 0.75 ✓
Findings: 6 ✓
Quality Gate: PASSED ✓
```

---

## Configuration Guide

### Complete Stage Configuration

```yaml
# configs/stages/my_parallel_stage.yaml
stage:
  name: my_parallel_stage
  description: "Multi-agent parallel execution"
  type: multi_agent_parallel

  # Agents
  agents:
    - name: agent1
      config_path: configs/agents/agent1.yaml
      role: researcher
    - name: agent2
      config_path: configs/agents/agent2.yaml
      role: analyst
    - name: agent3
      config_path: configs/agents/agent3.yaml
      role: validator

  # Execution mode
  execution:
    agent_mode: parallel  # parallel or sequential
    max_concurrent: 3
    timeout_seconds: 600

  # Error handling
  error_handling:
    min_successful_agents: 2  # Need 2/3 to succeed
    on_agent_failure: continue
    on_stage_failure: halt

  # Collaboration
  collaboration:
    strategy: consensus  # or debate_and_synthesize
    conflict_resolver: merit_weighted  # optional
    config:
      threshold: 0.5
      conflict_threshold: 0.3

  # Convergence (for debate)
  convergence:
    enabled: true
    threshold: 0.8
    early_termination: true

  # Quality gates
  quality_gates:
    enabled: true
    min_confidence: 0.7
    min_findings: 5
    on_failure: retry_stage
    max_retries: 2
```

---

## Examples

See [examples/multi_agent_collaboration_examples.md](../../../examples/guides/multi_agent_collaboration_examples.md) for complete runnable examples:

1. **Parallel Research**: 3 agents research in parallel
2. **Debate Decision**: Multi-round debate with convergence

---

## Troubleshooting

### Issue: "Only X/Y agents succeeded"

**Cause**: Too few agents succeeded, below `min_successful_agents`.

**Solution**:
```yaml
error_handling:
  min_successful_agents: 2  # Lower threshold
  on_agent_failure: continue
```

### Issue: "Debate did not converge"

**Cause**: Agents couldn't reach agreement within max_rounds.

**Solution**:
```yaml
collaboration:
  config:
    max_rounds: 5  # Increase rounds
    convergence_threshold: 0.7  # Lower threshold
    require_unanimous: false  # Don't require 100%
```

### Issue: "Quality gate failed: confidence too low"

**Cause**: Synthesis confidence below threshold.

**Solution**:
```yaml
quality_gates:
  min_confidence: 0.6  # Lower threshold
  on_failure: proceed_with_warning  # Continue anyway
```

### Issue: Slow parallel execution

**Cause**: Network latency, LLM API rate limits.

**Solution**:
```yaml
execution:
  max_concurrent: 2  # Reduce concurrency
  timeout_seconds: 900  # Increase timeout
```

---

## Performance Tips

1. **Use parallel for independent tasks**: Market research, competitor analysis, user research
2. **Use sequential for dependent tasks**: Analysis → Synthesis → Recommendations
3. **Start with consensus**: Simplest strategy, good for most cases
4. **Use debate for critical decisions**: Higher quality, but slower
5. **Enable convergence detection**: Saves cost by terminating early
6. **Set appropriate timeouts**: Balance between patience and responsiveness

---

## Next Steps

- **M4**: Safety & Experimentation (blast radius, approval workflows, A/B testing)
- **M5**: Self-Improvement Loop (outcome analysis, improvement hypotheses)
- **M6**: Production Hardening (multi-region, disaster recovery)

---

**Document Version**: 1.0
**Created**: 2026-01-26
**Last Updated**: 2026-01-26
**Author**: m3-16-documentation
