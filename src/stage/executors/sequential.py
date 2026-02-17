"""Sequential stage executor.

Executes agents one after another in the order specified in the stage config.
Each agent's output is accumulated and passed to subsequent agents, enabling
agent-to-agent context sharing within a stage.
"""
import logging
import threading
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional

from src.shared.constants.probabilities import PROB_VERY_HIGH
from src.shared.constants.sizes import UUID_HEX_SHORT_LENGTH
from src.shared.utils.exceptions import (
    ConfigValidationError,
)

logger = logging.getLogger(__name__)


@dataclass
class StageOutputData:
    """Bundles stage output parameters for _store_stage_output."""
    final_output: str
    synthesis_result: Any
    agent_outputs: Dict[str, Any]
    agent_statuses: Dict[str, Any]
    agent_metrics: Dict[str, Any]
    agents: list


from src.agent.utils.agent_factory import AgentFactory
from src.shared.core.protocols import ConfigLoaderProtocol, DomainToolRegistryProtocol
from src.stage.executors._sequential_helpers import (
    AgentExecutionContext,
    execute_agent,
    run_all_agents,
)
from src.stage.executors.base import StageExecutor
from src.stage.executors.state_keys import StateKeys
from src.stage._schemas import StageErrorHandlingConfig
from src.shared.utils.config_helpers import get_nested_value


def _get_collaboration_config(stage_config: Any) -> Any:
    """Extract collaboration config from stage config."""
    if hasattr(stage_config, 'stage') and hasattr(stage_config.stage, 'collaboration'):
        return stage_config.stage.collaboration
    if isinstance(stage_config, dict):
        return get_nested_value(stage_config, 'stage.collaboration')
    return None


