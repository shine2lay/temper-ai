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
from src.compiler.executors.state_keys import StateKeys
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

    def _parse_stage_config(
        self, stage_config: Any, halt_on_failure: bool,
    ) -> tuple[list, Any]:
        """Extract agents list and error handling config from stage config."""
        error_handling_config = None
        if hasattr(stage_config, 'stage'):
            agents = stage_config.stage.agents
            if hasattr(stage_config.stage, 'error_handling'):
                error_handling_config = stage_config.stage.error_handling
        else:
            agents = get_nested_value(stage_config, 'stage.agents') or stage_config.get('agents', [])
            error_handling_dict = get_nested_value(stage_config, 'stage.error_handling')
            if error_handling_dict:
                error_handling_config = StageErrorHandlingConfig(**error_handling_dict)

        if error_handling_config is None:
            on_failure: Literal["halt_stage", "continue_with_remaining"] = (
                "halt_stage" if halt_on_failure else "continue_with_remaining"
            )
            error_handling_config = StageErrorHandlingConfig(on_agent_failure=on_failure)

        return agents, error_handling_config

    def _run_agents_tracked(
        self, agents: list, stage_name: str, state: Dict[str, Any],
        config_loader: ConfigLoaderProtocol, error_handling: Any,
        tracker: Any, workflow_id: str,
    ) -> tuple:
        """Run all agents with optional tracker context."""
        if tracker:
            stage_config_dict = state.get("_stage_config_dict", {})
            with tracker.track_stage(
                stage_name=stage_name, stage_config=stage_config_dict,
                workflow_id=workflow_id, input_data=state.get(StateKeys.STAGE_OUTPUTS, {}),
            ) as stage_id:
                # Store stage_id for dialogue synthesis tracking
                state[StateKeys.CURRENT_STAGE_ID] = stage_id
                return run_all_agents(
                    executor=self, agents=agents, stage_id=stage_id,
                    stage_name=stage_name, workflow_id=workflow_id, state=state,
                    tracker=tracker, config_loader=config_loader,
                    error_handling=error_handling, agent_factory_cls=AgentFactory,
                )
        return run_all_agents(
            executor=self, agents=agents,
            stage_id=f"stage-{uuid.uuid4().hex[:UUID_HEX_SHORT_LENGTH]}",
            stage_name=stage_name, workflow_id=workflow_id, state=state,
            tracker=None, config_loader=config_loader,
            error_handling=error_handling, agent_factory_cls=AgentFactory,
        )

    def _resolve_final_output(
        self, agent_outputs: Dict[str, Any], stage_config: Any,
        stage_name: str, state: Dict[str, Any],
        config_loader: ConfigLoaderProtocol, agents: list,
    ) -> tuple[str, Any]:
        """Determine final output via synthesis or last agent fallback."""
        collaboration_config = None
        if hasattr(stage_config, 'stage') and hasattr(stage_config.stage, 'collaboration'):
            collaboration_config = stage_config.stage.collaboration
        elif isinstance(stage_config, dict):
            collaboration_config = get_nested_value(stage_config, 'stage.collaboration')

        if collaboration_config and len(agent_outputs) > 1:
            try:
                from src.strategies.base import AgentOutput
                agent_output_list = [
                    AgentOutput(
                        agent_name=name,
                        decision=data.get(StateKeys.OUTPUT, ""),
                        reasoning=data.get(StateKeys.REASONING, ""),
                        confidence=data.get(StateKeys.CONFIDENCE, PROB_VERY_HIGH),
                        metadata=data.get("metadata", {}),
                    )
                    for name, data in agent_outputs.items()
                ]
                result = self._run_synthesis(
                    agent_output_list, stage_config, stage_name,
                    state=state, config_loader=config_loader, agents=agents,
                )
                logger.info(
                    "Sequential stage %s used collaboration synthesis: "
                    "%s (confidence=%.2f)", stage_name, result.method, result.confidence,
                )
                return result.decision, result
            except (RuntimeError, ConfigValidationError, ValueError, KeyError) as e:
                logger.warning(
                    "Collaboration synthesis failed for sequential stage %s: %s. "
                    "Falling back to last agent output.", stage_name, e,
                )

        # Concatenate all non-empty agent outputs (preserves all work
        # when multiple agents contribute, e.g. foundation + integration specs).
        parts = [
            data.get(StateKeys.OUTPUT, "")
            for data in agent_outputs.values()
            if data.get(StateKeys.OUTPUT)
        ]
        final_output = "\n\n".join(parts) if parts else ""
        return final_output, None

    @staticmethod
    def _store_stage_output(
        state: Dict[str, Any], stage_name: str,
        final_output: str, synthesis_result: Any,
        agent_outputs: Dict[str, Any], agent_statuses: Dict[str, Any],
        agent_metrics: Dict[str, Any], agents: list,
    ) -> None:
        """Build and store stage output in state."""
        if not isinstance(state.get(StateKeys.STAGE_OUTPUTS), dict):
            state[StateKeys.STAGE_OUTPUTS] = {}

        stage_output: Dict[str, Any] = {
            StateKeys.OUTPUT: final_output,
            StateKeys.AGENT_OUTPUTS: agent_outputs,
            StateKeys.AGENT_STATUSES: agent_statuses,
            StateKeys.AGENT_METRICS: agent_metrics,
        }
        if synthesis_result:
            stage_output["synthesis_result"] = {
                StateKeys.METHOD: synthesis_result.method,
                StateKeys.CONFIDENCE: synthesis_result.confidence,
                StateKeys.VOTES: getattr(synthesis_result, "votes", {}),
                "metadata": getattr(synthesis_result, "metadata", {}),
            }

        failed_count = sum(
            1 for s in agent_statuses.values()
            if (isinstance(s, dict) and s.get(StateKeys.STATUS) == "failed") or s == "failed"
        )
        total_count = len(agents)
        if failed_count == total_count and total_count > 0:
            stage_output[StateKeys.STAGE_STATUS] = "failed"
        elif failed_count > 0:
            stage_output[StateKeys.STAGE_STATUS] = "degraded"
        else:
            stage_output[StateKeys.STAGE_STATUS] = "completed"

        state[StateKeys.STAGE_OUTPUTS][stage_name] = stage_output
        state[StateKeys.CURRENT_STAGE] = stage_name

    def execute_stage(
        self,
        stage_name: str,
        stage_config: Any,
        state: Dict[str, Any],
        config_loader: ConfigLoaderProtocol,
        tool_registry: Optional[DomainToolRegistryProtocol] = None,
        halt_on_failure: bool = True
    ) -> Dict[str, Any]:
        """Execute stage with sequential agent execution. Returns updated state."""
        tracker = state.get(StateKeys.TRACKER)
        workflow_id = state.get(StateKeys.WORKFLOW_ID, "unknown")

        agents, error_handling = self._parse_stage_config(stage_config, halt_on_failure)

        state["_stage_config_dict"] = (
            stage_config.model_dump() if hasattr(stage_config, 'model_dump') else stage_config
        )
        agent_outputs, agent_statuses, agent_metrics = self._run_agents_tracked(
            agents, stage_name, state, config_loader, error_handling, tracker, workflow_id,
        )
        state.pop("_stage_config_dict", None)

        final_output, synthesis_result = self._resolve_final_output(
            agent_outputs, stage_config, stage_name, state, config_loader, agents,
        )

        self._store_stage_output(
            state, stage_name, final_output, synthesis_result,
            agent_outputs, agent_statuses, agent_metrics, agents,
        )

        # Persist stage output to DB for dashboard visibility
        stage_id = state.get(StateKeys.CURRENT_STAGE_ID)
        if tracker and stage_id and hasattr(tracker, 'set_stage_output'):
            try:
                stage_out = state.get(StateKeys.STAGE_OUTPUTS, {}).get(stage_name)
                if stage_out:
                    tracker.set_stage_output(stage_id, stage_out)
            except Exception:
                logger.warning("Failed to persist stage output", exc_info=True)

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
