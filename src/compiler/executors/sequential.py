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

        Returns:
            Updated workflow state
        """
        # Get tracker if available
        tracker = state.get("tracker")
        workflow_id = state.get("workflow_id", "unknown")

        # Get agents for this stage
        if hasattr(stage_config, 'stage'):
            # Pydantic model
            agents = stage_config.stage.agents
        else:
            # Dict - try nested path first, then direct
            agents = get_nested_value(stage_config, 'stage.agents') or stage_config.get('agents', [])

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
                    halt_on_failure=halt_on_failure,
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
                halt_on_failure=halt_on_failure,
            )

        # Determine the final agent's text output for backward compatibility
        last_agent_output = ""
        if agent_outputs:
            last_key = list(agent_outputs.keys())[-1]
            last_agent_output = agent_outputs[last_key].get("output", "")

        # Store structured stage output in state
        if not isinstance(state.get("stage_outputs"), dict):
            state["stage_outputs"] = {}
        state["stage_outputs"][stage_name] = {
            "output": last_agent_output,
            "agent_outputs": agent_outputs,
            "agent_statuses": agent_statuses,
            "agent_metrics": agent_metrics,
        }
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
        halt_on_failure: bool,
    ) -> tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
        """Execute all agents in sequence with optional halt-on-failure.

        Args:
            agents: List of agent references
            stage_id: Stage execution ID
            stage_name: Stage name
            workflow_id: Workflow execution ID
            state: Current workflow state
            tracker: ExecutionTracker instance (optional)
            config_loader: ConfigLoader for loading agent configs
            halt_on_failure: Stop executing agents after first failure

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
            agent_outputs[agent_name] = agent_result["output_data"]
            agent_metrics[agent_name] = agent_result["metrics"]

            # Store status with error details for failed agents
            if agent_result["status"] == "failed":
                agent_statuses[agent_name] = {
                    "status": "failed",
                    "error": agent_result["output_data"].get("error", ""),
                    "error_type": agent_result["output_data"].get("error_type", ""),
                }
                if halt_on_failure:
                    logger.warning(
                        "Agent %s failed in stage %s, halting execution: %s",
                        agent_name, stage_name, agent_result["output_data"].get("error", "")
                    )
                    break
            else:
                agent_statuses[agent_name] = agent_result["status"]

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

            # Derive error_type from framework ErrorCode if available
            if isinstance(e, BaseError):
                error_type = e.error_code.value
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
