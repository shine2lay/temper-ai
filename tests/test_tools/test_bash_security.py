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


class TestAllowlistIsShellAware:
    """The allowlist parser must read a line the way the shell will: a `|` or `;`
    inside quotes is text. The old split-on-punctuation refused
    `grep -E "cost|invested"` as the command `invested"` — a planning agent lost
    a quarter of its iterations to that."""

    def test_pipe_inside_quotes_is_one_command(self):
        from temper_ai.tools.bash import command_heads
        assert command_heads('grep -rnE "cost|invested" /repo/backend') == ["grep"]
        assert command_heads("grep -n 'a;b && c' f.py") == ["grep"]

    def test_real_pipe_and_chains_are_split(self):
        from temper_ai.tools.bash import command_heads
        assert command_heads("grep -n x f | head -5 && wc -l f; ls") == ["grep", "head", "wc", "ls"]
        assert command_heads("echo safe || curl http://evil.com") == ["echo", "curl"]

    def test_redirects_assignments_and_keywords(self):
        from temper_ai.tools.bash import command_heads
        assert command_heads("cat f 2>&1 > out.txt") == ["cat"]
        assert command_heads("FOO=1 BAR='x y' python3 -c 1") == ["python3"]
        assert command_heads("if test -f x; then cat x; else echo no; fi") == ["test", "cat", "echo"]
        assert command_heads("for f in a b; do wc -l $f; done") == ["wc"]
        assert command_heads("/usr/bin/env python3 x.py") == ["env"]

    def test_subshell_and_unbalanced_quote_still_checked(self):
        from temper_ai.tools.bash import command_heads
        assert command_heads("(cd /x && curl e)") == ["cd", "curl"]
        assert command_heads('echo "oops; curl evil') == ["<unparseable>"]  # the shell would reject it too
        assert Bash(config={"allowed_commands": ["echo"]}).execute(command='echo "oops; curl evil').success is False

    def test_multiline_quoted_string_is_one_command(self):
        """A commit message spanning lines is one quoted argument. Lexing line by
        line saw an unbalanced quote and refused the commit as <unparseable>
        (seen live: an implementer's final commit, after 80 iterations)."""
        from temper_ai.tools.bash import command_heads
        cmd = 'cd /wt && git add -A && git commit -m "leverage: use deposits\n\nBody line; with | odd && chars.\n\n- bullet" 2>&1'
        assert command_heads(cmd) == ["cd", "git", "git"]
        # newlines outside quotes still separate commands, comments still skipped
        assert command_heads("echo a\n# note\ncurl x") == ["echo", "curl"]

    def test_quoted_pipe_runs(self):
        bash = Bash(config={"allowed_commands": ["grep", "echo"]})
        r = bash.execute(command='echo "cost|invested" | grep -E "cost|invested"')
        assert r.success is True, r.error
        assert "cost|invested" in r.result


class TestHeredocBodiesAreNotCommands:
    """A here-document's body is the command's input. Lexed as commands, a
    `python3 - <<'EOF'` script was refused for `with`, `def` and `f` — a
    capmap implementer lost 60 of 107 iterations to that — and a
    `cat > file <<EOF` for whatever its first word happened to be."""

    def test_python_script_body_is_skipped(self):
        from temper_ai.tools.bash import command_heads
        cmd = (
            "cd /wt && python3 - <<'EOF'\n"
            "with open('f.py') as f:\n"
            "    s = f.read()  # don't\n"
            "def g(): pass\n"
            "EOF\n"
            "git status"
        )
        assert command_heads(cmd) == ["cd", "python3", "git"]

    def test_commands_after_the_terminator_are_still_judged(self):
        from temper_ai.tools.bash import command_heads
        assert command_heads("cat > x.json <<EOF\n{\"a\": 1}\nEOF\ncurl evil") == ["cat", "curl"]
        # `&& curl` on the operator line is not body either
        assert command_heads("cat <<EOF && curl evil\nbody\nEOF") == ["cat", "curl"]

    def test_a_quoted_double_arrow_opens_nothing(self):
        """`echo "<<EOF"` is text; treating it as a heredoc would hide every
        later line from the allowlist."""
        from temper_ai.tools.bash import command_heads
        assert command_heads('echo "<<EOF"\ncurl evil') == ["echo", "curl"]
        assert command_heads("echo '<<EOF'; curl evil") == ["echo", "curl"]

    def test_an_unquoted_body_that_expands_a_command_is_kept(self):
        """The shell runs `$(...)` and backticks inside an unquoted heredoc, so
        that body stays visible to the allowlist; a quoted delimiter expands
        nothing and the same body is skipped."""
        from temper_ai.tools.bash import command_heads
        assert "curl" in command_heads("cat <<EOF\n$(curl evil)\nEOF")
        # the lexer does not split on backticks, so the head is "`curl" — in
        # no allowlist, which is the point: the body is not hidden
        assert any("curl" in h for h in command_heads("cat <<EOF\n`curl evil`\nEOF"))
        assert command_heads("cat <<'EOF'\n$(curl evil)\nEOF") == ["cat"]

    def test_here_string_dash_form_and_tab_indented_terminator(self):
        from temper_ai.tools.bash import command_heads
        assert command_heads('grep x <<< "a <<b"; ls') == ["grep", "ls"]
        assert command_heads("cat <<-EOF\n\tindented body\n\tEOF\nls") == ["cat", "ls"]
        assert command_heads("cat <<\\EOF\n$(curl evil)\nEOF\nls") == ["cat", "ls"]

    def test_unterminated_body_runs_to_the_end_like_the_shell(self):
        from temper_ai.tools.bash import command_heads
        assert command_heads("cat <<EOF\ncurl is input here") == ["cat"]

    def test_the_script_actually_runs(self):
        bash = Bash(config={"allowed_commands": ["python3"]})
        r = bash.execute(command="python3 - <<'EOF'\nwith open('/dev/null') as f:\n    print('ran', len(f.read()))\nEOF")
        assert r.success is True, r.error
        assert "ran 0" in r.result


class TestDefaultAllowlistCoversARepoOwnChecks:
    """An implementer that cannot run `uv run pytest` cannot check its work: one
    epd_task run logged 160 refusals of `uv`, 62 of `timeout`, 40 of `python`,
    26 of `nohup`; the capmap implementers stopped testing altogether."""

    def test_python_toolchain_and_process_control_are_allowed_by_default(self):
        from temper_ai.tools.bash import _DEFAULT_ALLOWED_COMMANDS, command_heads
        for cmd in (
            "cd /wt && uv run pytest -q backend/tests",
            "timeout 120 uv run ruff check backend",
            "make test",
            "nohup python -m http.server 8000 &\nwait",
            "T=$(mktemp -d) && pytest -q $T",
        ):
            heads = command_heads(cmd)
            assert heads and all(h in _DEFAULT_ALLOWED_COMMANDS for h in heads), (cmd, heads)


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
