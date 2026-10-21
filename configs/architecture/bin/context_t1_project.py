#!/usr/bin/env python3
"""D1: pinned, byte-preserving T1 projection; no model, key or semantic inference.

Port of C1 helper/check.py's descriptor reads, strict_json and packet_index
(SHA256 7bdacc782bd8b0b7f98fd45fe6c3ddaf3e6012904e595592b0182be606651919).
Refusals are tightened, never repaired. The root and descendant directories must
be private (0700); all files are regular, 0600, single-link, <=2,000,000 bytes.
Every path component is opened relative to a descriptor with O_NOFOLLOW. This
is a local file guard, NOT isolation from the same user or admission for judges.

CLI: --input-root DIR --packet REL --packet-sha256 HEX --label-rules REL
     --label-rules-sha256 HEX --format REL --format-sha256 HEX --output-root DIR
Exactly three named inputs; the input tree may contain only those files and
necessary private parent directories. Unknown entries are refused without being
opened; there is no directory-content ingestion. The output root must be empty. Outputs are fresh O_EXCL 0600 files:
projection.json (metadata only) and prompt.txt (never printed).

The invariant transport framing is exactly FRAMING, then the unmodified UTF-8
LABEL-RULES bytes, FORMAT_SEPARATOR, unmodified FORMAT bytes, PACKET_SEPARATOR,
and unmodified PACKET bytes. There is no final suffix, normalization, pruning,
semantic advice, target count, attempt metadata or content in stdout/errors.
Delimiters are transport framing, not modifications of the enclosed bytes.

H-T1-D12-1: separate pinned projection/strict validation should reject drift,
leaks and malformed/unbound answers without repair. Synthetic pass/refuse tests
and three disabled-check bites measure this; any such input passing refutes it.
"""
from __future__ import annotations

import argparse
import errno
import hashlib
import json
import math
import os
import re
import stat
import sys
from pathlib import Path

MAX_BYTES = 2_000_000
PACKET_SCHEMA = "label-free-controls/v2-candidate"
PROJECTION_SCHEMA = "context-t1-projection/v1"
FRAMING = (
    b"Return one strict JSON object in the supplied format.\n"
    b"The following documents are the complete task input.\n\nLABEL-RULES-v2.md\n"
)
FORMAT_SEPARATOR = b"\n\npacket/FORMAT.md\n"
PACKET_SEPARATOR = b"\n\npacket/PACKET.json\n"
FRAMING_BYTES = len(FRAMING) + len(FORMAT_SEPARATOR) + len(PACKET_SEPARATOR)
INPUT_NAMES = {"packet", "label_rules", "format"}
LEAK_WORDS = {"label", "labels", "family", "families", "expected", "key", "keys",
              "decision", "decisions", "count", "counts", "report", "reports"}


