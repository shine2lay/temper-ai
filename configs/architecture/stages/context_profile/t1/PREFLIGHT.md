# D0 synthetic metadata preflight candidate — frozen contract v1

## H-D0-META-1 (before implementation)

Problem/evidence: the public T1 helper inventory at base
8216277bfdb4ac6fcded43a7c1ab23c1ec87eb65 contains D1 projection, D2 validation,
D3 comparison and D4 aggregation, but no pure global six-slot envelope validator.
The allowed source-only D0-PLAN.md sections 3/4/6 describe, but do not implement,
that check. No stopped #194 computation or protected input was examined here.

One change: add a standalone stdlib-only metadata function, closed synthetic
schema, these frozen known answers, focused tests and Architecture ownership rows.
Expected result: every frozen clean envelope passes METADATA checks and every
frozen negative refuses, with no output leak or operational effect. Measurement:
ONE final focused synthetic suite after all source/test/doc/ownership edits.
Disproof: any false positive, missed negative, unexpected exception, input-content
output or operational dependency/effect. Preserve the first failure; no repair and
rerun in this task. H-D0-META-1 is UNTESTED at freeze; the private final report,
not a post-hoc change to this document, records HIT/MISS.

Accountable lead: Architecture. Own initiative system-arch-in-temper,
project arch-stage-context; $2,000/week Pacific rule applies. No budget write.
Candidate, once landed on master; not accepted; gives no dispatch, registration
or later-stage authority. No workflow, API, provider, root allocation, claim,
real evidence access or activation.

## Scope and trust boundary

`check_plan(plan_json: bytes, expected_json: bytes, now_utc: str) -> dict`
checks supplied declarations only. Both byte arguments have independent 65,536
byte limits. `expected_json` is a caller-supplied comparison reference, NOT an
approval, a custody receipt, loaded-route proof or authenticated evidence. Even a
perfect METADATA_PASS ALWAYS has `authorizes_dispatch=false` and
`authorizes_later_stage=false`. No actual price, route, funding, quota, root
freshness, lock, scheduler, containment or authenticity follows. Evidence records
are explicitly unverified claims. The `SYNTHETIC_ONLY` scope is also a claim, not
proof of origin. The helper has no CLI and loads no files, environment, provider,
worker, registry or network; it neither imports existing T1 helpers nor retries
any #194 checker. It never emits input identifiers, values, exception text,
credential selectors or model-bound content.

This is only one M06 subcomponent, NOT completed D0/controller, J, a workflow,
Stage1 qualification, judging admission or any project criterion. Stopped #194,
F03, M7, actual pricing, loaded-route custody and other prerequisites stay open.
The schema is a NEW candidate metadata format, not adapter pricing and not a
change to any existing T1 contract or threshold.

## Closed field sets (normative; schema frozen with this document)

File `preflight.v1.schema.json` describes three disjoint closed shapes: plan,
expected and result. Its required/properties sets must coincide at every object.
No extra field is accepted at any depth, including token, secret, selector,
registry alias or unsupported request parameter fields. No required value is null.
JSON Schema handles structure; the function also enforces the syntax, bounded
numbers, exact types and relational invariants below. A schema match alone is NOT
METADATA_PASS. Required fields (comma lists are exact, no optional fields):

* Plan: schema, scope, experiment_id, binding_id, pins, window, evidence, slots,
  total_reservation_usd, frontier.
* Expected: schema, scope, experiment_id, binding_id, pins, window, evidence,
  families.
* Pins (plan and expected): source_sha256, config_sha256, pricing_sha256,
  input_sha256, packet_sha256, projection_sha256, freeze_sha256, plan_sha256.
* Window: not_before_utc, expires_utc.
* Evidence: admission, loaded_route, request_shape, projection_provenance,
  pricing, cache, output_bound, containment, observer, budget, quota, custody.
* Every evidence record: state, sha256, not_before_utc, expires_utc.
* Families: A, B. Each value is a settings object.
* Every slot: slot, family, session_id, run_id, settings, root_state, claim_state,
  output_state, reservation_usd.
* Every settings object: provider, model, route, auth_mode, credential_policy,
  output_bound_mode, config_sha256, body_sha256, body_bytes, input_length_basis,
  output_bound, output_bound_enforced, reasoning_included, cache_policy,
  input_category, output_category, currency, input_rate_usd_per_million,
  output_rate_usd_per_million.
* Frontier: active_slots, reservation_usd.
* Result: schema, status, error_codes, metadata_only, authorizes_dispatch,
  authorizes_later_stage.

