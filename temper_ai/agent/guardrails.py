"""Output guardrails with feedback injection (R0.2).

Runs configurable checks (regex, function) against agent output and
optionally injects failure feedback into the prompt for LLM retry.
"""

from __future__ import annotations

import importlib
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from temper_ai.storage.schemas.agent_config import GuardrailCheck

logger = logging.getLogger(__name__)

_FEEDBACK_HEADER = "Your previous output failed the following guardrail checks:\n"
_FEEDBACK_FOOTER = "\nPlease revise your response to address the above issues."

_SEVERITY_BLOCK = "block"


@dataclass
class GuardrailResult:
    """Result of a single guardrail check."""

    passed: bool
    check_name: str
    severity: str
    message: str = ""


def run_guardrail_checks(
    output_text: str,
    checks: list[GuardrailCheck],
) -> list[GuardrailResult]:
    """Run all configured guardrail checks against the output."""
    results: list[GuardrailResult] = []
    for check in checks:
        if check.type == "regex":
            results.append(_run_regex_check(output_text, check))
        else:
            results.append(_run_function_check(output_text, check))
    return results


def _run_function_check(
    output_text: str,
    check: GuardrailCheck,
) -> GuardrailResult:
    """Import and call a function-based guardrail check."""
    if not check.check_ref:
        return GuardrailResult(
            passed=False,
            check_name=check.name,
            severity=check.severity,
            message="No check_ref specified for function check",
        )
    try:
        module_path, func_name = check.check_ref.rsplit(".", 1)
        module = importlib.import_module(module_path)
        func = getattr(module, func_name)
        result = func(output_text)
        if isinstance(result, bool):
            return GuardrailResult(
                passed=result,
                check_name=check.name,
                severity=check.severity,
            )
        # Assume tuple (passed, message)
        return GuardrailResult(
            passed=bool(result[0]),
            check_name=check.name,
            severity=check.severity,
            message=str(result[1]) if len(result) > 1 else "",
        )
    except (ImportError, AttributeError, TypeError, ValueError) as exc:
        logger.warning("Guardrail function check '%s' failed: %s", check.name, exc)
        return GuardrailResult(
            passed=False,
            check_name=check.name,
            severity=check.severity,
            message=f"Check execution error: {exc}",
        )


def _run_regex_check(
    output_text: str,
    check: GuardrailCheck,
) -> GuardrailResult:
    """Run a regex-based guardrail check.

    The check passes if the pattern matches the output.
    """
    if not check.pattern:
        return GuardrailResult(
            passed=False,
            check_name=check.name,
            severity=check.severity,
            message="No pattern specified for regex check",
        )
    try:
        match = re.search(check.pattern, output_text)
        return GuardrailResult(
            passed=match is not None,
            check_name=check.name,
            severity=check.severity,
            message="" if match else f"Pattern '{check.pattern}' not found",
        )
    except re.error as exc:
        return GuardrailResult(
            passed=False,
            check_name=check.name,
            severity=check.severity,
            message=f"Invalid regex pattern: {exc}",
        )


def build_feedback_injection(failures: list[GuardrailResult]) -> str:
    """Build feedback string from failed guardrail checks."""
    lines = [_FEEDBACK_HEADER]
    for fail in failures:
        msg = f"- [{fail.severity.upper()}] {fail.check_name}"
        if fail.message:
            msg += f": {fail.message}"
        lines.append(msg)
    lines.append(_FEEDBACK_FOOTER)
    return "\n".join(lines)


def has_blocking_failures(results: list[GuardrailResult]) -> bool:
    """Return True if any result has severity='block' and did not pass."""
    return any(not r.passed and r.severity == _SEVERITY_BLOCK for r in results)
