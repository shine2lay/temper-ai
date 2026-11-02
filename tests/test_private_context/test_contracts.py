"""Contract-only happy case first, then private-safe single-fact refusals.

No actual service, provider, profile or application schema is represented here.
"""
from __future__ import annotations

import copy
import dataclasses
import json
import pickle
from collections.abc import Callable
from typing import Any

import pytest

from temper_ai.private_context.contracts import (
    AttemptOutcome,
    CallerPrincipal,
    MediaCapability,
    NativeAttemptResult,
    NullableUsage,
    PrivateBinding,
    PrivateExecution,
    PrivateLease,
    RunPrincipal,
    SendReservation,
)
from temper_ai.private_context.errors import (
    HTTP_STATUS,
    PRIVATE_RESPONSE_HEADERS,
    PrivateDraftFailure,
)
from temper_ai.private_context.errors import PrivateDraftErrorCode as Code
from temper_ai.private_context.private_json import (
    decode_object,
    encode_private,
)
from temper_ai.private_context.schema import SchemaArtifact, SchemaIdentity
from temper_ai.private_context.wire import (
    VERSION,
    AcknowledgedReceipt,
    ContextRead,
    ContextReceipt,
    ContextStatus,
    DraftReceipt,
    ErrorResponse,
    FailureReceipt,
    PrivateRunStart,
    ResultRead,
    RevokedReceipt,
    decode_registration,
    decode_result,
    decode_wire,
    receipt_dict,
)
from temper_ai.shared.types import ExecutionContext

from . import ipd1
from .ipd1 import require


def refused(action: Callable[[], Any], code: Code = Code.CONTEXT_INVALID) -> None:
    caught = False
    safe = False
    try:
        action()
    except PrivateDraftFailure as exc:
        caught = True
        safe = exc.code == code and exc.__context__ is None and exc.__cause__ is None
        safe = safe and ipd1.scan({ipd1.Surface.ERROR: repr(exc) + str(exc)}).clean
    require(caught and safe)


def receipt() -> dict[str, Any]:
    return {"version": VERSION, "execution_id": ipd1.RUN, "draft_ref": ipd1.DRAFT, "state": "ready", "expires_at": ipd1.EXPIRY}


def missing_usage() -> dict[str, None]:
    return {key: None for key in NullableUsage.model_fields}


def outcome() -> dict[str, Any]:
    return {"phase": "complete", "transmission": "complete", "request_started": True, "usage": missing_usage(), "usage_state": "missing", "unknown_usage_fields": 0}


def binding() -> PrivateBinding:
    return PrivateBinding(context_ref=ipd1.REF, context_version=1, execution_id=ipd1.RUN, owner_principal="owner-1", namespace="scope-1", profile="synthetic-reply-v1", profile_revision="r1", context_schema="synthetic.ipd-context.v1", result_schema="synthetic.ipd-draft.v1", schema_revision="synthetic-v1", workflow="synthetic-workflow", workflow_revision="r1", node_path="draft", use="draft", expires_at=ipd1.EXPIRY, deadline_at=ipd1.EXPIRY, runner_generation=1, revoked=False, attempt_state="unreserved")


