# Private context custody service (inactive)

`temper_ai.private_context.service.PrivateContextService` implements the wire-v1
service ports. `composition_service.PrivateContextComposition(service)` implements
C2's composition ports. Neither is installed automatically. Imports create no
engine, profile, key, router, timer or provider. The application supplies:

- `store.MetadataStore(engine)` over its explicit supported SQLite/PostgreSQL DB;
- an actual `authority.PrivateAuthority` adapter, not constructed principal labels;
- configured `ProfileAuthority`/`RunAuthority` and the app-owned `SchemaArtifact`;
- optionally one explicitly shared `mailbox.VolatileMailbox` and an aware clock.

No successful default adapter exists. Missing adapter/config/claim/fence refuses
with fixed `context_unavailable`, `unauthenticated` or `scope_denied` codes. Generic
guard settings are not consulted. IPD-1 fixtures are synthetic tests, not app parity.

## Storage and migration

Call `migration.install_metadata(engine)` explicitly at composition time. It uses
the repository's table-scoped `create_all` pattern, creates only five additive
metadata tables and installs a conflict-safe singleton fence row. Existing rows
and ordinary run schemas are untouched. There is no destructive down migration.
Import alone does not install anything. Tests never use the live database.

Durable rows contain context IDs/versions, owner/namespace/profile/schema/workflow
bindings, expiry/deadline, generation, invocation/attempt IDs, selected slot,
closed outcome counters/codes and fixed refusal metadata. No content, images,
draft, content hash or provider text is durable. An `application_attempt_id` is an
opaque application idempotency identifier, never a place to put content.

Registered context, issued lease copies and results are owned volatile buffers.
Equality of registration retries is checked only while the buffer exists. A fresh
process cannot recover private content from metadata. Lost pre-send context is
`context_lost`; possible-send evidence is `send_ambiguous`; missing completed draft
is `result_lost`. Status returns those honest states; there is no implicit fetch,
regeneration, disk vault or reconstructed opaque handle.

## Ordering and transaction ownership

Every operation takes `MetadataStore.fence_in(session)` **before** authority/run
row locks or the mailbox mutex. SQLite UPDATE and PostgreSQL UPDATE/RETURNING
retain that fence until transaction end. All profile/key/run-generation/revocation
writers must participate in the same order. An adapter unable to fence its actual
source, including a separate store, must refuse; a read followed by unrelated
commit is not authorization. The singleton orders private operations only; it is
not a lock on ordinary workflow execution.

Standalone service methods own a transaction. Authenticated refusals after a
verified profile append exactly one closed refusal row when storage is available.
Unauthenticated/unavailable infrastructure cannot fabricate a durable refusal.
Unexpected transaction failure returns fixed `context_unavailable`, drops volatile
custody and never returns a reservation as permission to send.

Composition methods ending `_in` use the supplied caller-owned Session. They
never commit, roll back, dispatch, or make a key usable. The outer owner **must
roll back on every refusal**, including earlier unrelated writes. After that
rollback it may call `record_binding_refusal` with the authenticated caller and
closed code. It must not catch a refusal and commit pending callback writes.

`bind_and_queue_in` checks all pre-run facts under the fence, selects exact retry
without calling the queue, or calls `QueueBound(session, execution_id)` once. It
then independently verifies the actual staged run via `authority.binding_in` and
constructs the final binding. There is no provisional fabricated run authority.
Dispatch and usable key publication occur only after successful outer commit.

`worker_bootstrap_in` requires an independent real runner claim via
`authority.bootstrap_in`, verifies current binding, calls the trusted key writer
and verifies again. An execution ID is not a credential. Worker handle methods
resolve server-held objects and re-verify each current request's provenance;
they do not rebuild leases/reservations from request fields.

`lifecycle_in` refuses fork before callback. C1 owns canonical private generation
and revocation in `PrivateContextRow`, never `WorkflowRun.attempts` or a second
registry. It authenticates/prevalidates, freezes the prior state, stages exactly
old generation + 1 for resume (revocation for cancel), and passes that resulting
binding to C2's callback under the same fence/Session. C2 must check the caller's
exact expected generation under that fence, preserve scope/deadlines, and stage
normal run/queue changes plus old-key revocation; no commit or dispatch.

C1 then refreshes metadata and independently revalidates the actual configured
authority, normal run and provenance. Its own new metadata is not authentication.
All other context/invocation/reservation/terminal/loss history stays unchanged.
Missing/inconsistent authority refuses; cancellation validation intentionally
permits revoked state. Old worker handles are invalidated; cancel also drops
buffers without acquiring a payload lease. Durable failure rolls back all effects
together, but irreversible volatile cleanup can expose honest loss after rollback.
There is no promise to restore already-dropped private content.

**Remaining E obligation:** join C2's actual profile/run readers and independent
credential/runner provenance with canonical C1 metadata in these transactions,
and prove normal queue/key composition. No external private generation writer is
needed. Synthetic service tests alone do not demonstrate a cross-store fence,
actual HTTP/key composition or live runner behavior. No endpoint/profile/key is
activated here.

## Sending and private result custody

Reserve durably **before** a possible send. Repeating a reserve never grants a
second send. One invocation belongs to an execution. A next attempt of that same
invocation requires a durable explicit pre-stream HTTP refusal (401/403/429/529).
401/403/429 do not permit reuse of the refused slot. Reserved, streaming,
ambiguous and completed states prohibit a fresh send, even if a caller says no
request started. Outcome metadata is closed/revalidated before persistence.

Publication revalidates the supplied draft against the configured schema and
requires a completed invocation plus exact current scope/generation/deadlines.
Publication/cancellation, replacement/resolution and result read/ack use the same
fence. Pre-send replacement creates a new reference/version, revokes the old one,
and never clears any existing invocation. Once any send was reserved, changing
context cannot create another invocation or regenerate a lost result.

Private reads return independent copies repeatedly until ack/expiry/revocation.
The app must commit its result **before** ack; the store cannot enforce an
external application's commit. Ack closes owned buffers. Already delivered
copies cannot be retracted. `expire()` and `close()` are explicit lifecycle hooks;
this change schedules no sweep and starts no service.

## Verification boundary

Focused tests live in `tests/test_private_context/test_scope.py`,
`test_lifecycle.py`, `test_replay.py` and `test_service_composition.py`, with real
SQLite and the existing throwaway PostgreSQL tier. They inject explicit fake
authenticated identities/config and a fixed clock, never successful production
defaults. Ordered concurrent schedules exercise both race orders; verbose output
and JUnit artifacts are scanned with the shared synthetic canary scanner. Exact
executed counts and gate receipts belong in the task handoff, not this document.

Limits: volatile process custody, not high availability or a content vault; no
secure erasure, backup erasure, provider retraction or hostile-process isolation
claim. The service cannot retract bytes already sent to a permitted caller.
