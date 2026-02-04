"""Sequential stage executor.

Executes agents one after another in the order specified in the stage config.
Each agent's output is accumulated and passed to subsequent agents, enabling
agent-to-agent context sharing within a stage.
"""
from typing import Dict, Any, Optional, cast
import time
import uuid
import traceback
import logging

from src.utils.exceptions import BaseError, ErrorCode, sanitize_error_message
from src.llm.circuit_breaker import CircuitBreakerError

logger = logging.getLogger(__name__)

from src.compiler.executors.base import StageExecutor
from src.compiler.utils import extract_agent_name
from src.agents.agent_factory import AgentFactory
from src.core.context import ExecutionContext
from src.utils.config_helpers import get_nested_value, sanitize_config_for_display


class SequentialStageExecutor(StageExecutor):
    """Execute agents sequentially (M2 mode).

    Agents run one at a time, each receiving the full workflow state
    including outputs from previous agents/stages.
    """

    def execute_stage(
        self,
        stage_name: str,
        stage_config: Any,
        state: Dict[str, Any],
        config_loader: Any,
        tool_registry: Optional[Any] = None,
        halt_on_failure: bool = True
    ) -> Dict[str, Any]:
        """Execute stage with sequential agent execution.

        Agents run one at a time. Each agent's output is accumulated so that
        subsequent agents can see prior agents' work via ``current_stage_agents``
        in their input data. The final stage output is a dict containing all
        per-agent outputs, statuses, and metrics.

        Args:
            stage_name: Stage name
            stage_config: Stage configuration
            state: Current workflow state
            config_loader: ConfigLoader for loading agent configs
            tool_registry: ToolRegistry for agent tool access
            halt_on_failure: DEPRECATED - use stage error_handling config instead

        Returns:
            Updated workflow state
        """
        # Get tracker if available
        tracker = state.get("tracker")
        workflow_id = state.get("workflow_id", "unknown")

        # Get error handling config from stage_config
        error_handling_config = None
        if hasattr(stage_config, 'stage'):
            # Pydantic model
            agents = stage_config.stage.agents
            if hasattr(stage_config.stage, 'error_handling'):
                error_handling_config = stage_config.stage.error_handling
        else:
            # Dict - try nested path first, then direct
            agents = get_nested_value(stage_config, 'stage.agents') or stage_config.get('agents', [])
            error_handling_dict = get_nested_value(stage_config, 'stage.error_handling')
            if error_handling_dict:
                from src.compiler.schemas import StageErrorHandlingConfig
                error_handling_config = StageErrorHandlingConfig(**error_handling_dict)

        # If no error_handling config, create default based on halt_on_failure param
        if error_handling_config is None:
            from src.compiler.schemas import StageErrorHandlingConfig
            on_failure = "halt_stage" if halt_on_failure else "continue_with_remaining"
            error_handling_config = StageErrorHandlingConfig(on_agent_failure=on_failure)

        # Accumulators for per-agent results
        agent_outputs: Dict[str, Any] = {}
        agent_statuses: Dict[str, Any] = {}  # str for success, dict for failure
        agent_metrics: Dict[str, Any] = {}

        # Track stage execution if tracker available
        stage_config_dict = stage_config.model_dump() if hasattr(stage_config, 'model_dump') else stage_config

        if tracker:
            with tracker.track_stage(
                stage_name=stage_name,
                stage_config=stage_config_dict,
                workflow_id=workflow_id,
                input_data=state.get("stage_outputs", {})
            ) as stage_id:
                agent_outputs, agent_statuses, agent_metrics = self._run_all_agents(
                    agents=agents,
                    stage_id=stage_id,
                    stage_name=stage_name,
                    workflow_id=workflow_id,
                    state=state,
                    tracker=tracker,
                    config_loader=config_loader,
                    error_handling=error_handling_config,
                )
        else:
            agent_outputs, agent_statuses, agent_metrics = self._run_all_agents(
                agents=agents,
                stage_id=f"stage-{uuid.uuid4().hex[:12]}",
                stage_name=stage_name,
                workflow_id=workflow_id,
                state=state,
                tracker=None,
                config_loader=config_loader,
                error_handling=error_handling_config,
            )

        # Check if collaboration is configured
        collaboration_config = None
        if hasattr(stage_config, 'stage') and hasattr(stage_config.stage, 'collaboration'):
            collaboration_config = stage_config.stage.collaboration
        elif isinstance(stage_config, dict):
            collaboration_config = get_nested_value(stage_config, 'stage.collaboration')

        # Determine final output
        final_output = ""
        synthesis_result = None

        if collaboration_config and len(agent_outputs) > 1:
            # Run collaboration synthesis
            try:
                # Convert agent_outputs dict to list of AgentOutput objects for synthesis
                from src.strategies.base import AgentOutput
                agent_output_list = []
                for agent_name, output_data in agent_outputs.items():
                    agent_output_list.append(AgentOutput(
                        agent_name=agent_name,
                        decision=output_data.get("output", ""),
                        reasoning=output_data.get("reasoning", ""),
                        confidence=output_data.get("confidence", 0.8),
                        metadata=output_data.get("metadata", {})
                    ))

                # Run synthesis
                synthesis_result = self._run_synthesis(
                    agent_output_list,
                    stage_config,
                    stage_name
                )

                # Use synthesized output
                final_output = synthesis_result.decision

                logger.info(
                    f"Sequential stage {stage_name} used collaboration synthesis: "
                    f"{synthesis_result.method} (confidence={synthesis_result.confidence:.2f})"
                )

            except Exception as e:
                logger.warning(
                    f"Collaboration synthesis failed for sequential stage {stage_name}: {e}. "
                    f"Falling back to last agent output."
                )
                # Fall back to last agent output
                if agent_outputs:
                    last_key = list(agent_outputs.keys())[-1]
                    final_output = agent_outputs[last_key].get("output", "")
        else:
            # No collaboration - use last agent's output for backward compatibility
            if agent_outputs:
                last_key = list(agent_outputs.keys())[-1]
                final_output = agent_outputs[last_key].get("output", "")

        # Store structured stage output in state
        if not isinstance(state.get("stage_outputs"), dict):
            state["stage_outputs"] = {}

        stage_output = {
            "output": final_output,
            "agent_outputs": agent_outputs,
            "agent_statuses": agent_statuses,
            "agent_metrics": agent_metrics,
        }

        # Include synthesis result if collaboration was used
        if synthesis_result:
            stage_output["synthesis_result"] = {
                "method": synthesis_result.method,
                "confidence": synthesis_result.confidence,
                "votes": synthesis_result.votes if hasattr(synthesis_result, "votes") else {},
                "metadata": synthesis_result.metadata if hasattr(synthesis_result, "metadata") else {}
            }

        state["stage_outputs"][stage_name] = stage_output
        state["current_stage"] = stage_name

        return state

    def supports_stage_type(self, stage_type: str) -> bool:
        """Check if executor supports this stage type.

        Args:
            stage_type: Stage type identifier

        Returns:
            True for "sequential" type
        """
        return stage_type == "sequential"

    def _run_all_agents(
        self,
        agents: list,
        stage_id: str,
        stage_name: str,
        workflow_id: str,
        state: Dict[str, Any],
        tracker: Optional[Any],
        config_loader: Any,
        error_handling: Any,
    ) -> tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
        """Execute all agents in sequence with configurable error handling.

        Args:
            agents: List of agent references
            stage_id: Stage execution ID
            stage_name: Stage name
            workflow_id: Workflow execution ID
            state: Current workflow state
            tracker: ExecutionTracker instance (optional)
            config_loader: ConfigLoader for loading agent configs
            error_handling: StageErrorHandlingConfig with on_agent_failure policy

        Returns:
            Tuple of (agent_outputs, agent_statuses, agent_metrics)
        """
        agent_outputs: Dict[str, Any] = {}
        agent_statuses: Dict[str, Any] = {}
        agent_metrics: Dict[str, Any] = {}

        for agent_ref in agents:
            agent_result = self._execute_agent(
                agent_ref=agent_ref,
                stage_id=stage_id,
                stage_name=stage_name,
                workflow_id=workflow_id,
                state=state,
                tracker=tracker,
                config_loader=config_loader,
                prior_agent_outputs=agent_outputs,
            )

            agent_name = agent_result["agent_name"]

            # Store status with error details for failed agents
            if agent_result["status"] == "failed":
                agent_statuses[agent_name] = {
                    "status": "failed",
                    "error": agent_result["output_data"].get("error", ""),
                    "error_type": agent_result["output_data"].get("error_type", ""),
                }

                # Handle failure based on policy
                policy = error_handling.on_agent_failure

                if policy == "halt_stage":
                    logger.warning(
                        "Agent %s failed in stage %s (policy: halt_stage), stopping execution: %s",
                        agent_name, stage_name, agent_result["output_data"].get("error", "")
                    )
                    # Don't store output for halted agent
                    agent_outputs[agent_name] = agent_result["output_data"]
                    agent_metrics[agent_name] = agent_result["metrics"]
                    break

                elif policy == "skip_agent":
                    logger.warning(
                        "Agent %s failed in stage %s (policy: skip_agent), skipping: %s",
                        agent_name, stage_name, agent_result["output_data"].get("error", "")
                    )
                    # Don't add output to agent_outputs - subsequent agents won't see it
                    agent_metrics[agent_name] = agent_result["metrics"]
                    continue

                elif policy == "retry_agent":
                    max_retries = error_handling.max_agent_retries
                    logger.warning(
                        "Agent %s failed in stage %s (policy: retry_agent), retries not yet implemented: %s",
                        agent_name, stage_name, agent_result["output_data"].get("error", "")
                    )
                    # TODO: Implement retry_agent policy in future PR
                    # For now, treat as continue_with_remaining
                    agent_outputs[agent_name] = agent_result["output_data"]
                    agent_metrics[agent_name] = agent_result["metrics"]

                elif policy == "continue_with_remaining":
                    logger.warning(
                        "Agent %s failed in stage %s (policy: continue_with_remaining), continuing: %s",
                        agent_name, stage_name, agent_result["output_data"].get("error", "")
                    )
                    # Store output with error details for subsequent agents
                    agent_outputs[agent_name] = agent_result["output_data"]
                    agent_metrics[agent_name] = agent_result["metrics"]

            else:
                # Success
                agent_statuses[agent_name] = agent_result["status"]
                agent_outputs[agent_name] = agent_result["output_data"]
                agent_metrics[agent_name] = agent_result["metrics"]

        return agent_outputs, agent_statuses, agent_metrics

    def _execute_agent(
        self,
        agent_ref: Any,
        stage_id: str,
        stage_name: str,
        workflow_id: str,
        state: Dict[str, Any],
        tracker: Optional[Any],
        config_loader: Any,
        prior_agent_outputs: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute a single agent and return structured result.

        Args:
            agent_ref: Agent reference from stage config
            stage_id: Stage execution ID
            stage_name: Stage name
            workflow_id: Workflow execution ID
            state: Current workflow state
            tracker: ExecutionTracker instance (optional)
            config_loader: ConfigLoader for loading agent configs
            prior_agent_outputs: Outputs from prior agents in the same stage

        Returns:
            Dict with keys: agent_name, output_data, status, metrics
        """
        agent_name = self._extract_agent_name(agent_ref)
        start_time = time.time()

        try:
            return self._run_agent(
                agent_name=agent_name,
                agent_ref=agent_ref,
                stage_id=stage_id,
                stage_name=stage_name,
                workflow_id=workflow_id,
                state=state,
                tracker=tracker,
                config_loader=config_loader,
                prior_agent_outputs=prior_agent_outputs or {},
                start_time=start_time,
            )
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as e:
            duration = time.time() - start_time

            # Check for circuit breaker error (provider unhealthy)
            if isinstance(e, CircuitBreakerError):
                error_type = ErrorCode.LLM_CONNECTION_ERROR.value
                error_message = sanitize_error_message(str(e))
                error_traceback = sanitize_error_message(traceback.format_exc())

                logger.error(
                    "Agent %s failed: Circuit breaker OPEN (provider unhealthy). "
                    "Subsequent agents using same provider will fast-fail. Error: %s",
                    agent_name, error_message
                )

            # Derive error_type from framework ErrorCode if available
            elif isinstance(e, BaseError):
                error_type = e.error_code.value
                error_message = sanitize_error_message(str(e))
                error_traceback = sanitize_error_message(traceback.format_exc())

                logger.warning(
                    "Agent %s failed in stage: %s",
                    agent_name, error_message
                )

            else:
                # Map standard Python exceptions to ErrorCode
                error_type_map = {
                    "TimeoutError": ErrorCode.SYSTEM_TIMEOUT.value,
                    "ConnectionError": ErrorCode.LLM_CONNECTION_ERROR.value,
                    "ValueError": ErrorCode.VALIDATION_ERROR.value,
                    "RuntimeError": ErrorCode.AGENT_EXECUTION_ERROR.value,
                }
                error_type = error_type_map.get(
                    type(e).__name__, ErrorCode.UNKNOWN_ERROR.value
                )

                # Sanitize error message and traceback to prevent credential leakage
                error_message = sanitize_error_message(str(e))
                error_traceback = sanitize_error_message(traceback.format_exc())

                logger.warning(
                    "Agent %s failed in stage: %s",
                    agent_name, error_message
                )

            return {
                "agent_name": agent_name,
                "output_data": {
                    "output": "",
                    "error": error_message,
                    "error_type": error_type,
                    "traceback": error_traceback,
                },
                "status": "failed",
                "metrics": {
                    "tokens": 0,
                    "cost_usd": 0.0,
                    "duration_seconds": duration,
                    "tool_calls": 0,
                },
            }

    def _run_agent(
        self,
        agent_name: str,
        agent_ref: Any,
        stage_id: str,
        stage_name: str,
        workflow_id: str,
        state: Dict[str, Any],
        tracker: Optional[Any],
        config_loader: Any,
        prior_agent_outputs: Dict[str, Any],
        start_time: float,
    ) -> Dict[str, Any]:
        """Internal: load, execute, and track a single agent.

        Returns:
            Dict with keys: agent_name, output_data, status, metrics
        """
        # Load agent config
        agent_config_dict = config_loader.load_agent(agent_name)

        from src.compiler.schemas import AgentConfig
        agent_config = AgentConfig(**agent_config_dict)

        # Create agent
        agent = AgentFactory.create(agent_config)

        # Prepare input data
        if hasattr(state, 'to_dict'):
            state_dict = state.to_dict(exclude_internal=True)
        else:
            state_dict = dict(state) if hasattr(state, '__iter__') else state

        input_data = {
            **state_dict,
            "stage_outputs": state_dict.get("stage_outputs", {}),
            "current_stage_agents": dict(prior_agent_outputs),
        }

        # Create execution context
        context = ExecutionContext(
            workflow_id=workflow_id,
            stage_id=stage_id,
            agent_id=f"agent-{uuid.uuid4().hex[:12]}",
            metadata={
                "stage_name": stage_name,
                "agent_name": agent_name,
            }
        )

        # Prepare serializable config for tracking
        if hasattr(agent_config, 'model_dump'):
            agent_config_dict_for_tracking = agent_config.model_dump()
        elif hasattr(agent_config, 'dict'):
            agent_config_dict_for_tracking = agent_config.dict()
        else:
            agent_config_dict_for_tracking = cast(Dict[str, Any], agent_config)
        agent_config_dict_for_tracking = sanitize_config_for_display(agent_config_dict_for_tracking)

        if tracker:
            import json

            def is_serializable(value: Any) -> bool:
                try:
                    json.dumps(value)
                    return True
                except (TypeError, ValueError):
                    return False

            tracking_input_data = {
                k: v for k, v in input_data.items()
                if k not in ('tracker', 'tool_registry', 'config_loader', 'visualizer')
                and is_serializable(v)
            }
            tracking_input_data = sanitize_config_for_display(tracking_input_data)

            with tracker.track_agent(
                agent_name=agent_name,
                agent_config=agent_config_dict_for_tracking,
                stage_id=stage_id,
                input_data=tracking_input_data
            ) as agent_id:
                context.agent_id = agent_id

                # Pass tracker to agent for direct observability reporting
                input_data['tracker'] = tracker

                response = agent.execute(input_data, context)

                tracker.set_agent_output(
                    agent_id=agent_id,
                    output_data={"output": response.output},
                    reasoning=response.reasoning,
                    total_tokens=response.tokens,
                    estimated_cost_usd=response.estimated_cost_usd,
                    num_llm_calls=1 if response.tokens and response.tokens > 0 else 0,
                    num_tool_calls=len(response.tool_calls) if response.tool_calls else 0
                )
        else:
            response = agent.execute(input_data, context)

        duration = time.time() - start_time
        return {
            "agent_name": agent_name,
            "output_data": {
                "output": response.output,
                "reasoning": response.reasoning,
                "confidence": response.confidence,
                "tokens": response.tokens,
                "cost_usd": response.estimated_cost_usd,
                "tool_calls": len(response.tool_calls) if response.tool_calls else 0,
            },
            "status": "success",
            "metrics": {
                "tokens": response.tokens or 0,
                "cost_usd": response.estimated_cost_usd or 0.0,
                "duration_seconds": duration,
                "tool_calls": len(response.tool_calls) if response.tool_calls else 0,
            },
        }

    def _extract_agent_name(self, agent_ref: Any) -> str:
        """Extract agent name from various agent reference formats.

        Delegates to shared utility function to avoid code duplication.

        Args:
            agent_ref: Agent reference (dict, str, or Pydantic model)

        Returns:
            Agent name
        """
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
            ImportError: If strategy registry not available
        """
        try:
            # Try to import registry
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
            # Fallback: use simple consensus
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
        agents: list,
        stage_name: str,
        state: Dict[str, Any],
        config_loader: Any,
        dialogue_history: list,
        round_number: int,
        max_rounds: int
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

        Returns:
            List of AgentOutput objects
        """
        from src.strategies.base import AgentOutput
        from src.compiler.schemas import AgentConfig

        agent_outputs = []

        # Execute agents sequentially
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
