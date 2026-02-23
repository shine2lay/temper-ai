"""Adaptive stage executor.

Starts with parallel execution, switches to sequential if disagreement is high.
"""

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, cast

from temper_ai.observability.resilience_events import (
    FallbackEventData,
    emit_fallback_event,
)
from temper_ai.shared.constants.execution import (
    ADAPTIVE_META_DISAGREEMENT_RATE,
    ADAPTIVE_META_STARTED_WITH,
    ADAPTIVE_META_SWITCHED_TO,
    COLLAB_EVENT_MODE_SWITCH,
    EXECUTION_MODE_PARALLEL,
    EXECUTION_MODE_SEQUENTIAL,
)
from temper_ai.shared.constants.probabilities import PROB_MEDIUM
from temper_ai.shared.core.protocols import (
    ConfigLoaderProtocol,
    DomainToolRegistryProtocol,
)
from temper_ai.stage.executors.base import StageExecutor
from temper_ai.stage.executors.parallel import ParallelStageExecutor
from temper_ai.stage.executors.sequential import SequentialStageExecutor


@dataclass
class ParallelSwitchCheckParams:
    """Parameters for parallel execution with switch checking (bundles 8 params into 1)."""

    parallel_executor: Any
    stage_name: str
    stage_config: Any
    state: dict[str, Any]
    config_loader: Any
    tool_registry: Any | None
    disagreement_threshold: float
    tracker: Any | None


@dataclass
class ParallelErrorHandlerParams:
    """Parameters for parallel error handling (bundles 8 params into 1)."""

    e: Exception
    stage_name: str
    stage_config: Any
    state: dict[str, Any]
    config_loader: Any
    tool_registry: Any | None
    disagreement_threshold: float
    tracker: Any | None


def _execute_parallel_with_switch_check(
    params: ParallelSwitchCheckParams,
) -> tuple[dict[str, Any], bool, float, dict[str, Any]]:
    """Execute parallel and check if mode switch needed.

    Returns:
        Tuple of (parallel_state, should_switch, disagreement_rate, mode_metadata)
    """
    # Execute parallel
    parallel_state = params.parallel_executor.execute_stage(
        stage_name=params.stage_name,
        stage_config=params.stage_config,
        state=params.state,
        config_loader=params.config_loader,
        tool_registry=params.tool_registry,
    )

    # Get synthesis result
    stage_output = parallel_state["stage_outputs"][params.stage_name]
    synthesis_info = stage_output.get("synthesis", {})

    # Calculate disagreement
    synthesis_result = SimpleNamespace(votes=synthesis_info.get("votes", {}))
    disagreement_rate = _calculate_disagreement_rate(synthesis_result)

    # Build metadata
    mode_metadata = {
        ADAPTIVE_META_STARTED_WITH: EXECUTION_MODE_PARALLEL,
        ADAPTIVE_META_SWITCHED_TO: None,
        ADAPTIVE_META_DISAGREEMENT_RATE: disagreement_rate,
        "disagreement_threshold": params.disagreement_threshold,
    }

    # Check if switch needed
    should_switch = disagreement_rate > params.disagreement_threshold

    if should_switch and params.tracker:
        emit_fallback_event(
            tracker=params.tracker,
            stage_id=params.stage_name,
            event_data=FallbackEventData(
                from_mode=EXECUTION_MODE_PARALLEL,
                to_mode=EXECUTION_MODE_SEQUENTIAL,
                reason="disagreement_threshold_exceeded",
                stage_name=params.stage_name,
                disagreement_rate=disagreement_rate,
                threshold=params.disagreement_threshold,
                agents=list(stage_output.get("agent_outputs", {}).keys()),
            ),
        )

    return parallel_state, should_switch, disagreement_rate, mode_metadata


def _calculate_disagreement_rate(synthesis_result: Any) -> float:
    """Calculate disagreement rate from synthesis result.

    Disagreement rate is the percentage of votes NOT for the winning decision.
    Higher values indicate more disagreement among agents.

    Args:
        synthesis_result: SynthesisResult from synthesis

    Returns:
        Disagreement rate between 0.0 (unanimous) and 1.0 (maximum disagreement)

    Example:
        votes = {"A": 3, "B": 1, "C": 1}
        disagreement_rate = 1 - (3/5) = 0.4  # 40% disagreement
    """
    votes = synthesis_result.votes or {}

    if not votes:
        return 0.0  # No disagreement if no votes

    total_votes = cast(int, sum(votes.values()))
    if total_votes == 0:
        return 0.0

    # Get max vote count (winning decision)
    max_votes = cast(int, max(votes.values()))

    # Disagreement rate = 1 - (consensus strength)
    return 1.0 - (max_votes / total_votes)


