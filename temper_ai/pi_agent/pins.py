"""The Pi pins: every part a Pi member box runs on, by digest, and the model-free check of them
(M4 ADR-M4-04; SW-16, SW-24, SW-26, SW-29, SW-50; docs/pi-lane.md, "The pins").

The private box config (``local/pi/pi-box.json``, git-ignored; ``TEMPER_PI_BOX_CONFIG``) names
each pin and the digest it must have. The check's pins, by name:

  image               the worker image's id (``image``), present on this Docker host
  image_tag           the image's tag (``image_tag``), which must name that same id, so a
                      prune of dangling images never removes it
  image_tar           the image saved with ``docker save`` (``image_tar``, ``image_tar_sha256``)
  runtime             the Pi runtime folder (``runtime_dir``, ``runtime_sha256``: every entry,
                      node_modules and links included; :func:`full_tree_sha256`)
  pi_version          ``pi_version``, read back by running the runtime's own Pi offline
  search_tool:<name>  the static ``rg`` and ``fd`` at the runtime's top level (``search_tools``)
  add_ons             the pinned add-ons' names, which must be exactly :data:`DEFAULT_ADD_ONS`
                      (SW-29): a pin for any other add-on, or a default add-on without a pin,
                      is a mismatch
  add_on:<name>       each add-on's pinned copy (``add_ons``; :func:`tree_sha256`)
  identity_extension  the identity extension (``identity_extension``,
                      ``identity_extension_sha256``)
  identity_settings   the shared identity settings, ``pi-identity.json`` and
                      ``pi-identity-role.md`` (``identity_config``, ``identity_config_sha256``;
                      M2-roles D3, SW-26)
  route:<name>        each route's login extension or model catalog (``routes.<name>``:
                      ``extension_sha256``, ``catalog_sha256``)

A pin the box config doesn't record is a mismatch too: every part is pinned or the check fails.

:func:`check_pins` reads the box config, the pinned files, ``docker image inspect`` and the
runtime's ``pi --version`` (offline, in an empty environment), and nothing else: no network, no
model, no ``.env``, no credentials or token files (the Docker command runs without its config
folder). It writes nothing. Its report names pins and digests only, never a path: temper-ci's
live check publishes it.

Stdlib only and no temper import: ``scripts/pi_pins_check.py`` loads this file by path on the
host (temper-ci's live check, as the host user), and the Pi lane's preflight imports it
(runner/pi_preflight.py) for the same check before every Pi run. The box hashes add-ons and the
identity with its :func:`tree_sha256`.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

#: The add-ons every Pi member loads unless its config lists its own, each from a pinned copy:
#: exactly the ones the worker box test passed (M2, 2026-10-04; SW-29). billion-context-pi stays
#: out (member.py REFUSED_ADD_ONS). member.py's ADD_ONS, this list and the box test's list are
#: the same two (tests/test_pi_agent/test_pins.py).
DEFAULT_ADD_ONS: tuple[str, ...] = ("pi-image-trim", "pi-tldr")
#: The search binaries a production runtime pins (search_tools.py PINS; SW-24).
SEARCH_TOOLS: tuple[str, ...] = ("fd", "rg")
#: The whole check stays under this many seconds (Systems' rm-a8af8c68 item 2).
LIMIT_S = 60.0
PASS, MISMATCH, ERROR, NOT_SET_UP = "pass", "mismatch", "error", "not_set_up"
EXIT_CODES = {PASS: 0, MISMATCH: 1, ERROR: 2, NOT_SET_UP: 3}
#: The pins the identity read-back (D3) is about; the Pi lane's preflight names them apart.
IDENTITY_PINS = ("identity_extension", "identity_settings")
#: The pins about the image on the Docker host; the preflight names them apart too.
IMAGE_PINS = ("image", "image_tag")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
IMAGE_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]{1,40})?$")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
TAG_RE = re.compile(r"^[a-z0-9][a-z0-9._/-]{0,127}:[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$")
#: The runtime's Pi, as box.py starts it.
CLI_REL = "pi/dist/bundle/cli.js"
STEP_TIMEOUT_S = 20.0
CHUNK = 1 << 20
NOWHERE = "/nonexistent"
#: The whole environment the runtime's Pi prints its version in: no home or agent folder (it
#: makes none), offline, no update check, no telemetry; nothing of this process's environment.
VERSION_ENV = {"PATH": "/usr/bin:/bin", "HOME": NOWHERE, "PI_CODING_AGENT_DIR": NOWHERE + "/agent",
               "PI_OFFLINE": "1", "PI_SKIP_VERSION_CHECK": "1", "PI_TELEMETRY": "0",
               "LANG": "C.UTF-8"}

#: ``docker`` as the check asks it: ``(*args, timeout=)`` -> an object with ``returncode``,
#: ``stdout`` and ``stderr``.
Docker = Callable[..., Any]


class PinCheckError(Exception):
    """The check couldn't run: plain words, never a path."""


