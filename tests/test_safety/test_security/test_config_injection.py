"""
Security tests for YAML bombs and configuration injection attacks.

Tests YAML bomb (billion laughs) detection, environment variable injection,
config file size limits, excessive nesting depth, and circular references.
"""

import os
import tempfile
from pathlib import Path

import pytest

from temper_ai.shared.utils.exceptions import ConfigValidationError
from temper_ai.workflow.config_loader import ConfigLoader


class TestYAMLBombPrevention:
    """Test YAML bomb (billion laughs attack) detection."""

    def test_yaml_bomb_billion_laughs(self):
        """
        Test that billion laughs YAML bomb is detected and blocked.

        The billion laughs attack uses recursive entity expansion to exhaust memory:
        - Define entities that reference themselves recursively
        - Each level multiplies the expansion exponentially
        - 10 levels = 2^10 = 1024x expansion
        - Can easily exhaust gigabytes of memory
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            config_root = Path(tmpdir) / "configs"
            agents_dir = config_root / "agents"
            agents_dir.mkdir(parents=True)

            # Classic billion laughs attack using YAML anchors and aliases
            yaml_bomb = """
a: &a ["lol", "lol", "lol", "lol", "lol", "lol", "lol", "lol", "lol"]
b: &b [*a, *a, *a, *a, *a, *a, *a, *a, *a]
c: &c [*b, *b, *b, *b, *b, *b, *b, *b, *b]
d: &d [*c, *c, *c, *c, *c, *c, *c, *c, *c]
e: &e [*d, *d, *d, *d, *d, *d, *d, *d, *d]
f: &f [*e, *e, *e, *e, *e, *e, *e, *e, *e]
g: &g [*f, *f, *f, *f, *f, *f, *f, *f, *f]
h: &h [*g, *g, *g, *g, *g, *g, *g, *g, *g]
i: &i [*h, *h, *h, *h, *h, *h, *h, *h, *h]
j: &j [*i, *i, *i, *i, *i, *i, *i, *i, *i]
"""
            config_file = agents_dir / "malicious.yaml"
            config_file.write_text(yaml_bomb)

            loader = ConfigLoader(config_root=config_root)

            # Should detect and block the YAML bomb
            with pytest.raises(ConfigValidationError) as exc_info:
                loader.load_agent("malicious")

            error_msg = str(exc_info.value).lower()
            # Error should mention either "parsing failed", "recursion", "memory", or "complexity"
            assert any(
                keyword in error_msg
                for keyword in [
                    "parse",
                    "parsing",
                    "failed",
                    "recursion",
                    "memory",
                    "complexity",
                    "too large",
                ]
            ), f"Expected YAML bomb error, got: {exc_info.value}"

    def test_yaml_bomb_with_merge_keys(self):
        """
        Test YAML bomb using merge keys (<<:).

        This variant uses YAML merge keys to create exponential expansion.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            config_root = Path(tmpdir) / "configs"
            agents_dir = config_root / "agents"
            agents_dir.mkdir(parents=True)

            # YAML bomb using merge keys
            yaml_bomb = """
defaults: &defaults
  a: &a ["x", "x", "x", "x", "x", "x", "x", "x", "x", "x"]
  b: &b [*a, *a, *a, *a, *a, *a, *a, *a, *a, *a]
  c: &c [*b, *b, *b, *b, *b, *b, *b, *b, *b, *b]
  d: &d [*c, *c, *c, *c, *c, *c, *c, *c, *c, *c]

config:
  <<: *defaults
  e: *d
"""
            config_file = agents_dir / "malicious_merge.yaml"
            config_file.write_text(yaml_bomb)

            loader = ConfigLoader(config_root=config_root)

            # Should detect and block the YAML bomb
            with pytest.raises(ConfigValidationError) as exc_info:
                loader.load_agent("malicious_merge")

            error_msg = str(exc_info.value).lower()
            assert any(
                keyword in error_msg
                for keyword in [
                    "parse",
                    "parsing",
                    "failed",
                    "recursion",
                    "memory",
                    "complexity",
                    "too large",
                ]
            ), f"Expected YAML bomb error, got: {exc_info.value}"


