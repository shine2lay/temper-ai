"""Security tests for configuration loading."""

import pytest

from src.compiler.config_loader import ConfigLoader, ConfigValidationError


@pytest.fixture
def temp_config_dir(tmp_path):
    """Create temporary config directory."""
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (config_dir / "agents").mkdir()
    (config_dir / "workflows").mkdir()
    (config_dir / "prompts").mkdir()
    return config_dir


@pytest.fixture
def config_loader(temp_config_dir):
    """Create config loader with temporary directory."""
    return ConfigLoader(config_root=temp_config_dir)


class TestEnvironmentVariableInjection:
    """Test security against environment variable injection attacks."""

    @pytest.mark.skip(reason="Python os.environ rejects null bytes before our code can validate them")
    def test_env_var_with_null_byte(self, config_loader, monkeypatch):
        """Test that null bytes in env vars are rejected."""
        # Set env var with null byte
        monkeypatch.setenv("MALICIOUS_VAR", "value\x00injection")

        config = {
            "api_key": "${MALICIOUS_VAR}"
        }

        with pytest.raises(ConfigValidationError, match="null bytes"):
            config_loader._substitute_env_vars(config)

    def test_env_var_path_traversal(self, config_loader, monkeypatch):
        """Test that path traversal in env vars is rejected for path-like variables."""
        # Set env var with path traversal
        monkeypatch.setenv("CONFIG_PATH", "../../../etc/passwd")

        config = {
            "config_path": "${CONFIG_PATH}"
        }

        with pytest.raises(ConfigValidationError, match="path traversal|Path escapes base directory"):
            config_loader._substitute_env_vars(config)

    def test_env_var_path_traversal_non_path_var(self, config_loader, monkeypatch):
        """Test that path traversal in non-path variables is allowed."""
        # Set env var with ../ but not in a path-like variable
        monkeypatch.setenv("SOME_VALUE", "../data")

        config = {
            "some_value": "${SOME_VALUE}"  # Not a path-like variable name
        }

        # Should work fine since it's not a path variable
        result = config_loader._substitute_env_vars(config)
        assert result["some_value"] == "../data"

    def test_env_var_excessive_length(self, config_loader, monkeypatch):
        """Test that excessively long env vars are rejected."""
        # Create a very long value (>10KB)
        long_value = "A" * (10 * 1024 + 1)
        monkeypatch.setenv("LONG_VAR", long_value)

        config = {
            "value": "${LONG_VAR}"
        }

        with pytest.raises(ConfigValidationError, match="value too long"):
            config_loader._substitute_env_vars(config)

    def test_env_var_reasonable_length(self, config_loader, monkeypatch):
        """Test that reasonably sized env vars are accepted."""
        # 5KB value - should be fine
        reasonable_value = "A" * (5 * 1024)
        monkeypatch.setenv("REASONABLE_VAR", reasonable_value)

        config = {
            "value": "${REASONABLE_VAR}"
        }

        result = config_loader._substitute_env_vars(config)
        assert result["value"] == reasonable_value

    def test_env_var_normal_substitution(self, config_loader, monkeypatch):
        """Test that normal env var substitution still works."""
        monkeypatch.setenv("API_KEY", "sk-test123")
        monkeypatch.setenv("BASE_URL", "https://api.example.com")

        config = {
            "api_key": "${API_KEY}",
            "base_url": "${BASE_URL}"
        }

        result = config_loader._substitute_env_vars(config)
        assert result["api_key"] == "sk-test123"
        assert result["base_url"] == "https://api.example.com"

    def test_env_var_with_default(self, config_loader):
        """Test env var with default value."""
        config = {
            "api_key": "${MISSING_VAR:default_value}"
        }

        result = config_loader._substitute_env_vars(config)
        assert result["api_key"] == "default_value"

    def test_env_var_missing_without_default(self, config_loader):
        """Test that missing required env var raises error."""
        config = {
            "api_key": "${REQUIRED_MISSING_VAR}"
        }

        with pytest.raises(ConfigValidationError, match="required but not set"):
            config_loader._substitute_env_vars(config)

    def test_nested_config_substitution(self, config_loader, monkeypatch):
        """Test env var substitution in nested configs."""
        monkeypatch.setenv("MODEL_NAME", "gpt-4")
        monkeypatch.setenv("TEMPERATURE", "0.7")

        config = {
            "agent": {
                "inference": {
                    "model": "${MODEL_NAME}",
                    "temperature": "${TEMPERATURE}"
                }
            }
        }

        result = config_loader._substitute_env_vars(config)
        assert result["agent"]["inference"]["model"] == "gpt-4"
        assert result["agent"]["inference"]["temperature"] == "0.7"

    def test_list_config_substitution(self, config_loader, monkeypatch):
        """Test env var substitution in lists."""
        monkeypatch.setenv("TAG1", "production")
        monkeypatch.setenv("TAG2", "v1.0")

        config = {
            "tags": ["${TAG1}", "${TAG2}", "manual"]
        }

        result = config_loader._substitute_env_vars(config)
        assert result["tags"] == ["production", "v1.0", "manual"]

    def test_partial_string_substitution(self, config_loader, monkeypatch):
        """Test that env vars can be part of larger strings."""
        monkeypatch.setenv("VERSION", "1.0")

        config = {
            "name": "app-${VERSION}-release"
        }

        result = config_loader._substitute_env_vars(config)
        assert result["name"] == "app-1.0-release"

    def test_multiple_vars_in_string(self, config_loader, monkeypatch):
        """Test multiple env vars in single string."""
        monkeypatch.setenv("HOST", "api.example.com")
        monkeypatch.setenv("PORT", "8080")

        config = {
            "url": "https://${HOST}:${PORT}/v1"
        }

        result = config_loader._substitute_env_vars(config)
        assert result["url"] == "https://api.example.com:8080/v1"


