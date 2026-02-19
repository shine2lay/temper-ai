# ADR-0003: Multi-Agent Collaboration Strategies

**Date:** 2026-01-26
**Status:** Accepted
**Deciders:** Framework Core Team, solution-architect specialist
**Tags:** collaboration, multi-agent, consensus, debate, M3

---

## Context

After completing Milestone 2 (M2) with single-agent workflows, Milestone 3 (M3) aimed to enable multiple agents to collaborate on tasks. The challenge was synthesizing outputs from multiple agents into coherent, high-quality decisions.

**Problem Statement:**
- How do we combine outputs from multiple agents working in parallel?
- How do we handle disagreements between agents?
- How do we ensure quality when agents have different levels of expertise?
- How do we balance speed (quick consensus) vs quality (deep reasoning)?

**Use Cases:**
1. **Parallel Research** - 3 agents research different aspects, synthesize findings
2. **Decision Making** - Multiple agents debate options, converge on best choice
3. **Expert Panels** - Weight opinions by domain expertise
4. **Quality Assurance** - Multiple reviewers validate outputs

**Key Questions:**
1. What synthesis strategies should we support?
2. How do we detect and resolve conflicts?
3. Should we use voting, averaging, or LLM-based synthesis?
4. How do we handle convergence in multi-round debates?

---

## Decision Drivers

- **Quality** - Collaborative decisions should be higher quality than single-agent
- **Performance** - 2-3x speedup through parallel execution
- **Flexibility** - Different strategies for different use cases
- **Conflict Resolution** - Automatic disagreement detection and resolution
- **Convergence** - Stop debate early when agents reach agreement
- **Expertise** - Weight expert opinions appropriately
- **Simplicity** - Easy to configure and understand

---

## Considered Options

### Option 1: Simple Majority Voting

**Description:** Select the output that receives the most votes from agents.

**Pros:**
- Extremely simple to implement
- Fast (<10ms)
- Democratic

**Cons:**
- No nuance - loses minority insights
- No confidence tracking
- No handling of ties
- Doesn't leverage expertise differences
- Can't improve through iteration

**Effort:** 1 day (LOW)

---

### Option 2: Weighted Averaging

**Description:** Average agent outputs weighted by confidence scores.

**Pros:**
- Accounts for agent confidence
- Smooth blending of perspectives
- Fast

**Cons:**
- Only works for numeric outputs
- Doesn't work for text, decisions, structured data
- No conflict detection
- Loses semantic meaning in averaging

**Effort:** 1-2 days (LOW)

---

### Option 3: LLM-Based Synthesis (Single Round)

**Description:** Use a supervisor LLM to synthesize agent outputs into final result.

**Pros:**
- Can handle any output type (text, structured, decisions)
- Semantic understanding of outputs
- Can identify conflicts and nuances
- Flexible and powerful

**Cons:**
- Slow (additional LLM call, 2-5s)
- Adds LLM cost
- Non-deterministic
- Black box synthesis (hard to explain)

**Effort:** 2-3 days (MEDIUM)

---

### Option 4: Multi-Strategy Framework (Consensus + Debate + Merit-Weighted)

**Description:** Implement multiple synthesis strategies, configurable per workflow:
- **Consensus** - Fast majority voting with confidence tracking
- **Debate** - Multi-round argumentation with convergence detection
- **Merit-Weighted** - Expert-weighted voting

**Pros:**
- **Flexible** - Right strategy for each use case
- **Performance** - Fast consensus for simple decisions (<10ms)
- **Quality** - Deep debate for high-stakes decisions
- **Expertise** - Merit-weighted for expert panels
- **Convergence** - Early termination when agents agree
- **Conflict Detection** - Automatic disagreement detection
- **Observability** - Track synthesis events and conflicts
- **Extensible** - Plugin architecture for custom strategies

**Cons:**
- More complex to implement (3 strategies)
- More configuration options
- Need to document when to use each strategy

**Effort:** 1 week (MEDIUM-HIGH)

---

## Decision Outcome

**Chosen Option:** Option 4: Multi-Strategy Framework (Consensus + Debate + Merit-Weighted)

**Justification:**

A multi-strategy framework provides the flexibility needed for diverse collaboration use cases:

1. **Performance Spectrum** - Fast consensus (<10ms) for quick decisions, deep debate (3-10x slower) for high-stakes decisions

2. **Quality Assurance** - Debate strategy with convergence detection ensures high-quality decisions through multi-round argumentation

3. **Expertise Weighting** - Merit-weighted strategy respects domain expertise (40%) + overall performance (30%) + recent success (30%)

4. **Conflict Resolution** - Automatic detection (disagreement < 30% threshold) with fallback resolver chain

5. **Convergence Detection** - Stop debate early when 80% of agents unchanged, saving cost

6. **Real-World Fit** - Different problems need different collaboration modes:
   - **Consensus** - "What color should the button be?" (quick majority)
   - **Debate** - "Should we migrate to microservices?" (deep reasoning)
   - **Merit-Weighted** - "Which algorithm for this ML problem?" (trust experts)