class AdaptiveStageExecutor(StageExecutor):
    """Execute stage with adaptive mode (M3-10 feature).

    Starts with parallel execution. If disagreement rate exceeds threshold,
    switches to sequential execution for better quality.
    """

    def __init__(
        self,
        synthesis_coordinator: Any | None = None,
        quality_gate_validator: Any | None = None,
        tool_executor: Any | None = None,
    ) -> None:
        """Initialize adaptive executor.

        Args:
            synthesis_coordinator: Coordinator for synthesizing agent outputs
            quality_gate_validator: Validator for quality gates
            tool_executor: ToolExecutor with safety stack (optional).
                Wired through constructor instead of state dict.
        """
        self.tool_executor = tool_executor
        self.sequential_executor = SequentialStageExecutor(
            tool_executor=tool_executor,
        )
        self.parallel_executor = ParallelStageExecutor(
            synthesis_coordinator=synthesis_coordinator,
            quality_gate_validator=quality_gate_validator,
            tool_executor=tool_executor,
        )

    def _fallback_to_sequential(
        self,
        stage_name: str,
        stage_config: Any,
        state: dict[str, Any],
        config_loader: ConfigLoaderProtocol,
        tool_registry: DomainToolRegistryProtocol | None,
        mode_metadata: dict[str, Any],
    ) -> dict[str, Any]:
        """Fall back to sequential execution and attach mode metadata."""
        state["stage_outputs"].pop(stage_name, None)
        sequential_state = self.sequential_executor.execute_stage(
            stage_name=stage_name,
            stage_config=stage_config,
            state=state,
            config_loader=config_loader,
            tool_registry=tool_registry,
        )
        if isinstance(sequential_state["stage_outputs"].get(stage_name), dict):
            sequential_state["stage_outputs"][stage_name][
                COLLAB_EVENT_MODE_SWITCH
            ] = mode_metadata
        return sequential_state

    def _handle_parallel_error(
        self, params: ParallelErrorHandlerParams
    ) -> dict[str, Any]:
        """Handle parallel execution failure by falling back to sequential."""
        error_mode_metadata = {
            ADAPTIVE_META_STARTED_WITH: EXECUTION_MODE_PARALLEL,
            ADAPTIVE_META_SWITCHED_TO: EXECUTION_MODE_SEQUENTIAL,
            ADAPTIVE_META_DISAGREEMENT_RATE: None,
            "disagreement_threshold": params.disagreement_threshold,
            "error": str(params.e),
        }

        if params.tracker:
            emit_fallback_event(
                tracker=params.tracker,
                stage_id=params.stage_name,
                event_data=FallbackEventData(
                    from_mode=EXECUTION_MODE_PARALLEL,
                    to_mode=EXECUTION_MODE_SEQUENTIAL,
                    reason="parallel_execution_failed",
                    stage_name=params.stage_name,
                    agents=[],
                    error_message=str(params.e),
                ),
            )

        return self._fallback_to_sequential(
            params.stage_name,
            params.stage_config,
            params.state,
            params.config_loader,
            params.tool_registry,
            error_mode_metadata,
        )

    def execute_stage(
        self,
        stage_name: str,
        stage_config: Any,
        state: dict[str, Any],
        config_loader: ConfigLoaderProtocol,
        tool_registry: DomainToolRegistryProtocol | None = None,
    ) -> dict[str, Any]:
        """Execute stage with adaptive mode.

        Starts with parallel execution. If disagreement rate exceeds threshold,
        switches to sequential execution for better quality.

        Args:
            stage_name: Stage name
            stage_config: Stage configuration
            state: Current workflow state
            config_loader: ConfigLoader for loading agent configs
            tool_registry: ToolRegistry for agent tool access

        Returns:
            Updated workflow state

        Config example:
            execution:
              agent_mode: adaptive
              adaptive_config:
                disagreement_threshold: 0.5
                max_parallel_rounds: 2
        """
        tracker = state.get("tracker")

        stage_dict = stage_config if isinstance(stage_config, dict) else {}
        execution_config = stage_dict.get("execution", {})
        adaptive_config = execution_config.get("adaptive_config", {})
        disagreement_threshold = adaptive_config.get(
            "disagreement_threshold", PROB_MEDIUM
        )

        try:
            switch_params = ParallelSwitchCheckParams(
                parallel_executor=self.parallel_executor,
                stage_name=stage_name,
                stage_config=stage_config,
                state=state,
                config_loader=config_loader,
                tool_registry=tool_registry,
                disagreement_threshold=disagreement_threshold,
                tracker=tracker,
            )
            parallel_state, should_switch, disagreement_rate, mode_metadata = (
                _execute_parallel_with_switch_check(switch_params)
            )

            if should_switch:
                mode_metadata[ADAPTIVE_META_SWITCHED_TO] = EXECUTION_MODE_SEQUENTIAL
                return self._fallback_to_sequential(
                    stage_name,
                    stage_config,
                    state,
                    config_loader,
                    tool_registry,
                    mode_metadata,
                )

            stage_output = parallel_state["stage_outputs"][stage_name]
            if isinstance(stage_output, dict):
                stage_output[COLLAB_EVENT_MODE_SWITCH] = mode_metadata
                parallel_state["stage_outputs"][stage_name] = stage_output

            return parallel_state

        except (KeyError, TypeError, AttributeError, ValueError, RuntimeError) as e:
            error_params = ParallelErrorHandlerParams(
                e=e,
                stage_name=stage_name,
                stage_config=stage_config,
                state=state,
                config_loader=config_loader,
                tool_registry=tool_registry,
                disagreement_threshold=disagreement_threshold,
                tracker=tracker,
            )
            return self._handle_parallel_error(error_params)

    def supports_stage_type(self, stage_type: str) -> bool:
        """Check if executor supports this stage type.

        Args:
            stage_type: Stage type identifier

        Returns:
            True for "adaptive" type
        """
        return stage_type == "adaptive"

    def _calculate_disagreement_rate(self, synthesis_result: Any) -> float:
        """Calculate disagreement rate from synthesis result.

        Delegates to module-level function for compatibility.

        Args:
            synthesis_result: SynthesisResult from synthesis

        Returns:
            Disagreement rate between 0.0 (unanimous) and 1.0 (maximum disagreement)
        """
        return _calculate_disagreement_rate(synthesis_result)
