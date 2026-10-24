# Offline context profile candidate

**dormant; runnable route not established (R1: no standalone route; one-node workflow route pending Temper loader check and Security R2)**

Architecture #269, arch-stage-context / system-arch-in-temper. This is packaging, not a registered stage,
provider adapter, runner, workflow, accepted stage or permission to send a request. H-CTX-STAGE-BUILD-1:
the missing candidate artifact need not wait for the independent meaning-judge chain. Test only tiny,
new synthetic inputs here; no model calls. Preserve context_profile/v2, the 11 bars and blocked v3 grading.

## Instruction authority and provenance

The instruction file is the independent fresh author's artifact, task #270, read and accepted by HOME.
Its exact SHA256 is aee4f3b2ce88721c25e49ae6528c3de663e2dc1edfda30e9b2488ee193da3d58;
preparation rejects other instruction bytes, even if a caller updates its descriptor.
Its AUTHOR-INVENTORY.txt and SHA256SUMS live in the private stage-candidate-author packet; #269's separate
WORKER-INVENTORY.txt is NOT an answer-free author inventory. #269's pre-exposure draft is preserved outside
the repository and is not adopted. No case-derived examples belong in this document or the instructions.

The rule citations below are exclusively to these two frozen, case-answer-free sources, relative to this
folder at 331036ae:

- STANDARD.md, SHA256 696f12c42886cf97395e793e7add19bc23007988f1b84dcda21a2bba08feb437.
- contract.v2.schema.json, SHA256 965a75c384ab0b72220c507a78004aafc478bdcb4916ec1f050d8780ad377fbe.

## Exact contract and model judgment checklist

These are the model-only judgments; deterministic helpers do not pretend to establish them. Each line
states its source, not a lesson inferred from a brief.

| Obligation | Authority |
|---|---|
| Return one JSON object, contract=context_profile/v2, every required section present, no extra keys anywhere; brief_sha256 optional in the contract, checked if present. Candidate packets supply its exact digest. | STANDARD.md:82–85,95; contract.v2.schema.json:6–11 |
| Required sections: product, maturity, current_system, external_systems, workload, performance, reliability, privacy, security, team, budget, constraints, goals, unknowns, assumptions, plus contract. | contract.v2.schema.json:8; STANDARD.md:93–125 |
| Quote source kind=quote has quote; assumption source kind=assumption has why; no mixed shape. Exact contiguous 2–40-word quote, shortest span carrying the whole claim; normalization permits case/whitespace/curly quotes/dashes/markdown emphasis, not invented assertions. | STANDARD.md:87–91; contract.v2.schema.json:115–144 |
| Numeric digits, number words and scales must appear by value in the item's own quote. Derived numbers are assumptions. Assumptions interpret/derive stated facts; never fill silence, and working assumptions are listed. | STANDARD.md:132–144; contract.v2.schema.json:125–134,219–227 |
| Silent scalar=unknown or fact list=[]; every such field names its path in unknowns, including non-material silence. Exceptions: current_system.items when state none/unknown; empty maturity.evidence covered by stage unknown; unknowns/assumptions do not recurse. Empty constraints/goals need their own unknowns. | STANDARD.md:132–140; contract.v2.schema.json:144,208–218 |
| Unknown question and why_it_matters need at least 5 characters, decisions_affected at least one string of at least 2 characters; material is boolean, optional field uses the schema's closed path enum. | contract.v2.schema.json:208–218 |
| Maturity enum exactly idea, startup, growing, established, unknown. Classify lifecycle/demand evidence, not volume, age, headcount or governance. Non-unknown needs evidence. Replacement boundary ambiguity remains unknown. | STANDARD.md:151–160; contract.v2.schema.json:21–29 |
| Current-system state exactly none, exists, unknown; none/exists need quotes. Owned installed items use kind component, stack, hosting, data_store, client, other. Team skills/future architecture do not establish installed reality. External systems have name, role, source and are separate. | STANDARD.md:99–101,116–119,365–368; contract.v2.schema.json:30–39,156–175 |
| Observed workload must be quoted measured demand now; targets/hopes/forecasts belong in projected, not observed, even when qualified later. Others' demand is not this product's. Peaks and performance targets remain distinct. | STANDARD.md:102–105,146–149; contract.v2.schema.json:40–58,145–155 |
| Availability, RPO and RTO are distinct fact-or-unknown scalars; coverage alone is not recovery time. | STANDARD.md:106–108; contract.v2.schema.json:59–68 |
| Privacy holds data categories, sensitivity, retention, sharing and jurisdictions/rules separately. Sensitivity enum none, low, moderate, high, or scalar unknown. Classify from the standard's data/harm definitions, not workload or organizational size. | STANDARD.md:109–113,162–168; contract.v2.schema.json:69–80,176–185 |
| Security requirements, threats and compliance are separate fact lists; load slowdown is not an attacker/abuse incident. | STANDARD.md:114–116; contract.v2.schema.json:81–90 |
| Team size, skills and operating capacity are separate. Build/total available funding is not revenue; monthly operating money belongs in run_monthly. | STANDARD.md:117–121; contract.v2.schema.json:91–109 |
| Material facts/unknowns are those whose values/plausible answers change architecture decisions; contradictions or unclear authority are unknowns. Name affected decisions; do not elevate founder/brand narrative. | STANDARD.md:170–175; contract.v2.schema.json:208–218 |
| Constraints are must-holds: binding law/contract, authoritative must/never, fixed cap, consequential hard deadline or retained system. Mandatory privacy/security are never traded for money; mandatory performance is a target and a constraint. | STANDARD.md:179–184; contract.v2.schema.json:186–195 |
| Goals are tradeable preferences, one criterion each: cost, efficiency, performance, privacy, security, reliability, delivery_speed, operability, change_cost, scalability, other. Resource efficiency is not user-visible performance or shipping speed; money and resource efficiency, privacy and security remain distinct. | STANDARD.md:185–190; contract.v2.schema.json:196–207 |
| No item both constraint and goal; a distinct optional wish beyond a mandatory floor needs separate text. IDs C<number>/G<number> unique within their groups; goal ranks contiguous 1..n, guided by stated authority/priority, unresolved disagreement material. | STANDARD.md:191–195,217–219; contract.v2.schema.json:186–207 |
| Preserve string minimums, all required members and additionalProperties=false, rather than using prose or null as a missing-value substitute. | contract.v2.schema.json:7–225 |