Schema tags: plan `context-t1-preflight-plan/v1`, expected
`context-t1-preflight-expected/v1`, result `context-t1-preflight/v1`.
Both inputs require scope `SYNTHETIC_ONLY`. Identifiers are ASCII
`[A-Za-z0-9][A-Za-z0-9._-]{0,63}`; digests are exactly 64 lowercase hex characters.
Every session AND run is a canonical lowercase, nonzero UUID-shaped string;
all twelve are distinct (including session/run cross-collisions). UUID spelling
is checked, not runtime freshness, version provenance or session allocation.

Settings are identical to expected within each family; only slot and fresh IDs
vary between that family's three slots. Per-slot root/claim/output states must
all be IDLE/ABSENT/ABSENT; used, unknown or inconsistent state refuses. No root
path is accepted or inspected. The plan's IDs, pins, window and evidence equal
the supplied expected reference byte-value-for-byte-value after strict decoding.
No cryptographic authenticity or on-disk pin correspondence is established.

| Family | Slots | provider | model | route | auth_mode | credential_policy | output_bound_mode | cache_policy |
|---|---|---|---|---|---|---|---|---|
| A | A1,A2,A3 | anthropic | claude-opus-5-5 | anthropic-oauth-named-token | oauth | named-token | request_limit | no_cache |
| B | B1,B2,B3 | openai | gpt-6.1-sol | openai-codex-oauth | oauth | Codex | documented_max | cached_input_at_most_base |

`credential_policy` names a policy, NEVER a token/name/selector. Neither family
accepts credential fields. No `openai_codex` alias. Both families require currency
USD, input_category base, output_category all_output_including_reasoning,
input_length_basis final_serialized_input_utf8, and literal booleans
output_bound_enforced=true and reasoning_included=true. `body_bytes` is the
DECLARED final serialized model-visible input UTF-8 byte LENGTH, including all
framing/instructions, not prompt length. `body_sha256` is only its declared pin.
`output_bound` is the declared enforced reasoning-inclusive count, not observed
usage. Both positive integers are bounded by 1,000,000,000. B's documented_max is
not an unsupported max_output_tokens request field. Cache/category/maximum/rate
or reasoning uncertainty refuses; the policies and evidence do not verify those
behaviors. A's no_cache is the candidate's asserted known no-cache category, not
permission to ignore surprising cache use in a future actual call.

Each evidence state is exactly COMPLETE, with a digest and a valid finite UTC
coverage interval containing the entire plan window. UTC strings (including
now_utc) are exactly YYYY-MM-DDTHH:MM:SSZ, real Gregorian dates, no fractional
seconds, offset alternatives or leap seconds. Require start < end and
start <= supplied now < end. There is no clock read or timezone/environment use.

Prices: exact finite nonnegative DECIMAL STRINGS only. Rates match
`(?:0|[1-9][0-9]{0,11})(?:\.[0-9]{1,24})?`; amounts use the same grammar with
up to 30 fractional digits. No exponent, sign, whitespace, leading zeros,
underflow, NaN, Infinity, float/numeric rate or coercion. Zero is allowed only
when EXPLICITLY supplied, never as a default for unknown. Decimal computation
uses an independent 96-digit context trapping rounding/inexact/overflow; input
bounds make this sufficient even for six sums. Caller Decimal context cannot
change an answer or be changed by a call.

Exact reservation per slot:
`(body_bytes * input_rate + output_bound * output_rate) / 1000000`.
Each claimed reservation equals that value, six-slot total equals their sum,
and frontier reservation equals the sum for its named slots. Every computed AND
claimed individual <= 5, total <= 30, active <= 10. Exactly six slots A1-A3/B1-B3
once, in any order. Frontier is a hypothetical proposed active set, NOT a claim
that slots have already been sent: zero to two distinct existing slots, at most
one of each family. All six still need IDLE metadata. An actual in-flight/used
slot is rejected, not reconciled or cleared. Active and total caps are partly
redundant mathematically with six slots/two active and <=5 each; they are checked
explicitly anyway, INCLUDING independently supplied aggregate claims. Rejection
of a redundant over-cap case is not evidence of a runtime scheduler.

## Strict decoding and deterministic refusal precedence

Exact bytes inputs only (not str, bytearray or subclasses). Decode UTF-8 strictly;
reject BOM via JSON syntax, lone surrogate escapes, duplicate decoded object keys
at any depth, nonfinite tokens, all JSON float/exponent tokens, and malformed or
trailing JSON. JSON integer token magnitude <=1,000,000,000, <=10 digits excluding
minus; later integer fields reject bool, zero, negatives and all coercion. Decoded
metadata has depth <=16 (root depth zero), <=4096 value nodes and <=512 characters
per string/key. Resource/depth refusal is finite, not a raw parser exception.

