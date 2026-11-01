"""Fixed synthetic files only; no protected host path, state, key or live DB."""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Event
from unittest.mock import Mock

import pytest

from temper_ai.observability import usage_feed_epoch_journal as journal

SOURCE = "00000000-0000-4000-8000-000000000001"
OTHER = "00000000-0000-4000-8000-000000000002"


def semantic(records):
    # Only an envelope-stage fixture. Transition tests use validate_history,
    # the mandatory production protocol validator, not this fixture validator.
    for record in records:
        journal.closed(record.data, {"fixture"})
        if record.data["fixture"] != "known":
            raise journal.JournalError()


@pytest.fixture
def store(tmp_path):
    tmp_path.chmod(0o700)
    return journal.HostJournal(tmp_path / "synthetic-history", SOURCE, semantic)


def initialize(store):
    with store.locked(journal.EMPTY_HEAD, virgin=True) as session:
        session.confirm_history()
        return session.append("ADMISSION", {"fixture": "known"}).head


def raw(store):
    return store.path.read_bytes()


def overwrite(store, value):
    store.path.write_bytes(value)
    store.path.chmod(0o600)


def test_00_combined_fullappend_sync_chain_reopen_and_closed_session(store, monkeypatch):
    actual_write, actual_sync = os.write, os.fsync
    writes, syncs = [], []

    def short(fd, value):
        writes.append(len(value))
        return actual_write(fd, value[:7])

    def synced(fd):
        syncs.append("parent" if stat.S_ISDIR(os.fstat(fd).st_mode) else "file")
        actual_sync(fd)

    monkeypatch.setattr(os, "write", short)
    monkeypatch.setattr(os, "fsync", synced)
    first = initialize(store)
    with store.locked(first) as session:
        session.confirm_history()
        second = session.append("INTENT", {"fixture": "known"}).head
        assert session.records[-1].previous == first.checksum
        assert second.sequence == 2 and second.checksum != first.checksum
    with pytest.raises(journal.JournalError):
        session.append("INTENT", {"fixture": "known"})
    records = journal.validate_bytes(raw(store), SOURCE, semantic)
    assert records[-1].head == second and len(writes) > 10
    assert syncs[:4] == ["file", "parent", "file", "parent"]
    assert syncs.count("parent") == 4  # two creations + two explicit confirmations
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
    with store.locked(second) as reopened:
        assert reopened.head == second
        with pytest.raises(journal.JournalError):
            reopened.append("INTENT", {"fixture": "known"})  # no implicit sync trust
        reopened.confirm_history()


@pytest.mark.parametrize("damage", ["empty", "torn", "checksum", "order", "duplicate", "whitespace",
                                    "version", "sequence-bool", "source", "kind", "shape", "semantic"])
def test_known_damage_preserved_without_salvage(store, damage):
    head = initialize(store)
    good = raw(store)
    row = json.loads(good)
    if damage == "empty":
        bad = b""
    elif damage == "torn":
        bad = good[:-1]
    elif damage == "checksum":
        row["checksum"] = "1" * 64
        bad = journal.canonical_bytes(row) + b"\n"
    elif damage == "order":
        row["previous"] = "1" * 64
        row["checksum"] = journal.digest({k: v for k, v in row.items() if k != "checksum"})
        bad = journal.canonical_bytes(row) + b"\n"
    elif damage == "duplicate":
        bad = good.replace(b'"version":1', b'"version":1,"version":1')
    elif damage == "whitespace":
        bad = b" " + good
    else:
        if damage == "version":
            row["version"] = 2
        elif damage == "sequence-bool":
            row["sequence"] = True
        elif damage == "source":
            row["source_instance"] = OTHER
        elif damage == "kind":
            row["kind"] = "AUTO-REPAIR"
        elif damage == "shape":
            row["extra"] = "not-closed"
        elif damage == "semantic":
            row["data"] = {"fixture": "not-known"}
        row["checksum"] = journal.digest({k: v for k, v in row.items() if k != "checksum"})
        bad = journal.canonical_bytes(row) + b"\n"
    assert bad != good
    overwrite(store, bad)
    with pytest.raises(journal.JournalError):
        with store.locked(head):
            pytest.fail("damaged history must not enter")
    assert raw(store) == bad  # no truncation, repaired prefix, normalization or rewrite