class TestEnvironmentVariableInjection:
    """Test environment variable injection prevention."""

    def test_env_var_shell_injection(self):
        """
        Test that shell metacharacters in env var defaults are blocked.

        Prevents command injection via environment variables like:
        ${COMMAND:ls; rm -rf /}
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            config_root = Path(tmpdir) / "configs"
            agents_dir = config_root / "agents"
            agents_dir.mkdir(parents=True)

            # Config with shell injection in env var
            malicious_config = {
                "name": "test_agent",
                "version": "1.0",
                "llm": {"provider": "openai", "model": "gpt-4"},
                "command": "${SHELL_CMD:ls; rm -rf /}",
            }

            import yaml

            config_file = agents_dir / "shell_injection.yaml"
            config_file.write_text(yaml.dump(malicious_config))

            # Set malicious environment variable
            os.environ["SHELL_CMD"] = "ls; rm -rf /"

            try:
                loader = ConfigLoader(config_root=config_root)

                # Should detect shell metacharacters in command-like env var
                with pytest.raises(ConfigValidationError) as exc_info:
                    loader.load_agent("shell_injection", validate=False)

                error_msg = str(exc_info.value).lower()
                assert any(
                    keyword in error_msg
                    for keyword in [
                        "shell metacharacters",
                        "command injection",
                        "dangerous pattern",
                        "command separator",
                    ]
                ), f"Expected shell injection error, got: {exc_info.value}"

            finally:
                # Cleanup
                os.environ.pop("SHELL_CMD", None)

    def test_env_var_path_traversal(self):
        """
        Test that path traversal in env vars is blocked.

        Prevents directory traversal via environment variables like:
        ${CONFIG_PATH:../../etc/passwd}
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            config_root = Path(tmpdir) / "configs"
            agents_dir = config_root / "agents"
            agents_dir.mkdir(parents=True)

            # Config with path traversal in env var
            malicious_config = {
                "name": "test_agent",
                "version": "1.0",
                "llm": {"provider": "openai", "model": "gpt-4"},
                "config_path": "${CONFIG_PATH}",
            }

            import yaml

            config_file = agents_dir / "path_traversal.yaml"
            config_file.write_text(yaml.dump(malicious_config))

            # Set malicious environment variable with path traversal
            os.environ["CONFIG_PATH"] = "../../../etc/passwd"

            try:
                loader = ConfigLoader(config_root=config_root)

                # Should detect path traversal pattern
                with pytest.raises(ConfigValidationError) as exc_info:
                    loader.load_agent("path_traversal", validate=False)

                error_msg = str(exc_info.value).lower()
                assert any(
                    keyword in error_msg
                    for keyword in [
                        "path traversal",
                        "escapes base directory",
                        "path validation",
                    ]
                ), f"Expected path traversal error, got: {exc_info.value}"

            finally:
                # Cleanup
                os.environ.pop("CONFIG_PATH", None)

    def test_env_var_sql_injection(self):
        """
        Test that SQL injection patterns in env vars are blocked.

        Prevents SQL injection via environment variables like:
        ${DB_QUERY:' OR '1'='1}
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            config_root = Path(tmpdir) / "configs"
            agents_dir = config_root / "agents"
            agents_dir.mkdir(parents=True)

            # Config with SQL injection in env var
            malicious_config = {
                "name": "test_agent",
                "version": "1.0",
                "llm": {"provider": "openai", "model": "gpt-4"},
                "db_table": "${DB_TABLE}",
            }

            import yaml

            config_file = agents_dir / "sql_injection.yaml"
            config_file.write_text(yaml.dump(malicious_config))

            # Set malicious environment variable with SQL injection
            os.environ["DB_TABLE"] = "users'; DROP TABLE users;--"

            try:
                loader = ConfigLoader(config_root=config_root)

                # Should detect SQL injection pattern
                with pytest.raises(ConfigValidationError) as exc_info:
                    loader.load_agent("sql_injection", validate=False)

                error_msg = str(exc_info.value).lower()
                assert (
                    "sql injection" in error_msg or "sql" in error_msg
                ), f"Expected SQL injection error, got: {exc_info.value}"

            finally:
                # Cleanup
                os.environ.pop("DB_TABLE", None)

    def test_env_var_null_byte_injection(self):
        """
        Test that null bytes in env vars are blocked.

        Null bytes can truncate strings and bypass security checks.
        Note: Python's os.environ doesn't allow null bytes, so we test by
        creating a YAML file that contains a null byte in a value that
        will be expanded.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            config_root = Path(tmpdir) / "configs"
            agents_dir = config_root / "agents"
            agents_dir.mkdir(parents=True)

            # Write a YAML file with a null byte embedded in a value
            # that references an environment variable
            config_file = agents_dir / "null_byte.yaml"

            # Create config with default value containing null byte
            # ${FILE_PATH:safe.txt\x00../../etc/passwd}
            config_content = "name: test_agent\nversion: 1.0\nllm:\n  provider: openai\n  model: gpt-4\nfile_path: ${FILE_PATH:safe.txt\x00../../etc/passwd}\n"

            # Write the config with null byte
            with open(config_file, "wb") as f:
                f.write(config_content.encode("utf-8"))

            loader = ConfigLoader(config_root=config_root)

            # Should detect null bytes (either in YAML parsing or during validation)
            with pytest.raises(ConfigValidationError) as exc_info:
                loader.load_agent("null_byte", validate=False)

            error_msg = str(exc_info.value).lower()
            # Accept either "null byte" or YAML's "#x0000" error
            assert (
                "null byte" in error_msg
                or "#x0000" in error_msg
                or "special characters" in error_msg
            ), f"Expected null byte error, got: {exc_info.value}"


