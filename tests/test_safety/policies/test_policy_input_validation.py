"""Tests for policy input validation (code-high-12).

Regression tests to ensure that policy configuration parameters are properly
validated to prevent negative values, type errors, and extreme values that
could bypass safety limits or cause undefined behavior.
"""
import pytest

from temper_ai.safety.policies.rate_limit_policy import RateLimitPolicy
from temper_ai.safety.policies.resource_limit_policy import ResourceLimitPolicy


class TestRateLimitPolicyValidation:
    """Tests for RateLimitPolicy input validation."""

    def test_reject_negative_cooldown_multiplier(self):
        """Test that negative cooldown_multiplier is rejected."""
        with pytest.raises(ValueError, match="cooldown_multiplier must be non-negative"):
            RateLimitPolicy({"cooldown_multiplier": -1.0})

    def test_reject_extreme_cooldown_multiplier(self):
        """Test that extremely large cooldown_multiplier is rejected."""
        with pytest.raises(ValueError, match="cooldown_multiplier must be <= 100"):
            RateLimitPolicy({"cooldown_multiplier": 1000})

    def test_reject_string_cooldown_multiplier(self):
        """Test that string cooldown_multiplier is rejected."""
        with pytest.raises(ValueError, match="cooldown_multiplier must be numeric"):
            RateLimitPolicy({"cooldown_multiplier": "infinite"})

    def test_reject_non_bool_per_agent(self):
        """Test that non-boolean per_agent is rejected."""
        with pytest.raises(ValueError, match="per_agent must be boolean"):
            RateLimitPolicy({"per_agent": "yes"})

    def test_reject_non_dict_rate_limits(self):
        """Test that rate_limits must be a dictionary."""
        with pytest.raises(ValueError, match="rate_limits must be a dictionary"):
            RateLimitPolicy({"rate_limits": "invalid"})

    def test_reject_non_string_limit_type(self):
        """Test that rate limit type keys must be strings."""
        with pytest.raises(ValueError, match="config keys must be strings"):
            RateLimitPolicy({"rate_limits": {123: {"max_tokens": 10, "refill_rate": 1.0}}})

    def test_reject_missing_required_fields(self):
        """Test that rate limits with missing required fields are rejected."""
        with pytest.raises(ValueError, match="missing required field 'refill_rate'"):
            RateLimitPolicy({"rate_limits": {"commit": {"max_tokens": 10}}})

    def test_reject_invalid_rate_limit_config(self):
        """Test that invalid RateLimit config is rejected."""
        # RateLimit.__post_init__ will reject negative values
        with pytest.raises(ValueError, match="Invalid rate limit configuration"):
            RateLimitPolicy({
                "rate_limits": {
                    "commit": {
                        "max_tokens": -10,  # Negative
                        "refill_rate": 1.0
                    }
                }
            })

    def test_reject_wrong_type_for_limit_config(self):
        """Test that wrong type for limit config is rejected."""
        with pytest.raises(ValueError, match="must be dict or RateLimit"):
            RateLimitPolicy({
                "rate_limits": {
                    "commit": "not a dict or RateLimit"
                }
            })

    def test_accept_valid_cooldown_multiplier(self):
        """Test that valid cooldown_multiplier is accepted."""
        policy = RateLimitPolicy({"cooldown_multiplier": 2.5})
        assert policy.cooldown_multiplier == 2.5

    def test_accept_valid_rate_limits(self):
        """Test that valid rate limits are accepted."""
        config = {
            "rate_limits": {
                "commit": {
                    "max_tokens": 10,
                    "refill_rate": 1.0,
                    "refill_period": 60.0
                }
            }
        }
        policy = RateLimitPolicy(config)
        # Should not raise
        assert policy is not None
        assert "commit" in policy.rate_limits


