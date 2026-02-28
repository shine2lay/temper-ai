"""Extended tests for path_safety sub-modules.

Targets uncovered lines in:
- platform_detector.py (44%): lines 30-47, 93-95
- temp_directory.py (36%): lines 51-59, 78-97, 111-129, 137
- path_rules.py (74%): lines 81, 88, 132-133, 136, 143-145, 168-173
- symlink_validator.py (88%): lines 82, 107, 116, 141-142
- validator.py (83%): lines 51, 56, 184, 194, 199, 206-207, 239, 251, 267-268, 276, 280, 284
"""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from temper_ai.shared.utils.path_safety.exceptions import PathSafetyError
from temper_ai.shared.utils.path_safety.path_rules import PathValidationRules
from temper_ai.shared.utils.path_safety.platform_detector import PlatformPathDetector
from temper_ai.shared.utils.path_safety.symlink_validator import (
    SymlinkSecurityValidator,
)
from temper_ai.shared.utils.path_safety.temp_directory import SecureTempDirectory
from temper_ai.shared.utils.path_safety.validator import PathSafetyValidator

# ---------------------------------------------------------------------------
# PlatformPathDetector (lines 30-47, 93-95)
# ---------------------------------------------------------------------------


class TestPlatformPathDetectorWindowsPaths:
    """Tests for get_windows_system_paths on non-Windows."""

    def test_returns_empty_on_non_windows(self):
        """On Linux/macOS, returns empty list (line 27-28 covered, 30-47 skip)."""
        # Force os.name != 'nt' (we're on Linux anyway)
        with patch(
            "temper_ai.shared.utils.path_safety.platform_detector.os.name", "posix"
        ):
            result = PlatformPathDetector.get_windows_system_paths()
        assert result == []

    def test_returns_windows_paths_on_nt(self):
        """On Windows (nt), reads from environment (lines 30-47)."""
        env = {
            "SystemRoot": "C:\\Windows",
            "ProgramFiles": "C:\\Program Files",
            "ProgramFiles(x86)": "C:\\Program Files (x86)",
        }
        with (
            patch("temper_ai.shared.utils.path_safety.platform_detector.os.name", "nt"),
            patch.dict(os.environ, env, clear=True),
        ):
            result = PlatformPathDetector.get_windows_system_paths()
        assert "C:\\Windows" in result
        assert "C:\\Program Files" in result
        assert "C:\\Program Files (x86)" in result

    def test_windows_partial_env_vars(self):
        """Only present env vars are included."""
        with (
            patch("temper_ai.shared.utils.path_safety.platform_detector.os.name", "nt"),
            patch.dict(os.environ, {"SystemRoot": "D:\\Windows"}, clear=True),
        ):
            result = PlatformPathDetector.get_windows_system_paths()
        assert "D:\\Windows" in result
        assert len(result) == 1  # Only SystemRoot present

    def test_windows_no_env_vars_returns_empty(self):
        """No env vars on nt returns empty list."""
        with (
            patch("temper_ai.shared.utils.path_safety.platform_detector.os.name", "nt"),
            patch.dict(os.environ, {}, clear=True),
        ):
            result = PlatformPathDetector.get_windows_system_paths()
        assert result == []


class TestPlatformPathDetectorNormalize:
    """Tests for normalize_path_for_comparison (lines 93-95)."""

    def test_lowercase_on_case_insensitive_fs(self):
        """On darwin/win32, path is lowercased (line 93-94)."""
        with patch(
            "temper_ai.shared.utils.path_safety.platform_detector.PlatformPathDetector.is_case_insensitive_fs",
            return_value=True,
        ):
            result = PlatformPathDetector.normalize_path_for_comparison(
                "/Some/Path/FILE.TXT"
            )
        assert result == "/some/path/file.txt"

    def test_no_lowercase_on_case_sensitive_fs(self):
        """On Linux, path is returned unchanged (line 95)."""
        with patch(
            "temper_ai.shared.utils.path_safety.platform_detector.PlatformPathDetector.is_case_insensitive_fs",
            return_value=False,
        ):
            result = PlatformPathDetector.normalize_path_for_comparison(
                "/Some/Path/FILE.TXT"
            )
        assert result == "/Some/Path/FILE.TXT"

    def test_is_case_insensitive_fs_linux(self):
        """Linux is not case-insensitive."""
        with patch(
            "temper_ai.shared.utils.path_safety.platform_detector.sys.platform", "linux"
        ):
            assert PlatformPathDetector.is_case_insensitive_fs() is False

    def test_is_case_insensitive_fs_darwin(self):
        """macOS is case-insensitive."""
        with patch(
            "temper_ai.shared.utils.path_safety.platform_detector.sys.platform",
            "darwin",
        ):
            assert PlatformPathDetector.is_case_insensitive_fs() is True

    def test_is_case_insensitive_fs_win32(self):
        """Windows is case-insensitive."""
        with patch(
            "temper_ai.shared.utils.path_safety.platform_detector.sys.platform", "win32"
        ):
            assert PlatformPathDetector.is_case_insensitive_fs() is True