def test_initialized_missing_and_existing_empty_are_never_virgin(store):
    head = initialize(store)
    store.path.unlink()
    for expected, virgin in ((head, False), (head, True)):
        with pytest.raises(journal.JournalError):
            with store.locked(expected, virgin=virgin):
                pytest.fail("initialized loss cannot enter")
    assert not store.path.exists()  # initialized loss never creates a replacement
    overwrite(store, b"")  # explicit damaged synthetic fixture, not a repair
    with pytest.raises(journal.JournalError):
        with store.locked(journal.EMPTY_HEAD, virgin=True):
            pytest.fail("pre-existing empty is not recorded virgin")


def test_wrong_head_source_and_valid_suffix_rollback_are_closed_when_pinned(store):
    first = initialize(store)
    initial = raw(store)
    with store.locked(first) as session:
        session.confirm_history()
        last = session.append("INTENT", {"fixture": "known"}).head
    for expected in (first, journal.EMPTY_HEAD):
        with pytest.raises(journal.JournalError, match="epoch-history-head-changed"):
            with store.locked(expected):
                pytest.fail("stale pin")
    wrong = journal.HostJournal(store.path, OTHER, semantic)
    with pytest.raises(journal.JournalError):
        with wrong.locked(last):
            pytest.fail("wrong source")
    overwrite(store, initial)
    with pytest.raises(journal.JournalError, match="epoch-history-head-changed"):
        with store.locked(last):
            pytest.fail("retained current-head pin catches this rollback")
    # No universal valid-suffix/backup detection claim: an independently rolled
    # back external pin would require the actual native retained evidence proof.


@pytest.mark.parametrize("failure", ["zero-write", "partial-write", "file-sync", "parent-sync"])
def test_failed_write_or_sync_poison_and_preserve_bytes(store, monkeypatch, failure):
    head = initialize(store)
    before = raw(store)
    with pytest.raises(journal.JournalError):
        with store.locked(head) as session:
            if failure != "parent-sync":
                session.confirm_history()
            real_write, real_sync = os.write, os.fsync
            calls = 0

            def write(fd, value):
                nonlocal calls
                calls += 1
                if failure == "zero-write":
                    return 0
                if failure == "partial-write":
                    if calls == 1:
                        return real_write(fd, value[:13])
                    raise OSError("private-driver-canary")
                return real_write(fd, value)

            def sync(fd):
                is_parent = stat.S_ISDIR(os.fstat(fd).st_mode)
                if (failure == "parent-sync" and is_parent) or (failure == "file-sync" and not is_parent):
                    raise OSError("private-driver-canary")
                real_sync(fd)

            monkeypatch.setattr(os, "write", write)
            monkeypatch.setattr(os, "fsync", sync)
            with pytest.raises(journal.JournalError, match="^epoch-history-sync-failed$") as error:
                if failure == "parent-sync":
                    session.confirm_history()
                else:
                    session.append("INTENT", {"fixture": "known"})
            assert "canary" not in str(error.value)
            session.append("INTENT", {"fixture": "known"})  # poisoned, not implicitly retried
    after = raw(store)
    assert after.startswith(before)
    assert (after != before) == (failure in ("partial-write", "file-sync"))
    if failure == "partial-write":
        with pytest.raises(journal.JournalError):
            journal.validate_bytes(after, SOURCE, semantic)


@pytest.mark.parametrize("which", ["file", "parent"])
def test_creation_sync_failure_cannot_become_automatic_init(store, monkeypatch, which):
    real = os.fsync

    def sync(fd):
        directory = stat.S_ISDIR(os.fstat(fd).st_mode)
        if directory == (which == "parent"):
            raise OSError("creation-canary")
        real(fd)

    with monkeypatch.context() as patch:
        patch.setattr(os, "fsync", sync)
        with pytest.raises(journal.JournalError):
            initialize(store)
    # Provisioning did not finish; an operator must not infer authority from files.
    assert store.path.with_name(store.path.name + ".lock").exists()
    assert not store.path.exists()


@pytest.mark.parametrize("guard", ["record-bytes", "history-bytes", "record-count"])
def test_bounds_refuse_before_appending(store, monkeypatch, guard):
    head = initialize(store)
    before = raw(store)
    with store.locked(head) as session:
        session.confirm_history()
        monkeypatch.setattr(journal, {"record-bytes": "MAX_RECORD_BYTES", "history-bytes": "MAX_HISTORY_BYTES",
                                     "record-count": "MAX_RECORDS"}[guard],
                            {"record-bytes": 100, "history-bytes": len(before) + 1, "record-count": 1}[guard])
        with pytest.raises(journal.JournalError):
            session.append("INTENT", {"fixture": "known"})
    assert raw(store) == before


