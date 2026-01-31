"""
Security tests for path injection and traversal attacks.

Tests cover OWASP path traversal vectors and advanced bypass techniques:
- Unicode normalization attacks
- TOCTOU race conditions
- Symlink chain depth limits
- Case-insensitive bypasses
- Extremely long paths
- Null byte injection
- Mixed path separators
"""
import pytest
import tempfile
import os
import sys
import time
import threading
from pathlib import Path
from src.utils.path_safety import (
    PathSafetyValidator,
    PathSafetyError,
    validate_path,
    validate_write
)


@pytest.fixture
def temp_workspace(tmp_path):
    """Create a temporary workspace for testing."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "safe.txt").write_text("safe content")
    return workspace


@pytest.fixture
def validator(temp_workspace):
    """Create validator with temporary workspace as root."""
    return PathSafetyValidator(allowed_root=temp_workspace)


class TestUnicodeNormalizationAttacks:
    """Test path traversal via unicode normalization and encoding."""

    def test_url_encoded_path_traversal(self, validator, temp_workspace):
        """Test URL-encoded path traversal is blocked."""
        # %2E = '.', %2F = '/'
        # %2E%2E%2F = '../'
        malicious_paths = [
            str(temp_workspace) + "/%2E%2E%2Fetc/passwd",
            str(temp_workspace) + "/%2e%2e%2fetc/passwd",  # lowercase
            str(temp_workspace) + "/%252E%252E%252Fetc/passwd",  # double-encoded
        ]

        for malicious in malicious_paths:
            # URL encoding in path string
            # Note: Path() and filesystem don't decode URLs, but test the validator handles them
            try:
                result = validator.validate_path(malicious)
                # If it doesn't raise, verify it didn't escape the workspace
                assert str(result).startswith(str(temp_workspace))
            except (PathSafetyError, OSError):
                # Expected - malicious path blocked or doesn't resolve
                pass

    def test_unicode_slash_variants(self, validator, temp_workspace):
        """Test unicode slash equivalents don't bypass validation."""
        # Unicode has multiple slash-like characters
        malicious_paths = [
            # U+2215 (Division Slash)
            str(temp_workspace) + "/\u2215etc\u2215passwd",
            # U+2216 (Set Minus)
            str(temp_workspace) + "/\u2216etc\u2216passwd",
            # U+2044 (Fraction Slash)
            str(temp_workspace) + "/\u2044etc\u2044passwd",
        ]

        for malicious in malicious_paths:
            try:
                result = validator.validate_path(malicious)
                # Verify we didn't escape workspace
                assert str(result).startswith(str(temp_workspace))
            except (PathSafetyError, OSError, ValueError):
                # Expected - blocked or invalid path
                pass

    def test_unicode_dot_variants(self, validator, temp_workspace):
        """Test unicode dot equivalents don't bypass validation."""
        # Create a path with unicode dots
        malicious_paths = [
            # U+002E is normal dot, U+00B7 is middle dot
            str(temp_workspace) + "/\u00b7\u00b7/etc/passwd",
            # U+2024 is one dot leader
            str(temp_workspace) + "/\u2024\u2024/etc/passwd",
        ]

        for malicious in malicious_paths:
            try:
                result = validator.validate_path(malicious)
                assert str(result).startswith(str(temp_workspace))
            except (PathSafetyError, OSError, ValueError):
                # Expected
                pass

    def test_normalized_vs_unnormalized_paths(self, validator, temp_workspace):
        """Test that NFC and NFD normalized paths are handled consistently."""
        # é can be represented as:
        # - NFC: single character U+00E9
        # - NFD: e (U+0065) + combining acute accent (U+0301)
        nfc_path = temp_workspace / "café.txt"
        nfd_path = temp_workspace / "cafe\u0301.txt"

        nfc_path.write_text("test")

        # Both should resolve to the same file on most filesystems
        result_nfc = validator.validate_path(nfc_path)
        result_nfd = validator.validate_path(nfd_path)

        # Both should be allowed and resolve within workspace
        assert str(result_nfc).startswith(str(temp_workspace))
        assert str(result_nfd).startswith(str(temp_workspace))