class TestResourceLimitPolicyValidation:
    """Tests for ResourceLimitPolicy input validation."""

    def test_reject_negative_file_size_read(self):
        """Test that negative max_file_size_read is rejected."""
        with pytest.raises(ValueError, match="max_file_size_read must be >="):
            ResourceLimitPolicy({"max_file_size_read": -1})

    def test_reject_negative_file_size_write(self):
        """Test that negative max_file_size_write is rejected."""
        with pytest.raises(ValueError, match="max_file_size_write must be >="):
            ResourceLimitPolicy({"max_file_size_write": -100})

    def test_reject_zero_cpu_time(self):
        """Test that zero max_cpu_time is rejected."""
        with pytest.raises(ValueError, match="max_cpu_time must be >="):
            ResourceLimitPolicy({"max_cpu_time": 0})

    def test_reject_negative_cpu_time(self):
        """Test that negative max_cpu_time is rejected."""
        with pytest.raises(ValueError, match="max_cpu_time must be >="):
            ResourceLimitPolicy({"max_cpu_time": -10.0})

    def test_reject_negative_memory_limit(self):
        """Test that negative max_memory_per_operation is rejected."""
        with pytest.raises(ValueError, match="max_memory_per_operation must be >="):
            ResourceLimitPolicy({"max_memory_per_operation": -999999})

    def test_reject_negative_disk_space(self):
        """Test that negative min_free_disk_space is rejected."""
        with pytest.raises(ValueError, match="min_free_disk_space must be >="):
            ResourceLimitPolicy({"min_free_disk_space": -1024})

    def test_reject_extreme_file_size(self):
        """Test that extremely large file size is rejected."""
        # 100GB exceeds 10GB limit
        with pytest.raises(ValueError, match="max_file_size_read must be <="):
            ResourceLimitPolicy({"max_file_size_read": 100 * 1024**3})

    def test_reject_extreme_memory(self):
        """Test that extremely large memory limit is rejected."""
        # 16GB exceeds 8GB limit
        with pytest.raises(ValueError, match="max_memory_per_operation must be <="):
            ResourceLimitPolicy({"max_memory_per_operation": 16 * 1024**3})

    def test_reject_extreme_cpu_time(self):
        """Test that extremely large CPU time is rejected."""
        # 2 hours exceeds 1 hour limit
        with pytest.raises(ValueError, match="max_cpu_time must be <="):
            ResourceLimitPolicy({"max_cpu_time": 7200.0})

    def test_reject_extreme_disk_space(self):
        """Test that extremely large disk space requirement is rejected."""
        # 2TB exceeds 1TB limit
        with pytest.raises(ValueError, match="min_free_disk_space must be <="):
            ResourceLimitPolicy({"min_free_disk_space": 2 * 1024**4})

    def test_reject_string_file_size(self):
        """Test that string file size is rejected."""
        with pytest.raises(ValueError, match="max_file_size_read must be numeric"):
            ResourceLimitPolicy({"max_file_size_read": "unlimited"})

    def test_reject_string_cpu_time(self):
        """Test that string CPU time is rejected."""
        with pytest.raises(ValueError, match="max_cpu_time must be numeric"):
            ResourceLimitPolicy({"max_cpu_time": "infinite"})

    def test_reject_non_bool_track_memory(self):
        """Test that non-boolean track_memory is rejected."""
        with pytest.raises(ValueError, match="track_memory must be boolean"):
            ResourceLimitPolicy({"track_memory": "yes"})

    def test_reject_non_bool_track_cpu(self):
        """Test that non-boolean track_cpu is rejected."""
        with pytest.raises(ValueError, match="track_cpu must be boolean"):
            ResourceLimitPolicy({"track_cpu": 1})

    def test_reject_non_bool_track_disk(self):
        """Test that non-boolean track_disk is rejected."""
        with pytest.raises(ValueError, match="track_disk must be boolean"):
            ResourceLimitPolicy({"track_disk": None})

    def test_reject_list_for_file_size(self):
        """Test that list is rejected for file size."""
        with pytest.raises(ValueError, match="max_file_size_write must be numeric"):
            ResourceLimitPolicy({"max_file_size_write": [100, 200]})

    def test_accept_valid_limits(self):
        """Test that valid configuration is accepted."""
        config = {
            "max_file_size_read": 50 * 1024 * 1024,  # 50MB
            "max_file_size_write": 5 * 1024 * 1024,  # 5MB
            "max_memory_per_operation": 100 * 1024 * 1024,  # 100MB
            "max_cpu_time": 10.0,  # 10 seconds
            "min_free_disk_space": 500 * 1024 * 1024,  # 500MB
            "track_memory": True,
            "track_cpu": True,
            "track_disk": False
        }
        policy = ResourceLimitPolicy(config)
        assert policy.max_file_size_read == 50 * 1024 * 1024
        assert policy.max_file_size_write == 5 * 1024 * 1024
        assert policy.max_memory_per_operation == 100 * 1024 * 1024
        assert policy.max_cpu_time == 10.0
        assert policy.min_free_disk_space == 500 * 1024 * 1024
        assert policy.track_memory is True
        assert policy.track_cpu is True
        assert policy.track_disk is False

    def test_accept_float_for_size(self):
        """Test that float is accepted and converted to int for size."""
        policy = ResourceLimitPolicy({"max_file_size_read": 100.5})
        assert policy.max_file_size_read == 100  # Converted to int

    def test_accept_int_for_cpu_time(self):
        """Test that int is accepted and converted to float for time."""
        policy = ResourceLimitPolicy({"max_cpu_time": 30})
        assert policy.max_cpu_time == 30.0  # Converted to float


