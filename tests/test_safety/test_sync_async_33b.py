"""Tests for code-high-sync-async-33b.

Verifies that the refactored validate/validate_async in composition.py and
base.py share logic through extracted helpers and produce identical results.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from temper_ai.safety.base import BaseSafetyPolicy
from temper_ai.safety.composition import CompositeValidationResult, PolicyComposer
from temper_ai.safety.interfaces import (
    SafetyPolicy,
    SafetyViolation,
    ValidationResult,
    ViolationSeverity,
)

# ─── helpers ──────────────────────────────────────────────────────────


class PassPolicy(BaseSafetyPolicy):
    """Policy that always passes."""

    @property
    def name(self) -> str:
        return "pass_policy"

    @property
    def version(self) -> str:
        return "1.0"

    @property
    def priority(self) -> int:
        return 5

    def _validate_impl(self, action, context):
        return ValidationResult(valid=True, policy_name=self.name)

    async def _validate_async_impl(self, action, context):
        return ValidationResult(valid=True, policy_name=self.name)


class FailPolicy(BaseSafetyPolicy):
    """Policy that always fails with a HIGH violation."""

    @property
    def name(self) -> str:
        return "fail_policy"

    @property
    def version(self) -> str:
        return "1.0"

    @property
    def priority(self) -> int:
        return 10

    def _validate_impl(self, action, context):
        v = SafetyViolation(
            policy_name=self.name,
            severity=ViolationSeverity.HIGH,
            message="Blocked",
            action=str(action),
            context=context,
        )
        return ValidationResult(valid=False, violations=[v], policy_name=self.name)

    async def _validate_async_impl(self, action, context):
        return self._validate_impl(action, context)


class CriticalPolicy(BaseSafetyPolicy):
    """Policy that always raises a CRITICAL violation."""

    @property
    def name(self) -> str:
        return "critical_policy"

    @property
    def version(self) -> str:
        return "1.0"

    @property
    def priority(self) -> int:
        return 20

    def _validate_impl(self, action, context):
        v = SafetyViolation(
            policy_name=self.name,
            severity=ViolationSeverity.CRITICAL,
            message="Critical issue",
            action=str(action),
            context=context,
        )
        return ValidationResult(valid=False, violations=[v], policy_name=self.name)

    async def _validate_async_impl(self, action, context):
        return self._validate_impl(action, context)


ACTION = {"tool": "test"}
CONTEXT = {"agent": "tester"}


# ─── PolicyComposer tests ────────────────────────────────────────────


class TestComposerSyncAsyncConsistency:
    """Verify sync and async validation produce identical results."""

    def _compare_results(
        self,
        sync_result: CompositeValidationResult,
        async_result: CompositeValidationResult,
    ):
        assert sync_result.valid == async_result.valid
        assert len(sync_result.violations) == len(async_result.violations)
        assert sync_result.policies_evaluated == async_result.policies_evaluated
        assert sync_result.policies_skipped == async_result.policies_skipped
        assert sync_result.execution_order == async_result.execution_order
        for sv, av in zip(sync_result.violations, async_result.violations):
            assert sv.severity == av.severity
            assert sv.message == av.message

    def test_all_pass_consistent(self):
        composer = PolicyComposer()
        composer.add_policy(PassPolicy({}))

        sync_result = composer.validate(ACTION, CONTEXT)
        assert sync_result.valid is True

    @pytest.mark.asyncio
    async def test_all_pass_async_consistent(self):
        composer = PolicyComposer()
        composer.add_policy(PassPolicy({}))

        sync_result = composer.validate(ACTION, CONTEXT)
        async_result = await composer.validate_async(ACTION, CONTEXT)
        self._compare_results(sync_result, async_result)
        assert async_result.valid is True

    @pytest.mark.asyncio
    async def test_fail_policy_consistent(self):
        composer = PolicyComposer()
        composer.add_policy(FailPolicy({}))

        sync_result = composer.validate(ACTION, CONTEXT)
        async_result = await composer.validate_async(ACTION, CONTEXT)

        assert sync_result.valid is False
        self._compare_results(sync_result, async_result)

    @pytest.mark.asyncio
    async def test_fail_fast_consistent(self):
        composer = PolicyComposer(fail_fast=True)
        composer.add_policy(FailPolicy({}))
        composer.add_policy(PassPolicy({}))

        sync_result = composer.validate(ACTION, CONTEXT)
        async_result = await composer.validate_async(ACTION, CONTEXT)

        assert sync_result.policies_skipped == 1
        self._compare_results(sync_result, async_result)

    @pytest.mark.asyncio
    async def test_error_handling_consistent(self):
        """Policy that raises an exception is handled identically."""
        mock_policy = MagicMock(spec=SafetyPolicy)
        mock_policy.name = "error_policy"
        mock_policy.priority = 5
        mock_policy.validate.side_effect = RuntimeError("boom")
        mock_policy.validate_async = AsyncMock(side_effect=RuntimeError("boom"))

        composer = PolicyComposer()
        composer.add_policy(mock_policy)

        sync_result = composer.validate(ACTION, CONTEXT)
        async_result = await composer.validate_async(ACTION, CONTEXT)

        assert sync_result.valid is False
        assert len(sync_result.violations) == 1
        assert sync_result.violations[0].severity == ViolationSeverity.CRITICAL
        self._compare_results(sync_result, async_result)


class TestComposerHelpers:
    """Verify that shared helpers exist and work correctly.

    Intentional private access: unit tests for internal composer helpers.
    """

    def test_handle_policy_result_collects_violations(self):
        composer = PolicyComposer()
        violations = []
        results = {}

        policy = FailPolicy({})
        result = policy.validate(ACTION, CONTEXT)

        composer._handle_policy_result(policy, result, violations, results)

        assert len(violations) == 1
        assert "fail_policy" in results

    def test_handle_policy_result_no_violations_on_pass(self):
        composer = PolicyComposer()
        violations = []
        results = {}

        policy = PassPolicy({})
        result = policy.validate(ACTION, CONTEXT)

        composer._handle_policy_result(policy, result, violations, results)

        assert len(violations) == 0
        assert results["pass_policy"].valid is True

    def test_handle_policy_error_creates_critical(self):
        composer = PolicyComposer()
        violations = []
        results = {}

        policy = PassPolicy({})
        error = RuntimeError("test error")

        composer._handle_policy_error(
            policy, error, ACTION, CONTEXT, violations, results
        )

        assert len(violations) == 1
        assert violations[0].severity == ViolationSeverity.CRITICAL
        assert "test error" in violations[0].message

    def test_build_composite_result_valid(self):
        composer = PolicyComposer()
        result = composer._build_composite_result([], {}, 1, 0, ["p1"])
        assert result.valid is True
        assert result.policies_evaluated == 1

    def test_build_composite_result_invalid(self):
        composer = PolicyComposer()
        v = SafetyViolation(
            policy_name="test",
            severity=ViolationSeverity.HIGH,
            message="x",
            action="a",
            context={},
        )
        result = composer._build_composite_result([v], {}, 1, 0, ["p1"])
        assert result.valid is False


# ─── BaseSafetyPolicy tests ──────────────────────────────────────────


class TestBasePolicySyncAsyncConsistency:
    """Verify sync and async validation in BaseSafetyPolicy produce identical results."""

    def test_pass_policy_sync(self):
        policy = PassPolicy({})
        result = policy.validate(ACTION, CONTEXT)
        assert result.valid is True

    @pytest.mark.asyncio
    async def test_pass_policy_consistent(self):
        policy = PassPolicy({})
        sync_result = policy.validate(ACTION, CONTEXT)
        async_result = await policy.validate_async(ACTION, CONTEXT)

        assert sync_result.valid == async_result.valid
        assert len(sync_result.violations) == len(async_result.violations)

    @pytest.mark.asyncio
    async def test_child_short_circuit_consistent(self):
        """Short-circuit on CRITICAL child should be identical in both paths."""
        parent = PassPolicy({})
        parent.add_child_policy(CriticalPolicy({}))
        parent.add_child_policy(PassPolicy({}))

        sync_result = parent.validate(ACTION, CONTEXT)
        async_result = await parent.validate_async(ACTION, CONTEXT)

        assert sync_result.valid is False
        assert async_result.valid is False
        assert sync_result.metadata.get("short_circuit") is True
        assert async_result.metadata.get("short_circuit") is True


class TestBasePolicyHelpers:
    """Verify extracted helpers in BaseSafetyPolicy work correctly.

    Intentional private access: unit tests for internal policy helpers.
    """

    def test_init_validation_metadata(self):
        policy = PassPolicy({})
        metadata = policy._init_validation_metadata()
        assert metadata["policy_name"] == "pass_policy"
        assert metadata["policy_version"] == "1.0"
        assert "child_policies" in metadata

    def test_merge_child_result_no_critical(self):
        policy = PassPolicy({})
        child = PassPolicy({})
        child_result = child.validate(ACTION, CONTEXT)

        violations = []
        metadata = policy._init_validation_metadata()

        should_break = policy._merge_child_result(
            child, child_result, violations, metadata
        )
        assert should_break is False
        assert len(violations) == 0

    def test_merge_child_result_critical_returns_true(self):
        policy = PassPolicy({})
        child = CriticalPolicy({})
        child_result = child.validate(ACTION, CONTEXT)

        violations = []
        metadata = policy._init_validation_metadata()

        should_break = policy._merge_child_result(
            child, child_result, violations, metadata
        )
        assert should_break is True
        assert metadata["short_circuit"] is True
        assert len(violations) > 0

    def test_finalize_validation_valid(self):
        policy = PassPolicy({})
        result = policy._finalize_validation([], {"policy_name": "test"})
        assert result.valid is True

    def test_finalize_validation_invalid(self):
        policy = PassPolicy({})
        v = SafetyViolation(
            policy_name="test",
            severity=ViolationSeverity.HIGH,
            message="x",
            action="a",
            context={},
        )
        result = policy._finalize_validation([v], {"policy_name": "test"})
        assert result.valid is False
