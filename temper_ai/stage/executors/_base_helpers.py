"""Extracted helpers for StageExecutor.

Contains agent execution infrastructure (tracking, context creation,
conversation persistence) and re-exports dialogue helpers for backward
compatibility.
"""
import logging
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional

from temper_ai.shared.constants.execution import (
    AGENT_ROLE_LEADER,
    STATUS_UNKNOWN,
)
from temper_ai.shared.core.protocols import ConfigLoaderProtocol
from temper_ai.stage.executors.state_keys import StateKeys
from temper_ai.shared.constants.sizes import UUID_HEX_SHORT_LENGTH
from temper_ai.shared.utils.config_helpers import sanitize_config_for_display

# Re-export dialogue helpers for backward compatibility
from temper_ai.stage.executors._dialogue_helpers import (  # noqa: F401
    DialogueReinvocationParams,
    DialogueRoundParams,
    DialogueTrackingParams,
    SingleDialogueAgentParams,
    FinalSynthesisResultParams,
    DialogueRoundsParams,
    _extract_agent_role,
    _prepare_dialogue_input,
    _curate_history_and_resolve_context,
    _invoke_single_dialogue_agent,
    reinvoke_agents_with_dialogue,
    fallback_consensus_synthesis,
    record_dialogue_outputs_and_cost,
    track_dialogue_round,
    _build_dialogue_event_data,
    _enrich_with_round_metrics,
    check_dialogue_convergence,
    execute_dialogue_round,
    run_dialogue_rounds,
    record_initial_round,
    build_final_synthesis_result,
)

logger = logging.getLogger(__name__)


@dataclass
class AgentExecutionParams:
    """Parameters for agent execution with or without tracking."""
    agent: Any
    input_data: Dict[str, Any]
    current_stage_id: str
    stage_name: str
    agent_name: str
    state: Dict[str, Any]
    execution_mode: str
    tracker: Optional[Any] = None
    agent_config: Optional[Any] = None
    agent_config_dict: Optional[Dict[str, Any]] = None
    tracking_input: Optional[Dict[str, Any]] = None
    extra_metadata: Optional[Dict[str, Any]] = None


# Backward-compatible alias
AgentExecutionParamsNoTracking = AgentExecutionParams


def _save_conversation_turn(
    state: Dict[str, Any],
    history_key: str,
    input_data: Dict[str, Any],
    response: Any,
) -> None:
    """Persist the user/assistant turn into state conversation histories."""
    from temper_ai.llm.conversation import ConversationHistory

    assistant_output = getattr(response, "output", None)
    if not assistant_output:
        return

    user_prompt = getattr(response, "metadata", {}).get("_user_message")
    if not user_prompt:
        user_prompt = getattr(response, "metadata", {}).get("_rendered_prompt", "")

    if StateKeys.CONVERSATION_HISTORIES not in state:
        state[StateKeys.CONVERSATION_HISTORIES] = {}

    history = input_data.get("_conversation_history")
    if history is None:
        history = ConversationHistory()

    history.append_turn(
        user_content=user_prompt or "",
        assistant_content=assistant_output,
    )
    state[StateKeys.CONVERSATION_HISTORIES][history_key] = history.to_dict()


