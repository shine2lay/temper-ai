"""Tests for O-278-1: refuse ``| file`` inputs in P3-protected script launches."""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from temper_ai.agent.script_agent import ScriptAgent, ScriptRenderError, _ValueStash
from temper_ai.observability import EventType
from temper_ai.p3_authority.contract import AcceptedData, Result
from temper_ai.p3_authority.launch_adapters import (
    BashChildLaunchAdapter,
    ScriptLaunchObservationAdapter,
)
from temper_ai.p3_authority.worker_observation import WorkerObservationAdapter
from temper_ai.shared.types import ExecutionContext, Status
from temper_ai.tools.base import ToolResult
from temper_ai.tools.bash import Bash
from temper_ai.tools.executor import ToolExecutor
from tests.test_p3_authority.test_child_registration import (
    SyntheticWorkerProviderDouble,
    make_child_pair,
    make_evidence,
    make_grant,
    make_host_and_worker_processes,
    make_selected_job,
    make_selected_op,
    make_supplied_worker_frame,
)

CANARY_SECRET = "CANARY_O278_1_SECRET_VALUE_9D4F"
RUN_ID = "00000000-0000-4000-8000-000000000280"


@dataclass
class _DeclaredP3Context(ExecutionContext):
    """ExecutionContext subclass with declared P3 launch attributes."""

    p3_protected_launch: bool = False
    p3_launch_adapter: ScriptLaunchObservationAdapter | None = None


def _make_p3_script_adapter(
    workspace: Path,
    *,
    agent_name: str = "checker-script",
    run_id: str = RUN_ID,
) -> tuple[ScriptLaunchObservationAdapter, BashChildLaunchAdapter]:
    job = make_selected_job(execution_uuid=run_id)
    grant = make_grant(job)
    _, _, worker_proc, worker_closure = make_host_and_worker_processes()
    frame = make_supplied_worker_frame()
    provider = SyntheticWorkerProviderDouble(frame=frame)
    observer = WorkerObservationAdapter(provider=provider)
    obs_res = observer.observe(grant, job, "C_PRE_REQUEST")
    assert isinstance(obs_res, AcceptedData)

    def resolve_child(os_pid: int) -> Result[tuple[Any, Any]]:
        pair = make_child_pair(
            worker_proc,
            worker_closure,
            os_pid=os_pid,
            instance_id=f"child-{os_pid}",
            exec_epoch=1,
            birth_ref=f"birth:{os_pid}",
        )
        ev = make_evidence("C_BEFORE_COUNT", job)
        return AcceptedData(data=pair, evidence=ev)

    bash_adapter = BashChildLaunchAdapter(
        worker_observer=observer,
        grant=grant,
        selected_job=job,
        parent_instance=worker_proc,
        intended_effect=make_selected_op(),
        child_identity_resolver=resolve_child,
    )
    script_adapter = ScriptLaunchObservationAdapter(
        bash_adapter=bash_adapter,
        selected_job=job,
        expected_agent_name=agent_name,
        cwd=str(workspace),
    )
    return script_adapter, bash_adapter


def _make_recording_executor(workspace: Path) -> tuple[ToolExecutor, list[dict[str, Any]]]:
    real_bash = Bash(config={"workspace_root": str(workspace)})
    calls: list[dict[str, Any]] = []

    class _RecordingBash(Bash):
        def execute(self, **kwargs: Any) -> ToolResult:
            calls.append(dict(kwargs))
            return real_bash.execute(**kwargs)

    executor = ToolExecutor(workspace_root=str(workspace))
    executor.register_tools(
        {"Bash": _RecordingBash(config={"workspace_root": str(workspace)})}
    )
    return executor, calls


def _make_exec_context(
    *,
    agent_name: str,
    executor: Any,
    workspace_path: str | None,
    event_recorder: Any = None,
) -> ExecutionContext:
    recorder = event_recorder if event_recorder is not None else MagicMock()
    return ExecutionContext(
        run_id=RUN_ID,
        workflow_name="p3-wf",
        node_path="check",
        agent_name=agent_name,
        event_recorder=recorder,
        tool_executor=executor,
        workspace_path=workspace_path,
    )


