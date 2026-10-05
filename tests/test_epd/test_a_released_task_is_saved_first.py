"""epd_release: a task is let go only after what only this box has of it is saved (task_save).

The real script agents, run by /bin/sh the way ScriptAgent runs them, on a throwaway origin, its
clone and a task worktree: unpushed commits, uncommitted and untracked files go into a private,
checked archive that restores into a fresh clone; work that is already elsewhere saves nothing; a
save that cannot vouch for its copy fails and removes nothing; and the workflow cleans up only
after a good save.
"""

from __future__ import annotations

import json
import stat
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import yaml

from temper_ai.agent.script_agent import ScriptAgent
from temper_ai.config.helpers import substitute_env_vars
from temper_ai.config.store import ConfigStore
from temper_ai.stage.loader import GraphLoader
from temper_ai.tools.base import ToolResult

ROOT = Path(__file__).resolve().parents[2]
AGENTS = ROOT / "configs" / "epd" / "agents"
WORKFLOW = ROOT / "configs" / "epd" / "workflows" / "epd_release.yaml"

GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "init.defaultBranch=master",
       "-c", "commit.gpgsign=false"]
URL = "https://example.invalid/acme/widget.git"
SLUG = "feat-x"


def git(*args, cwd=None) -> str:
    done = subprocess.run([*GIT, *args], cwd=cwd, capture_output=True, text=True)
    assert done.returncode == 0, f"git {args}: {done.stderr}"
    return done.stdout


def commit(wt: Path, name: str, text: str) -> str:
    (wt / name).write_text(text)
    git("add", "-A", cwd=wt)
    git("commit", "-q", "-m", f"add {name}", cwd=wt)
    return git("rev-parse", "HEAD", cwd=wt).strip()


def served_config(name: str) -> dict:
    """The agent config as the server hands it out (ConfigStore.get runs the env substitution)."""
    return substitute_env_vars(yaml.safe_load((AGENTS / f"{name}.yaml").read_text()))["agent"]


def run_agent(name: str, inputs: dict) -> tuple[str, dict | None, str]:
    """The real agent and the real script, run by /bin/sh as the Bash tool runs it."""
    ctx = MagicMock()
    ctx.run_id, ctx.node_path, ctx.agent_name = "run-t", name, name
    ctx.workspace_path = None

    def execute(_tool, args, **_kw):
        env = {"PATH": "/usr/bin:/bin", "HOME": tempfile.gettempdir(), **args["env"]}
        done = subprocess.run(args["command"], shell=True, capture_output=True, text=True, env=env, timeout=120)
        return ToolResult(success=done.returncode == 0, result=done.stdout, error=done.stderr)

    ctx.tool_executor.execute.side_effect = execute
    result = ScriptAgent(config=served_config(name)).run(inputs, ctx)
    return result.status.value, result.structured_output, str(result.error or "") + str(result.output or "")


@pytest.fixture
def task(tmp_path):
    """An origin with one commit on master, the shared clone, and a claimed task worktree on its
    own branch, laid out as task_claim and task_worktree leave them."""
    origin = tmp_path / "origin.git"
    git("init", "-q", "--bare", str(origin))
    seed = tmp_path / "seed"
    git("clone", "-q", str(origin), str(seed))
    (seed / ".gitignore").write_text("*.log\n")
    (seed / "app.txt").write_text("app v1\n")
    git("add", "-A", cwd=seed)
    git("commit", "-q", "-m", "base", cwd=seed)
    git("push", "-q", "origin", "master", cwd=seed)

    repos = tmp_path / "workspaces" / "repos"
    main = repos / "widget" / "main"
    git("clone", "-q", str(origin), str(main))
    wt = repos / "widget" / "worktrees" / SLUG
    git("worktree", "add", "-q", "-b", SLUG, str(wt), "origin/master", cwd=main)
    claims = repos / "widget" / "claims"
    claims.mkdir(parents=True)
    claim = claims / f"{SLUG}.json"
    claim.write_text(json.dumps({"task_slug": SLUG, "repo_url": URL, "branch": SLUG, "status": "claimed"}))
    return SimpleNamespace(origin=origin, repos=repos, main=main, wt=wt, claim=claim,
                           archive_root=tmp_path / "workspaces" / "archive", tmp=tmp_path)