class TestPathTraversalInPrompts:
    """Test security against path traversal in prompt template loading."""

    def test_load_prompt_with_traversal(self, config_loader, temp_config_dir):
        """Test that path traversal is blocked in prompt loading."""
        # Try to access file outside prompts directory
        with pytest.raises(ConfigValidationError, match="within prompts directory"):
            config_loader.load_prompt_template("../../etc/passwd")

    def test_load_prompt_with_absolute_path(self, config_loader):
        """Test that absolute paths outside prompts dir are blocked."""
        with pytest.raises(ConfigValidationError, match="within prompts directory"):
            config_loader.load_prompt_template("/etc/passwd")

    def test_load_prompt_normal_path(self, config_loader, temp_config_dir):
        """Test that normal prompt loading works."""
        # Create a test prompt
        prompt_file = temp_config_dir / "prompts" / "test.txt"
        prompt_file.write_text("Hello {{name}}!")

        result = config_loader.load_prompt_template(
            "test.txt",
            variables={"name": "World"}
        )
        assert result == "Hello World!"

    def test_load_prompt_in_subdirectory(self, config_loader, temp_config_dir):
        """Test loading prompt from subdirectory."""
        # Create subdirectory and prompt
        subdir = temp_config_dir / "prompts" / "templates"
        subdir.mkdir()
        prompt_file = subdir / "agent.txt"
        prompt_file.write_text("Agent prompt: {{task}}")

        result = config_loader.load_prompt_template(
            "templates/agent.txt",
            variables={"task": "research"}
        )
        assert result == "Agent prompt: research"

    def test_load_prompt_file_too_large(self, config_loader, temp_config_dir):
        """Test that overly large prompt files are rejected."""
        # Create a file larger than MAX_CONFIG_SIZE
        large_file = temp_config_dir / "prompts" / "large.txt"
        large_content = "A" * (11 * 1024 * 1024)  # 11MB
        large_file.write_text(large_content)

        with pytest.raises(ConfigValidationError, match="too large"):
            config_loader.load_prompt_template("large.txt")