class TestEdgeCases:
    """Test edge cases for policy validation."""

    def test_zero_file_size_rejected(self):
        """Test that zero file size is rejected."""
        with pytest.raises(ValueError, match="must be >="):
            ResourceLimitPolicy({"max_file_size_read": 0})

    def test_boundary_cooldown_multiplier(self):
        """Test boundary values for cooldown_multiplier."""
        # Just below limit - should pass
        policy = RateLimitPolicy({"cooldown_multiplier": 100})
        assert policy.cooldown_multiplier == 100

        # Exactly at limit - should pass
        policy = RateLimitPolicy({"cooldown_multiplier": 100.0})
        assert policy.cooldown_multiplier == 100.0

        # Just above limit - should fail
        with pytest.raises(ValueError):
            RateLimitPolicy({"cooldown_multiplier": 100.1})

    def test_boundary_cpu_time(self):
        """Test boundary values for CPU time."""
        # Minimum allowed
        policy = ResourceLimitPolicy({"max_cpu_time": 0.001})
        assert policy.max_cpu_time == 0.001

        # Maximum allowed
        policy = ResourceLimitPolicy({"max_cpu_time": 3600.0})
        assert policy.max_cpu_time == 3600.0

        # Above maximum
        with pytest.raises(ValueError):
            ResourceLimitPolicy({"max_cpu_time": 3601.0})

    def test_boundary_file_size(self):
        """Test boundary values for file size."""
        # 1 byte minimum
        policy = ResourceLimitPolicy({"max_file_size_read": 1})
        assert policy.max_file_size_read == 1

        # 10GB maximum
        policy = ResourceLimitPolicy({"max_file_size_read": 10 * 1024**3})
        assert policy.max_file_size_read == 10 * 1024**3

        # Above maximum
        with pytest.raises(ValueError):
            ResourceLimitPolicy({"max_file_size_read": 11 * 1024**3})


class TestErrorMessages:
    """Test that error messages are helpful."""

    def test_negative_value_error_message(self):
        """Test that negative value errors have helpful messages."""
        try:
            ResourceLimitPolicy({"max_file_size_read": -100})
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "must be >=" in str(e)
            assert "-100" in str(e)

    def test_extreme_value_error_message(self):
        """Test that extreme value errors have helpful messages."""
        try:
            ResourceLimitPolicy({"max_cpu_time": 10000.0})
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "must be <=" in str(e)
            assert "10000" in str(e)

    def test_type_error_message(self):
        """Test that type errors have helpful messages."""
        try:
            ResourceLimitPolicy({"track_memory": "yes"})
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "must be boolean" in str(e)
            assert "str" in str(e)


# ============================================================================
# Tests for code-high-12 Fixes
# ============================================================================


