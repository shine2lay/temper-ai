"""
Unit tests for FileWriter tool.

Tests file writing with safety checks.
"""
import tempfile
from pathlib import Path

import pytest

from src.tools.file_writer import FileWriter


@pytest.fixture
def temp_dir():
    """Create a temporary directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


class TestFileWriterMetadata:
    """Test file writer metadata."""

    def test_metadata(self):
        """Test file writer metadata is correct."""
        writer = FileWriter()
        assert writer.name == "FileWriter"
        assert "writes content" in writer.description.lower()
        assert writer.version == "1.0"

    def test_parameters_schema(self):
        """Test parameters schema."""
        writer = FileWriter()
        schema = writer.get_parameters_schema()

        assert schema["type"] == "object"
        assert "file_path" in schema["properties"]
        assert "content" in schema["properties"]
        assert set(schema["required"]) == {"file_path", "content"}


class TestParameterNormalization:
    """Test LLM parameter alias normalization."""

    def test_path_alias_normalized(self):
        """'path' is normalized to 'file_path'."""
        result = FileWriter._normalize_params({"path": "/tmp/f.py", "content": "x"})
        assert result == {"file_path": "/tmp/f.py", "content": "x"}

    def test_contents_alias_normalized(self):
        """'contents' is normalized to 'content'."""
        result = FileWriter._normalize_params({"file_path": "/tmp/f.py", "contents": "x"})
        assert result == {"file_path": "/tmp/f.py", "content": "x"}

    def test_both_aliases_normalized(self):
        """Both 'path' and 'contents' normalized together."""
        result = FileWriter._normalize_params({"path": "/tmp/f.py", "contents": "x"})
        assert result == {"file_path": "/tmp/f.py", "content": "x"}

    def test_canonical_names_unchanged(self):
        """Canonical parameter names pass through unchanged."""
        params = {"file_path": "/tmp/f.py", "content": "x", "overwrite": True}
        result = FileWriter._normalize_params(params)
        assert result == params

    def test_canonical_not_overwritten_by_alias(self):
        """If both canonical and alias present, canonical wins."""
        result = FileWriter._normalize_params({
            "file_path": "/canonical", "path": "/alias", "content": "x",
        })
        assert result["file_path"] == "/canonical"

    def test_validate_params_normalizes(self):
        """validate_params accepts aliased parameters."""
        writer = FileWriter()
        result = writer.validate_params({"path": "/tmp/f.py", "contents": "x"})
        assert result.valid


class TestBasicFileWriting:
    """Test basic file writing operations."""

    def test_write_simple_file(self, temp_dir):
        """Test writing a simple text file."""
        writer = FileWriter()
        file_path = temp_dir / "test.txt"

        result = writer.execute(
            file_path=str(file_path),
            content="Hello, world!"
        )

        assert result.success is True
        assert file_path.exists()
        assert file_path.read_text() == "Hello, world!"

    def test_write_multiline_content(self, temp_dir):
        """Test writing multiline content."""
        writer = FileWriter()
        file_path = temp_dir / "multiline.txt"
        content = "Line 1\nLine 2\nLine 3"

        result = writer.execute(
            file_path=str(file_path),
            content=content
        )

        assert result.success is True
        assert file_path.read_text() == content

    def test_write_empty_file(self, temp_dir):
        """Test writing an empty file."""
        writer = FileWriter()
        file_path = temp_dir / "empty.txt"

        result = writer.execute(
            file_path=str(file_path),
            content=""
        )

        assert result.success is True
        assert file_path.exists()
        assert file_path.read_text() == ""

    def test_write_unicode_content(self, temp_dir):
        """Test writing unicode content."""
        writer = FileWriter()
        file_path = temp_dir / "unicode.txt"
        content = "Hello 世界 🌍"

        result = writer.execute(
            file_path=str(file_path),
            content=content
        )

        assert result.success is True
        assert file_path.read_text(encoding='utf-8') == content


class TestDirectoryCreation:
    """Test parent directory creation."""

    def test_create_parent_directories(self, temp_dir):
        """Test creating parent directories."""
        writer = FileWriter()
        file_path = temp_dir / "nested" / "dirs" / "file.txt"

        result = writer.execute(
            file_path=str(file_path),
            content="test",
            create_dirs=True
        )

        assert result.success is True
        assert file_path.exists()
        assert file_path.read_text() == "test"

    def test_fail_without_parent_dirs(self, temp_dir):
        """Test that writing fails when parent doesn't exist and create_dirs=False."""
        writer = FileWriter()
        file_path = temp_dir / "nonexistent" / "file.txt"

        result = writer.execute(
            file_path=str(file_path),
            content="test",
            create_dirs=False
        )

        assert result.success is False
        assert "parent directory does not exist" in result.error.lower()