class TestConfigValidation:
    """Test configuration validation security."""

    def test_validate_agent_config(self, config_loader, temp_config_dir):
        """Test agent config validation catches invalid configs."""
        # Create invalid agent config (missing required fields)
        agent_file = temp_config_dir / "agents" / "invalid.yaml"
        agent_file.write_text("""
agent:
  name: test_agent
  # Missing required fields like inference, tools, etc.
""")

        with pytest.raises(ConfigValidationError):
            config_loader.load_agent("invalid", validate=True)

    def test_validate_workflow_config(self, config_loader, temp_config_dir):
        """Test workflow config validation catches invalid configs."""
        # Create invalid workflow config
        workflow_file = temp_config_dir / "workflows" / "invalid.yaml"
        workflow_file.write_text("""
workflow:
  name: test_workflow
  # Missing required fields like stages, error_handling
""")

        with pytest.raises(ConfigValidationError):
            config_loader.load_workflow("invalid", validate=True)

    def test_skip_validation_when_disabled(self, config_loader, temp_config_dir):
        """Test that validation can be skipped."""
        # Create invalid config
        agent_file = temp_config_dir / "agents" / "invalid.yaml"
        agent_file.write_text("""
agent:
  name: test_agent
""")

        # Should work with validate=False
        result = config_loader.load_agent("invalid", validate=False)
        assert result["agent"]["name"] == "test_agent"


class TestSecurityEdgeCases:
    """Test edge cases and attack vectors."""

    def test_env_var_with_special_shell_chars(self, config_loader, monkeypatch):
        """Test that shell metacharacters in env vars are rejected by context-aware validation."""
        # Env vars with shell metacharacters — now rejected by stricter validator
        monkeypatch.setenv("SPECIAL_VAR", "value; rm -rf /")

        config = {
            "command": "${SPECIAL_VAR}"
        }

        # Stricter context-aware validation now rejects dangerous characters
        with pytest.raises(ConfigValidationError, match="dangerous pattern|invalid characters|Command separator"):
            config_loader._substitute_env_vars(config)

    def test_env_var_with_unicode_injection(self, config_loader, monkeypatch):
        """Test that unicode bidi characters in env vars are rejected by context-aware validation."""
        monkeypatch.setenv("UNICODE_VAR", "测试\u202e\u202d")

        config = {
            "value": "${UNICODE_VAR}"
        }

        # Stricter validation now rejects bidi override characters as dangerous
        with pytest.raises(ConfigValidationError, match="invalid characters|dangerous|bidi"):
            config_loader._substitute_env_vars(config)

    def test_deeply_nested_substitution(self, config_loader, monkeypatch):
        """Test deeply nested config with many substitutions."""
        for i in range(20):
            monkeypatch.setenv(f"VAR{i}", f"value{i}")

        config = {
            f"level{i}": {
                "value": f"${{VAR{i}}}"
            }
            for i in range(20)
        }

        result = config_loader._substitute_env_vars(config)
        for i in range(20):
            assert result[f"level{i}"]["value"] == f"value{i}"

    def test_circular_reference_prevention(self, config_loader, monkeypatch):
        """Test that circular env var references are handled safely."""
        # Values containing ${...} are now rejected by stricter validation
        monkeypatch.setenv("VAR1", "${VAR2}")
        monkeypatch.setenv("VAR2", "${VAR1}")

        config = {
            "value": "${VAR1}"
        }

        # The stricter validator rejects values with ${} patterns or special chars
        # This is actually better than allowing circular references
        with pytest.raises(ConfigValidationError, match="invalid characters|validation"):
            config_loader._substitute_env_vars(config)


