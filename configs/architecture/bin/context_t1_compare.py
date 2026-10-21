#!/usr/bin/env python3
"""D3: private, deterministic T1 equality, never a judge tool or semantic grader.

Read one D2-PASS raw answer, a key, and its freeze through a private root.
The caller pins the freeze's SHA256; its key/EXPECTED.json entry binds the key.
Only id/path/label/family are equality-scored. D2 owns literal-span validity;
Architecture's independent receipts own source/rationale acceptance. A different
valid span or rationale is not a mismatch. No repair, key inference or model.

CLI: --root DIR --slot A1 --freeze-sha256 HEX [--raw REL --validation REL
     --key REL --freeze REL]. Writes <slot>.comparison.json exclusively, 0600.
Exit 0: comparison PASS; 1: comparison FAIL; 2: refused (no replacement output).
Per-case actual/expected values accompany equality flags so D4 can independently
recompute counts and exact pair repeatability; all output remains private.
Shared strict JSON/private-file primitives below are also used by D4, not D1/D2.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import stat
from collections import Counter
from decimal import Decimal
from pathlib import Path

LABELS = ("supported", "contradicted", "unsupported", "uncertain")
BAD = ("contradicted", "unsupported")
FAMILIES = tuple(f"F{i:02d}" for i in range(1, 13))
SLOTS = ("A1", "A2", "A3", "B1", "B2", "B3")
CLASS_TOTALS = dict(zip(LABELS, (9, 10, 9, 9), strict=True))
FAMILY_TOTALS = dict(zip(FAMILIES, (1, 1, 2, 1, 2, 2, 2, 2, 1, 2, 1, 2), strict=True))
MAX_BYTES = 2_000_000
ROW_FIELDS = {"id", "path", "label", "family", "source_span", "rationale"}
CASE_FIELDS = {"id", "path", "expected_label", "actual_label", "expected_family", "actual_family",
               "class_match", "family_match", "nonbad_null_ok", "false_support"}
COMPARISON_FIELDS = {"schema", "slot", "raw_sha256", "packet_sha256", "key_sha256", "freeze_sha256",
                     "per_case", "classes", "families", "class_matches", "applicable_bad_family_matches",
                     "nonbad_null_families", "false_support", "known_bad_or_uncertain_cases", "verdict"}


class Refusal(ValueError):
    """Invalid/unbound evidence or unsafe file. The message is a non-content code."""


def require(condition, code):
    if not condition:
        raise Refusal(code)


def fields(value, names):
    require(type(value) is dict and set(value) == set(names), "fields")


def text(value):
    return type(value) is str and bool(value.strip())


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def is_digest(value):
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value) and value >= 0
    except OverflowError:
        return False


def strict_json(raw):
    def pairs(items):
        obj = {}
        for key, value in items:
            require(key not in obj, "duplicate_json_key")
            obj[key] = value
        return obj

    def nonfinite(_):
        raise Refusal("nonfinite")

    def finite_float(value):
        parsed = float(value)
        require(math.isfinite(parsed), "nonfinite")
        # Never round a just-over-cap price down to the cap (or underflow to 0).
        require(Decimal(str(parsed)) == Decimal(value), "lossy_number")
        return parsed

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

    try:
        result = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                            parse_constant=nonfinite, parse_float=finite_float)
        unicode_check(result)
        return result
    except (ValueError, UnicodeError, RecursionError, OverflowError) as exc:
        if isinstance(exc, Refusal):
            raise
        raise Refusal("json") from None


class PrivateStore:
    """Descriptor-relative O_NOFOLLOW on every component, including root ancestry.

    Inside root, directories are 0700 and files regular, single-link, 0600,
    at most 2 MB. This is a local file envelope, NOT judge/OS isolation proof.
    No mkdir, chmod, unlink, overwrite, recovery or symlink resolution here.
    """

    def __init__(self, root):
        root = os.fspath(root)
        require(root.startswith("/") and "\\" not in root and "\0" not in root, "root")
        parts = root[1:].split("/")
        require(all(part not in ("", ".", "..") for part in parts), "root")
        fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
        try:
            for part in parts:
                nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = nxt
            require(stat.S_IMODE(os.fstat(fd).st_mode) == 0o700, "directory_mode")
        except BaseException:
            os.close(fd)
            raise
        self.fd = fd

    def __enter__(self):
        return self

    def __exit__(self, *_):
        os.close(self.fd)

    def parent(self, relative):
        require(type(relative) is str and relative and "\\" not in relative and "\0" not in relative, "path")
        parts = relative.split("/")
        require(all(part not in ("", ".", "..") for part in parts), "path")
        fd = os.dup(self.fd)
        try:
            for part in parts[:-1]:
                nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = nxt
                require(stat.S_IMODE(os.fstat(fd).st_mode) == 0o700, "directory_mode")
            return fd, parts[-1]
        except BaseException:
            os.close(fd)
            raise

    def read(self, relative):
        parent, leaf = self.parent(relative)
        try:
            fd = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        finally:
            os.close(parent)
        try:
            before = os.fstat(fd)
            require(stat.S_ISREG(before.st_mode), "file_type")
            require(before.st_nlink == 1, "hardlink")
            require(stat.S_IMODE(before.st_mode) == 0o600, "file_mode")
            require(before.st_size <= MAX_BYTES, "size")
            chunks, size = [], 0
            while True:
                chunk = os.read(fd, min(65536, MAX_BYTES + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                require(size <= MAX_BYTES, "size")
            after = os.fstat(fd)
            require((before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
                    (after.st_size, after.st_mtime_ns, after.st_ctime_ns) and size == after.st_size, "file_changed")
            return b"".join(chunks)
        finally:
            os.close(fd)

    def load(self, relative):
        return strict_json(self.read(relative))

    def emit(self, relative, document):
        raw = (json.dumps(document, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode("utf-8")
        require(len(raw) <= MAX_BYTES, "size")
        parent, leaf = self.parent(relative)
        try:
            fd = os.open(leaf, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
        finally:
            os.close(parent)
        # A failed write is retained, never deleted or retried as a successful slot.
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())


def decisions(document):
    fields(document, {"schema", "decisions"})
    require(document["schema"] == "candidate-decisions/v2" and type(document["decisions"]) is list, "decisions_schema")
    indexed = {}
    for row in document["decisions"]:
        fields(row, ROW_FIELDS)
        ident = row["id"]
        require(text(ident) and ident not in indexed, "duplicate_or_invalid_id")
        require(text(row["path"]) and row["path"].startswith("/"), "path")
        require(type(row["label"]) is str and row["label"] in LABELS, "label")
        require((row["label"] in BAD and type(row["family"]) is str and row["family"] in FAMILIES)
                or (row["label"] not in BAD and row["family"] is None), "family")
        require(text(row["source_span"]) and text(row["rationale"]) and len(row["rationale"]) <= 1500, "evidence_shape")
        indexed[ident] = row
    require(len(indexed) == 37, "case_inventory")
    return indexed


def case_flags(row):
    applicable = row["expected_label"] in BAD
    return {
        "class_match": row["actual_label"] == row["expected_label"],
        "family_match": row["actual_family"] == row["expected_family"] if applicable else None,
        "nonbad_null_ok": applicable or row["actual_family"] is None,
        "false_support": row["expected_label"] != "supported" and row["actual_label"] == "supported",
    }


def summarize(rows):
    """Recomputed by D4 as well: per-case observations, never caller totals."""
    require(Counter(row["expected_label"] for row in rows) == CLASS_TOTALS, "key_class_inventory")
    require(Counter(row["expected_family"] for row in rows if row["expected_label"] in BAD) == FAMILY_TOTALS,
            "key_family_inventory")
    classes = {label: {"matches": sum(row["class_match"] for row in rows if row["expected_label"] == label),
                       "total": total} for label, total in CLASS_TOTALS.items()}
    families = {family: {"matches": sum(row["family_match"] is True for row in rows if row["expected_family"] == family),
                         "total": total} for family, total in FAMILY_TOTALS.items()}
    result = {
        "classes": classes, "families": families,
        "class_matches": sum(row["class_match"] for row in rows),
        "applicable_bad_family_matches": sum(row["family_match"] is True for row in rows),
        "nonbad_null_families": sum(row["nonbad_null_ok"] for row in rows if row["expected_label"] not in BAD),
        "false_support": sum(row["false_support"] for row in rows),
        "known_bad_or_uncertain_cases": sum(row["expected_label"] != "supported" for row in rows),
    }
    passed = (result["class_matches"] == 37 and result["applicable_bad_family_matches"] == 19
              and result["nonbad_null_families"] == 18 and result["false_support"] == 0
              and all(item["matches"] == item["total"] for item in (*classes.values(), *families.values())))
    return {**result, "verdict": "PASS" if passed else "FAIL"}


def checked_comparison(document):
    """Reject internally contradictory summaries/flags, not a provenance claim."""
    fields(document, COMPARISON_FIELDS)
    require(document["schema"] == "context-t1-comparison/v1" and document["slot"] in SLOTS, "comparison_schema")
    require(all(is_digest(document[name]) for name in ("raw_sha256", "packet_sha256", "key_sha256", "freeze_sha256")),
            "comparison_digest")
    rows = document["per_case"]
    require(type(rows) is list and len(rows) == 37, "comparison_inventory")
    seen = set()
    for row in rows:
        fields(row, CASE_FIELDS)
        require(text(row["id"]) and row["id"] not in seen and text(row["path"]) and row["path"].startswith("/"), "comparison_id_path")
        seen.add(row["id"])
        for prefix in ("expected", "actual"):
            label, family = row[f"{prefix}_label"], row[f"{prefix}_family"]
            require(type(label) is str and label in LABELS, "comparison_label")
            require((label in BAD and type(family) is str and family in FAMILIES)
                    or (label not in BAD and family is None), "comparison_family")
        for name, expected in case_flags(row).items():
            require(type(row[name]) is type(expected) and row[name] == expected, "comparison_flags")
    calculated = summarize(rows)
    # JSON comparison (not Python ==) keeps True from masquerading as count 1.
    require(json.dumps({name: document[name] for name in calculated}, sort_keys=True) ==
            json.dumps(calculated, sort_keys=True), "comparison_counts")
    return {row["id"]: row for row in rows}


def compare(root, slot, freeze_sha256, *, raw=None, validation=None,
            key="key/EXPECTED.json", freeze="key/EXPECTED-FREEZE.json"):
    require(slot in SLOTS and is_digest(freeze_sha256), "slot_or_pin")
    with PrivateStore(root) as store:
        frozen_raw = store.read(freeze)
        require(sha256(frozen_raw) == freeze_sha256, "freeze_binding")
        frozen = strict_json(frozen_raw)
        fields(frozen, {"schema", "sha256"})
        require(frozen["schema"] == "t0-expected-freeze/v1" and type(frozen["sha256"]) is dict
                and "key/EXPECTED.json" in frozen["sha256"]
                and all(text(name) and is_digest(value) for name, value in frozen["sha256"].items()), "freeze_schema")
        key_raw = store.read(key)
        key_sha256 = sha256(key_raw)
        require(key_sha256 == frozen["sha256"]["key/EXPECTED.json"], "key_binding")
        expected = decisions(strict_json(key_raw))
        raw_bytes = store.read(raw or f"{slot}.raw.json")
        raw_sha256 = sha256(raw_bytes)
        validated = store.load(validation or f"{slot}.validation.json")
        fields(validated, {"schema", "slot", "raw_sha256", "raw_bytes", "packet_sha256", "verdict", "reject_reasons", "decision_ids"})
        require(validated["schema"] == "context-t1-validation/v1" and validated["verdict"] == "PASS"
                and validated["reject_reasons"] == [], "d2_not_pass")
        require(validated["slot"] == slot and validated["raw_sha256"] == raw_sha256
                and type(validated["raw_bytes"]) is int and validated["raw_bytes"] == len(raw_bytes)
                and is_digest(validated["packet_sha256"]), "validation_binding")
        actual = decisions(strict_json(raw_bytes))
        require(type(validated["decision_ids"]) is list and all(text(ident) for ident in validated["decision_ids"])
                and len(validated["decision_ids"]) == 37 and set(validated["decision_ids"]) == set(actual), "validation_ids")
        require(set(actual) == set(expected), "id_binding")
        rows = []
        for ident, gold in expected.items():
            row = actual[ident]
            require(row["path"] == gold["path"], "path_binding")
            observation = {"id": ident, "path": gold["path"], "expected_label": gold["label"],
                           "actual_label": row["label"], "expected_family": gold["family"], "actual_family": row["family"]}
            rows.append({**observation, **case_flags(observation)})
        result = {"schema": "context-t1-comparison/v1", "slot": slot, "raw_sha256": raw_sha256,
                  "packet_sha256": validated["packet_sha256"], "key_sha256": key_sha256,
                  "freeze_sha256": freeze_sha256, "per_case": rows, **summarize(rows)}
        checked_comparison(result)
        store.emit(f"{slot}.comparison.json", result)
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--slot", required=True, choices=SLOTS)
    parser.add_argument("--freeze-sha256", required=True)
    for name in ("raw", "validation", "key", "freeze"):
        parser.add_argument(f"--{name}")
    args = parser.parse_args(argv)
    options = {name: getattr(args, name) for name in ("raw", "validation", "key", "freeze") if getattr(args, name) is not None}
    try:
        result = compare(args.root, args.slot, args.freeze_sha256, **options)
        print(json.dumps({"slot": args.slot, "verdict": result["verdict"]}))
        return 0 if result["verdict"] == "PASS" else 1
    except (Refusal, OSError):
        print(json.dumps({"slot": args.slot, "verdict": "REFUSED"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
