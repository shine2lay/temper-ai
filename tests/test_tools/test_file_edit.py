"""Tests for FileEdit tool."""


import pytest

from temper_ai.tools.file_edit import FileEdit


@pytest.fixture
def edit():
    return FileEdit()


@pytest.fixture
def sample_file(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("hello world\nfoo bar\nhello again\n")
    return str(f)


class TestFileEditBasic:
    def test_replace_unique(self, edit, sample_file):
        r = edit.execute(file_path=sample_file, old_text="foo bar", new_text="baz qux")
        assert r.success is True
        assert "Replaced 1" in r.result
        with open(sample_file) as f:
            assert "baz qux" in f.read()

    def test_no_match(self, edit, sample_file):
        r = edit.execute(file_path=sample_file, old_text="nonexistent", new_text="x")
        assert r.success is False
        assert "No match found" in r.error

    def test_multiple_matches_fails(self, edit, sample_file):
        r = edit.execute(file_path=sample_file, old_text="hello", new_text="hi")
        assert r.success is False
        assert "2 matches" in r.error

    def test_replace_all(self, edit, sample_file):
        r = edit.execute(file_path=sample_file, old_text="hello", new_text="hi", replace_all=True)
        assert r.success is True
        assert "Replaced 2" in r.result
        with open(sample_file) as f:
            content = f.read()
        assert "hello" not in content
        assert content.count("hi") == 2

    def test_identical_old_new(self, edit, sample_file):
        r = edit.execute(file_path=sample_file, old_text="hello", new_text="hello")
        assert r.success is False
        assert "identical" in r.error

    def test_file_not_found(self, edit):
        r = edit.execute(file_path="/tmp/nonexistent_xyz_123.txt", old_text="a", new_text="b")
        assert r.success is False
        assert "not found" in r.error.lower()


class TestFileEditValidation:
    def test_empty_file_path(self, edit):
        r = edit.execute(file_path="", old_text="a", new_text="b")
        assert r.success is False

    def test_empty_old_text(self, edit, sample_file):
        r = edit.execute(file_path=sample_file, old_text="", new_text="b")
        assert r.success is False