The instruction's silent checklist is only a request for self-checking, not independent proof of meaning.
The checker measures structural/anchor observations; assertion meaning stays NOT_MEASURED and final
acceptance BLOCKED. Never relabel anchor agreement semantic consistency. All bars B0–B10 and B6's median
$1/max $2 per run and median 4 minutes remain requirements, not relaxed by this packaging.
Authority: STANDARD.md:7–11,233–241,265–272,297–318.

## Proposed route (documentation only; not an engine config)

HOME decision: one call per brief, H-CTX-1(b), using agent type single_call, provider anthropic,
model claude-opus-5-5. Ordinary llm is deliberately excluded because its JSON-repair path may add a call.
No tools, memory, fallback, retries, recovery, dispatch or response rewriting. The existing bounded
single_call path is documented in docs/reference/agents/single_call.md and docs/single-call.md; it does
NOT by itself establish a supported enabled standalone stage route. R1 must name that route and fixed-input
binding, numeric usage and request-limit evidence, including settings/capability/consent requirements.
R2 then admits credential and observer handling. Neither approval is inferred from the offline files.
No runnable YAML is included. R1's read-only source answer (single-call-r1-route-331036ae/R1.md) found no supported standalone route; a one-node workflow needs Temper's loader check and its own admission, not an ad hoc harness. This paragraph records the task's route decision, not a new v2 contract rule.

## Offline preparation interface

context_profile_candidate_prepare.py takes explicit --brief, --instructions, --schema, --route, --pricing,
--binding and --root paths. It never searches directories for briefs. The literal 14 brief path identifiers
are packaging metadata only; no key/label is read by preparation. Approved instructions and schema paths
are fixed inside the checkout. Binding metadata fixes root/root_id/packet_slot/experiment_id/binding_id, case_id,
repetition (1,2,3), exact {bytes,sha256} descriptors of brief/instructions/schema/route/pricing, plus externally
admitted output_root, slot, family, cost_cap_usd, source_sha256, config_sha256 and packet_sha256.
The packaging packet_slot is <case-id>-r<repetition>; native slots are A1/A2/A3 for the three repetitions,
family A. Each brief needs an explicitly admitted native root allocation. Neither root nor slot is a
standalone execution interface. Source/config/admission-packet digests are supplied, never invented or
self-referentially equated to the newly generated manifest digest.

The helper's closed metadata versions are context-profile-candidate-binding/v1 and
context-profile-candidate-route/v1. They are candidate file formats, NOT registered agent config fields.
The route identity must be externally resolved, with single_call, anthropic/claude-opus-5-5,
anthropic-oauth-named-token/oauth, family A, request_limit, max_tokens=8,192, deadline_s=900,
request-limit HTTPS evidence and actual route/request-limit evidence digests. Unresolved required values
are refused. Framing is the explicit exception HOME admitted: framing_bytes=null and
framing_evidence_sha256=null until HOME supplies an engine-evidenced positive bound; never a zero guess.
A supplied URL/hash is provenance syntax, not admission or proof that it is true/current. Preparation
does not load a credential or check a service/flag. The native fixed mapping uses R1's exact keys:
prompt_path, prompt_sha256, prompt_bytes, output_root, slot, family, route, auth_mode, max_tokens,
output_bound_mode, deadline_s, cost_cap_usd, pricing_path, pricing_sha256, experiment_id, binding_id,
source_sha256, config_sha256, packet_sha256. No token name/value is loaded, printed or manufactured;
R2's named-credential/observer admission remains separate. This metadata is NOT a runnable agent config.

