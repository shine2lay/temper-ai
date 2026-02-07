"""Sequential stage executor.

Executes agents one after another in the order specified in the stage config.
Each agent's output is accumulated and passed to subsequent agents, enabling
agent-to-agent context sharing within a stage.
"""
import logging
import threading
import time
import traceback
import uuid
from typing import Any, Dict, Optional, cast

from src.llm.circuit_breaker import CircuitBreakerError
from src.utils.exceptions import BaseError, ErrorCode, sanitize_error_message

logger = logging.getLogger(__name__)

from src.agents.agent_factory import AgentFactory
from src.compiler.domain_state import ConfigLoaderProtocol, ToolRegistryProtocol
from src.compiler.executors.base import StageExecutor
from src.compiler.schemas import StageErrorHandlingConfig
from src.core.context import ExecutionContext
from src.utils.config_helpers import get_nested_value, sanitize_config_for_display

# Error types classified as transient (worth retrying)
_TRANSIENT_ERROR_TYPES: frozenset[str] = frozenset({
    ErrorCode.LLM_CONNECTION_ERROR.value,
    ErrorCode.LLM_TIMEOUT.value,
    ErrorCode.LLM_RATE_LIMIT.value,
    ErrorCode.SYSTEM_TIMEOUT.value,
    ErrorCode.SYSTEM_RESOURCE_ERROR.value,
    ErrorCode.TOOL_TIMEOUT.value,
    ErrorCode.AGENT_TIMEOUT.value,
    ErrorCode.WORKFLOW_TIMEOUT.value,
})


def _is_transient_error(error_type: str) -> bool:
    """Classify an error type as transient (retriable) vs permanent.

    Transient errors are network/timeout/rate-limit issues that may
    resolve on retry.  Everything else (config, auth, validation,
    safety) is permanent and should not be retried.
    """
    return error_type in _TRANSIENT_ERROR_TYPES


