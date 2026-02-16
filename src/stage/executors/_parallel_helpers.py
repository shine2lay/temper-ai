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
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, cast

from src.shared.constants.execution import ERROR_MSG_QUALITY_GATE_FAILED
from src.stage.executors._base_helpers import _truncate_tracking_data
from src.stage.executors.state_keys import StateKeys
from src.shared.constants.limits import DEFAULT_MIN_ITEMS, SMALL_ITEM_LIMIT
from src.shared.constants.probabilities import PROB_HIGH
from src.shared.constants.sizes import UUID_HEX_SHORT_LENGTH
from src.shared.core.context import ExecutionContext
from src.shared.utils.exceptions import (
    ConfigNotFoundError,
    ConfigValidationError,
    LLMError,
    ToolExecutionError,
)

logger = logging.getLogger(__name__)


@dataclass
class AgentNodeParams:
    """Parameters for creating agent execution node (reduces 9 params to 7)."""
    agent_name: str
    agent_ref: Any
    stage_name: str
    state: Dict[str, Any]
    config_loader: Any
    agent_cache: Dict[str, Any]
    agent_factory_cls: Any = None
    tracker: Optional[Any] = None
    stage_id: Optional[str] = None


@dataclass
class AgentRunParams:
    """Parameters for running agent with/without tracking (reduces 8 params to 7)."""
    agent: Any
    input_data: Dict[str, Any]
    context: Any
    agent_name: str
    agent_config_dict_for_tracking: Dict[str, Any]
    tracker: Optional[Any]
    stage_id: Optional[str]
    effective_stage_id: str


@dataclass
class QualityGateRetryParams:
    """Parameters for quality gate retry handling (reduces 8 params to 7)."""
    quality_gates_config: Dict[str, Any]
    stage_name: str
    state: Dict[str, Any]
    tracker: Any
    synthesis_result: Any
    violations: list
    wall_clock_start: float
    wall_clock_timeout: float


@dataclass
class QualityGateFailureParams:
    """Parameters for quality gate failure handling (reduces 8 params to 7)."""
    passed: bool
    violations: list
    synthesis_result: Any
    stage_config: Any
    stage_name: str
    state: Dict[str, Any]
    wall_clock_start: float
    wall_clock_timeout: float


def _prepare_agent_input(s: Dict[str, Any]) -> Dict[str, Any]:
    """Prepare agent input data by unwrapping workflow_inputs and filtering reserved keys.

    If STAGE_INPUT contains a ``_context_resolved`` flag, the context was
    already resolved by a ContextProvider — skip the unwrap step.
    """
    input_data = s.get(StateKeys.STAGE_INPUT, {})

    # If context was already resolved by ContextProvider, use it directly
    if input_data.get("_context_resolved"):
        result = dict(input_data)
        result.pop("_context_resolved", None)
        return result

    _reserved = frozenset({
        StateKeys.STAGE_OUTPUTS, StateKeys.CURRENT_STAGE, StateKeys.WORKFLOW_ID, StateKeys.TRACKER,
        StateKeys.TOOL_REGISTRY, StateKeys.CONFIG_LOADER, StateKeys.VISUALIZER, StateKeys.SHOW_DETAILS,
        StateKeys.DETAIL_CONSOLE, StateKeys.WORKFLOW_INPUTS, StateKeys.TOOL_EXECUTOR, StateKeys.STREAM_CALLBACK,
    })
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
    from src.shared.utils.config_helpers import sanitize_config_for_display

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
    tracking_input_data = _truncate_tracking_data(tracking_input_data)

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
            logger.warning("Failed to set agent output tracking for %s", agent_name, exc_info=True)

    return response


def _resolve_agent_factory(agent_factory_cls: Any) -> Any:
    """Resolve agent factory class, importing default if needed."""
    if agent_factory_cls is not None:
        return agent_factory_cls
    from src.agent.utils.agent_factory import AgentFactory as _AgentFactory
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
    from src.storage.schemas.agent_config import AgentConfig

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
        result: Dict[str, Any] = agent_config.model_dump()
        return result
    if hasattr(agent_config, 'dict'):
        result2: Dict[str, Any] = agent_config.dict()
        return result2
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