@pytest.mark.parametrize("object_kind", ["journal-symlink", "lock-symlink", "hardlink", "mode", "parent-mode", "fifo"])
def test_protected_custody_refusals(store, tmp_path, object_kind):
    head = initialize(store)
    if object_kind == "journal-symlink":
        target = tmp_path / "fixture-other"
        store.path.rename(target)
        store.path.symlink_to(target)
    elif object_kind == "lock-symlink":
        lock = store.path.with_name(store.path.name + ".lock")
        target = tmp_path / "other-lock"
        lock.rename(target)
        lock.symlink_to(target)
    elif object_kind == "hardlink":
        os.link(store.path, tmp_path / "another-link")
    elif object_kind == "mode":
        store.path.chmod(0o644)
    elif object_kind == "parent-mode":
        tmp_path.chmod(0o755)
    elif object_kind == "fifo":
        store.path.unlink()
        os.mkfifo(store.path, 0o600)
    with pytest.raises(journal.JournalError):
        with store.locked(head):
            pytest.fail("unsafe custody")


_MUTEX_CHILD = r'''
import sys
from pathlib import Path
from temper_ai.observability.usage_feed_epoch_journal import HostJournal, JournalError, JournalHead

j = HostJournal(Path(sys.argv[1]), sys.argv[2], lambda rows: None)
h = JournalHead(int(sys.argv[3]), sys.argv[4])
print("READY", flush=True)
if sys.stdin.readline() != "GO\n":
    sys.exit(2)
print("ATTEMPT", flush=True)
try:
    with j.locked(h, timeout=.08):
        print("entered")
except JournalError as error:
    print(error.code)
'''


# A failing assert, its message or a raised exception must never carry what the
# child printed or its argv (CWE-532): pytest's rewriting prints assert operands,
# its report prints helper arguments' repr, and TimeoutExpired's text holds argv.
# So asserts see only ints, bools and these closed labels.
_MUTEX_LINES = ("ATTEMPT", "entered", "epoch-host-busy")


class _MutexChild(subprocess.Popen):
    def __repr__(self):
        return "<mutex child>"  # Popen's own repr starts with argv


def _child_said(child, line):
    return child.stdout.readline() == f"{line}\n"


@contextmanager
def _mutex_child(store, head, source=SOURCE, *, code=_MUTEX_CHILD, pass_fds=()):
    command = [sys.executable, "-c", code, str(store.path), source, str(head.sequence), head.checksum]
    with _MutexChild(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                     stderr=subprocess.PIPE, text=True, pass_fds=pass_fds) as child:
        try:
            yield child
        finally:
            # Popen's context closes every pipe; kill first so a failed assertion
            # or result watchdog cannot leave its context waiting on a stuck child.
            if child.poll() is None:
                child.kill()
            child.wait()


def _expect_mutex_result(child, expected):
    # Imports and construction are startup, bounded by pytest's existing overall
    # watchdog (also bounds cleanup), not the three-second lock-result watchdog.
    assert _child_said(child, "READY"), "mutex child did not reach READY"
    try:
        out, err = child.communicate(input="GO\n", timeout=3)
    except subprocess.TimeoutExpired as expired:
        seen = {b"ATTEMPT\n": "after ATTEMPT", None: "before ATTEMPT"}.get(expired.output, "after other output")
        # from None: the report must not chain the TimeoutExpired, whose text is argv.
        raise pytest.fail.Exception(
            f"mutex child gave no lock result within the {expired.timeout} s watchdog {seen}") from None
    exit_code, wrote_stderr = child.returncode, bool(err)
    said = [line if line in _MUTEX_LINES else "other" for line in out.splitlines()]
    assert exit_code == 0 and not wrote_stderr, "mutex child exited with an error"
    assert said == ["ATTEMPT", expected], "mutex child returned wrong result"


def _assert_child_closed(child):
    assert child.returncode is not None
    assert all(pipe.closed for pipe in (child.stdin, child.stdout, child.stderr))
    with pytest.raises(ChildProcessError):
        os.waitpid(child.pid, os.WNOHANG)  # reaped, not merely signalled


