"""Unit and contract tests for configs/epd/agents/code_checkout.yaml and configs/epd/bin/code_checkout.py."""

from __future__ import annotations

import base64
import http.server
import importlib.util
import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import jinja2
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "configs" / "epd" / "bin" / "code_checkout.py"
AGENT_YAML_PATH = REPO_ROOT / "configs" / "epd" / "agents" / "code_checkout.yaml"


def _load_module():
    spec = importlib.util.spec_from_file_location("code_checkout", SCRIPT_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["code_checkout"] = mod
    spec.loader.exec_module(mod)
    return mod


code_checkout = _load_module()


def _shquote(val: Any) -> str:
    s = str(val)
    return "'" + s.replace("'", "'\"'\"'") + "'"


def _git_raw(cwd: Path, *args: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Test Author",
        "GIT_AUTHOR_EMAIL": "author@example.com",
        "GIT_COMMITTER_NAME": "Test Author",
        "GIT_COMMITTER_EMAIL": "author@example.com",
    }
    proc = subprocess.run(
        ["/usr/bin/git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return proc.stdout.strip()


@pytest.fixture()
def checkout_harness(tmp_path: Path):
    """External test harness: local HTTP token endpoint + git wrapper mapping github.com URLs to bare repos."""
    remotes_root = tmp_path / "remotes"
    remotes_root.mkdir(parents=True)

    # Create bare remote repo https://github.com/acme/widget.git
    bare_repo = remotes_root / "acme" / "widget.git"
    bare_repo.mkdir(parents=True)
    _git_raw(bare_repo, "init", "--bare", "-b", "main")

    seed = tmp_path / "seed"
    seed.mkdir(parents=True)
    _git_raw(seed, "init", "-b", "main")
    (seed / "README.md").write_text("commit 1\n", encoding="utf-8")
    _git_raw(seed, "add", "README.md")
    _git_raw(seed, "commit", "-m", "first commit")
    sha1 = _git_raw(seed, "rev-parse", "HEAD")

    (seed / "README.md").write_text("commit 2\n", encoding="utf-8")
    _git_raw(seed, "add", "README.md")
    _git_raw(seed, "commit", "-m", "second commit")
    main_sha = _git_raw(seed, "rev-parse", "HEAD")

    _git_raw(seed, "remote", "add", "origin", str(bare_repo))
    _git_raw(seed, "push", "-u", "origin", "main")

    # Also create an existing feature branch on origin
    _git_raw(seed, "checkout", "-b", "existing-work")
    (seed / "feature.txt").write_text("existing work content\n", encoding="utf-8")
    _git_raw(seed, "add", "feature.txt")
    _git_raw(seed, "commit", "-m", "existing work commit")
    existing_branch_sha = _git_raw(seed, "rev-parse", "HEAD")
    _git_raw(seed, "push", "-u", "origin", "existing-work")
    _git_raw(seed, "checkout", "main")

    # Start a local HTTP server implementing POST /api/github/token
    token_requests: list[dict[str, Any]] = []
    test_token = "ghs_TestSecretInstallToken987654321"
    active_token_file = tmp_path / "active_token.txt"
    active_token_file.write_text(test_token, encoding="utf-8")

    def set_token(new_token: str) -> None:
        active_token_file.write_text(new_token, encoding="utf-8")

    class TokenHandler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8")
            payload = json.loads(raw) if raw else {}
            current_tok = active_token_file.read_text(encoding="utf-8").strip()
            token_requests.append(
                {
                    "path": self.path,
                    "auth": self.headers.get("Authorization", ""),
                    "body": payload,
                }
            )
            if self.path != "/api/github/token":
                self.send_response(404)
                self.end_headers()
                return
            repo_slug = payload.get("repo", "")
            if repo_slug == "acme/forbidden":
                self.send_response(403)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(
                    json.dumps({"detail": f"denied for {current_tok}"}).encode()
                )
                return
            if repo_slug == "acme/uninstalled":
                self.send_response(404)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(
                    json.dumps(
                        {"detail": "the app is not installed on acme/uninstalled"}
                    ).encode()
                )
                return
            if repo_slug == "acme/unconfigured-503":
                self.send_response(503)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(
                    json.dumps(
                        {
                            "detail": "temper's GitHub app is not set up: TEMPER_GITHUB_APP_ID is not set"
                        }
                    ).encode()
                )
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {"token": current_tok, "expires_at": "2099-01-01T00:00:00Z"}
                ).encode()
            )

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return

    server = http.server.HTTPServer(("127.0.0.1", 0), TokenHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    # Create external git wrapper in tmp_path/bin/git that logs calls and maps github.com URLs to remotes_root
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    git_log_path = tmp_path / "git_calls.jsonl"
    git_wrapper = bin_dir / "git"
    git_wrapper.write_text(
        f"""#!{sys.executable}
import json, os, re, subprocess, sys

remotes_root = {str(remotes_root)!r}
log_path = {str(git_log_path)!r}
active_token_path = {str(active_token_file)!r}
args = sys.argv[1:]
rewritten = []
for arg in args:
    m = re.fullmatch(r"https://github\\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\\.git)?", arg)
    if m:
        rewritten.append("file://" + os.path.join(remotes_root, m.group(1) + ".git"))
    else:
        rewritten.append(arg)

record = {{
    "args": args,
    "git_config_count": os.environ.get("GIT_CONFIG_COUNT", ""),
    "git_config_key_0": os.environ.get("GIT_CONFIG_KEY_0", ""),
    "git_config_value_0": os.environ.get("GIT_CONFIG_VALUE_0", ""),
    "git_terminal_prompt": os.environ.get("GIT_TERMINAL_PROMPT", ""),
}}
with open(log_path, "a", encoding="utf-8") as fh:
    fh.write(json.dumps(record) + "\\n")

# When a remote operation (fetch/push/pull/ls-remote) runs without ephemeral extraheader
# (e.g. a subsequent git fetch/push >1h later in the worktree), exercise Git's configured
# credential.https://github.com.helper via `/usr/bin/git credential fill` + `approve`.
if not os.environ.get("GIT_CONFIG_VALUE_0"):
    cwd = os.getcwd()
    subcmd = None
    i = 0
    while i < len(args):
        if args[i] == "-C" and i + 1 < len(args):
            cwd = args[i + 1]
            i += 2
            continue
        if not args[i].startswith("-"):
            subcmd = args[i]
            break
        i += 1
    if subcmd in ("fetch", "push", "pull", "ls-remote"):
        cred_input = "protocol=https\\nhost=github.com\\npath=acme/widget.git\\n\\n"
        fill = subprocess.run(
            ["/usr/bin/git", "-C", cwd, "credential", "fill"],
            input=cred_input,
            capture_output=True,
            text=True,
            env=os.environ,
            check=False,
        )
        if fill.returncode != 0:
            sys.stderr.write(fill.stderr or "fatal: credential helper failed\\n")
            sys.exit(128)
        expected_tok = open(active_token_path, encoding="utf-8").read().strip()
        kv = dict(
            line.split("=", 1)
            for line in fill.stdout.splitlines()
            if "=" in line
        )
        if kv.get("username") != "x-access-token" or kv.get("password") != expected_tok:
            sys.stderr.write("fatal: Authentication failed for 'https://github.com/acme/widget.git/'\\n")
            sys.exit(128)
        subprocess.run(
            ["/usr/bin/git", "-C", cwd, "credential", "approve"],
            input=fill.stdout,
            capture_output=True,
            text=True,
            env=os.environ,
            check=False,
        )

os.execv("/usr/bin/git", ["/usr/bin/git"] + rewritten)
""",
        encoding="utf-8",
    )
    git_wrapper.chmod(0o755)

    workspace_dir = tmp_path / "workspaces"
    workspace_dir.mkdir(parents=True)

    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
        "TEMPER_SERVER_URL": f"http://127.0.0.1:{port}",
        "TEMPER_RUN_TOKEN": "trun_test_run_token_secret",
        "TEMPER_RUN_CONTAINER": "temper-run-99887766-5544-3322",
        "WORKSPACE_DIR": str(workspace_dir),
    }

    def read_git_calls() -> list[dict[str, Any]]:
        if not git_log_path.is_file():
            return []
        return [
            json.loads(line)
            for line in git_log_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    try:
        yield {
            "env": env,
            "bare_repo": bare_repo,
            "main_sha": main_sha,
            "first_sha": sha1,
            "existing_branch_sha": existing_branch_sha,
            "token_requests": token_requests,
            "read_git_calls": read_git_calls,
            "test_token": test_token,
            "set_token": set_token,
            "workspace_dir": workspace_dir,
            "tmp_path": tmp_path,
        }
    finally:
        server.shutdown()
        server.server_close()


def test_code_checkout_yaml_contract_and_shell_syntax() -> None:
    raw_text = AGENT_YAML_PATH.read_text(encoding="utf-8")
    assert "${" not in raw_text, "YAML command must not use ${...} env substitution"
    assert "/home/shinelay" not in raw_text
    assert "/app/github-deploy" not in raw_text

    doc = yaml.safe_load(raw_text)
    assert "agent" in doc
    cfg = doc["agent"]
    assert cfg["name"] == "code_checkout"
    assert cfg["type"] == "script"
    assert cfg["timeout_seconds"] == 300
    assert cfg["strict_undefined"] is True

    inputs = cfg["inputs"]
    assert set(inputs) == {
        "repo_url",
        "base_branch",
        "branch",
        "label",
        "resume",
        "root",
    }
    assert inputs["repo_url"]["required"] is True
    assert inputs["base_branch"]["required"] is True
    assert inputs["root"]["default"] == "/tmp/temper-checkout"

    outputs = cfg["outputs"]
    assert set(outputs) == {
        "status",
        "repo",
        "repo_url",
        "base_branch",
        "base_head",
        "branch",
        "repo_path",
        "worktree_path",
        "mode",
        "error",
    }

    jenv = jinja2.Environment(undefined=jinja2.StrictUndefined)
    rendered = jenv.from_string(cfg["script_template"]).render(
        repo_url="https://github.com/acme/widget.git",
        base_branch="main",
    )
    syntax = subprocess.run(
        ["/bin/sh", "-n"],
        input=rendered,
        capture_output=True,
        text=True,
        check=False,
    )
    assert syntax.returncode == 0

    from temper_ai.agent.script_agent import ScriptAgent

    script_agent = ScriptAgent(cfg)
    assert script_agent.validate_config() == []


def test_departments_md_lists_code_checkout() -> None:
    text = (REPO_ROOT / "docs" / "departments.md").read_text(encoding="utf-8")
    section = text.split("### systems (", 1)[1].split("\n### ", 1)[0]
    declared_count = int(section.split(")", 1)[0])
    rows = [line for line in section.splitlines() if line.startswith("| `")]
    assert len(rows) == declared_count
    assert any("`epd/agents/code_checkout.yaml`" in r for r in rows)
    assert any("`epd/bin/code_checkout.py`" in r for r in rows)


@pytest.mark.parametrize(
    ("raw_url", "expected_repo", "expected_https"),
    [
        (
            "https://github.com/shine/temper-ai",
            "shine/temper-ai",
            "https://github.com/shine/temper-ai.git",
        ),
        (
            "https://github.com/shine/temper-ai.git",
            "shine/temper-ai",
            "https://github.com/shine/temper-ai.git",
        ),
        (
            "git@github.com:shine/rollcall.git",
            "shine/rollcall",
            "https://github.com/shine/rollcall.git",
        ),
        (
            "ssh://git@github.com/shine/rollcall",
            "shine/rollcall",
            "https://github.com/shine/rollcall.git",
        ),
    ],
)
def test_parse_and_validate_repo_url_valid(
    raw_url: str, expected_repo: str, expected_https: str
) -> None:
    _, _, repo_slug, https_remote = code_checkout.parse_and_validate_repo_url(raw_url)
    assert repo_slug == expected_repo
    assert https_remote == expected_https


@pytest.mark.parametrize(
    "bad_url",
    [
        "",
        "   ",
        "https://github.com/only-owner",
        "https://github.com/owner/repo/extra",
        "https://github.com/owner/../repo",
        "https://github.com/owner/..",
        "https://gitlab.com/owner/repo.git",
        "http://github.com/owner/repo.git",
        "https://token@github.com/owner/repo.git",
        "https://github.com/owner/repo with space.git",
        "/tmp/local/repo",
        "file:///tmp/repo.git",
    ],
)
def test_malformed_repo_url_fails_before_any_network_call(
    bad_url: str, checkout_harness: dict[str, Any]
) -> None:
    root_dir = checkout_harness["tmp_path"] / "checkout-malformed"
    with pytest.raises(code_checkout.CodeCheckoutError, match="invalid repo_url"):
        code_checkout.checkout_code(
            repo_url=bad_url,
            base_branch="main",
            root=str(root_dir),
            env=checkout_harness["env"],
        )
    assert checkout_harness["token_requests"] == []
    assert checkout_harness["read_git_calls"]() == []


@pytest.mark.parametrize(
    "bad_root",
    [
        "",
        "relative/path",
        "/tmp/temper-checkout/../escape",
        "/home/shinelay/temper-ai/workspaces/foo",
        "/home/shinelay/anything",
        "/app/workspaces/run-1",
        "/",
        "/tmp",
    ],
)
def test_forbidden_root_rejected_before_network(
    bad_root: str, checkout_harness: dict[str, Any]
) -> None:
    with pytest.raises(code_checkout.CodeCheckoutError, match="invalid root"):
        code_checkout.checkout_code(
            repo_url="https://github.com/acme/widget.git",
            base_branch="main",
            root=bad_root,
            env=checkout_harness["env"],
        )
    assert checkout_harness["token_requests"] == []
    assert checkout_harness["read_git_calls"]() == []


def test_workspace_dir_root_rejected_before_network(
    checkout_harness: dict[str, Any],
) -> None:
    ws_sub = checkout_harness["workspace_dir"] / "sub"
    with pytest.raises(code_checkout.CodeCheckoutError, match="WORKSPACE_DIR"):
        code_checkout.checkout_code(
            repo_url="https://github.com/acme/widget.git",
            base_branch="main",
            root=str(ws_sub),
            env=checkout_harness["env"],
        )
    assert checkout_harness["token_requests"] == []
    assert checkout_harness["read_git_calls"]() == []


def test_fresh_clone_and_worktree_pass_case(checkout_harness: dict[str, Any]) -> None:
    root_dir = checkout_harness["tmp_path"] / "checkout-pass"
    res = code_checkout.checkout_code(
        repo_url="https://github.com/acme/widget.git",
        base_branch="main",
        label="Stage_Check",
        resume="false",
        root=str(root_dir),
        env=checkout_harness["env"],
    )

    assert res["status"] == "ready"
    assert res["repo"] == "acme/widget"
    assert res["repo_url"] == "https://github.com/acme/widget.git"
    assert res["base_branch"] == "main"
    assert res["base_head"] == checkout_harness["main_sha"]
    assert res["branch"] == "run-stage-check-99887766"
    assert res["repo_path"] == str(root_dir / "repo")
    assert res["worktree_path"] == str(root_dir / "work")
    assert res["mode"] == "cloned"

    work_dir = Path(res["worktree_path"])
    assert (work_dir / "README.md").read_text(encoding="utf-8") == "commit 2\n"
    assert (
        _git_raw(work_dir, "rev-parse", "--abbrev-ref", "HEAD")
        == "run-stage-check-99887766"
    )
    assert _git_raw(work_dir, "rev-parse", "HEAD") == checkout_harness["main_sha"]
    assert (Path(res["repo_path"]) / ".git" / "shallow").is_file()

    # Zero files written under WORKSPACE_DIR
    assert list(checkout_harness["workspace_dir"].iterdir()) == []

    # Verify token was passed via GIT_CONFIG_VALUE_0 extraheader and never written to .git/config
    git_calls = checkout_harness["read_git_calls"]()
    assert len(git_calls) > 0
    expected_b64 = base64.b64encode(
        f"x-access-token:{checkout_harness['test_token']}".encode()
    ).decode("ascii")
    assert git_calls[0]["git_config_key_0"] == "http.https://github.com/.extraheader"
    assert git_calls[0]["git_config_value_0"] == f"Authorization: Basic {expected_b64}"

    git_cfg = (Path(res["repo_path"]) / ".git" / "config").read_text(encoding="utf-8")
    assert checkout_harness["test_token"] not in git_cfg
    assert expected_b64 not in git_cfg
    assert _git_raw(
        work_dir, "config", "--get", "credential.https://github.com.helper"
    ) == code_checkout.build_credential_helper_command("acme/widget")
    assert (
        _git_raw(
            work_dir, "config", "--get", "credential.https://github.com.useHttpPath"
        )
        == "true"
    )

    # Verify pushing a new commit from the shallow worktree and deepening history work cleanly
    (work_dir / "new_file.txt").write_text("hello from worktree\n", encoding="utf-8")
    _git_raw(work_dir, "add", "new_file.txt")
    _git_raw(work_dir, "commit", "-m", "worktree commit")
    _git_raw(work_dir, "push", "origin", f"HEAD:refs/heads/{res['branch']}")

    git_env = code_checkout.build_git_env(
        checkout_harness["test_token"], base_env=checkout_harness["env"]
    )
    code_checkout.deepen_history(
        work_dir, 1, git_env=git_env, token=checkout_harness["test_token"]
    )
    log_lines = _git_raw(work_dir, "log", "--oneline").splitlines()
    assert len(log_lines) >= 3


def test_resume_true_on_existing_origin_branch_and_local_worktree(
    checkout_harness: dict[str, Any],
) -> None:
    root_dir = checkout_harness["tmp_path"] / "checkout-resume"

    # 1. Resume existing branch on origin in a fresh root directory
    res1 = code_checkout.checkout_code(
        repo_url="git@github.com:acme/widget.git",
        base_branch="main",
        branch="existing-work",
        resume="true",
        root=str(root_dir),
        env=checkout_harness["env"],
    )
    assert res1["status"] == "ready"
    assert res1["mode"] == "resumed"
    assert res1["branch"] == "existing-work"
    assert res1["base_head"] == checkout_harness["main_sha"]
    work_dir = Path(res1["worktree_path"])
    assert (work_dir / "feature.txt").read_text(
        encoding="utf-8"
    ) == "existing work content\n"
    assert (
        _git_raw(work_dir, "rev-parse", "HEAD")
        == checkout_harness["existing_branch_sha"]
    )

    # 2. Re-running with resume=true when worktree is already checked out reuses it
    res2 = code_checkout.checkout_code(
        repo_url="git@github.com:acme/widget.git",
        base_branch="main",
        branch="existing-work",
        resume=True,
        root=str(root_dir),
        env=checkout_harness["env"],
    )
    assert res2["status"] == "ready"
    assert res2["mode"] == "resumed"
    assert res2["branch"] == "existing-work"


def test_existing_work_branch_with_resume_false_fails(
    checkout_harness: dict[str, Any],
) -> None:
    root_dir = checkout_harness["tmp_path"] / "checkout-conflict"
    with pytest.raises(
        code_checkout.CodeCheckoutError,
        match="work branch 'existing-work' already exists on origin",
    ):
        code_checkout.checkout_code(
            repo_url="https://github.com/acme/widget.git",
            base_branch="main",
            branch="existing-work",
            resume="false",
            root=str(root_dir),
            env=checkout_harness["env"],
        )


def test_missing_base_branch_fails_naming_branch(
    checkout_harness: dict[str, Any],
) -> None:
    root_dir = checkout_harness["tmp_path"] / "checkout-missing-base"
    with pytest.raises(
        code_checkout.CodeCheckoutError,
        match="base_branch 'no-such-branch' does not exist on origin",
    ):
        code_checkout.checkout_code(
            repo_url="https://github.com/acme/widget.git",
            base_branch="no-such-branch",
            root=str(root_dir),
            env=checkout_harness["env"],
        )


def test_unreachable_repo_url_fails_naming_repo(
    checkout_harness: dict[str, Any],
) -> None:
    root_dir = checkout_harness["tmp_path"] / "checkout-unreachable"
    with pytest.raises(
        code_checkout.CodeCheckoutError,
        match="repository 'acme/missing-repo'.*is unreachable",
    ):
        code_checkout.checkout_code(
            repo_url="https://github.com/acme/missing-repo.git",
            base_branch="main",
            root=str(root_dir),
            env=checkout_harness["env"],
        )


def test_token_scrubbing_on_http_and_git_errors(
    checkout_harness: dict[str, Any],
) -> None:
    root_dir = checkout_harness["tmp_path"] / "checkout-scrub"
    with pytest.raises(code_checkout.CodeCheckoutError) as exc_info:
        code_checkout.checkout_code(
            repo_url="https://github.com/acme/forbidden.git",
            base_branch="main",
            root=str(root_dir),
            env=checkout_harness["env"],
        )
    err_text = str(exc_info.value)
    assert checkout_harness["test_token"] not in err_text
    assert "trun_test_run_token_secret" not in err_text
    assert "[REDACTED]" in err_text


def test_cli_json_output_through_yaml_command(
    checkout_harness: dict[str, Any],
) -> None:
    doc = yaml.safe_load(AGENT_YAML_PATH.read_text(encoding="utf-8"))
    cfg = doc["agent"]
    jenv = jinja2.Environment(undefined=jinja2.StrictUndefined)

    root_dir = checkout_harness["tmp_path"] / "yaml-run"
    cmd = jenv.from_string(cfg["script_template"]).render(
        repo_url="https://github.com/acme/widget.git",
        base_branch="main",
        branch="yaml-feature-branch",
        label="",
        resume="false",
        root=str(root_dir),
    )
    env = {
        **checkout_harness["env"],
        "CONFIGS_DIR": str(REPO_ROOT / "configs"),
        "TEMPER_PYTHON": sys.executable,
    }
    proc = subprocess.run(
        ["/bin/sh", "-c", cmd],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout.strip())
    assert payload["status"] == "ready"
    assert payload["branch"] == "yaml-feature-branch"
    assert payload["mode"] == "cloned"

    # Running the same command again with resume="false" exits 1 with JSON status=="failed"
    proc_fail = subprocess.run(
        ["/bin/sh", "-c", cmd],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert proc_fail.returncode == 1
    fail_payload = json.loads(proc_fail.stdout.strip())
    assert fail_payload["status"] == "failed"
    assert "yaml-feature-branch" in fail_payload["error"]

    # Also verify script_template succeeds when TEMPER_PYTHON and CONFIGS_DIR are unset.
    root_dir_unset = checkout_harness["tmp_path"] / "yaml-run-unset"
    cmd_unset = jenv.from_string(cfg["script_template"]).render(
        repo_url="https://github.com/acme/widget.git",
        base_branch="main",
        branch="yaml-unset-env-branch",
        label="",
        resume="false",
        root=str(root_dir_unset),
    )
    env_unset = dict(checkout_harness["env"])
    env_unset.pop("TEMPER_PYTHON", None)
    env_unset.pop("CONFIGS_DIR", None)
    proc_unset = subprocess.run(
        ["/bin/sh", "-c", cmd_unset],
        cwd=str(REPO_ROOT),
        env=env_unset,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc_unset.returncode == 0
    unset_payload = json.loads(proc_unset.stdout.strip())
    assert unset_payload["status"] == "ready"
    assert unset_payload["branch"] == "yaml-unset-env-branch"


def test_credential_helper_get_rotates_token_and_store_erase_are_noops(
    checkout_harness: dict[str, Any],
) -> None:
    env = dict(checkout_harness["env"])

    # 1. Initial `get` fetches token v1 from POST /api/github/token
    proc_get1 = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--credential-helper",
            "--repo",
            "acme/widget",
            "get",
        ],
        input="protocol=https\nhost=github.com\npath=acme/widget.git\n\n",
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert proc_get1.returncode == 0
    assert (
        proc_get1.stdout
        == f"username=x-access-token\npassword={checkout_harness['test_token']}\n\n"
    )
    assert len(checkout_harness["token_requests"]) == 1
    assert checkout_harness["token_requests"][0]["body"] == {"repo": "acme/widget"}

    # 2. Rotate server token (simulating >1h installation token expiry) and call `get` again
    rotated_token = "ghs_RotatedInstallTokenAfterOneHour_222"
    checkout_harness["set_token"](rotated_token)

    proc_get2 = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--credential-helper",
            "--repo",
            "acme/widget",
            "get",
        ],
        input="protocol=https\nhost=github.com\npath=acme/widget.git\n\n",
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert proc_get2.returncode == 0
    assert proc_get2.stdout == f"username=x-access-token\npassword={rotated_token}\n\n"
    assert len(checkout_harness["token_requests"]) == 2

    # 3. `store` and `erase` are no-ops: exit 0, empty stdout, zero token requests, zero files written
    for op in ("store", "erase"):
        proc_op = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "--credential-helper",
                "--repo",
                "acme/widget",
                op,
            ],
            input=f"protocol=https\nhost=github.com\nusername=x-access-token\npassword={rotated_token}\n\n",
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        assert proc_op.returncode == 0
        assert proc_op.stdout == ""
        assert proc_op.stderr == ""
    assert len(checkout_harness["token_requests"]) == 2


def test_subsequent_git_fetch_and_push_without_git_config_count_use_credential_helper(
    checkout_harness: dict[str, Any],
) -> None:
    root_dir = checkout_harness["tmp_path"] / "checkout-long-run"
    res = code_checkout.checkout_code(
        repo_url="https://github.com/acme/widget.git",
        base_branch="main",
        branch="long-run-branch",
        resume="false",
        root=str(root_dir),
        env=checkout_harness["env"],
    )
    assert res["status"] == "ready"
    assert len(checkout_harness["token_requests"]) == 1

    # Simulate >1h passing: rotate the installation token on the Temper server
    rotated_token = "ghs_FreshTokenAfterOneHourExpiry_999"
    checkout_harness["set_token"](rotated_token)

    # Clean environment without GIT_CONFIG_COUNT / GIT_CONFIG_KEY_0 / GIT_CONFIG_VALUE_0
    clean_env = {
        k: v
        for k, v in checkout_harness["env"].items()
        if not k.startswith("GIT_CONFIG_")
    }
    clean_env["GIT_TERMINAL_PROMPT"] = "0"
    clean_env["GIT_CONFIG_NOSYSTEM"] = "1"
    clean_env["GIT_CONFIG_GLOBAL"] = "/dev/null"
    clean_env["GIT_AUTHOR_NAME"] = "Test Author"
    clean_env["GIT_AUTHOR_EMAIL"] = "author@example.com"
    clean_env["GIT_COMMITTER_NAME"] = "Test Author"
    clean_env["GIT_COMMITTER_EMAIL"] = "author@example.com"

    work_dir = Path(res["worktree_path"])
    repo_dir = Path(res["repo_path"])

    # Subsequent `git -C <worktree_path> fetch --deepen=1 origin` re-requests fresh token via helper
    fetch_proc = subprocess.run(
        ["git", "-C", str(work_dir), "fetch", "--deepen=1", "origin"],
        env=clean_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert fetch_proc.returncode == 0
    assert len(checkout_harness["token_requests"]) == 2

    # Subsequent `git -C <worktree_path> push` re-requests another fresh token via helper
    rotated_token_2 = "ghs_SecondRotatedTokenForPush_888"
    checkout_harness["set_token"](rotated_token_2)
    (work_dir / "later_change.txt").write_text("pushed after 1h\n", encoding="utf-8")
    _git_raw(work_dir, "add", "later_change.txt")
    _git_raw(work_dir, "commit", "-m", "commit after 1h")

    push_proc = subprocess.run(
        [
            "git",
            "-C",
            str(work_dir),
            "push",
            "origin",
            f"HEAD:refs/heads/{res['branch']}",
        ],
        env=clean_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert push_proc.returncode == 0
    assert len(checkout_harness["token_requests"]) == 3

    # Verify zero tokens or secrets are persisted in .git/config
    git_cfg = (repo_dir / ".git" / "config").read_text(encoding="utf-8")
    for tok in (checkout_harness["test_token"], rotated_token, rotated_token_2):
        assert tok not in git_cfg
    assert "x-access-token:" not in git_cfg


def test_missing_installation_404_fails_loud_even_when_github_token_set(
    checkout_harness: dict[str, Any],
) -> None:
    root_dir = checkout_harness["tmp_path"] / "checkout-404"
    env_with_fallback = {
        **checkout_harness["env"],
        "GITHUB_TOKEN": "ghp_ShouldNeverBeUsedWhenAppNotInstalled123",
    }

    with pytest.raises(
        code_checkout.CodeCheckoutError,
        match=(
            r"GitHub App installation \(temper-ai-bot\) does not cover repository "
            r"'acme/uninstalled' \(https://github\.com/acme/uninstalled\.git\): "
            r"the app is not installed on acme/uninstalled"
        ),
    ):
        code_checkout.checkout_code(
            repo_url="https://github.com/acme/uninstalled.git",
            base_branch="main",
            root=str(root_dir),
            env=env_with_fallback,
        )

    # Must NEVER fall back to GITHUB_TOKEN or invoke git when /api/github/token returns 404
    assert len(checkout_harness["token_requests"]) == 1
    assert checkout_harness["read_git_calls"]() == []

    # Credential helper also fails loud on 404 without emitting credentials to stdout
    helper_proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--credential-helper",
            "--repo",
            "acme/uninstalled",
            "get",
        ],
        input="protocol=https\nhost=github.com\npath=acme/uninstalled.git\n\n",
        env=env_with_fallback,
        capture_output=True,
        text=True,
        check=False,
    )
    assert helper_proc.returncode == 1
    assert helper_proc.stdout == ""
    assert (
        "GitHub App installation (temper-ai-bot) does not cover repository 'acme/uninstalled'"
        in helper_proc.stderr
    )
    assert "ghp_ShouldNeverBeUsedWhenAppNotInstalled123" not in helper_proc.stderr


def test_unreachable_server_and_503_fallback_to_github_token_only_when_set(
    checkout_harness: dict[str, Any],
) -> None:
    # 1. Unreachable server without GITHUB_TOKEN fails loud
    unreachable_env = {
        **checkout_harness["env"],
        "TEMPER_SERVER_URL": "http://127.0.0.1:1",
    }
    unreachable_env.pop("GITHUB_TOKEN", None)
    with pytest.raises(
        code_checkout.CodeCheckoutError,
        match="failed to reach Temper server for GitHub token",
    ):
        code_checkout.checkout_code(
            repo_url="https://github.com/acme/widget.git",
            base_branch="main",
            root=str(checkout_harness["tmp_path"] / "unreachable-no-token"),
            env=unreachable_env,
        )

    # 2. HTTP 503 (app not configured) without GITHUB_TOKEN fails loud
    env_503_no_token = dict(checkout_harness["env"])
    env_503_no_token.pop("GITHUB_TOKEN", None)
    with pytest.raises(
        code_checkout.CodeCheckoutError,
        match="failed to reach Temper server for GitHub token.*HTTP 503",
    ):
        code_checkout.fetch_github_token(
            "acme/unconfigured-503",
            repo_url="https://github.com/acme/unconfigured-503.git",
            env=env_503_no_token,
        )

    # 3. HTTP 503 with single env var GITHUB_TOKEN falls back to GITHUB_TOKEN
    fallback_secret = "ghp_FallbackEnvTokenForUnreachableServer999"
    env_503_with_token = {
        **checkout_harness["env"],
        "GITHUB_TOKEN": fallback_secret,
    }
    tok_503 = code_checkout.fetch_github_token(
        "acme/unconfigured-503",
        repo_url="https://github.com/acme/unconfigured-503.git",
        env=env_503_with_token,
    )
    assert tok_503 == fallback_secret

    # 4. Unreachable server with single env var GITHUB_TOKEN falls back to GITHUB_TOKEN over HTTPS
    unreachable_with_token = {
        **unreachable_env,
        "GITHUB_TOKEN": fallback_secret,
    }
    root_fallback = checkout_harness["tmp_path"] / "unreachable-with-token"
    res = code_checkout.checkout_code(
        repo_url="https://github.com/acme/widget.git",
        base_branch="main",
        branch="fallback-work-branch",
        root=str(root_fallback),
        env=unreachable_with_token,
    )
    assert res["status"] == "ready"
    assert res["branch"] == "fallback-work-branch"
    git_cfg = (Path(res["repo_path"]) / ".git" / "config").read_text(encoding="utf-8")
    assert fallback_secret not in git_cfg
    assert "x-access-token:" not in git_cfg
