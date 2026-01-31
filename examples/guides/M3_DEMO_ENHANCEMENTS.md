# M3 Comprehensive Demo Enhancements

**Date**: 2026-01-27
**File**: `examples/m3_comprehensive_demo.py`
**Status**: Enhanced to mimic real M3 workflows

---

## Summary

Enhanced the M3 comprehensive demo to show realistic multi-agent collaboration workflows instead of static simulations. The demo now clearly demonstrates:

1. **How agents change their minds** through multi-round debate
2. **Step-by-step merit calculation** for weighted voting
3. **Actual prompts** that would be sent to agents
4. **Round-by-round evolution** of positions

---

## Demo 2: Debate & Convergence (Major Enhancement)

### Before (Static)
- Pre-scripted debate history
- No visibility into how agents change minds
- Just showed final results

### After (Realistic Simulation)

**Round 0: Initial Positions**
- Shows 3 divergent opinions
- Detailed reasoning for each position
- Clear confidence levels

**Round 1: Agents Reconsider**
```
🤖 Compiler re-queries agents with debate history...

optimist prompt:
  'You said: Launch Now'
  'realist argues: Critical bugs, security risks'
  'analyst proposes: Launch Beta (500 users, controlled risk)'
  'Do you want to revise your position?'

✓ optimist CHANGED: Launch Now → Launch Beta
  "After hearing realist's security concerns, analyst's beta
   approach makes sense. We can still capture market quickly
   but with less risk."
```

- Shows actual prompt that would be sent to agent LLM
- Demonstrates how debate context influences decisions
- Tracks position changes with ✓ markers

**Round 2: Further Persuasion**
```
realist prompt:
  'You said: Wait 1 Month'
  'optimist NOW says: Launch Beta (changed from Launch Now)'
  '2 out of 3 agents now support Launch Beta'
  'Do you want to revise your position?'

✓ realist CHANGED: Wait 1 Month → Launch Beta
  "After seeing strong consensus, I concede. If we limit to
   500 vetted users and monitor closely, risk is acceptable."
```

- Shows social proof effect (2/3 consensus influences holdout)
- Realistic reasoning for mind-change

**Round 3: Convergence Detection**
```
Convergence: 100% (3/3 agents unchanged)
Threshold: 80%
✓ 100% > 80% → CONVERGED! Stopping debate.
```

- Shows when debate stops (convergence threshold reached)
- Prevents unnecessary rounds

**Debate Evolution Tree**
```
💬 Debate Timeline
├── Round 0: Initial Divergence
│   ├── Launch Now: 1 (optimist)
│   ├── Wait 1 Month: 1 (realist)
│   └── Launch Beta: 1 (analyst)
├── Round 1: Optimist Changes Mind
│   ├── Launch Beta: 2 (optimist ✓, analyst)
│   └── Wait 1 Month: 1 (realist)
└── Round 2: Realist Persuaded
    └── Launch Beta: 3 ✓ UNANIMOUS
```

- Visual summary of position evolution
- Clear tracking of who changed when

---

## Demo 3: Merit-Weighted Resolution (Enhanced)

### Added: Step-by-Step Calculation

**Before**: Just showed final result
**After**: Shows complete merit calculation

```
═══ Weighted Voting Calculation ═══

For each agent:
  weighted_vote = merit_score × confidence

  senior_expert (Option A):
    merit: 0.926 × confidence: 0.90 = 0.833

  mid_level (Option A):
    merit: 0.803 × confidence: 0.85 = 0.683

  junior_dev (Option B):
    merit: 0.674 × confidence: 0.80 = 0.539

Total weighted votes:
  Option A: 0.833 + 0.683 = 1.516
  Option B: 0.539 = 0.539

Winner: Option A (1.516 > 0.539)
Expert opinions (senior + mid) outweigh junior opinion
```

**Benefits**:
- Clear visibility into how merit scores combine with confidence
- Shows why expert opinions dominate
- Explains the math behind the resolution

---

## Key Improvements

### 1. **Realistic Agent Behavior**
- Shows actual prompts that would be sent to LLMs
- Demonstrates how debate context influences thinking
- Realistic reasoning for position changes

### 2. **Educational Value**
- Step-by-step calculations visible
- Clear explanations of convergence
- Visual tracking of position evolution