Pricing uses the existing docs/usage-rows.md snapshot layout (currency=USD, models mapping the model to
input_usd_per_million, output_usd_per_million and A's request_limit_evidence); it is supplied by path
with exact bytes and hash. Rates stay exactly $4/$20 per million. Input is the accepted instruction
bytes (already containing the schema) + the supplied brief digest + that brief's bytes, separated by
constant delimiters. No schema duplication, brief substitution, graph input_data, prompt repair or
truncation. single_call reads the exact prompt_path bytes and ignores input_data. Prompt limit 32,768 B
is only an instruction-artifact ceiling, not a reservation or a token count.

HOME's H-CTX-R1-SIZE-2 replaces the mistaken 24,576-byte proof. Record text_utf8_bytes and
text_json_bound_bytes=len(json.dumps(text, ensure_ascii=True)); the latter bounds that Python JSON string,
not a whole request. Record framing_bytes=null until an engine-evidenced bound is admitted.
reservation_lower_usd=(text_utf8_bytes×4+8,192×20)/1,000,000. reservation_upper_usd is null with unknown
framing; otherwise it uses text_json_bound_bytes+framing_bytes in that formula. Refuse only if the lower
bound exceeds externally supplied cost_cap_usd, proving certain native refusal. Otherwise return
NATIVE_CAP_DECIDES: only the native guard measures final serialized body bytes and enforces its cap.
No wire-body inspection, offline input-token estimate or guarantee of a send is implied.

The caller supplies a pre-existing canonical private root (0700); snapshots are 0600, write-once O_EXCL,
non-symlink regular files. No root fallback, directory retargeting, overwrite, deletion or cleanup retry.
Persistence failure consumes the slot and preserves evidence. The caller must retain immutable packet
hashes; mode bits/hashes are tamper detection, not a claim of OS-level write protection against its owner.
Helper stdout never contains input text. It returns only packaging status, numeric reservations and hashes.

Reservation uses exact Decimal, separately from actual receipts. For the accepted 26,416-B instructions
alone the conditional lower bound is $0.269504, NOT B6 and not a per-call or 42-call reservation. Briefs,
JSON escaping, system/OAuth prefixes and provider framing add exposure. pool_reservation_usd stays null.
The per-call cap and 42-call sum must be set at dev-run admission from text bounds plus an admitted framing
bound; this task sets neither. The $12 experiment stop is unchanged: unknown exposure or an unknown next
reservation returns STOP_UNKNOWN, and a known sum above $12 returns STOP_CAP. The helper is not an
authorized spender, runner or budget enforcer; a future admitted runner must apply these stops before
every send. Preparation never consumes an engine slot; the later native exclusive claim does that.
A used native slot or packaging slot is refused without repair or automatic root replacement.

## Offline reporting boundary

context_profile_candidate_report.py accepts only complete indexed evidence, with immutable packet,
raw-answer and native receipt hashes. Raw answer JSON is strict: one object, no markdown, duplicate
members, NaN/Infinity, wrappers, trailing prose or repair. Answer bytes are never rewritten. Structural
self-checks precede diagnostic execution. Scripts use their unchanged public command-line interfaces:
checker --brief/--schema PROFILE; scorer --case DIR PROFILE, --pool for each complete 14-position
repetition, and --case DIR --runs P1 P2 P3 for each of 14 cases; meaning --case DIR PROFILE.
Exit 1 from completed scorer/meaning diagnostics is normal BLOCKED output, NOT a missing run; exit 2,
malformed output, missing/duplicate positions or a changed source/receipt refuses the report. No run or
repair is requested to fill a gap. Meaning support remains NOT_MEASURED, including a missing judge.

Reports retain raw script results privately and expose a numeric/enum-only summary. Exact-price and
actual-time tables are independently recomputed from pinned native receipts, not scorer estimates,
reservation-as-spend, a cost_usd assertion, null-to-zero conversions, or caching discounts. Strictly
validate native call and attempt against docs/schemas/context-t1-call.v1.schema.json and
t1/attempt.v1.schema.json, including if/then/else, formats and uniqueItems; unknown keywords refuse.
attempt.json is authoritative final accounting: retain its amount beside the independent call-usage
price and native byte-reservation recompute, reporting MATCH/MISMATCH/UNKNOWN without rewriting it.
There is no published claim schema: record presence, identify empty claims as incomplete, and leave
nonempty completeness UNKNOWN rather than inventing internals or proving the durable send barriers.
A claim without a valid final attempt is FAILED/UNKNOWN here, never free exposure.

Price base input/output totals only. Codex cache/reasoning subsets are not added or subtracted; invalid
subsets refuse. Positive Anthropic cache categories are unpriced: preserve exact KNOWN usage but UNKNOWN
cost, and retain exposure as unknown rather than a safe ceiling. Missing counters remain null; nullable
Anthropic cache categories conservatively leave the independent price UNKNOWN_CACHE rather than guessing
that no extra cache charge exists. An authoritative attempt value is preserved, never overwritten. Native
monotonic cleanup-minus-dispatch and separately sampled UTC/transport deltas are actual-time evidence;
a declared 900-s deadline is never substituted for elapsed time. Missing clocks stay null. Failed cleanup
or failed/cancelled calls remain visible and never earn a free slot.
All requested, attempted, completed, failed, cancelled, cleanup and retained-exposure states are distinct.
No post-failure retry, fallback, service call or provider activity exists in either helper.
