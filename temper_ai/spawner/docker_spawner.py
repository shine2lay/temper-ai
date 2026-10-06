"""DockerSpawner — one container per run: a copy of a template container, minus the socket.

The worker container is the trusted control plane: it holds the host's
docker socket (docker-compose.host-docker.yml) and uses it for exactly one
thing, starting a sibling container per queued run. The run container is
where the workflow's nodes execute, and it is what the sandbox has always
been documented as: the boundary around a run. Inside it the workspace
check and the platform baseline policy are guardrails; outside it there is
nothing of the host to reach.

The template is the worker's own container by default. Set
TEMPER_DOCKER_TEMPLATE_CONTAINER to copy another one instead: pointing it
at the server's container gives each run exactly what it had when it ran
inside the server (the same image, user, files and keys), and a server
recreated with a new key or image passes it on to the next run. The
template is read again for every run.

What a run container is, precisely:

  image     the template's image (so the run has the same toolchain and
            the same temper_ai), unless TEMPER_DOCKER_IMAGE says otherwise
  env       only the template's variables named on the box's allow-list
            (configs/boxes/env.yaml + configs/boxes/local/env.yaml,
            shared/box_env.py), plus TEMPER_RUN_CONTAINER=<its own name>;
            each spawn logs the names it left out. TEMPER_BOX_ENV=inherit
            (emergency rollback) copies everything but the GitHub app's
            keys, and warns on every spawn
  network   the template's first network (postgres/redis by compose name)
  command   `uv run python -m temper_ai.cli.main run-workflow`, or
            TEMPER_DOCKER_RUN_COMMAND
  mounts    the template's bind mounts (source, configs, credentials,
            claude binaries) as they are; the docker socket never; the
            broad workspaces tree (the template's one host-equivalent mount,
            `WORKSPACE_DIR:WORKSPACE_DIR`) replaced by the run's own
            workspace, read-write, at the same host path — plus the git
            main repository when that workspace is a `git worktree`, since
            worktree operations write to the main repo's .git.
            TEMPER_DOCKER_WORKSPACES=all keeps the whole tree instead (runs
            here share folders under it, as they did inside the server);
            a run's workspace inside an inherited mount is not mounted again
  ~/.claude its own small tmpfs, writable by the run's user, when the
            credentials file is mounted inside it: the Claude CLI saves its
            sessions there, and a node's next turn resumes from them
  /tmp      its own: the scratch dir dies with the container
  identity  --name and --hostname temper-run-<execution_id>, labels
            temper.role=run and temper.execution_id; --rm, --init (a PID 1
            that reaps the tools a node forks), no-new-privileges
  health    none: the image's HEALTHCHECK asks for the server's port,
            which nothing in a run container listens on, so every run
            would show as "unhealthy" in `docker ps`

What it does not change: the run still executes as the template's user
with the template's credentials mounted (claude_code needs them), and the
node's Bash is still gated by the allowlist and the platform baseline
inside. Those are guardrails inside the sandbox now, which is what they
were always documented as.

The worker discovers all of that with `docker inspect` on the template
(by default $HOSTNAME — docker sets a container's hostname to its id).

That is the legacy box, still the default. TEMPER_BOX_RUNTIME_BOUNDARY=sealed
(box secrets BS1, docs/boxes.md) builds another kind instead: none of the
template's mounts are inherited, only a positive list of grants is mounted,
each pinned from the worker's check to docker's use (box_seal.py); the image
is taken by its id, the root filesystem is read-only, every capability is
dropped and the runner starts with a fixed interpreter, PATH and HOME. Each
box, of either kind, gets a box profile compiled here before `docker run`
(box_profile.py): it is stored on the run's row and handed to the box, which
checks it before anything runs.

TEMPER_BOX_SECRET_BOOTSTRAP=oneshot (box secrets BS2, sealed boxes only) keeps
secrets out of the box's environment altogether: docker gets only the names the box
list declares safe for tools and the spawner's own settings, and the rest reaches the
runner once, through box_bootstrap.py, after it has made itself non-dumpable. The
spawn returns only when the runner has acknowledged its delivery; otherwise the box
is stopped and the delivery recorded as revoked.

Handles: the container name is derived from the execution_id, so
is_alive() and kill() work from the row alone — across worker restarts,
and regardless of what the run writes into spawner_handle.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shlex
import socket
import subprocess  # noqa: S404 — intentional: this is the spawner
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from temper_ai.integrations.github import secret as github_secret
from temper_ai.shared import box_env as box_env_list
from temper_ai.shared.clock import utcnow
from temper_ai.spawner import (
    box_bootstrap,
    box_launches,
    box_profile,
    box_seal,
    box_view,
)
from temper_ai.spawner.base import Spawner, SpawnerBusy, SpawnerError
from temper_ai.spawner.box_profile import BoxProfileError
from temper_ai.worker_proto import ProcessHandle, SpawnerKind

logger = logging.getLogger(__name__)

DOCKER_SOCKET = "/var/run/docker.sock"
CONTAINER_PREFIX = "temper-run-"
RUN_COMMAND = ["uv", "run", "python", "-m", "temper_ai.cli.main", "run-workflow"]
# How long a run waits for a template container that can't be read (it is
# being recreated, say) when there is no earlier look to fall back on.
TEMPLATE_GRACE_SECONDS = 120.0

#: What a sealed box runs: the template image's own interpreter, isolated (-I: no
#: PYTHON* variables, no user site, no current folder on the import path).
SEALED_ARGS = ["-I", "-m", "temper_ai.cli.main", "run-workflow"]
#: What a sealed box runs first: the box check, as source the worker holds (read when this
#: module loads), so the check of the mounts doesn't come from a mount it checks.
BOOT_PROGRAM = box_view.boot_program()
BOOT_DIGEST = "sha256:" + hashlib.sha256(BOOT_PROGRAM.encode("utf-8")).hexdigest()
#: Variables a sealed box never takes from the template: the spawner fixes PATH and HOME,
#: and none of these may steer what the runner loads.
SEALED_DROP = frozenset({
    "PATH", "HOME", "PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONUSERBASE",
    "PYTHONINSPECT", "LD_PRELOAD", "LD_LIBRARY_PATH", "LD_AUDIT", "BASH_ENV", "ENV",
    "TEMPER_LOG_DIR", "CLAUDE_CONFIG_DIR", "DISABLE_AUTOUPDATER",
})
#: What the spawner sets in a sealed box itself: logs and the Claude CLI's state go to
#: the box's own tmpfs, and the CLI never updates itself.
SEALED_SET = {"TEMPER_LOG_DIR": "/tmp/temper-logs",
              "CLAUDE_CONFIG_DIR": box_seal.CLAUDE_STATE, "DISABLE_AUTOUPDATER": "1"}
#: The provider agents that name none use (shared/types.py resolve_provider). A sealed box
#: is given the one its launch was classified with; unset, those launches are refused.
DEFAULT_PROVIDER_ENV = "TEMPER_DEFAULT_PROVIDER"
#: What the worker runs in a oneshot box to deliver its secrets: box_bootstrap.py's own
#: source, held by the worker (like BOOT_PROGRAM), never a file from a mount.
WRITER_PROGRAM = box_bootstrap.writer_program()
WRITER_DIGEST = "sha256:" + hashlib.sha256(WRITER_PROGRAM.encode("utf-8")).hexdigest()
#: Names a oneshot box's docker environment may carry besides the tools' list: the
#: spawner's own fixed settings and the profile it checks itself with.
_FIXED_PLAIN = frozenset({"PATH", "HOME", box_env_list.RUN_CONTAINER_ENV, DEFAULT_PROVIDER_ENV,
                          *SEALED_SET, box_view.PROFILE_ENV, box_view.DIGEST_ENV,
                          box_view.GENERATION_ENV})
#: A URL with a password in it, or a run's GitHub key: secret whatever the name says.
_SECRET_VALUE = re.compile(r"://[^/\s@:]*:[^/\s@]+@")
#: A variable the python base images bake in, named like a key but public: the release
#: manager's signing-key fingerprint. Allowed only when the value is a fingerprint.
_PUBLIC_BAKED = {"GPG_KEY": re.compile(r"^[0-9A-Fa-f]{16,64}$")}


def value_looks_secret(value: str) -> bool:
    return bool(_SECRET_VALUE.search(value)) or value.startswith(box_env_list.RUN_GITHUB_KEY_PREFIX)


def split_delivery(box_env: Iterable[str],
                   agent_tools: Iterable[str]) -> tuple[list[str], dict[str, str]]:
    """A oneshot box's variables: what docker may carry, and what is delivered instead.

    Docker carries a name only when the box list declares it safe for tools or the
    spawner set it itself, and neither its name nor its value looks secret. Everything
    else (the database URL, the secret key, model, GitHub, Notion and other tokens, the
    runner's own settings) is delivered; tools still see the declared names, from the
    runner's environment mapping (shared/agent_env.py).
    """
    tools = frozenset(agent_tools)
    plain: list[str] = []
    delivered: dict[str, str] = {}
    for var in box_env:
        name, _, value = var.partition("=")
        if ((name in _FIXED_PLAIN or name in tools) and not box_env_list.looks_secret(name)
                and not value_looks_secret(value)):
            plain.append(var)
        else:
            delivered[name] = value
    return plain, delivered


def secrets_in_command(cmd: Iterable[str], delivered: Mapping[str, str]) -> list[str]:
    """Names of delivered secrets whose value shows up in a docker command (and so inspect)."""
    parts = list(cmd)
    return sorted(name for name, value in delivered.items()
                  if len(value) >= 8
                  and (box_env_list.looks_secret(name) or value_looks_secret(value))
                  and any(value in part for part in parts))

#: Launch sites found per scanned tree: (worker path, prefix, entries, tree digest) -> sites.
_SITES: dict[tuple[str, str, tuple[str, ...], str], frozenset[str]] = {}


def _launch_sites(path: str, prefix: str, entries: tuple[str, ...],
                  digest: str | None) -> frozenset[str]:
    if not digest:
        return frozenset(box_launches.launch_sites(path, prefix=prefix, only=entries))
    key = (path, prefix, entries, digest)
    if key not in _SITES:
        _SITES[key] = frozenset(box_launches.launch_sites(path, prefix=prefix, only=entries))
    return _SITES[key]

# `docker inspect` on a name that does not exist exits 1 with this on stderr.
# Lower case, matched against lower-cased stderr: docker 29's CLI writes "error: no such object: X"
# where older ones wrote "Error: No such object: X". Matched as written, a run container that --rm
# had removed never counted as gone, and the reaper left its run "running" for good (2026-09-27,
# queue task 9's resume probe: its killed run, and every run of a box that dies, never ended).
_NO_SUCH = ("no such container", "no such object")


def _delivery_status(result: subprocess.CompletedProcess) -> dict:
    """The writer's status line (its last JSON line), or what docker said instead (safe text)."""
    out = result.stdout.decode("utf-8", "replace") if isinstance(result.stdout, bytes) \
        else str(result.stdout or "")
    for line in reversed(out.strip().splitlines()):
        try:
            status = json.loads(line)
        except ValueError:
            continue
        if isinstance(status, dict) and status.get("state"):
            return {"state": str(status["state"]), "reason": str(status.get("reason") or "")}
    err = result.stderr.decode("utf-8", "replace") if isinstance(result.stderr, bytes) \
        else str(result.stderr or "")
    said = err.strip().splitlines()[-1][:200] if err.strip() else "nothing"
    return {"state": "error",
            "reason": f"the writer gave no status (exit {result.returncode}; docker said: {said})"}


def _says_gone(stderr: str) -> bool:
    """Whether docker's error says the container does not exist (any docker version's wording)."""
    said = stderr.lower()
    return any(marker in said for marker in _NO_SUCH)


@dataclass(frozen=True)
class BoxEnvSplit:
    """The template's variables a box gets, and the names it leaves out."""

    mode: str
    kept: tuple[str, ...]      # NAME=value entries, as docker run takes them
    dropped: tuple[str, ...]   # names only, sorted
    agent_tools: frozenset[str] = frozenset()  # names the list declares safe for tools

    @classmethod
    def of(cls, template_env: Iterable[str], mode: str,
           allowed: box_env_list.BoxEnv | None) -> BoxEnvSplit:
        kept: list[str] = []
        dropped: set[str] = set()
        for var in template_env:
            name = var.split("=", 1)[0]
            if name == box_env_list.RUN_CONTAINER_ENV:
                continue  # set below to the box's own name
            # The GitHub app's key stays in the server, in every mode: a box's shell
            # could read the environment the box started with (integrations.github.secret).
            # So do the Pi switch and box config: Pi steps never run in a run box (SW-42).
            if name in github_secret.SERVER_ONLY or name in box_env_list.PI_ONLY:
                dropped.add(name)
            elif mode == box_env_list.MODE_INHERIT or (allowed is not None and allowed.allows(name)):
                kept.append(var)
            else:
                dropped.add(name)
        if mode == box_env_list.MODE_INHERIT:
            # The box's tools read the switch too (shared/agent_env.py).
            kept = [v for v in kept if v.split("=", 1)[0] != box_env_list.MODE_ENV]
            kept.append(f"{box_env_list.MODE_ENV}={box_env_list.MODE_INHERIT}")
        return cls(mode=mode, kept=tuple(kept), dropped=tuple(sorted(dropped)),
                   agent_tools=frozenset(allowed.agent_tools) if allowed is not None else frozenset())


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
    image_id: str = ""     # the image's content id (sha256:...): what a sealed box runs
    user: str = ""
    working_dir: str = ""

    def env_value(self, name: str) -> str | None:
        for var in self.env:
            key, _, value = var.partition("=")
            if key == name:
                return value
        return None

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
            image_id=info.get("Image") or "",
            user=config.get("User") or "",
            working_dir=config.get("WorkingDir") or "",
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


def workspace_mounts(workspace_path: str, covered: Iterable[Mount] = ()) -> list[Mount]:
    """The run's workspace, read-write, at its host path — and, when it is a
    git worktree, the main repository too (its `.git` is a file pointing at
    `<main>/.git/worktrees/<name>`; git in the worktree reads and writes there).

    ``covered`` are the mounts the run already inherits: a path inside one of
    them is left out (it is there already, and inside the worker it may not
    be a host path at all, like /app/workspaces).
    """
    covered = list(covered)
    workspace = Path(workspace_path)
    inside = _inside_any(workspace, covered)
    if not inside and not workspace.is_dir():
        raise SpawnerError(
            f"Workspace {workspace_path!r} is not a directory on this host — "
            "the run container needs it bind-mounted at the same path",
        )
    mounts = [] if inside else [Mount(str(workspace), str(workspace), read_only=False)]
    main_repo = _git_main_repo(workspace) if workspace.is_dir() else None
    if (main_repo is not None and not _is_relative_to(main_repo, workspace)
            and not _inside_any(main_repo, covered)):
        mounts.append(Mount(str(main_repo), str(main_repo), read_only=False))
    return mounts


def _inside_any(path: Path, mounts: list[Mount]) -> bool:
    return any(_is_relative_to(path, Path(m.target)) for m in mounts)


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


def _passes_through(mount: Mount, all_workspaces: bool = False) -> bool:
    """Which of the worker's mounts a run inherits.

    Never the docker socket. Not the host-equivalent mount (source == target):
    by the compose convention that is the whole workspaces tree, and the run
    gets only its own workspace instead (see workspace_mounts), unless
    ``all_workspaces`` (TEMPER_DOCKER_WORKSPACES=all), where runs see the
    whole tree, as runs inside the server always have.
    """
    if mount.target == DOCKER_SOCKET or mount.source == DOCKER_SOCKET:
        return False
    return all_workspaces or mount.source != mount.target


def _run_command() -> list[str]:
    """What the run container executes (before --execution-id).

    TEMPER_DOCKER_RUN_COMMAND overrides the default, e.g. with the template
    image's own interpreter (`.venv/bin/python -m temper_ai.cli.main
    run-workflow`) where `uv run` would first sync the environment.
    """
    override = os.environ.get("TEMPER_DOCKER_RUN_COMMAND", "").strip()
    return shlex.split(override) if override else list(RUN_COMMAND)


def _workspace_forms(workspace_path: str, workspace_dir: str | None) -> list[str]:
    """The ways a run's row may spell this workspace: its host path and the /app/workspaces alias."""
    forms = [workspace_path]
    if workspace_dir and workspace_path.startswith(workspace_dir.rstrip("/") + "/"):
        forms.append(box_seal.WORKSPACES_ALIAS + workspace_path[len(workspace_dir.rstrip("/")):])
    return forms


def _all_workspaces() -> bool:
    return os.environ.get("TEMPER_DOCKER_WORKSPACES", "own").strip().lower() == "all"


def _claude_homes(mounts: list[Mount]) -> list[str]:
    """`~/.claude` directories that a file mount (the credentials) sits in.

    Docker makes the missing directory for such a mount root-owned, and the
    Claude CLI then cannot save its sessions there, so a node's next turn
    cannot pick its conversation back up (--resume). The run gets that
    directory as a small tmpfs of its own, owned by the run's user.
    """
    homes: list[str] = []
    for mount in mounts:
        marker = mount.target.find("/.claude/")
        if marker >= 0:
            home = mount.target[: marker + len("/.claude")]
            if home not in homes:
                homes.append(home)
    return homes


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
        clock: Callable[[], float] = time.monotonic,
        box_env: Callable[[], box_env_list.BoxEnv] = box_env_list.load_box_env,
        profile_store: box_profile.ProfileStore | None = None,
        worker_view: box_seal.WorkerView | None = None,
        engine_launches: Mapping[str, str] | None = None,
        delivery_limits: Mapping[str, int] | None = None,
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
        self._clock = clock
        self._box_env = box_env
        self._store = profile_store if profile_store is not None else box_profile.DbProfileStore()
        self._worker_view_given = worker_view
        # The engine's classified launch sites (None: the table shipped with this code,
        # box_launches.ENGINE_LAUNCHES). Trusted code only, never anything a run controls.
        self._engine_table = engine_launches
        # A oneshot delivery's bounds and deadlines (None: box_bootstrap.LIMITS). Trusted
        # code only: they go into the profile the box obeys.
        self._delivery_limits = dict(delivery_limits) if delivery_limits else None
        self._box_ids_seen: dict[tuple[str, str], tuple[int, int]] = {}
        self._image_env_seen: dict[str, list[str]] = {}
        self._template: Template | None = None
        self._template_missing_since: float | None = None

    # -- Spawner contract -----------------------------------------------------

    def spawn(self, execution_id: str) -> ProcessHandle:
        workspace_path = self._workspace_lookup(execution_id)
        if workspace_path is None:
            raise SpawnerError(f"No WorkflowRun row for execution_id={execution_id}")
        settings = box_profile.install_settings()
        template = self.template()
        name = container_name(execution_id)
        env = self.env_split(template)
        if env.mode == box_env_list.MODE_INHERIT:
            logger.warning(
                "Run container %s inherits the template's whole environment "
                "(%s=inherit, the emergency rollback): its agents can read every secret in it",
                name, box_env_list.MODE_ENV,
            )
        if env.dropped:
            logger.info(
                "Run container %s: left out %d variable(s) not on the box list: %s",
                name, len(env.dropped), ", ".join(env.dropped),
            )
        if settings[box_profile.BOUNDARY_ENV] == box_profile.SEALED:
            return self._spawn_sealed(execution_id, workspace_path, template, env, settings)

        record = self._legacy_record(execution_id, workspace_path, template, env, settings)
        extra = box_profile.env_for(record["doc"]) if record else None
        cmd = self.run_command(execution_id, workspace_path, template, env, extra_env=extra)
        result = self._docker_run(cmd)
        return self._handle(execution_id, result, self._image_override or template.image, record)

    def _handle(self, execution_id: str, result: subprocess.CompletedProcess, image: str,
                record: dict | None) -> ProcessHandle:
        name = container_name(execution_id)
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
        metadata = {"execution_id": execution_id, "container_id": container_id, "image": image}
        if record is not None:
            # The row has it already (stored before docker run); the handle carries it too,
            # because some callers replace spawner_metadata with the handle's (api/routes.py).
            metadata[box_profile.METADATA_KEY] = record
        return ProcessHandle(kind=SpawnerKind.docker, handle=name, metadata=metadata)

    # -- Box profiles ---------------------------------------------------------

    def _legacy_record(self, execution_id: str, workspace_path: str, template: Template,
                       env: BoxEnvSplit, settings: dict[str, str]) -> dict | None:
        """A legacy box's profile, stored on the row; None (the box starts as before) on trouble.

        The profile machinery never stops a legacy box, with one exception: a run that
        ever had a sealed box is never given a legacy one (BoxProfileError).
        """
        facts = None
        try:
            facts = self._store.load(execution_id)
            previous = box_profile.stored_profile(facts.metadata if facts else None)
        except Exception as exc:  # noqa: BLE001 - a legacy box starts without a profile then
            raw = (facts.metadata if facts else {}).get(box_profile.METADATA_KEY)
            if box_profile.looks_sealed(raw):
                raise BoxProfileError(
                    f"run {execution_id} had a sealed box and its stored profile can't be read "
                    f"({exc}); no legacy box is started for it",
                ) from exc
            logger.warning("Run container %s: no box profile (%s); it starts without one",
                           container_name(execution_id), exc)
            return None
        generation = box_profile.next_generation(previous, box_profile.LEGACY)
        try:
            homes, mounts = self.legacy_mounts(workspace_path, template)
            workspaces = template.env_value("WORKSPACE_DIR")
            inherited = [{"source": m.source, "target": m.target, "read_only": m.read_only,
                          "kind": "inherited",
                          "class": box_seal.mount_class(m.source, m.target, workspaces)}
                         for m in mounts]
            doc = box_profile.compile_profile(
                execution_id=execution_id, generation=generation, settings=settings,
                boundary=box_profile.LEGACY,
                image={"ref": self._image_override or template.image,
                       "id": template.image_id or "unknown"},
                source={},
                launch={"workflow": facts.workflow_name if facts else None,
                        "boundary": box_profile.LEGACY, "classified": False},
                grants=inherited, tmpfs=[f"{home}:mode=1777" for home in homes],
                runtime={"command": _run_command(), "user": template.user or None,
                         "path": (template.env_value("PATH") or "").split(os.pathsep),
                         "home": template.env_value("HOME"), "env_mode": env.mode},
                limits=self._limits_doc(),
                graph=box_profile.network_graph(container_name(execution_id),
                                                template.networks[:1], template.extra_hosts),
                legacy_mounts=inherited,
            )
            record = box_profile.record_for(doc, previous)
            self._store.save(execution_id, record,
                             previous.generation if previous else None)
        except Exception as exc:  # noqa: BLE001 - as before: the box starts without one
            logger.warning("Run container %s: no box profile (%s); it starts without one",
                           container_name(execution_id), exc)
            return None
        logger.info("Run container %s: %s", container_name(execution_id),
                    box_profile.summary(record["doc"]))
        return record

    def _spawn_sealed(self, execution_id: str, workspace_path: str, template: Template,
                      env: BoxEnvSplit, settings: dict[str, str]) -> ProcessHandle:
        """A sealed box (BS1): checked, planned, pinned, profiled and stored, then started."""
        name = container_name(execution_id)
        oneshot = settings[box_profile.BOOTSTRAP_ENV] == box_bootstrap.ONESHOT
        facts = self._store.load(execution_id)
        if facts is None:
            raise SpawnerError(f"No WorkflowRun row for execution_id={execution_id}")
        previous = box_profile.stored_profile(facts.metadata)
        generation = box_profile.next_generation(previous, box_profile.SEALED)
        interpreter = self._sealed_preflight(template, env)
        if oneshot:
            self._baked_check(template)
        path_value = template.env_value("PATH")
        home = template.env_value("HOME")
        if not path_value or not home:
            raise BoxProfileError("the template has no PATH or HOME for a sealed box to fix")
        workspaces = template.env_value("WORKSPACE_DIR")
        configs = next((m.source for m in template.mounts
                        if m.target == box_seal.CONFIG_TARGET), None)
        if configs is None:
            raise BoxProfileError("the template container mounts no /app/configs to seal")
        view = self._worker_view()
        configs_here = view.path(configs)
        with box_seal.plan_sealed(
            mounts=[(m.source, m.target) for m in template.mounts],
            workspace_dir=workspaces, workspace_path=workspace_path,
            data_targets=box_seal.declared_data(facts.workflow_name, configs_here), view=view,
        ) as plan:
            default_provider = template.env_value(DEFAULT_PROVIDER_ENV) or None
            launch = box_launches.classify(
                box_launches.ConfigIndex.of(box_launches.FsTree(configs_here)),
                facts.workflow_name, default_provider=default_provider,
                absent_roots=[(p, f"names {p}, which a sealed box doesn't have")
                              for p in plan.absent],
                extra_markers=box_launches.ONESHOT_MARKERS if oneshot else (),
            )
            if launch.boundary != box_launches.SEALED:
                raise BoxProfileError(
                    f"workflow {facts.workflow_name!r} can't run in a sealed box (classified "
                    f"{launch.boundary}): " + "; ".join(launch.reasons),
                )
            engine = self._engine_check(plan, view)
            if workspace_path:
                others = self._store.neighbours(execution_id,
                                                _workspace_forms(workspace_path, workspaces))
                if others:
                    raise BoxProfileError(
                        f"the run's workspace {workspace_path} holds, sits inside or shares "
                        f"other runs' workspaces: {', '.join(others[:5])}",
                    )
            box_env = self._sealed_env(name, env, path_value, home)
            if launch.default_provider:
                # The provider the launch was classified with, whatever the box list says.
                box_env = [v for v in box_env if v.split("=", 1)[0] != DEFAULT_PROVIDER_ENV]
                box_env.append(f"{DEFAULT_PROVIDER_ENV}={launch.default_provider}")
            delivered: dict[str, str] = {}
            bootstrap = None
            if oneshot:
                box_env, delivered = split_delivery(box_env, env.agent_tools)
                uid, gid = self._box_ids(template, interpreter)
                bootstrap = box_bootstrap.section(names=delivered, uid=uid, gid=gid,
                                                  limits=self._delivery_limits)
                plan.tmpfs.append(box_bootstrap.tmpfs_spec(bootstrap))
            source = {part: dict(facts_) for part, facts_ in plan.sources.items()}
            for part in ("code", "configs"):
                if source.get(part, {}).get("from") == "image":
                    source[part]["digest"] = template.image_id
            workdir = template.working_dir or "/"
            doc = box_profile.compile_profile(
                execution_id=execution_id, generation=generation, settings=settings,
                boundary=box_profile.SEALED,
                image={"ref": template.image, "id": template.image_id},
                source=source,
                launch={**launch.as_dict(), "engine": engine},
                grants=[grant.to_profile() for grant in plan.grants],
                tmpfs=list(plan.tmpfs),
                runtime={
                    "interpreter": interpreter, "argv": list(SEALED_ARGS),
                    "boot": BOOT_DIGEST,
                    "path": path_value.split(os.pathsep), "home": home,
                    "user": template.user, "workdir": workdir,
                    "immutable": sorted({box_seal.CODE_TARGET, box_seal.CONFIG_TARGET,
                                         box_seal.LOCAL_TARGET, box_seal.CLAUDE_BIN,
                                         interpreter, os.path.dirname(os.path.dirname(interpreter)),
                                         workdir, home}),
                    "absent": list(plan.absent),
                    "env_names": sorted(v.split("=", 1)[0] for v in box_env),
                    **({"writer": WRITER_DIGEST} if oneshot else {}),
                },
                limits=self._limits_doc(),
                graph=box_profile.network_graph(name, template.networks[:1], template.extra_hosts),
                bootstrap=bootstrap,
            )
            record = box_profile.record_for(doc, previous)
            box_env += [f"{k}={v}" for k, v in box_profile.env_for(doc).items()]
            cmd = self.sealed_command(execution_id, template, box_env, plan, interpreter)
            leaked = secrets_in_command(cmd, delivered)
            if leaked:
                raise BoxProfileError(
                    "the box's command would carry secret values (docker inspect shows a "
                    f"command): {', '.join(leaked)}; refused",
                )
            self._store.save(execution_id, record, previous.generation if previous else None)
            logger.info("Run container %s: %s", name, box_profile.summary(doc))
            result = self._docker_run(cmd)
        if oneshot and result.returncode == 0:
            record = self._deliver(execution_id, doc, record, delivered, template.user,
                                   interpreter)
        return self._handle(execution_id, result, template.image_id, record)

    # -- BS2: one-shot delivery -------------------------------------------------

    def _deliver(self, execution_id: str, doc: dict, record: dict, values: Mapping[str, str],
                 user: str, interpreter: str) -> dict:
        """Hand the started box its secrets once; the record with the delivery's state.

        The envelope goes to the writer's stdin (docker exec -i) and nowhere else; it is
        zeroed here once sent. Anything but the runner's acknowledgement of this very
        envelope stops the box, records the delivery as revoked and fails the spawn.
        """
        name = container_name(execution_id)
        boot = doc["bootstrap"]
        deadlines = boot["deadlines"]
        cmd = [self._docker, "exec", "-i", "--user", user, name,
               interpreter, "-I", "-S", "-c", WRITER_PROGRAM, "--deliver",
               "--dir", boot["dir"], "--leaf", boot["leaf"], "--max", str(boot["max_bytes"]),
               "--ready", str(deadlines["ready"]), "--ack", str(deadlines["ack"]),
               "--execution", execution_id, "--generation", str(doc["generation"])]
        data = bytearray()
        try:
            data = box_bootstrap.envelope(doc, record["digest"], values)
            result = self._run(cmd, input=data, capture_output=True, check=False,
                               timeout=deadlines["ready"] + deadlines["ack"] + 30)
            status = _delivery_status(result)
        except box_bootstrap.DeliveryRefused as exc:
            status = {"state": "refused", "reason": str(exc)}
        except subprocess.TimeoutExpired:
            status = {"state": "timeout", "reason": "the writer did not finish in time"}
        except OSError as exc:
            status = {"state": "error",
                      "reason": f"docker exec could not run ({type(exc).__name__})"}
        finally:
            box_bootstrap.zero(data)
        state = {"generation": doc["generation"], "at": utcnow().isoformat(),
                 "names": len(values)}
        if status.get("state") == "consumed":
            updated = self._record_delivery(execution_id, record, {**state, "state": "consumed"})
            logger.info("Run container %s took its one-shot delivery (%d names, generation %s)",
                        name, len(values), doc["generation"])
            return updated
        reason = str(status.get("reason") or "no status")[:300]
        self._docker_run([self._docker, "kill", name])
        self._record_delivery(execution_id, record, {**state, "state": "revoked",
                                                     "why": f"{status.get('state')}: {reason}"})
        raise SpawnerError(
            f"the box's one-shot secret delivery failed ({status.get('state')}: {reason}); "
            "the box was stopped and the delivery revoked",
        )

    def _record_delivery(self, execution_id: str, record: dict, state: dict) -> dict:
        """The run's row keeps how its box's delivery went (names counted, never values)."""
        updated = {**record, "delivery": state}
        try:
            self._store.save(execution_id, updated, record["generation"])
        except Exception as exc:  # noqa: BLE001 - the box's fate doesn't hang on this note
            logger.warning("Run container %s: its delivery state could not be stored (%s)",
                           container_name(execution_id), exc)
        return updated

    def _baked_check(self, template: Template) -> None:
        """Refuse an image that bakes secret-named variables into every box it starts."""
        image = template.image_id
        if image not in self._image_env_seen:
            result = self._docker_run([self._docker, "image", "inspect", "--format",
                                       "{{json .Config.Env}}", image])
            try:
                baked = json.loads(result.stdout or "null") if result.returncode == 0 else None
            except ValueError:
                baked = None
            if not isinstance(baked, list):
                raise BoxProfileError(
                    f"the image {image} can't be inspected for the variables it bakes in, so no "
                    "oneshot box is started from it",
                )
            self._image_env_seen[image] = [str(v) for v in baked]
        bad = []
        for var in self._image_env_seen[image]:
            name, _, value = var.partition("=")
            public = _PUBLIC_BAKED.get(name)
            if public is not None and public.match(value):
                continue
            if box_env_list.looks_secret(name) or value_looks_secret(value):
                bad.append(name)
        if bad:
            raise BoxProfileError(
                "the image bakes variables named or valued like secrets into every box ("
                + ", ".join(sorted(bad)) + "); a oneshot box starts only from an image whose "
                "own environment is fixed, non-secret configuration",
            )

    def _box_ids(self, template: Template, interpreter: str) -> tuple[int, int]:
        """The numeric uid and gid the box's user has in its image (the delivery tmpfs's owner)."""
        key = (template.image_id, template.user)
        if key not in self._box_ids_seen:
            numeric = re.fullmatch(r"(\d+):(\d+)", template.user)
            if numeric:
                ids = (int(numeric.group(1)), int(numeric.group(2)))
            else:
                result = self._docker_run([
                    self._docker, "run", "--rm", "--network", "none", "--read-only",
                    "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                    "--label", "temper.role=probe", "--user", template.user,
                    "--entrypoint", interpreter, template.image_id,
                    "-I", "-S", "-c", "import os; print(os.getuid(), os.getgid())",
                ])
                found = re.fullmatch(r"\s*(\d+) (\d+)\s*", result.stdout or "")
                if result.returncode != 0 or not found:
                    raise BoxProfileError(
                        f"the uid of {template.user!r} in the image can't be read "
                        f"({(result.stderr or '').strip()[:200]}); no oneshot box is started",
                    )
                ids = (int(found.group(1)), int(found.group(2)))
            if 0 in ids:
                raise BoxProfileError("a oneshot box's user is root; refused")
            self._box_ids_seen[key] = ids
        return self._box_ids_seen[key]

    def _engine_check(self, plan: box_seal.SealPlan, view: box_seal.WorkerView) -> dict:
        """Refuse code that starts programs from places the gate hasn't classified (G11).

        The worker scans the code and local folders the box would mount (the scan is kept
        per tree digest, so an unchanged tree is scanned once).
        """
        code = plan.sources.get("code") or {}
        if code.get("from") != "bind":
            raise BoxProfileError(
                "the box's code would come from its image, where the worker can't look for "
                "the places it starts programs; a sealed box runs bind-mounted code",
            )
        sites = set(_launch_sites(view.path(code["path"]), "temper_ai/", (),
                                  code.get("digest")))
        local = plan.sources.get("local")
        if local:
            sites |= _launch_sites(view.path(local["path"]), "local/",
                                   tuple(local.get("entries") or ()), local.get("digest"))
        missing = box_launches.unclassified_sites(sites, self._engine_table)
        if missing:
            raise BoxProfileError(
                "the code this box would mount starts programs from places the gate hasn't "
                f"classified ({len(missing)}): " + ", ".join(missing[:8])
                + (" and more" if len(missing) > 8 else ""),
            )
        return {"sites": len(sites), "code": code.get("digest"),
                "local": (local or {}).get("digest"), "rules": box_launches.GENERATOR}

    def _sealed_preflight(self, template: Template, env: BoxEnvSplit) -> str:
        """Refuse what a sealed box can't be; the interpreter it starts with."""
        if env.mode == box_env_list.MODE_INHERIT:
            raise BoxProfileError(
                f"{box_env_list.MODE_ENV}=inherit copies every variable into the box; a sealed "
                "install can't run that way",
            )
        if _all_workspaces():
            raise BoxProfileError(
                "TEMPER_DOCKER_WORKSPACES=all gives every run the whole workspaces tree; a "
                "sealed install gives each run its own folder only: unset it",
            )
        if self._image_override:
            raise BoxProfileError(
                "a sealed box runs the template's own image, taken by its id; unset "
                "TEMPER_DOCKER_IMAGE",
            )
        if not template.image_id.startswith("sha256:"):
            raise BoxProfileError("the template's image has no content id to pin")
        user = template.user.split(":", 1)[0]
        if user in ("", "root", "0"):
            raise BoxProfileError(
                f"the template container runs as {template.user or 'root'}; a sealed box runs "
                "as an unprivileged user",
            )
        parts = _run_command()
        if len(parts) != 4 or parts[1:] != ["-m", "temper_ai.cli.main", "run-workflow"]:
            raise BoxProfileError(
                "a sealed box starts the image's own interpreter directly: "
                "TEMPER_DOCKER_RUN_COMMAND must be '<python> -m temper_ai.cli.main run-workflow', "
                f"not {shlex.join(parts)!r} (uv run would sync packages as the box starts)",
            )
        interpreter = parts[0]
        if not interpreter.startswith("/"):
            interpreter = os.path.normpath(os.path.join(template.working_dir or "/", interpreter))
        return interpreter

    def _sealed_env(self, name: str, env: BoxEnvSplit, path_value: str, home: str) -> list[str]:
        kept = [v for v in env.kept if v.split("=", 1)[0] not in SEALED_DROP]
        return [*kept, f"PATH={path_value}", f"HOME={home}",
                *(f"{k}={v}" for k, v in SEALED_SET.items()),
                f"{box_env_list.RUN_CONTAINER_ENV}={name}"]

    def sealed_command(self, execution_id: str, template: Template, box_env: list[str],
                       plan: box_seal.SealPlan, interpreter: str) -> list[str]:
        name = container_name(execution_id)
        cmd = [
            self._docker, "run", "--detach", "--rm", "--init",
            "--name", name, "--hostname", name,
            "--label", "temper.role=run",
            "--label", f"temper.execution_id={execution_id}",
            "--label", "temper.box=sealed",
            "--security-opt", "no-new-privileges", "--cap-drop", "ALL", "--read-only",
            "--no-healthcheck", "--user", template.user,
            "--workdir", template.working_dir or "/",
        ]
        for network in template.networks[:1]:
            cmd += ["--network", network]
        for host in template.extra_hosts:
            cmd += ["--add-host", host]
        for var in box_env:
            cmd += ["--env", var]
        for tmpfs in plan.tmpfs:
            cmd += ["--tmpfs", tmpfs]
        for grant in plan.grants:
            cmd += ["--mount", grant.to_arg()]
        cmd += self._resource_limits()
        runner = [interpreter, *SEALED_ARGS, "--execution-id", execution_id]
        cmd += ["--entrypoint", interpreter, template.image_id,
                "-I", "-c", BOOT_PROGRAM, "--exec", *runner]
        return cmd

    def _worker_view(self) -> box_seal.WorkerView:
        """Where the template's host paths are in this process (its own container's binds)."""
        if self._worker_view_given is not None:
            return self._worker_view_given
        me = os.environ.get("TEMPER_DOCKER_SELF_CONTAINER") or socket.gethostname()
        result = self._docker_run([self._docker, "inspect", me])
        if result.returncode != 0:
            if os.path.exists("/.dockerenv"):
                raise BoxProfileError(
                    f"the worker runs in a container it can't inspect ({me}), so it can't pin "
                    "a sealed box's mounts; set TEMPER_DOCKER_SELF_CONTAINER",
                )
            return box_seal.WorkerView(None)
        try:
            info = json.loads(result.stdout)[0]
        except (ValueError, IndexError, TypeError) as exc:
            raise BoxProfileError(f"Unexpected `docker inspect` output for {me}: {exc}") from exc
        return box_seal.WorkerView(
            (m["Source"], m["Destination"]) for m in info.get("Mounts") or []
            if m.get("Type") == "bind"
        )

    @staticmethod
    def _limits_doc() -> dict[str, str | None]:
        return {"memory": os.environ.get("TEMPER_DOCKER_MEMORY") or None,
                "cpus": os.environ.get("TEMPER_DOCKER_CPUS") or None,
                "pids": os.environ.get("TEMPER_DOCKER_PIDS_LIMIT") or None}

    def is_alive(self, handle: ProcessHandle) -> bool:
        result = self._docker_run(
            [self._docker, "inspect", "--format", "{{.State.Running}}", self._name_for(handle)],
        )
        if result.returncode != 0:
            if _says_gone(result.stderr):
                return False  # gone: --rm removed it on exit, or it never started
            # Not an answer about the container (the daemon is busy or down):
            # the reaper must not bury a run over it.
            raise SpawnerError(f"docker inspect failed: {result.stderr.strip()}")
        return result.stdout.strip() == "true"

    def is_gone(self, handle: ProcessHandle) -> bool:
        """Whether the run's container no longer exists (removed, not merely stopped).

        A parked Pi run is carried on in a new container with the same name, which docker
        refuses while the old one is still there (runner/parked.py, spawner/reaper.py).
        """
        result = self._docker_run(
            [self._docker, "inspect", "--format", "{{.State.Running}}", self._name_for(handle)],
        )
        if result.returncode == 0:
            return False
        if _says_gone(result.stderr):
            return True
        raise SpawnerError(f"docker inspect failed: {result.stderr.strip()}")

    def kill(self, handle: ProcessHandle, *, force: bool = False) -> None:
        name = self._name_for(handle)
        sig = "KILL" if force else "TERM"
        result = self._docker_run([self._docker, "kill", "--signal", sig, name])
        if result.returncode == 0:
            logger.info("Sent SIG%s to run container %s", sig, name)
            return
        if _says_gone(result.stderr) or "is not running" in result.stderr.lower():
            logger.debug("Run container %s already gone", name)
            return
        raise SpawnerError(f"docker kill -s {sig} {name} failed: {result.stderr.strip()}")

    # -- Building the run container ------------------------------------------

    def template(self) -> Template:
        """The container runs are copied from, looked at again for each run.

        Fresh each time, so a template container recreated with a new key
        or image passes it to the next run without a worker restart. While
        it can't be read (it is being recreated), the last good look stands
        in; with none yet, the run waits in the queue (SpawnerBusy) for up
        to TEMPLATE_GRACE_SECONDS, then fails.
        """
        try:
            fresh = self._inspect_template()
        except SpawnerError as exc:
            if self._template is not None:
                logger.warning(
                    "Can't read %s (%s); using the last look at it", self._template_container, exc,
                )
                return self._template
            now = self._clock()
            if self._template_missing_since is None:
                self._template_missing_since = now
            if now - self._template_missing_since < TEMPLATE_GRACE_SECONDS:
                raise SpawnerBusy(str(exc)) from exc
            raise
        self._template = fresh
        self._template_missing_since = None
        return fresh

    def _inspect_template(self) -> Template:
        result = self._docker_run([self._docker, "inspect", self._template_container])
        if result.returncode != 0:
            raise SpawnerError(
                f"Cannot inspect the container {self._template_container!r} to "
                f"template runs from it (is the docker socket mounted? see "
                f"docker-compose.host-docker.yml): {result.stderr.strip()}",
            )
        try:
            info = json.loads(result.stdout)[0]
        except (ValueError, IndexError, TypeError) as exc:
            raise SpawnerError(f"Unexpected `docker inspect` output: {exc}") from exc
        template = Template.from_inspect(info)
        if not template.image:
            raise SpawnerError(
                f"The container {self._template_container!r} reports no image to template runs from",
            )
        return template

    def env_split(self, template: Template) -> BoxEnvSplit:
        """Which of the template's variables the box gets: the allow-list, read for every run.

        A list that cannot be read fails the spawn: a box with no list would get either
        nothing it needs or everything it must not have.
        """
        mode = box_env_list.box_env_mode()
        if mode == box_env_list.MODE_INHERIT:
            return BoxEnvSplit.of(template.env, mode, None)
        try:
            allowed = self._box_env()
        except box_env_list.BoxEnvError as exc:
            raise SpawnerError(f"The box's allow-list is broken, so no run can start: {exc}") from exc
        return BoxEnvSplit.of(template.env, mode, allowed)

    def legacy_mounts(self, workspace_path: str, template: Template) -> tuple[list[str], list[Mount]]:
        """A legacy box's ~/.claude tmpfs homes and bind mounts, in the order docker gets them."""
        all_workspaces = _all_workspaces()
        inherited = [m for m in template.mounts if _passes_through(m, all_workspaces)]
        mounts = list(inherited)
        if workspace_path:
            mounts += workspace_mounts(workspace_path, covered=inherited)
        return _claude_homes(inherited), mounts

    def run_command(
        self, execution_id: str, workspace_path: str, template: Template,
        env: BoxEnvSplit | None = None, extra_env: dict[str, str] | None = None,
    ) -> list[str]:
        """A legacy box's `docker run` (``extra_env``: its profile's variables)."""
        name = container_name(execution_id)
        cmd = [
            self._docker, "run", "--detach", "--rm", "--init",
            "--name", name, "--hostname", name,
            "--label", "temper.role=run",
            "--label", f"temper.execution_id={execution_id}",
            "--security-opt", "no-new-privileges",
            "--no-healthcheck",
        ]
        for network in template.networks[:1]:
            cmd += ["--network", network]
        for host in template.extra_hosts:
            cmd += ["--add-host", host]
        env = env or self.env_split(template)
        for var in env.kept:
            cmd += ["--env", var]
        cmd += ["--env", f"{box_env_list.RUN_CONTAINER_ENV}={name}"]
        for key, value in (extra_env or {}).items():
            cmd += ["--env", f"{key}={value}"]
        homes, mounts = self.legacy_mounts(workspace_path, template)
        for home in homes:
            # Writable by whichever user the image runs as (the template may be
            # another container than this one); the box is that user's alone.
            cmd += ["--tmpfs", f"{home}:mode=1777"]
        for mount in mounts:
            cmd += ["--mount", mount.to_arg()]
        cmd += self._resource_limits()
        cmd.append(self._image_override or template.image)
        cmd += [*_run_command(), "--execution-id", execution_id]
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