class Budget:
    """The check's time limit: :meth:`left` is the time left, and raises once it is spent."""

    def __init__(self, limit_s: float = LIMIT_S, clock: Callable[[], float] = time.monotonic):
        self.limit_s = limit_s
        self.clock = clock
        self.end = clock() + limit_s

    def left(self) -> float:
        left = self.end - self.clock()
        if left <= 0:
            raise PinCheckError(f"the pin check took longer than {self.limit_s:g} s")
        return left


def file_sha256(path: str | os.PathLike[str],
                deadline: Callable[[], object] | None = None) -> str | None:
    """A file's sha256 (hex), or None when it can't be read."""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(CHUNK), b""):
                if deadline is not None:
                    deadline()
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def tree_sha256(root: str | os.PathLike[str],
                deadline: Callable[[], object] | None = None) -> str:
    """One digest over a folder's regular files (relative path + content), node_modules and
    symlinks excluded: the digest pinned for an add-on, the identity extension and settings,
    and a route's login extension."""
    h = hashlib.sha256()
    root = Path(root)
    files = sorted(p for p in root.rglob("*")
                   if p.is_file() and not p.is_symlink() and "node_modules" not in p.parts)
    for p in files:
        h.update(p.relative_to(root).as_posix().encode() + b"\0")
        h.update(_content_digest(p, deadline))
    return h.hexdigest()


def full_tree_sha256(root: str | os.PathLike[str],
                     deadline: Callable[[], object] | None = None) -> str:
    """One digest over everything under ``root``: each entry's relative path, kind and mode, a
    file's content, a link's target; links never followed, node_modules included. The digest
    pinned for the Pi runtime, as ``scripts/pi_search_tools.py`` digests the runtime it builds."""
    h = hashlib.sha256()
    root = Path(root)
    entries: list[Path] = []
    for folder, dirs, files in os.walk(root, followlinks=False):
        if deadline is not None:
            deadline()
        dirs.sort()
        entries += [Path(folder) / name for name in sorted(dirs + files)]
    for path in sorted(entries, key=lambda p: p.relative_to(root).as_posix()):
        info = path.lstat()
        rel = path.relative_to(root).as_posix()
        if stat.S_ISLNK(info.st_mode):
            kind, body = "l", os.readlink(path).encode()
        elif stat.S_ISDIR(info.st_mode):
            kind, body = "d", b""
        elif stat.S_ISREG(info.st_mode):
            kind, body = "f", _content_digest(path, deadline)
        else:
            kind, body = "o", b""
        h.update(f"{kind} {stat.S_IMODE(info.st_mode):o} {rel}\0".encode() + body + b"\0")
    return h.hexdigest()


def _content_digest(path: Path, deadline: Callable[[], object] | None) -> bytes:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK), b""):
            if deadline is not None:
                deadline()
            h.update(chunk)
    return h.digest()


# --- the check --------------------------------------------------------------------------------