class TestConfigSizeLimits:
    """Test config file size limits."""

    def test_config_size_limit(self):
        """
        Test that config files larger than 10MB are rejected.

        Prevents memory exhaustion from maliciously large config files.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            config_root = Path(tmpdir) / "configs"
            agents_dir = config_root / "agents"
            agents_dir.mkdir(parents=True)

            # Create an 11MB config file (exceeds 10MB limit)
            config_file = agents_dir / "huge.yaml"

            # Write 11MB of YAML data
            # Each line is ~100 bytes, so 110,000 lines = ~11MB
            with open(config_file, "w") as f:
                f.write("name: test_agent\n")
                f.write("version: 1.0\n")
                f.write("llm:\n")
                f.write("  provider: openai\n")
                f.write("  model: gpt-4\n")
                f.write("data:\n")
                for i in range(110000):
                    # Each entry is ~100 bytes
                    f.write(f"  - item_{i}: {'x' * 80}\n")

            loader = ConfigLoader(config_root=config_root)

            # Should reject file larger than 10MB
            with pytest.raises(ConfigValidationError) as exc_info:
                loader.load_agent("huge", validate=False)

            error_msg = str(exc_info.value).lower()
            assert (
                "too large" in error_msg or "size" in error_msg
            ), f"Expected size limit error, got: {exc_info.value}"

    def test_config_size_boundary(self):
        """
        Test that config files exactly at 10MB are accepted.

        Verifies the boundary condition. Uses large string values to reach 10MB
        without exceeding the node count limit (100k nodes).
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            config_root = Path(tmpdir) / "configs"
            agents_dir = config_root / "agents"
            agents_dir.mkdir(parents=True)

            # Create a config file at exactly 10MB
            config_file = agents_dir / "at_limit.yaml"

            # Calculate how much data to write to reach 10MB
            target_size = 10 * 1024 * 1024  # 10MB
            header = "name: test_agent\nversion: 1.0\nllm:\n  provider: openai\n  model: gpt-4\ndata:\n"
            len(header.encode("utf-8"))

            # Use fewer nodes with larger values to stay under 100k node limit
            # Each line is ~1KB (1000 bytes), so 10,000 lines = ~10MB
            # This keeps us well under the 100k node limit
            line_template = "  - item_{}: {}\n"
            large_value = "x" * 950  # ~950 bytes per value

            with open(config_file, "w") as f:
                f.write(header)

                # Write 10,000 large items to reach ~10MB
                for i in range(10000):
                    line = line_template.format(i, large_value)
                    f.write(line)

                    # Stop when we reach target size
                    current_size = f.tell()
                    if current_size >= target_size:
                        break

            loader = ConfigLoader(config_root=config_root)

            # Should accept file at exactly 10MB
            config = loader.load_agent("at_limit", validate=False)
            assert config["name"] == "test_agent"


