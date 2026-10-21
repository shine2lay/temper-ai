#!/usr/bin/env python3
"""D2: validate one preserved raw T1 answer, without repair or semantic inference.

Uses context_t1_project's C1-derived nofollow file reader, strict_json and packet
index. The C1 validate rule is retained: only literal 'none' is the unsupported
sentinel (T1 ERRATUM-1 SHA256 ef5adb9ba56ccf4d205302665ae3cad44ce169bace40dd27622e4c723ccadc99).
Other spellings are ordinary exact-substring candidates, not alternate sentinels.
Neither a literal quote nor a PASS establishes source-based meaning or admission.

CLI: --input-root DIR --raw REL --packet REL --projection REL --slot A1..B3
     --output-root DIR
Inputs use private descriptor-relative paths, never a structured_output field.
The packet's digest, length and ordered inventory must match the strict D1
projection. D1 is a trusted controller artifact, not a cryptographic signature:
its provenance and prompt hash must be bound separately before any future J.

Output: <slot>.validation.json, O_EXCL, mode 0600; first failure only, with a
stable reason code. decision_ids appears only on PASS and follows packet order,
not arbitrary answer order. Unsafe/unreadable bytes are never read for a hash;
raw_sha256/raw_bytes or packet_sha256 remain null when unavailable. This is
terminal REJECT evidence, never success or zero-length invented evidence.
Stdout contains only this metadata, never raw answers, briefs or prompts.
Exit 0 = PASS, 1 = recorded REJECT, 2 = no safe output/invalid invocation.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from context_t1_project import (
    FRAMING_BYTES,
    INPUT_NAMES,
    MAX_BYTES,
    PROJECTION_SCHEMA,
    PrivateRoot,
    Refusal,
    digest,
    fields,
    inventory,
    json_bytes,
    packet_index,
    strict_json,
    text,
)

VALIDATION_SCHEMA = "context-t1-validation/v1"
SLOTS = ("A1", "A2", "A3", "B1", "B2", "B3")
LABELS = ("supported", "contradicted", "unsupported", "uncertain")
FAMILIES = tuple(f"F{i:02d}" for i in range(1, 13))
ROW_KEYS = {"id", "path", "label", "family", "source_span", "rationale"}
# The exported record's enum; one stable code per distinct rejection mechanism.
REASON_CODES = (
    "invalid_utf8", "bom", "code_fence", "prose", "trailing_data", "malformed_json",
    "duplicate_json_key", "nan", "infinity", "overflow_nonfinite", "invalid_unicode",
    "field_extra", "field_missing", "field_type", "schema", "invalid_id", "duplicate_id",
    "missing_id", "extra_id", "target_path", "label", "family", "nonbad_family",
    "empty_span", "nonliteral_span", "sentinel_label", "empty_rationale", "rationale_too_long",
    "path", "symlink", "file_type", "hardlink", "file_mode", "size", "directory_mode",
    "filesystem", "file_changed", "input_alias", "leak_marker", "packet_schema",
    "packet_control", "pointer", "projection_schema", "projection_digest", "projection_bytes",
    "projection_inventory", "projection_packet_pin",
)


def _sha(value) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) is not None


def _length(value) -> bool:
    return type(value) is int and 0 < value <= MAX_BYTES


def check_projection(projection, packet_raw: bytes, controls: dict) -> None:
    fields(projection, {"schema", "inputs", "inventory", "prompt_sha256", "prompt_bytes"})
    if projection["schema"] != PROJECTION_SCHEMA:
        raise Refusal("projection_schema")
    fields(projection["inputs"], INPUT_NAMES)
    for binding in projection["inputs"].values():
        fields(binding, {"sha256", "bytes"})
        if not _sha(binding["sha256"]):
            raise Refusal("projection_digest")
        if not _length(binding["bytes"]):
            raise Refusal("projection_bytes")
    if not _sha(projection["prompt_sha256"]):
        raise Refusal("projection_digest")
    expected_bytes = FRAMING_BYTES + sum(b["bytes"] for b in projection["inputs"].values())
    if not _length(projection["prompt_bytes"]) or projection["prompt_bytes"] != expected_bytes:
        raise Refusal("projection_bytes")
    if projection["inputs"]["packet"] != {"sha256": digest(packet_raw), "bytes": len(packet_raw)}:
        raise Refusal("projection_packet_pin")
    if projection["inventory"] != inventory(controls):
        raise Refusal("projection_inventory")


def validate(controls: dict, document) -> list[str]:
    """C1 validate, tightened types/reasons; no semantic inference, repair or coercion."""
    fields(document, {"schema", "decisions"})
    if not isinstance(document["schema"], str) or not isinstance(document["decisions"], list):
        raise Refusal("field_type")
    if document["schema"] != "candidate-decisions/v2":
        raise Refusal("schema")
    indexed = {}
    for row in document["decisions"]:
        fields(row, ROW_KEYS)
        for name in ("id", "path", "label", "source_span", "rationale"):
            if not isinstance(row[name], str):
                raise Refusal("field_type")
        ident = row["id"]
        if not text(ident):
            raise Refusal("invalid_id")
        if ident in indexed:
            raise Refusal("duplicate_id")
        if ident not in controls:
            raise Refusal("extra_id")
        control = controls[ident]
        if row["path"] != control["path"]:
            raise Refusal("target_path")
        if row["label"] not in LABELS:
            raise Refusal("label")
        if row["label"] in ("contradicted", "unsupported"):
            if not isinstance(row["family"], str) or row["family"] not in FAMILIES:
                raise Refusal("family")
        elif row["family"] is not None:
            raise Refusal("nonbad_family")
        span = row["source_span"]
        if not text(span):
            raise Refusal("empty_span")
        if span == "none":
            if row["label"] != "unsupported":
                raise Refusal("sentinel_label")
        elif span.encode("utf-8") not in control["brief"].encode("utf-8"):
            raise Refusal("nonliteral_span")
        if not text(row["rationale"]):
            raise Refusal("empty_rationale")
        if len(row["rationale"]) > 1500:
            raise Refusal("rationale_too_long")
        indexed[ident] = row
    if set(indexed) != set(controls):
        raise Refusal("missing_id")
    return list(controls)


def validate_slot(input_root: str | Path, raw: str, packet: str, projection: str, slot: str,
                  output_root: str | Path) -> dict:
    if slot not in SLOTS:
        raise Refusal("slot")
    result = {"schema": VALIDATION_SCHEMA, "slot": slot, "raw_sha256": None, "raw_bytes": None,
              "packet_sha256": None, "verdict": "REJECT", "reject_reasons": []}
    try:
        if len({raw, packet, projection}) != 3:
            raise Refusal("input_alias")
        with PrivateRoot(input_root) as source:
            answer_raw = source.read_bytes(raw)
            result.update(raw_sha256=digest(answer_raw), raw_bytes=len(answer_raw))
            packet_raw = source.read_bytes(packet)
            result["packet_sha256"] = digest(packet_raw)
            controls = packet_index(strict_json(packet_raw))
            check_projection(strict_json(source.read_bytes(projection)), packet_raw, controls)
        ids = validate(controls, strict_json(answer_raw))
        result.update(verdict="PASS", decision_ids=ids)
    except Refusal as error:
        result["reject_reasons"] = [error.code]
    except OSError:
        result["reject_reasons"] = ["filesystem"]
    with PrivateRoot(output_root) as output:
        output.write_new(f"{slot}.validation.json", json_bytes(result))
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="D2 raw-answer validator; no repair or re-ask.")
    parser.add_argument("--input-root", required=True)
    parser.add_argument("--raw", required=True)
    parser.add_argument("--packet", required=True)
    parser.add_argument("--projection", required=True)
    parser.add_argument("--slot", required=True, choices=SLOTS)
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args(argv)
    try:
        result = validate_slot(**vars(args))
        print(json.dumps(result, sort_keys=True))
        return 0 if result["verdict"] == "PASS" else 1
    except (Refusal, OSError) as error:
        code = error.code if isinstance(error, Refusal) else "filesystem"
        print(json.dumps({"ok": False, "reject_reasons": [code]}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
