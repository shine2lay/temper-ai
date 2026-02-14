"""Extracted helpers for StageExecutor.

Contains large standalone functions that were extracted from StageExecutor
to keep the class within the 500-line threshold. These functions operate
on explicit parameters and do not depend on StageExecutor instance state.
"""
import logging
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.compiler.constants import (
    AGENT_ROLE_LEADER,
    STATUS_UNKNOWN,
)
from src.compiler.domain_state import ConfigLoaderProtocol
from src.compiler.executors.state_keys import StateKeys
from src.constants.sizes import UUID_HEX_SHORT_LENGTH
from src.utils.config_helpers import sanitize_config_for_display

logger = logging.getLogger(__name__)


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
    from src.core.context import ExecutionContext

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


def _record_agent_tracking(
    tracker: Any,
    agent_id: str,
    response: Any,
    agent_name: str,
    label: str,
) -> None:
    """Record agent output in tracker, logging on failure."""
    try:
        tracker.set_agent_output(
            agent_id=agent_id,
            output_data={StateKeys.OUTPUT: response.output},
            reasoning=response.reasoning,
            total_tokens=response.tokens,
            estimated_cost_usd=response.estimated_cost_usd,
            num_llm_calls=1 if response.tokens and response.tokens > 0 else 0,
            num_tool_calls=len(response.tool_calls) if response.tool_calls else 0,
        )
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


def _execute_agent_with_tracking(
    agent: Any,
    input_data: Dict[str, Any],
    tracker: Any,
    agent_config: Any,
    agent_config_dict: Dict[str, Any],
    current_stage_id: str,
    stage_name: str,
    agent_name: str,
    state: Dict[str, Any],
    execution_mode: str,
    tracking_input: Dict[str, Any],
    extra_metadata: Optional[Dict[str, Any]] = None,
) -> Any:
    """Execute agent under tracker context and record output."""
    agent_config_for_tracking = sanitize_config_for_display(
        agent_config.model_dump() if hasattr(agent_config, 'model_dump') else dict(agent_config_dict)
    )
    with tracker.track_agent(
        agent_name=agent_name,
        agent_config=agent_config_for_tracking,
        stage_id=current_stage_id,
        input_data=tracking_input,
    ) as agent_id:
        context = _create_execution_context(
            state, current_stage_id, agent_id,
            stage_name, agent_name, execution_mode, extra_metadata,
        )
        response = agent.execute(input_data, context)
        _record_agent_tracking(tracker, agent_id, response, agent_name, execution_mode)
    return response


def _execute_agent_without_tracking(
    agent: Any,
    input_data: Dict[str, Any],
    current_stage_id: str,
    stage_name: str,
    agent_name: str,
    state: Dict[str, Any],
    execution_mode: str,
    extra_metadata: Optional[Dict[str, Any]] = None,
) -> Any:
    """Execute agent without tracker (synthetic IDs)."""
    input_data.pop(StateKeys.TRACKER, None)
    agent_id = f"agent-{uuid.uuid4().hex[:UUID_HEX_SHORT_LENGTH]}"
    context = _create_execution_context(
        state, current_stage_id, agent_id,
        stage_name, agent_name, execution_mode, extra_metadata,
    )
    return agent.execute(input_data, context)


def _build_agent_output(
    agent_name: str,
    response: Any,
    role: str = AGENT_ROLE_LEADER,
    extra_metadata: Optional[Dict[str, Any]] = None,
) -> Any:
    """Build an AgentOutput from an agent response."""
    from src.strategies.base import AgentOutput

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
    from src.agents.agent_factory import AgentFactory
    from src.compiler.schemas import AgentConfig

    agent_config_dict = config_loader.load_agent(leader_name)
    agent_config = AgentConfig(**agent_config_dict)
    agent = AgentFactory.create(agent_config)

    input_data = {**state, "team_outputs": team_outputs_text}
    tracker = state.get(StateKeys.TRACKER)
    current_stage_id = _get_stage_id(state)
    tracking_input = {"role": AGENT_ROLE_LEADER, "team_outputs_length": len(team_outputs_text)}

    if tracker:
        response = _execute_agent_with_tracking(
            agent, input_data, tracker, agent_config, agent_config_dict,
            current_stage_id, stage_name, leader_name, state,
            AGENT_ROLE_LEADER, tracking_input,
        )
    else:
        response = _execute_agent_without_tracking(
            agent, input_data, current_stage_id,
            stage_name, leader_name, state, AGENT_ROLE_LEADER,
        )

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


def _invoke_single_dialogue_agent(
    agent_name: str,
    agent_ref: Any,
    config_loader: ConfigLoaderProtocol,
    state: Dict[str, Any],
    stage_name: str,
    dialogue_history: list,
    round_number: int,
    max_rounds: int,
    strategy: Any,
) -> Tuple[Any, Any]:
    """Invoke a single agent for a dialogue round.

    Returns:
        Tuple of (AgentOutput, llm_provider)
    """
    from src.agents.agent_factory import AgentFactory
    from src.compiler.schemas import AgentConfig

    agent_config_dict = config_loader.load_agent(agent_name)
    agent_config = AgentConfig(**agent_config_dict)
    agent = AgentFactory.create(agent_config)

    agent_role = _extract_agent_role(agent_config)
    curated_history, mode_context = _curate_and_get_context(
        strategy, dialogue_history, round_number, agent_name,
    )
    input_data = _prepare_dialogue_input(
        state, curated_history, round_number, max_rounds, agent_role, mode_context,
    )

    tracker = state.get(StateKeys.TRACKER)
    current_stage_id = _get_stage_id(state)
    extra_meta = {"round": round_number}
    tracking_input = {"round": round_number, "max_rounds": max_rounds}

    if tracker:
        response = _execute_agent_with_tracking(
            agent, input_data, tracker, agent_config, agent_config_dict,
            current_stage_id, stage_name, agent_name, state,
            "dialogue", tracking_input, extra_meta,
        )
    else:
        response = _execute_agent_without_tracking(
            agent, input_data, current_stage_id,
            stage_name, agent_name, state, "dialogue", extra_meta,
        )

    output = _build_agent_output(
        agent_name, response, role="dialogue",
        extra_metadata={"round": round_number},
    )
    return output, agent.llm  # type: ignore[attr-defined]


