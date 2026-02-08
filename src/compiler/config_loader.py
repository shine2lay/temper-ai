"""
Configuration loader for YAML/JSON configs.

Loads and validates configuration files for agents, stages, workflows, tools, and triggers.
Supports environment variable substitution, secret references, and prompt template loading.

M5 Integration: Automatically checks ConfigDeployer for M5-improved configs before
falling back to YAML files. This closes the self-improvement feedback loop.
"""
import json
import logging
import os
import re
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Match, Optional, Union, cast

import yaml
from pydantic import ValidationError

# Import context-aware environment variable validator
from src.compiler.env_var_validator import EnvVarValidator

# Import schemas for validation
from src.compiler.schemas import (
    AgentConfig,
    CronTrigger,
    EventTrigger,
    StageConfig,
    ThresholdTrigger,
    ToolConfig,
    WorkflowConfig,
)

# Import security limits from shared configuration
from src.compiler.security_limits import CONFIG_SECURITY

# Import enhanced exceptions
from src.utils.exceptions import ConfigNotFoundError, ConfigValidationError

# Import secrets management
from src.utils.secrets import SecretReference, resolve_secret

# Security limit constants (imported from security_limits.py for consistency)
MAX_CONFIG_SIZE = CONFIG_SECURITY.MAX_CONFIG_SIZE
MAX_ENV_VAR_SIZE = CONFIG_SECURITY.MAX_ENV_VAR_SIZE
MAX_YAML_NESTING_DEPTH = CONFIG_SECURITY.MAX_YAML_NESTING_DEPTH
MAX_YAML_NODES = CONFIG_SECURITY.MAX_YAML_NODES


__all__ = [
    "ConfigLoader",
    "ConfigNotFoundError",
    "ConfigValidationError",
]


