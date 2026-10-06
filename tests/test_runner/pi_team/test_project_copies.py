"""Each member's own project copy (#38, W1): only the workspace's committed content is copied,
never untracked or ignored files (a ``.env`` stays home); a workspace with uncommitted changes to
tracked files is refused with a plain reason, so the team never works on a version nobody
committed; the copies have no remote, no hooks, and keep their git data outside every member's
folder. Model-free and database-free: these pieces are plain git.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from temper_ai.pi_agent.team_leader import CopyError, CopyFormatError, ProjectCopies
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


@pytest.mark.parametrize("target", ["/etc", "other_member"])
@pytest.mark.parametrize("step", ["ensure", "commit_review", "move_to", "changes"])
def test_sw51_git_is_never_given_a_working_folder_that_is_a_link(tmp_path, target, step):
    """SW-51: a member may swap its working folder for a link -- to /etc, or to another
    member's copy. git would follow it: commit /etc into a review, or reset and clean the other
    member's work. Each git step checks the folder without following links, and refuses."""
    src = ls.project(tmp_path / "proj")
    copies = ProjectCopies(tmp_path / "team", str(src))
    pdirs = _member_dirs(tmp_path / "team", "lead", "victim", "mallory")
    for name in ("lead", "victim") if step == "ensure" else ("lead", "victim", "mallory"):
        copies.ensure(name, pdirs[name])
    victim_ws = ProjectCopies.worktree(pdirs["victim"])
    (victim_ws / "draft.md").write_text("the victim's own work, not committed\n")
    victim_before = {p: (victim_ws / p).read_text() for p in _files(victim_ws)}
    sha = copies.commit_review("lead", pdirs["lead"], "act-1")
    mallory_ws = ProjectCopies.worktree(pdirs["mallory"])
    if mallory_ws.exists():
        shutil.rmtree(mallory_ws)
    os.symlink("/etc" if target == "/etc" else victim_ws, mallory_ws)
    head = copies._head(copies.git_dir("mallory"))

    step_of = {
        "ensure": lambda: copies.ensure("mallory", pdirs["mallory"]),
        "commit_review": lambda: copies.commit_review("mallory", pdirs["mallory"], "act-2"),
        "move_to": lambda: copies.move_to("mallory", pdirs["mallory"], "lead", "act-1", sha),
        "changes": lambda: copies.changes("mallory", pdirs["mallory"]),
    }
    with pytest.raises(CopyError) as refused:
        step_of[step]()
    assert str(refused.value) == (f"the member's working folder {mallory_ws} is a link; Temper "
                                  "does not follow links in a member's folder")
    assert {p: (victim_ws / p).read_text() for p in _files(victim_ws)} == victim_before
    assert copies._head(copies.git_dir("mallory")) == head, "no commit was made"


# --- committed content only, never what backs it (ADR-M4-12, SW-34) --------------------------


SUB_CONTENT = "the submodule's own file: it stays home\n"
LFS_CONTENT = "the large file's real content: it stays home\n"
POINTER = ("version https://git-lfs.github.com/spec/v1\n"
           "oid sha256:4d7a214614ab2935c943f9e0ff69d22eadbb8f32b1258daaa5e2ca24d17e2393\n"
           "size 46\n")


def _with_submodule_and_lfs(tmp_path: Path) -> Path:
    sub = ls.project(tmp_path / "sub", {"inside.txt": SUB_CONTENT})
    src = ls.project(tmp_path / "proj", {"app.py": "print('hello')\n",
                                          ".gitattributes": "*.bin filter=lfs diff=lfs merge=lfs -text\n"})
    ls.git(src, "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(sub),
           "vendor/sub")
    (src / "big.bin").write_text(POINTER)
    ls.git(src, "add", "-A")
    ls.git(src, "commit", "-qm", "a submodule and an LFS file")
    # what LFS keeps beside the repository, and a filter in the workspace's own config that
    # would put it in place: a copy must use neither
    lfs = src / ".git" / "lfs" / "objects" / "4d" / "7a"
    lfs.mkdir(parents=True)
    (lfs / "4d7a214614ab2935c943f9e0ff69d22eadbb8f32b1258daaa5e2ca24d17e2393").write_text(
        LFS_CONTENT)
    ls.git(src, "config", "filter.lfs.smudge", f"cat {lfs}/4d7a*")
    ls.git(src, "config", "filter.lfs.clean", "cat")  # a pointer cleans to itself
    return src


def test_sw34_a_submodule_and_an_lfs_file_reach_a_copy_as_their_ids_never_their_content(
        tmp_path):
    src = _with_submodule_and_lfs(tmp_path)
    assert (src / "vendor" / "sub" / "inside.txt").read_text() == SUB_CONTENT
    copies = ProjectCopies(tmp_path / "team", str(src))
    pdir = _member_dirs(tmp_path / "team", "lead")["lead"]

    head = copies.ensure("lead", pdir)

    ws = ProjectCopies.worktree(pdir)
    assert (ws / "big.bin").read_text() == POINTER, "an LFS file stays its pointer"
    assert not (ws / "vendor" / "sub" / "inside.txt").exists()
    assert "vendor/sub" not in _files(ws)
    files, _count = copies.files("lead", head)
    assert files["vendor/sub"].startswith("commit:"), "the submodule is its commit id only"
    assert not (copies.git_dir("lead") / "lfs").exists()
    assert not (copies.git_dir("lead") / "modules").exists()
    for path in (tmp_path / "team").rglob("*"):
        if path.is_file() and not path.is_symlink():
            data = path.read_bytes()
            assert b"stays home" not in data, path


def test_sw34_no_file_of_a_copy_shares_its_inode_with_the_workspace(tmp_path):
    """git's own transfer, never hard links: a member changing a copy's file can never
    change the workspace's."""
    src = _with_submodule_and_lfs(tmp_path)
    copies = ProjectCopies(tmp_path / "team", str(src))
    for name, pdir in _member_dirs(tmp_path / "team", "lead", "builder").items():
        copies.ensure(name, pdir)

    def inodes(folder: Path) -> set[tuple[int, int]]:
        return {(st.st_dev, st.st_ino) for p in folder.rglob("*")
                if p.is_file() and not p.is_symlink() for st in [p.stat()]}

    shared = inodes(tmp_path / "team") & (inodes(src) | inodes(tmp_path / "sub"))
    assert shared == set()


def test_sw34_a_repository_format_git_can_t_read_is_named_before_anything_is_copied(tmp_path):
    src = ls.project(tmp_path / "proj")
    ls.git(src, "config", "core.repositoryformatversion", "1")
    ls.git(src, "config", "extensions.temperTestUnknown", "true")
    copies = ProjectCopies(tmp_path / "team", str(src))
    pdir = _member_dirs(tmp_path / "team", "lead")["lead"]

    with pytest.raises(CopyFormatError, match="uses a format this git can't read"):
        copies.ensure("lead", pdir)
    assert not copies.record_path.exists()
    assert not copies.git_dir("lead").exists()