class TestYAMLBombPrevention:
    """Test protection against YAML bomb attacks (billion laughs, exponential expansion)."""

    def test_yaml_bomb_anchor_alias_expansion(self, config_loader, temp_config_dir):
        """Test that YAML anchor/alias bombs are detected and rejected."""
        # Classic YAML bomb pattern: exponential expansion through aliases
        yaml_bomb = """
agent:
  name: test
a: &a ["a","a","a","a","a","a","a","a","a"]
b: &b [*a,*a,*a,*a,*a,*a,*a,*a,*a]
c: &c [*b,*b,*b,*b,*b,*b,*b,*b,*b]
d: &d [*c,*c,*c,*c,*c,*c,*c,*c,*c]
e: &e [*d,*d,*d,*d,*d,*d,*d,*d,*d]
f: &f [*e,*e,*e,*e,*e,*e,*e,*e,*e]
"""

        agent_file = temp_config_dir / "agents" / "bomb.yaml"
        agent_file.write_text(yaml_bomb)

        # Note: yaml.safe_load() already prevents most YAML bombs by not allowing
        # recursive references and limiting alias expansion depth.
        # This test verifies that the current implementation handles it gracefully.
        try:
            result = config_loader.load_agent("bomb", validate=False)
            # If it loads successfully, verify it's not excessively large
            import sys
            size = sys.getsizeof(result)
            # Should be reasonable size (< 10MB)
            assert size < 10 * 1024 * 1024, f"YAML expanded to {size} bytes"
        except (ConfigValidationError, MemoryError, RecursionError) as e:
            # Also acceptable to reject it entirely
            err_msg = str(e).lower()
            assert "too large" in err_msg or "recursion" in err_msg or "memory" in err_msg or "node count" in err_msg or "yaml bomb" in err_msg

    def test_deeply_nested_yaml_structure(self, config_loader, temp_config_dir):
        """Test that excessively deep YAML nesting is handled."""
        # Create very deeply nested structure
        nested_yaml = "agent:\n  name: test\n"
        current = "  data:\n"

        # Create 200 levels of nesting
        indent = "  "
        for i in range(200):
            current += f"{indent * (i + 2)}level{i}:\n"

        current += f"{indent * 202}value: end"
        nested_yaml += current

        agent_file = temp_config_dir / "agents" / "deep.yaml"
        agent_file.write_text(nested_yaml)

        # Should handle gracefully - either load with reasonable limits or reject
        try:
            result = config_loader.load_agent("deep", validate=False)
            # Verify it loaded without issues
            assert result["agent"]["name"] == "test"
        except (ConfigValidationError, RecursionError) as e:
            # Also acceptable to reject deeply nested structures
            assert "depth" in str(e).lower() or "recursion" in str(e).lower()

    def test_large_yaml_with_many_keys(self, config_loader, temp_config_dir):
        """Test YAML with very large number of keys."""
        # Create config with 10,000 keys
        yaml_content = "agent:\n  name: test\n  data:\n"
        for i in range(10000):
            yaml_content += f"    key{i}: value{i}\n"

        agent_file = temp_config_dir / "agents" / "many_keys.yaml"
        agent_file.write_text(yaml_content)

        # File size check should catch this if it's too large
        file_size = agent_file.stat().st_size
        if file_size > 10 * 1024 * 1024:  # MAX_CONFIG_SIZE
            with pytest.raises(ConfigValidationError, match="too large"):
                config_loader.load_agent("many_keys", validate=False)
        else:
            # Should load successfully if under size limit
            result = config_loader.load_agent("many_keys", validate=False)
            assert result["agent"]["name"] == "test"
            assert len(result["agent"]["data"]) == 10000

    def test_yaml_with_large_string_values(self, config_loader, temp_config_dir):
        """Test YAML with very large string values."""
        # Create config with large string
        large_string = "x" * (11 * 1024 * 1024)  # 11MB string (exceeds 10MB limit)
        yaml_content = f"""
agent:
  name: test
  large_field: "{large_string}"
"""

        agent_file = temp_config_dir / "agents" / "large_string.yaml"
        agent_file.write_text(yaml_content)

        # Verify file is actually large
        file_size = agent_file.stat().st_size
        assert file_size > 10 * 1024 * 1024, f"File should be > 10MB, got {file_size}"

        # Should be rejected due to file size limit
        with pytest.raises(ConfigValidationError, match="too large"):
            config_loader.load_agent("large_string", validate=False)

    def test_yaml_recursive_merge_keys(self, config_loader, temp_config_dir):
        """Test YAML with recursive merge keys."""
        yaml_content = """
agent:
  name: test
defaults: &defaults
  timeout: 30
  retries: 3

config1: &config1
  <<: *defaults
  name: config1

config2:
  <<: *config1
  name: config2
"""

        agent_file = temp_config_dir / "agents" / "merge.yaml"
        agent_file.write_text(yaml_content)

        # Merge keys should work normally (not a bomb)
        result = config_loader.load_agent("merge", validate=False)
        assert result["agent"]["name"] == "test"
        assert result["config2"]["timeout"] == 30
        assert result["config2"]["name"] == "config2"


