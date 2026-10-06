"""The box's own look at itself, before anything in it runs: is it the box its profile says?

The trusted worker compiles a box profile (box_profile.py) and starts the box with it in
three variables: the profile (canonical JSON), its digest and its generation. The first
thing `temper run-workflow` does is call check_box(): the profile must match its digest,
and a sealed box must look exactly like its grants say. Every granted mount is the very
object the worker pinned (device and inode, so a path swapped between the worker's check
and docker's mount is caught), read-only where it should be, and nothing else is mounted.
The root filesystem is read-only, the runner's code, PATH, HOME and import roots can't be
written, and the paths a legacy box has (the main repo, keys, the login file, other runs'
workspaces) are not there. Any difference stops the box before a tool or a secret is used.

Standard library only, so it also runs as a script in any image with a Python:
`python3 -I temper_ai/spawner/box_view.py` (exit 0 = the box is what its profile says,
3 = refused, with the reasons on stderr). The model-free gate uses that form.

A sealed box starts with this very file as its first program: the worker passes its
source as `python -I -c <source> --exec <runner command>` (BOOT_PROGRAM), so the check
that the mounts are the pinned ones is code the worker holds, not code from a mount it
is checking. Once the box passes, the program replaces itself with the runner.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
from collections.abc import Iterable, Mapping
from typing import Any

PROFILE_ENV = "TEMPER_BOX_PROFILE"
DIGEST_ENV = "TEMPER_BOX_PROFILE_DIGEST"
GENERATION_ENV = "TEMPER_BOX_PROFILE_GENERATION"
SCHEMA_VERSION = 2
SEALED = "sealed"

#: Mounts docker itself makes in every container (and --init's PID 1): not grants, never code.
#: What docker itself mounts into every box (--init's binary sits at either path, by version).
_DOCKER_FILES = ("/etc/hosts", "/etc/hostname", "/etc/resolv.conf", "/sbin/docker-init",
                 "/usr/sbin/docker-init")
_KERNEL_ROOTS = ("/proc", "/dev", "/sys")


class BoxStartRefused(Exception):
    """A box found, before any tool started, that it is not the box its profile describes."""


def canonical(doc: Mapping[str, Any]) -> str:
    """The one text a profile is digested from: sorted keys, no spaces, plain JSON types."""
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False)


def digest_of(doc: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical(doc).encode("ascii")).hexdigest()


def profile_from_env(environ: Mapping[str, str] | None = None) -> dict | None:
    """The profile this box was started with, checked against its digest. None without one."""
    env = os.environ if environ is None else environ
    text = env.get(PROFILE_ENV)
    if not text:
        if env.get(DIGEST_ENV) or env.get(GENERATION_ENV):
            raise BoxStartRefused("the box has a profile digest but no profile")
        return None
    try:
        doc = json.loads(text)
    except ValueError as exc:
        raise BoxStartRefused(f"the box's profile is not readable ({exc})") from exc
    if not isinstance(doc, dict):
        raise BoxStartRefused("the box's profile is not a document")
    if digest_of(doc) != env.get(DIGEST_ENV):
        raise BoxStartRefused("the box's profile does not match the digest it was given")
    if str(doc.get("generation")) != env.get(GENERATION_ENV):
        raise BoxStartRefused("the box's profile generation does not match the one it was given")
    if doc.get("schema_version") != SCHEMA_VERSION:
        raise BoxStartRefused(f"the box's profile has schema {doc.get('schema_version')!r}; "
                              f"this runner knows {SCHEMA_VERSION}")
    return doc


# -- what the kernel says is mounted ------------------------------------------------------


def _unescape(field: str) -> str:
    """mountinfo writes space, tab, newline and backslash as octal escapes."""
    out, i = [], 0
    while i < len(field):
        code = field[i + 1:i + 4]
        if field[i] == "\\" and len(code) == 3 and code.isdigit():
            out.append(chr(int(code, 8)))
            i += 4
        else:
            out.append(field[i])
            i += 1
    return "".join(out)


def mountinfo(path: str = "/proc/self/mountinfo") -> list[dict]:
    """Every mount this process sees: where, read-only or not, which filesystem."""
    mounts = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            left, _, right = line.rstrip("\n").partition(" - ")
            parts, tail = left.split(" "), right.split(" ")
            if len(parts) < 6 or len(tail) < 2:
                continue
            mounts.append({
                "target": _unescape(parts[4]),
                "options": set(parts[5].split(",")),
                "fstype": tail[0],
            })
    return mounts


def _inside(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip("/") + "/")


def _writable(path: str) -> bool:
    """Whether this process could write at ``path`` (access(2) knows read-only mounts too)."""
    return os.access(path, os.W_OK, follow_symlinks=False) if os.path.lexists(path) else False


def _ancestors(path: str) -> Iterable[str]:
    path = os.path.normpath(path)
    while True:
        yield path
        if path == "/":
            return
        path = os.path.dirname(path)


# -- the check ----------------------------------------------------------------------------


def view_problems(doc: Mapping[str, Any], *, mounts: list[dict] | None = None,
                  environ: Mapping[str, str] | None = None,
                  import_roots: Iterable[str] | None = None) -> list[str]:
    """What is different about this box from its sealed profile ([] = nothing). Legacy: []."""
    if doc.get("boundary") != SEALED:
        return []
    env = os.environ if environ is None else environ
    seen = mountinfo() if mounts is None else mounts
    problems: list[str] = []
    by_target: dict[str, dict] = {}
    for mount in seen:
        by_target[mount["target"]] = mount  # the last one at a path is the one in use

    grants = list(doc.get("grants") or [])
    tmpfs = [str(t).split(":", 1)[0] for t in doc.get("tmpfs") or []]
    for grant in grants:
        problems += _grant_problems(grant, by_target.get(grant["target"]))
    allowed = {g["target"] for g in grants} | set(tmpfs) | set(_DOCKER_FILES) | {"/"}
    for mount in seen:
        target = mount["target"]
        if target in allowed or any(_inside(target, k) for k in _KERNEL_ROOTS):
            continue
        problems.append(f"{target} is mounted but the profile grants nothing there")
    root = by_target.get("/")
    if root is None or "ro" not in root["options"]:
        problems.append("the root filesystem is writable; a sealed box's is read-only")

    runtime = doc.get("runtime") or {}
    problems += _identity_problems(runtime, status=None if mounts is None else {})
    for path in list(runtime.get("immutable") or []) + [runtime.get("home") or "/"]:
        for p in _ancestors(path):
            if _writable(p):
                problems.append(f"{p} can be written; the runtime is meant to be immutable")
    path_now = (env.get("PATH") or "").split(os.pathsep)
    if path_now != list(runtime.get("path") or []):
        problems.append("PATH is not the one the profile fixed")
    for directory in path_now:
        if directory and any(_writable(p) for p in _ancestors(directory)):
            problems.append(f"{directory} on PATH can be written (a tool could shadow a command)")
    if env.get("HOME") != runtime.get("home"):
        problems.append("HOME is not the one the profile fixed")
    for directory in import_roots if import_roots is not None else sys.path:
        if directory and os.path.isdir(directory) and _writable(directory):
            problems.append(f"{directory} is on the import path and can be written")
    for path in runtime.get("absent") or []:
        if _shows(path):
            problems.append(f"{path} is in the box; a sealed box has no such path")
    return sorted(set(problems))


def _shows(path: str) -> bool:
    """Whether ``path`` is there with something in it.

    An empty folder baked into the image (production's /opt/claude/versions, a mount
    point docker made for a granted file) carries nothing; anything else counts, and so
    does a folder this process can't list.
    """
    if not os.path.lexists(path):
        return False
    if os.path.islink(path) or not os.path.isdir(path):
        return True
    try:
        return bool(os.listdir(path))
    except OSError:
        return True


def _identity_problems(runtime: Mapping[str, Any], status: Mapping[str, str] | None) -> list[str]:
    """Not root, the profile's user, no privileges to gain or hold (``status``: /proc/self/status)."""
    import pwd

    problems = []
    uid = os.getuid()
    if uid == 0 or os.geteuid() == 0:
        problems.append("the box runs as root; a sealed box runs as the template's own user")
    user = str(runtime.get("user") or "").split(":", 1)[0]
    try:
        name = pwd.getpwuid(uid).pw_name
    except KeyError:
        name = None
    if user and user not in (str(uid), name):
        problems.append(f"the box runs as uid {uid}, not as {user}")
    if status is None:
        status = {}
        try:
            with open("/proc/self/status", encoding="ascii", errors="replace") as fh:
                for line in fh:
                    key, _, value = line.partition(":")
                    status[key] = value.strip()
        except OSError:
            problems.append("/proc/self/status can't be read to check privileges")
    if status and status.get("NoNewPrivs") != "1":
        problems.append("the box can gain privileges (no-new-privileges is off)")
    if status and status.get("CapEff", "0").strip("0"):
        problems.append("the box holds capabilities; a sealed box drops them all")
    return problems


