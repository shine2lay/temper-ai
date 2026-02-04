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

    # Use semantic similarity instead of exact string matching (default: true)
    # Requires sentence-transformers: pip install sentence-transformers
    use_semantic_convergence: true

    # Context propagation strategy (default: "full")
    # - "full": All dialogue history (current behavior)
    # - "recent": Only recent rounds (reduces context size)
    # - "relevant": Filter by relevance to current agent
    context_strategy: "recent"

    # For "recent" strategy: number of recent rounds to include (default: 2)
    context_window_size: 2

    # Merit-weighted synthesis: weight agent opinions by historical performance (default: false)
    use_merit_weighting: true

    # Merit domain: domain for merit score lookup, None uses agent name (default: None)
    merit_domain: "architecture_decisions"
```

### Merit-Weighted Synthesis

Weight agent opinions by historical performance tracked in AgentMeritScore. Higher-performing agents have more influence on the final decision.

**How It Works**:
```
Merit Weight = expertise_score (or success_rate if not available)
Vote Weight = merit_weight × confidence
Winning Decision = highest total weighted votes
```

**Example**:
```yaml
# Enable merit weighting
collaboration:
  strategy: dialogue
  config:
    use_merit_weighting: true
    merit_domain: "architecture"  # Optional: specific domain
```

**When to Use**:
- ✅ When agent historical performance data is available
- ✅ Specialized agents with different expertise levels
- ✅ High-stakes decisions where expert opinions should matter more
- ✅ When some agents are known to be more reliable than others

**When NOT to Use**:
- ❌ No historical data (new agents, cold start)
- ❌ All agents equally expert in the domain
- ❌ Want democratic equal-weight voting
- ❌ Observability tracker not configured

**Impact**:
```
Without Merit Weighting (equal votes):
- Agent A (expert, merit: 0.9, confidence: 0.9): "Option X" → weight: 1.0
- Agent B (novice, merit: 0.4, confidence: 0.6): "Option Y" → weight: 1.0
Result: Tie (needs tie-breaking)

With Merit Weighting:
- Agent A (expert, merit: 0.9, confidence: 0.9): "Option X" → weight: 0.81
- Agent B (novice, merit: 0.4, confidence: 0.6): "Option Y" → weight: 0.24
Result: Option X wins decisively (expert opinion weighted 3.4× higher)
```

**Graceful Fallback**:
- If observability tracker unavailable → equal weights (1.0 for all)
- If no merit score for agent → neutral weight (0.5)
- If only success_rate available → use success_rate instead of expertise_score
```

### Context Curation Strategies

For long dialogues (many rounds or agents), full history becomes expensive and noisy. Context curation reduces costs by selectively propagating history.

| Strategy | What's Included | Use When | Cost Impact |
|----------|----------------|----------|-------------|
| **full** | All dialogue history | Default, < 5 rounds | Baseline |
| **recent** | Last N rounds (sliding window) | Long dialogues, recent context matters most | -40% to -70% |
| **relevant** | Agent's own history + mentions + latest round | Specific agents need specific context | -30% to -60% |

**Example Comparison** (5 rounds, 3 agents = 15 total entries):

```yaml
# Full strategy (baseline)
context_strategy: "full"
→ Agent sees: 15 entries (all history)

# Recent strategy (window_size: 2)
context_strategy: "recent"
context_window_size: 2
→ Agent sees: 6 entries (last 2 rounds only)
→ Cost savings: ~60%

# Relevant strategy
context_strategy: "relevant"
→ Agent sees: ~4-7 entries (own contributions + mentions + latest)
→ Cost savings: ~40-50%
```

**When to Use Each**:
- **Full**: Short dialogues (≤3 rounds), all context important
- **Recent**: Long dialogues where recent context matters most, all agents equally important
- **Relevant**: Long dialogues where each agent needs specific context (role-based, specialized agents)
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

**Convergence Detection**

Dialogue stops early when agents' positions stabilize (converge). Two modes:

1. **Semantic Convergence** (default, requires `sentence-transformers`):
   - Detects when agents express the same idea differently
   - Example: "Use microservices" ≈ "Adopt microservice architecture" (converged)
   - Uses sentence embeddings to calculate semantic similarity
   - Threshold: 90% similarity required for match
   - Fallback: If embeddings unavailable, uses exact match