# ---------------------------------------------------------------------------
# SecureTempDirectory (lines 51-59, 78-97, 111-129, 137)
# ---------------------------------------------------------------------------


class TestSecureTempDirectory:
    """Tests for SecureTempDirectory."""

    def test_enabled_creates_temp_dir(self, tmp_path):
        """enabled=True creates .tmp directory (lines 44-50)."""
        manager = SecureTempDirectory(allowed_root=tmp_path, enabled=True)
        assert manager.temp_dir is not None
        assert manager.temp_dir.exists()
        assert manager.temp_dir.name == ".tmp"

    def test_disabled_does_not_create_dir(self, tmp_path):
        """enabled=False does not create directory."""
        manager = SecureTempDirectory(allowed_root=tmp_path, enabled=False)
        assert manager.temp_dir is None

    def test_is_enabled_true(self, tmp_path):
        """is_enabled returns True when temp_dir is set (line 137)."""
        manager = SecureTempDirectory(allowed_root=tmp_path, enabled=True)
        assert manager.is_enabled() is True

    def test_is_enabled_false(self, tmp_path):
        """is_enabled returns False when disabled (line 137)."""
        manager = SecureTempDirectory(allowed_root=tmp_path, enabled=False)
        assert manager.is_enabled() is False

    def test_create_secure_temp_dir_oserror_disables(self, tmp_path):
        """OSError during mkdir disables temp_dir and logs warning (lines 51-59)."""
        with patch.object(Path, "mkdir", side_effect=OSError("permission denied")):
            manager = SecureTempDirectory(allowed_root=tmp_path, enabled=True)
        assert manager.temp_dir is None

    def test_get_temp_path_valid_filename(self, tmp_path):
        """Valid filename returns path within .tmp dir (lines 96-97)."""
        manager = SecureTempDirectory(allowed_root=tmp_path, enabled=True)
        result = manager.get_temp_path("output.json")
        assert result.parent == manager.temp_dir
        assert result.name == "output.json"

    def test_get_temp_path_disabled_raises(self, tmp_path):
        """get_temp_path when disabled raises PathSafetyError (lines 78-82)."""
        manager = SecureTempDirectory(allowed_root=tmp_path, enabled=False)
        with pytest.raises(PathSafetyError, match="Temporary directory is disabled"):
            manager.get_temp_path("file.txt")

    def test_get_temp_path_with_slash_raises(self, tmp_path):
        """Filename with '/' raises PathSafetyError (lines 85-88)."""
        manager = SecureTempDirectory(allowed_root=tmp_path, enabled=True)
        with pytest.raises(PathSafetyError, match="no path components allowed"):
            manager.get_temp_path("subdir/file.txt")

    def test_get_temp_path_with_backslash_raises(self, tmp_path):
        """Filename with '\\' raises PathSafetyError."""
        manager = SecureTempDirectory(allowed_root=tmp_path, enabled=True)
        with pytest.raises(PathSafetyError, match="no path components allowed"):
            manager.get_temp_path("bad\\file.txt")

    def test_get_temp_path_with_dotdot_raises(self, tmp_path):
        """Filename with '..' raises PathSafetyError."""
        manager = SecureTempDirectory(allowed_root=tmp_path, enabled=True)
        with pytest.raises(PathSafetyError, match="no path components allowed"):
            manager.get_temp_path("../../etc/passwd")

    def test_get_temp_path_too_long_raises(self, tmp_path):
        """Filename exceeding max length raises PathSafetyError (lines 91-94)."""
        manager = SecureTempDirectory(
            allowed_root=tmp_path, enabled=True, max_component_length=10
        )
        with pytest.raises(PathSafetyError, match="too long"):
            manager.get_temp_path("a" * 11)

    def test_cleanup_temp_directory_disabled_raises(self, tmp_path):
        """cleanup when disabled raises PathSafetyError (lines 111-115)."""
        manager = SecureTempDirectory(allowed_root=tmp_path, enabled=False)
        with pytest.raises(PathSafetyError, match="Temporary directory is disabled"):
            manager.cleanup_temp_directory()

    def test_cleanup_temp_directory_removes_files(self, tmp_path):
        """cleanup removes files and recreates directory (lines 117-129)."""
        manager = SecureTempDirectory(allowed_root=tmp_path, enabled=True)
        # Create a file in temp dir
        test_file = manager.temp_dir / "test.txt"
        test_file.write_text("data")
        assert test_file.exists()

        manager.cleanup_temp_directory()

        # File is gone but directory still exists
        assert not test_file.exists()
        assert manager.temp_dir.exists()

    def test_cleanup_temp_directory_nonexistent_dir_no_error(self, tmp_path):
        """If temp_dir doesn't exist, cleanup is a no-op."""
        manager = SecureTempDirectory(allowed_root=tmp_path, enabled=True)
        # Remove it manually
        import shutil

        shutil.rmtree(manager.temp_dir)
        assert not manager.temp_dir.exists()

        # Should not raise
        manager.cleanup_temp_directory()

    def test_cleanup_oserror_logs_warning(self, tmp_path):
        """OSError during cleanup is caught and logged (lines 126-129)."""
        manager = SecureTempDirectory(allowed_root=tmp_path, enabled=True)
        with patch("shutil.rmtree", side_effect=OSError("io error")):
            # Should not raise
            manager.cleanup_temp_directory()