def test_whole_contract_happy_path_before_refusal_edges() -> None:
    """All wire/holder/schema/receipt seams together, NOT a workflow success claim."""
    schemas = ipd1.schemas()
    for media in ("zero-png", "two-png"):
        context = decode_registration(ipd1.registration(media).to_private_json())
        schemas.validate_registration(context)
        start = decode_wire(encode_private({"workflow": "synthetic-workflow", "inputs": {"private_context": {"version": VERSION, "context_ref": ipd1.REF, "context_version": 1}}}), PrivateRunStart)
        require(start.inputs.private_context.context_version == 1)
        registered = decode_wire(encode_private({"context_ref": ipd1.REF, "context_version": 1, "expires_at": ipd1.EXPIRY, "profile": "synthetic-reply-v1"}), ContextReceipt)
        ready = decode_wire(encode_private(receipt()), DraftReceipt)
        status = decode_wire(encode_private({"context_ref": ipd1.REF, "context_version": 1, "execution_id": ipd1.RUN, "state": "ready", "receipt": receipt()}), ContextStatus)
        result = decode_result(encode_private({"version": VERSION, "execution_id": ipd1.RUN, "draft_ref": ipd1.DRAFT, "result_schema": "synthetic.ipd-draft.v1", "draft": ipd1.draft().open_private()}))
        validated = schemas.validate_result(result)
        require(validated.open_private() == ipd1.draft().open_private())
        require(result.open_private() == result.open_private())
        lease = PrivateLease(lease_id=ipd1.REF, binding=binding(), context=context)
        reserve = SendReservation(lease_id=ipd1.REF, execution_id=ipd1.RUN, invocation_id=ipd1.REF, attempt_id=ipd1.ATTEMPT, runner_generation=1, selected_slot=0, deadline_at=ipd1.EXPIRY)
        observed = decode_wire(encode_private(outcome()), AttemptOutcome)
        native = NativeAttemptResult(observed, validated)
        require(native.open_private() is validated and reserve.selected_slot == 0)
        read = decode_wire(encode_private({"context_ref": ipd1.REF, "execution_id": ipd1.RUN, "draft_ref": ipd1.DRAFT}), ResultRead)
        require(read.execution_id == ipd1.RUN)
        ack = decode_wire(encode_private({"version": VERSION, "draft_ref": ipd1.DRAFT, "state": "acknowledged"}), AcknowledgedReceipt)
        deleted = decode_wire(encode_private({"context_ref": ipd1.REF, "state": "revoked"}), RevokedReceipt)
        public = [receipt_dict(item) for item in (registered, ready, status, ack, deleted)]
        require(ipd1.scan({ipd1.Surface.EXPORT: json.dumps(public), ipd1.Surface.EVENT: repr((lease, native, result, validated))}).clean)
        native.close()
        lease.close()
        refused(lease.open_private, Code.CONTEXT_LOST)
        refused(validated.open_private, Code.CONTEXT_LOST)
        require(ipd1.capability().source_kind == "synthetic")


@pytest.mark.parametrize("raw", [
    b'{"a":1,"a":2}', b'{"a":{"b":1,"b":2}}', b'{"a":NaN}',
    b'{"a":Infinity}', b'{"a":-Infinity}', b'{"a":1e999}', b'[]',
    b'null', b'{} trailing', b'```json\n{}\n```', b'\xef\xbb\xbf{}',
    b'{"a":"\\ud800"}', b'{"\\udfff":1}', b'\xff', b'',
], ids=["duplicate", "nested-duplicate", "nan", "infinity", "negative-infinity", "overflow", "array", "null", "suffix", "fence", "bom", "surrogate", "key-surrogate", "encoding", "empty"])
def test_strict_json_refuses_without_retaining_input(raw: bytes) -> None:
    refused(lambda: decode_object(raw))


def test_no_string_or_mapping_coercion_at_json_boundary() -> None:
    for raw in ('{}', {}, bytearray(b'{}')):
        refused(lambda: decode_object(raw))  # type: ignore[arg-type]


@pytest.mark.parametrize(("field", "value"), [
    ("version", VERSION + ".extra"), ("version", "prefix." + VERSION), ("version", None),
    ("profile", 1), ("namespace", ""), ("application_attempt_id", False),
    ("expires_at", "2099-01-01"), ("expires_at", "2099-01-01T00:00:00+01:00"),
    ("expires_at", "2099-02-30T00:00:00Z"), ("expires_at", "2099-01-01T00:00:00-00:00"),
    ("context_schema", []), ("context", []), ("attachments", {}), ("extra", "ignored"),
], ids=["version-suffix", "version-prefix", "version-null", "profile-type", "blank-namespace", "attempt-type", "date-only", "nonutc", "bad-date", "unknown-offset", "schema-type", "context-type", "attachments-type", "extra"])
def test_registration_shape_refusal(field: str, value: Any) -> None:
    obj = ipd1.registration().open_private()
    obj[field] = value
    refused(lambda: decode_registration(encode_private(obj)))


@pytest.mark.parametrize("field", ["version", "profile", "namespace", "application_attempt_id", "expires_at", "context_schema", "context", "attachments"])
def test_registration_requires_every_field(field: str) -> None:
    obj = ipd1.registration().open_private()
    del obj[field]
    refused(lambda: decode_registration(encode_private(obj)))


