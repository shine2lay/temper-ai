"""Read-only, names-only observations for the manual Pi rehearsal.

Never persist docker inspect's original result: it contains environment values. Unknown
mounts are a refusal, not an observation that can later be called safe.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

BOX_NAME = re.compile(r"temper-pi-[0-9a-f]{20}\Z")
DOCKER_SOCKET = Path("/var/run/docker.sock")


class RigRefusal(RuntimeError):
    """The rig cannot safely proceed with its current setup."""


def inside(path: Path, root: Path) -> bool:
    return path == root or path.is_relative_to(root)


def real_path(path: str | Path) -> Path:
    """The path with every link followed; one that can't be read is unknown, so a refusal."""
    try:
        return Path(path).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise RigRefusal(f"path can't be read: {path}") from exc


def mount_check(containers: list[dict[str, Any]], *, root: Path, checkout: Path,
                project: str, docker_socket: Path = DOCKER_SOCKET) -> dict[str, Any]:
    """Check created, not started, containers; only pi-worker may bind docker.sock.

    Resolve bind sources before classification, so a symlink out of the scratch tree
    isn't accepted. Named volumes must belong to this compose project. A rig tree that holds
    the home folder (where the owner's credentials and role folders live) is refused whole.
    """
    if not project.startswith("pi-rehearsal-"):
        raise RigRefusal("not a rehearsal compose project")
    root, checkout = real_path(root), real_path(checkout)
    if inside(Path.home().resolve(), root):
        raise RigRefusal("the rig tree holds the home folder")
    if not inside(checkout, root):
        raise RigRefusal("checkout must be inside the private rig tree")
    socket_path = docker_socket.resolve()
    if not containers:
        raise RigRefusal("no created containers to check")
    rows = []
    for container in containers:
        labels = container.get("Config", {}).get("Labels", {}) or {}
        if labels.get("com.docker.compose.project") != project:
            raise RigRefusal("container belongs to another compose project")
        service = labels.get("com.docker.compose.service")
        if not service:
            raise RigRefusal("container has no compose service")
        if container.get("State", {}).get("Status") != "created":
            raise RigRefusal("mount check requires every container still created")
        mounts = container.get("Mounts")
        if not isinstance(mounts, list):
            raise RigRefusal("unknown mount list")
        for mount in mounts:
            kind = mount.get("Type")
            source = mount.get("Source", "")
            if kind == "bind":
                if not source or not Path(source).is_absolute():
                    raise RigRefusal("unknown bind source")
                path = real_path(source)
                if path == socket_path:
                    if service != "pi-worker" or mount.get("Destination") != str(DOCKER_SOCKET):
                        raise RigRefusal("only pi-worker may mount docker.sock at its own path")
                    classification = "PW02: pi-worker Docker socket"
                elif inside(path, root):
                    classification = "own checkout" if inside(path, checkout) else "rig scratch tree"
                else:
                    raise RigRefusal(f"bind source outside rig: {source}")
            elif kind == "volume":
                if not str(mount.get("Name", "")).startswith(project + "_"):
                    raise RigRefusal("unclassified named volume")
                classification = "own compose volume"
            elif kind == "tmpfs":
                classification = "throwaway tmpfs"
            else:
                raise RigRefusal(f"unknown mount type: {kind}")
            if not isinstance(mount.get("RW"), bool):
                raise RigRefusal("mount has no read-only flag")
            rows.append({"container": container["Name"].lstrip("/"), "service": service,
                         "type": kind, "source": source, "destination": mount["Destination"],
                         "read_only": not mount["RW"], "classification": classification})
    return {"result": "pass", "before_start": True, "project": project, "mounts": rows}


def bind_settings(source: str, settings: dict[str, str]) -> list[str]:
    """Name every box setting covered by this bind, including a shared pins root."""
    src = Path(os.path.normpath(source))
    return sorted(name for name, path in settings.items()
                  if inside(src, Path(os.path.normpath(path)))
                  or inside(Path(os.path.normpath(path)), src))


def names_only(container: dict[str, Any], *, settings: dict[str, str],
               root: Path, member: bool = False) -> dict[str, Any]:
    """Exact allow-list of inspect fields; environment values never leave this function."""
    config, host = container["Config"], container["HostConfig"]
    mounts = []
    for mount in container["Mounts"]:
        source = mount.get("Source", "")
        mapped = bind_settings(source, settings) if source and mount["Type"] == "bind" else []
        if member and mount["Type"] == "bind":
            if not inside(real_path(source), real_path(root)):
                raise RigRefusal("member binds outside rig scratch tree")
            if not mapped:
                raise RigRefusal("member bind has no box-setting classification")
        mounts.append({"type": mount["Type"], "source": source,
                       "destination": mount["Destination"], "read_only": not mount["RW"],
                       "settings": mapped,
                       "rehearsal_only": mount["Destination"] == "/box-ca/ca.pem"})
    env_names = sorted({entry.split("=", 1)[0] for entry in (config.get("Env") or [])})
    labels = config.get("Labels") or {}
    out = {"name": container["Name"].lstrip("/"), "image_id": container["Image"],
           "user": config.get("User", ""), "network_mode": host.get("NetworkMode", ""),
           "networks": sorted(container.get("NetworkSettings", {}).get("Networks", {})),
           "read_only_root": host.get("ReadonlyRootfs"), "privileged": host.get("Privileged"),
           "cap_add": host.get("CapAdd") or [], "cap_drop": host.get("CapDrop") or [],
           "devices": host.get("Devices") or [], "pid_mode": host.get("PidMode", ""),
           "ipc_mode": host.get("IpcMode", ""), "userns_mode": host.get("UsernsMode", ""),
           "security_options": host.get("SecurityOpt") or [], "mounts": mounts,
           "env_names": env_names,
           "rehearsal_only_env_names": [n for n in env_names if n == "NODE_EXTRA_CA_CERTS"],
           "run_id": labels.get("temper.pi.run"), "turn_id_prefix": labels.get("temper.pi.turn")}
    if member:
        if not BOX_NAME.fullmatch(out["name"]):
            raise RigRefusal("not a real WorkerBox name")
        if out["network_mode"] != "none" or out["privileged"] or out["cap_add"] or out["devices"]:
            raise RigRefusal("member has unexpected isolation settings")
        if out["read_only_root"] is not True or "ALL" not in out["cap_drop"]:
            raise RigRefusal("member root or capabilities differ")
        for mount in mounts:
            if "docker.sock" in mount["source"] or "docker.sock" in mount["destination"]:
                raise RigRefusal("member has a Docker socket")
            if "host_helper_socket" in mount["settings"]:
                raise RigRefusal("member has a helper socket")
    return out
