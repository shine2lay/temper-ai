"""Dialogue orchestration helpers for multi-round agent conversations.

Contains dialogue-specific dataclasses, agent re-invocation logic,
convergence detection, tracking, and synthesis for dialogue mode.
Extracted from _base_helpers.py and base.py to reduce file sizes.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from temper_ai.shared.constants.execution import ERROR_MSG_FOR_STAGE_SUFFIX
from temper_ai.shared.core.protocols import ConfigLoaderProtocol
from temper_ai.stage.executors.state_keys import StateKeys

logger = logging.getLogger(__name__)


# ── Dataclasses ──────────────────────────────────────────────────────


@dataclass
class DialogueReinvocationParams:
    """Parameters for dialogue agent re-invocation (reduces 9 params to 1)."""

    agents: list
    stage_name: str
    state: dict[str, Any]
    config_loader: ConfigLoaderProtocol
    dialogue_history: list
    round_number: int
    max_rounds: int
    strategy: Any
    extract_agent_name_fn: Callable[[Any], str]


@dataclass
class DialogueRoundParams:
    """Parameters for dialogue round execution (bundles 10 params into 1)."""

    round_num: int
    reinvoke_fn: Callable[..., tuple[list, dict[str, Any]]]
    agents: list
    strategy: Any
    stage_name: str
    state: dict[str, Any]
    config_loader: ConfigLoaderProtocol
    tracker: Any
    dialogue_history: list[dict[str, Any]]
    previous_outputs: list


@dataclass
class DialogueTrackingParams:
    """Parameters for dialogue round tracking (bundles 10 params into 1)."""

    tracker: Any
    strategy: Any
    state: dict[str, Any]
    current_outputs: list
    round_num: int
    round_outcome: str
    conv_score: float | None = None
    agent_stances: dict[str, str] | None = None
    dialogue_history: list[dict[str, Any]] | None = None
    previous_convergence: float | None = None


@dataclass
class SingleDialogueAgentParams:
    """Parameters for single dialogue agent invocation (bundles 9 params into 1)."""

    agent_name: str
    agent_ref: Any
    config_loader: ConfigLoaderProtocol
    state: dict[str, Any]
    stage_name: str
    dialogue_history: list
    round_number: int
    max_rounds: int
    strategy: Any


@dataclass
class FinalSynthesisResultParams:
    """Parameters for building final synthesis result (bundles 8 params into 1)."""

    strategy: Any
    current_outputs: list
    final_round: int
    total_cost: float
    dialogue_history: list[dict[str, Any]]
    converged: bool
    convergence_round: int
    stage_name: str


@dataclass
class DialogueRoundsParams:
    """Parameters for running dialogue rounds (reduces 10 params)."""

    executor: Any
    strategy: Any
    agents: list
    stage_name: str
    state: dict[str, Any]
    config_loader: ConfigLoaderProtocol
    tracker: Any
    dialogue_history: list[dict[str, Any]]
    initial_outputs: list
    total_cost: float


@dataclass
class InteractiveTurnsParams:
    """Parameters for interactive turn-taking dialogue."""

    executor: Any
    strategy: Any
    agents: list
    stage_name: str
    state: dict[str, Any]
    config_loader: ConfigLoaderProtocol
    tracker: Any
    initial_outputs: list
    total_cost: float
    max_turns: int
    min_cycles: int
    extract_agent_name_fn: Callable[[Any], str]


@dataclass
class SingleInteractiveAgentParams:
    """Parameters for single interactive agent invocation."""

    agent_name: str
    agent_ref: Any
    config_loader: ConfigLoaderProtocol
    state: dict[str, Any]
    stage_name: str
    conversation: list[dict[str, Any]]
    turn_number: int
    max_turns: int
    strategy: Any


# ── Agent invocation helpers ─────────────────────────────────────────


def _extract_agent_role(agent_config: Any) -> str | None:
    """Extract role from agent config metadata."""
    agent_role = None
    if hasattr(agent_config.agent, "metadata") and agent_config.agent.metadata:
        if agent_config.agent.metadata.tags:
            agent_role = agent_config.agent.metadata.tags[0]
        if hasattr(agent_config.agent.metadata, "role"):
            agent_role = agent_config.agent.metadata.role
    return agent_role


def _prepare_dialogue_input(
    state: dict[str, Any],
    curated_history: list,
    round_number: int,
    max_rounds: int,
    agent_role: str | None,
    mode_context: dict[str, Any],
) -> dict[str, Any]:
    """Build enriched input data for a dialogue round agent invocation."""
    return {
        **state,
        "dialogue_history": curated_history,
        "round_number": round_number,
        "max_rounds": max_rounds,
        "agent_role": agent_role,
        **mode_context,
    }


def _curate_history_and_resolve_context(
    strategy: Any,
    dialogue_history: list,
    round_number: int,
    agent_name: str,
) -> tuple[list, dict[str, Any]]:
    """Curate dialogue history and get mode-specific context from strategy."""
    from temper_ai.stage.executors._protocols import StanceCuratingStrategy

    curated_history = dialogue_history
    if strategy and isinstance(strategy, StanceCuratingStrategy):
        curated_history = strategy.curate_dialogue_history(
            dialogue_history=dialogue_history,
            current_round=round_number,
            agent_name=agent_name,
        )
        mode_context: dict[str, Any] = strategy.get_round_context(
            round_number, agent_name
        )
        return curated_history, mode_context

    return curated_history, {}


def _build_and_execute_dialogue_agent(  # noqa: long
    params: SingleDialogueAgentParams,
    agent: Any,
    agent_config: Any,
    agent_config_dict: dict[str, Any],
    input_data: dict[str, Any],
) -> Any:
    """Build AgentExecutionParams and run tracking or non-tracking execution."""
    from temper_ai.stage.executors._base_helpers import (
        AgentExecutionParams,
        _execute_agent_with_tracking,
        _execute_agent_without_tracking,
        _get_stage_id,
    )

    tracker = params.state.get(StateKeys.TRACKER)
    current_stage_id = _get_stage_id(params.state)
    exec_params = AgentExecutionParams(
        agent=agent,
        input_data=input_data,
        current_stage_id=current_stage_id,
        stage_name=params.stage_name,
        agent_name=params.agent_name,
        state=params.state,
        execution_mode="dialogue",
        tracker=tracker,
        agent_config=agent_config,
        agent_config_dict=agent_config_dict,
        tracking_input={"round": params.round_number, "max_rounds": params.max_rounds},
        extra_metadata={"round": params.round_number},
    )
    if tracker:
        return _execute_agent_with_tracking(exec_params)
    return _execute_agent_without_tracking(exec_params)


def _invoke_single_dialogue_agent(  # noqa: long
    params: SingleDialogueAgentParams,
) -> tuple[Any, Any]:
    """Invoke a single agent for a dialogue round.

    Returns:
        Tuple of (AgentOutput, llm_provider)
    """
    from temper_ai.agent.utils.agent_factory import AgentFactory
    from temper_ai.stage.executors._base_helpers import _build_agent_output
    from temper_ai.storage.schemas.agent_config import AgentConfig

    agent_config_dict = params.config_loader.load_agent(params.agent_name)
    agent_config = AgentConfig(**agent_config_dict)
    agent = AgentFactory.create(agent_config)

    agent_role = _extract_agent_role(agent_config)
    curated_history, mode_context = _curate_history_and_resolve_context(
        params.strategy,
        params.dialogue_history,
        params.round_number,
        params.agent_name,
    )
    input_data = _prepare_dialogue_input(
        params.state,
        curated_history,
        params.round_number,
        params.max_rounds,
        agent_role,
        mode_context,
    )

    response = _build_and_execute_dialogue_agent(
        params, agent, agent_config, agent_config_dict, input_data
    )
    output = _build_agent_output(
        params.agent_name,
        response,
        role="dialogue",
        extra_metadata={"round": params.round_number},
    )
    return output, agent.llm


def reinvoke_agents_with_dialogue(
    params: DialogueReinvocationParams,
) -> tuple[list, dict[str, Any]]:
    """Re-invoke agents with dialogue history as context.

    Returns:
        Tuple of (agent_outputs, llm_providers) where llm_providers
        maps agent_name -> LLM provider for stance extraction.
    """
    agent_outputs: list = []
    llm_providers: dict[str, Any] = {}

    for agent_ref in params.agents:
        agent_name = params.extract_agent_name_fn(agent_ref)
        single_agent_params = SingleDialogueAgentParams(
            agent_name=agent_name,
            agent_ref=agent_ref,
            config_loader=params.config_loader,
            state=params.state,
            stage_name=params.stage_name,
            dialogue_history=params.dialogue_history,
            round_number=params.round_number,
            max_rounds=params.max_rounds,
            strategy=params.strategy,
        )
        output, llm = _invoke_single_dialogue_agent(single_agent_params)
        agent_outputs.append(output)
        llm_providers[agent_name] = llm

    return agent_outputs, llm_providers


# ── Synthesis helpers ────────────────────────────────────────────────


def fallback_consensus_synthesis(agent_outputs: list) -> Any:
    """Fallback consensus synthesis when strategy registry is unavailable."""
    from temper_ai.agent.strategies.base import (
        SynthesisResult,
        calculate_vote_distribution,
        extract_majority_decision,
    )
    from temper_ai.shared.constants.probabilities import PROB_MEDIUM

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


# ── Recording and tracking ──────────────────────────────────────────


def record_dialogue_outputs_and_cost(
    current_outputs: list,
    round_num: int,
    agent_stances: dict[str, str],
    dialogue_history: list[dict[str, Any]],
) -> float:
    """Record outputs from a dialogue round into history.

    Returns:
        Round cost (sum of agent costs this round).
    """
    round_cost = 0.0
    for output in current_outputs:
        entry: dict[str, Any] = {
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
    """Track dialogue round collaboration event with enriched metrics."""
    from temper_ai.shared.core.protocols import TrackerProtocol

    if not (params.tracker and isinstance(params.tracker, TrackerProtocol)):
        return

    try:
        agent_names = [o.agent_name for o in params.current_outputs]
        event_data: dict[str, Any] = _build_dialogue_event_data(params, agent_names)

        from temper_ai.observability._tracker_helpers import CollaborationEventData

        params.tracker.track_collaboration_event(
            CollaborationEventData(
                event_type=f"{params.strategy.mode}_round",
                stage_id=params.state.get(StateKeys.CURRENT_STAGE_ID),
                agents_involved=agent_names,
                round_number=params.round_num,
                outcome=params.round_outcome,
                confidence_score=params.conv_score,
                event_data=event_data,
            )
        )
    except Exception:
        logger.warning(
            "Failed to track round %d collaboration event",
            params.round_num,
            exc_info=True,
        )


def _build_dialogue_event_data(
    params: DialogueTrackingParams,
    agent_names: list[str],
) -> dict[str, Any]:
    """Build event data dict for dialogue round tracking."""
    event_data: dict[str, Any] = {
        "agent_count": len(agent_names),
        "avg_confidence": (
            sum(o.confidence for o in params.current_outputs)
            / len(params.current_outputs)
            if params.current_outputs
            else 0.0
        ),
    }

    if params.agent_stances:
        stance_dist: dict[str, int] = {}
        for s in params.agent_stances.values():
            if s:
                stance_dist[s] = stance_dist.get(s, 0) + 1
        event_data["stance_distribution"] = stance_dist
        event_data["agent_stances"] = params.agent_stances

    _enrich_with_round_metrics(params, event_data)
    return event_data


def _enrich_with_round_metrics(
    params: DialogueTrackingParams,
    event_data: dict[str, Any],
) -> None:
    """Enrich event data with computed dialogue round metrics."""
    try:
        from temper_ai.observability.dialogue_metrics import compute_round_metrics

        history = params.dialogue_history or []
        metrics = compute_round_metrics(
            current_outputs=params.current_outputs,
            dialogue_history=history,
            round_number=params.round_num,
            convergence_score=params.conv_score,
            previous_convergence=params.previous_convergence,
        )
        event_data["confidence_trajectory"] = metrics.confidence_trajectory
        event_data["convergence_speed"] = metrics.convergence_speed
        event_data["stance_changes"] = metrics.stance_changes
    except Exception:
        logger.debug(
            "Failed to compute dialogue round metrics for round %d",
            params.round_num,
            exc_info=True,
        )


# ── Convergence ──────────────────────────────────────────────────────


def check_dialogue_convergence(
    strategy: Any,
    current_outputs: list,
    previous_outputs: list,
    round_num: int,
    stage_name: str,
) -> tuple[float | None, bool, str]:
    """Check convergence after min_rounds.

    Returns:
        Tuple of (conv_score, converged, round_outcome)
    """
    conv_score = strategy.calculate_convergence(current_outputs, previous_outputs)
    logger.info(
        f"Dialogue round {round_num + 1}{ERROR_MSG_FOR_STAGE_SUFFIX}{stage_name}': "
        f"convergence {conv_score:.1%} "
        f"(threshold: {strategy.convergence_threshold:.1%})"
    )

    if conv_score >= strategy.convergence_threshold:
        logger.info(
            f"Dialogue converged at round {round_num + 1} for "  # noqa: long
            f"stage '{stage_name}': {conv_score:.1%} >= "
            f"{strategy.convergence_threshold:.1%}"
        )
        return conv_score, True, "converged"

    return conv_score, False, "in_progress"


def _check_convergence_and_track(
    params: DialogueRoundParams,
    current_outputs: list,
    agent_stances: dict[str, str],
    round_outcome: str,
    conv_score: float | None,
) -> tuple[float | None, bool, int, str]:
    """Check convergence if min_rounds reached, then track the round.

    Returns (conv_score, converged, convergence_round, round_outcome).
    """
    converged = False
    convergence_round = -1

    if params.round_num >= params.strategy.min_rounds:
        conv_score, converged, round_outcome = check_dialogue_convergence(
            params.strategy,
            current_outputs,
            params.previous_outputs,
            params.round_num,
            params.stage_name,
        )
        if converged:
            convergence_round = params.round_num

    track_params = DialogueTrackingParams(
        tracker=params.tracker,
        strategy=params.strategy,
        state=params.state,
        current_outputs=current_outputs,
        round_num=params.round_num,
        round_outcome=round_outcome,
        conv_score=conv_score,
        agent_stances=agent_stances,
        dialogue_history=params.dialogue_history,
    )
    track_dialogue_round(track_params)
    return conv_score, converged, convergence_round, round_outcome


def execute_dialogue_round(  # noqa: long
    params: DialogueRoundParams,
) -> tuple[list, float, float | None, bool, int, str]:
    """Execute a single dialogue round: re-invoke, record, check convergence.

    Returns:
        Tuple of (current_outputs, round_cost, conv_score, converged,
                  convergence_round, round_outcome)
    """
    reinvoke_params = DialogueReinvocationParams(
        agents=params.agents,
        stage_name=params.stage_name,
        state=params.state,
        config_loader=params.config_loader,
        dialogue_history=params.dialogue_history,
        round_number=params.round_num,
        max_rounds=params.strategy.max_rounds,
        strategy=params.strategy,
        extract_agent_name_fn=lambda ref: ref,  # placeholder, set by caller
    )
    current_outputs, llm_providers = params.reinvoke_fn(params=reinvoke_params)

    from temper_ai.stage.executors._protocols import StanceCuratingStrategy

    agent_stances: dict[str, str] = {}
    if isinstance(params.strategy, StanceCuratingStrategy):
        agent_stances = params.strategy.extract_stances(current_outputs, llm_providers)

    round_cost = record_dialogue_outputs_and_cost(
        current_outputs,
        params.round_num,
        agent_stances,
        params.dialogue_history,
    )

    conv_score, converged, convergence_round, round_outcome = (
        _check_convergence_and_track(
            params, current_outputs, agent_stances, "in_progress", None
        )
    )

    return (
        current_outputs,
        round_cost,
        conv_score,
        converged,
        convergence_round,
        round_outcome,
    )


# ── Dialogue round orchestration (from base.py) ─────────────────────


def run_dialogue_rounds(params: DialogueRoundsParams) -> tuple:
    """Run dialogue rounds until convergence, budget, or max rounds.

    Returns:
        (final_round, current_outputs, total_cost, converged, convergence_round)
    """
    previous_outputs = params.initial_outputs
    current_outputs = params.initial_outputs
    converged = False
    convergence_round = -1
    final_round = 0
    total_cost = params.total_cost

    for round_num in range(1, params.strategy.max_rounds):
        final_round = round_num
        round_params = DialogueRoundParams(
            round_num=round_num,
            reinvoke_fn=params.executor._reinvoke_agents_with_dialogue,
            agents=params.agents,
            strategy=params.strategy,
            stage_name=params.stage_name,
            state=params.state,
            config_loader=params.config_loader,
            tracker=params.tracker,
            dialogue_history=params.dialogue_history,
            previous_outputs=previous_outputs,
        )
        outputs, cost, _, conv, conv_round, _ = execute_dialogue_round(round_params)
        current_outputs = outputs
        total_cost += cost
        if conv:
            converged = True
            convergence_round = conv_round
            break
        if (
            params.strategy.cost_budget_usd
            and total_cost >= params.strategy.cost_budget_usd
        ):
            logger.warning(
                f"Dialogue stopped at round {round_num + 1} for stage '{params.stage_name}': "
                f"budget ${params.strategy.cost_budget_usd:.2f} reached (cost: ${total_cost:.2f})"
            )
            break
        previous_outputs = current_outputs

    return final_round, current_outputs, total_cost, converged, convergence_round


def record_initial_round(
    current_outputs: list,
    dialogue_history: list[dict[str, Any]],
) -> float:
    """Record initial round outputs in dialogue history.

    Returns:
        Total cost from initial outputs
    """
    total_cost = 0.0
    for output in current_outputs:
        dialogue_history.append(
            {
                "agent": output.agent_name,
                "round": 0,
                StateKeys.OUTPUT: output.decision,
                StateKeys.REASONING: output.reasoning,
                StateKeys.CONFIDENCE: output.confidence,
            }
        )
        total_cost += output.metadata.get(StateKeys.COST_USD, 0.0)
    return total_cost


def build_final_synthesis_result(params: FinalSynthesisResultParams) -> Any:
    """Build final synthesis result with metadata."""
    result = params.strategy.synthesize(params.current_outputs, {})
    result.metadata["dialogue_rounds"] = params.final_round + 1
    result.metadata["total_cost_usd"] = params.total_cost
    result.metadata["dialogue_history"] = params.dialogue_history
    result.metadata["converged"] = params.converged

    if params.converged:
        result.metadata["convergence_round"] = params.convergence_round
        result.metadata["early_stop_reason"] = "convergence"
    elif (
        params.strategy.cost_budget_usd
        and params.total_cost >= params.strategy.cost_budget_usd
    ):
        result.metadata["early_stop_reason"] = "budget"
    else:
        result.metadata["early_stop_reason"] = "max_rounds"

    logger.info(
        f"Dialogue completed{ERROR_MSG_FOR_STAGE_SUFFIX}{params.stage_name}': "
        f"{params.final_round + 1} rounds, ${params.total_cost:.2f} cost, "
        f"converged: {params.converged}, "
        f"reason: {result.metadata['early_stop_reason']}"
    )

    return result


# ── Interactive turn-taking ──────────────────────────────────────────


def run_interactive_turns(params: InteractiveTurnsParams) -> tuple:
    """Run turn-taking dialogue. One agent per turn, round-robin.

    Returns:
        (final_turn, last_outputs_per_agent, total_cost, converged, convergence_turn)
    """
    agents = params.agents
    agent_count = len(agents)
    conversation: list[dict[str, Any]] = []
    last_output_per_agent: dict[str, Any] = {}
    total_cost = params.total_cost
    converged = False
    convergence_turn = -1

    # Seed conversation from initial outputs (round 0)
    for output in params.initial_outputs:
        agent_name = output.agent_name
        conversation.append(
            {
                "agent": agent_name,
                "turn": 0,
                "output": output.decision,
                "reasoning": output.reasoning,
                "confidence": output.confidence,
            }
        )
        last_output_per_agent[agent_name] = output

    final_turn = 0
    for turn in range(1, params.max_turns):
        agent_idx = turn % agent_count
        agent_ref = agents[agent_idx]
        agent_name = params.extract_agent_name_fn(agent_ref)

        prev_output = last_output_per_agent.get(agent_name)

        output, _llm = _invoke_single_interactive_agent(
            SingleInteractiveAgentParams(
                agent_name=agent_name,
                agent_ref=agent_ref,
                config_loader=params.config_loader,
                state=params.state,
                stage_name=params.stage_name,
                conversation=conversation,
                turn_number=turn,
                max_turns=params.max_turns,
                strategy=params.strategy,
            )
        )

        conversation.append(
            {
                "agent": agent_name,
                "turn": turn,
                "output": output.decision,
                "reasoning": output.reasoning,
                "confidence": output.confidence,
            }
        )
        last_output_per_agent[agent_name] = output
        total_cost += output.metadata.get(StateKeys.COST_USD, 0.0)
        final_turn = turn

        # Track this turn
        _track_interactive_turn(
            params.tracker,
            params.strategy,
            params.state,
            output,
            turn,
            agent_name,
        )

        # Convergence: check after min_cycles complete cycles
        cycle = turn // agent_count
        if cycle >= params.min_cycles and prev_output is not None:
            if _all_agents_converged(
                last_output_per_agent,
                conversation,
                params.strategy,
                agent_count,
            ):
                converged = True
                convergence_turn = turn
                break

        # Budget check
        if (
            params.strategy.cost_budget_usd
            and total_cost >= params.strategy.cost_budget_usd
        ):
            break

    return (final_turn, last_output_per_agent, total_cost, converged, convergence_turn)


def _invoke_single_interactive_agent(
    params: SingleInteractiveAgentParams,
) -> tuple[Any, Any]:
    """Invoke a single agent for an interactive turn.

    Returns:
        Tuple of (AgentOutput, llm_provider)
    """
    from temper_ai.agent.utils.agent_factory import AgentFactory
    from temper_ai.stage.executors._base_helpers import _build_agent_output
    from temper_ai.storage.schemas.agent_config import AgentConfig

    agent_config_dict = params.config_loader.load_agent(params.agent_name)
    agent_config = AgentConfig(**agent_config_dict)
    agent = AgentFactory.create(agent_config)

    agent_role = _extract_agent_role(agent_config)
    curated_history, mode_context = _curate_history_and_resolve_context(
        params.strategy,
        params.conversation,
        params.turn_number,
        params.agent_name,
    )

    # Build previous_speakers from last 3 conversation entries (not from this agent)
    previous_speakers = [
        entry
        for entry in params.conversation[-3:]
        if entry["agent"] != params.agent_name
    ][-2:]

    input_data = {
        **params.state,
        "conversation": curated_history,
        "turn_number": params.turn_number,
        "max_turns": params.max_turns,
        "agent_role": agent_role,
        "interaction_mode": "interactive",
        "previous_speakers": previous_speakers,
        **mode_context,
    }

    # Reuse the shared agent execution path
    dialogue_params = SingleDialogueAgentParams(
        agent_name=params.agent_name,
        agent_ref=params.agent_ref,
        config_loader=params.config_loader,
        state=params.state,
        stage_name=params.stage_name,
        dialogue_history=params.conversation,
        round_number=params.turn_number,
        max_rounds=params.max_turns,
        strategy=params.strategy,
    )

    response = _build_and_execute_dialogue_agent(
        dialogue_params, agent, agent_config, agent_config_dict, input_data
    )
    output = _build_agent_output(
        params.agent_name,
        response,
        role="interactive",
        extra_metadata={"turn": params.turn_number},
    )
    return output, agent.llm


def _all_agents_converged(
    last_outputs: dict[str, Any],
    conversation: list[dict[str, Any]],
    strategy: Any,
    agent_count: int,
) -> bool:
    """Check if all agents have converged across their last two outputs."""
    if len(conversation) < agent_count * 2:
        return False

    for agent_name, current_output in last_outputs.items():
        prev = _find_previous_output(conversation, agent_name)
        if prev is None:
            return False
        score = strategy.calculate_convergence([current_output], [prev])
        if score < strategy.convergence_threshold:
            return False
    return True


def _find_previous_output(
    conversation: list[dict[str, Any]],
    agent_name: str,
) -> Any | None:
    """Find this agent's second-to-last output in conversation."""
    agent_entries = [e for e in conversation if e["agent"] == agent_name]
    if len(agent_entries) < 2:
        return None
    # Return second-to-last as an AgentOutput for convergence calc
    prev = agent_entries[-2]
    from temper_ai.agent.strategies.base import AgentOutput

    return AgentOutput(
        agent_name=agent_name,
        decision=prev["output"],
        reasoning=prev.get("reasoning", ""),
        confidence=prev.get("confidence", 0.0),
        metadata={},
    )


def _track_interactive_turn(
    tracker: Any,
    strategy: Any,
    state: dict[str, Any],
    output: Any,
    turn: int,
    agent_name: str,
) -> None:
    """Track a single interactive turn via collaboration event."""
    track_params = DialogueTrackingParams(
        tracker=tracker,
        strategy=strategy,
        state=state,
        current_outputs=[output],
        round_num=turn,
        round_outcome="in_progress",
    )
    track_dialogue_round(track_params)
