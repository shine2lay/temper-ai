"""Tests for FileAccessPolicy.

Tests cover:
- Allowlist mode (explicit permissions)
- Denylist mode (explicit denials)
- Path traversal prevention
- Forbidden directory protection
- Forbidden file protection
- Forbidden extension blocking
- Symlink restrictions
- Absolute vs relative path control
- Pattern matching (wildcards, recursive)
- Case sensitivity
"""
from src.safety.file_access import FileAccessPolicy
from src.safety.interfaces import ViolationSeverity


class TestFileAccessPolicyBasics:
    """Basic tests for FileAccessPolicy initialization and configuration."""

    def test_default_initialization(self):
        """Test policy with default configuration."""
        policy = FileAccessPolicy()

        assert policy.name == "file_access"
        assert policy.version == "1.0.0"
        assert policy.priority == 95  # Highest priority
        assert policy.mode == "denylist"  # Default mode
        assert not policy.allow_parent_traversal
        assert not policy.allow_symlinks
        assert policy.allow_absolute_paths
        assert policy.case_sensitive

    def test_allowlist_mode_initialization(self):
        """Test policy in allowlist mode."""
        config = {
            "allowed_paths": ["/project/**", "/tmp/**"]
        }
        policy = FileAccessPolicy(config)

        assert policy.mode == "allowlist"
        assert len(policy.allowed_paths) == 2

    def test_denylist_mode_initialization(self):
        """Test policy in denylist mode."""
        config = {
            "denied_paths": ["/etc/**", "/root/**"]
        }
        policy = FileAccessPolicy(config)

        assert policy.mode == "denylist"
        assert len(policy.denied_paths) == 2

    def test_forbidden_defaults(self):
        """Test default forbidden directories and files."""
        policy = FileAccessPolicy()

        # Should have default forbidden directories
        assert "/etc" in policy.forbidden_directories
        assert "/sys" in policy.forbidden_directories
        assert "/proc" in policy.forbidden_directories
        assert "/root" in policy.forbidden_directories

        # Should have default forbidden files
        assert "/.env" in policy.forbidden_files
        assert "/etc/passwd" in policy.forbidden_files
        assert "/etc/shadow" in policy.forbidden_files

        # Should have default forbidden extensions
        assert ".pem" in policy.forbidden_extensions
        assert ".key" in policy.forbidden_extensions


class TestPathTraversalPrevention:
    """Tests for path traversal attack prevention."""

    def test_parent_traversal_blocked_by_default(self):
        """Test that ../ is blocked by default."""
        policy = FileAccessPolicy()

        result = policy.validate(
            action={"operation": "read", "path": "/project/../etc/passwd"},
            context={}
        )

        assert not result.valid
        assert len(result.violations) == 1
        assert result.violations[0].severity == ViolationSeverity.CRITICAL
        assert "traversal" in result.violations[0].message.lower()

    def test_multiple_parent_references(self):
        """Test multiple ../ references are caught."""
        policy = FileAccessPolicy()

        result = policy.validate(
            action={"operation": "read", "path": "../../etc/passwd"},
            context={}
        )

        assert not result.valid
        assert "traversal" in result.violations[0].message.lower()

    def test_parent_traversal_allowed_when_configured(self):
        """Test that ../ can be allowed via configuration."""
        config = {
            "allow_parent_traversal": True,
            "allowed_paths": ["../**"]  # Allow parent access
        }
        policy = FileAccessPolicy(config)

        result = policy.validate(
            action={"operation": "read", "path": "../file.txt"},
            context={}
        )

        # Should pass traversal check, may fail allowlist
        violations_are_traversal = any(
            "traversal" in v.message.lower()
            for v in result.violations
        )
        assert not violations_are_traversal

    def test_dot_dot_in_filename(self):
        """Test that ..hidden (not ..) in filename is allowed.

        The path '/project/..hidden/file.txt' contains '..hidden' which is a
        valid directory name starting with two dots -- it is NOT a parent
        traversal ('..').  After os.path.normpath it stays unchanged, so the
        policy correctly allows it.
        """
        policy = FileAccessPolicy()

        result = policy.validate(
            action={"operation": "read", "path": "/project/..hidden/file.txt"},
            context={}
        )

        # '..hidden' is a valid directory name, not a traversal -- should pass
        assert result.valid