def inputs(task) -> dict:
    return {"repo_url": URL, "task_name": SLUG, "workspaces_root": str(task.repos)}


def has_branch(task) -> bool:
    done = subprocess.run([*GIT, "rev-parse", "-q", "--verify", f"refs/heads/{SLUG}"], cwd=task.main,
                          capture_output=True, text=True)
    return done.returncode == 0


def test_unsaved_work_is_archived_checked_and_restores_into_a_fresh_clone(task):
    first = commit(task.wt, "one.txt", "first change\n")
    tip = commit(task.wt, "two.txt", "second change\n")
    (task.wt / "app.txt").write_text("app v2, not committed\n")  # a tracked file, changed
    (task.wt / "notes.md").write_text("untracked notes\n")       # untracked, not ignored
    (task.wt / "debug.log").write_text("ignored output\n")       # gitignored: counted, not kept

    status, out, said = run_agent("task_save", inputs(task))
    assert status == "completed", said
    assert out["status"] == "saved", out
    assert (out["commits"], out["changed_files"], out["untracked_files"], out["ignored_files"]) == (2, 1, 1, 1)
    assert out["release_force"] is True and out["tip"] == tip

    archive = Path(out["archive"])
    assert archive.parent == task.archive_root / "widget" and archive.name.startswith(f"{SLUG}.")
    assert sorted(p.name for p in archive.iterdir()) == [
        "branch.bundle", "changes.patch", "manifest.json", "untracked.tar.gz"]
    assert stat.S_IMODE(archive.stat().st_mode) == 0o700
    assert not list(archive.parent.glob("*.partial"))
    # Names and counts only: no file contents in what the run says.
    for text in ("first change", "app v2", "untracked notes", "ignored output"):
        assert text not in said

    manifest = json.loads((archive / "manifest.json").read_text())
    assert manifest["tip"] == tip and manifest["base"] == "master"
    assert [c["sha"] for c in manifest["commits"]] == [tip, first]
    assert manifest["excluded_refs"] == ["refs/remotes/origin/master"]
    assert manifest["changed_files"] == ["app.txt"] and manifest["untracked_files"] == ["notes.md"]
    assert manifest["ignored_files_not_saved"] == 1
    assert manifest["claim"]["task_slug"] == SLUG and manifest["saved_by_run"] == "run-t"
    assert set(manifest["files"]) == {"branch.bundle", "changes.patch", "untracked.tar.gz"}

    # task_save removes nothing.
    assert task.wt.is_dir() and has_branch(task) and task.claim.is_file()
    assert (task.wt / "app.txt").read_text() == "app v2, not committed\n"

    # The archive restores: the branch from the bundle, the changes from the patch, the files from the tar.
    fresh = task.tmp / "fresh"
    git("clone", "-q", str(task.origin), str(fresh))
    git("fetch", "-q", str(archive / "branch.bundle"), f"refs/heads/{SLUG}:refs/heads/restored", cwd=fresh)
    assert git("rev-parse", "restored", cwd=fresh).strip() == tip
    git("checkout", "-q", manifest["worktree_head"], cwd=fresh)
    git("apply", str(archive / "changes.patch"), cwd=fresh)
    assert (fresh / "app.txt").read_text() == "app v2, not committed\n"
    listed = subprocess.run(["tar", "-tzf", str(archive / "untracked.tar.gz")], capture_output=True, text=True,
                            check=True).stdout.split()
    assert listed == ["notes.md"]
    subprocess.run(["tar", "-xzf", str(archive / "untracked.tar.gz"), "-C", str(fresh)], check=True)
    assert (fresh / "notes.md").read_text() == "untracked notes\n"

    # Then cleanup, given force by the save, lets the task go; the archive stays.
    status, gone, said = run_agent("task_cleanup", {**inputs(task), "force": out["release_force"]})
    assert status == "completed", said
    assert (gone["worktree"], gone["branch"], gone["claim"]) == ("removed", "deleted", "released")
    assert not task.wt.exists() and not has_branch(task) and not task.claim.exists()
    assert (archive / "branch.bundle").is_file() and (archive / "manifest.json").is_file()