class TestExcessiveNestingDepth:
    """Test excessive nesting depth detection."""

    def test_excessive_nesting_depth(self):
        """
        Test that configs with >50 levels of nesting are rejected.

        Prevents stack overflow and memory exhaustion from deeply nested configs.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            config_root = Path(tmpdir) / "configs"
            agents_dir = config_root / "agents"
            agents_dir.mkdir(parents=True)

            # Create config with 100 levels of nesting
            nested_config = "name: test_agent\nversion: 1.0\nllm:\n  provider: openai\n  model: gpt-4\n"
            nested_config += "deeply_nested:\n"

            # Build 100 levels of nesting
            indent = "  "
            for i in range(100):
                nested_config += f"{indent * (i + 1)}level_{i}:\n"
            nested_config += f"{indent * 101}value: deep\n"

            config_file = agents_dir / "deep.yaml"
            config_file.write_text(nested_config)

            loader = ConfigLoader(config_root=config_root)

            # Should detect excessive nesting depth
            with pytest.raises(ConfigValidationError) as exc_info:
                loader.load_agent("deep", validate=False)

            error_msg = str(exc_info.value).lower()
            assert any(
                keyword in error_msg
                for keyword in [
                    "nesting",
                    "depth",
                    "deep",
                    "recursion",
                    "parse",
                    "parsing",
                    "failed",
                ]
            ), f"Expected nesting depth error, got: {exc_info.value}"

    def test_acceptable_nesting_depth(self):
        """
        Test that configs with reasonable nesting depth (10 levels) are accepted.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            config_root = Path(tmpdir) / "configs"
            agents_dir = config_root / "agents"
            agents_dir.mkdir(parents=True)

            # Create config with 10 levels of nesting (acceptable)
            nested_config = "name: test_agent\nversion: 1.0\nllm:\n  provider: openai\n  model: gpt-4\n"
            nested_config += "nested:\n"

            indent = "  "
            for i in range(10):
                nested_config += f"{indent * (i + 1)}level_{i}:\n"
            nested_config += f"{indent * 11}value: acceptable\n"

            config_file = agents_dir / "shallow.yaml"
            config_file.write_text(nested_config)

            loader = ConfigLoader(config_root=config_root)

            # Should accept reasonable nesting depth
            config = loader.load_agent("shallow", validate=False)
            assert config["name"] == "test_agent"


class TestCircularReferences:
    """Test circular reference detection in YAML."""

    def test_circular_reference_detection(self):
        """
        Test that circular references in YAML are detected.

        YAML anchors/aliases can create circular references that cause
        infinite loops when traversing the config.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            config_root = Path(tmpdir) / "configs"
            agents_dir = config_root / "agents"
            agents_dir.mkdir(parents=True)

            # YAML with circular reference
            # Note: PyYAML actually handles this by creating a recursive structure,
            # but we should detect and reject it during processing
            circular_yaml = """
name: test_agent
version: 1.0
llm:
  provider: openai
  model: gpt-4
# Create circular reference using anchors
node_a: &node_a
  next: *node_b
  data: "a"
node_b: &node_b
  next: *node_a
  data: "b"
"""
            config_file = agents_dir / "circular.yaml"
            config_file.write_text(circular_yaml)

            loader = ConfigLoader(config_root=config_root)

            # Should detect circular reference during processing
            # This might be caught during parsing or during env var substitution
            with pytest.raises((ConfigValidationError, RecursionError)):
                config = loader.load_agent("circular", validate=False)

                # If loading succeeds, try to access the circular structure
                # This should trigger recursion detection
                import json

                json.dumps(config)  # Will fail on circular refs

            # Accept either ConfigValidationError or RecursionError
            # (pytest.raises already guarantees the exception was raised)

    def test_self_referential_anchor(self):
        """
        Test that self-referential YAML anchors are detected.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            config_root = Path(tmpdir) / "configs"
            agents_dir = config_root / "agents"
            agents_dir.mkdir(parents=True)

            # Self-referential anchor
            self_ref_yaml = """
name: test_agent
version: 1.0
llm:
  provider: openai
  model: gpt-4
recursive: &loop
  - *loop
"""
            config_file = agents_dir / "self_ref.yaml"
            config_file.write_text(self_ref_yaml)

            loader = ConfigLoader(config_root=config_root)

            # Should detect self-reference
            with pytest.raises((ConfigValidationError, RecursionError)):
                config = loader.load_agent("self_ref", validate=False)

                # Try to serialize to trigger detection
                import json

                json.dumps(config)

            # (pytest.raises already guarantees the exception was raised)