class TestSecretDetectionPolicyValidation:
    """Tests for SecretDetectionPolicy input validation (code-high-12)."""

    def test_reject_non_list_enabled_patterns(self):
        """Test that non-list enabled_patterns is rejected (unless string)."""
        from temper_ai.safety.secret_detection import SecretDetectionPolicy

        # Dict should be rejected
        with pytest.raises(ValueError, match="enabled_patterns must be a list"):
            SecretDetectionPolicy({"enabled_patterns": {"aws": True}})

    def test_convert_string_to_list_enabled_patterns(self):
        """Test that single string is converted to list for convenience."""
        from temper_ai.safety.secret_detection import SecretDetectionPolicy

        policy = SecretDetectionPolicy({"enabled_patterns": "aws_access_key"})
        assert "aws_access_key" in policy.enabled_patterns

    def test_reject_invalid_pattern_name(self):
        """Test that unknown pattern name is rejected."""
        from temper_ai.safety.secret_detection import SecretDetectionPolicy

        with pytest.raises(ValueError, match="Unknown pattern 'invalid_pattern'"):
            SecretDetectionPolicy({"enabled_patterns": ["invalid_pattern"]})

    def test_reject_empty_enabled_patterns(self):
        """Test that empty enabled_patterns is rejected."""
        from temper_ai.safety.secret_detection import SecretDetectionPolicy

        with pytest.raises(ValueError, match="enabled_patterns cannot be empty"):
            SecretDetectionPolicy({"enabled_patterns": []})

    def test_reject_negative_entropy_threshold(self):
        """Test that negative entropy threshold is rejected."""
        from temper_ai.safety.secret_detection import SecretDetectionPolicy

        with pytest.raises(ValueError, match="entropy_threshold must be between 0.0 and 8.0"):
            SecretDetectionPolicy({"entropy_threshold": -1.0})

    def test_reject_extreme_entropy_threshold(self):
        """Test that entropy threshold > 8.0 is rejected (max Shannon entropy)."""
        from temper_ai.safety.secret_detection import SecretDetectionPolicy

        with pytest.raises(ValueError, match="entropy_threshold must be between 0.0 and 8.0"):
            SecretDetectionPolicy({"entropy_threshold": 10.0})

    def test_reject_string_entropy_threshold(self):
        """Test that string entropy threshold is rejected."""
        from temper_ai.safety.secret_detection import SecretDetectionPolicy

        with pytest.raises(ValueError, match="entropy_threshold must be a number"):
            SecretDetectionPolicy({"entropy_threshold": "high"})

    def test_reject_non_list_excluded_paths(self):
        """Test that non-list excluded_paths is rejected."""
        from temper_ai.safety.secret_detection import SecretDetectionPolicy

        with pytest.raises(ValueError, match="excluded_paths must be a list"):
            SecretDetectionPolicy({"excluded_paths": "/project"})

    def test_reject_too_long_excluded_path(self):
        """Test that excluded_paths with > 500 chars is rejected."""
        from temper_ai.safety.secret_detection import SecretDetectionPolicy

        long_path = "a" * 501
        with pytest.raises(ValueError, match="excluded_paths items must be <= 500"):
            SecretDetectionPolicy({"excluded_paths": [long_path]})

    def test_reject_too_many_excluded_paths(self):
        """Test that > 1000 excluded_paths is rejected."""
        from temper_ai.safety.secret_detection import SecretDetectionPolicy

        many_paths = [f"path_{i}" for i in range(1001)]
        with pytest.raises(ValueError, match="config list/tuple/set must have <= 1000 items"):
            SecretDetectionPolicy({"excluded_paths": many_paths})

    def test_reject_string_allow_test_secrets(self):
        """Test that string boolean is rejected (prevents 'false' -> True bug)."""
        from temper_ai.safety.secret_detection import SecretDetectionPolicy

        with pytest.raises(ValueError, match="must be a boolean"):
            SecretDetectionPolicy({"allow_test_secrets": "false"})

    def test_accept_valid_configuration(self):
        """Test that valid configuration is accepted."""
        from temper_ai.safety.secret_detection import SecretDetectionPolicy

        policy = SecretDetectionPolicy({
            "enabled_patterns": ["aws_access_key", "github_token"],
            "entropy_threshold": 5.0,
            "entropy_threshold_generic": 3.5,
            "excluded_paths": ["/test", "/examples"],
            "allow_test_secrets": False
        })
        assert len(policy.enabled_patterns) == 2
        assert policy.entropy_threshold == 5.0
        assert policy.entropy_threshold_generic == 3.5
        assert len(policy.excluded_paths) == 2
        assert policy.allow_test_secrets is False


