# Custom Policy Development Guide

**Last Updated:** 2026-01-27
**Related:** [M4 Safety System Architecture](./M4_SAFETY_SYSTEM.md)

---

## Overview

This guide teaches you how to create custom safety policies for domain-specific requirements. Learn to:
- Implement the `SafetyPolicy` interface
- Handle sync and async validation
- Report violations effectively
- Test your policies
- Register and configure policies

---

## Quick Start

### Minimal Policy Implementation

```python
from typing import Dict, Any
from temper_ai.safety.interfaces import (
    SafetyPolicy,
    ValidationResult,
    SafetyViolation,
    ViolationSeverity
)

class MyCustomPolicy(SafetyPolicy):
    """Custom policy for domain-specific validation."""

    @property
    def name(self) -> str:
        return "my_custom_policy"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def priority(self) -> int:
        return 100  # P1 priority

    def validate(
        self,
        action: Dict[str, Any],
        context: Dict[str, Any]
    ) -> ValidationResult:
        """Validate action against custom rules."""

        # Your validation logic here
        if self._is_violation(action):
            violation = SafetyViolation(
                policy_name=self.name,
                severity=ViolationSeverity.HIGH,
                message="Custom rule violated",
                action=str(action),
                context=context,
                remediation_hint="How to fix this issue"
            )

            return ValidationResult(
                valid=False,
                violations=[violation],
                policy_name=self.name
            )

        # No violation
        return ValidationResult(
            valid=True,
            violations=[],
            policy_name=self.name
        )

    def _is_violation(self, action: Dict[str, Any]) -> bool:
        """Check if action violates policy."""
        # Implement your logic
        return False
```

---

## SafetyPolicy Interface

### Required Properties

```python
class SafetyPolicy(ABC):
    """Base interface for all safety policies."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique policy name (e.g., 'my_custom_policy')."""
        pass

    @property
    @abstractmethod
    def version(self) -> str:
        """Policy version (e.g., '1.0.0')."""
        pass

    @property
    def priority(self) -> int:
        """
        Execution priority (default: 100).

        Priority levels:
        - P0 (200): Critical security - file access, secrets
        - P1 (100): Important - rate limits, resource limits
        - P2 (50):  Optimization - circuit breakers
        """
        return 100

    @property
    def description(self) -> str:
        """Human-readable description."""
        return f"Safety policy: {self.name}"
```

**Important Note:** The interface above shows abstract properties marked with `@abstractmethod`. When implementing your custom policy, you provide concrete implementations of these properties by returning values:

```python
class MyCustomPolicy(BaseSafetyPolicy):
    """Your implementation."""

    @property
    def name(self) -> str:
        return "my_custom_policy"  # Concrete implementation

    @property
    def version(self) -> str:
        return "1.0.0"  # Concrete implementation

    @property
    def priority(self) -> int:
        return 100  # Override default if needed
```

### Required Methods

```python
@abstractmethod
def validate(
    self,
    action: Dict[str, Any],
    context: Dict[str, Any]
) -> ValidationResult:
    """
    Validate action (synchronous).

    Args:
        action: Action to validate
        context: Execution context

    Returns:
        ValidationResult with valid flag and violations
    """
    pass

async def validate_async(
    self,
    action: Dict[str, Any],
    context: Dict[str, Any]
) -> ValidationResult:
    """
    Validate action (asynchronous).

    Default: calls validate() synchronously.
    Override for async operations (DB, API calls).
    """
    return self.validate(action, context)

def report_violation(self, violation: SafetyViolation) -> None:
    """
    Report violation to observability.

    Default: no-op.
    Override to integrate with M1 observability.
    """
    pass
```

---

## Step-by-Step Development

### Step 1: Define Your Policy

Identify what you want to validate:
- **Business rules** - "No deployments on Fridays"
- **Compliance** - "All PII must be encrypted"
- **Domain logic** - "Users can't delete their own account"
- **Resource limits** - "Max 3 concurrent jobs per user"

### Step 2: Choose Priority Level

| Priority | Use When | Examples |
|----------|----------|----------|
| P0 (200) | Prevents security breaches, data loss | File access, secret detection |
| P1 (100) | Important safety, best practices | Rate limits, resource limits |
| P2 (50) | Optimization, nice-to-have | Circuit breakers, caching |