def _assert_refused_error(
    error_text: str | None,
    *,
    agent_name: str,
    expr: str,
    secret_value: str = CANARY_SECRET,
) -> None:
    assert error_text is not None
    assert agent_name in error_text
    assert expr in error_text
    assert f"{{{{ {expr} | file }}}}" in error_text
    assert "use | env or | quoted" in error_text
    assert secret_value not in error_text


def test_protected_launch_refuses_file_filter_and_unprotected_launch_runs(
    tmp_path: Path,
) -> None:
    """Combined whole-feature check (bp-be8d76b9):
    1. A P3-protected ScriptAgent launch using ``{{ x | file }}`` fails before execution
       with ``ScriptRenderError`` / ``AGENT_FAILED``, never calls Bash or the P3 adapter,
       writes zero ``.temper_v*`` files in the workspace, and never leaks the input value.
    2. The exact same template in an unprotected launch runs and reads the staged 0600 file.
    """
    protected_ws = tmp_path / "protected_ws"
    protected_ws.mkdir()
    unprotected_ws = tmp_path / "unprotected_ws"
    unprotected_ws.mkdir()

    template = (
        "python3 - {{ x | file }} <<'PYEOF'\n"
        "import json, os, stat, sys\n"
        "p = sys.argv[1]\n"
        "mode = oct(stat.S_IMODE(os.stat(p).st_mode))[2:]\n"
        "with open(p, encoding='utf-8') as fh:\n"
        "    print(json.dumps({'read_back': fh.read(), 'mode': mode}))\n"
        "PYEOF"
    )

    script_adapter, bash_adapter = _make_p3_script_adapter(
        protected_ws, agent_name="checker-script"
    )
    protected_executor, protected_bash_calls = _make_recording_executor(protected_ws)
    recorder = MagicMock()

    protected_ctx = _make_exec_context(
        agent_name="checker-script",
        executor=protected_executor,
        workspace_path=str(protected_ws),
        event_recorder=recorder,
    )
    protected_agent = ScriptAgent(
        {
            "name": "checker-script",
            "script_template": template,
            "p3_launch_adapter": script_adapter,
            "p3_protected_launch": True,
        }
    )

    stash = _ValueStash(
        agent_name="checker-script",
        workspace_path=str(protected_ws),
        inputs={"x": CANARY_SECRET},
        file_expressions=["x"],
    )
    with pytest.raises(ScriptRenderError) as render_exc:
        stash.refuse_file(CANARY_SECRET)
    _assert_refused_error(str(render_exc.value), agent_name="checker-script", expr="x")

    res = protected_agent.run({"x": CANARY_SECRET}, protected_ctx)
    assert res.status == Status.FAILED
    _assert_refused_error(res.error, agent_name="checker-script", expr="x")
    assert protected_bash_calls == []
    assert script_adapter.bindings == ()
    assert bash_adapter.pre_spawn_checks == 0
    assert bash_adapter.spawn_registrations == 0
    assert list(protected_ws.glob(".temper_v*")) == []

    failed_calls = [
        call
        for call in recorder.record.call_args_list
        if call.args and call.args[0] == EventType.AGENT_FAILED
    ]
    assert len(failed_calls) == 1
    failed_data = failed_calls[0].kwargs["data"]
    assert failed_data["error_type"] == "ScriptRenderError"
    _assert_refused_error(
        failed_data.get("error"),
        agent_name="checker-script",
        expr="x",
    )
    assert CANARY_SECRET not in json.dumps(failed_data, default=str)

    # Same template unprotected -> runs and reads the 0600 file.
    unprotected_executor, unprotected_bash_calls = _make_recording_executor(unprotected_ws)
    unprotected_ctx = _make_exec_context(
        agent_name="checker-script",
        executor=unprotected_executor,
        workspace_path=str(unprotected_ws),
    )
    unprotected_agent = ScriptAgent(
        {
            "name": "checker-script",
            "script_template": template,
        }
    )
    res_ok = unprotected_agent.run({"x": CANARY_SECRET}, unprotected_ctx)
    assert res_ok.status == Status.COMPLETED
    assert len(unprotected_bash_calls) == 1
    assert res_ok.structured_output == {"read_back": CANARY_SECRET, "mode": "600"}
    assert len(list(unprotected_ws.glob(".temper_v*"))) == 1


