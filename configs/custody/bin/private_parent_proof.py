#!/usr/bin/env python3
"""Private parent proof: the run itself creates a private parent P inside its own workspace W.

temper queue #211 (Stage1 P1, 2026-10-25). One model-free step in an ordinary run box, run by
configs/custody/agents/private_parent_proof.yaml. It proves that the run's real identity can create
a private parent inside the run's workspace, owned by that identity, and leaves it for the host to
read back after the box has gone. It reads nothing inside W, writes nothing outside the tree it
creates, changes and deletes nothing that was there, and uses no model, provider or credential.

In order:
  1. umask 077; measures euid, egid and the supplementary groups.
  2. reads /proc/self/mountinfo and keeps only the mounts that hold W, /app/temper_ai and
     /app/configs: mount id, fs type, major:minor, ro or rw, and whether the mount point is the
     path itself ("exact") or above it ("ancestor").
  3. walks to W from / one name at a time without following links, lstats W and opens it without
     following links; counts W's entries (never their names) only once W is known to be the
     expected directory, owned by euid, on a writable mount.
  4. refuses, having written nothing, when: an input is not valid; euid is 0; the mount table
     can't be read or doesn't hold all three; the code or config mount is writable; W is missing,
     reached through a link, a link itself or not a directory; W's st_dev/st_ino are not the
     expected ones (or W changed between lstat and open); W's owner is not euid; W's mount is
     read-only; W is not empty.
  5. creates CP = W/<collection>, P = CP/<profile_id> and the families inside P, parents first,
     each with an exclusive mkdir 0700, opened back without following links, checked (owned by
     euid, mode 0700) and fsynced together with its parent; then P/P1-PROOF.json (O_CREAT|O_EXCL|
     O_NOFOLLOW, 0600, closed metadata only), written whole, fsynced, checked (one link, owned by
     euid, mode 0600), and P fsynced after it.
  A failure while creating stops there and keeps everything made so far (nothing is deleted); the
  result names the object, the errno and the repair.

Inputs, from the environment (the agent sets them from the run):
  PROOF_WORKSPACE        W: the run's workspace_path, absolute and normalised
  PROOF_EXPECTED_W_DEV   W's st_dev as the host operator recorded it (decimal)
  PROOF_EXPECTED_W_INO   W's st_ino as the host operator recorded it (decimal)
  PROOF_COLLECTION       CP's name inside W
  PROOF_PROFILE_ID       P's name inside CP
  PROOF_FAMILIES         JSON array of directories to create inside P, one or two levels, each
                         parent before its children (["native", "native/k01"]); [] for P alone
  PROOF_RUN_ID           the run's id

Output: one JSON line on stdout, the closed projection (format private-parent-proof/1): ids,
numbers, enums, digests and explicit nulls. Never a path, an environment value, a traceback or
free text: check_projection() checks it before it is printed, and a projection it rejects is
replaced by a fixed refusal (projection_invalid). Nothing goes to stderr. Exit 0 for CREATED and
REFUSED alike: a refusal is a result, and the step fails only when the script gives none.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import stat
import sys
import time
from collections.abc import Mapping
from typing import Any, NamedTuple

FORMAT = "private-parent-proof/1"
FILE_FORMAT = "private-parent-proof-file/1"
PROOF_FILE = "P1-PROOF.json"
MOUNTINFO = "/proc/self/mountinfo"
CODE_ROOT = "/app/temper_ai"
CONFIG_ROOT = "/app/configs"
DIR_MODE = 0o700
FILE_MODE = 0o600
UMASK = 0o077
# How a directory is opened and the proof file created: never through a link, never an existing file.
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
CREATE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC

BEFORE_WRITE = "before_write"
DURING_CREATE = "during_create"
COMPLETE = "complete"
UNKNOWN = "unknown"
PHASES = (BEFORE_WRITE, DURING_CREATE, COMPLETE, UNKNOWN)
TYPES = ("dir", "file", "symlink", "other")

_NAME = r"[a-z0-9][a-z0-9._-]{0,63}"
NAME = re.compile(_NAME)
FAMILY = re.compile(_NAME + r"(?:/" + _NAME + r")?")
NUMBER = re.compile(r"[0-9]{1,20}")
RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
MOUNT_DEV = re.compile(r"[0-9]{1,10}:[0-9]{1,10}")
FSTYPE = re.compile(r"[a-z0-9][a-z0-9._-]{0,31}")
ERRNO_NAME = re.compile(r"E[A-Z0-9]{1,15}")
MODE = re.compile(r"[0-7]{4}")
SHA256 = re.compile(r"[0-9a-f]{64}")
OCTAL_ESCAPE = re.compile(r"\\([0-7]{3})")

# Every reason the proof can refuse for, with the one repair that answers it.
REPAIRS = {
    "input_invalid": "correct_inputs",
    "euid_root": "nonroot_run_identity",
    "mountinfo_unreadable": "box_mountinfo_access",
    "code_mount_writable": "readonly_code_config_mapping",
    "config_mount_writable": "readonly_code_config_mapping",
    "w_missing": "create_w_by_host_operator",
    "w_path_unsafe": "new_w_by_host_operator",
    "w_symlink": "new_w_by_host_operator",
    "w_not_directory": "new_w_by_host_operator",
    "w_identity_mismatch": "remeasure_w_record",
    "w_owner_not_euid": "scoped_reown_empty_w",
    "w_mount_readonly": "writable_workspace_mapping",
    "w_not_empty": "new_w_by_host_operator",
    "cp_exists": "new_profile_decision",
    "p_exists": "new_profile_decision",
    "family_exists": "new_profile_decision",
    "proof_exists": "new_profile_decision",
    "mkdir_failed": "storage_fault_review",
    "open_failed": "storage_fault_review",
    "write_failed": "storage_fault_review",
    "fsync_failed": "storage_fault_review",
    "owner_mismatch": "identity_mode_review",
    "mode_mismatch": "identity_mode_review",
    "proof_not_single_link": "proof_file_review",
    "internal_error": "proof_code_fix",
    "projection_invalid": "proof_code_fix",
}

TOP_KEYS = frozenset({
    "format", "outcome", "phase", "reason", "errno", "failed_object", "repair", "run_id",
    "collection", "profile_id", "expected", "identity", "mounts", "w", "objects", "proof",
    "fsyncs", "private_reads", "private_input_custody", "rights_beyond_objects",
})
IDENTITY_KEYS = frozenset({"euid", "egid", "groups", "umask_before", "umask_used"})
MOUNT_KEYS = frozenset({"mount_id", "fstype", "dev", "ro", "match"})
STAT_KEYS = frozenset({"dev", "ino", "uid", "gid", "mode", "type", "nlink"})
NULL_KEYS = ("private_reads", "private_input_custody", "rights_beyond_objects")


class Refusal(Exception):
    """A closed refusal: a reason from REPAIRS, the object it concerns and the errno, if any."""

    def __init__(self, reason: str, failed_object: str | None = None, err: int | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.failed_object = failed_object
        self.err = err


class Inputs(NamedTuple):
    workspace: str
    w_dev: int
    w_ino: int
    collection: str
    profile_id: str
    families: tuple[str, ...]
    run_id: str


class Mount(NamedTuple):
    mount_id: int
    point: str
    fstype: str | None
    dev: str
    ro: bool


class Host:
    """Every call that touches the system, in one place, so a test can stand in for any of them."""

    code_root = CODE_ROOT
    config_root = CONFIG_ROOT

    def identity(self) -> tuple[int, int, list[int]]:
        return os.geteuid(), os.getegid(), sorted(set(os.getgroups()))

    def umask(self, mask: int) -> int:
        return os.umask(mask)

    def mountinfo(self) -> str:
        with open(MOUNTINFO, encoding="utf-8") as handle:
            return handle.read()

    def open_dir(self, name: str, dir_fd: int | None) -> int:
        return os.open(name, DIR_FLAGS, dir_fd=dir_fd)

    def lstat(self, name: str, dir_fd: int) -> os.stat_result:
        return os.stat(name, dir_fd=dir_fd, follow_symlinks=False)

    def entries(self, fd: int) -> int:
        return len(os.listdir(fd))

    def mkdir(self, name: str, dir_fd: int) -> None:
        os.mkdir(name, DIR_MODE, dir_fd=dir_fd)

    def create_file(self, name: str, dir_fd: int) -> int:
        return os.open(name, CREATE_FLAGS, FILE_MODE, dir_fd=dir_fd)

    def write(self, fd: int, data: memoryview) -> int:
        return os.write(fd, data)

    def fsync(self, fd: int) -> None:
        os.fsync(fd)

    def fstat(self, fd: int) -> os.stat_result:
        return os.fstat(fd)

    def close(self, fd: int) -> None:
        os.close(fd)

    def utc_now(self) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def parse_inputs(env: Mapping[str, str]) -> Inputs:
    """The inputs, checked; anything not exactly as the docstring says refuses as input_invalid."""
    inputs = _inputs(env)
    if inputs is None:
        raise Refusal("input_invalid")
    return inputs


def _inputs(env: Mapping[str, str]) -> Inputs | None:
    values = {key: env.get(key) for key in (
        "PROOF_WORKSPACE", "PROOF_EXPECTED_W_DEV", "PROOF_EXPECTED_W_INO", "PROOF_COLLECTION",
        "PROOF_PROFILE_ID", "PROOF_FAMILIES", "PROOF_RUN_ID")}
    if not all(isinstance(value, str) for value in values.values()):
        return None
    workspace = str(values["PROOF_WORKSPACE"])
    if not workspace.startswith("/") or workspace == "/" or "//" in workspace or "\x00" in workspace:
        return None
    if os.path.normpath(workspace) != workspace:
        return None
    dev, ino = str(values["PROOF_EXPECTED_W_DEV"]), str(values["PROOF_EXPECTED_W_INO"])
    if not (NUMBER.fullmatch(dev) and NUMBER.fullmatch(ino)):
        return None
    collection, profile_id = str(values["PROOF_COLLECTION"]), str(values["PROOF_PROFILE_ID"])
    if not (NAME.fullmatch(collection) and NAME.fullmatch(profile_id)):
        return None
    run_id = str(values["PROOF_RUN_ID"])
    if not RUN_ID.fullmatch(run_id):
        return None
    try:
        families = json.loads(str(values["PROOF_FAMILIES"]))
    except ValueError:
        return None
    if not isinstance(families, list):
        return None
    seen: list[str] = []
    for family in families:
        if not isinstance(family, str) or not FAMILY.fullmatch(family) or family in seen:
            return None
        parent = family.rpartition("/")[0]
        if parent and parent not in seen:
            return None
        seen.append(family)
    return Inputs(workspace, int(dev), int(ino), collection, profile_id, tuple(seen), run_id)


def parse_mountinfo(text: str) -> list[Mount]:
    """The mount table in /proc/self/mountinfo's format (proc(5)); ValueError when it isn't one."""
    mounts = []
    for line in text.splitlines():
        if not line:
            continue
        head, _, tail = line.partition(" - ")
        fields, rest = head.split(" "), tail.split(" ")
        if len(fields) < 6 or not NUMBER.fullmatch(fields[0]) or not MOUNT_DEV.fullmatch(fields[2]):
            raise ValueError("not a mountinfo line")
        if not rest[0]:  # no " - " separator, or no fs type after it
            raise ValueError("not a mountinfo line")
        point = OCTAL_ESCAPE.sub(lambda match: chr(int(match.group(1), 8)), fields[4])
        fstype = rest[0] if FSTYPE.fullmatch(rest[0]) else None
        mounts.append(Mount(int(fields[0]), point, fstype, fields[2], "ro" in fields[5].split(",")))
    if not mounts:
        raise ValueError("empty mount table")
    return mounts


def covering(mounts: list[Mount], path: str) -> tuple[Mount, str] | None:
    """The mount that holds path: the deepest mount point at or above it, and of two at the same
    point the later one (a later mount sits on top). With "exact" or "ancestor"."""
    best = None
    for mount in mounts:
        if mount.point == path or path.startswith(mount.point.rstrip("/") + "/"):
            if best is None or len(mount.point) >= len(best.point):
                best = mount
    if best is None:
        return None
    return best, "exact" if best.point == path else "ancestor"


def describe(st: os.stat_result) -> dict[str, Any]:
    """The closed metadata of one object: numbers and enums only."""
    if stat.S_ISDIR(st.st_mode):
        kind = "dir"
    elif stat.S_ISREG(st.st_mode):
        kind = "file"
    elif stat.S_ISLNK(st.st_mode):
        kind = "symlink"
    else:
        kind = "other"
    return {"dev": st.st_dev, "ino": st.st_ino, "uid": st.st_uid, "gid": st.st_gid,
            "mode": f"{stat.S_IMODE(st.st_mode):04o}", "type": kind, "nlink": st.st_nlink}


def blank() -> dict[str, Any]:
    return {
        "format": FORMAT, "outcome": "REFUSED", "phase": BEFORE_WRITE, "reason": None, "errno": None,
        "failed_object": None, "repair": None, "run_id": None, "collection": None, "profile_id": None,
        "expected": None,
        "identity": {"euid": None, "egid": None, "groups": [], "umask_before": None, "umask_used": None},
        "mounts": None, "w": None, "objects": [], "proof": None, "fsyncs": 0,
        "private_reads": None, "private_input_custody": None, "rights_beyond_objects": None,
    }


def fallback() -> dict[str, Any]:
    """The fixed answer when a projection fails its own check: nothing measured is passed on."""
    projection = blank()
    projection.update(phase=UNKNOWN, reason="projection_invalid", repair=REPAIRS["projection_invalid"])
    return projection


def run(env: Mapping[str, str], host: Host | None = None) -> dict[str, Any]:
    """Do the proof (see the module docstring) and return its projection."""
    host = host or Host()
    projection = blank()
    held: list[int] = []
    previous = host.umask(UMASK)
    projection["identity"].update(umask_before=f"{previous:04o}", umask_used=f"{UMASK:04o}")
    try:
        _prove(env, host, projection, held)
        projection.update(outcome="CREATED", phase=COMPLETE)
    except Refusal as refusal:
        projection.update(outcome="REFUSED", reason=refusal.reason, failed_object=refusal.failed_object,
                          errno=errno.errorcode.get(refusal.err) if refusal.err else None,
                          repair=REPAIRS[refusal.reason])
    except Exception:
        projection.update(outcome="REFUSED", reason="internal_error", failed_object=None, errno=None,
                          repair=REPAIRS["internal_error"])
    finally:
        for fd in reversed(held):
            try:
                host.close(fd)
            except OSError:
                pass
        host.umask(previous)
    return projection


def _prove(env: Mapping[str, str], host: Host, projection: dict[str, Any], held: list[int]) -> None:
    euid, egid, groups = host.identity()
    projection["identity"].update(euid=euid, egid=egid, groups=list(groups))
    inputs = parse_inputs(env)
    projection.update(run_id=inputs.run_id, collection=inputs.collection, profile_id=inputs.profile_id,
                      expected={"w_dev": inputs.w_dev, "w_ino": inputs.w_ino})
    if euid == 0:
        raise Refusal("euid_root")
    try:
        table = parse_mountinfo(host.mountinfo())
        found = {"W": covering(table, inputs.workspace), "code": covering(table, host.code_root),
                 "config": covering(table, host.config_root)}
        mounts = {name: hit for name, hit in found.items() if hit is not None}
        if len(mounts) != len(found):
            raise ValueError("a path outside the mount table")
    except (OSError, ValueError):
        raise Refusal("mountinfo_unreadable") from None
    projection["mounts"] = {name: {"mount_id": mount.mount_id, "fstype": mount.fstype, "dev": mount.dev,
                                   "ro": mount.ro, "match": match} for name, (mount, match) in mounts.items()}
    if not mounts["code"][0].ro:
        raise Refusal("code_mount_writable", "code")
    if not mounts["config"][0].ro:
        raise Refusal("config_mount_writable", "config")
    w_fd, w_stat = _open_workspace(host, inputs, projection, held)
    if w_stat.st_uid != euid:
        raise Refusal("w_owner_not_euid", "W")
    if mounts["W"][0].ro:
        raise Refusal("w_mount_readonly", "W")
    try:
        entries = host.entries(w_fd)
    except OSError as exc:
        raise Refusal("w_path_unsafe", "W", exc.errno) from None
    projection["w"]["entries"] = entries
    if entries != 0:
        raise Refusal("w_not_empty", "W")

    projection["phase"] = DURING_CREATE
    cp_fd = _make_dir(host, projection, held, w_fd, inputs.collection, "CP", "cp_exists", euid)
    p_fd = _make_dir(host, projection, held, cp_fd, inputs.profile_id, "P", "p_exists", euid)
    family_fds = {"": p_fd}
    for family in inputs.families:
        parent, _, leaf = family.rpartition("/")
        family_fds[family] = _make_dir(host, projection, held, family_fds[parent], leaf, "family:" + family,
                                       "family_exists", euid)
    _write_proof(host, projection, held, p_fd, inputs, (euid, egid, list(groups)))


def _open_workspace(host: Host, inputs: Inputs, projection: dict[str, Any],
                    held: list[int]) -> tuple[int, os.stat_result]:
    """W reached from / one name at a time, no link followed, and checked to be the expected
    directory: (its fd, its fstat)."""
    names = inputs.workspace.strip("/").split("/")
    try:
        fd = host.open_dir("/", None)
        held.append(fd)
        for name in names[:-1]:
            fd = host.open_dir(name, fd)
            held.append(fd)
        before = host.lstat(names[-1], fd)
    except FileNotFoundError:
        raise Refusal("w_missing", "W", errno.ENOENT) from None
    except OSError as exc:
        raise Refusal("w_path_unsafe", "W", exc.errno) from None
    projection["w"] = {**describe(before), "entries": None}
    if stat.S_ISLNK(before.st_mode):
        raise Refusal("w_symlink", "W")
    if not stat.S_ISDIR(before.st_mode):
        raise Refusal("w_not_directory", "W")
    try:
        w_fd = host.open_dir(names[-1], fd)
        held.append(w_fd)
        opened = host.fstat(w_fd)
    except OSError as exc:
        raise Refusal("w_path_unsafe", "W", exc.errno) from None
    projection["w"] = {**describe(opened), "entries": None}
    if not (opened.st_dev, opened.st_ino) == (before.st_dev, before.st_ino) == (inputs.w_dev, inputs.w_ino):
        raise Refusal("w_identity_mismatch", "W")
    return w_fd, opened


def _make_dir(host: Host, projection: dict[str, Any], held: list[int], parent_fd: int, name: str,
              object_id: str, exists_reason: str, euid: int) -> int:
    """One new private directory: exclusive mkdir 0700, opened back without following links,
    checked, then fsynced with its parent. Its fd."""
    try:
        host.mkdir(name, parent_fd)
    except FileExistsError:
        raise Refusal(exists_reason, object_id, errno.EEXIST) from None
    except OSError as exc:
        raise Refusal("mkdir_failed", object_id, exc.errno) from None
    try:
        fd = host.open_dir(name, parent_fd)
        held.append(fd)
        st = host.fstat(fd)
    except OSError as exc:
        raise Refusal("open_failed", object_id, exc.errno) from None
    projection["objects"].append({"id": object_id, **describe(st)})
    if st.st_uid != euid:
        raise Refusal("owner_mismatch", object_id)
    if stat.S_IMODE(st.st_mode) != DIR_MODE:
        raise Refusal("mode_mismatch", object_id)
    _sync(host, projection, fd, object_id)
    _sync(host, projection, parent_fd, object_id)
    return fd


def _write_proof(host: Host, projection: dict[str, Any], held: list[int], p_fd: int, inputs: Inputs,
                 identity: tuple[int, int, list[int]]) -> None:
    """P/P1-PROOF.json: closed metadata, created exclusively without following links, written
    whole, fsynced and checked, then P fsynced."""
    euid, egid, groups = identity
    body = (json.dumps({
        "format": FILE_FORMAT, "run_id": inputs.run_id, "collection": inputs.collection,
        "profile_id": inputs.profile_id, "identity": {"euid": euid, "egid": egid, "groups": groups},
        "w": {"dev": inputs.w_dev, "ino": inputs.w_ino},
        "objects": [{"id": o["id"], "dev": o["dev"], "ino": o["ino"]} for o in projection["objects"]],
        "created_utc": host.utc_now(),
    }, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")
    try:
        fd = host.create_file(PROOF_FILE, p_fd)
    except FileExistsError:
        raise Refusal("proof_exists", "proof", errno.EEXIST) from None
    except OSError as exc:
        raise Refusal("open_failed", "proof", exc.errno) from None
    held.append(fd)
    try:
        _write_all(host, fd, body)
    except OSError as exc:
        raise Refusal("write_failed", "proof", exc.errno) from None
    _sync(host, projection, fd, "proof")
    st = host.fstat(fd)
    projection["proof"] = {"id": "proof", **describe(st), "size": st.st_size,
                           "sha256": hashlib.sha256(body).hexdigest()}
    if st.st_nlink != 1:
        raise Refusal("proof_not_single_link", "proof")
    if st.st_uid != euid:
        raise Refusal("owner_mismatch", "proof")
    if stat.S_IMODE(st.st_mode) != FILE_MODE:
        raise Refusal("mode_mismatch", "proof")
    _sync(host, projection, p_fd, "proof")


def _write_all(host: Host, fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = host.write(fd, view)
        if written <= 0:
            raise OSError(errno.EIO, "nothing written")
        view = view[written:]


def _sync(host: Host, projection: dict[str, Any], fd: int, object_id: str) -> None:
    try:
        host.fsync(fd)
    except OSError as exc:
        raise Refusal("fsync_failed", object_id, exc.errno) from None
    projection["fsyncs"] += 1


def _count(value: Any) -> bool:
    return type(value) is int and value >= 0


def _text(pattern: re.Pattern[str], value: Any) -> bool:
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _object_id(value: Any, *, whole: bool = False) -> bool:
    if value in ("CP", "P") or (whole and value in ("W", "code", "config", "proof")):
        return True
    return isinstance(value, str) and value.startswith("family:") and _text(FAMILY, value[len("family:"):])


def _stat_problems(record: Any, where: str, extra: frozenset[str]) -> list[str]:
    if not isinstance(record, dict) or set(record) != STAT_KEYS | extra:
        return [where]
    problems = [f"{where}.{key}" for key in ("dev", "ino", "uid", "gid", "nlink") if not _count(record[key])]
    if not _text(MODE, record["mode"]):
        problems.append(f"{where}.mode")
    if record["type"] not in TYPES:
        problems.append(f"{where}.type")
    return problems


def check_projection(p: Any) -> list[str]:
    """What is wrong with a projection, [] when nothing: exact keys, closed values, no free text."""
    if not isinstance(p, dict) or set(p) != TOP_KEYS:
        return ["keys"]
    problems = []
    if p["format"] != FORMAT:
        problems.append("format")
    if p["phase"] not in PHASES:
        problems.append("phase")
    closing = ("reason", "errno", "failed_object", "repair")
    if p["outcome"] == "CREATED":
        if p["phase"] != COMPLETE or any(p[key] is not None for key in closing) or p["proof"] is None:
            problems.append("created")
    elif p["outcome"] == "REFUSED":
        if p["phase"] == COMPLETE or p["reason"] not in REPAIRS or p["repair"] != REPAIRS.get(p["reason"]):
            problems.append("refused")
    else:
        problems.append("outcome")
    if p["errno"] is not None and not _text(ERRNO_NAME, p["errno"]):
        problems.append("errno")
    if p["failed_object"] is not None and not _object_id(p["failed_object"], whole=True):
        problems.append("failed_object")
    if p["run_id"] is not None and not _text(RUN_ID, p["run_id"]):
        problems.append("run_id")
    problems += [key for key in ("collection", "profile_id") if p[key] is not None and not _text(NAME, p[key])]
    expected = p["expected"]
    if expected is not None and not (isinstance(expected, dict) and set(expected) == {"w_dev", "w_ino"}
                                     and all(_count(value) for value in expected.values())):
        problems.append("expected")
    identity = p["identity"]
    if not isinstance(identity, dict) or set(identity) != IDENTITY_KEYS:
        problems.append("identity")
    else:
        if any(identity[key] is not None and not _count(identity[key]) for key in ("euid", "egid")):
            problems.append("identity.ids")
        if not isinstance(identity["groups"], list) or not all(_count(g) for g in identity["groups"]):
            problems.append("identity.groups")
        if any(identity[key] is not None and not _text(MODE, identity[key]) for key in ("umask_before", "umask_used")):
            problems.append("identity.umask")
    mounts = p["mounts"]
    if mounts is not None:
        if not isinstance(mounts, dict) or set(mounts) != {"W", "code", "config"}:
            problems.append("mounts")
        else:
            for name, mount in mounts.items():
                if not (isinstance(mount, dict) and set(mount) == MOUNT_KEYS and _count(mount["mount_id"])
                        and (mount["fstype"] is None or _text(FSTYPE, mount["fstype"]))
                        and _text(MOUNT_DEV, mount["dev"]) and type(mount["ro"]) is bool
                        and mount["match"] in ("exact", "ancestor")):
                    problems.append(f"mounts.{name}")
    w = p["w"]
    if w is not None:
        problems += _stat_problems(w, "w", frozenset({"entries"}))
        if isinstance(w, dict) and w.get("entries") is not None and not _count(w.get("entries")):
            problems.append("w.entries")
    objects = p["objects"]
    if not isinstance(objects, list):
        problems.append("objects")
    else:
        for index, record in enumerate(objects):
            problems += _stat_problems(record, f"objects.{index}", frozenset({"id"}))
            if isinstance(record, dict) and not _object_id(record.get("id")):
                problems.append(f"objects.{index}.id")
    proof = p["proof"]
    if proof is not None:
        problems += _stat_problems(proof, "proof", frozenset({"id", "size", "sha256"}))
        if isinstance(proof, dict) and not (proof.get("id") == "proof" and _count(proof.get("size"))
                                            and _text(SHA256, proof.get("sha256"))):
            problems.append("proof.fields")
    if not _count(p["fsyncs"]):
        problems.append("fsyncs")
    problems += [key for key in NULL_KEYS if p[key] is not None]
    return problems


def main() -> int:
    try:
        projection = run(os.environ)
        if check_projection(projection):
            projection = fallback()
    except Exception:
        projection = fallback()
    sys.stdout.write(json.dumps(projection, sort_keys=True, separators=(",", ":")) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
