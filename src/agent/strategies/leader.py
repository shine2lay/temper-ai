"""Leader-based collaboration strategy.

Implements the "perspectives + decision-maker" pattern in a single stage:
1. Non-leader agents run in parallel (perspectives)
2. Leader agent runs alone with all perspective outputs injected
3. Leader's output becomes the SynthesisResult

This replaces the two-stage pattern of separate perspectives + decider stages.

Config Example:
    collaboration:
      strategy: leader
      config:
        leader_agent: vcs_triage_decider
        fallback_to_consensus: true
"""

import logging
from typing import Any, Dict, List, Optional

from src.agent.strategies.base import (
    AgentOutput,
    CollaborationStrategy,
    SynthesisMethod,
    SynthesisResult,
    calculate_consensus_confidence,
    calculate_vote_distribution,
    extract_majority_decision,
)
from src.agent.strategies.constants import CONFIG_KEY_LEADER_AGENT

logger = logging.getLogger(__name__)

SEPARATOR_WIDTH = 40

# Separator for formatting team outputs
TEAM_OUTPUT_SEPARATOR = "-" * SEPARATOR_WIDTH


class LeaderCollaborationStrategy(CollaborationStrategy):
    """Leader-based collaboration: perspectives + leader decision in one stage.

    Non-leader agents provide independent perspectives. The leader agent
    receives all perspectives and makes the final decision. If the leader
    fails, falls back to consensus on perspective outputs.

    Configuration:
        leader_agent (str): Name of the leader agent (required)
        fallback_to_consensus (bool): Fall back to consensus if leader
            output is missing (default: True)
    """

    def __init__(
        self,
        leader_agent: Optional[str] = None,
        fallback_to_consensus: bool = True,
        **kwargs: Any,
    ) -> None:
        self._leader_agent = leader_agent
        self._fallback_to_consensus = fallback_to_consensus

    @property
    def requires_requery(self) -> bool:
        """Leader strategy does not require multi-round re-invocation."""
        return False

    @property
    def requires_leader_synthesis(self) -> bool:
        """Leader strategy requires leader-specific synthesis path."""
        return True

    def get_leader_agent_name(self, config: Dict[str, Any]) -> Optional[str]:
        """Extract leader agent name from collaboration config.

        Uses the config argument if provided, otherwise falls back
        to the value stored at construction time.

        Args:
            config: Collaboration config dict (the 'config' sub-key)

        Returns:
            Leader agent name, or None if not configured
        """
        return config.get(CONFIG_KEY_LEADER_AGENT, self._leader_agent)

    def format_team_outputs(
        self, agent_outputs: List[AgentOutput]
    ) -> str:
        """Format perspective outputs as structured text for leader prompt injection.

        Creates a formatted string of all perspective agent outputs that gets
        injected into the leader's prompt via the ``{{ team_outputs }}`` variable.

        Args:
            agent_outputs: Outputs from perspective (non-leader) agents

        Returns:
            Formatted string with each agent's name, confidence, and output
        """
        if not agent_outputs:
            return "(No team outputs available)"

        sections: List[str] = []
        for output in agent_outputs:
            section = (
                f"## {output.agent_name} (confidence: {output.confidence:.0%})\n"
                f"{output.decision}\n"
                f"\nReasoning: {output.reasoning}"
            )
            sections.append(section)

        return ("\n" + TEAM_OUTPUT_SEPARATOR + "\n").join(sections)

    def synthesize(
        self,
        agent_outputs: List[AgentOutput],
        config: Dict[str, Any],
    ) -> SynthesisResult:
        """Synthesize outputs using leader's decision.

        If leader output is present, uses it as the final decision.
        If leader output is missing and fallback_to_consensus is True,
        falls back to consensus on non-leader outputs.

        Args:
            agent_outputs: All agent outputs (perspectives + leader)
            config: Strategy config with leader_agent and fallback_to_consensus

        Returns:
            SynthesisResult with leader's decision or consensus fallback
        """
        self.validate_inputs(agent_outputs)

        leader_name = self.get_leader_agent_name(config)
        fallback = config.get(
            "fallback_to_consensus", self._fallback_to_consensus
        )

        # Separate leader and perspective outputs
        leader_output = None
        perspective_outputs: List[AgentOutput] = []

        for output in agent_outputs:
            if leader_name and output.agent_name == leader_name:
                leader_output = output
            else:
                perspective_outputs.append(output)

        # Leader found: use leader's decision
        if leader_output is not None:
            return SynthesisResult(
                decision=leader_output.decision,
                confidence=leader_output.confidence,
                method=SynthesisMethod.HIERARCHICAL.value,
                votes={leader_output.decision: 1},
                conflicts=self.detect_conflicts(agent_outputs),
                reasoning=(
                    f"Leader '{leader_name}' decided after reviewing "
                    f"{len(perspective_outputs)} perspective(s). "
                    f"Reasoning: {leader_output.reasoning}"
                ),
                metadata={
                    "leader_agent": leader_name,
                    "perspective_count": len(perspective_outputs),
                    "perspective_agents": [
                        o.agent_name for o in perspective_outputs
                    ],
                },
            )

        # Leader not found: fallback or error
        if not fallback:
            raise ValueError(
                f"Leader agent '{leader_name}' not found in outputs "
                f"and fallback_to_consensus is disabled"
            )

        logger.warning(
            "Leader agent '%s' output not found; falling back to consensus "
            "on %d perspective outputs",
            leader_name,
            len(perspective_outputs),
        )

        return self._consensus_fallback(perspective_outputs, leader_name)

    def _consensus_fallback(
        self,
        perspective_outputs: List[AgentOutput],
        leader_name: Optional[str],
    ) -> SynthesisResult:
        """Fall back to consensus when leader output is unavailable.

        Args:
            perspective_outputs: Non-leader agent outputs
            leader_name: Name of the missing leader agent

        Returns:
            SynthesisResult using consensus method
        """
        if not perspective_outputs:
            return SynthesisResult(
                decision="",
                confidence=0.0,
                method="leader_fallback_consensus",
                votes={},
                conflicts=[],
                reasoning="No outputs available for consensus fallback",
                metadata={"leader_agent": leader_name, "fallback": True},
            )

        decision = extract_majority_decision(perspective_outputs)
        votes = calculate_vote_distribution(perspective_outputs)

        if decision is not None:
            confidence = calculate_consensus_confidence(
                perspective_outputs, decision
            )
        else:
            # Tie — pick first decision, low confidence
            decision = perspective_outputs[0].decision
            confidence = 1.0 / len(perspective_outputs)

        return SynthesisResult(
            decision=decision,
            confidence=confidence,
            method="leader_fallback_consensus",
            votes=votes,
            conflicts=self.detect_conflicts(perspective_outputs),
            reasoning=(
                f"Leader '{leader_name}' unavailable; consensus fallback "
                f"from {len(perspective_outputs)} perspective(s)."
            ),
            metadata={
                "leader_agent": leader_name,
                "fallback": True,
                "perspective_count": len(perspective_outputs),
            },
        )

    def get_capabilities(self) -> Dict[str, bool]:
        """Get strategy capabilities for feature detection."""
        return {
            "supports_debate": False,
            "supports_convergence": False,
            "supports_merit_weighting": False,
            "supports_partial_participation": True,
            "supports_async": False,
            "deterministic": True,
            "requires_leader": True,
        }

    def get_metadata(self) -> Dict[str, Any]:
        """Get strategy metadata for introspection."""
        return {
            **super().get_metadata(),
            "config_schema": {
                "leader_agent": {
                    "type": "str",
                    "required": True,
                    "description": "Name of the leader agent",
                },
                "fallback_to_consensus": {
                    "type": "bool",
                    "default": True,
                    "description": (
                        "Fall back to consensus if leader output is missing"
                    ),
                },
            },
        }
