"""Shared IPD-1 synthetic inputs and safe reports; NOT an engine simulator.

Selectors describe later B/C/E stage tests. Expected counts are specifications,
not observed sends or proof that authorization/custody exists. Content builders
are private test inputs; only booleans/counts/fixed codes reach assertions.
"""
from __future__ import annotations

import base64
import json
import struct
import zlib
from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import Field

from temper_ai.private_context.contracts import MediaCapability
from temper_ai.private_context.errors import PrivateDraftErrorCode as Code
from temper_ai.private_context.private_json import PrivateJSON, encode_private
from temper_ai.private_context.schema import SchemaArtifact, SchemaIdentity
from temper_ai.private_context.wire import ClosedModel, NonnegativeInt, decode_wire

REF = "00000000-0000-4000-8000-000000000001"
RUN = "00000000-0000-4000-8000-000000000002"
DRAFT = "00000000-0000-4000-8000-000000000003"
ATTEMPT = "00000000-0000-4000-8000-000000000004"
EXPIRY = "2099-01-01T00:00:00Z"
CaseID = Literal["M1-good", "M1-refusal", "M2-good", "M2-refusal", "M3-good", "M3-refusal", "M4-good", "M4-refusal", "M5-good", "M5-refusal", "M6-good", "M6-refusal", "M7-good", "M7-refusal", "M8-good", "M8-refusal"]


class Arrange(ClosedModel):
    principal: Literal["named-owner", "named-other"]
    namespace: Literal["scope-1"]
    profile: Literal["synthetic-reply-v1", "legacy-named-image"]
    context_fixture: Literal["valid"]
    media_fixture: Literal["zero-png", "one-png", "two-png", "missing-png"]
    model_profile: Literal["SYNTHETIC-P2"]
    pool_schedule: Literal["healthy", "two-eligible", "named"]
    transport_schedule: Literal["complete", "http429-then-complete", "stream429", "missing-summary"]
    store_schedule: Literal["current", "clean", "injected-leak", "ready-reread", "ready-mailbox-lost", "cancel-before-reserve", "cancel-after-reserve"]


class Expected(ClosedModel):
    code: Code | None
    initiated_requests: NonnegativeInt | None = None
    selected_slots: list[NonnegativeInt] | None = None
    resolutions: NonnegativeInt | None = None
    publications: NonnegativeInt | None = None
    private_reads: NonnegativeInt | None = None
    export_leak_count: NonnegativeInt | None = None


class Case(ClosedModel):
    id: CaseID
    pair_id: CaseID
    purpose: Literal["auth-ref", "text-photos", "true-pool", "draft-sink", "persistence", "lifecycle", "compatibility", "cancel"]
    arrange: Arrange
    act: Literal["resolve", "validate-media", "invoke", "validate-draft", "scan", "resume", "legacy-image", "cancel"]
    expect: Expected


class Manifest(ClosedModel):
    suite: Literal["IPD-1"]
    schema_revision: Literal["synthetic-v1"]
    authority: Literal["synthetic-contract-fixtures-only"]
    cases: list[Case]


def manifest() -> Manifest:
    raw = (Path(__file__).parent / "fixtures" / "ipd1.json").read_bytes()
    return decode_wire(raw, Manifest)


class CheckCode(StrEnum):
    CONTRACT = "contract"
    SCANNER = "scanner"
    EXPECTATION = "expectation"
    FIXTURE = "fixture"


def require(condition: bool, code: CheckCode = CheckCode.CONTRACT) -> None:
    """No pytest operand repr, input value, child process or arbitrary failure text."""
    if type(condition) is not bool or type(code) is not CheckCode:
        raise AssertionError("invalid safe check")
    if not condition:
        raise AssertionError(code.value)


class SafeReport(ClosedModel):
    suite: Literal["IPD-1"] = "IPD-1"
    case_id: CaseID
    stage: Literal["contracts", "transport", "service", "integration"]
    passed: bool
    code: Code | None = None
    checks: NonnegativeInt = 0
    leak_count: NonnegativeInt = 0


class Surface(StrEnum):
    EVENT = "event"
    CHECKPOINT = "checkpoint"
    ERROR = "error"
    JSONL = "jsonl"
    STREAM = "stream"
    EXPORT = "export"


class ScanReport(ClosedModel):
    clean: bool
    inspected: NonnegativeInt
    leak_count: NonnegativeInt
    # Keys are fixed surface labels, values counts. No path/text/exception input.
    hits: dict[Surface, NonnegativeInt] = Field(default_factory=dict)


