"""Parallel stage executor.

Executes multiple agents concurrently using nested LangGraph subgraphs.
"""
from typing import Dict, Any, Optional, List, Callable, cast
from typing_extensions import TypedDict as TD, Annotated
import uuid
import time
import logging

from langgraph.graph import StateGraph, START, END

from src.compiler.executors.base import StageExecutor
from src.compiler.utils import extract_agent_name
from src.agents.agent_factory import AgentFactory
from src.core.context import ExecutionContext
from src.utils.config_helpers import get_nested_value
from src.utils.exceptions import ConfigNotFoundError, ConfigValidationError

logger = logging.getLogger(__name__)


class ParallelStageExecutor(StageExecutor):
    """Execute agents in parallel (M3 mode).

    Creates a nested LangGraph with parallel branches for each agent,
    collects outputs, and delegates to synthesis coordinator.
    """

    def __init__(self, synthesis_coordinator: Optional[Any] = None, quality_gate_validator: Optional[Any] = None) -> None:
        """Initialize parallel executor.

        Args:
            synthesis_coordinator: Coordinator for synthesizing agent outputs
            quality_gate_validator: Validator for quality gates
        """
        self.synthesis_coordinator = synthesis_coordinator
        self.quality_gate_validator = quality_gate_validator

    def execute_stage(
        self,
        stage_name: str,
        stage_config: Any,
        state: Dict[str, Any],
        config_loader: Any,
        tool_registry: Optional[Any] = None
    ) -> Dict[str, Any]:
        """Execute stage with parallel agent execution.

        Creates a nested LangGraph with parallel branches for agents,
        collects outputs, and synthesizes via collaboration strategy.

        Uses an iterative loop for quality gate retries to avoid stack
        overflow with high max_retries values.

        Args:
            stage_name: Stage name
            stage_config: Stage configuration
            state: Current workflow state
            config_loader: ConfigLoader for loading agent configs
            tool_registry: ToolRegistry for agent tool access

        Returns:
            Updated workflow state with synthesized output

        Raises:
            RuntimeError: If stage execution fails
        """
        # Custom reducer for merging dict updates
        def merge_dicts(left: Dict[str, Any], right: Dict[str, Any]) -> Dict[str, Any]:
            """Merge two dicts for concurrent updates.

            Optimization: Avoid unnecessary dictionary copies when one dict is empty.
            - If left is empty, return right directly (no copy needed)
            - If right is empty, return left as-is (no merge needed)
            - Otherwise, copy left and update with right
            """
            if not left:
                return right if right else {}
            if not right:
                return left
            result = left.copy()
            result.update(right)
            return result

        # Define state for parallel execution subgraph
        # Use Annotated with custom merge function for concurrent dict writes
        class ParallelStageState(TD, total=False):
            agent_outputs: Annotated[Dict[str, Any], merge_dicts]
            agent_statuses: Annotated[Dict[str, str], merge_dicts]
            agent_metrics: Annotated[Dict[str, Any], merge_dicts]
            errors: Annotated[Dict[str, str], merge_dicts]
            stage_input: Dict[str, Any]

        # Iterative retry loop — replaces former recursive self.execute_stage() call.
        # Stack depth stays constant regardless of max_retries.
        while True:
            # Create subgraph for parallel execution
            subgraph = StateGraph(ParallelStageState)

            # Get agents for this stage
            if hasattr(stage_config, 'stage'):
                agents = stage_config.stage.agents
            else:
                agents = get_nested_value(stage_config, 'stage.agents') or stage_config.get('agents', [])

            # Add initialization node
            def init_parallel(s: ParallelStageState) -> Dict[str, Any]:
                """Initialize parallel state with empty collections."""
                return {
                    "agent_outputs": {},
                    "agent_statuses": {},
                    "agent_metrics": {},
                    "errors": {},
                    "stage_input": {
                        **state,
                        "stage_outputs": state.get("stage_outputs", {})
                    }
                }

            subgraph.add_node("init", init_parallel)  # type: ignore[call-overload]

            # Create node for each agent
            for agent_ref in agents:
                agent_name = self._extract_agent_name(agent_ref)

                # Create agent execution node
                agent_node = self._create_agent_node(
                    agent_name=agent_name,
                    agent_ref=agent_ref,
                    stage_name=stage_name,
                    state=state,
                    config_loader=config_loader
                )

                subgraph.add_node(agent_name, agent_node)  # type: ignore[call-overload]

            # Create collection node (waits for all agents)
            def collect_outputs(s: ParallelStageState) -> Dict[str, Any]:
                """Collect and validate agent outputs, calculate aggregate metrics."""
                # Get min_successful_agents from config
                stage_dict = stage_config if isinstance(stage_config, dict) else {}
                error_handling = stage_dict.get("error_handling", {})
                min_successful = error_handling.get("min_successful_agents", 1)

                # Count successful agents
                agent_statuses = s.get("agent_statuses", {})
                successful = [
                    name for name, status in agent_statuses.items()
                    if status == "success"
                ]

                if len(successful) < min_successful:
                    raise RuntimeError(
                        f"Only {len(successful)}/{len(agents)} agents succeeded. "
                        f"Minimum required: {min_successful}"
                    )

                # Calculate aggregate metrics
                agent_metrics = s.get("agent_metrics", {})
                agent_outputs_dict = s.get("agent_outputs", {})

                total_tokens = 0
                total_cost = 0.0
                max_duration = 0.0
                total_confidence = 0.0
                num_successful = 0

                for agent_name, metrics in agent_metrics.items():
                    if agent_statuses.get(agent_name) == "success":
                        total_tokens += metrics.get("tokens", 0)
                        total_cost += metrics.get("cost_usd", 0.0)
                        max_duration = max(max_duration, metrics.get("duration_seconds", 0.0))

                        # Get confidence from output
                        output = agent_outputs_dict.get(agent_name, {})
                        total_confidence += output.get("confidence", 0.0)
                        num_successful += 1

                avg_confidence = total_confidence / num_successful if num_successful > 0 else 0.0

                # Store aggregate metrics in a special key
                return {
                    "agent_outputs": {
                        "__aggregate_metrics__": {
                            "total_tokens": total_tokens,
                            "total_cost_usd": total_cost,
                            "total_duration_seconds": max_duration,
                            "avg_confidence": avg_confidence,
                            "num_agents": len(agents),
                            "num_successful": num_successful,
                            "num_failed": len(agents) - num_successful
                        }
                    }
                }

            subgraph.add_node("collect", collect_outputs)  # type: ignore[call-overload]

            # Add edges: init → all agents (parallel) → collect
            subgraph.add_edge(START, "init")

            for agent_ref in agents:
                agent_name = self._extract_agent_name(agent_ref)
                subgraph.add_edge("init", agent_name)  # Parallel branches
                subgraph.add_edge(agent_name, "collect")  # All → collect

            subgraph.add_edge("collect", END)

            # Set entry point
            subgraph.set_entry_point("init")

            # Compile and execute subgraph
            compiled_subgraph = subgraph.compile()

            try:
                # Execute parallel subgraph with initial state
                initial_state: Dict[str, Any] = {
                    "agent_outputs": {},
                    "agent_statuses": {},
                    "agent_metrics": {},
                    "errors": {},
                    "stage_input": {}
                }
                parallel_result = compiled_subgraph.invoke(initial_state)  # type: ignore[arg-type]

                # Extract agent outputs
                agent_outputs_dict = parallel_result["agent_outputs"]

                # Extract aggregate metrics (stored with special key)
                aggregate_metrics = agent_outputs_dict.pop("__aggregate_metrics__", {})

                # Create AgentOutput objects for synthesis
                from src.strategies.base import AgentOutput

                agent_outputs = []
                for agent_name, output_data in agent_outputs_dict.items():
                    agent_outputs.append(AgentOutput(
                        agent_name=agent_name,
                        decision=output_data.get("output", ""),
                        reasoning=output_data.get("reasoning", ""),
                        confidence=output_data.get("confidence", 0.8),
                        metadata=output_data.get("metadata", {})
                    ))

                # Run synthesis (pass dialogue parameters for multi-round support)
                synthesis_result = self._run_synthesis(
                    agent_outputs=agent_outputs,
                    stage_config=stage_config,
                    stage_name=stage_name,
                    state=state,
                    config_loader=config_loader,
                    agents=agents
                )

                # Validate quality gates (M3-12)
                passed, violations = self._validate_quality_gates(
                    synthesis_result=synthesis_result,
                    stage_config=stage_config,
                    stage_name=stage_name,
                    state=state
                )

                # Reset retry counter if quality gates passed (successful after retry)
                if passed and "stage_retry_counts" in state and stage_name in state["stage_retry_counts"]:
                    retry_count = state["stage_retry_counts"][stage_name]
                    del state["stage_retry_counts"][stage_name]
                    logger.info(
                        f"Stage '{stage_name}' passed quality gates after {retry_count} retries"
                    )

                # Handle quality gate failures
                if not passed:
                    stage_dict = stage_config if isinstance(stage_config, dict) else {}
                    quality_gates_config = stage_dict.get("quality_gates", {})
                    on_failure = quality_gates_config.get("on_failure", "retry_stage")

                    # Get retry count for observability tracking
                    retry_count = state.get("stage_retry_counts", {}).get(stage_name, 0)

                    # Track quality gate failure in observability
                    tracker = state.get("tracker")
                    if tracker and hasattr(tracker, 'track_collaboration_event'):
                        tracker.track_collaboration_event(
                            event_type="quality_gate_failure",
                            stage_name=stage_name,
                            agents=[],
                            decision=None,
                            confidence=getattr(synthesis_result, "confidence", 0.0),
                            metadata={
                                "violations": violations,
                                "on_failure_action": on_failure,
                                "synthesis_method": synthesis_result.method,
                                "retry_count": retry_count,
                                "max_retries": quality_gates_config.get("max_retries", 2)
                            }
                        )

                    # Handle based on on_failure config
                    if on_failure == "escalate":
                        raise RuntimeError(
                            f"Quality gates failed for stage '{stage_name}': {'; '.join(violations)}"
                        )
                    elif on_failure == "proceed_with_warning":
                        # Log warning but continue
                        logger.warning(
                            f"Quality gates failed for stage '{stage_name}' but proceeding: {'; '.join(violations)}"
                        )
                        # Add warning to metadata
                        if not hasattr(synthesis_result, "metadata") or synthesis_result.metadata is None:
                            synthesis_result.metadata = {}
                        synthesis_result.metadata["quality_gate_warning"] = violations
                    elif on_failure == "retry_stage":
                        # Get max retries configuration
                        max_retries = quality_gates_config.get("max_retries", 2)

                        # Initialize retry tracking in state if needed
                        if "stage_retry_counts" not in state:
                            state["stage_retry_counts"] = {}

                        # Get current retry count for this stage
                        retry_count = state["stage_retry_counts"].get(stage_name, 0)

                        # Check if retries exhausted
                        if retry_count >= max_retries:
                            # Retries exhausted - escalate
                            raise RuntimeError(
                                f"Quality gates failed for stage '{stage_name}' after {retry_count} retries "
                                f"(max: {max_retries}). Final violations: {'; '.join(violations)}"
                            )

                        # Increment retry counter
                        state["stage_retry_counts"][stage_name] = retry_count + 1

                        # Track retry attempt in observability
                        if tracker and hasattr(tracker, 'track_collaboration_event'):
                            tracker.track_collaboration_event(
                                event_type="quality_gate_retry",
                                stage_name=stage_name,
                                agents=[],
                                decision=None,
                                confidence=getattr(synthesis_result, "confidence", 0.0),
                                metadata={
                                    "violations": violations,
                                    "retry_attempt": retry_count + 1,
                                    "max_retries": max_retries,
                                    "synthesis_method": synthesis_result.method
                                }
                            )

                        # Log retry attempt
                        logger.warning(
                            f"Quality gates failed for stage '{stage_name}', retrying "
                            f"(attempt {retry_count + 2}/{max_retries + 1}). Violations: {'; '.join(violations)}"
                        )

                        # Iterative retry: continue the while loop instead of recursing
                        continue

                # Update state with enhanced multi-agent tracking
                state["stage_outputs"][stage_name] = {
                    "decision": synthesis_result.decision,
                    "agent_outputs": agent_outputs_dict,
                    "agent_statuses": parallel_result.get("agent_statuses", {}),
                    "agent_metrics": parallel_result.get("agent_metrics", {}),
                    "aggregate_metrics": aggregate_metrics,
                    "synthesis": {
                        "method": synthesis_result.method,
                        "confidence": synthesis_result.confidence,
                        "votes": synthesis_result.votes,
                        "conflicts": len(synthesis_result.conflicts)
                    }
                }
                state["current_stage"] = stage_name

                # Track synthesis in observability
                tracker = state.get("tracker")
                if tracker:
                    # Track collaboration event with agent-level metrics
                    tracker_metadata = {
                        "method": synthesis_result.method,
                        "confidence": synthesis_result.confidence,
                        "votes": synthesis_result.votes,
                        "num_conflicts": len(synthesis_result.conflicts),
                        "reasoning": synthesis_result.reasoning,
                        "agent_statuses": parallel_result.get("agent_statuses", {}),
                        "aggregate_metrics": aggregate_metrics
                    }
                    if hasattr(tracker, 'track_collaboration_event'):
                        tracker.track_collaboration_event(
                            event_type="synthesis",
                            stage_name=stage_name,
                            agents=list(agent_outputs_dict.keys()),
                            decision=synthesis_result.decision,
                            confidence=synthesis_result.confidence,
                            metadata=tracker_metadata
                        )

                return state

            except Exception as e:
                # Handle stage failure
                stage_dict = stage_config if isinstance(stage_config, dict) else {}
                error_handling = stage_dict.get("error_handling", {})
                on_failure = error_handling.get("on_stage_failure", "halt")

                if on_failure == "halt":
                    raise
                elif on_failure == "skip":
                    # Skip this stage, continue workflow
                    state["stage_outputs"][stage_name] = None
                    return state
                else:
                    raise

    def supports_stage_type(self, stage_type: str) -> bool:
        """Check if executor supports this stage type.

        Args:
            stage_type: Stage type identifier

        Returns:
            True for "parallel" type
        """
        return stage_type == "parallel"

    def _create_agent_node(
        self,
        agent_name: str,
        agent_ref: Any,
        stage_name: str,
        state: Dict[str, Any],
        config_loader: Any
    ) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
        """Create execution node for a single agent in parallel execution.

        Args:
            agent_name: Agent name
            agent_ref: Agent reference from stage config
            stage_name: Stage name
            state: Workflow state (for context)
            config_loader: ConfigLoader for loading agent configs

        Returns:
            Callable node function that executes the agent
        """
        def agent_node(s: Dict[str, Any]) -> Dict[str, Any]:
            """Execute single agent and store result."""
            start_time = time.time()

            try:
                # Load agent config
                agent_config_dict = config_loader.load_agent(agent_name)

                from src.compiler.schemas import AgentConfig
                agent_config = AgentConfig(**agent_config_dict)

                # Create agent
                agent = AgentFactory.create(agent_config)

                # Prepare input
                input_data = s.get("stage_input", {})

                # Pass tracker to agent for direct observability reporting
                tracker = state.get("tracker")
                if tracker:
                    input_data['tracker'] = tracker

                # Create execution context
                context = ExecutionContext(
                    workflow_id=state.get("workflow_id", "unknown"),
                    stage_id=f"stage-{uuid.uuid4().hex[:12]}",
                    agent_id=f"agent-{uuid.uuid4().hex[:12]}",
                    metadata={
                        "stage_name": stage_name,
                        "agent_name": agent_name,
                        "execution_mode": "parallel"
                    }
                )

                # Execute agent
                response = agent.execute(input_data, context)

                # Calculate duration
                duration = time.time() - start_time

                # Return success updates for Annotated fields
                return {
                    "agent_outputs": {
                        agent_name: {
                            "output": response.output,
                            "reasoning": response.reasoning,
                            "confidence": response.confidence,
                            "tokens": response.tokens,
                            "cost": response.estimated_cost_usd,
                            "metadata": {
                                "tool_calls": len(response.tool_calls) if response.tool_calls else 0
                            }
                        }
                    },
                    "agent_statuses": {agent_name: "success"},
                    "agent_metrics": {
                        agent_name: {
                            "tokens": response.tokens,
                            "cost_usd": response.estimated_cost_usd,
                            "duration_seconds": duration,
                            "tool_calls": len(response.tool_calls) if response.tool_calls else 0,
                            "retries": 0
                        }
                    },
                    "errors": {}  # Empty errors on success
                }

            except (ConfigNotFoundError, ConfigValidationError, ValueError, TypeError, KeyError) as e:
                # Expected configuration or validation errors - log as info
                logger.info(f"Agent {agent_name} configuration/validation error: {e}")
                duration = time.time() - start_time

                return {
                    "agent_outputs": {},
                    "agent_statuses": {agent_name: "failed"},
                    "agent_metrics": {
                        agent_name: {
                            "tokens": 0,
                            "cost_usd": 0.0,
                            "duration_seconds": duration,
                            "tool_calls": 0,
                            "retries": 0
                        }
                    },
                    "errors": {agent_name: f"{type(e).__name__}: {str(e)}"}
                }

            except (KeyboardInterrupt, SystemExit):
                # System-level interrupts should propagate
                raise

            except Exception as e:
                # Unexpected errors - log with full context for debugging
                logger.error(
                    f"Unexpected error in agent {agent_name}: {type(e).__name__}: {e}",
                    exc_info=True  # Include full traceback
                )
                duration = time.time() - start_time

                return {
                    "agent_outputs": {},
                    "agent_statuses": {agent_name: "failed"},
                    "agent_metrics": {
                        agent_name: {
                            "tokens": 0,
                            "cost_usd": 0.0,
                            "duration_seconds": duration,
                            "tool_calls": 0,
                            "retries": 0
                        }
                    },
                    "errors": {agent_name: f"Unexpected error: {type(e).__name__}: {str(e)}"}
                }

        return agent_node

    def _run_synthesis(
        self,
        agent_outputs: List[Any],
        stage_config: Any,
        stage_name: str,
        state: Dict[str, Any] = None,
        config_loader: Any = None,
        agents: List = None
    ) -> Any:
        """Run collaboration strategy to synthesize agent outputs.

        Args:
            agent_outputs: List of AgentOutput objects
            stage_config: Stage configuration
            stage_name: Stage name
            state: Workflow state (optional, for dialogue mode)
            config_loader: Config loader (optional, for dialogue mode)
            agents: List of agent refs (optional, for dialogue mode)

        Returns:
            SynthesisResult

        Raises:
            ImportError: If strategy registry not available (m3-06 not complete)
        """
        if self.synthesis_coordinator:
            return self.synthesis_coordinator.synthesize(
                agent_outputs=agent_outputs,
                stage_config=stage_config,
                stage_name=stage_name
            )

        # Fallback to inline implementation
        try:
            # Try to import registry (m3-06)
            from src.strategies.registry import get_strategy_from_config

            # Get strategy from config
            strategy = get_strategy_from_config(stage_config)

            # Check if strategy requires multi-round dialogue
            if hasattr(strategy, 'requires_requery') and strategy.requires_requery:
                # Multi-round dialogue mode
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

            # Get strategy config
            stage_dict = stage_config if isinstance(stage_config, dict) else {}
            collaboration_config = stage_dict.get("collaboration", {}).get("config", {})

            # One-shot synthesis
            result = strategy.synthesize(agent_outputs, collaboration_config)

            return result

        except ImportError:
            # Fallback: m3-06 not complete yet, use simple consensus
            from src.strategies.base import SynthesisResult, calculate_vote_distribution, extract_majority_decision

            decision = extract_majority_decision(agent_outputs)
            votes = calculate_vote_distribution(agent_outputs)

            # Calculate simple confidence
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
                reasoning=f"Fallback synthesis (m3-06 pending): {len(agent_outputs)} agents, decision='{decision}'",
                metadata={"fallback": True}
            )

    def _run_dialogue_synthesis(
        self,
        initial_outputs: List[Any],
        strategy: Any,
        stage_config: Any,
        stage_name: str,
        state: Dict[str, Any],
        config_loader: Any,
        agents: List
    ) -> Any:
        """Execute multi-round dialogue with agent re-invocation.

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
        from src.strategies.base import AgentOutput

        dialogue_history = []
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
                f"budget ${strategy.cost_budget_usd:.2f} reached (cost: ${total_cost:.2f})"
            )
            result = strategy.synthesize(current_outputs, {})
            result.metadata["dialogue_rounds"] = 1
            result.metadata["total_cost_usd"] = total_cost
            result.metadata["early_stop_reason"] = "budget"
            return result

        # Execute additional rounds (1 to max_rounds-1)
        final_round = 0
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
                max_rounds=strategy.max_rounds
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

            # Check budget
            if strategy.cost_budget_usd and total_cost >= strategy.cost_budget_usd:
                logger.warning(
                    f"Dialogue stopped at round {round_num + 1} for stage '{stage_name}': "
                    f"budget ${strategy.cost_budget_usd:.2f} reached (cost: ${total_cost:.2f})"
                )
                break

        # Final synthesis
        result = strategy.synthesize(current_outputs, {})
        result.metadata["dialogue_rounds"] = final_round + 1
        result.metadata["total_cost_usd"] = total_cost
        result.metadata["dialogue_history"] = dialogue_history

        logger.info(
            f"Dialogue completed for stage '{stage_name}': "
            f"{final_round + 1} rounds, ${total_cost:.2f} cost"
        )

        return result

    def _reinvoke_agents_with_dialogue(
        self,
        agents: List,
        stage_name: str,
        state: Dict[str, Any],
        config_loader: Any,
        dialogue_history: List[Dict],
        round_number: int,
        max_rounds: int
    ) -> List[Any]:
        """Re-invoke agents with dialogue history as context.

        Args:
            agents: List of agent refs
            stage_name: Stage name
            state: Workflow state
            config_loader: Config loader
            dialogue_history: Accumulated dialogue history
            round_number: Current round number
            max_rounds: Maximum rounds

        Returns:
            List of AgentOutput objects
        """
        from src.strategies.base import AgentOutput
        from src.compiler.schemas import AgentConfig

        agent_outputs = []

        for agent_ref in agents:
            agent_name = self._extract_agent_name(agent_ref)

            # Load agent config
            agent_config_dict = config_loader.load_agent(agent_name)
            agent_config = AgentConfig(**agent_config_dict)
            agent = AgentFactory.create(agent_config)

            # Enrich input with dialogue context
            input_data = {
                **state,
                "dialogue_history": dialogue_history,
                "round_number": round_number,
                "max_rounds": max_rounds
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

    def _validate_quality_gates(
        self,
        synthesis_result: Any,
        stage_config: Any,
        stage_name: str,
        state: Dict[str, Any]
    ) -> tuple[bool, list[str]]:
        """Validate synthesis result against quality gates.

        Args:
            synthesis_result: SynthesisResult from synthesis
            stage_config: Stage configuration
            stage_name: Stage name
            state: Current workflow state

        Returns:
            Tuple of (passed: bool, violations: List[str])
        """
        if self.quality_gate_validator:
            return cast(
                tuple[bool, list[str]],
                self.quality_gate_validator.validate(
                    synthesis_result=synthesis_result,
                    stage_config=stage_config,
                    stage_name=stage_name
                )
            )

        # Fallback to inline implementation
        # Get quality gates config
        stage_dict = stage_config if isinstance(stage_config, dict) else {}
        quality_gates_config = stage_dict.get("quality_gates", {})

        # Check if quality gates are enabled (default: False for backward compatibility)
        if not quality_gates_config.get("enabled", False):
            return True, []  # Quality gates disabled, pass

        violations = []

        # Check minimum confidence
        min_confidence = quality_gates_config.get("min_confidence", 0.7)
        actual_confidence = getattr(synthesis_result, "confidence", 0.0)
        if actual_confidence < min_confidence:
            violations.append(
                f"Confidence {actual_confidence:.2f} below minimum {min_confidence:.2f}"
            )

        # Check minimum findings
        min_findings = quality_gates_config.get("min_findings", 5)
        # Look for findings in synthesis result metadata or decision
        findings = []
        if hasattr(synthesis_result, "metadata"):
            findings = synthesis_result.metadata.get("findings", [])
        elif hasattr(synthesis_result, "decision") and isinstance(synthesis_result.decision, dict):
            findings = synthesis_result.decision.get("findings", [])

        if min_findings > 0 and len(findings) < min_findings:
            violations.append(
                f"Only {len(findings)} findings, minimum {min_findings} required"
            )

        # Check citations required
        require_citations = quality_gates_config.get("require_citations", True)
        if require_citations:
            citations = []
            if hasattr(synthesis_result, "metadata"):
                citations = synthesis_result.metadata.get("citations", [])
            elif hasattr(synthesis_result, "decision") and isinstance(synthesis_result.decision, dict):
                citations = synthesis_result.decision.get("citations", [])

            if not citations:
                violations.append("No citations provided")

        passed = len(violations) == 0
        return passed, violations

    def _extract_agent_name(self, agent_ref: Any) -> str:
        """Extract agent name from various agent reference formats.

        Delegates to shared utility function to avoid code duplication.

        Args:
            agent_ref: Agent reference (dict, str, or Pydantic model)

        Returns:
            Agent name
        """
        return extract_agent_name(agent_ref)
