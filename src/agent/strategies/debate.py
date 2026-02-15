"""Debate-based collaboration strategy — backward-compat shim.

Deprecated: Use MultiRoundStrategy(mode='debate') directly.

This module now re-exports MultiRoundStrategy as DebateAndSynthesize
for backward compatibility. The old simulated-debate behavior (same outputs
across rounds, comment at line 171 of the original) has been replaced with
real multi-round agent re-invocation via MultiRoundStrategy.
"""

import warnings
from typing import Any, Dict, List

from src.agent.strategies.base import AgentOutput, SynthesisResult
from src.agent.strategies.multi_round import (
    CommunicationHistory,
    CommunicationRound,
    MultiRoundStrategy,
)

# Re-export aliases for backward compatibility
DebateRound = CommunicationRound
DebateHistory = CommunicationHistory


class DebateAndSynthesize(MultiRoundStrategy):
    """Deprecated. Use MultiRoundStrategy(mode='debate').

    This class is a thin wrapper that defaults to debate mode.
    All behavior is provided by MultiRoundStrategy.

    Breaking change: Previously had requires_requery=False (simulated debate
    without re-invoking agents). Now inherits requires_requery=True from
    MultiRoundStrategy. This is intentional — the old behavior was broken
    (agents were never re-invoked, same outputs reused across rounds).
    """

    def __init__(self, **kwargs: Any) -> None:
        warnings.warn(
            "DebateAndSynthesize is deprecated, use MultiRoundStrategy(mode='debate')",
            DeprecationWarning,
            stacklevel=2,
        )
        kwargs.setdefault("mode", "debate")
        super().__init__(**kwargs)

    def synthesize(
        self,
        agent_outputs: List[AgentOutput],
        config: Dict[str, Any],
    ) -> SynthesisResult:
        """Synthesize agent outputs.

        Accepts both old-style config dict (with max_rounds, convergence_threshold)
        and new-style (empty, since config is on constructor).
        """
        result = super().synthesize(agent_outputs, config)
        # Preserve the old method name for compatibility
        if result.method != "debate_and_synthesize":
            result.method = "debate_and_synthesize"
        return result

    def get_capabilities(self) -> Dict[str, bool]:
        """Get capabilities, including legacy keys."""
        caps = super().get_capabilities()
        # Add legacy capability keys
        caps["deterministic"] = False
        caps["requires_conflict_resolver"] = True
        return caps
