"""
Security tests for /tmp path traversal vulnerability fix (code-crit-13).

Ensures that /tmp access is blocked and dedicated temp directory prevents:
- Cross-user file access
- Symlink attacks
- Path traversal outside allowed_root
- TOCTOU vulnerabilities
"""
from pathlib import Path

import pytest

from src.utils.path_safety import PathSafetyError, PathSafetyValidator


class TestTmpAccessBlocked:
    """Test that /tmp paths are rejected after security fix."""

    def test_tmp_file_access_blocked(self, tmp_path):
        """Verify /tmp file paths are rejected."""
        validator = PathSafetyValidator(allowed_root=tmp_path)

        # Try to access /tmp path (may or may not exist)
        tmp_file = Path("/tmp/test_file.txt")

        # Should reject /tmp path regardless of existence
        with pytest.raises(PathSafetyError, match="outside allowed root"):
            validator.validate_path(tmp_file, must_exist=False)

    def test_tmp_directory_access_blocked(self, tmp_path):
        """Verify /tmp directory paths are rejected."""
        validator = PathSafetyValidator(allowed_root=tmp_path)

        # Should reject /tmp itself
        with pytest.raises(PathSafetyError, match="outside allowed root"):
            validator.validate_path("/tmp")

    def test_tmp_subdirectory_blocked(self, tmp_path):
        """Verify /tmp subdirectories are rejected."""
        validator = PathSafetyValidator(allowed_root=tmp_path)

        # Create subdirectory in /tmp
        tmp_subdir = Path("/tmp/test_subdir")
        try:
            tmp_subdir.mkdir(exist_ok=True)

            # Should reject /tmp subdirectory
            with pytest.raises(PathSafetyError, match="outside allowed root"):
                validator.validate_path(tmp_subdir)
        finally:
            tmp_subdir.rmdir()

    def test_tmp_write_blocked(self, tmp_path):
        """Verify writing to /tmp is blocked."""
        validator = PathSafetyValidator(allowed_root=tmp_path)

        tmp_file = Path("/tmp/write_test.txt")

        # Should reject write to /tmp
        with pytest.raises(PathSafetyError, match="outside allowed root"):
            validator.validate_write(tmp_file)

    def test_tmp_read_blocked(self, tmp_path):
        """Verify reading from /tmp is blocked."""
        validator = PathSafetyValidator(allowed_root=tmp_path)

        # Create file in /tmp
        tmp_file = Path("/tmp/read_test.txt")
        try:
            tmp_file.write_text("sensitive data")

            # Should reject read from /tmp
            with pytest.raises(PathSafetyError, match="outside allowed root"):
                validator.validate_read(tmp_file)
        finally:
            tmp_file.unlink(missing_ok=True)


class TestSymlinkAttacksPrevented:
    """Test that symlink attacks via /tmp are prevented."""

    def test_tmp_symlink_to_sensitive_file_blocked(self, tmp_path):
        """Verify symlink in /tmp pointing to sensitive file is blocked."""
        validator = PathSafetyValidator(allowed_root=tmp_path)

        # Create sensitive file outside allowed root
        sensitive_file = tmp_path.parent / "secret.txt"
        sensitive_file.write_text("SENSITIVE DATA")

        # Create symlink in /tmp
        tmp_symlink = Path("/tmp/innocent_link")

        try:
            tmp_symlink.symlink_to(sensitive_file)

            # Should reject symlink in /tmp
            with pytest.raises(PathSafetyError, match="outside allowed root"):
                validator.validate_path(tmp_symlink)
        finally:
            tmp_symlink.unlink(missing_ok=True)
            sensitive_file.unlink(missing_ok=True)

    def test_tmp_symlink_chain_blocked(self, tmp_path):
        """Verify multi-hop symlink chain through /tmp is blocked."""
        validator = PathSafetyValidator(allowed_root=tmp_path)

        # Create symlink chain in /tmp
        tmp_link1 = Path("/tmp/link1")
        tmp_link2 = Path("/tmp/link2")
        tmp_link3 = Path("/tmp/link3")
        target = tmp_path.parent / "target.txt"

        try:
            target.write_text("TARGET")
            tmp_link3.symlink_to(target)
            tmp_link2.symlink_to(tmp_link3)
            tmp_link1.symlink_to(tmp_link2)

            # Should reject first link in chain
            with pytest.raises(PathSafetyError, match="outside allowed root"):
                validator.validate_path(tmp_link1)
        finally:
            for link in [tmp_link1, tmp_link2, tmp_link3]:
                link.unlink(missing_ok=True)
            target.unlink(missing_ok=True)

    def test_tmp_symlink_to_system_file_blocked(self, tmp_path):
        """Verify symlink to system files (/etc/passwd) is blocked."""
        validator = PathSafetyValidator(allowed_root=tmp_path)

        tmp_symlink = Path("/tmp/passwd_link")

        try:
            # Symlink to /etc/passwd
            tmp_symlink.symlink_to("/etc/passwd")

            # Should reject
            with pytest.raises(PathSafetyError, match="outside allowed root"):
                validator.validate_path(tmp_symlink)
        finally:
            tmp_symlink.unlink(missing_ok=True)


