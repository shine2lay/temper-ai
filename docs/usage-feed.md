# Usage calls v1: closed numeric items

`temper_ai.observability.usage_feed.to_item(row) -> dict` is a pure serializer of
an **already materialized** `UsageObservation`/`UsageCallRow`, or a mapping with
the same column names. It does not load events, query a database, inspect the
runtime, price usage or perform I/O. Caller must not pass expired/lazy ORM rows.
The reader is separate work; this module exposes no route and activates nothing.

The item is an observation, not a quote, bill, coverage claim or exclusive-class
proof. Unknown is JSON `null`, never a made-up zero. A revision can faithfully
report a **lower** count than an earlier revision; no maxima or upward clamp.

## Item fields (exactly these twenty; no `seq`)

| Field | Type / source |
| --- | --- |
| `event_id` | native row event identifier, string or null after defensive validation |
| `revision` | integer 0..`2**53-1`; own identity is `(event_id, revision)` within the reader's instance |
| `call_key` | `pi:<llm_call_id>` for every Pi row; `svc:<event_id>` for a service start; `svc:<started_event_id>` for an exactly linked service end; otherwise null with `call-unlinked` |
| `origin` | `live` or `reconciled` |
| `execution_id` | native execution identifier or null |
| `agent_event_id` | row `parent_id`, or null; no lookup or attribution |
| `event` | `call_started`, `call_completed`, `call_failed`, mapped from the three `llm.call.*` row types |
| `call_kind` | `model`, `compaction` or null |
| `llm_call_id` | native Pi call identifier, or null; never synthesized from order |
| `started_event_id` | exact native start link from the row, or null; serializer neither searches nor invents links |
| `provider`, `model` | independently observed native labels or null; never inherited by this module |
| `occurred_at` | native row `occurred_at`, UTC `YYYY-MM-DDTHH:MM:SS.mmmZ`; truncate sub-millisecond precision, never use `event_at`, DB time, serialization time or a backfill clock |
| `occurrence_basis` | `call_end` or `call_start` from the producer; `call_start_unended` only for a start carrying the explicit closed row code `call-unended` |
| `observed_tokens` | exactly `{prompt, completion, total, cache_read, cache_write}`, each safe nonnegative integer or null, with the Pi rules below |
| `token_convention` | `service-inclusive-prompt` only for the Anthropic service path; otherwise `service-unverified`; Pi is `pi-unverified` (see evidence below) |
| `exclusive_tokens` | exactly `{input, output, cache_read, cache_write}` on the proven Anthropic service path, otherwise null |
| `legacy_cost` | exactly `{text, source, basis}`; `text` is Python `repr()` of the stored finite nonnegative **float**, or null; `source` is `pi_estimate`, `service` or null; `basis` is always `unproven` |
| `lost_attempts` | the row's safe nonnegative count or null; not reconstructed into usage |
| `faults` | sorted, duplicate-free array of closed codes below; unknown input codes are dropped and marked `faults-invalid` |

Revision rows keep their native call key. Pi start/end share `pi:<id>`; an exactly
linked service start/end share `svc:<start-id>`. The writer, not the serializer,
proves the start link. There is no item cursor, sequence, project, task,
initiative, root, payer or scope. The reader supplies instance and cursor outside
the item; consumers must not build a cursor from a call key or event identifier.

Native timestamps from SQLite/legacy timezone-naive columns mean UTC, matching
`temper_ai.shared.clock.as_utc`. A missing/invalid native occurrence timestamp
is rejected rather than replaced with the recording time. The landed SQL basis
stays `call_start`/`call_end` (16 characters; no schema change). The reconciler
writes an unended start as a **new start-row revision** with `call-unended`, null
usage/cost, native start time and unchanged call key. Only a start plus that
explicit code maps to wire `call_start_unended`. The code stays in `faults`.
A non-start carrying the code keeps its stored basis. Revision/origin alone,
a missing end or a time comparison never establish an unended start. The
wire-only basis spelling is not accepted as a stored-row input. Producer
linkability checks remain the reconciler's job, not a serializer lookup.

## Service token semantics

`temper_ai/llm/models.py:18-24` says cache classes are **inside** prompt, not
additional prompt. For Anthropic, `temper_ai/llm/providers/anthropic.py:879-896`
constructs `P = usage.input_tokens + cache_read + cache_write`, sets completion
from `usage.output_tokens`, and sets total to `P + completion`.

