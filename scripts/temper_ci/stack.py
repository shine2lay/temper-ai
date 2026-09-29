"""The throwaway temper a commit is checked in.

One commit, one stack: its own compose project name (``temper-box-<sha>``),
its own published ports, its own database (a tmpfs, so there is nothing to
leave behind), its own workspace tree, and no model keys at all. The live
``temper-ai`` project is never named on any command line here, and every
destructive call asserts the project name it is about to act on starts with
``temper-box-``.

The commit's own files are what runs: a worktree of that exact commit,
taken from a clone of temper-ai that temper-ci keeps for itself, so
``~/temper-ai`` is never checked out, fetched into or otherwise touched.

Runs happen in boxes, the way they do live: the stack's worker holds the
host's docker socket and starts a container per run from the stack's own
server container. A run therefore gets this stack's database and network,
never the live one's.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from . import paths
from .paths import MAIN_REPO, MIRROR, WORK, log, sh

COMPOSE_FILES = ("docker-compose.yml", "docker-compose.ci.yml")
UP_TIMEOUT = 300
API_TIMEOUT = 180


class BoxError(RuntimeError):
    pass


def _docker_gid() -> str:
    try:
        return str(Path("/var/run/docker.sock").stat().st_gid)
    except OSError:
        return "988"


def mirror() -> Path:
    """temper-ci's own clone of temper-ai, made once and fetched since.

    Its own, deliberately: making a worktree or fetching inside
    ``~/temper-ai`` would be changing the main folder, which nothing here is
    allowed to do.
    """
    MIRROR.parent.mkdir(parents=True, exist_ok=True)
    if not (MIRROR / "HEAD").exists() and not (MIRROR / ".git").exists():
        r = sh("git", "clone", "--quiet", "--bare", str(MAIN_REPO), str(MIRROR), timeout=600)
        if r.returncode:
            raise BoxError(f"could not clone {MAIN_REPO} into {MIRROR}: {r.stderr.strip()}")
        sh("git", "-C", str(MIRROR), "remote", "add", "upstream",
           f"https://github.com/{paths.GH_REPO}.git")
    return MIRROR


def fetch(ref: str = "") -> None:
    """Bring the mirror up to date with GitHub (and with the main folder)."""
    m = mirror()
    sh("git", "-C", str(m), "fetch", "--quiet", "--prune", "origin",
       "+refs/heads/*:refs/heads/*", timeout=300)
    sh("git", "-C", str(m), "fetch", "--quiet", "--prune", "upstream",
       "+refs/heads/*:refs/remotes/github/*", timeout=300)
    if ref:
        sh("git", "-C", str(m), "fetch", "--quiet", "upstream", ref, timeout=300)


def has_commit(sha: str) -> bool:
    return sh("git", "-C", str(mirror()), "cat-file", "-e", f"{sha}^{{commit}}").returncode == 0


def changed_files(sha: str) -> list[str]:
    """What this commit changed against its first parent (everything, for a root commit)."""
    m = mirror()
    parents = sh("git", "-C", str(m), "rev-list", "--parents", "-n", "1", sha).stdout.split()
    if len(parents) < 2:
        return sh("git", "-C", str(m), "ls-tree", "-r", "--name-only", sha).stdout.split("\n")
    r = sh("git", "-C", str(m), "diff", "--name-only", f"{sha}^", sha)
    return [f for f in r.stdout.split("\n") if f]


def tree_sha(sha: str) -> str:
    return sh("git", "-C", str(mirror()), "rev-parse", f"{sha}^{{tree}}").stdout.strip()


def docs_only(files: list[str]) -> bool:
    if not files:
        return False
    for f in files:
        if any(f.startswith(d) for d in paths.DOCS_DIRS):
            continue
        if any(f.lower().endswith(ext) for ext in paths.DOCS_ONLY):
            continue
        return False
    return True


def touches_image(files: list[str]) -> bool:
    return any(f in paths.IMAGE_INPUTS for f in files)


@dataclass
class Box:
    """A throwaway temper for one commit."""

    sha: str
    project: str = ""
    tree: Path = field(default_factory=Path)
    workspaces: Path = field(default_factory=Path)
    server_port: int = 0
    postgres_port: int = 0
    redis_port: int = 0
    env_file: Path = field(default_factory=Path)
    built: dict[str, str] = field(default_factory=dict)
    up_at: float = 0.0

    # -- setting up ---------------------------------------------------------

    def __post_init__(self) -> None:
        short = self.sha[:12]
        self.project = f"{paths.BOX_PREFIX}{short}"
        self.tree = WORK / short
        self.workspaces = WORK / f"{short}-workspaces"
        self.env_file = WORK / f"{short}.env"

    @property
    def api(self) -> str:
        return f"http://127.0.0.1:{self.server_port}"

    def _guard(self) -> None:
        if not self.project.startswith(paths.BOX_PREFIX) or self.project == paths.LIVE_PROJECT:
            raise BoxError(f"{self.project!r} is not a throwaway project name; refusing")

    def _compose(self, *args: str, timeout: int = 120) -> subprocess.CompletedProcess:
        self._guard()
        cmd = ["docker", "compose", "-p", self.project, "--env-file", str(self.env_file)]
        for f in COMPOSE_FILES:
            cmd += ["-f", f]
        # The worker lives behind a profile in the base file; every call here
        # needs to see it, `build` included.
        cmd += ["--profile", "worker"]
        return sh(*cmd, *args, cwd=self.tree, timeout=timeout)

    def checkout(self) -> None:
        """A worktree of the commit, in temper-ci's own clone."""
        if not has_commit(self.sha):
            fetch()
        if not has_commit(self.sha):
            raise BoxError(f"{self.sha} is not a commit this machine has, even after fetching")
        self.remove_tree()
        self.tree.parent.mkdir(parents=True, exist_ok=True)
        r = sh("git", "-C", str(mirror()), "worktree", "add", "--quiet", "--detach",
               str(self.tree), self.sha, timeout=300)
        if r.returncode:
            raise BoxError(f"could not check {self.sha} out into {self.tree}: {r.stderr.strip()}")
        self.workspaces.mkdir(parents=True, exist_ok=True)

    def write_env(self) -> None:
        self.server_port = paths.free_port()
        self.postgres_port = paths.free_port()
        self.redis_port = paths.free_port()
        lines = [
            "# Written by temper-ci for one commit's check. Not a copy of the live .env:",
            "# there are no model keys here, and no Slack, Telegram or Notion token.",
            f"COMPOSE_PROJECT_NAME={self.project}",
            f"TEMPER_CI_SERVER_PORT={self.server_port}",
            f"POSTGRES_PORT={self.postgres_port}",
            f"REDIS_PORT={self.redis_port}",
            f"PLAYWRIGHT_MCP_PORT={paths.free_port()}",
            "TEMPER_BIND=127.0.0.1",
            "FRONTEND_DIST=/dev/null",  # never used: the ci overlay drops that mount
            "POSTGRES_PASSWORD=box",
            f"WORKSPACE_DIR={self.workspaces}",
            f"TEMPER_CI_TEMPLATE_CONTAINER={self.project}-server-1",
            f"TEMPER_CI_IMAGE_SERVER=temper-ci-server:{self.sha[:12]}",
            f"TEMPER_CI_IMAGE_WORKER=temper-ci-worker:{self.sha[:12]}",
            f"DOCKER_GID={_docker_gid()}",
            "TEMPER_LOG_LEVEL=INFO",
            "TEMPER_CI_LINEAR_SECRET=box-linear-secret",
            "TEMPER_CI_NOTION_SECRET=box-notion-secret",
            "TEMPER_SLACK_TEST_TOKEN=box-slack-test-token",
        ]
        self.env_file.parent.mkdir(parents=True, exist_ok=True)
        self.env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def build(self) -> dict[str, str]:
        """Build the images this commit needs.

        Always asked for, never always done: docker's layer cache means a
        commit that changed no image input reuses every layer and this takes
        seconds, while one that changed the Dockerfile, the lock file or a
        package file really does build a new image — which is then the image
        the check runs, and the one the deploy afterwards reuses.
        """
        r = self._compose("build", "server", "worker", timeout=2400)
        if r.returncode:
            tail = "\n".join((r.stderr or r.stdout).strip().splitlines()[-25:])
            raise BoxError(f"building the images for {self.sha[:12]} failed:\n{tail}")
        for service in ("server", "worker"):
            got = self._compose("images", "--format", "json", service, timeout=60)
            try:
                rows = json.loads(got.stdout or "[]")
                self.built[service] = (rows[0].get("ID") or "")[:19] if rows else ""
            except (ValueError, IndexError, AttributeError):
                self.built[service] = ""
        return self.built

    def up(self) -> None:
        r = self._compose("up", "-d", "--no-build", "server", "worker", timeout=UP_TIMEOUT)
        if r.returncode:
            tail = "\n".join((r.stderr or r.stdout).strip().splitlines()[-25:])
            raise BoxError(f"the throwaway stack for {self.sha[:12]} did not come up:\n{tail}")
        self.up_at = time.time()
        self.wait_for_api()

    def wait_for_api(self, seconds: int = API_TIMEOUT) -> None:
        deadline = time.time() + seconds
        last = ""
        while time.time() < deadline:
            try:
                self.get("/api/health", timeout=5)
                return
            except Exception as exc:  # noqa: BLE001 - any failure means "not yet"
                last = str(exc)
                time.sleep(2)
        raise BoxError(f"the box's API never answered on {self.api} ({last})")

    # -- talking to it ------------------------------------------------------

    def request(self, method: str, path: str, body=None, timeout: int = 30,
                headers: dict[str, str] | None = None, raw: bytes | None = None):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(  # noqa: S310 - a fixed loopback address
            self.api + path, data=data, method=method,
            headers={"Content-Type": "application/json", **(headers or {})},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            text = resp.read().decode()
            try:
                return json.loads(text) if text else {}
            except ValueError:
                return {"_text": text}

    def get(self, path: str, timeout: int = 30):
        return self.request("GET", path, timeout=timeout)

    def get_with_token(self, path: str, timeout: int = 30):
        """A GET on the box's private test entry, with that entry's own token."""
        return self.request("GET", path, timeout=timeout,
                            headers={"X-Temper-Test-Token": "box-slack-test-token"})

    def post(self, path: str, body=None, timeout: int = 30, **kw):
        return self.request("POST", path, body, timeout=timeout, **kw)

    def status_of(self, method: str, path: str, raw: bytes = b"{}",
                  headers: dict[str, str] | None = None) -> tuple[int, str]:
        """The status code a call comes back with, errors included."""
        try:
            self.request(method, path, raw=raw, headers=headers, timeout=20)
            return 200, ""
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode()[:400]
        except Exception as exc:  # noqa: BLE001
            return 0, str(exc)

    # -- runs ---------------------------------------------------------------

    def start_run(self, workflow: str, inputs: dict | None = None) -> str:
        got = self.post("/api/runs", {"workflow": workflow, "inputs": inputs or {}}, timeout=60)
        run_id = got.get("execution_id") or got.get("id") or ""
        if not run_id:
            raise BoxError(f"starting {workflow} gave back no run id: {got}")
        return run_id

    def run_status(self, run_id: str) -> str:
        return str(self.get(f"/api/workflows/{run_id}").get("status") or "")

    def wait_for(self, run_id: str, want=("completed",), seconds: int = 240) -> str:
        """Wait until the run reaches one of `want` or a state it cannot leave."""
        settled = {"completed", "failed", "cancelled", "stopped", "error", "interrupted", "orphaned"}
        deadline = time.time() + seconds
        status = ""
        while time.time() < deadline:
            try:
                status = self.run_status(run_id)
            except Exception:  # noqa: BLE001 - the server may be restarting under us
                time.sleep(2)
                continue
            if status in want:
                return status
            if status in settled:
                raise BoxError(f"run {run_id[:8]} is {status}, and it was meant to reach {'/'.join(want)}")
            time.sleep(2)
        raise BoxError(f"run {run_id[:8]} was still {status or 'unknown'} after {seconds}s")

    def workspace_of(self, run_id: str) -> Path:
        """Where the run's files are on this host."""
        info = self.get(f"/api/workflows/{run_id}")
        for key in ("workspace_path", "workspace"):
            value = info.get(key)
            if value:
                return Path(str(value))
        return self.workspaces / run_id

    # -- looking at the containers -----------------------------------------

    def container(self, service: str) -> str:
        return f"{self.project}-{service}-1"

    def server_log(self, since: float | None = None) -> str:
        args = ["docker", "logs"]
        if since:
            args += ["--since", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(since))]
        r = sh(*args, self.container("server"), timeout=60)
        return (r.stdout or "") + (r.stderr or "")

    def restart_server(self) -> None:
        self._guard()
        r = sh("docker", "restart", self.container("server"), timeout=180)
        if r.returncode:
            raise BoxError(f"could not restart the box's server: {r.stderr.strip()}")
        self.wait_for_api()

    # -- tearing down -------------------------------------------------------

    def remove_tree(self) -> None:
        if self.tree.exists():
            sh("git", "-C", str(mirror()), "worktree", "remove", "--force", str(self.tree), timeout=120)
        if self.tree.exists():
            shutil.rmtree(self.tree, ignore_errors=True)
        sh("git", "-C", str(mirror()), "worktree", "prune", timeout=60)

    def down(self) -> None:
        """Everything this box made, gone: containers, network, volumes, files."""
        self._guard()
        # Run containers the worker started are the box's children, but they
        # are not in its compose project, so `down` would leave them.
        leftovers = sh("docker", "ps", "-aq", "--filter", "label=temper.role=run",
                       "--filter", f"network={self.project}_default", timeout=60).stdout.split()
        for cid in leftovers:
            sh("docker", "rm", "-f", cid, timeout=60)
        self._compose("down", "-v", "--remove-orphans", "-t", "10", timeout=300)
        self.remove_tree()
        shutil.rmtree(self.workspaces, ignore_errors=True)
        self.env_file.unlink(missing_ok=True)

    # -- the whole thing ----------------------------------------------------

    def __enter__(self) -> Box:
        self.checkout()
        self.write_env()
        log(f"{self.project}: building the images")
        self.build()
        log(f"{self.project}: starting it on {self.api}")
        self.up()
        return self

    def __exit__(self, *exc) -> None:
        try:
            self.down()
        except Exception as err:  # noqa: BLE001 - tearing down must not hide the real failure
            log(f"{self.project}: tearing down had a problem: {err}")


def live_fingerprint() -> dict[str, str]:
    """Enough about the live stack to prove a box never touched it."""
    out: dict[str, str] = {}
    for container in ("temper-ai-server-1", "temper-ai-worker-1", "temper-ai-postgres-1"):
        r = sh("docker", "inspect", "-f", "{{.State.StartedAt}} {{.State.Status}}", container, timeout=30)
        out[container] = r.stdout.strip() or "missing"
    r = sh("docker", "exec", "temper-ai-postgres-1", "psql", "-U", "temper_ai", "-d", "temper_ai",
           "-tAc", "select count(*) from workflow_runs", timeout=30)
    out["workflow_runs"] = r.stdout.strip() or "?"
    r = sh("docker", "exec", "temper-ai-postgres-1", "psql", "-U", "temper_ai", "-d", "temper_ai",
           "-tAc", "select count(*) from events", timeout=30)
    out["events"] = r.stdout.strip() or "?"
    return out
