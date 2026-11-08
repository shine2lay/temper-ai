"""Tests for configs/epd/bin/workspace_lifecycle.py and workspace_startup / workspace_cleanup agents."""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml
from jinja2 import BaseLoader
from jinja2.sandbox import SandboxedEnvironment

from temper_ai.agent.script_agent import (
    _INTERP,
    _ends_with_file_filter,
    _extract_file_exprs,
    _recording_undefined,
    _rewrite_interpolations,
    _ValueStash,
)

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "configs" / "epd" / "bin" / "workspace_lifecycle.py"
LEFTOVERS_SCRIPT = ROOT / "configs" / "epd" / "bin" / "leftovers.py"
AGENTS_DIR = ROOT / "configs" / "epd" / "agents"
STARTUP_YAML = AGENTS_DIR / "workspace_startup.yaml"
CLEANUP_YAML = AGENTS_DIR / "workspace_cleanup.yaml"

GIT = [
    "git",
    "-c",
    "user.name=test",
    "-c",
    "user.email=test@temper.ai",
    "-c",
    "init.defaultBranch=master",
    "-c",
    "commit.gpgsign=false",
]


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


lifecycle = _load_module("workspace_lifecycle_under_test", SCRIPT)
leftovers = _load_module("leftovers_for_lifecycle_test", LEFTOVERS_SCRIPT)


def git(*args: str, cwd: Path | None = None) -> str:
    proc = subprocess.run([*GIT, *args], cwd=cwd, capture_output=True, text=True, check=False)
    assert proc.returncode == 0
    return proc.stdout


def make_commit(repo_dir: Path, filename: str, content: str = "hello\n") -> str:
    target = repo_dir / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    git("add", "-A", cwd=repo_dir)
    git("commit", "-q", "-m", f"add {filename}", cwd=repo_dir)
    return git("rev-parse", "HEAD", cwd=repo_dir).strip()


@pytest.fixture
def git_world(tmp_path: Path) -> dict[str, Path]:
    """Create a local bare origin repository and workspaces/repos directory."""
    ws = tmp_path / "workspaces"
    repos = ws / "repos"
    repos.mkdir(parents=True)

    origin_parent = tmp_path / "remotes" / "shine2lay"
    origin_parent.mkdir(parents=True)
    origin = origin_parent / "rollcall.git"
    git("init", "-q", "--bare", str(origin))

    seed = tmp_path / "seed"
    git("clone", "-q", str(origin), str(seed))
    make_commit(seed, "README.md", "# RollCall\n")
    git("push", "-q", "origin", "master", cwd=seed)
    git("symbolic-ref", "HEAD", "refs/heads/master", cwd=origin)

    return {
        "tmp": tmp_path,
        "ws": ws,
        "repos": repos,
        "origin": origin,
        "seed": seed,
    }


def run_cli(*args: str) -> tuple[int, dict]:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    lines = [line for line in proc.stdout.strip().splitlines() if line.strip()]
    assert lines
    return proc.returncode, json.loads(lines[-1])


def render_agent_script(yaml_path: Path, **inputs: Any) -> tuple[str, dict[str, str]]:
    doc = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    agent_cfg = doc["agent"]
    raw_template = agent_cfg["script_template"]
    agent_name = agent_cfg["name"]
    env_exprs = [
        m.group(1).strip()
        for m in _INTERP.finditer(raw_template)
        if not _ends_with_file_filter(m.group(1).strip())
    ]
    stash = _ValueStash(
        agent_name=agent_name,
        workspace_path=None,
        inputs=inputs,
        expressions=env_exprs,
        file_expressions=_extract_file_exprs(raw_template),
    )
    undefined_refs: list[str] = []
    template_text = _rewrite_interpolations(raw_template, agent_name)
    jenv = SandboxedEnvironment(
        loader=BaseLoader(),
        undefined=_recording_undefined(undefined_refs),
    )
    stash.register_filters(jenv, p3_protected=False)
    rendered = jenv.from_string(template_text).render(**inputs)
    return rendered, dict(stash.env)


