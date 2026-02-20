"""Tests for output guardrails with feedback injection (R0.2)."""
from unittest.mock import MagicMock, Mock, patch

import pytest

from temper_ai.agent.guardrails import (
    GuardrailResult,
    build_feedback_injection,
    has_blocking_failures,
    run_guardrail_checks,
)
from temper_ai.storage.schemas.agent_config import GuardrailCheck, OutputGuardrailsConfig


class TestRunGuardrailChecks:
    """Tests for run_guardrail_checks."""

    def test_regex_check_passes(self):
        """Should pass when regex pattern matches output."""
        check = GuardrailCheck(name="has_json", type="regex", pattern=r"\{.*\}")
        results = run_guardrail_checks('{"key": "value"}', [check])
        assert len(results) == 1
        assert results[0].passed is True

    def test_regex_check_fails(self):
        """Should fail when regex pattern does not match output."""
        check = GuardrailCheck(name="has_json", type="regex", pattern=r"\{.*\}")
        results = run_guardrail_checks("plain text", [check])
        assert len(results) == 1
        assert results[0].passed is False
        assert "not found" in results[0].message

    def test_regex_no_pattern(self):
        """Should fail when regex check has no pattern."""
        check = GuardrailCheck(name="empty", type="regex", pattern=None)
        results = run_guardrail_checks("text", [check])
        assert results[0].passed is False
        assert "No pattern" in results[0].message

    def test_regex_invalid_pattern(self):
        """Should fail with invalid regex pattern."""
        check = GuardrailCheck(name="bad_regex", type="regex", pattern="[invalid")
        results = run_guardrail_checks("text", [check])
        assert results[0].passed is False
        assert "Invalid regex" in results[0].message

    def test_function_check_passes(self):
        """Should call function and return result."""
        check = GuardrailCheck(
            name="length_check",
            type="function",
            check_ref="tests.test_agent.test_guardrails._sample_check_pass",
        )
        results = run_guardrail_checks("output", [check])
        assert len(results) == 1
        assert results[0].passed is True

    def test_function_check_fails(self):
        """Should handle function returning False."""
        check = GuardrailCheck(
            name="length_check",
            type="function",
            check_ref="tests.test_agent.test_guardrails._sample_check_fail",
        )
        results = run_guardrail_checks("output", [check])
        assert results[0].passed is False

    def test_function_no_check_ref(self):
        """Should fail when function check has no check_ref."""
        check = GuardrailCheck(name="no_ref", type="function", check_ref=None)
        results = run_guardrail_checks("text", [check])
        assert results[0].passed is False
        assert "No check_ref" in results[0].message

    def test_function_import_error(self):
        """Should handle import errors gracefully."""
        check = GuardrailCheck(
            name="bad_import",
            type="function",
            check_ref="nonexistent.module.func",
        )
        results = run_guardrail_checks("text", [check])
        assert results[0].passed is False
        assert "Check execution error" in results[0].message

    def test_multiple_checks(self):
        """Should run all checks and return all results."""
        checks = [
            GuardrailCheck(name="check1", type="regex", pattern=r"hello"),
            GuardrailCheck(name="check2", type="regex", pattern=r"world"),
        ]
        results = run_guardrail_checks("hello world", checks)
        assert len(results) == 2
        assert all(r.passed for r in results)

    def test_function_returns_tuple(self):
        """Should handle function returning (bool, message) tuple."""
        check = GuardrailCheck(
            name="tuple_check",
            type="function",
            check_ref="tests.test_agent.test_guardrails._sample_check_tuple",
        )
        results = run_guardrail_checks("output", [check])
        assert results[0].passed is True
        assert results[0].message == "all good"

    def test_severity_preserved(self):
        """Should preserve severity from check definition."""
        check = GuardrailCheck(
            name="warn_check", type="regex", pattern=r"hello", severity="warn",
        )
        results = run_guardrail_checks("hello", [check])
        assert results[0].severity == "warn"


class TestHasBlockingFailures:
    """Tests for has_blocking_failures."""

    def test_no_failures(self):
        """Should return False when all checks pass."""
        results = [
            GuardrailResult(passed=True, check_name="a", severity="block"),
        ]
        assert has_blocking_failures(results) is False

    def test_blocking_failure(self):
        """Should return True when a block-severity check fails."""
        results = [
            GuardrailResult(passed=False, check_name="a", severity="block"),
        ]
        assert has_blocking_failures(results) is True

    def test_warn_failure_not_blocking(self):
        """Should return False when only warn-severity checks fail."""
        results = [
            GuardrailResult(passed=False, check_name="a", severity="warn"),
        ]
        assert has_blocking_failures(results) is False

    def test_mixed_results(self):
        """Should detect blocking in mixed results."""
        results = [
            GuardrailResult(passed=True, check_name="a", severity="block"),
            GuardrailResult(passed=False, check_name="b", severity="warn"),
            GuardrailResult(passed=False, check_name="c", severity="block"),
        ]
        assert has_blocking_failures(results) is True

    def test_empty_results(self):
        """Should return False for empty results."""
        assert has_blocking_failures([]) is False


class TestBuildFeedbackInjection:
    """Tests for build_feedback_injection."""

    def test_single_failure(self):
        """Should build feedback for a single failure."""
        failures = [
            GuardrailResult(passed=False, check_name="json_check", severity="block", message="Not JSON"),
        ]
        feedback = build_feedback_injection(failures)
        assert "json_check" in feedback
        assert "Not JSON" in feedback
        assert "revise" in feedback.lower()

    def test_multiple_failures(self):
        """Should include all failures."""
        failures = [
            GuardrailResult(passed=False, check_name="check1", severity="block", message="fail1"),
            GuardrailResult(passed=False, check_name="check2", severity="warn", message="fail2"),
        ]
        feedback = build_feedback_injection(failures)
        assert "check1" in feedback
        assert "check2" in feedback
        assert "[BLOCK]" in feedback
        assert "[WARN]" in feedback

    def test_empty_message(self):
        """Should handle failure with no message."""
        failures = [
            GuardrailResult(passed=False, check_name="check1", severity="block"),
        ]
        feedback = build_feedback_injection(failures)
        assert "check1" in feedback


class TestGuardrailConfig:
    """Tests for guardrail configuration schemas."""

    def test_output_guardrails_defaults(self):
        """Should have sensible defaults."""
        cfg = OutputGuardrailsConfig()
        assert cfg.enabled is False
        assert cfg.checks == []
        assert cfg.max_retries == 2
        assert cfg.inject_feedback is True

    def test_guardrail_check_defaults(self):
        """Should have sensible defaults for individual checks."""
        check = GuardrailCheck(name="test")
        assert check.type == "function"
        assert check.severity == "block"
        assert check.check_ref is None
        assert check.pattern is None


# Sample check functions used by function-type guardrail tests
def _sample_check_pass(output: str) -> bool:
    """Always passes."""
    return True


def _sample_check_fail(output: str) -> bool:
    """Always fails."""
    return False


def _sample_check_tuple(output: str) -> tuple:
    """Returns a tuple result."""
    return (True, "all good")
