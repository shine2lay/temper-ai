"""Policy Registry for managing safety policy registration and lookup.

Provides centralized registry for:
- Registering policies by action type
- Global policies (apply to all actions)
- Priority-based policy ordering
- Dynamic policy registration/unregistration

Example:
    >>> registry = PolicyRegistry()
    >>> registry.register_policy(FileAccessPolicy(), ["file_read", "file_write"])
    >>> registry.register_policy(RateLimitPolicy())  # Global
    >>> policies = registry.get_policies_for_action("file_write")
"""
import threading
from typing import Any, Dict, List, Optional, Set

from temper_ai.safety.interfaces import SafetyPolicy


class PolicyRegistry:
    """Registry for safety policies.

    Manages policy registration and lookup by action type. Supports:
    - Action-specific policies (e.g., file_write, git_commit)
    - Global policies (apply to all actions)
    - Priority-based ordering (highest priority first)
    - Dynamic registration/unregistration

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
        self._policies: Dict[str, List[SafetyPolicy]] = {}

        # Global policies (apply to all actions)
        self._global_policies: List[SafetyPolicy] = []

        # Policy name -> action_types (for tracking)
        self._policy_mappings: Dict[str, Set[str]] = {}

    def register_policy(
        self,
        policy: SafetyPolicy,
        action_types: Optional[List[str]] = None
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
                    self._policies[action_type].sort(key=lambda p: p.priority, reverse=True)

                self._policy_mappings[policy.name] = action_types_set

    def list_policies(self) -> List[str]:
        """Get names of all registered policies.

        Returns:
            Sorted list of policy names
        """
        return sorted(self._policy_mappings.keys())

    def list(self) -> List[str]:
        """Get names of all registered policies (Registry Protocol method).

        Returns:
            Sorted list of policy names
        """
        return self.list_policies()

    def list_all(self) -> List[str]:
        """DEPRECATED: Use list() instead.

        Get names of all registered policies (backward compatibility).

        Returns:
            Sorted list of policy names
        """
        return self.list_policies()

    def _remove_global_policy(self, policy_name: str) -> None:
        """Remove a global policy by name."""
        self._global_policies = [
            p for p in self._global_policies
            if p.name != policy_name
        ]

    def _remove_action_specific_policy(
        self,
        policy_name: str,
        action_types: Set[str]
    ) -> None:
        """Remove an action-specific policy by name."""
        for action_type in action_types:
            if action_type not in self._policies:
                continue

            self._policies[action_type] = [
                p for p in self._policies[action_type]
                if p.name != policy_name
            ]

            # Remove empty action type entries
            if not self._policies[action_type]:
                del self._policies[action_type]

    def unregister_policy(self, policy_name: str) -> bool:
        """Remove policy by name.

        Args:
            policy_name: Name of policy to remove

        Returns:
            True if policy was found and removed, False otherwise

        Example:
            >>> registry.unregister_policy("file_access_policy")
        """
        with self._lock:
            # Guard clause: policy not found
            if policy_name not in self._policy_mappings:
                return False

            action_types = self._policy_mappings[policy_name]

            # Remove based on policy type
            if not action_types:
                self._remove_global_policy(policy_name)
            else:
                self._remove_action_specific_policy(policy_name, action_types)

            del self._policy_mappings[policy_name]
            return True

    def get_policies_for_action(self, action_type: str) -> List[SafetyPolicy]:
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

    def get_policy(self, policy_name: str) -> Optional[SafetyPolicy]:
        """Get policy instance by name.

        Args:
            policy_name: Name of policy to retrieve

        Returns:
            SafetyPolicy instance if found, None otherwise

        Example:
            >>> policy = registry.get_policy("file_access_policy")
        """
        # Search global policies
        for policy in self._global_policies:
            if policy.name == policy_name:
                return policy

        # Search action-specific policies
        for action_type, policies in self._policies.items():
            for policy in policies:
                if policy.name == policy_name:
                    return policy

        return None

    def get(self, name: str) -> Optional[SafetyPolicy]:
        """Get policy instance by name (Registry Protocol method).

        This is an alias for get_policy() to satisfy the Registry Protocol.

        Args:
            name: Name of policy to retrieve

        Returns:
            SafetyPolicy instance if found, None otherwise
        """
        return self.get_policy(name)

    def is_registered(self, policy_name: str) -> bool:
        """Check if policy is registered.

        Args:
            policy_name: Name of policy to check

        Returns:
            True if policy is registered, False otherwise

        Example:
            >>> if registry.is_registered("file_access_policy"):
            ...     print("Policy is active")
        """
        return policy_name in self._policy_mappings

    def get_action_types(self) -> List[str]:
        """Get all action types with registered policies.

        Returns:
            List of action type identifiers

        Example:
            >>> action_types = registry.get_action_types()
            >>> print(f"Protected actions: {action_types}")
        """
        return list(self._policies.keys())

    def get_policies_for_action_by_priority(
        self,
        action_type: str
    ) -> Dict[int, List[SafetyPolicy]]:
        """Get policies grouped by priority level.

        Useful for understanding policy execution order and identifying
        which policies have P0/P1/P2 priority.

        Args:
            action_type: Action type identifier

        Returns:
            Dictionary mapping priority level to list of policies

        Example:
            >>> by_priority = registry.get_policies_for_action_by_priority("file_write")
            >>> for priority, policies in sorted(by_priority.items(), reverse=True):
            ...     print(f"Priority {priority}: {[p.name for p in policies]}")
        """
        policies = self.get_policies_for_action(action_type)
        grouped: Dict[int, List[SafetyPolicy]] = {}

        for policy in policies:
            priority = policy.priority
            if priority not in grouped:
                grouped[priority] = []
            grouped[priority].append(policy)

        return grouped

    def clear(self) -> None:
        """Remove all registered policies.

        Useful for testing or complete reconfiguration.

        Example:
            >>> registry.clear()
        """
        with self._lock:
            self._policies.clear()
            self._global_policies.clear()
            self._policy_mappings.clear()

    def policy_count(self) -> int:
        """Get total number of registered policies.

        Returns:
            Total policy count (including global)

        Example:
            >>> count = registry.policy_count()
        """
        return len(self._policy_mappings)

    def count(self) -> int:
        """Get total number of registered policies (Registry Protocol method).

        This is an alias for policy_count() to satisfy the Registry Protocol.

        Returns:
            Total policy count (including global)
        """
        return self.policy_count()

    def get_statistics(self) -> Dict[str, Any]:
        """Get registry statistics.

        Returns:
            Dictionary with statistics about registered policies

        Example:
            >>> stats = registry.get_statistics()
            >>> print(f"Total policies: {stats['total_policies']}")
        """
        return {
            "total_policies": len(self._policy_mappings),
            "global_policies": len(self._global_policies),
            "action_types": len(self._policies),
            "policies_by_action_type": {
                action_type: len(policies)
                for action_type, policies in self._policies.items()
            }
        }

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"PolicyRegistry("
            f"policies={len(self._policy_mappings)}, "
            f"global={len(self._global_policies)}, "
            f"action_types={len(self._policies)})"
        )
