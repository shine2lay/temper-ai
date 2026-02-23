"""Quality gate validation and failure handling for parallel execution.

Contains:
- Inline quality gate checks (confidence, findings, citations)
- Quality gate failure policies (escalate, warn, retry)
- Wall-clock timeout enforcement during retries

Extracted from _parallel_helpers.py to reduce file size.
"""

import logging
import time
from dataclasses import dataclass
from typing import Any, cast

from temper_ai.shared.constants.execution import ERROR_MSG_QUALITY_GATE_FAILED
from temper_ai.shared.constants.limits import SMALL_ITEM_LIMIT
from temper_ai.shared.constants.probabilities import PROB_HIGH
from temper_ai.stage.executors._parallel_observability import (
    _emit_quality_gate_violation_details,
    _track_quality_gate_event,
)
from temper_ai.stage.executors.state_keys import StateKeys

logger = logging.getLogger(__name__)


@dataclass
class QualityGateRetryParams:
    """Parameters for quality gate retry handling (bundles 8 params into 1)."""

    quality_gates_config: dict[str, Any]
    stage_name: str
    state: dict[str, Any]
    tracker: Any
    synthesis_result: Any
    violations: list
    wall_clock_start: float
    wall_clock_timeout: float


@dataclass
class QualityGateFailureParams:
    """Parameters for quality gate failure handling (bundles 8 params into 1)."""

    passed: bool
    violations: list
    synthesis_result: Any
    stage_config: Any
    stage_name: str
    state: dict[str, Any]
    wall_clock_start: float
    wall_clock_timeout: float


def _extract_result_field(synthesis_result: Any, field: str) -> list:
    """Extract a list field from synthesis_result metadata or decision dict."""
    if hasattr(synthesis_result, "metadata"):
        result: list = synthesis_result.metadata.get(field, [])
        return result
    if hasattr(synthesis_result, "decision") and isinstance(
        synthesis_result.decision, dict
    ):
        result_from_decision: list = synthesis_result.decision.get(field, [])
        return result_from_decision
    return []


def _check_inline_quality_gates(
    quality_gates_config: dict[str, Any],
    synthesis_result: Any,
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
    quality_gate_validator: Any | None,
    synthesis_result: Any,
    stage_config: Any,
    stage_name: str,
    state: dict[str, Any],
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
            state,
            stage_name,
            violations,
            synthesis_result,
            quality_gates_config,
        )

    return passed, violations


def _handle_quality_gate_escalate(stage_name: str, violations: list) -> None:
    """Handle escalate policy for quality gate failure."""
    raise RuntimeError(
        f"{ERROR_MSG_QUALITY_GATE_FAILED}{stage_name}': {'; '.join(violations)}"
    )


def _handle_quality_gate_warn(
    stage_name: str, violations: list, synthesis_result: Any
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
    violations: list,
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
    passed: bool, state: dict[str, Any], stage_name: str
) -> None:
    """Reset retry counter if quality gates passed after retries."""
    if (
        passed
        and StateKeys.STAGE_RETRY_COUNTS in state
        and stage_name in state[StateKeys.STAGE_RETRY_COUNTS]
    ):
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
        params.tracker,
        "quality_gate_retry",
        params.stage_name,
        params.synthesis_result,
        params.violations,
        params.quality_gates_config,
        retry_count,
    )

    _check_retry_timeout(
        params.stage_name,
        params.wall_clock_start,
        params.wall_clock_timeout,
        retry_count,
        params.violations,
    )

    elapsed = time.monotonic() - params.wall_clock_start
    logger.warning(
        f"{ERROR_MSG_QUALITY_GATE_FAILED}{params.stage_name}', retrying "
        f"(attempt {retry_count + 2}/{max_retries + 1}, "
        f"elapsed {elapsed:.1f}s/{params.wall_clock_timeout:.0f}s). "
        f"Violations: {'; '.join(params.violations)}"
    )

    return "continue"


def handle_quality_gate_failure(params: QualityGateFailureParams) -> str | None:
    """Handle quality gate failures: escalate, warn, or prepare for retry.

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

    retry_count = params.state.get(StateKeys.STAGE_RETRY_COUNTS, {}).get(
        params.stage_name, 0
    )

    tracker = params.state.get(StateKeys.TRACKER)
    _track_quality_gate_event(
        tracker,
        "quality_gate_failure",
        params.stage_name,
        params.synthesis_result,
        params.violations,
        quality_gates_config,
        retry_count,
    )

    if on_failure == "escalate":
        _handle_quality_gate_escalate(params.stage_name, params.violations)
        return None

    if on_failure == "proceed_with_warning":
        _handle_quality_gate_warn(
            params.stage_name, params.violations, params.synthesis_result
        )
        return None

    if on_failure == "retry_stage":
        retry_params = QualityGateRetryParams(
            quality_gates_config=quality_gates_config,
            stage_name=params.stage_name,
            state=params.state,
            tracker=tracker,
            synthesis_result=params.synthesis_result,
            violations=params.violations,
            wall_clock_start=params.wall_clock_start,
            wall_clock_timeout=params.wall_clock_timeout,
        )
        return _handle_quality_gate_retry(retry_params)

    return None
