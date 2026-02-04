# Collaboration Strategies Guide

This guide explains the different collaboration strategies available for multi-agent workflows and how to choose between them.

## Overview

The framework supports three main collaboration strategies for synthesizing outputs from multiple agents:

| Strategy | Rounds | Agent Interaction | Use Case |
|----------|--------|-------------------|----------|
| **Consensus** | Single | Post-hoc voting | Simple decisions, quick consensus |
| **Debate** | Multi | Simulated back-and-forth | Adversarial analysis, thorough vetting |
| **Dialogue** | Multi | True agent re-invocation | Complex decisions, iterative refinement |

## Consensus Strategy

### Description
Consensus uses simple majority voting to synthesize agent outputs. All agents execute once in parallel or sequence, then their outputs are combined using voting logic.

### When to Use
- ✅ Simple decisions with clear options
- ✅ Time/cost-sensitive scenarios (single LLM call per agent)
- ✅ When agents have independent perspectives
- ✅ Straightforward requirements with little ambiguity

### When NOT to Use
- ❌ Complex decisions requiring deliberation
- ❌ When agents need to respond to each other
- ❌ Situations where initial positions may be uninformed

### Configuration

```yaml
collaboration:
  strategy: consensus
  config:
    # Minimum percentage required for consensus (default: 0.51)
    min_consensus: 0.75

    # Tie-breaking method: "confidence" or "first" (default: "confidence")
    tie_breaker: "confidence"

    # Minimum number of agents required (default: 1)
    min_agents: 2
```

### Example

```yaml
stages:
  - name: "quick_decision"
    type: parallel
    agents:
      - reviewer_1
      - reviewer_2
      - reviewer_3
    collaboration:
      strategy: consensus
      config:
        min_consensus: 0.67  # Require 2/3 agreement
```

### Output
- **Method**: `"consensus"` or `"consensus_weak"` (if below threshold)
- **Confidence**: (support_percentage) × (average_confidence_of_supporters)
- **Metadata**: `supporters`, `dissenters`, `decision_support`, `needs_conflict_resolution`

---

## Debate Strategy

### Description
Debate simulates multi-round adversarial discussion by re-running the same agents with accumulated context. Agents see prior round outputs as static text, not as true dialogue partners.

### When to Use
- ✅ Adversarial analysis (find flaws, challenge assumptions)
- ✅ When you want thorough vetting of proposals
- ✅ Cost-effective multi-round reasoning
- ✅ Convergence detection is important

### When NOT to Use
- ❌ When true agent-to-agent interaction is needed
- ❌ Extremely high-stakes decisions (use dialogue instead)
- ❌ Single-round decisions (use consensus)

### Configuration

```yaml
collaboration:
  strategy: debate
  config:
    # Maximum debate rounds (default: 3)
    max_rounds: 5

    # Convergence threshold: 0.0-1.0 (default: 0.8)
    convergence_threshold: 0.85

    # Require unanimous agreement (default: false)
    require_unanimous: false

    # Minimum rounds before convergence check (default: 1)
    min_rounds: 2
```

### Example

```yaml
stages:
  - name: "adversarial_review"
    type: sequential
    agents:
      - proposer
      - critic
      - reviewer
    collaboration:
      strategy: debate
      config:
        max_rounds: 3
        convergence_threshold: 0.8
        min_rounds: 2
```

### Output
- **Method**: `"debate_and_synthesize"`
- **Confidence**: Boosted if converged, reduced if not
- **Metadata**: `debate_history`, `total_rounds`, `converged`, `convergence_round`

### Debate vs Consensus
- **Debate** = Multiple rounds, convergence detection, accumulated context
- **Consensus** = Single round, majority vote, no iteration

---

## Dialogue Strategy

### Description
Dialogue enables true multi-agent dialogue by re-invoking agents across multiple rounds with structured dialogue history. Agents can directly respond to each other's reasoning and adjust positions based on new insights.

### When to Use
- ✅ **Complex architectural decisions** (microservices vs monolith, database choice)
- ✅ **High-stakes decisions** requiring thorough deliberation
- ✅ **Multi-perspective synthesis** where agents have complementary expertise
- ✅ **Iterative refinement** of proposals across rounds
- ✅ When agent positions should **evolve based on peer reasoning**

### When NOT to Use
- ❌ Simple yes/no decisions (use consensus)
- ❌ Tight budget constraints (dialogue = multiple LLM calls per agent)
- ❌ Time-sensitive scenarios (dialogue takes longer)
- ❌ When independent opinions are required (use consensus)

### Configuration

```yaml
collaboration:
  strategy: dialogue
  config:
    # Maximum dialogue rounds (default: 3, must be >= 1)
    max_rounds: 5

    # Convergence threshold: 0.0-1.0 (default: 0.85)
    # Percentage of agents whose positions must remain unchanged
    convergence_threshold: 0.90

    # Cost budget in USD (optional, default: None = unlimited)
    cost_budget_usd: 20.0

    # Minimum rounds before allowing convergence (default: 1, must be >= 1)
    min_rounds: 3
```

### Example: Architecture Decision