def _grant_problems(grant: Mapping[str, Any], mount: dict | None) -> list[str]:
    target = grant["target"]
    if mount is None:
        return [f"{target} is granted but not mounted"]
    problems = []
    want_ro = bool(grant.get("read_only"))
    if want_ro and "ro" not in mount["options"]:
        problems.append(f"{target} is mounted writable; the grant is read-only")
    if not want_ro and "rw" not in mount["options"]:
        problems.append(f"{target} is mounted read-only; the grant is writable")
    pin = grant.get("pin") or {}
    try:
        st = os.stat(target, follow_symlinks=False)
    except OSError as exc:
        return [*problems, f"{target} can't be looked at ({exc.strerror})"]
    if (st.st_dev, st.st_ino) != (pin.get("dev"), pin.get("ino")):
        problems.append(f"{target} is not the object the worker checked (it was swapped "
                        "between the check and the mount)")
    kind = "dir" if stat.S_ISDIR(st.st_mode) else "file" if stat.S_ISREG(st.st_mode) else "other"
    if kind != pin.get("type"):
        problems.append(f"{target} is a {kind}; the worker pinned a {pin.get('type')}")
    return problems


def check_box(environ: Mapping[str, str] | None = None) -> dict | None:
    """The box's whole start check. The profile (None for a box started without one).

    Raises BoxStartRefused, with every difference found, for a profile that doesn't match
    its digest or a sealed box that isn't what its profile says.
    """
    doc = profile_from_env(environ)
    if doc is None:
        return None
    problems = view_problems(doc, environ=environ)
    if problems:
        raise BoxStartRefused("this box is not the sealed box its profile describes: "
                              + "; ".join(problems))
    return doc


def boot_program() -> str:
    """This file's source: what a sealed box runs first (`python -I -c <it> --exec ...`)."""
    with open(__file__, encoding="utf-8") as fh:
        return fh.read()


def main(argv: list[str] | None = None) -> int:
    """Check the box; with ``--exec <command...>``, become that command once it passes."""
    args = sys.argv[1:] if argv is None else argv
    then = args[args.index("--exec") + 1:] if "--exec" in args else []
    try:
        doc = check_box()
        if then and (doc is None or doc.get("boundary") != SEALED):
            raise BoxStartRefused("the box was started as a sealed box but has no sealed profile")
    except BoxStartRefused as exc:
        print(f"box refused: {exc}", file=sys.stderr)
        return 3
    if doc is None:
        print("box: no profile (an older or unboxed start)")
    else:
        print(f"box: profile g{doc.get('generation')} {doc.get('boundary')} "
              f"{digest_of(doc)[:19]} ok", file=sys.stderr if then else sys.stdout)
    if then:
        sys.stdout.flush()
        sys.stderr.flush()
        os.execv(then[0], then)
    return 0


if __name__ == "__main__":
    sys.exit(main())