def test_cross_process_source_mutex_and_no_replacement(store):
    head = initialize(store)
    with store.locked(head):
        for source in (SOURCE, OTHER):
            # Wrong source uses the SAME lock, not a per-source-id second inode.
            with _mutex_child(store, head, source) as child:
                _expect_mutex_result(child, "epoch-host-busy")
            _assert_child_closed(child)
    with _mutex_child(store, head) as child:
        _expect_mutex_result(child, "entered")
    _assert_child_closed(child)


def test_mutex_child_startup_is_outside_the_lock_result_watchdog(store, monkeypatch):
    head = initialize(store)
    reader, writer = os.pipe()
    with os.fdopen(reader, "rb") as gate, os.fdopen(writer, "wb") as release:
        code = (f'import os\nprint("SPAWNED", flush=True)\nassert os.read({gate.fileno()}, 1) == b"!"\n'
                + _MUTEX_CHILD)
        # Close/kill the child BEFORE joining a worker blocked on its READY pipe.
        with ThreadPoolExecutor(max_workers=1) as pool:
            with store.locked(head), _mutex_child(store, head, code=code, pass_fds=(gate.fileno(),)) as child:
                assert _child_said(child, "SPAWNED")
                started, ready = Event(), Event()
                readline, communicate = child.stdout.readline, child.communicate

                def observe_ready():
                    line = readline()
                    if line == "READY\n":
                        ready.set()
                    return line

                def after_ready(*args, **kwargs):
                    assert ready.is_set(), "result watchdog started before READY"
                    assert kwargs == {"input": "GO\n", "timeout": 3}
                    return communicate(*args, **kwargs)

                def expect():
                    started.set()
                    _expect_mutex_result(child, "epoch-host-busy")

                monkeypatch.setattr(child.stdout, "readline", observe_ready)
                monkeypatch.setattr(child, "communicate", after_ready)
                result = pool.submit(expect)
                started.wait()  # bounded, like child startup, by the suite watchdog
                # A controlled pre-import hold outlasts the OLD combined deadline.
                # No sleep or slow-machine assumption decides when startup resumes.
                with pytest.raises(subprocess.TimeoutExpired):
                    child.wait(timeout=3)
                assert not result.done() and not ready.is_set()
                release.write(b"!")
                release.flush()
                result.result()
            _assert_child_closed(child)
    assert gate.closed and release.closed


def test_mutex_child_post_ready_hang_still_times_out_and_is_reaped(store):
    head = initialize(store)
    code = _MUTEX_CHILD.replace('print("ATTEMPT", flush=True)',
                               'print("ATTEMPT", flush=True)\nimport signal\nsignal.pause()')
    with store.locked(head):
        expected = "^mutex child gave no lock result within the 3 s watchdog after ATTEMPT$"
        with pytest.raises(pytest.fail.Exception, match=expected):
            with _mutex_child(store, head, code=code) as child:
                _expect_mutex_result(child, "epoch-host-busy")
        _assert_child_closed(child)


@pytest.mark.parametrize("source", [SOURCE, OTHER])
def test_mutex_child_cannot_pass_exclusion_when_flock_is_bypassed(store, source):
    head = initialize(store)
    code = _MUTEX_CHILD.replace('print("READY", flush=True)',
                               'import fcntl\nfcntl.flock = lambda *args: None\nprint("READY", flush=True)')
    with store.locked(head):
        with pytest.raises(AssertionError, match="mutex child returned wrong result"):
            with _mutex_child(store, head, source, code=code) as child:
                _expect_mutex_result(child, "epoch-host-busy")
        _assert_child_closed(child)


@pytest.mark.parametrize("old,new", [
    ('print("READY", flush=True)', 'print("NOT-READY", flush=True)'),
    ('print("READY", flush=True)', 'sys.exit(0)'),
    ('print("ATTEMPT", flush=True)', ''),
    ('print("entered")', 'print("epoch-host-busy")'),
    ('print("entered")', 'print("entered"); sys.exit(7)'),
    ('print("entered")', 'print("entered"); print("known-error", file=sys.stderr)'),
])
def test_mutex_child_protocol_and_result_failures_close_every_pipe(store, old, new):
    head = initialize(store)
    with pytest.raises(AssertionError, match="mutex child"):
        with _mutex_child(store, head, code=_MUTEX_CHILD.replace(old, new)) as child:
            _expect_mutex_result(child, "entered")
    _assert_child_closed(child)


