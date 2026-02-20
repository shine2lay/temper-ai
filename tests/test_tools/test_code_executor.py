"""Tests for the CodeExecutorTool."""
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from temper_ai.tools.code_executor import CodeExecutorTool
from temper_ai.tools.code_executor_constants import CODE_EXEC_DEFAULT_TIMEOUT, CODE_EXEC_MAX_OUTPUT


@pytest.fixture
def tool():
    return CodeExecutorTool()


def _make_proc(stdout="", stderr="", returncode=0):
    proc = MagicMock()
    proc.stdout = stdout
    proc.stderr = stderr
    proc.returncode = returncode
    return proc


def test_metadata(tool):
    meta = tool.get_metadata()
    assert meta.name == "CodeExecutor"
    assert meta.category == "execution"
    assert meta.requires_network is False
    assert meta.modifies_state is True


def test_simple_execution(tool):
    with patch("temper_ai.tools.code_executor.subprocess.run") as mock_run:
        mock_run.return_value = _make_proc(stdout="hello\n")
        result = tool.execute(code='print("hello")')

    assert result.success is True
    assert "hello" in result.result["stdout"]


def test_timeout(tool):
    with patch("temper_ai.tools.code_executor.subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd=["python"], timeout=1)
        result = tool.execute(code="while True: pass", timeout=1)

    assert result.success is False
    assert "timed out" in result.error.lower()


def test_blocked_import_os(tool):
    result = tool.execute(code="import os\nprint(os.getcwd())")
    assert result.success is False
    assert "os" in result.error
    assert "blocked" in result.error.lower()


def test_blocked_import_from(tool):
    result = tool.execute(code="from subprocess import run\nrun(['ls'])")
    assert result.success is False
    assert "subprocess" in result.error
    assert "blocked" in result.error.lower()


def test_blocked_import_sys(tool):
    result = tool.execute(code="import sys")
    assert result.success is False
    assert "blocked" in result.error.lower()


def test_syntax_error(tool):
    with patch("temper_ai.tools.code_executor.subprocess.run") as mock_run:
        mock_run.return_value = _make_proc(
            stderr="SyntaxError: invalid syntax", returncode=1
        )
        result = tool.execute(code="def broken(")

    assert result.success is False
    assert result.error is not None


def test_unsupported_language(tool):
    result = tool.execute(code="puts 'hello'", language="ruby")
    assert result.success is False
    assert "unsupported language" in result.error.lower()


def test_max_output_truncation(tool):
    huge_output = "x" * (CODE_EXEC_MAX_OUTPUT + 1000)
    with patch("temper_ai.tools.code_executor.subprocess.run") as mock_run:
        mock_run.return_value = _make_proc(stdout=huge_output)
        result = tool.execute(code=f'print("x" * {CODE_EXEC_MAX_OUTPUT + 1000})')

    assert result.success is True
    assert len(result.result["stdout"]) == CODE_EXEC_MAX_OUTPUT
    assert result.metadata["stdout_truncated"] is True


def test_empty_code_returns_error(tool):
    result = tool.execute(code="")
    assert result.success is False
    assert result.error is not None
