"""The Pi lane's checks before a Pi run starts (M4 ADR-M4-05, SW-46, H3; docs/pi-lane.md).

The run process runs them in the Pi lane (:func:`temper_ai.runner.pi_lane.check_run`), after
the lane and the Pi-only rule and before the run is marked running, so before any turn. Each
failed check is a named reason with plain words. The run fails red naming every one, and
nothing of it runs.

Reasons, in order:

  pi_switched_off    the Pi step is not switched on in this worker
  commit_unreadable  the temper commit this worker runs can't be read from the checkout's
                     .git, which every Pi run records (SW-16)
  box_config         the box config can't be read or fails its own checks (box.py
                     ``BoxConfig.check``): the runtime and Pi version, the identity files, and
                     the add-on, search-tool, identity and login digests it pins, read back
                     now (a changed add-on or identity is refused here)
  roots              no roots, a root that isn't a folder here, or a state or socket root that
                     isn't writable
  uid                this worker isn't 1000:1000, so its members wouldn't be (SW-43)
  socket_path        a turn's socket path would reach 100 bytes (SW-44)
  docker             Docker doesn't answer
  image              the pinned worker image isn't on this Docker host, or its tag doesn't
                     name it (the pin check's ``image`` and ``image_tag``)
  pins               any other pin that differs from the box config or isn't recorded there:
                     the image's tar, the runtime, the Pi version its own Pi prints, the
                     search binaries, the add-ons (exactly pi-image-trim and pi-tldr, SW-29),
                     the login extension; or the pin check couldn't run
                     (:mod:`temper_ai.pi_agent.pins`, the check ``scripts/pi_pins_check.py``
                     runs on the host)
  identity           the box config pins no digest for the identity extension or the shared
                     identity settings, so they can't be read back, or one changed since
                     (M2-roles D3, SW-26)
  template_mounts    the run-box template mounts a Pi or project folder (or the account-room
                     folder), or can't be read
  host_helper        live mode without a helper socket, a helper that doesn't answer ok, or a
                     login bridge that isn't ready
  workspace_overlap  a Pi folder (or the account-room folder) inside WORKSPACE_DIR, which
                     every run box may mount (H3)
  account_room       the team settings name no account_room_file, or its folder isn't this
                     worker's own read-only mount (ADR-M4-18). Never whether the file is
                     there or fresh: a run's first claim reads it (pi_agent/accounts.py), so
                     the lane may start before ops' writer first publishes it
  pi_schema          the pi_ tables can't be brought to this build's version (ADR-M4-07)
  disk               less than 2 GiB free under the state root (ADR-M4-11)

What it read for the run's record (SW-16), when asked (``record``): every pin's digest as
checked, and the host's Pi version from the host helper's status.

Not here: the project source's folder checks (ADR-M4-12), which the team's start runs.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
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
              ensure_ledger: Callable[[], None] | None = None,
              record: dict[str, Any] | None = None) -> list[Reason]:
    """Every failed check as ``(reason, plain words)``; empty when the run may start. Given
    ``record``, puts in it what the run records (SW-16): ``pins`` (each pin's digest as
    checked) and ``host_pi`` (the host's Pi version)."""
    from temper_ai import pi_agent

    if not pi_agent.enabled():
        return [("pi_switched_off",
                 f"the Pi step is switched off in the Pi lane's worker ({pi_agent.SWITCH_ENV})")]
    from temper_ai.pi_agent.box import CONFIG_ENV, _docker_cli

    record = {} if record is None else record
    failed: list[Reason] = _commit()
    path = os.environ.get(CONFIG_ENV, "")
    cfg, problems = _box_config(path)
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
        failed += _pins(path, run, record)
        failed += _template_mounts(cfg, run)
    failed += _host_helper(cfg, record)
    failed += _workspace_overlap(cfg)
    failed += _account_room()
    failed += _pi_schema(ensure_ledger or _ensure_ledger)
    failed += _disk(cfg)
    return failed


def _box_config(path: str) -> tuple[Any, list[Reason]]:
    """The box config and its own checks (box.py ``BoxConfig.check``); None when it fails."""
    from temper_ai.pi_agent.box import BoxConfig, BoxError

    try:
        return BoxConfig.load(path), []
    except BoxError as exc:
        return None, [("box_config", str(exc))]


def _pins(path: str, run: Callable[..., Any], record: dict[str, Any]) -> list[Reason]:
    """The pin check, the same one ``scripts/pi_pins_check.py`` runs on the host
    (:func:`temper_ai.pi_agent.pins.check_pins`), its failures under three reasons: the
    image, the identity (D3) and every other pin."""
    from temper_ai.pi_agent import pins

    result = pins.check_pins(path, docker=run)
    record["pins"] = pins.digests(result)
    if result["result"] == pins.PASS:
        return []
    if result["result"] != pins.MISMATCH:
        return [("pins", f"the pin check couldn't run: {result.get('error') or 'no reason'}")]
    failed = pins.failed(result)
    image = [name for name in failed if name in pins.IMAGE_PINS]
    identity = [name for name in failed if name in pins.IDENTITY_PINS]
    other = [name for name in failed if name not in image and name not in identity]
    reasons: list[Reason] = []
    if image:
        reasons.append(("image", "the pinned worker image isn't on this Docker host, or its "
                                 f"tag doesn't name it ({', '.join(image)})"))
    if other:
        reasons.append(("pins", "these pins differ from the box config's, or it doesn't "
                                f"record them: {', '.join(other)}"))
    if identity:
        reasons.append(("identity", "the box config pins no digest for these, or they don't "
                                    "read back with it (D3): " + ", ".join(identity)))
    return reasons


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
    # helper's socket folder, project roots) and the account-room folder, the mount being
    # it, inside it or above it.
    clash = sorted({what for what, path in _guarded_paths(cfg).items()
                    for source in sources if source and overlap(source, path)})
    if clash:
        return [("template_mounts", f"the run-box template {name} mounts a Pi or project "
                                    f"folder ({', '.join(clash)}), which every run box would get")]
    return []


def account_room_folder() -> str | None:
    """The folder of the team settings' ``account_room_file`` (ops' folder, which pi-worker
    alone mounts read-only), else None."""
    from temper_ai.pi_agent.team_config import load_team_config

    path = load_team_config().account_room_file
    return os.path.dirname(path) if path else None


def _guarded_paths(cfg: Any) -> dict[str, str]:
    """The folders no run box may get: every Pi path, and the account-room folder."""
    paths = dict(cfg.pi_paths())
    folder = account_room_folder()
    if folder:
        paths["account_room"] = folder
    return paths


def _is_mount(path: str) -> bool:
    return os.path.ismount(path)


def _read_only(path: str) -> bool:
    return bool(os.statvfs(path).f_flag & os.ST_RDONLY)


def _account_room() -> list[Reason]:
    """The account-room file's folder is this worker's own read-only mount and a folder, its
    path reached without a link (account-room interface). Whether the file is there or
    fresh is left to a run's first claim."""
    folder = account_room_folder()
    if not folder:
        return [("account_room", "the team settings name no account_room_file, so no Pi "
                                 "run's account can be picked")]
    where = f"the account-room folder {folder}"
    try:
        info = os.lstat(folder)
    except OSError:
        return [("account_room", f"{where} isn't here (pi-worker's read-only mount of it is "
                                 "missing)")]
    if not stat.S_ISDIR(info.st_mode):
        return [("account_room", f"{where} isn't a folder")]
    if os.path.realpath(folder) != folder:
        return [("account_room", f"{where} is reached through a link")]
    problems = []
    if not _is_mount(folder):
        problems.append(f"{where} isn't its own mount (pi-worker's read-only mount of it is "
                        "missing)")
    try:
        read_only = _read_only(folder)
    except OSError:
        read_only = False
    if not read_only:
        problems.append(f"{where} is writable here; pi-worker mounts it read-only")
    return [("account_room", "; ".join(problems))] if problems else []


def _host_helper(cfg: Any, record: dict[str, Any]) -> list[Reason]:
    """The host helper answers ok and its login bridge is ready; the host's Pi version it
    reports goes in ``record`` (``host_pi``, SW-16)."""
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
    status = status if isinstance(status, dict) else {}
    record["host_pi"] = str(status.get("pi") or "unknown")[:40]
    state = str((status.get("bridge") or {}).get("state") or "unknown")
    if state not in BRIDGE_OK:
        return [("host_helper", f"the host helper's login bridge is {state[:40]}, not ready")]
    return []


def _workspace_overlap(cfg: Any) -> list[Reason]:
    workspaces = os.environ.get(WORKSPACE_ENV, "").strip()
    if not workspaces:
        return [("workspace_overlap", f"{WORKSPACE_ENV} is not set, so the Pi folders can't be "
                                      "checked against the run workspaces")]
    inside = sorted(what for what, path in _guarded_paths(cfg).items()
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