2. **Exact Match Convergence** (`use_semantic_convergence: false`):
   - Requires identical decision strings
   - Example: "Use microservices" ≠ "Adopt microservices" (not converged)
   - Faster, no dependencies, but more strict

**Installation for Semantic Convergence**:
```bash
pip install sentence-transformers
```

**Early Stopping Conditions**
1. **Convergence**: >= `convergence_threshold` of agents maintain positions between rounds (after `min_rounds`)
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

## Role-Based Dialogue (Advanced)

### Description
Role-based dialogue is a **structured variant** of dialogue where each agent has a specific role in the conversation. This creates a natural interaction pattern that drives better decisions through specialized perspectives.

### Available Roles

| Role | Responsibility | When They Speak | Example Output |
|------|----------------|-----------------|----------------|
| **Proposer** | Makes proposals, refines based on feedback | First, then responds to critique | "Use microservices architecture" |
| **Critic** | Challenges proposals, identifies flaws | After proposer, identifies risks | "Operational complexity concern" |
| **Synthesizer** | Merges perspectives, finds common ground | After critic, integrates feedback | "Hybrid approach with bounded contexts" |
| **Reviewer** | Final validation, ensures quality | Last, approves or requests more work | "APPROVE / NEEDS WORK" |

### When to Use Role-Based Dialogue

- ✅ **Complex architectural decisions** requiring multiple expert perspectives
- ✅ **High-stakes choices** needing thorough vetting and validation
- ✅ **Multi-stakeholder decisions** where different viewpoints must be integrated
- ✅ **When you need both creativity and caution** (proposer vs critic tension)
- ✅ **4+ agents** (enough agents to fill roles meaningfully)

### When NOT to Use

- ❌ Simple decisions (overhead not worth it)
- ❌ Only 2-3 agents (not enough for role differentiation)
- ❌ When all agents should have equal voice (use standard dialogue)
- ❌ Urgent decisions (role-based takes longer but produces better quality)

### Configuration Example

```yaml
stages:
  - name: "architecture_decision"
    type: sequential
    agents:
      - dialogue_proposer      # Makes proposal
      - dialogue_critic        # Challenges proposal
      - dialogue_synthesizer   # Integrates feedback
      - dialogue_reviewer      # Final validation

    collaboration:
      strategy: dialogue
      config:
        max_rounds: 4
        convergence_threshold: 0.85
        use_semantic_convergence: true
```

### How It Works

**Round 1: Initial Positions**
1. **Proposer**: Makes bold proposal with rationale
2. **Critic**: Identifies flaws, risks, edge cases
3. **Synthesizer**: Proposes balanced middle ground
4. **Reviewer**: Assesses if ready (usually "NEEDS WORK" in round 1)

**Round 2+: Refinement**
1. **Proposer**: Refines proposal addressing critique
2. **Critic**: Acknowledges improvements or raises new concerns
3. **Synthesizer**: Updates synthesis based on evolution
4. **Reviewer**: Re-assesses readiness ("CONDITIONAL" if close)

**Final Round: Convergence**
1. **Proposer**: Final proposal incorporating all feedback
2. **Critic**: Accepts if concerns addressed
3. **Synthesizer**: Confirms alignment
4. **Reviewer**: "APPROVE" when quality threshold met

### Benefits

| Benefit | Explanation |
|---------|-------------|
| **Structured** | Clear roles prevent chaotic free-for-all |
| **Quality** | Reviewer ensures threshold met before approval |
| **Balance** | Synthesizer prevents polarization between proposer/critic |
| **Faster** | Roles guide conversation toward resolution |
| **Accountability** | Each role has clear responsibility |

### Role-Specific Agent Templates

Pre-built templates available:

- `configs/agents/dialogue_proposer.yaml` - Makes proposals and iterates
- `configs/agents/dialogue_critic.yaml` - Challenges and identifies flaws
- `configs/agents/dialogue_synthesizer.yaml` - Merges perspectives
- `configs/agents/dialogue_reviewer.yaml` - Final validation

Copy and customize these templates for your domain.

### Example Use Case: Microservices Decision

**Problem**: Should we adopt microservices architecture?

