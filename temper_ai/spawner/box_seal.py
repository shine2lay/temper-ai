"""A sealed box's mounts: a positive list, each source pinned from the worker's check to docker's use.

BS1 (docs/boxes.md, "Sealed boxes"). A legacy box copies the template container's bind
mounts as they are. A sealed box inherits none of them: it gets only what this module
grants, each one named and read-only unless it is the run's own workspace:

  /app/temper_ai, /app/configs   the runner's code and the configs
  /app/local/<code>              the private provider code only (register_providers.py,
                                 providers/, agents/), never the rest of local/
  /app/.local/bin/claude         one Claude CLI executable, the newest the template has
  the run's workspace            read-write, at its host path: a folder inside
                                 WORKSPACE_DIR, given as a host path
  declared data                  read-only, per workflow (configs/boxes/data.yaml)

Everything else the template mounts is absent: the main repo copy (/app/repo), the whole
workspaces tree and its /app/workspaces alias, key folders, the Claude login file,
sockets, other runs' workspaces.

Pinning. A path checked now and handed to docker later can be swapped in between (a
folder renamed away and another, or a symlink, put in its place). So each source is
opened here one path component at a time without following a symlink, its (device,
inode, type) goes into the profile, and the descriptor stays open until `docker run`
returns: while it is open the inode can't be freed and reused, so whatever docker mounts
is either that very object or one with another identity. The box compares each mount
with the profile before anything else runs (box_view.py) and refuses on any difference.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from temper_ai.spawner.box_profile import BoxProfileError, tree_digest

DOCKER_SOCKET = "/var/run/docker.sock"
CODE_TARGET = "/app/temper_ai"
CONFIG_TARGET = "/app/configs"
LOCAL_TARGET = "/app/local"
#: The part of local/ the runner imports (llm/providers/factory.py -> local.register_providers).
LOCAL_CODE = ("__init__.py", "register_providers.py", "providers", "agents")
CLAUDE_VERSIONS_TARGET = "/opt/claude/versions"
CLAUDE_BIN = "/app/.local/bin/claude"
MAIN_REPO_TARGET = "/app/repo"
WORKSPACES_ALIAS = "/app/workspaces"
CLAUDE_STATE = "/app/.claude"
#: Always absent from a sealed box, whatever the template mounts.
ALWAYS_ABSENT = (MAIN_REPO_TARGET, WORKSPACES_ALIAS, "/app/.env")
TMPFS = ("/tmp:rw,exec,nosuid,nodev,mode=1777",
         f"{CLAUDE_STATE}:rw,noexec,nosuid,nodev,mode=1777")

#: Classes a declared data folder may never be.
NOT_DATA = frozenset({"docker socket", "all workspaces", "code", "executables",
                      "private code and keys", "main repo copy", "login", "keys"})
_KEYISH = re.compile(r"ssh|deploy|secret|token|key|cred|password|\.env|\.pem")
_VERSION = re.compile(r"^\d+(\.\d+)*$")


def mount_class(source: str, target: str, workspace_dir: str | None) -> str:
    """What a template mount is, in the words the profile and the readiness report use."""
    if DOCKER_SOCKET in (source, target):
        return "docker socket"
    if target == WORKSPACES_ALIAS or (workspace_dir and workspace_dir in (source, target)):
        return "all workspaces"
    if target in (CODE_TARGET, CONFIG_TARGET):
        return "code"
    if target == CLAUDE_VERSIONS_TARGET:
        return "executables"
    if target == LOCAL_TARGET or target.startswith(LOCAL_TARGET + "/"):
        return "private code and keys"
    if target == MAIN_REPO_TARGET:
        return "main repo copy"
    said = f"{source} {target}".lower()
    if ".credentials" in said or "/.claude" in said:
        return "login"
    if _KEYISH.search(said):
        return "keys"
    return "shared root"


# -- the worker's view of a host path --------------------------------------------------------


class WorkerView:
    """Where a host path is in this process's own filesystem.

    The template's mounts name host paths; the worker may itself run in a container
    that has them at other paths (/home/.../local at /app/local). ``binds`` are the
    worker's own (host source, worker target) pairs; None means this process sees the
    host's paths as they are.
    """

    def __init__(self, binds: Iterable[tuple[str, str]] | None) -> None:
        self.binds = None if binds is None else sorted(binds, key=lambda b: -len(b[0]))

    def path(self, host_path: str) -> str:
        if self.binds is None:
            return host_path
        for source, target in self.binds:
            if host_path == source or host_path.startswith(source.rstrip("/") + "/"):
                return target + host_path[len(source):]
        raise BoxProfileError(
            f"{host_path} is not visible to the worker, so it can't be pinned for a sealed box",
        )


# -- pinning ---------------------------------------------------------------------------------


def _plain(path: str) -> bool:
    return (path.startswith("/") and os.path.normpath(path) == path
            and not any(c in path for c in ",=\n\r\0"))


def pin(path: str) -> tuple[int, dict]:
    """Open ``path`` one component at a time, never through a symlink: (descriptor, pin).

    The pin is {dev, ino, type}; the caller keeps the descriptor open until docker has
    the mount.
    """
    if not _plain(path):
        raise BoxProfileError(f"{path!r} is not a plain absolute path a sealed box can mount")
    fd = os.open("/", os.O_PATH | os.O_DIRECTORY)
    try:
        for part in [p for p in path.split("/") if p]:
            nxt = os.open(part, os.O_PATH | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nxt
            if stat.S_ISLNK(os.fstat(fd).st_mode):
                raise BoxProfileError(
                    f"{path} goes through a symlink ({part}), which docker would follow: refused",
                )
        st = os.fstat(fd)
    except OSError as exc:
        os.close(fd)
        raise BoxProfileError(f"can't open {path} to pin it ({exc.strerror})") from exc
    except BoxProfileError:
        os.close(fd)
        raise
    if stat.S_ISDIR(st.st_mode):
        kind = "dir"
    elif stat.S_ISREG(st.st_mode):
        kind = "file"
    else:
        os.close(fd)
        raise BoxProfileError(f"{path} is neither a folder nor a file: refused")
    return fd, {"dev": st.st_dev, "ino": st.st_ino, "type": kind}


_FILE_DIGESTS: dict[tuple, str] = {}


def file_digest(fd: int) -> str:
    """sha256 of a pinned file, read through its own descriptor (cached by identity and age)."""
    st = os.fstat(fd)
    key = (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)
    if key not in _FILE_DIGESTS:
        h = hashlib.sha256()
        with open(f"/proc/self/fd/{fd}", "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        _FILE_DIGESTS[key] = "sha256:" + h.hexdigest()
    return _FILE_DIGESTS[key]


@dataclass(frozen=True)
class Grant:
    source: str      # the host path docker gets
    target: str      # where the box has it
    read_only: bool
    kind: str        # code | config | local | executable | workspace | data
    pin: dict

    def to_profile(self) -> dict:
        return {"source": self.source, "target": self.target, "read_only": self.read_only,
                "kind": self.kind, "pin": dict(self.pin)}

    def to_arg(self) -> str:
        arg = f"type=bind,source={self.source},target={self.target}"
        return arg + ",readonly" if self.read_only else arg


@dataclass
class SealPlan:
    """The grants, the tmpfs mounts and what must be absent; holds the pins open until closed."""

    grants: list[Grant] = field(default_factory=list)
    tmpfs: list[str] = field(default_factory=lambda: list(TMPFS))
    absent: list[str] = field(default_factory=list)
    sources: dict[str, dict] = field(default_factory=dict)
    _fds: list[int] = field(default_factory=list)

    def grant(self, view: WorkerView, source: str, target: str, *, read_only: bool,
              kind: str) -> int:
        if not _plain(source) or not _plain(target):
            raise BoxProfileError(f"{source} -> {target} is not a mount a sealed box can have")
        if any(g.target == target for g in self.grants):
            raise BoxProfileError(f"two grants for {target}")
        fd, pinned = pin(view.path(source))
        self._fds.append(fd)
        self.grants.append(Grant(source, target, read_only, kind, pinned))
        return fd

    def close(self) -> None:
        while self._fds:
            try:
                os.close(self._fds.pop())
            except OSError:
                pass

    def __enter__(self) -> SealPlan:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


# -- the plan --------------------------------------------------------------------------------


def _version_key(name: str) -> tuple[int, ...]:
    return tuple(int(p) for p in name.split("."))


def newest_version(names: Iterable[str]) -> str | None:
    found = [n for n in names if _VERSION.match(n)]
    return max(found, key=_version_key) if found else None


def _inside(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip("/") + "/")


def plan_sealed(
    *,
    mounts: Iterable[tuple[str, str]],
    workspace_dir: str | None,
    workspace_path: str,
    data_targets: Iterable[str],
    view: WorkerView,
) -> SealPlan:
    """The sealed box's mounts for one run. ``mounts`` are the template's (source, target) binds.

    Refuses (BoxProfileError) anything it can't grant safely; the caller closes the plan
    once docker has the mounts.
    """
    by_target = {target: source for source, target in mounts}
    plan = SealPlan()
    try:
        if CONFIG_TARGET not in by_target:
            raise BoxProfileError("the template container mounts no /app/configs to seal")
        for target, kind, name in ((CODE_TARGET, "code", "code"), (CONFIG_TARGET, "config", "configs")):
            if target in by_target:
                plan.grant(view, by_target[target], target, read_only=True, kind=kind)
                plan.sources[name] = {"from": "bind", "path": by_target[target],
                                      "digest": tree_digest(view.path(by_target[target]))}
            else:
                plan.sources[name] = {"from": "image"}  # its digest is the image's id
        if LOCAL_TARGET in by_target:
            source = by_target[LOCAL_TARGET]
            here = view.path(source)
            present = [e for e in LOCAL_CODE if os.path.lexists(os.path.join(here, e))]
            for entry in present:
                plan.grant(view, f"{source}/{entry}", f"{LOCAL_TARGET}/{entry}", read_only=True,
                           kind="local")
            plan.sources["local"] = {"from": "bind", "path": source, "entries": present,
                                     "digest": tree_digest(here, only=present)}
            plan.absent += [f"{LOCAL_TARGET}/{e}" for e in sorted(os.listdir(here))
                            if e not in present]
        if CLAUDE_VERSIONS_TARGET in by_target:
            source = by_target[CLAUDE_VERSIONS_TARGET]
            newest = newest_version(os.listdir(view.path(source)))
            if newest is not None:
                fd = plan.grant(view, f"{source}/{newest}", CLAUDE_BIN, read_only=True,
                                kind="executable")
                plan.sources["claude"] = {"from": "bind", "path": f"{source}/{newest}",
                                          "version": newest, "digest": file_digest(fd)}
        if workspace_path:
            fd = plan.grant(view, _workspace(workspace_path, workspace_dir), workspace_path,
                            read_only=False, kind="workspace")
            _no_outside_repo(fd, workspace_path)
        for target in data_targets:
            if target not in by_target:
                raise BoxProfileError(f"declared data {target} is not mounted in the template")
            klass = mount_class(by_target[target], target, workspace_dir)
            if klass in NOT_DATA:
                raise BoxProfileError(f"declared data {target} is {klass}: never data")
            if workspace_dir and (_inside(by_target[target], workspace_dir)
                                  or _inside(workspace_dir, by_target[target])):
                raise BoxProfileError(
                    f"declared data {target} is in or holds the workspaces tree, where other "
                    "runs' folders are: never data",
                )
            if any(_inside(target, g.target) or _inside(g.target, target) for g in plan.grants):
                raise BoxProfileError(f"declared data {target} overlaps another grant")
            plan.grant(view, by_target[target], target, read_only=True, kind="data")
        granted = [g.target for g in plan.grants]
        for target in by_target:
            if any(_inside(g, target) for g in granted):
                continue  # granted, or a folder a grant sits in
            plan.absent.append(target)
        plan.absent += [p for p in ALWAYS_ABSENT if p not in plan.absent]
    except BaseException:
        plan.close()
        raise
    return plan


def _workspace(workspace_path: str, workspace_dir: str | None) -> str:
    """The run's workspace as a host path inside WORKSPACE_DIR, or BoxProfileError."""
    if _inside(workspace_path, WORKSPACES_ALIAS):
        raise BoxProfileError(
            f"the run's workspace {workspace_path} is the /app/workspaces alias of the shared "
            "tree; a sealed box needs its host path inside WORKSPACE_DIR",
        )
    if not workspace_dir or not _plain(workspace_dir):
        raise BoxProfileError("the template has no WORKSPACE_DIR, so no workspace can be sealed")
    if not _plain(workspace_path) or workspace_path == workspace_dir or not _inside(
            workspace_path, workspace_dir):
        raise BoxProfileError(
            f"the run's workspace {workspace_path} is not a folder inside WORKSPACE_DIR "
            f"({workspace_dir}); a sealed box gets only its own folder there",
        )
    return workspace_path