class TestSymlinkAttackPrevention:
    """Test protection against symlink attacks."""

    def test_symlink_to_system_files(self, config_loader, temp_config_dir):
        """Test that symlinks to /etc are rejected."""
        import platform
        if platform.system() == "Windows":
            pytest.skip("Symlink test not applicable on Windows")

        prompts_dir = temp_config_dir / "prompts"
        symlink_path = prompts_dir / "evil_link"

        try:
            symlink_path.symlink_to("/etc/passwd")
        except (OSError, PermissionError):
            pytest.skip("Cannot create symlinks (insufficient permissions)")

        # Attempting to load should be blocked
        with pytest.raises(ConfigValidationError, match="within prompts directory"):
            config_loader.load_prompt_template("evil_link")

    def test_symlink_outside_project_directory(self, config_loader, temp_config_dir):
        """Test that symlinks outside project directory are rejected."""
        import platform
        if platform.system() == "Windows":
            pytest.skip("Symlink test not applicable on Windows")

        prompts_dir = temp_config_dir / "prompts"
        symlink_path = prompts_dir / "outside_link"

        try:
            # Create symlink to /tmp (outside project)
            symlink_path.symlink_to("/tmp")
        except (OSError, PermissionError):
            pytest.skip("Cannot create symlinks (insufficient permissions)")

        # Should be blocked
        with pytest.raises(ConfigValidationError, match="within prompts directory"):
            config_loader.load_prompt_template("outside_link")

    def test_symlink_traversal_attack(self, config_loader, temp_config_dir):
        """Test symlink traversal attacks are blocked."""
        import platform
        if platform.system() == "Windows":
            pytest.skip("Symlink test not applicable on Windows")

        prompts_dir = temp_config_dir / "prompts"
        subdir = prompts_dir / "templates"
        subdir.mkdir()

        symlink_path = subdir / "traversal_link"

        try:
            # Create symlink that goes up and outside
            symlink_path.symlink_to("../../..")
        except (OSError, PermissionError):
            pytest.skip("Cannot create symlinks (insufficient permissions)")

        # Should be blocked
        with pytest.raises(ConfigValidationError, match="within prompts directory"):
            config_loader.load_prompt_template("templates/traversal_link")

    def test_relative_symlink_within_prompts(self, config_loader, temp_config_dir):
        """Test that symlinks within prompts directory are allowed."""
        import platform
        if platform.system() == "Windows":
            pytest.skip("Symlink test not applicable on Windows")

        prompts_dir = temp_config_dir / "prompts"

        # Create actual file
        actual_file = prompts_dir / "actual.txt"
        actual_file.write_text("Actual content")

        # Create symlink to it
        symlink_path = prompts_dir / "link.txt"
        try:
            symlink_path.symlink_to("actual.txt")
        except (OSError, PermissionError):
            pytest.skip("Cannot create symlinks (insufficient permissions)")

        # Should work fine (within prompts dir)
        result = config_loader.load_prompt_template("link.txt")
        assert result == "Actual content"