def scan(surfaces: Mapping[Surface, bytes | str], markers: tuple[bytes, ...] | None = None) -> ScanReport:
    needles = canaries() if markers is None else markers
    require(bool(needles) and all(type(item) is bytes and len(item) > 0 for item in needles), CheckCode.SCANNER)
    hits: dict[Surface, int] = {}
    for label, content in surfaces.items():
        require(type(label) is Surface and type(content) in {str, bytes}, CheckCode.SCANNER)
        raw = content.encode("utf-8") if isinstance(content, str) else content
        count = sum(raw.count(marker) for marker in needles)
        if count:
            hits[label] = count
    total = sum(hits.values())
    return ScanReport(clean=total == 0, inspected=len(surfaces), leak_count=total, hits=hits)


def _png(ordinal: int) -> bytes:
    # Two distinct full-frame RGB fixtures. This builds bytes, never validates PNG.
    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(bytes((0, 81 + ordinal, 142, 219)))) + chunk(b"IEND", b"")


def canaries() -> tuple[bytes, ...]:
    return (b"IPD1_CONTEXT_CANARY_PRIVATE", b"IPD1_DRAFT_CANARY_PRIVATE", b"IPD1_CREDENTIAL_CANARY_PRIVATE", b"IPD1_PROVIDER_CANARY_PRIVATE", _png(0), base64.b64encode(_png(0)))


def schemas() -> SchemaArtifact:
    # Deliberately NOT Inkflow's schema; exercises actual JSON Schema rules.
    nonblank = {"type": "string", "pattern": "\\S"}
    context = {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object", "required": ["snapshot_version", "purpose", "messages"], "additionalProperties": False, "properties": {"snapshot_version": nonblank, "purpose": nonblank, "messages": {"type": "array", "items": {"type": "object", "required": ["message_ref", "text"], "additionalProperties": False, "properties": {"message_ref": nonblank, "text": {"$ref": "#/$defs/text"}}}}}, "$defs": {"text": nonblank}}
    draft = {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object", "required": ["reply", "purposeSummary"], "additionalProperties": False, "properties": {"reply": nonblank, "purposeSummary": nonblank}}
    identity = SchemaIdentity(owner="engine-tests", revision="synthetic-v1", source_kind="synthetic", context_schema="synthetic.ipd-context.v1", result_schema="synthetic.ipd-draft.v1")
    return SchemaArtifact(identity, context=encode_private(context), result=encode_private(draft))


def capability() -> MediaCapability:
    return MediaCapability(profile="SYNTHETIC-P2", revision="synthetic-v1", source_kind="synthetic", provider="synthetic", model="synthetic", max_images=2, max_image_bytes=4096, max_width=32, max_height=32, max_request_bytes=16384)


def registration(media: Literal["zero-png", "one-png", "two-png", "missing-png"] = "two-png") -> PrivateJSON:
    count = {"zero-png": 0, "one-png": 1, "two-png": 2, "missing-png": 2}[media]
    attachments = []
    for ordinal in range(count):
        common = {"attachment_ref": f"attachment-{ordinal}", "message_ref": f"turn-{ordinal}", "ordinal": ordinal}
        if media == "missing-png" and ordinal == 1:
            attachments.append({**common, "status": "unavailable", "reason_code": "missing"})
        else:
            image = _png(ordinal)
            attachments.append({**common, "status": "available", "media_type": "image/png", "data_base64": base64.b64encode(image).decode("ascii"), "decoded_bytes": len(image), "width": 1, "height": 1, "preparation_version": "synthetic-v1"})
    return PrivateJSON(encode_private({"version": "temper.private-draft.v1", "profile": "synthetic-reply-v1", "namespace": "scope-1", "application_attempt_id": "app-attempt-1", "expires_at": EXPIRY, "context_schema": "synthetic.ipd-context.v1", "context": {"snapshot_version": "snapshot-1", "purpose": canaries()[0].decode(), "messages": [{"message_ref": f"turn-{i}", "text": canaries()[0].decode()} for i in range(2)]}, "attachments": attachments}))


def draft() -> PrivateJSON:
    return PrivateJSON(encode_private({"reply": canaries()[1].decode(), "purposeSummary": canaries()[1].decode()}))


def safe_json(report: SafeReport | ScanReport) -> str:
    require(type(report) in {SafeReport, ScanReport}, CheckCode.EXPECTATION)
    return json.dumps(report.model_dump(mode="json"), allow_nan=False, sort_keys=True)
