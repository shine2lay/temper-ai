"""Each member's own project copy (#38, W1): only the workspace's committed content is copied,
never untracked or ignored files (a ``.env`` stays home); a workspace with uncommitted changes to
tracked files is refused with a plain reason, so the team never works on a version nobody
committed; the copies have no remote, no hooks, and keep their git data outside every member's
folder. Model-free and database-free: these pieces are plain git.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from temper_ai.pi_agent.team_leader import CopyError, ProjectCopies
from tests.test_runner.pi_team import leader_support as ls

SECRET = "TOKEN=not-a-real-secret-but-it-must-stay-home\n"


def _member_dirs(root: Path, *names: str) -> dict[str, Path]:
    out = {}
    for name in names:
        pdir = root / "members" / name
        pdir.mkdir(parents=True)
        out[name] = pdir
    return out


def _files(folder: Path) -> list[str]:
    return sorted(str(p.relative_to(folder)) for p in folder.rglob("*") if p.is_file())


def test_w1_only_committed_content_is_copied_never_untracked_or_ignored_files(tmp_path):
    src = ls.project(tmp_path / "proj", {"app.py": "print('hello')\n", ".gitignore": ".env\n"})
    (src / ".env").write_text(SECRET)            # ignored
    (src / "notes.txt").write_text("draft\n")    # untracked
    copies = ProjectCopies(tmp_path / "team", str(src))
    pdirs = _member_dirs(tmp_path / "team", "lead", "builder")

    heads = {name: copies.ensure(name, pdir) for name, pdir in pdirs.items()}

    commit = ls.git(src, "rev-parse", "HEAD").strip()
    assert set(heads.values()) == {commit}, "every copy starts at the workspace's HEAD"
    assert copies.record() == {"source": str(src), "commit": commit}
    for name, pdir in pdirs.items():
        ws = ProjectCopies.worktree(pdir)
        assert _files(ws) == [".gitignore", "app.py"], name
        assert not (ws / ".git").exists(), "git data lives outside the member's folder"
        assert copies.git_dir(name).is_dir()
        assert not copies.git_dir(name).is_relative_to(pdir)
        assert ls.git(ws, f"--git-dir={copies.git_dir(name)}", "remote").strip() == "", \
            "a copy has no remote"
    # nothing under the team folder holds the ignored file's content
    for path in (tmp_path / "team").rglob("*"):
        if path.is_file():
            assert b"must-stay-home" not in path.read_bytes(), path


def test_w1_a_copy_that_exists_is_never_reset(tmp_path):
    src = ls.project(tmp_path / "proj")
    copies = ProjectCopies(tmp_path / "team", str(src))
    pdir = _member_dirs(tmp_path / "team", "lead")["lead"]
    first = copies.ensure("lead", pdir)
    (ProjectCopies.worktree(pdir) / "README.md").write_text("# work in progress\n")

    assert copies.ensure("lead", pdir) == first
    assert (ProjectCopies.worktree(pdir) / "README.md").read_text() == "# work in progress\n"


def test_w1_a_workspace_with_uncommitted_changes_to_tracked_files_is_refused(tmp_path):
    src = ls.project(tmp_path / "proj")
    (src / "app.py").write_text("print('changed, not committed')\n")
    copies = ProjectCopies(tmp_path / "team", str(src))
    pdir = _member_dirs(tmp_path / "team", "lead")["lead"]

    with pytest.raises(CopyError, match="uncommitted changes to tracked files"):
        copies.ensure("lead", pdir)
    assert not copies.record_path.exists(), "nothing is fixed for a refused workspace"


@pytest.mark.parametrize("make, reason", [
    (lambda p: p.mkdir(), "not a git repository"),
    (lambda p: (p.mkdir(), ls.git(p, "init", "-q")), "has no commit yet"),
    (lambda p: None, "is not a folder"),
])
def test_w1_a_workspace_the_team_cannot_copy_is_refused_with_a_plain_reason(
        tmp_path, make, reason):
    src = tmp_path / "proj"
    make(src)
    copies = ProjectCopies(tmp_path / "team", str(src))
    pdir = _member_dirs(tmp_path / "team", "lead")["lead"]

    with pytest.raises(CopyError, match=reason):
        copies.ensure("lead", pdir)


def test_w1_without_a_workspace_every_member_starts_from_an_empty_commit(tmp_path):
    copies = ProjectCopies(tmp_path / "team", None)
    pdirs = _member_dirs(tmp_path / "team", "lead", "builder")

    for name, pdir in pdirs.items():
        head = copies.ensure(name, pdir)
        assert head
        assert _files(ProjectCopies.worktree(pdir)) == []
        files, count = copies.files(name, head)
        assert (files, count) == ({}, 0)
    assert copies.record() == {"source": None, "commit": None}


def test_a_reviewers_copy_is_moved_to_exactly_the_review_commit(tmp_path):
    """Temper commits the leader's copy and moves a reviewer's copy to that commit, dropping
    whatever the reviewer had changed or added (W2: everyone sees exactly that version)."""
    src = ls.project(tmp_path / "proj")
    copies = ProjectCopies(tmp_path / "team", str(src))
    pdirs = _member_dirs(tmp_path / "team", "lead", "builder")
    for name, pdir in pdirs.items():
        copies.ensure(name, pdir)
    lead_ws, builder_ws = (ProjectCopies.worktree(pdirs[n]) for n in ("lead", "builder"))
    (lead_ws / "README.md").write_text("# Tiny\n")
    (builder_ws / "app.py").write_text("print('reviewer edit')\n")
    (builder_ws / "stray.txt").write_text("left behind\n")

    sha = copies.commit_review("lead", pdirs["lead"], "act-1")
    assert copies.commit_review("lead", pdirs["lead"], "act-1") == sha, "once per review"
    copies.move_to("builder", pdirs["builder"], "lead", "act-1", sha)

    assert copies.differs("builder", pdirs["builder"], sha) is None
    assert _files(builder_ws) == ["README.md", "app.py"]
    assert (builder_ws / "app.py").read_text() == "print('hello')\n"
    files, count = copies.files("builder", sha)
    assert count == 2 and set(files) == {"README.md", "app.py"}
    # the leader changing its copy after the review shows as a difference
    (lead_ws / "README.md").write_text("# Tiny, changed after the review\n")
    assert "change(s) since the reviewed version" in copies.differs("lead", pdirs["lead"], sha)