@pytest.mark.parametrize(("field", "value"), [
    ("ordinal", -1), ("ordinal", True), ("ordinal", 0.0), ("width", "1"),
    ("width", 0), ("height", False), ("decoded_bytes", 0), ("status", "available-extra"),
    ("media_type", "image/jpeg"), ("data_base64", 42), ("path", "/not-authority"),
    ("url", "https://not-authority.invalid/"), ("message_ref", ""),
], ids=["negative-ordinal", "bool-ordinal", "float-ordinal", "width-coercion", "zero-width", "bool-height", "zero-bytes", "status-suffix", "mime", "data-type", "path", "url", "empty-ref"])
def test_attachment_envelope_only_refuses_shape(field: str, value: Any) -> None:
    obj = ipd1.registration().open_private()
    obj["attachments"][0][field] = value
    refused(lambda: decode_registration(encode_private(obj)))


def test_unavailable_attachment_is_explicit_not_silently_dropped() -> None:
    context = decode_registration(ipd1.registration("missing-png").to_private_json())
    require(len(context.open_private()["attachments"]) == 2)
    for key, value in (("reason_code", "arbitrary"), ("data_base64", "not-allowed")):
        obj = context.open_private()
        obj["attachments"][1][key] = value
        refused(lambda: decode_registration(encode_private(obj)))


@pytest.mark.parametrize("version", [0, -1, True, 1.0, "1", None])
def test_start_context_version_never_coerced(version: Any) -> None:
    value = {"workflow": "synthetic-workflow", "inputs": {"private_context": {"version": VERSION, "context_ref": ipd1.REF, "context_version": version}}}
    refused(lambda: decode_wire(encode_private(value), PrivateRunStart))


@pytest.mark.parametrize("layer", ["start", "inputs", "binding"])
def test_start_all_layers_closed(layer: str) -> None:
    value: dict[str, Any] = {"workflow": "synthetic-workflow", "inputs": {"private_context": {"version": VERSION, "context_ref": ipd1.REF, "context_version": 1}}}
    target = {"start": value, "inputs": value["inputs"], "binding": value["inputs"]["private_context"]}[layer]
    target["extra"] = ipd1.canaries()[0].decode()
    refused(lambda: decode_wire(encode_private(value), PrivateRunStart))


@pytest.mark.parametrize("reference", ["", "not-a-uuid", "00000000000040008000000000000001", ipd1.REF + "suffix", True])
def test_refs_are_generated_uuid_not_payload_or_coercible(reference: Any) -> None:
    refused(lambda: decode_wire(encode_private({"context_ref": reference, "context_version": 1}), ContextRead))


@pytest.mark.parametrize("variant", ["extra", "missing-summary", "blank", "wrong-type", "duplicate", "nan"])
def test_real_schema_draft_refusal(variant: str) -> None:
    obj = ipd1.draft().open_private()
    if variant == "extra":
        obj["extra"] = True
    elif variant == "missing-summary":
        del obj["purposeSummary"]
    elif variant == "blank":
        obj["purposeSummary"] = " \n\t"
    elif variant == "wrong-type":
        obj["reply"] = 7
    raw = encode_private(obj)
    if variant == "duplicate":
        raw = raw[:-1] + b',"reply":"second"}'
    if variant == "nan":
        raw = b'{"reply":NaN,"purposeSummary":"summary"}'
    refused(lambda: ipd1.schemas().validate_draft(raw), Code.OUTPUT_INVALID)


@pytest.mark.parametrize("variant", ["schema-prefix", "schema-suffix", "context-extra", "context-missing", "nested-extra", "local-ref"])
def test_real_schema_context_and_exact_schema_identity(variant: str) -> None:
    obj = ipd1.registration().open_private()
    if variant == "schema-prefix":
        obj["context_schema"] = "prefix." + obj["context_schema"]
    elif variant == "schema-suffix":
        obj["context_schema"] += ".extra"
    elif variant == "context-extra":
        obj["context"]["extra"] = True
    elif variant == "context-missing":
        del obj["context"]["purpose"]
    elif variant == "nested-extra":
        obj["context"]["messages"][0]["extra"] = True
    else:
        obj["context"]["messages"][0]["text"] = "   "
    refused(lambda: ipd1.schemas().validate_registration(decode_registration(encode_private(obj))))


