"""Safety stack factory for creating integrated safety components.

This module provides factory functions to create a fully-wired safety stack
including ActionPolicyEngine, ApprovalWorkflow, RollbackManager, and ToolExecutor.
"""
import os
import yaml
import logging
from typing import Dict, Any, Optional, Type
from pathlib import Path

from src.safety.policy_registry import PolicyRegistry
from src.safety.action_policy_engine import ActionPolicyEngine
from src.safety.approval import ApprovalWorkflow, NoOpApprover
from src.safety.rollback import RollbackManager
from src.safety.base import BaseSafetyPolicy
from src.safety.secret_detection import SecretDetectionPolicy
from src.safety.file_access import FileAccessPolicy
from src.safety.forbidden_operations import ForbiddenOperationsPolicy
from src.safety.blast_radius import BlastRadiusPolicy
from src.safety.rate_limiter import RateLimiterPolicy
from src.safety.config_change_policy import ConfigChangePolicy
from src.safety.policies.rate_limit_policy import RateLimitPolicy
from src.safety.policies.resource_limit_policy import ResourceLimitPolicy
from src.tools.executor import ToolExecutor
from src.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


# Mapping from YAML config policy names to their implementation classes.
# Each class accepts an optional config dict in its constructor.
BUILTIN_POLICIES: Dict[str, Type[BaseSafetyPolicy]] = {
    "secret_detection_policy": SecretDetectionPolicy,
    "file_access_policy": FileAccessPolicy,
    "forbidden_ops_policy": ForbiddenOperationsPolicy,
    "blast_radius_policy": BlastRadiusPolicy,
    "rate_limiter_policy": RateLimiterPolicy,
    "config_change_policy": ConfigChangePolicy,
    "rate_limit_policy": RateLimitPolicy,
    "resource_limit_policy": ResourceLimitPolicy,
}


def load_safety_config(config_path: Optional[str] = None, environment: str = "development") -> Dict[str, Any]:
    """Load safety configuration from YAML file.

    Args:
        config_path: Path to action_policies.yaml (default: config/safety/action_policies.yaml)
        environment: Environment name (development/staging/production)

    Returns:
        Merged configuration dict with environment overrides applied
    """
    if config_path is None:
        # Default path relative to project root
        project_root = Path(__file__).parent.parent.parent
        config_path = project_root / "config" / "safety" / "action_policies.yaml"

    if not Path(config_path).exists():
        logger.warning(f"Safety config not found at {config_path}, using defaults")
        return _get_default_config()

    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)

    # Apply environment overrides
    if 'environments' in config and environment in config['environments']:
        env_config = config['environments'][environment]
        config = _merge_configs(config, env_config)

    return config


def _get_default_config() -> Dict[str, Any]:
    """Get default safety configuration."""
    return {
        'policy_engine': {
            'cache_ttl': 60,
            'max_cache_size': 1000,
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
    policy_action_map: Dict[str, set] = {}

    for action_type, policy_names in policy_mappings.items():
        for pname in policy_names:
            policy_action_map.setdefault(pname, set()).add(action_type)

    for pname in global_policy_names:
        # None sentinel will be handled below to register as global
        policy_action_map.setdefault(pname, set())

    # Instantiate and register each policy
    for pname, action_types in policy_action_map.items():
        policy_cls = BUILTIN_POLICIES.get(pname)
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
        len([p for p in global_policy_names if p in BUILTIN_POLICIES]),
        registry.policy_count() - len([p for p in global_policy_names if p in BUILTIN_POLICIES]),
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
    # For development, use NoOpApprover (auto-approves everything)
    # For staging/production, this should be replaced with real approver
    if environment == "development":
        approval_workflow = NoOpApprover()
        logger.info("Created NoOpApprover approval workflow (auto-approve for dev)")
    else:
        # In staging/production, use NoOpApprover but log warning
        # Real approver implementation should be added for production use
        approval_workflow = NoOpApprover()
        logger.warning(
            f"Using NoOpApprover in {environment} environment. "
            "Replace with real approver for production use."
        )

    # Create RollbackManager
    rollback_manager = RollbackManager()
    logger.info("Created RollbackManager")

    # Create ToolExecutor with all safety components
    tool_executor = ToolExecutor(
        registry=tool_registry,
        policy_engine=policy_engine,
        approval_workflow=approval_workflow,
        rollback_manager=rollback_manager,
        enable_auto_rollback=True
    )

    logger.info("Created ToolExecutor with complete safety stack")
    return tool_executor