# ---------------------------------------------------------------------------
# PathValidationRules (lines 81, 88, 132-133, 136, 143-145, 168-173)
# ---------------------------------------------------------------------------


class TestPathValidationRulesExtended:
    """Extended tests for PathValidationRules."""

    def _make_rules(self, tmp_path):
        return PathValidationRules(
            allowed_root=tmp_path,
            forbidden_paths=["/etc", "/sys"],
            forbidden_project_dirs=[".git", "secrets"],
        )

    def test_path_too_long_raises(self, tmp_path):
        """Path exceeding MAX_PATH_LENGTH raises PathSafetyError (line 80-83)."""
        rules = self._make_rules(tmp_path)
        with patch.object(PathValidationRules, "MAX_PATH_LENGTH", 10):
            with pytest.raises(PathSafetyError, match="exceeds maximum length"):
                rules.normalize_and_validate_basic("a" * 11)

    def test_component_too_long_raises(self, tmp_path):
        """Component exceeding MAX_COMPONENT_LENGTH raises PathSafetyError (lines 87-90)."""
        rules = self._make_rules(tmp_path)
        with patch.object(PathValidationRules, "MAX_COMPONENT_LENGTH", 5):
            with pytest.raises(PathSafetyError, match="exceeds maximum length"):
                rules.normalize_and_validate_basic("abcdef")

    def test_check_forbidden_paths_case_insensitive(self, tmp_path):
        """Case-insensitive forbidden path check on darwin/win32 (lines 132-133)."""
        rules = PathValidationRules(
            allowed_root=tmp_path,
            forbidden_paths=["/ETC"],
            forbidden_project_dirs=[],
        )
        with patch.object(
            PlatformPathDetector, "is_case_insensitive_fs", return_value=True
        ):
            with pytest.raises(PathSafetyError, match="forbidden path"):
                rules.check_forbidden_paths(Path("/etc/passwd"))

    def test_check_forbidden_project_dir_case_insensitive(self, tmp_path):
        """Case-insensitive forbidden project dir check (lines 143-145)."""
        rules = PathValidationRules(
            allowed_root=tmp_path,
            forbidden_paths=[],
            forbidden_project_dirs=["secrets"],
        )
        with patch.object(
            PlatformPathDetector, "is_case_insensitive_fs", return_value=True
        ):
            with pytest.raises(PathSafetyError, match="forbidden directory"):
                rules.check_forbidden_paths(tmp_path / "SECRETS" / "config.yaml")

    def test_check_forbidden_project_dir_case_sensitive(self, tmp_path):
        """Case-sensitive forbidden project dir check (lines 148-150)."""
        rules = PathValidationRules(
            allowed_root=tmp_path,
            forbidden_paths=[],
            forbidden_project_dirs=["secrets"],
        )
        with patch.object(
            PlatformPathDetector, "is_case_insensitive_fs", return_value=False
        ):
            with pytest.raises(PathSafetyError, match="forbidden directory"):
                rules.check_forbidden_paths(tmp_path / "secrets" / "config.yaml")

    def test_check_forbidden_project_dir_case_sensitive_no_match(self, tmp_path):
        """Case-sensitive - SECRETS != secrets, does not raise."""
        rules = PathValidationRules(
            allowed_root=tmp_path,
            forbidden_paths=[],
            forbidden_project_dirs=["secrets"],
        )
        with patch.object(
            PlatformPathDetector, "is_case_insensitive_fs", return_value=False
        ):
            # SECRETS != secrets in case-sensitive mode — should not raise
            rules.check_forbidden_paths(tmp_path / "SECRETS" / "config.yaml")

    def test_resolve_path_oserror_symlink_message(self, tmp_path):
        """OSError with 'too many' raises PathSafetyError about symlinks (lines 171-172)."""
        rules = self._make_rules(tmp_path)
        with patch.object(
            Path, "resolve", side_effect=OSError("too many levels of symbolic links")
        ):
            with pytest.raises(PathSafetyError, match="Symlink chain"):
                rules.resolve_path_safely(tmp_path / "some_path")

    def test_resolve_path_oserror_generic(self, tmp_path):
        """Generic OSError raises PathSafetyError with 'Cannot resolve' (line 173)."""
        rules = self._make_rules(tmp_path)
        with patch.object(Path, "resolve", side_effect=OSError("device not ready")):
            with pytest.raises(PathSafetyError, match="Cannot resolve"):
                rules.resolve_path_safely(tmp_path / "some_path")

    def test_resolve_path_runtime_error(self, tmp_path):
        """RuntimeError (e.g. circular symlinks) also raises PathSafetyError."""
        rules = self._make_rules(tmp_path)
        with patch.object(
            Path, "resolve", side_effect=RuntimeError("circular symbolic link")
        ):
            with pytest.raises(PathSafetyError):
                rules.resolve_path_safely(tmp_path / "circular")

    def test_path_as_path_object_normalized(self, tmp_path):
        """Path object input is also NFC-normalized (line 71-72)."""
        rules = self._make_rules(tmp_path)
        path_input = tmp_path / "test.txt"
        result = rules.normalize_and_validate_basic(path_input)
        assert isinstance(result, Path)