```yaml
stages:
  - name: "architecture_dialogue"
    type: sequential
    agents:
      - architect
      - security_engineer
      - performance_engineer
      - tech_lead
    collaboration:
      strategy: dialogue
      config:
        max_rounds: 5
        convergence_threshold: 0.90
        cost_budget_usd: 20.0
        min_rounds: 3
```

### How Dialogue Works

**Round 1: Initial Positions**
- All agents execute independently
- No dialogue history provided
- Each agent provides initial position

**Round 2+: Dialogue Rounds**
- Agents receive `dialogue_history` in input data
- History contains prior rounds' outputs (agent name, decision, reasoning, confidence)
- Agents can respond to others' reasoning
- Agents may change or maintain positions

**Early Stopping Conditions**
1. **Convergence**: >= `convergence_threshold` of agents maintain positions between rounds
2. **Budget**: Cumulative cost exceeds `cost_budget_usd`
3. **Max Rounds**: `max_rounds` reached

**Final Synthesis**
- Uses consensus strategy on final round's outputs
- High-confidence synthesis if converged

### Agent Prompt Template

To make agents dialogue-aware, use this pattern in your agent prompt:

```yaml
prompt: |
  {% if dialogue_history %}
  ## Prior Dialogue Rounds:

  {% for entry in dialogue_history %}
  **Round {{ entry.round }} - {{ entry.agent }}:**
  Decision: {{ entry.output }}
  Reasoning: {{ entry.reasoning }}
  Confidence: {{ entry.confidence }}
  {% endfor %}

  Based on the above dialogue, provide your revised position:
  - Have you changed your mind? Why?
  - What new insights emerged?
  {% else %}
  ## Initial Round:
  Provide your initial position.
  {% endif %}

  {{ task_description }}
```

See `configs/agents/dialogue_aware_agent.yaml` for a complete example.

### Output
- **Method**: `"consensus"` (final synthesis method)
- **Confidence**: Based on final round consensus
- **Metadata**:
  - `strategy`: `"dialogue"`
  - `synthesis_method`: `"consensus_from_final_round"`
  - Plus all consensus metadata (votes, supporters, etc.)

### Dialogue vs Debate
| Aspect | Dialogue | Debate |
|--------|----------|--------|
| **Agent Re-invocation** | True (agents get dialogue_history) | Simulated (static context) |
| **Interaction** | Agents respond to each other | Agents see prior outputs as text |
| **Cost** | Higher (multiple LLM calls) | Moderate |
| **Use Case** | Complex decisions | Adversarial analysis |
| **Agent Awareness** | Agents know they're in dialogue | Agents see accumulated text |

---

## Choosing the Right Strategy

### Decision Tree

```
Is it a simple decision with clear options?
├─ Yes → Use CONSENSUS (fast, cost-effective)
└─ No → Are agents' positions likely to evolve through discussion?
    ├─ Yes → Use DIALOGUE (true multi-agent interaction)
    └─ No → Do you need adversarial analysis?
        ├─ Yes → Use DEBATE (challenge assumptions)
        └─ No → Use CONSENSUS (default)
```

### Cost Comparison

Assuming 3 agents, $0.50 per LLM call:

| Strategy | Rounds | Calls | Cost |
|----------|--------|-------|------|
| **Consensus** | 1 | 3 | $1.50 |
| **Debate** (3 rounds) | 3 | 9 | $4.50 |
| **Dialogue** (3 rounds) | 3 | 9 | $4.50 |

**Note:** Debate and Dialogue have similar costs but different interaction models.

### Performance Comparison

| Metric | Consensus | Debate | Dialogue |
|--------|-----------|--------|----------|
| **Latency** | Low (parallel) | Medium (sequential rounds) | Medium-High (sequential rounds) |
| **Quality** | Baseline | High (adversarial) | Highest (collaborative) |
| **Cost** | Low | Medium | Medium |
| **Convergence** | N/A (single round) | Detected | Detected |
| **Complexity** | Simple | Moderate | High |

---

## Configuration Best Practices

### Consensus
```yaml
# Default configuration (works for most cases)
collaboration:
  strategy: consensus
  config:
    min_consensus: 0.51  # Simple majority
    tie_breaker: "confidence"  # Use agent confidence scores

# High-stakes decisions
collaboration:
  strategy: consensus
  config:
    min_consensus: 0.75  # Require strong majority
    min_agents: 3  # Require multiple perspectives
```

### Debate
```yaml
# Balanced configuration
collaboration:
  strategy: debate
  config:
    max_rounds: 3
    convergence_threshold: 0.8
    min_rounds: 1

# Thorough vetting
collaboration:
  strategy: debate
  config:
    max_rounds: 5
    convergence_threshold: 0.9
    min_rounds: 2
    require_unanimous: false  # Allow dissent
```

### Dialogue
```yaml
# Standard dialogue
collaboration:
  strategy: dialogue
  config:
    max_rounds: 3
    convergence_threshold: 0.85
    cost_budget_usd: 10.0
    min_rounds: 2

# High-stakes dialogue
collaboration:
  strategy: dialogue
  config:
    max_rounds: 5
    convergence_threshold: 0.90  # Higher convergence bar
    cost_budget_usd: 20.0
    min_rounds: 3  # Require thorough discussion
```

