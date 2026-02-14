"""Safety stack factory for creating integrated safety components.

This module provides factory functions to create a fully-wired safety stack
including ActionPolicyEngine, ApprovalWorkflow, RollbackManager, and ToolExecutor.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional, Type

import yaml

from src.constants.durations import RATE_LIMIT_WINDOW_MINUTE
from src.constants.limits import THRESHOLD_VERY_LARGE_COUNT
from src.safety.action_policy_engine import ActionPolicyEngine
from src.safety.approval import ApprovalWorkflow, NoOpApprover
from src.safety.base import BaseSafetyPolicy
from src.safety.blast_radius import BlastRadiusPolicy
from src.safety.config_change_policy import ConfigChangePolicy
from src.safety.constants import ENV_DEVELOPMENT, ENV_KEY
from src.safety.file_access import FileAccessPolicy
from src.safety.forbidden_operations import ForbiddenOperationsPolicy
from src.safety.policies.rate_limit_policy import TokenBucketRateLimitPolicy
from src.safety.policies.resource_limit_policy import ResourceLimitPolicy
from src.safety.policy_registry import PolicyRegistry
from src.safety.rate_limiter import WindowRateLimitPolicy
from src.safety.rollback import RollbackManager
from src.safety.secret_detection import SecretDetectionPolicy
from src.safety.stub_policies import ApprovalWorkflowPolicy, CircuitBreakerPolicy

if TYPE_CHECKING:
    from src.tools.executor import ToolExecutor
    from src.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


# Fallback mapping from YAML config policy names to their implementation classes.
# Each class accepts an optional config dict in its constructor.
# Prefer using _resolve_policy_class() which checks _CUSTOM_POLICIES first.
_BUILTIN_POLICIES: Dict[str, Type[BaseSafetyPolicy]] = {
    "secret_detection_policy": SecretDetectionPolicy,
    "file_access_policy": FileAccessPolicy,
    "forbidden_ops_policy": ForbiddenOperationsPolicy,
    "blast_radius_policy": BlastRadiusPolicy,
    "rate_limiter_policy": WindowRateLimitPolicy,
    "config_change_policy": ConfigChangePolicy,
    "rate_limit_policy": TokenBucketRateLimitPolicy,
    "resource_limit_policy": ResourceLimitPolicy,
    "approval_workflow_policy": ApprovalWorkflowPolicy,
    "circuit_breaker_policy": CircuitBreakerPolicy,
}

# Custom policy class registrations (takes precedence over _BUILTIN_POLICIES).
# Populated by register_policy_class().
_CUSTOM_POLICIES: Dict[str, Type[BaseSafetyPolicy]] = {}


def register_policy_class(name: str, policy_cls: Type[BaseSafetyPolicy]) -> None:
    """Register a custom policy class for use in safety config.

    Custom policy classes take precedence over built-in policies when
    resolving policy names from YAML configuration.

    Args:
        name: Policy config name (e.g., "my_custom_policy")
        policy_cls: Policy class (must be a BaseSafetyPolicy subclass)

    Raises:
        TypeError: If policy_cls is not a BaseSafetyPolicy subclass
    """
    if not (isinstance(policy_cls, type) and issubclass(policy_cls, BaseSafetyPolicy)):
        raise TypeError(
            f"policy_cls must be a BaseSafetyPolicy subclass, got {policy_cls!r}"
        )
    _CUSTOM_POLICIES[name] = policy_cls
    logger.debug("Registered custom policy class: %s -> %s", name, policy_cls.__name__)


def _resolve_policy_class(name: str) -> Optional[Type[BaseSafetyPolicy]]:
    """Resolve a policy config name to its implementation class.

    Checks custom registrations first, then falls back to built-in policies.

    Args:
        name: Policy config name (e.g., "file_access_policy")

    Returns:
        Policy class if found, None otherwise
    """
    # Custom registrations take precedence
    policy_cls = _CUSTOM_POLICIES.get(name)
    if policy_cls is not None:
        return policy_cls
    # Fall back to built-in policies
    return _BUILTIN_POLICIES.get(name)


# Public alias for backward compatibility
BUILTIN_POLICIES = _BUILTIN_POLICIES


def load_safety_config(config_path: Optional[str] = None, environment: str = "development") -> Dict[str, Any]:
    """Load safety configuration from YAML file.

    Args:
        config_path: Path to action_policies.yaml (default: config/safety/action_policies.yaml)
        environment: Environment name (development/staging/production)

    Returns:
        Merged configuration dict with environment overrides applied
    """
    path_obj: Path
    if config_path is None:
        # Default path relative to project root
        project_root = Path(__file__).parent.parent.parent
        path_obj = project_root / "config" / "safety" / "action_policies.yaml"
    else:
        path_obj = Path(config_path)

    if not path_obj.exists():
        logger.warning(f"Safety config not found at {path_obj}, using defaults")
        return _get_default_config()

    with open(path_obj, 'r') as f:
        loaded_config = yaml.safe_load(f)

    if not isinstance(loaded_config, dict):
        logger.warning(f"Invalid config format in {path_obj}, using defaults")
        return _get_default_config()

    # Apply environment overrides
    if ENV_KEY in loaded_config and environment in loaded_config[ENV_KEY]:
        env_config = loaded_config[ENV_KEY][environment]
        if isinstance(env_config, dict):
            loaded_config = _merge_configs(loaded_config, env_config)

    return dict(loaded_config)


def _get_default_config() -> Dict[str, Any]:
    """Get default safety configuration."""
    return {
        'policy_engine': {
            'cache_ttl': RATE_LIMIT_WINDOW_MINUTE,
            'max_cache_size': THRESHOLD_VERY_LARGE_COUNT,
            'enable_caching': True,
            'short_circuit_critical': True,
            'log_violations': True,
        },
        'policy_mappings': {},
        'global_policies': [],
        'policy_config': {},
    }


def _merge_configs(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Deep merge override config into base config."""
    result = base.copy()

    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _merge_configs(result[key], value)
        else:
            result[key] = value

    return result


