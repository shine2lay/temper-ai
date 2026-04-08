"""Security regression tests for file tool path validation.

Tests the security hardening applied in this session:
- P0-SEC-7: FileEdit and FileAppend now validate paths
- P0-SEC-8: FileWriter prefix off-by-one fixed
"""

import os
import tempfile

import pytest

from temper_ai.tools._path_utils import validate_file_path
from temper_ai.tools.file_edit import FileEdit
from temper_ai.tools.file_append import FileAppend
from temper_ai.tools.file_writer import FileWriter


class TestValidateFilePath:
    """Shared path validation used by all file tools."""

    def test_blocks_etc(self):
        with pytest.raises(ValueError, match="forbidden"):
            validate_file_path("/etc/passwd")

    def test_blocks_etc_subdirectory(self):
        with pytest.raises(ValueError, match="forbidden"):
            validate_file_path("/etc/shadow")

    def test_blocks_sys(self):
        with pytest.raises(ValueError, match="forbidden"):
            validate_file_path("/sys/kernel/something")

    def test_blocks_proc(self):
        with pytest.raises(ValueError, match="forbidden"):
            validate_file_path("/proc/1/environ")

    def test_blocks_dev(self):
        with pytest.raises(ValueError, match="forbidden"):
            validate_file_path("/dev/sda")

    def test_allows_tmp(self):
        p = validate_file_path("/tmp/safe_file.txt")
        assert str(p) == "/tmp/safe_file.txt"

    def test_allows_home(self):
        p = validate_file_path(os.path.expanduser("~/test.txt"))
        assert "test.txt" in str(p)

    def test_null_byte_rejected(self):
        with pytest.raises(ValueError, match="null byte"):
            validate_file_path("/tmp/file\x00.txt")

    def test_allowed_root_enforced(self):
        with pytest.raises(ValueError, match="outside allowed root"):
            validate_file_path("/home/user/secret.txt", allowed_root="/workspace")

    def test_allowed_root_permits_children(self):
        p = validate_file_path("/workspace/project/file.txt", allowed_root="/workspace")
        assert str(p) == "/workspace/project/file.txt"

    def test_allowed_root_permits_exact_match(self):
        p = validate_file_path("/workspace", allowed_root="/workspace")
        assert str(p) == "/workspace"

    def test_prefix_off_by_one(self):
        """P0-SEC-8: /workspace should NOT match /workspaceevildir."""
        with pytest.raises(ValueError, match="outside allowed root"):
            validate_file_path("/workspaceevildir/file.txt", allowed_root="/workspace")

    def test_traversal_prevented(self):
        # /workspace/../etc/passwd resolves to /etc/passwd — blocked by either
        # forbidden prefix or allowed_root check
        with pytest.raises(ValueError):
            validate_file_path("/workspace/../etc/passwd", allowed_root="/workspace")


class TestFileEditPathValidation:
    """P0-SEC-7: FileEdit now validates paths."""

    def test_blocks_system_paths(self):
        edit = FileEdit()
        r = edit.execute(file_path="/etc/passwd", old_text="root", new_text="hacked")
        assert r.success is False
        assert "forbidden" in r.error

    def test_blocks_proc(self):
        edit = FileEdit()
        r = edit.execute(file_path="/proc/1/status", old_text="a", new_text="b")
        assert r.success is False
        assert "forbidden" in r.error

    def test_respects_allowed_root(self):
        edit = FileEdit(config={"allowed_root": "/workspace"})
        r = edit.execute(file_path="/home/user/file.txt", old_text="a", new_text="b")
        assert r.success is False
        assert "outside allowed root" in r.error

    def test_allows_valid_path(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("hello world")
            path = f.name
        try:
            edit = FileEdit()
            r = edit.execute(file_path=path, old_text="hello", new_text="goodbye")
            assert r.success is True
            assert "Replaced" in r.result
        finally:
            os.unlink(path)


class TestFileAppendPathValidation:
    """P0-SEC-7: FileAppend now validates paths."""

    def test_blocks_system_paths(self):
        append = FileAppend()
        r = append.execute(file_path="/etc/hosts", content="evil.com 127.0.0.1")
        assert r.success is False
        assert "forbidden" in r.error

    def test_respects_allowed_root(self):
        append = FileAppend(config={"allowed_root": "/workspace"})
        r = append.execute(file_path="/tmp/outside.txt", content="data")
        assert r.success is False
        assert "outside allowed root" in r.error

    def test_allows_valid_path(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("line1\n")
            path = f.name
        try:
            append = FileAppend()
            r = append.execute(file_path=path, content="line2\n")
            assert r.success is True
            with open(path) as f:
                content = f.read()
            assert "line1" in content
            assert "line2" in content
        finally:
            os.unlink(path)


class TestFileWriterPrefixFix:
    """P0-SEC-8: FileWriter prefix off-by-one regression test."""

    def test_prefix_off_by_one_blocked(self):
        writer = FileWriter(config={"allowed_root": "/workspace"})
        r = writer.execute(file_path="/workspaceevildir/file.txt", content="evil")
        assert r.success is False
        assert "outside allowed root" in r.error
