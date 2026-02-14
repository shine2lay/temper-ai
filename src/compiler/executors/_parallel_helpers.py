"""Helper functions extracted from ParallelStageExecutor to reduce class size.

Contains:
- Agent node creation for parallel execution
- Quality gate validation
- Parallel execution orchestration
- Output collection and metric aggregation
"""
import logging
import time
import uuid
from typing import Any, Callable, Dict, Optional, cast

from src.compiler.constants import ERROR_MSG_QUALITY_GATE_FAILED
from src.compiler.executors.state_keys import StateKeys
from src.constants.limits import DEFAULT_MIN_ITEMS, SMALL_ITEM_LIMIT
from src.constants.probabilities import PROB_HIGH
from src.constants.sizes import UUID_HEX_SHORT_LENGTH
from src.core.context import ExecutionContext
from src.utils.exceptions import (
    ConfigNotFoundError,
    ConfigValidationError,
    LLMError,
    ToolExecutionError,
)

logger = logging.getLogger(__name__)


def _prepare_agent_input(s: Dict[str, Any]) -> Dict[str, Any]:
    """Prepare agent input data by unwrapping workflow_inputs and filtering reserved keys."""
    _reserved = frozenset({
        StateKeys.STAGE_OUTPUTS, StateKeys.CURRENT_STAGE, StateKeys.WORKFLOW_ID, StateKeys.TRACKER,
        StateKeys.TOOL_REGISTRY, StateKeys.CONFIG_LOADER, StateKeys.VISUALIZER, StateKeys.SHOW_DETAILS,
        StateKeys.DETAIL_CONSOLE, StateKeys.WORKFLOW_INPUTS, StateKeys.TOOL_EXECUTOR, StateKeys.STREAM_CALLBACK,
    })
    input_data = s.get(StateKeys.STAGE_INPUT, {})
    wi = {k: v for k, v in input_data.get(StateKeys.WORKFLOW_INPUTS, {}).items()
          if k not in _reserved}
    return {**input_data, **wi}


def _build_agent_success_result(
    agent_name: str,
    response: Any,
    duration: float
) -> Dict[str, Any]:
    """Build success result dict from agent response."""
    return {
        StateKeys.AGENT_OUTPUTS: {
            agent_name: {
                StateKeys.OUTPUT: response.output,
                StateKeys.REASONING: response.reasoning,
                StateKeys.CONFIDENCE: response.confidence,
                StateKeys.TOKENS: response.tokens,
                StateKeys.COST_USD: response.estimated_cost_usd,
                StateKeys.TOOL_CALLS: response.tool_calls if response.tool_calls else [],
            }
        },
        StateKeys.AGENT_STATUSES: {agent_name: "success"},
        StateKeys.AGENT_METRICS: {
            agent_name: {
                StateKeys.TOKENS: response.tokens,
                StateKeys.COST_USD: response.estimated_cost_usd,
                StateKeys.DURATION_SECONDS: duration,
                StateKeys.TOOL_CALLS: len(response.tool_calls) if response.tool_calls else 0,
                StateKeys.RETRIES: 0
            }
        },
        StateKeys.ERRORS: {}
    }


def _build_agent_error_result(
    agent_name: str,
    e: Exception,
    duration: float
) -> Dict[str, Any]:
    """Build error result dict from exception."""
    return {
        StateKeys.AGENT_OUTPUTS: {},
        StateKeys.AGENT_STATUSES: {agent_name: "failed"},
        StateKeys.AGENT_METRICS: {
            agent_name: {
                StateKeys.TOKENS: 0,
                StateKeys.COST_USD: 0.0,
                StateKeys.DURATION_SECONDS: duration,
                StateKeys.TOOL_CALLS: 0,
                StateKeys.RETRIES: 0
            }
        },
        StateKeys.ERRORS: {agent_name: f"{type(e).__name__}: {str(e)}"}
    }


