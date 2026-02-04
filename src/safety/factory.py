"""Safety stack factory for creating integrated safety components.

This module provides factory functions to create a fully-wired safety stack
including ActionPolicyEngine, ApprovalWorkflow, RollbackManager, and ToolExecutor.
"""
import os
import yaml
import logging
from typing import Dict, Any, Optional
from pathlib import Path

from src.safety.policy_registry import PolicyRegistry
from src.safety.action_policy_engine import ActionPolicyEngine
from src.safety.approval import ApprovalWorkflow, NoOpApprover
from src.safety.rollback import RollbackManager
from src.tools.executor import ToolExecutor
from src.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


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

    Args:
        config: Safety configuration dict

    Returns:
        PolicyRegistry with registered policies

    Note:
        Currently creates empty registry. Full policy loading from config
        will be implemented in future iteration. Policies can be registered
        manually after creation.
    """
    registry = PolicyRegistry()

    # TODO: Load and register policies from config['policy_mappings']
    # For now, return empty registry - policies can be registered manually
    # or in a future enhancement

    logger.info("Created PolicyRegistry (empty - policies can be registered manually)")
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
        approver = NoOpApprover()
        logger.info("Created ApprovalWorkflow with NoOpApprover (auto-approve for dev)")
    else:
        # In staging/production, use NoOpApprover but log warning
        # Real approver implementation should be added for production use
        approver = NoOpApprover()
        logger.warning(
            f"Using NoOpApprover in {environment} environment. "
            "Replace with real approver for production use."
        )

    approval_workflow = ApprovalWorkflow(approver=approver)

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
