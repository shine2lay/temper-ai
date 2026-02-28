"""Tests for temper_ai/tools/_bash_helpers.py."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

from temper_ai.tools._bash_helpers import (
    _build_success_result,
    _check_metachar_simple,
    _check_metachar_substring,
    _check_shell_metacharacters,
    _handle_run_error,
    _truncate_output,
    _validate_command_allowlist,
    _validate_path_arguments,
    get_safe_env,
    run_command,
    validate_sandbox,
    validate_shell_mode_command,
    validate_strict_mode_command,
)
from temper_ai.tools.base import ToolResult
from temper_ai.tools.constants import MAX_BASH_OUTPUT_LENGTH

# ---------------------------------------------------------------------------
# TestCheckMetacharSimple
# ---------------------------------------------------------------------------


class TestCheckMetacharSimple:
    def test_returns_none_for_safe_command(self):
        result = _check_metachar_simple("echo hello", ";|&", "bad chars")
        assert result is None

    def test_returns_tool_result_for_forbidden_semicolon(self):
        result = _check_metachar_simple("echo; rm", ";", "bad chars")
        assert isinstance(result, ToolResult)
        assert result.success is False

    def test_returns_tool_result_for_forbidden_pipe(self):
        result = _check_metachar_simple("ls | grep foo", "|", "pipe not allowed")
        assert isinstance(result, ToolResult)
        assert result.success is False

    def test_error_message_preserved(self):
        result = _check_metachar_simple("a{b", "{}", "no braces allowed")
        assert result is not None
        assert "no braces allowed" in result.error

    def test_first_matching_char_triggers_error(self):
        result = _check_metachar_simple("hello*world", "*?[", "no glob")
        assert result is not None
        assert result.success is False

    def test_multiple_chars_checked_all_clean(self):
        result = _check_metachar_simple("echo hello world", "*?[{}|;&", "bad")
        assert result is None


# ---------------------------------------------------------------------------
# TestCheckMetacharSubstring
# ---------------------------------------------------------------------------


class TestCheckMetacharSubstring:
    def test_detects_backtick(self):
        result = _check_metachar_substring("echo `date`", ["`", "$("], "no sub")
        assert result is not None
        assert result.success is False

    def test_detects_dollar_paren(self):
        result = _check_metachar_substring("echo $(date)", ["`", "$("], "no sub")
        assert result is not None
        assert result.success is False

    def test_detects_heredoc(self):
        result = _check_metachar_substring("cat << EOF", ["<<"], "no heredoc")
        assert result is not None
        assert result.success is False

    def test_detects_process_sub_less(self):
        result = _check_metachar_substring(
            "diff <(ls a) b", ["<(", ">("], "no proc sub"
        )
        assert result is not None
        assert result.success is False

    def test_detects_process_sub_greater(self):
        result = _check_metachar_substring("tee >(cat)", ["<(", ">("], "no proc sub")
        assert result is not None
        assert result.success is False

    def test_returns_none_for_safe_command(self):
        result = _check_metachar_substring("echo hello world", ["`", "$("], "no sub")
        assert result is None

    def test_error_message_preserved(self):
        result = _check_metachar_substring("ls<<", ["<<"], "heredoc blocked")
        assert result is not None
        assert "heredoc blocked" in result.error


# ---------------------------------------------------------------------------
# TestCheckShellMetacharacters
# ---------------------------------------------------------------------------


class TestCheckShellMetacharacters:
    ALLOWED: set[str] = {"echo", "ls", "cat"}

    def test_blocks_backtick_command_substitution(self):
        result = _check_shell_metacharacters("echo `date`", self.ALLOWED)
        assert result is not None
        assert result.success is False

    def test_blocks_dollar_paren_command_substitution(self):
        result = _check_shell_metacharacters("echo $(date)", self.ALLOWED)
        assert result is not None
        assert result.success is False

    def test_blocks_heredoc(self):
        result = _check_shell_metacharacters("cat << EOF", self.ALLOWED)
        assert result is not None
        assert result.success is False

    def test_blocks_brace_open(self):
        result = _check_shell_metacharacters("ls {a,b}", self.ALLOWED)
        assert result is not None
        assert result.success is False

    def test_blocks_brace_close(self):
        result = _check_shell_metacharacters("ls foo}", self.ALLOWED)
        assert result is not None
        assert result.success is False

    def test_blocks_glob_star(self):
        result = _check_shell_metacharacters("ls *.py", self.ALLOWED)
        assert result is not None
        assert result.success is False

    def test_blocks_glob_question(self):
        result = _check_shell_metacharacters("ls file?.txt", self.ALLOWED)
        assert result is not None
        assert result.success is False

    def test_blocks_glob_bracket(self):
        result = _check_shell_metacharacters("ls [abc].py", self.ALLOWED)
        assert result is not None
        assert result.success is False

    def test_blocks_process_substitution_less(self):
        result = _check_shell_metacharacters("diff <(ls a) <(ls b)", self.ALLOWED)
        assert result is not None
        assert result.success is False

    def test_blocks_process_substitution_greater(self):
        result = _check_shell_metacharacters("tee >(cat)", self.ALLOWED)
        assert result is not None
        assert result.success is False

    def test_blocks_stderr_redirect_2(self):
        result = _check_shell_metacharacters("ls 2> err.txt", self.ALLOWED)
        assert result is not None
        assert result.success is False

    def test_blocks_stderr_redirect_amp(self):
        result = _check_shell_metacharacters("ls &> out.txt", self.ALLOWED)
        assert result is not None
        assert result.success is False

    def test_returns_none_for_clean_command(self):
        result = _check_shell_metacharacters("echo hello", self.ALLOWED)
        assert result is None

    def test_returns_none_for_piped_command(self):
        # Pipes are not blocked by _check_shell_metacharacters
        result = _check_shell_metacharacters("echo hello | cat", self.ALLOWED)
        assert result is None


# ---------------------------------------------------------------------------
# TestValidateCommandAllowlist
# ---------------------------------------------------------------------------


class TestValidateCommandAllowlist:
    ALLOWED: set[str] = {"echo", "ls", "cat"}

    def test_allowed_command_passes(self):
        result = _validate_command_allowlist(["echo hello"], self.ALLOWED)
        assert result is None

    def test_disallowed_command_blocked(self):
        result = _validate_command_allowlist(["rm -rf /"], self.ALLOWED)
        assert result is not None
        assert result.success is False
        assert "rm" in result.error

    def test_path_in_command_name_blocked(self):
        result = _validate_command_allowlist(["/bin/echo hello"], self.ALLOWED)
        assert result is not None
        assert result.success is False

    def test_empty_sub_command_skipped(self):
        result = _validate_command_allowlist(["", "  "], self.ALLOWED)
        assert result is None

    def test_unparseable_command_returns_error(self):
        result = _validate_command_allowlist(["echo 'unterminated"], self.ALLOWED)
        assert result is not None
        assert result.success is False

    def test_multiple_sub_commands_first_disallowed(self):
        result = _validate_command_allowlist(
            ["wget http://x.com", "echo ok"], self.ALLOWED
        )
        assert result is not None
        assert result.success is False

    def test_multiple_allowed_sub_commands_pass(self):
        result = _validate_command_allowlist(["echo hello", "ls -la"], self.ALLOWED)
        assert result is None


# ---------------------------------------------------------------------------
# TestValidatePathArguments
# ---------------------------------------------------------------------------


class TestValidatePathArguments:
    def test_path_within_sandbox_passes(self, tmp_path):
        sub = tmp_path / "subdir"
        sub.mkdir()
        result = _validate_path_arguments([f"ls {sub}"], tmp_path)
        assert result is None

    def test_path_outside_sandbox_blocked(self, tmp_path):
        result = _validate_path_arguments(["cat /etc/passwd"], tmp_path)
        assert result is not None
        assert result.success is False

    def test_flag_arguments_skipped(self, tmp_path):
        result = _validate_path_arguments(["ls -la --color"], tmp_path)
        assert result is None

    def test_relative_path_within_sandbox_passes(self, tmp_path):
        (tmp_path / "data").mkdir()
        result = _validate_path_arguments(["ls data"], tmp_path)
        assert result is None

    def test_empty_sub_command_skipped(self, tmp_path):
        result = _validate_path_arguments(["", "  "], tmp_path)
        assert result is None


# ---------------------------------------------------------------------------
# TestValidateShellModeCommand
# ---------------------------------------------------------------------------


class TestValidateShellModeCommand:
    ALLOWED: set[str] = {"echo", "ls", "cat"}

    def test_valid_command_passes(self, tmp_path):
        result = validate_shell_mode_command("echo hello", self.ALLOWED, tmp_path)
        assert result is None

    def test_metachar_blocked(self, tmp_path):
        result = validate_shell_mode_command("echo $(date)", self.ALLOWED, tmp_path)
        assert result is not None
        assert result.success is False

    def test_disallowed_command_blocked(self, tmp_path):
        result = validate_shell_mode_command(
            "wget http://x.com", self.ALLOWED, tmp_path
        )
        assert result is not None
        assert result.success is False

    def test_path_outside_sandbox_blocked(self, tmp_path):
        result = validate_shell_mode_command("cat /etc/passwd", self.ALLOWED, tmp_path)
        assert result is not None
        assert result.success is False

    def test_piped_allowed_commands_pass(self, tmp_path):
        result = validate_shell_mode_command("echo hello | cat", self.ALLOWED, tmp_path)
        assert result is None


# ---------------------------------------------------------------------------
# TestValidateStrictModeCommand
# ---------------------------------------------------------------------------


class TestValidateStrictModeCommand:
    ALLOWED: set[str] = {"echo", "ls", "cat"}
    DANGEROUS: set[str] = {";", "|", "&", "$", "`"}

    def test_dangerous_chars_blocked(self):
        parts, error = validate_strict_mode_command(
            "echo hello; rm -rf /", self.ALLOWED, self.DANGEROUS
        )
        assert parts is None
        assert error is not None
        assert error.success is False

    def test_allowed_command_returns_parts(self):
        parts, error = validate_strict_mode_command(
            "echo hello", self.ALLOWED, self.DANGEROUS
        )
        assert error is None
        assert parts == ["echo", "hello"]

    def test_path_in_command_name_blocked(self):
        parts, error = validate_strict_mode_command(
            "/bin/echo hello", self.ALLOWED, self.DANGEROUS
        )
        assert parts is None
        assert error is not None
        assert error.success is False

    def test_disallowed_command_blocked(self):
        parts, error = validate_strict_mode_command(
            "wget http://x.com", self.ALLOWED, self.DANGEROUS
        )
        assert parts is None
        assert error is not None

    def test_empty_command_returns_error(self):
        parts, error = validate_strict_mode_command("", self.ALLOWED, set())
        assert parts is None
        assert error is not None
        assert error.success is False

    def test_backslash_in_command_name_blocked(self):
        parts, error = validate_strict_mode_command(
            "C:\\echo hello", self.ALLOWED, set()
        )
        assert parts is None
        assert error is not None


# ---------------------------------------------------------------------------
# TestValidateSandbox
# ---------------------------------------------------------------------------


class TestValidateSandbox:
    def test_workspace_creation(self, tmp_path):
        new_workspace = tmp_path / "new_ws"
        assert not new_workspace.exists()
        cwd, error = validate_sandbox(new_workspace, None, None)
        assert error is None
        assert new_workspace.exists()

    def test_working_dir_in_sandbox(self, tmp_path):
        sub = tmp_path / "subdir"
        sub.mkdir()
        cwd, error = validate_sandbox(tmp_path, str(sub), None)
        assert error is None
        assert cwd == sub.resolve()

    def test_working_dir_outside_sandbox(self, tmp_path):
        cwd, error = validate_sandbox(tmp_path, "/etc", None)
        assert cwd is None
        assert error is not None
        assert error.success is False

    def test_command_arg_path_traversal_blocked(self, tmp_path):
        parts = ["cat", "/etc/passwd"]
        cwd, error = validate_sandbox(tmp_path, None, parts)
        assert cwd is None
        assert error is not None
        assert error.success is False

    def test_cwd_creation(self, tmp_path):
        new_dir = tmp_path / "new_subdir"
        assert not new_dir.exists()
        cwd, error = validate_sandbox(tmp_path, str(new_dir), None)
        assert error is None
        assert new_dir.exists()

    def test_default_cwd_is_workspace_root(self, tmp_path):
        cwd, error = validate_sandbox(tmp_path, None, None)
        assert error is None
        assert cwd == tmp_path.resolve()


# ---------------------------------------------------------------------------
# TestTruncateOutput
# ---------------------------------------------------------------------------


class TestTruncateOutput:
    def test_within_limit_passes_through(self):
        text = "a" * 100
        assert _truncate_output(text) == text

    def test_over_limit_truncated_with_marker(self):
        text = "x" * (MAX_BASH_OUTPUT_LENGTH + 1000)
        result = _truncate_output(text)
        assert len(result) < len(text)
        assert "truncated" in result

    def test_exactly_at_limit_not_truncated(self):
        text = "b" * MAX_BASH_OUTPUT_LENGTH
        assert _truncate_output(text) == text

    def test_empty_string_passes_through(self):
        assert _truncate_output("") == ""


# ---------------------------------------------------------------------------
# TestBuildSuccessResult
# ---------------------------------------------------------------------------


class TestBuildSuccessResult:
    def test_exit_code_zero_is_success(self, tmp_path):
        result = _build_success_result("hello", "", 0, "echo hello", tmp_path, 30)
        assert result.success is True

    def test_exit_code_zero_result_is_stdout(self, tmp_path):
        result = _build_success_result("hello\n", "", 0, "echo hello", tmp_path, 30)
        assert result.result == "hello\n"

    def test_nonzero_exit_is_failure(self, tmp_path):
        result = _build_success_result("", "error text", 1, "ls /bad", tmp_path, 30)
        assert result.success is False

    def test_nonzero_exit_result_contains_exit_code(self, tmp_path):
        result = _build_success_result("", "err", 2, "bad_cmd", tmp_path, 30)
        assert "exit 2" in result.result

    def test_metadata_exit_code(self, tmp_path):
        result = _build_success_result("out", "err", 0, "echo", tmp_path, 30)
        assert result.metadata["exit_code"] == 0

    def test_metadata_command(self, tmp_path):
        result = _build_success_result("", "", 0, "my_cmd", tmp_path, 30)
        assert result.metadata["command"] == "my_cmd"

    def test_metadata_timeout(self, tmp_path):
        result = _build_success_result("", "", 0, "echo", tmp_path, 60)
        assert result.metadata["timeout"] == 60

    def test_stderr_in_error_field_on_failure(self, tmp_path):
        result = _build_success_result("", "stderr msg", 1, "bad_cmd", tmp_path, 30)
        assert result.error == "stderr msg"

    def test_no_error_field_on_success(self, tmp_path):
        result = _build_success_result("ok", "", 0, "echo ok", tmp_path, 30)
        assert result.error is None


# ---------------------------------------------------------------------------
# TestHandleRunError
# ---------------------------------------------------------------------------


class TestHandleRunError:
    def test_timeout_expired(self, tmp_path):
        exc = subprocess.TimeoutExpired("echo", 10)
        result = _handle_run_error(
            exc, "echo hello", ["echo", "hello"], tmp_path, 10, False
        )
        assert result.success is False
        assert "timed out" in result.error

    def test_timeout_includes_duration(self, tmp_path):
        exc = subprocess.TimeoutExpired("echo", 5)
        result = _handle_run_error(exc, "echo hello", None, tmp_path, 5, True)
        assert "5" in result.error

    def test_file_not_found(self, tmp_path):
        exc = FileNotFoundError("No such file")
        result = _handle_run_error(exc, "foo bar", ["foo", "bar"], tmp_path, 30, False)
        assert result.success is False
        assert "not found" in result.error.lower() or "foo" in result.error

    def test_permission_error(self, tmp_path):
        exc = PermissionError("Permission denied")
        result = _handle_run_error(
            exc, "secret_cmd arg", ["secret_cmd", "arg"], tmp_path, 30, False
        )
        assert result.success is False
        assert "permission" in result.error.lower()

    def test_generic_oserror(self, tmp_path):
        exc = OSError("something went wrong")
        result = _handle_run_error(exc, "cmd", ["cmd"], tmp_path, 30, False)
        assert result.success is False
        assert result.error is not None

    def test_command_metadata_preserved_on_timeout(self, tmp_path):
        exc = subprocess.TimeoutExpired("echo", 10)
        result = _handle_run_error(exc, "echo hello", ["echo"], tmp_path, 10, False)
        assert result.metadata.get("command") == "echo hello"


# ---------------------------------------------------------------------------
# TestRunCommand
# ---------------------------------------------------------------------------


class TestRunCommand:
    def test_successful_execution(self, tmp_path):
        mock_result = MagicMock()
        mock_result.stdout = "hello\n"
        mock_result.stderr = ""
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result):
            result = run_command(
                "echo hello", ["echo", "hello"], tmp_path, 30, False, {}
            )
        assert result.success is True
        assert "hello" in result.result

    def test_timeout(self, tmp_path):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("echo", 1)):
            result = run_command(
                "echo hello", ["echo", "hello"], tmp_path, 1, False, {}
            )
        assert result.success is False
        assert "timed out" in result.error

    def test_command_not_found(self, tmp_path):
        with patch("subprocess.run", side_effect=FileNotFoundError("not found")):
            result = run_command(
                "nonexistent_cmd", ["nonexistent_cmd"], tmp_path, 30, False, {}
            )
        assert result.success is False

    def test_shell_mode_passes_shell_true(self, tmp_path):
        mock_result = MagicMock()
        mock_result.stdout = "output"
        mock_result.stderr = ""
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            run_command("echo hello", None, tmp_path, 30, True, {})
        assert mock_run.call_args[1]["shell"] is True

    def test_nonzero_exit_returns_failure(self, tmp_path):
        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.stderr = "error"
        mock_result.returncode = 1

        with patch("subprocess.run", return_value=mock_result):
            result = run_command("ls /bad", ["ls", "/bad"], tmp_path, 30, False, {})
        assert result.success is False


# ---------------------------------------------------------------------------
# TestGetSafeEnv
# ---------------------------------------------------------------------------


class TestGetSafeEnv:
    def test_picks_allowed_vars_from_environment(self, monkeypatch):
        monkeypatch.setenv("PATH", "/usr/bin")
        monkeypatch.setenv("HOME", "/home/user")
        result = get_safe_env({"PATH", "HOME"})
        assert result["PATH"] == "/usr/bin"
        assert result["HOME"] == "/home/user"

    def test_missing_vars_excluded(self):
        result = get_safe_env({"TEMPER_AI_NONEXISTENT_VAR_XYZ_99"})
        assert "TEMPER_AI_NONEXISTENT_VAR_XYZ_99" not in result

    def test_empty_set_returns_empty_dict(self):
        result = get_safe_env(set())
        assert result == {}

    def test_partial_vars_present(self, monkeypatch):
        monkeypatch.setenv("TEMPER_AI_TEST_VAR", "value123")
        result = get_safe_env({"TEMPER_AI_TEST_VAR", "TEMPER_AI_NOT_SET_VAR"})
        assert result.get("TEMPER_AI_TEST_VAR") == "value123"
        assert "TEMPER_AI_NOT_SET_VAR" not in result
