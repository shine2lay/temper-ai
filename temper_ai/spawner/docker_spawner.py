"""DockerSpawner — one container per run: a copy of the worker's, minus the socket.

The worker container is the trusted control plane: it holds the host's
docker socket (docker-compose.host-docker.yml) and uses it for exactly one
thing, starting a sibling container per queued run. The run container is
where the workflow's nodes execute, and it is what the sandbox has always
been documented as: the boundary around a run. Inside it the workspace
check and the platform baseline policy are guardrails; outside it there is
nothing of the host to reach.

What a run container is, precisely:

  image     the worker's own image (so the run has the same toolchain and
            the same temper_ai), unless TEMPER_DOCKER_IMAGE says otherwise
  env       the worker's environment (DB URL, Redis URL, provider keys) plus
            TEMPER_RUN_CONTAINER=<its own name>
  network   the worker's networks (postgres/redis by compose name)
  mounts    the worker's read-only mounts (source, configs, credentials,
            claude binaries) as they are; the docker socket never; the
            broad workspaces tree (the worker's one host-equivalent mount,
            `WORKSPACE_DIR:WORKSPACE_DIR`) replaced by the run's own
            workspace, read-write, at the same host path — plus the git
            main repository when that workspace is a `git worktree`, since
            worktree operations write to the main repo's .git
  /tmp      its own: the scratch dir dies with the container
  identity  --name and --hostname temper-run-<execution_id>, labels
            temper.role=run and temper.execution_id; --rm, --init (a PID 1
            that reaps the tools a node forks), no-new-privileges

What it does not change: the run still executes as the worker's uid with
the worker's credentials mounted (claude_code needs them), and the node's
Bash is still gated by the allowlist and the platform baseline inside.
Those are guardrails inside the sandbox now, which is what they were
always documented as.

The worker discovers all of that by inspecting itself (`docker inspect
$HOSTNAME` — docker sets a container's hostname to its id). Set
TEMPER_DOCKER_TEMPLATE_CONTAINER when the hostname is not the container.

Handles: the container name is derived from the execution_id, so
is_alive() and kill() work from the row alone — across worker restarts,
and regardless of what the run writes into spawner_handle.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import subprocess  # noqa: S404 — intentional: this is the spawner
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from temper_ai.spawner.base import Spawner, SpawnerError
from temper_ai.worker_proto import ProcessHandle, SpawnerKind

logger = logging.getLogger(__name__)

DOCKER_SOCKET = "/var/run/docker.sock"
CONTAINER_PREFIX = "temper-run-"
RUN_COMMAND = ["uv", "run", "python", "-m", "temper_ai.cli.main", "run-workflow"]

# `docker inspect` on a name that does not exist exits 1 with this on stderr.
_NO_SUCH = ("No such container", "No such object")


def container_name(execution_id: str) -> str:
    return f"{CONTAINER_PREFIX}{execution_id}"


@dataclass(frozen=True)
class Mount:
    source: str
    target: str
    read_only: bool

    def to_arg(self) -> str:
        # --mount, not -v: -v silently creates a missing host path as root;
        # --mount refuses, which is the error we want to see.
        arg = f"type=bind,source={self.source},target={self.target}"
        return arg + ",readonly" if self.read_only else arg


@dataclass(frozen=True)
class Template:
    """What the worker container looks like, read once from `docker inspect`."""

    image: str
    env: list[str]
    mounts: list[Mount]
    networks: list[str]
    extra_hosts: list[str]

    @classmethod
    def from_inspect(cls, info: dict) -> Template:
        config = info.get("Config") or {}
        host_config = info.get("HostConfig") or {}
        mounts = [
            Mount(
                source=m["Source"],
                target=m["Destination"],
                read_only=not m.get("RW", True),
            )
            for m in info.get("Mounts") or []
            if m.get("Type") == "bind"
        ]
        networks = list(((info.get("NetworkSettings") or {}).get("Networks") or {}).keys())
        return cls(
            image=config.get("Image") or "",
            env=list(config.get("Env") or []),
            mounts=mounts,
            networks=networks,
            extra_hosts=list(host_config.get("ExtraHosts") or []),
        )


def _lookup_workspace_path(execution_id: str) -> str | None:
    """The run's workspace from its WorkflowRun row ('' when the run has none)."""
    from sqlmodel import select

    from temper_ai.database import get_session
    from temper_ai.runner.models import WorkflowRun

    with get_session() as session:
        row = session.exec(
            select(WorkflowRun).where(WorkflowRun.execution_id == execution_id),
        ).first()
        return None if row is None else row.workspace_path