def test_yaml_templates_pass_sh_syntax_and_avoid_loader_env_vars():
    for yaml_path, expected_name in (
        (STARTUP_YAML, "workspace_startup"),
        (CLEANUP_YAML, "workspace_cleanup"),
    ):
        doc = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        agent = doc["agent"]
        assert agent["name"] == expected_name
        assert agent["type"] == "script"
        raw_script = agent["script_template"]
        # Config loader rewrites ${VAR} with the server's environment at load time; forbid it.
        assert "${" not in raw_script

        raw_check = subprocess.run(
            ["/bin/sh", "-n"],
            input=raw_script,
            capture_output=True,
            text=True,
            check=False,
        )
        assert raw_check.returncode == 0

        rendered, _ = render_agent_script(
            yaml_path,
            product="rollcall",
            run_slug="design-run-1",
            department="design",
            run_id="run-1",
        )
        rendered_check = subprocess.run(
            ["/bin/sh", "-n"],
            input=rendered,
            capture_output=True,
            text=True,
            check=False,
        )
        assert rendered_check.returncode == 0


def test_departments_md_lists_systems_workspace_lifecycle_configs():
    text = (ROOT / "docs" / "departments.md").read_text(encoding="utf-8")
    section = text.split("### systems (", 1)[1].split("\n### ", 1)[0]
    declared_count = int(section.split(")", 1)[0])
    rows = [line for line in section.splitlines() if line.startswith("| `")]
    assert len(rows) == declared_count
    for expected in (
        "`epd/bin/workspace_lifecycle.py`",
        "`epd/agents/workspace_startup.yaml`",
        "`epd/agents/workspace_cleanup.yaml`",
    ):
        assert any(expected in r for r in rows)


def test_startup_by_repo_url_creates_worktree_temper_department_and_excludes(git_world: dict[str, Path]):
    repos = git_world["repos"]
    origin = git_world["origin"]

    code, out = run_cli(
        "startup",
        f"--repo-url={origin}",
        "--task-name=Design App Screen: Hold Gate #1",
        "--department=design",
        "--exclude-dirs=.temper/design,scratch_dir/",
        "--run-id=run-abc-1",
        f"--workspaces-root={repos}",
    )
    assert code == 0, out
    assert out["status"] == "ready"
    assert out["repo"] == "rollcall"
    assert out["task_slug"] == "design-app-screen-hold-gate-1"
    assert out["department"] == "design"
    assert out["clone"] == "fresh"
    assert out["worktree"] == "created"
    assert out["branch"] == "design-app-screen-hold-gate-1"
    assert out["base_branch"] == "master"
    assert out["head"] == out["base_head"]

    wt_path = Path(out["worktree_path"])
    temper_path = Path(out["temper_path"])
    dept_path = Path(out["department_path"])
    claim_path = Path(out["claim_path"])
    main_repo = Path(out["main_repo"])

    assert wt_path == repos / "rollcall" / "worktrees" / "design-app-screen-hold-gate-1"
    assert temper_path == wt_path / ".temper"
    assert dept_path == wt_path / ".temper" / "design"
    assert wt_path.is_dir()
    assert (wt_path / "README.md").is_file()
    assert temper_path.is_dir()
    assert dept_path.is_dir()
    assert claim_path.is_file()

    claim = json.loads(claim_path.read_text(encoding="utf-8"))
    assert claim["status"] == "worktree_ready"
    assert claim["department"] == "design"
    assert claim["run_id"] == "run-abc-1"
    assert claim["worktree_path"] == str(wt_path)
    assert claim["temper_path"] == str(temper_path)
    assert claim["department_path"] == str(dept_path)

    exclude_lines = (main_repo / ".git" / "info" / "exclude").read_text(encoding="utf-8").splitlines()
    assert ".epd/" in exclude_lines
    assert ".temper/design" in exclude_lines
    assert "scratch_dir/" in exclude_lines