---

## Troubleshooting

### Dialogue Not Converging

**Symptom:** Dialogue reaches `max_rounds` without convergence

**Causes:**
- Agents have fundamentally different perspectives
- `convergence_threshold` is too high
- Agents' prompts don't encourage compromise

**Solutions:**
1. Lower `convergence_threshold` (e.g., 0.75 instead of 0.90)
2. Increase `max_rounds` to allow more time
3. Update agent prompts to encourage synthesis
4. Consider if consensus is more appropriate

### High Costs

**Symptom:** Dialogue costs exceed budget

**Causes:**
- Too many agents
- Too many rounds
- Agents producing long outputs

**Solutions:**
1. Reduce `max_rounds`
2. Set lower `cost_budget_usd` to force early stop
3. Use fewer agents (3-4 is often sufficient)
4. Optimize agent prompts to be more concise
5. Consider debate strategy instead

### Weak Consensus

**Symptom:** Result has `method: "consensus_weak"` or low confidence

**Causes:**
- Agents genuinely disagree
- Not enough agents participating
- Poor initial positions

**Solutions:**
1. Use debate or dialogue for deliberation
2. Add more agents with diverse perspectives
3. Improve agent prompts
4. Lower `min_consensus` threshold if appropriate

### Agents Not Changing Positions

**Symptom:** Dialogue shows 0% convergence (all agents change) or 100% convergence (none change) every round

**Causes:**
- Agent prompts don't reference `dialogue_history`
- Agents too stubborn or too agreeable
- Insufficient guidance on when to change positions

**Solutions:**
1. Use dialogue-aware prompt template (see above)
2. Add explicit instructions: "Consider others' reasoning and adjust if warranted"
3. Provide examples of position changes in prompts
4. Verify `dialogue_history` is being passed correctly

---

## Examples

### Example 1: Code Review (Consensus)

```yaml
name: "Code Review Workflow"
stages:
  - name: "parallel_review"
    type: parallel  # Fast parallel execution
    agents:
      - style_reviewer
      - security_reviewer
      - performance_reviewer
    collaboration:
      strategy: consensus
      config:
        min_consensus: 0.67  # 2/3 must agree
        tie_breaker: "confidence"
```

**Why consensus?** Independent reviews, no need for interaction, cost-effective.

### Example 2: Security Analysis (Debate)

```yaml
name: "Security Assessment"
stages:
  - name: "adversarial_analysis"
    type: sequential
    agents:
      - security_analyst
      - attacker_mindset
      - defender
    collaboration:
      strategy: debate
      config:
        max_rounds: 3
        convergence_threshold: 0.85
        min_rounds: 2
```

**Why debate?** Adversarial perspectives benefit from multi-round analysis.

### Example 3: Architecture Decision (Dialogue)

```yaml
name: "Architecture Selection"
stages:
  - name: "collaborative_decision"
    type: sequential
    agents:
      - solution_architect
      - security_engineer
      - performance_engineer
      - cost_analyst
      - tech_lead
    collaboration:
      strategy: dialogue
      config:
        max_rounds: 5
        convergence_threshold: 0.90
        cost_budget_usd: 25.0
        min_rounds: 3
```

**Why dialogue?** High-stakes decision requiring true collaboration and position evolution.

---

## Validation

To validate DialogueOrchestrator works correctly, run:

```bash
python3 examples/validate_dialogue_orchestrator.py
```

This will:
- Create a dialogue-enabled workflow
- Simulate multi-round agent execution
- Verify dialogue history propagation
- Test convergence detection
- Validate final synthesis

Expected output: Dialogue transcript showing multiple rounds, agent position changes, convergence detection, and final synthesized decision.

---

## References

- **Consensus Implementation**: `src/strategies/consensus.py`
- **Debate Implementation**: `src/strategies/debate.py`
- **Dialogue Implementation**: `src/strategies/dialogue.py`
- **Base Classes**: `src/strategies/base.py`
- **Test Coverage**:
  - `tests/test_strategies/test_consensus.py`
  - `tests/test_strategies/test_debate.py`
  - `tests/test_strategies/test_dialogue.py`
- **Examples**:
  - `examples/dialogue_simple.yaml`
  - `examples/dialogue_advanced.yaml`
  - `configs/agents/dialogue_aware_agent.yaml`
- **Validation**: `examples/validate_dialogue_orchestrator.py`

---

## Future Enhancements (Phase 2)

The following enhancements are planned for DialogueOrchestrator:

1. **Semantic Convergence Detection**: Use embeddings to detect when agents express the same idea differently
2. **Role-Based Dialogue**: Agent roles (proposer, critic, synthesizer) for structured dialogue
3. **Context Curation**: Selective history propagation to reduce noise and cost
4. **Merit-Weighted Dialogue**: Weight agent opinions by historical performance

See `ARCHITECTURE_ISSUES_BACKLOG.md` for details.
