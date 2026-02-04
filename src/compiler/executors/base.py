"""Base interface for stage executors.

Defines the contract that all stage execution strategies must implement,
plus the ParallelRunner abstraction for engine-agnostic parallel execution,
and shared methods for synthesis, dialogue, and agent name extraction.
"""
from abc import ABC, abstractmethod
from typing import Callable, Dict, Any, List, Optional
import uuid
import time
import logging

logger = logging.getLogger(__name__)


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
        config_loader: Any,
        tool_registry: Optional[Any] = None
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
        state: Dict[str, Any] = None,
        config_loader: Any = None,
        agents: List = None
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
                confidence = 0.5

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
        config_loader: Any,
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
                "output": output.decision,
                "reasoning": output.reasoning,
                "confidence": output.confidence
            })
            total_cost += output.metadata.get("cost_usd", 0.0)

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
            current_outputs = self._reinvoke_agents_with_dialogue(
                agents=agents,
                stage_name=stage_name,
                state=state,
                config_loader=config_loader,
                dialogue_history=dialogue_history,
                round_number=round_num,
                max_rounds=strategy.max_rounds,
                strategy=strategy
            )

            # Record this round
            for output in current_outputs:
                dialogue_history.append({
                    "agent": output.agent_name,
                    "round": round_num,
                    "output": output.decision,
                    "reasoning": output.reasoning,
                    "confidence": output.confidence
                })
                total_cost += output.metadata.get("cost_usd", 0.0)

            # Check convergence (after min_rounds)
            if round_num >= strategy.min_rounds:
                convergence_score = strategy.calculate_convergence(
                    current_outputs,
                    previous_outputs
                )
                logger.info(
                    f"Dialogue round {round_num + 1} for stage '{stage_name}': "
                    f"convergence {convergence_score:.1%} "
                    f"(threshold: {strategy.convergence_threshold:.1%})"
                )

                if convergence_score >= strategy.convergence_threshold:
                    converged = True
                    convergence_round = round_num
                    logger.info(
                        f"Dialogue converged at round {round_num + 1} for "
                        f"stage '{stage_name}': {convergence_score:.1%} >= "
                        f"{strategy.convergence_threshold:.1%}"
                    )
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

    def _reinvoke_agents_with_dialogue(
        self,
        agents: list,
        stage_name: str,
        state: Dict[str, Any],
        config_loader: Any,
        dialogue_history: list,
        round_number: int,
        max_rounds: int,
        strategy: Any = None
    ) -> list:
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
            List of AgentOutput objects
        """
        from src.strategies.base import AgentOutput
        from src.compiler.schemas import AgentConfig
        from src.agents.agent_factory import AgentFactory
        from src.core.context import ExecutionContext

        agent_outputs = []

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

            # Enrich input with dialogue context
            input_data = {
                **state,
                "dialogue_history": curated_history,
                "round_number": round_number,
                "max_rounds": max_rounds,
                "agent_role": agent_role
            }

            # Create execution context
            context = ExecutionContext(
                workflow_id=state.get("workflow_id", "unknown"),
                stage_id=f"stage-{uuid.uuid4().hex[:12]}",
                agent_id=f"agent-{uuid.uuid4().hex[:12]}",
                metadata={
                    "stage_name": stage_name,
                    "agent_name": agent_name,
                    "execution_mode": "dialogue",
                    "round": round_number
                }
            )

            # Execute agent
            response = agent.execute(input_data, context)

            # Create agent output
            agent_outputs.append(AgentOutput(
                agent_name=agent_name,
                decision=response.output,
                reasoning=response.reasoning,
                confidence=response.confidence,
                metadata={
                    "tokens": response.tokens,
                    "cost_usd": response.estimated_cost_usd,
                    "round": round_number
                }
            ))

        return agent_outputs
