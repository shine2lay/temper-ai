"""Stage-specific protocol definitions for structural typing.

Replaces hasattr-based duck typing with isinstance-checkable protocols
for collaboration strategies, synthesis coordinators, and quality gate
validators used across stage executors.
"""
from typing import Any, Dict, Optional, Protocol, runtime_checkable


@runtime_checkable
class SynthesisCoordinatorProtocol(Protocol):
    """Protocol for synthesis coordination in parallel execution."""

    def synthesize(
        self,
        agent_outputs: list,
        stage_config: Any,
        stage_name: str,
    ) -> Any:
        """Synthesize agent outputs into a single result."""
        ...


@runtime_checkable
class QualityGateValidatorProtocol(Protocol):
    """Protocol for quality gate validation."""

    def validate(
        self,
        synthesis_result: Any,
        stage_config: Any,
        stage_name: str,
    ) -> tuple:
        """Validate synthesis result against quality gates.

        Returns:
            Tuple of (passed: bool, violations: list[str])
        """
        ...


@runtime_checkable
class LeaderCapableStrategy(Protocol):
    """Protocol for strategies that use leader-based synthesis."""

    requires_leader_synthesis: bool

    def get_leader_agent_name(self, config: Dict[str, Any]) -> Optional[str]:
        """Get the leader agent name from collaboration config."""
        ...

    def format_team_outputs(self, outputs: list) -> str:
        """Format team outputs as structured text for leader prompt."""
        ...


@runtime_checkable
class DialogueCapableStrategy(Protocol):
    """Protocol for strategies that use multi-round dialogue."""

    requires_requery: bool
    max_rounds: int
    min_rounds: int
    convergence_threshold: float
    cost_budget_usd: Optional[float]
    mode: str

    def synthesize(self, agent_outputs: list, config: Dict[str, Any]) -> Any:
        """Synthesize agent outputs."""
        ...

    def calculate_convergence(
        self, current: list, previous: list,
    ) -> float:
        """Calculate convergence score between round outputs."""
        ...


@runtime_checkable
class StanceCuratingStrategy(Protocol):
    """Protocol for strategies that curate dialogue history per agent."""

    def curate_dialogue_history(
        self,
        dialogue_history: list,
        current_round: int,
        agent_name: str,
    ) -> list:
        """Curate dialogue history for a specific agent and round."""
        ...

    def get_round_context(
        self, round_num: int, agent_name: str,
    ) -> Dict[str, Any]:
        """Get mode-specific context for a dialogue round."""
        ...

    def extract_stances(
        self,
        outputs: list,
        llm_providers: Dict[str, Any],
    ) -> Dict[str, str]:
        """Extract agent stances from outputs."""
        ...
