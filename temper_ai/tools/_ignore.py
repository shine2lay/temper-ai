"""What the search tools skip — shared by Grep and Glob.

Two layers, because neither alone is enough:

* **The repo's own .gitignore.** If a project already declares `build/`,
  `*.generated.ts` or `fixtures/huge/` uninteresting, a search tool that walks
  them wastes the agent's context on files the humans decided not to look at.
  This is the layer pi's grep/find have and temper's shelling-out did not.
* **A baseline skip list.** A workspace is not always a git repo (a scratch
  directory, a downloaded tarball), and some directories are never worth
  searching even when untracked — `.venv`, `node_modules`, `__pycache__`.

Scope: the root `.gitignore` plus `.git/info/exclude`. Per-directory
`.gitignore` files deeper in the tree are not read — that is the remaining gap
versus `git check-ignore`, and it is deliberate: reading every nested file
would mean a stat per directory on every search, and the baseline list already
covers the nested cases that actually appear (vendor dirs, caches).
"""

from pathlib import Path

import pathspec

#: Skipped regardless of .gitignore — see module docstring.
BASELINE_DIRS = frozenset({
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", "dist", "build", ".next",
})


class Ignore:
    """Decides whether a path should be skipped, relative to a search root."""

    def __init__(self, root: Path, use_gitignore: bool = True) -> None:
        self.root = root
        self._spec: pathspec.PathSpec | None = None
        if use_gitignore:
            lines: list[str] = []
            for candidate in (root / ".gitignore", root / ".git" / "info" / "exclude"):
                try:
                    lines.extend(candidate.read_text(encoding="utf-8", errors="replace").splitlines())
                except OSError:
                    continue
            if lines:
                # "gitignore", not the older "gitwildmatch" — pathspec 1.x deprecates the latter.
                self._spec = pathspec.PathSpec.from_lines("gitignore", lines)

    def skips(self, path: Path) -> bool:
        """True when `path` (a file under root) should not be searched."""
        try:
            rel = path.relative_to(self.root)
        except ValueError:
            return False
        if any(part in BASELINE_DIRS for part in rel.parts):
            return True
        if self._spec is None:
            return False
        # Test the file and each parent directory: gitignore rules like "build/"
        # exclude a directory, and pathspec matches those against "build/", not
        # against "build/nested/file.txt".
        if self._spec.match_file(rel.as_posix()):
            return True
        for parent in rel.parents:
            if parent == Path("."):
                break
            if self._spec.match_file(parent.as_posix() + "/"):
                return True
        return False