First refusal only, from this finite code enum:
INPUT_TYPE, INPUT_SIZE, UTF8, JSON_SYNTAX, DUPLICATE_KEY, NONFINITE, JSON_NUMBER,
NUMBER_BOUND, JSON_LIMIT, FIELDS, SCHEMA, IDENTITY, TYPE, UTC, WINDOW, EVIDENCE,
ROUTE, SETTINGS, PRICE, BINDING, SLOTS, UUID, UUID_REUSE, USED_SLOT, DRIFT,
TOTAL_CAP, SLOT_CAP, FRONTIER, ACTIVE_CAP, RESERVATION.

Order: decode plan then expected; parse now; validate expected shape/IDs/pins,
window/evidence then A/B settings; validate plan shared shape/IDs/pins,
window/evidence and compare shared bindings; validate six-slot list and each slot
(shape/slot-family/IDs/settings/state/expected-settings), then completeness; parse
total/frontier, validate frontier membership/count/family; check total cap,
individual caps, active cap; check exact individual/total/active arithmetic.
Nested shape checks precede their value checks. METADATA_PASS has empty codes;
REJECT has one enum code. All outputs have metadata_only=true and both
permission flags false, with no other fields or input echo.

## Frozen known-answer table (before module/test implementation)

All fixtures are freshly authored toy metadata, never copied real #194 data,
sealed controls, SDK requests, prompts, labels, answers or credentials. Base:
now 2001-01-01T00:10:00Z; window 00:00:00Z..01:00:00Z that day; evidence covers
that window. IDs synthetic-experiment/synthetic-binding, toy hex digests, twelve
distinct toy UUIDs. All six body_bytes/output_bound=1000, both rates="1",
slot="0.002", total="0.012", frontier=[A1,B1]/"0.004". No request body exists.
The following table is exhaustive by case ID plus the defined cross-products.
Every case also checks result closure, permission flags and no content output.
Core rows name exact error code; closure cross-products require REJECT and one
frozen enum code without prescribing the first nested-shape code.

