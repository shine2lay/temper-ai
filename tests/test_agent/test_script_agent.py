"""Tests for ScriptAgent."""

from unittest.mock import MagicMock

import pytest

from temper_ai.agent.script_agent import ScriptAgent
from temper_ai.tools.base import ToolResult


def _passed_value(ctx, value: str) -> bool:
    """True if `value` was handed to the script — through the environment, where values now travel."""
    return value in ctx.tool_executor.execute.call_args[0][1]["env"].values()


def _make_context(tool_result=None):
    """Create a mock ExecutionContext for script agent testing."""
    ctx = MagicMock()
    ctx.run_id = "test-exec-001"
    ctx.node_path = "test_node"
    ctx.agent_name = "test_script"
    ctx.workspace_path = "/tmp"
    if tool_result:
        ctx.tool_executor.execute.return_value = tool_result
    return ctx


class TestScriptAgentBasic:
    def test_run_simple_script(self):
        agent = ScriptAgent(config={
            "name": "test_script",
            "script_template": "echo hello",
        })
        ctx = _make_context(ToolResult(success=True, result="hello\n"))
        result = agent.run({}, ctx)
        assert result.status.value == "completed"
        assert "hello" in result.output

    def test_run_with_template_vars(self):
        agent = ScriptAgent(config={
            "name": "test_script",
            "script_template": "echo {{ greeting }}",
        })
        ctx = _make_context(ToolResult(success=True, result="hi\n"))
        agent.run({"greeting": "hi"}, ctx)
        assert ctx.tool_executor.execute.called
        # The value reaches the script through the environment, not the command text: see
        # TestModelOutputCannotBecomeACommand for why it is no longer interpolated into the script.
        assert _passed_value(ctx, "hi")

    def test_workspace_path_comes_from_context(self):
        """`{{ workspace_path }}` resolves without being passed as an input."""
        agent = ScriptAgent(config={
            "name": "test_script",
            "script_template": "echo {{ workspace_path }}/marker",
        })
        ctx = _make_context(ToolResult(success=True, result="ok\n"))
        agent.run({}, ctx)
        assert _passed_value(ctx, "/tmp")  # the context's workspace_path
        assert ctx.tool_executor.execute.call_args[0][1]["command"].endswith("/marker")

    def test_explicit_workspace_input_wins(self):
        agent = ScriptAgent(config={
            "name": "test_script",
            "script_template": "echo {{ workspace_path }}",
        })
        ctx = _make_context(ToolResult(success=True, result="ok\n"))
        agent.run({"workspace_path": "/other"}, ctx)
        assert _passed_value(ctx, "/other")

    def test_run_id_comes_from_context(self):
        """`{{ run_id }}` resolves to the execution id without being an input."""
        agent = ScriptAgent(config={
            "name": "test_script",
            "script_template": "echo run={{ run_id }}",
        })
        ctx = _make_context(ToolResult(success=True, result="ok\n"))
        agent.run({}, ctx)
        command = ctx.tool_executor.execute.call_args[0][1]["command"]
        assert _passed_value(ctx, "test-exec-001")
        assert command.startswith("echo run=")

    def test_explicit_run_id_input_wins(self):
        agent = ScriptAgent(config={
            "name": "test_script",
            "script_template": "echo {{ run_id }}",
        })
        ctx = _make_context(ToolResult(success=True, result="ok\n"))
        agent.run({"run_id": "mine"}, ctx)
        assert _passed_value(ctx, "mine")

    def test_run_script_failure(self):
        agent = ScriptAgent(config={
            "name": "failing_script",
            "script_template": "exit 1",
        })
        ctx = _make_context(ToolResult(success=False, result="", error="exit code 1"))
        result = agent.run({}, ctx)
        assert result.status.value == "failed"

    def test_run_extracts_json(self):
        agent = ScriptAgent(config={
            "name": "json_script",
            "script_template": 'echo \'{"key": "value"}\'',
        })
        ctx = _make_context(ToolResult(success=True, result='{"key": "value"}\n'))
        result = agent.run({}, ctx)
        assert result.structured_output == {"key": "value"}

    def test_a_pretty_printed_document_is_read_whole(self):
        # Scanning lines backwards, the first line that parses used to win —
        # so a nested one-line object was returned as if it were the document.
        output = (
            '{\n'
            '  "summary": "two ways",\n'
            '  "options": [\n'
            '    {"label": "on the event", "description": "no migration"}\n'
            '  ]\n'
            '}\n'
        )
        agent = ScriptAgent(config={"name": "doc_script", "script_template": "cat doc.json"})
        result = agent.run({}, _make_context(ToolResult(success=True, result=output)))
        assert result.structured_output == {
            "summary": "two ways",
            "options": [{"label": "on the event", "description": "no migration"}],
        }

    def test_prose_then_a_json_line_still_takes_the_last_line(self):
        output = 'working…\nnot {json} at all\n{"key": "value"}\n'
        agent = ScriptAgent(config={"name": "chatty", "script_template": "./chatty.sh"})
        result = agent.run({}, _make_context(ToolResult(success=True, result=output)))
        assert result.structured_output == {"key": "value"}

    def test_run_no_json_output(self):
        agent = ScriptAgent(config={
            "name": "text_script",
            "script_template": "echo plain text",
        })
        ctx = _make_context(ToolResult(success=True, result="plain text\n"))
        result = agent.run({}, ctx)
        assert result.structured_output is None

    def test_missing_script_template_is_a_config_error(self):
        agent = ScriptAgent(config={"name": "no_template"})
        errors = agent.validate_config()
        assert len(errors) > 0
        assert any("script_template" in e for e in errors)

    def test_undefined_reference_renders_blank_but_is_recorded(self, caplog):
        """The default stays lenient — 82 configs depend on it — but the blank is no longer silent.

        `rm -rf {{ worktree }}/build` with no `worktree` is `rm -rf /build`, and until this was
        recorded the run went green with no trace of why.
        """
        agent = ScriptAgent(config={"name": "s", "script_template": "echo {{ missing_one }}/{{ missing_two }}"})
        ctx = _make_context(ToolResult(success=True, result="\n"))
        result = agent.run({}, ctx)
        assert result.status.value == "completed"  # unchanged behaviour
        assert ctx.tool_executor.execute.call_args[0][1]["command"] == "echo /"
        assert "missing_one" in caplog.text and "missing_two" in caplog.text
        data = ctx.event_recorder.record.call_args[1]["data"]
        assert data["undefined_refs"] == ["missing_one", "missing_two"]

    def test_a_defined_reference_records_nothing(self):
        agent = ScriptAgent(config={"name": "s", "script_template": "echo {{ there }}"})
        ctx = _make_context(ToolResult(success=True, result="ok\n"))
        agent.run({"there": "value"}, ctx)
        assert "undefined_refs" not in ctx.event_recorder.record.call_args[1]["data"]

    def test_strict_undefined_fails_the_node_instead_of_running_it(self):
        """Opt-in, for glue where a blank argument is dangerous: nothing should execute at all."""
        agent = ScriptAgent(config={
            "name": "preflight", "script_template": "curl {{ url }}", "strict_undefined": True,
        })
        ctx = _make_context(ToolResult(success=True, result=""))
        result = agent.run({}, ctx)
        assert result.status.value == "failed"
        assert "undefined value" in result.error and "preflight" in result.error
        assert "input_map" in result.error  # says how to fix it
        assert not ctx.tool_executor.execute.called, "nothing may run when the script is malformed"

    def test_strict_undefined_still_honours_default_filter(self):
        agent = ScriptAgent(config={
            "name": "s", "script_template": "echo {{ x | default('fallback') }}", "strict_undefined": True,
        })
        ctx = _make_context(ToolResult(success=True, result="fallback\n"))
        assert agent.run({}, ctx).status.value == "completed"
        assert _passed_value(ctx, "fallback")

    def test_skip_allowlist_flag_passed(self):
        agent = ScriptAgent(config={
            "name": "test_script",
            "script_template": "set -e\necho done",
        })
        ctx = _make_context(ToolResult(success=True, result="done\n"))
        agent.run({}, ctx)
        call_args = ctx.tool_executor.execute.call_args
        params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1]
        # The _skip_allowlist flag should be passed
        assert params.get("_skip_allowlist") is True