Only when the provider is exactly `anthropic` and all four component observations
are valid: `input = P - cache_read - cache_write`, `output = completion`, and
both cache classes are copied. If input would be negative, exclusive classes are
null with `token-overlap` and `exclusive-unavailable`; never clamp to zero.
A missing/invalid component also makes exclusive classes unavailable.

Example: P150, output10, read30, write20 -> input100, output10, read30, write20.
The observed total160 is a cross-check only: never a fifth class, never split,
never added to the four-class sum. Total-only160 does not establish any class.

OpenAI's `providers/openai.py:192-194,249-252` records native prompt/completion/
total; Codex's `providers/openai_codex.py:303-313` takes Responses counts (and
can derive a missing total); Gemini's `providers/gemini.py:257-258` has legacy
zero defaults. Those observations are retained as reported by the service,
**not promoted to proved exclusive classes or provider-presence evidence**.
All other providers get `exclusive_tokens: null`, `service-unverified` and
`exclusive-unavailable`. These source locations are under `temper_ai/llm/`.

A failed call with usage keeps it; without any valid observed token it has all
nulls and `usage-absent`. A compaction is its own usage record. `tokensBefore`
and `estimatedTokensAfter` are not usage; they are never read, and compaction
never borrows a provider or model. Pi compaction can aggregate two final
summary calls and miss failed attempts: it is not one priced leaf call.

## Pi evidence and conservative convention

Read-only audit of the installed pin **0.87.1**, rooted at
`~/.local/share/temper/pi-runtime/pi-0.87.1-rg15.2.0-fd10.5.0/pi/`.
`local/pi/pi-box.json` pins `pi_version: 0.87.1`; no runtime invocation/change
was used. The deployment record identifies this as the only runtime since
2026-10-05, covering the backfill window; **rows do not store version or API**.

Relative to that runtime's `pi/`:

| File:line | What the source actually proves |
| --- | --- |
| `node_modules/@earendil-works/pi-ai/package.json` | package `@earendil-works/pi-ai` version `0.87.1` |
| `node_modules/@earendil-works/pi-ai/dist/api/anthropic-messages.js:346-353` | all counters initialize to 0 before a report |
| `node_modules/@earendil-works/pi-ai/dist/api/anthropic-messages.js:416-424` | four distinct fields from `input_tokens`, `output_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens`, with `|| 0`; total is their derived sum |
| `node_modules/@earendil-works/pi-ai/dist/api/anthropic-messages.js:575-599` | non-null deltas replace snapshots, including positive -> 0; proxy divergence is explicitly noted; total is recomputed |
| `dist/core/compaction/compaction.js:91-104` | all-zero or error/aborted usage is not valid context-usage evidence |
| `dist/core/compaction/compaction.js:475-483,498-509,550-554,722-740` | compaction has final-attempt and split-summary aggregation, with no provider/API/model identity |

Audited SHA-256: adapter
`97de17d406264322ff7927fa0c20e1c61b46386b5e14f9c6e0012599c01664f7`;
compaction `871f81769ef67a78c63cfc674e09f13097899effe4677f156a3613878c387640`.
See [Pi count evidence and upgrade procedure](pi-usage-counts.md) for the
provider/proxy registrations and the separate legacy aggregate contract.

This is **not enough to claim `pi-exclusive:<package>@<version>` for a row**:
multiple proxy providers use the same API, rows have no API/version, and
compaction lacks even provider identity. This serializer therefore returns
`pi-unverified`, null exclusive classes and `pi-convention-unverified` for
**every Pi row**. There is no speculative proof table, zero allowlist, current
runtime lookup or promotion from untrusted extra fields. Positive Pi input100
stays observed prompt100: caches are never subtracted from it. Adding a proven
convention would need its own provenance change and Data's confirmation. Data
confirmed this all-Pi interpretation: observed100/output20/read80/write10 with
total210 retains observed210 and still gets null exclusive classes, even when
the model name is recognizable. A matching sum is not convention provenance.

### Pi zero, unknown and total rules (old rows too)

1. Validate counts first: true integers only, not booleans, fractions, negatives,
   strings, NaN/Infinity or values above `2**53-1`.
2. All four raw component classes equal integer0: all five observations null,
   `usage-absent`, even if a positive total was stored.
3. In every other case **any** component0 -> null, `pi-zero-or-absent`. There is
   no class proven to mean a known zero for 0.87.1 (`|| 0`, proxy sharing, deltas).
