# `single_call`: a dormant, fixed-input, send-once primitive

No checked-in workflow uses this type; one dormant agent and stage do
(configs/architecture/agents/context_profile_candidate.yaml and
configs/architecture/stages/context_profile_candidate.yaml), and nothing runs them.
This is **not** T1/T2 admission, permission
to call a provider, switch-on, or a process sandbox. The flag defaults to off;
ordinary agents/providers keep their existing request, retries and fallback.

## Contract

The agent config has only `name`, `type: single_call`, optional `description`, an
**explicit** `provider` and `model`, and the closed `single_call` mapping. No tools,
provider defaults/overrides, memory, fallback, templates, checkpoints or repair.
A node's `input_data` is ignored by this agent, but the graph may persist it before
execution: the calling workflow must supply **IDs/paths/digests only**, never
prompt, answer, held-out text or a secret.

Required fixed fields:

- `prompt_path` (absolute), `prompt_sha256`, `prompt_bytes` (UTF-8 file bytes).
- `output_root`: pre-existing, non-symlink, owned by the box effective UID, exactly
  0700. The agent never creates it. Its provisioner **must fsync its parent** before
  the first claim. A missing/unknown expected root is UNKNOWN exposure to a later
  aggregator, not a new experiment or unused slot.
- `slot`, `family`, `route`, `auth_mode`; `max_tokens`, `deadline_s: 900`,
  `cost_cap_usd`, `output_bound_mode`.
- `pricing_path` and `pricing_sha256`; `experiment_id`, `binding_id`, and the
  `source_sha256`, `config_sha256`, `packet_sha256` digests. Identity/config/source
  fields are copied, never inferred from a public checkout or another attempt.
- Family A only: a nonempty named `token`. Optional A parameters are `temperature`,
  `thinking`, `thinking_budget` (positive, less than `max_tokens`) or `effort`.
  Do not combine `thinking` and `thinking_budget`.

| Slots | Registry key | Actual transport | Model | Bound |
|---|---|---|---|---|
| A1–A3 | `anthropic` | `anthropic-oauth-named-token`, `oauth` | `claude-opus-5-5` | `request_limit` |
| B1–B3 | `openai` | `openai-codex-oauth`, `oauth` | `gpt-6.1-sol` | `documented_max` |

`openai_codex` is a family/transport description, **not** a registry alias. A needs
a named subscription token, never an unnamed pool. B has one credential and
refuses any token field. API-key OpenAI, CLI providers and other implementations
refuse `single_send=True` before sending, including subclass method overrides
unless that concrete class explicitly declares strict support. This is not
protection against monkey-patching or hostile code in the same interpreter.

### Pinned pricing and maximum

Pricing is a duplicate-key-free JSON object with `currency: "USD"` and a `models`
mapping keyed by the exact slot model. `parse_pinned_pricing(pricing_bytes)` reads
numeric literals as Decimal, rejects duplicate keys and non-finite constants, and
is also the decoder for offline recomputation. Do not read replay prices through
binary floats first: that can round high-precision literals or underflow a rate
to zero before the exact guards run. Each entry supplies finite nonnegative
`input_usd_per_million` and `output_usd_per_million`. A additionally requires an
HTTPS `request_limit_evidence` source for its enforced, reasoning-inclusive
`max_tokens`. B requires `max_output_tokens` (a positive documented,
reasoning-inclusive maximum) and HTTPS `public_source`.

The later workflow's D0 must verify the actual public source, prices and maximum
**again before each run window**. A pinned digest proves bytes, not accuracy,
truth, support or currency. Synthetic `example.invalid/FAKE-TEST-ONLY` sources
in tests are not admissible run evidence.

The reservation is `(exact final serialized request UTF-8 bytes × highest pinned
input rate + enforced output bound × pinned output rate) / 1,000,000`. It includes
system/instructions/OAuth prefixes, message framing and all model-visible input.
Cache breakpoints are removed; strict calls never request cache writes. B reserves
its documented maximum even when nominal `max_tokens` is lower, and sends **no**
unsupported output-limit field. Missing evidence/bounds or an over-cap reservation
means zero sends, never a discovery call. The Codex transport has a separately
fixed `request_limit` mode for known supported endpoints; `single_call` does not
enable it for today's undocumented ChatGPT endpoint.

