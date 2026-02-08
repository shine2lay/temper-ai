"""
Configuration loader for YAML/JSON configs.

Loads and validates configuration files for agents, stages, workflows, tools, and triggers.
Supports environment variable substitution, secret references, and prompt template loading.

M5 Integration: Automatically checks ConfigDeployer for M5-improved configs before
falling back to YAML files. This closes the self-improvement feedback loop.
"""
import logging
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional, Union, cast

from src.compiler._config_loader_helpers import (
    load_config_file,
    resolve_secrets,
    substitute_env_vars,
    substitute_template_vars,
    validate_config,
    validate_config_structure,
)

# Import security limits from shared configuration
from src.compiler.security_limits import CONFIG_SECURITY
from src.constants.limits import MEDIUM_ITEM_LIMIT

# Import enhanced exceptions
from src.utils.exceptions import ConfigNotFoundError, ConfigValidationError
from src.utils.logging import ASCII_CONTROL_CHAR_MAX

# Security limit constants (imported from security_limits.py for consistency)
MAX_CONFIG_SIZE = CONFIG_SECURITY.MAX_CONFIG_SIZE

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

    # Cache size calculation constants
    CACHE_SIZE_MULTIPLIER = 12  # Multiply base item limit by this for total cache size

    # Default maximum number of cached configs before LRU eviction
    DEFAULT_MAX_CACHE_SIZE = MEDIUM_ITEM_LIMIT * CACHE_SIZE_MULTIPLIER  # 120 configs (10 * 12)

    def __init__(
        self,
        config_root: Optional[Union[str, Path]] = None,
        cache_enabled: bool = True,
        config_deployer: Any = None,
        max_cache_size: int = DEFAULT_MAX_CACHE_SIZE
    ) -> None:
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
        """Lazy-initialize ConfigDeployer for M5 integration."""
        if self._config_deployer_initialized:
            return

        self._config_deployer_initialized = True
        _logger = logging.getLogger(__name__)

        # If ConfigDeployer was explicitly provided, use it
        if self.config_deployer is not None:
            self._config_deployer_available = True
            _logger.debug("Using provided ConfigDeployer for M5 integration")
            return

        # ConfigDeployer integration removed (coordination system obsolete)
        self.config_deployer = None
        self._config_deployer_available = False

    def load_agent(self, agent_name: str, validate: bool = True) -> Dict[str, Any]:
        """
        Load agent configuration.

        M5 Integration: Checks ConfigDeployer first for improved configs deployed by M5,
        then falls back to YAML files if no deployed config exists.

        Args:
            agent_name: Name of the agent (without extension)
            validate: Whether to validate the config (requires schema)

        Returns:
            Agent configuration dictionary (from ConfigDeployer or YAML)

        Raises:
            ConfigNotFoundError: If agent config not found in either source
            ConfigValidationError: If validation fails
        """
        _logger = logging.getLogger(__name__)

        # M5 Integration: Ensure ConfigDeployer is initialized (lazy init)
        self._ensure_config_deployer()

        # M5 Integration: Check ConfigDeployer first (closes feedback loop)
        if self._config_deployer_available and self.config_deployer:
            try:
                deployed_config_obj = self.config_deployer.get_agent_config(agent_name)
                deployed_config: Dict[str, Any] = deployed_config_obj.to_dict()

                if deployed_config.get("inference") or deployed_config.get("prompt"):
                    _logger.info(
                        f"Loading M5-improved config for {agent_name} from ConfigDeployer"
                    )
                    if validate:
                        self._validate_config("agent", deployed_config)
                    return deployed_config
                else:
                    _logger.debug(
                        f"No deployed config for {agent_name}, falling back to YAML"
                    )
            except Exception as e:
                _logger.debug(
                    f"ConfigDeployer lookup failed for {agent_name}, falling back to YAML: {e}"
                )

        # Fall back to YAML file loading (baseline config)
        return self._load_config("agent", agent_name, self.agents_dir, validate)

    def load_stage(self, stage_name: str, validate: bool = True) -> Dict[str, Any]:
        """Load stage configuration."""
        return self._load_config("stage", stage_name, self.stages_dir, validate)

    def load_workflow(self, workflow_name: str, validate: bool = True) -> Dict[str, Any]:
        """Load workflow configuration."""
        return self._load_config("workflow", workflow_name, self.workflows_dir, validate)

    def load_tool(self, tool_name: str, validate: bool = True) -> Dict[str, Any]:
        """Load tool configuration."""
        return self._load_config("tool", tool_name, self.tools_dir, validate)

    def load_trigger(self, trigger_name: str, validate: bool = True) -> Dict[str, Any]:
        """Load trigger configuration."""
        return self._load_config("trigger", trigger_name, self.triggers_dir, validate)

    def load_prompt_template(self, template_path: str, variables: Optional[Dict[str, str]] = None) -> str:
        """
        Load prompt template and substitute variables.

        Args:
            template_path: Relative path to template file (e.g., "researcher_base.txt")
            variables: Variables to substitute in template

        Returns:
            Rendered prompt string

        Raises:
            ConfigNotFoundError: If template not found
            ConfigValidationError: If path attempts directory traversal, contains null bytes,
                                   contains control characters, or file too large
        """
        _logger = logging.getLogger(__name__)

        # SECURITY FIX: Check for null bytes FIRST (before any path operations)
        if '\x00' in template_path:
            _logger.warning(
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

        # SECURITY FIX: Check for control characters
        if any(ord(c) < ASCII_CONTROL_CHAR_MAX and c not in '\n\r\t' for c in template_path):
            _logger.warning(
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

        # Resolve full path and validate it's within prompts directory
        full_path = (self.prompts_dir / template_path).resolve()

        try:
            full_path.relative_to(self.prompts_dir.resolve())
        except ValueError:
            _logger.warning(
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

        with open(full_path, 'r', encoding='utf-8') as f:
            template = f.read()

        if variables:
            template = self._substitute_template_vars(template, variables)

        return template

    def list_configs(self, config_type: str) -> List[str]:
        """List available configuration files of a given type."""
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
        """Load a configuration file (YAML or JSON). Delegates to helper."""
        return load_config_file(directory, name)

    def _parse_config_file(self, file_path: Path) -> Dict[str, Any]:
        """Parse a YAML or JSON configuration file. Delegates to helper."""
        from src.compiler._config_loader_helpers import parse_config_file
        return parse_config_file(file_path)

    def _validate_config_structure(
        self, config: Any, file_path: Path,
        current_depth: int = 0, visited: Optional[set] = None,
        node_count: Optional[list] = None
    ) -> None:
        """Validate config structure for security issues. Delegates to helper."""
        validate_config_structure(config, file_path, current_depth, visited, node_count)

    def _substitute_env_vars(self, config: Any) -> Any:
        """Recursively substitute environment variables. Delegates to helper."""
        return substitute_env_vars(config)

    def _resolve_secrets(self, config: Any) -> Any:
        """Recursively resolve secret references. Delegates to helper."""
        return resolve_secrets(config)

    def _substitute_template_vars(self, template: str, variables: Dict[str, str]) -> str:
        """Substitute variables in a prompt template. Delegates to helper."""
        return substitute_template_vars(template, variables)

    def _validate_config(self, config_type: str, config: Dict[str, Any]) -> None:
        """Validate configuration against Pydantic schemas. Delegates to helper."""
        validate_config(config_type, config)
