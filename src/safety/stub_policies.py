"""Stub safety policies for config-referenced policies not yet fully implemented.

These policies exist so that the safety config can reference them without
producing "no built-in implementation found" warnings.  They accept their
config section but perform no validation (always allow).

When a real implementation is needed, replace the stub with a full policy
class and remove the corresponding entry from this file.
"""
from typing import Any, Dict

from src.safety.base import BaseSafetyPolicy
from src.safety.interfaces import ValidationResult


class ApprovalWorkflowPolicy(BaseSafetyPolicy):
    """Stub for approval_workflow_policy.

    The actual approval workflow is handled by the ApprovalWorkflow /
    NoOpApprover component in the safety stack.  This policy stub
    exists so the config reference doesn't produce a warning.
    """

    @property
    def name(self) -> str:
        return "approval_workflow_policy"

    @property
    def version(self) -> str:
        return "0.1.0"

    def _validate_impl(
        self, action: Dict[str, Any], context: Dict[str, Any]
    ) -> ValidationResult:
        # Approval logic is delegated to ApprovalWorkflow component
        return ValidationResult(
            valid=True, violations=[], metadata={}, policy_name=self.name
        )


class CircuitBreakerPolicy(BaseSafetyPolicy):
    """Stub for circuit_breaker_policy.

    The actual circuit breaker is handled per-LLM-provider in the
    llm_providers module.  This policy stub exists so the config
    reference doesn't produce a warning.
    """

    @property
    def name(self) -> str:
        return "circuit_breaker_policy"

    @property
    def version(self) -> str:
        return "0.1.0"

    def _validate_impl(
        self, action: Dict[str, Any], context: Dict[str, Any]
    ) -> ValidationResult:
        # Circuit breaker logic is in LLM provider layer
        return ValidationResult(
            valid=True, violations=[], metadata={}, policy_name=self.name
        )
