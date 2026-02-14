"""Base interface for stage executors.

Defines the contract that all stage execution strategies must implement,
plus the ParallelRunner abstraction for engine-agnostic parallel execution,
and shared methods for synthesis, dialogue, and agent name extraction.
"""
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from typing_extensions import TypedDict

if TYPE_CHECKING:
    from src.compiler.executors._base_helpers import DialogueReinvocationParams

from src.compiler.constants import ERROR_MSG_FOR_STAGE_SUFFIX
from src.compiler.domain_state import (
    ConfigLoaderProtocol,
    DomainToolRegistryProtocol,
    TrackerProtocol,
    VisualizerProtocol,
)
from src.compiler.executors._base_helpers import (
    execute_dialogue_round,
    fallback_consensus_synthesis,
    invoke_leader_agent,
    reinvoke_agents_with_dialogue,
    track_dialogue_round,
)
from src.compiler.executors.state_keys import StateKeys

logger = logging.getLogger(__name__)


@dataclass
class FinalSynthesisResultParams:
    """Parameters for building final synthesis result (reduces 8 params to 7)."""
    strategy: Any
    current_outputs: list
    final_round: int
    total_cost: float
    dialogue_history: List[Dict[str, Any]]
    converged: bool
    convergence_round: int
    stage_name: str


def _run_dialogue_rounds(
    executor: Any,
    strategy: Any,
    agents: list,
    stage_name: str,
    state: Dict[str, Any],
    config_loader: ConfigLoaderProtocol,
    tracker: Any,
    dialogue_history: List[Dict[str, Any]],
    initial_outputs: list,
    total_cost: float,
) -> tuple:
    """Run dialogue rounds until convergence, budget, or max rounds.

    Returns:
        (final_round, current_outputs, total_cost, converged, convergence_round)
    """
    previous_outputs = initial_outputs
    current_outputs = initial_outputs
    converged = False
    convergence_round = -1
    final_round = 0

    for round_num in range(1, strategy.max_rounds):
        final_round = round_num
        from src.compiler.executors._base_helpers import DialogueRoundParams
        round_params = DialogueRoundParams(
            round_num=round_num, reinvoke_fn=executor._reinvoke_agents_with_dialogue,
            agents=agents, strategy=strategy, stage_name=stage_name,
            state=state, config_loader=config_loader, tracker=tracker,
            dialogue_history=dialogue_history, previous_outputs=previous_outputs,
        )
        outputs, cost, _, conv, conv_round, _ = execute_dialogue_round(round_params)
        current_outputs = outputs
        total_cost += cost
        if conv:
            converged = True
            convergence_round = conv_round
            break
        if strategy.cost_budget_usd and total_cost >= strategy.cost_budget_usd:
            logger.warning(
                f"Dialogue stopped at round {round_num + 1} for stage '{stage_name}': "
                f"budget ${strategy.cost_budget_usd:.2f} reached (cost: ${total_cost:.2f})"
            )
            break
        previous_outputs = current_outputs

    return final_round, current_outputs, total_cost, converged, convergence_round


def _record_initial_round(
    current_outputs: list,
    dialogue_history: List[Dict[str, Any]]
) -> float:
    """Record initial round outputs in dialogue history.

    Returns:
        Total cost from initial outputs
    """
    total_cost = 0.0
    for output in current_outputs:
        dialogue_history.append({
            "agent": output.agent_name,
            "round": 0,
            StateKeys.OUTPUT: output.decision,
            StateKeys.REASONING: output.reasoning,
            StateKeys.CONFIDENCE: output.confidence,
        })
        total_cost += output.metadata.get(StateKeys.COST_USD, 0.0)
    return total_cost