class Refusal(Exception):
    """Stable metadata-only reason; never include rejected content or paths."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def parts(relative: str) -> list[str]:
    if not isinstance(relative, str) or not relative or "\\" in relative or "\x00" in relative:
        raise Refusal("path")
    result = relative.split("/")
    if any(p in ("", ".", "..") for p in result):
        raise Refusal("path")
    return result


def _open_dir(parent: int, leaf: str) -> int:
    try:
        return os.open(leaf, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
    except OSError as error:
        # Linux reports ENOTDIR, rather than ELOOP, for a directory symlink.
        try:
            link = stat.S_ISLNK(os.stat(leaf, dir_fd=parent, follow_symlinks=False).st_mode)
        except OSError:
            link = False
        raise Refusal("symlink" if link or error.errno == errno.ELOOP else "filesystem") from None


class PrivateRoot:
    """Descriptor-confined port of C1's _root_fd/_parent/read_bytes/emit_new."""

    def __init__(self, root: str | Path):
        name = os.fspath(root)
        if not name.startswith("/"):
            raise Refusal("path")
        components = parts(name[1:])
        fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
        try:
            for component in components:
                nxt = _open_dir(fd, component)
                os.close(fd)
                fd = nxt
            self._directory_mode(fd)
        except BaseException:
            os.close(fd)
            raise
        self.fd = fd

    @staticmethod
    def _directory_mode(fd: int) -> None:
        if stat.S_IMODE(os.fstat(fd).st_mode) != 0o700:
            raise Refusal("directory_mode")

    def __enter__(self) -> PrivateRoot:
        return self

    def __exit__(self, *_exc) -> None:
        os.close(self.fd)

    def parent(self, relative: str) -> tuple[int, str]:
        components = parts(relative)
        fd = os.dup(self.fd)
        try:
            for component in components[:-1]:
                nxt = _open_dir(fd, component)
                os.close(fd)
                fd = nxt
                self._directory_mode(fd)
            return fd, components[-1]
        except BaseException:
            os.close(fd)
            raise

    def read_bytes(self, relative: str) -> bytes:
        try:
            parent, leaf = self.parent(relative)
            try:
                fd = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            finally:
                os.close(parent)
            try:
                before = os.fstat(fd)
                if not stat.S_ISREG(before.st_mode):
                    raise Refusal("file_type")
                if before.st_nlink != 1:
                    raise Refusal("hardlink")
                if stat.S_IMODE(before.st_mode) != 0o600:
                    raise Refusal("file_mode")
                if before.st_size > MAX_BYTES:
                    raise Refusal("size")
                chunks, size = [], 0
                while True:
                    chunk = os.read(fd, min(65536, MAX_BYTES + 1 - size))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise Refusal("size")
                after = os.fstat(fd)
                attributes = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns",
                              "st_mode", "st_nlink")
                if size != before.st_size or any(getattr(before, a) != getattr(after, a) for a in attributes):
                    raise Refusal("file_changed")
                return b"".join(chunks)
            finally:
                os.close(fd)
        except OSError as error:
            raise Refusal("symlink" if error.errno == errno.ELOOP else "filesystem") from None

    def write_new(self, relative: str, raw: bytes) -> None:
        if len(raw) > MAX_BYTES:
            raise Refusal("size")
        try:
            parent, leaf = self.parent(relative)
            try:
                fd = os.open(leaf, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=parent)
            finally:
                os.close(parent)
            # A restrictive caller umask must not silently change the contract.
            with os.fdopen(fd, "wb") as stream:
                os.fchmod(stream.fileno(), 0o600)
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            # Partial artifacts are retained on failure, never deleted/retried.
        except FileExistsError:
            raise Refusal("output_collision") from None
        except OSError:
            raise Refusal("filesystem") from None

    def require_empty(self) -> None:
        if os.listdir(self.fd):
            raise Refusal("output_not_empty")

    def require_files(self, names: tuple[str, ...]) -> None:
        tree = {}
        for name in names:
            branch = tree
            components = parts(name)
            for component in components[:-1]:
                if component in branch and branch[component] is None:
                    raise Refusal("input_alias")
                branch = branch.setdefault(component, {})
            if components[-1] in branch:
                raise Refusal("input_alias")
            branch[components[-1]] = None

        def walk(fd: int, allowed: dict) -> None:
            if set(os.listdir(fd)) != set(allowed):
                raise Refusal("input_file_set")
            for name, children in allowed.items():
                if children is not None:
                    child = _open_dir(fd, name)
                    try:
                        self._directory_mode(child)
                        walk(child, children)
                    finally:
                        os.close(child)

        walk(self.fd, tree)


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise Refusal("duplicate_json_key")
        value[key] = item
    return value


def _constant(token: str):
    raise Refusal("nan" if token == "NaN" else "infinity")


def _float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise Refusal("overflow_nonfinite")
    return value


def utf8(raw: bytes) -> str:
    try:
        text = raw.decode("utf-8", "strict")
    except UnicodeError:
        raise Refusal("invalid_utf8") from None
    if text.lstrip(" \t\r\n").startswith("\ufeff"):
        raise Refusal("bom")
    return text


def strict_json(raw: bytes):
    """One unmodified JSON value; no extraction, fences, repair or coercion."""
    text = utf8(raw)
    start = len(text) - len(text.lstrip(" \t\r\n"))
    if text[start:].startswith("```"):
        raise Refusal("code_fence")
    if text[start:] and text[start] not in '{["-0123456789tfnNI':
        raise Refusal("prose")
    try:
        decoder = json.JSONDecoder(object_pairs_hook=_pairs, parse_constant=_constant, parse_float=_float)
        obj, end = decoder.raw_decode(text, start)
        if text[end:].strip(" \t\r\n"):
            raise Refusal("trailing_data")

        def unicode_check(value):
            if isinstance(value, str):
                value.encode("utf-8", "strict")
            elif isinstance(value, dict):
                for key, item in value.items():
                    unicode_check(key)
                    unicode_check(item)
            elif isinstance(value, list):
                for item in value:
                    unicode_check(item)

        unicode_check(obj)
        return obj
    except Refusal:
        raise
    except UnicodeError:
        raise Refusal("invalid_unicode") from None
    except (ValueError, RecursionError, OverflowError):
        raise Refusal("malformed_json") from None


def fields(value, required: set[str]) -> None:
    if not isinstance(value, dict):
        raise Refusal("field_type")
    if set(value) - required:
        raise Refusal("field_extra")
    if required - set(value):
        raise Refusal("field_missing")