class ConfigLoader:
    """
    Loads and validates YAML/JSON configuration files.

    Features:
    - Loads configs from configs/ directory structure
    - Supports both YAML and JSON formats
    - Environment variable substitution (${VAR_NAME})
    - Prompt template loading with variable substitution
    - Validation against schemas (when provided)
    - Caching for performance
    - M5 Integration: Checks ConfigDeployer for improved configs before YAML fallback
    """

    # Default maximum number of cached configs before LRU eviction
    DEFAULT_MAX_CACHE_SIZE = 128

    def __init__(
        self,
        config_root: Optional[Union[str, Path]] = None,
        cache_enabled: bool = True,
        config_deployer=None,
        max_cache_size: int = DEFAULT_MAX_CACHE_SIZE
    ):
        """
        Initialize config loader.

        Args:
            config_root: Root directory for configs (defaults to ./configs)
            cache_enabled: Whether to cache loaded configs
            config_deployer: Optional ConfigDeployer for M5 integration (closes feedback loop)
            max_cache_size: Maximum number of cached configs (LRU eviction when exceeded)
        """
        self.config_deployer = config_deployer
        self._config_deployer_initialized = False  # Lazy init flag
        self._config_deployer_available = False  # Whether ConfigDeployer is available

        if config_root is None:
            # Default to configs/ in current directory or project root
            config_root = Path.cwd() / "configs"
            if not config_root.exists():
                # Try to find project root
                current = Path.cwd()
                while current != current.parent:
                    potential_root = current / "configs"
                    if potential_root.exists():
                        config_root = potential_root
                        break
                    current = current.parent

        self.config_root = Path(config_root)
        if not self.config_root.exists():
            raise ConfigNotFoundError(
                message=f"Config root directory not found: {self.config_root}",
                config_path=str(self.config_root)
            )

        self.cache_enabled = cache_enabled
        self._max_cache_size = max_cache_size
        self._cache: OrderedDict[str, Dict[str, Any]] = OrderedDict()

        # Subdirectories for each config type
        self.agents_dir = self.config_root / "agents"
        self.stages_dir = self.config_root / "stages"
        self.workflows_dir = self.config_root / "workflows"
        self.tools_dir = self.config_root / "tools"
        self.triggers_dir = self.config_root / "triggers"
        self.prompts_dir = self.config_root / "prompts"

    def _load_config(
        self,
        config_type: str,
        name: str,
        directory: Path,
        validate: bool = True
    ) -> Dict[str, Any]:
        """
        Generic config loading with caching, substitution, and validation.

        Args:
            config_type: Type of config (agent, stage, workflow, tool, trigger)
            name: Config name (without extension)
            directory: Directory to load from
            validate: Whether to validate against schema

        Returns:
            Configuration dictionary

        Raises:
            ConfigNotFoundError: If config not found
            ConfigValidationError: If validation fails
        """
        cache_key = f"{config_type}:{name}"
        if self.cache_enabled and cache_key in self._cache:
            self._cache.move_to_end(cache_key)
            return self._cache[cache_key]

        config = self._load_config_file(directory, name)
        config = self._substitute_env_vars(config)

        # Resolve secret references (${env:VAR}, ${vault:path}, ${aws:secret-id})
        config = self._resolve_secrets(config)

        # Validate against schemas
        if validate:
            self._validate_config(config_type, config)

        if self.cache_enabled:
            self._cache[cache_key] = config
            # Evict least-recently-used entries when cache exceeds max size
            while len(self._cache) > self._max_cache_size:
                self._cache.popitem(last=False)

        return cast(Dict[str, Any], config)

    def _ensure_config_deployer(self) -> None:
        """
        Lazy-initialize ConfigDeployer for M5 integration.

        Attempts to import and initialize ConfigDeployer with coordination database.
        If initialization fails (no database, import error, etc.), gracefully disables
        M5 integration and logs the issue.

        This enables seamless M5 integration: when coordination database is available,
        ConfigLoader automatically uses M5-improved configs. When not available, it
        falls back to YAML-only mode.
        """
        if self._config_deployer_initialized:
            return

        self._config_deployer_initialized = True
        logger = logging.getLogger(__name__)

        # If ConfigDeployer was explicitly provided, use it
        if self.config_deployer is not None:
            self._config_deployer_available = True
            logger.debug("Using provided ConfigDeployer for M5 integration")
            return

        # ConfigDeployer integration removed (coordination system obsolete)
        self.config_deployer = None
        self._config_deployer_available = False

    def load_agent(self, agent_name: str, validate: bool = True) -> Dict[str, Any]:
        """
        Load agent configuration.

        M5 Integration: Checks ConfigDeployer first for improved configs deployed by M5,
        then falls back to YAML files if no deployed config exists. This closes the
        self-improvement feedback loop.

        Flow:
        1. If config_deployer provided, check for deployed config
        2. If deployed config exists and valid, return it (M5-improved config)
        3. Otherwise, fall back to loading from YAML file (baseline config)

        Args:
            agent_name: Name of the agent (without extension)
            validate: Whether to validate the config (requires schema)

        Returns:
            Agent configuration dictionary (from ConfigDeployer or YAML)

        Raises:
            ConfigNotFoundError: If agent config not found in either source
            ConfigValidationError: If validation fails
        """
        logger = logging.getLogger(__name__)

        # M5 Integration: Ensure ConfigDeployer is initialized (lazy init)
        self._ensure_config_deployer()

        # M5 Integration: Check ConfigDeployer first (closes feedback loop)
        if self._config_deployer_available and self.config_deployer:
            try:
                deployed_config_obj = self.config_deployer.get_agent_config(agent_name)
                # Convert AgentConfig object to dict
                deployed_config = deployed_config_obj.to_dict()

                # If we got a non-default config (has deployed settings), use it
                if deployed_config.get("inference") or deployed_config.get("prompt"):
                    logger.info(
                        f"Loading M5-improved config for {agent_name} from ConfigDeployer"
                    )

                    # Validate if requested
                    if validate:
                        self._validate_config("agent", deployed_config)

                    return deployed_config
                else:
                    # Got default config from ConfigDeployer, fall back to YAML
                    logger.debug(
                        f"No deployed config for {agent_name}, falling back to YAML"
                    )
            except Exception as e:
                # ConfigDeployer failed, fall back to YAML
                logger.debug(
                    f"ConfigDeployer lookup failed for {agent_name}, falling back to YAML: {e}"
                )

        # Fall back to YAML file loading (baseline config)
        return self._load_config("agent", agent_name, self.agents_dir, validate)

    def load_stage(self, stage_name: str, validate: bool = True) -> Dict[str, Any]:
        """
        Load stage configuration.

        Args:
            stage_name: Name of the stage (without extension)
            validate: Whether to validate the config

        Returns:
            Stage configuration dictionary
        """
        return self._load_config("stage", stage_name, self.stages_dir, validate)

    def load_workflow(self, workflow_name: str, validate: bool = True) -> Dict[str, Any]:
        """
        Load workflow configuration.

        Args:
            workflow_name: Name of the workflow (without extension)
            validate: Whether to validate the config

        Returns:
            Workflow configuration dictionary
        """
        return self._load_config("workflow", workflow_name, self.workflows_dir, validate)

    def load_tool(self, tool_name: str, validate: bool = True) -> Dict[str, Any]:
        """
        Load tool configuration.

        Args:
            tool_name: Name of the tool (without extension)
            validate: Whether to validate the config

        Returns:
            Tool configuration dictionary
        """
        return self._load_config("tool", tool_name, self.tools_dir, validate)

    def load_trigger(self, trigger_name: str, validate: bool = True) -> Dict[str, Any]:
        """
        Load trigger configuration.

        Args:
            trigger_name: Name of the trigger (without extension)
            validate: Whether to validate the config

        Returns:
            Trigger configuration dictionary
        """
        return self._load_config("trigger", trigger_name, self.triggers_dir, validate)

    def load_prompt_template(self, template_path: str, variables: Optional[Dict[str, str]] = None) -> str:
        """
        Load prompt template and substitute variables.

        Args:
            template_path: Relative path to template file (e.g., "researcher_base.txt")
            variables: Variables to substitute in template

        Returns:
            Rendered prompt string

        Example:
            >>> loader.load_prompt_template("agent_base.txt", {"domain": "SaaS", "tone": "professional"})
            "You are an expert in SaaS products. Use a professional tone..."

        Raises:
            ConfigNotFoundError: If template not found
            ConfigValidationError: If path attempts directory traversal, contains null bytes,
                                   contains control characters, or file too large
        """
        logger = logging.getLogger(__name__)

        # SECURITY FIX: Check for null bytes FIRST (before any path operations)
        # Prevents null byte injection attacks where attacker provides: "safe.txt\x00../../etc/passwd"
        if '\x00' in template_path:
            logger.warning(
                "Security violation: Null byte detected in template path",
                extra={
                    "template_path": repr(template_path),
                    "attack_type": "null_byte_injection"
                }
            )
            raise ConfigValidationError(
                'Invalid template path: null byte detected. '
                'This may indicate a path traversal attack attempt.'
            )

        # SECURITY FIX: Check for control characters (0x00-0x1F except newline, carriage return, tab)
        # Control characters can bypass validation or cause unexpected behavior
        if any(ord(c) < 32 and c not in '\n\r\t' for c in template_path):
            logger.warning(
                "Security violation: Control characters detected in template path",
                extra={
                    "template_path": repr(template_path),
                    "attack_type": "control_character_injection"
                }
            )
            raise ConfigValidationError(
                'Invalid template path: control characters detected. '
                'Only printable characters are allowed in paths.'
            )

        # Resolve full path and validate it's within prompts directory (prevent directory traversal)
        full_path = (self.prompts_dir / template_path).resolve()

        try:
            # Check if path is relative to prompts_dir (Python 3.9+)
            full_path.relative_to(self.prompts_dir.resolve())
        except ValueError:
            logger.warning(
                "Security violation: Path traversal attempt detected",
                extra={
                    "template_path": repr(template_path),
                    "resolved_path": str(full_path),
                    "prompts_dir": str(self.prompts_dir),
                    "attack_type": "path_traversal"
                }
            )
            raise ConfigValidationError(
                f"Template path must be within prompts directory: {template_path}"
            )

        if not full_path.exists():
            raise ConfigNotFoundError(
                message=f"Prompt template not found: {full_path}",
                config_path=str(full_path)
            )

        # Check file size to prevent memory exhaustion
        file_size = full_path.stat().st_size
        if file_size > MAX_CONFIG_SIZE:
            raise ConfigValidationError(
                f"Template file too large: {file_size} bytes (max: {MAX_CONFIG_SIZE})"
            )

        # Load template content
        with open(full_path, 'r', encoding='utf-8') as f:
            template = f.read()

        # Substitute variables if provided
        if variables:
            template = self._substitute_template_vars(template, variables)

        return template

    def list_configs(self, config_type: str) -> List[str]:
        """
        List available configuration files of a given type.

        Args:
            config_type: One of: agent, stage, workflow, tool, trigger

        Returns:
            List of config names (without extensions)
        """
        type_dirs = {
            "agent": self.agents_dir,
            "stage": self.stages_dir,
            "workflow": self.workflows_dir,
            "tool": self.tools_dir,
            "trigger": self.triggers_dir,
        }

        if config_type not in type_dirs:
            raise ValueError(f"Unknown config type: {config_type}")

        config_dir = type_dirs[config_type]
        if not config_dir.exists():
            return []

        configs = []
        for file_path in config_dir.iterdir():
            if file_path.suffix in ['.yaml', '.yml', '.json']:
                configs.append(file_path.stem)

        return sorted(configs)

    def clear_cache(self) -> None:
        """Clear the configuration cache."""
        self._cache.clear()

    def _load_config_file(self, directory: Path, name: str) -> Dict[str, Any]:
        """
        Load a configuration file (YAML or JSON).

        Tries both .yaml, .yml, and .json extensions.
        """
        # Try different extensions
        for ext in ['.yaml', '.yml', '.json']:
            file_path = directory / f"{name}{ext}"
            if file_path.exists():
                return self._parse_config_file(file_path)

        raise ConfigNotFoundError(
            message=f"Config file not found: {name} in {directory}\nTried extensions: .yaml, .yml, .json",
            config_path=str(directory / name)
        )

    def _parse_config_file(self, file_path: Path) -> Dict[str, Any]:
        """
        Parse a YAML or JSON configuration file with security protections.

        Args:
            file_path: Path to config file

        Returns:
            Parsed configuration dictionary

        Raises:
            ConfigValidationError: If file too large, parsing fails, or security limits exceeded
        """
        # Check file size to prevent memory exhaustion
        file_size = file_path.stat().st_size
        if file_size > MAX_CONFIG_SIZE:
            raise ConfigValidationError(
                f"Config file too large: {file_size} bytes (max: {MAX_CONFIG_SIZE})"
            )

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                if file_path.suffix == '.json':
                    config = json.load(f)
                else:
                    # Use safe_load with additional security checks
                    config = yaml.safe_load(f)

            # Validate the parsed config for security issues
            self._validate_config_structure(config, file_path)

            return cast(Dict[str, Any], config)

        except yaml.YAMLError as e:
            raise ConfigValidationError(
                f"YAML parsing failed for {file_path}: {e}"
            )
        except json.JSONDecodeError as e:
            raise ConfigValidationError(
                f"JSON parsing failed for {file_path}: {e}"
            )
        except Exception as e:
            raise ConfigValidationError(
                f"Failed to parse config file {file_path}: {e}"
            )

    def _validate_config_structure(
        self,
        config: Any,
        file_path: Path,
        current_depth: int = 0,
        visited: Optional[set[int]] = None,
        node_count: Optional[list[int]] = None
    ) -> None:
        """
        Validate config structure for security issues.

        Checks for:
        - Excessive nesting depth (>50 levels) - prevents stack overflow
        - Too many nodes (>100k) - prevents YAML bomb (billion laughs)
        - Circular references - prevents infinite loops

        Args:
            config: Configuration to validate
            file_path: Path to config file (for error messages)
            current_depth: Current nesting depth
            visited: Set of visited object IDs (for circular reference detection)
            node_count: List containing single integer (mutable counter for nodes)

        Raises:
            ConfigValidationError: If security limits exceeded
        """
        # Initialize tracking on first call
        if visited is None:
            visited = set()
        if node_count is None:
            node_count = [0]  # Use list to make it mutable in nested calls

        # Check nesting depth
        if current_depth > MAX_YAML_NESTING_DEPTH:
            raise ConfigValidationError(
                f"Config file {file_path} exceeds maximum nesting depth of {MAX_YAML_NESTING_DEPTH} levels. "
                f"This may indicate a YAML bomb attack or malformed config."
            )

        # Increment node count
        node_count[0] += 1
        if node_count[0] > MAX_YAML_NODES:
            raise ConfigValidationError(
                f"Config file {file_path} exceeds maximum node count of {MAX_YAML_NODES}. "
                f"This may indicate a YAML bomb (billion laughs) attack."
            )

        # Check for circular references (only for mutable objects)
        if isinstance(config, (dict, list)):
            obj_id = id(config)
            if obj_id in visited:
                raise ConfigValidationError(
                    f"Circular reference detected in config file {file_path}. "
                    f"This may cause infinite loops during processing."
                )
            visited.add(obj_id)

            try:
                # Recursively validate nested structures
                if isinstance(config, dict):
                    for key, value in config.items():
                        self._validate_config_structure(
                            value,
                            file_path,
                            current_depth + 1,
                            visited,
                            node_count
                        )
                elif isinstance(config, list):
                    for item in config:
                        self._validate_config_structure(
                            item,
                            file_path,
                            current_depth + 1,
                            visited,
                            node_count
                        )
            finally:
                # Remove from visited after processing children
                # This allows the same object to appear in different branches
                # but prevents cycles within a single branch
                visited.discard(obj_id)

    def _substitute_env_vars(self, config: Any) -> Any:
        """
        Recursively substitute environment variables in config.

        Replaces ${VAR_NAME} with os.environ['VAR_NAME']
        Replaces ${VAR_NAME:default_value} with os.environ.get('VAR_NAME', 'default_value')
        """
        if isinstance(config, dict):
            return {k: self._substitute_env_vars(v) for k, v in config.items()}
        elif isinstance(config, list):
            return [self._substitute_env_vars(item) for item in config]
        elif isinstance(config, str):
            return self._substitute_env_var_string(config)
        else:
            return config

    def _substitute_env_var_string(self, value: str) -> str:
        """
        Substitute environment variables in a string with security validation.

        Supports:
        - ${VAR_NAME} - required variable
        - ${VAR_NAME:default} - optional variable with default

        Note: This is for legacy env var substitution. Prefer secret references
        (${env:VAR_NAME}) for credentials, which are handled by _resolve_secrets.

        Validates environment variable values to prevent injection attacks.
        """
        # Skip if value looks like a secret reference (will be handled by _resolve_secrets)
        if SecretReference.is_reference(value):
            return value

        # Pattern: ${VAR_NAME} or ${VAR_NAME:default}
        pattern = r'\$\{([A-Za-z_][A-Za-z0-9_]*)(?::([^}]*))?\}'

        def replacer(match: Match[str]) -> str:
            var_name = match.group(1)
            default_value = match.group(2)

            if var_name in os.environ:
                env_value = os.environ[var_name]
                # Validate environment variable value for security
                self._validate_env_var_value(var_name, env_value)
                return env_value
            elif default_value is not None:
                # Validate default values as well (they could contain malicious content)
                self._validate_env_var_value(var_name, default_value)
                return default_value
            else:
                raise ConfigValidationError(
                    f"Environment variable '{var_name}' is required but not set"
                )

        return re.sub(pattern, replacer, value)

    def _validate_env_var_value(self, var_name: str, value: str) -> None:
        """
        Validate environment variable value for security issues using context-aware validation.

        This method uses the EnvVarValidator which provides defense-in-depth through:
        - Context detection from variable name patterns
        - Whitelist-based validation (defines what IS allowed)
        - Multiple validation layers (pattern + context-specific checks)
        - Protection against: command injection, SQL injection, path traversal, etc.

        Key Security Improvements (vs previous implementation):
        - Validates ALL variables based on context, not just those matching specific name patterns
        - Prevents command injection bypass via non-obvious variable names
        - Uses whitelist approach instead of blacklist for better security
        - Context-aware rules: executable, path, structured, identifier, data, unrestricted

        Args:
            var_name: Name of environment variable
            value: Value to validate

        Raises:
            ConfigValidationError: If value fails validation for its detected context

        Example:
            # OLD (VULNERABLE): Only checked if name contained 'cmd', 'command', etc.
            # API_ENDPOINT = "http://api.com; rm -rf /" would PASS (bypassed validation)

            # NEW (SECURE): Checks ALL variables based on detected context
            # API_ENDPOINT = "http://api.com; rm -rf /" will FAIL (semicolon not allowed in STRUCTURED context)
        """
        # Use context-aware validator
        validator = EnvVarValidator()
        is_valid, error_message = validator.validate(
            var_name=var_name,
            value=value,
            max_length=MAX_ENV_VAR_SIZE
        )

        if not is_valid:
            raise ConfigValidationError(error_message)

    def _resolve_secrets(self, config: Any) -> Any:
        """
        Recursively resolve secret references in configuration.

        Resolves references like:
        - ${env:VAR_NAME} - environment variable
        - ${vault:path} - HashiCorp Vault (future)
        - ${aws:secret-id} - AWS Secrets Manager (future)

        Args:
            config: Configuration to process (dict, list, str, etc.)

        Returns:
            Configuration with resolved secrets

        Raises:
            ConfigValidationError: If secret resolution fails
        """
        try:
            return resolve_secret(config)
        except (ValueError, NotImplementedError) as e:
            raise ConfigValidationError(f"Secret resolution failed: {e}")

    def _substitute_template_vars(self, template: str, variables: Dict[str, str]) -> str:
        """
        Substitute variables in a prompt template.

        Replaces {{var_name}} with variables['var_name']
        """
        pattern = r'\{\{([A-Za-z_][A-Za-z0-9_]*)\}\}'

        def replacer(match: Match[str]) -> str:
            var_name = match.group(1)
            if var_name not in variables:
                raise ConfigValidationError(
                    f"Template variable '{var_name}' is required but not provided"
                )
            return variables[var_name]

        return re.sub(pattern, replacer, template)

    def _validate_config(self, config_type: str, config: Dict[str, Any]) -> None:
        """
        Validate configuration against Pydantic schemas.

        Args:
            config_type: Type of config (agent, stage, workflow, tool, trigger)
            config: Configuration dictionary to validate

        Raises:
            ConfigValidationError: If validation fails
        """
        schema_map = {
            "agent": AgentConfig,
            "stage": StageConfig,
            "workflow": WorkflowConfig,
            "tool": ToolConfig,
        }

        try:
            if config_type == "trigger":
                # Triggers have multiple possible schemas - try each
                trigger_type = config.get("trigger", {}).get("type")
                if trigger_type == "EventTrigger":
                    EventTrigger(**config)
                elif trigger_type == "CronTrigger":
                    CronTrigger(**config)
                elif trigger_type == "ThresholdTrigger":
                    ThresholdTrigger(**config)
                else:
                    raise ConfigValidationError(
                        f"Unknown trigger type: {trigger_type}"
                    )
            elif config_type in schema_map:
                # Validate with appropriate schema
                schema_map[config_type](**config)
            # else: Unknown config type - skip validation (no action needed)

        except ValidationError as e:
            raise ConfigValidationError(
                f"Config validation failed for {config_type}: {e}"
            )