@pytest.mark.parametrize("variant", ["remote-ref", "remote-dynamic-ref", "bad-schema", "bad-dialect", "false-provenance"])
def test_schema_configuration_refuses_without_retrieval(variant: str) -> None:
    identity = ipd1.schemas().identity
    obj: dict[str, Any] = {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object"}
    if variant in {"remote-ref", "remote-dynamic-ref"}:
        obj["$ref" if variant == "remote-ref" else "$dynamicRef"] = "https://not-authority.invalid/schema"
    elif variant == "bad-schema":
        obj["type"] = 1
    elif variant == "bad-dialect":
        obj["$schema"] = "custom"
    else:
        identity = SchemaIdentity(owner="engine-tests", revision="r1", source_kind="synthetic", context_schema="application.context.v1", result_schema="application.draft.v1")
    raw = encode_private(obj)
    refused(lambda: SchemaArtifact(identity, context=raw, result=raw), Code.CONFIGURATION_INVALID)


def test_draft7_is_supported_without_claiming_source_parity() -> None:
    raw = encode_private({"$schema": "http://json-schema.org/draft-07/schema#", "type": "object", "additionalProperties": False, "properties": {"value": {"type": "integer"}}, "required": ["value"]})
    schemas = SchemaArtifact(ipd1.schemas().identity, context=raw, result=raw)
    valid = schemas.validate_draft(b'{"value":1}')
    require(valid.open_private() == {"value": 1})
    refused(lambda: schemas.validate_draft(b'{"value":"1"}'), Code.OUTPUT_INVALID)
    require(schemas.identity.source_kind == "synthetic")


@pytest.mark.parametrize("variant", ["extra", "schema-prefix", "schema-suffix", "id", "missing", "version", "draft-type"])
def test_result_envelope_and_schema_are_separate_mandatory_checks(variant: str) -> None:
    obj = {"version": VERSION, "execution_id": ipd1.RUN, "draft_ref": ipd1.DRAFT, "result_schema": "synthetic.ipd-draft.v1", "draft": ipd1.draft().open_private()}
    if variant == "extra":
        obj["extra"] = True
    elif variant == "schema-prefix":
        obj["result_schema"] = "prefix." + str(obj["result_schema"])
    elif variant == "schema-suffix":
        obj["result_schema"] += ".extra"
    elif variant == "id":
        obj["execution_id"] = "text"
    elif variant == "missing":
        del obj["draft_ref"]
    elif variant == "version":
        obj["version"] = VERSION + "extra"
    else:
        obj["draft"] = []
    refused(lambda: ipd1.schemas().validate_result(decode_result(encode_private(obj))), Code.OUTPUT_INVALID)


@pytest.mark.parametrize("state", ["registered", "bound", "running", "ready", "failed", "cancelled", "expired", "lost", "acknowledged"])
def test_status_union_happy_and_wrong_branch(state: str) -> None:
    obj: dict[str, Any] = {"context_ref": ipd1.REF, "context_version": 1, "execution_id": None if state == "registered" else ipd1.RUN, "state": state}
    if state == "ready":
        obj["receipt"] = receipt()
    elif state in {"failed", "cancelled", "expired", "lost"}:
        obj["failure"] = {"version": VERSION, "code": "cancelled", "retry_class": "terminal", "transmission": "ambiguous"}
    good = decode_wire(encode_private(obj), ContextStatus)
    require(receipt_dict(good) == obj)
    obj["failure" if state == "ready" else "receipt"] = None
    refused(lambda: decode_wire(encode_private(obj), ContextStatus))


@pytest.mark.parametrize("variant", ["registered-run", "ready-no-run", "bound-no-run", "running-no-run", "acknowledged-no-run", "wrong-receipt-run", "ready-no-receipt", "failed-no-failure", "unknown-state"])
def test_status_binding_and_required_branch(variant: str) -> None:
    obj: dict[str, Any] = {"context_ref": ipd1.REF, "context_version": 1, "execution_id": ipd1.RUN, "state": "ready", "receipt": receipt()}
    if variant == "registered-run":
        obj["state"] = "registered"
        del obj["receipt"]
    elif variant == "ready-no-run":
        obj["execution_id"] = None
    elif variant in {"bound-no-run", "running-no-run", "acknowledged-no-run"}:
        obj["state"] = variant.removesuffix("-no-run")
        obj["execution_id"] = None
        del obj["receipt"]
    elif variant == "wrong-receipt-run":
        obj["receipt"]["execution_id"] = ipd1.REF
    elif variant == "ready-no-receipt":
        del obj["receipt"]
    elif variant == "failed-no-failure":
        obj["state"] = "failed"
        del obj["receipt"]
    else:
        obj["state"] = "ready-extra"
    refused(lambda: decode_wire(encode_private(obj), ContextStatus))


def test_every_error_has_one_fixed_http_mapping_and_no_store() -> None:
    expected = [401, 403, 400, 409, 410, 503, 410, 400, 400, 400, 403, 503, 503, 503, 503, 503, 400, 504, 504, 422, 422, 422, 503, 410, 409]
    require(list(HTTP_STATUS.values()) == expected and set(HTTP_STATUS) == set(Code))
    require(dict(PRIVATE_RESPONSE_HEADERS) == {"Cache-Control": "no-store"})
    for code in Code:
        obj = {"error": {"version": VERSION, "code": code.value, "retry_class": "terminal", "transmission": "not_sent"}}
        parsed = decode_wire(encode_private(obj), ErrorResponse)
        require(receipt_dict(parsed) == obj)
    require(PrivateDraftFailure("raw private prose").code == Code.CONTEXT_INVALID)  # type: ignore[arg-type]


@pytest.mark.parametrize(("field", "value"), [("code", "unknown"), ("code", "scope_denied-extra"), ("detail", "prose"), ("retry_class", "automatic"), ("transmission", "sent"), ("call_id", None), ("attempt_id", "not-uuid"), ("next_eligible_at", "later")])
def test_failure_only_closed_applicable_fields(field: str, value: Any) -> None:
    obj = {"version": VERSION, "code": "scope_denied", "retry_class": "terminal", "transmission": "not_sent"}
    obj[field] = value
    refused(lambda: decode_wire(encode_private(obj), FailureReceipt))


@pytest.mark.parametrize(("retry", "transmission"), [("safe_pre_send", "refused"), ("safe_pre_send", "ambiguous"), ("explicit_refusal", "not_sent"), ("explicit_refusal", "complete")])
def test_failure_retry_class_never_implies_ambiguous_resend(retry: str, transmission: str) -> None:
    refused(lambda: decode_wire(encode_private({"version": VERSION, "code": "send_ambiguous", "retry_class": retry, "transmission": transmission}), FailureReceipt))


@pytest.mark.parametrize("variant", ["phase", "not-started", "http-on-complete", "known-null", "missing-number", "partial-all-null", "negative-counter", "bool-counter", "float-counter", "unknown-usage", "failure-phase"])
def test_outcome_phase_and_nullable_usage_refusals(variant: str) -> None:
    obj = outcome()
    if variant == "phase":
        obj["transmission"] = "not_sent"
    elif variant == "not-started":
        obj["request_started"] = False
    elif variant == "http-on-complete":
        obj["http_status"] = 429
    elif variant == "known-null":
        obj["usage_state"] = "known"
    elif variant == "missing-number":
        obj["usage"]["input_tokens"] = 1
    elif variant == "partial-all-null":
        obj["usage_state"] = "partial"
    elif variant == "negative-counter":
        obj["unknown_usage_fields"] = -1
    elif variant in {"bool-counter", "float-counter"}:
        obj["usage"]["input_tokens"] = True if variant == "bool-counter" else 1.0
    elif variant == "unknown-usage":
        obj["usage"]["extra"] = ipd1.canaries()[0].decode()
    else:
        obj["failure"] = {"version": VERSION, "code": "send_ambiguous", "retry_class": "terminal", "transmission": "ambiguous"}
    refused(lambda: decode_wire(encode_private(obj), AttemptOutcome))


@pytest.mark.parametrize(("phase", "transmission", "started", "status"), [("before_reserve", "not_sent", False, None), ("reserved", "ambiguous", False, None), ("reserved", "ambiguous", True, None), ("http_refused", "refused", True, 429), ("streaming", "ambiguous", True, None), ("complete", "complete", True, None)])
def test_observation_phases_do_not_treat_reserved_zero_as_not_sent(phase: str, transmission: str, started: bool, status: int | None) -> None:
    obj = {**outcome(), "phase": phase, "transmission": transmission, "request_started": started, "http_status": status}
    valid = decode_wire(encode_private(obj), AttemptOutcome)
    require(valid.transmission == transmission)
    if phase == "before_reserve":
        obj["request_started"] = True
    elif phase == "http_refused":
        obj["http_status"] = None
    else:
        obj["transmission"] = "refused"
    refused(lambda: decode_wire(encode_private(obj), AttemptOutcome))


@pytest.mark.parametrize("status", [429.0, "429", True, 500])
def test_http_refusal_status_is_closed_and_never_coerced(status: Any) -> None:
    obj = {**outcome(), "phase": "http_refused", "transmission": "refused", "request_started": True, "http_status": status}
    refused(lambda: decode_wire(encode_private(obj), AttemptOutcome))


def test_schema_registry_never_retrieves_even_if_reference_precheck_is_removed() -> None:
    import urllib.request

    from temper_ai.private_context import schema

    calls = []

    def denied(*args: Any, **kwargs: Any) -> None:
        calls.append(True)
        raise ValueError("network forbidden")

    # Exercise the actual validator retrieval path, not only a source scan.
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(schema, "_local_references", lambda value: None)
        patch.setattr(urllib.request, "urlopen", denied)
        raw = encode_private({"$schema": "https://json-schema.org/draft/2020-12/schema", "$ref": "https://synthetic.invalid/schema"})
        artifact = SchemaArtifact(ipd1.schemas().identity, context=raw, result=raw)
        refused(lambda: artifact.validate_draft(b"{}"), Code.OUTPUT_INVALID)
        require(len(calls) == 0)


def test_supported_private_representations_never_serialize_payload() -> None:
    context = decode_registration(ipd1.registration().to_private_json())
    objects = [context, ipd1.draft(), PrivateLease(lease_id=ipd1.REF, binding=binding(), context=context), NativeAttemptResult(decode_wire(encode_private(outcome()), AttemptOutcome), ipd1.draft())]
    for obj in objects:
        require(ipd1.scan({ipd1.Surface.EXPORT: repr(obj) + str(obj)}).clean)
        for encode in (json.dumps, pickle.dumps, copy.copy, copy.deepcopy, vars, dataclasses.asdict):
            denied = False
            try:
                encode(obj)
            except (TypeError, ValueError):
                denied = True
            require(denied)
    independent = context.open_private()
    independent["context"]["purpose"] = "modified"
    require(context.open_private() != independent)
    context.close()
    refused(context.open_private, Code.CONTEXT_LOST)
    refused(lambda: receipt_dict(ipd1.draft()))  # type: ignore[arg-type]


def test_execution_context_optional_type_seam_is_not_a_payload_holder() -> None:
    context = ExecutionContext(run_id=ipd1.RUN, workflow_name="synthetic", node_path="draft", agent_name="synthetic", event_recorder=None, tool_executor=None)
    require(context.private_context is None)
    run = RunPrincipal(execution_id=ipd1.RUN, runner_generation=1, provenance="verified_private_worker_key")
    seam = PrivateExecution(None, run)  # type: ignore[arg-type]
    current = dataclasses.replace(context, private_context=seam)
    require(dataclasses.replace(current).private_context is seam and "private_context" not in repr(current))
    require("PrivateLease" not in str(ExecutionContext.__annotations__["private_context"]))
    require(not hasattr(seam, "open_private"))
    refused(lambda: decode_wire(encode_private({"principal_id": "p", "namespace": "scope-1", "profile": "synthetic", "provenance": "named"}), CallerPrincipal))
    refused(lambda: decode_wire(encode_private({"execution_id": ipd1.RUN, "runner_generation": 0, "provenance": "verified_private_worker_key"}), RunPrincipal))


def test_media_capability_has_no_production_defaults() -> None:
    good = ipd1.capability()
    require(good.max_images == 2 and good.source_kind == "synthetic")
    for key in MediaCapability.model_fields:
        obj = good.model_dump()
        del obj[key]
        refused(lambda: decode_wire(encode_private(obj), MediaCapability))
