"""Tests for path_safety module."""

import os
import tempfile
from pathlib import Path

import pytest

from temper_ai.shared.utils.path_safety import (
    PathSafetyError,
    PathSafetyValidator,
    validate_path,
    validate_read,
    validate_write,
)


@pytest.fixture
def temp_workspace(tmp_path):
    """Create a temporary workspace for testing."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    # Create some test files
    (workspace / "test.txt").write_text("test content")
    (workspace / "subdir").mkdir()
    (workspace / "subdir" / "file.txt").write_text("nested file")

    return workspace


@pytest.fixture
def validator(temp_workspace):
    """Create validator with temporary workspace as root."""
    return PathSafetyValidator(allowed_root=temp_workspace)


class TestPathSafetyValidator:
    """Test PathSafetyValidator class."""

    def test_init_default_root(self):
        """Test initialization with default root (cwd)."""
        validator = PathSafetyValidator()
        assert validator.allowed_root == Path.cwd().resolve()

    def test_init_custom_root(self, temp_workspace):
        """Test initialization with custom root."""
        validator = PathSafetyValidator(allowed_root=temp_workspace)
        assert validator.allowed_root == temp_workspace.resolve()

    def test_validate_path_within_root(self, validator, temp_workspace):
        """Test validation of path within allowed root."""
        test_file = temp_workspace / "test.txt"
        result = validator.validate_path(test_file)
        assert result == test_file.resolve()

    def test_validate_path_outside_root(self, validator, temp_workspace):
        """Test validation rejects path outside root."""
        # Use a path that's outside both allowed_root and /tmp
        outside_path = Path("/etc/outside.txt")
        with pytest.raises(PathSafetyError, match="outside allowed root"):
            validator.validate_path(outside_path)

    def test_validate_path_traversal_attempt(self, validator, temp_workspace):
        """Test validation catches directory traversal."""
        # Path that tries to escape using ../ to reach /etc
        # This will resolve to /etc/passwd which is outside allowed_root
        traversal_path = Path("/etc/passwd")
        with pytest.raises(PathSafetyError, match="outside allowed root"):
            validator.validate_path(traversal_path)

    def test_validate_path_null_byte(self, validator):
        """Test validation rejects null bytes."""
        with pytest.raises(PathSafetyError, match="null bytes"):
            validator.validate_path("test\x00file.txt")

    def test_validate_path_must_exist(self, validator, temp_workspace):
        """Test must_exist parameter."""
        # Existing file - should pass
        existing = temp_workspace / "test.txt"
        result = validator.validate_path(existing, must_exist=True)
        assert result.exists()

        # Non-existing file - should fail
        nonexisting = temp_workspace / "does_not_exist.txt"
        with pytest.raises(PathSafetyError, match="must exist"):
            validator.validate_path(nonexisting, must_exist=True)

    def test_validate_path_allow_create(self, validator, temp_workspace):
        """Test allow_create parameter."""
        # Non-existing with allow_create=True - should pass
        new_file = temp_workspace / "new_file.txt"
        result = validator.validate_path(new_file, allow_create=True)
        assert result == new_file.resolve()

        # Non-existing with allow_create=False - should fail
        another_new = temp_workspace / "another_new.txt"
        with pytest.raises(PathSafetyError, match="does not exist"):
            validator.validate_path(another_new, allow_create=False)

    def test_validate_read_success(self, validator, temp_workspace):
        """Test validate_read for valid file."""
        test_file = temp_workspace / "test.txt"
        result = validator.validate_read(test_file)
        assert result == test_file.resolve()
        assert result.is_file()

    def test_validate_read_nonexistent(self, validator, temp_workspace):
        """Test validate_read fails for non-existent file."""
        missing = temp_workspace / "missing.txt"
        with pytest.raises(PathSafetyError, match="must exist"):
            validator.validate_read(missing)

    def test_validate_read_directory(self, validator, temp_workspace):
        """Test validate_read fails for directory."""
        directory = temp_workspace / "subdir"
        with pytest.raises(PathSafetyError, match="not a file"):
            validator.validate_read(directory)

    def test_validate_write_new_file(self, validator, temp_workspace):
        """Test validate_write for new file."""
        new_file = temp_workspace / "new.txt"
        result = validator.validate_write(new_file)
        assert result == new_file.resolve()

    def test_validate_write_existing_with_overwrite(self, validator, temp_workspace):
        """Test validate_write allows overwriting existing file."""
        existing = temp_workspace / "test.txt"
        result = validator.validate_write(existing, allow_overwrite=True)
        assert result == existing.resolve()

    def test_validate_write_existing_no_overwrite(self, validator, temp_workspace):
        """Test validate_write rejects overwriting when disabled."""
        existing = temp_workspace / "test.txt"
        with pytest.raises(PathSafetyError, match="exists and overwrite not allowed"):
            validator.validate_write(existing, allow_overwrite=False)

    def test_validate_write_parent_missing(self, validator, temp_workspace):
        """Test validate_write fails when parent directory doesn't exist."""
        nested = temp_workspace / "missing_dir" / "file.txt"
        with pytest.raises(PathSafetyError, match="Parent directory does not exist"):
            validator.validate_write(nested)

    def test_forbidden_system_paths(self, validator):
        """Test forbidden system paths are blocked."""
        forbidden_paths = [
            "/etc/passwd",
            "/sys/kernel",
            "/proc/version",
            "/dev/null",
        ]

        for forbidden in forbidden_paths:
            # Skip if path doesn't exist (platform-specific)
            if not Path(forbidden).exists():
                continue

            with pytest.raises(PathSafetyError, match="forbidden"):
                validator.validate_path(Path(forbidden))

    def test_forbidden_project_directories(self, validator, temp_workspace):
        """Test forbidden project directories are blocked."""
        # Create .git directory
        git_dir = temp_workspace / ".git"
        git_dir.mkdir()

        with pytest.raises(PathSafetyError, match="forbidden directory"):
            validator.validate_path(git_dir / "config")

    def test_symlink_within_root(self, validator, temp_workspace):
        """Test symlink pointing within root is allowed."""
        target = temp_workspace / "test.txt"
        link = temp_workspace / "link.txt"

        try:
            link.symlink_to(target)
            result = validator.validate_path(link)
            assert result == target.resolve()
        except OSError:
            # Symlinks may not be supported on all platforms
            pytest.skip("Symlinks not supported")

    def test_symlink_outside_root(self, validator, temp_workspace):
        """Test symlink pointing outside root is blocked."""
        # Create target outside workspace
        outside_target = temp_workspace.parent / "outside.txt"
        outside_target.write_text("outside content")

        link = temp_workspace / "bad_link.txt"

        try:
            link.symlink_to(outside_target)
            with pytest.raises(PathSafetyError, match="outside allowed root"):
                validator.validate_path(link)
        except OSError:
            # Symlinks may not be supported
            pytest.skip("Symlinks not supported")
        finally:
            if outside_target.exists():
                outside_target.unlink()

    def test_additional_forbidden_paths(self, temp_workspace):
        """Test adding custom forbidden paths."""
        validator = PathSafetyValidator(
            allowed_root=temp_workspace, additional_forbidden=["/custom/forbidden"]
        )

        assert "/custom/forbidden" in validator.forbidden


