# Task: m3-05-merit-weighted-resolution - Implement MeritWeighted Conflict Resolution

**Priority:** HIGH (P1)
**Effort:** 10 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

Implement merit-weighted conflict resolution strategy that uses agent success history to weight votes. Agents with higher merit scores (domain expertise, recent performance, overall success rate) have more influence in resolving conflicts.

---

## Files to Create

- `src/strategies/merit_weighted.py` - Merit-weighted resolver (~300 lines)
- `tests/test_strategies/test_merit_weighted.py` - Resolver tests

---

## Acceptance Criteria

### Core Functionality
- [ ] Implements `ConflictResolver` interface
- [ ] Weighted voting: merit_score * confidence * recency_factor
- [ ] Domain-specific merit (agent expertise in current task domain)
- [ ] Recent performance boost (recency decay factor)
- [ ] Confidence thresholds for auto-resolve vs escalation
- [ ] Fallback to HumanEscalation when confidence <50%

### Merit Calculation
- [ ] Calculate composite merit score from multiple dimensions
- [ ] Configurable weights for each merit component
- [ ] Handle missing merit data gracefully
- [ ] Normalize scores across agents

### Auto-Resolve Logic
- [ ] Auto-resolve if winning decision has >85% weighted support
- [ ] Escalate to human if no decision has >50% weighted support
- [ ] Middle ground: use merit-weighted decision but flag for review

### Integration
- [ ] Query merit scores from observability database (M1)
- [ ] Track resolution history for learning
- [ ] Log weighted votes for transparency

### Testing
- [ ] Test with equal merit (equivalent to simple voting)
- [ ] Test with high merit disparity (expert vs novice)
- [ ] Test auto-resolve threshold
- [ ] Test escalation threshold
- [ ] Test missing merit data handling
- [ ] Integration test with observability DB
- [ ] Coverage >85%

---

## Implementation Details

### Class Implementation

