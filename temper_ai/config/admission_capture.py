"""Opt-in raw capture and closed owned lookup; no start or custody authority.

DB capture uses the caller's transaction. Classified capture is a separate
identity-only API, not a supported candidate launch mode. Neither calls get(),
substitutes variables, reopens files, or falls back to another source.
"""
from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from typing import Any

import yaml

from temper_ai.config.admission_contract import (
    AdmissionRefused,
    ApprovedCandidateDescriptor,
    ContractCodec,
    DescriptorAuthority,
    RawClosure,
    RawRecord,
    RefusalCode,
    canonical_bytes,
    decode_canonical,
)
from temper_ai.config.helpers import (
    MAX_YAML_NESTING_DEPTH,
    MAX_YAML_NODES,
    SUPPORTED_SCHEMA_VERSION,
)
from temper_ai.config.store import ConfigStore
from temper_ai.spawner import box_guard


class _UniqueYAML(yaml.SafeLoader):
    """Reject all aliases (including scalar aliases) and duplicate/non-string keys."""

    def compose_node(self, parent: Any, index: Any) -> Any:
        if self.check_event(yaml.AliasEvent):
            raise AdmissionRefused(RefusalCode.ALIAS)
        return super().compose_node(parent, index)

    def construct_mapping(self, node: Any, deep: bool = False) -> dict:
        result: dict = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if type(key) is not str:
                raise AdmissionRefused(RefusalCode.TYPE)
            if key in result:
                raise AdmissionRefused(RefusalCode.DUPLICATE)
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def _parse_classified(data: bytes) -> dict:
    # Use the existing config resource limits, including before constructing a
    # recursive YAML document. No parser exception or rejected data escapes.
    try:
        depth = count = 0
        for event in yaml.parse(data.decode("utf-8"), Loader=_UniqueYAML):
            count += 1
            if isinstance(event, (yaml.SequenceStartEvent, yaml.MappingStartEvent)):
                depth += 1
            elif isinstance(event, (yaml.SequenceEndEvent, yaml.MappingEndEvent)):
                depth -= 1
            if depth > MAX_YAML_NESTING_DEPTH or count > MAX_YAML_NODES:
                raise AdmissionRefused(RefusalCode.SCHEMA)
        loader = _UniqueYAML(data.decode("utf-8"))
        try:
            raw = loader.get_single_data()
        finally:
            loader.dispose()
        owned = decode_canonical(canonical_bytes(raw))
        if type(owned) is not dict:
            raise AdmissionRefused(RefusalCode.TYPE)
        return owned
    except (yaml.YAMLError, UnicodeError, RecursionError, ValueError, TypeError):
        raise AdmissionRefused(RefusalCode.JSON) from None


def capture_classified_record(
    codec: ContractCodec, *, guard: box_guard.Guard, name: str,
    config_type: str, launch_id: str,
) -> RawRecord:
    """Capture only the active guard's checked bytes; launch_id is caller authority.

    This label is supplied by the already authorized classified caller. It is
    not inferred from a workflow name or a digest, and is NOT launch permission.
    v1 descriptors still reject classified origins at the start-mode boundary.
    """
    if type(guard) is not box_guard.Guard or guard is not box_guard.active():
        raise AdmissionRefused(RefusalCode.ORIGIN)
    path, data = guard.raw_config_record(name, config_type)
    config = _parse_classified(data)
    if config.get("schema_version", "1.0") != SUPPORTED_SCHEMA_VERSION:
        raise AdmissionRefused(RefusalCode.VERSION)
    return codec.raw_record(canonical_bytes({
        "format": "candidate-raw-record/v1", "kind": config_type, "name": name,
        "schema_version": config.get("schema_version", "1.0"),
        "origin": {"kind": "classified_file", "launch_id": launch_id,
                   "relative_path": path, "file_sha256": hashlib.sha256(data).hexdigest(),
                   "git_blob_sha1": box_guard.blob_id(data)},
        "config_json": canonical_bytes(config).decode("utf-8"),
        "file_base64": base64.b64encode(data).decode("ascii"),
    }))


@dataclass(frozen=True, slots=True)
class RawCapture:
    codec: ContractCodec
    authority: DescriptorAuthority
    store: ConfigStore

    def capture(self, descriptor: ApprovedCandidateDescriptor, *, transaction: object) -> tuple[RawRecord, ...]:
        """Capture the exact inventory, before transformation, in one transaction."""
        approved = self.codec.descriptor(descriptor.wire, self.authority)
        if box_guard.active() is not None:
            raise AdmissionRefused(RefusalCode.MODE)
        records = []
        for expected in approved.value()["records"]:
            config, version = self.store.get_raw_record(
                expected["name"], expected["kind"], transaction=transaction,
            )
            records.append(self.codec.raw_record(canonical_bytes({
                "format": "candidate-raw-record/v1", "kind": expected["kind"],
                "name": expected["name"], "schema_version": version,
                "origin": {"kind": "db"}, "file_base64": None,
                "config_json": canonical_bytes(config).decode("utf-8"),
            })))
        return self.codec.closure(approved, tuple(records)).records


@dataclass(frozen=True, slots=True, init=False)
class SnapshotResolver:
    """Loader-compatible get(name, type), owning only immutable checked bytes.

    No underlying store or fallback. Revalidation also closes public dataclass
    constructor bypasses; the descriptor wrapper's embedded authority is not
    used in place of the independently supplied authority.
    """

    closure: RawClosure

    def __init__(self, codec: ContractCodec, descriptor: ApprovedCandidateDescriptor,
                 records: tuple[RawRecord, ...], *, authority: DescriptorAuthority):
        approved = codec.descriptor(descriptor.wire, authority)
        object.__setattr__(self, "closure", codec.closure(approved, records))

    def get(self, name: str, config_type: str) -> dict[str, Any]:
        if type(name) is not str or type(config_type) is not str:
            raise AdmissionRefused(RefusalCode.TYPE)
        return self.closure.get(config_type, name)