def test_startup_by_product_uses_existing_main_origin_and_fallback_slug(git_world: dict[str, Path]):
    repos = git_world["repos"]
    origin = git_world["origin"]
    main_dir = repos / "rollcall" / "main"
    main_dir.parent.mkdir(parents=True, exist_ok=True)
    git("clone", "-q", str(origin), str(main_dir))

    # Omit run_slug and task_name: falls back to <department>-<run_id>.
    code, out = run_cli(
        "startup",
        "--product=rollcall",
        "--department=design",
        "--run-id=run-42",
        f"--workspaces-root={repos}",
    )
    assert code == 0, out
    assert out["status"] == "ready"
    assert out["repo"] == "rollcall"
    assert out["repo_url"] == str(origin)
    assert out["task_slug"] == "design-run-42"
    assert out["clone"] == "reused"
    assert out["worktree"] == "created"
    assert Path(out["department_path"]).is_dir()

    # Omit department as well: falls back to run-<run_id> and department_path is None.
    code2, out2 = run_cli(
        "startup",
        "--product=rollcall",
        "--run-id=run-99",
        f"--workspaces-root={repos}",
    )
    assert code2 == 0, out2
    assert out2["task_slug"] == "run-99"
    assert out2["department"] is None
    assert out2["department_path"] is None
    assert Path(out2["temper_path"]).is_dir()


def test_idempotent_same_run_reuse_and_active_claim_refusal(git_world: dict[str, Path]):
    repos = git_world["repos"]
    origin = git_world["origin"]

    code1, out1 = run_cli(
        "startup",
        f"--repo-url={origin}",
        "--run-slug=arch-check-1",
        "--department=architecture",
        "--run-id=run-owner",
        f"--workspaces-root={repos}",
    )
    assert code1 == 0
    assert out1["worktree"] == "created"

    # Same run_id re-entering idempotently succeeds without force.
    code2, out2 = run_cli(
        "startup",
        "--product=rollcall",
        "--run-slug=arch-check-1",
        "--department=architecture",
        "--run-id=run-owner",
        f"--workspaces-root={repos}",
    )
    assert code2 == 0
    assert out2["worktree"] == "reused"
    assert out2["clone"] == "reused"
    assert out2["worktree_path"] == out1["worktree_path"]

    # Another run_id without force is refused loud and fast.
    code3, out3 = run_cli(
        "startup",
        "--product=rollcall",
        "--run-slug=arch-check-1",
        "--run-id=run-intruder",
        f"--workspaces-root={repos}",
    )
    assert code3 == 1
    assert out3["status"] == "failed"
    assert "already claimed" in out3["error"]
    assert "run-owner" in out3["error"]

    # Passing force=true takes over the claim and reuses the worktree.
    code4, out4 = run_cli(
        "startup",
        "--product=rollcall",
        "--run-slug=arch-check-1",
        "--run-id=run-takeover",
        "--force=true",
        f"--workspaces-root={repos}",
    )
    assert code4 == 0
    assert out4["worktree"] == "reused"
    claim = json.loads(Path(out4["claim_path"]).read_text(encoding="utf-8"))
    assert claim["run_id"] == "run-takeover"