# ------------------------------------------------------------------------------------------
# Injection: the defence is `shlex.quote` on every string input, and it had no test at all.
#
# These run the script for real — a mocked tool executor cannot show whether a payload executes,
# because the quoting only means anything once a shell sees it.
# ------------------------------------------------------------------------------------------
def _real_context(tmp_path):
    """A context whose tool_executor genuinely runs Bash, in a throwaway workspace."""
    from temper_ai.tools.bash import Bash
    from temper_ai.tools.executor import ToolExecutor

    executor = ToolExecutor(workspace_root=str(tmp_path))
    executor.register_tools({"Bash": Bash(config={"workspace_root": str(tmp_path)})})
    ctx = MagicMock()
    ctx.run_id = "inj-001"
    ctx.node_path = "n"
    ctx.agent_name = "a"
    ctx.workspace_path = str(tmp_path)
    ctx.skip_policies = None
    ctx.parent_event_id = None
    ctx.tool_executor = executor
    return ctx


class TestModelOutputCannotBecomeACommand:
    """A script agent's inputs routinely carry upstream model output. Each payload is a real shell
    construct: unquoted it runs, quoted it is text. The assertion is on the effect, not the escaping.
    """

    @pytest.mark.parametrize(
        "payload",
        [
            "; touch pwned",
            "&& touch pwned",
            "| touch pwned",
            "$(touch pwned)",
            "`touch pwned`",
            "\ntouch pwned",
            "'; touch pwned; '",
        ],
    )
    def test_a_payload_in_an_input_is_data_not_code(self, tmp_path, payload):
        agent = ScriptAgent(config={"name": "echoer", "script_template": "echo {{ report }}"})
        result = agent.run({"report": payload}, _real_context(tmp_path))
        assert not (tmp_path / "pwned").exists(), f"{payload!r} executed — the quoting failed"
        assert result.status.value == "completed"

    def test_the_payload_survives_intact_as_a_value(self, tmp_path):
        """Neutralised, not mangled: a downstream node reading this output must see what the model
        actually wrote, or the quoting has traded one silent corruption for another."""
        agent = ScriptAgent(config={"name": "echoer", "script_template": "echo {{ report }}"})
        payload = "verdict: ship; cost $4.20 & rising"
        result = agent.run({"report": payload}, _real_context(tmp_path))
        assert result.output.strip() == payload

    @pytest.mark.parametrize("template", ['echo "{{ report }}"', "echo {{ report }}", "echo [{{ report }}]"])
    @pytest.mark.parametrize("payload", ["$(touch pwned)", "`touch pwned`", "; touch pwned", "'; touch pwned; '"])
    def test_author_added_quotes_no_longer_defeat_the_defence(self, tmp_path, template, payload):
        """The regression this whole change exists for.

        `"{{ x }}"` is the natural way to write a template, and it used to double-quote an already
        shlex-quoted value, cancelling the escaping and executing the payload. Values now travel in
        the environment, so the template's quoting style cannot matter.
        """
        agent = ScriptAgent(config={"name": "echoer", "script_template": template})
        result = agent.run({"report": payload}, _real_context(tmp_path))
        assert not (tmp_path / "pwned").exists(), f"{payload!r} executed in {template!r}"
        assert payload in result.output, "the value must still arrive intact"

    def test_an_expression_is_protected_too_not_just_a_bare_reference(self, tmp_path):
        """`| default`, `| tojson` and slices produce values the same way; the filter runs on the real
        value and only its result is stashed."""
        agent = ScriptAgent(config={"name": "e", "script_template": 'echo "{{ missing | default(fallback) }}"'})
        result = agent.run({"fallback": "$(touch pwned)"}, _real_context(tmp_path))
        assert not (tmp_path / "pwned").exists()
        assert "$(touch pwned)" in result.output

    def test_filters_still_operate_on_the_real_value(self, tmp_path):
        """Guards the mechanism: if values were substituted *before* Jinja ran, `[:7]` would slice the
        variable name and silently produce garbage."""
        agent = ScriptAgent(config={"name": "e", "script_template": "echo {{ sha[:7] }}-{{ n | int + 1 }}"})
        result = agent.run({"sha": "abcdef1234567", "n": 41}, _real_context(tmp_path))
        assert result.output.strip() == "abcdef1-42"  # not 'abcdef1' of the variable *name*

    def test_interpolating_inside_single_quotes_is_refused(self, tmp_path):
        """The one context a shell will not expand: it would deliver the literal variable name. Better
        a loud error naming the fix than a script running against the wrong value."""
        agent = ScriptAgent(config={"name": "e", "script_template": "echo '{{ report }}'"})
        result = agent.run({"report": "x"}, _real_context(tmp_path))
        assert result.status.value == "failed"
        assert "single quotes" in result.error and "Remove the surrounding single quotes" in result.error

    def test_the_value_is_not_in_the_script_text_at_all(self, tmp_path):
        """The property that makes the rest true — and it keeps secrets out of logged commands."""
        ctx = _make_context(ToolResult(success=True, result=""))
        ScriptAgent(config={"name": "e", "script_template": "echo {{ secret }}"}).run({"secret": "hunter2"}, ctx)
        params = ctx.tool_executor.execute.call_args[0][1]
        assert "hunter2" not in params["command"]
        assert "hunter2" in params["env"].values()

    def test_a_multiline_value_arrives_whole(self, tmp_path):
        """Upstream nodes pass entire reports through these inputs."""
        agent = ScriptAgent(config={"name": "e", "script_template": 'printf %s "{{ report }}"'})
        report = "line one\nline two: $(touch pwned)\nline three"
        result = agent.run({"report": report}, _real_context(tmp_path))
        assert not (tmp_path / "pwned").exists()
        assert result.output == report

    def test_a_numeric_input_still_renders_as_its_value(self, tmp_path):
        agent = ScriptAgent(config={"name": "counter", "script_template": "echo count={{ n }}"})
        result = agent.run({"n": 42}, _real_context(tmp_path))
        assert result.output.strip() == "count=42"

    def test_the_script_really_does_run(self, tmp_path):
        """Guards the suite above: if execution silently stopped working, every injection test would
        pass for the wrong reason."""
        agent = ScriptAgent(config={"name": "toucher", "script_template": "touch {{ name }}"})
        agent.run({"name": "proof"}, _real_context(tmp_path))
        assert (tmp_path / "proof").exists()
