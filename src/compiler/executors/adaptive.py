"""Adaptive stage executor.

Starts with parallel execution, switches to sequential if disagreement is high.
"""
from typing import Any, Dict, Optional, cast

from src.compiler.executors.base import StageExecutor
from src.compiler.executors.parallel import ParallelStageExecutor
from src.compiler.executors.sequential import SequentialStageExecutor


class AdaptiveStageExecutor(StageExecutor):
    """Execute stage with adaptive mode (M3-10 feature).

    Starts with parallel execution. If disagreement rate exceeds threshold,
    switches to sequential execution for better quality.
    """

    def __init__(
        self,
        synthesis_coordinator: Optional[Any] = None,
        quality_gate_validator: Optional[Any] = None
    ) -> None:
        """Initialize adaptive executor.

        Args:
            synthesis_coordinator: Coordinator for synthesizing agent outputs
            quality_gate_validator: Validator for quality gates
        """
        self.sequential_executor = SequentialStageExecutor()
        self.parallel_executor = ParallelStageExecutor(
            synthesis_coordinator=synthesis_coordinator,
            quality_gate_validator=quality_gate_validator
        )

    def execute_stage(
        self,
        stage_name: str,
        stage_config: Any,
        state: Dict[str, Any],
        config_loader: Any,
        tool_registry: Optional[Any] = None
    ) -> Dict[str, Any]:
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
        # Get tracker for observability
        tracker = state.get("tracker")

        # Get adaptive config
        stage_dict = stage_config if isinstance(stage_config, dict) else {}
        execution_config = stage_dict.get("execution", {})
        adaptive_config = execution_config.get("adaptive_config", {})

        # Get threshold (default: 0.5 = 50% disagreement)
        disagreement_threshold = adaptive_config.get("disagreement_threshold", 0.5)

        # Track mode switch metadata
        mode_switch_metadata = {
            "started_with": "parallel",
            "switched_to": None,
            "disagreement_rate": None,
            "disagreement_threshold": disagreement_threshold
        }

        try:
            # Round 1: Try parallel execution
            parallel_state = self.parallel_executor.execute_stage(
                stage_name=stage_name,
                stage_config=stage_config,
                state=state,
                config_loader=config_loader,
                tool_registry=tool_registry
            )

            # Get synthesis result from parallel execution
            stage_output = parallel_state["stage_outputs"][stage_name]
            synthesis_info = stage_output.get("synthesis", {})

            # Calculate disagreement rate from synthesis result
            # We need to reconstruct a minimal SynthesisResult-like object
            class MinimalSynthesisResult:
                """Lightweight synthesis result for disagreement calculation."""
                def __init__(self, votes: Dict[str, int]) -> None:
                    self.votes = votes

            synthesis_result = MinimalSynthesisResult(votes=synthesis_info.get("votes", {}))
            disagreement_rate = self._calculate_disagreement_rate(synthesis_result)

            mode_switch_metadata["disagreement_rate"] = disagreement_rate

            # Check if we need to switch to sequential
            if disagreement_rate > disagreement_threshold:
                mode_switch_metadata["switched_to"] = "sequential"

                # Track mode switch in observability
                if tracker and hasattr(tracker, 'track_collaboration_event'):
                    tracker.track_collaboration_event(
                        event_type="adaptive_mode_switch",
                        stage_name=stage_name,
                        agents=list(stage_output.get("agent_outputs", {}).keys()),
                        decision=None,
                        confidence=None,
                        metadata={
                            "reason": "disagreement_threshold_exceeded",
                            "disagreement_rate": disagreement_rate,
                            "threshold": disagreement_threshold,
                            "switching_from": "parallel",
                            "switching_to": "sequential"
                        }
                    )

                # Switch to sequential execution
                # Reset state to before parallel execution
                state["stage_outputs"].pop(stage_name, None)

                # Execute sequentially
                sequential_state = self.sequential_executor.execute_stage(
                    stage_name=stage_name,
                    stage_config=stage_config,
                    state=state,
                    config_loader=config_loader,
                    tool_registry=tool_registry
                )

                # Add mode switch metadata to final output
                if isinstance(sequential_state["stage_outputs"].get(stage_name), dict):
                    sequential_state["stage_outputs"][stage_name]["mode_switch"] = mode_switch_metadata

                return sequential_state
            else:
                # Disagreement is acceptable, keep parallel result
                mode_switch_metadata["switched_to"] = None  # No switch needed

                # Add mode switch metadata to output (no switch occurred)
                if isinstance(stage_output, dict):
                    stage_output["mode_switch"] = mode_switch_metadata
                    parallel_state["stage_outputs"][stage_name] = stage_output

                return parallel_state

        except Exception as e:
            # If parallel execution fails, fall back to sequential
            mode_switch_metadata["switched_to"] = "sequential"
            mode_switch_metadata["disagreement_rate"] = None
            mode_switch_metadata["error"] = str(e)

            # Track mode switch due to error
            if tracker and hasattr(tracker, 'track_collaboration_event'):
                tracker.track_collaboration_event(
                    event_type="adaptive_mode_switch",
                    stage_name=stage_name,
                    agents=[],
                    decision=None,
                    confidence=None,
                    metadata={
                        "reason": "parallel_execution_failed",
                        "error": str(e),
                        "switching_from": "parallel",
                        "switching_to": "sequential"
                    }
                )

            # Fall back to sequential
            state["stage_outputs"].pop(stage_name, None)
            sequential_state = self.sequential_executor.execute_stage(
                stage_name=stage_name,
                stage_config=stage_config,
                state=state,
                config_loader=config_loader,
                tool_registry=tool_registry
            )

            # Add mode switch metadata
            if isinstance(sequential_state["stage_outputs"].get(stage_name), dict):
                sequential_state["stage_outputs"][stage_name]["mode_switch"] = mode_switch_metadata

            return sequential_state

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
        disagreement_rate = 1.0 - (max_votes / total_votes)

        return disagreement_rate