class TestDedicatedTempDirectory:
    """Test dedicated temporary directory functionality."""

    def test_temp_directory_created(self, tmp_path):
        """Verify dedicated temp directory is created."""
        validator = PathSafetyValidator(allowed_root=tmp_path)

        assert validator.temp_dir is not None
        assert validator.temp_dir.exists()
        assert validator.temp_dir == tmp_path / ".tmp"

    def test_temp_directory_permissions(self, tmp_path):
        """Verify temp directory has owner-only permissions."""
        validator = PathSafetyValidator(allowed_root=tmp_path)

        # Check permissions (owner-only: 0o700)
        stat_result = validator.temp_dir.stat()
        mode = stat_result.st_mode & 0o777
        assert mode == 0o700, f"Expected 0o700, got {oct(mode)}"

    def test_temp_directory_within_allowed_root(self, tmp_path):
        """Verify temp directory is scoped to allowed_root."""
        validator = PathSafetyValidator(allowed_root=tmp_path)

        # Should be within allowed_root
        relative_path = validator.temp_dir.relative_to(validator.allowed_root)
        assert relative_path is not None
        assert validator.temp_dir.is_relative_to(validator.allowed_root)

    def test_temp_directory_can_be_disabled(self, tmp_path):
        """Verify temp directory can be disabled."""
        validator = PathSafetyValidator(
            allowed_root=tmp_path,
            enable_temp_directory=False
        )

        assert validator.temp_dir is None

    def test_get_temp_path_creates_valid_path(self, tmp_path):
        """Verify get_temp_path returns valid path."""
        validator = PathSafetyValidator(allowed_root=tmp_path)

        temp_file = validator.get_temp_path("test.txt")

        # Should be within allowed_root
        temp_file.relative_to(validator.allowed_root)

        # Should be in .tmp subdirectory
        assert temp_file.parent.name == ".tmp"

        # Should validate successfully
        validated = validator.validate_path(temp_file, must_exist=False)
        assert validated == temp_file

    def test_get_temp_path_rejects_path_traversal(self, tmp_path):
        """Verify get_temp_path blocks path traversal in filename."""
        validator = PathSafetyValidator(allowed_root=tmp_path)

        # Should reject path traversal
        with pytest.raises(PathSafetyError, match="no path components"):
            validator.get_temp_path("../etc/passwd")

        with pytest.raises(PathSafetyError, match="no path components"):
            validator.get_temp_path("../../secret.txt")

        with pytest.raises(PathSafetyError, match="no path components"):
            validator.get_temp_path("subdir/file.txt")

    def test_get_temp_path_rejects_long_filename(self, tmp_path):
        """Verify get_temp_path rejects excessively long filenames."""
        validator = PathSafetyValidator(allowed_root=tmp_path)

        # Create filename longer than MAX_COMPONENT_LENGTH
        long_filename = "a" * (validator.MAX_COMPONENT_LENGTH + 1)

        with pytest.raises(PathSafetyError, match="too long"):
            validator.get_temp_path(long_filename)

    def test_get_temp_path_when_disabled_raises_error(self, tmp_path):
        """Verify get_temp_path raises error when temp dir is disabled."""
        validator = PathSafetyValidator(
            allowed_root=tmp_path,
            enable_temp_directory=False
        )

        with pytest.raises(PathSafetyError, match="disabled"):
            validator.get_temp_path("test.txt")

    def test_cleanup_temp_directory_removes_files(self, tmp_path):
        """Verify cleanup_temp_directory removes all temp files."""
        validator = PathSafetyValidator(allowed_root=tmp_path)

        # Create temp files
        temp1 = validator.get_temp_path("file1.txt")
        temp2 = validator.get_temp_path("file2.txt")

        temp1.write_text("data1")
        temp2.write_text("data2")

        assert temp1.exists()
        assert temp2.exists()

        # Cleanup
        validator.cleanup_temp_directory()

        # Files should be removed
        assert not temp1.exists()
        assert not temp2.exists()

        # Temp directory should still exist
        assert validator.temp_dir.exists()

    def test_cleanup_temp_directory_recreates_with_secure_permissions(self, tmp_path):
        """Verify cleanup recreates temp dir with secure permissions."""
        validator = PathSafetyValidator(allowed_root=tmp_path)

        # Cleanup
        validator.cleanup_temp_directory()

        # Directory should exist with secure permissions
        assert validator.temp_dir.exists()
        stat_result = validator.temp_dir.stat()
        mode = stat_result.st_mode & 0o777
        assert mode == 0o700

    def test_cleanup_when_disabled_raises_error(self, tmp_path):
        """Verify cleanup raises error when temp dir is disabled."""
        validator = PathSafetyValidator(
            allowed_root=tmp_path,
            enable_temp_directory=False
        )

        with pytest.raises(PathSafetyError, match="disabled"):
            validator.cleanup_temp_directory()


