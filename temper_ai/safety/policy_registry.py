"""Policy Registry for managing safety policy registration and lookup.

Provides centralized registry for:
- Registering policies by action type
- Global policies (apply to all actions)
- Priority-based policy ordering

Example:
    >>> registry = PolicyRegistry()
    >>> registry.register_policy(FileAccessPolicy(), ["file_read", "file_write"])
    >>> registry.register_policy(RateLimitPolicy())  # Global
    >>> policies = registry.get_policies_for_action("file_write")
"""

import builtins
import threading

from temper_ai.safety.interfaces import SafetyPolicy


class PolicyRegistry:
    """Registry for safety policies.

    Manages policy registration and lookup by action type. Supports:
    - Action-specific policies (e.g., file_write, git_commit)
    - Global policies (apply to all actions)
    - Priority-based ordering (highest priority first)

    Example:
        >>> registry = PolicyRegistry()
        >>>
        >>> # Register action-specific policy
        >>> registry.register_policy(
        ...     FileAccessPolicy(),
        ...     action_types=["file_read", "file_write"]
        ... )
        >>>
        >>> # Register global policy (applies to all actions)
        >>> registry.register_policy(CircuitBreakerPolicy())
        >>>
        >>> # Get policies for specific action
        >>> policies = registry.get_policies_for_action("file_write")
    """

    def __init__(self) -> None:
        """Initialize empty policy registry."""
        self._lock = threading.Lock()

        # action_type -> List[SafetyPolicy]
        self._policies: dict[str, list[SafetyPolicy]] = {}

        # Global policies (apply to all actions)
        self._global_policies: list[SafetyPolicy] = []

        # Policy name -> action_types (for tracking)
        self._policy_mappings: dict[str, set[str]] = {}

    def register_policy(
        self, policy: SafetyPolicy, action_types: list[str] | None = None
    ) -> None:
        """Register policy for specific action types or globally.

        Args:
            policy: Policy instance to register
            action_types: List of action types (None = global policy)

        Raises:
            ValueError: If policy with same name already registered

        Example:
            >>> registry.register_policy(
            ...     FileAccessPolicy(),
            ...     action_types=["file_read", "file_write"]
            ... )
        """
        with self._lock:
            # Check for duplicate policy name
            if policy.name in self._policy_mappings:
                raise ValueError(
                    f"Policy '{policy.name}' already registered. "
                    f"Unregister existing policy first or use unique name."
                )

            if action_types is None:
                # Global policy (applies to all actions)
                self._global_policies.append(policy)
                self._global_policies.sort(key=lambda p: p.priority, reverse=True)
                self._policy_mappings[policy.name] = set()  # Empty set = global
            else:
                # Action-specific policy
                action_types_set = set(action_types)

                for action_type in action_types:
                    if action_type not in self._policies:
                        self._policies[action_type] = []

                    self._policies[action_type].append(policy)
                    # Sort by priority (highest first)
                    self._policies[action_type].sort(
                        key=lambda p: p.priority, reverse=True
                    )

                self._policy_mappings[policy.name] = action_types_set

    def list_policies(self) -> list[str]:
        """Get names of all registered policies.

        Returns:
            Sorted list of policy names
        """
        return sorted(self._policy_mappings.keys())

    def get_policies_for_action(self, action_type: str) -> builtins.list[SafetyPolicy]:
        """Get all policies applicable to an action type.

        Returns both global policies and action-specific policies,
        sorted by priority (highest first).

        Args:
            action_type: Action type identifier (e.g., "file_write", "git_commit")

        Returns:
            List of applicable SafetyPolicy instances, sorted by priority

        Example:
            >>> policies = registry.get_policies_for_action("file_write")
            >>> for policy in policies:
            ...     print(f"{policy.name} (priority {policy.priority})")
        """
        with self._lock:
            # Start with global policies (apply to all actions)
            policies = list(self._global_policies)

            # Add action-specific policies
            if action_type in self._policies:
                policies.extend(self._policies[action_type])

            # Re-sort by priority (highest first) to ensure correct order
            # when combining global + action-specific policies
            policies.sort(key=lambda p: p.priority, reverse=True)

            return policies

    def clear(self) -> None:
        """Remove all registered policies.

        Useful for testing or complete reconfiguration.
        """
        with self._lock:
            self._policies.clear()
            self._global_policies.clear()
            self._policy_mappings.clear()

    def policy_count(self) -> int:
        """Get total number of registered policies.

        Returns:
            Total policy count (including global)
        """
        return len(self._policy_mappings)

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"PolicyRegistry("
            f"policies={len(self._policy_mappings)}, "
            f"global={len(self._global_policies)}, "
            f"action_types={len(self._policies)})"
        )