@pytest.mark.parametrize(
    ("template", "expected_expr"),
    [
        ('cat "{{ payload | file }}"', "payload"),
        ("cat '{{ payload | file }}'", "payload"),
        ("{% set p = payload | file %}\ncat \"$p\"", "payload"),
        ("cat {{ payload | default('') | file }}", "payload | default('')"),
        ("cat {{ payload | _temper_file_bare }}", "payload"),
    ],
    ids=[
        "double_quoted",
        "single_quoted",
        "jinja_set_stmt",
        "chained_default_filter",
        "direct_bare_filter",
    ],
)
def test_protected_launch_refuses_all_file_filter_syntactic_forms(
    tmp_path: Path,
    template: str,
    expected_expr: str,
) -> None:
    """Quoted ``"{{ x | file }}"``, ``'{{ x | file }}'``, ``{% set p = x | file %}``,
    chained filters, and direct ``_temper_file_bare`` all fail before any file write or Bash call.
    """
    script_adapter, bash_adapter = _make_p3_script_adapter(
        tmp_path, agent_name="syntax-agent"
    )
    executor, bash_calls = _make_recording_executor(tmp_path)
    ctx = _make_exec_context(
        agent_name="syntax-agent",
        executor=executor,
        workspace_path=str(tmp_path),
    )
    agent = ScriptAgent(
        {
            "name": "syntax-agent",
            "script_template": template,
            "p3_launch_adapter": script_adapter,
            "p3_protected_launch": True,
        }
    )

    res = agent.run({"payload": CANARY_SECRET}, ctx)
    assert res.status == Status.FAILED
    _assert_refused_error(res.error, agent_name="syntax-agent", expr=expected_expr)
    assert bash_calls == []
    assert script_adapter.bindings == ()
    assert bash_adapter.pre_spawn_checks == 0
    assert list(tmp_path.glob(".temper_v*")) == []


@pytest.mark.parametrize(
    "source_mode",
    [
        "config_flag_only",
        "config_adapter_only",
        "context_flag_only",
        "context_adapter_only",
    ],
)
def test_protection_detected_from_context_declared_attribute_or_config(
    tmp_path: Path,
    source_mode: str,
) -> None:
    """Protection from ``context`` declared attributes or ``config`` (either flag or
    ``p3_launch_adapter`` alone) refuses ``{{ x | file }}`` before any file write or Bash call.
    """
    script_adapter, bash_adapter = _make_p3_script_adapter(
        tmp_path, agent_name="source-agent"
    )
    executor, bash_calls = _make_recording_executor(tmp_path)

    config: dict[str, Any] = {
        "name": "source-agent",
        "script_template": "cat {{ doc | file }}",
    }
    if source_mode == "config_flag_only":
        config["p3_protected_launch"] = True
        ctx: ExecutionContext = _make_exec_context(
            agent_name="source-agent",
            executor=executor,
            workspace_path=str(tmp_path),
        )
    elif source_mode == "config_adapter_only":
        config["p3_launch_adapter"] = script_adapter
        ctx = _make_exec_context(
            agent_name="source-agent",
            executor=executor,
            workspace_path=str(tmp_path),
        )
    elif source_mode == "context_flag_only":
        ctx = _DeclaredP3Context(
            run_id=RUN_ID,
            workflow_name="p3-wf",
            node_path="check",
            agent_name="source-agent",
            event_recorder=MagicMock(),
            tool_executor=executor,
            workspace_path=str(tmp_path),
            p3_protected_launch=True,
        )
    else:
        ctx = _DeclaredP3Context(
            run_id=RUN_ID,
            workflow_name="p3-wf",
            node_path="check",
            agent_name="source-agent",
            event_recorder=MagicMock(),
            tool_executor=executor,
            workspace_path=str(tmp_path),
            p3_launch_adapter=script_adapter,
        )

    agent = ScriptAgent(config)
    res = agent.run({"doc": CANARY_SECRET}, ctx)
    assert res.status == Status.FAILED
    _assert_refused_error(res.error, agent_name="source-agent", expr="doc")
    assert bash_calls == []
    assert script_adapter.bindings == ()
    assert bash_adapter.pre_spawn_checks == 0
    assert list(tmp_path.glob(".temper_v*")) == []


