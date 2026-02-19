"""Parallel stage executor.

Executes multiple agents concurrently via a pluggable ParallelRunner.
"""
import logging
import time
import uuid
from typing import Any, Callable, Dict, Optional

from temper_ai.agent.utils.agent_factory import AgentFactory
from temper_ai.shared.core.protocols import ConfigLoaderProtocol, DomainToolRegistryProtocol
from temper_ai.stage.executors._parallel_helpers import (
    AgentNodeParams,
    QualityGateFailureParams,
    build_collect_outputs_node,
    build_init_parallel_node,
    create_agent_node,
    handle_quality_gate_failure,
    print_parallel_progress,
    update_state_with_results,
    validate_quality_gates,
)
from temper_ai.stage._config_accessors import (
    get_collaboration_inner_config,
    get_stage_agents,
    get_wall_clock_timeout,
    stage_config_to_dict,
)
from temper_ai.stage.executors.base import ParallelRunner, StageExecutor
from temper_ai.stage.executors.state_keys import StateKeys
from temper_ai.stage._schemas import QualityGatesConfig
from temper_ai.shared.constants.probabilities import PROB_VERY_HIGH
from temper_ai.shared.constants.sizes import UUID_HEX_SHORT_LENGTH
from temper_ai.shared.utils.exceptions import (
    ConfigNotFoundError,
    ConfigValidationError,
    LLMError,
    ToolExecutionError,
)

logger = logging.getLogger(__name__)


def _print_stage_header(state: Dict[str, Any], stage_name: str) -> None:
    """Print stage header if detail console is active."""
    if state.get(StateKeys.SHOW_DETAILS) and state.get(StateKeys.DETAIL_CONSOLE):
        state[StateKeys.DETAIL_CONSOLE].print(
            f"\n[bold cyan]\u2500\u2500 Stage: {stage_name} \u2500\u2500[/bold cyan]"
        )


def _persist_stage_output(
    tracker: Optional[Any], stage_id: Optional[str],
    state: Dict[str, Any], stage_name: str,
) -> None:
    """Persist stage output to DB for dashboard visibility."""
    from temper_ai.shared.core.protocols import TrackerProtocol

    if not (tracker and stage_id and isinstance(tracker, TrackerProtocol)):
        return
    try:
        stage_out = state.get(StateKeys.STAGE_OUTPUTS, {}).get(stage_name)
        if stage_out:
            tracker.set_stage_output(stage_id, stage_out)
    except Exception:
        logger.warning("Failed to persist stage output", exc_info=True)


