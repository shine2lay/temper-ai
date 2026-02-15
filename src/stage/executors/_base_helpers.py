"""Extracted helpers for StageExecutor.

Contains large standalone functions that were extracted from StageExecutor
to keep the class within the 500-line threshold. These functions operate
on explicit parameters and do not depend on StageExecutor instance state.
"""
import logging
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.workflow.constants import (
    AGENT_ROLE_LEADER,
    STATUS_UNKNOWN,
)
from src.workflow.domain_state import ConfigLoaderProtocol
from src.stage.executors.state_keys import StateKeys
from src.shared.constants.sizes import UUID_HEX_SHORT_LENGTH
from src.shared.utils.config_helpers import sanitize_config_for_display

logger = logging.getLogger(__name__)


@dataclass
class DialogueReinvocationParams:
    """Parameters for dialogue agent re-invocation (reduces 9 params to 1)."""
    agents: list
    stage_name: str
    state: Dict[str, Any]
    config_loader: ConfigLoaderProtocol
    dialogue_history: list
    round_number: int
    max_rounds: int
    strategy: Any
    extract_agent_name_fn: Callable[[Any], str]


@dataclass
class AgentExecutionParams:
    """Parameters for agent execution with tracking (reduces 12 params to 7)."""
    agent: Any
    input_data: Dict[str, Any]
    tracker: Any
    agent_config: Any
    agent_config_dict: Dict[str, Any]
    current_stage_id: str
    stage_name: str
    agent_name: str
    state: Dict[str, Any]
    execution_mode: str
    tracking_input: Dict[str, Any]
    extra_metadata: Optional[Dict[str, Any]] = None


@dataclass
class AgentExecutionParamsNoTracking:
    """Parameters for agent execution without tracking (reduces 8 params to 7)."""
    agent: Any
    input_data: Dict[str, Any]
    current_stage_id: str
    stage_name: str
    agent_name: str
    state: Dict[str, Any]
    execution_mode: str
    extra_metadata: Optional[Dict[str, Any]] = None


@dataclass
class DialogueRoundParams:
    """Parameters for dialogue round execution (reduces 10 params to 7)."""
    round_num: int
    reinvoke_fn: Callable[..., Tuple[list, Dict[str, Any]]]
    agents: list
    strategy: Any
    stage_name: str
    state: Dict[str, Any]
    config_loader: ConfigLoaderProtocol
    tracker: Any
    dialogue_history: List[Dict[str, Any]]
    previous_outputs: list


@dataclass
class DialogueTrackingParams:
    """Parameters for dialogue round tracking (reduces 8 params to 7)."""
    tracker: Any
    strategy: Any
    state: Dict[str, Any]
    current_outputs: list
    round_num: int
    round_outcome: str
    conv_score: Optional[float] = None
    agent_stances: Optional[Dict[str, str]] = None


