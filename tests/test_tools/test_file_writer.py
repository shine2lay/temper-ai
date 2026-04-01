"""Tests for FileWriter tool."""

import os
import tempfile
from pathlib import Path

import pytest

from temper_ai.tools.file_writer import FileWriter


class TestFileWriter:
    def setup_method(self):
        self._tmpdir = tempfile.mkdtemp()
        self.fw = FileWriter(config={"allowed_root": self._tmpdir})

    def test_write_new_file(self):
        path = os.path.join(self._tmpdir, "test.txt")
        r = self.fw.execute(file_path=path, content="hello world")
        assert r.success is True
        assert Path(path).read_text() == "hello world"
        assert r.metadata["bytes_written"] == len("hello world".encode())

    def test_creates_parent_directories(self):
        path = os.path.join(self._tmpdir, "a", "b", "c", "deep.txt")
        r = self.fw.execute(file_path=path, content="deep")
        assert r.success is True
        assert Path(path).read_text() == "deep"

    def test_overwrite_existing(self):
        path = os.path.join(self._tmpdir, "existing.txt")
        Path(path).write_text("old")
        r = self.fw.execute(file_path=path, content="new", overwrite=True)
        assert r.success is True
        assert Path(path).read_text() == "new"

    def test_no_overwrite_protection(self):
        path = os.path.join(self._tmpdir, "protected.txt")
        Path(path).write_text("original")
        r = self.fw.execute(file_path=path, content="replacement", overwrite=False)
        assert r.success is False
        assert "already exists" in r.error
        assert Path(path).read_text() == "original"

    def test_parameter_aliases(self):
        """LLMs sometimes use 'path' instead of 'file_path'."""
        path = os.path.join(self._tmpdir, "aliased.txt")
        r = self.fw.execute(path=path, contents="via alias")
        assert r.success is True
        assert Path(path).read_text() == "via alias"

    def test_empty_path(self):
        r = self.fw.execute(file_path="", content="x")
        assert r.success is False
        assert "required" in r.error.lower()


class TestFileWriterSecurity:
    def test_forbidden_path_etc(self):
        fw = FileWriter()
        r = fw.execute(file_path="/etc/passwd", content="hacked")
        assert r.success is False
        assert "forbidden" in r.error.lower()

    def test_forbidden_path_proc(self):
        fw = FileWriter()
        r = fw.execute(file_path="/proc/something", content="x")
        assert r.success is False

    def test_null_byte_in_path(self):
        fw = FileWriter()
        r = fw.execute(file_path="/tmp/evil\x00.txt", content="x")
        assert r.success is False
        assert "null byte" in r.error.lower()

    def test_allowed_root_escape(self):
        tmpdir = tempfile.mkdtemp()
        fw = FileWriter(config={"allowed_root": tmpdir})
        r = fw.execute(file_path="/tmp/escape.txt", content="x")
        assert r.success is False
        assert "outside allowed root" in r.error.lower()

    def test_path_traversal_blocked(self):
        tmpdir = tempfile.mkdtemp()
        fw = FileWriter(config={"allowed_root": tmpdir})
        r = fw.execute(file_path=os.path.join(tmpdir, "..", "..", "etc", "passwd"), content="x")
        assert r.success is False

    def test_content_size_limit(self):
        fw = FileWriter()
        r = fw.execute(file_path="/tmp/huge.txt", content="x" * 11_000_000)
        assert r.success is False
        assert "too large" in r.error.lower()

    def test_modifies_state_true(self):
        fw = FileWriter()
        assert fw.modifies_state is True