```python
@property
def priority(self) -> int:
    return 200  # P0 - critical security
```

### Step 3: Implement Validation Logic

```python
def validate(
    self,
    action: Dict[str, Any],
    context: Dict[str, Any]
) -> ValidationResult:
    """Implement validation logic."""

    # Extract relevant data from action
    action_type = action.get("type")
    action_data = action.get("data", {})

    # Perform validation checks
    violations = []

    # Check 1: Example validation
    if self._check_rule_1(action_data):
        violations.append(
            self._create_violation(
                severity=ViolationSeverity.HIGH,
                message="Rule 1 violated",
                action=action,
                context=context
            )
        )

    # Check 2: Another validation
    if self._check_rule_2(action_data):
        violations.append(
            self._create_violation(
                severity=ViolationSeverity.MEDIUM,
                message="Rule 2 violated",
                action=action,
                context=context
            )
        )

    # Return result
    return ValidationResult(
        valid=len(violations) == 0,
        violations=violations,
        policy_name=self.name,
        metadata={"checks_performed": 2}
    )
```

### Step 4: Create Helper Methods

```python
def _check_rule_1(self, data: Dict[str, Any]) -> bool:
    """Check if rule 1 is violated."""
    # Implement your logic
    return False

def _create_violation(
    self,
    severity: ViolationSeverity,
    message: str,
    action: Dict[str, Any],
    context: Dict[str, Any]
) -> SafetyViolation:
    """Create a violation object."""
    return SafetyViolation(
        policy_name=self.name,
        severity=severity,
        message=message,
        action=str(action),
        context=context,
        remediation_hint=self._get_remediation_hint(message),
        metadata={"policy_version": self.version}
    )

def _get_remediation_hint(self, message: str) -> str:
    """Get remediation hint for violation."""
    # Provide helpful guidance
    return "Contact security team for guidance"
```

### Step 5: Write Tests

```python
# tests/safety/test_my_custom_policy.py
import pytest
from my_module import MyCustomPolicy
from temper_ai.safety.interfaces import ViolationSeverity

class TestMyCustomPolicy:
    """Tests for MyCustomPolicy."""

    @pytest.fixture
    def policy(self):
        """Create policy instance."""
        return MyCustomPolicy()

    def test_valid_action(self, policy):
        """Test that valid action passes."""
        result = policy.validate(
            action={"type": "valid_action", "data": {}},
            context={}
        )

        assert result.valid is True
        assert len(result.violations) == 0

    def test_invalid_action(self, policy):
        """Test that invalid action is caught."""
        result = policy.validate(
            action={"type": "invalid_action", "data": {}},
            context={}
        )

        assert result.valid is False
        assert len(result.violations) > 0
        assert result.violations[0].severity == ViolationSeverity.HIGH

    def test_policy_properties(self, policy):
        """Test policy properties."""
        assert policy.name == "my_custom_policy"
        assert policy.version == "1.0.0"
        assert policy.priority == 100
```

### Step 6: Register Policy

```python
from temper_ai.safety.policy_registry import PolicyRegistry
from my_module import MyCustomPolicy

registry = PolicyRegistry()

# Register for specific action types
registry.register_policy(
    MyCustomPolicy(),
    action_types=["custom_action", "other_action"]
)

# Or register as global policy
registry.register_policy(MyCustomPolicy())  # Applies to all actions
```

### Step 7: Configure in YAML

```yaml
# configs/safety/action_policies.yaml

policy_mappings:
  custom_action:
    - my_custom_policy

policy_config:
  my_custom_policy:
    # Custom configuration
    max_retries: 3
    timeout_seconds: 30
```

---

## Complete Example: Business Hours Policy

### Use Case

Prevent deployments during business hours (9am-5pm Mon-Fri) to avoid disruption.

### Implementation