@dataclass
class SingleDialogueAgentParams:
    """Parameters for single dialogue agent invocation (reduces 9 params to 7)."""
    agent_name: str
    agent_ref: Any
    config_loader: ConfigLoaderProtocol
    state: Dict[str, Any]
    stage_name: str
    dialogue_history: list
    round_number: int
    max_rounds: int
    strategy: Any


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
    from src.shared.core.context import ExecutionContext

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
        from src.observability.metric_aggregator import AgentOutputParams
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
    agent_config_for_tracking = sanitize_config_for_display(
        params.agent_config.model_dump() if hasattr(params.agent_config, 'model_dump') else dict(params.agent_config_dict)
    )
    with params.tracker.track_agent(
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


def _execute_agent_without_tracking(params: AgentExecutionParamsNoTracking) -> Any:
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
    from src.agent.strategies.base import AgentOutput

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
    """Invoke the leader agent with team outputs injected.

    Args:
        leader_name: Leader agent name
        team_outputs_text: Formatted perspective outputs
        stage_name: Stage name
        state: Workflow state
        config_loader: Config loader

    Returns:
        AgentOutput from the leader agent
    """
    from src.agent.utils.agent_factory import AgentFactory
    from src.storage.schemas.agent_config import AgentConfig

    agent_config_dict = config_loader.load_agent(leader_name)
    agent_config = AgentConfig(**agent_config_dict)
    agent = AgentFactory.create(agent_config)

    input_data = {**state, "team_outputs": team_outputs_text}
    tracker = state.get(StateKeys.TRACKER)
    current_stage_id = _get_stage_id(state)
    tracking_input = {"role": AGENT_ROLE_LEADER, "team_outputs_length": len(team_outputs_text)}

    if tracker:
        exec_params = AgentExecutionParams(
            agent=agent, input_data=input_data, tracker=tracker,
            agent_config=agent_config, agent_config_dict=agent_config_dict,
            current_stage_id=current_stage_id, stage_name=stage_name,
            agent_name=leader_name, state=state,
            execution_mode=AGENT_ROLE_LEADER, tracking_input=tracking_input,
        )
        response = _execute_agent_with_tracking(exec_params)
    else:
        exec_params_no_track = AgentExecutionParamsNoTracking(
            agent=agent, input_data=input_data, current_stage_id=current_stage_id,
            stage_name=stage_name, agent_name=leader_name, state=state,
            execution_mode=AGENT_ROLE_LEADER,
        )
        response = _execute_agent_without_tracking(exec_params_no_track)

    return _build_agent_output(leader_name, response)


def _extract_agent_role(agent_config: Any) -> Optional[str]:
    """Extract role from agent config metadata."""
    agent_role = None
    if hasattr(agent_config.agent, 'metadata') and agent_config.agent.metadata:
        if agent_config.agent.metadata.tags:
            agent_role = agent_config.agent.metadata.tags[0]
        if hasattr(agent_config.agent.metadata, 'role'):
            agent_role = agent_config.agent.metadata.role
    return agent_role


def _prepare_dialogue_input(
    state: Dict[str, Any],
    curated_history: list,
    round_number: int,
    max_rounds: int,
    agent_role: Optional[str],
    mode_context: Dict[str, Any],
) -> Dict[str, Any]:
    """Build enriched input data for a dialogue round agent invocation."""
    return {
        **state,
        "dialogue_history": curated_history,
        "round_number": round_number,
        "max_rounds": max_rounds,
        "agent_role": agent_role,
        **mode_context,
    }


def _curate_and_get_context(
    strategy: Any,
    dialogue_history: list,
    round_number: int,
    agent_name: str,
) -> Tuple[list, Dict[str, Any]]:
    """Curate dialogue history and get mode-specific context from strategy."""
    curated_history = dialogue_history
    if strategy and hasattr(strategy, 'curate_dialogue_history'):
        curated_history = strategy.curate_dialogue_history(
            dialogue_history=dialogue_history,
            current_round=round_number,
            agent_name=agent_name,
        )

    mode_context: Dict[str, Any] = {}
    if strategy and hasattr(strategy, 'get_round_context'):
        mode_context = strategy.get_round_context(round_number, agent_name)

    return curated_history, mode_context


def _invoke_single_dialogue_agent(params: SingleDialogueAgentParams) -> Tuple[Any, Any]:
    """Invoke a single agent for a dialogue round.

    Returns:
        Tuple of (AgentOutput, llm_provider)
    """
    from src.agent.utils.agent_factory import AgentFactory
    from src.storage.schemas.agent_config import AgentConfig

    agent_config_dict = params.config_loader.load_agent(params.agent_name)
    agent_config = AgentConfig(**agent_config_dict)
    agent = AgentFactory.create(agent_config)

    agent_role = _extract_agent_role(agent_config)
    curated_history, mode_context = _curate_and_get_context(
        params.strategy, params.dialogue_history, params.round_number, params.agent_name,
    )
    input_data = _prepare_dialogue_input(
        params.state, curated_history, params.round_number, params.max_rounds, agent_role, mode_context,
    )

    tracker = params.state.get(StateKeys.TRACKER)
    current_stage_id = _get_stage_id(params.state)
    extra_meta = {"round": params.round_number}
    tracking_input = {"round": params.round_number, "max_rounds": params.max_rounds}

    if tracker:
        exec_params = AgentExecutionParams(
            agent=agent, input_data=input_data, tracker=tracker,
            agent_config=agent_config, agent_config_dict=agent_config_dict,
            current_stage_id=current_stage_id, stage_name=params.stage_name,
            agent_name=params.agent_name, state=params.state,
            execution_mode="dialogue", tracking_input=tracking_input,
            extra_metadata=extra_meta,
        )
        response = _execute_agent_with_tracking(exec_params)
    else:
        exec_params_no_track = AgentExecutionParamsNoTracking(
            agent=agent, input_data=input_data, current_stage_id=current_stage_id,
            stage_name=params.stage_name, agent_name=params.agent_name,
            state=params.state, execution_mode="dialogue", extra_metadata=extra_meta,
        )
        response = _execute_agent_without_tracking(exec_params_no_track)

    output = _build_agent_output(
        params.agent_name, response, role="dialogue",
        extra_metadata={"round": params.round_number},
    )
    return output, agent.llm


def reinvoke_agents_with_dialogue(
    params: DialogueReinvocationParams,
) -> Tuple[list, Dict[str, Any]]:
    """Re-invoke agents with dialogue history as context.

    Args:
        params: DialogueReinvocationParams bundle containing all needed parameters

    Returns:
        Tuple of (agent_outputs, llm_providers) where llm_providers
        maps agent_name -> LLM provider for stance extraction.
    """
    agent_outputs: list = []
    llm_providers: Dict[str, Any] = {}

    for agent_ref in params.agents:
        agent_name = params.extract_agent_name_fn(agent_ref)
        single_agent_params = SingleDialogueAgentParams(
            agent_name=agent_name, agent_ref=agent_ref,
            config_loader=params.config_loader, state=params.state,
            stage_name=params.stage_name, dialogue_history=params.dialogue_history,
            round_number=params.round_number, max_rounds=params.max_rounds,
            strategy=params.strategy,
        )
        output, llm = _invoke_single_dialogue_agent(single_agent_params)
        agent_outputs.append(output)
        llm_providers[agent_name] = llm

    return agent_outputs, llm_providers


def fallback_consensus_synthesis(agent_outputs: list) -> Any:
    """Fallback consensus synthesis when strategy registry is unavailable."""
    from src.shared.constants.probabilities import PROB_MEDIUM
    from src.agent.strategies.base import (
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
        metadata={"fallback": True},
    )


def record_dialogue_round_outputs(
    current_outputs: list,
    round_num: int,
    agent_stances: Dict[str, str],
    dialogue_history: List[Dict[str, Any]],
) -> float:
    """Record outputs from a dialogue round into history.

    Returns:
        Round cost (sum of agent costs this round).
    """
    round_cost = 0.0
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
        round_cost += output.metadata.get(StateKeys.COST_USD, 0.0)
    return round_cost


def track_dialogue_round(params: DialogueTrackingParams) -> None:
    """Track dialogue round collaboration event."""
    if not (params.tracker and hasattr(params.tracker, 'track_collaboration_event')):
        return

    try:
        agent_names = [o.agent_name for o in params.current_outputs]
        event_data: Dict[str, Any] = {
            "agent_count": len(agent_names),
            "avg_confidence": (
                sum(o.confidence for o in params.current_outputs) / len(params.current_outputs)
                if params.current_outputs else 0.0
            ),
        }

        if params.agent_stances:
            stance_dist: Dict[str, int] = {}
            for s in params.agent_stances.values():
                if s:
                    stance_dist[s] = stance_dist.get(s, 0) + 1
            event_data["stance_distribution"] = stance_dist
            event_data["agent_stances"] = params.agent_stances

        from src.observability._tracker_helpers import CollaborationEventData
        params.tracker.track_collaboration_event(CollaborationEventData(
            event_type=f"{params.strategy.mode}_round",
            stage_id=params.state.get(StateKeys.CURRENT_STAGE_ID),
            agents_involved=agent_names,
            round_number=params.round_num,
            outcome=params.round_outcome,
            confidence_score=params.conv_score,
            event_data=event_data,
        ))
    except Exception:
        logger.warning(
            "Failed to track round %d collaboration event",
            params.round_num,
            exc_info=True,
        )


def check_dialogue_convergence(
    strategy: Any,
    current_outputs: list,
    previous_outputs: list,
    round_num: int,
    stage_name: str,
) -> Tuple[Optional[float], bool, str]:
    """Check convergence after min_rounds.

    Returns:
        Tuple of (conv_score, converged, round_outcome)
    """
    from src.workflow.constants import ERROR_MSG_FOR_STAGE_SUFFIX

    conv_score = strategy.calculate_convergence(current_outputs, previous_outputs)
    logger.info(
        f"Dialogue round {round_num + 1}{ERROR_MSG_FOR_STAGE_SUFFIX}{stage_name}': "
        f"convergence {conv_score:.1%} "
        f"(threshold: {strategy.convergence_threshold:.1%})"
    )

    if conv_score >= strategy.convergence_threshold:
        logger.info(
            f"Dialogue converged at round {round_num + 1} for "
            f"stage '{stage_name}': {conv_score:.1%} >= "
            f"{strategy.convergence_threshold:.1%}"
        )
        return conv_score, True, "converged"

    return conv_score, False, "in_progress"


def execute_dialogue_round(params: DialogueRoundParams) -> Tuple[list, float, Optional[float], bool, int, str]:
    """Execute a single dialogue round: re-invoke, record, check convergence.

    Returns:
        Tuple of (current_outputs, round_cost, conv_score, converged, convergence_round, round_outcome)
    """
    current_outputs, llm_providers = params.reinvoke_fn(
        agents=params.agents, stage_name=params.stage_name, state=params.state,
        config_loader=params.config_loader, dialogue_history=params.dialogue_history,
        round_number=params.round_num, max_rounds=params.strategy.max_rounds, strategy=params.strategy,
    )

    agent_stances: Dict[str, str] = {}
    if hasattr(params.strategy, 'extract_stances'):
        agent_stances = params.strategy.extract_stances(current_outputs, llm_providers)

    round_cost = record_dialogue_round_outputs(
        current_outputs, params.round_num, agent_stances, params.dialogue_history,
    )

    conv_score: Optional[float] = None
    converged = False
    convergence_round = -1
    round_outcome = "in_progress"

    if params.round_num >= params.strategy.min_rounds:
        conv_score, converged, round_outcome = check_dialogue_convergence(
            params.strategy, current_outputs, params.previous_outputs, params.round_num, params.stage_name,
        )
        if converged:
            convergence_round = params.round_num

    track_params = DialogueTrackingParams(
        tracker=params.tracker, strategy=params.strategy, state=params.state,
        current_outputs=current_outputs, round_num=params.round_num,
        round_outcome=round_outcome, conv_score=conv_score, agent_stances=agent_stances,
    )
    track_dialogue_round(track_params)

    return current_outputs, round_cost, conv_score, converged, convergence_round, round_outcome
