"""Tests for compiler security limits (src/compiler/security_limits.py).

Tests cover:
- ConfigSecurityLimits frozen dataclass
- Constant value verification (MAX_CONFIG_SIZE, MAX_ENV_VAR_SIZE, etc.)
- CONFIG_SECURITY singleton instance
- Frozen dataclass immutability
- Security limit rationale and protections
"""
import pytest

from src.workflow.security_limits import CONFIG_SECURITY, ConfigSecurityLimits


class TestConfigSecurityLimits:
    """Test the ConfigSecurityLimits frozen dataclass."""

    def test_max_config_size_value(self):
        """Test MAX_CONFIG_SIZE is set to 10MB."""
        limits = ConfigSecurityLimits()
        assert limits.MAX_CONFIG_SIZE == 10 * 1024 * 1024
        assert limits.MAX_CONFIG_SIZE == 10485760

    def test_max_env_var_size_value(self):
        """Test MAX_ENV_VAR_SIZE is set to 10KB."""
        limits = ConfigSecurityLimits()
        assert limits.MAX_ENV_VAR_SIZE == 10 * 1024
        assert limits.MAX_ENV_VAR_SIZE == 10240

    def test_max_yaml_nesting_depth_value(self):
        """Test MAX_YAML_NESTING_DEPTH is set to 50."""
        limits = ConfigSecurityLimits()
        assert limits.MAX_YAML_NESTING_DEPTH == 50

    def test_max_yaml_nodes_value(self):
        """Test MAX_YAML_NODES is set to 100,000."""
        limits = ConfigSecurityLimits()
        assert limits.MAX_YAML_NODES == 100_000
        assert limits.MAX_YAML_NODES == 100000

    def test_frozen_dataclass_immutability(self):
        """Test that ConfigSecurityLimits is frozen and cannot be modified."""
        limits = ConfigSecurityLimits()

        with pytest.raises(AttributeError):
            limits.MAX_CONFIG_SIZE = 999

        with pytest.raises(AttributeError):
            limits.MAX_ENV_VAR_SIZE = 999

        with pytest.raises(AttributeError):
            limits.MAX_YAML_NESTING_DEPTH = 999

        with pytest.raises(AttributeError):
            limits.MAX_YAML_NODES = 999

    def test_dataclass_instantiation(self):
        """Test that ConfigSecurityLimits can be instantiated."""
        limits = ConfigSecurityLimits()
        assert isinstance(limits, ConfigSecurityLimits)

    def test_multiple_instances_same_values(self):
        """Test that multiple instances have the same constant values."""
        limits1 = ConfigSecurityLimits()
        limits2 = ConfigSecurityLimits()

        assert limits1.MAX_CONFIG_SIZE == limits2.MAX_CONFIG_SIZE
        assert limits1.MAX_ENV_VAR_SIZE == limits2.MAX_ENV_VAR_SIZE
        assert limits1.MAX_YAML_NESTING_DEPTH == limits2.MAX_YAML_NESTING_DEPTH
        assert limits1.MAX_YAML_NODES == limits2.MAX_YAML_NODES


class TestConfigSecuritySingleton:
    """Test the CONFIG_SECURITY singleton instance."""

    def test_singleton_exists(self):
        """Test that CONFIG_SECURITY singleton is available."""
        assert CONFIG_SECURITY is not None
        assert isinstance(CONFIG_SECURITY, ConfigSecurityLimits)

    def test_singleton_has_correct_values(self):
        """Test that singleton has correct constant values."""
        assert CONFIG_SECURITY.MAX_CONFIG_SIZE == 10 * 1024 * 1024
        assert CONFIG_SECURITY.MAX_ENV_VAR_SIZE == 10 * 1024
        assert CONFIG_SECURITY.MAX_YAML_NESTING_DEPTH == 50
        assert CONFIG_SECURITY.MAX_YAML_NODES == 100_000

    def test_singleton_immutability(self):
        """Test that singleton cannot be modified."""
        with pytest.raises(AttributeError):
            CONFIG_SECURITY.MAX_CONFIG_SIZE = 12345

        with pytest.raises(AttributeError):
            CONFIG_SECURITY.MAX_ENV_VAR_SIZE = 12345

        with pytest.raises(AttributeError):
            CONFIG_SECURITY.MAX_YAML_NESTING_DEPTH = 12345

        with pytest.raises(AttributeError):
            CONFIG_SECURITY.MAX_YAML_NODES = 12345


