"""Sequential stage executor.

Executes agents one after another in the order specified in the stage config.
Each agent's output is accumulated and passed to subsequent agents, enabling
agent-to-agent context sharing within a stage.
"""
import logging
import threading
import uuid
from typing import Any, Dict, Literal, Optional

from src.constants.probabilities import PROB_VERY_HIGH
from src.constants.sizes import UUID_HEX_SHORT_LENGTH
from src.utils.exceptions import (
    ConfigValidationError,
)

logger = logging.getLogger(__name__)

from src.agents.agent_factory import AgentFactory
from src.compiler.domain_state import ConfigLoaderProtocol, DomainToolRegistryProtocol
from src.compiler.executors._sequential_helpers import (
    execute_agent,
    run_all_agents,
)
from src.compiler.executors.base import StageExecutor
from src.compiler.schemas import StageErrorHandlingConfig
from src.utils.config_helpers import get_nested_value


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
        # H-13: Shared shutdown event for interruptible retry waits
        self.shutdown_event = threading.Event()

    def execute_stage(
        self,
        stage_name: str,
        stage_config: Any,
        state: Dict[str, Any],
        config_loader: ConfigLoaderProtocol,
        tool_registry: Optional[DomainToolRegistryProtocol] = None,
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
            on_failure: Literal["halt_stage", "continue_with_remaining"] = (
                "halt_stage" if halt_on_failure else "continue_with_remaining"
            )
            error_handling_config = StageErrorHandlingConfig(on_agent_failure=on_failure)

        # Track stage execution if tracker available
        stage_config_dict = stage_config.model_dump() if hasattr(stage_config, 'model_dump') else stage_config

        if tracker:
            with tracker.track_stage(
                stage_name=stage_name,
                stage_config=stage_config_dict,
                workflow_id=workflow_id,
                input_data=state.get("stage_outputs", {})
            ) as stage_id:
                agent_outputs, agent_statuses, agent_metrics = run_all_agents(
                    executor=self,
                    agents=agents,
                    stage_id=stage_id,
                    stage_name=stage_name,
                    workflow_id=workflow_id,
                    state=state,
                    tracker=tracker,
                    config_loader=config_loader,
                    error_handling=error_handling_config,
                    agent_factory_cls=AgentFactory,
                )
        else:
            agent_outputs, agent_statuses, agent_metrics = run_all_agents(
                executor=self,
                agents=agents,
                stage_id=f"stage-{uuid.uuid4().hex[:UUID_HEX_SHORT_LENGTH]}",
                stage_name=stage_name,
                workflow_id=workflow_id,
                state=state,
                tracker=None,
                config_loader=config_loader,
                error_handling=error_handling_config,
                agent_factory_cls=AgentFactory,
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
                from src.strategies.base import AgentOutput
                agent_output_list = []
                for agent_name, output_data in agent_outputs.items():
                    agent_output_list.append(AgentOutput(
                        agent_name=agent_name,
                        decision=output_data.get("output", ""),
                        reasoning=output_data.get("reasoning", ""),
                        confidence=output_data.get("confidence", PROB_VERY_HIGH),
                        metadata=output_data.get("metadata", {})
                    ))

                synthesis_result = self._run_synthesis(
                    agent_output_list,
                    stage_config,
                    stage_name,
                    state=state,
                    config_loader=config_loader,
                    agents=agents
                )

                final_output = synthesis_result.decision

                logger.info(
                    f"Sequential stage {stage_name} used collaboration synthesis: "
                    f"{synthesis_result.method} (confidence={synthesis_result.confidence:.2f})"
                )

            except (RuntimeError, ConfigValidationError, ValueError, KeyError) as e:
                logger.warning(
                    f"Collaboration synthesis failed for sequential stage {stage_name}: {e}. "
                    f"Falling back to last agent output."
                )
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

        Delegates to helper function.
        """
        return execute_agent(
            executor=self,
            agent_ref=agent_ref,
            stage_id=stage_id,
            stage_name=stage_name,
            workflow_id=workflow_id,
            state=state,
            tracker=tracker,
            config_loader=config_loader,
            prior_agent_outputs=prior_agent_outputs,
            agent_factory_cls=AgentFactory,
        )