class TestForbiddenDirectories:
    """Tests for forbidden directory protection."""

    def test_etc_directory_blocked(self):
        """Test that /etc/ is blocked."""
        policy = FileAccessPolicy()

        result = policy.validate(
            action={"operation": "read", "path": "/etc/passwd"},
            context={}
        )

        assert not result.valid
        assert result.violations[0].severity == ViolationSeverity.CRITICAL
        # Can be blocked as either forbidden file or forbidden directory
        assert "forbidden" in result.violations[0].message.lower()

    def test_sys_directory_blocked(self):
        """Test that /sys/ is blocked."""
        policy = FileAccessPolicy()

        result = policy.validate(
            action={"operation": "read", "path": "/sys/kernel/config"},
            context={}
        )

        assert not result.valid

    def test_proc_directory_blocked(self):
        """Test that /proc/ is blocked."""
        policy = FileAccessPolicy()

        result = policy.validate(
            action={"operation": "read", "path": "/proc/cpuinfo"},
            context={}
        )

        assert not result.valid

    def test_root_directory_blocked(self):
        """Test that /root/ is blocked."""
        policy = FileAccessPolicy()

        result = policy.validate(
            action={"operation": "read", "path": "/root/.bashrc"},
            context={}
        )

        assert not result.valid

    def test_custom_forbidden_directories(self):
        """Test adding custom forbidden directories."""
        config = {
            "forbidden_directories": ["/secrets"]
        }
        policy = FileAccessPolicy(config)

        result = policy.validate(
            action={"operation": "read", "path": "/secrets/api_key.txt"},
            context={}
        )

        assert not result.valid

    def test_subdirectory_of_forbidden_blocked(self):
        """Test that subdirectories of forbidden dirs are blocked."""
        policy = FileAccessPolicy()

        result = policy.validate(
            action={"operation": "read", "path": "/etc/apache2/sites-enabled/default"},
            context={}
        )

        assert not result.valid


class TestForbiddenFiles:
    """Tests for forbidden file protection."""

    def test_env_file_blocked(self):
        """Test that .env files are blocked."""
        policy = FileAccessPolicy()

        result = policy.validate(
            action={"operation": "read", "path": "/.env"},
            context={}
        )

        assert not result.valid
        assert result.violations[0].severity == ViolationSeverity.CRITICAL

    def test_passwd_file_blocked(self):
        """Test that /etc/passwd is blocked."""
        policy = FileAccessPolicy()

        result = policy.validate(
            action={"operation": "read", "path": "/etc/passwd"},
            context={}
        )

        assert not result.valid

    def test_shadow_file_blocked(self):
        """Test that /etc/shadow is blocked."""
        policy = FileAccessPolicy()

        result = policy.validate(
            action={"operation": "read", "path": "/etc/shadow"},
            context={}
        )

        assert not result.valid

    def test_env_file_in_project_blocked(self):
        """Test that .env in various locations is blocked."""
        policy = FileAccessPolicy()

        # Absolute .env file
        result = policy.validate(
            action={"operation": "read", "path": "/project/.env"},
            context={}
        )

        # Should be blocked as it ends with /.env
        assert not result.valid


class TestForbiddenExtensions:
    """Tests for forbidden file extension blocking."""

    def test_pem_file_blocked(self):
        """Test that .pem files are blocked."""
        policy = FileAccessPolicy()

        result = policy.validate(
            action={"operation": "read", "path": "/project/cert.pem"},
            context={}
        )

        # Will fail because .pem is forbidden (not because of path)
        violations = [v for v in result.violations if "extension" in v.message.lower()]
        assert len(violations) >= 1

    def test_key_file_blocked(self):
        """Test that .key files are blocked."""
        policy = FileAccessPolicy()

        result = policy.validate(
            action={"operation": "read", "path": "/project/private.key"},
            context={}
        )

        violations = [v for v in result.violations if "extension" in v.message.lower()]
        assert len(violations) >= 1

    def test_custom_forbidden_extensions(self):
        """Test custom forbidden extensions."""
        config = {
            "forbidden_extensions": [".secret", ".private"]
        }
        policy = FileAccessPolicy(config)

        result = policy.validate(
            action={"operation": "read", "path": "/project/data.secret"},
            context={}
        )

        assert not result.valid

    def test_case_insensitive_extension_matching(self):
        """Test that extension matching is case-insensitive."""
        policy = FileAccessPolicy()

        result = policy.validate(
            action={"operation": "read", "path": "/project/cert.PEM"},
            context={}
        )

        violations = [v for v in result.violations if "extension" in v.message.lower()]
        assert len(violations) >= 1