def _execute_agent_with_tracking(
    agent: Any,
    input_data: Dict[str, Any],
    context: Any,
    agent_name: str,
    agent_config_dict: Dict[str, Any],
    tracker: Any,
    stage_id: str
) -> Any:
    """Execute agent with tracker context and set output tracking."""
    from src.utils.config_helpers import sanitize_config_for_display

    agent_config_for_tracking = sanitize_config_for_display(agent_config_dict)

    # Filter non-serializable keys for tracking
    _non_serializable_keys: frozenset[str] = frozenset({
        StateKeys.TRACKER, StateKeys.TOOL_REGISTRY, StateKeys.CONFIG_LOADER, StateKeys.VISUALIZER,
        StateKeys.SHOW_DETAILS, StateKeys.DETAIL_CONSOLE, StateKeys.TOOL_EXECUTOR, StateKeys.STREAM_CALLBACK,
    })
    tracking_input_data = {
        k: v for k, v in input_data.items()
        if k not in _non_serializable_keys
    }
    tracking_input_data = sanitize_config_for_display(tracking_input_data)

    with tracker.track_agent(
        agent_name=agent_name,
        agent_config=agent_config_for_tracking,
        stage_id=stage_id,
        input_data=tracking_input_data,
    ) as agent_id:
        context.agent_id = agent_id
        input_data[StateKeys.TRACKER] = tracker
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
            logger.warning("Failed to set agent output tracking for %s", agent_name, exc_info=True)

    return response


def _resolve_agent_factory(agent_factory_cls: Any) -> Any:
    """Resolve agent factory class, importing default if needed."""
    if agent_factory_cls is not None:
        return agent_factory_cls
    from src.agents.agent_factory import AgentFactory as _AgentFactory
    return _AgentFactory


def _load_or_cache_agent(
    agent_name: str,
    config_loader: Any,
    agent_cache: Dict[str, Any],
    agent_factory: Any,
) -> tuple[Any, Any, Dict[str, Any]]:
    """Load agent config, create or retrieve cached agent instance.

    Returns:
        Tuple of (agent, agent_config, agent_config_dict)
    """
    from src.compiler.schemas import AgentConfig

    agent_config_dict = config_loader.load_agent(agent_name)
    agent_config = AgentConfig(**agent_config_dict)
    if agent_name in agent_cache:
        agent = agent_cache[agent_name]
    else:
        agent = agent_factory.create(agent_config)
        agent_cache[agent_name] = agent
    return agent, agent_config, agent_config_dict


