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
        # ... and the output is not compacted for a model: code reads it
        assert params.get("_raw_output") is True

    def test_json_that_does_not_parse_is_reported(self, caplog):
        agent = ScriptAgent(config={"name": "cut", "script_template": "echo x"})
        ctx = _make_context(ToolResult(success=True, result='{"pitch": "cut here'))
        with caplog.at_level("WARNING"):
            result = agent.run({}, ctx)
        assert result.structured_output is None
        assert "printed JSON that does not parse" in caplog.text
        done = [c for c in ctx.event_recorder.record.call_args_list if c.kwargs.get("data", {}).get("agent_name") == "cut"
                and "has_structured_output" in c.kwargs["data"]]
        assert done and "does not parse" in done[-1].kwargs["data"]["structured_output_error"]


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

    def test_interpolating_inside_a_quoted_heredoc_is_refused(self, tmp_path):
        """The b003 gate bug. `python3 - <<'PYEOF'` with `{{ x }}` in the body: the shell expands
        nothing there, so the Python received the text `$TEMPER_V1` and task_gate judged
        "temper_v" against "approve" on every build, requesting changes each time."""
        template = "python3 - <<'PYEOF'\nverdict = \"{{ verdict }}\"\nprint(verdict)\nPYEOF\n"
        agent = ScriptAgent(config={"name": "gate", "script_template": template})
        result = agent.run({"verdict": "approve"}, _real_context(tmp_path))
        assert result.status.value == "failed"
        assert "quoted heredoc (<<'PYEOF')" in result.error and "| env" in result.error

    def test_the_env_filter_carries_a_value_into_a_quoted_heredoc(self, tmp_path):
        """The way through: ask for the variable's name and read the environment yourself. The
        payload is the proof — it arrives whole and runs nothing."""
        template = (
            "python3 - <<'PYEOF'\n"
            "import os\n"
            "print(os.environ[\"{{ verdict | env }}\"])\n"
            "PYEOF\n"
        )
        agent = ScriptAgent(config={"name": "gate", "script_template": template})
        payload = "approve'; touch pwned; '$(touch pwned)"
        result = agent.run({"verdict": payload}, _real_context(tmp_path))
        assert result.status.value == "completed", result.error
        assert result.output.strip() == payload
        assert not (tmp_path / "pwned").exists()

    def test_an_unquoted_heredoc_expands_the_value_and_ignores_quotes_in_the_body(self, tmp_path):
        """`<<EOF` expands like double quotes: the bare reference is right there, and an apostrophe
        in the body is data, not an open shell quote that swallows the rest of the script."""
        template = "cat <<EOF\nit's {{ a }}, \"{{ b }}\"\nEOF\necho {{ c }}\n"
        agent = ScriptAgent(config={"name": "e", "script_template": template})
        result = agent.run({"a": "$(touch pwned)", "b": "two words", "c": "after"}, _real_context(tmp_path))
        assert result.status.value == "completed", result.error
        assert result.output == "it's $(touch pwned), \"two words\"\nafter\n"
        assert not (tmp_path / "pwned").exists()

    def test_apostrophes_in_a_quoted_heredoc_body_do_not_poison_what_follows(self, tmp_path):
        """Before the scanner knew heredocs, `don't` in a Python body opened a single quote and the
        next interpolation was refused as 'inside single quotes'."""
        template = "python3 - <<'PYEOF'\nprint(\"don't\")\nPYEOF\necho {{ after }}\n"
        agent = ScriptAgent(config={"name": "e", "script_template": template})
        result = agent.run({"after": "ok"}, _real_context(tmp_path))
        assert result.status.value == "completed", result.error
        assert result.output == "don't\nok\n"

    def test_a_here_string_is_not_a_heredoc(self):
        """`<<<` is a word (bash here-string), not a heredoc: the scanner must not wait for a
        delimiter line that never comes and swallow the rest of the script. Checked on the
        rendered text because scripts run under /bin/sh, which has no here-strings."""
        from temper_ai.agent.script_agent import _rewrite_interpolations

        rewritten = _rewrite_interpolations("cat <<< {{ a }}\necho {{ b }}\n", "e")
        assert rewritten.count("_temper_env_quoted") == 2, rewritten

    def test_the_env_filter_works_inside_single_quotes_too(self, tmp_path):
        template = "python3 -c 'import os; print(os.environ[\"{{ a | env }}\"])'\n"
        agent = ScriptAgent(config={"name": "e", "script_template": template})
        result = agent.run({"a": "it's $(touch pwned)"}, _real_context(tmp_path))
        assert result.status.value == "completed", result.error
        assert result.output.strip() == "it's $(touch pwned)"
        assert not (tmp_path / "pwned").exists()

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

    def test_the_file_filter_delivers_single_and_three_photo_megabyte_payloads_intact(self, tmp_path):
        """Combined happy path: a real-size ~1.3 MB single-photo payload and a ~4 MB 3-photo
        payload travel through `| file` into the script byte-equal, in 0600 files inside the
        workspace, with single-quoted shell-safe paths and nothing in env or command text."""
        import hashlib
        import json
        import pathlib
        import stat

        ws = tmp_path / "inkflow run's workspace"
        ws.mkdir()

        photo_1 = "data:image/jpeg;base64," + ("A1b2" * 337_500)  # 1,350,023 B (> 1.3 MB real photo)
        photo_2 = "data:image/png;base64," + ("C3d4" * 337_500)   # 1,350,022 B
        photo_3 = "data:image/webp;base64," + ("E5f6" * 340_000)  # 1,360,023 B

        single_req = json.dumps({
            "conversation": [{"id": "m-1", "sender": "client", "text": "Here is my photo $(touch pwned) 'quote'"}],
            "referencePhotos": [{"mediaId": "ig-1", "messageId": "m-1", "mimeType": "image/jpeg", "dataUrl": photo_1}],
        })
        three_req = json.dumps({
            "conversation": [{"id": "m-3", "sender": "client", "text": "Three reference photos attached"}],
            "referencePhotos": [
                {"mediaId": "ig-1", "messageId": "m-3", "mimeType": "image/jpeg", "dataUrl": photo_1},
                {"mediaId": "ig-2", "messageId": "m-3", "mimeType": "image/png", "dataUrl": photo_2},
                {"mediaId": "ig-3", "messageId": "m-3", "mimeType": "image/webp", "dataUrl": photo_3},
            ],
        })
        single_bytes = len(single_req.encode("utf-8"))
        three_bytes = len(three_req.encode("utf-8"))
        assert single_bytes >= 1_350_000
        assert three_bytes >= 4_000_000

        template = (
            "python3 - {{ single_req | default('') | file }} <<'PYEOF'\n"
            "import hashlib, json, pathlib, stat, sys\n"
            "p1 = pathlib.Path(sys.argv[1])\n"
            "p2 = pathlib.Path({{ three_req | default('') | file }})\n"
            "p3 = pathlib.Path(\"{{ single_req | file }}\")\n"
            "b1 = p1.read_bytes()\n"
            "b2 = p2.read_bytes()\n"
            "b3 = p3.read_bytes()\n"
            "d1 = json.loads(b1.decode('utf-8'))\n"
            "d2 = json.loads(b2.decode('utf-8'))\n"
            "print(json.dumps({\n"
            "    'paths': [str(p1), str(p2), str(p3)],\n"
            "    'modes': [stat.S_IMODE(p1.stat().st_mode), stat.S_IMODE(p2.stat().st_mode), stat.S_IMODE(p3.stat().st_mode)],\n"
            "    'sizes': [len(b1), len(b2), len(b3)],\n"
            "    'sha256': [hashlib.sha256(b1).hexdigest(), hashlib.sha256(b2).hexdigest(), hashlib.sha256(b3).hexdigest()],\n"
            "    'photo_counts': [len(d1['referencePhotos']), len(d2['referencePhotos'])],\n"
            "    'photo1_len': len(d1['referencePhotos'][0]['dataUrl']),\n"
            "}))\n"
            "PYEOF\n"
        )
        agent = ScriptAgent(config={"name": "inkflow_reply_prepare", "script_template": template})
        result = agent.run({"single_req": single_req, "three_req": three_req}, _real_context(ws))
        status_val = result.status.value
        assert status_val == "completed"
        assert not (ws / "pwned").exists()

        out = result.structured_output
        assert out is not None
        expected_1_sha = hashlib.sha256(single_req.encode("utf-8")).hexdigest()
        expected_2_sha = hashlib.sha256(three_req.encode("utf-8")).hexdigest()
        assert out["sizes"] == [single_bytes, three_bytes, single_bytes]
        assert out["sha256"] == [expected_1_sha, expected_2_sha, expected_1_sha]
        assert out["modes"] == [0o600, 0o600, 0o600]
        assert out["photo_counts"] == [1, 3]
        photo1_len = len(photo_1)
        assert out["photo1_len"] == photo1_len
        for staged in out["paths"]:
            p = pathlib.Path(staged)
            assert p.parent == ws
            assert stat.S_IMODE(p.stat().st_mode) == 0o600

        # Check rendered command quotes the path and keeps payload out of command and env
        mock_ctx = _make_context(ToolResult(success=True, result="{}"))
        mock_ctx.workspace_path = str(ws)
        agent.run({"single_req": single_req, "three_req": three_req}, mock_ctx)
        params = mock_ctx.tool_executor.execute.call_args[0][1]
        cmd = params["command"]
        has_escaped_quote = "'\"'\"'" in cmd
        assert has_escaped_quote  # apostrophe in workspace path is single-quote escaped
        prefix = photo_1[:64]
        in_cmd = prefix in cmd
        assert not in_cmd
        in_env = any(prefix in str(env_val) for env_val in params["env"].values())
        assert not in_env

    def test_non_string_values_serialize_as_json_for_both_file_and_env(self, tmp_path):
        """Non-string values (dict, list, bool, int) serialize as JSON for both `| file` and `| env`,
        while strings pass through as-is and None becomes empty text."""
        template = (
            "python3 - <<'PYEOF'\n"
            "import json, os, pathlib\n"
            "obj_file = json.loads(pathlib.Path({{ obj | file }}).read_text(encoding='utf-8'))\n"
            "arr_file = json.loads(pathlib.Path({{ arr | file }}).read_text(encoding='utf-8'))\n"
            "obj_env = json.loads(os.environ['{{ obj | env }}'])\n"
            "arr_env = json.loads(os.environ['{{ arr | env }}'])\n"
            "raw_str = pathlib.Path({{ text | file }}).read_text(encoding='utf-8')\n"
            "none_str = pathlib.Path({{ empty | file }}).read_text(encoding='utf-8')\n"
            "print(json.dumps({\n"
            "    'obj_match': obj_file == obj_env == {'a': 1, 'ok': True},\n"
            "    'arr_match': arr_file == arr_env == ['x', 2, False],\n"
            "    'raw_str': raw_str,\n"
            "    'none_str': none_str,\n"
            "}))\n"
            "PYEOF\n"
        )
        agent = ScriptAgent(config={"name": "serializer", "script_template": template})
        result = agent.run(
            {
                "obj": {"a": 1, "ok": True},
                "arr": ["x", 2, False],
                "text": "plain string",
                "empty": None,
            },
            _real_context(tmp_path),
        )
        assert result.status.value == "completed", result.error
        assert result.structured_output == {
            "obj_match": True,
            "arr_match": True,
            "raw_str": "plain string",
            "none_str": "",
        }

    def test_file_filter_without_workspace_uses_private_temp_dir_and_cleans_up(self):
        """When a run has no workspace_path, `| file` stages into a private 0700 temp directory
        for the attempt and removes it once the attempt finishes (including on render failure)."""
        import pathlib
        import tempfile
        from unittest.mock import patch

        from temper_ai.agent.script_agent import ENV_MAX_BYTES
        from temper_ai.tools.bash import Bash
        from temper_ai.tools.executor import ToolExecutor

        executor = ToolExecutor(workspace_root=None)
        executor.register_tools({"Bash": Bash()})
        ctx = MagicMock()
        ctx.run_id = "run-no-ws"
        ctx.node_path = "prepare"
        ctx.agent_name = "no_ws_agent"
        ctx.workspace_path = None
        ctx.skip_policies = None
        ctx.parent_event_id = None
        ctx.tool_executor = executor

        template = (
            "python3 - <<'PYEOF'\n"
            "import json, pathlib, stat\n"
            "p = pathlib.Path({{ payload | file }})\n"
            "print(json.dumps({\n"
            "    'file': str(p),\n"
            "    'dir': str(p.parent),\n"
            "    'file_mode': stat.S_IMODE(p.stat().st_mode),\n"
            "    'dir_mode': stat.S_IMODE(p.parent.stat().st_mode),\n"
            "    'text': p.read_text(encoding='utf-8'),\n"
            "}))\n"
            "PYEOF\n"
        )
        agent = ScriptAgent(config={"name": "no_ws_agent", "script_template": template})
        result = agent.run({"payload": "no-workspace-secret-payload"}, ctx)
        assert result.status.value == "completed", result.error
        out = result.structured_output
        assert out is not None
        assert out["file_mode"] == 0o600
        assert out["dir_mode"] == 0o700
        assert out["text"] == "no-workspace-secret-payload"
        assert not pathlib.Path(out["file"]).exists()
        assert not pathlib.Path(out["dir"]).exists()

        # Also verify fallback temp dir is cleaned up if rendering fails later in the same template
        created_dirs: list[pathlib.Path] = []
        orig_mkdtemp = tempfile.mkdtemp

        def tracking_mkdtemp(*args, **kwargs):
            d = orig_mkdtemp(*args, **kwargs)
            created_dirs.append(pathlib.Path(d))
            return d

        fail_agent = ScriptAgent(
            config={
                "name": "no_ws_fail",
                "script_template": "cat {{ first | file }} && echo {{ huge | env }}",
            }
        )
        with patch("temper_ai.agent.script_agent.tempfile.mkdtemp", side_effect=tracking_mkdtemp):
            fail_res = fail_agent.run(
                {"first": "staged-first", "huge": "X" * (ENV_MAX_BYTES + 10)},
                ctx,
            )
        fail_status = fail_res.status.value
        fail_err = fail_res.error or ""
        has_huge = "huge" in fail_err
        has_huge_fix = "{{ huge | file }}" in fail_err
        assert fail_status == "failed"
        assert has_huge
        assert has_huge_fix
        assert len(created_dirs) == 1
        assert not created_dirs[0].exists()

    def test_env_filter_over_limit_fails_loud_before_exec(self, tmp_path):
        """`| env` (and any environment-stashed interpolation) over 131072 UTF-8 bytes raises
        ScriptRenderError naming the agent, the input, and the `| file` fix before Bash starts."""
        from temper_ai.agent.exceptions import ScriptRenderError
        from temper_ai.agent.script_agent import ENV_MAX_BYTES, _ValueStash

        # Boundary: exact 131,072-byte value is allowed
        exact_limit = "A" * ENV_MAX_BYTES
        stash_ok = _ValueStash(
            agent_name="inkflow_reply_prepare",
            inputs={"request_json": exact_limit},
            expressions=["request_json | default('') | env"],
        )
        assert stash_ok.name(exact_limit) == "TEMPER_V1"

        # 1 byte over limit (131,073 B) raises ScriptRenderError directly
        over_by_one = "B" * (ENV_MAX_BYTES + 1)
        stash_over = _ValueStash(
            agent_name="inkflow_reply_prepare",
            inputs={"request_json": over_by_one},
            expressions=["request_json | default('') | env"],
        )
        with pytest.raises(ScriptRenderError) as exc_info:
            stash_over.name(over_by_one)
        err_msg = str(exc_info.value)
        assert "inkflow_reply_prepare" in err_msg
        assert "request_json" in err_msg
        assert "131073 bytes" in err_msg
        assert "131072-byte limit" in err_msg
        assert "{{ request_json | default('') | file }}" in err_msg

        # Real-size photo request (~1.25 MB) through ScriptAgent.run fails before subprocess starts
        canary = "CANARY_SECRET_DATAURL_PAYLOAD_DO_NOT_LEAK"
        real_size_photo = canary + ("P" * 1_250_944)
        ctx = _make_context(ToolResult(success=True, result="should-not-run"))
        ctx.workspace_path = str(tmp_path)
        agent = ScriptAgent(
            config={
                "name": "inkflow_reply_prepare",
                "script_template": (
                    "python3 - <<'PYEOF'\n"
                    "import os\n"
                    "req = os.environ.get(\"{{ request_json | default('') | env }}\", \"\")\n"
                    "PYEOF\n"
                ),
            }
        )
        result = agent.run({"request_json": real_size_photo}, ctx)
        status_val = result.status.value
        exec_called = ctx.tool_executor.execute.called
        err_text = result.error or ""
        has_agent = "inkflow_reply_prepare" in err_text
        has_key = "request_json" in err_text
        has_fix = "{{ request_json | default('') | file }}" in err_text
        has_canary = canary in err_text
        assert status_val == "failed"
        assert not exec_called
        assert has_agent
        assert has_key
        assert has_fix
        assert not has_canary


def test_a_long_json_output_reaches_the_next_node_whole(tmp_path):
    """The EPD plan stage's hand-off prints about 130,000 characters of JSON on one line. Through the
    real Bash tool it was compacted to 40,050 for a model's context, never parsed, and the lead ran
    without any of it (2026-09-25)."""
    agent = ScriptAgent(config={"name": "handoff", "script_template":
                                "python3 -c 'import json; print(json.dumps({\"design\": \"x\" * 150000, \"round\": 1}))'"})
    result = agent.run({}, _real_context(tmp_path))
    assert result.structured_output == {"design": "x" * 150_000, "round": 1}