| IDs | Synthetic change | Expected |
|---|---|---|
| P01 | Base six slots/two families/two frontier members | METADATA_PASS |
| P02 | Empty frontier, active reservation 0 | METADATA_PASS |
| P03 | One frontier member A2, active 0.002 | METADATA_PASS |
| P04 | Each body/output=1000000, rates 2/3, reservations 5,total30,active10 | METADATA_PASS |
| P05 | Both rates explicitly 0, all reservations/total/active 0 | METADATA_PASS |
| P06 | All body/output=1, input rate 0.123456789012345678901234, output 0; slot0.000000123456789012345678901234,total0.000000740740734074074073407404,active0.000000246913578024691357802468 | METADATA_PASS |
| P07 | Reverse slot order, retain frontier names | METADATA_PASS |
| P08 | now exactly window start | METADATA_PASS |
| P09 | now one second before window expiry | METADATA_PASS |
| P10 | Different toy binding/pins/IDs in both inputs consistently | METADATA_PASS |
| N01,N02,N03 | Plan str/bytearray/subclass-of-bytes | INPUT_TYPE |
| N04 | Expected str | INPUT_TYPE |
| N05,N06 | Plan/expected 65537 bytes | INPUT_SIZE |
| N07,N08 | Plan/expected invalid UTF8 | UTF8 |
| N09,N10,N11,N12 | Truncated/trailing/BOM/empty plan JSON | JSON_SYNTAX |
| N13,N14,N15 | Duplicate top key/nested key/escaped-equivalent key | DUPLICATE_KEY |
| N16,N17,N18 | NaN/Infinity/-Infinity JSON token | NONFINITE |
| N19,N20 | Fraction/exponent JSON number token | JSON_NUMBER |
| N21,N22 | 11-digit integer/1000000001 integer | NUMBER_BOUND |
| N23,N24,N25 | Depth17/>4096 values/string513 | JSON_LIMIT |
| N26,N27 | Lone surrogate value/key | UTF8 |
| N28,N29 | Top plan array/null | FIELDS |
| N30,N31 | Wrong plan schema/scope | SCHEMA |
| N32,N33 | Invalid/zero UUID | UUID |
| N34,N35,N36 | Repeated sessions/runs/session-run collision | UUID_REUSE |
| N37,N38,N39,N40 | Missing/repeated/extra slot/wrong slot-family | SLOTS |
| N41,N42,N43,N44,N45,N46 | A provider/model/route/auth/policy/bound-mode wrong | ROUTE |
| N47,N48,N49,N50,N51,N52,N53 | B provider/model/route/auth/policy/bound-mode/registry alias wrong | ROUTE |
| N54,N55,N56 | B token/A selector/unsupported B output request field | FIELDS |
| N57,N58,N59,N60,N61,N62,N63 | Unknown cache/input category/output category/length basis/unenforced bound/reasoning false/currency | SETTINGS |
| N64,N65,N66,N67,N68 | Body bool/output bool/zero body/negative bound/body overbound | TYPE,TYPE,TYPE,TYPE,NUMBER_BOUND respectively |
| N69,N70 | Within-family body pin/rate drift (slot only) | DRIFT |
| N71,N72,N73,N74 | Binding/pins/window/evidence drift (still well-formed) | BINDING |
| N75,N76,N77,N78,N79,N80 | Stale/future/reversed/zero window/bad date/non-Z now | WINDOW,WINDOW,WINDOW,WINDOW,UTC,UTC respectively |
| N81,N82,N83 | Evidence UNKNOWN/short coverage/expired coverage | EVIDENCE |
| N84,N85,N86,N87,N88,N89,N90,N91,N92,N93 | Rate null/JSON float/UNKNOWN/NaN/Infinity/negative/exponent/25 fractional digits/leading zero/whitespace | PRICE,JSON_NUMBER,PRICE,PRICE,PRICE,PRICE,PRICE,PRICE,PRICE,PRICE respectively |
| N94,N95,N96 | Incorrect slot/total/frontier reservation arithmetic | RESERVATION |
| N97 | Each body/output=1000000; A1-A3 and expected A rates 3/3, compute/claim6; B1-B3 and expected B rates 0.5/0.5, compute/claim1; total21,frontier7 | SLOT_CAP |
| N98 | Six slots compute/claim6,total36,frontier12 | TOTAL_CAP |
| N99 | Individually valid base, declared total30.000001 | TOTAL_CAP |
| N100 | Individually valid base, declared active10.000001 | ACTIVE_CAP |
| N101,N102,N103,N104 | Three frontier slots/repeated member/same-family overlap/unknown member | FRONTIER |
| N105,N106,N107,N108 | Used root/claim exists/output exists/unknown root | USED_SLOT |
| N109 | Lossy numeric rate integer rather than decimal string | PRICE |
| N110 | Sub-precision rate (31 fractional zeros then1) | PRICE |
| N111 | Lowercase unknown bound mode | ROUTE |
| N112,N113 | Expected duplicate key/nonfinite token | DUPLICATE_KEY,NONFINITE |
| N114 | Amount has31 fractional digits | PRICE |
| N115,N116 | Null now/bad now type | UTC |
| N117 | now exactly expiry | WINDOW |
| N118 | Evidence coverage reversed | EVIDENCE |
| N119 | Oversized 5000-digit JSON integer | NUMBER_BOUND |
| N120 | Parser recursion-depth overflow | JSON_LIMIT |
| N121 | Unknown evidence name (complete otherwise) | FIELDS |
| N122 | Noncanonical uppercase UUID | UUID |
| N123 | Expected families includes C | FIELDS |
| N124 | No slots (empty list) | SLOTS |
| N125 | Slot settings includes registry_alias | FIELDS |
| N126 | Slot body null | TYPE |
| N127 | Explicit reservation null (never defaults to zero) | PRICE |
| N128 | Incorrect reservation as bool | PRICE |
| N129 | N97's settings (A1-A3 compute6, B1-B3 compute1, total21, frontier A1+B1 7) but every slot claims1, total claim6, frontier claim2; only the computed side is over a cap | SLOT_CAP |
| N130 | N98's settings (six slots compute6, total36, frontier12) but every slot claims5, total claim30, frontier claim10; only the computed side is over a cap | TOTAL_CAP |
| N131 | Individually valid base but A1 claims6, total claim6.010, frontier claim6.002 (A1 in frontier); only the claimed side is over a cap | SLOT_CAP |

Closure cross-products C: for EVERY object instance in the base plan and expected
(root, pins, window, evidence container, EACH evidence record, families container,
EACH family/slot settings, EACH slot, frontier), independently remove EACH required
field, set EACH to null, and replace EACH with a wrong JSON type (string->array,
integer->string, boolean->integer, object->array, array->object); also independently
add one unknown field to EACH object. Reset to pristine base before every case.
Object inventories come from the frozen schema, not the module. Every C case is
REJECT. Array-valued frontier/slots members receive the explicit core negatives;
null/extra/missing slot fields are also covered per slot by C.