class TestOverwriteProtection:
    """Test file overwrite protection."""

    def test_prevent_overwrite_by_default(self, temp_dir):
        """Test that existing files are not overwritten by default."""
        writer = FileWriter()
        file_path = temp_dir / "existing.txt"

        # Create initial file
        file_path.write_text("original content")

        # Try to overwrite without permission
        result = writer.execute(
            file_path=str(file_path),
            content="new content",
            overwrite=False
        )

        assert result.success is False
        assert "already exists" in result.error.lower()
        assert file_path.read_text() == "original content"  # Unchanged

    def test_allow_overwrite_with_flag(self, temp_dir):
        """Test that files can be overwritten when flag is set."""
        writer = FileWriter()
        file_path = temp_dir / "existing.txt"

        # Create initial file
        file_path.write_text("original content")

        # Overwrite with permission
        result = writer.execute(
            file_path=str(file_path),
            content="new content",
            overwrite=True
        )

        assert result.success is True
        assert file_path.read_text() == "new content"


class TestPathSafety:
    """Test path safety checks."""

    def test_prevent_etc_write(self):
        """Test that writing to /etc is prevented."""
        writer = FileWriter()

        result = writer.execute(
            file_path="/etc/test.txt",
            content="malicious"
        )

        assert result.success is False
        assert "path safety validation failed" in result.error.lower()

    def test_prevent_sys_write(self):
        """Test that writing to /sys is prevented."""
        writer = FileWriter()

        result = writer.execute(
            file_path="/sys/test.txt",
            content="malicious"
        )

        assert result.success is False
        assert "path safety validation failed" in result.error.lower()

    def test_prevent_dangerous_extension(self):
        """Test that dangerous extensions are blocked."""
        writer = FileWriter()

        result = writer.execute(
            file_path="/tmp/test.exe",
            content="malicious"
        )

        assert result.success is False
        assert "cannot write file with forbidden extension" in result.error.lower()

    def test_prevent_shell_script(self):
        """Test that shell scripts are blocked."""
        writer = FileWriter()

        result = writer.execute(
            file_path="/tmp/test.sh",
            content="#!/bin/bash\nrm -rf /"
        )

        assert result.success is False
        assert "cannot write file with forbidden extension" in result.error.lower()

    def test_allow_safe_paths(self, temp_dir):
        """Test that safe paths are allowed."""
        writer = FileWriter()
        file_path = temp_dir / "safe.txt"

        result = writer.execute(
            file_path=str(file_path),
            content="safe content"
        )

        assert result.success is True

    def test_allow_safe_extensions(self, temp_dir):
        """Test that safe extensions are allowed."""
        writer = FileWriter()

        safe_extensions = [".txt", ".md", ".json", ".yaml", ".csv", ".log"]

        for ext in safe_extensions:
            file_path = temp_dir / f"test{ext}"
            result = writer.execute(
                file_path=str(file_path),
                content="test"
            )
            assert result.success is True, f"Should allow {ext} extension"