def test_protected_launch_without_workspace_never_creates_fallback_temp_dir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``workspace_path`` is unset, a P3-protected launch refuses ``{{ x | file }}``
    before ``tempfile.mkdtemp`` is ever called for the no-workspace fallback directory.
    """
    mkdtemp_calls: list[Any] = []
    real_mkdtemp = tempfile.mkdtemp

    def _spy_mkdtemp(*args: Any, **kwargs: Any) -> str:
        mkdtemp_calls.append((args, kwargs))
        return real_mkdtemp(*args, **kwargs)

    monkeypatch.setattr(tempfile, "mkdtemp", _spy_mkdtemp)

    executor = MagicMock()
    executor.execute = MagicMock()
    ctx = _make_exec_context(
        agent_name="no-ws-agent",
        executor=executor,
        workspace_path=None,
    )
    agent = ScriptAgent(
        {
            "name": "no-ws-agent",
            "script_template": "cat {{ blob | file }}",
            "p3_protected_launch": True,
        }
    )

    res = agent.run({"blob": CANARY_SECRET}, ctx)
    assert res.status == Status.FAILED
    _assert_refused_error(res.error, agent_name="no-ws-agent", expr="blob")
    assert mkdtemp_calls == []
    executor.execute.assert_not_called()


def test_validate_config_reports_file_filter_in_protected_config(
    tmp_path: Path,
) -> None:
    """``validate_config`` fails early when the config declares ``p3_protected_launch``
    or ``p3_launch_adapter`` and ``script_template`` uses ``| file`` in any form, while
    allowing unprotected ``| file`` and protected ``| env`` / ``| quoted``.
    """
    script_adapter, _ = _make_p3_script_adapter(tmp_path, agent_name="cfg-agent")

    for template in (
        "cat {{ secret_in | file }}",
        'cat "{{ secret_in | file }}"',
        "{% set p = secret_in | file %}\ncat \"$p\"",
    ):
        err_flag = ScriptAgent(
            {
                "name": "cfg-agent",
                "script_template": template,
                "p3_protected_launch": True,
            }
        ).validate_config()
        assert len(err_flag) == 1
        _assert_refused_error(err_flag[0], agent_name="cfg-agent", expr="secret_in")

        err_adapter = ScriptAgent(
            {
                "name": "cfg-agent",
                "script_template": template,
                "p3_launch_adapter": script_adapter,
            }
        ).validate_config()
        assert len(err_adapter) == 1
        _assert_refused_error(err_adapter[0], agent_name="cfg-agent", expr="secret_in")

    # Unprotected config with | file is valid.
    assert (
        ScriptAgent(
            {
                "name": "cfg-agent",
                "script_template": "cat {{ secret_in | file }}",
            }
        ).validate_config()
        == []
    )

    # Protected config with | env, | quoted, plain {{ x }}, or literal/comment "| file" is valid.
    for safe_template in (
        'python3 -c \'import os; print(os.environ["{{ secret_in | env }}"])\'',
        "echo {{ secret_in | quoted }}",
        "echo {{ secret_in }}",
        '{# {{ secret_in | file }} #}\necho {{ "literal | file" }}',
    ):
        assert (
            ScriptAgent(
                {
                    "name": "cfg-agent",
                    "script_template": safe_template,
                    "p3_protected_launch": True,
                }
            ).validate_config()
            == []
        )


@pytest.mark.parametrize(
    "template",
    [
        'python3 -c \'import json, os; print(json.dumps({"v": os.environ["{{ msg | env }}"]}))\'',
        'python3 - {{ msg | quoted }} <<\'PYEOF\'\nimport json, sys\nprint(json.dumps({"v": sys.argv[1]}))\nPYEOF',
        'python3 - "{{ msg | quoted }}" <<\'PYEOF\'\nimport json, sys\nprint(json.dumps({"v": sys.argv[1]}))\nPYEOF',
    ],
    ids=["env_filter", "quoted_filter_unquoted", "quoted_filter_in_double_quotes"],
)
def test_env_and_quoted_filters_in_protected_mode_reach_p3_adapter_unchanged(
    tmp_path: Path,
    template: str,
) -> None:
    """``| env`` and ``| quoted`` in a P3-protected launch still flow through
    ``ScriptLaunchObservationAdapter`` and ``BashChildLaunchAdapter`` unchanged.
    """
    script_adapter, bash_adapter = _make_p3_script_adapter(
        tmp_path, agent_name="checker-script"
    )
    executor, bash_calls = _make_recording_executor(tmp_path)
    ctx = _make_exec_context(
        agent_name="checker-script",
        executor=executor,
        workspace_path=str(tmp_path),
    )
    agent = ScriptAgent(
        {
            "name": "checker-script",
            "script_template": template,
            "p3_launch_adapter": script_adapter,
            "p3_protected_launch": True,
        }
    )

    payload = "safe env value $(not_executed)"
    res = agent.run({"msg": payload}, ctx)
    assert res.status == Status.COMPLETED
    assert res.structured_output == {"v": payload}
    assert len(bash_calls) == 1
    assert len(script_adapter.bindings) == 1
    assert bash_adapter.pre_spawn_checks >= 1
    assert bash_adapter.spawn_registrations == 1
    assert len(bash_adapter.registrations) == 1
    assert len(bash_adapter.terminations) == 1
    assert bash_adapter.terminations[0].returncode == 0
    assert list(tmp_path.glob(".temper_v*")) == []


def test_bite_dropping_refusing_filters_fails_combined_test(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bite 1: if ``register_filters`` fails to register the refusing filter in
    protected mode (falling back to ``stash.file`` / ``stash.file_bare``), the
    combined test fails because a ``.temper_v*`` file is written into the workspace.
    """
    orig_register = _ValueStash.register_filters

    def _unprotected_register(
        self: _ValueStash, env: Any, *, p3_protected: bool = False
    ) -> None:
        orig_register(self, env, p3_protected=False)

    monkeypatch.setattr(_ValueStash, "register_filters", _unprotected_register)

    with pytest.raises(AssertionError):
        test_protected_launch_refuses_file_filter_and_unprotected_launch_runs(tmp_path)