def text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def pointer(profile: dict, path: str):
    if not isinstance(path, str) or not path.startswith("/"):
        raise Refusal("pointer")
    value = profile
    for raw in path[1:].split("/"):
        i = 0
        while i < len(raw):
            if raw[i] == "~":
                if i + 1 == len(raw) or raw[i + 1] not in "01":
                    raise Refusal("pointer")
                i += 1
            i += 1
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(value, dict) and token in value:
            value = value[token]
        elif (isinstance(value, list) and token.isascii() and token.isdecimal()
              and str(int(token)) == token and int(token) < len(value)):
            value = value[int(token)]
        else:
            raise Refusal("pointer")
    if not text(value):
        raise Refusal("pointer")
    return value


def refuse_leaks(value) -> None:
    """Structural leak markers in the packet, not semantic keyword judging.

    The pinned protocol/FORMAT legitimately name labels/counts/schema; they are
    not screened or rewritten. Packet fields are screened recursively, including
    compound count/report/expected keys; candidate-decisions strings are banned.
    """
    if isinstance(value, dict):
        for key, item in value.items():
            separated = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", key)
            words = set(re.split(r"[^a-z0-9]+", separated.casefold()))
            if words & LEAK_WORDS:
                raise Refusal("leak_marker")
            refuse_leaks(item)
    elif isinstance(value, list):
        for item in value:
            refuse_leaks(item)
    elif isinstance(value, str) and "candidate-decisions" in value.casefold():
        raise Refusal("leak_marker")


def packet_index(packet) -> dict:
    refuse_leaks(packet)
    fields(packet, {"schema", "controls"})
    if packet["schema"] != PACKET_SCHEMA:
        raise Refusal("packet_schema")
    if not isinstance(packet["controls"], list) or not packet["controls"]:
        raise Refusal("packet_schema")
    controls = {}
    for row in packet["controls"]:
        fields(row, {"id", "brief", "profile", "path"})
        if not text(row["id"]) or not text(row["brief"]) or not isinstance(row["profile"], dict):
            raise Refusal("packet_control")
        if row["id"] in controls:
            raise Refusal("duplicate_id")
        pointer(row["profile"], row["path"])
        controls[row["id"]] = row
    return controls


def inventory(controls: dict) -> list[dict]:
    return [{"id": row["id"], "path": row["path"]} for row in controls.values()]


def json_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def pinned(raw: bytes, pin: str) -> None:
    if not isinstance(pin, str) or not re.fullmatch(r"[a-f0-9]{64}", pin) or digest(raw) != pin:
        raise Refusal("pin_mismatch")


def project(input_root: str | Path, packet: str, packet_sha256: str, label_rules: str,
            label_rules_sha256: str, format_file: str, format_sha256: str,
            output_root: str | Path) -> dict:
    if len({packet, label_rules, format_file}) != 3:
        raise Refusal("input_alias")
    with PrivateRoot(input_root) as source:
        source.require_files((packet, label_rules, format_file))
        packet_raw = source.read_bytes(packet)
        pinned(packet_raw, packet_sha256)
        rules_raw = source.read_bytes(label_rules)
        pinned(rules_raw, label_rules_sha256)
        format_raw = source.read_bytes(format_file)
        pinned(format_raw, format_sha256)
    controls = packet_index(strict_json(packet_raw))
    if not rules_raw or not format_raw:
        raise Refusal("empty_input")
    utf8(rules_raw)
    utf8(format_raw)
    prompt = FRAMING + rules_raw + FORMAT_SEPARATOR + format_raw + PACKET_SEPARATOR + packet_raw
    if len(prompt) > MAX_BYTES:
        raise Refusal("size")
    result = {"schema": PROJECTION_SCHEMA,
              "inputs": {name: {"sha256": digest(raw), "bytes": len(raw)} for name, raw in
                         (("packet", packet_raw), ("label_rules", rules_raw), ("format", format_raw))},
              "inventory": inventory(controls), "prompt_sha256": digest(prompt), "prompt_bytes": len(prompt)}
    with PrivateRoot(output_root) as output:
        output.require_empty()
        output.write_new("projection.json", json_bytes(result))
        output.write_new("prompt.txt", prompt)
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="D1 exact-byte projection; prints metadata only.")
    parser.add_argument("--input-root", required=True)
    parser.add_argument("--packet", required=True)
    parser.add_argument("--packet-sha256", required=True)
    parser.add_argument("--label-rules", required=True)
    parser.add_argument("--label-rules-sha256", required=True)
    parser.add_argument("--format", dest="format_file", required=True)
    parser.add_argument("--format-sha256", required=True)
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args(argv)
    try:
        result = project(**vars(args))
        print(json.dumps(result, sort_keys=True))
        return 0
    except (Refusal, OSError) as error:
        code = error.code if isinstance(error, Refusal) else "filesystem"
        print(json.dumps({"ok": False, "reject_reasons": [code]}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