# ---------------------------------------------------------------------------
# SymlinkSecurityValidator (lines 82, 107, 116, 141-142)
# ---------------------------------------------------------------------------


class TestSymlinkSecurityValidatorExtended:
    """Extended tests for SymlinkSecurityValidator."""

    def test_check_symlink_target_oserror_raises(self, tmp_path):
        """OSError on readlink raises PathSafetyError (line 81-82)."""
        validator = SymlinkSecurityValidator(allowed_root=tmp_path)
        symlink = tmp_path / "broken_link"

        with (
            patch.object(Path, "is_symlink", return_value=True),
            patch.object(Path, "readlink", side_effect=OSError("no such file")),
        ):
            with pytest.raises(PathSafetyError, match="Cannot read symlink"):
                validator._check_symlink_target(symlink)

    def test_walk_parent_symlinks_oserror_raises(self, tmp_path):
        """OSError during parent symlink walk raises PathSafetyError (lines 115-118)."""
        validator = SymlinkSecurityValidator(allowed_root=tmp_path)
        path = tmp_path / "subdir" / "file.txt"

        # Make is_symlink return True for a parent, then readlink fails
        call_count = [0]

        def mock_is_symlink(self_path):
            call_count[0] += 1
            # Return True on first call (for the path itself in walk), then False
            return call_count[0] == 1

        with (
            patch.object(Path, "is_symlink", mock_is_symlink),
            patch.object(Path, "readlink", side_effect=OSError("io error")),
        ):
            with pytest.raises(PathSafetyError, match="Cannot validate symlink"):
                validator._walk_and_validate_parent_symlinks(path)

    def test_check_final_symlink_absolute_within_root_allowed(self, tmp_path):
        """Absolute symlink pointing within allowed_root is permitted (lines 138-144)."""
        validator = SymlinkSecurityValidator(allowed_root=tmp_path)
        real_file = tmp_path / "real.txt"
        real_file.write_text("content")

        symlink = tmp_path / "link.txt"
        symlink.symlink_to(real_file.absolute())

        # Should not raise
        validator.check_final_symlink(symlink)

    def test_check_final_symlink_absolute_outside_root_raises(self, tmp_path):
        """Absolute symlink pointing outside allowed_root raises PathSafetyError (lines 141-144)."""
        outside = tmp_path.parent / "outside.txt"
        outside.write_text("outside")

        validator = SymlinkSecurityValidator(allowed_root=tmp_path)
        symlink = tmp_path / "evil.txt"
        symlink.symlink_to(outside.absolute())

        try:
            with pytest.raises(PathSafetyError, match="outside allowed root"):
                validator.check_final_symlink(symlink)
        finally:
            if outside.exists():
                outside.unlink()

    def test_check_final_symlink_not_a_symlink_no_error(self, tmp_path):
        """Regular file (not symlink) passes check_final_symlink silently."""
        validator = SymlinkSecurityValidator(allowed_root=tmp_path)
        regular_file = tmp_path / "regular.txt"
        regular_file.write_text("content")
        # Should not raise
        validator.check_final_symlink(regular_file)

    def test_walk_parent_symlinks_relative_absolute_resolution(self, tmp_path):
        """Absolute symlink in parent dir: symlink_resolved is absolute target (line 104-105)."""
        validator = SymlinkSecurityValidator(allowed_root=tmp_path)
        subdir = tmp_path / "subdir"
        subdir.symlink_to(tmp_path)  # Points within root

        # Path inside the symlinked subdir
        path = subdir / "file.txt"
        # Should not raise since symlink is within root
        validator._walk_and_validate_parent_symlinks(path)