def test_bite_bypassing_filters_is_caught_by_stash_files_defence_in_depth(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bite 2: if a caller or filter bypasses ``refuse_file`` during rendering so
    ``stash.files`` becomes non-empty, the defence-in-depth ``if stash.files:`` guard
    in the P3 launch block still refuses with ``ScriptRenderError`` before
    ``ScriptLaunchObservationAdapter.prepare_bash_kwargs`` or ``Bash`` is called.
    """
    script_adapter, bash_adapter = _make_p3_script_adapter(
        tmp_path, agent_name="checker-script"
    )
    executor, bash_calls = _make_recording_executor(tmp_path)
    ctx = _make_exec_context(
        agent_name="checker-script",
        executor=executor,
        workspace_path=str(tmp_path),
    )

    def _bypass_refuse_file(self: _ValueStash, _value: Any) -> str:
        # Simulate a filter bypass that populates stash.files without raising in render.
        self.files.append(str(tmp_path / ".temper_v1_simulated"))
        return "'/simulated/path'"

    monkeypatch.setattr(_ValueStash, "refuse_file", _bypass_refuse_file)

    agent = ScriptAgent(
        {
            "name": "checker-script",
            "script_template": "echo {{ x | file }}",
            "p3_launch_adapter": script_adapter,
            "p3_protected_launch": True,
        }
    )
    res = agent.run({"x": CANARY_SECRET}, ctx)
    assert res.status == Status.FAILED
    _assert_refused_error(res.error, agent_name="checker-script", expr="x")
    assert bash_calls == []
    assert script_adapter.bindings == ()
    assert bash_adapter.pre_spawn_checks == 0
    assert bash_adapter.spawn_registrations == 0

    # Control: if stash.files is also empty (dropping the stash.files guard),
    # execution reaches ScriptLaunchObservationAdapter and Bash.
    def _bypass_both(self: _ValueStash, _value: Any) -> str:
        return "'/simulated/path'"

    monkeypatch.setattr(_ValueStash, "refuse_file", _bypass_both)
    res_unblocked = agent.run({"x": CANARY_SECRET}, ctx)
    assert res_unblocked.status == Status.COMPLETED
    assert len(script_adapter.bindings) == 1
    assert len(bash_calls) == 1
