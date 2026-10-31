"""Both box paths share one bounded .git reader, retaining their distinct error/type policies."""

import errno
import os

import pytest

from temper_ai.spawner import box_seal
from temper_ai.spawner.docker_spawner import _gitdir_named


def test_both_callers_share_the_first_line_and_sealed_keeps_its_pinned_directory(tmp_path, monkeypatch):
    workspace = tmp_path / "run"
    workspace.mkdir()
    (workspace / ".git").write_text("gitdir: .own\ngitdir: /outside\n")
    # A lost dir_fd must not pass just because the process's own .git also points outside.
    unrelated = tmp_path / "unrelated-cwd"
    unrelated.mkdir()
    (unrelated / ".git").write_text("gitdir: .own\n")
    monkeypatch.chdir(unrelated)
    fd = os.open(workspace, os.O_RDONLY | os.O_DIRECTORY)
    try:
        assert _gitdir_named(str(workspace)) == ".own"
        assert box_seal.read_gitdir(".git", dir_fd=fd, regular_only=True) == ".own"
        box_seal._no_outside_repo(fd, str(workspace))

        workspace.rename(tmp_path / "pinned")
        workspace.mkdir()
        (workspace / ".git").write_text("gitdir: /replacement\n")
        assert _gitdir_named(str(workspace)) == "/replacement"
        assert box_seal.read_gitdir(".git", dir_fd=fd, regular_only=True) == ".own"
        box_seal._no_outside_repo(fd, str(workspace))

        # The harmless cwd decoy stays put; only the pinned record now points outside.
        (tmp_path / "pinned" / ".git").write_text("gitdir: /outside-pinned\n")
        with pytest.raises(box_seal.BoxProfileError, match="outside-pinned"):
            box_seal._no_outside_repo(fd, str(workspace))
    finally:
        os.close(fd)


@pytest.mark.parametrize(("content", "expected"), [
    (b"", None),
    (b"not a link\ngitdir: /outside\n", None),
    (b" gitdir: /outside\n", None),
    (b"gitdir: \n", ""),
    (b"gitdir: ../main/.git/worktrees/run \r\ngitdir: /ignored", "../main/.git/worktrees/run"),
    (b"gitdir: /bad-\xff\n", "/bad-\ufffd"),
    (b"gitdir: " + b"x" * 5000, "x" * (4096 - len(b"gitdir: "))),
])
def test_reader_variants_keep_the_same_bounded_first_line(tmp_path, content, expected):
    (tmp_path / ".git").write_bytes(content)
    fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        assert _gitdir_named(str(tmp_path)) == expected
        assert box_seal.read_gitdir(".git", dir_fd=fd, regular_only=True) == expected
    finally:
        os.close(fd)


@pytest.mark.parametrize("kind", ["missing", "directory", "symlink"])
def test_neither_caller_treats_missing_directory_or_symlink_as_a_gitdir(tmp_path, kind):
    path = tmp_path / ".git"
    if kind == "directory":
        path.mkdir()
    elif kind == "symlink":
        target = tmp_path / "outside"
        target.write_text("gitdir: /outside\n")
        path.symlink_to(target)
    fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        assert _gitdir_named(str(tmp_path)) is None
        box_seal._no_outside_repo(fd, str(tmp_path))
    finally:
        os.close(fd)


def test_fifo_stays_nonblocking_and_only_legacy_reads_its_buffered_line(tmp_path):
    path = tmp_path / ".git"
    os.mkfifo(path)
    fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    fifo = os.open(path, os.O_RDWR | os.O_NONBLOCK)
    try:
        assert _gitdir_named(str(tmp_path)) is None  # empty nonblocking FIFO raises EAGAIN
        os.write(fifo, b"gitdir: /outside\n")
        box_seal._no_outside_repo(fd, str(tmp_path))  # rejects type without consuming the line
        assert _gitdir_named(str(tmp_path)) == "/outside"
    finally:
        os.close(fifo)
        os.close(fd)


def test_read_errors_still_propagate_for_sealed_only_and_both_close(tmp_path, monkeypatch):
    (tmp_path / ".git").write_text("gitdir: .own\n")
    opened = []

    def unreadable(fd, size):
        opened.append(fd)
        raise OSError(errno.EIO, "synthetic read failure")

    fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        monkeypatch.setattr(box_seal.os, "read", unreadable)
        assert _gitdir_named(str(tmp_path)) is None
        with pytest.raises(OSError, match="synthetic read failure"):
            box_seal._no_outside_repo(fd, str(tmp_path))
        assert len(opened) == 2
        for git in opened:
            with pytest.raises(OSError) as caught:
                os.fstat(git)
            assert caught.value.errno == errno.EBADF
    finally:
        os.close(fd)


def test_sealed_type_errors_are_not_swallowed_and_legacy_does_not_stat(tmp_path, monkeypatch):
    (tmp_path / ".git").write_text("gitdir: .own\n")

    def unstattable(fd):
        raise OSError(errno.EIO, "synthetic stat failure")

    fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        monkeypatch.setattr(box_seal.os, "fstat", unstattable)
        assert _gitdir_named(str(tmp_path)) == ".own"
        with pytest.raises(OSError, match="synthetic stat failure"):
            box_seal._no_outside_repo(fd, str(tmp_path))
    finally:
        os.close(fd)