def _run_agent(params: AgentRunParams) -> Any:
    """Execute agent with or without tracking."""
    if params.tracker and params.stage_id:
        return _execute_agent_with_tracking(
            params.agent, params.input_data, params.context, params.agent_name,
            params.agent_config_dict_for_tracking, params.tracker, params.effective_stage_id
        )
    params.input_data.pop(StateKeys.TRACKER, None)
    return params.agent.execute(params.input_data, params.context)


def create_agent_node(params: AgentNodeParams) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    """Create execution node for a single agent in parallel execution.

    Args:
        params: AgentNodeParams bundle containing all needed parameters

    Returns:
        Callable node function that executes the agent
    """
    def agent_node(s: Dict[str, Any]) -> Dict[str, Any]:
        """Execute single agent and store result."""
        start_time = time.time()

        try:
            agent_factory = _resolve_agent_factory(params.agent_factory_cls)
            agent, agent_config, agent_config_dict = _load_or_cache_agent(
                params.agent_name, params.config_loader, params.agent_cache, agent_factory
            )
            input_data = _prepare_agent_input(s)
            agent_config_dict_for_tracking = _config_to_tracking_dict(agent_config, agent_config_dict)
            effective_stage_id = params.stage_id if params.stage_id else f"stage-{uuid.uuid4().hex[:UUID_HEX_SHORT_LENGTH]}"
            context = _create_agent_context(params.state, params.stage_name, params.agent_name, effective_stage_id)

            run_params = AgentRunParams(
                agent=agent, input_data=input_data, context=context,
                agent_name=params.agent_name, agent_config_dict_for_tracking=agent_config_dict_for_tracking,
                tracker=params.tracker, stage_id=params.stage_id, effective_stage_id=effective_stage_id
            )
            response = _run_agent(run_params)

            duration = time.time() - start_time
            return _build_agent_success_result(params.agent_name, response, duration)

        except (ConfigNotFoundError, ConfigValidationError, ValueError, TypeError, KeyError) as e:
            logger.info(f"Agent {params.agent_name} configuration/validation error: {e}")
            duration = time.time() - start_time
            return _build_agent_error_result(params.agent_name, e, duration)

        except (KeyboardInterrupt, SystemExit):
            raise

        except (RuntimeError, ToolExecutionError, LLMError, ValueError, TypeError) as e:
            logger.error(
                f"Unexpected error in agent {params.agent_name}: {type(e).__name__}: {e}",
                exc_info=True
            )
            duration = time.time() - start_time
            return _build_agent_error_result(params.agent_name, e, duration)

    return agent_node


def _extract_result_field(synthesis_result: Any, field: str) -> list:
    """Extract a list field from synthesis_result metadata or decision dict."""
    if hasattr(synthesis_result, "metadata"):
        result: list = synthesis_result.metadata.get(field, [])
        return result
    if hasattr(synthesis_result, "decision") and isinstance(synthesis_result.decision, dict):
        result_from_decision: list = synthesis_result.decision.get(field, [])
        return result_from_decision
    return []


def _check_inline_quality_gates(
    quality_gates_config: Dict[str, Any], synthesis_result: Any,
) -> list[str]:
    """Run inline quality gate checks and return violations."""
    violations: list[str] = []

    min_confidence = quality_gates_config.get("min_confidence", PROB_HIGH)
    actual_confidence = getattr(synthesis_result, "confidence", 0.0)
    if actual_confidence < min_confidence:
        violations.append(
            f"Confidence {actual_confidence:.2f} below minimum {min_confidence:.2f}"
        )

    min_findings = quality_gates_config.get("min_findings", SMALL_ITEM_LIMIT)
    findings = _extract_result_field(synthesis_result, "findings")
    if min_findings > 0 and len(findings) < min_findings:
        violations.append(
            f"Only {len(findings)} findings, minimum {min_findings} required"
        )

    if quality_gates_config.get("require_citations", True):
        citations = _extract_result_field(synthesis_result, "citations")
        if not citations:
            violations.append("No citations provided")

    return violations