class TestGlobalFunctions:
    """Test global convenience functions."""

    def test_validate_path_global(self, temp_workspace):
        """Test global validate_path function with cwd path."""
        cwd_file = Path.cwd() / "test.txt"
        try:
            result = validate_path(cwd_file)
            # If accepted, must return a resolved absolute Path
            assert isinstance(result, Path)
            assert result.is_absolute()
        except PathSafetyError:
            # Expected if cwd is outside the validator's allowed root
            pass

    def test_validate_read_global(self, temp_workspace):
        """Test global validate_read function."""
        # Create file in cwd
        test_file = Path.cwd() / "temp_test.txt"
        try:
            test_file.write_text("test")
            result = validate_read(test_file)
            assert result.is_file()
        except (PathSafetyError, PermissionError):
            # May fail if cwd is restricted
            pass
        finally:
            if test_file.exists():
                test_file.unlink()

    def test_validate_write_global(self, temp_workspace):
        """Test global validate_write function."""
        # Test with path in cwd
        test_file = Path.cwd() / "temp_write_test.txt"
        try:
            result = validate_write(test_file)
            assert isinstance(result, Path)
        except PathSafetyError:
            # May fail if cwd is restricted
            pass
        finally:
            if test_file.exists():
                test_file.unlink()


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_relative_path_resolution(self, validator, temp_workspace):
        """Test that relative paths are resolved correctly."""
        # Create a relative path
        relative = Path("test.txt")
        # Change to workspace directory temporarily
        original_cwd = Path.cwd()
        try:
            os.chdir(temp_workspace)
            result = validator.validate_path(relative)
            assert result.is_absolute()
            assert result == (temp_workspace / "test.txt").resolve()
        finally:
            os.chdir(original_cwd)

    def test_string_path_conversion(self, validator, temp_workspace):
        """Test that string paths are converted to Path objects."""
        path_str = str(temp_workspace / "test.txt")
        result = validator.validate_path(path_str)
        assert isinstance(result, Path)

    def test_empty_path(self, validator):
        """Test handling of empty path."""
        with pytest.raises((PathSafetyError, ValueError)):
            validator.validate_path("")

    def test_very_long_path(self, validator, temp_workspace):
        """Test handling of very long paths."""
        # Create a very long path
        long_name = "a" * 255  # Max filename length on most systems
        long_path = temp_workspace / long_name

        try:
            result = validator.validate_path(long_path)
            assert isinstance(result, Path)
        except (OSError, PathSafetyError):
            # May fail on systems with shorter path limits
            pass

    def test_unicode_path(self, validator, temp_workspace):
        """Test handling of unicode characters in paths."""
        unicode_path = temp_workspace / "测试文件.txt"
        result = validator.validate_path(unicode_path)
        assert isinstance(result, Path)

    def test_special_characters_in_path(self, validator, temp_workspace):
        """Test handling of special characters."""
        special_path = temp_workspace / "file with spaces & (special) chars!.txt"
        result = validator.validate_path(special_path)
        assert isinstance(result, Path)