### 3. **Workflow Authenticity**
- Mimics real M3 multi-agent execution
- Shows compiler re-querying agents with context
- Demonstrates convergence detection in action

### 4. **Better Understanding**
- Users can see exactly how debate works
- Clear visibility into merit weighting math
- Understands when/why agents change minds

---

## Code Quality

- Maintained clean structure
- Rich markup properly balanced
- Clear section separators
- Educational comments

---

## Usage

```bash
# Run the enhanced demo
python3 examples/m3_comprehensive_demo.py

# Focus on specific demos
# Demo 1: Consensus (simple voting)
# Demo 2: Debate (realistic multi-round, mind-changing)
# Demo 3: Merit-weighted (step-by-step calculation)
# Demo 4: Quality gates (validation)
# Demo 5: Parallel execution (performance)
# Demo 6: Strategy registry (available strategies)
```

---

## Future Enhancements (Optional)

1. **Interactive Mode**: Let users choose positions and see debate evolve
2. **Real LLM Integration**: Connect to actual LLM for true agent responses
3. **Custom Scenarios**: Let users configure number of agents, initial positions
4. **Visualizations**: Add graphs showing convergence over time
5. **Comparison Mode**: Run same scenario with different strategies

---

## Technical Details

### Debate Flow (src/strategies/debate.py)

```python
# Key method: _calculate_convergence
def _calculate_convergence(
    self,
    current_outputs: List[AgentOutput],
    previous_decisions: Optional[Dict[str, Any]]
) -> float:
    """Calculate convergence score (% agents unchanged)."""
    if previous_decisions is None:
        return 0.0  # First round

    unchanged_count = 0
    for output in current_outputs:
        prev_decision = previous_decisions.get(output.agent_name)
        if prev_decision is not None and str(output.decision) == str(prev_decision):
            unchanged_count += 1

    return unchanged_count / len(current_outputs)
```

**In real workflows**:
- Line 168-169: Compiler re-queries agents with debate context
- Agents receive: previous arguments, current vote distribution, round number
- Agents can: maintain position OR change based on new information
- Convergence check: when >threshold% agents unchanged, stop

### Merit Calculation (src/strategies/conflict_resolution.py)

```python
def calculate_merit_weighted_votes(
    conflict: Conflict,
    context: ResolutionContext,
    merit_weights: Dict[str, float]
) -> Dict[str, float]:
    """Calculate weighted votes for each decision option."""
    decision_scores: Dict[str, float] = {}

    for agent_name in conflict.agents:
        output = context.agent_outputs.get(agent_name)
        merit = context.agent_merits.get(agent_name)

        merit_score = merit.calculate_weight(merit_weights)
        # Weighted vote = merit * confidence
        weight = merit_score * output.confidence

        decision_scores[output.decision] = decision_scores.get(output.decision, 0.0) + weight

    return decision_scores
```

**Composite merit** (default weights):
- Domain merit: 40% (success in this specific domain)
- Overall merit: 30% (general track record)
- Recent performance: 30% (last 10 tasks)

---

## Comparison: Static vs Realistic

| Aspect | Before | After |
|--------|--------|-------|
| **Debate rounds** | Static history | Simulated re-querying |
| **Agent prompts** | Hidden | Visible |
| **Position changes** | Unexplained | Explained with reasoning |
| **Convergence** | Just a number | Clear threshold check |
| **Merit calculation** | Black box | Step-by-step breakdown |
| **Educational value** | Low | High |
| **Workflow authenticity** | Low | High |

---

## Impact

**Before**: Users saw results but not how they were produced
**After**: Users understand the complete multi-agent workflow

**Learning curve**: Reduced - clear visibility into all steps
**Trust**: Increased - can verify calculations manually
**Debugging**: Easier - can see exactly where decisions change

---

## Related Files

- `examples/m3_comprehensive_demo.py` - Enhanced demo script
- `src/strategies/debate.py` - Debate strategy implementation
- `src/strategies/conflict_resolution.py` - Merit-weighted resolution
- `src/strategies/consensus.py` - Simple consensus voting
- `src/compiler/langgraph_compiler.py` - Orchestration layer

---

**Status**: ✅ Complete
**Demo runs**: Successfully (all 6 demos)
**Output**: Enhanced with realistic workflow simulation