**Round 1**:
- Proposer: "Yes, microservices for scalability"
- Critic: "Too complex operationally"
- Synthesizer: "Hybrid - bounded contexts, not full micro"
- Reviewer: "NEEDS WORK - ops plan unclear"

**Round 2**:
- Proposer: "Microservices + centralized ops platform"
- Critic: "Better, but need migration strategy"
- Synthesizer: "Phased migration, new features first"
- Reviewer: "CONDITIONAL - need monitoring plan"

**Round 3**:
- Proposer: "Microservices + ops + monitoring + phased"
- Critic: "All concerns addressed"
- Synthesizer: "Consensus on phased approach with guardrails"
- Reviewer: "APPROVE - comprehensive solution"

**Result**: High-quality decision with buy-in from all perspectives

### Comparison: Standard vs Role-Based Dialogue

| Aspect | Standard Dialogue | Role-Based Dialogue |
|--------|-------------------|---------------------|
| **Structure** | Unstructured conversation | Clear roles and responsibilities |
| **Speed** | Can be slower (wandering) | Faster (guided toward resolution) |
| **Quality** | Variable | Higher (reviewer enforces threshold) |
| **Setup** | Any agents | Requires role-specific agents |
| **Best For** | 2-3 agents, exploratory | 4+ agents, decisive |
| **Convergence** | May not reach consensus | Structured toward approval |

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
- Using exact match when agents rephrase (disable `use_semantic_convergence: false`)

**Solutions:**
1. Enable semantic convergence: `use_semantic_convergence: true` (requires sentence-transformers)
2. Lower `convergence_threshold` (e.g., 0.75 instead of 0.90)
3. Increase `max_rounds` to allow more time
4. Update agent prompts to encourage synthesis
5. Consider if consensus is more appropriate

**Check convergence mode**:
- If agents say the same thing differently, use semantic convergence
- If you need exact string matches, use exact match mode

### High Costs

**Symptom:** Dialogue costs exceed budget

**Causes:**
- Too many agents
- Too many rounds
- Agents producing long outputs
- Full dialogue history passed every round (context explosion)

**Solutions:**
1. **Enable context curation**: `context_strategy: "recent"` or `"relevant"` (40-70% cost reduction)
2. Reduce `max_rounds`
3. Set lower `cost_budget_usd` to force early stop
4. Use fewer agents (3-4 is often sufficient)
5. Optimize agent prompts to be more concise
6. Consider debate strategy instead

**Context Curation Impact**:
```yaml
# Before (5 rounds × 3 agents × 2000 tokens = 30k tokens)
context_strategy: "full"
Cost: $X

# After (5 rounds × 3 agents × 800 tokens = 12k tokens)
context_strategy: "recent"
context_window_size: 2
Cost: ~$0.4X (60% savings)
```

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

## Enhancements

### Implemented - Phase 2 Complete! 🎉

**✅ Phase 2.1: Semantic Convergence Detection**
- Uses sentence embeddings to detect when agents express the same idea differently
- Automatically falls back to exact match if sentence-transformers unavailable
- Configurable via `use_semantic_convergence` flag
- See Dialogue Strategy configuration section for usage

**✅ Phase 2.2: Role-Based Dialogue**
- Agent roles (proposer, critic, synthesizer, reviewer) for structured dialogue
- Role context passed automatically to agents during dialogue
- Pre-built role-specific agent templates
- See Role-Based Dialogue section above for details

**✅ Phase 2.3: Context Curation**
- Selective history propagation reduces costs by 40-70%
- Three strategies: "full" (default), "recent" (sliding window), "relevant" (agent-specific)
- Configurable via `context_strategy` and `context_window_size`
- See Context Curation Strategies section for details

**✅ Phase 2.4: Merit-Weighted Dialogue**
- Weight agent opinions by historical performance (AgentMeritScore)
- Higher-performing agents have more influence on final decision
- Graceful fallback to equal weights when merit scores unavailable
- Configurable via `use_merit_weighting` and `merit_domain`
- See Merit-Weighted Synthesis section above for details

**All Phase 2 enhancements complete!** DialogueOrchestrator is now production-ready with advanced features for enterprise-grade multi-agent collaboration.
