"""Base interface for stage executors.

Defines the contract that all stage execution strategies must implement,
plus the ParallelRunner abstraction for engine-agnostic parallel execution,
and shared methods for synthesis, dialogue, and agent name extraction.
"""
import logging
import uuid
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional

from typing_extensions import TypedDict

from src.compiler.domain_state import (
    ConfigLoaderProtocol,
    DomainToolRegistryProtocol,
    TrackerProtocol,
    VisualizerProtocol,
)
from src.compiler.executors.state_keys import StateKeys
from src.constants.probabilities import PROB_MEDIUM
from src.constants.sizes import UUID_HEX_SHORT_LENGTH
from src.utils.config_helpers import sanitize_config_for_display

logger = logging.getLogger(__name__)

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

            # Check if strategy requires AGENT_ROLE_LEADER-based synthesis
            if hasattr(strategy, 'requires_AGENT_ROLE_LEADER_synthesis') and strategy.requires_AGENT_ROLE_LEADER_synthesis:
                return self._run_AGENT_ROLE_LEADER_synthesis(
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
            # Fallback: strategy registry not available, use simple consensus
            from src.strategies.base import (
                SynthesisResult,
                calculate_vote_distribution,
                extract_majority_decision,
            )

            decision = extract_majority_decision(agent_outputs)
            votes = calculate_vote_distribution(agent_outputs)

            if decision and votes:
                confidence = votes.get(str(decision), 0) / len(agent_outputs)
            else:
                confidence = PROB_MEDIUM

            return SynthesisResult(
                decision=decision or "",
                confidence=confidence,
                method="fallback_consensus",
                votes=votes,
                conflicts=[],
                reasoning=(
                    f"Fallback synthesis: {len(agent_outputs)} agents, "
                    f"decision='{decision}'"
                ),
                metadata={"fallback": True}
            )

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

        Args:
            initial_outputs: Initial round agent outputs
            strategy: DialogueOrchestrator strategy
            stage_config: Stage configuration
            stage_name: Stage name
            state: Workflow state
            config_loader: Config loader
            agents: List of agent refs

        Returns:
            SynthesisResult from final dialogue round
        """
        dialogue_history: List[Dict[str, Any]] = []
        current_outputs = initial_outputs
        total_cost = 0.0

        # Record initial round (round 0)
        for output in current_outputs:
            dialogue_history.append({
                "agent": output.agent_name,
                "round": 0,
                StateKeys.OUTPUT: output.decision,
                StateKeys.REASONING: output.reasoning,
                StateKeys.CONFIDENCE: output.confidence,
            })
            total_cost += output.metadata.get(StateKeys.COST_USD, 0.0)

        # Track round 0 collaboration event
        tracker = state.get(StateKeys.TRACKER)
        if tracker and hasattr(tracker, 'track_collaboration_event'):
            try:
                agent_names = [o.agent_name for o in current_outputs]
                tracker.track_collaboration_event(
                    event_type=f"{strategy.mode}_round",
                    stage_id=state.get(StateKeys.CURRENT_STAGE_ID),
                    agents_involved=agent_names,
                    round_number=0,
                    outcome="initial",
                    event_data={
                        "agent_count": len(agent_names),
                        "avg_confidence": (
                            sum(o.confidence for o in current_outputs) / len(current_outputs)
                            if current_outputs else 0.0
                        ),
                    },
                )
            except Exception:
                logger.warning(
                    "Failed to track round 0 collaboration event",
                    exc_info=True,
                )

        # Check budget after round 0
        if strategy.cost_budget_usd and total_cost >= strategy.cost_budget_usd:
            logger.warning(
                f"Dialogue stopped after round 0 for stage '{stage_name}': "
                f"budget ${strategy.cost_budget_usd:.2f} reached "
                f"(cost: ${total_cost:.2f})"
            )
            result = strategy.synthesize(current_outputs, {})
            result.metadata["dialogue_rounds"] = 1
            result.metadata["total_cost_usd"] = total_cost
            result.metadata["early_stop_reason"] = "budget"
            return result

        # Execute additional rounds (1 to max_rounds-1)
        final_round = 0
        previous_outputs = initial_outputs
        converged = False
        convergence_round = -1

        for round_num in range(1, strategy.max_rounds):
            final_round = round_num

            # Re-invoke agents with dialogue history
            current_outputs, llm_providers = self._reinvoke_agents_with_dialogue(
                agents=agents,
                stage_name=stage_name,
                state=state,
                config_loader=config_loader,
                dialogue_history=dialogue_history,
                round_number=round_num,
                max_rounds=strategy.max_rounds,
                strategy=strategy
            )

            # Delegate stance extraction to the strategy (LLM-based)
            agent_stances: Dict[str, str] = {}
            if hasattr(strategy, 'extract_stances'):
                agent_stances = strategy.extract_stances(
                    current_outputs, llm_providers
                )

            # Record this round
            for output in current_outputs:
                entry: Dict[str, Any] = {
                    "agent": output.agent_name,
                    "round": round_num,
                    "output": output.decision,
                    "reasoning": output.reasoning,
                    "confidence": output.confidence,
                }
                stance = agent_stances.get(output.agent_name, "")
                if stance:
                    entry["stance"] = stance
                dialogue_history.append(entry)
                total_cost += output.metadata.get(StateKeys.COST_USD, 0.0)

            # Check convergence (after min_rounds)
            conv_score = None
            round_outcome = "in_progress"
            if round_num >= strategy.min_rounds:
                conv_score = strategy.calculate_convergence(
                    current_outputs,
                    previous_outputs
                )
                logger.info(
                    f"Dialogue round {round_num + 1} for stage '{stage_name}': "
                    f"convergence {conv_score:.1%} "
                    f"(threshold: {strategy.convergence_threshold:.1%})"
                )

                if conv_score >= strategy.convergence_threshold:
                    converged = True
                    convergence_round = round_num
                    round_outcome = "converged"
                    logger.info(
                        f"Dialogue converged at round {round_num + 1} for "
                        f"stage '{stage_name}': {conv_score:.1%} >= "
                        f"{strategy.convergence_threshold:.1%}"
                    )

            # Track round N collaboration event (with stance distribution)
            stance_dist: Dict[str, int] = {}
            for s in agent_stances.values():
                if s:
                    stance_dist[s] = stance_dist.get(s, 0) + 1

            tracker = state.get(StateKeys.TRACKER)
            if tracker and hasattr(tracker, 'track_collaboration_event'):
                try:
                    agent_names = [o.agent_name for o in current_outputs]
                    tracker.track_collaboration_event(
                        event_type=f"{strategy.mode}_round",
                        stage_id=state.get(StateKeys.CURRENT_STAGE_ID),
                        agents_involved=agent_names,
                        round_number=round_num,
                        outcome=round_outcome,
                        confidence_score=conv_score,
                        event_data={
                            "agent_count": len(agent_names),
                            "avg_confidence": (
                                sum(o.confidence for o in current_outputs) / len(current_outputs)
                                if current_outputs else 0.0
                            ),
                            "stance_distribution": stance_dist,
                            "agent_stances": agent_stances,
                        },
                    )
                except Exception:
                    logger.warning(
                        "Failed to track round %d collaboration event",
                        round_num,
                        exc_info=True,
                    )

            if converged:
                break

            # Check budget
            if strategy.cost_budget_usd and total_cost >= strategy.cost_budget_usd:
                logger.warning(
                    f"Dialogue stopped at round {round_num + 1} for "
                    f"stage '{stage_name}': budget "
                    f"${strategy.cost_budget_usd:.2f} reached "
                    f"(cost: ${total_cost:.2f})"
                )
                break

            # Update previous outputs for next convergence check
            previous_outputs = current_outputs

        # Final synthesis
        result = strategy.synthesize(current_outputs, {})
        result.metadata["dialogue_rounds"] = final_round + 1
        result.metadata["total_cost_usd"] = total_cost
        result.metadata["dialogue_history"] = dialogue_history
        result.metadata["converged"] = converged
        if converged:
            result.metadata["convergence_round"] = convergence_round
            result.metadata["early_stop_reason"] = "convergence"
        elif strategy.cost_budget_usd and total_cost >= strategy.cost_budget_usd:
            result.metadata["early_stop_reason"] = "budget"
        else:
            result.metadata["early_stop_reason"] = "max_rounds"

        logger.info(
            f"Dialogue completed for stage '{stage_name}': "
            f"{final_round + 1} rounds, ${total_cost:.2f} cost, "
            f"converged: {converged}, "
            f"reason: {result.metadata['early_stop_reason']}"
        )

        return result

    def _run_AGENT_ROLE_LEADER_synthesis(
        self,
        agent_outputs: list,
        strategy: Any,
        stage_config: Any,
        stage_name: str,
        state: Optional[Dict[str, Any]] = None,
        config_loader: Optional[ConfigLoaderProtocol] = None,
        agents: Optional[List] = None,
    ) -> Any:
        """Execute AGENT_ROLE_LEADER-based synthesis: re-invoke AGENT_ROLE_LEADER with team outputs.

        The perspective agents have already run (their outputs are in
        agent_outputs). This method:
        1. Formats perspective outputs as structured text
        2. Re-invokes the AGENT_ROLE_LEADER agent with ``team_outputs`` in its input
        3. Calls strategy.synthesize() with all outputs (perspectives + AGENT_ROLE_LEADER)

        Falls back to consensus on perspective outputs if AGENT_ROLE_LEADER invocation fails.

        Args:
            agent_outputs: Outputs from perspective agents (round 0)
            strategy: LeaderCollaborationStrategy instance
            stage_config: Stage configuration dict
            stage_name: Name of the current stage
            state: Workflow state
            config_loader: Config loader for loading agent configs
            agents: List of agent refs from stage config

        Returns:
            SynthesisResult from AGENT_ROLE_LEADER or consensus fallback
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
        AGENT_ROLE_LEADER_name = strategy.get_AGENT_ROLE_LEADER_agent_name(collaboration_config)

        if not AGENT_ROLE_LEADER_name:
            logger.warning(
                "Leader strategy for stage '%s' has no AGENT_ROLE_LEADER_agent configured; "
                "falling back to consensus.",
                stage_name,
            )
            return strategy.synthesize(agent_outputs, collaboration_config)

        # Format perspective outputs for AGENT_ROLE_LEADER prompt injection
        team_outputs_text = strategy.format_team_outputs(agent_outputs)

        # Re-invoke the AGENT_ROLE_LEADER agent
        try:
            if state is None or config_loader is None:
                raise ValueError("state and config_loader required for AGENT_ROLE_LEADER synthesis")

            AGENT_ROLE_LEADER_output = self._invoke_AGENT_ROLE_LEADER_agent(
                AGENT_ROLE_LEADER_name=AGENT_ROLE_LEADER_name,
                team_outputs_text=team_outputs_text,
                stage_name=stage_name,
                state=state,
                config_loader=config_loader,
            )

            # Combine perspective + AGENT_ROLE_LEADER outputs and synthesize
            all_outputs = list(agent_outputs) + [AGENT_ROLE_LEADER_output]
            return strategy.synthesize(all_outputs, collaboration_config)

        except Exception as exc:
            logger.warning(
                "Leader agent '%s' failed for stage '%s': %s. "
                "Falling back to consensus on perspective outputs.",
                AGENT_ROLE_LEADER_name,
                stage_name,
                exc,
            )
            return strategy.synthesize(agent_outputs, collaboration_config)

    def _invoke_AGENT_ROLE_LEADER_agent(
        self,
        AGENT_ROLE_LEADER_name: str,
        team_outputs_text: str,
        stage_name: str,
        state: Dict[str, Any],
        config_loader: ConfigLoaderProtocol,
    ) -> Any:
        """Invoke the AGENT_ROLE_LEADER agent with team outputs injected.

        Args:
            AGENT_ROLE_LEADER_name: Leader agent name
            team_outputs_text: Formatted perspective outputs
            stage_name: Stage name
            state: Workflow state
            config_loader: Config loader

        Returns:
            AgentOutput from the AGENT_ROLE_LEADER agent
        """
        from src.agents.agent_factory import AgentFactory
        from src.compiler.schemas import AgentConfig
        from src.core.context import ExecutionContext
        from src.strategies.base import AgentOutput

        agent_config_dict = config_loader.load_agent(AGENT_ROLE_LEADER_name)
        agent_config = AgentConfig(**agent_config_dict)
        agent = AgentFactory.create(agent_config)

        # Inject team_outputs into agent input
        input_data = {
            **state,
            "team_outputs": team_outputs_text,
        }

        tracker = state.get(StateKeys.TRACKER)
        current_stage_id = state.get(StateKeys.CURRENT_STAGE_ID) or f"stage-{uuid.uuid4().hex[:UUID_HEX_SHORT_LENGTH]}"

        if tracker:
            agent_config_for_tracking = sanitize_config_for_display(
                agent_config.model_dump() if hasattr(agent_config, 'model_dump') else dict(agent_config_dict)
            )
            with tracker.track_agent(
                agent_name=AGENT_ROLE_LEADER_name,
                agent_config=agent_config_for_tracking,
                stage_id=current_stage_id,
                input_data={"role": "AGENT_ROLE_LEADER", "team_outputs_length": len(team_outputs_text)},
            ) as agent_id:
                context = ExecutionContext(
                    workflow_id=state.get(StateKeys.WORKFLOW_ID, "STATUS_UNKNOWN"),
                    stage_id=current_stage_id,
                    agent_id=agent_id,
                    metadata={
                        "stage_name": stage_name,
                        "agent_name": AGENT_ROLE_LEADER_name,
                        "execution_mode": "AGENT_ROLE_LEADER",
                    },
                )
                response = agent.execute(input_data, context)

                try:
                    tracker.set_agent_output(
                        agent_id=agent_id,
                        output_data={StateKeys.OUTPUT: response.output},
                        reasoning=response.reasoning,
                        total_tokens=response.tokens,
                        estimated_cost_usd=response.estimated_cost_usd,
                        num_llm_calls=1 if response.tokens and response.tokens > 0 else 0,
                        num_tool_calls=len(response.tool_calls) if response.tool_calls else 0,
                    )
                except Exception:
                    logger.warning(
                        "Failed to set agent output tracking for AGENT_ROLE_LEADER agent %s",
                        AGENT_ROLE_LEADER_name,
                        exc_info=True,
                    )
        else:
            input_data.pop(StateKeys.TRACKER, None)
            context = ExecutionContext(
                workflow_id=state.get(StateKeys.WORKFLOW_ID, "STATUS_UNKNOWN"),
                stage_id=current_stage_id,
                agent_id=f"agent-{uuid.uuid4().hex[:UUID_HEX_SHORT_LENGTH]}",
                metadata={
                    "stage_name": stage_name,
                    "agent_name": AGENT_ROLE_LEADER_name,
                    "execution_mode": "AGENT_ROLE_LEADER",
                },
            )
            response = agent.execute(input_data, context)

        return AgentOutput(
            agent_name=AGENT_ROLE_LEADER_name,
            decision=response.output,
            reasoning=response.reasoning or "",
            confidence=response.confidence or 0.0,
            metadata={
                StateKeys.TOKENS: response.tokens,
                StateKeys.COST_USD: response.estimated_cost_usd,
                "role": "AGENT_ROLE_LEADER",
            },
        )

    def _reinvoke_agents_with_dialogue(
        self,
        agents: list,
        stage_name: str,
        state: Dict[str, Any],
        config_loader: ConfigLoaderProtocol,
        dialogue_history: list,
        round_number: int,
        max_rounds: int,
        strategy: Any = None
    ) -> tuple:
        """Re-invoke agents with dialogue history as context.

        Args:
            agents: List of agent refs
            stage_name: Stage name
            state: Workflow state
            config_loader: Config loader
            dialogue_history: Accumulated dialogue history
            round_number: Current round number
            max_rounds: Maximum rounds
            strategy: DialogueOrchestrator strategy (for context curation)

        Returns:
            Tuple of (agent_outputs, llm_providers) where llm_providers
            maps agent_name -> LLM provider for stance extraction.
        """
        from src.agents.agent_factory import AgentFactory
        from src.compiler.schemas import AgentConfig
        from src.core.context import ExecutionContext
        from src.strategies.base import AgentOutput

        agent_outputs = []
        llm_providers: Dict[str, Any] = {}

        for agent_ref in agents:
            agent_name = self._extract_agent_name(agent_ref)

            # Load agent config
            agent_config_dict = config_loader.load_agent(agent_name)
            agent_config = AgentConfig(**agent_config_dict)
            agent = AgentFactory.create(agent_config)

            # Extract role from agent metadata (if present)
            agent_role = None
            if hasattr(agent_config.agent, 'metadata') and agent_config.agent.metadata:
                if agent_config.agent.metadata.tags:
                    agent_role = agent_config.agent.metadata.tags[0]
                if hasattr(agent_config.agent.metadata, 'role'):
                    agent_role = agent_config.agent.metadata.role

            # Curate dialogue history based on strategy
            curated_history = dialogue_history
            if strategy and hasattr(strategy, 'curate_dialogue_history'):
                curated_history = strategy.curate_dialogue_history(
                    dialogue_history=dialogue_history,
                    current_round=round_number,
                    agent_name=agent_name
                )

            # Get mode-specific context from strategy (e.g. MultiRoundStrategy)
            mode_context: Dict[str, Any] = {}
            if strategy and hasattr(strategy, 'get_round_context'):
                mode_context = strategy.get_round_context(round_number, agent_name)

            # Enrich input with dialogue context
            input_data = {
                **state,
                "dialogue_history": curated_history,
                "round_number": round_number,
                "max_rounds": max_rounds,
                "agent_role": agent_role,
                **mode_context,
            }

            tracker = state.get(StateKeys.TRACKER)
            current_stage_id = state.get(StateKeys.CURRENT_STAGE_ID) or f"stage-{uuid.uuid4().hex[:UUID_HEX_SHORT_LENGTH]}"

            if tracker:
                # Use tracker for proper agent_executions record so LLM calls
                # can reference a valid agent_execution_id (avoids FK violations).
                agent_config_for_tracking = sanitize_config_for_display(
                    agent_config.model_dump() if hasattr(agent_config, 'model_dump') else dict(agent_config_dict)
                )
                with tracker.track_agent(
                    agent_name=agent_name,
                    agent_config=agent_config_for_tracking,
                    stage_id=current_stage_id,
                    input_data={"round": round_number, "max_rounds": max_rounds},
                ) as agent_id:
                    context = ExecutionContext(
                        workflow_id=state.get(StateKeys.WORKFLOW_ID, "STATUS_UNKNOWN"),
                        stage_id=current_stage_id,
                        agent_id=agent_id,
                        metadata={
                            "stage_name": stage_name,
                            "agent_name": agent_name,
                            "execution_mode": "dialogue",
                            "round": round_number
                        }
                    )
                    response = agent.execute(input_data, context)

                    try:
                        tracker.set_agent_output(
                            agent_id=agent_id,
                            output_data={StateKeys.OUTPUT: response.output},
                            reasoning=response.reasoning,
                            total_tokens=response.tokens,
                            estimated_cost_usd=response.estimated_cost_usd,
                            num_llm_calls=1 if response.tokens and response.tokens > 0 else 0,
                            num_tool_calls=len(response.tool_calls) if response.tool_calls else 0,
                        )
                    except Exception:
                        logger.warning("Failed to set agent output tracking for dialogue agent %s", agent_name, exc_info=True)
            else:
                # No tracker — use synthetic IDs (no agent_executions row,
                # so don't pass tracker to avoid FK violations on llm_calls).
                input_data.pop(StateKeys.TRACKER, None)
                context = ExecutionContext(
                    workflow_id=state.get(StateKeys.WORKFLOW_ID, "STATUS_UNKNOWN"),
                    stage_id=current_stage_id,
                    agent_id=f"agent-{uuid.uuid4().hex[:UUID_HEX_SHORT_LENGTH]}",
                    metadata={
                        "stage_name": stage_name,
                        "agent_name": agent_name,
                        "execution_mode": "dialogue",
                        "round": round_number
                    }
                )
                response = agent.execute(input_data, context)

            # Create agent output (metadata must be JSON-serializable)
            agent_outputs.append(AgentOutput(
                agent_name=agent_name,
                decision=response.output,
                reasoning=response.reasoning or "",
                confidence=response.confidence or 0.0,
                metadata={
                    StateKeys.TOKENS: response.tokens,
                    StateKeys.COST_USD: response.estimated_cost_usd,
                    "round": round_number,
                }
            ))
            # Keep LLM provider reference for stance extraction (not serialized)
            llm_providers[agent_name] = agent.llm

        return agent_outputs, llm_providers
