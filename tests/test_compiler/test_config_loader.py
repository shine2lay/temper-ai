"""
Unit tests for ConfigLoader.

Tests YAML/JSON loading, environment variable substitution,
prompt template loading, and error handling.
"""
import os
import json
import pytest
import tempfile
from pathlib import Path
import yaml

from src.compiler.config_loader import (
    ConfigLoader,
    ConfigNotFoundError,
    ConfigValidationError,
)


@pytest.fixture
def temp_config_dir():
    """Create a temporary config directory structure for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_root = Path(tmpdir)

        # Create subdirectories
        (config_root / "agents").mkdir()
        (config_root / "stages").mkdir()
        (config_root / "workflows").mkdir()
        (config_root / "tools").mkdir()
        (config_root / "triggers").mkdir()
        (config_root / "prompts").mkdir()

        yield config_root


@pytest.fixture
def config_loader(temp_config_dir):
    """Create a ConfigLoader instance with temp directory."""
    return ConfigLoader(config_root=temp_config_dir, cache_enabled=True)


class TestConfigLoaderInit:
    """Test ConfigLoader initialization."""

    def test_init_with_explicit_path(self, temp_config_dir):
        """Test initialization with explicit config root path."""
        loader = ConfigLoader(config_root=temp_config_dir)
        assert loader.config_root == temp_config_dir
        assert loader.cache_enabled is True

    def test_init_with_invalid_path(self):
        """Test initialization with non-existent path raises error."""
        with pytest.raises(ConfigNotFoundError):
            ConfigLoader(config_root="/nonexistent/path")

    def test_init_cache_disabled(self, temp_config_dir):
        """Test initialization with caching disabled."""
        loader = ConfigLoader(config_root=temp_config_dir, cache_enabled=False)
        assert loader.cache_enabled is False


class TestLoadYAMLConfigs:
    """Test loading YAML configuration files."""

    def test_load_agent_yaml(self, config_loader, temp_config_dir):
        """Test loading an agent config in YAML format."""
        # Create test agent config
        agent_config = {
            "agent": {
                "name": "test_agent",
                "description": "A test agent",
                "version": "1.0",
                "inference": {
                    "provider": "ollama",
                    "model": "llama3.2:3b",
                },
            }
        }

        agent_path = temp_config_dir / "agents" / "test_agent.yaml"
        with open(agent_path, 'w') as f:
            yaml.dump(agent_config, f)

        # Load the config
        loaded = config_loader.load_agent("test_agent", validate=False)

        assert loaded == agent_config
        assert loaded["agent"]["name"] == "test_agent"

    def test_load_stage_yaml(self, config_loader, temp_config_dir):
        """Test loading a stage config."""
        stage_config = {
            "stage": {
                "name": "research_stage",
                "agents": ["market_researcher", "competitor_analyst"],
            }
        }

        stage_path = temp_config_dir / "stages" / "research_stage.yaml"
        with open(stage_path, 'w') as f:
            yaml.dump(stage_config, f)

        loaded = config_loader.load_stage("research_stage", validate=False)
        assert loaded == stage_config

    def test_load_workflow_yaml(self, config_loader, temp_config_dir):
        """Test loading a workflow config."""
        workflow_config = {
            "workflow": {
                "name": "mvp_lifecycle",
                "stages": ["research", "requirements", "build"],
            }
        }

        workflow_path = temp_config_dir / "workflows" / "mvp_lifecycle.yaml"
        with open(workflow_path, 'w') as f:
            yaml.dump(workflow_config, f)

        loaded = config_loader.load_workflow("mvp_lifecycle", validate=False)
        assert loaded == workflow_config

    def test_load_tool_yaml(self, config_loader, temp_config_dir):
        """Test loading a tool config."""
        tool_config = {
            "tool": {
                "name": "WebScraper",
                "timeout": 30,
            }
        }

        tool_path = temp_config_dir / "tools" / "WebScraper.yaml"
        with open(tool_path, 'w') as f:
            yaml.dump(tool_config, f)

        loaded = config_loader.load_tool("WebScraper", validate=False)
        assert loaded == tool_config

    def test_load_trigger_yaml(self, config_loader, temp_config_dir):
        """Test loading a trigger config."""
        trigger_config = {
            "trigger": {
                "type": "cron",
                "schedule": "0 0 * * *",
            }
        }

        trigger_path = temp_config_dir / "triggers" / "daily_check.yaml"
        with open(trigger_path, 'w') as f:
            yaml.dump(trigger_config, f)

        loaded = config_loader.load_trigger("daily_check", validate=False)
        assert loaded == trigger_config


class TestLoadJSONConfigs:
    """Test loading JSON configuration files."""

    def test_load_agent_json(self, config_loader, temp_config_dir):
        """Test loading an agent config in JSON format."""
        agent_config = {
            "agent": {
                "name": "json_agent",
                "description": "JSON format agent",
            }
        }

        agent_path = temp_config_dir / "agents" / "json_agent.json"
        with open(agent_path, 'w') as f:
            json.dump(agent_config, f)

        loaded = config_loader.load_agent("json_agent", validate=False)
        assert loaded == agent_config


class TestYMLExtension:
    """Test loading configs with .yml extension."""

    def test_load_yml_extension(self, config_loader, temp_config_dir):
        """Test that .yml extension is also supported."""
        agent_config = {"agent": {"name": "yml_agent"}}

        agent_path = temp_config_dir / "agents" / "yml_agent.yml"
        with open(agent_path, 'w') as f:
            yaml.dump(agent_config, f)

        loaded = config_loader.load_agent("yml_agent", validate=False)
        assert loaded == agent_config


class TestEnvironmentVariableSubstitution:
    """Test environment variable substitution in configs."""

    def test_substitute_required_env_var(self, config_loader, temp_config_dir):
        """Test substitution of required environment variable."""
        os.environ["TEST_API_KEY"] = "secret123"

        agent_config = {
            "agent": {
                "inference": {
                    "api_key": "${TEST_API_KEY}",
                }
            }
        }

        agent_path = temp_config_dir / "agents" / "env_agent.yaml"
        with open(agent_path, 'w') as f:
            yaml.dump(agent_config, f)

        loaded = config_loader.load_agent("env_agent", validate=False)
        assert loaded["agent"]["inference"]["api_key"] == "secret123"

        # Cleanup
        del os.environ["TEST_API_KEY"]

    def test_substitute_optional_env_var_with_default(self, config_loader, temp_config_dir):
        """Test substitution with default value when env var not set."""
        agent_config = {
            "agent": {
                "inference": {
                    "base_url": "${CUSTOM_URL:http://localhost:11434}",
                }
            }
        }

        agent_path = temp_config_dir / "agents" / "default_agent.yaml"
        with open(agent_path, 'w') as f:
            yaml.dump(agent_config, f)

        loaded = config_loader.load_agent("default_agent", validate=False)
        assert loaded["agent"]["inference"]["base_url"] == "http://localhost:11434"

    def test_substitute_optional_env_var_present(self, config_loader, temp_config_dir):
        """Test substitution uses env var when present even with default."""
        os.environ["CUSTOM_URL"] = "http://custom:8080"

        agent_config = {
            "agent": {
                "inference": {
                    "base_url": "${CUSTOM_URL:http://localhost:11434}",
                }
            }
        }

        agent_path = temp_config_dir / "agents" / "custom_agent.yaml"
        with open(agent_path, 'w') as f:
            yaml.dump(agent_config, f)

        loaded = config_loader.load_agent("custom_agent", validate=False)
        assert loaded["agent"]["inference"]["base_url"] == "http://custom:8080"

        # Cleanup
        del os.environ["CUSTOM_URL"]

    def test_missing_required_env_var_raises_error(self, config_loader, temp_config_dir):
        """Test that missing required env var raises error."""
        agent_config = {
            "agent": {
                "inference": {
                    "api_key": "${MISSING_API_KEY}",
                }
            }
        }

        agent_path = temp_config_dir / "agents" / "missing_env.yaml"
        with open(agent_path, 'w') as f:
            yaml.dump(agent_config, f)

        with pytest.raises(ConfigValidationError, match="Environment variable 'MISSING_API_KEY' is required but not set"):
            config_loader.load_agent("missing_env")

    def test_env_var_in_nested_structure(self, config_loader, temp_config_dir):
        """Test env var substitution in nested dictionary."""
        os.environ["NESTED_VALUE"] = "nested_secret"

        config = {
            "workflow": {
                "optimization": {
                    "target": {
                        "metric": "${NESTED_VALUE}",
                    }
                }
            }
        }

        workflow_path = temp_config_dir / "workflows" / "nested.yaml"
        with open(workflow_path, 'w') as f:
            yaml.dump(config, f)

        loaded = config_loader.load_workflow("nested", validate=False)
        assert loaded["workflow"]["optimization"]["target"]["metric"] == "nested_secret"

        # Cleanup
        del os.environ["NESTED_VALUE"]

    def test_env_var_in_list(self, config_loader, temp_config_dir):
        """Test env var substitution in list items."""
        os.environ["LIST_ITEM"] = "list_value"

        config = {
            "tool": {
                "allowed_domains": ["example.com", "${LIST_ITEM}"],
            }
        }

        tool_path = temp_config_dir / "tools" / "list_tool.yaml"
        with open(tool_path, 'w') as f:
            yaml.dump(config, f)

        loaded = config_loader.load_tool("list_tool", validate=False)
        assert loaded["tool"]["allowed_domains"] == ["example.com", "list_value"]

        # Cleanup
        del os.environ["LIST_ITEM"]


class TestPromptTemplateLoading:
    """Test prompt template loading and variable substitution."""

    def test_load_simple_template(self, config_loader, temp_config_dir):
        """Test loading a simple prompt template."""
        template_content = "You are an expert in {{domain}}. Use a {{tone}} tone."

        template_path = temp_config_dir / "prompts" / "base.txt"
        with open(template_path, 'w') as f:
            f.write(template_content)

        variables = {"domain": "SaaS", "tone": "professional"}
        result = config_loader.load_prompt_template("base.txt", variables)

        assert result == "You are an expert in SaaS. Use a professional tone."

    def test_load_template_no_variables(self, config_loader, temp_config_dir):
        """Test loading template without variable substitution."""
        template_content = "This is a static prompt."

        template_path = temp_config_dir / "prompts" / "static.txt"
        with open(template_path, 'w') as f:
            f.write(template_content)

        result = config_loader.load_prompt_template("static.txt")
        assert result == "This is a static prompt."

    def test_load_template_missing_variable_raises_error(self, config_loader, temp_config_dir):
        """Test that missing template variable raises error."""
        template_content = "Domain: {{domain}}, Tone: {{tone}}"

        template_path = temp_config_dir / "prompts" / "missing_var.txt"
        with open(template_path, 'w') as f:
            f.write(template_content)

        variables = {"domain": "SaaS"}  # Missing 'tone'

        with pytest.raises(ConfigValidationError, match="Template variable 'tone' is required but not provided"):
            config_loader.load_prompt_template("missing_var.txt", variables)

    def test_load_nonexistent_template_raises_error(self, config_loader):
        """Test that loading non-existent template raises error."""
        with pytest.raises(ConfigNotFoundError, match="Prompt template not found"):
            config_loader.load_prompt_template("nonexistent.txt")

    def test_load_template_multiline(self, config_loader, temp_config_dir):
        """Test loading multi-line prompt template."""
        template_content = """You are a {{role}}.