def prepare_tracking_input(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """Filter non-serializable keys and sanitize input for tracking."""
    filtered = {k: v for k, v in input_data.items() if k not in StateKeys.NON_SERIALIZABLE_KEYS}
    result = sanitize_config_for_display(filtered)
    return _truncate_tracking_data(result)


def build_agent_output_params(agent_id: str, response: Any) -> Any:
    """Build AgentOutputParams from an agent response."""
    from temper_ai.observability.metric_aggregator import AgentOutputParams
    return AgentOutputParams(
        agent_id=agent_id,
        output_data={StateKeys.OUTPUT: response.output},
        reasoning=response.reasoning,
        total_tokens=response.tokens,
        estimated_cost_usd=response.estimated_cost_usd,
        num_llm_calls=1 if response.tokens and response.tokens > 0 else 0,
        num_tool_calls=len(response.tool_calls) if response.tool_calls else 0,
    )


def _create_execution_context(
    state: Dict[str, Any],
    current_stage_id: str,
    agent_id: str,
    stage_name: str,
    agent_name: str,
    execution_mode: str,
    extra_metadata: Optional[Dict[str, Any]] = None,
) -> Any:
    """Create an ExecutionContext with standard metadata."""
    from temper_ai.shared.core.context import ExecutionContext

    metadata: Dict[str, Any] = {
        "stage_name": stage_name,
        "agent_name": agent_name,
        "execution_mode": execution_mode,
    }
    if extra_metadata:
        metadata.update(extra_metadata)

    return ExecutionContext(
        workflow_id=state.get(StateKeys.WORKFLOW_ID, STATUS_UNKNOWN),
        stage_id=current_stage_id,
        agent_id=agent_id,
        metadata=metadata,
    )


MAX_TRACKING_INPUT_BYTES = 400 * 1024  # scanner: skip-magic — 400KB, safely under 0.5MB DB limit


def _truncate_tracking_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """Truncate tracking input data to fit within DB size limits.

    Stage outputs accumulate across pipeline stages and can exceed the
    0.5MB input_data limit in the SQL backend. This truncates large
    stage_outputs values to keep the tracking data within bounds.
    """
    import json
    try:
        serialized = json.dumps(data, separators=(',', ':'), default=str)
    except (TypeError, ValueError):
        return data

    if len(serialized.encode('utf-8')) <= MAX_TRACKING_INPUT_BYTES:
        return data

    # Truncate stage_outputs values (largest contributor)
    truncated = dict(data)
    stage_outputs = truncated.get(StateKeys.STAGE_OUTPUTS)
    if isinstance(stage_outputs, dict):
        truncated_outputs: Dict[str, Any] = {}
        for stage_name, output in stage_outputs.items():
            output_str = json.dumps(output, separators=(',', ':'), default=str)
            if len(output_str) > 1024:  # noqa  # scanner: skip-magic
                truncated_outputs[stage_name] = f"[truncated: {len(output_str)} bytes]"
            else:
                truncated_outputs[stage_name] = output
        truncated[StateKeys.STAGE_OUTPUTS] = truncated_outputs

    return truncated


def _record_agent_tracking(
    tracker: Any,
    agent_id: str,
    response: Any,
    agent_name: str,
    label: str,
) -> None:
    """Record agent output in tracker, logging on failure."""
    try:
        from temper_ai.observability.metric_aggregator import AgentOutputParams
        tracker.set_agent_output(AgentOutputParams(
            agent_id=agent_id,
            output_data={StateKeys.OUTPUT: response.output},
            reasoning=response.reasoning,
            total_tokens=response.tokens,
            estimated_cost_usd=response.estimated_cost_usd,
            num_llm_calls=1 if response.tokens and response.tokens > 0 else 0,
            num_tool_calls=len(response.tool_calls) if response.tool_calls else 0,
        ))
    except Exception:
        logger.warning(
            "Failed to set agent output tracking for %s agent %s",
            label,
            agent_name,
            exc_info=True,
        )


def _get_stage_id(state: Dict[str, Any]) -> str:
    """Return current_stage_id from state or generate a new one."""
    return state.get(StateKeys.CURRENT_STAGE_ID) or f"stage-{uuid.uuid4().hex[:UUID_HEX_SHORT_LENGTH]}"


def _execute_agent_with_tracking(params: AgentExecutionParams) -> Any:
    """Execute agent under tracker context and record output."""
    from temper_ai.stage.executors._agent_execution import config_to_tracking_dict

    config_dict = params.agent_config_dict or {}
    agent_config_for_tracking = sanitize_config_for_display(
        config_to_tracking_dict(params.agent_config, config_dict)
    )
    tracker = params.tracker
    assert tracker is not None, "_execute_agent_with_tracking requires a tracker"
    with tracker.track_agent(
        agent_name=params.agent_name,
        agent_config=agent_config_for_tracking,
        stage_id=params.current_stage_id,
        input_data=params.tracking_input,
    ) as agent_id:
        context = _create_execution_context(
            params.state, params.current_stage_id, agent_id,
            params.stage_name, params.agent_name, params.execution_mode, params.extra_metadata,
        )
        response = params.agent.execute(params.input_data, context)
        _record_agent_tracking(params.tracker, agent_id, response, params.agent_name, params.execution_mode)
    return response


def _execute_agent_without_tracking(params: AgentExecutionParams) -> Any:
    """Execute agent without tracker (synthetic IDs)."""
    params.input_data.pop(StateKeys.TRACKER, None)
    agent_id = f"agent-{uuid.uuid4().hex[:UUID_HEX_SHORT_LENGTH]}"
    context = _create_execution_context(
        params.state, params.current_stage_id, agent_id,
        params.stage_name, params.agent_name, params.execution_mode, params.extra_metadata,
    )
    return params.agent.execute(params.input_data, context)


def _build_agent_output(
    agent_name: str,
    response: Any,
    role: str = AGENT_ROLE_LEADER,
    extra_metadata: Optional[Dict[str, Any]] = None,
) -> Any:
    """Build an AgentOutput from an agent response."""
    from temper_ai.agent.strategies.base import AgentOutput

    metadata: Dict[str, Any] = {
        StateKeys.TOKENS: response.tokens,
        StateKeys.COST_USD: response.estimated_cost_usd,
        "role": role,
    }
    if extra_metadata:
        metadata.update(extra_metadata)

    return AgentOutput(
        agent_name=agent_name,
        decision=response.output,
        reasoning=response.reasoning or "",
        confidence=response.confidence or 0.0,
        metadata=metadata,
    )


def invoke_leader_agent(
    leader_name: str,
    team_outputs_text: str,
    stage_name: str,
    state: Dict[str, Any],
    config_loader: ConfigLoaderProtocol,
) -> Any:
    """Invoke the leader agent with team outputs injected."""
    from temper_ai.agent.utils.agent_factory import AgentFactory
    from temper_ai.storage.schemas.agent_config import AgentConfig

    agent_config_dict = config_loader.load_agent(leader_name)
    agent_config = AgentConfig(**agent_config_dict)
    agent = AgentFactory.create(agent_config)

    input_data = {**state, "team_outputs": team_outputs_text}
    tracker = state.get(StateKeys.TRACKER)
    current_stage_id = _get_stage_id(state)
    tracking_input = {"role": AGENT_ROLE_LEADER, "team_outputs_length": len(team_outputs_text)}

    exec_params = AgentExecutionParams(
        agent=agent, input_data=input_data, current_stage_id=current_stage_id,
        stage_name=stage_name, agent_name=leader_name, state=state,
        execution_mode=AGENT_ROLE_LEADER, tracker=tracker,
        agent_config=agent_config, agent_config_dict=agent_config_dict,
        tracking_input=tracking_input,
    )
    if tracker:
        response = _execute_agent_with_tracking(exec_params)
    else:
        response = _execute_agent_without_tracking(exec_params)

    return _build_agent_output(leader_name, response)
