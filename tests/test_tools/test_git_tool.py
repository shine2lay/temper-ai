"""Tests for the GitTool."""
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from temper_ai.tools.git_tool import GitTool
from temper_ai.tools.git_tool_constants import GIT_DEFAULT_TIMEOUT


@pytest.fixture
def tool():
    return GitTool()


def _make_proc(stdout="", stderr="", returncode=0):
    proc = MagicMock()
    proc.stdout = stdout
    proc.stderr = stderr
    proc.returncode = returncode
    return proc


def test_metadata(tool):
    meta = tool.get_metadata()
    assert meta.name == "Git"
    assert meta.category == "vcs"
    assert meta.requires_network is True
    assert meta.modifies_state is True


def test_status(tool, tmp_path):
    with patch("temper_ai.tools.git_tool.subprocess.run") as mock_run:
        mock_run.return_value = _make_proc(stdout="On branch main\nnothing to commit")
        result = tool.execute(operation="status", repo_path=str(tmp_path))

    assert result.success is True
    assert "On branch" in result.result["stdout"]
    mock_run.assert_called_once()
    call_args = mock_run.call_args[0][0]
    assert "git" in call_args
    assert "status" in call_args


def test_log(tool, tmp_path):
    with patch("temper_ai.tools.git_tool.subprocess.run") as mock_run:
        mock_run.return_value = _make_proc(stdout="commit abc123\nAuthor: Dev")
        result = tool.execute(operation="log", repo_path=str(tmp_path), args=["--oneline"])

    assert result.success is True
    assert "abc123" in result.result["stdout"]
    call_args = mock_run.call_args[0][0]
    assert "--oneline" in call_args


def test_blocked_operation(tool, tmp_path):
    result = tool.execute(operation="rm", repo_path=str(tmp_path))
    assert result.success is False
    assert "not allowed" in result.error.lower()


def test_blocked_flag_force(tool, tmp_path):
    result = tool.execute(operation="push", repo_path=str(tmp_path), args=["--force"])
    # Note: 'push' may fail operation check first; test either error about operation or flag
    assert result.success is False
    assert "not allowed" in result.error.lower() or "blocked" in result.error.lower()


def test_blocked_flag_hard(tool, tmp_path):
    with patch("temper_ai.tools.git_tool.subprocess.run"):
        result = tool.execute(
            operation="reset", repo_path=str(tmp_path), args=["--hard"]
        )
    # 'reset' is not in allowed operations
    assert result.success is False
    assert "not allowed" in result.error.lower() or "blocked" in result.error.lower()


def test_blocked_flag_on_allowed_op(tool, tmp_path):
    """Test that --force is rejected even on an allowed operation like branch."""
    result = tool.execute(operation="branch", repo_path=str(tmp_path), args=["--force"])
    assert result.success is False
    assert "blocked" in result.error.lower()


def test_invalid_repo_path(tool):
    result = tool.execute(operation="status", repo_path="/nonexistent/path/xyz")
    assert result.success is False
    assert "does not exist" in result.error.lower()


def test_timeout(tool, tmp_path):
    with patch("temper_ai.tools.git_tool.subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd=["git"], timeout=GIT_DEFAULT_TIMEOUT)
        result = tool.execute(operation="fetch", repo_path=str(tmp_path))

    assert result.success is False
    assert "timed out" in result.error.lower()


def test_nonzero_exit_code(tool, tmp_path):
    with patch("temper_ai.tools.git_tool.subprocess.run") as mock_run:
        mock_run.return_value = _make_proc(
            stderr="fatal: not a git repository", returncode=128
        )
        result = tool.execute(operation="status", repo_path=str(tmp_path))

    assert result.success is False
    assert "fatal" in result.error.lower() or "not a git repository" in result.error.lower()
