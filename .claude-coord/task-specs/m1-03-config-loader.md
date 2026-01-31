# Task: m1-03-config-loader - Implement YAML config loading and validation

**Priority:** CRITICAL
**Effort:** 2 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

Implement YAML configuration loading system that discovers, loads, validates, and caches agent/stage/workflow/tool/trigger configs. Supports environment variable substitution and schema validation against Pydantic models.

---

## Files to Create

- `src/compiler/config_loader.py` - Main config loading logic
- `src/compiler/config_cache.py` - Config caching
- `src/compiler/exceptions.py` - Config loading exceptions
- `tests/test_compiler/test_config_loader.py` - Config loader tests

---

## Acceptance Criteria

### Core Functionality
- [ ] ConfigLoader class with methods: load_agent, load_stage, load_workflow, load_tool, load_trigger
- [ ] Auto-discovery of configs in configs/ directories
- [ ] YAML parsing with error handling
- [ ] Environment variable substitution (${VAR_NAME} syntax)
- [ ] Config validation against Pydantic schemas (from m1-04)
- [ ] Config caching for performance
- [ ] Clear error messages for missing/invalid configs

### Features
- [ ] Support both YAML and JSON formats
- [ ] Template variable substitution in prompts
- [ ] Config inheritance (future: extends: base_config.yaml)
- [ ] Hot-reload detection (optional for M1)

### Testing
- [ ] Test loading valid configs
- [ ] Test loading invalid configs (error handling)
- [ ] Test environment variable substitution
- [ ] Test caching works
- [ ] Test missing file errors
- [ ] Coverage > 90%

### Documentation
- [ ] Docstrings for all public methods
- [ ] Usage examples
- [ ] Type hints

---

## Implementation Details

```python
"""Configuration loading and validation system."""
import os
import yaml
import json
from pathlib import Path
from typing import Dict, Any, Optional, TypeVar, Type
from pydantic import BaseModel, ValidationError
import re


T = TypeVar('T', bound=BaseModel)


class ConfigLoadError(Exception):
    """Raised when config fails to load."""
    pass


class ConfigLoader:
    """Loads and validates YAML/JSON configurations."""

    def __init__(self, config_root: str = "configs"):
        """Initialize config loader.

        Args:
            config_root: Root directory for configs (default: configs/)
        """
        self.config_root = Path(config_root)
        self._cache: Dict[str, Any] = {}

    def load_agent(self, agent_name: str) -> 'AgentConfig':
        """Load agent configuration."""
        return self._load_config(
            "agents", agent_name, AgentConfig
        )

    def load_stage(self, stage_name: str) -> 'StageConfig':
        """Load stage configuration."""
        return self._load_config(
            "stages", stage_name, StageConfig
        )

    def load_workflow(self, workflow_name: str) -> 'WorkflowConfig':
        """Load workflow configuration."""
        return self._load_config(
            "workflows", workflow_name, WorkflowConfig
        )

    def load_tool(self, tool_name: str) -> 'ToolConfig':
        """Load tool configuration."""
        return self._load_config(
            "tools", tool_name, ToolConfig
        )

    def _load_config(
        self, 
        subdir: str, 
        name: str, 
        schema_class: Type[T]
    ) -> T:
        """Generic config loader with caching and validation."""
        cache_key = f"{subdir}/{name}"

        # Check cache
        if cache_key in self._cache:
            return self._cache[cache_key]

        # Find config file (try .yaml then .json)
        config_path = self._find_config_file(subdir, name)
        if not config_path:
            raise ConfigLoadError(
                f"Config not found: {subdir}/{name}.yaml or .json"
            )

        # Load raw config
        raw_config = self._load_yaml_or_json(config_path)

        # Substitute environment variables
        raw_config = self._substitute_env_vars(raw_config)

        # Validate against schema
        try:
            validated_config = schema_class(**raw_config)
        except ValidationError as e:
            raise ConfigLoadError(
                f"Config validation failed for {config_path}:\n{e}"
            )

        # Cache and return
        self._cache[cache_key] = validated_config
        return validated_config

    def _find_config_file(self, subdir: str, name: str) -> Optional[Path]:
        """Find config file (.yaml or .json)."""
        base_path = self.config_root / subdir / name

        for ext in [".yaml", ".yml", ".json"]:
            path = base_path.with_suffix(ext)
            if path.exists():
                return path

        return None

    def _load_yaml_or_json(self, path: Path) -> Dict[str, Any]:
        """Load YAML or JSON file."""
        try:
            with open(path, "r") as f:
                if path.suffix == ".json":
                    return json.load(f)
                else:
                    return yaml.safe_load(f)
        except Exception as e:
            raise ConfigLoadError(f"Failed to parse {path}: {e}")

    def _substitute_env_vars(self, config: Any) -> Any:
        """Recursively substitute ${VAR_NAME} with environment variables."""
        if isinstance(config, dict):
            return {
                k: self._substitute_env_vars(v) 
                for k, v in config.items()
            }
        elif isinstance(config, list):
            return [self._substitute_env_vars(item) for item in config]
        elif isinstance(config, str):
            return self._substitute_env_var_string(config)
        else:
            return config

    def _substitute_env_var_string(self, value: str) -> str:
        """Substitute ${VAR_NAME} in a string."""
        pattern = r'\$\{([^}]+)\}'

        def replacer(match):
            var_name = match.group(1)
            env_value = os.getenv(var_name)
            if env_value is None:
                raise ConfigLoadError(
                    f"Environment variable not set: {var_name}"
                )
            return env_value

        return re.sub(pattern, replacer, value)

    def clear_cache(self):
        """Clear config cache (useful for hot-reload)."""
        self._cache.clear()


# Global instance
_config_loader: Optional[ConfigLoader] = None


def init_config_loader(config_root: str = "configs") -> ConfigLoader:
    """Initialize global config loader."""
    global _config_loader
    _config_loader = ConfigLoader(config_root)
    return _config_loader


def get_config_loader() -> ConfigLoader:
    """Get global config loader instance."""
    if _config_loader is None:
        raise RuntimeError(
            "Config loader not initialized. Call init_config_loader() first."
        )
    return _config_loader
```

---

## Test Strategy

```python
def test_load_valid_agent_config():
    # Create test YAML file
    # Load using ConfigLoader
    # Assert fields are correct

def test_env_var_substitution():
    # Create config with ${TEST_VAR}
    # Set os.environ["TEST_VAR"] = "test_value"
    # Load config
    # Assert substitution worked

def test_missing_env_var_raises_error():
    # Config with ${MISSING_VAR}
    # Assert ConfigLoadError raised

def test_caching():
    # Load config twice
    # Assert second load uses cache (fast)

def test_invalid_yaml_raises_error():
    # Create invalid YAML
    # Assert ConfigLoadError raised
```

---

## Success Metrics

- [ ] All config types load correctly
- [ ] Environment variable substitution works
- [ ] Validation catches invalid configs
- [ ] Caching improves performance
- [ ] Tests pass > 90% coverage

---

## Dependencies

- **Blocked by:** m1-00-structure (completed)
- **Blocks:** m1-07-integration
- **Integrates with:** m1-04-config-schemas (uses Pydantic models for validation)

---

## Design References

- TECHNICAL_SPECIFICATION.md Section 2: Configuration System
- Pydantic docs: https://docs.pydantic.dev/

---

## Notes

- Use yaml.safe_load() not load() for security
- Environment variables MUST be set or raise error (don't use defaults silently)
- Cache configs for performance but allow clear_cache() for hot-reload