def validate_quality_gates(
    quality_gate_validator: Optional[Any],
    synthesis_result: Any,
    stage_config: Any,
    stage_name: str,
    state: Dict[str, Any],
) -> tuple[bool, list[str]]:
    """Validate synthesis result against quality gates."""
    if quality_gate_validator:
        return cast(
            tuple[bool, list[str]],
            quality_gate_validator.validate(
                synthesis_result=synthesis_result,
                stage_config=stage_config,
                stage_name=stage_name,
            ),
        )

    stage_dict = stage_config if isinstance(stage_config, dict) else {}
    quality_gates_config = stage_dict.get("quality_gates", {})

    if not quality_gates_config.get("enabled", False):
        return True, []

    violations = _check_inline_quality_gates(quality_gates_config, synthesis_result)
    passed = len(violations) == 0

    if not passed:
        _emit_quality_gate_violation_details(
            state, stage_name, violations, synthesis_result, quality_gates_config,
        )

    return passed, violations


def _emit_quality_gate_violation_details(
    state: Dict[str, Any],
    stage_name: str,
    violations: list,
    synthesis_result: Any,
    quality_gates_config: Dict[str, Any],
) -> None:
    """Emit per-gate violation details as a collaboration event."""
    try:
        from src.observability.dialogue_metrics import (
            build_quality_gate_details,
            emit_quality_gate_details,
        )

        tracker = state.get(StateKeys.TRACKER)
        stage_id = state.get(StateKeys.CURRENT_STAGE_ID, "")
        details = build_quality_gate_details(
            violations, synthesis_result, quality_gates_config,
        )
        emit_quality_gate_details(tracker, stage_id, stage_name, details)
    except Exception:
        logger.debug(
            "Failed to emit quality gate violation details for %s",
            stage_name,
            exc_info=True,
        )


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
    context_provider: Optional[Any] = None,
    stage_config: Optional[Any] = None,
) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    """Build the init node function for parallel execution.

    When ``context_provider`` and ``stage_config`` are supplied and the
    stage declares inputs with source refs, the resolved (focused) context
    is placed in STAGE_INPUT instead of the full state.

    Args:
        state: Current workflow state
        context_provider: Optional ContextProvider for selective resolution
        stage_config: Stage configuration (needed for context resolution)

    Returns:
        Callable node function for initializing parallel state
    """
    # Dynamic inputs override normal resolution
    dynamic = state.get(StateKeys.DYNAMIC_INPUTS)
    if dynamic is not None:
        from src.workflow.context_provider import _INFRASTRUCTURE_KEYS

        resolved_input_dyn: Dict[str, Any] = dict(dynamic)
        resolved_input_dyn["_context_resolved"] = True
        for key in _INFRASTRUCTURE_KEYS:
            if key in state:
                resolved_input_dyn[key] = state[key]

        def init_parallel_dynamic(s: Dict[str, Any]) -> Dict[str, Any]:
            """Initialize parallel stage state with resolved dynamic inputs."""
            return {
                StateKeys.AGENT_OUTPUTS: {},
                StateKeys.AGENT_STATUSES: {},
                StateKeys.AGENT_METRICS: {},
                StateKeys.ERRORS: {},
                StateKeys.STAGE_INPUT: resolved_input_dyn,
            }

        return init_parallel_dynamic

    # Try resolving focused context upfront
    resolved_input: Optional[Dict[str, Any]] = None
    if context_provider is not None and stage_config is not None:
        try:
            resolved_input = context_provider.resolve(stage_config, state)
            resolved_input["_context_resolved"] = True
            # Propagate context metadata to state for stage output tracking
            if "_context_meta" in resolved_input:
                state["_context_meta"] = resolved_input["_context_meta"]
        except Exception:  # noqa: BLE001 -- graceful fallback when context resolution fails
            resolved_input = None

    def init_parallel(s: Dict[str, Any]) -> Dict[str, Any]:
        """Initialize parallel state with empty collections."""
        if resolved_input is not None:
            stage_input = resolved_input
        else:
            stage_input = {
                **state,
                StateKeys.STAGE_OUTPUTS: state.get(StateKeys.STAGE_OUTPUTS, {}),
            }
        return {
            StateKeys.AGENT_OUTPUTS: {},
            StateKeys.AGENT_STATUSES: {},
            StateKeys.AGENT_METRICS: {},
            StateKeys.ERRORS: {},
            StateKeys.STAGE_INPUT: stage_input,
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

        from src.observability._tracker_helpers import CollaborationEventData
        tracker.track_collaboration_event(CollaborationEventData(
            event_type=event_type,
            stage_name=stage_name,
            agents=[],
            decision=None,
            confidence=getattr(synthesis_result, "confidence", 0.0),
            metadata=metadata
        ))


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


def _handle_quality_gate_retry(params: QualityGateRetryParams) -> str:
    """Handle retry_stage policy for quality gate failure.

    Returns:
        "continue" to signal retry needed.

    Raises:
        RuntimeError: If max retries exhausted or wall-clock timeout exceeded.
    """
    max_retries = params.quality_gates_config.get("max_retries", 2)

    if StateKeys.STAGE_RETRY_COUNTS not in params.state:
        params.state[StateKeys.STAGE_RETRY_COUNTS] = {}

    retry_count = params.state[StateKeys.STAGE_RETRY_COUNTS].get(params.stage_name, 0)

    if retry_count >= max_retries:
        raise RuntimeError(
            f"{ERROR_MSG_QUALITY_GATE_FAILED}{params.stage_name}' after {retry_count} retries "
            f"(max: {max_retries}). Final violations: {'; '.join(params.violations)}"
        )

    params.state[StateKeys.STAGE_RETRY_COUNTS][params.stage_name] = retry_count + 1

    _track_quality_gate_event(
        params.tracker, "quality_gate_retry", params.stage_name,
        params.synthesis_result, params.violations, params.quality_gates_config, retry_count
    )

    _check_retry_timeout(
        params.stage_name, params.wall_clock_start, params.wall_clock_timeout,
        retry_count, params.violations
    )

    elapsed = time.monotonic() - params.wall_clock_start
    logger.warning(
        f"{ERROR_MSG_QUALITY_GATE_FAILED}{params.stage_name}', retrying "
        f"(attempt {retry_count + 2}/{max_retries + 1}, "
        f"elapsed {elapsed:.1f}s/{params.wall_clock_timeout:.0f}s). "
        f"Violations: {'; '.join(params.violations)}"
    )

    return "continue"


def handle_quality_gate_failure(params: QualityGateFailureParams) -> Optional[str]:
    """Handle quality gate failures: escalate, warn, or prepare for retry.

    Args:
        params: QualityGateFailureParams bundle containing all needed parameters

    Returns:
        "continue" if retry needed, None if passed or handled without retry

    Raises:
        RuntimeError: If escalation or retries exhausted
    """
    _reset_retry_counter_on_pass(params.passed, params.state, params.stage_name)

    if params.passed:
        return None

    stage_dict = params.stage_config if isinstance(params.stage_config, dict) else {}
    quality_gates_config = stage_dict.get("quality_gates", {})
    on_failure = quality_gates_config.get("on_failure", "retry_stage")

    retry_count = params.state.get(StateKeys.STAGE_RETRY_COUNTS, {}).get(params.stage_name, 0)

    tracker = params.state.get(StateKeys.TRACKER)
    _track_quality_gate_event(
        tracker, "quality_gate_failure", params.stage_name,
        params.synthesis_result, params.violations, quality_gates_config, retry_count
    )

    if on_failure == "escalate":
        _handle_quality_gate_escalate(params.stage_name, params.violations)
        return None

    if on_failure == "proceed_with_warning":
        _handle_quality_gate_warn(params.stage_name, params.violations, params.synthesis_result)
        return None

    if on_failure == "retry_stage":
        retry_params = QualityGateRetryParams(
            quality_gates_config=quality_gates_config, stage_name=params.stage_name,
            state=params.state, tracker=tracker, synthesis_result=params.synthesis_result,
            violations=params.violations, wall_clock_start=params.wall_clock_start,
            wall_clock_timeout=params.wall_clock_timeout
        )
        return _handle_quality_gate_retry(retry_params)

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
    structured: Optional[Dict[str, Any]] = None,
) -> None:
    """Update workflow state with parallel execution results in two-compartment format.

    Args:
        state: Current workflow state (mutated in place)
        stage_name: Stage name
        synthesis_result: SynthesisResult from synthesis
        agent_outputs_dict: Agent outputs dict
        parallel_result: Full parallel runner result
        aggregate_metrics: Aggregate metrics dict
        structured: Extracted structured fields (from OutputExtractor)
    """
    agent_statuses = parallel_result.get(StateKeys.AGENT_STATUSES, {})
    stage_status = _compute_stage_status(agent_statuses)
    raw_dict: Dict[str, Any] = {
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
            StateKeys.CONFLICTS: len(synthesis_result.conflicts),
        },
    }

    stage_entry: Dict[str, Any] = {
        "structured": structured or {},
        "raw": dict(raw_dict),
        **raw_dict,  # Top-level compat for condition expressions
    }
    context_meta = state.get("_context_meta")
    if context_meta is not None:
        stage_entry["_context_meta"] = context_meta
    state[StateKeys.STAGE_OUTPUTS][stage_name] = stage_entry
    state[StateKeys.CURRENT_STAGE] = stage_name

    _emit_synthesis_event(
        state, stage_name, synthesis_result, agent_outputs_dict,
        parallel_result, aggregate_metrics,
    )
    _emit_output_lineage(state, stage_name, agent_outputs_dict, parallel_result, synthesis_result)
    _emit_parallel_cost_summary(state, stage_name, parallel_result)


