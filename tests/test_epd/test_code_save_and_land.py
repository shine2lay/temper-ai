"""Tests for `code_save` and `code_land` (rm-f63411b6, rm-ee86289c, rm-5e2678ef, rm-1b9fb527, rm-78845199).

Uses `LocalGitHubHarness` (external bare-git + `git-http-backend` + GitHub REST v3 server
on `127.0.0.1:0`) with zero mock branches or test flags in production scripts (Rule 29).
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import jinja2
import pytest
import yaml
from fastapi.testclient import TestClient

from tests.test_epd.code_land_harness import GIT_BIN, LocalGitHubHarness, git_raw

REPO_ROOT = Path(__file__).resolve().parents[2]
BIN_DIR = REPO_ROOT / "configs" / "epd" / "bin"
if str(BIN_DIR) not in sys.path:
    sys.path.insert(0, str(BIN_DIR))


def _load_bin_module(name: str):
    path = BIN_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


code_checkout = _load_bin_module("code_checkout")
code_save = _load_bin_module("code_save")
code_land_github = _load_bin_module("code_land_github")
code_land = _load_bin_module("code_land")
code_land_pause = _load_bin_module("code_land_pause")


def _shquote(val: Any) -> str:
    s = str(val)
    return "'" + s.replace("'", "'\"'\"'") + "'"


def _render_and_run_agent_yaml(
    yaml_rel: str, inputs: dict[str, Any], *, env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    cfg = yaml.safe_load((REPO_ROOT / yaml_rel).read_text(encoding="utf-8"))
    agent_cfg = cfg["agent"] if "agent" in cfg else cfg
    merged_inputs: dict[str, Any] = {}
    for k, spec in (agent_cfg.get("inputs") or {}).items():
        if isinstance(spec, dict) and "default" in spec:
            merged_inputs[k] = spec["default"]
    merged_inputs.update(inputs)
    tmpl = jinja2.Environment().from_string(agent_cfg["script_template"])
    quoted = {k: _shquote(v) if v is not None else "None" for k, v in merged_inputs.items()}
    rendered = tmpl.render(**quoted)
    return subprocess.run(
        ["/bin/sh", "-c", rendered],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def harness(tmp_path: Path):
    h = LocalGitHubHarness(tmp_path)
    try:
        yield h
    finally:
        h.close()


def _checkout_feature_branch(
    harness: LocalGitHubHarness, tmp_path: Path, branch: str = "feat/demo"
) -> Path:
    root = tmp_path / f"container-checkout-{branch.replace('/', '_')}"
    out = code_checkout.checkout_code(
        repo_url=f"https://github.com/{harness.repo_slug}.git",
        base_branch="main",
        branch=branch,
        root=str(root),
        env=harness.env(),
    )
    return Path(out["path"])


# ---------------------------------------------------------------------------
# 1. code_save stage tests
# ---------------------------------------------------------------------------


class TestCodeSave:
    def test_dirty_worktree_commits_pushes_and_persists_no_token(
        self, harness: LocalGitHubHarness, tmp_path: Path
    ):
        work_dir = _checkout_feature_branch(harness, tmp_path, "feat/save-dirty")
        (work_dir / "feature.py").write_text("VALUE = 42\n", encoding="utf-8")

        proc = _render_and_run_agent_yaml(
            "configs/epd/agents/code_save.yaml",
            {"work_dir": str(work_dir), "message": "feat: add value"},
            env=harness.env(),
        )
        assert proc.returncode == 0
        data = json.loads(proc.stdout)
        assert data["pushed"] is True
        assert data["clean"] is False
        assert data["branch"] == "feat/save-dirty"
        assert len(data["sha"]) == 40
        assert harness.branch_sha("feat/save-dirty") == data["sha"]

        git_cfg = (work_dir / ".git" / "config").read_text(encoding="utf-8")
        assert "ghs_" not in git_cfg
        assert "x-access-token" not in git_cfg
        assert harness.run_token not in proc.stdout + proc.stderr

    def test_clean_worktree_noop_unless_allow_empty(
        self, harness: LocalGitHubHarness, tmp_path: Path
    ):
        work_dir = _checkout_feature_branch(harness, tmp_path, "feat/save-clean")
        before_sha = git_raw(work_dir, "rev-parse", "HEAD")

        noop = code_save.save_code(
            work_dir=str(work_dir),
            message="chore: nothing changed",
            allow_empty="false",
            env=harness.env(),
        )
        assert noop == {
            "pushed": False,
            "branch": "feat/save-clean",
            "sha": before_sha,
            "clean": True,
        }
        assert harness.branch_sha("feat/save-clean") is None

        empty_push = code_save.save_code(
            work_dir=str(work_dir),
            message="chore: empty marker",
            allow_empty="true",
            env=harness.env(),
        )
        assert empty_push["pushed"] is True
        assert empty_push["clean"] is True
        assert empty_push["sha"] != before_sha
        assert harness.branch_sha("feat/save-clean") == empty_push["sha"]

    def test_files_subset_stages_only_selected_and_rejects_traversal(
        self, harness: LocalGitHubHarness, tmp_path: Path
    ):
        work_dir = _checkout_feature_branch(harness, tmp_path, "feat/subset")
        (work_dir / "keep.txt").write_text("picked\n", encoding="utf-8")
        (work_dir / "leave.txt").write_text("untracked\n", encoding="utf-8")

        res = code_save.save_code(
            work_dir=str(work_dir),
            message="feat: stage subset",
            files=json.dumps(["keep.txt"]),
            env=harness.env(),
        )
        assert res["pushed"] is True
        committed_files = subprocess.run(
            [GIT_BIN, "--git-dir", str(harness.bare_repo), "diff-tree", "--no-commit-id", "--name-only", "-r", res["sha"]],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.splitlines()
        assert committed_files == ["keep.txt"]
        assert (work_dir / "leave.txt").exists()

        for bad in (["../outside.txt"], ["/etc/passwd"], [".git/config"]):
            with pytest.raises(code_save.CodeSaveError):
                code_save.save_code(
                    work_dir=str(work_dir),
                    message="bad files",
                    files=bad,
                    env=harness.env(),
                )

    @pytest.mark.parametrize(
        "rel_path,content",
        [
            (".env", "DB_PASS=hunter2\n"),
            (".env.production", "API_KEY=xyz\n"),
            ("certs/server.pem", "cert\n"),
            ("keys/private.key", "key\n"),
            ("config/credentials.json", "{}\n"),
            ("src/leaked.py", "TOKEN = 'ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456'\n"),
            ("src/keyblock.py", "K = '-----BEGIN RSA PRIVATE KEY-----'\n"),
        ],
    )
    def test_secret_refusal_unstages_and_never_commits_or_pushes(
        self,
        harness: LocalGitHubHarness,
        tmp_path: Path,
        rel_path: str,
        content: str,
    ):
        work_dir = _checkout_feature_branch(harness, tmp_path, "feat/secret-guard")
        head_before = git_raw(work_dir, "rev-parse", "HEAD")
        target = work_dir / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

        with pytest.raises(code_save.CodeSaveError, match="refusing to commit"):
            code_save.save_code(
                work_dir=str(work_dir),
                message="accidental secret",
                env=harness.env(),
            )
        assert git_raw(work_dir, "rev-parse", "HEAD") == head_before
        assert harness.branch_sha("feat/secret-guard") is None
        staged_after = git_raw(work_dir, "diff", "--cached", "--name-only")
        assert staged_after == ""

    def test_rejects_forbidden_work_dirs_protected_branches_and_redacts_tokens(
        self, harness: LocalGitHubHarness, tmp_path: Path
    ):
        ws = tmp_path / "ws_forbidden"
        ws.mkdir()
        env = harness.env(workspace_dir=ws)

        for bad_dir in ("/home/shinelay/temper-ai", "/app/workspaces/r1", str(ws / "repo")):
            with pytest.raises(code_save.CodeSaveError):
                code_save.save_code(work_dir=bad_dir, message="x", env=env)

        work_dir = _checkout_feature_branch(harness, tmp_path, "feat/redact")
        with pytest.raises(code_save.CodeSaveError, match="protected branch"):
            code_save.save_code(
                work_dir=str(work_dir), message="x", branch="main", env=env
            )

        (work_dir / "a.txt").write_text("hello\n", encoding="utf-8")
        leaked_ghs = "ghs_superSecretInstallationToken987654321"
        harness.fail_token_status = 500
        harness.fail_token_message = f"upstream leaked {leaked_ghs} and {harness.run_token}"
        with pytest.raises(code_save.CodeSaveError) as exc_info:
            code_save.save_code(work_dir=str(work_dir), message="feat: a", env=env)
        err_text = str(exc_info.value)
        assert leaked_ghs not in err_text
        assert harness.run_token not in err_text
        assert "[REDACTED]" in err_text


# ---------------------------------------------------------------------------
# 2. code_land stage: require_checks, mode=pr/merge, auto-resolve & conflicts
# ---------------------------------------------------------------------------


class TestCodeLandStage:
    def test_require_checks_waits_for_pending_dedupes_reruns_and_merges(
        self, harness: LocalGitHubHarness, tmp_path: Path
    ):
        work_dir = _checkout_feature_branch(harness, tmp_path, "feat/checks-wait")
        (work_dir / "app.py").write_text("x = 1\n", encoding="utf-8")
        saved = code_save.save_code(
            work_dir=str(work_dir), message="feat: add app", env=harness.env()
        )
        sha = saved["sha"]

        harness.set_check_sequence(
            sha,
            [
                [
                    {"id": 10, "name": "unit", "status": "in_progress", "conclusion": None, "app": {"id": 1}},
                ],
                [
                    # Older failed attempt id=10 superseded by rerun id=11!
                    {"id": 10, "name": "unit", "status": "completed", "conclusion": "failure", "app": {"id": 1}},
                    {"id": 11, "name": "unit", "status": "completed", "conclusion": "success", "app": {"id": 1}},
                    {"id": 12, "name": "docs-optional", "status": "completed", "conclusion": "skipped", "app": {"id": 1}},
                ],
            ],
        )

        res = code_land.land_code(
            work_dir=str(work_dir),
            branch="feat/checks-wait",
            base="main",
            mode="pr",
            require_checks="true",
            poll_interval_s="0.02",
            checks_appear_timeout_s="0.2",
            env=harness.env(),
        )
        assert res["action"] == "merged"
        assert res["merged"] is True
        assert res["status"] == "merged"
        assert res["pr_number"] == 1
        assert res["checks"]["state"] == "passed"
        assert {r["name"]: r["conclusion"] for r in res["checks"]["runs"]} == {
            "unit": "success",
            "docs-optional": "skipped",
        }
        assert harness.check_polls_by_sha[sha] >= 2

    def test_require_checks_failing_check_pauses_and_never_merges(
        self, harness: LocalGitHubHarness, tmp_path: Path
    ):
        sha = harness.commit_on_remote("feat/red-ci", {"f.py": "bad = True\n"})
        harness.set_checks(
            sha,
            [
                {
                    "id": 1,
                    "name": "pytest-suite",
                    "status": "completed",
                    "conclusion": "failure",
                    "html_url": "https://github.com/acme/widget/runs/1",
                    "app": {"id": 1},
                }
            ],
        )

        res = code_land.land_code(
            repo=harness.repo_slug,
            branch="feat/red-ci",
            base="main",
            mode="pr",
            require_checks="true",
            poll_interval_s="0.02",
            checks_appear_timeout_s="0.1",
            env=harness.env(),
        )
        assert res["action"] == "pause"
        assert res["merged"] is False
        assert res["status"] == "paused"
        assert res["checks"]["state"] == "failed"
        assert "pytest-suite" in res["question"]
        assert harness.merge_calls == []

    def test_zero_checks_blocks_when_required_and_merges_when_disabled(
        self, harness: LocalGitHubHarness
    ):
        sha = harness.commit_on_remote("feat/no-ci", {"note.md": "docs\n"})

        blocked = code_land.land_code(
            repo=harness.repo_slug,
            branch="feat/no-ci",
            base="main",
            mode="pr",
            require_checks="true",
            poll_interval_s="0.02",
            checks_appear_timeout_s="0.05",
            env=harness.env(),
        )
        assert blocked["action"] == "pause"
        assert blocked["merged"] is False
        assert blocked["status"] == "blocked"
        assert blocked["checks"] == {"state": "none", "runs": []}
        assert "no checks reported" in blocked["question"]
        assert sha in blocked["question"]
        assert harness.merge_calls == []

        merged = code_land.land_code(
            repo=harness.repo_slug,
            branch="feat/no-ci",
            base="main",
            mode="pr",
            require_checks="false",
            poll_interval_s="0.02",
            checks_appear_timeout_s="0.05",
            env=harness.env(),
        )
        assert merged["action"] == "merged"
        assert merged["merged"] is True
        assert merged["checks"]["state"] == "none"
        assert len(harness.merge_calls) == 1

    def test_mode_merge_enforces_require_checks_without_opening_pr(
        self, harness: LocalGitHubHarness
    ):
        sha = harness.commit_on_remote("feat/direct", {"direct.txt": "ok\n"})

        # 0 checks -> pauses in mode=merge when require_checks=true
        paused = code_land.land_code(
            repo=harness.repo_slug,
            branch="feat/direct",
            base="main",
            mode="merge",
            require_checks="true",
            poll_interval_s="0.02",
            checks_appear_timeout_s="0.05",
            env=harness.env(),
        )
        assert paused["action"] == "pause"
        assert paused["merged"] is False
        assert paused["pr_number"] is None
        assert harness.prs == {}
        assert harness.merge_calls == []

        # Green check -> merges directly without creating a PR
        harness.set_checks(
            sha,
            [{"id": 1, "name": "ci", "status": "completed", "conclusion": "success", "app": {"id": 1}}],
        )
        merged = code_land.land_code(
            repo=harness.repo_slug,
            branch="feat/direct",
            base="main",
            mode="merge",
            require_checks="true",
            poll_interval_s="0.02",
            checks_appear_timeout_s="0.1",
            env=harness.env(),
        )
        assert merged["action"] == "merged"
        assert merged["merged"] is True
        assert merged["pr_number"] is None
        assert merged["pr_url"] == ""
        assert merged["checks"]["state"] == "passed"
        assert harness.prs == {}
        assert len(harness.merge_calls) == 1
        assert harness.merge_calls[0]["mode"] == "merge"

    def test_auto_resolve_clean_conflict_invalidates_prior_green_checks(
        self, harness: LocalGitHubHarness, tmp_path: Path
    ):
        """rm-5e2678ef + rm-1b9fb527: auto-resolve pushes new_sha and MUST re-verify checks on new_sha."""
        work_dir = _checkout_feature_branch(harness, tmp_path, "feat/auto-resolve")
        (work_dir / "feature_only.py").write_text("FEATURE = True\n", encoding="utf-8")
        pre_sha = code_save.save_code(
            work_dir=str(work_dir), message="feat: isolated file", env=harness.env()
        )["sha"]
        # Pre-resolve commit is already green!
        harness.set_checks(
            pre_sha,
            [{"id": 1, "name": "ci", "status": "completed", "conclusion": "success", "app": {"id": 1}}],
        )

        # Advance main on a disjoint file and instruct GitHub PR view to report behind/dirty until merged
        harness.commit_on_remote("main", {"README.md": "line 1\nline 2\nmain update\n"}, message="docs: main")
        harness.force_behind_when_diverged = True

        # Any newly pushed auto-resolve SHA starts `in_progress` on poll 1, then turns `success` on poll 2!
        def checks_for_new_sha(sha: str, poll_num: int) -> list[dict[str, Any]]:
            assert sha != pre_sha, "must query check-runs on post-resolve SHA"
            if poll_num == 1:
                return [{"id": 20, "name": "ci", "status": "in_progress", "conclusion": None, "app": {"id": 1}}]
            return [{"id": 20, "name": "ci", "status": "completed", "conclusion": "success", "app": {"id": 1}}]

        harness.set_default_checks_callback(checks_for_new_sha)

        res = code_land.land_code(
            work_dir=str(work_dir),
            branch="feat/auto-resolve",
            base="main",
            mode="pr",
            require_checks="true",
            poll_interval_s="0.02",
            checks_appear_timeout_s="0.2",
            env=harness.env(),
        )
        post_sha = harness.branch_sha("feat/auto-resolve")
        assert post_sha is not None and post_sha != pre_sha
        assert res["action"] == "merged"
        assert res["merged"] is True
        assert res["auto_resolved"] is True
        assert res["resolved_files"] == ["README.md"]
        assert res["checks"]["state"] == "passed"
        # Proves pre_sha green was NOT reused: post_sha was polled until pending -> passed!
        assert harness.check_polls_by_sha.get(post_sha, 0) >= 2
        assert harness.merge_calls[-1]["head_sha"] == post_sha

    def test_overlapping_conflict_aborts_cleanly_and_pauses_naming_files(
        self, harness: LocalGitHubHarness, tmp_path: Path
    ):
        work_dir = _checkout_feature_branch(harness, tmp_path, "feat/true-conflict")
        (work_dir / "shared.txt").write_text("branch edit\nbeta\ngamma\n", encoding="utf-8")
        branch_sha = code_save.save_code(
            work_dir=str(work_dir), message="feat: edit shared", env=harness.env()
        )["sha"]
        harness.set_checks(
            branch_sha,
            [{"id": 1, "name": "ci", "status": "completed", "conclusion": "success", "app": {"id": 1}}],
        )

        # Conflicting edit on same line of shared.txt on main
        harness.commit_on_remote("main", {"shared.txt": "main conflicting edit\nbeta\ngamma\n"})

        res = code_land.land_code(
            work_dir=str(work_dir),
            branch="feat/true-conflict",
            base="main",
            mode="pr",
            require_checks="true",
            poll_interval_s="0.02",
            checks_appear_timeout_s="0.1",
            env=harness.env(),
        )
        assert res["action"] == "pause"
        assert res["merged"] is False
        assert res["status"] == "paused"
        assert res["conflicting_files"] == ["shared.txt"]
        assert "shared.txt" in res["question"]
        # Branch on remote and local work_dir must remain untouched with zero conflict markers!
        assert harness.branch_sha("feat/true-conflict") == branch_sha
        assert "<<<<<<<" not in (work_dir / "shared.txt").read_text(encoding="utf-8")
        assert git_raw(work_dir, "status", "--porcelain") == ""


# ---------------------------------------------------------------------------
# 3. Full workflow, StageNode pipeline, and dead-box / wiped-work_dir resume
# ---------------------------------------------------------------------------


@pytest.fixture
def temper_runtime(tmp_path: Path, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch):
    from temper_ai.api.app_state import AppState
    from temper_ai.api.routes import _state, init_app_state
    from temper_ai.cli.check import _FileConfigs
    from temper_ai.config import ConfigStore
    from temper_ai.database import init_database, reset_database
    from temper_ai.memory import InMemoryStore, MemoryService
    from temper_ai.server import app
    from temper_ai.stage.loader import GraphLoader
    from tests.conftest import TEST_DATABASE_URL

    url = request.node.stash.get(TEST_DATABASE_URL, "")
    if url.startswith("sqlite") or not url:
        db_file = tmp_path / "temper_test.sqlite"
        url = f"sqlite:///{db_file}"
        reset_database()
        request.node.stash[TEST_DATABASE_URL] = url
        init_database(url)
    monkeypatch.setenv("TEMPER_DATABASE_URL", url)

    file_configs = _FileConfigs(REPO_ROOT / "configs")
    loader = GraphLoader(file_configs)  # type: ignore[arg-type]

    try:
        prev_state = _state()
    except RuntimeError:
        prev_state = None

    state = AppState(
        config_store=ConfigStore(),
        graph_loader=loader,
        llm_providers={},
        memory_service=MemoryService(InMemoryStore()),
    )
    init_app_state(state)
    client = TestClient(app)
    try:
        yield file_configs, client
    finally:
        if prev_state is not None:
            init_app_state(prev_state)
        if url.startswith("sqlite"):
            reset_database()


def _make_box_context(
    exec_id: str,
    store: Any,
    harness: LocalGitHubHarness,
    *,
    park_at_gates: bool,
    cancel_event: threading.Event | None = None,
):
    from temper_ai.api.run_tokens import open_for_run
    from temper_ai.checkpoint.service import CheckpointService
    from temper_ai.observability.event_recorder import EventRecorder
    from temper_ai.shared.types import ExecutionContext
    from temper_ai.stage.loader import GraphLoader
    from temper_ai.tools import TOOL_CLASSES, ToolExecutor

    rk = open_for_run(exec_id, "code_land")
    if rk:
        harness.valid_run_tokens.add(rk)

    tool_exec = ToolExecutor()
    tool_exec.register_tools({"Bash": TOOL_CLASSES["Bash"]()})
    cp = CheckpointService(exec_id)
    ctx = ExecutionContext(
        run_id=exec_id,
        workflow_name="code_land",
        node_path="",
        agent_name="",
        event_recorder=EventRecorder(exec_id),
        tool_executor=tool_exec,
        checkpoint_service=cp,
        graph_loader=GraphLoader(store),  # type: ignore[arg-type]
        cancel_event=cancel_event,
        park_at_gates=park_at_gates,
    )
    return ctx, cp, tool_exec


class TestCodeLandWorkflowAndDeadBoxResume:
    def test_pi_park_at_gates_wipes_work_dir_auto_resolves_and_resumes_statelessly(
        self,
        harness: LocalGitHubHarness,
        temper_runtime: tuple[Any, TestClient],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """rm-78845199 Case A: Pi workflow (`park_at_gates=True`) exits box at gate;
        `work_dir` is wiped; fresh box resumes, clones shallowly to auto-resolve new base
        movement, re-verifies checks on new merge SHA, and merges."""
        from temper_ai.api.run_tokens import close_for_run
        from temper_ai.shared.types import Status
        from temper_ai.stage.executor import (
            RunParked,
            execute_graph,
            execute_graph_with_state,
        )
        from temper_ai.stage.input_defaults import fill_input_defaults
        from temper_ai.stage.loader import GraphLoader
        from temper_ai.stage.pi_workflows import is_pi_workflow, pi_loop_problems

        store, client = temper_runtime
        for k, v in harness.env().items():
            monkeypatch.setenv(k, v)

        # Verify code_land's loop configuration satisfies Pi workflow rules (`on_max_loops: fail`)
        loader = GraphLoader(store)
        nodes1, wf_cfg = loader.load_workflow("code_land")
        store.configs[("agent", "_test_pi_step")] = {
            "name": "_test_pi_step",
            "type": "pi",
            "prompt_template": "ship it",
        }
        store.configs[("workflow", "_test_pi_wrapper")] = {
            "name": "_test_pi_wrapper",
            "nodes": [
                {"name": "coder", "type": "agent", "agent": "_test_pi_step"},
                {
                    "name": "land",
                    "type": "stage",
                    "ref": "code_land",
                    "depends_on": ["coder"],
                    "input_map": {"branch": "main"},
                },
            ],
        }
        try:
            pi_nodes, _ = loader.load_workflow("_test_pi_wrapper")
            assert is_pi_workflow(pi_nodes) is True
            assert pi_loop_problems(pi_nodes) == []
        finally:
            store.configs.pop(("workflow", "_test_pi_wrapper"), None)
            store.configs.pop(("agent", "_test_pi_step"), None)

        work_dir = _checkout_feature_branch(harness, tmp_path, "feat/parked-overnight")
        (work_dir / "service.py").write_text("PORT = 8080\n", encoding="utf-8")
        saved = code_save.save_code(
            work_dir=str(work_dir), message="feat: add service", env=harness.env()
        )
        sha1 = saved["sha"]
        harness.set_checks(
            sha1,
            [{"id": 1, "name": "ci", "status": "completed", "conclusion": "failure", "app": {"id": 1}}],
        )

        exec_id = "exec-pi-parked-128"
        wf_inputs = fill_input_defaults(
            wf_cfg.inputs,
            {
                "work_dir": str(work_dir),
                "branch": "feat/parked-overnight",
                "base": "main",
                "mode": "pr",
                "require_checks": "true",
                "poll_interval_s": "0.02",
                "checks_appear_timeout_s": "0.1",
            },
        )

        # Round 1 (Box 1): fails CI check -> hits code_land_pause -> parks & exits box!
        ctx1, _cp1, tool_exec1 = _make_box_context(
            exec_id, store, harness, park_at_gates=True
        )
        try:
            with pytest.raises(RunParked) as parked_exc:
                execute_graph(
                    nodes1,
                    wf_inputs,
                    ctx1,
                    graph_name="code_land",
                    is_workflow=True,
                    workflow_outputs=wf_cfg.outputs,
                )
        finally:
            tool_exec1.shutdown()

        # Verify unanswered overnight state: nothing merged, PR open, gate waiting via API
        assert harness.merge_calls == []
        gates_resp = client.get(f"/api/runs/{exec_id}/gates")
        assert gates_resp.status_code == 200
        gates = gates_resp.json()["gates"]
        assert len(gates) == 1
        assert gates[0]["status"] == "waiting"
        assert gates[0]["event_id"] == parked_exc.value.event_id
        assert "ci" in gates[0]["questions"][0]["question"]

        # Simulate Box 1 termination wiping `/tmp` container work_dir completely!
        shutil.rmtree(work_dir)
        assert not work_dir.exists()

        # Overnight: human pushes fix on branch AND main moves on a disjoint file
        # (forcing shallow-clone auto-resolve in Box 2 without work_dir!)
        fix_sha = harness.commit_on_remote(
            "feat/parked-overnight", {"service.py": "PORT = 9090\n"}, message="fix: port"
        )
        harness.commit_on_remote(
            "main", {"README.md": "line 1\nline 2\novernight main commit\n"}, message="docs: main"
        )
        harness.force_behind_when_diverged = True
        harness.set_default_checks_callback(
            lambda sha, poll: (
                [{"id": 50, "name": "ci", "status": "in_progress", "conclusion": None, "app": {"id": 1}}]
                if poll == 1
                else [{"id": 50, "name": "ci", "status": "completed", "conclusion": "success", "app": {"id": 1}}]
            )
        )

        # Approve gate via API
        approve_resp = client.post(
            f"/api/runs/{exec_id}/approve/code_land_pause",
            json={
                "response": "CI fixed, retry land",
                "event_id": gates[0]["event_id"],
                "by": "owner",
            },
        )
        assert approve_resp.status_code == 200
        assert approve_resp.json()["status"] == "approved"

        # Round 2 (Fresh Box 2, work_dir STILL gone!): reconstruct checkpoint & resume
        nodes2, wf_cfg2 = loader.load_workflow("code_land")
        ctx2, cp2, tool_exec2 = _make_box_context(
            exec_id, store, harness, park_at_gates=True
        )
        try:
            restored = cp2.reconstruct()
            result = execute_graph_with_state(
                nodes2,
                wf_inputs,
                ctx2,
                graph_name="code_land",
                is_workflow=True,
                initial_outputs=restored,
                workflow_outputs=wf_cfg2.outputs,
            )
        finally:
            tool_exec2.shutdown()
            close_for_run(exec_id)

        assert not work_dir.exists(), "must not recreate stale Box 1 path"
        assert result.status == Status.COMPLETED
        out = result.structured_output
        assert out is not None
        assert out["merged"] is True
        assert out["status"] == "merged"
        assert out["pr_number"] == 1
        assert out["auto_resolved"] is True
        assert out["resolved_files"] == ["README.md"]
        assert out["checks"]["state"] == "passed"
        post_resolve_sha = harness.branch_sha("feat/parked-overnight")
        assert post_resolve_sha != fix_sha
        assert harness.check_polls_by_sha.get(post_resolve_sha, 0) >= 2

    def test_dead_non_pi_box_holds_unanswered_gate_then_approves_and_resumes_without_work_dir(
        self,
        harness: LocalGitHubHarness,
        temper_runtime: tuple[Any, TestClient],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """rm-78845199 Case B: Non-Pi workflow (`park_at_gates=False`) waits at gate with no
        timeout; container dies (`cancel_event`) and `work_dir` is wiped; unanswered state holds
        cleanly; later `approve` sets `needs_resume=True` and fresh box resumes to merged."""
        from temper_ai.api.run_tokens import close_for_run
        from temper_ai.shared.types import Status
        from temper_ai.stage.executor import execute_graph, execute_graph_with_state
        from temper_ai.stage.input_defaults import fill_input_defaults
        from temper_ai.stage.loader import GraphLoader

        store, client = temper_runtime
        for k, v in harness.env().items():
            monkeypatch.setenv(k, v)

        work_dir = _checkout_feature_branch(harness, tmp_path, "feat/dead-box")
        (work_dir / "shared.txt").write_text("branch conflicting line\nbeta\ngamma\n", encoding="utf-8")
        branch_sha = code_save.save_code(
            work_dir=str(work_dir), message="feat: touch shared", env=harness.env()
        )["sha"]
        harness.set_checks(
            branch_sha,
            [{"id": 1, "name": "ci", "status": "completed", "conclusion": "success", "app": {"id": 1}}],
        )
        harness.commit_on_remote("main", {"shared.txt": "main conflicting line\nbeta\ngamma\n"})

        exec_id = "exec-dead-box-128"
        loader = GraphLoader(store)
        nodes1, wf_cfg = loader.load_workflow("code_land")
        wf_inputs = fill_input_defaults(
            wf_cfg.inputs,
            {
                "work_dir": str(work_dir),
                "branch": "feat/dead-box",
                "base": "main",
                "mode": "pr",
                "require_checks": "true",
                "poll_interval_s": "0.02",
                "checks_appear_timeout_s": "0.1",
            },
        )
        cancel_event = threading.Event()
        ctx1, _cp1, tool_exec1 = _make_box_context(
            exec_id, store, harness, park_at_gates=False, cancel_event=cancel_event
        )
        box1_out: dict[str, Any] = {}

        def run_box1():
            box1_out["res"] = execute_graph(
                nodes1,
                wf_inputs,
                ctx1,
                graph_name="code_land",
                is_workflow=True,
                workflow_outputs=wf_cfg.outputs,
            )

        t = threading.Thread(target=run_box1, daemon=True)
        t.start()

        try:
            # Poll until gate_wait is recorded in DB
            gate_id = None
            deadline = time.monotonic() + 15.0
            while time.monotonic() < deadline:
                resp = client.get(f"/api/runs/{exec_id}/gates")
                gates = resp.json().get("gates", []) if resp.status_code == 200 else []
                if gates and gates[0]["status"] == "waiting":
                    gate_id = gates[0]["event_id"]
                    assert "shared.txt" in gates[0]["questions"][0]["question"]
                    break
                time.sleep(0.05)
            assert gate_id is not None, "expected code_land_pause gate to enter waiting state"

            # Verify unanswered hold: PR #1 open, nothing merged, branch intact
            assert harness.merge_calls == []
            assert harness.prs[1]["state"] == "open"
            assert harness.branch_sha("feat/dead-box") == branch_sha

            # Simulate container/box death after >4h & wipe work_dir
            cancel_event.set()
            t.join(timeout=10.0)
            shutil.rmtree(work_dir)
        finally:
            tool_exec1.shutdown()

        # Resolve conflict on remote branch (real 2-parent merge commit) and mark new SHA green
        resolved_sha = harness.commit_on_remote(
            "feat/dead-box",
            {"shared.txt": "main conflicting line\nbranch resolved line\ngamma\n"},
            message="fix: resolve conflict with main",
            merge_base="main",
        )
        harness.set_checks(
            resolved_sha,
            [{"id": 9, "name": "ci", "status": "completed", "conclusion": "success", "app": {"id": 1}}],
        )

        gates_after = client.get(f"/api/runs/{exec_id}/gates").json()["gates"]
        assert len(gates_after) == 1
        assert gates_after[0]["status"] == "waiting"
        approve = client.post(
            f"/api/runs/{exec_id}/approve/code_land_pause",
            json={
                "response": "Conflict resolved on branch",
                "event_id": gate_id,
                "by": "owner",
            },
        )
        assert approve.status_code == 200
        assert approve.json()["needs_resume"] is True

        # Fresh Box 2 resumes from checkpoint with work_dir completely absent!
        nodes2, wf_cfg2 = loader.load_workflow("code_land")
        ctx2, cp2, tool_exec2 = _make_box_context(
            exec_id, store, harness, park_at_gates=False
        )
        try:
            restored = cp2.reconstruct()
            res2 = execute_graph_with_state(
                nodes2,
                wf_inputs,
                ctx2,
                graph_name="code_land",
                is_workflow=True,
                initial_outputs=restored,
                workflow_outputs=wf_cfg2.outputs,
            )
        finally:
            tool_exec2.shutdown()
            close_for_run(exec_id)

        assert res2.status == Status.COMPLETED
        out2 = res2.structured_output
        assert out2 is not None
        assert out2["merged"] is True
        assert out2["pr_number"] == 1
        assert out2["checks"]["state"] == "passed"
        assert len(harness.merge_calls) == 1

    def test_end_to_end_pipeline_checkout_save_and_stage_land(
        self,
        harness: LocalGitHubHarness,
        temper_runtime: tuple[Any, TestClient],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Proves `code_checkout -> edit -> code_save -> code_land (StageNode)` end-to-end."""
        from temper_ai.api.run_tokens import close_for_run
        from temper_ai.shared.types import Status
        from temper_ai.stage.executor import execute_graph
        from temper_ai.stage.loader import GraphLoader

        store, _client = temper_runtime
        for k, v in harness.env().items():
            monkeypatch.setenv(k, v)

        harness.set_default_checks_callback(
            lambda sha, poll: [
                {"id": 1, "name": "temper-ci", "status": "completed", "conclusion": "success", "app": {"id": 1}}
            ]
        )

        # Register an inline script agent in the test ConfigStore to edit a file in checkout.path
        store.configs[("agent", "_test_write_shipped_file")] = {
            "name": "_test_write_shipped_file",
            "type": "script",
            "script_template": (
                "#!/bin/sh\n"
                "set -eu\n"
                'DIR="{{ work_dir }}"\n'
                'printf "SHIPPED = 1\\n" > "$DIR/shipped.py"\n'
                'printf \'{"edited": true}\\n\'\n'
            ),
        }
        try:
            wf_dict = {
                "name": "checkout_save_land_e2e",
                "inputs": {
                    "repo_url": {"type": "string", "required": True},
                    "branch": {"type": "string", "required": True},
                    "root": {"type": "string", "required": True},
                },
                "nodes": [
                    {
                        "name": "checkout",
                        "type": "agent",
                        "agent": "code_checkout",
                        "input_map": {
                            "repo_url": "input.repo_url",
                            "base_branch": "main",
                            "branch": "input.branch",
                            "root": "input.root",
                        },
                    },
                    {
                        "name": "edit_file",
                        "type": "agent",
                        "agent": "_test_write_shipped_file",
                        "depends_on": ["checkout"],
                        "input_map": {"work_dir": "checkout.structured.path"},
                    },
                    {
                        "name": "save",
                        "type": "agent",
                        "agent": "code_save",
                        "depends_on": ["edit_file"],
                        "input_map": {
                            "work_dir": "checkout.structured.path",
                            "message": "feat: ship portable pipeline",
                        },
                    },
                    {
                        "name": "land",
                        "type": "stage",
                        "ref": "code_land",
                        "depends_on": ["save"],
                        "input_map": {
                            "work_dir": "checkout.structured.path",
                            "branch": "save.structured.branch",
                            "base": "main",
                            "mode": "pr",
                            "require_checks": "true",
                            "poll_interval_s": "0.02",
                            "checks_appear_timeout_s": "0.2",
                        },
                    },
                ],
                "outputs": {
                    "pushed": "save.structured.pushed",
                    "merged": "land.structured.merged",
                    "pr_number": "land.structured.pr_number",
                    "checks": "land.structured.checks",
                },
            }
            store.configs[("workflow", "checkout_save_land_e2e")] = wf_dict
            loader = GraphLoader(store)
            nodes, wf_cfg = loader.load_workflow("checkout_save_land_e2e")
            exec_id = "exec-e2e-pipeline-128"
            ctx, _cp, tool_exec = _make_box_context(
                exec_id, store, harness, park_at_gates=False
            )
            try:
                res = execute_graph(
                    nodes,
                    {
                        "repo_url": f"https://github.com/{harness.repo_slug}.git",
                        "branch": "feat/e2e-ship",
                        "root": str(tmp_path / "e2e-root"),
                    },
                    ctx,
                    graph_name="checkout_save_land_e2e",
                    is_workflow=True,
                    workflow_outputs=wf_cfg.outputs,
                )
            finally:
                tool_exec.shutdown()
                close_for_run(exec_id)
        finally:
            store.configs.pop(("workflow", "checkout_save_land_e2e"), None)
            store.configs.pop(("agent", "_test_write_shipped_file"), None)

        assert res.status == Status.COMPLETED
        out = res.structured_output
        assert out is not None
        assert out["pushed"] is True
        assert out["merged"] is True
        assert out["pr_number"] == 1
        assert out["checks"]["state"] == "passed"


def test_departments_md_and_docs_register_code_save_and_land() -> None:
    text = (REPO_ROOT / "docs" / "departments.md").read_text(encoding="utf-8")
    section = text.split("### systems (", 1)[1].split("\n### ", 1)[0]
    declared_count = int(section.split(")", 1)[0])
    rows = [line for line in section.splitlines() if line.startswith("| `")]
    assert len(rows) == declared_count
    expected = (
        "`epd/workflows/code_land.yaml`",
        "`epd/agents/code_land_attempt.yaml`",
        "`epd/agents/code_land_pause.yaml`",
        "`epd/agents/code_save.yaml`",
        "`epd/bin/code_land.py`",
        "`epd/bin/code_land_github.py`",
        "`epd/bin/code_land_pause.py`",
        "`epd/bin/code_save.py`",
    )
    for item in expected:
        assert any(item in r for r in rows), f"missing {item} in docs/departments.md"
    assert (REPO_ROOT / "docs" / "code-checkout-save-land.md").is_file()