class TestInputValidation:
    """Test input parameter validation."""

    def test_missing_file_path(self):
        """Test that missing file_path is rejected."""
        writer = FileWriter()

        result = writer.execute(content="test")

        assert result.success is False
        assert "file_path" in result.error.lower()

    def test_missing_content(self):
        """Test that missing content is rejected."""
        writer = FileWriter()

        result = writer.execute(file_path="/tmp/test.txt")

        assert result.success is False
        assert "content" in result.error.lower()

    def test_empty_file_path(self):
        """Test that empty file_path is rejected."""
        writer = FileWriter()

        result = writer.execute(
            file_path="",
            content="test"
        )

        assert result.success is False
        assert "file_path" in result.error.lower()

    def test_non_string_file_path(self):
        """Test that non-string file_path is rejected."""
        writer = FileWriter()

        result = writer.execute(
            file_path=123,
            content="test"
        )

        assert result.success is False
        assert "file_path" in result.error.lower()

    def test_non_string_content(self):
        """Test that non-string content is rejected."""
        writer = FileWriter()

        result = writer.execute(
            file_path="/tmp/test.txt",
            content=123
        )

        assert result.success is False
        assert "content" in result.error.lower()


class TestSizeLimit:
    """Test file size limits."""

    def test_reject_oversized_content(self):
        """Test that very large content is rejected."""
        writer = FileWriter()

        # Create content larger than 10MB
        large_content = "x" * (11 * 1024 * 1024)

        result = writer.execute(
            file_path="/tmp/large.txt",
            content=large_content
        )

        assert result.success is False
        assert "exceeds maximum size" in result.error.lower()

    def test_allow_normal_size(self, temp_dir):
        """Test that normal sized content is allowed."""
        writer = FileWriter()
        file_path = temp_dir / "normal.txt"

        # Create 1MB content (well under limit)
        content = "x" * (1024 * 1024)

        result = writer.execute(
            file_path=str(file_path),
            content=content
        )

        assert result.success is True


class TestMetadata:
    """Test result metadata."""

    def test_metadata_includes_path(self, temp_dir):
        """Test that result includes file path in metadata."""
        writer = FileWriter()
        file_path = temp_dir / "test.txt"

        result = writer.execute(
            file_path=str(file_path),
            content="test"
        )

        assert result.success is True
        assert "file_path" in result.metadata
        assert "size_bytes" in result.metadata
        assert result.metadata["size_bytes"] == 4  # "test" is 4 bytes

    def test_result_value_is_path(self, temp_dir):
        """Test that result value is the file path."""
        writer = FileWriter()
        file_path = temp_dir / "test.txt"

        result = writer.execute(
            file_path=str(file_path),
            content="test"
        )

        assert result.success is True
        assert Path(result.result) == file_path


class TestLLMSchema:
    """Test LLM function calling schema."""

    def test_to_llm_schema(self):
        """Test conversion to LLM schema."""
        writer = FileWriter()
        schema = writer.to_llm_schema()

        assert schema["type"] == "function"
        assert schema["function"]["name"] == "FileWriter"
        assert "file_path" in schema["function"]["parameters"]["properties"]
        assert "content" in schema["function"]["parameters"]["properties"]


class TestErrorHandling:
    """Test error handling."""

    def test_handle_permission_error(self):
        """Test handling of permission errors."""
        writer = FileWriter()

        # Try to write to a file we don't have permission to write
        # This test may fail on systems where we do have permission
        result = writer.execute(
            file_path="/root/test.txt",
            content="test"
        )

        # Should either fail with permission error or forbidden path error
        assert result.success is False

    def test_handle_directory_as_file(self, temp_dir):
        """Test that writing to a directory fails."""
        writer = FileWriter()
        dir_path = temp_dir / "subdir"
        dir_path.mkdir()

        result = writer.execute(
            file_path=str(dir_path),
            content="test"
        )

        assert result.success is False
        assert "directory" in result.error.lower()