Amounts are computed exactly (no Decimal rounding) and the v1 records carry them
as JSON numbers, so an amount a float would round is never rounded: a reservation
that doesn't round-trip exactly is refused with zero sends (`strict_parser`), and a
reported price that doesn't round-trip leaves cost `UNKNOWN` (unknown exposure =
reservation). Pinned rates with a few decimals always pass.

## Send and persistence order

1. Validate root/slot, then create `<slot>.claim` with O_EXCL/O_NOFOLLOW, fchmod
   0600 and retain its initially empty fd. A real monotonic/UTC pair taken just
   before the successful claim is the attempt start. Deadline = that monotonic
   value + 900 exactly. Existing claim or output files refuse without overwrite.
2. Validate the remaining fixed inputs, exact file length/digests, model/route,
   current final request shape, cap and ordinary budget policy. No account probe,
   allowance park, service construction, fallback or tool is involved.
3. Populate the claim **once** with bounded `context-t1-claim/v1` metadata: attempt
   and experiment bindings, pinned digests, actual start/deadline, frozen final
   body hash/byte count, bound/evidence digest, and an exact Decimal-string
   `reservation_usd`. Never content, credentials, token names or a request body.
   Write once, **fsync claim, then fsync retained root directory**.
4. Only after both barriers and final body/deadline checks, take the actual
   HTTP-start clock pair and one fresh client transmission UUID. Any write,
   short-write, flush or either sync failure sends zero times. Changed body or
   higher exposure after this gate refuses; the claim is never rewritten.
5. Make one internally streamed request, no text callback. Anthropic clones its
   pinned client per call with `max_retries=0`; it does not consult/update learned
   thinking/temperature sets or resend a refused parameter. Codex does one POST,
   no redirects, reconnect or replay. Both use owned retry-free HTTP clients.
6. Close transport, disarm/bounded-join watchdog, close the claim fd; write and
   fsync/close `<slot>.raw` if any answer was received and `<slot>.call.json`, then
   fsync their directory. Sample actual cleanup clocks immediately before creating
   `<slot>.attempt.json` **last**. Its own persistence is evidence, not a recursive
   claim to measure its own fsync. Receipt failure never returns success.

All creates are exclusive and explicitly 0600, independent of the umask. The root
is retained through fd-relative operations. Files must be regular, effective-UID
owned and single-link; content/bindings/digests matter, never dev+inode alone.
These measures are **crash/race fault tolerance, not same-UID writer exclusion**.
No append, replace, repair, resume, reuse, rewrite or cleanup deletion.

Offline reconciliation distinguishes two existing-claim states under this owned,
write-once protocol:

- A claim that is not one complete, valid `context-t1-claim/v1` record proves no
  request started: exposure is exactly zero, but the slot is permanently used and
  must never be resumed or re-sent. This includes empty and partial claims: both
  durable barriers require a complete claim before any HTTP request can start.
- A complete valid claim without a valid final attempt is a **FAILED/UNKNOWN**
  used slot. Retain its original reservation as unknown exposure, never infer
  zero from missing raw/call files or an unobserved request. A valid final
  zero-send attempt can establish zero exposure without invented usage.

These rules do not turn a missing/unknown expected root into zero exposure or
provide protection from hostile same-UID rewriting. A repeat invocation returns
only its own zero-send NOT_MEASURED refusal; it never relabels, repairs or sends
the previous slot or clears that slot's retained exposure. The later T1 workflow
must perform the same fixed-input checks before dispatch; a consumed slot spoils
its experiment root.

`raw` holds the concatenated provider answer text's UTF-8 bytes unchanged (including
whitespace/empty answers), not JSON parsing/repair, reasoning or tools. It is
**untrusted data**, not executable code or an instruction to an agent.

`attempt.json` is Architecture's unchanged `context-t1-attempt/v1` schema. Its run
and session UUIDs are fresh per slot; both clocks are actual back-to-back samples,
not fabricated from one another. `call.json` is the closed
[`context-t1-call/v1`](schemas/context-t1-call.v1.schema.json) schema: raw hash,
EVERY model-input part's kind/order/bytes/hash, final body bytes/hash, actual
parameters, exactly reported nullable usage counters, safe stop/id/class/status,
HTTP/transport clock observations and accounting. Provider, model, route, auth
mode and bound mode are recorded only after their admitted identity checks pass;
the pricing digest is recorded only after its bytes match. Unverified values are
null, including on refusals, never rejected types or prose copied into a receipt.
The enclosing workflow run ID is in call.json only, not substituted for the slot's
fresh run UUID.