def _build_final_synthesis_result(params: FinalSynthesisResultParams) -> Any:
    """Build final synthesis result with metadata."""
    result = params.strategy.synthesize(params.current_outputs, {})
    result.metadata["dialogue_rounds"] = params.final_round + 1
    result.metadata["total_cost_usd"] = params.total_cost
    result.metadata["dialogue_history"] = params.dialogue_history
    result.metadata["converged"] = params.converged

    if params.converged:
        result.metadata["convergence_round"] = params.convergence_round
        result.metadata["early_stop_reason"] = "convergence"
    elif params.strategy.cost_budget_usd and params.total_cost >= params.strategy.cost_budget_usd:
        result.metadata["early_stop_reason"] = "budget"
    else:
        result.metadata["early_stop_reason"] = "max_rounds"

    logger.info(
        f"Dialogue completed{ERROR_MSG_FOR_STAGE_SUFFIX}{params.stage_name}': "
        f"{params.final_round + 1} rounds, ${params.total_cost:.2f} cost, "
        f"converged: {params.converged}, "
        f"reason: {result.metadata['early_stop_reason']}"
    )

    return result


class WorkflowStateDict(TypedDict, total=False):
    """Canonical type hints for the workflow state dictionary.

    This is the single authoritative definition of the workflow state dict
    used throughout the framework. All other modules should import from here.

    All keys are optional (total=False) since different executors and
    lifecycle phases populate different subsets of the state.
    """

    # Core workflow identity
    workflow_id: str
    current_stage: str

    # Accumulated stage outputs: stage_name -> stage output dict
    stage_outputs: Dict[str, Any]

    # Arbitrary user-supplied workflow inputs (survives LangGraph dataclass coercion)
    workflow_inputs: Dict[str, Any]

    # Common workflow inputs
    topic: Optional[str]
    depth: Optional[str]
    focus_areas: Optional[List[str]]
    query: Optional[str]
    input: Optional[str]
    context: Optional[str]
    data: Any

    # Infrastructure (non-serializable)
    tracker: Optional[TrackerProtocol]
    tool_registry: Optional[DomainToolRegistryProtocol]
    config_loader: Optional[ConfigLoaderProtocol]
    visualizer: Optional[VisualizerProtocol]

    # Server / isolation
    workspace_root: Optional[str]
    run_id: Optional[str]

    # UI/display
    show_details: bool
    detail_console: Any  # Rich Console or None
    stream_callback: Optional[Any]  # StreamCallback or None

    # Quality gate retry tracking (parallel executor)
    stage_retry_counts: Dict[str, int]

    # Parallel executor internal state
    agent_outputs: Dict[str, Any]
    agent_statuses: Dict[str, Any]
    agent_metrics: Dict[str, Any]
    errors: Dict[str, Any]
    stage_input: Dict[str, Any]


