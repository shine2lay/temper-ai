"""Run-owned transport for controls_p3's w1_before; W1 validation stays in first_app_p3_w1.

Inline bytes also enter ordinary workflow input/events. Private staging is NOT secret transport.
No source path is read; legacy text (even malformed references) is forwarded untouched.
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


def _inline(text: str) -> tuple[bytes, str] | None:
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
        # Malformed JSON keeps the old checker's diagnostics and original argv.
        return None
    if not isinstance(obj, dict) or "data_base64" not in obj:
        return None
    if duplicate or set(obj) != {"data_base64", "sha256"}:
        raise Refused("inline W1 needs exactly data_base64 and sha256 with unique keys")
    encoded, digest = obj["data_base64"], obj["sha256"]
    if not isinstance(encoded, str) or not isinstance(digest, str) or not w1.HEX64.fullmatch(digest):
        raise Refused("inline W1 needs base64 text and a lowercase SHA256")
    if len(encoded) > ENCODED_MAX:
        raise Refused("inline W1 exceeds the reading size bound")
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise Refused("inline W1 is not canonical standard base64") from None
    # validate=True alone still accepts nonzero pad bits and some extra padding.
    if base64.b64encode(data).decode("ascii") != encoded:
        raise Refused("inline W1 is not canonical standard base64")
    if len(data) > w1.READING_MAX:
        raise Refused("inline W1 exceeds the reading size bound")
    if hashlib.sha256(data).hexdigest() != digest:
        raise Refused("inline W1 does not match the supplied SHA256")
    return data, digest


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
    path = pathlib.Path(os.path.abspath(workspace)) / "check" / STAGING_DIR / BEFORE_NAME
    uid, gid = os.geteuid(), os.getegid()
    try:
        with guard.directory_fd(path.parent.parent, create=True) as check_fd:
            try:
                os.mkdir(STAGING_DIR, mode=0o700, dir_fd=check_fd)
            except FileExistsError:
                pass
            with guard.directory_fd(path.parent) as stage_fd:
                directory = os.fstat(stage_fd)
                if directory.st_uid != uid or stat.S_IMODE(directory.st_mode) != 0o700:
                    raise Refused("inline W1 staging directory is not private and process-owned")
                guard.write_private(path, data)
                file = os.stat(BEFORE_NAME, dir_fd=stage_fd, follow_symlinks=False)
                linked = os.stat(STAGING_DIR, dir_fd=check_fd, follow_symlinks=False)
                if ((directory.st_dev, directory.st_ino) != (linked.st_dev, linked.st_ino)
                        or not stat.S_ISREG(file.st_mode) or file.st_uid != uid
                        or stat.S_IMODE(file.st_mode) != 0o600 or file.st_size != len(data)):
                    raise Refused("inline W1 staged file identity or mode changed")
    except (OSError, ValueError):
        # Includes collisions, symlinks, unsafe modes and failed writes; no path/OS/content echo.
        raise Refused("inline W1 could not be staged privately at its fixed create-once destination") from None
    ref = {"path": str(path), "sha256": digest}
    return json.dumps(ref), {**ref, "process_uid": uid, "process_gid": gid,
                             "file_uid": file.st_uid, "file_gid": file.st_gid,
                             "file_mode": format(stat.S_IMODE(file.st_mode), "04o")}
