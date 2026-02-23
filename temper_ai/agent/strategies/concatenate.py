"""Concatenation strategy for independent parallel agents.

Joins all agent outputs into a single string, separated by agent name headers.
Unlike consensus (which votes) or leader (which picks one), this strategy
preserves ALL outputs — ideal for parallel workers doing complementary tasks
(e.g., 3 coders each writing different files).

When an agent's text output is empty (common for tool-heavy agents that write
files via FileWriter/Bash), the strategy falls back to using the agent's
reasoning field or notes the agent produced no text summary.
"""

import logging
from typing import Any

from temper_ai.agent.strategies.base import (
    AgentOutput,
    CollaborationStrategy,
    SynthesisResult,
)

logger = logging.getLogger(__name__)

SEPARATOR = "\n\n---\n\n"
CONFIDENCE_FULL = 1.0
STRATEGY_NAME = "concatenate"


class ConcatenateStrategy(CollaborationStrategy):
    """Concatenates independent agent outputs into a single combined result.

    Designed for parallel stages where agents do complementary (non-overlapping)
    work. No voting, no conflict resolution — just merge all outputs.

    Example:
        >>> outputs = [
        ...     AgentOutput("coder_a", "Created models.py", "foundation", 0.9, {}),
        ...     AgentOutput("coder_b", "Created routes.py", "backend", 0.8, {}),
        ... ]
        >>> strategy = ConcatenateStrategy()
        >>> result = strategy.synthesize(outputs, {})
        >>> "coder_a" in result.decision
        True
    """

    def synthesize(
        self,
        agent_outputs: list[AgentOutput],
        config: dict[str, Any],
    ) -> SynthesisResult:
        """Concatenate all agent outputs into a single decision string.

        Args:
            agent_outputs: Outputs from all participating agents.
            config: Strategy configuration (unused for concatenation).

        Returns:
            SynthesisResult with all outputs joined, confidence 1.0, no conflicts.
        """
        self.validate_inputs(agent_outputs)

        parts: list[str] = []
        agent_contributions: dict[str, int] = {}

        for ao in agent_outputs:
            text = _extract_useful_text(ao)
            agent_contributions[ao.agent_name] = len(text)
            parts.append(f"[{ao.agent_name}]\n{text}")

        combined = SEPARATOR.join(parts)

        empty_agents = [
            name for name, length in agent_contributions.items() if length == 0
        ]
        if empty_agents:
            logger.warning(
                "Concatenate strategy: agents with empty output: %s",
                empty_agents,
            )

        avg_confidence = (
            sum(ao.confidence for ao in agent_outputs) / len(agent_outputs)
            if agent_outputs
            else CONFIDENCE_FULL
        )

        return SynthesisResult(
            decision=combined,
            confidence=avg_confidence,
            method=STRATEGY_NAME,
            votes=agent_contributions,
            conflicts=[],
            reasoning=f"Concatenated {len(agent_outputs)} independent agent outputs",
            metadata={
                "agent_count": len(agent_outputs),
                "empty_agents": empty_agents,
                "total_chars": len(combined),
            },
        )

    def get_capabilities(self) -> dict[str, bool]:
        """Return capabilities — concatenation is simple, no debate/convergence."""
        return {
            "supports_debate": False,
            "supports_convergence": False,
            "supports_merit_weighting": False,
            "supports_partial_participation": True,
            "supports_async": False,
            "supports_streaming": False,
        }

    def get_metadata(self) -> dict[str, Any]:
        """Return strategy metadata for registry introspection."""
        return {
            "description": (
                "Concatenates independent agent outputs. "
                "Ideal for parallel workers doing complementary tasks."
            ),
            "config_schema": {},
        }


def _extract_useful_text(ao: AgentOutput) -> str:
    """Extract the most useful text from an agent output.

    Priority: decision text > reasoning > empty-notice.
    """
    decision_text = str(ao.decision).strip() if ao.decision else ""
    if decision_text:
        return decision_text

    # Fallback to reasoning if decision is empty (tool-heavy agents)
    reasoning_text = str(ao.reasoning).strip() if ao.reasoning else ""
    if reasoning_text:
        return f"(no summary — reasoning: {reasoning_text})"

    return "(no text output produced)"