def check_pins(config_path: str | os.PathLike[str] | None, *, docker: Docker | None = None,
               pi_version: Callable[[Path, float], str | None] | None = None,
               limit_s: float = LIMIT_S,
               clock: Callable[[], float] = time.monotonic) -> dict[str, Any]:
    """Every pin in the box config at ``config_path`` against what is on this host.

    Returns ``{"result": pass | mismatch | not_set_up | error, "pins": [{"name", "want",
    "have", "ok"}], "error": plain words}`` (``error`` only when there is one). ``want`` is the
    box config's digest (None when it records none, or for a pin that must not be there),
    ``have`` what is here (None when it is missing). No box config at that path is
    ``not_set_up``; a config that can't be read, Docker not answering or the time limit spent
    is ``error``."""
    budget = Budget(limit_s, clock)
    if not config_path or not os.path.lexists(config_path):
        return report(NOT_SET_UP, [], "there is no private box config yet")
    try:
        raw = json.loads(Path(config_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return report(ERROR, [], f"the box config could not be read ({type(exc).__name__})")
    if not isinstance(raw, dict):
        return report(ERROR, [], "the box config is not a JSON object")
    pins: list[dict[str, Any]] = []
    try:
        pins += image_pins(raw, docker or docker_cli, budget)
        pins += runtime_pins(raw, pi_version or runtime_pi_version, budget)
        pins += add_on_pins(raw, budget)
        pins += identity_pins(raw, budget)
        pins += route_pins(raw, budget)
    except PinCheckError as exc:
        return report(ERROR, pins, str(exc))
    except Exception as exc:  # noqa: BLE001 - any failure is "couldn't run", plainly
        return report(ERROR, pins, f"the pin check failed ({type(exc).__name__})")
    return report(PASS if all(pin["ok"] for pin in pins) else MISMATCH, pins)


def report(result: str, pins: list[dict[str, Any]], error: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"result": result, "pins": pins}
    if error:
        out["error"] = error
    return out


def exit_code(result: dict[str, Any]) -> int:
    return EXIT_CODES.get(str(result.get("result")), EXIT_CODES[ERROR])


def pin(name: str, want: Any, have: Any) -> dict[str, Any]:
    return {"name": name, "want": want, "have": have, "ok": want is not None and want == have}


def failed(result: dict[str, Any]) -> list[str]:
    """The names of the pins that don't match."""
    return [str(p["name"]) for p in result.get("pins") or [] if not p.get("ok")]


def digests(result: dict[str, Any]) -> dict[str, Any]:
    """Each pin's digest (or name list, or version) as the check read it, by name: what a Pi
    run records of its pins (SW-16)."""
    return {str(p["name"]): p.get("have") for p in result.get("pins") or []}


def image_pins(raw: dict, docker: Docker, budget: Budget) -> list[dict[str, Any]]:
    image = _text(raw.get("image"))
    want = image if IMAGE_RE.match(image) else None
    pins = [pin("image", want, image_id(docker, image, budget) if want else None)]
    tag = _text(raw.get("image_tag"))
    want_tag = want if TAG_RE.match(tag) else None
    pins.append(pin("image_tag", want_tag, image_id(docker, tag, budget) if want_tag else None))
    tar = _file(raw.get("image_tar"))
    pins.append(pin("image_tar", _digest(raw.get("image_tar_sha256")),
                    file_sha256(tar, budget.left) if tar else None))
    return pins


def image_id(docker: Docker, ref: str, budget: Budget) -> str | None:
    """The id Docker has for ``ref``; None when it has no such image."""
    try:
        got = docker("image", "inspect", "--format", "{{.Id}}", ref,
                     timeout=min(STEP_TIMEOUT_S, budget.left()))
    except subprocess.TimeoutExpired:
        raise PinCheckError("Docker did not answer in time") from None
    except OSError as exc:
        raise PinCheckError(f"Docker could not be asked ({type(exc).__name__})") from None
    out = (getattr(got, "stdout", "") or "").strip()
    if getattr(got, "returncode", 1) == 0 and IMAGE_RE.match(out):
        return out
    # Only the daemon's own answer counts as "not here": an unreachable daemon says "no such
    # file or directory" about its socket, which must not read as a missing image.
    if "no such image" in (getattr(got, "stderr", "") or "").lower():
        return None
    raise PinCheckError("Docker didn't answer (is the daemon up, and its socket reachable?)")


def docker_cli(*args: str, timeout: float = STEP_TIMEOUT_S) -> subprocess.CompletedProcess:
    """``docker`` with no config folder (so no registry credentials are read) and nothing else
    of this process's environment but where Docker is."""
    env = {"PATH": "/usr/bin:/bin:/usr/local/bin", "DOCKER_CONFIG": NOWHERE}
    if os.environ.get("DOCKER_HOST"):
        env["DOCKER_HOST"] = os.environ["DOCKER_HOST"]
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout,
                          env=env, stdin=subprocess.DEVNULL, check=False)


def runtime_pins(raw: dict, pi_version: Callable[[Path, float], str | None],
                 budget: Budget) -> list[dict[str, Any]]:
    runtime = _folder(raw.get("runtime_dir"))
    pins = [pin("runtime", _digest(raw.get("runtime_sha256")),
                full_tree_sha256(runtime, budget.left) if runtime else None),
            pin("pi_version", _text(raw.get("pi_version")) or None,
                pi_version(runtime, min(STEP_TIMEOUT_S, budget.left())) if runtime else None)]
    tools = raw.get("search_tools") or {}
    if not isinstance(tools, dict):
        raise PinCheckError("the box config's search_tools is not an object")
    for name in sorted(set(SEARCH_TOOLS) | set(tools)):
        entry = tools.get(name)
        want = _digest(entry.get("sha256")) if isinstance(entry, dict) and name in SEARCH_TOOLS \
            else None
        binary = runtime / name if runtime and name in SEARCH_TOOLS else None
        have = file_sha256(binary, budget.left) \
            if binary is not None and binary.is_file() and not binary.is_symlink() else None
        pins.append(pin(f"search_tool:{_name(name)}", want, have))
    return pins


def runtime_pi_version(runtime: Path, timeout: float) -> str | None:
    """The version the runtime's own Pi prints, run offline in :data:`VERSION_ENV`."""
    node, cli = runtime / "node", runtime / CLI_REL
    if not node.is_file() or not cli.is_file():
        return None
    try:
        got = subprocess.run([str(node), str(cli), "--offline", "--version"], cwd="/",
                             env=dict(VERSION_ENV), capture_output=True, text=True,
                             timeout=timeout, stdin=subprocess.DEVNULL, check=False)
    except subprocess.TimeoutExpired:
        raise PinCheckError("the runtime's Pi did not print its version in time") from None
    except OSError:
        return None
    out = (got.stdout or "").strip()
    return out if got.returncode == 0 and VERSION_RE.match(out) else None


def add_on_pins(raw: dict, budget: Budget) -> list[dict[str, Any]]:
    add_ons = raw.get("add_ons") or {}
    if not isinstance(add_ons, dict):
        raise PinCheckError("the box config's add_ons is not an object")
    pins = [pin("add_ons", list(DEFAULT_ADD_ONS), sorted(_name(name) for name in add_ons))]
    for name in sorted(set(add_ons) | set(DEFAULT_ADD_ONS)):
        entry = add_ons.get(name)
        entry = entry if isinstance(entry, dict) else {}
        want = _digest(entry.get("sha256")) if name in DEFAULT_ADD_ONS else None
        folder = _folder(entry.get("dir"))
        pins.append(pin(f"add_on:{_name(name)}", want,
                        tree_sha256(folder, budget.left) if folder else None))
    return pins


def identity_pins(raw: dict, budget: Budget) -> list[dict[str, Any]]:
    ext, conf = _folder(raw.get("identity_extension")), _folder(raw.get("identity_config"))
    return [pin("identity_extension", _digest(raw.get("identity_extension_sha256")),
                tree_sha256(ext, budget.left) if ext else None),
            pin("identity_settings", _digest(raw.get("identity_config_sha256")),
                tree_sha256(conf, budget.left) if conf else None)]


def route_pins(raw: dict, budget: Budget) -> list[dict[str, Any]]:
    routes = raw.get("routes") or {}
    if not isinstance(routes, dict):
        raise PinCheckError("the box config's routes is not an object")
    pins = []
    for name in sorted(routes):
        route = routes[name] if isinstance(routes[name], dict) else {}
        if route.get("extension"):
            folder = _folder(route.get("extension"))
            pins.append(pin(f"route:{_name(name)}", _digest(route.get("extension_sha256")),
                            tree_sha256(folder, budget.left) if folder else None))
        if route.get("catalog"):
            catalog = _file(route.get("catalog"))
            pins.append(pin(f"route:{_name(name)}:catalog", _digest(route.get("catalog_sha256")),
                            file_sha256(catalog, budget.left) if catalog else None))
    return pins


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _digest(value: Any) -> str | None:
    text = _text(value)
    return text if SHA256_RE.match(text) else None


def _name(value: Any) -> str:
    """A name from the box config as the report shows it: plain, or not shown at all."""
    text = _text(value)
    return text if NAME_RE.match(text) else "(not a plain name)"


def _folder(value: Any) -> Path | None:
    text = _text(value)
    return Path(text) if text and os.path.isabs(text) and Path(text).is_dir() else None


def _file(value: Any) -> Path | None:
    text = _text(value)
    return Path(text) if text and os.path.isabs(text) and Path(text).is_file() else None