class TestFileAccessPolicyValidation:
    """Tests for FileAccessPolicy input validation (code-high-12)."""

    def test_reject_non_list_allowed_paths(self):
        """Test that non-list allowed_paths is rejected."""
        from temper_ai.safety.file_access import FileAccessPolicy

        with pytest.raises(ValueError, match="allowed_paths must be a list"):
            FileAccessPolicy({"allowed_paths": "/project/src"})

    def test_reject_non_string_path_item(self):
        """Test that non-string path items are rejected."""
        from temper_ai.safety.file_access import FileAccessPolicy

        with pytest.raises(ValueError, match="allowed_paths items must be strings"):
            FileAccessPolicy({"allowed_paths": ["/project", 123]})

    def test_reject_too_long_path(self):
        """Test that paths > 500 chars are rejected."""
        from temper_ai.safety.file_access import FileAccessPolicy

        long_path = "a" * 501
        with pytest.raises(ValueError, match="allowed_paths items must be <= 500"):
            FileAccessPolicy({"allowed_paths": [long_path]})

    def test_reject_too_many_paths(self):
        """Test that > 1000 paths are rejected."""
        from temper_ai.safety.file_access import FileAccessPolicy

        many_paths = [f"/path{i}" for i in range(1001)]
        with pytest.raises(ValueError, match="config list/tuple/set must have <= 1000 items"):
            FileAccessPolicy({"allowed_paths": many_paths})

    def test_reject_string_allow_parent_traversal(self):
        """Test that string boolean is rejected (CRITICAL: prevents security bypass)."""
        from temper_ai.safety.file_access import FileAccessPolicy

        # This is CRITICAL: "false" would evaluate to True, enabling parent traversal!
        with pytest.raises(ValueError, match="must be a boolean"):
            FileAccessPolicy({"allow_parent_traversal": "false"})

    def test_reject_string_allow_symlinks(self):
        """Test that string boolean is rejected for allow_symlinks."""
        from temper_ai.safety.file_access import FileAccessPolicy

        with pytest.raises(ValueError, match="must be a boolean"):
            FileAccessPolicy({"allow_symlinks": "true"})

    def test_auto_add_dot_to_extensions(self):
        """Test that missing dot is auto-added to extensions."""
        from temper_ai.safety.file_access import FileAccessPolicy

        policy = FileAccessPolicy({"forbidden_extensions": ["exe", "dll"]})
        assert ".exe" in policy.forbidden_extensions
        assert ".dll" in policy.forbidden_extensions

    def test_reject_too_long_extension(self):
        """Test that extensions > 20 chars are rejected."""
        from temper_ai.safety.file_access import FileAccessPolicy

        long_ext = "a" * 21
        with pytest.raises(ValueError, match="forbidden_extensions items must be <= 20"):
            FileAccessPolicy({"forbidden_extensions": [long_ext]})

    def test_reject_too_many_extensions(self):
        """Test that > 100 extensions are rejected."""
        from temper_ai.safety.file_access import FileAccessPolicy

        many_exts = [f".ext{i}" for i in range(101)]
        with pytest.raises(ValueError, match="forbidden_extensions must have <= 100"):
            FileAccessPolicy({"forbidden_extensions": many_exts})

    def test_reject_non_list_forbidden_directories(self):
        """Test that non-list forbidden_directories is rejected."""
        from temper_ai.safety.file_access import FileAccessPolicy

        with pytest.raises(ValueError, match="forbidden_directories must be a list"):
            FileAccessPolicy({"forbidden_directories": "/etc"})

    def test_accept_valid_configuration(self):
        """Test that valid configuration is accepted."""
        from temper_ai.safety.file_access import FileAccessPolicy

        policy = FileAccessPolicy({
            "allowed_paths": ["/project/src", "/project/tests"],
            "denied_paths": ["/project/src/secrets"],
            "allow_parent_traversal": False,
            "allow_symlinks": False,
            "allow_absolute_paths": True,
            "case_sensitive": True,
            "forbidden_extensions": ["exe", "dll"],
            "forbidden_directories": ["/custom/forbidden"],
            "forbidden_files": [".env.production"]
        })
        assert len(policy.allowed_paths) == 2
        assert policy.allow_parent_traversal is False
        assert ".exe" in policy.forbidden_extensions


