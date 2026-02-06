"""Merit-weighted conflict resolution strategy.

Resolves conflicts by weighting votes based on agent merit:
- Domain expertise in current task
- Overall success rate
- Recent performance (time-decayed)

Higher-merit agents have more influence in close decisions.
"""

from typing import Any, Dict, List, Optional

from src.strategies.base import AgentOutput, Conflict
from src.strategies.conflict_resolution import (
    AgentMerit,
    ConflictResolver,
    Resolution,
    ResolutionContext,
    ResolutionResult,
    calculate_merit_weighted_votes,
    get_highest_weighted_decision,
)


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
        >>> resolution = resolver.resolve_with_context(conflict, context)
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

    def resolve_with_context(
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
        winning_agents: List[str],
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

    # Backward-compatible resolve method (old API)
    def resolve(self, conflict: Conflict, agent_outputs: List[AgentOutput], config: Dict[str, Any]) -> ResolutionResult:
        """Backward-compatible resolve method.

        Uses confidence as merit proxy since full merit tracking is in M4.
        """
        # Create minimal context from agent_outputs
        agent_merits = {}
        agent_output_dict = {}

        for output in agent_outputs:
            # Use confidence as merit proxy
            agent_merits[output.agent_name] = AgentMerit(
                agent_name=output.agent_name,
                domain_merit=output.confidence,
                overall_merit=output.confidence,
                recent_performance=output.confidence,
                expertise_level="unknown"
            )
            agent_output_dict[output.agent_name] = output

        context = ResolutionContext(
            agent_merits=agent_merits,
            agent_outputs=agent_output_dict,
            stage_name="unknown",
            workflow_name="unknown",
            workflow_config=config,
            previous_resolutions=[]
        )

        resolution = self.resolve_with_context(conflict, context)

        # Convert Resolution to ResolutionResult for backward compatibility
        from src.strategies.conflict_resolution import ResolutionResult
        return ResolutionResult(
            decision=resolution.decision,
            method=resolution.method,
            reasoning=resolution.reasoning,
            success=not resolution.metadata.get("needs_review", False),
            confidence=resolution.confidence,
            metadata=resolution.metadata
        )

    def get_capabilities(self) -> Dict[str, bool]:
        """Get resolver capabilities."""
        return {
            "requires_merit": True,  # Needs merit scores
            "requires_human": False,  # Can auto-resolve
            "requires_llm": False,  # No LLM call
            "supports_partial_context": True,  # Can handle missing merit
            "deterministic": True,  # Same merit -> same result
            "supports_negotiation": False,
            "supports_escalation": True,
            "supports_merit_weighting": True,
            "supports_iterative": False
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

    def resolve_with_context(
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

    def resolve(self, conflict: Conflict, agent_outputs: List[AgentOutput], config: Dict[str, Any]) -> ResolutionResult:
        """Backward-compatible resolve method."""
        # Create minimal context
        context = ResolutionContext(
            agent_merits={},
            agent_outputs={},
            stage_name="unknown",
            workflow_name="unknown",
            workflow_config=config,
            previous_resolutions=[]
        )
        resolution = self.resolve_with_context(conflict, context)

        # Convert Resolution to ResolutionResult for backward compatibility
        return ResolutionResult(
            decision=resolution.decision,
            method=resolution.method,
            reasoning=resolution.reasoning,
            success=True,
            confidence=resolution.confidence,
            metadata=resolution.metadata
        )

    def get_capabilities(self) -> Dict[str, bool]:
        """Get resolver capabilities."""
        return {
            "requires_merit": False,
            "requires_human": True,
            "requires_llm": False,
            "supports_partial_context": True,
            "deterministic": False,  # Human decisions vary
            "supports_negotiation": False,
            "supports_escalation": True,
            "supports_merit_weighting": False,
            "supports_iterative": False
        }