class TestSecurityLimitRationale:
    """Test that security limits provide expected protections."""

    def test_config_size_prevents_memory_exhaustion(self):
        """Test that MAX_CONFIG_SIZE is large enough for legitimate use but protects against attacks."""
        # 10MB should allow large multi-agent workflows
        assert CONFIG_SECURITY.MAX_CONFIG_SIZE >= 1 * 1024 * 1024  # At least 1MB for legitimate configs
        # But not so large that it allows easy memory exhaustion
        assert CONFIG_SECURITY.MAX_CONFIG_SIZE <= 100 * 1024 * 1024  # Not more than 100MB

    def test_env_var_size_allows_large_tokens(self):
        """Test that MAX_ENV_VAR_SIZE allows large JWTs/keys but prevents DoS."""
        # 10KB should allow large JWTs and API keys
        assert CONFIG_SECURITY.MAX_ENV_VAR_SIZE >= 1024  # At least 1KB
        # But prevents massive environment variable expansion attacks
        assert CONFIG_SECURITY.MAX_ENV_VAR_SIZE <= 1024 * 1024  # Not more than 1MB

    def test_yaml_nesting_prevents_stack_overflow(self):
        """Test that MAX_YAML_NESTING_DEPTH prevents stack overflow."""
        # Should allow reasonable nesting for legitimate configs
        assert CONFIG_SECURITY.MAX_YAML_NESTING_DEPTH >= 20
        # But prevent deeply nested attacks
        assert CONFIG_SECURITY.MAX_YAML_NESTING_DEPTH <= 100

    def test_yaml_nodes_prevents_billion_laughs(self):
        """Test that MAX_YAML_NODES prevents billion laughs attacks."""
        # Should allow large configs with many nodes
        assert CONFIG_SECURITY.MAX_YAML_NODES >= 1000
        # But prevent exponential expansion (billion laughs can create billions of nodes)
        assert CONFIG_SECURITY.MAX_YAML_NODES <= 1_000_000


class TestSecurityLimitTypes:
    """Test that security limits have correct types."""

    def test_max_config_size_is_int(self):
        """Test that MAX_CONFIG_SIZE is an integer."""
        assert isinstance(CONFIG_SECURITY.MAX_CONFIG_SIZE, int)

    def test_max_env_var_size_is_int(self):
        """Test that MAX_ENV_VAR_SIZE is an integer."""
        assert isinstance(CONFIG_SECURITY.MAX_ENV_VAR_SIZE, int)

    def test_max_yaml_nesting_depth_is_int(self):
        """Test that MAX_YAML_NESTING_DEPTH is an integer."""
        assert isinstance(CONFIG_SECURITY.MAX_YAML_NESTING_DEPTH, int)

    def test_max_yaml_nodes_is_int(self):
        """Test that MAX_YAML_NODES is an integer."""
        assert isinstance(CONFIG_SECURITY.MAX_YAML_NODES, int)

    def test_all_values_positive(self):
        """Test that all security limits are positive values."""
        assert CONFIG_SECURITY.MAX_CONFIG_SIZE > 0
        assert CONFIG_SECURITY.MAX_ENV_VAR_SIZE > 0
        assert CONFIG_SECURITY.MAX_YAML_NESTING_DEPTH > 0
        assert CONFIG_SECURITY.MAX_YAML_NODES > 0


class TestSecurityLimitUsage:
    """Test expected usage patterns of security limits."""

    def test_can_import_singleton(self):
        """Test that CONFIG_SECURITY can be imported directly."""
        from src.workflow.security_limits import CONFIG_SECURITY as imported_singleton
        assert imported_singleton is CONFIG_SECURITY
        assert imported_singleton.MAX_CONFIG_SIZE == 10 * 1024 * 1024

    def test_can_import_class(self):
        """Test that ConfigSecurityLimits class can be imported."""
        from src.workflow.security_limits import ConfigSecurityLimits as ImportedClass
        assert ImportedClass is ConfigSecurityLimits

    def test_typical_config_size_check(self):
        """Test typical usage pattern for config size validation."""
        sample_config_size = 5 * 1024 * 1024  # 5MB
        assert sample_config_size < CONFIG_SECURITY.MAX_CONFIG_SIZE

        oversized_config = 15 * 1024 * 1024  # 15MB
        assert oversized_config > CONFIG_SECURITY.MAX_CONFIG_SIZE

    def test_typical_env_var_size_check(self):
        """Test typical usage pattern for env var size validation."""
        typical_jwt = 2048  # ~2KB JWT
        assert typical_jwt < CONFIG_SECURITY.MAX_ENV_VAR_SIZE

        malicious_env_var = 50 * 1024  # 50KB
        assert malicious_env_var > CONFIG_SECURITY.MAX_ENV_VAR_SIZE

    def test_typical_nesting_depth_check(self):
        """Test typical usage pattern for nesting depth validation."""
        normal_nesting = 10  # Typical config depth
        assert normal_nesting < CONFIG_SECURITY.MAX_YAML_NESTING_DEPTH

        excessive_nesting = 100
        assert excessive_nesting > CONFIG_SECURITY.MAX_YAML_NESTING_DEPTH

    def test_typical_node_count_check(self):
        """Test typical usage pattern for node count validation."""
        normal_nodes = 500  # Typical config nodes
        assert normal_nodes < CONFIG_SECURITY.MAX_YAML_NODES

        billion_laughs_nodes = 1_000_000  # Exponential expansion
        assert billion_laughs_nodes > CONFIG_SECURITY.MAX_YAML_NODES
