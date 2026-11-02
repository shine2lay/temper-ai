# Private drafting contracts (inert v1)

`temper_ai.private_context` defines `temper.private-draft.v1`. It does **not**
register a route, caller, profile, worker key, provider, agent or workflow. It
performs no dispatch or private call. Ordinary named-token/image behavior is
unchanged. The optional `ExecutionContext.private_context` field is a type-only
service/principal seam, default `None`; never put a lease or payload there.

## Consumer imports

- `wire`: `decode_registration`, `RegisterContext`; `decode_result`,
  `PrivateResult`; `decode_wire`; closed metadata types `ContextReceipt`,
  `PrivateContextDescriptor`, `PrivateRunInputs`, `PrivateRunStart`, `ContextRead`,
  `ContextStatus`, `ResultRead`, `DraftReceipt`, `FailureReceipt`, `ErrorResponse`,
  `AcknowledgedReceipt`, `RevokedReceipt`; `receipt_dict`.
- `errors`: `PrivateDraftErrorCode`, `PrivateDraftFailure`, `HTTP_STATUS`,
  `PRIVATE_RESPONSE_HEADERS` (`Cache-Control: no-store`).
- `schema`: `SchemaIdentity`, `SchemaArtifact`, `ValidatedDraft`.
- `contracts`: `CallerPrincipal`, `RunPrincipal`, `PrivateBinding`,
  `PrivateLease`, `SendReservation`, `AttemptOutcome`, `NullableUsage`,
  `PrivateContextService`, `PrivateExecution`, `NativeAttempt`,
  `NativeAttemptResult`, `MediaCapability`, `PrivateMedia`, `ReleaseDisposition`.

All untrusted envelopes enter through the strict decoders: UTF-8 JSON objects,
no duplicate keys, nonfinite numbers, extra fields or coercion. Receipts are
closed metadata only. Use `receipt_dict` for applicable optional fields; a
status retains its explicitly nullable execution ID. A fixed error contains
only a closed code; decoder errors do not retain parser/validation chains.
Do not expose Pydantic/JSON Schema exceptions directly. Direct trusted model
constructors are not the ingress API. Never use `model_construct`/unchecked
`model_copy(update=...)` to admit untrusted input.

Registration/result holders have no dataclass/Pydantic/dict serialization
surface. `repr`, generic JSON, copy/deepcopy and pickle cannot emit their
content. Only `open_private()` (fresh dictionary) and `to_private_json()` (bytes)
expose content, **inside** an authorized private boundary. `close()` drops this
holder's reference. This is not hostile-Python memory isolation, secure erasure,
provider-retention certification or revocation of copies already delivered.
Never call a private accessor in a logger, assertion, event or checkpoint.

## Schema ownership

The application owns and generates its context/result JSON Schemas from its
source types. Supply those artifacts as bytes to
`SchemaArtifact(identity, context=..., result=...)`; the engine loads no schema
files/URLs and contains no application enum lists. Explicit Draft 7 and 2020-12
are supported, with bundled local references only. Use `validate_registration`,
`validate_draft` and `validate_result` in addition to envelope validation. The
service must recheck its **current** source schema at publication.

The profile owner must verify artifact provenance/revision: a `source_generated`
label is not proof of origin. `source_kind=synthetic` requires `synthetic.*`
schema identifiers. Engine test schemas are not application parity. Joined
integration must validate against the actual source-generated artifact.

## Service/transport semantics

The synchronous `PrivateContextService` protocol freezes:

```
register(caller, context) -> ContextReceipt
bind(caller, context_ref, context_version, execution_id, profile_revision) -> PrivateBinding
status(caller, context) -> ContextStatus
result(caller, read) -> PrivateResult
ack(caller, read) -> AcknowledgedReceipt
delete(caller, context_ref) -> RevokedReceipt
resolve(run_principal, execution_id, running_attempt, node_path, use="draft") -> PrivateLease
reserve_send(lease, invocation_id, attempt_id, selected_slot) -> SendReservation
finish_attempt(reservation, outcome_metadata) -> None
publish(lease, invocation_id, validated_result) -> DraftReceipt
release(lease, disposition) -> None
```

Principal constructors are not authority. The implementation must authenticate
named-key provenance and exact caller/namespace/profile permission before
private decoding, and verify a scoped private worker key before worker access.
Ref possession, shared tokens and fabricated principal objects grant nothing.

Binding metadata has no content/digest. Runner generation is the current
monotonic running-attempt number; application expiry and existing run deadline
are separate. Resolve/reserve/finish/publish require atomic current-generation,
scope, revocation and deadline checks. A durable reservation is possible-send
evidence even if `request_started` is false. Uncertain storage forbids sending.
A complete pre-stream refusal must be durably finished before another attempt.
No post-reservation ambiguous resend or post-cancel publication. Metadata alone
never enforces these rules; the service implementation and its tests must.

Result reads are repeatable until acknowledgement/expiry. Acknowledgement,
delete, cancellation and expiry independently remove private buffers while
retaining safe metadata. Lost buffers produce context/result loss, never disk
fallback or hidden regeneration. App persistence precedes acknowledgement;
engine deletion cannot retract application storage or provider delivery.

`NativeAttempt.send_once(request, *, reservation, control, capability)` uses the
existing `SingleSendControl` for policy/cancel/deadline and returns an opaque
`NativeAttemptResult`. Exactly one request; no SDK retry/redirect/fallback/tool
or model-stream export. Outcomes distinguish before-reserve, reserved,
pre-stream HTTP refusal, partial stream and complete. Unknown usage stays null;
unknown field **counts**, never values, may be reported. Old named-token mode
remains at most one send.

`PrivateMedia.validate_attachments` and `validate_final_body` are ports only.
The implementation must extend the existing PNG validator, retaining every
selected association and measuring the final OAuth-shaped request. Envelope
validation does not prove valid PNG/base64/dimensions/association or size.
`MediaCapability` has explicit source/revision and required limits with **no
production defaults**. No engine URL/file retrieval, drop/downscale or collage.

## Shared synthetic IPD-1 corpus

`tests/test_private_context/fixtures/ipd1.json` supplies M1–M8 good/refusal pairs;
`tests/test_private_context/ipd1.py` supplies synthetic builders, mock schemas,
SYNTHETIC-P2 capability, scanner and fixed reports. Each pair changes one arrange
selector. Selectors/expected counts describe later auth/media/transport/lifecycle
proofs, not simulated claims that those paths already work.

Contract tests combine envelopes/schema/private holders/metadata first, then
refusal twins. Scanner controls inject separate text, draft, key, provider,
image/base64 markers into generic surfaces, including allowed-label suffixes
and nested values. Failure reports contain only fixed labels/codes/booleans/
counts. A deliberate leak proves the `-vv` terminal/JUnit detector works; real
contract failures never print private fixture bodies. Guard mutations run in
scratch import trees and must fail named assertions, not crash in setup.

These tests establish inert contract behavior only, not private end-to-end
custody, real authorization, source-schema parity or production media support.
