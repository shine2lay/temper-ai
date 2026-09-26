"""The build's script steps stop the run when something went wrong, instead of passing it on.

Each was a run that ended "completed" with the damage found later:
- task_gate (gap 16, b009 on 2026-09-24): "token pool exhausted" killed the plan step, implement
  and every judge were skipped, and the gate approved "nothing judged this round".
- task_branch_check (gap 14, b022): the implementer left HEAD detached on master, and the tests
  passed master.
- task_deploy (gap 13, b009 round 2): one Docker Hub "TLS handshake timeout" killed the deploy.
- epd_deploy (gap 5, b023 on 2026-09-22): GitHub refused to merge a PR that conflicted with master,
  and `ssh ... | tee` handed the step tee's exit code, 0.

The real agents and scripts, run by /bin/sh as the Bash tool runs them; ssh is a fake on PATH.
"""

import http.server
import json
import subprocess
import threading
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from temper_ai.agent.script_agent import ScriptAgent
from temper_ai.tools.base import ToolResult
from tests.test_epd.test_script_agents import AGENTS, ROOT, served_config

GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}


def run_step(name: str, inputs: dict, home: Path, *, bin_dir: Path | None = None, env: dict | None = None,
             swap: dict | None = None):
    """(status, structured output, what it said). `swap` rewrites the rendered script: the key
    directories are the container's, fixed in the script."""
    ctx = MagicMock()
    ctx.run_id, ctx.node_path, ctx.agent_name = "t", name, name
    ctx.workspace_path = None

    def execute(_tool, args, **_kw):
        command = args["command"]
        for old, new in (swap or {}).items():
            command = command.replace(old, new)
        path = ":".join([*([str(bin_dir)] if bin_dir else []), "/usr/bin", "/bin"])
        full = {"PATH": path, "HOME": str(home), **GIT_ENV, **(env or {}), **args["env"]}
        done = subprocess.run(command, shell=True, capture_output=True, text=True, env=full, timeout=120)
        return ToolResult(success=done.returncode == 0, result=done.stdout, error=done.stderr)

    ctx.tool_executor.execute.side_effect = execute
    result = ScriptAgent(config=served_config(AGENTS / f"{name}.yaml")).run(inputs, ctx)
    return result.status.value, result.structured_output, str(result.error or "") + str(result.output or "")


def fake(bin_dir: Path, name: str, body: str) -> None:
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / name).write_text("#!/bin/sh\n" + body)
    (bin_dir / name).chmod(0o755)


def git(*args: str, cwd: Path) -> str:
    done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True,
                          env={"PATH": "/usr/bin:/bin", "HOME": str(cwd), **GIT_ENV})
    return done.stdout.strip()


# ---- task_gate: a build that never built does not pass ---------------------------------------------


def gate(tmp_path: Path, **inputs):
    return run_step("task_gate", {"workspace_path": str(tmp_path), "run_id": "r1", **inputs}, tmp_path)


def planned(tmp_path: Path) -> str:
    (tmp_path / ".epd").mkdir(exist_ok=True)
    (tmp_path / ".epd" / "plan.md").write_text("# Plan\n")
    return str(tmp_path)


JUDGED = {"review_verdict": "approve", "qa_verdict": "pass", "security_verdict": "pass", "test_verdict": "pass"}


def test_the_gate_fails_a_round_where_nothing_was_built(tmp_path):
    """b009: the plan died, implement and every judge were skipped."""
    status, out, said = gate(tmp_path, implement_status=None, worktree_path=str(tmp_path),
                             review_verdict=None, qa_verdict=None, security_verdict=None, test_verdict=None)
    assert status == "failed", out
    assert "the build did not build, so nothing can pass the gate" in said
    assert "the implement step reported nothing" in said
    assert "no plan at" in said


def test_the_gate_fails_a_round_no_judge_ran(tmp_path):
    status, out, said = gate(tmp_path, implement_status="complete", worktree_path=planned(tmp_path))
    assert status == "failed", out
    assert "no judge ran" in said


def test_the_gate_still_approves_a_built_and_judged_round(tmp_path):
    status, out, _ = gate(tmp_path, implement_status="complete", worktree_path=planned(tmp_path), **JUDGED)
    assert status == "completed"
    assert out["verdict"] == "approve"