```python
from typing import Dict, Any
from datetime import datetime, time
import pytz

from temper_ai.safety.base import BaseSafetyPolicy
from temper_ai.safety.interfaces import (
    ValidationResult,
    SafetyViolation,
    ViolationSeverity
)

class BusinessHoursPolicy(BaseSafetyPolicy):
    """Prevent deployments during business hours."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)

        # Configuration
        self.timezone = pytz.timezone(
            config.get("timezone", "America/New_York")
        )
        self.business_start = self._parse_time(
            config.get("business_start", "09:00")
        )
        self.business_end = self._parse_time(
            config.get("business_end", "17:00")
        )
        self.blocked_actions = config.get(
            "blocked_actions",
            ["deploy", "db_migration"]
        )

    @property
    def name(self) -> str:
        return "business_hours_policy"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def priority(self) -> int:
        return 150  # P1 priority (between P0 and standard P1)

    def validate(
        self,
        action: Dict[str, Any],
        context: Dict[str, Any]
    ) -> ValidationResult:
        """Validate action against business hours rule."""

        action_type = action.get("type")

        # Only check configured action types
        if action_type not in self.blocked_actions:
            return ValidationResult(
                valid=True,
                violations=[],
                policy_name=self.name
            )

        # Get current time in configured timezone
        now = datetime.now(self.timezone)

        # Check if weekend
        if now.weekday() >= 5:  # Saturday = 5, Sunday = 6
            # Weekend - allow
            return ValidationResult(
                valid=True,
                violations=[],
                policy_name=self.name,
                metadata={"reason": "weekend"}
            )

        # Check if business hours
        current_time = now.time()

        if self.business_start <= current_time < self.business_end:
            # Business hours - block
            violation = SafetyViolation(
                policy_name=self.name,
                severity=ViolationSeverity.HIGH,
                message=(
                    f"Action '{action_type}' not allowed during business hours "
                    f"({self.business_start}-{self.business_end} {self.timezone})"
                ),
                action=str(action),
                context=context,
                remediation_hint=(
                    f"Wait until after {self.business_end} or "
                    "request emergency approval"
                ),
                metadata={
                    "current_time": current_time.isoformat(),
                    "business_start": self.business_start.isoformat(),
                    "business_end": self.business_end.isoformat(),
                    "timezone": str(self.timezone)
                }
            )

            return ValidationResult(
                valid=False,
                violations=[violation],
                policy_name=self.name
            )

        # Outside business hours - allow
        return ValidationResult(
            valid=True,
            violations=[],
            policy_name=self.name,
            metadata={"reason": "outside_business_hours"}
        )

    def _parse_time(self, time_str: str) -> time:
        """Parse time string (HH:MM) to time object."""
        hour, minute = map(int, time_str.split(":"))
        return time(hour, minute)
```

### Configuration

```yaml
policy_config:
  business_hours_policy:
    timezone: "America/New_York"
    business_start: "09:00"
    business_end: "17:00"
    blocked_actions:
      - deploy
      - db_migration
      - rollback
```

### Tests

```python
import pytest
from datetime import datetime, time
from unittest.mock import patch
import pytz

from business_hours_policy import BusinessHoursPolicy
from temper_ai.safety.interfaces import ViolationSeverity

class TestBusinessHoursPolicy:
    """Tests for BusinessHoursPolicy."""

    @pytest.fixture
    def policy(self):
        """Create policy with default config."""
        config = {
            "timezone": "America/New_York",
            "business_start": "09:00",
            "business_end": "17:00",
            "blocked_actions": ["deploy"]
        }
        return BusinessHoursPolicy(config)

    @patch('business_hours_policy.datetime')
    def test_blocks_during_business_hours(self, mock_datetime, policy):
        """Test that deployments blocked during business hours."""
        # Mock Wednesday 2pm ET
        mock_datetime.now.return_value = datetime(
            2026, 1, 28, 14, 0, 0,
            tzinfo=pytz.timezone("America/New_York")
        )

        result = policy.validate(
            action={"type": "deploy"},
            context={}
        )

        assert result.valid is False
        assert len(result.violations) == 1
        assert result.violations[0].severity == ViolationSeverity.HIGH
        assert "business hours" in result.violations[0].message.lower()

    @patch('business_hours_policy.datetime')
    def test_allows_outside_business_hours(self, mock_datetime, policy):
        """Test that deployments allowed outside business hours."""
        # Mock Wednesday 7pm ET (after 5pm)
        mock_datetime.now.return_value = datetime(
            2026, 1, 28, 19, 0, 0,
            tzinfo=pytz.timezone("America/New_York")
        )

        result = policy.validate(
            action={"type": "deploy"},
            context={}
        )

        assert result.valid is True
        assert len(result.violations) == 0

    @patch('business_hours_policy.datetime')
    def test_allows_on_weekend(self, mock_datetime, policy):
        """Test that deployments allowed on weekend."""
        # Mock Saturday 2pm ET
        mock_datetime.now.return_value = datetime(
            2026, 1, 31, 14, 0, 0,  # Saturday
            tzinfo=pytz.timezone("America/New_York")
        )

        result = policy.validate(
            action={"type": "deploy"},
            context={}
        )

        assert result.valid is True
        assert result.metadata["reason"] == "weekend"

    def test_allows_non_blocked_actions(self, policy):
        """Test that non-blocked actions are allowed."""
        result = policy.validate(
            action={"type": "file_read"},
            context={}
        )

        assert result.valid is True
```