def _extract_collab_config(stage_config: Any) -> dict:
    """Extract collaboration config from stage config (nested or flat format)."""
    return get_collaboration_inner_config(stage_config)


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
        tool_executor: Optional[Any] = None,
    ) -> None:
        """Initialize parallel executor.

        Args:
            synthesis_coordinator: Coordinator for synthesizing agent outputs
            quality_gate_validator: Validator for quality gates
            parallel_runner: Runner for parallel node execution (defaults to
                LangGraphParallelRunner)
            tool_executor: ToolExecutor with safety stack (optional).
                Wired through constructor instead of state dict.
        """
        self.synthesis_coordinator = synthesis_coordinator
        self.quality_gate_validator = quality_gate_validator
        if parallel_runner is None:
            from temper_ai.stage.executors.langgraph_runner import LangGraphParallelRunner
            parallel_runner = LangGraphParallelRunner()
        self.parallel_runner = parallel_runner
        self.tool_executor = tool_executor
        # Per-workflow agent cache: agent_name -> agent instance.
        # Avoids recreating agents on every parallel invocation.
        self._agent_cache: Dict[str, Any] = {}

    @staticmethod
    def _get_wall_clock_timeout(stage_config: Any) -> float:
        """Extract wall-clock timeout from stage config."""
        return get_wall_clock_timeout(stage_config)

    @staticmethod
    def _get_agents(stage_config: Any) -> list:
        """Extract agents list from stage config."""
        return get_stage_agents(stage_config)

    def _build_agent_nodes(
        self, agents: list, stage_name: str, state: Dict[str, Any],
        config_loader: ConfigLoaderProtocol,
        tracker: Optional[Any] = None, stage_id: Optional[str] = None,
    ) -> Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]]:
        """Build agent node callables for parallel execution."""
        nodes: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {}
        for agent_ref in agents:
            name = self._extract_agent_name(agent_ref)
            node_params = AgentNodeParams(
                agent_name=name, agent_ref=agent_ref, stage_name=stage_name,
                state=state, config_loader=config_loader,
                agent_cache=self._agent_cache, agent_factory_cls=AgentFactory,
                tracker=tracker, stage_id=stage_id,
                tool_executor=self.tool_executor,
            )
            nodes[name] = create_agent_node(node_params)
        return nodes

    def _run_parallel_and_synthesize(
        self, agents: list, stage_name: str, stage_config: Any,
        state: Dict[str, Any], config_loader: ConfigLoaderProtocol,
        tracker: Optional[Any] = None, stage_id: Optional[str] = None,
    ) -> tuple:
        """Run agents in parallel, synthesize, return (parallel_result, agent_outputs_dict, aggregate_metrics, synthesis_result)."""
        # Filter out leader agent from parallel batch (leader runs in synthesis phase)
        parallel_agents = self._filter_leader_from_agents(agents, stage_config)

        init_parallel = build_init_parallel_node(
            state,
            context_provider=self.context_provider,
            stage_config=stage_config,
        )
        collect_outputs = build_collect_outputs_node(parallel_agents, stage_config)
        agent_nodes = self._build_agent_nodes(
            parallel_agents, stage_name, state, config_loader,
            tracker=tracker, stage_id=stage_id,
        )

        initial_state: Dict[str, Any] = {
            StateKeys.AGENT_OUTPUTS: {}, StateKeys.AGENT_STATUSES: {},
            StateKeys.AGENT_METRICS: {}, StateKeys.ERRORS: {}, StateKeys.STAGE_INPUT: {},
        }
        parallel_result = self.parallel_runner.run_parallel(
            nodes=agent_nodes, initial_state=initial_state,
            init_node=init_parallel, collect_node=collect_outputs,
        )

        agent_outputs_dict = parallel_result[StateKeys.AGENT_OUTPUTS]
        if state.get(StateKeys.SHOW_DETAILS) and state.get(StateKeys.DETAIL_CONSOLE):
            print_parallel_progress(parallel_result, state[StateKeys.DETAIL_CONSOLE])
        logger.info("Stage '%s' parallel execution complete", stage_name)

        aggregate_metrics = agent_outputs_dict.pop(StateKeys.AGGREGATE_METRICS_KEY, {})

        from temper_ai.agent.strategies.base import AgentOutput
        agent_output_list = [
            AgentOutput(
                agent_name=a_name,
                decision=data.get(StateKeys.OUTPUT, ""),
                reasoning=data.get(StateKeys.REASONING, ""),
                confidence=data.get(StateKeys.CONFIDENCE, PROB_VERY_HIGH),
                metadata=data.get("metadata", {}),
            )
            for a_name, data in agent_outputs_dict.items()
        ]
        # Make stage_id available for dialogue synthesis tracking
        if stage_id:
            state[StateKeys.CURRENT_STAGE_ID] = stage_id
        synthesis_result = self._run_synthesis(
            agent_outputs=agent_output_list, stage_config=stage_config,
            stage_name=stage_name, state=state,
            config_loader=config_loader, agents=agents,
        )
        return parallel_result, agent_outputs_dict, aggregate_metrics, synthesis_result

    @staticmethod
    def _handle_stage_error(stage_name: str, stage_config: Any, state: Dict[str, Any], exc: Exception) -> Dict[str, Any]:
        """Handle error based on error_handling policy. Returns state or re-raises."""
        logger.error(
            "Stage '%s' failed during parallel execution: %s: %s",
            stage_name, type(exc).__name__, exc, exc_info=True,
        )
        stage_dict = stage_config if isinstance(stage_config, dict) else {}
        on_failure = stage_dict.get("error_handling", {}).get("on_stage_failure", "halt")
        if on_failure == "skip":
            logger.warning(
                "Stage '%s' error_handling policy is 'skip'; continuing without this stage's output.",
                stage_name,
            )
            state[StateKeys.STAGE_OUTPUTS][stage_name] = None
            return state
        raise exc

    def execute_stage(
        self,
        stage_name: str,
        stage_config: Any,
        state: Dict[str, Any],
        config_loader: ConfigLoaderProtocol,
        tool_registry: Optional[DomainToolRegistryProtocol] = None
    ) -> Dict[str, Any]:
        """Execute stage with parallel agent execution. Returns updated state."""
        tracker = state.get(StateKeys.TRACKER)
        workflow_id = state.get(StateKeys.WORKFLOW_ID, "unknown")
        stage_config_dict = stage_config_to_dict(stage_config)
        if tracker:
            from temper_ai.stage.executors._base_helpers import prepare_tracking_input
            tracking_input = prepare_tracking_input(
                state.get(StateKeys.STAGE_OUTPUTS, {}),
            )
            with tracker.track_stage(
                stage_name=stage_name, stage_config=stage_config_dict,
                workflow_id=workflow_id, input_data=tracking_input,
            ) as stage_id:
                return self._execute_stage_core(
                    stage_name, stage_config, state, config_loader,
                    tracker=tracker, stage_id=stage_id,
                )
        else:
            return self._execute_stage_core(
                stage_name, stage_config, state, config_loader,
                tracker=None, stage_id=f"stage-{uuid.uuid4().hex[:UUID_HEX_SHORT_LENGTH]}",
            )

    @staticmethod
    def _get_max_retries(stage_config: Any) -> int:
        """Extract max quality gate retries from stage config."""
        default_retries: int = QualityGatesConfig.model_fields["max_retries"].default
        if isinstance(stage_config, dict):
            qg = stage_config.get("quality_gates", {})
            result: int = qg.get("max_retries", default_retries)
            return result
        if hasattr(stage_config, "quality_gates") and stage_config.quality_gates:
            retries: int = stage_config.quality_gates.max_retries
            return retries
        return default_retries

    def _execute_stage_core(
        self,
        stage_name: str,
        stage_config: Any,
        state: Dict[str, Any],
        config_loader: ConfigLoaderProtocol,
        tracker: Optional[Any] = None,
        stage_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Core stage execution logic (bounded retry loop)."""
        wc_timeout = self._get_wall_clock_timeout(stage_config)
        wc_start = time.monotonic()
        max_retries = self._get_max_retries(stage_config)

        for _attempt in range(max_retries + 1):
            agents = self._get_agents(stage_config)
            _print_stage_header(state, stage_name)

            try:
                pr, ao_dict, agg, synth = self._run_parallel_and_synthesize(
                    agents, stage_name, stage_config, state, config_loader,
                    tracker=tracker, stage_id=stage_id,
                )
                passed, violations = self._validate_quality_gates(
                    synthesis_result=synth, stage_config=stage_config,
                    stage_name=stage_name, state=state,
                )
                failure_params = QualityGateFailureParams(
                    passed=passed, violations=violations, synthesis_result=synth,
                    stage_config=stage_config, stage_name=stage_name, state=state,
                    wall_clock_start=wc_start, wall_clock_timeout=wc_timeout,
                )
                action = handle_quality_gate_failure(failure_params)
                if action == "continue":
                    continue
                structured = self._extract_structured_fields(
                    stage_config, synth.decision, stage_name,
                )
                update_state_with_results(
                    state=state, stage_name=stage_name, synthesis_result=synth,
                    agent_outputs_dict=ao_dict, parallel_result=pr,
                    aggregate_metrics=agg, structured=structured,
                )
                _persist_stage_output(tracker, stage_id, state, stage_name)
                return state

            except (RuntimeError, ConfigNotFoundError, ConfigValidationError, ToolExecutionError, LLMError, ValueError) as exc:
                return self._handle_stage_error(stage_name, stage_config, state, exc)

        raise RuntimeError(
            f"Stage '{stage_name}' exhausted {max_retries} quality gate retries"
        )

    def _filter_leader_from_agents(
        self, agents: list, stage_config: Any,
    ) -> list:
        """Remove leader agent from agent list if using leader strategy."""
        try:
            from temper_ai.agent.strategies.registry import get_strategy_from_config

            from temper_ai.stage.executors._protocols import LeaderCapableStrategy

            strategy = get_strategy_from_config(stage_config)
            if not (isinstance(strategy, LeaderCapableStrategy) and strategy.requires_leader_synthesis):
                return agents

            collab_config = _extract_collab_config(stage_config)
            leader_name = strategy.get_leader_agent_name(collab_config)
            if not leader_name:
                return agents

            filtered = [
                a for a in agents
                if self._extract_agent_name(a) != leader_name
            ]
            if len(filtered) < len(agents):
                logger.info(
                    "Leader strategy: excluded '%s' from parallel batch "
                    "(%d perspective agents remain)",
                    leader_name,
                    len(filtered),
                )
            return filtered

        except (ImportError, ValueError):
            return agents

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
        config_loader: ConfigLoaderProtocol,
        tracker: Optional[Any] = None,
        stage_id: Optional[str] = None,
    ) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
        """Create execution node for a single agent in parallel execution.

        Args:
            agent_name: Agent name
            agent_ref: Agent reference from stage config
            stage_name: Stage name
            state: Workflow state (for context)
            config_loader: ConfigLoader for loading agent configs
            tracker: ExecutionTracker instance (optional)
            stage_id: Stage execution ID (optional)

        Returns:
            Callable node function that executes the agent
        """
        return create_agent_node(AgentNodeParams(
            agent_name=agent_name,
            agent_ref=agent_ref,
            stage_name=stage_name,
            state=state,
            config_loader=config_loader,
            agent_cache=self._agent_cache,
            agent_factory_cls=AgentFactory,
            tracker=tracker,
            stage_id=stage_id,
            tool_executor=self.tool_executor,
        ))

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