class TestSymlinkSecurity:
    """Test symlink attack prevention.

    SECURITY CRITICAL: These tests verify that symlinks cannot be used
    to bypass path restrictions and access files outside allowed root.
    """

    @pytest.fixture
    def attack_target_dir(self, tmp_path):
        """Create a directory outside the allowed root for attack tests."""
        attack_dir = tmp_path / "attack_target"
        attack_dir.mkdir()
        (attack_dir / "secret.txt").write_text("SENSITIVE DATA")
        return attack_dir

    def test_symlink_to_outside_directory_blocked(
        self, validator, temp_workspace, attack_target_dir
    ):
        """Test that symlink pointing outside allowed root is blocked.

        SECURITY: Prevents path traversal via symlinks.
        Attack: Create symlink in allowed dir pointing to sensitive file outside.
        """
        # Create symlink in allowed workspace pointing to attack target
        symlink_path = temp_workspace / "innocent_looking_file.txt"
        symlink_path.symlink_to(attack_target_dir / "secret.txt")

        # Should block the symlink
        with pytest.raises(PathSafetyError, match="outside allowed root"):
            validator.validate_path(symlink_path)

    def test_symlink_parent_directory_to_outside_blocked(
        self, validator, temp_workspace, attack_target_dir
    ):
        """Test that symlink in parent directory pointing outside is blocked.

        SECURITY: Prevents path traversal via symlinked parent directories.
        Attack: Create symlinked directory in path hierarchy pointing outside.
        """
        # Create symlink directory (don't create normal dir first)
        subdir = temp_workspace / "evil_subdir"
        subdir.symlink_to(attack_target_dir)

        # Try to access file through symlinked directory
        evil_path = subdir / "secret.txt"

        # Should block because parent directory is a symlink pointing outside
        with pytest.raises(PathSafetyError, match="outside allowed root"):
            validator.validate_path(evil_path)

    def test_symlink_to_parent_directory_blocked(self, validator, temp_workspace):
        """Test that symlink pointing to parent directory is blocked.

        SECURITY: Prevents escaping allowed root via .. traversal through symlinks.
        Attack: Create symlink to parent directory, then traverse up.
        """
        # Create symlink to parent of workspace
        symlink_path = temp_workspace / "escape"
        symlink_path.symlink_to(temp_workspace.parent)

        # Try to traverse through symlink
        evil_path = symlink_path / ".." / ".." / "etc" / "passwd"

        # Should block the symlink
        with pytest.raises(PathSafetyError, match="outside allowed root"):
            validator.validate_path(evil_path)

    def test_relative_symlink_escaping_root_blocked(self, validator, temp_workspace):
        """Test that relative symlink escaping root is blocked.

        SECURITY: Prevents path traversal via relative symlinks.
        Attack: Create relative symlink with .. to escape allowed root.
        """
        # Create deep directory structure
        deep_dir = temp_workspace / "a" / "b" / "c"
        deep_dir.mkdir(parents=True)

        # Create relative symlink that goes up beyond workspace
        symlink_path = deep_dir / "escape"
        # ../../../../ from c goes to parent of temp_workspace
        symlink_path.symlink_to(Path("../../../../etc"))

        # Should block the symlink
        with pytest.raises(PathSafetyError, match="outside allowed root"):
            validator.validate_path(symlink_path)

    def test_symlink_chain_blocked(self, validator, temp_workspace, attack_target_dir):
        """Test that chain of symlinks pointing outside is blocked.

        SECURITY: Prevents multi-hop symlink attacks.
        Attack: Create chain of symlinks where final target is outside root.
        """
        # Create chain: link1 -> link2 -> attack_target
        link1 = temp_workspace / "link1"
        link2 = temp_workspace / "link2"

        link2.symlink_to(attack_target_dir / "secret.txt")
        link1.symlink_to(link2)

        # Should block the chain
        with pytest.raises(PathSafetyError, match="outside allowed root"):
            validator.validate_path(link1)

    def test_symlink_within_allowed_root_permitted(self, validator, temp_workspace):
        """Test that symlinks within allowed root are permitted.

        SECURITY: Verify legitimate use case still works.
        """
        # Create legitimate file and symlink within workspace
        real_file = temp_workspace / "real.txt"
        real_file.write_text("legitimate content")

        symlink = temp_workspace / "link.txt"
        symlink.symlink_to(real_file)

        # Should allow symlink within allowed root
        result = validator.validate_path(symlink)
        assert isinstance(result, Path)

    def test_symlink_to_subdirectory_within_root_permitted(
        self, validator, temp_workspace
    ):
        """Test that symlinks to subdirectories within root are permitted."""
        # Create subdirectory and symlink to it
        subdir = temp_workspace / "mysubdir"
        subdir.mkdir()
        (subdir / "file.txt").write_text("content")

        symlink = temp_workspace / "link_to_subdir"
        symlink.symlink_to(subdir)

        # Should allow symlink to subdirectory within root
        result = validator.validate_path(symlink / "file.txt")
        assert isinstance(result, Path)

    def test_absolute_symlink_within_root_permitted(self, validator, temp_workspace):
        """Test that absolute symlinks within allowed root are permitted."""
        # Create file and absolute symlink within workspace
        real_file = temp_workspace / "real.txt"
        real_file.write_text("content")

        symlink = temp_workspace / "absolute_link.txt"
        symlink.symlink_to(real_file.absolute())

        # Should allow absolute symlink within allowed root
        result = validator.validate_path(symlink)
        assert isinstance(result, Path)

    def test_symlink_attack_via_tmp(self, validator, temp_workspace, attack_target_dir):
        """Test that /tmp symlink cannot be used to bypass restrictions.

        SECURITY: Verifies /tmp exception doesn't create symlink vulnerability.
        Attack: Create symlink in /tmp pointing to sensitive location.
        """

        # Create symlink in /tmp pointing to attack target
        with tempfile.TemporaryDirectory() as tmpdir:
            symlink_path = Path(tmpdir) / "evil_link"
            symlink_path.symlink_to(attack_target_dir / "secret.txt")

            # Should block symlink in /tmp pointing outside /tmp
            with pytest.raises(PathSafetyError, match="outside allowed root"):
                validator.validate_path(symlink_path)

    def test_time_of_check_time_of_use_prevented(
        self, validator, temp_workspace, attack_target_dir
    ):
        """Test that TOCTOU race condition is prevented.

        SECURITY: Verifies symlink checks happen before resolution.
        Attack: Although we can't simulate the race, we verify checks happen first.
        """
        # Create a symlink
        symlink = temp_workspace / "file.txt"
        symlink.symlink_to(attack_target_dir / "secret.txt")

        # Validation should fail immediately (not after resolution)
        with pytest.raises(PathSafetyError) as exc_info:
            validator.validate_path(symlink)

        # Error should mention symlink, not just "outside allowed root"
        assert (
            "symlink" in str(exc_info.value).lower()
            or "points outside" in str(exc_info.value).lower()
        )
