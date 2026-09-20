"""Tests for Bash tool."""

import time

from temper_ai.tools.bash import Bash


class TestBash:
    def setup_method(self):
        self.bash = Bash()

    def test_simple_command(self):
        r = self.bash.execute(command="echo hello")
        assert r.success is True
        assert "hello" in r.result

    def test_pwd(self):
        r = self.bash.execute(command="pwd")
        assert r.success is True
        assert "/" in r.result

    def test_ls(self):
        r = self.bash.execute(command="ls /tmp")
        assert r.success is True

    def test_command_with_exit_code(self):
        r = self.bash.execute(command="false")
        assert r.success is False
        assert r.metadata.get("exit_code") != 0

    def test_stderr_captured(self):
        r = self.bash.execute(command="echo err >&2")
        assert "err" in r.result
        assert "STDERR" in r.result

    def test_empty_command(self):
        r = self.bash.execute(command="")
        assert r.success is False
        assert "Empty command" in r.error

    def test_timeout(self):
        bash = Bash(config={"allowed_commands": ["sleep"]})
        r = bash.execute(command="sleep 10", timeout=1)
        assert r.success is False
        assert "timed out" in r.error.lower()

    def test_timeout_kills_everything_the_command_started(self, tmp_path):
        """A timed-out command dies whole, not just its shell.

        `subprocess.run` killed the shell and left its children running: every
        `uv run pytest | tail` that outran its timeout kept the suite going in
        the container, and the executor's worker waiting on it. The subshell
        here would touch the marker 2s in; killed with the group at 1s, it does not.
        """
        mark = tmp_path / "survived"
        bash = Bash(config={"allowed_commands": ["sleep", "touch"]})
        r = bash.execute(command=f"(sleep 2; touch {mark}) & sleep 10", timeout=1)
        assert r.success is False
        assert "killed" in r.error
        time.sleep(2.5)
        assert not mark.exists(), "a child of the timed-out command outlived it"

    def test_max_timeout_cap(self):
        # Even if you pass a huge timeout, it's capped at 600
        r = self.bash.execute(command="echo fast", timeout=99999)
        assert r.success is True


class TestBashAllowlist:
    def test_default_allows_common_commands(self):
        bash = Bash()
        r = bash.execute(command="echo hello")
        assert r.success is True

    def test_blocked_command(self):
        bash = Bash(config={"allowed_commands": ["ls", "echo"]})
        r = bash.execute(command="rm -rf /")
        assert r.success is False
        assert "not in allowed list" in r.error

    def test_custom_allowlist(self):
        bash = Bash(config={"allowed_commands": ["python3"]})
        r = bash.execute(command="python3 -c 'print(42)'")
        assert r.success is True
        assert "42" in r.result

    def test_command_with_path_prefix(self):
        bash = Bash(config={"allowed_commands": ["echo"]})
        r = bash.execute(command="/bin/echo hello")
        assert r.success is True


class TestBashWorkspace:
    def test_workspace_root(self):
        bash = Bash(config={"workspace_root": "/tmp"})
        r = bash.execute(command="pwd")
        assert r.success is True
        assert "/tmp" in r.result