def _emit_synthesis_event(
    state: Dict[str, Any],
    stage_name: str,
    synthesis_result: Any,
    agent_outputs_dict: Dict[str, Any],
    parallel_result: Dict[str, Any],
    aggregate_metrics: Dict[str, Any],
) -> None:
    """Emit synthesis collaboration event via tracker (if available)."""
    tracker = state.get(StateKeys.TRACKER)
    if not (tracker and hasattr(tracker, 'track_collaboration_event')):
        return
    tracker_metadata = _build_synthesis_metadata(
        synthesis_result, parallel_result, aggregate_metrics
    )
    from src.observability._tracker_helpers import CollaborationEventData
    tracker.track_collaboration_event(CollaborationEventData(
        event_type="synthesis",
        stage_name=stage_name,
        agents=list(agent_outputs_dict.keys()),
        decision=synthesis_result.decision,
        confidence=synthesis_result.confidence,
        metadata=tracker_metadata
    ))


def _emit_output_lineage(
    state: Dict[str, Any],
    stage_name: str,
    agent_outputs_dict: Dict[str, Any],
    parallel_result: Dict[str, Any],
    synthesis_result: Any,
) -> None:
    """Compute output lineage and store via tracker (best-effort)."""
    try:
        from src.observability.lineage import compute_output_lineage, lineage_to_dict

        agent_statuses = parallel_result.get(StateKeys.AGENT_STATUSES, {})
        synthesis_method = getattr(synthesis_result, "method", None)
        lineage = compute_output_lineage(
            stage_name, agent_outputs_dict, agent_statuses, synthesis_method,
        )
        lineage_dict = lineage_to_dict(lineage)

        tracker = state.get(StateKeys.TRACKER)
        stage_id = state.get(StateKeys.CURRENT_STAGE_ID, "")
        if tracker and hasattr(tracker, "set_stage_output"):
            tracker.set_stage_output(
                stage_id=stage_id,
                output_data={},
                output_lineage=lineage_dict,
            )
    except Exception:
        logger.debug(
            "Failed to compute output lineage for stage %s",
            stage_name,
            exc_info=True,
        )


def _emit_parallel_cost_summary(
    state: Dict[str, Any],
    stage_name: str,
    parallel_result: Dict[str, Any],
) -> None:
    """Emit cost rollup for parallel stage execution."""
    try:
        from src.observability.cost_rollup import (
            compute_stage_cost_summary,
            emit_cost_summary,
        )

        agent_metrics = parallel_result.get(StateKeys.AGENT_METRICS, {})
        agent_statuses = parallel_result.get(StateKeys.AGENT_STATUSES, {})
        tracker = state.get(StateKeys.TRACKER)
        stage_id = state.get(StateKeys.CURRENT_STAGE_ID, "")

        summary = compute_stage_cost_summary(
            stage_name, agent_metrics, agent_statuses,
        )
        emit_cost_summary(tracker, stage_id, summary)
    except Exception:
        logger.debug(
            "Failed to emit cost summary for stage %s",
            stage_name,
            exc_info=True,
        )