7. **Extensibility** - Plugin architecture allows custom strategies without modifying framework

**Decision Factors:**
- Parallel execution delivers **2.25x speedup** (3 agents: 45s sequential → 20s parallel)
- Consensus strategy: **<10ms latency** (suitable for high-throughput)
- Debate strategy: **3-10x single-round** (LLM-dependent, but higher quality)
- Merit-weighted: **<20ms latency** (includes DB query for agent performance)

---

## Consequences

### Positive

- **Performance** - 2-3x faster execution through parallel agent processing
- **Quality** - Higher-quality decisions through collaborative synthesis
- **Flexibility** - Right strategy for each use case (consensus/debate/merit)
- **Conflict Resolution** - Automatic disagreement detection and resolution
- **Convergence** - Early termination saves cost when agents reach agreement
- **Expertise** - Merit-weighted voting respects domain expertise
- **Observability** - Track synthesis events, conflicts, convergence
- **Extensibility** - Plugin architecture for custom strategies
- **Backward Compatible** - Single-agent workflows work unchanged

### Negative

- **Complexity** - 3 strategies to understand and configure
- **Configuration** - More options to set (strategy, thresholds, weights)
- **Testing** - More test coverage needed for multi-agent scenarios
- **Documentation** - Need guidance on when to use each strategy
- **Learning Curve** - Developers must understand strategy tradeoffs

### Neutral

- **Cost** - More LLM calls for debate, but balanced by convergence savings
- **State Management** - Requires multi-agent state fields (Annotated with custom merger)

---

## Implementation Notes

**Architecture:**

```python
# Strategy Interface
class CollaborationStrategy(ABC):
    @abstractmethod
    def synthesize(self, agent_outputs: List[AgentOutput]) -> SynthesisResult:
        """Synthesize multiple agent outputs into final result."""
        pass

# Consensus (Fast)
class ConsensusStrategy(CollaborationStrategy):
    def synthesize(self, outputs):
        # Majority voting with confidence tracking
        # <10ms latency
        pass

# Debate (Quality)
class DebateAndSynthesize(CollaborationStrategy):
    def synthesize(self, outputs):
        # Multi-round debate with convergence detection
        # 3-10x slower but higher quality
        pass

# Merit-Weighted (Expertise)
class MeritWeightedResolver(CollaborationStrategy):
    def synthesize(self, outputs):
        # Weight by domain expertise + performance
        # <20ms latency
        pass
```

**Key Components:**

1. **State Management** (`temper_ai/compiler/langgraph_compiler.py`)
   - Annotated state fields with custom dict merger
   - Preserves agent outputs for synthesis

2. **Strategies** (`temper_ai/strategies/`)
   - `consensus.py` - Democratic voting (<10ms)
   - `debate.py` - Multi-round argumentation with convergence
   - `merit_weighted.py` - Expertise-weighted voting
   - `registry.py` - Strategy registration and selection

3. **Parallel Execution** (`temper_ai/compiler/langgraph_compiler.py`)
   - LangGraph nested subgraphs for concurrent agents
   - Configurable max_concurrent limit
   - Minimum success threshold

4. **Convergence Detection** (`temper_ai/strategies/debate.py`)
   - Stop when 80% of agents unchanged
   - Position tracking across rounds
   - Cost savings through early termination

**Configuration:**

```yaml
collaboration:
  strategy: consensus  # or debate, merit_weighted
  conflict_resolver: merit_weighted
  config:
    threshold: 0.5
    conflict_threshold: 0.3
    max_rounds: 3  # debate only
    convergence_threshold: 0.8  # debate only
```

**Action Items:**
- [x] Implement ConsensusStrategy
- [x] Implement DebateAndSynthesize with convergence detection
- [x] Implement MeritWeightedResolver
- [x] Create StrategyRegistry for plugin architecture
- [x] Add parallel execution support in LangGraph compiler
- [x] Add observability tracking for synthesis events
- [x] Create example workflows (parallel-research, debate-decision)
- [x] Document strategy selection guidelines

---

## Related Decisions

- [ADR-0001: Execution Engine Abstraction](./0001-execution-engine-abstraction.md) - Enables custom execution for convergence
- [ADR-0002: LangGraph as Initial Engine](./0002-langgraph-as-initial-engine.md) - Nested subgraphs for parallel execution
- [ADR-0004: Observability Database Schema](./0004-observability-database-schema.md) - Track collaboration events

---

## References

- [Milestone 3 Completion Report](../milestones/milestone3_completion.md)
- [Multi-Agent Collaboration Guide](../features/collaboration/multi_agent_collaboration.md)
- [Collaboration Strategies Reference](../features/collaboration/collaboration_strategies.md)
- [Multi-Agent Examples](../../examples/guides/multi_agent_collaboration_examples.md)
- [TECHNICAL_SPECIFICATION.md](../../TECHNICAL_SPECIFICATION.md) - M3 specification

---

## Update History

| Date | Author | Change |
|------|--------|--------|
| 2026-01-26 | Framework Core Team | Initial decision |
| 2026-01-28 | agent-d6e90e | Backfilled from M3 completion |
