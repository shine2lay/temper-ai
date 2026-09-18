"""Security regression tests for file tool path validation.

Originally written against FileEdit/FileAppend/FileWriter:
- P0-SEC-7: the edit and append tools validate paths
- P0-SEC-8: allowed_root prefix off-by-one (/workspace must not match /workspaceevildir)

Those tools were replaced by Edit and Write (append is now Write(append=True)).
The properties they pin are unchanged and carried over here — a rewrite of the
file tools is exactly when a path check is most likely to be lost.
"""

import os
import tempfile

import pytest

from temper_ai.tools._path_utils import validate_file_path
from temper_ai.tools.edit import Edit
from temper_ai.tools.write import Write


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


class TestEditPathValidation:
    """P0-SEC-7, carried over from FileEdit."""

    def test_blocks_system_paths(self):
        r = Edit().execute(path="/etc/passwd", edits=[{"old_text": "root", "new_text": "hacked"}])
        assert r.success is False
        assert "forbidden" in r.error

    def test_blocks_proc(self):
        r = Edit().execute(path="/proc/1/status", edits=[{"old_text": "a", "new_text": "b"}])
        assert r.success is False
        assert "forbidden" in r.error

    def test_respects_allowed_root(self):
        edit = Edit(config={"allowed_root": "/workspace"})
        r = edit.execute(path="/home/user/file.txt", edits=[{"old_text": "a", "new_text": "b"}])
        assert r.success is False
        assert "outside allowed root" in r.error

    def test_allows_valid_path(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("hello world")
            path = f.name
        try:
            r = Edit().execute(path=path, edits=[{"old_text": "hello", "new_text": "goodbye"}])
            assert r.success is True
            assert open(path).read() == "goodbye world"
        finally:
            os.unlink(path)

    def test_single_edit_form_still_validated(self):
        """The old FileEdit call shape is accepted — it must not bypass the path check."""
        r = Edit().execute(file_path="/etc/passwd", old_text="root", new_text="hacked")
        assert r.success is False
        assert "forbidden" in r.error


class TestWriteAppendPathValidation:
    """P0-SEC-7, carried over from FileAppend (now Write(append=True))."""

    def test_blocks_system_paths(self):
        r = Write().execute(path="/etc/hosts", content="evil.com 127.0.0.1", append=True)
        assert r.success is False
        assert "forbidden" in r.error

    def test_respects_allowed_root(self):
        write = Write(config={"allowed_root": "/workspace"})
        r = write.execute(path="/tmp/outside.txt", content="data", append=True)
        assert r.success is False
        assert "outside allowed root" in r.error

    def test_allows_valid_path(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("line1\n")
            path = f.name
        try:
            r = Write().execute(path=path, content="line2\n", append=True)
            assert r.success is True
            content = open(path).read()
            assert "line1" in content and "line2" in content
        finally:
            os.unlink(path)


class TestWritePrefixFix:
    """P0-SEC-8: allowed_root prefix off-by-one regression test."""

    def test_prefix_off_by_one_blocked(self):
        writer = Write(config={"allowed_root": "/workspace"})
        r = writer.execute(path="/workspaceevildir/file.txt", content="evil")
        assert r.success is False
        assert "outside allowed root" in r.error


class TestReadPathValidation:
    """Read is new — the same checks must apply to it, not only to the writers."""

    def test_blocks_system_paths(self):
        from temper_ai.tools.read import Read

        r = Read().execute(path="/etc/passwd")
        assert r.success is False
        assert "forbidden" in r.error

    def test_respects_allowed_root(self):
        from temper_ai.tools.read import Read

        r = Read(config={"allowed_root": "/workspace"}).execute(path="/tmp/outside.txt")
        assert r.success is False
        assert "outside allowed root" in r.error
