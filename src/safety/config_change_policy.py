"""Config change policy for M5 self-improvement deployments.

Validates config changes before deployment to prevent unsafe modifications
that could degrade system performance or violate safety constraints.
"""
import logging
from dataclasses import dataclass
from typing import Any, Dict, List

from src.safety.base import BaseSafetyPolicy
from src.safety.interfaces import SafetyViolation, ValidationResult, ViolationSeverity

logger = logging.getLogger(__name__)

# Cost increase limits
DEFAULT_MAX_COST_INCREASE_PCT = 50.0  # Maximum allowed cost increase percentage

# Model cost estimates (relative scale: 1-15)
MODEL_COST_MISTRAL_7B = 5
MODEL_COST_LLAMA_8B = 6
MODEL_COST_MIXTRAL_8X7B = 15
DEFAULT_MODEL_COST = 3  # Default cost for unknown models


@dataclass
class ConfigChange:
    """Represents a configuration change."""
    field_path: str  # e.g., "inference.model"
    old_value: Any
    new_value: Any
    change_type: str  # "added", "removed", "modified"


class ConfigChangePolicy(BaseSafetyPolicy):
    """Validates configuration changes for safety.

    Checks:
    - Model changes (require approval for production models)
    - Temperature/parameter changes (validate ranges)
    - Tool configuration changes (ensure tools remain safe)
    - Cost-impact changes (require approval for high-cost changes)
    - Safety mode changes (block downgrading safety levels)

    Example:
        >>> policy = ConfigChangePolicy(config={
        ...     "require_approval_for_model_change": True,
        ...     "max_temperature": 1.0,
        ...     "allowed_models": ["llama3.2:3b", "phi3:mini"]
        ... })
        >>> result = await policy.validate_async(action, context)
    """

    def __init__(self, config: Dict[str, Any]):
        """Initialize config change policy.

        Args:
            config: Policy configuration with the following keys:
                - require_approval_for_model_change: bool (default: True)
                - max_temperature: float (default: 1.0)
                - min_temperature: float (default: 0.0)
                - allowed_models: List[str] (default: None - all allowed)
                - block_safety_downgrades: bool (default: True)
                - max_cost_increase_pct: float (default: 50.0)
        """
        super().__init__(config)
        self.require_approval_for_model_change = config.get("require_approval_for_model_change", True)
        self.max_temperature = config.get("max_temperature", 1.0)
        self.min_temperature = config.get("min_temperature", 0.0)
        self.allowed_models = config.get("allowed_models", None)  # None = all allowed
        self.block_safety_downgrades = config.get("block_safety_downgrades", True)
        self.max_cost_increase_pct = config.get("max_cost_increase_pct", DEFAULT_MAX_COST_INCREASE_PCT)

    @property
    def name(self) -> str:
        """Policy name."""
        return "ConfigChangePolicy"

    @property
    def version(self) -> str:
        """Policy version."""
        return "1.0.0"

    @property
    def action_types(self) -> List[str]:
        """Action types this policy applies to."""
        return ["config_change"]

    def _validate_impl(self, action: Dict[str, Any], context: Dict[str, Any]) -> ValidationResult:
        """Validate config change action.

        Args:
            action: Action dict with keys:
                - action_type: "config_change"
                - agent_name: str
                - old_config: dict
                - new_config: dict
            context: Execution context dict

        Returns:
            ValidationResult with valid=True/False and violations
        """
        violations: List[SafetyViolation] = []

        # Extract configs
        agent_name = action.get("agent_name", "unknown")
        old_config = action.get("old_config", {})
        new_config = action.get("new_config", {})

        # Detect changes
        changes = self._detect_changes(old_config, new_config)

        # Check each change type
        for change in changes:
            # Model changes
            if "model" in change.field_path.lower():
                model_violations = self._check_model_change(change, agent_name, action, context)
                violations.extend(model_violations)

            # Temperature changes
            elif "temperature" in change.field_path.lower():
                temp_violations = self._check_temperature_change(change, agent_name, action, context)
                violations.extend(temp_violations)

            # Safety mode changes
            elif "safety" in change.field_path.lower() and "mode" in change.field_path.lower():
                safety_violations = self._check_safety_mode_change(change, agent_name, action, context)
                violations.extend(safety_violations)

            # Tool configuration changes
            elif "tools" in change.field_path.lower():
                tool_violations = self._check_tool_change(change, agent_name, action, context)
                violations.extend(tool_violations)

        # Check estimated cost impact
        cost_violations = self._check_cost_impact(old_config, new_config, agent_name, action, context)
        violations.extend(cost_violations)

        # Determine if valid
        critical_violations = [v for v in violations if v.severity == ViolationSeverity.CRITICAL]
        high_violations = [v for v in violations if v.severity == ViolationSeverity.HIGH]

        # Block if critical violations
        valid = len(critical_violations) == 0

        return ValidationResult(
            valid=valid,
            violations=violations,
            policy_name=self.name,
            metadata={
                "num_changes": len(changes),
                "num_critical_violations": len(critical_violations),
                "num_high_violations": len(high_violations),
                "requires_approval": len(high_violations) > 0,
                "agent_name": agent_name
            }
        )

    def _detect_changes(
        self,
        old_config: Dict[str, Any],
        new_config: Dict[str, Any],
        prefix: str = ""
    ) -> List[ConfigChange]:
        """Detect all changes between configs.

        Args:
            old_config: Old configuration dict
            new_config: New configuration dict
            prefix: Field path prefix for recursion

        Returns:
            List of ConfigChange objects
        """
        changes = []

        # Get all keys from both configs
        all_keys = set(old_config.keys()) | set(new_config.keys())

        for key in all_keys:
            field_path = f"{prefix}.{key}" if prefix else key
            old_value = old_config.get(key)
            new_value = new_config.get(key)

            if key not in old_config:
                # Added field
                changes.append(ConfigChange(
                    field_path=field_path,
                    old_value=None,
                    new_value=new_value,
                    change_type="added"
                ))
            elif key not in new_config:
                # Removed field
                changes.append(ConfigChange(
                    field_path=field_path,
                    old_value=old_value,
                    new_value=None,
                    change_type="removed"
                ))
            elif isinstance(old_value, dict) and isinstance(new_value, dict):
                # Recurse into nested dicts
                nested_changes = self._detect_changes(old_value, new_value, field_path)
                changes.extend(nested_changes)
            elif old_value != new_value:
                # Modified field
                changes.append(ConfigChange(
                    field_path=field_path,
                    old_value=old_value,
                    new_value=new_value,
                    change_type="modified"
                ))

        return changes

    def _check_model_change(
        self,
        change: ConfigChange,
        agent_name: str,
        action: Dict[str, Any],
        context: Dict[str, Any]
    ) -> List[SafetyViolation]:
        """Check if model change is safe.

        Args:
            change: ConfigChange for model field
            agent_name: Name of agent
            action: Action dict
            context: Execution context

        Returns:
            List of violations
        """
        violations = []

        new_model = change.new_value

        # Check if model is in allowed list
        if self.allowed_models is not None and new_model not in self.allowed_models:
            violations.append(SafetyViolation(
                policy_name=self.name,
                severity=ViolationSeverity.CRITICAL,
                message=f"Model '{new_model}' not in allowed list for {agent_name}",
                action=str(action),
                context=context,
                metadata={
                    "field": change.field_path,
                    "new_model": new_model,
                    "allowed_models": self.allowed_models
                }
            ))

        # Require approval for model changes
        if self.require_approval_for_model_change:
            violations.append(SafetyViolation(
                policy_name=self.name,
                severity=ViolationSeverity.HIGH,
                message=f"Model change from '{change.old_value}' to '{new_model}' requires approval for {agent_name}",
                action=str(action),
                context=context,
                metadata={
                    "field": change.field_path,
                    "old_model": change.old_value,
                    "new_model": new_model
                }
            ))

        return violations

    def _check_temperature_change(
        self,
        change: ConfigChange,
        agent_name: str,
        action: Dict[str, Any],
        context: Dict[str, Any]
    ) -> List[SafetyViolation]:
        """Check if temperature change is within safe range.

        Args:
            change: ConfigChange for temperature field
            agent_name: Name of agent
            action: Action dict
            context: Execution context

        Returns:
            List of violations
        """
        violations = []

        new_temp = change.new_value

        # Validate temperature range
        if new_temp < self.min_temperature or new_temp > self.max_temperature:
            violations.append(SafetyViolation(
                policy_name=self.name,
                severity=ViolationSeverity.CRITICAL,
                message=f"Temperature {new_temp} outside safe range [{self.min_temperature}, {self.max_temperature}] for {agent_name}",
                action=str(action),
                context=context,
                metadata={
                    "field": change.field_path,
                    "new_temperature": new_temp,
                    "min_allowed": self.min_temperature,
                    "max_allowed": self.max_temperature
                }
            ))

        return violations

    def _check_safety_mode_change(
        self,
        change: ConfigChange,
        agent_name: str,
        action: Dict[str, Any],
        context: Dict[str, Any]
    ) -> List[SafetyViolation]:
        """Check if safety mode change is allowed.

        Args:
            change: ConfigChange for safety mode field
            agent_name: Name of agent
            action: Action dict
            context: Execution context

        Returns:
            List of violations
        """
        violations = []

        old_mode = change.old_value
        new_mode = change.new_value

        # Block downgrades from require_approval to execute
        if self.block_safety_downgrades:
            if old_mode == "require_approval" and new_mode in ("execute", "dry_run"):
                violations.append(SafetyViolation(
                    policy_name=self.name,
                    severity=ViolationSeverity.CRITICAL,
                    message=f"Safety mode downgrade from '{old_mode}' to '{new_mode}' blocked for {agent_name}",
                    action=str(action),
                    context=context,
                    metadata={
                        "field": change.field_path,
                        "old_mode": old_mode,
                        "new_mode": new_mode
                    }
                ))

        return violations

    def _check_tool_change(
        self,
        change: ConfigChange,
        agent_name: str,
        action: Dict[str, Any],
        context: Dict[str, Any]
    ) -> List[SafetyViolation]:
        """Check if tool configuration change is safe.

        Args:
            change: ConfigChange for tool field
            agent_name: Name of agent
            action: Action dict
            context: Execution context

        Returns:
            List of violations
        """
        violations = []

        # For now, just flag tool changes as requiring approval
        # More sophisticated checks could validate specific tool configs
        violations.append(SafetyViolation(
            policy_name=self.name,
            severity=ViolationSeverity.HIGH,
            message=f"Tool configuration change requires approval for {agent_name}",
            action=str(action),
            context=context,
            metadata={
                "field": change.field_path,
                "old_value": change.old_value,
                "new_value": change.new_value
            }
        ))

        return violations

    def _check_cost_impact(
        self,
        old_config: Dict[str, Any],
        new_config: Dict[str, Any],
        agent_name: str,
        action: Dict[str, Any],
        context: Dict[str, Any]
    ) -> List[SafetyViolation]:
        """Check estimated cost impact of config change.

        Args:
            old_config: Old configuration
            new_config: New configuration
            agent_name: Name of agent
            action: Action dict
            context: Execution context

        Returns:
            List of violations
        """
        violations = []

        # Simple heuristic: check if switching to more expensive model
        old_model = old_config.get("inference", {}).get("model", "")
        new_model = new_config.get("inference", {}).get("model", "")

        # Map model sizes to relative costs (rough estimates)
        model_costs = {
            "phi3:mini": 1,
            "llama3.2:3b": 2,
            "gemma2:2b": 2,
            "mistral:7b": MODEL_COST_MISTRAL_7B,
            "llama3.1:8b": MODEL_COST_LLAMA_8B,
            "mixtral:8x7b": MODEL_COST_MIXTRAL_8X7B,
        }

        old_cost = model_costs.get(old_model, DEFAULT_MODEL_COST)
        new_cost = model_costs.get(new_model, DEFAULT_MODEL_COST)

        if new_cost > old_cost:
            cost_increase_pct = ((new_cost - old_cost) / old_cost) * 100

            if cost_increase_pct > self.max_cost_increase_pct:
                violations.append(SafetyViolation(
                    policy_name=self.name,
                    severity=ViolationSeverity.HIGH,
                    message=f"Estimated cost increase of {cost_increase_pct:.0f}% exceeds threshold for {agent_name}",
                    action=str({"old_model": old_model, "new_model": new_model}),
                    context=context,
                    metadata={
                        "old_model": old_model,
                        "new_model": new_model,
                        "cost_increase_pct": cost_increase_pct,
                        "max_allowed_pct": self.max_cost_increase_pct
                    }
                ))

        return violations
