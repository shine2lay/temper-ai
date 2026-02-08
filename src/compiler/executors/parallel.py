"""Parallel stage executor.

Executes multiple agents concurrently via a pluggable ParallelRunner.
"""
import logging
import time
from typing import Any, Callable, Dict, Optional

from src.agents.agent_factory import AgentFactory
from src.compiler.domain_state import ConfigLoaderProtocol, DomainToolRegistryProtocol
from src.compiler.executors._parallel_helpers import (
    build_collect_outputs_node,
    build_init_parallel_node,
    create_agent_node,
    handle_quality_gate_failure,
    print_parallel_progress,
    update_state_with_results,
    validate_quality_gates,
)
from src.compiler.executors.base import ParallelRunner, StageExecutor
from src.constants.durations import SECONDS_PER_10_MINUTES
from src.constants.probabilities import PROB_VERY_HIGH
from src.utils.config_helpers import get_nested_value
from src.utils.exceptions import (
    ConfigNotFoundError,
    ConfigValidationError,
    LLMError,
    ToolExecutionError,
)

logger = logging.getLogger(__name__)


class ParallelStageExecutor(StageExecutor):
    """Execute agents in parallel (M3 mode).

    Creates a nested LangGraph with parallel branches for each agent,
    collects outputs, and delegates to synthesis coordinator.
    """

    def __init__(
        self,
        synthesis_coordinator: Optional[Any] = None,
        quality_gate_validator: Optional[Any] = None,
        parallel_runner: Optional[ParallelRunner] = None,
    ) -> None:
        """Initialize parallel executor.

        Args:
            synthesis_coordinator: Coordinator for synthesizing agent outputs
            quality_gate_validator: Validator for quality gates
            parallel_runner: Runner for parallel node execution (defaults to
                LangGraphParallelRunner)
        """
        self.synthesis_coordinator = synthesis_coordinator
        self.quality_gate_validator = quality_gate_validator
        if parallel_runner is None:
            from src.compiler.executors.langgraph_runner import LangGraphParallelRunner
            parallel_runner = LangGraphParallelRunner()
        self.parallel_runner = parallel_runner
        # Per-workflow agent cache: agent_name -> agent instance.
        # Avoids recreating agents on every parallel invocation.
        self._agent_cache: Dict[str, Any] = {}

    def execute_stage(
        self,
        stage_name: str,
        stage_config: Any,
        state: Dict[str, Any],
        config_loader: ConfigLoaderProtocol,
        tool_registry: Optional[DomainToolRegistryProtocol] = None
    ) -> Dict[str, Any]:
        """Execute stage with parallel agent execution.

        Creates a nested LangGraph with parallel branches for agents,
        collects outputs, and synthesizes via collaboration strategy.

        Uses an iterative loop for quality gate retries to avoid stack
        overflow with high max_retries values.

        Args:
            stage_name: Stage name
            stage_config: Stage configuration
            state: Current workflow state
            config_loader: ConfigLoader for loading agent configs
            tool_registry: ToolRegistry for agent tool access

        Returns:
            Updated workflow state with synthesized output

        Raises:
            RuntimeError: If stage execution fails
        """
        # Derive wall-clock timeout for the entire retry loop from stage config.
        _wall_clock_timeout: float = SECONDS_PER_10_MINUTES
        if hasattr(stage_config, 'stage') and hasattr(stage_config.stage, 'execution'):
            _wall_clock_timeout = float(
                getattr(stage_config.stage.execution, 'timeout_seconds', SECONDS_PER_10_MINUTES)
            )
        elif isinstance(stage_config, dict):
            _exec_cfg = get_nested_value(stage_config, 'stage.execution') or {}
            _wall_clock_timeout = float(_exec_cfg.get('timeout_seconds', SECONDS_PER_10_MINUTES))

        _wall_clock_start = time.monotonic()

        # Iterative retry loop -- replaces former recursive self.execute_stage() call.
        while True:
            # Get agents for this stage
            if hasattr(stage_config, 'stage'):
                agents = stage_config.stage.agents
            else:
                agents = get_nested_value(stage_config, 'stage.agents') or stage_config.get('agents', [])

            # Build init and collection nodes via helpers
            init_parallel = build_init_parallel_node(state)
            collect_outputs = build_collect_outputs_node(agents, stage_config)

            # Build agent nodes
            agent_nodes: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {}
            for agent_ref in agents:
                agent_name = self._extract_agent_name(agent_ref)
                agent_nodes[agent_name] = create_agent_node(
                    agent_name=agent_name,
                    agent_ref=agent_ref,
                    stage_name=stage_name,
                    state=state,
                    config_loader=config_loader,
                    agent_cache=self._agent_cache,
                    agent_factory_cls=AgentFactory,
                )

            prior_stages = list(state.get("stage_outputs", {}).keys())
            input_info = f"prior stages: {prior_stages}" if prior_stages else "workflow inputs only"
            logger.info("Stage '%s' starting parallel execution with %d agent(s) (%s)", stage_name, len(agents), input_info)

            show_details = state.get("show_details", False)
            detail_console = state.get("detail_console")
            if show_details and detail_console:
                detail_console.print(f"\n[bold cyan]\u2500\u2500 Stage: {stage_name} \u2500\u2500[/bold cyan]")

            try:
                initial_state: Dict[str, Any] = {
                    "agent_outputs": {},
                    "agent_statuses": {},
                    "agent_metrics": {},
                    "errors": {},
                    "stage_input": {}
                }
                parallel_result = self.parallel_runner.run_parallel(
                    nodes=agent_nodes,
                    initial_state=initial_state,
                    init_node=init_parallel,
                    collect_node=collect_outputs,
                )

                agent_outputs_dict = parallel_result["agent_outputs"]

                # Print progress for parallel agents (after all complete)
                if show_details and detail_console:
                    print_parallel_progress(parallel_result, detail_console)

                logger.info("Stage '%s' parallel execution complete", stage_name)

                # Extract aggregate metrics (stored with special key)
                aggregate_metrics = agent_outputs_dict.pop("__aggregate_metrics__", {})

                # Create AgentOutput objects for synthesis
                from src.strategies.base import AgentOutput

                agent_outputs = []
                for a_name, output_data in agent_outputs_dict.items():
                    agent_outputs.append(AgentOutput(
                        agent_name=a_name,
                        decision=output_data.get("output", ""),
                        reasoning=output_data.get("reasoning", ""),
                        confidence=output_data.get("confidence", PROB_VERY_HIGH),
                        metadata=output_data.get("metadata", {})
                    ))

                # Run synthesis
                synthesis_result = self._run_synthesis(
                    agent_outputs=agent_outputs,
                    stage_config=stage_config,
                    stage_name=stage_name,
                    state=state,
                    config_loader=config_loader,
                    agents=agents
                )

                # Validate quality gates (M3-12)
                passed, violations = self._validate_quality_gates(
                    synthesis_result=synthesis_result,
                    stage_config=stage_config,
                    stage_name=stage_name,
                    state=state
                )

                # Handle quality gate failures via helper
                action = handle_quality_gate_failure(
                    passed=passed,
                    violations=violations,
                    synthesis_result=synthesis_result,
                    stage_config=stage_config,
                    stage_name=stage_name,
                    state=state,
                    wall_clock_start=_wall_clock_start,
                    wall_clock_timeout=_wall_clock_timeout,
                )
                if action == "continue":
                    continue

                # Update state with results via helper
                update_state_with_results(
                    state=state,
                    stage_name=stage_name,
                    synthesis_result=synthesis_result,
                    agent_outputs_dict=agent_outputs_dict,
                    parallel_result=parallel_result,
                    aggregate_metrics=aggregate_metrics,
                )

                return state

            except (RuntimeError, ConfigNotFoundError, ConfigValidationError, ToolExecutionError, LLMError, ValueError) as exc:
                logger.error(
                    "Stage '%s' failed during parallel execution: %s: %s",
                    stage_name, type(exc).__name__, exc, exc_info=True,
                )

                stage_dict = stage_config if isinstance(stage_config, dict) else {}
                error_handling = stage_dict.get("error_handling", {})
                on_failure = error_handling.get("on_stage_failure", "halt")

                if on_failure == "halt":
                    raise
                elif on_failure == "skip":
                    logger.warning(
                        "Stage '%s' error_handling policy is 'skip'; "
                        "continuing workflow without this stage's output.",
                        stage_name,
                    )
                    state["stage_outputs"][stage_name] = None
                    return state
                else:
                    raise

    def supports_stage_type(self, stage_type: str) -> bool:
        """Check if executor supports this stage type.

        Args:
            stage_type: Stage type identifier

        Returns:
            True for "parallel" type
        """
        return stage_type == "parallel"

    def _create_agent_node(
        self,
        agent_name: str,
        agent_ref: Any,
        stage_name: str,
        state: Dict[str, Any],
        config_loader: ConfigLoaderProtocol
    ) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
        """Create execution node for a single agent in parallel execution.

        Args:
            agent_name: Agent name
            agent_ref: Agent reference from stage config
            stage_name: Stage name
            state: Workflow state (for context)
            config_loader: ConfigLoader for loading agent configs

        Returns:
            Callable node function that executes the agent
        """
        return create_agent_node(
            agent_name=agent_name,
            agent_ref=agent_ref,
            stage_name=stage_name,
            state=state,
            config_loader=config_loader,
            agent_cache=self._agent_cache,
            agent_factory_cls=AgentFactory,
        )

    def _validate_quality_gates(
        self,
        synthesis_result: Any,
        stage_config: Any,
        stage_name: str,
        state: Dict[str, Any]
    ) -> tuple[bool, list[str]]:
        """Validate synthesis result against quality gates.

        Args:
            synthesis_result: SynthesisResult from synthesis
            stage_config: Stage configuration
            stage_name: Stage name
            state: Current workflow state

        Returns:
            Tuple of (passed: bool, violations: List[str])
        """
        return validate_quality_gates(
            quality_gate_validator=self.quality_gate_validator,
            synthesis_result=synthesis_result,
            stage_config=stage_config,
            stage_name=stage_name,
            state=state,
        )
