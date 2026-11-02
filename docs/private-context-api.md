# Private context HTTP and process boundary

This is **dormant transport source**, not a configured private drafting service.
Registering its routes grants no access. No service, namespace assignments,
profile, worker credential, workflow or provider is installed by these modules.
An absent service or authority refuses; it never creates fake custody.

## Composition and ownership

- `private_context/contracts.py`, `wire.py`, `schema.py`: v1 records, strict
  decoders, opaque content holders and service ports.
- `private_context/authority.py`: canonical configured-profile and current-run
  authority records/protocol; these are assertions, not credentials.
- `private_context/composition.py`: fenced lookup, queue/lifecycle and worker
  handle protocols. `QueueBound = Callable[[Session, str], None]` receives the
  allocated execution ID, not a provisional binding.
- `api/private_authority_adapter.py`: verifies request-issued object provenance,
  actual run metadata, current worker-key scope and active run state. Its configured
  authority readers and independent trusted runner-claim reader have no defaults.
- `private_context/runtime.py`: explicit composition bundle. The production join
  must supply the canonical configured authority readers, concrete service,
  fenced composition and post-commit dispatcher. This is not another registry.

The service owns custody, locking, generation, invocation/send state and opaque
handle resolution. The transport does not guess service tables or infer generation
from `WorkflowRun.attempts`. Tests using recording ports prove orchestration only;
they do not prove concrete service atomicity, durability or runner provenance.

## Application HTTP

The registered closed namespace is `/api/private-contexts`:

| Method and path | Strict request | Result |
| --- | --- | --- |
| POST root | `RegisterContext` | `ContextReceipt` |
| POST `/status` | `ContextRead` | `ContextStatus` |
| POST `/result` | `ResultRead` | private result bytes |
| POST `/ack` | `ResultRead` | `AcknowledgedReceipt` |
| DELETE `/{context_ref}` | canonical generated reference; no query | `RevokedReceipt` |

Only one unambiguous `Authorization: Bearer ...` **or** `X-Temper-Token` header is
accepted. The existing named-key source must verify its principal. Shared tokens,
Origin, loopback, query/cookie credentials, fabricated Caller/principal records,
start-run keys, GitHub keys and reference possession are not private authority.
These rules apply with the ordinary guard off, record or enforce.

Credential and configured-profile preflight precede body receive. Registration
then checks the requested exact namespace/profile before its private schema is
interpreted. Reads use authorized reference-only metadata lookup: their requests
cannot supply a namespace/profile to bypass ownership. The authority adapter
rechecks credential provenance inside the service's transaction.

Bodies are JSON-only, in memory, through the strict private decoder. No multipart
parser or default FastAPI body validation handles them. Unknown fields, duplicate
JSON keys, invalid values, methods and paths produce fixed refusal receipts.
Errors never include a request field, URL, header, provider prose or traceback.
Every response uses `Cache-Control: no-store` and a newly generated request ID;
a client-supplied correlation value is not reflected. Only the result endpoint
returns application draft content. Neither refs nor receipt records are keys.

The current service contract's `register` receipt does not distinguish new from
identical registration; this transport returns HTTP 200, without inventing a
"newly created" assertion. It does not alter the public v1 receipt schema.

## Normal start and lifecycle

All starts enter `runner/private_context_binding.submit_private_start` before
ordinary persistence if a private input descriptor or configured private workflow
is present. The closed start contains only the workflow and versioned context
reference. Workspace, graph/node overrides, payload fields and extra inputs are
refused. Generic HTTP start must inspect its metadata-only discriminator; the
private variant is then strictly decoded, never passed to reflective validation.
MCP/internal starts reuse the same `_start_run` preparation.

The caller opens the normal session. Under the service fence, composition
rechecks authority and chooses exact retry or new admission:

1. Exact authorized retry returns the original binding, `created=False`, without
   invoking the queue callback or dispatching again.
2. New admission invokes the queue callback exactly once with that same session
   and allocated ID. The callback calls the existing `queue_run_in`, never commits.
3. The service independently verifies the staged run and constructs authoritative
   binding/generation/deadline. Any failure rolls back the transaction.
4. Only after the outer commit does the prepared dispatcher run.

Direct queue calls require this scoped callback permission. The queue checks both
before locking and against the refreshed locked row; an existing private marker
cannot be removed by renaming/requeueing. Direct legacy subprocess, in-process,
checkpoint and CLI executors refuse private runs; the concrete private executor
is a separate join, not a fallback to ordinary tools or model execution.

Resume retains the same execution and all service invocation/send/loss state;
it rotates the independent generation and revokes the old key inside the fence.
Cancel revokes credentials before any subsequent payload access. Existing private
bindings cannot fork, including before reservation. A fresh separately authorized
context/start is distinct. Private lifecycle overrides are refused before effects.

## Worker process transport

`run_tokens.PRIVATE_CONTEXT` uses an explicit `run_private_keys` table mapping,
not the start-run table fallback. The additive table contains only a credential
hash and exact owner/namespace/profile/revisions/workflow/node/use/execution/
generation/deadline scope. `database/private_worker_schema.py` exposes its isolated
additive migration; normal schema creation includes the model. HTTP operations do
not create missing tables; absence is unavailable for private operations only.

`api/private_worker_keys.open_private_key` asks the concrete composition to verify
independent runner provenance and current authority under its fence. Its key
staging callback must use the same session; it does not commit. The raw key becomes
process-held only after successful outer commit. No default runner verifier exists.
Cleanup forgets the held key and conditionally retires only its own hash, never a
successor's credential. Lifecycle revocation uses the shared fenced transaction.

`PrivateWorkerClient` holds no environment/argv/script/tool credential. It obtains
the process-held key from the existing run-token machinery for each request.
Redirects, automatic retries and environment-derived HTTP credentials are disabled.
Its only route powers are exact POST paths under `/api/private-worker`:
`acquire`, `validate`, `reserve`, `finish`, `publish`, `release`.

The server verifies the key plus current generation/scope before receiving a body.
Each lease/reservation handle is resolved by the authoritative service, never
reconstructed from submitted metadata. Transport failures expose fixed codes only.
A worker key cannot register/read application results or call ordinary API routes,
even with the ordinary guard disabled. These process credentials are filtered
from script/agent environments by name and value shape, alongside existing keys.

## Remaining production join

The integration owner must connect real configured authority, shared fence,
independent generation/current runner claim, concrete custody, private executor
and lifecycle dispatch. It must prove actual binding+queue and key+generation
atomicity, cancellation races, process-loss behavior and runtime leak isolation.
No recording-port test substitutes for those checks or enables a profile.