def workspace_mounts(workspace_path: str) -> list[Mount]:
    """The run's workspace, read-write, at its host path — and, when it is a
    git worktree, the main repository too (its `.git` is a file pointing at
    `<main>/.git/worktrees/<name>`; git in the worktree reads and writes there).
    """
    workspace = Path(workspace_path)
    if not workspace.is_dir():
        raise SpawnerError(
            f"Workspace {workspace_path!r} is not a directory on this host — "
            "the run container needs it bind-mounted at the same path",
        )
    mounts = [Mount(str(workspace), str(workspace), read_only=False)]
    main_repo = _git_main_repo(workspace)
    if main_repo is not None and not _is_relative_to(main_repo, workspace):
        mounts.append(Mount(str(main_repo), str(main_repo), read_only=False))
    return mounts


def _git_main_repo(workspace: Path) -> Path | None:
    dot_git = workspace / ".git"
    if not dot_git.is_file():
        return None
    try:
        first = dot_git.read_text().splitlines()[0]
    except (OSError, IndexError):
        return None
    if not first.startswith("gitdir:"):
        return None
    gitdir = Path(first[len("gitdir:"):].strip())
    if not gitdir.is_absolute():
        gitdir = (workspace / gitdir).resolve()
    # <main>/.git/worktrees/<name> → <main>
    for parent in gitdir.parents:
        if parent.name == ".git":
            return parent.parent
    return None


def _is_relative_to(path: Path, other: Path) -> bool:
    try:
        path.relative_to(other)
    except ValueError:
        return False
    return True


def _passes_through(mount: Mount) -> bool:
    """Which of the worker's mounts a run inherits.

    Never the docker socket. Not the host-equivalent mount (source == target):
    by the compose convention that is the whole workspaces tree, and the run
    gets only its own workspace instead (see workspace_mounts).
    """
    if mount.target == DOCKER_SOCKET or mount.source == DOCKER_SOCKET:
        return False
    return mount.source != mount.target