class TestAllowlistMode:
    """Tests for allowlist (whitelist) mode."""

    def test_allowed_path_exact_match(self):
        """Test exact path match in allowlist."""
        config = {
            "allowed_paths": ["/project/src/main.py"]
        }
        policy = FileAccessPolicy(config)

        result = policy.validate(
            action={"operation": "read", "path": "/project/src/main.py"},
            context={}
        )

        assert result.valid

    def test_not_in_allowlist_blocked(self):
        """Test that paths not in allowlist are blocked."""
        config = {
            "allowed_paths": ["/project/src/**"]
        }
        policy = FileAccessPolicy(config)

        # Use a path that's not forbidden, just not in allowlist
        result = policy.validate(
            action={"operation": "read", "path": "/home/user/data.txt"},
            context={}
        )

        assert not result.valid
        violations = [v for v in result.violations if "allowlist" in v.message.lower()]
        assert len(violations) >= 1

    def test_wildcard_pattern_matching(self):
        """Test wildcard pattern in allowlist."""
        config = {
            "allowed_paths": ["/project/*.py"]
        }
        policy = FileAccessPolicy(config)

        result = policy.validate(
            action={"operation": "read", "path": "/project/main.py"},
            context={}
        )

        assert result.valid

    def test_recursive_wildcard_matching(self):
        """Test recursive wildcard (**) in allowlist."""
        config = {
            "allowed_paths": ["/project/**/*.py"]
        }
        policy = FileAccessPolicy(config)

        # Should match nested paths
        result = policy.validate(
            action={"operation": "read", "path": "/project/src/utils/helper.py"},
            context={}
        )

        assert result.valid

    def test_directory_prefix_matching(self):
        """Test directory prefix pattern in allowlist."""
        config = {
            "allowed_paths": ["/project/src/"]
        }
        policy = FileAccessPolicy(config)

        result = policy.validate(
            action={"operation": "read", "path": "/project/src/main.py"},
            context={}
        )

        assert result.valid

    def test_multiple_allowed_paths(self):
        """Test multiple allowed path patterns."""
        config = {
            "allowed_paths": ["/project/src/**", "/tmp/**", "/data/output/**"]
        }
        policy = FileAccessPolicy(config)

        # All should be allowed
        paths = [
            "/project/src/main.py",
            "/tmp/cache/data.json",
            "/data/output/results.csv"
        ]

        for path in paths:
            result = policy.validate(
                action={"operation": "read", "path": path},
                context={}
            )
            assert result.valid, f"Path {path} should be allowed"


class TestDenylistMode:
    """Tests for denylist (blacklist) mode."""

    def test_denied_path_blocked(self):
        """Test that denied paths are blocked."""
        config = {
            "denied_paths": ["/secrets/**"]
        }
        policy = FileAccessPolicy(config)

        result = policy.validate(
            action={"operation": "read", "path": "/secrets/api_key.txt"},
            context={}
        )

        assert not result.valid
        violations = [v for v in result.violations if "denylist" in v.message.lower()]
        assert len(violations) >= 1

    def test_not_in_denylist_allowed(self):
        """Test that paths not in denylist are allowed."""
        config = {
            "denied_paths": ["/etc/**", "/root/**"]
        }
        policy = FileAccessPolicy(config)

        # Access to /project should be allowed (not in denylist, not forbidden)
        result = policy.validate(
            action={"operation": "read", "path": "/home/user/project/main.py"},
            context={}
        )

        assert result.valid

    def test_denylist_wildcard_matching(self):
        """Test wildcard in denylist."""
        config = {
            "denied_paths": ["/project/*.log"]
        }
        policy = FileAccessPolicy(config)

        result = policy.validate(
            action={"operation": "read", "path": "/project/debug.log"},
            context={}
        )

        assert not result.valid


class TestAbsoluteAndRelativePaths:
    """Tests for absolute vs relative path handling."""

    def test_absolute_path_allowed_by_default(self):
        """Test that absolute paths are allowed by default."""
        config = {
            "allowed_paths": ["/project/**"]
        }
        policy = FileAccessPolicy(config)

        result = policy.validate(
            action={"operation": "read", "path": "/project/main.py"},
            context={}
        )

        assert result.valid

    def test_absolute_path_blocked_when_configured(self):
        """Test blocking absolute paths."""
        config = {
            "allow_absolute_paths": False
        }
        policy = FileAccessPolicy(config)

        result = policy.validate(
            action={"operation": "read", "path": "/project/main.py"},
            context={}
        )

        assert not result.valid
        violations = [v for v in result.violations if "absolute" in v.message.lower()]
        assert len(violations) >= 1

    def test_relative_path_allowed(self):
        """Test that relative paths work."""
        config = {
            "allowed_paths": ["project/**"]
        }
        policy = FileAccessPolicy(config)

        result = policy.validate(
            action={"operation": "read", "path": "project/main.py"},
            context={}
        )

        assert result.valid