4. An already-null component stays null with `pi-count-unreported` (landed #129
   writes these nulls). Invalid numbers additionally get their field fault.
5. Retain an observed total only if all four validated classes are known safe
   integers and the reported total equals their sum. Otherwise total is null
   with `pi-total-unverified`. Never sum only known positives or invent a total.
   Thus old total200 + one ambiguous0 and new mismatched totals are both null.
6. If every observation is null, also mark `usage-absent`. Partial positive
   observations remain observations, not complete usage or a price basis.

## Closed faults

All writer faults pass through **except `ordering-deferred`**, which is internal
operational evidence, not an external v1 fault or a coverage claim.

| Code(s) | Meaning |
| --- | --- |
| `prompt-invalid`, `completion-invalid`, `total-invalid`, `cache-read-invalid`, `cache-write-invalid` | producer or defensive check rejected the number; retain null, never coerce |
| `provider-invalid`, `model-invalid` | bad native-label syntax/type/length or a forbidden path/URI/userinfo label |
| `provider-unproven`, `model-unproven` | label absent; no inherited label |
| `kind-invalid`, `id-invalid` | optional kind or identifier rejected |
| `cost-invalid`, `lost-invalid`, `link-unproven`, `usage-missing` | original writer findings, not reinterpreted or discarded |
| `faults-invalid` | malformed/oversized fault-code input or a code outside the writer allowlist; no input echoed |
| `call-unlinked` | no safe native Pi id or exact service start identity |
| `call-unended` | explicit producer marker of an exactly linkable unended start revision; passed through, and only start + code changes the wire occurrence basis |
| `exclusive-unavailable` | service observations cannot establish all exclusive classes |
| `token-overlap` | subtracting observed service caches would make fresh input negative |
| `pi-convention-unverified` | Pi row cannot establish exclusive classes from pinned API/provider provenance |
| `pi-zero-or-absent` | at least one Pi component0 is ambiguous, not known0 |
| `pi-count-unreported` | at least one Pi component was null |
| `pi-total-unverified` | Pi total missing, inconsistent or not supported by all four known classes |
| `usage-absent` | no usable usage observation (including all-zero Pi report) |
| `legacy-cost-invalid` | stored cost not a finite nonnegative float, or its source not closed |

## Defensive bounds and refusal

IDs/provider/model: 1..128 ASCII characters matching
`^[A-Za-z0-9._:/@+-]+$`, otherwise null plus the field fault. Native labels
also retain the writer's rejection of filesystem roots, URI schemes and userinfo.
A character allowlist cannot prove an arbitrary accepted native label is public
or non-secret; there is **no DLP guarantee**. Arbitrary event text, unknown
columns and fault strings are never copied or stringified.

All integer observations, lost counts and revisions are safe nonnegative
integers. The final JSON check uses `allow_nan=False`, ASCII encoding, and a
**2048-byte maximum**, including ordinary `json.dumps` spaces. Invalid required
event/origin/token-source/occurrence-basis/revision/time or an item over the
bound raises a fixed `ValueError` (no source value or partial item). Optional
bad fields become null and named faults; no truncation of identifiers, silent
field removal or clamping is allowed. A caller must fail closed on refusal;
never skip a refused row and advance its cursor past it.

## Verification boundaries

`tests/test_observability/test_usage_feed.py` begins with one combined happy
path, then Data's fixed cases, Pi zero/total rules, every native call-key path,
faithful lower revisions/native timestamps, fault pass-through/filtering,
canary and encoding bounds, and deterministic in-memory guard-removal controls.

The **later** #129-to-#125 SQL compatibility check uses fixed usage-only inputs
through the landed `PiEventMapper`, turn `ChunkSink` and `_record_end`, landed
`usage_rows.extract`/`write_or_queue_row`, then this serializer, on **throwaway
in-memory SQLite**. It checks SQL NULL rather than invented zero, separate
unchanged legacy numeric cost, native faults/call identity, compaction and a
higher revision with lower observations. It does not claim #129 previously ran
this check, and uses no provider request, model payload, production run or live
DB. This integration check does not replace the pure fixed cases.

Data case4 (prices/rates/quotes) belongs to the consumer, not the serializer.
The feed proves no rate, 3/15 default, cache tier, subscription coverage, free
usage, complete interval, occurrence count, task/project allocation or bill.
Legacy `0.30000000000000004` stays exactly that text and **unproven**, with no
rounding, decimal reconstruction or pricing fallback.