def test_a_judge_asking_for_changes_is_still_a_send_back_not_a_failure(tmp_path):
    status, out, _ = gate(tmp_path, implement_status="complete", worktree_path=planned(tmp_path),
                          **{**JUDGED, "review_verdict": "request_changes"})
    assert status == "completed"
    assert out["verdict"] == "request_changes"


# ---- task_branch_check: the judges read the implementer's commit -----------------------------------


@pytest.fixture
def repo(tmp_path):
    wt = tmp_path / "wt"
    wt.mkdir()
    git("init", "-q", "-b", "master", cwd=wt)
    git("commit", "-q", "--allow-empty", "-m", "master", cwd=wt)
    git("checkout", "-q", "-b", "epd/b022", cwd=wt)
    git("commit", "-q", "--allow-empty", "-m", "first", cwd=wt)
    first = git("rev-parse", "HEAD", cwd=wt)
    git("commit", "-q", "--allow-empty", "-m", "second", cwd=wt)
    return {"wt": wt, "first": first, "tip": git("rev-parse", "HEAD", cwd=wt), "master": git("rev-parse", "master", cwd=wt)}


def branch_check(repo, commit):
    return run_step("task_branch_check",
                    {"workspace_path": str(repo["wt"]), "branch": "epd/b022", "commit": commit}, repo["wt"].parent)


def test_a_worktree_left_detached_goes_back_on_its_branch(repo):
    """b022's implementer ran `git checkout -q 88b7615 --` and left HEAD detached on master."""
    git("checkout", "-q", "--detach", repo["master"], cwd=repo["wt"])
    status, out, said = branch_check(repo, repo["tip"])
    assert status == "completed", said
    assert out["head"] == repo["tip"]
    assert "detached at" in out["detail"]
    assert git("symbolic-ref", "--short", "HEAD", cwd=repo["wt"]) == "epd/b022"


def test_a_branch_not_at_the_reported_commit_stops_the_build(repo):
    git("reset", "-q", "--hard", repo["first"], cwd=repo["wt"])
    status, _, said = branch_check(repo, repo["tip"])
    assert status == "failed"
    assert "not at the commit the implementer reported" in said


def test_a_reported_commit_the_worktree_does_not_have_stops_the_build(repo):
    status, _, said = branch_check(repo, "0123abcd")
    assert status == "failed"
    assert "which is not a commit in this worktree" in said


def test_no_reported_commit_only_puts_the_branch_right(repo):
    git("checkout", "-q", "--detach", repo["master"], cwd=repo["wt"])
    status, out, said = branch_check(repo, None)
    assert status == "completed", said
    assert out["head"] == repo["tip"]


def test_every_judge_waits_for_the_branch_check_and_the_gate_is_told_what_was_built():
    nodes = {n["name"]: n for n in yaml.safe_load((ROOT / "configs/epd/workflows/epd_task.yaml").read_text())
             ["workflow"]["nodes"]}
    assert nodes["branch"]["agent"] == "task_branch_check"
    assert nodes["branch"]["depends_on"] == ["implement"]
    assert nodes["branch"]["input_map"]["commit"] == "implement.structured.commit"
    for judge in ("review", "deploy", "security", "test"):
        assert nodes[judge]["depends_on"] == ["branch"], judge
    assert nodes["gate"]["input_map"]["implement_status"] == "implement.structured.status"
    assert nodes["gate"]["input_map"]["worktree_path"] == "worktree.structured.worktree_path"


# ---- task_deploy: a network or registry hiccup is tried again ---------------------------------------

STANDEE = """
while [ $# -gt 0 ]; do case "$1" in shinelay@*) shift; break ;; *) shift ;; esac; done
[ "$1" = standee ] && shift
case "$1" in
  up)
    n=$(( $(cat "$COUNT" 2>/dev/null || echo 0) + 1 )); echo "$n" > "$COUNT"
    if [ "$n" -le "$FAILS" ]; then echo "$FAIL_WITH"; exit 1; fi
    echo "env  epd-b009-t1"; echo "url  $URL"; exit 0 ;;
  seed) echo "seeded"; exit 0 ;;
  url) echo "$URL"; exit 0 ;;
  *) echo "unexpected: $*" >&2; exit 2 ;;
esac
"""
DOCKER_HUB = ('ERROR: failed to solve: docker/dockerfile:1: failed to resolve source metadata for '
              'docker.io/docker/dockerfile:1: failed to do request: Head "https://registry-1.docker.io/v2/'
              'docker/dockerfile/manifests/1": net/http: TLS handshake timeout')