class TestForbiddenOperationsPolicyValidation:
    """Tests for ForbiddenOperationsPolicy input validation (code-high-12)."""

    def test_reject_string_check_file_writes(self):
        """Test that string boolean is rejected."""
        from temper_ai.safety.forbidden_operations import ForbiddenOperationsPolicy

        with pytest.raises(ValueError, match="must be a boolean"):
            ForbiddenOperationsPolicy({"check_file_writes": "yes"})

    def test_reject_non_dict_custom_patterns(self):
        """Test that non-dict custom_forbidden_patterns is rejected."""
        from temper_ai.safety.forbidden_operations import ForbiddenOperationsPolicy

        with pytest.raises(ValueError, match="custom_forbidden_patterns must be a dict"):
            ForbiddenOperationsPolicy({"custom_forbidden_patterns": ["pattern1"]})

    def test_reject_non_string_pattern_value(self):
        """Test that non-string pattern values are rejected."""
        from temper_ai.safety.forbidden_operations import ForbiddenOperationsPolicy

        with pytest.raises(ValueError, match="must be a string"):
            ForbiddenOperationsPolicy({"custom_forbidden_patterns": {"test": 123}})

    def test_reject_too_long_pattern(self):
        """Test that patterns > 500 chars are rejected."""
        from temper_ai.safety.forbidden_operations import ForbiddenOperationsPolicy

        long_pattern = "a" * 501
        with pytest.raises(ValueError, match="must be <= 500 characters"):
            ForbiddenOperationsPolicy({"custom_forbidden_patterns": {"test": long_pattern}})

    def test_reject_too_many_patterns(self):
        """Test that > 100 custom patterns are rejected."""
        from temper_ai.safety.forbidden_operations import ForbiddenOperationsPolicy

        many_patterns = {f"pattern{i}": f"test{i}" for i in range(101)}
        with pytest.raises(ValueError, match="must have <= 100 patterns"):
            ForbiddenOperationsPolicy({"custom_forbidden_patterns": many_patterns})

    def test_reject_non_list_whitelist(self):
        """Test that non-list whitelist_commands is rejected."""
        from temper_ai.safety.forbidden_operations import ForbiddenOperationsPolicy

        with pytest.raises(ValueError, match="whitelist_commands must be a list"):
            ForbiddenOperationsPolicy({"whitelist_commands": "cat file.txt"})

    def test_reject_too_long_whitelist_command(self):
        """Test that whitelist commands > 200 chars are rejected."""
        from temper_ai.safety.forbidden_operations import ForbiddenOperationsPolicy

        long_cmd = "a" * 201
        with pytest.raises(ValueError, match="whitelist_commands items must be <= 200"):
            ForbiddenOperationsPolicy({"whitelist_commands": [long_cmd]})

    def test_reject_too_many_whitelist_commands(self):
        """Test that > 1000 whitelist commands are rejected."""
        from temper_ai.safety.forbidden_operations import ForbiddenOperationsPolicy

        many_cmds = [f"cmd{i}" for i in range(1001)]
        with pytest.raises(ValueError, match="config list/tuple/set must have <= 1000 items"):
            ForbiddenOperationsPolicy({"whitelist_commands": many_cmds})

    def test_accept_valid_configuration(self):
        """Test that valid configuration is accepted."""
        from temper_ai.safety.forbidden_operations import ForbiddenOperationsPolicy

        policy = ForbiddenOperationsPolicy({
            "check_file_writes": True,
            "check_dangerous_commands": True,
            "check_injection_patterns": True,
            "allow_read_only": False,
            "custom_forbidden_patterns": {"test": r"rm\s+-rf"},
            "whitelist_commands": ["git status", "ls -la"]
        })
        assert policy.check_file_writes is True
        assert len(policy.custom_forbidden_patterns) == 1
        assert len(policy.whitelist_commands) == 2