```python
"""Merit-weighted conflict resolution strategy.

Resolves conflicts by weighting votes based on agent merit:
- Domain expertise in current task
- Overall success rate
- Recent performance (time-decayed)

Higher-merit agents have more influence in close decisions.
"""
from typing import Dict, Any, Optional, Tuple
import math

from src.strategies.conflict_resolution import (
    ConflictResolver,
    Resolution,
    ResolutionContext,
    AgentMerit,
    calculate_merit_weighted_votes,
    get_highest_weighted_decision
)
from src.strategies.base import Conflict


class MeritWeightedResolver(ConflictResolver):
    """Merit-weighted conflict resolution.

    Uses agent success history to weight votes:
    - Domain merit: Success rate in current domain (40%)
    - Overall merit: Global success rate (30%)
    - Recent performance: Recent task success (30%)

    Example:
        >>> resolver = MeritWeightedResolver()
        >>> conflict = Conflict(
        ...     agents=["expert_agent", "novice_agent"],
        ...     decisions=["Option A", "Option B"],
        ...     disagreement_score=0.8,
        ...     context={}
        ... )
        >>> context = ResolutionContext(
        ...     agent_merits={
        ...         "expert_agent": AgentMerit("expert", 0.9, 0.85, 0.9, "expert"),
        ...         "novice_agent": AgentMerit("novice", 0.6, 0.65, 0.6, "novice")
        ...     },
        ...     agent_outputs={...},
        ...     stage_name="research",
        ...     workflow_name="mvp",
        ...     workflow_config={},
        ...     previous_resolutions=[]
        ... )
        >>> resolution = resolver.resolve(conflict, context)
        >>> # Expert's vote weighs ~1.5x novice's vote
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize resolver.

        Args:
            config: Configuration:
                - merit_weights: Weights for merit components
                - auto_resolve_threshold: Confidence for auto-resolve (default: 0.85)
                - escalation_threshold: Confidence for escalation (default: 0.5)
                - recency_decay_days: Days for 50% decay (default: 30)
        """
        self.config = config or {}
        self.merit_weights = self.config.get("merit_weights", {
            "domain_merit": 0.4,
            "overall_merit": 0.3,
            "recent_performance": 0.3
        })
        self.auto_resolve_threshold = self.config.get("auto_resolve_threshold", 0.85)
        self.escalation_threshold = self.config.get("escalation_threshold", 0.5)
        self.recency_decay_days = self.config.get("recency_decay_days", 30)

    def resolve(
        self,
        conflict: Conflict,
        context: ResolutionContext
    ) -> Resolution:
        """Resolve conflict using merit-weighted voting.

        Args:
            conflict: Conflict to resolve
            context: Context with agent merits

        Returns:
            Resolution with merit-weighted decision

        Raises:
            ValueError: If conflict is invalid or context missing
        """
        # Validate inputs
        if not conflict.agents:
            raise ValueError("Conflict must have agents")

        if not context.agent_merits:
            raise ValueError("Context must have agent merits")

        # Calculate weighted votes
        decision_scores = calculate_merit_weighted_votes(
            conflict,
            context,
            self.merit_weights
        )

        if not decision_scores:
            raise ValueError("No decision scores calculated")

        # Get winning decision
        decision, raw_score = get_highest_weighted_decision(decision_scores)

        # Normalize confidence (0-1 scale)
        total_possible_weight = len(conflict.agents)  # If all agents perfect merit + confidence
        confidence = min(raw_score / total_possible_weight, 1.0)

        # Determine resolution method based on confidence
        if confidence >= self.auto_resolve_threshold:
            method = "merit_weighted_auto"
            needs_review = False
        elif confidence < self.escalation_threshold:
            method = "merit_weighted_escalation"
            needs_review = True
        else:
            method = "merit_weighted_flagged"
            needs_review = True  # Middle ground: resolve but flag

        # Identify winning agents
        winning_agents = [
            agent for agent in conflict.agents
            if str(context.agent_outputs[agent].decision) == decision
        ]

        # Build detailed reasoning
        reasoning = self._build_reasoning(
            decision, confidence, winning_agents, context, decision_scores
        )

        return Resolution(
            decision=decision,
            reasoning=reasoning,
            confidence=confidence,
            method=method,
            winning_agents=winning_agents,
            metadata={
                "decision_scores": decision_scores,
                "auto_resolved": not needs_review,
                "needs_review": needs_review,
                "merit_weights_used": self.merit_weights,
                "threshold_info": {
                    "auto_resolve": self.auto_resolve_threshold,
                    "escalation": self.escalation_threshold
                }
            }
        )

    def _build_reasoning(
        self,
        decision: str,
        confidence: float,
        winning_agents: list,
        context: ResolutionContext,
        decision_scores: Dict[str, float]
    ) -> str:
        """Build detailed reasoning for resolution.

        Args:
            decision: Resolved decision
            confidence: Confidence score
            winning_agents: Agents who voted for decision
            context: Resolution context
            decision_scores: Weighted scores per decision

        Returns:
            Reasoning string
        """
        lines = []

        # Overall decision
        lines.append(
            f"Resolved to '{decision}' via merit-weighted voting "
            f"(confidence: {confidence:.1%})."
        )

        # Winning agents and their merits
        merit_info = []
        for agent in winning_agents:
            merit = context.agent_merits.get(agent)
            if merit:
                weight = merit.calculate_weight(self.merit_weights)
                merit_info.append(f"{agent} (merit: {weight:.2f})")

        if merit_info:
            lines.append(f"Supporting agents: {', '.join(merit_info)}.")

        # Score breakdown
        score_breakdown = ", ".join(
            f"'{d}': {s:.2f}" for d, s in decision_scores.items()
        )
        lines.append(f"Weighted scores: {score_breakdown}.")

        # Resolution action
        if confidence >= self.auto_resolve_threshold:
            lines.append("High confidence - auto-resolved.")
        elif confidence < self.escalation_threshold:
            lines.append("Low confidence - escalating to human review.")
        else:
            lines.append("Medium confidence - resolved but flagged for review.")

        return " ".join(lines)

    def get_capabilities(self) -> Dict[str, bool]:
        """Get resolver capabilities."""
        return {
            "requires_merit": True,  # Needs merit scores
            "requires_human": False,  # Can auto-resolve
            "requires_llm": False,  # No LLM call
            "supports_partial_context": True,  # Can handle missing merit
            "deterministic": True  # Same merit -> same result
        }

    def get_metadata(self) -> Dict[str, Any]:
        """Get resolver metadata."""
        return {
            **super().get_metadata(),
            "config_schema": {
                "merit_weights": {
                    "type": "dict",
                    "default": {
                        "domain_merit": 0.4,
                        "overall_merit": 0.3,
                        "recent_performance": 0.3
                    },
                    "description": "Weights for merit components"
                },
                "auto_resolve_threshold": {
                    "type": "float",
                    "default": 0.85,
                    "description": "Confidence for auto-resolve (0-1)"
                },
                "escalation_threshold": {
                    "type": "float",
                    "default": 0.5,
                    "description": "Confidence for escalation (0-1)"
                },
                "recency_decay_days": {
                    "type": "int",
                    "default": 30,
                    "description": "Days for 50% merit decay"
                }
            }
        }


class HumanEscalationResolver(ConflictResolver):
    """Human escalation resolver (placeholder for M3).

    Escalates conflicts to human for manual resolution.
    In M3, returns error prompting human intervention.
    In M4+, will integrate with approval workflow system.
    """

    def resolve(
        self,
        conflict: Conflict,
        context: ResolutionContext
    ) -> Resolution:
        """Escalate to human.

        Args:
            conflict: Conflict requiring human input
            context: Resolution context

        Returns:
            Resolution indicating human escalation needed

        Raises:
            RuntimeError: Always (requires human intervention)
        """
        # Build escalation message
        decision_summary = ", ".join(
            f"'{d}'" for d in conflict.decisions[:3]  # Limit to 3
        )

        message = (
            f"Conflict requires human resolution. "
            f"Agents: {', '.join(conflict.agents[:5])} disagree on: {decision_summary}. "
            f"Disagreement severity: {conflict.disagreement_score:.1%}."
        )

        raise RuntimeError(
            f"Human escalation required: {message}"
        )

    def get_capabilities(self) -> Dict[str, bool]:
        """Get resolver capabilities."""
        return {
            "requires_merit": False,
            "requires_human": True,
            "requires_llm": False,
            "supports_partial_context": True,
            "deterministic": False  # Human decisions vary
        }
```

