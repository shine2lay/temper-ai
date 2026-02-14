"""Extracted helpers for StageExecutor.

Contains large standalone functions that were extracted from StageExecutor
to keep the class within the 500-line threshold. These functions operate
on explicit parameters and do not depend on StageExecutor instance state.
"""
import logging
import uuid
from typing import Any, Callable, Dict, Tuple

from src.compiler.constants import (
    AGENT_ROLE_LEADER,
    STATUS_UNKNOWN,
)
from src.compiler.domain_state import ConfigLoaderProtocol
from src.compiler.executors.state_keys import StateKeys
from src.constants.sizes import UUID_HEX_SHORT_LENGTH
from src.utils.config_helpers import sanitize_config_for_display

logger = logging.getLogger(__name__)


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
    from src.core.context import ExecutionContext
    from src.strategies.base import AgentOutput

    agent_config_dict = config_loader.load_agent(leader_name)
    agent_config = AgentConfig(**agent_config_dict)
    agent = AgentFactory.create(agent_config)

    # Inject team_outputs into agent input
    input_data = {
        **state,
        "team_outputs": team_outputs_text,
    }

    tracker = state.get(StateKeys.TRACKER)
    current_stage_id = state.get(StateKeys.CURRENT_STAGE_ID) or f"stage-{uuid.uuid4().hex[:UUID_HEX_SHORT_LENGTH]}"

    if tracker:
        agent_config_for_tracking = sanitize_config_for_display(
            agent_config.model_dump() if hasattr(agent_config, 'model_dump') else dict(agent_config_dict)
        )
        with tracker.track_agent(
            agent_name=leader_name,
            agent_config=agent_config_for_tracking,
            stage_id=current_stage_id,
            input_data={"role": AGENT_ROLE_LEADER, "team_outputs_length": len(team_outputs_text)},
        ) as agent_id:
            context = ExecutionContext(
                workflow_id=state.get(StateKeys.WORKFLOW_ID, STATUS_UNKNOWN),
                stage_id=current_stage_id,
                agent_id=agent_id,
                metadata={
                    "stage_name": stage_name,
                    "agent_name": leader_name,
                    "execution_mode": AGENT_ROLE_LEADER,
                },
            )
            response = agent.execute(input_data, context)

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
                    "Failed to set agent output tracking for leader agent %s",
                    leader_name,
                    exc_info=True,
                )
    else:
        input_data.pop(StateKeys.TRACKER, None)
        context = ExecutionContext(
            workflow_id=state.get(StateKeys.WORKFLOW_ID, STATUS_UNKNOWN),
            stage_id=current_stage_id,
            agent_id=f"agent-{uuid.uuid4().hex[:UUID_HEX_SHORT_LENGTH]}",
            metadata={
                "stage_name": stage_name,
                "agent_name": leader_name,
                "execution_mode": AGENT_ROLE_LEADER,
            },
        )
        response = agent.execute(input_data, context)

    return AgentOutput(
        agent_name=leader_name,
        decision=response.output,
        reasoning=response.reasoning or "",
        confidence=response.confidence or 0.0,
        metadata={
            StateKeys.TOKENS: response.tokens,
            StateKeys.COST_USD: response.estimated_cost_usd,
            "role": AGENT_ROLE_LEADER,
        },
    )


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
    from src.agents.agent_factory import AgentFactory
    from src.compiler.schemas import AgentConfig
    from src.core.context import ExecutionContext
    from src.strategies.base import AgentOutput

    agent_outputs: list = []
    llm_providers: Dict[str, Any] = {}

    for agent_ref in agents:
        agent_name = extract_agent_name_fn(agent_ref)

        # Load agent config
        agent_config_dict = config_loader.load_agent(agent_name)
        agent_config = AgentConfig(**agent_config_dict)
        agent = AgentFactory.create(agent_config)

        # Extract role from agent metadata (if present)
        agent_role = None
        if hasattr(agent_config.agent, 'metadata') and agent_config.agent.metadata:
            if agent_config.agent.metadata.tags:
                agent_role = agent_config.agent.metadata.tags[0]
            if hasattr(agent_config.agent.metadata, 'role'):
                agent_role = agent_config.agent.metadata.role

        # Curate dialogue history based on strategy
        curated_history = dialogue_history
        if strategy and hasattr(strategy, 'curate_dialogue_history'):
            curated_history = strategy.curate_dialogue_history(
                dialogue_history=dialogue_history,
                current_round=round_number,
                agent_name=agent_name
            )

        # Get mode-specific context from strategy (e.g. MultiRoundStrategy)
        mode_context: Dict[str, Any] = {}
        if strategy and hasattr(strategy, 'get_round_context'):
            mode_context = strategy.get_round_context(round_number, agent_name)

        # Enrich input with dialogue context
        input_data = {
            **state,
            "dialogue_history": curated_history,
            "round_number": round_number,
            "max_rounds": max_rounds,
            "agent_role": agent_role,
            **mode_context,
        }

        tracker = state.get(StateKeys.TRACKER)
        current_stage_id = state.get(StateKeys.CURRENT_STAGE_ID) or f"stage-{uuid.uuid4().hex[:UUID_HEX_SHORT_LENGTH]}"

        if tracker:
            # Use tracker for proper agent_executions record so LLM calls
            # can reference a valid agent_execution_id (avoids FK violations).
            agent_config_for_tracking = sanitize_config_for_display(
                agent_config.model_dump() if hasattr(agent_config, 'model_dump') else dict(agent_config_dict)
            )
            with tracker.track_agent(
                agent_name=agent_name,
                agent_config=agent_config_for_tracking,
                stage_id=current_stage_id,
                input_data={"round": round_number, "max_rounds": max_rounds},
            ) as agent_id:
                context = ExecutionContext(
                    workflow_id=state.get(StateKeys.WORKFLOW_ID, STATUS_UNKNOWN),
                    stage_id=current_stage_id,
                    agent_id=agent_id,
                    metadata={
                        "stage_name": stage_name,
                        "agent_name": agent_name,
                        "execution_mode": "dialogue",
                        "round": round_number
                    }
                )
                response = agent.execute(input_data, context)

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
                    logger.warning("Failed to set agent output tracking for dialogue agent %s", agent_name, exc_info=True)
        else:
            # No tracker -- use synthetic IDs (no agent_executions row,
            # so don't pass tracker to avoid FK violations on llm_calls).
            input_data.pop(StateKeys.TRACKER, None)
            context = ExecutionContext(
                workflow_id=state.get(StateKeys.WORKFLOW_ID, STATUS_UNKNOWN),
                stage_id=current_stage_id,
                agent_id=f"agent-{uuid.uuid4().hex[:UUID_HEX_SHORT_LENGTH]}",
                metadata={
                    "stage_name": stage_name,
                    "agent_name": agent_name,
                    "execution_mode": "dialogue",
                    "round": round_number
                }
            )
            response = agent.execute(input_data, context)

        # Create agent output (metadata must be JSON-serializable)
        agent_outputs.append(AgentOutput(
            agent_name=agent_name,
            decision=response.output,
            reasoning=response.reasoning or "",
            confidence=response.confidence or 0.0,
            metadata={
                StateKeys.TOKENS: response.tokens,
                StateKeys.COST_USD: response.estimated_cost_usd,
                "round": round_number,
            }
        ))
        # Keep LLM provider reference for stance extraction (not serialized)
        llm_providers[agent_name] = agent.llm  # type: ignore[attr-defined]

    return agent_outputs, llm_providers