class ParallelRunner(ABC):
    """Abstraction for running nodes in parallel.

    Encapsulates the "build graph, compile, invoke" pattern so executors
    don't need to import a specific graph engine (e.g., LangGraph).
    """

    @abstractmethod
    def run_parallel(
        self,
        nodes: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]],
        initial_state: Dict[str, Any],
        *,
        init_node: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
        collect_node: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Execute nodes in parallel and return collected results.

        Args:
            nodes: Mapping of node_name -> callable for parallel execution.
            initial_state: Starting state for the graph.
            init_node: Optional initialization callable (runs before parallel nodes).
            collect_node: Optional collection callable (runs after all parallel nodes).

        Returns:
            Final state after all nodes have completed.
        """
        pass


class StageExecutor(ABC):
    """Base class for stage execution strategies.

    Each executor implements a specific execution mode:
    - Sequential: Execute agents one after another
    - Parallel: Execute agents concurrently
    - Adaptive: Start parallel, switch to sequential if needed

    Provides shared methods for synthesis, dialogue, and agent name
    extraction used by all concrete executors.
    """

    @abstractmethod
    def execute_stage(
        self,
        stage_name: str,
        stage_config: Any,
        state: Dict[str, Any],
        config_loader: ConfigLoaderProtocol,
        tool_registry: Optional[DomainToolRegistryProtocol] = None
    ) -> Dict[str, Any]:
        """Execute stage and return updated state.

        Args:
            stage_name: Name of the stage being executed
            stage_config: Stage configuration (dict or Pydantic model)
            state: Current workflow state
            config_loader: ConfigLoader for loading agent configs
            tool_registry: ToolRegistry for agent tool access

        Returns:
            Updated workflow state with stage outputs

        Raises:
            RuntimeError: If stage execution fails
        """
        pass

    @abstractmethod
    def supports_stage_type(self, stage_type: str) -> bool:
        """Check if executor supports this stage type.

        Args:
            stage_type: Stage type identifier

        Returns:
            True if executor can handle this stage type
        """
        pass

    # ------------------------------------------------------------------
    # Shared helpers used by Sequential, Parallel, and Adaptive executors
    # ------------------------------------------------------------------

    def _extract_agent_name(self, agent_ref: Any) -> str:
        """Extract agent name from various agent reference formats.

        Delegates to shared utility function.

        Args:
            agent_ref: Agent reference (dict, str, or Pydantic model)

        Returns:
            Agent name
        """
        from src.compiler.utils import extract_agent_name
        return extract_agent_name(agent_ref)

    def _run_synthesis(
        self,
        agent_outputs: list,
        stage_config: Any,
        stage_name: str,
        state: Optional[Dict[str, Any]] = None,
        config_loader: Optional[ConfigLoaderProtocol] = None,
        agents: Optional[List] = None
    ) -> Any:
        """Run collaboration strategy to synthesize agent outputs.

        If a ``synthesis_coordinator`` attribute exists on the executor
        (e.g. ParallelStageExecutor), it is used for a fast-path
        delegation.  Otherwise falls back to strategy-registry lookup
        and, ultimately, simple majority-vote consensus.

        Args:
            agent_outputs: List of AgentOutput objects
            stage_config: Stage configuration
            stage_name: Stage name
            state: Workflow state (optional, for dialogue mode)
            config_loader: Config loader (optional, for dialogue mode)
            agents: List of agent refs (optional, for dialogue mode)

        Returns:
            SynthesisResult
        """
        # Fast-path: injected coordinator (used by ParallelStageExecutor)
        coordinator = getattr(self, 'synthesis_coordinator', None)
        if coordinator:
            return coordinator.synthesize(
                agent_outputs=agent_outputs,
                stage_config=stage_config,
                stage_name=stage_name
            )

        try:
            from src.strategies.registry import get_strategy_from_config

            strategy = get_strategy_from_config(stage_config)

            # Check if strategy requires leader-based synthesis
            if hasattr(strategy, 'requires_leader_synthesis') and strategy.requires_leader_synthesis:
                return self._run_leader_synthesis(
                    agent_outputs=agent_outputs,
                    strategy=strategy,
                    stage_config=stage_config,
                    stage_name=stage_name,
                    state=state,
                    config_loader=config_loader,
                    agents=agents,
                )

            # Check if strategy requires multi-round dialogue
            if hasattr(strategy, 'requires_requery') and strategy.requires_requery:
                if state is None or config_loader is None or agents is None:
                    logger.warning(
                        "Dialogue mode requires state, config_loader, and agents. "
                        "Falling back to one-shot synthesis."
                    )
                else:
                    return self._run_dialogue_synthesis(
                        initial_outputs=agent_outputs,
                        strategy=strategy,
                        stage_config=stage_config,
                        stage_name=stage_name,
                        state=state,
                        config_loader=config_loader,
                        agents=agents
                    )

            # One-shot synthesis
            stage_dict = stage_config if isinstance(stage_config, dict) else {}
            collaboration_config = stage_dict.get("collaboration", {}).get("config", {})
            return strategy.synthesize(agent_outputs, collaboration_config)

        except ImportError:
            return fallback_consensus_synthesis(agent_outputs)

    def _run_dialogue_synthesis(
        self,
        initial_outputs: list,
        strategy: Any,
        stage_config: Any,
        stage_name: str,
        state: Dict[str, Any],
        config_loader: ConfigLoaderProtocol,
        agents: list
    ) -> Any:
        """Execute multi-round dialogue with agent re-invocation.

        Includes convergence detection: once agent outputs stabilise
        beyond ``strategy.convergence_threshold`` after
        ``strategy.min_rounds``, the dialogue terminates early.
        """
        dialogue_history: List[Dict[str, Any]] = []
        current_outputs = initial_outputs
        total_cost = _record_initial_round(current_outputs, dialogue_history)
        tracker = state.get(StateKeys.TRACKER)
        from src.compiler.executors._base_helpers import DialogueTrackingParams
        track_params = DialogueTrackingParams(
            tracker=tracker, strategy=strategy, state=state,
            current_outputs=current_outputs, round_num=0, round_outcome="initial"
        )
        track_dialogue_round(track_params)

        if strategy.cost_budget_usd and total_cost >= strategy.cost_budget_usd:
            return self._budget_stop_result(strategy, current_outputs, total_cost, stage_name)

        final_round, current_outputs, total_cost, converged, convergence_round = (
            _run_dialogue_rounds(
                self, strategy, agents, stage_name, state, config_loader,
                tracker, dialogue_history, initial_outputs, total_cost,
            )
        )

        synth_params = FinalSynthesisResultParams(
            strategy=strategy, current_outputs=current_outputs, final_round=final_round,
            total_cost=total_cost, dialogue_history=dialogue_history,
            converged=converged, convergence_round=convergence_round,
            stage_name=stage_name
        )
        return _build_final_synthesis_result(synth_params)

    @staticmethod
    def _budget_stop_result(
        strategy: Any, current_outputs: list, total_cost: float, stage_name: str
    ) -> Any:
        """Return early synthesis result when budget is exhausted after round 0."""
        logger.warning(
            f"Dialogue stopped after round 0{ERROR_MSG_FOR_STAGE_SUFFIX}{stage_name}': "
            f"budget ${strategy.cost_budget_usd:.2f} reached "
            f"(cost: ${total_cost:.2f})"
        )
        result = strategy.synthesize(current_outputs, {})
        result.metadata["dialogue_rounds"] = 1
        result.metadata["total_cost_usd"] = total_cost
        result.metadata["early_stop_reason"] = "budget"
        return result

    def _run_leader_synthesis(
        self,
        agent_outputs: list,
        strategy: Any,
        stage_config: Any,
        stage_name: str,
        state: Optional[Dict[str, Any]] = None,
        config_loader: Optional[ConfigLoaderProtocol] = None,
        agents: Optional[List] = None,
    ) -> Any:
        """Execute leader-based synthesis: re-invoke leader with team outputs.

        The perspective agents have already run (their outputs are in
        agent_outputs). This method:
        1. Formats perspective outputs as structured text
        2. Re-invokes the leader agent with ``team_outputs`` in its input
        3. Calls strategy.synthesize() with all outputs (perspectives + leader)

        Falls back to consensus on perspective outputs if leader invocation fails.

        Args:
            agent_outputs: Outputs from perspective agents (round 0)
            strategy: LeaderCollaborationStrategy instance
            stage_config: Stage configuration dict
            stage_name: Name of the current stage
            state: Workflow state
            config_loader: Config loader for loading agent configs
            agents: List of agent refs from stage config

        Returns:
            SynthesisResult from leader or consensus fallback
        """
        # Extract collaboration config (handles nested "stage.collaboration.config"
        # and flat "collaboration.config" formats)
        stage_dict = stage_config if isinstance(stage_config, dict) else {}
        collab = stage_dict.get("collaboration")
        if collab is None:
            inner = stage_dict.get("stage", {})
            if isinstance(inner, dict):
                collab = inner.get("collaboration", {})
            else:
                collab = {}
        collaboration_config = collab.get("config", {}) if isinstance(collab, dict) else {}
        leader_name = strategy.get_leader_agent_name(collaboration_config)

        if not leader_name:
            logger.warning(
                "Leader strategy for stage '%s' has no leader_agent configured; "
                "falling back to consensus.",
                stage_name,
            )
            return strategy.synthesize(agent_outputs, collaboration_config)

        # Format perspective outputs for leader prompt injection
        team_outputs_text = strategy.format_team_outputs(agent_outputs)

        # Re-invoke the leader agent
        try:
            if state is None or config_loader is None:
                raise ValueError("state and config_loader required for leader synthesis")

            leader_output = self._invoke_leader_agent(
                leader_name=leader_name,
                team_outputs_text=team_outputs_text,
                stage_name=stage_name,
                state=state,
                config_loader=config_loader,
            )

            # Combine perspective + leader outputs and synthesize
            all_outputs = list(agent_outputs) + [leader_output]
            return strategy.synthesize(all_outputs, collaboration_config)

        except Exception as exc:
            logger.warning(
                "Leader agent '%s' failed for stage '%s': %s. "
                "Falling back to consensus on perspective outputs.",
                leader_name,
                stage_name,
                exc,
            )
            return strategy.synthesize(agent_outputs, collaboration_config)

    def _invoke_leader_agent(
        self,
        leader_name: str,
        team_outputs_text: str,
        stage_name: str,
        state: Dict[str, Any],
        config_loader: ConfigLoaderProtocol,
    ) -> Any:
        """Invoke the leader agent with team outputs injected."""
        return invoke_leader_agent(
            leader_name=leader_name,
            team_outputs_text=team_outputs_text,
            stage_name=stage_name,
            state=state,
            config_loader=config_loader,
        )

    def _reinvoke_agents_with_dialogue(
        self,
        params: Optional["DialogueReinvocationParams"] = None,
        agents: Optional[list] = None,
        stage_name: Optional[str] = None,
        state: Optional[Dict[str, Any]] = None,
        config_loader: Optional[ConfigLoaderProtocol] = None,
        dialogue_history: Optional[list] = None,
        round_number: Optional[int] = None,
        max_rounds: Optional[int] = None,
        strategy: Any = None,
    ) -> tuple:
        """Re-invoke agents with dialogue history as context.

        Args:
            params: DialogueReinvocationParams with all parameters (recommended)
            agents: (deprecated) List of agent references
            stage_name: (deprecated) Stage name
            state: (deprecated) State dict
            config_loader: (deprecated) Config loader
            dialogue_history: (deprecated) Dialogue history
            round_number: (deprecated) Current round number
            max_rounds: (deprecated) Max rounds
            strategy: (deprecated) Strategy instance

        Returns:
            Tuple of (agent_outputs, llm_providers)
        """
        from src.compiler.executors._base_helpers import (
            DialogueReinvocationParams,
            reinvoke_agents_with_dialogue,
        )

        # Support both new and legacy calling styles
        if params is None:
            if agents is None or stage_name is None:
                raise ValueError("Either params or all legacy args must be provided")
            params = DialogueReinvocationParams(
                agents=agents,  # type: ignore
                stage_name=stage_name,  # type: ignore
                state=state or {},  # type: ignore
                config_loader=config_loader,  # type: ignore
                dialogue_history=dialogue_history or [],  # type: ignore
                round_number=round_number or 0,  # type: ignore
                max_rounds=max_rounds or 3,  # type: ignore
                strategy=strategy,
                extract_agent_name_fn=self._extract_agent_name,
            )
        else:
            # Ensure extract_agent_name_fn is set
            params.extract_agent_name_fn = self._extract_agent_name

        return reinvoke_agents_with_dialogue(params)
