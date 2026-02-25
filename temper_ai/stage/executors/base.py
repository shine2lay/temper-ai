"""Base interface for stage executors.

Defines the contract that all stage execution strategies must implement,
plus the ParallelRunner abstraction for engine-agnostic parallel execution,
and shared methods for synthesis, dialogue, and agent name extraction.
"""

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from temper_ai.stage.executors._dialogue_helpers import DialogueReinvocationParams

from temper_ai.shared.constants.execution import ERROR_MSG_FOR_STAGE_SUFFIX
from temper_ai.shared.core.protocols import (
    ConfigLoaderProtocol,
    DomainToolRegistryProtocol,
)
from temper_ai.stage.executors._base_helpers import (
    invoke_leader_agent,
)
from temper_ai.stage.executors._dialogue_helpers import (
    DialogueRoundsParams,
    DialogueTrackingParams,
    FinalSynthesisResultParams,
    build_final_synthesis_result,
    fallback_consensus_synthesis,
    record_initial_round,
    run_dialogue_rounds,
    track_dialogue_round,
)
from temper_ai.stage.executors.state_keys import StateKeys

logger = logging.getLogger(__name__)


class ParallelRunner(ABC):
    """Abstraction for running nodes in parallel.

    Encapsulates the "build graph, compile, invoke" pattern so executors
    don't need to import a specific graph engine (e.g., LangGraph).
    """

    @abstractmethod
    def run_parallel(
        self,
        nodes: dict[str, Callable[[dict[str, Any]], dict[str, Any]]],
        initial_state: dict[str, Any],
        *,
        init_node: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        collect_node: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Execute nodes in parallel and return collected results."""
        pass


class StageExecutor(ABC):
    """Base class for stage execution strategies.

    Each executor implements a specific execution mode:
    - Sequential: Execute agents one after another
    - Parallel: Execute agents concurrently
    - Adaptive: Start parallel, switch to sequential if needed

    Provides shared methods for synthesis, dialogue, and agent name
    extraction used by all concrete executors.
    """

    context_provider: Any | None = None
    output_extractor: Any | None = None
    tool_executor: Any | None = None

    def _extract_structured_fields(
        self,
        stage_config: Any,
        raw_output: str,
        stage_name: str,
    ) -> dict[str, Any]:
        """Extract structured fields from raw output using output declarations."""
        if not self.output_extractor or not raw_output:
            return {}
        from temper_ai.shared.utils.config_helpers import get_nested_value
        from temper_ai.workflow.context_schemas import parse_stage_outputs

        outputs_raw = get_nested_value(stage_config, "stage.outputs") or {}
        output_decls = parse_stage_outputs(outputs_raw)
        if not output_decls:
            return {}
        result: dict[str, Any] = self.output_extractor.extract(
            str(raw_output), output_decls, stage_name
        )
        return result

    @abstractmethod
    def execute_stage(
        self,
        stage_name: str,
        stage_config: Any,
        state: dict[str, Any],
        config_loader: ConfigLoaderProtocol,
        tool_registry: DomainToolRegistryProtocol | None = None,
    ) -> dict[str, Any]:
        """Execute stage and return updated state."""
        pass

    @abstractmethod
    def supports_stage_type(self, stage_type: str) -> bool:
        """Check if executor supports this stage type."""
        pass

    # ------------------------------------------------------------------
    # Shared helpers used by Sequential, Parallel, and Adaptive executors
    # ------------------------------------------------------------------

    def _extract_agent_name(self, agent_ref: Any) -> str:
        """Extract agent name from various agent reference formats."""
        from temper_ai.workflow.utils import extract_agent_name

        return extract_agent_name(agent_ref)

    def _run_strategy_synthesis(  # noqa: long
        self,
        agent_outputs: list,
        stage_config: Any,
        stage_name: str,
        state: dict[str, Any] | None,
        config_loader: ConfigLoaderProtocol | None,
        agents: list | None,
    ) -> Any:
        """Run strategy-based synthesis (leader, dialogue, or default)."""
        from temper_ai.agent.strategies.registry import get_strategy_from_config
        from temper_ai.stage.executors._protocols import (
            DialogueCapableStrategy,
            LeaderCapableStrategy,
        )

        strategy = get_strategy_from_config(stage_config)

        if (
            isinstance(strategy, LeaderCapableStrategy)
            and strategy.requires_leader_synthesis
        ):
            return self._run_leader_synthesis(
                agent_outputs=agent_outputs,
                strategy=strategy,
                stage_config=stage_config,
                stage_name=stage_name,
                state=state,
                config_loader=config_loader,
                agents=agents,
            )

        if isinstance(strategy, DialogueCapableStrategy) and strategy.requires_requery:
            if state is None or config_loader is None or agents is None:
                logger.warning(
                    "Dialogue mode requires state, config_loader, and agents. Falling back to one-shot."
                )
            else:
                return self._run_dialogue_synthesis(
                    initial_outputs=agent_outputs,
                    strategy=strategy,
                    stage_config=stage_config,
                    stage_name=stage_name,
                    state=state,
                    config_loader=config_loader,
                    agents=agents,
                )

        from temper_ai.stage._config_accessors import (
            get_collaboration_inner_config as _get_collab_cfg,
        )

        return strategy.synthesize(agent_outputs, _get_collab_cfg(stage_config))

    def _run_synthesis(
        self,
        agent_outputs: list,
        stage_config: Any,
        stage_name: str,
        state: dict[str, Any] | None = None,
        config_loader: ConfigLoaderProtocol | None = None,
        agents: list | None = None,
    ) -> Any:
        """Run collaboration strategy to synthesize agent outputs."""
        # Fast-path: injected coordinator (used by ParallelStageExecutor)
        coordinator = getattr(self, "synthesis_coordinator", None)
        if coordinator:
            return coordinator.synthesize(
                agent_outputs=agent_outputs,
                stage_config=stage_config,
                stage_name=stage_name,
            )

        try:
            return self._run_strategy_synthesis(  # noqa: long
                agent_outputs, stage_config, stage_name, state, config_loader, agents
            )
        except ImportError:
            return fallback_consensus_synthesis(agent_outputs)

    def _run_dialogue_synthesis(  # noqa: long
        self,
        initial_outputs: list,
        strategy: Any,
        stage_config: Any,
        stage_name: str,
        state: dict[str, Any],
        config_loader: ConfigLoaderProtocol,
        agents: list,
    ) -> Any:
        """Execute multi-round dialogue with agent re-invocation."""
        dialogue_history: list[dict[str, Any]] = []
        current_outputs = initial_outputs
        total_cost = record_initial_round(current_outputs, dialogue_history)
        tracker = state.get(StateKeys.TRACKER)
        track_params = DialogueTrackingParams(
            tracker=tracker,
            strategy=strategy,
            state=state,
            current_outputs=current_outputs,
            round_num=0,
            round_outcome="initial",
        )
        track_dialogue_round(track_params)

        if strategy.cost_budget_usd and total_cost >= strategy.cost_budget_usd:
            return self._budget_stop_result(
                strategy, current_outputs, total_cost, stage_name
            )

        final_round, current_outputs, total_cost, converged, convergence_round = (
            run_dialogue_rounds(
                DialogueRoundsParams(
                    executor=self,
                    strategy=strategy,
                    agents=agents,
                    stage_name=stage_name,
                    state=state,
                    config_loader=config_loader,
                    tracker=tracker,
                    dialogue_history=dialogue_history,
                    initial_outputs=initial_outputs,
                    total_cost=total_cost,
                )
            )
        )

        synth_params = FinalSynthesisResultParams(
            strategy=strategy,
            current_outputs=current_outputs,
            final_round=final_round,
            total_cost=total_cost,
            dialogue_history=dialogue_history,
            converged=converged,
            convergence_round=convergence_round,
            stage_name=stage_name,
        )
        return build_final_synthesis_result(synth_params)

    @staticmethod
    def _budget_stop_result(
        strategy: Any, current_outputs: list, total_cost: float, stage_name: str
    ) -> Any:
        """Return early synthesis result when budget is exhausted after round 0."""
        logger.warning(
            f"Dialogue stopped after round 0{ERROR_MSG_FOR_STAGE_SUFFIX}{stage_name}': "
            f"budget ${strategy.cost_budget_usd:.2f} reached "
            f"(cost: ${total_cost:.2f})"
        )
        result = strategy.synthesize(current_outputs, {})
        result.metadata["dialogue_rounds"] = 1
        result.metadata["total_cost_usd"] = total_cost
        result.metadata["early_stop_reason"] = "budget"
        return result

    def _run_leader_synthesis(
        self,
        agent_outputs: list,
        strategy: Any,
        stage_config: Any,
        stage_name: str,
        state: dict[str, Any] | None = None,
        config_loader: ConfigLoaderProtocol | None = None,
        agents: list | None = None,
    ) -> Any:
        """Execute leader-based synthesis: re-invoke leader with team outputs."""
        from temper_ai.stage._config_accessors import get_collaboration_inner_config

        collaboration_config = get_collaboration_inner_config(stage_config)
        leader_name = strategy.get_leader_agent_name(collaboration_config)

        if not leader_name:
            logger.warning(
                "Leader strategy for stage '%s' has no leader_agent configured; "
                "falling back to consensus.",
                stage_name,
            )
            return strategy.synthesize(agent_outputs, collaboration_config)

        team_outputs_text = strategy.format_team_outputs(agent_outputs)

        try:
            if state is None or config_loader is None:
                raise ValueError(
                    "state and config_loader required for leader synthesis"
                )

            leader_output = self._invoke_leader_agent(
                leader_name=leader_name,
                team_outputs_text=team_outputs_text,
                stage_name=stage_name,
                state=state,
                config_loader=config_loader,
            )

            all_outputs = list(agent_outputs) + [leader_output]
            return strategy.synthesize(all_outputs, collaboration_config)

        except Exception as exc:
            logger.warning(
                "Leader agent '%s' failed for stage '%s': %s. "
                "Falling back to consensus on perspective outputs.",
                leader_name,
                stage_name,
                exc,
            )
            return strategy.synthesize(agent_outputs, collaboration_config)

    def _invoke_leader_agent(
        self,
        leader_name: str,
        team_outputs_text: str,
        stage_name: str,
        state: dict[str, Any],
        config_loader: ConfigLoaderProtocol,
    ) -> Any:
        """Invoke the leader agent with team outputs injected."""
        return invoke_leader_agent(
            leader_name=leader_name,
            team_outputs_text=team_outputs_text,
            stage_name=stage_name,
            state=state,
            config_loader=config_loader,
        )

    def _reinvoke_agents_with_dialogue(
        self,
        params: "DialogueReinvocationParams",
    ) -> tuple:
        """Re-invoke agents with dialogue history as context."""
        from temper_ai.stage.executors._dialogue_helpers import (
            reinvoke_agents_with_dialogue,
        )

        params.extract_agent_name_fn = self._extract_agent_name
        return reinvoke_agents_with_dialogue(params)