Your goal is to {{goal}}.
Use {{style}} communication."""

        template_path = temp_config_dir / "prompts" / "multiline.txt"
        with open(template_path, 'w') as f:
            f.write(template_content)

        variables = {
            "role": "data analyst",
            "goal": "analyze trends",
            "style": "clear and concise",
        }
        result = config_loader.load_prompt_template("multiline.txt", variables)

        expected = """You are a data analyst.
Your goal is to analyze trends.
Use clear and concise communication."""
        assert result == expected


class TestCaching:
    """Test configuration caching functionality."""

    def test_caching_enabled_returns_cached_config(self, config_loader, temp_config_dir):
        """Test that caching returns same object on second load."""
        agent_config = {"agent": {"name": "cached_agent"}}

        agent_path = temp_config_dir / "agents" / "cached_agent.yaml"
        with open(agent_path, 'w') as f:
            yaml.dump(agent_config, f)

        # First load
        first_load = config_loader.load_agent("cached_agent", validate=False)

        # Second load should hit cache
        second_load = config_loader.load_agent("cached_agent", validate=False)

        # Should be same object from cache
        assert first_load is second_load

    def test_clear_cache(self, config_loader, temp_config_dir):
        """Test clearing the cache."""
        agent_config = {"agent": {"name": "cache_test"}}

        agent_path = temp_config_dir / "agents" / "cache_test.yaml"
        with open(agent_path, 'w') as f:
            yaml.dump(agent_config, f)

        # Load and cache
        first_load = config_loader.load_agent("cache_test", validate=False)

        # Clear cache
        config_loader.clear_cache()

        # Load again - should be different object
        second_load = config_loader.load_agent("cache_test", validate=False)

        assert first_load is not second_load
        assert first_load == second_load

    def test_cache_disabled_always_reloads(self, temp_config_dir):
        """Test that disabled cache always reloads config."""
        loader = ConfigLoader(config_root=temp_config_dir, cache_enabled=False)

        agent_config = {"agent": {"name": "no_cache"}}

        agent_path = temp_config_dir / "agents" / "no_cache.yaml"
        with open(agent_path, 'w') as f:
            yaml.dump(agent_config, f)

        # Load twice
        first_load = loader.load_agent("no_cache", validate=False)
        second_load = loader.load_agent("no_cache", validate=False)

        # Should be different objects (not cached)
        assert first_load is not second_load


class TestErrorHandling:
    """Test error handling in ConfigLoader."""

    def test_load_nonexistent_config_raises_error(self, config_loader):
        """Test loading non-existent config raises ConfigNotFoundError."""
        with pytest.raises(ConfigNotFoundError, match="Config file not found"):
            config_loader.load_agent("nonexistent_agent")

    def test_load_invalid_yaml_raises_error(self, config_loader, temp_config_dir):
        """Test loading invalid YAML raises ConfigValidationError."""
        # Create invalid YAML file
        invalid_path = temp_config_dir / "agents" / "invalid.yaml"
        with open(invalid_path, 'w') as f:
            f.write("invalid: yaml: content: [[[")

        with pytest.raises(ConfigValidationError, match="YAML parsing failed"):
            config_loader.load_agent("invalid")

    def test_load_invalid_json_raises_error(self, config_loader, temp_config_dir):
        """Test loading invalid JSON raises ConfigValidationError."""
        # Create invalid JSON file
        invalid_path = temp_config_dir / "agents" / "invalid_json.json"
        with open(invalid_path, 'w') as f:
            f.write('{"invalid": json content}')

        with pytest.raises(ConfigValidationError, match="JSON parsing failed"):
            config_loader.load_agent("invalid_json")


class TestListConfigs:
    """Test listing available configuration files."""

    def test_list_agent_configs(self, config_loader, temp_config_dir):
        """Test listing available agent configs."""
        # Create multiple agent configs
        for name in ["agent1", "agent2", "agent3"]:
            path = temp_config_dir / "agents" / f"{name}.yaml"
            with open(path, 'w') as f:
                yaml.dump({"agent": {"name": name}}, f)

        configs = config_loader.list_configs("agent")
        assert configs == ["agent1", "agent2", "agent3"]

    def test_list_mixed_extensions(self, config_loader, temp_config_dir):
        """Test listing configs with mixed file extensions."""
        # Create configs with different extensions
        (temp_config_dir / "tools" / "tool1.yaml").write_text("tool: {}")
        (temp_config_dir / "tools" / "tool2.yml").write_text("tool: {}")
        (temp_config_dir / "tools" / "tool3.json").write_text("{}")

        configs = config_loader.list_configs("tool")
        assert set(configs) == {"tool1", "tool2", "tool3"}

    def test_list_empty_directory(self, config_loader):
        """Test listing configs from empty directory."""
        configs = config_loader.list_configs("stage")
        assert configs == []

    def test_list_invalid_type_raises_error(self, config_loader):
        """Test listing invalid config type raises error."""
        with pytest.raises(ValueError, match="Unknown config type"):
            config_loader.list_configs("invalid_type")


class TestEnvironmentVariableSecurityValidation:
    """Test security validation of environment variable values."""

    def test_path_traversal_rejected(self, config_loader, temp_config_dir):
        """Test path traversal in path variables is rejected."""
        os.environ["CONFIG_PATH"] = "../../../etc/passwd"

        agent_config = {
            "agent": {
                "config_path": "${CONFIG_PATH}",
            }
        }

        agent_path = temp_config_dir / "agents" / "path_attack.yaml"
        with open(agent_path, 'w') as f:
            yaml.dump(agent_config, f)

        with pytest.raises(ConfigValidationError, match="path traversal pattern"):
            config_loader.load_agent("path_attack")

        # Cleanup
        del os.environ["CONFIG_PATH"]

    def test_shell_metacharacters_in_command_rejected(self, config_loader, temp_config_dir):
        """Test shell metacharacters in command variables are rejected."""
        os.environ["COMMAND"] = "echo hello; rm -rf /"

        config = {
            "tool": {
                "command": "${COMMAND}",
            }
        }

        tool_path = temp_config_dir / "tools" / "cmd_injection.yaml"
        with open(tool_path, 'w') as f:
            yaml.dump(config, f)

        with pytest.raises(ConfigValidationError, match="shell metacharacters"):
            config_loader.load_tool("cmd_injection")

        # Cleanup
        del os.environ["COMMAND"]

    def test_sql_injection_in_db_var_rejected(self, config_loader, temp_config_dir):
        """Test SQL injection patterns in database variables are rejected."""
        os.environ["DB_TABLE"] = "users' OR '1'='1"

        config = {
            "agent": {
                "database_table": "${DB_TABLE}",
            }
        }

        agent_path = temp_config_dir / "agents" / "sql_injection.yaml"
        with open(agent_path, 'w') as f:
            yaml.dump(config, f)

        with pytest.raises(ConfigValidationError, match="SQL injection pattern"):
            config_loader.load_agent("sql_injection")

        # Cleanup
        del os.environ["DB_TABLE"]

    def test_credentials_in_url_rejected(self, config_loader, temp_config_dir):
        """Test credentials embedded in URL variables are rejected."""
        os.environ["API_URL"] = "https://user:password@api.example.com/endpoint"

        config = {
            "agent": {
                "api_url": "${API_URL}",
            }
        }

        agent_path = temp_config_dir / "agents" / "url_creds.yaml"
        with open(agent_path, 'w') as f:
            yaml.dump(config, f)

        with pytest.raises(ConfigValidationError, match="credentials in URL"):
            config_loader.load_agent("url_creds")

        # Cleanup
        del os.environ["API_URL"]

    # Note: Cannot test null bytes via environment variables because
    # os.environ doesn't allow setting values with null bytes.
    # The null byte check remains valuable for validating values from other sources.

    def test_excessively_long_value_rejected(self, config_loader, temp_config_dir):
        """Test excessively long environment variable values are rejected."""
        os.environ["LONG_VALUE"] = "A" * (11 * 1024)  # 11KB > 10KB limit

        config = {
            "agent": {
                "value": "${LONG_VALUE}",
            }
        }

        agent_path = temp_config_dir / "agents" / "long_value.yaml"
        with open(agent_path, 'w') as f:
            yaml.dump(config, f)

        with pytest.raises(ConfigValidationError, match="value too long"):
            config_loader.load_agent("long_value")

        # Cleanup
        del os.environ["LONG_VALUE"]

    def test_safe_command_value_accepted(self, config_loader, temp_config_dir):
        """Test safe command values are accepted."""
        os.environ["SAFE_CMD"] = "echo hello world"

        config = {
            "tool": {
                "command": "${SAFE_CMD}",
            }
        }

        tool_path = temp_config_dir / "tools" / "safe_cmd.yaml"
        with open(tool_path, 'w') as f:
            yaml.dump(config, f)

        # Should not raise (skip schema validation, only test env var validation)
        loaded = config_loader.load_tool("safe_cmd", validate=False)
        assert loaded["tool"]["command"] == "echo hello world"

        # Cleanup
        del os.environ["SAFE_CMD"]

    def test_safe_url_without_credentials_accepted(self, config_loader, temp_config_dir):
        """Test URLs without embedded credentials are accepted."""
        os.environ["SAFE_URL"] = "https://api.example.com/endpoint"

        config = {
            "agent": {
                "api_url": "${SAFE_URL}",
            }
        }

        agent_path = temp_config_dir / "agents" / "safe_url.yaml"
        with open(agent_path, 'w') as f:
            yaml.dump(config, f)

        # Should not raise (skip schema validation, only test env var validation)
        loaded = config_loader.load_agent("safe_url", validate=False)
        assert loaded["agent"]["api_url"] == "https://api.example.com/endpoint"

        # Cleanup
        del os.environ["SAFE_URL"]

    def test_safe_db_value_accepted(self, config_loader, temp_config_dir):
        """Test safe database values are accepted."""
        os.environ["DB_NAME"] = "production_db"

        config = {
            "agent": {
                "database_name": "${DB_NAME}",
            }
        }

        agent_path = temp_config_dir / "agents" / "safe_db.yaml"
        with open(agent_path, 'w') as f:
            yaml.dump(config, f)

        # Should not raise (skip schema validation, only test env var validation)
        loaded = config_loader.load_agent("safe_db", validate=False)
        assert loaded["agent"]["database_name"] == "production_db"

        # Cleanup
        del os.environ["DB_NAME"]