class SequentialStageExecutor(StageExecutor):
    """Execute agents sequentially (M2 mode).

    Agents run one at a time, each receiving the full workflow state
    including outputs from previous agents/stages.
    """

    def __init__(self) -> None:
        """Initialize sequential executor with an empty agent cache."""
        # Per-workflow agent cache: agent_name -> agent instance.
        # Avoids recreating agents for every stage invocation when the
        # same agent appears in multiple stages of the same workflow.
        self._agent_cache: Dict[str, Any] = {}

    def execute_stage(
        self,
        stage_name: str,
        stage_config: Any,
        state: Dict[str, Any],
        config_loader: ConfigLoaderProtocol,
        tool_registry: Optional[ToolRegistryProtocol] = None,
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
                error_handling_config = StageErrorHandlingConfig(**error_handling_dict)

        # If no error_handling config, create default based on halt_on_failure param
        if error_handling_config is None:
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

                # Run synthesis (pass dialogue parameters for multi-round support)
                synthesis_result = self._run_synthesis(
                    agent_output_list,
                    stage_config,
                    stage_name,
                    state=state,
                    config_loader=config_loader,
                    agents=agents
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
        config_loader: ConfigLoaderProtocol,
        error_handling: StageErrorHandlingConfig,
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

        show_details = state.get("show_details", False)
        detail_console = state.get("detail_console")
        if show_details and detail_console:
            detail_console.print(f"\n[bold cyan]── Stage: {stage_name} ──[/bold cyan]")

        total_agents = len(agents)
        prior_stages = list(state.get("stage_outputs", {}).keys())
        input_info = f"prior stages: {prior_stages}" if prior_stages else "workflow inputs only"
        logger.info("Stage '%s' starting sequential execution with %d agent(s) (%s)", stage_name, total_agents, input_info)
        for agent_idx, agent_ref in enumerate(agents):
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
            logger.info("Stage '%s' agent '%s' completed (%s)", stage_name, agent_name, agent_result["status"])

            # Print real-time progress if show_details enabled
            if show_details and detail_console:
                is_last = (agent_idx == total_agents - 1)
                connector = "└─" if is_last else "├─"
                metrics = agent_result.get("metrics", {})
                duration = metrics.get("duration_seconds", 0.0)
                tokens = metrics.get("tokens", 0)

                if agent_result["status"] == "failed":
                    error_type = agent_result.get("output_data", {}).get("error_type", "error")
                    detail_console.print(
                        f"  {connector} [red]{agent_name} ✗[/red] ({duration:.1f}s) [{error_type}]"
                    )
                else:
                    detail_console.print(
                        f"  {connector} [green]{agent_name} ✓[/green] ({duration:.1f}s, {tokens} tokens)"
                    )

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
                    error_type = agent_result["output_data"].get("error_type", "")

                    if _is_transient_error(error_type) and max_retries > 0:
                        retry_result = self._retry_agent_with_backoff(
                            agent_ref=agent_ref,
                            stage_id=stage_id,
                            stage_name=stage_name,
                            workflow_id=workflow_id,
                            state=state,
                            tracker=tracker,
                            config_loader=config_loader,
                            prior_agent_outputs=agent_outputs,
                            max_retries=max_retries,
                            agent_name=agent_name,
                        )
                        # Use retry result (may be success or final failure)
                        agent_name = retry_result["agent_name"]
                        if retry_result["status"] == "success":
                            agent_statuses[agent_name] = retry_result["status"]
                        else:
                            agent_statuses[agent_name] = {
                                "status": "failed",
                                "error": retry_result["output_data"].get("error", ""),
                                "error_type": retry_result["output_data"].get("error_type", ""),
                            }
                        agent_outputs[agent_name] = retry_result["output_data"]
                        agent_metrics[agent_name] = retry_result["metrics"]
                    else:
                        # Permanent error or retries disabled — do not retry
                        if not _is_transient_error(error_type):
                            logger.warning(
                                "Agent %s failed with permanent error type '%s' in stage %s "
                                "(policy: retry_agent, not retrying): %s",
                                agent_name, error_type, stage_name,
                                agent_result["output_data"].get("error", ""),
                            )
                        else:
                            logger.warning(
                                "Agent %s failed in stage %s (policy: retry_agent, "
                                "max_retries=0): %s",
                                agent_name, stage_name,
                                agent_result["output_data"].get("error", ""),
                            )
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

    def _retry_agent_with_backoff(
        self,
        agent_ref: Any,
        stage_id: str,
        stage_name: str,
        workflow_id: str,
        state: Dict[str, Any],
        tracker: Optional[Any],
        config_loader: ConfigLoaderProtocol,
        prior_agent_outputs: Dict[str, Any],
        max_retries: int,
        agent_name: str,
    ) -> Dict[str, Any]:
        """Retry a failed agent with exponential backoff.

        Only retries on transient errors.  Stops immediately if a
        permanent error is encountered during a retry attempt.

        Args:
            agent_ref: Agent reference from stage config
            stage_id: Stage execution ID
            stage_name: Stage name
            workflow_id: Workflow execution ID
            state: Current workflow state
            tracker: ExecutionTracker instance (optional)
            config_loader: ConfigLoader for loading agent configs
            prior_agent_outputs: Outputs from prior agents in the same stage
            max_retries: Maximum number of retry attempts
            agent_name: Agent name (for logging)

        Returns:
            Dict with keys: agent_name, output_data, status, metrics
        """
        base_delay = 1.0  # seconds
        last_result: Dict[str, Any] = {}

        _backoff_event = threading.Event()

        for attempt in range(1, max_retries + 1):
            delay = min(base_delay * (2 ** (attempt - 1)), 30.0)
            logger.info(
                "Retrying agent %s in stage %s (attempt %d/%d, backoff %.1fs)",
                agent_name, stage_name, attempt, max_retries, delay,
            )
            # Use Event.wait() instead of time.sleep() so the delay is
            # interruptible (e.g. by a shutdown signal setting the event).
            _backoff_event.wait(timeout=delay)

            last_result = self._execute_agent(
                agent_ref=agent_ref,
                stage_id=stage_id,
                stage_name=stage_name,
                workflow_id=workflow_id,
                state=state,
                tracker=tracker,
                config_loader=config_loader,
                prior_agent_outputs=prior_agent_outputs,
            )

            if last_result["status"] == "success":
                logger.info(
                    "Agent %s succeeded on retry attempt %d/%d in stage %s",
                    agent_name, attempt, max_retries, stage_name,
                )
                # Record retries in metrics
                last_result["metrics"]["retries"] = attempt
                return last_result

            # Check if this retry's error is still transient
            retry_error_type = last_result["output_data"].get("error_type", "")
            if not _is_transient_error(retry_error_type):
                logger.warning(
                    "Agent %s retry %d/%d hit permanent error type '%s' in stage %s, "
                    "stopping retries: %s",
                    agent_name, attempt, max_retries, retry_error_type, stage_name,
                    last_result["output_data"].get("error", ""),
                )
                last_result["metrics"]["retries"] = attempt
                return last_result

        # All retries exhausted
        logger.warning(
            "Agent %s exhausted all %d retries in stage %s",
            agent_name, max_retries, stage_name,
        )
        if last_result:
            last_result["metrics"]["retries"] = max_retries
        return last_result

    def _execute_agent(
        self,
        agent_ref: Any,
        stage_id: str,
        stage_name: str,
        workflow_id: str,
        state: Dict[str, Any],
        tracker: Optional[Any],
        config_loader: ConfigLoaderProtocol,
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
        config_loader: ConfigLoaderProtocol,
        prior_agent_outputs: Dict[str, Any],
        start_time: float,
    ) -> Dict[str, Any]:
        """Internal: load, execute, and track a single agent.

        Returns:
            Dict with keys: agent_name, output_data, status, metrics
        """
        # Load agent config and create agent (with per-workflow caching)
        if agent_name in self._agent_cache:
            agent = self._agent_cache[agent_name]
            # Still need the config dict for tracking purposes below
            agent_config_dict = config_loader.load_agent(agent_name)
            from src.compiler.schemas import AgentConfig
            agent_config = AgentConfig(**agent_config_dict)
        else:
            agent_config_dict = config_loader.load_agent(agent_name)
            from src.compiler.schemas import AgentConfig
            agent_config = AgentConfig(**agent_config_dict)
            agent = AgentFactory.create(agent_config)
            self._agent_cache[agent_name] = agent

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
            # Allowlist of known non-serializable/infrastructure keys to exclude
            # from tracking data. This avoids the cost of attempting json.dumps()
            # on every value in the state dict.
            _NON_SERIALIZABLE_KEYS: frozenset[str] = frozenset({
                'tracker', 'tool_registry', 'config_loader', 'visualizer',
                'show_details', 'detail_console',
            })

            tracking_input_data = {
                k: v for k, v in input_data.items()
                if k not in _NON_SERIALIZABLE_KEYS
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
                "tool_calls": response.tool_calls if response.tool_calls else [],
            },
            "status": "success",
            "metrics": {
                "tokens": response.tokens or 0,
                "cost_usd": response.estimated_cost_usd or 0.0,
                "duration_seconds": duration,
                "tool_calls": len(response.tool_calls) if response.tool_calls else 0,
            },
        }

