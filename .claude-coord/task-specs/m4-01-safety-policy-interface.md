# Task: m4-01 - Safety Policy Interface & Base Classes

**Priority:** CRITICAL (P0 - Security)
**Effort:** 8 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

Create the foundational interface and abstract base class for all safety policies. This establishes the contract for safety enforcement, including validation methods, violation reporting, and policy composition. Must support both synchronous and asynchronous validation for different execution contexts.

---

## Files to Create

- `src/safety/interfaces.py` - Core safety interfaces (SafetyPolicy, Validator)
- `src/safety/base.py` - Base safety policy class with composition support
- `src/safety/__init__.py` - Package initialization and exports
- `tests/safety/test_interfaces.py` - Interface contract tests

---

## Files to Modify

- `src/core/service.py` - Add safety service mixins

---

## Acceptance Criteria

### Core Functionality
- [ ] `SafetyPolicy` interface with abstract methods: `validate()`, `enforce()`, `report_violation()`
- [ ] Base class `BaseSafetyPolicy` supports policy chaining and composition
- [ ] Violation severity levels: CRITICAL, HIGH, MEDIUM, LOW, INFO
- [ ] Both async and sync validation modes supported
- [ ] Policy metadata: name, version, description, priority

### Interface Design
- [ ] `validate(action: Action, context: ExecutionContext) -> ValidationResult`
- [ ] `enforce(action: Action, context: ExecutionContext) -> EnforcementResult`
- [ ] `report_violation(violation: SafetyViolation) -> None`
- [ ] Return types: ValidationResult(valid: bool, violations: List[Violation], metadata: dict)

### Testing
- [ ] Unit tests cover all interface methods (>95% coverage)
- [ ] Test policy composition (multiple policies chained)
- [ ] Test async and sync validation modes
- [ ] Test severity level filtering

### Security Controls
- [ ] Policy validation cannot be bypassed
- [ ] Violations are always logged (integration with M1 observability)
- [ ] Critical violations halt execution immediately

---

## Implementation Details

### SafetyPolicy Interface

```python
from abc import ABC, abstractmethod
from enum import Enum
from typing import List, Optional, Dict, Any
from dataclasses import dataclass

class ViolationSeverity(Enum):
    CRITICAL = 5  # Blocks execution immediately
    HIGH = 4      # Requires approval
    MEDIUM = 3    # Warning + logging
    LOW = 2       # Logging only
    INFO = 1      # Informational

@dataclass
class SafetyViolation:
    policy_name: str
    severity: ViolationSeverity
    message: str
    action: str
    context: Dict[str, Any]
    timestamp: str
    remediation_hint: Optional[str] = None

@dataclass
class ValidationResult:
    valid: bool
    violations: List[SafetyViolation]
    metadata: Dict[str, Any]

class SafetyPolicy(ABC):
    """Abstract base class for all safety policies."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Policy name for identification."""
        pass

    @property
    @abstractmethod
    def version(self) -> str:
        """Policy version."""
        pass

    @property
    def priority(self) -> int:
        """Policy priority (higher = execute first). Default: 100"""
        return 100

    @abstractmethod
    def validate(
        self,
        action: Dict[str, Any],
        context: Dict[str, Any]
    ) -> ValidationResult:
        """
        Validate action against safety policy.

        Args:
            action: Action to validate (tool call, file operation, etc.)
            context: Execution context (agent, workflow, stage)

        Returns:
            ValidationResult with valid flag and any violations
        """
        pass

    async def validate_async(
        self,
        action: Dict[str, Any],
        context: Dict[str, Any]
    ) -> ValidationResult:
        """Async validation (default: calls sync validate)."""
        return self.validate(action, context)

    def report_violation(self, violation: SafetyViolation) -> None:
        """Report violation to observability system."""
        pass
```

### BaseSafetyPolicy Implementation

```python
class BaseSafetyPolicy(SafetyPolicy):
    """Base implementation with composition support."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self._child_policies: List[SafetyPolicy] = []

    def add_child_policy(self, policy: SafetyPolicy):
        """Add child policy for composition."""
        self._child_policies.append(policy)
        self._child_policies.sort(key=lambda p: p.priority, reverse=True)

    def validate(
        self,
        action: Dict[str, Any],
        context: Dict[str, Any]
    ) -> ValidationResult:
        """Validate with child policy composition."""
        violations = []
        metadata = {}

        # Validate with child policies first (higher priority)
        for child in self._child_policies:
            result = child.validate(action, context)
            violations.extend(result.violations)
            metadata.update(result.metadata)

            # Short-circuit on CRITICAL violations
            if any(v.severity == ViolationSeverity.CRITICAL for v in result.violations):
                break

        # Add own validation
        own_result = self._validate_impl(action, context)
        violations.extend(own_result.violations)
        metadata.update(own_result.metadata)

        valid = len([v for v in violations if v.severity >= ViolationSeverity.HIGH]) == 0

        return ValidationResult(
            valid=valid,
            violations=violations,
            metadata=metadata
        )

    def _validate_impl(
        self,
        action: Dict[str, Any],
        context: Dict[str, Any]
    ) -> ValidationResult:
        """Override in subclasses for specific validation logic."""
        return ValidationResult(valid=True, violations=[], metadata={})
```

---

## Test Strategy

### Unit Tests
- Test policy interface compliance
- Test composition with multiple child policies
- Test priority-based execution order
- Test short-circuit on CRITICAL violations
- Test async and sync validation modes

### Integration Tests
- Test with real action objects
- Test observability integration (violation reporting)
- Test with M1 database logging

---

## Success Metrics

- [ ] Test coverage >95%
- [ ] All interface methods documented with docstrings
- [ ] Type hints complete and validated with mypy
- [ ] Zero circular dependencies
- [ ] Policy execution overhead <1ms

---

## Dependencies

**Blocked by:** None (foundation task)
**Blocks:** m4-02, m4-03, m4-04, m4-05, m4-06, m4-07

---

## Design References

- Python ABC module for interfaces
- Strategy pattern for policy implementations
- Composite pattern for policy composition
- Observer pattern for violation reporting

---

## Notes

This is the foundation for all M4 safety systems. Design decisions here affect all downstream tasks. Key considerations:

1. **Performance:** Validation is in critical path - must be fast
2. **Extensibility:** Users should be able to create custom policies
3. **Composability:** Multiple policies should work together seamlessly
4. **Type Safety:** Use strict typing for better IDE support and error detection