def _no_outside_repo(fd: int, workspace_path: str) -> None:
    """A git worktree's .git points at its main repository: a sealed box can't have that."""
    try:
        git = os.open(".git", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    except OSError:
        return  # no .git, or a symlink (it dangles inside the box: nothing outside is mounted)
    try:
        if not stat.S_ISREG(os.fstat(git).st_mode):
            return  # a .git folder: the repository is the workspace's own
        first = os.read(git, 4096).decode("utf-8", "replace").splitlines()[:1]
    finally:
        os.close(git)
    if first and first[0].startswith("gitdir:"):
        gitdir = first[0][len("gitdir:"):].strip()
        if not _inside(os.path.normpath(os.path.join(workspace_path, gitdir)), workspace_path):
            raise BoxProfileError(
                f"the run's workspace {workspace_path} is a git worktree of a repository "
                f"outside it ({gitdir}); a sealed box can't have the main repo's backing",
            )


# -- declared data ---------------------------------------------------------------------------


def declared_data(workflow: str, config_dir: str | Path) -> list[str]:
    """The mount targets ``workflow`` declares as read-only data (configs/boxes/data.yaml).

    configs/boxes/local/data.yaml (git-ignored) adds this install's own. A file that
    can't be read refuses the sealed launch rather than guess.
    """
    targets: list[str] = []
    for path in (Path(config_dir) / "boxes" / "data.yaml",
                 Path(config_dir) / "boxes" / "local" / "data.yaml"):
        if not path.exists():
            continue
        try:
            doc = yaml.safe_load(path.read_text()) or {}
        except (OSError, yaml.YAMLError) as exc:
            raise BoxProfileError(f"{path} can't be read ({exc})") from exc
        data = doc.get("data") if isinstance(doc, Mapping) else None
        if not isinstance(data, Mapping) or not all(
                isinstance(v, list) and all(isinstance(t, str) for t in v) for v in data.values()):
            raise BoxProfileError(f"{path}: data must map workflow names to lists of mount targets")
        targets += [t for t in data.get(workflow) or [] if t not in targets]
    return targets


def summary(plan: SealPlan) -> dict[str, Any]:
    return {"grants": [g.target for g in plan.grants], "absent": list(plan.absent)}