def reinvoke_agents_with_dialogue(
    agents: list,
    stage_name: str,
    state: Dict[str, Any],
    config_loader: ConfigLoaderProtocol,
    dialogue_history: list,
    round_number: int,
    max_rounds: int,
    strategy: Any,
    extract_agent_name_fn: Callable[[Any], str],
) -> Tuple[list, Dict[str, Any]]:
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
        extract_agent_name_fn: Callable to extract agent name from ref

    Returns:
        Tuple of (agent_outputs, llm_providers) where llm_providers
        maps agent_name -> LLM provider for stance extraction.
    """
    agent_outputs: list = []
    llm_providers: Dict[str, Any] = {}

    for agent_ref in agents:
        agent_name = extract_agent_name_fn(agent_ref)
        output, llm = _invoke_single_dialogue_agent(
            agent_name, agent_ref, config_loader, state, stage_name,
            dialogue_history, round_number, max_rounds, strategy,
        )
        agent_outputs.append(output)
        llm_providers[agent_name] = llm

    return agent_outputs, llm_providers


def fallback_consensus_synthesis(agent_outputs: list) -> Any:
    """Fallback consensus synthesis when strategy registry is unavailable."""
    from src.constants.probabilities import PROB_MEDIUM
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


def track_dialogue_round(
    tracker: Any,
    strategy: Any,
    state: Dict[str, Any],
    current_outputs: list,
    round_num: int,
    round_outcome: str,
    conv_score: Optional[float] = None,
    agent_stances: Optional[Dict[str, str]] = None
) -> None:
    """Track dialogue round collaboration event."""
    if not (tracker and hasattr(tracker, 'track_collaboration_event')):
        return

    try:
        agent_names = [o.agent_name for o in current_outputs]
        event_data: Dict[str, Any] = {
            "agent_count": len(agent_names),
            "avg_confidence": (
                sum(o.confidence for o in current_outputs) / len(current_outputs)
                if current_outputs else 0.0
            ),
        }

        if agent_stances:
            stance_dist: Dict[str, int] = {}
            for s in agent_stances.values():
                if s:
                    stance_dist[s] = stance_dist.get(s, 0) + 1
            event_data["stance_distribution"] = stance_dist
            event_data["agent_stances"] = agent_stances

        tracker.track_collaboration_event(
            event_type=f"{strategy.mode}_round",
            stage_id=state.get(StateKeys.CURRENT_STAGE_ID),
            agents_involved=agent_names,
            round_number=round_num,
            outcome=round_outcome,
            confidence_score=conv_score,
            event_data=event_data,
        )
    except Exception:
        logger.warning(
            "Failed to track round %d collaboration event",
            round_num,
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
    from src.compiler.constants import ERROR_MSG_FOR_STAGE_SUFFIX

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


def execute_dialogue_round(
    round_num: int,
    reinvoke_fn: Callable[..., Tuple[list, Dict[str, Any]]],
    agents: list,
    strategy: Any,
    stage_name: str,
    state: Dict[str, Any],
    config_loader: ConfigLoaderProtocol,
    tracker: Any,
    dialogue_history: List[Dict[str, Any]],
    previous_outputs: list,
) -> Tuple[list, float, Optional[float], bool, int, str]:
    """Execute a single dialogue round: re-invoke, record, check convergence.

    Returns:
        Tuple of (current_outputs, round_cost, conv_score, converged, convergence_round, round_outcome)
    """
    current_outputs, llm_providers = reinvoke_fn(
        agents=agents, stage_name=stage_name, state=state,
        config_loader=config_loader, dialogue_history=dialogue_history,
        round_number=round_num, max_rounds=strategy.max_rounds, strategy=strategy,
    )

    agent_stances: Dict[str, str] = {}
    if hasattr(strategy, 'extract_stances'):
        agent_stances = strategy.extract_stances(current_outputs, llm_providers)

    round_cost = record_dialogue_round_outputs(
        current_outputs, round_num, agent_stances, dialogue_history,
    )

    conv_score: Optional[float] = None
    converged = False
    convergence_round = -1
    round_outcome = "in_progress"

    if round_num >= strategy.min_rounds:
        conv_score, converged, round_outcome = check_dialogue_convergence(
            strategy, current_outputs, previous_outputs, round_num, stage_name,
        )
        if converged:
            convergence_round = round_num

    track_dialogue_round(
        tracker, strategy, state, current_outputs,
        round_num, round_outcome, conv_score, agent_stances,
    )

    return current_outputs, round_cost, conv_score, converged, convergence_round, round_outcome
