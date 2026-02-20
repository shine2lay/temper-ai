"""Tests for ScriptAgent — deterministic bash script execution."""
from __future__ import annotations

import subprocess
import time
from unittest.mock import MagicMock, patch

import pytest

from temper_ai.agent.script_agent import (
    DEFAULT_SCRIPT_TIMEOUT,
    ScriptAgent,
    _build_error_message,
    _execute_script,
    _parse_script_outputs,
)
from temper_ai.agent.utils.agent_factory import AgentFactory
from temper_ai.agent.utils.constants import AGENT_TYPE_SCRIPT
from temper_ai.storage.schemas.agent_config import (
    AgentConfig,
    AgentConfigInner,
    ErrorHandlingConfig,
    InferenceConfig,
    PromptConfig,
)


# ── Helpers ──────────────────────────────────────────────────────────


def _make_script_config(
    script: str = "echo hello",
    timeout: int | None = None,
    name: str = "test_script",
) -> AgentConfig:
    """Create a minimal script-type AgentConfig for testing."""
    return AgentConfig(
        agent=AgentConfigInner(
            name=name,
            description="Test script agent",
            type="script",
            script=script,
            timeout_seconds=timeout,
            error_handling=ErrorHandlingConfig(),
        )
    )


def _make_mock_proc(
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> MagicMock:
    """Create a mock subprocess result."""
    proc = MagicMock()
    proc.returncode = returncode
    proc.stdout = stdout
    proc.stderr = stderr
    return proc


# ── _parse_script_outputs ────────────────────────────────────────────


class TestParseScriptOutputs:
    """Tests for the ::output directive parser."""

    def test_basic_parsing(self) -> None:
        stdout = "line1\n::output key1=value1\nline2\n::output key2=value2"
        remaining, outputs = _parse_script_outputs(stdout)
        assert outputs == {"key1": "value1", "key2": "value2"}
        assert remaining == "line1\nline2"

    def test_no_directives(self) -> None:
        stdout = "just some output\nnothing special"
        remaining, outputs = _parse_script_outputs(stdout)
        assert outputs == {}
        assert remaining == stdout

    def test_value_with_spaces(self) -> None:
        stdout = "::output path=/tmp/some path/dir"
        remaining, outputs = _parse_script_outputs(stdout)
        assert outputs == {"path": "/tmp/some path/dir"}
        assert remaining == ""

    def test_empty_value(self) -> None:
        stdout = "::output key="
        remaining, outputs = _parse_script_outputs(stdout)
        assert outputs == {"key": ""}
        assert remaining == ""

    def test_empty_stdout(self) -> None:
        remaining, outputs = _parse_script_outputs("")
        assert outputs == {}
        assert remaining == ""

    def test_value_with_equals(self) -> None:
        """Equals signs in the value are preserved."""
        stdout = "::output expr=a=b+c"
        remaining, outputs = _parse_script_outputs(stdout)
        assert outputs == {"expr": "a=b+c"}

    def test_invalid_directive_kept_in_output(self) -> None:
        """Lines that almost match but don't are kept in output."""
        stdout = "::output =nokey\n::output \n::outputbad"
        remaining, outputs = _parse_script_outputs(stdout)
        assert outputs == {}
        assert "::output =nokey" in remaining
        assert "::outputbad" in remaining


# ── _build_error_message ─────────────────────────────────────────────


class TestBuildErrorMessage:
    """Tests for error message construction."""

    def test_success_returns_none(self) -> None:
        assert _build_error_message(0, "", None) is None

    def test_exec_error_takes_priority(self) -> None:
        msg = _build_error_message(-1, "stderr", "timed out")
        assert msg == "timed out"

    def test_stderr_used_when_no_exec_error(self) -> None:
        msg = _build_error_message(1, "something failed", None)
        assert msg == "something failed"

    def test_fallback_message(self) -> None:
        msg = _build_error_message(42, "", None)
        assert msg == "Script exited with code 42"

    def test_stderr_truncated(self) -> None:
        long_stderr = "x" * 500
        msg = _build_error_message(1, long_stderr, None)
        assert msg is not None
        assert len(msg) == 200  # noqa  scanner: skip-magic


# ── _execute_script ──────────────────────────────────────────────────


class TestExecuteScript:
    """Tests for the subprocess execution function."""

    @patch("temper_ai.agent.script_agent.subprocess")
    def test_success(self, mock_subprocess: MagicMock) -> None:
        mock_subprocess.run.return_value = _make_mock_proc(
            returncode=0, stdout="ok",
        )
        mock_subprocess.TimeoutExpired = subprocess.TimeoutExpired

        code, stdout, stderr, error = _execute_script("echo ok", 60, {})
        assert code == 0
        assert stdout == "ok"
        assert error is None

    @patch("temper_ai.agent.script_agent.subprocess")
    def test_nonzero_exit(self, mock_subprocess: MagicMock) -> None:
        mock_subprocess.run.return_value = _make_mock_proc(
            returncode=1, stderr="fail",
        )
        mock_subprocess.TimeoutExpired = subprocess.TimeoutExpired

        code, stdout, stderr, error = _execute_script("exit 1", 60, {})
        assert code == 1
        assert stderr == "fail"
        assert error is None  # _execute_script doesn't set error for non-zero

    @patch("temper_ai.agent.script_agent.subprocess")
    def test_timeout(self, mock_subprocess: MagicMock) -> None:
        mock_subprocess.run.side_effect = subprocess.TimeoutExpired("cmd", 10)
        mock_subprocess.TimeoutExpired = subprocess.TimeoutExpired

        code, stdout, stderr, error = _execute_script("sleep 100", 10, {})
        assert code == -1
        assert error is not None
        assert "timed out" in error.lower()

    @patch("temper_ai.agent.script_agent.subprocess")
    def test_oserror(self, mock_subprocess: MagicMock) -> None:
        mock_subprocess.run.side_effect = OSError("No such file")
        mock_subprocess.TimeoutExpired = subprocess.TimeoutExpired

        code, stdout, stderr, error = _execute_script("bad", 60, {})
        assert code == -1
        assert error is not None
        assert "No such file" in error


# ── ScriptAgent._run ─────────────────────────────────────────────────


class TestScriptAgentRun:
    """Tests for ScriptAgent._run (bypasses _setup)."""

    @patch("temper_ai.agent.script_agent._build_safe_env", return_value={})
    @patch("temper_ai.agent.script_agent.subprocess")
    def test_success_with_outputs(
        self, mock_subprocess: MagicMock, mock_env: MagicMock,
    ) -> None:
        mock_subprocess.run.return_value = _make_mock_proc(
            returncode=0,
            stdout="hello world\n::output result=42\n::output status=ok",
        )
        mock_subprocess.TimeoutExpired = subprocess.TimeoutExpired

        agent = ScriptAgent(_make_script_config(script="echo hello"))
        agent._stream_callback = None
        agent._observer = None

        response = agent._run({}, None, time.time())

        assert response.error is None
        assert "hello world" in response.output
        assert "::output" not in response.output
        assert response.metadata["outputs"]["result"] == "42"
        assert response.metadata["outputs"]["status"] == "ok"
        assert response.metadata["exit_code"] == 0
        assert response.tokens == 0
        assert response.estimated_cost_usd == 0.0

    @patch("temper_ai.agent.script_agent._build_safe_env", return_value={})
    @patch("temper_ai.agent.script_agent.subprocess")
    def test_template_rendering(
        self, mock_subprocess: MagicMock, mock_env: MagicMock,
    ) -> None:
        """Verify Jinja2 variables are rendered with shlex.quote."""
        mock_subprocess.run.return_value = _make_mock_proc(returncode=0)
        mock_subprocess.TimeoutExpired = subprocess.TimeoutExpired

        agent = ScriptAgent(_make_script_config(script="echo {{ name }}"))
        agent._stream_callback = None
        agent._observer = None

        agent._run({"name": "/tmp/test dir"}, None, time.time())

        rendered_script = mock_subprocess.run.call_args[0][0]
        assert "'/tmp/test dir'" in rendered_script

    @patch("temper_ai.agent.script_agent._build_safe_env", return_value={})
    @patch("temper_ai.agent.script_agent.subprocess")
    def test_nonzero_exit_code(
        self, mock_subprocess: MagicMock, mock_env: MagicMock,
    ) -> None:
        mock_subprocess.run.return_value = _make_mock_proc(
            returncode=1, stderr="command failed",
        )
        mock_subprocess.TimeoutExpired = subprocess.TimeoutExpired

        agent = ScriptAgent(_make_script_config(script="exit 1"))
        agent._stream_callback = None
        agent._observer = None

        response = agent._run({}, None, time.time())

        assert response.error is not None
        assert "command failed" in response.error
        assert response.metadata["exit_code"] == 1

    @patch("temper_ai.agent.script_agent._build_safe_env", return_value={})
    @patch("temper_ai.agent.script_agent.subprocess")
    def test_timeout_handling(
        self, mock_subprocess: MagicMock, mock_env: MagicMock,
    ) -> None:
        mock_subprocess.run.side_effect = subprocess.TimeoutExpired("cmd", 10)
        mock_subprocess.TimeoutExpired = subprocess.TimeoutExpired

        agent = ScriptAgent(_make_script_config(script="sleep 100", timeout=10))
        agent._stream_callback = None
        agent._observer = None

        response = agent._run({}, None, time.time())

        assert response.error is not None
        assert "timed out" in response.error.lower()
        assert response.metadata["exit_code"] == -1

    @patch("temper_ai.agent.script_agent._build_safe_env", return_value={})
    @patch("temper_ai.agent.script_agent.subprocess")
    def test_custom_timeout_used(
        self, mock_subprocess: MagicMock, mock_env: MagicMock,
    ) -> None:
        """Verify custom timeout_seconds from config is passed to subprocess."""
        mock_subprocess.run.return_value = _make_mock_proc(returncode=0)
        mock_subprocess.TimeoutExpired = subprocess.TimeoutExpired

        agent = ScriptAgent(_make_script_config(script="echo ok", timeout=60))
        agent._stream_callback = None
        agent._observer = None

        agent._run({}, None, time.time())

        call_kwargs = mock_subprocess.run.call_args[1]
        assert call_kwargs["timeout"] == 60

    @patch("temper_ai.agent.script_agent._build_safe_env", return_value={})
    @patch("temper_ai.agent.script_agent.subprocess")
    def test_default_timeout_used(
        self, mock_subprocess: MagicMock, mock_env: MagicMock,
    ) -> None:
        """Verify DEFAULT_SCRIPT_TIMEOUT when not specified in config."""
        mock_subprocess.run.return_value = _make_mock_proc(returncode=0)
        mock_subprocess.TimeoutExpired = subprocess.TimeoutExpired

        agent = ScriptAgent(_make_script_config(script="echo ok"))
        agent._stream_callback = None
        agent._observer = None

        agent._run({}, None, time.time())

        call_kwargs = mock_subprocess.run.call_args[1]
        assert call_kwargs["timeout"] == DEFAULT_SCRIPT_TIMEOUT

    @patch("temper_ai.agent.script_agent._build_safe_env", return_value={})
    @patch("temper_ai.agent.script_agent.subprocess")
    def test_stream_events_emitted(
        self, mock_subprocess: MagicMock, mock_env: MagicMock,
    ) -> None:
        """Verify stream events are sent to callback."""
        mock_subprocess.run.return_value = _make_mock_proc(
            returncode=0, stdout="output",
        )
        mock_subprocess.TimeoutExpired = subprocess.TimeoutExpired

        mock_cb = MagicMock()
        agent = ScriptAgent(_make_script_config(script="echo ok"))
        agent._stream_callback = mock_cb
        agent._observer = None

        agent._run({}, None, time.time())

        assert mock_cb.call_count >= 2  # At least TOOL_START + TOOL_RESULT


# ── ScriptAgent.execute (integration) ────────────────────────────────


class TestScriptAgentExecute:
    """Integration tests for the full execute() flow."""

    @patch("temper_ai.agent.script_agent._build_safe_env", return_value={})
    @patch("temper_ai.agent.script_agent.subprocess")
    def test_full_execute_flow(
        self, mock_subprocess: MagicMock, mock_env: MagicMock,
    ) -> None:
        """Test execute() including _setup path."""
        mock_subprocess.run.return_value = _make_mock_proc(
            returncode=0,
            stdout="done\n::output key=val",
        )
        mock_subprocess.TimeoutExpired = subprocess.TimeoutExpired

        agent = ScriptAgent(_make_script_config(script="echo done"))
        response = agent.execute({"query": "test"})

        assert response.error is None
        assert "done" in response.output
        assert response.metadata["outputs"]["key"] == "val"

    @patch("temper_ai.agent.script_agent._build_safe_env", return_value={})
    @patch("temper_ai.agent.script_agent.subprocess")
    def test_execute_error_handling(
        self, mock_subprocess: MagicMock, mock_env: MagicMock,
    ) -> None:
        """Test that execute() handles errors gracefully via _on_error."""
        mock_subprocess.run.side_effect = OSError("exec failed")
        mock_subprocess.TimeoutExpired = subprocess.TimeoutExpired

        agent = ScriptAgent(_make_script_config(script="bad"))
        response = agent.execute({"query": "test"})

        assert response.error is not None


# ── AgentFactory ─────────────────────────────────────────────────────


class TestScriptAgentFactory:
    """Tests for factory registration."""

    def test_factory_creates_script_agent(self) -> None:
        AgentFactory.reset_for_testing()
        config = _make_script_config()
        agent = AgentFactory.create(config)
        assert isinstance(agent, ScriptAgent)
        AgentFactory.reset_for_testing()

    def test_factory_lists_script_type(self) -> None:
        AgentFactory.reset_for_testing()
        types = AgentFactory.list_types()
        assert AGENT_TYPE_SCRIPT in types
        AgentFactory.reset_for_testing()


# ── Schema validation ────────────────────────────────────────────────


class TestScriptAgentSchema:
    """Tests for AgentConfigInner validation with script type."""

    def test_valid_script_config(self) -> None:
        config = AgentConfigInner(
            name="test",
            description="test",
            type="script",
            script="echo hello",
            error_handling=ErrorHandlingConfig(),
        )
        assert config.script == "echo hello"
        assert config.prompt is None
        assert config.inference is None

    def test_script_type_requires_script(self) -> None:
        with pytest.raises(ValueError, match="script.*required"):
            AgentConfigInner(
                name="test",
                description="test",
                type="script",
                error_handling=ErrorHandlingConfig(),
            )

    def test_standard_type_requires_prompt(self) -> None:
        with pytest.raises(ValueError, match="prompt.*required"):
            AgentConfigInner(
                name="test",
                description="test",
                type="standard",
                inference=InferenceConfig(provider="ollama", model="test"),
                error_handling=ErrorHandlingConfig(),
            )

    def test_standard_type_requires_inference(self) -> None:
        with pytest.raises(ValueError, match="inference.*required"):
            AgentConfigInner(
                name="test",
                description="test",
                type="standard",
                prompt=PromptConfig(inline="test"),
                error_handling=ErrorHandlingConfig(),
            )

    def test_script_with_timeout(self) -> None:
        config = AgentConfigInner(
            name="test",
            description="test",
            type="script",
            script="echo hello",
            timeout_seconds=60,
            error_handling=ErrorHandlingConfig(),
        )
        assert config.timeout_seconds == 60


# ── ScriptAgent capabilities and config ──────────────────────────────


class TestScriptAgentMeta:
    """Tests for get_capabilities and validate_config."""

    def test_get_capabilities(self) -> None:
        agent = ScriptAgent(_make_script_config(name="my_script"))
        caps = agent.get_capabilities()
        assert caps["type"] == "script"
        assert caps["tools"] == []
        assert caps["name"] == "my_script"
        assert caps["supports_streaming"] is False

    def test_validate_config_success(self) -> None:
        agent = ScriptAgent(_make_script_config())
        assert agent.validate_config() is True

    def test_validate_config_missing_script(self) -> None:
        config = _make_script_config()
        config.agent.script = None
        agent = ScriptAgent(config)
        with pytest.raises(ValueError, match="requires a 'script' field"):
            agent.validate_config()
