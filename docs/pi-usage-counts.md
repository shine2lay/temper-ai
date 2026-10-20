# Pi call token counts: unknown is not zero

Contract of `temper_ai/llm/pi_stream.py` for completed and failed Pi calls,
including compaction. These are **observations, not a pricing or completeness
claim**. The five existing event keys remain, with `None` legal just as on the
service-provider path (`temper_ai/llm/models.py`). No schema or pricing changes.

## The rule

For `prompt_tokens`, `completion_tokens`, `cached_prompt_tokens`,
`cache_write_tokens` and `total_tokens`:

1. Accept only a positive integer, not a boolean, at most `2**53 - 1`.
   Missing, null, strings, fractions (`7.9` is never truncated to 7), floats,
   negative values, NaN, infinity and larger integers become `None`.
2. No usage object, or all four of Pi's `input`, `output`, `cacheRead` and
   `cacheWrite` equal to integer zero, means **no usable report**. All five
   observations become `None`, even with a supplied total or legacy cost.
3. **A Pi-reported zero is never a known count.** Data confirmed no zero
   class for Pi 0.87.1 / anthropic-messages: `|| 0` loses presence, deltas can
   overwrite a positive with zero, and multiple providers share the API.
   There is no empty allowlist, unused version/API lookup or synthetic proof
   branch. This rule also fails closed on unknown versions/APIs; safe positive
   components remain observations.
4. A positive integer `cacheWrite1h` makes `cache_write_tokens` unknown,
   including when it exceeds `cacheWrite`. The existing field cannot express
   the more expensive one-hour price class. An absent or zero `cacheWrite1h`
   does **not** prove the ordinary write's pricing tier; a positive write can
   remain a count without being quotable.
5. A reported `totalTokens` must itself be a safe integer and equal the sum of
   **all four known validated component observations**. Otherwise the total is
   `None`. Never synthesize a missing total or label a partial sum known. A
   zero total cannot establish a report: all-zero components fail rule 2.

The zero rule is unconditional, so no version or API plumbing was added to
`PiEventMapper` or `run_turn`. A compaction, unknown API/version or message
claiming a known version cannot gain a zero proof. A future proven version/API
pair returns only as its own planned change with Data's confirmation and
provider-presence evidence; see the upgrade procedure.

A failed/aborted call can retain a positive snapshot, but it can be partial
(output can be a lower bound). `responseModel`, when present, identifies the
served model rather than the requested one. Unknown version/API conventions
are unproven. Compaction is an aggregate of up to two final summary calls,
without provider/API/model identity or failed-attempt coverage. None of these
observations alone proves exclusive price classes, complete occurrence
coverage, free usage or subscription coverage. Count a compaction record once,
as its own spend: its summary calls appear in no other record. Treat it as a
lower bound, because failed attempts are missing. Never treat it as one leaf
model call (per-call counts, rates, quotes, model attribution), and never add it
again to an aggregate that already includes it (agent-end totals do).

## Source evidence: pinned Pi 0.87.1

Read-only audit of
`~/.local/share/temper/pi-runtime/pi-0.87.1-rg15.2.0-fd10.5.0/pi/`.
`local/pi/pi-box.json` pins `pi_version: 0.87.1`;
`temper_ai/pi_agent/box.py:163,254` checks that pin against the installed runtime.
No Pi process, provider request or pin/runtime change was needed.

Paths in this table are relative to that runtime's `pi/` directory:

| Source | Evidence |
| --- | --- |
| `node_modules/@earendil-works/pi-ai/dist/api/anthropic-messages.js:346-353` | Every count starts at 0, before a provider reports anything. |
| `node_modules/@earendil-works/pi-ai/dist/api/anthropic-messages.js:416-420` | `message_start` assigns input, output, cache read and cache write with `value || 0`, merging explicit 0 with null/absent/false/NaN/empty string. One-hour cache writes are separate. |
| `node_modules/@earendil-works/pi-ai/dist/api/anthropic-messages.js:575-588` | Deltas replace only non-null fields; an explicit zero can overwrite a positive. The adapter itself notes proxy divergence. Missing delta usage leaves the start snapshot. |
| `node_modules/@earendil-works/pi-ai/dist/api/anthropic-messages.js:422-424,597-599` | `totalTokens` is a derived sum; strings can concatenate. It is not an independent provider total. |
| `node_modules/@earendil-works/pi-ai/dist/api/anthropic-messages.js:19-40` | Short retention defaults to five minutes. Long needs `PI_CACHE_RETENTION=long` or `cacheRetention`; TTL is selected request-side. |
| `node_modules/@earendil-works/pi-ai/dist/api/anthropic-messages.js:406-413,627-636` | A served `responseModel` can differ; error/abort retains a potentially partial usage snapshot. |
| `node_modules/@earendil-works/pi-coding-agent/dist/core/compaction/compaction.js:91-104` | Pi excludes aborted, error and all-zero usage as no valid context-usage data. This is not evidence that failed calls are free. |
| `node_modules/@earendil-works/pi-coding-agent/dist/core/compaction/compaction.js:475-483,498-509,550-554,722-740` | Retries return the final attempt; failed/length-limited summaries can throw without a record; split summaries can combine two calls. No API/provider/model is attached. |

Data's independent read-only confirmation bound those files to
SHA-256 `97de17d406264322ff7927fa0c20e1c61b46386b5e14f9c6e0012599c01664f7`
(adapter) and `871f81769ef67a78c63cfc674e09f13097899effe4677f156a3613878c387640`
(compaction). It confirmed all-zero => no report and invalid => unknown, and
confirmed **no** zero class. The same adapter API is also registered for
GitHub Copilot, OpenRouter, Fireworks, Cloudflare AI Gateway and OpenCode;
version plus API is not a pinned provider contract.

