"""The Pi lane's checks before a Pi run starts (M4 ADR-M4-05, SW-46, H3; docs/pi-lane.md).

The run process runs them in the Pi lane (:func:`temper_ai.runner.pi_lane.check_run`), after
the lane and the Pi-only rule and before the run is marked running, so before any turn. Each
failed check is a named reason with plain words. The run fails red naming every one, and
nothing of it runs.

Reasons, in order:

  pi_switched_off    the Pi step is not switched on in this worker
  commit_unreadable  the temper commit this worker runs can't be read from the checkout's
                     .git, which every Pi run records (SW-16)
  box_config         the box config can't be read or fails its own checks: the runtime, Pi
                     version, identity files and the add-on and search-tool pins
                     (:func:`pins_and_identity`, until #53)
  roots              no roots, a root that isn't a folder here, or a state or socket root that
                     isn't writable
  uid                this worker isn't 1000:1000, so its members wouldn't be (SW-43)
  socket_path        a turn's socket path would reach 100 bytes (SW-44)
  docker             Docker doesn't answer
  image              the pinned worker image isn't on this Docker host
  host_helper        live mode without a helper socket, a helper that doesn't answer ok, or a
                     login bridge that isn't ready
  template_mounts    the run-box template mounts a Pi or project folder, or can't be read
  workspace_overlap  a Pi folder inside WORKSPACE_DIR, which every run box may mount (H3)
  pi_schema          the pi_ tables can't be brought to this build's version (ADR-M4-07)
  disk               less than 2 GiB free under the state root (ADR-M4-11)

Not here: the project source's folder checks (ADR-M4-12), which the team's start runs. The
pins check and the identity settings' read-back (D3) come with #53, which replaces
:func:`pins_and_identity`.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

#: Members run as the worker's own user (box.py create_args), which must be this one: the
#: image's ``temperai-worker``, the one uid the host helper answers.
MEMBER_UID = 1000
MEMBER_GID = 1000
MIN_FREE_BYTES = 2 * 1024**3
DOCKER_TIMEOUT_S = 20.0
HELPER_TIMEOUT_S = 5.0
TEMPLATE_ENV = "TEMPER_DOCKER_TEMPLATE_CONTAINER"
WORKSPACE_ENV = "WORKSPACE_DIR"
#: The helper's login bridge may be ready, or not set up at all (a route without one).
BRIDGE_OK = ("ready", "not_configured")

Reason = tuple[str, str]


def preflight(*, docker: Callable[..., Any] | None = None,
              ensure_ledger: Callable[[], None] | None = None) -> list[Reason]:
    """Every failed check as ``(reason, plain words)``; empty when the run may start."""
    from temper_ai import pi_agent

    if not pi_agent.enabled():
        return [("pi_switched_off",
                 f"the Pi step is switched off in the Pi lane's worker ({pi_agent.SWITCH_ENV})")]
    from temper_ai.pi_agent.box import _docker_cli

    failed: list[Reason] = _commit()
    cfg, problems = pins_and_identity()
    failed += problems
    if cfg is None:
        return failed
    run = docker or _docker_cli
    failed += _roots(cfg)
    failed += _uid()
    failed += _socket_path(cfg)
    unreachable = _docker_unreachable(run)
    if unreachable:
        failed.append(("docker", unreachable))
    else:
        failed += _image(cfg, run)
        failed += _template_mounts(cfg, run)
    failed += _host_helper(cfg)
    failed += _workspace_overlap(cfg)
    failed += _pi_schema(ensure_ledger or _ensure_ledger)
    failed += _disk(cfg)
    return failed


def pins_and_identity() -> tuple[Any, list[Reason]]:
    """The box config, with the pins check and the identity check: the one function #53
    replaces (Architecture rm-c9c941d4, item 6).

    INTERIM: until #53's pins function lands, the box config's own checks stand in for both
    (box.py ``BoxConfig.check``, run by ``BoxConfig.load``): the runtime and the Pi version,
    the identity files and folder, and the add-on and search-tool digests, under one reason,
    ``box_config``. #53 swaps this function for its pins function and D3's identity read-back,
    with reasons of their own, and names the swap in its done note. Returns ``(config,
    reasons)``; the config is None when it can't be read at all."""
    from temper_ai.pi_agent.box import BoxConfig, BoxError

    try:
        return BoxConfig.load(), []
    except BoxError as exc:
        return None, [("box_config", str(exc))]


def _commit() -> list[Reason]:
    """Every Pi run records the temper commit it runs on (SW-16): in the Pi lane a commit
    that can't be read refuses the run (a dropped ``.git`` mount would otherwise go unseen)."""
    from temper_ai.runner.pi_lane import read_commit

    commit, why = read_commit()
    if commit:
        return []
    return [("commit_unreadable", f"the temper commit this worker runs can't be read ({why}); "
                                  "every Pi run records it (SW-16)")]


def overlap(a: str, b: str) -> bool:
    """True when one path is the other or inside it (both as written, normalised)."""
    pa, pb = Path(os.path.normpath(a)), Path(os.path.normpath(b))
    return pa == pb or pa.is_relative_to(pb) or pb.is_relative_to(pa)


def _roots(cfg: Any) -> list[Reason]:
    if not cfg.roots:
        return [("roots", "the box config names no roots; the Pi lane mounts each of its "
                          "folders at its own host path and binds nothing from elsewhere")]
    problems = [f"{root} is not a folder here" for root in cfg.roots if not Path(root).is_dir()]
    for what in ("state_root", "socket_root"):
        path = cfg.state_root if what == "state_root" else str(cfg.sockets)
        if not Path(path).is_dir() or not os.access(path, os.W_OK | os.X_OK):
            problems.append(f"the {what} is not a writable folder here")
    return [("roots", "; ".join(problems))] if problems else []