def test_startup_resumes_existing_local_or_pushed_remote_branch_and_rolls_back_claim_on_bad_base(
    git_world: dict[str, Path],
):
    repos = git_world["repos"]
    origin = git_world["origin"]

    # 1. Start a worktree, commit and push a change, then clean it up (removes worktree + local branch).
    code1, out1 = run_cli(
        "startup",
        f"--repo-url={origin}",
        "--run-slug=resumable-slug",
        "--run-id=run-1",
        f"--workspaces-root={repos}",
    )
    assert code1 == 0
    wt = Path(out1["worktree_path"])
    pushed_sha = make_commit(wt, "feature.txt", "shipped work\n")
    git("push", "-q", "origin", "resumable-slug", cwd=wt)

    c_clean, _ = run_cli(
        "cleanup",
        "--product=rollcall",
        "--run-slug=resumable-slug",
        "--run-id=run-1",
        f"--workspaces-root={repos}",
    )
    assert c_clean == 0
    assert not wt.exists()

    # 2. Starting again on the same slug picks up origin/resumable-slug (pushed_branch).
    code2, out2 = run_cli(
        "startup",
        "--product=rollcall",
        "--run-slug=resumable-slug",
        "--run-id=run-2",
        f"--workspaces-root={repos}",
    )
    assert code2 == 0
    assert out2["worktree"] == "pushed_branch"
    assert out2["head"] == pushed_sha

    # 3. If worktree is removed manually while local branch remains, startup re-attaches existing_branch.
    main_dir = Path(out2["main_repo"])
    git("worktree", "remove", "--force", str(wt), cwd=main_dir)
    code3, out3 = run_cli(
        "startup",
        "--product=rollcall",
        "--run-slug=resumable-slug",
        "--run-id=run-2",
        f"--workspaces-root={repos}",
    )
    assert code3 == 0
    assert out3["worktree"] == "existing_branch"
    assert out3["head"] == pushed_sha

    # 4. Nonexistent base_branch fails loud and removes the newly-created claim file.
    code_bad, out_bad = run_cli(
        "startup",
        "--product=rollcall",
        "--run-slug=bad-base-slug",
        "--base-branch=no-such-branch",
        "--run-id=run-bad",
        f"--workspaces-root={repos}",
    )
    assert code_bad == 1
    assert "base branch origin/no-such-branch does not exist" in out_bad["error"]
    assert not (repos / "rollcall" / "claims" / "bad-base-slug.json").exists()


def test_cleanup_refuses_dirty_or_unpushed_without_force_and_cleans_when_safe_or_forced(
    git_world: dict[str, Path],
):
    repos = git_world["repos"]
    origin = git_world["origin"]

    code, started = run_cli(
        "startup",
        f"--repo-url={origin}",
        "--run-slug=design-dirty-check",
        "--department=design",
        "--exclude-dirs=.temper/design",
        "--run-id=run-10",
        f"--workspaces-root={repos}",
    )
    assert code == 0
    wt = Path(started["worktree_path"])
    claim_path = Path(started["claim_path"])

    # Files written inside excluded .temper/design do not count as dirty.
    (Path(started["department_path"]) / "intake.json").write_text("{}\n", encoding="utf-8")

    # Add an untracked non-excluded file -> cleanup with force=false must refuse and remove nothing.
    dirty_file = wt / "untracked.txt"
    dirty_file.write_text("dirty\n", encoding="utf-8")

    c_dirty, res_dirty = run_cli(
        "cleanup",
        "--product=rollcall",
        "--run-slug=design-dirty-check",
        "--force=false",
        f"--workspaces-root={repos}",
    )
    assert c_dirty == 1
    assert res_dirty["status"] == "failed"
    assert "uncommitted change" in res_dirty["error"]
    assert wt.is_dir()
    assert claim_path.is_file()

    # Commit the file locally without pushing -> cleanup with force=false must refuse on unpushed commit.
    make_commit(wt, "untracked.txt", "committed but unpushed\n")
    c_unpushed, res_unpushed = run_cli(
        "cleanup",
        "--product=rollcall",
        "--run-slug=design-dirty-check",
        "--force=false",
        f"--workspaces-root={repos}",
    )
    assert c_unpushed == 1
    assert res_unpushed["status"] == "failed"
    assert "commit(s) not on origin/design-dirty-check or origin/master" in res_unpushed["error"]
    assert wt.is_dir()
    assert claim_path.is_file()

    # Push the branch to origin -> cleanup with force=false now succeeds cleanly!
    git("push", "-q", "origin", "design-dirty-check", cwd=wt)
    c_clean, res_clean = run_cli(
        "cleanup",
        "--product=rollcall",
        "--run-slug=design-dirty-check",
        "--run-id=run-10",
        "--force=false",
        f"--workspaces-root={repos}",
    )
    assert c_clean == 0, res_clean
    assert res_clean["status"] == "clean"
    assert res_clean["repo"] == "rollcall"
    assert res_clean["task_slug"] == "design-dirty-check"
    assert res_clean["worktree"] == "removed"
    assert res_clean["branch"] == "deleted"
    assert res_clean["claim"] == "released"
    assert not wt.exists()
    assert not claim_path.exists()
    released = Path(res_clean["released_claim_path"])
    assert released.is_file()
    released_data = json.loads(released.read_text(encoding="utf-8"))
    assert released_data["status"] == "released"
    assert released_data["department"] == "design"
    assert released_data["released_by_run"] == "run-10"

    # Re-running cleanup when everything is already gone is idempotent.
    c_again, res_again = run_cli(
        "cleanup",
        "--product=rollcall",
        "--run-slug=design-dirty-check",
        f"--workspaces-root={repos}",
    )
    assert c_again == 0
    assert res_again["worktree"] == "absent"
    assert res_again["branch"] == "absent"
    assert res_again["claim"] == "absent"