def create_policy_registry(config: Dict[str, Any]) -> PolicyRegistry:
    """Create and populate PolicyRegistry from config.

    Reads ``policy_mappings``, ``global_policies``, and ``policy_config``
    from the safety configuration and registers all available built-in
    policies.  Unknown policy names (e.g. policies that haven't been
    implemented yet) are logged as warnings and skipped.

    Args:
        config: Safety configuration dict (from ``load_safety_config()``)

    Returns:
        PolicyRegistry with built-in policies registered
    """
    registry = PolicyRegistry()

    policy_mappings: Dict[str, list] = config.get("policy_mappings", {})
    global_policy_names: list = config.get("global_policies", [])
    policy_configs: Dict[str, Any] = config.get("policy_config", {})

    # Collect all unique policy names referenced in the config, together
    # with the action types they should be registered for.
    # Key: policy config name  →  Value: set of action types (empty = global)
    policy_action_map: Dict[str, set[str]] = {}

    for action_type, policy_names in policy_mappings.items():
        for pname in policy_names:
            policy_action_map.setdefault(pname, set()).add(str(action_type))

    for pname in global_policy_names:
        # None sentinel will be handled below to register as global
        policy_action_map.setdefault(pname, set())

    # Instantiate and register each policy
    for pname, action_types in policy_action_map.items():
        policy_cls = _resolve_policy_class(pname)
        if policy_cls is None:
            logger.warning(
                "Policy '%s' referenced in config but no built-in implementation found — skipping",
                pname,
            )
            continue

        # Build per-policy config.  BaseSafetyPolicy validates that values
        # are primitives (no nested dicts), so we filter out nested dicts.
        # Policies fall back to their built-in defaults for any omitted keys.
        raw_pcfg = policy_configs.get(pname, {})
        pcfg = {k: v for k, v in raw_pcfg.items() if not isinstance(v, dict)}

        try:
            policy_instance = policy_cls(config=pcfg)
        except Exception:
            logger.exception("Failed to instantiate policy '%s' — skipping", pname)
            continue

        # Determine registration mode
        is_global = pname in global_policy_names
        if is_global:
            # Register as global (applies to all action types)
            registry.register_policy(policy_instance, action_types=None)
            logger.debug("Registered global policy: %s", pname)
        else:
            registry.register_policy(policy_instance, action_types=list(action_types))
            logger.debug(
                "Registered policy '%s' for action types: %s",
                pname,
                sorted(action_types),
            )

    logger.info(
        "Created PolicyRegistry with %d policies (%d global, %d action-specific)",
        registry.policy_count(),
        len([p for p in global_policy_names if _resolve_policy_class(p) is not None]),
        registry.policy_count() - len([p for p in global_policy_names if _resolve_policy_class(p) is not None]),
    )
    return registry