@pytest.mark.parametrize("where", ["pushed_to_its_own_branch", "merged_into_base", "no_commits"])
def test_work_that_is_already_elsewhere_saves_nothing(task, where):
    if where == "pushed_to_its_own_branch":
        commit(task.wt, "one.txt", "first change\n")
        git("push", "-q", "origin", SLUG, cwd=task.wt)
    elif where == "merged_into_base":
        commit(task.wt, "one.txt", "first change\n")
        git("push", "-q", "origin", "HEAD:master", cwd=task.wt)
    (task.wt / "debug.log").write_text("ignored output\n")  # ignored files do not make a worktree dirty

    status, out, said = run_agent("task_save", inputs(task))
    assert status == "completed", said
    assert out["status"] == "nothing_to_save", out
    assert out["release_force"] is False and out["archive"] == "" and out["ignored_files"] == 1
    assert (out["worktree"], out["branch"], out["claim"]) == ("present", "present", "present")
    assert not task.archive_root.exists()

    # Cleanup without force agrees: its own safe test passes.
    status, gone, said = run_agent("task_cleanup", {**inputs(task), "force": out["release_force"]})
    assert status == "completed", said
    assert (gone["worktree"], gone["branch"], gone["claim"]) == ("removed", "deleted", "released")


def test_a_claim_with_no_worktree_or_branch_saves_nothing(task):
    git("worktree", "remove", str(task.wt), cwd=task.main)
    git("branch", "-q", "-D", SLUG, cwd=task.main)

    status, out, said = run_agent("task_save", inputs(task))
    assert status == "completed", said
    assert out["status"] == "nothing_to_save"
    assert (out["worktree"], out["branch"], out["claim"]) == ("absent", "absent", "present")
    assert not task.archive_root.exists()


@pytest.mark.parametrize("trouble", ["archive_not_writable", "unregistered_worktree_folder", "detached_head_commits"])
def test_a_save_it_cannot_vouch_for_fails_and_removes_nothing(task, trouble):
    if trouble == "archive_not_writable":
        commit(task.wt, "one.txt", "first change\n")
        task.archive_root.parent.mkdir(parents=True, exist_ok=True)
        task.archive_root.write_text("a file where the archive folder would go\n")
        expect = "cannot create archive folder"
    elif trouble == "unregistered_worktree_folder":
        git("worktree", "remove", str(task.wt), cwd=task.main)
        task.wt.mkdir(parents=True)
        (task.wt / "stray.txt").write_text("not in git\n")
        expect = "not a registered worktree"
    else:
        git("checkout", "-q", "--detach", cwd=task.wt)
        commit(task.wt, "one.txt", "made on a detached HEAD\n")
        expect = "detached HEAD with 1 commit(s)"

    status, out, said = run_agent("task_save", inputs(task))
    assert status == "failed", said
    assert expect in said
    assert task.wt.is_dir() and has_branch(task) and task.claim.is_file()
    if task.archive_root.is_dir():
        assert not [p for p in (task.archive_root / "widget").iterdir() if not p.name.endswith(".partial")]


def test_the_release_workflow_cleans_up_only_after_a_good_save():
    flow = yaml.safe_load(WORKFLOW.read_text())["workflow"]
    nodes = {n["name"]: n for n in flow["nodes"]}
    assert list(nodes) == ["save", "cleanup"]
    assert nodes["save"]["agent"] == "task_save"
    cleanup = nodes["cleanup"]
    assert cleanup["agent"] == "task_cleanup" and cleanup["depends_on"] == ["save"]
    # A failed save stops the run before cleanup: it neither runs after a failure nor is a clean-up step.
    assert not cleanup.get("run_after_failure") and "undoes" not in cleanup
    assert cleanup["condition"] == {"source": "save.structured.status", "operator": "in",
                                    "value": ["saved", "nothing_to_save"]}
    # force only when the archive holds what cleanup's own checks would refuse to lose
    assert cleanup["input_map"]["force"] == "save.structured.release_force"
    for node in nodes.values():
        assert node["input_map"]["repo_url"] == "input.repo_url"
        assert node["input_map"]["task_name"] == "input.task_name"
        assert node["input_map"]["workspaces_root"] == "input.workspaces_root"

    store = ConfigStore()
    store.put("epd_release", "workflow", flow)
    for name in ("task_save", "task_cleanup"):
        store.put(name, "agent", served_config(name))
    loaded, config = GraphLoader(store).load_workflow("epd_release")
    assert [n.name for n in loaded] == ["save", "cleanup"] and config.name == "epd_release"