# ---------------------------------------------------------------------------
# PathSafetyValidator (lines 51, 56, 184, 194, 199, 206-207, 239, 251, 267-268, 276, 280, 284)
# ---------------------------------------------------------------------------


class TestPathSafetyValidatorExtended:
    """Extended tests for PathSafetyValidator covering uncovered branches."""

    def test_deprecated_get_windows_system_paths(self, tmp_path):
        """_get_windows_system_paths delegates to PlatformPathDetector (line 51)."""
        result = PathSafetyValidator._get_windows_system_paths()
        assert isinstance(result, list)

    def test_deprecated_get_forbidden_paths(self, tmp_path):
        """_get_forbidden_paths delegates to PlatformPathDetector (line 56)."""
        result = PathSafetyValidator._get_forbidden_paths()
        assert isinstance(result, list)

    def test_validate_read_not_a_file_raises(self, tmp_path):
        """validate_read on a directory raises PathSafetyError (line 181)."""
        validator = PathSafetyValidator(allowed_root=tmp_path)
        subdir = tmp_path / "mydir"
        subdir.mkdir()
        with pytest.raises(PathSafetyError, match="not a file"):
            validator.validate_read(subdir)

    def test_validate_read_no_read_permission_raises(self, tmp_path):
        """validate_read on unreadable file raises PathSafetyError (line 183-184)."""
        validator = PathSafetyValidator(allowed_root=tmp_path)
        test_file = tmp_path / "noperms.txt"
        test_file.write_text("content")
        test_file.chmod(0o000)
        try:
            with pytest.raises(PathSafetyError, match="No read permission"):
                validator.validate_read(test_file)
        finally:
            test_file.chmod(0o644)

    def test_resolve_nearest_ancestor_existing(self, tmp_path):
        """_resolve_nearest_ancestor finds nearest existing parent (line 196-197)."""
        validator = PathSafetyValidator(allowed_root=tmp_path)
        # Path whose parent exists
        deep = tmp_path / "a" / "b" / "c"
        result = validator._resolve_nearest_ancestor(deep)
        assert isinstance(result, Path)

    def test_resolve_nearest_ancestor_no_existing_parent(self, tmp_path):
        """_resolve_nearest_ancestor falls back to absolute when no parent exists (line 199)."""
        validator = PathSafetyValidator(allowed_root=tmp_path)
        # All non-existent
        with patch.object(Path, "exists", return_value=False):
            result = validator._resolve_nearest_ancestor(Path("/nonexistent/path"))
        assert isinstance(result, Path)

    def test_validate_new_file_parent_nonexistent_no_create_raises(self, tmp_path):
        """Parent doesn't exist and allow_create_parents=False raises (lines 214-215)."""
        validator = PathSafetyValidator(allowed_root=tmp_path)
        new_file = tmp_path / "nonexistent_dir" / "file.txt"
        with pytest.raises(PathSafetyError, match="Parent directory does not exist"):
            validator._validate_new_file_parent(new_file, allow_create_parents=False)

    def test_validate_write_allow_create_parents(self, tmp_path):
        """validate_write with allow_create_parents=True allows missing parent (line 239)."""
        validator = PathSafetyValidator(allowed_root=tmp_path)
        new_file = tmp_path / "newdir" / "file.txt"
        result = validator.validate_write(new_file, allow_create_parents=True)
        assert isinstance(result, Path)

    def test_validate_write_no_write_permission_raises(self, tmp_path):
        """validate_write when parent dir has no write permission raises (lines 250-251)."""
        validator = PathSafetyValidator(allowed_root=tmp_path)
        subdir = tmp_path / "readonly_dir"
        subdir.mkdir()
        subdir.chmod(0o555)
        try:
            new_file = subdir / "file.txt"
            with pytest.raises(PathSafetyError, match="No write permission"):
                validator.validate_write(new_file)
        finally:
            subdir.chmod(0o755)

    def test_get_temp_path_returns_valid_path(self, tmp_path):
        """get_temp_path returns a valid path within .tmp dir (lines 267-268)."""
        validator = PathSafetyValidator(
            allowed_root=tmp_path, enable_temp_directory=True
        )
        result = validator.get_temp_path("output.json")
        assert isinstance(result, Path)

    def test_cleanup_temp_directory_delegates(self, tmp_path):
        """cleanup_temp_directory delegates to manager (line 276)."""
        validator = PathSafetyValidator(
            allowed_root=tmp_path, enable_temp_directory=True
        )
        # Should not raise
        validator.cleanup_temp_directory()

    def test_deprecated_check_forbidden_delegates(self, tmp_path):
        """_check_forbidden delegates to rules.check_forbidden_paths (line 280)."""
        validator = PathSafetyValidator(allowed_root=tmp_path)
        # A path not in forbidden list should not raise
        safe_path = tmp_path / "safe.txt"
        validator._check_forbidden(safe_path)

    def test_deprecated_check_symlinks_delegates(self, tmp_path):
        """_check_symlinks delegates to symlink_validator.check_final_symlink (line 284)."""
        validator = PathSafetyValidator(allowed_root=tmp_path)
        regular_file = tmp_path / "regular.txt"
        regular_file.write_text("content")
        # Should not raise for a non-symlink
        validator._check_symlinks(regular_file, regular_file)

    def test_forbidden_paths_populated_on_first_init(self, tmp_path):
        """FORBIDDEN_PATHS class variable is populated on first init."""
        # Reset class-level cache
        PathSafetyValidator.FORBIDDEN_PATHS = None
        PathSafetyValidator(allowed_root=tmp_path)
        assert PathSafetyValidator.FORBIDDEN_PATHS is not None

    def test_additional_forbidden_extends_list(self, tmp_path):
        """additional_forbidden adds to the forbidden list."""
        validator = PathSafetyValidator(
            allowed_root=tmp_path, additional_forbidden=["/custom/secret"]
        )
        assert "/custom/secret" in validator.forbidden

    def test_init_without_temp_directory(self, tmp_path):
        """enable_temp_directory=False means temp_dir is None."""
        validator = PathSafetyValidator(
            allowed_root=tmp_path, enable_temp_directory=False
        )
        assert validator.temp_dir is None

    def test_check_parent_in_allowed_root_outside_raises(self, tmp_path):
        """_check_parent_in_allowed_root raises when parent is outside root (lines 206-208)."""
        validator = PathSafetyValidator(allowed_root=tmp_path)
        outside_parent = tmp_path.parent / "other_dir"
        with pytest.raises(PathSafetyError, match="outside allowed root"):
            validator._check_parent_in_allowed_root(outside_parent)

    def test_validate_write_string_path_converted(self, tmp_path):
        """String paths are converted to Path for validate_write (line 238-239)."""
        validator = PathSafetyValidator(allowed_root=tmp_path)
        new_file = str(tmp_path / "new_file.txt")
        result = validator.validate_write(new_file)
        assert isinstance(result, Path)
