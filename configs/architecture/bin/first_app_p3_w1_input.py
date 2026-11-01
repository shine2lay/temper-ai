"""Run-owned transport for controls_p3's w1_before; W1 validation stays in first_app_p3_w1.

Inline bytes also enter ordinary workflow input/events. Private staging is NOT secret transport.
No source path is read; legacy text (even malformed references) is forwarded untouched.
load_json, decode and stage are shared with first_app_p3_w2_input (the same envelope and staging for W2 records).
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import pathlib
import stat

import first_app_p3_guard as guard
import first_app_p3_w1 as w1

ENCODED_MAX = 4 * ((w1.READING_MAX + 2) // 3)
STAGING_DIR = "w1-input"
BEFORE_NAME = "before.json"


class Refused(ValueError):
    """Fixed transport diagnostic, never input bytes or an underlying OS exception."""


def load_json(text: str) -> tuple[object, bool] | None:
    """The parsed text and whether any object in it repeats a key; None when it is not JSON."""
    duplicate = False

    def pairs(items):
        nonlocal duplicate
        obj = {}
        for key, value in items:
            if key in obj:
                duplicate = True
            obj[key] = value
        return obj

    try:
        obj = json.loads(text, object_pairs_hook=pairs)
    except (ValueError, RecursionError):
        return None
    return obj, duplicate


def decode(obj: dict, duplicate: bool, *, label: str, limit: int, bound: str) -> tuple[bytes, str]:
    """One {data_base64, sha256} envelope -> its exact bytes and sha256, or a fixed diagnostic naming label."""
    if duplicate or set(obj) != {"data_base64", "sha256"}:
        raise Refused(f"inline {label} needs exactly data_base64 and sha256 with unique keys")
    encoded, digest = obj["data_base64"], obj["sha256"]
    if not isinstance(encoded, str) or not isinstance(digest, str) or not w1.HEX64.fullmatch(digest):
        raise Refused(f"inline {label} needs base64 text and a lowercase SHA256")
    if len(encoded) > 4 * ((limit + 2) // 3):
        raise Refused(f"inline {label} exceeds the {bound} size bound")
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise Refused(f"inline {label} is not canonical standard base64") from None
    # validate=True alone still accepts nonzero pad bits and some extra padding.
    if base64.b64encode(data).decode("ascii") != encoded:
        raise Refused(f"inline {label} is not canonical standard base64")
    if len(data) > limit:
        raise Refused(f"inline {label} exceeds the {bound} size bound")
    if hashlib.sha256(data).hexdigest() != digest:
        raise Refused(f"inline {label} does not match the supplied SHA256")
    return data, digest


def _inline(text: str) -> tuple[bytes, str] | None:
    loaded = load_json(text)
    if loaded is None:
        # Malformed JSON keeps the old checker's diagnostics and original argv.
        return None
    obj, duplicate = loaded
    if not isinstance(obj, dict) or "data_base64" not in obj:
        return None
    return decode(obj, duplicate, label="W1", limit=w1.READING_MAX, bound="reading")


def stage(workspace: pathlib.Path, directory: str, files: list[tuple[str, bytes]], *, label: str) -> dict[str, dict]:
    """Write each (name, bytes) once, 0600, into the private run-owned check/<directory>; name -> file metadata.

    Unsafe staging directories refuse rather than being repaired. The existing writer creates once; any partial
    failed write is preserved, with no retry or alternate path. This is a process/file observation, not
    authentication or hostile-same-UID protection.
    """
    check = pathlib.Path(os.path.abspath(workspace)) / "check"
    uid, gid = os.geteuid(), os.getegid()
    staged = {}
    try:
        with guard.directory_fd(check, create=True) as check_fd:
            try:
                os.mkdir(directory, mode=0o700, dir_fd=check_fd)
            except FileExistsError:
                pass
            with guard.directory_fd(check / directory) as stage_fd:
                found = os.fstat(stage_fd)
                if found.st_uid != uid or stat.S_IMODE(found.st_mode) != 0o700:
                    raise Refused(f"inline {label} staging directory is not private and process-owned")
                for name, data in files:
                    path = check / directory / name
                    guard.write_private(path, data)
                    file = os.stat(name, dir_fd=stage_fd, follow_symlinks=False)
                    linked = os.stat(directory, dir_fd=check_fd, follow_symlinks=False)
                    if ((found.st_dev, found.st_ino) != (linked.st_dev, linked.st_ino)
                            or not stat.S_ISREG(file.st_mode) or file.st_uid != uid
                            or stat.S_IMODE(file.st_mode) != 0o600 or file.st_size != len(data)):
                        raise Refused(f"inline {label} staged file identity or mode changed")
                    staged[name] = {"path": str(path), "sha256": hashlib.sha256(data).hexdigest(),
                                    "process_uid": uid, "process_gid": gid, "file_uid": file.st_uid,
                                    "file_gid": file.st_gid, "file_mode": format(stat.S_IMODE(file.st_mode), "04o")}
    except (OSError, ValueError):
        # Includes collisions, symlinks, unsafe modes and failed writes; no path/OS/content echo.
        raise Refused(f"inline {label} could not be staged privately at its fixed create-once destination") from None
    return staged


def prepare(text: str, workspace: pathlib.Path) -> tuple[str, dict | None]:
    """Legacy text or one staged ordinary reference, plus non-content metadata.

    The caller restricts this to controls_p3. Unsafe staging directories refuse rather than being repaired.
    The existing writer creates once; any partial failed write is preserved, with no retry or alternate path.
    This is a process/file observation, not authentication or hostile-same-UID protection.
    """
    inline = _inline(text)
    if inline is None:
        return text, None
    data, digest = inline
    meta = stage(workspace, STAGING_DIR, [(BEFORE_NAME, data)], label="W1")[BEFORE_NAME]
    return json.dumps({"path": meta["path"], "sha256": digest}), meta