def test_cleanup_with_force_removes_dirty_and_unpushed_worktree(git_world: dict[str, Path]):
    repos = git_world["repos"]
    origin = git_world["origin"]

    code, started = run_cli(
        "startup",
        f"--repo-url={origin}",
        "--run-slug=force-clean-slug",
        "--department=design",
        "--run-id=run-force",
        f"--workspaces-root={repos}",
    )
    assert code == 0
    wt = Path(started["worktree_path"])
    make_commit(wt, "local_only.txt", "unpushed\n")
    (wt / "dirty.txt").write_text("uncommitted\n", encoding="utf-8")

    c_force, res_force = run_cli(
        "cleanup",
        "--product=rollcall",
        "--run-slug=force-clean-slug",
        "--force=true",
        "--run-id=run-force",
        f"--workspaces-root={repos}",
    )
    assert c_force == 0, res_force
    assert res_force["status"] == "clean"
    assert res_force["worktree"] == "removed"
    assert res_force["branch"] == "deleted"
    assert res_force["claim"] == "released"
    assert not wt.exists()


def test_rendered_yaml_agents_execute_startup_and_cleanup_end_to_end(git_world: dict[str, Path]):
    repos = git_world["repos"]
    origin = git_world["origin"]

    start_script, start_env = render_agent_script(
        STARTUP_YAML,
        repo_url=str(origin),
        product="rollcall",
        run_slug="yaml-e2e-slug",
        department="design",
        exclude_dirs='[".temper/design"]',
        run_id="run-yaml-1",
        workspaces_root=str(repos),
    )
    start_proc = subprocess.run(
        ["/bin/sh", "-c", start_script],
        cwd=str(ROOT),
        env={**os.environ, **start_env},
        capture_output=True,
        text=True,
        check=False,
    )
    assert start_proc.returncode == 0
    start_out = json.loads(start_proc.stdout.strip().splitlines()[-1])
    assert start_out["status"] == "ready"
    assert Path(start_out["department_path"]).is_dir()

    clean_script, clean_env = render_agent_script(
        CLEANUP_YAML,
        product="rollcall",
        run_slug="yaml-e2e-slug",
        department="design",
        run_id="run-yaml-1",
        workspaces_root=str(repos),
    )
    clean_proc = subprocess.run(
        ["/bin/sh", "-c", clean_script],
        cwd=str(ROOT),
        env={**os.environ, **clean_env},
        capture_output=True,
        text=True,
        check=False,
    )
    assert clean_proc.returncode == 0
    clean_out = json.loads(clean_proc.stdout.strip().splitlines()[-1])
    assert clean_out["status"] == "clean"
    assert clean_out["worktree"] == "removed"
    assert clean_out["branch"] == "deleted"
    assert clean_out["claim"] == "released"