class TestBatchOperations:
    """Tests for validating multiple paths in a single action."""

    def test_multiple_paths_in_action(self):
        """Test validating action with multiple paths."""
        config = {
            "allowed_paths": ["/project/**"]
        }
        policy = FileAccessPolicy(config)

        result = policy.validate(
            action={
                "operation": "batch_read",
                "paths": [
                    "/project/src/main.py",
                    "/project/src/utils.py",
                    "/project/tests/test_main.py"
                ]
            },
            context={}
        )

        assert result.valid
        assert result.metadata["paths_checked"] == 3

    def test_batch_with_one_violation(self):
        """Test batch where one path violates policy."""
        config = {
            "allowed_paths": ["/project/**"]
        }
        policy = FileAccessPolicy(config)

        result = policy.validate(
            action={
                "operation": "batch_read",
                "paths": [
                    "/project/main.py",
                    "/etc/passwd",  # Forbidden
                    "/project/utils.py"
                ]
            },
            context={}
        )

        assert not result.valid
        assert len(result.violations) >= 1

    def test_source_destination_paths(self):
        """Test actions with source and destination paths."""
        config = {
            "allowed_paths": ["/project/**"]
        }
        policy = FileAccessPolicy(config)

        result = policy.validate(
            action={
                "operation": "copy",
                "source": "/project/data.txt",
                "destination": "/project/backup/data.txt"
            },
            context={}
        )

        assert result.valid
        assert result.metadata["paths_checked"] == 2


class TestCaseSensitivity:
    """Tests for case-sensitive path matching."""

    def test_case_sensitive_by_default(self):
        """Test that matching is case-sensitive by default."""
        config = {
            "allowed_paths": ["/Project/**"]
        }
        policy = FileAccessPolicy(config)

        # Lowercase 'project' should not match uppercase 'Project'
        result = policy.validate(
            action={"operation": "read", "path": "/project/main.py"},
            context={}
        )

        # Should fail allowlist check
        assert not result.valid

    def test_case_insensitive_mode(self):
        """Test case-insensitive matching."""
        config = {
            "allowed_paths": ["/PROJECT/**"],
            "case_sensitive": False
        }
        policy = FileAccessPolicy(config)

        # Lowercase should match uppercase
        result = policy.validate(
            action={"operation": "read", "path": "/project/main.py"},
            context={}
        )

        assert result.valid


class TestComplexCases:
    """Tests for complex real-world scenarios."""

    def test_strict_project_isolation(self):
        """Test strict isolation to project directory."""
        config = {
            "allowed_paths": ["/home/user/project/**"],
            "allow_parent_traversal": False,
            "allow_symlinks": False
        }
        policy = FileAccessPolicy(config)

        # Allowed access
        result = policy.validate(
            action={"operation": "read", "path": "/home/user/project/src/main.py"},
            context={"agent": "coder"}
        )
        assert result.valid

        # Attempt to escape via traversal
        result = policy.validate(
            action={"operation": "read", "path": "/home/user/project/../.ssh/id_rsa"},
            context={"agent": "coder"}
        )
        assert not result.valid

        # Access outside project
        result = policy.validate(
            action={"operation": "read", "path": "/etc/passwd"},
            context={"agent": "coder"}
        )
        assert not result.valid

    def test_read_only_access_pattern(self):
        """Test read-only access to specific directories."""
        config = {
            "allowed_paths": ["/data/readonly/**"],
            "denied_paths": []  # Explicit denylist mode
        }
        policy = FileAccessPolicy(config)

        # Read allowed
        result = policy.validate(
            action={"operation": "read", "path": "/data/readonly/config.json"},
            context={}
        )
        assert result.valid

        # Write to same path - policy doesn't distinguish operations,
        # but action tracking would catch this
        result = policy.validate(
            action={"operation": "write", "path": "/data/readonly/config.json"},
            context={}
        )
        # From policy perspective, path is allowed
        assert result.valid

    def test_temporary_file_access(self):
        """Test access restricted to temporary directories."""
        config = {
            "allowed_paths": ["/tmp/**", "/var/tmp/**"]
        }
        policy = FileAccessPolicy(config)

        # Temp access allowed
        result = policy.validate(
            action={"operation": "write", "path": "/tmp/output.txt"},
            context={}
        )
        assert result.valid

        # Non-temp blocked
        result = policy.validate(
            action={"operation": "write", "path": "/home/user/output.txt"},
            context={}
        )
        assert not result.valid