class TestCrossUserAccessPrevented:
    """Test that cross-user file access is prevented."""

    def test_different_user_temp_dir_inaccessible(self, tmp_path):
        """Verify temp files from different validators are isolated."""
        # Simulate User A
        user_a_root = tmp_path / "user_a"
        user_a_root.mkdir()
        validator_a = PathSafetyValidator(allowed_root=user_a_root)

        # Simulate User B
        user_b_root = tmp_path / "user_b"
        user_b_root.mkdir()
        validator_b = PathSafetyValidator(allowed_root=user_b_root)

        # User A creates temp file
        temp_a = validator_a.get_temp_path("secret.txt")
        temp_a.write_text("USER A SECRET")

        # User B tries to access User A's temp file
        with pytest.raises(PathSafetyError, match="outside allowed root"):
            validator_b.validate_path(temp_a)

    def test_temp_files_scoped_to_allowed_root(self, tmp_path):
        """Verify temp files are scoped per validator instance."""
        # Create directories first
        app1_root = tmp_path / "app1"
        app2_root = tmp_path / "app2"
        app1_root.mkdir()
        app2_root.mkdir()

        validator1 = PathSafetyValidator(allowed_root=app1_root)
        validator2 = PathSafetyValidator(allowed_root=app2_root)

        # Each validator has separate temp directory
        assert validator1.temp_dir != validator2.temp_dir

        # Temp directories are isolated
        temp1 = validator1.get_temp_path("data.txt")
        temp1.write_text("data1")

        # Validator 2 cannot access validator 1's temp files
        with pytest.raises(PathSafetyError, match="outside allowed root"):
            validator2.validate_path(temp1)


