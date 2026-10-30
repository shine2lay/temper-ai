"""Known answers for the entry to wt's pool, without implementing or testing another pool."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests import conftest, machine_slot

ROOT = Path(__file__).resolve().parents[1]
MARKER = "TEMPER_PYTEST_MACHINE_SLOT"
SKIP_VARS = ("PYTEST_XDIST_WORKER", "PYTEST_CURRENT_TEST", "CI", "GITHUB_ACTIONS", MARKER)


class Restart(Exception):
    """exec does not return; this stand-in must not be swallowed."""


@pytest.fixture
def restart(monkeypatch):
    # pytest sets PYTEST_CURRENT_TEST again at the call phase. Isolate the
    # module's environment, rather than briefly clearing pytest's real one.
    environ = {}
    monkeypatch.setattr(machine_slot.shutil, "which", lambda name: "/fake/wt" if name == "wt" else None)
    attempts = []

    def execute(program, argv):
        attempts.append((program, argv, environ.get(MARKER), environ.get("PYTEST_XDIST_AUTO_NUM_WORKERS")))
        raise Restart

    monkeypatch.setattr(machine_slot, "os", SimpleNamespace(environ=environ, execvp=execute))
    return attempts


@pytest.mark.parametrize("args", [
    ["-n", "auto"], ["-n", "4"], ["--numprocesses=logical"], ["-n8"], ["--numprocesses", "1"],
], ids=["auto", "four", "logical", "eight", "one"])
def test_parallel_requests_wrap(pytestconfig, restart, args):
    workers = pytestconfig._parser.parse(args).numprocesses
    with pytest.raises(Restart):
        machine_slot.enter_machine_slot(workers)
    assert len(restart) == 1


@pytest.mark.parametrize("args", [[], ["-n", "0"], ["--numprocesses=0"]], ids=["none", "zero", "long-zero"])
def test_single_process_requests_do_not_wrap(pytestconfig, restart, args):
    machine_slot.enter_machine_slot(pytestconfig._parser.parse(args).numprocesses)
    assert restart == []
    assert MARKER not in machine_slot.os.environ


@pytest.mark.parametrize("name", SKIP_VARS)
@pytest.mark.parametrize("value", ["1", ""], ids=["set", "empty"])
def test_skip_environment_is_not_wrapped(restart, name, value):
    machine_slot.os.environ[name] = value
    machine_slot.enter_machine_slot("auto")
    assert restart == []
    assert machine_slot.os.environ[name] == value


def test_no_wt_runs_unwrapped(monkeypatch, restart):
    monkeypatch.setattr(machine_slot.shutil, "which", lambda _: None)
    machine_slot.enter_machine_slot(4)
    assert restart == []
    assert MARKER not in machine_slot.os.environ


@pytest.mark.parametrize("original", [
    ["/original/python", "-m", "pytest", "tests/a file.py", "-n", "8"],
    ["/original/python", "-X", "dev", "/venv/bin/pytest", "--numprocesses=logical"],
], ids=["module", "script"])
def test_exact_restart_keeps_interpreter_arguments_and_explicit_workers(monkeypatch, restart, original):
    monkeypatch.setattr(machine_slot.sys, "orig_argv", original)
    monkeypatch.setattr(machine_slot.sys, "executable", "/actual/venv/python")
    machine_slot.os.environ["PYTEST_XDIST_AUTO_NUM_WORKERS"] = "2"
    with pytest.raises(Restart):
        machine_slot.enter_machine_slot(8)
    assert restart == [("wt", ["wt", "slot", "--", "/actual/venv/python", *original[1:]], "1", "2")]


def test_failed_restart_runs_unwrapped_and_says_why_once(monkeypatch, restart, capsys):
    def gone(program, argv):
        assert machine_slot.os.environ[MARKER] == "1"
        raise OSError("wt disappeared\nbetween lookup and exec")

    monkeypatch.setattr(machine_slot.os, "execvp", gone)
    assert machine_slot.enter_machine_slot("auto") is None
    assert MARKER not in machine_slot.os.environ
    out = capsys.readouterr()
    assert out.out == ""
    assert out.err == (
        "temper pytest: couldn't restart under wt slot (wt disappeared between lookup and exec); running unwrapped\n"
    )


def test_conftest_calls_entry_early(monkeypatch):
    calls = []
    monkeypatch.setattr(conftest, "enter_machine_slot", calls.append)

    class Config:
        def getoption(self, name, default):
            assert name == "numprocesses"
            assert default is None
            return 4

    conftest.pytest_configure(Config())
    assert calls == [4]
    assert conftest.pytest_configure.pytest_impl["tryfirst"] is True


@pytest.mark.parametrize(("override", "caller", "expected"), [
    (None, None, None), ("4", None, "4"), (None, "2", "2"), ("4", "2", "4"),
], ids=["default", "override", "caller", "override-wins"])
def test_hook_runs_auto_and_only_sets_workers_when_requested(tmp_path, override, caller, expected):
    tools = tmp_path / "bin"
    tools.mkdir()
    record = tmp_path / "uv.jsonl"
    scripts = {
        "git": "import os, sys\nif sys.argv[1:] == ['rev-parse', '--show-toplevel']: print(os.getcwd())\n",
        "uv": (
            "import json, os, sys\n"
            "with open(os.environ['HOOK_RECORD'], 'a') as f:\n"
            "    f.write(json.dumps([sys.argv[1:], os.environ.get('PYTEST_XDIST_AUTO_NUM_WORKERS')]) + '\\n')\n"
        ),
    }
    for name, body in scripts.items():
        path = tools / name
        path.write_text(f"#!{sys.executable}\n{body}")
        path.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if k not in ("PRECOMMIT_PYTEST_WORKERS", "PYTEST_XDIST_AUTO_NUM_WORKERS")}
    env.update(PATH=f"{tools}:{env['PATH']}", HOOK_RECORD=str(record), PRECOMMIT_PG="0")
    if override is not None:
        env["PRECOMMIT_PYTEST_WORKERS"] = override
    if caller is not None:
        env["PYTEST_XDIST_AUTO_NUM_WORKERS"] = caller
    done = subprocess.run(["bash", str(ROOT / "scripts/git-hooks/pre-commit")], cwd=tmp_path,
                          env=env, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stdout + done.stderr
    calls = [json.loads(line) for line in record.read_text().splitlines()]
    pytest_calls = [(args, workers) for args, workers in calls if "pytest" in args]
    assert pytest_calls == [(["run", "--quiet", "pytest", "tests/", "--timeout=120", "-q", "--no-header", "-n", "auto"], expected)]


def test_real_pytest_restarts_once_through_fake_wt(tmp_path):
    # Use the real conftest, not a reconstructed hook: disconnecting its call must fail this test.
    for relative in ("tests/__init__.py", "tests/conftest.py", "tests/pgtier.py", "tests/machine_slot.py"):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    (tmp_path / "tests/test_probe.py").write_text(
        "import os\ndef test_probe():\n"
        "    assert os.environ.get('TEMPER_PYTEST_MACHINE_SLOT') == '1'\n"
        "    assert os.environ['PYTEST_XDIST_WORKER'] in ('gw0', 'gw1')\n"
    )
    tools = tmp_path / "bin"
    tools.mkdir()
    record = tmp_path / "wt.jsonl"
    wt = tools / "wt"
    wt.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "with open(os.environ['WT_RECORD'], 'a') as f:\n"
        "    f.write(json.dumps([sys.argv[1:], os.environ.get('TEMPER_PYTEST_MACHINE_SLOT')]) + '\\n')\n"
        "assert sys.argv[1:3] == ['slot', '--']\n"
        "os.execv(sys.argv[3], sys.argv[3:])\n"
    )
    wt.chmod(0o755)
    # Only this explicit integration fixture removes the nested-test/CI exemptions.
    env = {k: v for k, v in os.environ.items() if k not in (*SKIP_VARS, "PYTEST_ADDOPTS", "TEMPER_TEST_DATABASE_URL")}
    env.update(PATH=f"{tools}:{env['PATH']}", WT_RECORD=str(record), PYTHONPATH=f"{tmp_path}:{ROOT}")
    args = [sys.executable, "-m", "pytest", "-q", "tests/test_probe.py", "-n", "2"]
    done = subprocess.run(args, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "1 passed" in done.stdout
    assert [json.loads(line) for line in record.read_text().splitlines()] == [[["slot", "--", *args], "1"]]
