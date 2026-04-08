"""Tests for FileAppend tool."""

import os

import pytest

from temper_ai.tools.file_append import FileAppend


@pytest.fixture
def append():
    return FileAppend()


class TestFileAppendBasic:
    def test_append_to_file(self, append, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("line1\n")
        r = append.execute(file_path=str(f), content="line2\n")
        assert r.success is True
        assert f.read_text() == "line1\nline2\n"

    def test_multiple_appends(self, append, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("")
        append.execute(file_path=str(f), content="a")
        append.execute(file_path=str(f), content="b")
        append.execute(file_path=str(f), content="c")
        assert f.read_text() == "abc"

    def test_file_not_found(self, append):
        r = append.execute(file_path="/tmp/nonexistent_xyz_append.txt", content="data")
        assert r.success is False
        assert "not found" in r.error.lower()

    def test_no_auto_newline(self, append, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("start")
        append.execute(file_path=str(f), content="end")
        assert f.read_text() == "startend"


class TestFileAppendValidation:
    def test_empty_file_path(self, append):
        r = append.execute(file_path="", content="data")
        assert r.success is False

    def test_empty_content(self, append, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("original")
        r = append.execute(file_path=str(f), content="")
        assert r.success is False