class DockerSpawner(Spawner):
    kind = SpawnerKind.docker

    def __init__(
        self,
        *,
        docker_bin: str = "docker",
        template_container: str | None = None,
        image: str | None = None,
        workspace_lookup: Callable[[str], str | None] = _lookup_workspace_path,
        run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    ) -> None:
        self._docker = docker_bin
        self._template_container = (
            template_container
            or os.environ.get("TEMPER_DOCKER_TEMPLATE_CONTAINER")
            or socket.gethostname()
        )
        self._image_override = image or os.environ.get("TEMPER_DOCKER_IMAGE")
        self._workspace_lookup = workspace_lookup
        self._run = run
        self._template: Template | None = None

    # -- Spawner contract -----------------------------------------------------

    def spawn(self, execution_id: str) -> ProcessHandle:
        workspace_path = self._workspace_lookup(execution_id)
        if workspace_path is None:
            raise SpawnerError(f"No WorkflowRun row for execution_id={execution_id}")
        template = self.template()
        name = container_name(execution_id)
        cmd = self.run_command(execution_id, workspace_path, template)

        result = self._docker_run(cmd)
        if result.returncode != 0:
            raise SpawnerError(
                f"docker run failed for {execution_id} (exit {result.returncode}): "
                f"{result.stderr.strip()}",
            )
        container_id = result.stdout.strip()
        logger.info(
            "Spawned run container %s (%s) for execution_id=%s",
            name, container_id[:12], execution_id,
        )
        return ProcessHandle(
            kind=SpawnerKind.docker,
            handle=name,
            metadata={
                "execution_id": execution_id,
                "container_id": container_id,
                "image": template.image if self._image_override is None else self._image_override,
            },
        )

    def is_alive(self, handle: ProcessHandle) -> bool:
        result = self._docker_run(
            [self._docker, "inspect", "--format", "{{.State.Running}}", self._name_for(handle)],
        )
        if result.returncode != 0:
            return False  # gone: --rm removed it on exit, or it never started
        return result.stdout.strip() == "true"

    def kill(self, handle: ProcessHandle, *, force: bool = False) -> None:
        name = self._name_for(handle)
        sig = "KILL" if force else "TERM"
        result = self._docker_run([self._docker, "kill", "--signal", sig, name])
        if result.returncode == 0:
            logger.info("Sent SIG%s to run container %s", sig, name)
            return
        if any(marker in result.stderr for marker in _NO_SUCH) or "is not running" in result.stderr:
            logger.debug("Run container %s already gone", name)
            return
        raise SpawnerError(f"docker kill -s {sig} {name} failed: {result.stderr.strip()}")

    # -- Building the run container ------------------------------------------

    def template(self) -> Template:
        """The worker's own container, inspected once and cached."""
        if self._template is None:
            result = self._docker_run([self._docker, "inspect", self._template_container])
            if result.returncode != 0:
                raise SpawnerError(
                    f"Cannot inspect the worker's own container "
                    f"{self._template_container!r} to template runs from it "
                    f"(is the docker socket mounted? see docker-compose.host-docker.yml): "
                    f"{result.stderr.strip()}",
                )
            try:
                info = json.loads(result.stdout)[0]
            except (ValueError, IndexError, TypeError) as exc:
                raise SpawnerError(f"Unexpected `docker inspect` output: {exc}") from exc
            self._template = Template.from_inspect(info)
            if not self._template.image:
                raise SpawnerError("The worker's container reports no image to template runs from")
        return self._template

    def run_command(
        self, execution_id: str, workspace_path: str, template: Template,
    ) -> list[str]:
        name = container_name(execution_id)
        cmd = [
            self._docker, "run", "--detach", "--rm", "--init",
            "--name", name, "--hostname", name,
            "--label", "temper.role=run",
            "--label", f"temper.execution_id={execution_id}",
            "--security-opt", "no-new-privileges",
        ]
        for network in template.networks[:1]:
            cmd += ["--network", network]
        for host in template.extra_hosts:
            cmd += ["--add-host", host]
        for var in template.env:
            if not var.startswith("TEMPER_RUN_CONTAINER="):
                cmd += ["--env", var]
        cmd += ["--env", f"TEMPER_RUN_CONTAINER={name}"]
        for mount in template.mounts:
            if _passes_through(mount):
                cmd += ["--mount", mount.to_arg()]
        if workspace_path:
            for mount in workspace_mounts(workspace_path):
                cmd += ["--mount", mount.to_arg()]
        cmd += self._resource_limits()
        cmd.append(self._image_override or template.image)
        cmd += [*RUN_COMMAND, "--execution-id", execution_id]
        return cmd

    @staticmethod
    def _resource_limits() -> list[str]:
        """Optional caps from the worker's env; none by default."""
        limits = []
        if memory := os.environ.get("TEMPER_DOCKER_MEMORY"):
            limits += ["--memory", memory]
        if cpus := os.environ.get("TEMPER_DOCKER_CPUS"):
            limits += ["--cpus", cpus]
        if pids := os.environ.get("TEMPER_DOCKER_PIDS_LIMIT"):
            limits += ["--pids-limit", pids]
        return limits

    # -- Plumbing -------------------------------------------------------------

    @staticmethod
    def _name_for(handle: ProcessHandle) -> str:
        execution_id = handle.metadata.get("execution_id")
        if execution_id:
            return container_name(execution_id)
        if handle.handle.startswith(CONTAINER_PREFIX):
            return handle.handle
        raise SpawnerError(f"Cannot derive a run container from handle {handle.handle!r}")

    def _docker_run(self, cmd: list[str]) -> subprocess.CompletedProcess:
        try:
            return self._run(  # noqa: S603 — args are a list, no shell
                cmd, capture_output=True, text=True, check=False, timeout=60,
            )
        except FileNotFoundError as exc:
            raise SpawnerError(f"{self._docker!r} not found on PATH: {exc}") from exc
        except subprocess.TimeoutExpired as exc:
            raise SpawnerError(f"{' '.join(cmd[:2])} timed out after 60s") from exc