`recompute_list_price_usd(call_record, pinned_pricing)` is pure and uses reported
base input/output usage and pinned Decimal rates. Codex's nullable numeric
`input_tokens_details.cached_tokens` and `output_tokens_details.reasoning_tokens`
are subsets: require 0 <= subset <= its reported total, and price **only the
whole totals**, never add or subtract a subset. This conservative full-input price
requires the later workflow to verify publicly that cached input costs no more
than base input. Unreported counters/splits stay null, never invented zeros.
Malformed/extra usage fields or invalid subsets give FAILED `strict_parser` with
UNKNOWN usage and cost. (The Anthropic provider itself keeps the answer and
reports such a usage as `usage_fault`; usage is what this harness measures, so
here the attempt still fails.) A known but unpriced category (Anthropic cache counters
> 0) keeps COMPLETED and exact KNOWN usage with no failure reason, but UNKNOWN
cost; it does not pretend the parser failed. Premium cache writes, although never
requested, could exceed the reserved base-rate exposure: that reservation is then
only a lower bound. The later T1 workflow must stop new dispatch after any attempt
whose terminal is not COMPLETED or whose cost is not KNOWN.

`attempt.json` alone is authoritative final accounting. The contract separates
zero initiated requests from a transmitted call:

- **Zero transmissions:** list price and exposure are exactly zero, KNOWN without
  any usage evidence. Unreported counters remain null and usage stays UNKNOWN;
  the pure reported-usage helper returns None, not an invented zero. This also
  applies to this invocation's preflight refusal when it cannot create files,
  but does not erase an earlier used slot's exposure.
- **One transmission:** a KNOWN attempt requires durable call evidence and full
  priced usage; `recompute_list_price_usd(call, parse_pinned_pricing(bytes))`
  equals its recorded price exactly. Missing, unpriced or non-durable evidence
  stays UNKNOWN with its reservation; never fabricate counters or a PASS.

`call.json` is a write-once observation **before cleanup**: for a transmitted
call the attempt may downgrade its cost view, never upgrade it. An UNKNOWN or
non-durable call never becomes a KNOWN one-transmission attempt. This
implementation conservatively keeps a transmitted call's cost UNKNOWN on every
deadline breach (even with a complete response), cancellation, missing/unpriced
usage or uncertain cleanup: null list price and full reserved exposure. A late
cleanup may therefore downgrade a previously KNOWN call observation. Receipt
failure never implies zero transmitted cost. A known cost above its reservation
fails without clamping. Reservation is not spend. Numeric
`AgentResult.cost_usd == 0` under UNKNOWN is only a legacy transport placeholder;
never use it as evidence of zero cost. Reconcile claim, call and attempt records.

## Deadline, privacy and limits

The network cutoff is five seconds before the original 900-second deadline, with
remaining-time client timeouts, a bounded watchdog and per-stream-event deadline
checks (including thinking/pings). Cleanup must satisfy both actual clocks.
Cancelled/blocked/late cleanup or a failed watchdog join is FAILED timeout (or
cancel) with UNCERTAIN cleanup, not a success. Closing Python sockets/threads does
not prove provider-side work stopped or the process can be forcibly killed.
Process/box containment still needs admission in the later workflow.

Only metadata reaches AgentResult, events, logs and the live panel: paths, digests,
lengths, counters, cost state, allowlisted stop/id, terminal and enum reasons. No
provider error prose or exception chain is persisted. A scoped ContextVar/LogRecord
factory redacts msg, args, exc_info, exc_text and stack_info **without dropping
records**, resets its token in finally, preserves concurrent ordinary logs and
enters a separate scope in watchdog/cleanup threads. This covers strict building,
pinned dispatch, stream parsing, exception mapping and cleanup, not a preexisting
factory's own export, other telemetry systems or HTTP trace hooks. Unsupported
observers remain an admission hold.

This primitive **controls use, not credential isolation**: registry construction
and a stage process may already see all configured credentials. Do not treat a
named token as a sandbox. Each real workflow needs Security admission, correct
secret/bootstrap policy and worker/environment scoping. T2 held-out isolation and
digest placement are separate pre-persistence decisions. SEALED_PROVIDERS is
unchanged: Anthropic can be gate-classified, OpenAI/Codex still cannot. No workflow,
provider call, probe, secret isolation claim or admission is granted by this type.