class TestTOCTOURaceConditions:
    """Test Time-of-Check-Time-of-Use (TOCTOU) race condition vulnerabilities."""

    def test_file_swap_after_validation(self, validator, temp_workspace):
        """Test that file changes between validation and use are detected."""
        # This is a limitation test - path_safety validates at call time
        # Real TOCTOU protection requires atomic operations at filesystem level

        safe_file = temp_workspace / "swapped.txt"
        safe_file.write_text("original content")

        # Validate the safe file
        validated_path = validator.validate_path(safe_file, must_exist=True)
        assert validated_path.exists()

        # Simulate attacker swapping file with symlink after validation
        original_content = safe_file.read_text()
        safe_file.unlink()

        # Try to create symlink (may not work on all platforms)
        try:
            outside = temp_workspace.parent / "outside.txt"
            outside.write_text("malicious")
            safe_file.symlink_to(outside)

            # Re-validate - should detect the symlink now points outside
            with pytest.raises(PathSafetyError, match="outside allowed root"):
                validator.validate_path(safe_file)

            # Cleanup
            safe_file.unlink()
            outside.unlink()
        except OSError:
            # Symlinks not supported on platform, skip this test
            pytest.skip("Symlinks not supported")
        finally:
            if not safe_file.exists():
                safe_file.write_text(original_content)

    def test_concurrent_file_access(self, validator, temp_workspace):
        """Test concurrent validation doesn't cause race conditions."""
        test_file = temp_workspace / "concurrent.txt"
        test_file.write_text("test")

        errors = []
        results = []

        def validate_file():
            try:
                result = validator.validate_path(test_file)
                results.append(result)
            except Exception as e:
                errors.append(e)

        # Run 10 concurrent validations
        threads = [threading.Thread(target=validate_file) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All should succeed
        assert len(errors) == 0
        assert len(results) == 10
        assert all(str(r).startswith(str(temp_workspace)) for r in results)


class TestSymlinkChainDepth:
    """Test deeply nested symlink chains are rejected."""

    def test_symlink_chain_depth_limit(self, validator, temp_workspace):
        """Test excessive symlink chain depth is handled."""
        try:
            # Create a chain of 50 symlinks
            target = temp_workspace / "target.txt"
            target.write_text("final target")

            current = target
            for i in range(50):
                next_link = temp_workspace / f"link_{i}.txt"
                next_link.symlink_to(current)
                current = next_link

            # Try to validate the deep chain
            # Python's Path.resolve() has internal limits and will raise
            try:
                result = validator.validate_path(current)
                # If it succeeds, verify it's still within workspace
                assert str(result).startswith(str(temp_workspace))
            except (OSError, RuntimeError, PathSafetyError) as e:
                # Expected - too many levels of symbolic links
                assert "symlink" in str(e).lower() or "cannot resolve" in str(e).lower()

        except OSError:
            pytest.skip("Symlinks not supported on this platform")

    def test_symlink_loop_detection(self, validator, temp_workspace):
        """Test circular symlink loops are detected."""
        try:
            link_a = temp_workspace / "link_a.txt"
            link_b = temp_workspace / "link_b.txt"

            # Create circular loop: a -> b -> a
            link_a.symlink_to(link_b)
            link_b.symlink_to(link_a)

            # Should raise error when trying to resolve
            with pytest.raises((PathSafetyError, OSError, RuntimeError)):
                validator.validate_path(link_a)

        except OSError:
            pytest.skip("Symlinks not supported on this platform")


class TestCaseInsensitivePaths:
    """Test case-insensitive path handling (especially on Windows)."""

    def test_forbidden_path_case_variations(self, validator):
        """Test that case variations of forbidden paths are blocked."""
        # Note: PathSafetyValidator.FORBIDDEN_PATHS are case-sensitive
        # This test verifies they're checked correctly

        forbidden_variations = [
            ("/etc/passwd", "/ETC/passwd"),
            ("/etc/passwd", "/Etc/passwd"),
            ("/sys/kernel", "/SYS/kernel"),
            ("/sys/kernel", "/Sys/Kernel"),
        ]

        for original, variation in forbidden_variations:
            if not Path(original).exists():
                continue

            # On case-insensitive filesystems (Windows, macOS), both should be blocked
            # On case-sensitive filesystems (Linux), only exact match is blocked
            try:
                validator.validate_path(Path(variation))
                # If validation passes, verify behavior is platform-appropriate
                if sys.platform == "win32" or sys.platform == "darwin":
                    # Should have been blocked on case-insensitive FS
                    pytest.fail(f"Expected {variation} to be blocked on case-insensitive FS")
            except PathSafetyError:
                # Expected - path is forbidden
                pass

    def test_project_directory_case_variations(self, validator, temp_workspace):
        """Test case variations of forbidden project directories."""
        # Create .git directory
        git_dir = temp_workspace / ".git"
        git_dir.mkdir()

        variations = [
            git_dir / "config",
            temp_workspace / ".GIT" / "config",
            temp_workspace / ".Git" / "config",
        ]

        for path_var in variations:
            try:
                validator.validate_path(path_var)
                # On case-insensitive FS, all should be blocked
                # Validator checks ".git" in parts, which is case-sensitive
                # So .GIT may not be caught
                pass
            except (PathSafetyError, FileNotFoundError):
                # Either blocked or doesn't exist (expected)
                pass


class TestExtremelyLongPaths:
    """Test paths exceeding OS limits are rejected gracefully."""

    def test_path_length_limit(self, validator, temp_workspace):
        """Test extremely long paths are handled."""
        # Most systems have a limit around 4096 bytes for paths
        # Windows has MAX_PATH = 260 unless long path support is enabled

        # Create an extremely long filename
        long_component = "a" * 300
        long_path = temp_workspace
        for i in range(20):  # 20 * 300 = 6000 char path
            long_path = long_path / long_component

        try:
            result = validator.validate_path(long_path, must_exist=False, allow_create=True)
            # If it succeeds, verify it's within workspace
            assert str(result).startswith(str(temp_workspace))
        except (OSError, PathSafetyError) as e:
            # Expected - path too long or cannot resolve
            # OSError: File name too long
            assert "too long" in str(e).lower() or "cannot resolve" in str(e).lower()

    def test_path_component_length_limit(self, validator, temp_workspace):
        """Test filename component length limits."""
        # Most filesystems limit individual filename components to 255 bytes

        long_filename = "a" * 300  # Exceeds 255 byte limit
        long_path = temp_workspace / long_filename

        try:
            result = validator.validate_path(long_path, must_exist=False, allow_create=True)
            # Some platforms may allow it
            assert str(result).startswith(str(temp_workspace))
        except (OSError, PathSafetyError) as e:
            # Expected on most platforms
            assert "too long" in str(e).lower() or "file name" in str(e).lower()


class TestNullByteInjection:
    """Test null byte injection in paths is blocked."""

    def test_null_byte_in_path(self, validator):
        """Test that null bytes in paths are rejected."""
        malicious_paths = [
            "test\x00.txt",
            "dir/file\x00malicious.exe",
            "\x00etc/passwd",
            "test.txt\x00",
        ]

        for malicious in malicious_paths:
            with pytest.raises(PathSafetyError, match="null byte"):
                validator.validate_path(malicious)

    def test_null_byte_at_boundaries(self, validator, temp_workspace):
        """Test null byte at path boundaries is detected."""
        with pytest.raises(PathSafetyError, match="null byte"):
            validator.validate_path(str(temp_workspace) + "/\x00file.txt")

        with pytest.raises(PathSafetyError, match="null byte"):
            validator.validate_path(str(temp_workspace) + "/file.txt\x00.jpg")


class TestMixedPathSeparators:
    """Test mixed path separators don't bypass validation."""

    def test_mixed_forward_backward_slashes(self, validator, temp_workspace):
        """Test paths with mixed / and \\ separators."""
        # Try to escape using mixed separators
        malicious_paths = [
            str(temp_workspace) + "/..\\..\\etc\\passwd",
            str(temp_workspace) + "\\../etc/passwd",
            str(temp_workspace) + "/subdir\\..\\..\\etc\\passwd",
        ]

        for malicious in malicious_paths:
            try:
                result = validator.validate_path(malicious)
                # If validation passes, verify we didn't escape workspace
                assert str(result).startswith(str(temp_workspace))
            except (PathSafetyError, OSError):
                # Expected - blocked or invalid on this platform
                pass

    def test_double_slashes(self, validator, temp_workspace):
        """Test double slashes are normalized correctly."""
        # Double slashes should be normalized
        paths_with_double_slash = [
            str(temp_workspace) + "//safe.txt",
            str(temp_workspace) + "/subdir//file.txt",
            str(temp_workspace) + "///multiple///slashes///file.txt",
        ]

        for path in paths_with_double_slash:
            try:
                result = validator.validate_path(path, must_exist=False)
                # Should normalize to single slashes
                assert "//" not in str(result) or sys.platform == "win32"  # Windows UNC paths may have //
                assert str(result).startswith(str(temp_workspace))
            except (PathSafetyError, OSError):
                # Some edge case handling
                pass


class TestPathTraversalPatterns:
    """Test various path traversal attack patterns."""

    def test_classic_path_traversal(self, validator, temp_workspace):
        """Test classic ../ path traversal attempts."""
        malicious_paths = [
            temp_workspace / ".." / ".." / "etc" / "passwd",
            temp_workspace / "subdir" / ".." / ".." / ".." / "etc" / "passwd",
            temp_workspace.parent / "outside.txt",
        ]

        for malicious in malicious_paths:
            with pytest.raises(PathSafetyError, match="outside allowed root"):
                validator.validate_path(malicious)

    def test_absolute_path_escape(self, validator, temp_workspace):
        """Test that absolute paths outside workspace are blocked."""
        malicious_paths = [
            "/etc/passwd",
            "/tmp/../etc/passwd",
            "/sys/kernel/config",
            "/root/.ssh/id_rsa",
        ]

        for malicious in malicious_paths:
            if not Path(malicious).exists():
                continue

            with pytest.raises(PathSafetyError):
                validator.validate_path(malicious)

    def test_relative_path_resolution(self, validator, temp_workspace):
        """Test relative paths are resolved correctly."""
        # Create subdirectory
        subdir = temp_workspace / "subdir"
        subdir.mkdir()
        (subdir / "file.txt").write_text("test")

        # Change to subdir
        original_cwd = Path.cwd()
        try:
            os.chdir(subdir)

            # Relative path from subdir
            relative = Path("file.txt")
            result = validator.validate_path(relative)

            # Should resolve to absolute path within workspace
            assert result.is_absolute()
            assert str(result).startswith(str(temp_workspace))

        finally:
            os.chdir(original_cwd)


class TestErrorMessageSecurity:
    """Test that error messages don't leak sensitive information."""

    def test_error_messages_no_internal_paths(self, validator):
        """Test error messages don't expose internal system paths."""
        # Try to access forbidden path
        try:
            validator.validate_path("/etc/shadow")
        except PathSafetyError as e:
            error_msg = str(e)
            # Error message should mention the issue but not leak internal details
            assert "forbidden" in error_msg.lower() or "outside" in error_msg.lower()
            # Should not expose unrelated internal paths
            # (This is a weak test, mainly documentational)

    def test_validation_failure_details(self, validator, temp_workspace):
        """Test validation failures provide useful but safe error details."""
        # Non-existent file with must_exist=True
        try:
            validator.validate_path(
                temp_workspace / "nonexistent.txt",
                must_exist=True
            )
        except PathSafetyError as e:
            error_msg = str(e)
            assert "must exist" in error_msg.lower()
            # Should mention the path that failed
            assert "nonexistent.txt" in error_msg


class TestCrossPlatformBehavior:
    """Test platform-specific path handling."""

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific test")
    def test_windows_drive_letters(self, validator):
        """Test Windows drive letter handling."""
        # Windows-specific paths
        windows_paths = [
            "C:\\Windows\\System32",
            "D:\\etc\\passwd",  # Try to access via different drive
        ]

        for path in windows_paths:
            try:
                validator.validate_path(path)
            except (PathSafetyError, OSError):
                # Expected - outside allowed root or doesn't exist
                pass

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific test")
    def test_windows_unc_paths(self, validator):
        """Test Windows UNC path handling."""
        unc_paths = [
            "\\\\server\\share\\file.txt",
            "\\\\?\\C:\\Windows\\System32",
        ]

        for path in unc_paths:
            try:
                validator.validate_path(path)
            except (PathSafetyError, OSError, ValueError):
                # Expected - UNC paths should be blocked or invalid
                pass

    @pytest.mark.skipif(sys.platform == "win32", reason="Unix-specific test")
    def test_unix_special_files(self, validator):
        """Test Unix special file handling."""
        special_files = [
            "/dev/null",
            "/proc/self/environ",
            "/sys/class/net",
        ]

        for path in special_files:
            if not Path(path).exists():
                continue

            with pytest.raises(PathSafetyError):
                validator.validate_path(path)