# Canaries sit after an allowed word or line, so a looser match (prefix, contains,
# filter instead of map) keeps them visible or lets the fault pass, and fails here.
_CANARY_FAULTS = {  # fault: (child line replaced, replacement, failure it must give)
    "not-ready": ('print("READY", flush=True)',
                  'print("READY {stdout}", flush=True); print("{stderr}", file=sys.stderr, flush=True)',
                  "did not reach READY"),
    "wrong-result": ('print("entered")', 'print("entered {stdout}")', "returned wrong result"),
    "extra-line": ('print("entered")', 'print("entered"); print("{stdout}")', "returned wrong result"),
    "stderr": ('print("entered")', 'print("entered"); print("{stdout}"); print("{stderr}", file=sys.stderr)',
               "exited with an error"),
    "exit": ('print("entered")', 'print("{stdout}"); print("{stderr}", file=sys.stderr); sys.exit(7)',
             "exited with an error"),
    "post-ready-hang": ('print("ATTEMPT", flush=True)',
                        'print("ATTEMPT", flush=True); print("{stdout}", flush=True); '
                        'print("{stderr}", file=sys.stderr, flush=True)\nimport signal\nsignal.pause()',
                        "within the 3 s watchdog after other output"),
}


@pytest.mark.parametrize("fault", list(_CANARY_FAULTS))
def test_mutex_child_failure_text_carries_no_child_output_or_argv(store, fault):
    head = initialize(store)
    # Fresh tokens, so no source line shown in the report can contain them.
    canary = {stream: f"{stream}-canary-{uuid.uuid4().hex}" for stream in ("stdout", "stderr", "argv")}
    old, new, failure = _CANARY_FAULTS[fault]
    code = f"# {canary['argv']}\n" + _MUTEX_CHILD.replace(old, new.format(**canary))
    with pytest.raises((AssertionError, pytest.fail.Exception), match=failure) as error:
        with _mutex_child(store, head, code=code) as child:
            _expect_mutex_result(child, "entered")
    _assert_child_closed(child)
    # The text pytest reports: message, frames with their arguments, chained exceptions.
    text = str(error.value) + str(error.getrepr(funcargs=True, style="long", chain=True))
    leaked = sorted(stream for stream, token in canary.items() if token in text)
    # Popen's own repr, whatever the class is named: "<Name: returncode: N args: [argv...]>".
    shows_process_repr = re.search(r"<\w+: returncode: ", text) is not None
    assert leaked == [] and not shows_process_repr


def test_inode_change_has_real_bite(store, tmp_path, monkeypatch):
    head = initialize(store)
    original = raw(store)
    with store.locked(head) as session:
        session.confirm_history()
        moved = tmp_path / "retained-old-inode"
        store.path.rename(moved)
        overwrite(store, original)

        def closed_assertion():
            with pytest.raises(journal.JournalError):
                _ = session.head

        closed_assertion()
        with monkeypatch.context() as mutation:
            mutation.setattr(journal, "_same_inode", lambda *args: None)
            with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
                closed_assertion()
        # Restore the fixture identity so context exit validates its held inode.
        store.path.unlink()
        moved.rename(store.path)


def test_invalid_scalars_closed_json_semantics_and_no_mutable_payload(store):
    with pytest.raises(journal.JournalError):
        journal.JournalHead(True, journal.ZERO_DIGEST)
    with pytest.raises(journal.JournalError):
        journal.JournalHead(0, "1" * 64)
    for value in ({"bad": float("nan")}, {"bad": object()}):
        with pytest.raises(journal.JournalError):
            journal.canonical_bytes(value)
    head = initialize(store)
    with store.locked(head) as session:
        session.confirm_history()
        data = {"fixture": "known"}
        record = session.append("INTENT", data)
        data["fixture"] = "changed"
        returned = record.data
        returned["fixture"] = "changed"
        assert record.data == {"fixture": "known"}
        with pytest.raises(journal.JournalError):
            session.append("INTENT", {"fixture": "unknown"})
        with pytest.raises(journal.JournalError):
            session.append("AUTO-REPAIR", data)


def test_missing_parent_no_creation_no_default_path(tmp_path):
    store = journal.HostJournal(tmp_path / "unprovisioned" / "history", SOURCE, semantic)
    with pytest.raises(journal.JournalError):
        initialize(store)
    assert not store.path.parent.exists()
    with pytest.raises(journal.JournalError):
        journal.HostJournal(tmp_path / "history", "INVALID", Mock())