Additional harness assertions H (not additional provider trials):
H01 schema closure/required parity and exact field inventories/constants/enums;
H02 independent schema structural validation of P01..P10 and rejection of C;
H03 AST import allowlist json,re,datetime,decimal only, no dynamic import, I/O,
process, environment, network or existing T1 dependencies;
H04 runtime tripwires on filesystem/environment/network/process entry points,
captured stdout/stderr, unchanged supplied bytes/reference objects;
H05 P06 and a negative under caller Decimal precision2/traps, unchanged context;
H06 compile/execute the verified literal module bytes directly in a fresh isolated
process, bind module/schema/document SHA256s and paths (never rely on -B alone);
H07 repeated positive call is deterministic and non-authorizing; canary strings
in malformed metadata never appear in output. Source/schema contract hashes must
match CLI pins before any test runs; mismatch preserves a harness failure.

## Single final command and reporting

After ALL edits, use existing /usr/bin/python3 and stdlib unittest, no dependencies:
`/usr/bin/python3 -I -B /home/shinelay/temper-ai-arch-d0-preflight-v1/tests/test_architecture/test_context_t1_preflight.py --module-sha256 <actual> --schema-sha256 <frozen> --contract-sha256 <frozen>`

The test harness reads only these new candidate files and its own synthetic
objects, checks the pinned bytes, compiles the module bytes directly, and reports
the core/C denominators and unittest outcome. No pytest collection/conftest,
full suite, cache-based import, server, DB, browser, provider or real packet.
Do not run tests, import candidate code or execute validation examples before
this final command. If it fails, preserve original status/output, write a finite
correction hypothesis/MISSING disposition in the private report, and stop.
Read-only source/schema review and bounded Git/hash checks are not suite reruns.

Private report binds actual base/worktree/branch, this freeze, file hashes and
uncommitted diff, exact command/status/denominators, first misses and remaining
whole-M06/real-admission gaps. Cost actual if available, otherwise UNKNOWN; no
quota/headroom inference or memory/budget writes. Candidate, once landed on
master after HOME review; not accepted; gives no dispatch, registration or
later-stage authority; no promotion or stage/criterion acceptance.

## Revision note (2026-10-23, Architecture #214, H-D0-N97-3)

Row N97 was revised in place to match the test fixture fixed in #212 under
H-D0-N97-2. The old row, verbatim:

    | N97 | One slot computes/claims6, others1,total11,frontier7 | SLOT_CAP |

Reason: the frozen N97 also tripped DRIFT first (A1 alone at rates 3/3, its
family A at 0.5/0.5), so #200's run returned DRIFT, not SLOT_CAP. Known answer
unchanged: SLOT_CAP. This contract is still an uncommitted candidate, so the
row is revised in place; this note keeps its history.

## Revision note (2026-10-23, Architecture #224, H-D0-CAPS-1)

Rows N129, N130 and N131 were added after N128. #220's independent land check
(LAND FALSE, M1) switched off the computed side of SLOT_CAP (bite 3) and of
TOTAL_CAP (bite 11), and every case still passed: N97 and N98 claim exactly what
they compute, so either side refuses them alone. SLOT_CAP's claimed side had no
case of its own either (bite 4, #220 S1). Each new row's first refusal comes from
one side of one cap only; with that side off, a later check reports another code:

* N129, SLOT_CAP computed side only: A1-A3 compute 6 but claim 1. With that side
  off: RESERVATION.
* N130, TOTAL_CAP computed side only: computed total 36, total claim 30. With
  that side off: SLOT_CAP.
* N131, SLOT_CAP claimed side only: A1 computes 0.002 but claims 6. With that
  side off: RESERVATION.

ACTIVE_CAP's computed side gets no row: two active slots of at most 5 each total
at most 10, and SLOT_CAP runs first, so it can never refuse first. Frozen core
now 141 (10 positive, 131 negative); closure 1152; total 1293. No earlier row's
known answer changed, and the module is unchanged. The contract sha256 before
this revision was 4b1c141a9e2f683538d2b93633c5e1e972ff626b50b1d7c0ebd2df456749e0bc.

The trust-boundary line under H-D0-META-1 and the last paragraph of "Single
final command and reporting" were reworded in place (#220 S6), so they stay true
once these files land on master. The old lines, verbatim:

    Candidate private worktree only; no commit, land, registration, workflow, API,
    provider, root allocation, claim, real evidence access, dispatch or activation.

    quota/headroom inference or memory/budget writes. Leave private/uncommitted for
    HOME review; no promotion or stage/criterion acceptance.
