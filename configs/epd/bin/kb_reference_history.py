"""Read Git's evidence for one missing reference; never infer a rename ourselves.

Deletion discovery uses a literal path on first-parent history. Rename detection
must see the whole parent/child diff: a pathspec would hide its destination.
Only the latest deletion of each path counts; do not follow rename chains.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import NamedTuple


class Rename(NamedTuple):
    commit: str
    old_path: str  # Git-root relative, even when --repo is a subdirectory
    new_path: str


class ReferenceHistory:
    """Read-only, lazy history with per-invocation deletion and diff caches."""

    def __init__(self, root: Path):
        self.root = root
        self._git_root: Path | None = None
        self._head: str | None = None
        self._loaded = False
        self._deletions: dict[str, tuple[Rename, ...]] = {}
        self._diffs: dict[str, tuple[Rename, ...]] = {}

    def _git(self, *args: str) -> bytes:
        return subprocess.run(
            ["git", "-C", str(self._git_root or self.root), *args],
            capture_output=True, check=True,
        ).stdout

    @property
    def git_root(self) -> Path:
        if not self._loaded:
            self._git_root = Path(os.fsdecode(self._git("rev-parse", "--show-toplevel")).removesuffix("\n"))
            result = subprocess.run(
                ["git", "-C", str(self._git_root), "rev-parse", "--verify", "--quiet", "HEAD"],
                capture_output=True,
            )
            if result.returncode == 0:
                self._head = result.stdout.decode("ascii").strip()
            elif result.returncode != 1:  # unborn repository is not an internal error
                result.check_returncode()
            self._loaded = True
        assert self._git_root is not None
        return self._git_root

    def _renames(self, commit: str) -> tuple[Rename, ...]:
        if commit not in self._diffs:
            fields = self._git(
                "diff", "--no-ext-diff", "--no-textconv", "--no-relative", "-M",
                "--name-status", "-z", f"{commit}^", commit,
            ).split(b"\0")
            if fields[-1] != b"":
                raise ValueError("Git name-status output is not NUL-terminated")
            fields.pop()
            renames = []
            i = 0
            while i < len(fields):
                status = fields[i].decode("ascii")
                width = 3 if status.startswith(("R", "C")) else 2
                if i + width > len(fields):
                    raise ValueError("Git name-status output has an incomplete path record")
                if status.startswith("R"):
                    renames.append(Rename(commit, os.fsdecode(fields[i + 1]), os.fsdecode(fields[i + 2])))
                i += width
            self._diffs[commit] = tuple(sorted(renames))
        return self._diffs[commit]

    def renames_from(self, target: Path) -> tuple[Rename, ...]:
        """Return all exact rename records at this path's latest deletion, if any."""
        path = target.relative_to(self.git_root).as_posix()
        if path not in self._deletions:
            found: tuple[Rename, ...] = ()
            if self._head:
                commit = self._git(
                    "log", "--first-parent", "-1", "--format=%H", "--no-renames",
                    "--diff-filter=D", self._head, "--", f":(literal){path}",
                ).decode("ascii").strip()
                if commit:
                    found = tuple(rename for rename in self._renames(commit) if rename.old_path == path)
            self._deletions[path] = found
        return self._deletions[path]