def test_leftovers_audit_attributes_department_and_clears_after_cleanup(git_world: dict[str, Path]):
    repos = git_world["repos"]
    origin = git_world["origin"]

    code, started = run_cli(
        "startup",
        f"--repo-url={origin}",
        "--run-slug=design-leftover-slug",
        "--department=design",
        "--run-id=run-finished-1",
        f"--workspaces-root={repos}",
    )
    assert code == 0

    class FakeRuns:
        server = "http://fake-server"

        def get(self, run_id: str) -> dict:
            return {
                "ok": {
                    "status": "completed",
                    "workflow_name": "design_app_screen_v1",
                    "end_time": "2026-11-08T01:00:00Z",
                }
            }

    class FakeStandee:
        via = "fake"

        def ls(self) -> list[dict]:
            return []

        def unattached_volumes(self) -> tuple[int, str]:
            return 0, "no orphans"

    report_before = leftovers.audit(
        repos, FakeRuns(), FakeStandee(), dt.datetime.now(dt.UTC)
    )
    assert report_before["counts"]["leftover"] == 3
    for kind in ("claim", "worktree", "branch"):
        matches = [
            i
            for i in report_before["items"]
            if i["kind"] == kind and i["name"] == "design-leftover-slug"
        ]
        assert len(matches) == 1
        assert matches[0]["class"] == "leftover"
        assert matches[0]["fix_owner"] == "systems"
        assert matches[0]["department"] == "design"
        assert matches[0]["evidence"]["department"] == "design"

    c_clean, _ = run_cli(
        "cleanup",
        "--product=rollcall",
        "--run-slug=design-leftover-slug",
        "--run-id=run-finished-1",
        f"--workspaces-root={repos}",
    )
    assert c_clean == 0

    report_after = leftovers.audit(
        repos, FakeRuns(), FakeStandee(), dt.datetime.now(dt.UTC)
    )
    assert report_after["items"] == []
    assert report_after["counts"]["leftover"] == 0


@pytest.mark.parametrize(
    ("cli_args", "expected_error"),
    [
        ([], "missing subcommand"),
        (["startup", "--run-slug=s1"], "either repo_url or product is required"),
        (
            ["startup", "--product=../bad", "--run-slug=s1"],
            "invalid product",
        ),
        (
            ["startup", "--product=unknownprod", "--run-slug=s1"],
            "unknown product 'unknownprod'",
        ),
        (
            ["startup", "--repo-url=not-a-valid-url", "--run-slug=s1"],
            "could not parse owner/repo from repo_url",
        ),
        (
            [
                "startup",
                "--product=rollcall",
                "--repo-url=https://github.com/shine2lay/inkflow.git",
                "--run-slug=s1",
            ],
            "does not match repo",
        ),
        (
            ["startup", "--repo-url=https://github.com/shine2lay/rollcall.git"],
            "missing task identifier",
        ),
        (
            [
                "startup",
                "--repo-url=https://github.com/shine2lay/rollcall.git",
                "--run-slug=../escape",
            ],
            "invalid run_slug",
        ),
        (
            [
                "startup",
                "--repo-url=https://github.com/shine2lay/rollcall.git",
                "--run-slug=---",
            ],
            "empty slug",
        ),
        (
            [
                "startup",
                "--repo-url=https://github.com/shine2lay/rollcall.git",
                "--run-slug=s1",
                "--department=Bad/Dept",
            ],
            "invalid department",
        ),
        (
            [
                "startup",
                "--repo-url=https://github.com/shine2lay/rollcall.git",
                "--run-slug=s1",
                "--base-branch=bad..branch",
            ],
            "invalid base_branch",
        ),
        (
            [
                "startup",
                "--repo-url=https://github.com/shine2lay/rollcall.git",
                "--run-slug=s1",
                "--exclude-dirs=../outside",
            ],
            "invalid exclude_dirs entry",
        ),
        (
            [
                "startup",
                "--repo-url=https://github.com/shine2lay/rollcall.git",
                "--run-slug=s1",
                "--exclude-dirs=/abs/path",
            ],
            "must be a relative path",
        ),
        (
            [
                "startup",
                "--repo-url=https://github.com/shine2lay/rollcall.git",
                "--run-slug=s1",
                "--force=maybe",
            ],
            "invalid force value",
        ),
    ],
)
def test_fail_fast_validation_on_bad_inputs(
    tmp_path: Path, cli_args: list[str], expected_error: str
):
    full_args = (
        [*cli_args, f"--workspaces-root={tmp_path / 'repos'}"]
        if cli_args
        else cli_args
    )
    code, out = run_cli(*full_args)
    assert code == 1
    assert out["status"] == "failed"
    assert expected_error in out["error"]