---

## Test Strategy

### Unit Tests (`tests/test_strategies/test_merit_weighted.py`)

```python
import pytest
from src.strategies.merit_weighted import MeritWeightedResolver, HumanEscalationResolver
from src.strategies.conflict_resolution import AgentMerit, ResolutionContext
from src.strategies.base import Conflict, AgentOutput


def test_equal_merit_equal_votes():
    """Test with equal merit (equivalent to simple voting)."""
    resolver = MeritWeightedResolver()

    # Two agents, equal merit, different decisions
    merit_a = AgentMerit("a", 0.8, 0.8, 0.8, "intermediate")
    merit_b = AgentMerit("b", 0.8, 0.8, 0.8, "intermediate")

    output_a = AgentOutput("a", "Option A", "reason", 0.9, {})
    output_b = AgentOutput("b", "Option B", "reason", 0.9, {})

    conflict = Conflict(["a", "b"], ["Option A", "Option B"], 0.5, {})
    context = ResolutionContext(
        agent_merits={"a": merit_a, "b": merit_b},
        agent_outputs={"a": output_a, "b": output_b},
        stage_name="test",
        workflow_name="test",
        workflow_config={},
        previous_resolutions=[]
    )

    resolution = resolver.resolve(conflict, context)

    # Should pick one (tie-break by implementation detail)
    assert resolution.decision in ["Option A", "Option B"]
    assert 0.4 < resolution.confidence < 0.6  # Close vote


def test_high_merit_disparity():
    """Test with expert vs novice (merit matters)."""
    resolver = MeritWeightedResolver()

    # Expert (0.9 merit) vs Novice (0.6 merit)
    merit_expert = AgentMerit("expert", 0.9, 0.85, 0.9, "expert")
    merit_novice = AgentMerit("novice", 0.6, 0.65, 0.6, "novice")

    output_expert = AgentOutput("expert", "Option A", "reason", 0.9, {})
    output_novice = AgentOutput("novice", "Option B", "reason", 0.8, {})

    conflict = Conflict(["expert", "novice"], ["Option A", "Option B"], 0.5, {})
    context = ResolutionContext(
        agent_merits={"expert": merit_expert, "novice": merit_novice},
        agent_outputs={"expert": output_expert, "novice": output_novice},
        stage_name="test",
        workflow_name="test",
        workflow_config={},
        previous_resolutions=[]
    )

    resolution = resolver.resolve(conflict, context)

    # Expert should win
    assert resolution.decision == "Option A"
    assert resolution.confidence > 0.6  # Expert's higher merit


def test_auto_resolve_threshold():
    """Test auto-resolve when confidence high."""
    resolver = MeritWeightedResolver({"auto_resolve_threshold": 0.85})

    # 3 high-merit agents agree
    merit = AgentMerit("a", 0.9, 0.9, 0.9, "expert")

    outputs = {
        f"a{i}": AgentOutput(f"a{i}", "Option A", "reason", 0.9, {})
        for i in range(3)
    }

    conflict = Conflict(list(outputs.keys()), ["Option A"], 0.0, {})
    context = ResolutionContext(
        agent_merits={k: merit for k in outputs.keys()},
        agent_outputs=outputs,
        stage_name="test",
        workflow_name="test",
        workflow_config={},
        previous_resolutions=[]
    )

    resolution = resolver.resolve(conflict, context)

    assert resolution.method == "merit_weighted_auto"
    assert resolution.metadata["auto_resolved"] is True
    assert resolution.confidence >= 0.85


def test_escalation_threshold():
    """Test escalation when confidence low."""
    resolver = MeritWeightedResolver({"escalation_threshold": 0.5})

    # 3 agents, all disagree, low confidence
    merits = {
        f"a{i}": AgentMerit(f"a{i}", 0.5, 0.5, 0.5, "novice")
        for i in range(3)
    }

    outputs = {
        "a0": AgentOutput("a0", "Option A", "reason", 0.6, {}),
        "a1": AgentOutput("a1", "Option B", "reason", 0.6, {}),
        "a2": AgentOutput("a2", "Option C", "reason", 0.6, {})
    }

    conflict = Conflict(list(outputs.keys()), list(outputs.keys()), 0.8, {})
    context = ResolutionContext(
        agent_merits=merits,
        agent_outputs=outputs,
        stage_name="test",
        workflow_name="test",
        workflow_config={},
        previous_resolutions=[]
    )

    resolution = resolver.resolve(conflict, context)

    assert resolution.confidence < 0.5
    assert resolution.metadata["needs_review"] is True


def test_missing_merit_handling():
    """Test graceful handling of missing merit data."""
    resolver = MeritWeightedResolver()

    # One agent missing merit
    merit_a = AgentMerit("a", 0.8, 0.8, 0.8, "intermediate")

    output_a = AgentOutput("a", "Option A", "reason", 0.9, {})
    output_b = AgentOutput("b", "Option B", "reason", 0.9, {})

    conflict = Conflict(["a", "b"], ["Option A", "Option B"], 0.5, {})
    context = ResolutionContext(
        agent_merits={"a": merit_a},  # Missing "b"
        agent_outputs={"a": output_a, "b": output_b},
        stage_name="test",
        workflow_name="test",
        workflow_config={},
        previous_resolutions=[]
    )

    # Should handle gracefully (skip agent with missing merit)
    resolution = resolver.resolve(conflict, context)
    assert resolution.decision in ["Option A", "Option B"]


def test_human_escalation_resolver():
    """Test human escalation resolver."""
    resolver = HumanEscalationResolver()

    conflict = Conflict(["a", "b"], ["Option A", "Option B"], 0.8, {})
    context = ResolutionContext(
        agent_merits={},
        agent_outputs={},
        stage_name="test",
        workflow_name="test",
        workflow_config={},
        previous_resolutions=[]
    )

    # Should raise RuntimeError
    with pytest.raises(RuntimeError, match="Human escalation required"):
        resolver.resolve(conflict, context)


def test_capabilities():
    """Test resolver capabilities."""
    resolver = MeritWeightedResolver()
    caps = resolver.get_capabilities()

    assert caps["requires_merit"] is True
    assert caps["requires_human"] is False
    assert caps["deterministic"] is True
```

