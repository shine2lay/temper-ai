"""PolicyEngine — evaluates all active policies before an action executes.

First deny wins. If all policies allow, the action proceeds.
Policies that don't handle the current action_type are skipped.
"""

from __future__ import annotations

import logging
from typing import Any

from temper_ai.safety.base import ActionType, BasePolicy, PolicyDecision
from temper_ai.safety.exceptions import SafetyConfigError

logger = logging.getLogger(__name__)

# Registry of policy types — maps config "type" strings to classes.
# New policies register here to be usable in YAML configs.
POLICY_REGISTRY: dict[str, type[BasePolicy]] = {}


def register_policy(name: str, cls: type[BasePolicy]):
    """Register a policy type for use in YAML configs."""
    POLICY_REGISTRY[name] = cls


class PolicyEngine:
    """Evaluates all active policies for a given action.

    Usage:
        engine = PolicyEngine.from_config({"policies": [...]})
        decision = engine.evaluate(ActionType.TOOL_CALL, action_data, context)
    """

    def __init__(self, policies: list[BasePolicy] | None = None):
        self.policies = policies or []

    def evaluate(
        self,
        action_type: ActionType,
        action_data: dict[str, Any],
        context: dict[str, Any],
        skip_types: set[str] | None = None,
    ) -> PolicyDecision:
        """Run all applicable policies. First deny wins.

        Args:
            action_type: What kind of action is being evaluated.
            action_data: Action-specific data.
            context: Execution context (run_id, accumulated cost, etc.)
            skip_types: Policy type names to skip (e.g., {"budget"}).

        Returns:
            PolicyDecision — allow if all pass, deny on first failure.
        """
        for policy in self.policies:
            if not policy.enabled:
                continue
            if action_type not in policy.action_types:
                continue
            if skip_types and policy.config.get("type") in skip_types:
                continue

            decision = policy.evaluate(action_type, action_data, context)
            if decision.action == "deny":
                logger.info(
                    "Policy '%s' denied %s: %s",
                    policy.name, action_type, decision.reason,
                )
                return decision

        return PolicyDecision(
            action="allow",
            reason="All policies passed",
            policy_name="engine",
        )

    def add_policy(self, policy: BasePolicy):
        """Add a policy to the engine at runtime."""
        self.policies.append(policy)

    @classmethod
    def from_config(cls, config: dict) -> PolicyEngine:
        """Load policies from a workflow safety config dict.

        Config format:
            {"policies": [{"type": "file_access", "denied_paths": [...]}, ...]}

        Raises SafetyConfigError if a policy type is unknown or config is invalid.
        """
        policies: list[BasePolicy] = []
        for policy_config in config.get("policies", []):
            policy_type = policy_config.get("type")
            if not policy_type:
                raise SafetyConfigError("Policy config missing 'type' field")

            if policy_type not in POLICY_REGISTRY:
                available = sorted(POLICY_REGISTRY.keys())
                raise SafetyConfigError(
                    f"Unknown policy type: '{policy_type}'. "
                    f"Available: {available}"
                )

            policy_cls = POLICY_REGISTRY[policy_type]
            # validate_config is called in __init__, will raise on invalid config
            policies.append(policy_cls(policy_config))

        return cls(policies)

    @classmethod
    def validate_config(cls, config: dict) -> list[str]:
        """Validate safety config at compile time without instantiating policies.

        Returns list of errors. Used by GraphLoader for early validation.
        """
        errors = []
        for i, policy_config in enumerate(config.get("policies", [])):
            policy_type = policy_config.get("type")
            if not policy_type:
                errors.append(f"Policy [{i}] missing 'type' field")
                continue

            if policy_type not in POLICY_REGISTRY:
                errors.append(
                    f"Policy [{i}] unknown type: '{policy_type}'. "
                    f"Available: {sorted(POLICY_REGISTRY.keys())}"
                )
                continue

            policy_errors = POLICY_REGISTRY[policy_type].validate_config(policy_config)
            for err in policy_errors:
                errors.append(f"Policy [{i}] ({policy_type}): {err}")

        return errors

    @staticmethod
    def validate_action_coverage(
        config: dict,
        wired_action_types: set[ActionType],
    ) -> list[str]:
        """Warn if configured policies don't handle any wired action type.

        Called at load time to catch policies that would never execute.
        """
        warnings = []
        for policy_config in config.get("policies", []):
            policy_type = policy_config.get("type")
            if policy_type not in POLICY_REGISTRY:
                continue
            policy_cls = POLICY_REGISTRY[policy_type]
            policy_actions = set(policy_cls.action_types)
            if not policy_actions & wired_action_types:
                warnings.append(
                    f"Policy '{policy_type}' handles {sorted(policy_actions)} "
                    f"but only {sorted(wired_action_types)} are evaluated. "
                    f"This policy will never run."
                )
        return warnings