def _config_to_tracking_dict(agent_config: Any, agent_config_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Convert agent config to a dict suitable for tracking."""
    if hasattr(agent_config, 'model_dump'):
        return agent_config.model_dump()
    if hasattr(agent_config, 'dict'):
        return agent_config.dict()
    return dict(agent_config_dict)


def _create_agent_context(
    state: Dict[str, Any],
    stage_name: str,
    agent_name: str,
    effective_stage_id: str,
) -> Any:
    """Create ExecutionContext for an agent node."""
    return ExecutionContext(
        workflow_id=state.get(StateKeys.WORKFLOW_ID, "unknown"),
        stage_id=effective_stage_id,
        agent_id=f"agent-{uuid.uuid4().hex[:UUID_HEX_SHORT_LENGTH]}",
        metadata={
            "stage_name": stage_name,
            "agent_name": agent_name,
            "execution_mode": "parallel"
        }
    )


def _run_agent(
    agent: Any,
    input_data: Dict[str, Any],
    context: Any,
    agent_name: str,
    agent_config_dict_for_tracking: Dict[str, Any],
    tracker: Optional[Any],
    stage_id: Optional[str],
    effective_stage_id: str,
) -> Any:
    """Execute agent with or without tracking."""
    if tracker and stage_id:
        return _execute_agent_with_tracking(
            agent, input_data, context, agent_name,
            agent_config_dict_for_tracking, tracker, effective_stage_id
        )
    input_data.pop(StateKeys.TRACKER, None)
    return agent.execute(input_data, context)


def create_agent_node(
    agent_name: str,
    agent_ref: Any,
    stage_name: str,
    state: Dict[str, Any],
    config_loader: Any,
    agent_cache: Dict[str, Any],
    agent_factory_cls: Any = None,
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
        agent_cache: Per-workflow agent cache dict
        agent_factory_cls: AgentFactory class (optional)
        tracker: ExecutionTracker instance (optional)
        stage_id: Stage execution ID (optional)

    Returns:
        Callable node function that executes the agent
    """
    def agent_node(s: Dict[str, Any]) -> Dict[str, Any]:
        """Execute single agent and store result."""
        start_time = time.time()

        try:
            agent_factory = _resolve_agent_factory(agent_factory_cls)
            agent, agent_config, agent_config_dict = _load_or_cache_agent(
                agent_name, config_loader, agent_cache, agent_factory
            )
            input_data = _prepare_agent_input(s)
            agent_config_dict_for_tracking = _config_to_tracking_dict(agent_config, agent_config_dict)
            effective_stage_id = stage_id if stage_id else f"stage-{uuid.uuid4().hex[:UUID_HEX_SHORT_LENGTH]}"
            context = _create_agent_context(state, stage_name, agent_name, effective_stage_id)

            response = _run_agent(
                agent, input_data, context, agent_name,
                agent_config_dict_for_tracking, tracker, stage_id, effective_stage_id
            )

            duration = time.time() - start_time
            return _build_agent_success_result(agent_name, response, duration)

        except (ConfigNotFoundError, ConfigValidationError, ValueError, TypeError, KeyError) as e:
            logger.info(f"Agent {agent_name} configuration/validation error: {e}")
            duration = time.time() - start_time
            return _build_agent_error_result(agent_name, e, duration)

        except (KeyboardInterrupt, SystemExit):
            raise

        except (RuntimeError, ToolExecutionError, LLMError, ValueError, TypeError) as e:
            logger.error(
                f"Unexpected error in agent {agent_name}: {type(e).__name__}: {e}",
                exc_info=True
            )
            duration = time.time() - start_time
            return _build_agent_error_result(agent_name, e, duration)

    return agent_node


def validate_quality_gates(
    quality_gate_validator: Optional[Any],
    synthesis_result: Any,
    stage_config: Any,
    stage_name: str,
    state: Dict[str, Any],
) -> tuple[bool, list[str]]:
    """Validate synthesis result against quality gates.

    Args:
        quality_gate_validator: Optional validator instance
        synthesis_result: SynthesisResult from synthesis
        stage_config: Stage configuration
        stage_name: Stage name
        state: Current workflow state

    Returns:
        Tuple of (passed: bool, violations: List[str])
    """
    if quality_gate_validator:
        return cast(
            tuple[bool, list[str]],
            quality_gate_validator.validate(
                synthesis_result=synthesis_result,
                stage_config=stage_config,
                stage_name=stage_name
            )
        )

    # Fallback to inline implementation
    stage_dict = stage_config if isinstance(stage_config, dict) else {}
    quality_gates_config = stage_dict.get("quality_gates", {})

    if not quality_gates_config.get("enabled", False):
        return True, []

    violations = []

    # Check minimum confidence
    min_confidence = quality_gates_config.get("min_confidence", PROB_HIGH)
    actual_confidence = getattr(synthesis_result, "confidence", 0.0)
    if actual_confidence < min_confidence:
        violations.append(
            f"Confidence {actual_confidence:.2f} below minimum {min_confidence:.2f}"
        )

    # Check minimum findings
    min_findings = quality_gates_config.get("min_findings", SMALL_ITEM_LIMIT)
    findings = []
    if hasattr(synthesis_result, "metadata"):
        findings = synthesis_result.metadata.get("findings", [])
    elif hasattr(synthesis_result, "decision") and isinstance(synthesis_result.decision, dict):
        findings = synthesis_result.decision.get("findings", [])

    if min_findings > 0 and len(findings) < min_findings:
        violations.append(
            f"Only {len(findings)} findings, minimum {min_findings} required"
        )

    # Check citations required
    require_citations = quality_gates_config.get("require_citations", True)
    if require_citations:
        citations = []
        if hasattr(synthesis_result, "metadata"):
            citations = synthesis_result.metadata.get("citations", [])
        elif hasattr(synthesis_result, "decision") and isinstance(synthesis_result.decision, dict):
            citations = synthesis_result.decision.get("citations", [])

        if not citations:
            violations.append("No citations provided")

    passed = len(violations) == 0
    return passed, violations


def build_collect_outputs_node(
    agents: list,
    stage_config: Any,
) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    """Build the collection node function for parallel execution.

    Args:
        agents: List of agent references
        stage_config: Stage configuration

    Returns:
        Callable node function for collecting outputs
    """
    def collect_outputs(s: Dict[str, Any]) -> Dict[str, Any]:
        """Collect and validate agent outputs, calculate aggregate metrics."""
        stage_dict = stage_config if isinstance(stage_config, dict) else {}
        error_handling = stage_dict.get("error_handling", {})
        min_successful = error_handling.get("min_successful_agents", DEFAULT_MIN_ITEMS)

        agent_statuses = s.get(StateKeys.AGENT_STATUSES, {})
        successful = [
            name for name, status in agent_statuses.items()
            if status == "success"
        ]

        if len(successful) < min_successful:
            raise RuntimeError(
                f"Only {len(successful)}/{len(agents)} agents succeeded. "
                f"Minimum required: {min_successful}"
            )

        agent_metrics = s.get(StateKeys.AGENT_METRICS, {})
        agent_outputs_dict = s.get(StateKeys.AGENT_OUTPUTS, {})

        total_tokens = 0
        total_cost = 0.0
        max_duration = 0.0
        total_confidence = 0.0
        num_successful = 0

        for agent_name, metrics in agent_metrics.items():
            if agent_statuses.get(agent_name) == "success":
                total_tokens += metrics.get(StateKeys.TOKENS, 0)
                total_cost += metrics.get(StateKeys.COST_USD, 0.0)
                max_duration = max(max_duration, metrics.get(StateKeys.DURATION_SECONDS, 0.0))

                output = agent_outputs_dict.get(agent_name, {})
                total_confidence += output.get(StateKeys.CONFIDENCE, 0.0)
                num_successful += 1

        avg_confidence = total_confidence / num_successful if num_successful > 0 else 0.0

        return {
            StateKeys.AGENT_OUTPUTS: {
                StateKeys.AGGREGATE_METRICS_KEY: {
                    StateKeys.TOTAL_TOKENS: total_tokens,
                    StateKeys.TOTAL_COST_USD: total_cost,
                    StateKeys.TOTAL_DURATION_SECONDS: max_duration,
                    StateKeys.AVG_CONFIDENCE: avg_confidence,
                    StateKeys.NUM_AGENTS: len(agents),
                    StateKeys.NUM_SUCCESSFUL: num_successful,
                    StateKeys.NUM_FAILED: len(agents) - num_successful
                }
            }
        }

    return collect_outputs


def build_init_parallel_node(
    state: Dict[str, Any],
) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    """Build the init node function for parallel execution.

    Args:
        state: Current workflow state

    Returns:
        Callable node function for initializing parallel state
    """
    def init_parallel(s: Dict[str, Any]) -> Dict[str, Any]:
        """Initialize parallel state with empty collections."""
        return {
            StateKeys.AGENT_OUTPUTS: {},
            StateKeys.AGENT_STATUSES: {},
            StateKeys.AGENT_METRICS: {},
            StateKeys.ERRORS: {},
            StateKeys.STAGE_INPUT: {
                **state,
                StateKeys.STAGE_OUTPUTS: state.get(StateKeys.STAGE_OUTPUTS, {})
            }
        }

    return init_parallel


def print_parallel_progress(
    parallel_result: Dict[str, Any],
    detail_console: Any,
) -> None:
    """Print progress for parallel agents after all complete.

    Args:
        parallel_result: Result dict from parallel runner
        detail_console: Rich console for detail output
    """
    agent_statuses = parallel_result.get(StateKeys.AGENT_STATUSES, {})
    agent_metrics_dict = parallel_result.get(StateKeys.AGENT_METRICS, {})
    agent_names = list(agent_statuses.keys())
    for idx, aname in enumerate(agent_names):
        is_last = (idx == len(agent_names) - 1)
        connector = "\u2514\u2500" if is_last else "\u251c\u2500"
        status = agent_statuses.get(aname, "unknown")
        m = agent_metrics_dict.get(aname, {})
        duration = m.get(StateKeys.DURATION_SECONDS, 0.0)
        tokens = m.get(StateKeys.TOKENS, 0)

        if status == "success":
            detail_console.print(
                f"  {connector} [green]{aname} \u2713[/green] ({duration:.1f}s, {tokens} tokens)"
            )
        else:
            detail_console.print(
                f"  {connector} [red]{aname} \u2717[/red] ({duration:.1f}s)"
            )


def _track_quality_gate_event(
    tracker: Any,
    event_type: str,
    stage_name: str,
    synthesis_result: Any,
    violations: list,
    quality_gates_config: Dict[str, Any],
    retry_count: int
) -> None:
    """Track quality gate event in observability system."""
    if tracker and hasattr(tracker, 'track_collaboration_event'):
        metadata = {
            "violations": violations,
            "synthesis_method": synthesis_result.method,
            "retry_count": retry_count,
            "max_retries": quality_gates_config.get("max_retries", 2)
        }
        if event_type == "quality_gate_failure":
            metadata["on_failure_action"] = quality_gates_config.get("on_failure", "retry_stage")
        elif event_type == "quality_gate_retry":
            metadata["retry_attempt"] = retry_count + 1

        tracker.track_collaboration_event(
            event_type=event_type,
            stage_name=stage_name,
            agents=[],
            decision=None,
            confidence=getattr(synthesis_result, "confidence", 0.0),
            metadata=metadata
        )


def _handle_quality_gate_escalate(stage_name: str, violations: list) -> None:
    """Handle escalate policy for quality gate failure."""
    raise RuntimeError(
        f"{ERROR_MSG_QUALITY_GATE_FAILED}{stage_name}': {'; '.join(violations)}"
    )


def _handle_quality_gate_warn(
    stage_name: str,
    violations: list,
    synthesis_result: Any
) -> None:
    """Handle proceed_with_warning policy for quality gate failure."""
    logger.warning(
        f"{ERROR_MSG_QUALITY_GATE_FAILED}{stage_name}' but proceeding: {'; '.join(violations)}"
    )
    if not hasattr(synthesis_result, "metadata") or synthesis_result.metadata is None:
        synthesis_result.metadata = {}
    synthesis_result.metadata[StateKeys.QUALITY_GATE_WARNING] = violations


def _check_retry_timeout(
    stage_name: str,
    wall_clock_start: float,
    wall_clock_timeout: float,
    retry_count: int,
    violations: list
) -> None:
    """Check if wall-clock timeout exceeded during retry."""
    elapsed = time.monotonic() - wall_clock_start
    if elapsed >= wall_clock_timeout:
        raise RuntimeError(
            f"Quality gate retry for stage '{stage_name}' aborted: "
            f"wall-clock timeout ({wall_clock_timeout:.0f}s) exceeded "
            f"after {elapsed:.1f}s and {retry_count + 1} retries. "
            f"Violations: {'; '.join(violations)}"
        )


def _reset_retry_counter_on_pass(
    passed: bool, state: Dict[str, Any], stage_name: str
) -> None:
    """Reset retry counter if quality gates passed after retries."""
    if passed and StateKeys.STAGE_RETRY_COUNTS in state and stage_name in state[StateKeys.STAGE_RETRY_COUNTS]:
        retry_count = state[StateKeys.STAGE_RETRY_COUNTS][stage_name]
        del state[StateKeys.STAGE_RETRY_COUNTS][stage_name]
        logger.info(
            f"Stage '{stage_name}' passed quality gates after {retry_count} retries"
        )


def _handle_quality_gate_retry(
    quality_gates_config: Dict[str, Any],
    stage_name: str,
    state: Dict[str, Any],
    tracker: Any,
    synthesis_result: Any,
    violations: list,
    wall_clock_start: float,
    wall_clock_timeout: float,
) -> str:
    """Handle retry_stage policy for quality gate failure.

    Returns:
        "continue" to signal retry needed.

    Raises:
        RuntimeError: If max retries exhausted or wall-clock timeout exceeded.
    """
    max_retries = quality_gates_config.get("max_retries", 2)

    if StateKeys.STAGE_RETRY_COUNTS not in state:
        state[StateKeys.STAGE_RETRY_COUNTS] = {}

    retry_count = state[StateKeys.STAGE_RETRY_COUNTS].get(stage_name, 0)

    if retry_count >= max_retries:
        raise RuntimeError(
            f"{ERROR_MSG_QUALITY_GATE_FAILED}{stage_name}' after {retry_count} retries "
            f"(max: {max_retries}). Final violations: {'; '.join(violations)}"
        )

    state[StateKeys.STAGE_RETRY_COUNTS][stage_name] = retry_count + 1

    _track_quality_gate_event(
        tracker, "quality_gate_retry", stage_name,
        synthesis_result, violations, quality_gates_config, retry_count
    )

    _check_retry_timeout(
        stage_name, wall_clock_start, wall_clock_timeout,
        retry_count, violations
    )

    elapsed = time.monotonic() - wall_clock_start
    logger.warning(
        f"{ERROR_MSG_QUALITY_GATE_FAILED}{stage_name}', retrying "
        f"(attempt {retry_count + 2}/{max_retries + 1}, "
        f"elapsed {elapsed:.1f}s/{wall_clock_timeout:.0f}s). "
        f"Violations: {'; '.join(violations)}"
    )

    return "continue"


def handle_quality_gate_failure(
    passed: bool,
    violations: list,
    synthesis_result: Any,
    stage_config: Any,
    stage_name: str,
    state: Dict[str, Any],
    wall_clock_start: float,
    wall_clock_timeout: float,
) -> Optional[str]:
    """Handle quality gate failures: escalate, warn, or prepare for retry.

    Args:
        passed: Whether quality gates passed
        violations: List of violation messages
        synthesis_result: The synthesis result
        stage_config: Stage configuration
        stage_name: Stage name
        state: Current workflow state
        wall_clock_start: Start time for wall-clock timeout
        wall_clock_timeout: Wall-clock timeout seconds

    Returns:
        "continue" if retry needed, None if passed or handled without retry

    Raises:
        RuntimeError: If escalation or retries exhausted
    """
    _reset_retry_counter_on_pass(passed, state, stage_name)

    if passed:
        return None

    stage_dict = stage_config if isinstance(stage_config, dict) else {}
    quality_gates_config = stage_dict.get("quality_gates", {})
    on_failure = quality_gates_config.get("on_failure", "retry_stage")

    retry_count = state.get(StateKeys.STAGE_RETRY_COUNTS, {}).get(stage_name, 0)

    tracker = state.get(StateKeys.TRACKER)
    _track_quality_gate_event(
        tracker, "quality_gate_failure", stage_name,
        synthesis_result, violations, quality_gates_config, retry_count
    )

    if on_failure == "escalate":
        _handle_quality_gate_escalate(stage_name, violations)
        return None

    if on_failure == "proceed_with_warning":
        _handle_quality_gate_warn(stage_name, violations, synthesis_result)
        return None

    if on_failure == "retry_stage":
        return _handle_quality_gate_retry(
            quality_gates_config, stage_name, state, tracker,
            synthesis_result, violations, wall_clock_start, wall_clock_timeout
        )

    return None


def _compute_stage_status(agent_statuses: Dict[str, Any]) -> str:
    """Compute stage status from agent results."""
    failed_count = sum(1 for s in agent_statuses.values() if s != "success")
    total_count = len(agent_statuses)
    if failed_count == total_count and total_count > 0:
        return "failed"
    if failed_count > 0:
        return "degraded"
    return "completed"


def _build_synthesis_metadata(
    synthesis_result: Any,
    parallel_result: Dict[str, Any],
    aggregate_metrics: Dict[str, Any]
) -> Dict[str, Any]:
    """Build tracker metadata for synthesis event."""
    return {
        StateKeys.METHOD: synthesis_result.method,
        StateKeys.CONFIDENCE: synthesis_result.confidence,
        StateKeys.VOTES: synthesis_result.votes,
        "num_conflicts": len(synthesis_result.conflicts),
        StateKeys.REASONING: synthesis_result.reasoning,
        StateKeys.AGENT_STATUSES: parallel_result.get(StateKeys.AGENT_STATUSES, {}),
        StateKeys.AGGREGATE_METRICS: aggregate_metrics
    }


def update_state_with_results(
    state: Dict[str, Any],
    stage_name: str,
    synthesis_result: Any,
    agent_outputs_dict: Dict[str, Any],
    parallel_result: Dict[str, Any],
    aggregate_metrics: Dict[str, Any],
) -> None:
    """Update workflow state with parallel execution results and track synthesis.

    Args:
        state: Current workflow state (mutated in place)
        stage_name: Stage name
        synthesis_result: SynthesisResult from synthesis
        agent_outputs_dict: Agent outputs dict
        parallel_result: Full parallel runner result
        aggregate_metrics: Aggregate metrics dict
    """
    agent_statuses = parallel_result.get(StateKeys.AGENT_STATUSES, {})
    stage_status = _compute_stage_status(agent_statuses)

    state[StateKeys.STAGE_OUTPUTS][stage_name] = {
        StateKeys.DECISION: synthesis_result.decision,
        StateKeys.AGENT_OUTPUTS: agent_outputs_dict,
        StateKeys.AGENT_STATUSES: agent_statuses,
        StateKeys.AGENT_METRICS: parallel_result.get(StateKeys.AGENT_METRICS, {}),
        StateKeys.AGGREGATE_METRICS: aggregate_metrics,
        StateKeys.STAGE_STATUS: stage_status,
        StateKeys.SYNTHESIS: {
            StateKeys.METHOD: synthesis_result.method,
            StateKeys.CONFIDENCE: synthesis_result.confidence,
            StateKeys.VOTES: synthesis_result.votes,
            StateKeys.CONFLICTS: len(synthesis_result.conflicts)
        }
    }
    state[StateKeys.CURRENT_STAGE] = stage_name

    tracker = state.get(StateKeys.TRACKER)
    if tracker and hasattr(tracker, 'track_collaboration_event'):
        tracker_metadata = _build_synthesis_metadata(
            synthesis_result, parallel_result, aggregate_metrics
        )
        tracker.track_collaboration_event(
            event_type="synthesis",
            stage_name=stage_name,
            agents=list(agent_outputs_dict.keys()),
            decision=synthesis_result.decision,
            confidence=synthesis_result.confidence,
            metadata=tracker_metadata
        )