class TestViolationMetadata:
    """Tests for violation metadata and error messages."""

    def test_violation_includes_path(self):
        """Test that violations include the problematic path."""
        policy = FileAccessPolicy()

        result = policy.validate(
            action={"operation": "read", "path": "/etc/passwd"},
            context={}
        )

        assert not result.valid
        assert "path" in result.violations[0].metadata
        assert result.violations[0].metadata["path"] == "/etc/passwd"

    def test_violation_includes_type(self):
        """Test that violations include violation type."""
        policy = FileAccessPolicy()

        result = policy.validate(
            action={"operation": "read", "path": "/etc/passwd"},
            context={}
        )

        assert "violation" in result.violations[0].metadata
        violation_type = result.violations[0].metadata["violation"]
        assert violation_type in ["forbidden_directory", "forbidden_file"]

    def test_remediation_hints_are_helpful(self):
        """Test that remediation hints provide actionable guidance."""
        config = {
            "allowed_paths": ["/project/**"]
        }
        policy = FileAccessPolicy(config)

        result = policy.validate(
            action={"operation": "read", "path": "/etc/passwd"},
            context={}
        )

        # Should have remediation hint
        assert result.violations[0].remediation_hint is not None
        assert len(result.violations[0].remediation_hint) > 0


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_empty_path(self):
        """Test handling of empty path."""
        policy = FileAccessPolicy()

        result = policy.validate(
            action={"operation": "read", "path": ""},
            context={}
        )

        # Should handle gracefully (likely invalid, but no crash)
        assert result.valid or not result.valid  # Either outcome is ok, just no crash

    def test_root_path(self):
        """Test handling of root path /."""
        policy = FileAccessPolicy()

        result = policy.validate(
            action={"operation": "read", "path": "/"},
            context={}
        )

        # Root should be handled (likely blocked, but no crash)
        assert isinstance(result.valid, bool)

    def test_action_without_paths(self):
        """Test action with no path information."""
        policy = FileAccessPolicy()

        result = policy.validate(
            action={"operation": "status"},
            context={}
        )

        # Should validate successfully (no paths to check)
        assert result.valid

    def test_path_with_special_characters(self):
        """Test paths with special characters."""
        config = {
            "allowed_paths": ["/project/**"]
        }
        policy = FileAccessPolicy(config)

        result = policy.validate(
            action={"operation": "read", "path": "/project/file with spaces.txt"},
            context={}
        )

        assert result.valid

    def test_unicode_paths(self):
        """Test paths with unicode characters."""
        config = {
            "allowed_paths": ["/project/**"]
        }
        policy = FileAccessPolicy(config)

        result = policy.validate(
            action={"operation": "read", "path": "/project/文件.txt"},
            context={}
        )

        assert result.valid


class TestPathNormalizationSecurity:
    """Tests that path normalization resolves .. before forbidden directory checks."""

    def test_traversal_to_forbidden_dir_blocked_with_allow_parent(self):
        """Paths like /allowed/../etc/passwd must be blocked even when allow_parent_traversal=True.

        The .. component must be resolved by normpath BEFORE the forbidden directory
        check, so /allowed/../etc/passwd becomes /etc/passwd and is rejected.
        """
        config = {
            "allow_parent_traversal": True,
            "allowed_paths": ["/allowed/**", "/etc/**"],
        }
        policy = FileAccessPolicy(config)

        result = policy.validate(
            action={"operation": "read", "path": "/allowed/../etc/passwd"},
            context={}
        )

        assert not result.valid
        has_forbidden = any(
            "forbidden" in v.message.lower()
            for v in result.violations
        )
        assert has_forbidden

    def test_normpath_resolves_dotdot_for_denylist(self):
        """Normalization must resolve .. so denylist matches work correctly."""
        config = {
            "allow_parent_traversal": True,
            "denied_paths": ["/secrets/**"],
        }
        policy = FileAccessPolicy(config)

        result = policy.validate(
            action={"operation": "read", "path": "/project/../secrets/key.pem"},
            context={}
        )

        assert not result.valid

    def test_normal_paths_unaffected_by_normpath(self):
        """Regular paths without .. should still work after normpath fix."""
        config = {
            "allowed_paths": ["/project/**"],
        }
        policy = FileAccessPolicy(config)

        result = policy.validate(
            action={"operation": "read", "path": "/project/src/main.py"},
            context={}
        )

        assert result.valid