BUILD_BROKE = 'ERROR: failed to solve: process "/bin/sh -c npm ci" did not complete successfully: exit code: 1'


class _Ok(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 -- the stdlib's name
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args):
        pass


@pytest.fixture
def stack(tmp_path):
    server = http.server.HTTPServer(("127.0.0.1", 0), _Ok)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    wt = tmp_path / "wt"
    wt.mkdir()
    git("init", "-q", cwd=wt)
    git("commit", "-q", "--allow-empty", "-m", "the build", cwd=wt)
    keys = tmp_path / "keys"
    keys.mkdir()
    (keys / "id_ed25519").write_text("not a key\n")
    fake(tmp_path / "bin", "ssh", STANDEE)
    yield {"tmp": tmp_path, "wt": wt, "keys": keys, "head": git("rev-parse", "HEAD", cwd=wt),
           "url": f"http://127.0.0.1:{server.server_port}/", "count": tmp_path / "up-count"}
    server.shutdown()


def deploy(stack, fails: int, fail_with: str):
    inputs = {"worktree_path": str(stack["wt"]), "host_worktree_path": "/host/wt", "project": "rollcall",
              "task_slug": "b009-t1", "env_name": "epd-b009-t1", "env_name_actual": None, "ttl": "",
              "has_docker": True, "run_verify": True, "candidate_commit": stack["head"],
              "paper_account": None, "paper_email": None}
    env = {"COUNT": str(stack["count"]), "FAILS": str(fails), "FAIL_WITH": fail_with, "URL": stack["url"],
           "EPD_DEPLOY_RETRY_WAITS": "0 0 0"}
    got = run_step("task_deploy", inputs, stack["tmp"], bin_dir=stack["tmp"] / "bin", env=env,
                   swap={"/app/standee-ssh": str(stack["keys"])})
    return (*got, int(stack["count"].read_text()))


def test_a_registry_hiccup_is_tried_again(stack):
    status, out, said, ups = deploy(stack, fails=2, fail_with=DOCKER_HUB)
    assert status == "completed", said
    assert out["status"] == "deployed"
    assert ups == 3
    assert "trying again" in said


def test_a_build_that_breaks_is_not_tried_again(stack):
    status, _, said, ups = deploy(stack, fails=9, fail_with=BUILD_BROKE)
    assert status == "failed"
    assert ups == 1
    assert "standee up failed" in said


def test_the_retries_stop_after_three(stack):
    status, _, _, ups = deploy(stack, fails=9, fail_with=DOCKER_HUB)
    assert status == "failed"
    assert ups == 4


# ---- epd_deploy: the driver's refusal is the step's failure -----------------------------------------


@pytest.fixture
def ship(tmp_path):
    keys = tmp_path / "keys"
    keys.mkdir()
    (keys / "id_ed25519_ship").write_text("not a key\n")
    bet = tmp_path / "b023"
    bet.mkdir()
    # What the bet's state said when b023's deploy was refused: the PR was open, nothing merged.
    (bet / "state.json").write_text(json.dumps({"bet_id": "b023", "status": "pr_opened",
                                                "stages": {"ship": {"pr_number": 21}}}))
    return {"tmp": tmp_path, "keys": keys, "bet": bet}


def ship_deploy(ship, ssh_body: str):
    fake(ship["tmp"] / "bin", "ssh", ssh_body)
    return run_step("epd_deploy", {"bet_id": "b023", "bet_dir": str(ship["bet"]),
                                   "gate": {"answers": [{"selected": ["Merge and deploy"]}]}},
                    ship["tmp"], bin_dir=ship["tmp"] / "bin", swap={"/app/standee-ssh": str(ship["keys"])})


def test_a_deploy_the_driver_refused_fails_the_step(ship):
    status, out, said = ship_deploy(ship, 'echo "ERROR: PR #21 conflicts with master, so it was not merged" >&2\nexit 1\n')
    assert status == "failed", out
    assert "PR #21 conflicts with master" in said


def test_a_deploy_the_driver_did_is_read_back(ship):
    state = json.loads((ship["bet"] / "state.json").read_text())
    state["status"] = "shipped"
    state["stages"]["ship"].update(merge_sha="abc123def4567890", prod_env="rollcall-prod")
    (ship["bet"] / "state.json").write_text(json.dumps(state))
    status, out, said = ship_deploy(ship, 'echo "deployed"\nexit 0\n')
    assert status == "completed", said
    assert out["status"] == "shipped"