def _uid() -> list[Reason]:
    uid, gid = os.getuid(), os.getgid()
    if (uid, gid) == (MEMBER_UID, MEMBER_GID):
        return []
    return [("uid", f"the Pi lane's worker runs as {uid}:{gid}; its members run as its user, "
                    f"which must be {MEMBER_UID}:{MEMBER_GID}")]


def _socket_path(cfg: Any) -> list[Reason]:
    from temper_ai.pi_agent.box import SOCKET_PATH_LIMIT, SOCKET_TAIL_BYTES

    longest = len(str(cfg.sockets).encode()) + SOCKET_TAIL_BYTES
    if longest < SOCKET_PATH_LIMIT:
        return []
    return [("socket_path", f"a turn's socket path would be {longest} bytes; it must stay under "
                            f"{SOCKET_PATH_LIMIT} (use a shorter socket_root)")]


def _docker_unreachable(run: Callable[..., Any]) -> str | None:
    try:
        got = run("version", "--format", "{{.Server.Version}}", timeout=DOCKER_TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"Docker could not be asked ({type(exc).__name__})"
    if got.returncode != 0 or not (got.stdout or "").strip():
        return "Docker doesn't answer (the socket or its group missing?)"
    return None


def _image(cfg: Any, run: Callable[..., Any]) -> list[Reason]:
    try:
        got = run("image", "inspect", "--format", "{{.Id}}", cfg.image, timeout=DOCKER_TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [("image", f"the worker image could not be looked up ({type(exc).__name__})")]
    if got.returncode != 0 or (got.stdout or "").strip() != cfg.image:
        return [("image", f"the pinned worker image {cfg.image[:19]} is not on this Docker host")]
    return []


def _template_mounts(cfg: Any, run: Callable[..., Any]) -> list[Reason]:
    name = os.environ.get(TEMPLATE_ENV, "").strip()
    if not name:
        return [("template_mounts", f"{TEMPLATE_ENV} is not set, so the run-box template's "
                                    "mounts can't be checked")]
    try:
        got = run("inspect", "--type", "container", "--format", "{{json .Mounts}}", name,
                  timeout=DOCKER_TIMEOUT_S)
        mounts = json.loads(got.stdout) if got.returncode == 0 else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        mounts = None
    if not isinstance(mounts, list):
        return [("template_mounts", f"the run-box template {name} could not be inspected")]
    sources = [str(m.get("Source") or "") for m in mounts if isinstance(m, dict)]
    # Every Pi path (box.py BoxConfig.pi_paths: state, sockets, pins, role folders, the
    # helper's socket folder, project roots), the mount being it, inside it or above it.
    clash = sorted({what for what, path in cfg.pi_paths().items()
                    for source in sources if source and overlap(source, path)})
    if clash:
        return [("template_mounts", f"the run-box template {name} mounts a Pi or project "
                                    f"folder ({', '.join(clash)}), which every run box would get")]
    return []


def _host_helper(cfg: Any) -> list[Reason]:
    if not cfg.host_helper_socket:
        if cfg.mode == "live":
            return [("host_helper", "live mode needs the host helper (host_helper_socket)")]
        return []
    from temper_ai.pi_agent.host_helper import HelperUnreachable, ask

    try:
        answer = ask(cfg.host_helper_socket, "status", HELPER_TIMEOUT_S)
    except HelperUnreachable as exc:
        return [("host_helper", str(exc))]
    verb, _, rest = answer.partition(" ")
    if verb != "ok":
        return [("host_helper", "the host helper didn't answer ok to status")]
    try:
        status = json.loads(rest)
    except ValueError:
        return [("host_helper", "the host helper's status could not be read")]
    state = str(((status if isinstance(status, dict) else {}).get("bridge") or {}).get("state")
                or "unknown")
    if state not in BRIDGE_OK:
        return [("host_helper", f"the host helper's login bridge is {state[:40]}, not ready")]
    return []


def _workspace_overlap(cfg: Any) -> list[Reason]:
    workspaces = os.environ.get(WORKSPACE_ENV, "").strip()
    if not workspaces:
        return [("workspace_overlap", f"{WORKSPACE_ENV} is not set, so the Pi folders can't be "
                                      "checked against the run workspaces")]
    inside = sorted(what for what, path in cfg.pi_paths().items()
                    if Path(os.path.realpath(path)).is_relative_to(os.path.realpath(workspaces)))
    if inside:
        return [("workspace_overlap", f"{', '.join(inside)} inside {WORKSPACE_ENV}, which every "
                                      "run box may mount read-write")]
    return []


def _ensure_ledger() -> None:
    from temper_ai.database import get_database
    from temper_ai.pi_agent.ledger import Ledger

    Ledger(get_database().engine).ensure()


def _pi_schema(ensure: Callable[[], None]) -> list[Reason]:
    from temper_ai.pi_agent.ledger import LedgerError

    try:
        ensure()
    except LedgerError as exc:
        return [("pi_schema", str(exc))]
    except Exception as exc:  # noqa: BLE001 - any database failure is this reason, plainly
        return [("pi_schema", f"the pi_ tables could not be checked ({type(exc).__name__})")]
    return []


def _disk(cfg: Any) -> list[Reason]:
    try:
        free = shutil.disk_usage(cfg.state_root).free
    except OSError as exc:
        return [("disk", f"free space under the state root can't be read ({type(exc).__name__})")]
    if free >= MIN_FREE_BYTES:
        return []
    return [("disk", f"{free // 2**20} MiB free under the state root; the Pi lane needs "
                     f"{MIN_FREE_BYTES // 2**30} GiB")]
