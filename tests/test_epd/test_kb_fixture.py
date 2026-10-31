"""The KB fixture must stop writing before its complete no-write baseline.

Trace actual Git children, then control a real maintenance process with a pipe.
The latter deliberately starts maintenance asynchronously even on older Git;
it proves the disappearing-lock ordering, not the historical CI scheduling.
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

from tests.test_epd import test_kb_refresh as refresh_tests
from tests.test_epd.test_kb_check import commit, git, put
from tests.test_epd.test_kb_check import make_repo as make_repo  # noqa: F401


def maintenance_children(trace: Path) -> list[list[str]]:
    events = [json.loads(line) for line in trace.read_text().splitlines()]
    return [event["argv"] for event in events if event["event"] == "child_start"
            and "maintenance" in event["argv"]]


@pytest.mark.parametrize("broken_index", [True, False])
def test_completed_fixture_is_quiet_before_full_cli_byte_safety(make_repo, tmp_path, monkeypatch, broken_index):
    """Whole feature: real factory, later commit, baseline and four real CLI calls."""
    trace = tmp_path / "fixture-trace.json"
    monkeypatch.setenv("GIT_TRACE2_EVENT", str(trace))
    root = make_repo({"source.py": "Kept = 1\n"}, "`source.py::Kept`\n")
    (root / "link.py").symlink_to("source.py")
    commit(root)
    monkeypatch.delenv("GIT_TRACE2_EVENT")
    # Checking actual children works on both foreground and detached Git versions.
    # No automatic child means none can outlive the fixture and race its baseline.
    assert maintenance_children(trace) == []
    put(root, "ignored/local.py", "Local = 1\n")
    if broken_index:
        (root / ".git/index").write_bytes(b"broken")
    refresh_tests.unchanged_cli(root, 2 if broken_index else 0)


@contextmanager
def held_git_maintenance(root: Path, tmp_path: Path):
    """Real Git owns the lock; pre-auto-gc waits for a byte, then refuses GC.

    Two fixed blobs in Git's sampled objects/17 bucket trigger gc.auto=1.
    The refusing hook keeps the control limited to the maintenance lock's
    lifecycle, not a repack or another writer. All settings are per-command.
    """
    for number in (156, 237):
        blob = put(tmp_path, f"blob-{number}", f"KB maintenance control {number}\n")
        assert git(root, "hash-object", "-w", str(blob)).startswith(b"17")
    ready_read, ready_write = os.pipe()
    release_read, release_write = os.pipe()
    hook = put(root, ".git/hooks/pre-auto-gc", "#!/bin/sh\nexec " + shlex.quote(sys.executable)
               + " -c " + shlex.quote(
                   f"import os; os.write({ready_write}, b'R'); "
                   f"os.read({release_read}, 1); raise SystemExit(1)"
               ) + "\n")
    hook.chmod(0o755)
    command = ["git", "-C", str(root), "-c", "gc.auto=1", "-c", "gc.autoDetach=false",
               "-c", "maintenance.autoDetach=false", "maintenance", "run", "--auto", "--quiet", "--task=gc"]
    with subprocess.Popen(command, pass_fds=(ready_write, release_read),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE) as process:
        os.close(ready_write)
        os.close(release_read)
        released = False

        def finish():
            nonlocal released
            if not released:
                released = True
                os.write(release_write, b"G")
            stdout, stderr = process.communicate()
            assert process.returncode == 0 and stdout == stderr == b""

        try:
            assert os.read(ready_read, 1) == b"R"
            assert process.poll() is None
            lock = root / ".git/objects/maintenance.lock"
            assert lock.is_file()
            yield lock, finish
        finally:
            finish()
            os.close(ready_read)
            os.close(release_write)


def test_real_maintenance_lock_can_disappear_during_before_snapshot(make_repo, tmp_path, monkeypatch):
    """Read the real lock; let its owner exit; unchanged snapshot then fails at stat."""
    root = make_repo({"source.py": "Kept = 1\n"}, "`source.py::Kept`\n")
    cli_calls = []
    original_run = refresh_tests.run

    def record_cli(*args, **kwargs):
        cli_calls.append(args)
        return original_run(*args, **kwargs)

    monkeypatch.setattr(refresh_tests, "run", record_cli)
    with held_git_maintenance(root, tmp_path) as (lock, finish):
        (root / ".git/index").write_bytes(b"broken")
        original_read = Path.read_bytes
        reads = []

        def read_then_finish(path):
            content = original_read(path)
            if path == lock:
                reads.append(content)
                finish()  # process completion, not a sleep or polling window
                assert not lock.exists()
            return content

        monkeypatch.setattr(Path, "read_bytes", read_then_finish)
        with pytest.raises(FileNotFoundError) as failure:
            refresh_tests.unchanged_cli(root, 2)
        assert Path(failure.value.filename) == lock
        assert reads == [b""]
        assert cli_calls == []  # failure is baseline capture, not a CLI side effect
    # Once the explicit writer is joined, the same real broken-index CLI passes.
    refresh_tests.unchanged_cli(root, 2)
    assert len(cli_calls) == 4


@pytest.mark.parametrize("change", ["bytes", "mode", "link", "directory"])
def test_complete_snapshot_still_catches_cli_side_effects(make_repo, monkeypatch, change):
    """A quiet fixture must not hide real writes, even to ignored or Git metadata."""
    root = make_repo({"source.py": "Kept = 1\n"}, "`source.py::Kept`\n")
    marker = put(root, ".git/snapshot-marker", "before\n")
    marker.chmod(0o644)
    link = root / "ignored/link"
    link.parent.mkdir()
    link.symlink_to("../source.py")
    original_run = refresh_tests.run

    def write_after_cli(*args, **kwargs):
        result = original_run(*args, **kwargs)
        if change == "bytes":
            marker.write_bytes(b"after\n")
        elif change == "mode":
            marker.chmod(0o600)
        elif change == "link":
            link.unlink()
            link.symlink_to("../other.py")
        else:
            (root / "ignored/new-directory").mkdir(exist_ok=True)
        return result

    monkeypatch.setattr(refresh_tests, "run", write_after_cli)
    with pytest.raises(AssertionError):
        refresh_tests.unchanged_cli(root, 0)