---

## Advanced Patterns

### Pattern 1: Async Validation

For policies that need to query databases or external APIs:

```python
import aiohttp

class ExternalAPIPolicy(SafetyPolicy):
    """Policy that validates against external API."""

    async def validate_async(
        self,
        action: Dict[str, Any],
        context: Dict[str, Any]
    ) -> ValidationResult:
        """Async validation with external API call."""

        # Make async API call
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.example.com/validate",
                json=action
            ) as response:
                data = await response.json()

                if not data.get("valid"):
                    violation = SafetyViolation(
                        policy_name=self.name,
                        severity=ViolationSeverity.HIGH,
                        message=data.get("error", "Validation failed"),
                        action=str(action),
                        context=context
                    )

                    return ValidationResult(
                        valid=False,
                        violations=[violation],
                        policy_name=self.name
                    )

        return ValidationResult(valid=True, violations=[], policy_name=self.name)
```

### Pattern 2: Stateful Validation

For policies that track state across validations:

```python
class RateLimitPolicy(SafetyPolicy):
    """Policy with internal state tracking."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__()
        self.config = config
        self._state = {}  # Track state

    def validate(
        self,
        action: Dict[str, Any],
        context: Dict[str, Any]
    ) -> ValidationResult:
        """Validate with state tracking."""

        agent_id = context.get("agent_id")
        action_type = action.get("type")

        # Get current count from state
        key = f"{agent_id}:{action_type}"
        count = self._state.get(key, 0)

        # Check limit
        limit = self.config.get(f"limits.{action_type}", 100)

        if count >= limit:
            violation = SafetyViolation(
                policy_name=self.name,
                severity=ViolationSeverity.HIGH,
                message=f"Rate limit exceeded: {count}/{limit}",
                action=str(action),
                context=context
            )

            return ValidationResult(
                valid=False,
                violations=[violation],
                policy_name=self.name
            )

        # Increment count
        self._state[key] = count + 1

        return ValidationResult(valid=True, violations=[], policy_name=self.name)
```

### Pattern 3: Composition with BaseSafetyPolicy

Extend `BaseSafetyPolicy` for built-in composition support:

```python
from temper_ai.safety.base import BaseSafetyPolicy

class ComposablePolicy(BaseSafetyPolicy):
    """Policy with composition support."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)

        # Add child policies
        self.add_child_policy(SubPolicy1())
        self.add_child_policy(SubPolicy2())

    @property
    def name(self) -> str:
        return "composable_policy"

    @property
    def version(self) -> str:
        return "1.0.0"

    def _validate_impl(
        self,
        action: Dict[str, Any],
        context: Dict[str, Any]
    ) -> ValidationResult:
        """Implement policy-specific validation."""
        # BaseSafetyPolicy will also execute child policies
        return ValidationResult(valid=True, violations=[], policy_name=self.name)
```

### Pattern 4: Configuration-Driven Validation

For highly configurable policies:

```python
class ConfigurablePolicy(SafetyPolicy):
    """Policy driven by configuration."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__()
        self.config = config

        # Load rules from config
        self.rules = self._load_rules(config.get("rules", []))

    def _load_rules(self, rules_config: List[Dict]) -> List[Callable]:
        """Load validation rules from configuration."""
        rules = []

        for rule_config in rules_config:
            rule_type = rule_config.get("type")
            rule_params = rule_config.get("params", {})

            # Create rule function based on type
            if rule_type == "regex":
                rules.append(self._create_regex_rule(rule_params))
            elif rule_type == "comparison":
                rules.append(self._create_comparison_rule(rule_params))
            # Add more rule types...

        return rules

    def validate(
        self,
        action: Dict[str, Any],
        context: Dict[str, Any]
    ) -> ValidationResult:
        """Validate using configured rules."""

        violations = []

        for rule in self.rules:
            if not rule(action, context):
                violations.append(
                    SafetyViolation(
                        policy_name=self.name,
                        severity=ViolationSeverity.MEDIUM,
                        message="Rule violated",
                        action=str(action),
                        context=context
                    )
                )

        return ValidationResult(
            valid=len(violations) == 0,
            violations=violations,
            policy_name=self.name
        )
```

