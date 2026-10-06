#!/usr/bin/env python3
"""Make a Pi runtime whose grep and find work in the sealed, offline worker box (queue #47).

    uv run python scripts/pi_search_tools.py --from <runtime> --to <new runtime>

Copies ``<runtime>`` (node and Pi, unchanged; links kept as they are) into a new folder
``<new runtime>``, adds the pinned static ``rg`` and ``fd`` at its top level (``/pi-runtime/rg``
and ``/pi-runtime/fd`` in the box, first on the box ``PATH``), writes ``search-tools.json``,
makes the whole tree read only, moves it into place and prints the ``search_tools`` block for
the worker box config.

Every download happens here, on the host, and is checked against the pins in
``temper_ai/pi_agent/search_tools.py``: first the archive's sha256, then the binary's. Only the
named binary is taken out of each archive. Refuses when ``<new runtime>`` already exists, when its
parent folder doesn't (the parent is never made or changed), or when this machine isn't aarch64.
Nothing is written before every download has passed its checks. ``<runtime>`` is never changed:
its tree digest is compared before and after. Stdlib only.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
import os
import platform
import shutil
import stat
import sys
import tarfile
import tempfile
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

PINS_FILE = Path(__file__).resolve().parents[1] / "temper_ai" / "pi_agent" / "search_tools.py"
#: The largest archive the script reads (both pinned archives are under 2 MB).
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
DOWNLOAD_TIMEOUT_S = 120


class Refused(Exception):
    """A plain reason the runtime was not made; nothing was left behind."""


def load_pins(path: Path = PINS_FILE) -> ModuleType:
    """temper's pin module, read straight from its file (no temper package import)."""
    spec = importlib.util.spec_from_file_location("_temper_pi_search_pins", path)
    if spec is None or spec.loader is None:
        raise Refused(f"can't read the pins in {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up while it loads
    spec.loader.exec_module(module)
    return module


def fetch_url(url: str) -> bytes:
    """One release asset, over HTTPS, at most :data:`MAX_ARCHIVE_BYTES`."""
    if not url.startswith("https://"):
        raise Refused(f"refusing a download that isn't https: {url}")
    with urllib.request.urlopen(url, timeout=DOWNLOAD_TIMEOUT_S) as answer:  # noqa: S310
        data = answer.read(MAX_ARCHIVE_BYTES + 1)
    if len(data) > MAX_ARCHIVE_BYTES:
        raise Refused(f"{url} is larger than {MAX_ARCHIVE_BYTES} bytes")
    return data


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tree_digest(root: Path) -> str:
    """One digest over everything under ``root``: each entry's relative path, kind and mode,
    a file's content, a link's target. Links are never followed."""
    h = hashlib.sha256()
    root = Path(root)
    entries: list[Path] = []
    for folder, dirs, files in os.walk(root, followlinks=False):
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
            kind, body = "f", bytes.fromhex(file_digest(path))
        else:
            kind, body = "o", b""
        h.update(f"{kind} {stat.S_IMODE(info.st_mode):o} {rel}\0".encode() + body + b"\0")
    return h.hexdigest()


def file_digest(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def take_binary(archive: bytes, member: str) -> bytes:
    """The one named regular file from a .tar.gz, read into memory; nothing is extracted."""
    try:
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
            info = tar.getmember(member)
            if not info.isreg():
                raise Refused(f"{member} in the archive is not a plain file")
            fh = tar.extractfile(info)
            if fh is None:
                raise Refused(f"can't read {member} from the archive")
            return fh.read()
    except KeyError:
        raise Refused(f"the archive has no {member}") from None
    except (tarfile.TarError, OSError, EOFError) as exc:
        raise Refused(f"the archive can't be read ({type(exc).__name__})") from None


def checked_binaries(pins: dict[str, Any], fetch: Callable[[str], bytes]) -> dict[str, bytes]:
    """Every pinned binary, downloaded and checked: the archive's digest, then the binary's."""
    out: dict[str, bytes] = {}
    for name, pin in sorted(pins.items()):
        archive = fetch(pin.url)
        got = sha256(archive)
        if got != pin.archive_sha256:
            raise Refused(f"{name}: the downloaded archive's sha256 is {got}, not the pinned "
                          f"{pin.archive_sha256}; nothing was written")
        binary = take_binary(archive, pin.member)
        got = sha256(binary)
        if got != pin.sha256:
            raise Refused(f"{name}: {pin.member}'s sha256 is {got}, not the pinned {pin.sha256}; "
                          "nothing was written")
        out[name] = binary
    return out


def read_only(root: Path) -> None:
    """Take every write bit off the tree (links are left as they are)."""
    for folder, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            path = Path(folder) / name
            if not path.is_symlink():
                path.chmod(stat.S_IMODE(path.lstat().st_mode) & ~0o222)
    root.chmod(stat.S_IMODE(root.lstat().st_mode) & ~0o222)


def remove_tree(root: Path) -> None:
    """Remove a half-made copy, read-only folders included."""
    if not root.exists():
        return
    for folder, dirs, _files in os.walk(root, followlinks=False):
        for name in dirs:
            path = Path(folder) / name
            if not path.is_symlink():
                path.chmod(0o700)
    root.chmod(0o700)
    shutil.rmtree(root, ignore_errors=True)


def pi_version(runtime: Path) -> str | None:
    try:
        return json.loads((runtime / "pi" / "package.json").read_text(encoding="utf-8"))["version"]
    except (OSError, ValueError, KeyError):
        return None


def install(source: Path, target: Path, *, fetch: Callable[[str], bytes] = fetch_url,
            machine: str | None = None, pins_module: ModuleType | None = None) -> dict:
    """Make ``target`` as a read-only copy of ``source`` plus the pinned search binaries.
    Returns the box config's ``search_tools`` block. Raises :class:`Refused` with nothing
    left behind."""
    mod = pins_module or load_pins()
    pins = mod.PINS
    machine = machine or platform.machine()
    if machine != mod.MACHINE:
        raise Refused(f"this machine is {machine}; the pinned builds are {mod.MACHINE} only")
    source, target = Path(source).absolute(), Path(target).absolute()
    if os.path.lexists(target):
        raise Refused(f"{target} already exists; a runtime is never changed in place")
    if not target.parent.is_dir():
        raise Refused(f"{target.parent} doesn't exist; it is not made here")
    if not (source / "node").is_file() or pi_version(source) is None:
        raise Refused(f"{source} is not a Pi runtime (node and pi/package.json)")
    before = tree_digest(source)
    binaries = checked_binaries(pins, fetch)

    tmp = Path(tempfile.mkdtemp(prefix=f".{target.name}-", dir=target.parent))
    try:
        shutil.copytree(source, tmp, symlinks=True, dirs_exist_ok=True)
        if tree_digest(tmp) != before:
            raise Refused("the copy of the source runtime differs from it")
        # The copy has the source's modes (read only); the owner writes rg, fd and the manifest,
        # then every write bit comes off again.
        tmp.chmod(stat.S_IMODE(tmp.lstat().st_mode) | 0o700)
        for name, data in sorted(binaries.items()):
            fd = os.open(tmp / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            (tmp / name).chmod(0o555)
        manifest = {
            "what": "static rg and fd for Pi's grep and find in the sealed, offline worker box "
                    "(temper queue #47)",
            "made_by": "scripts/pi_search_tools.py",
            "made_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "machine": mod.MACHINE,
            "pi_version": pi_version(source),
            "source_runtime": str(source),
            "source_tree_sha256": before,
            "search_tools": {name: {"version": pin.version, "version_line": pin.version_line,
                                    "url": pin.url, "archive_sha256": pin.archive_sha256,
                                    "member": pin.member, "sha256": pin.sha256}
                             for name, pin in sorted(pins.items())},
        }
        (tmp / mod.MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        read_only(tmp)
        for name, pin in pins.items():
            if file_digest(tmp / name) != pin.sha256:
                raise Refused(f"{name} changed while it was written")
        if os.path.lexists(target):
            raise Refused(f"{target} appeared while the copy was made; left as it is")
        os.rename(tmp, target)
    except BaseException:
        remove_tree(tmp)
        raise
    if tree_digest(source) != before:
        raise Refused(f"the source runtime {source} changed while the copy was made; check it "
                      f"(the new runtime {target} was made)")
    return {name: {"version": pin.version, "sha256": pin.sha256}
            for name, pin in sorted(pins.items())}


def pins_manifest(pins_module: ModuleType | None) -> str:
    return (pins_module or load_pins()).MANIFEST


def main(argv: list[str] | None = None, *, fetch: Callable[[str], bytes] = fetch_url,
         machine: str | None = None, pins_module: ModuleType | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--from", dest="source", required=True,
                        help="the pinned runtime to copy (node and pi/), never changed")
    parser.add_argument("--to", dest="target", required=True,
                        help="the new runtime folder; must not exist, its parent must")
    args = parser.parse_args(argv)
    try:
        block = install(Path(args.source), Path(args.target), fetch=fetch, machine=machine,
                        pins_module=pins_module)
    except Refused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    target = Path(args.target).absolute()
    manifest = json.loads((target / pins_manifest(pins_module)).read_text(encoding="utf-8"))
    print(f"made {target} (read only)")
    print(f"source runtime {manifest['source_runtime']}: tree sha256 "
          f"{manifest['source_tree_sha256']} before and after (unchanged)")
    print("worker box config, next to runtime_dir and pi_version:")
    print(json.dumps({"runtime_dir": str(target), "pi_version": pi_version(target),
                      "search_tools": block}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