class TestTOCTOUMitigation:
    """Test TOCTOU (Time-of-Check Time-of-Use) mitigation."""

    def test_temp_path_always_within_allowed_root(self, tmp_path):
        """Verify temp paths are always within allowed_root."""
        validator = PathSafetyValidator(allowed_root=tmp_path)

        temp_file = validator.get_temp_path("test.txt")
        temp_file.write_text("original content")

        # Validate
        validated = validator.validate_path(temp_file, must_exist=True)

        # Even if attacker swaps file, it's still within allowed_root
        # (No /tmp exception that could escape to other locations)
        assert validated.is_relative_to(validator.allowed_root)

    def test_no_tmp_escape_after_validation(self, tmp_path):
        """Verify validated paths cannot escape to /tmp."""
        validator = PathSafetyValidator(allowed_root=tmp_path)

        # Create valid file
        valid_file = tmp_path / "test.txt"
        valid_file.write_text("legitimate")

        # Validate
        validated = validator.validate_path(valid_file)

        # Try to use /tmp path - should fail
        tmp_file = Path("/tmp/attack.txt")
        try:
            tmp_file.write_text("malicious")

            # Direct /tmp access should fail
            with pytest.raises(PathSafetyError, match="outside allowed root"):
                validator.validate_path(tmp_file)
        finally:
            tmp_file.unlink(missing_ok=True)


class TestIntegration:
    """Integration tests for real-world temporary file workflows."""

    def test_temp_file_lifecycle(self, tmp_path):
        """Test complete temporary file lifecycle."""
        validator = PathSafetyValidator(allowed_root=tmp_path)

        # Create temp file
        temp_file = validator.get_temp_path("session_abc123.json")
        temp_file.write_text('{"token": "xyz"}')

        # Validate can read
        validated = validator.validate_read(temp_file)
        data = validated.read_text()
        assert data == '{"token": "xyz"}'

        # Validate can write
        validated_write = validator.validate_write(temp_file, allow_overwrite=True)
        validated_write.write_text('{"token": "updated"}')

        # Cleanup
        validator.cleanup_temp_directory()
        assert not temp_file.exists()

    def test_multiple_temp_files(self, tmp_path):
        """Test multiple temporary files can coexist."""
        validator = PathSafetyValidator(allowed_root=tmp_path)

        # Create multiple temp files
        temp_files = []
        for i in range(5):
            temp_file = validator.get_temp_path(f"file_{i}.txt")
            temp_file.write_text(f"data {i}")
            temp_files.append(temp_file)

        # All should exist
        for temp_file in temp_files:
            assert temp_file.exists()

        # Cleanup removes all
        validator.cleanup_temp_directory()
        for temp_file in temp_files:
            assert not temp_file.exists()

    def test_temp_directory_survives_validator_recreation(self, tmp_path):
        """Test temp directory persists across validator instances."""
        # Create validator and temp file
        validator1 = PathSafetyValidator(allowed_root=tmp_path)
        temp_file = validator1.get_temp_path("persistent.txt")
        temp_file.write_text("data")

        # Create new validator for same root
        validator2 = PathSafetyValidator(allowed_root=tmp_path)

        # File still exists and is accessible
        assert temp_file.exists()
        validated = validator2.validate_path(temp_file)
        assert validated.read_text() == "data"


class TestBackwardCompatibility:
    """Test that existing path validation still works."""

    def test_normal_paths_still_work(self, tmp_path):
        """Verify normal path validation is unaffected."""
        validator = PathSafetyValidator(allowed_root=tmp_path)

        # Create normal file
        normal_file = tmp_path / "normal.txt"
        normal_file.write_text("content")

        # Should validate successfully
        validated = validator.validate_path(normal_file)
        assert validated == normal_file.resolve()

    def test_symlink_validation_still_works(self, tmp_path):
        """Verify symlink validation is unaffected."""
        validator = PathSafetyValidator(allowed_root=tmp_path)

        # Create file and symlink within allowed_root
        target = tmp_path / "target.txt"
        target.write_text("target content")

        symlink = tmp_path / "link.txt"
        symlink.symlink_to(target)

        # Should validate successfully
        validated = validator.validate_path(symlink)
        assert validated.resolve() == target.resolve()

    def test_forbidden_paths_still_blocked(self, tmp_path):
        """Verify forbidden paths are still blocked."""
        validator = PathSafetyValidator(allowed_root=tmp_path)

        # Should still block /etc (caught by "outside allowed root" or "Forbidden path")
        with pytest.raises(PathSafetyError, match="outside allowed root|Forbidden path"):
            validator.validate_path("/etc/passwd")