---

## Testing Best Practices

### 1. Test Valid and Invalid Cases

```python
def test_valid_action(self, policy):
    """Test action that should pass."""
    result = policy.validate(action=VALID_ACTION, context={})
    assert result.valid is True

def test_invalid_action(self, policy):
    """Test action that should fail."""
    result = policy.validate(action=INVALID_ACTION, context={})
    assert result.valid is False
    assert len(result.violations) > 0
```

### 2. Test Edge Cases

```python
def test_empty_action(self, policy):
    """Test handling of empty action."""
    result = policy.validate(action={}, context={})
    # Should handle gracefully

def test_missing_required_fields(self, policy):
    """Test handling of missing fields."""
    result = policy.validate(
        action={"type": "test"},  # Missing other fields
        context={}
    )
```

### 3. Test Severity Levels

```python
def test_critical_violation(self, policy):
    """Test that critical violations have correct severity."""
    result = policy.validate(action=CRITICAL_ACTION, context={})
    assert result.violations[0].severity == ViolationSeverity.CRITICAL

def test_high_violation(self, policy):
    """Test that high violations have correct severity."""
    result = policy.validate(action=HIGH_ACTION, context={})
    assert result.violations[0].severity == ViolationSeverity.HIGH
```

### 4. Test Async Support

```python
@pytest.mark.asyncio
async def test_async_validation(self, policy):
    """Test async validation."""
    result = await policy.validate_async(action=TEST_ACTION, context={})
    assert result.valid is not None
```

### 5. Test Remediation Hints

```python
def test_remediation_hint(self, policy):
    """Test that violations include remediation hints."""
    result = policy.validate(action=INVALID_ACTION, context={})
    assert result.violations[0].remediation_hint is not None
    assert len(result.violations[0].remediation_hint) > 0
```

---

## Deployment Checklist

- [ ] Policy implements all required methods
- [ ] Policy has unique name
- [ ] Priority set appropriately (P0/P1/P2)
- [ ] Validation logic is correct
- [ ] Violations have clear messages
- [ ] Remediation hints are helpful
- [ ] Unit tests written (>90% coverage)
- [ ] Integration tests with engine
- [ ] Configuration documented
- [ ] Registered in PolicyRegistry
- [ ] Added to action_policies.yaml
- [ ] Tested in development environment
- [ ] Performance acceptable (<10ms)
- [ ] Observability integration tested
- [ ] Documentation updated

---

## Common Pitfalls

### Pitfall 1: Blocking Too Much

**Problem:** Policy too strict, blocks legitimate actions.

**Solution:**
- Start lenient, tighten gradually
- Add configuration options
- Provide override mechanisms
- Use environment-specific settings

### Pitfall 2: Slow Validation

**Problem:** Policy takes >50ms to validate.

**Solution:**
- Cache expensive computations
- Use async for I/O operations
- Optimize hot paths
- Consider result caching at engine level

### Pitfall 3: Poor Error Messages

**Problem:** Violations don't explain what's wrong.

**Solution:**
- Be specific in messages
- Include relevant details
- Provide remediation hints
- Link to documentation

### Pitfall 4: Missing Context

**Problem:** Policy doesn't have enough context to validate.

**Solution:**
- Request additional context fields
- Use metadata effectively
- Document required context
- Handle missing context gracefully

---

## References

- [M4 Safety System Architecture](./M4_SAFETY_SYSTEM.md)
- [Policy Configuration Guide](./POLICY_CONFIGURATION_GUIDE.md)
- [Safety Examples](./SAFETY_EXAMPLES.md)
- `temper_ai/safety/interfaces.py` - Interface definitions
- `temper_ai/safety/base.py` - Base policy implementation
- `tests/safety/test_*.py` - Test examples