def create_safety_stack(
    tool_registry: ToolRegistry,
    config_path: Optional[str] = None,
    environment: Optional[str] = None
) -> ToolExecutor:
    """Create fully-wired safety stack with ToolExecutor.

    Creates and wires together:
    - PolicyRegistry (with policies from config)
    - ActionPolicyEngine (with policy_engine config)
    - ApprovalWorkflow (with NoOpApprover for dev, can be overridden)
    - RollbackManager (with default config)
    - ToolExecutor (with all safety components)

    Args:
        tool_registry: ToolRegistry instance for tool execution
        config_path: Path to action_policies.yaml (default: config/safety/action_policies.yaml)
        environment: Environment name (default: from SAFETY_ENV or "development")

    Returns:
        ToolExecutor with complete safety stack wired in

    Example:
        >>> from src.tools.registry import ToolRegistry
        >>> from src.safety.factory import create_safety_stack
        >>>
        >>> tool_registry = ToolRegistry()
        >>> tool_executor = create_safety_stack(tool_registry, environment="development")
        >>> # Now pass tool_executor to agents for safe tool execution
    """
    # Determine environment
    if environment is None:
        environment = os.getenv("SAFETY_ENV", "development")

    logger.info(f"Creating safety stack for environment: {environment}")

    # Load configuration
    config = load_safety_config(config_path, environment)

    # Create policy registry
    policy_registry = create_policy_registry(config)

    # Create ActionPolicyEngine
    engine_config = config.get('policy_engine', {})
    policy_engine = ActionPolicyEngine(policy_registry, config=engine_config)
    logger.info(f"Created ActionPolicyEngine with config: {engine_config}")

    # Create ApprovalWorkflow
    approval_mode = config.get("approval_mode", None)
    approval_workflow: Any
    if approval_mode == "noop":
        # Explicit opt-in to auto-approve in any environment
        approval_workflow = NoOpApprover()
        if environment != "development":
            logger.warning(
                "Using NoOpApprover in '%s' environment (explicit opt-in). "
                "All approval requests will be auto-approved.",
                environment,
            )
        else:
            logger.info("Created NoOpApprover approval workflow (auto-approve for dev)")
    elif environment == ENV_DEVELOPMENT:
        # Development default: auto-approve
        approval_workflow = NoOpApprover()
        logger.info("Created NoOpApprover approval workflow (auto-approve for dev)")
    else:
        # Non-dev default: real approval workflow requiring human review
        approval_workflow = ApprovalWorkflow()
        logger.info(
            "Created ApprovalWorkflow for '%s' environment — "
            "high-risk actions will require human approval",
            environment,
        )

    # Create RollbackManager
    rollback_manager = RollbackManager()
    logger.info("Created RollbackManager")

    # Create ToolExecutor with all safety components (lazy import to avoid
    # module-level coupling between safety and tools packages)
    from src.tools.executor import ToolExecutor as _ToolExecutor
    tool_executor = _ToolExecutor(
        registry=tool_registry,
        policy_engine=policy_engine,
        approval_workflow=approval_workflow,
        rollback_manager=rollback_manager,
        enable_auto_rollback=True
    )

    logger.info("Created ToolExecutor with complete safety stack")
    return tool_executor