def _concatenate_agent_outputs(agent_outputs: Dict[str, Any]) -> str:
    """Concatenate all non-empty agent outputs."""
    parts = [
        data.get(StateKeys.OUTPUT, "")
        for data in agent_outputs.values()
        if data.get(StateKeys.OUTPUT)
    ]
    return "\n\n".join(parts) if parts else ""


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

    def _extract_agents_and_error_config(
        self, stage_config: Any,
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
            error_handling_config = StageErrorHandlingConfig(on_agent_failure="halt_stage")

        return agents, error_handling_config

    def _run_agents_tracked(
        self, agents: list, stage_name: str, state: Dict[str, Any],
        config_loader: ConfigLoaderProtocol, error_handling: Any,
        stage_config: Any = None,
    ) -> tuple:
        """Run all agents with optional tracker context."""
        tracker = state.get(StateKeys.TRACKER)
        workflow_id: str = state.get(StateKeys.WORKFLOW_ID, "unknown")
        if tracker:
            stage_config_dict = state.get("_stage_config_dict", {})
            with tracker.track_stage(
                stage_name=stage_name, stage_config=stage_config_dict,
                workflow_id=workflow_id, input_data=state.get(StateKeys.STAGE_OUTPUTS, {}),
            ) as stage_id:
                # Store stage_id for dialogue synthesis tracking
                state[StateKeys.CURRENT_STAGE_ID] = stage_id
                ctx = AgentExecutionContext(
                    executor=self, stage_id=stage_id, stage_name=stage_name,
                    workflow_id=workflow_id, state=state, tracker=tracker,
                    config_loader=config_loader, agent_factory_cls=AgentFactory,
                    context_provider=self.context_provider,
                    stage_config=stage_config,
                )
                return run_all_agents(
                    ctx=ctx, agents=agents, error_handling=error_handling,
                )
        stage_id = f"stage-{uuid.uuid4().hex[:UUID_HEX_SHORT_LENGTH]}"
        ctx = AgentExecutionContext(
            executor=self, stage_id=stage_id, stage_name=stage_name,
            workflow_id=workflow_id, state=state, tracker=None,
            config_loader=config_loader, agent_factory_cls=AgentFactory,
            context_provider=self.context_provider,
            stage_config=stage_config,
        )
        return run_all_agents(
            ctx=ctx, agents=agents, error_handling=error_handling,
        )

    def _resolve_final_output(
        self, agent_outputs: Dict[str, Any], stage_config: Any,
        stage_name: str, state: Dict[str, Any],
        config_loader: ConfigLoaderProtocol, agents: list,
    ) -> tuple[str, Any]:
        """Determine final output via synthesis or last agent fallback."""
        collaboration_config = _get_collaboration_config(stage_config)

        if collaboration_config and len(agent_outputs) > 1:
            result = self._try_synthesis(
                agent_outputs, stage_config, stage_name, state,
                config_loader, agents,
            )
            if result is not None:
                return result

        return _concatenate_agent_outputs(agent_outputs), None

    def _try_synthesis(
        self, agent_outputs: Dict[str, Any], stage_config: Any,
        stage_name: str, state: Dict[str, Any],
        config_loader: ConfigLoaderProtocol, agents: list,
    ) -> "tuple[str, Any] | None":
        """Attempt collaboration synthesis, returning None on failure."""
        try:
            from src.agent.strategies.base import AgentOutput

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
            return None

    @staticmethod
    def _store_stage_output(
        state: Dict[str, Any],
        stage_name: str,
        data: StageOutputData,
        structured: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Build and store stage output in two-compartment format.

        The output is stored as::

            stage_outputs[stage_name] = {
                "structured": { ... },      # extracted structured fields
                "raw": { output, agents },  # full execution data
                **raw_dict,                 # top-level compat aliases
            }

        Args:
            state: Current workflow state
            stage_name: Name of the stage
            data: Bundle of stage output data
            structured: Extracted structured fields (from OutputExtractor)
        """
        if not isinstance(state.get(StateKeys.STAGE_OUTPUTS), dict):
            state[StateKeys.STAGE_OUTPUTS] = {}

        # Build the raw dict (full execution data)
        raw_dict: Dict[str, Any] = {
            StateKeys.OUTPUT: data.final_output,
            StateKeys.AGENT_OUTPUTS: data.agent_outputs,
            StateKeys.AGENT_STATUSES: data.agent_statuses,
            StateKeys.AGENT_METRICS: data.agent_metrics,
        }
        if data.synthesis_result:
            raw_dict["synthesis_result"] = {
                StateKeys.METHOD: data.synthesis_result.method,
                StateKeys.CONFIDENCE: data.synthesis_result.confidence,
                StateKeys.VOTES: getattr(data.synthesis_result, "votes", {}),
                "metadata": getattr(data.synthesis_result, "metadata", {}),
            }

        failed_count = sum(
            1 for s in data.agent_statuses.values()
            if (isinstance(s, dict) and s.get(StateKeys.STATUS) == "failed") or s == "failed"
        )
        total_count = len(data.agents)
        if failed_count == total_count and total_count > 0:
            raw_dict[StateKeys.STAGE_STATUS] = "failed"
        elif failed_count > 0:
            raw_dict[StateKeys.STAGE_STATUS] = "degraded"
        else:
            raw_dict[StateKeys.STAGE_STATUS] = "completed"

        # Two-compartment format with top-level compat aliases
        stage_entry: Dict[str, Any] = {
            "structured": structured or {},
            "raw": dict(raw_dict),
            **raw_dict,  # Top-level compat for condition expressions
        }

        # Propagate context metadata from stage input if available
        context_meta = state.get("_context_meta")
        if context_meta is not None:
            stage_entry["_context_meta"] = context_meta

        state[StateKeys.STAGE_OUTPUTS][stage_name] = stage_entry
        state[StateKeys.CURRENT_STAGE] = stage_name

    def execute_stage(
        self,
        stage_name: str,
        stage_config: Any,
        state: Dict[str, Any],
        config_loader: ConfigLoaderProtocol,
        tool_registry: Optional[DomainToolRegistryProtocol] = None,
    ) -> Dict[str, Any]:
        """Execute stage with sequential agent execution. Returns updated state."""
        tracker = state.get(StateKeys.TRACKER)

        agents, error_handling = self._extract_agents_and_error_config(stage_config)

        state["_stage_config_dict"] = (
            stage_config.model_dump() if hasattr(stage_config, 'model_dump') else stage_config
        )
        agent_outputs, agent_statuses, agent_metrics = self._run_agents_tracked(
            agents, stage_name, state, config_loader, error_handling,
            stage_config=stage_config,
        )
        state.pop("_stage_config_dict", None)

        final_output, synthesis_result = self._resolve_final_output(
            agent_outputs, stage_config, stage_name, state, config_loader, agents,
        )

        output_data = StageOutputData(
            final_output=final_output,
            synthesis_result=synthesis_result,
            agent_outputs=agent_outputs,
            agent_statuses=agent_statuses,
            agent_metrics=agent_metrics,
            agents=agents,
        )
        structured = self._extract_structured_fields(
            stage_config, final_output, stage_name,
        )
        self._store_stage_output(state, stage_name, output_data, structured=structured)

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
        ctx: AgentExecutionContext,
        agent_ref: Any,
        prior_agent_outputs: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute a single agent and return structured result.

        Args:
            ctx: Agent execution context bundle
            agent_ref: Agent reference from stage config
            prior_agent_outputs: Outputs from prior agents in the same stage

        Returns:
            Dict with keys: agent_name, output_data, status, metrics

        Note:
            Delegates to helper function. This wrapper exists for potential
            external callers that need a class method interface.
        """
        return execute_agent(
            ctx=ctx,
            agent_ref=agent_ref,
            prior_agent_outputs=prior_agent_outputs,
        )