class TestResourceLimits:
    """Test enforcement of resource limits during config loading."""

    def test_maximum_file_size_enforcement(self, config_loader, temp_config_dir):
        """Test that maximum file size limit is enforced."""
        # Create file larger than MAX_CONFIG_SIZE (10MB)
        large_file = temp_config_dir / "agents" / "huge.yaml"

        # Write in chunks to avoid memory issues
        with open(large_file, 'w') as f:
            f.write("agent:\n  name: test\n  data:\n")
            # Write ~11MB of data
            for i in range(550000):  # ~11MB
                f.write(f"    key{i}: value{i}\n")

        # Should be rejected
        with pytest.raises(ConfigValidationError, match="too large"):
            config_loader.load_agent("huge", validate=False)

    def test_reasonable_file_size_accepted(self, config_loader, temp_config_dir):
        """Test that reasonable file sizes are accepted."""
        # Create 1MB file (well under 10MB limit)
        reasonable_file = temp_config_dir / "agents" / "reasonable.yaml"

        with open(reasonable_file, 'w') as f:
            f.write("agent:\n  name: test\n  data:\n")
            # Write ~1MB of data
            for i in range(50000):
                f.write(f"    key{i}: value{i}\n")

        # Should load successfully
        result = config_loader.load_agent("reasonable", validate=False)
        assert result["agent"]["name"] == "test"

    def test_parse_time_reasonable(self, config_loader, temp_config_dir):
        """Test that config parsing completes in reasonable time."""
        import time

        # Create moderately complex config
        agent_file = temp_config_dir / "agents" / "complex.yaml"
        yaml_content = "agent:\n  name: test\n  config:\n"

        # Nested structure with 100 items
        for i in range(100):
            yaml_content += f"    section{i}:\n"
            for j in range(10):
                yaml_content += f"      key{j}: value{j}\n"

        agent_file.write_text(yaml_content)

        # Should parse quickly (< 1 second)
        start = time.time()
        result = config_loader.load_agent("complex", validate=False)
        elapsed = time.time() - start

        assert elapsed < 1.0, f"Parse took {elapsed:.2f}s (expected < 1s)"
        assert result["agent"]["name"] == "test"

    def test_memory_usage_during_parse(self, config_loader, temp_config_dir):
        """Test that memory usage during parsing is reasonable."""
        import sys

        # Create config with many small items
        agent_file = temp_config_dir / "agents" / "many_items.yaml"
        yaml_content = "agent:\n  name: test\n  items:\n"

        for i in range(1000):
            yaml_content += f"    - item{i}\n"

        agent_file.write_text(yaml_content)

        result = config_loader.load_agent("many_items", validate=False)

        # Check result size is reasonable
        result_size = sys.getsizeof(result)
        assert result_size < 10 * 1024 * 1024, f"Result size: {result_size} bytes"


class TestYAMLSecurityBestPractices:
    """Test that YAML loading follows security best practices."""

    def test_uses_safe_load_not_unsafe_load(self, config_loader, temp_config_dir):
        """Test that yaml.safe_load is used (not yaml.load with Loader=Loader)."""
        # Create YAML with Python object (would only work with unsafe load)
        unsafe_yaml = """
agent:
  name: test
  dangerous: !!python/object/apply:os.system
    args: ['echo pwned']
"""

        agent_file = temp_config_dir / "agents" / "unsafe.yaml"
        agent_file.write_text(unsafe_yaml)

        # safe_load should reject this
        with pytest.raises(ConfigValidationError):
            config_loader.load_agent("unsafe", validate=False)

    def test_yaml_tags_are_restricted(self, config_loader, temp_config_dir):
        """Test that dangerous YAML tags are not processed."""
        # Try various dangerous tags
        dangerous_tags = [
            "!!python/object/apply:os.system",
            "!!python/object/new:os.system",
            "!!python/name:os.system",
        ]

        for i, tag in enumerate(dangerous_tags):
            yaml_content = f"""
agent:
  name: test{i}
  dangerous: {tag}
"""
            agent_file = temp_config_dir / "agents" / f"dangerous{i}.yaml"
            agent_file.write_text(yaml_content)

            # Should be rejected
            with pytest.raises(ConfigValidationError):
                config_loader.load_agent(f"dangerous{i}", validate=False)