Temper source/allowlist evidence, not a sampled live member environment:
`temper_ai/pi_agent/box.py:91-98` seals settings without `cacheRetention`, and
`DOCKER_ENV_KEYS` allows only `HOME` and `LANG` into the Docker/RPC launcher.
`WorkerBox._write_agent_dir` writes those settings; `WorkerBox.env`
(`temper_ai/pi_agent/box.py:971-991`) constructs an explicit environment without
`PI_CACHE_RETENTION`. No long-retention mechanism was found or enabled.

## Numeric totals and cost deliberately stay separate

`_usage` emits nullable observations. `_add_legacy_usage_totals(raw)` separately
keeps the old numeric aggregation at the same model-end and compaction-end
call sites. **Do not rebuild legacy totals from nullable call rows.** Hiding a
one-hour write must not subtract it from old totals; rejecting a fraction as
an observation must not change its previously truncated aggregate.

Before changing aggregation, fixed outputs were captured from master
`296711b41065f1b2ebf94d4ad54b18ccfbc5c918` in
`tests/fixtures/pi_usage_legacy_totals.json`: normal integers, one-hour writes,
all-zero components with a positive total, fractions, absent usage and
compaction. Each pins numeric totals, snapshot and cost independently of its
new observation expectations. Temper lead approved this split and the plain
zero-unknown rule instead of an empty proof table. Data's semantics review
covers observations only. `tests/fixtures/pi_usage_observations.json` holds
Data's separate catch/clean cases (delta overwrite, all-null normalization,
partial error/abort, served model, compaction, unproven convention, string
concatenation, one-hour writes and matching/mismatched totals).

NaN/Infinity token values now count as 0 in legacy totals instead of crashing.
This is a crash-to-ignore change for unreachable real Pi input:
`JSON.stringify` serializes them as null. No real Pi numeric total changes.
No price, rate table, `cost_usd` or `cost_basis` changes. Mapper, agent-end
and stored run token totals, `usage_snapshot` and live check-ins retain old
values. Cost and dollar spend are unchanged everywhere.

A deliberate boundary, decided by the Temper lead: when no numeric agent-end
total exists, `observability/run_totals.py` falls back to nullable call totals,
counting unknown as zero. This covers in-flight agents, a parked run's in-flight
step, and lost/cancelled/failed agents without a numeric end. Its fallback
token figure is a floor and can therefore fall, e.g. raw 200 becomes unknown/0.
The old raw count is not persisted elsewhere by this change. This replaces
the original blanket promise that every token total stays unchanged; it is
not owner approval or a new spend, field, activation or consent. Prices and
dollar spend are still unchanged. Do not rebuild a partial token sum from
known classes: service-path prompt counts include cache and would double-count.

Reader audit found no reader fix needed:

- `temper_ai/observability/run_totals.py`: nullable SQL projections and
  `cost or 0` / `total_tokens or 0`; numeric agent-end totals retained.
  Without an agent end, unknown call totals become zero in the fallback,
  not a preserved raw-token total; the fixed reader test pins this boundary.
- `temper_ai/api/data_service.py`: nullable call counts pass through; reducer
  arithmetic uses `or 0`. `temper_ai/mcp/tools.py` and
  `temper_ai/observability/webhook_notifier.py` use numeric agent/run totals
  and nullable-safe fallbacks, not arithmetic on raw None.
- `temper_ai/pi_agent/team_flow.py` and `team_leader.py`: snapshots/results
  stay numeric; nullable fallbacks already use `or 0`.
- Frontend call views allow `number | null`; `formatTokens` shows `-` for
  unknown, and story statistics use `?? 0`. Historical event fixtures stay
  historical; replay checks allow only intended ended-call totals to become
  unknown (their cache zeros are unproven). No other story field changes.
  No model content or request bodies are needed for this audit.

Usage-row work separately stores None as SQL NULL and preserves 0. Historical
ambiguous rows remain the serializer's concern; this change does not
reinterpret old rows or change the row writer.

## Upgrade procedure (fail closed)

1. Use the normal pin procedure and retain the old runtime. A new version is
   unproven by default: **its zeros remain unknown**. No entry is inherited.
2. Read the exact adapter and compaction source; record version, provider,
   API, file:line/hash, initialization, per-field presence/null behavior,
   deltas, derived totals, served-model identity and retention. Check sealed
   settings and explicit environment. No model probe to guess semantics.
3. Keep the plain zero-unknown rule while raw presence is lost. A future
   proven version/API pair needs its **own planned change**: raw per-field
   presence capture, keyed at least by provider + API + version, and a pinned
   provider contract. Reading a newer adapter alone is insufficient. Obtain
   Data's class-by-class confirmation before adding any proof table/lookup;
   an unconfirmed class stays unknown. That redesign is not part of this change.
4. Long retention needs an explicit one-hour class and accounting semantics
   first. Source defaults and a zero `cacheWrite1h` do not prove a price tier.
   This document authorizes no cache setting or retention change.
5. Test changed stages on fixed known answers: normal/positive and zero,
   no-report/all-null, compaction, invalid values/boundaries, unknown identity,
   total consistency, one-hour writes and partial failures. Demonstrate each
   guard's bite and compare numeric totals and cost to the old implementation.
6. Get Data's observation confirmation and Architecture's exact-patch Pi land
   check, then the full gate and temper-ci deploy/live checks. No provider call,
   separate Temper, new runtime or activation is implied by this procedure.
