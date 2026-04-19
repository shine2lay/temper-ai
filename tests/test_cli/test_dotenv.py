"""Tests for CLI .env loading."""

import os

from temper_ai.cli.main import _load_dotenv


class TestLoadDotenv:
    def _run_in_dir(self, tmp_path, env_content, monkeypatch):
        """Helper: write .env in tmp_path and run _load_dotenv from there."""
        (tmp_path / ".env").write_text(env_content)
        old_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            _load_dotenv()
        finally:
            os.chdir(old_cwd)

    def test_no_env_file(self, tmp_path, monkeypatch):
        old_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            _load_dotenv()  # should not raise
        finally:
            os.chdir(old_cwd)

    def test_loads_simple_vars(self, tmp_path, monkeypatch):
        os.environ.pop("TEST_CLI_VAR", None)
        self._run_in_dir(tmp_path, "TEST_CLI_VAR=hello\n", monkeypatch)
        assert os.environ.get("TEST_CLI_VAR") == "hello"
        del os.environ["TEST_CLI_VAR"]

    def test_skips_comments(self, tmp_path, monkeypatch):
        os.environ.pop("TEST_CLI_COMMENT", None)
        self._run_in_dir(tmp_path, "# comment\nTEST_CLI_COMMENT=yes\n", monkeypatch)
        assert os.environ.get("TEST_CLI_COMMENT") == "yes"
        del os.environ["TEST_CLI_COMMENT"]

    def test_skips_empty_lines(self, tmp_path, monkeypatch):
        os.environ.pop("TEST_CLI_EMPTY", None)
        self._run_in_dir(tmp_path, "\n\nTEST_CLI_EMPTY=val\n\n", monkeypatch)
        assert os.environ.get("TEST_CLI_EMPTY") == "val"
        del os.environ["TEST_CLI_EMPTY"]

    def test_does_not_override_existing(self, tmp_path, monkeypatch):
        os.environ["TEST_CLI_EXIST"] = "old"
        self._run_in_dir(tmp_path, "TEST_CLI_EXIST=new\n", monkeypatch)
        assert os.environ["TEST_CLI_EXIST"] == "old"
        del os.environ["TEST_CLI_EXIST"]

    def test_handles_equals_in_value(self, tmp_path, monkeypatch):
        os.environ.pop("TEST_CLI_EQ", None)
        self._run_in_dir(tmp_path, "TEST_CLI_EQ=key=value=extra\n", monkeypatch)
        assert os.environ.get("TEST_CLI_EQ") == "key=value=extra"
        del os.environ["TEST_CLI_EQ"]

    def test_skips_lines_without_equals(self, tmp_path, monkeypatch):
        os.environ.pop("TEST_CLI_OK", None)
        self._run_in_dir(tmp_path, "NOEQUALS\nTEST_CLI_OK=yes\n", monkeypatch)
        assert os.environ.get("TEST_CLI_OK") == "yes"
        assert "NOEQUALS" not in os.environ
        del os.environ["TEST_CLI_OK"]