---

## Success Metrics

- [ ] File created: `src/strategies/merit_weighted.py`
- [ ] All tests pass: `pytest tests/test_strategies/test_merit_weighted.py -v`
- [ ] Code coverage >85%
- [ ] Merit weighting demonstrably affects outcomes
- [ ] Auto-resolve and escalation thresholds work correctly
- [ ] Integration with M1 observability merit tracking

---

## Dependencies

**Blocked by:**
- m3-01-collaboration-strategy-interface (needs base types)
- m3-02-conflict-resolution-interface (needs ConflictResolver ABC)

**Blocks:**
- m3-09-synthesis-node (needs resolver for conflict handling)

**Integrates with:**
- M1 observability database (agent merit tracking)

---

## Design References

- [Vision Document - Merit-Based Collaboration](../../META_AUTONOMOUS_FRAMEWORK_VISION.md#why-merit-based-collaboration-matters)
- [M1 Observability Schema](./m1-01-observability-db.md)

---

## Notes

**Why Merit-Weighted Resolution:**
- Prevents "tyranny of the majority" (quantity ≠ quality)
- Rewards agent performance with influence
- Enables continuous learning (merit evolves)
- Aligns with human expert systems (domain expertise matters)

**Design Decisions:**
- Composite merit score (domain + overall + recent)
- Configurable thresholds (different risk tolerances)
- Graceful degradation (missing merit → skip agent)
- Transparency (log all weights for audit)

**Critical:**
- Merit must be fair and auditable
- Time decay prevents stale merit dominance
- Confidence thresholds prevent bad auto-resolves
- Integration with M1 observability is essential

**Future Enhancements (M4+):**
- Merit learning from resolution outcomes
- Dynamic weight adjustment (optimize over time)
- Human escalation workflow integration
- Multi-criteria merit (speed, cost, quality)
