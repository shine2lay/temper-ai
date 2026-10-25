# Candidate admission wire v1

Status: **inert source contract**, not an enabled start route, custody receipt,
registration or binding-MET result. No existing importer calls this module.
The single wire shape authority is
[`schemas/candidate-admission-v1.schema.json`](schemas/candidate-admission-v1.schema.json).
`temper_ai/config/admission_contract.py` interprets those pinned bytes and adds
these normative byte, trust and relational constraints; it does not carry a
second object-shape schema. A schema-only check is insufficient admission.
Schema/version changes require a new reviewed artifact and pin; no network
schema resolution, extensions, defaults, coercion or permissive unknown fields.

## Hypothesis and delivery boundary

H-192-1 (before implementation): prose-only producers can disagree about wire
names, nulls, numeric types and expected digests. One engine-owned versioned wire
artifact, reference codec and independently handwritten literals should eliminate
that ambiguity. Cross-consumer disagreement, implementation-derived expected
answers or unspecified fields falsify it. Synthetic tests establish only the
contract; later raw/transport/use implementations must prove their own guards.

Architecture supplies the externally fixed semantic descriptor and independent
oracles. This codec must **not** generate those answers from candidate configs.
The compiler consumes this schema; it must not publish a competing schema.
The fixtures are deliberately tiny, synthetic and not runnable engine configs.
They do not replace an independent complete graph/native position inventory.

## CAJ-1: exact canonical bytes

CAJ-1 is deliberately named, not advertised as RFC 8785 or Python's ordinary
`json.dumps(sort_keys=True)` floating-point encoding.

* UTF-8 without BOM, newline, indentation or insignificant whitespace. Objects
  sort keys by Unicode scalar-value sequence (not UTF-16, locale or NFC).
  Arrays retain order. No Unicode normalization. Lone surrogates refuse.
* Strings use JSON double quotes. Escape quote and backslash; use `\b`, `\f`,
  `\n`, `\r`, `\t` for those five controls and lowercase `\u00xx` for the
  other U+0000..U+001F characters. Other scalar values are literal UTF-8; do not
  escape slash, DEL, U+2028 or non-ASCII text.
* Null and booleans are `null`, `true`, `false`. Integers use signed base-ten,
  no leading zeros or plus sign. Zero is `0`.
* Floats are **finite IEEE-754 binary64**. Print the exact real value of the
  binary64 number in ordinary base-ten decimal (no exponent), remove trailing
  fractional zeros, and retain `.0` if the fraction would disappear. Preserve
  negative zero as `-0.0`. E.g. 1.0 is not 1; 0.5 is `0.5`; the binary64 nearest
  0.1 is `0.1000000000000000055511151231257827021181583404541015625`.
  This is reproducible with exact integer arithmetic on sign/exponent/mantissa
  (or Python `Decimal.from_float`, not the current decimal precision context).
  NaN and infinities refuse, including overflow while parsing exponent input.
* Reference in-memory input accepts only exact built-in dict/list/str/int/float/
  bool/None types. No mapping adapters, bool-as-int, Decimal, enums, tuples,
  bytes values, custom subclasses, cycles or repeated mutable container aliases.
  The API wire itself is exact `bytes`, not mutable bytearray/memoryview.
* Duplicate object keys refuse, before any normalization. Decode followed by
  re-encode must equal the input bytes. Thus `1e0`, `-0`, escaped non-ASCII,
  extra whitespace and alternate key order are not canonical wire encodings.
  Parsed results are fresh objects; frozen contracts own only immutable bytes.

JSON Schema's mathematical `integer` cannot distinguish `1` from `1.0`; the
normative CAJ-1 exact-type check additionally requires the former for integer
fields. Standard schema validators check shape, not that byte-level condition.
`*_json` fields are **strings containing CAJ-1 objects**; byte comparison uses
UTF-8 of their string value, not JSON re-rendering that loses numeric types.
They preserve every nested key/type/value. At the wire level every property is
required. The only nullable fields are `rawRecord.file_base64`, node `factory`,
position `root_policy`, and dispatch `previous_nonce`/`worker_label`. Absence is
never null. Inside raw/effective JSON, absence and null remain distinct and are
not filled by the codec. Raw policy and exact effective-default construction
belong to T1, not global loader changes.

## Digest domains and identity

All SHA-256 fields are exactly 64 lowercase hex digits; Git SHA-1 identities
are exactly 40. For each `DigestDomain D`, digest bytes are exactly:

`SHA256(UTF8("temper-admission/v1") || 0x00 || ASCII(D) || 0x00 || CAJ1(payload))`

Domains/payloads:

| Domain | Payload |
| --- | --- |
| `descriptor` | Complete descriptor object |
| `source` | Complete descriptor `source` object |
| `raw-record` | Object containing exactly kind, name, schema_version, origin, config_json |
| `raw-closure` | Array of complete raw-record objects, ordered by (kind, name) |
| `graph` | Complete descriptor graph, including factories/per-node config |
| `immutable` | Complete persisted immutable section |
| `readiness` | Complete one readiness receipt |

No digest field hashes itself. File/template hashes are the ordinary undomained
SHA256 of **exact file bytes** / UTF-8 template bytes. Git file identity is
`SHA1(b"blob " + ASCII(decimal byte length) + b"\0" + exact file bytes)`.
No digest, canonical string or label authenticates itself.

DB origin is exactly `{"kind":"db"}`. Capture original `Config.config` JSON
**before** substitution plus its separate schema_version in one transaction.
Do not infer nonexistent original YAML. Its required file_base64 is null.
A classified-file origin separately binds authorized launch id, canonical
relative path, exact file hash and Git blob identity. file_base64 is padded
standard RFC 4648 base64 with no whitespace; it must round-trip byte-for-byte.
The codec checks the hashes but deliberately does not parse YAML; a future
classified adapter must attest that config_json came from these checked bytes,
with duplicate/alias policy and the existing classified guard, never a DB
fallback. The raw-file codec is **not** a supported classified start mode.
Authoring-file hashes are not substitutes for DB identity.

Paths use `/`, no empty, `.` or `..` components, no NUL, no trailing slash;
absolute paths start `/`, relative file names do not. Node paths are arrays of
canonical names, never ambiguous dotted strings. Snapshot keys are ordered
unique `(kind,name)`, kind one of workflow/stage/agent. The closure must equal
the descriptor inventory exactly, including the named workflow; no extra or
missing record. `RawClosure.get` returns a fresh parse and refuses absent keys.
It is not yet the production loader adapter.

## Trust and complete effective expectations

`DescriptorAuthority(expected_descriptor_sha256, expected_source_sha256,
authorized_caller_label, receipt_id)` is obtained **out of band** from the
existing authorized caller. It is never decoded from candidate wire or derived
by hashing the just-submitted candidate as its own expected answer. The codec
requires exact descriptor/source matches. Authority labels record origin,
not an access grant; authentication, persistence integrity and receipt checking
remain external responsibilities. Public dataclass constructors are not secret
capabilities. Adapters revalidate untrusted values with ContractCodec.
Changing both candidate and its claimed digest without changing the trusted
out-of-band pin refuses. Replacing the authorized caller is outside this test,
not a passing negative control.

`logical_run_id` is an experiment identity. `execution_uuid` is a separately
preselected canonical lowercase UUID; T2 must atomically reject collisions and
store that exact identity, never substitute a new UUID or trust user run_id.
It is not the native invocation UUID. Inputs, workspace and complete request
options are frozen, not caller-overridable defaults.

The source tuple is engine commit/tree, binding ABI and sorted exact field-name
inventories for workflow/node/request/native. The workflow_json has exactly the
workflow inventory, each node_json exactly the node inventory, and request
options exactly the request inventory. All effective dataclass fields, including
defaulted values, scheduler policies and nested nodes, must appear. In the
current source, `_KNOWN_FIELDS` is a class inventory rather than runtime data:
exclude it from the projection, but bind its exact members in the source node
inventory; T1 must fail on inventory/dataclass field drift. No guessed omissions.
The native inventory is the permitted full field-name set; each actual per-call
config preserves its exact present field set (optional absent != null).

The graph has a complete workflow_json plus a preorder node inventory. Each
node_json must match the corresponding recursive workflow node exactly. Stage
factories are null; agent factories pin full qualified class_name, type and
entire effective agent config, not just selected native keys. v1 handles only
stage, script and single_call node shapes. T1 still validates real engine types,
references, markers, defaults, prohibited raw fields and exact source inventory;
synthetic inventories cannot masquerade as a current production source pin.

Every single_call path has exactly one position, with explicit record/variant/
call identities, preparation path, slot, full agent config and root policy.
Preparation paths name admitted scripts. Every script has exact template bytes,
template hash and full canonical variables. Renderer safety/provenance remains
T1/T3 work, never granted by this shape check. The compiler keeps the independent
literal 14x3 expectations; it cannot derive correctness from this parser.
Repeated slots across different roots are permitted; duplicate root+slot pairs
are not. The root_policy may be null **only as unresolved source data**;
`require_custody` refuses it before installation/execution. Non-null policies
are externally accepted facts, not inferred mounts, ownership or permission.

## Protected transport, generation, readiness and rollback

Reserve `WorkflowRun.spawner_metadata["config_admission"]`. No record is written
by this module. The eventual adapter owns these transitions:

1. `install`: in the run creation transaction, verify authorized origin, required
   candidate classification, source/current field inventories, closed raw capture,
   resolved graph, real accepted custody, fixed request and UUID collision.
   Persist the immutable section plus initial queued dispatch (attempt 0,
   fresh nonce, previous_nonce=null, worker_label=null, readiness=[]).
2. `restore`: parse the original record and original authority. Recheck all
   hashes and current source; never re-resolve a name from mutable configuration.
   Candidate recovery/replacement modes are refused in this initial profile.
3. `bind_dispatch`: atomic row compare-and-swap of original nonce/phase; queued
   -> running, fresh different nonce, previous_nonce=old nonce, attempt=1,
   actual worker label. No immutable/readiness changes. The pure transition
   checker checks a proposal only, not transaction atomicity.
4. `preserve`: ordinary queue/spawner metadata updates cannot erase/change any
   byte of the reserved slot. Typed transitions are separate. Check for reserved
   key in extras **before** merge, even when value is null or equal.
5. `bind_root_readiness`: only the engine's successful, exact admitted preparation
   NodeResult plus verified durable checkpoint provenance can propose a receipt.
   No initial_outputs or arbitrary workflow inputs. Bind exact preparation path,
   position, descriptor/graph/execution identity, nonce/attempt/checkpoint hash,
   no-follow root/parent/file stats, file hashes/lengths and durable=true. First
   valid write wins; identical repeated receipt is idempotent, change refuses.
   Preserve all other positions. Codec checks reference equality and root policy;
   T3 checks actual parent traversal, contents, fsync and checkpoint provenance.
6. `authorize_and_claim`: T2 serializes a current-generation row check **with**
   the supplied native exclusive-claim callback. T3 compares actual context,
   complete native config and current readiness, fstats the **same borrowed root
   fd** and no-follow parent traversal that native operations will use. Never
   stat(path) then reopen. Hold the fence until callback finishes; callback only
   creates the existing exclusive claim, not a network/model send. A stale
   worker gets no claim. Existing consumed claims and single-send/caller/read
   checks stay untouched. Do not claim protection from a hostile DB administrator.

Readiness measurements are numbers/labels, not synthetic custody proof. File
length is exact bytes, modes are integer POSIX permission+special bits (0..4095),
not octal strings; directory and file policy comparisons remain separate. Device,
inode, uid/gid and nonnegative attempt are exact integers, never booleans.

`require_admission(designated_candidate, has_record, supported_code)` preserves
ordinary noncandidate structural behavior only when no record is present.
Missing required candidate admission refuses. Any admitted record presented to
unsupported code refuses rollback, even when the workflow is renamed or no
longer designated. A rollback release must retain a pre-load tombstone/fence;
old code incapable of recognizing the slot must not run pending admitted rows.
Never delete protected metadata and reload by workflow name. Digests are not
row signatures: protected writer installation and a rollback migration/fence
are mandatory T2 work, not accomplished by these JSON bytes.

## Mode and interfaces frozen for the next pieces

Only `external-db-fresh` is a **contract-supported prospective mode**, based on
the existing external DB-backed submit/queued worker path. Nothing is enabled.
Resume, fork, rerun, replacement/recovery, sealed start, direct/inprocess/CLI,
preview and cleanup-as-execution are unsupported candidate modes and must fail
before transformed load. `require_mode` accepts exactly the one token, rejecting
all other strings and types. Ordinary noncandidate modes are unchanged. This
preserves the first-batch no-recovery decision without building new routes.

Public interfaces (exact Python declarations are in the module):

* `ContractCodec(schema_bytes: bytes)`; `descriptor(data, authority)` ->
  ApprovedCandidateDescriptor; `raw_record(data)` -> RawRecord;
  `closure(descriptor, tuple[RawRecord,...])` -> RawClosure;
  `record(data, authority)` -> AdmissionRecord; `readiness(data)` -> RootReadiness.
* `canonical_bytes(value) -> bytes`, `decode_canonical(bytes) -> Any`,
  `digest(DigestDomain, bytes) -> str`; only canonical payloads hash.
* `RawCapture.capture(descriptor, *, transaction) -> tuple[RawRecord,...]`;
  `SnapshotResolver.get(name, config_type) -> dict`. T1 adapts this to the loader.
* `AdmissionContext.admission -> CandidateInvocationBinding | None` plus
  read-only run_id, node_path, workspace_path. T1 alone adds the optional context
  field in shared/types.py and propagates it with dataclasses.replace.
* `AdmissionTransport.install`, `restore`, `preserve`, `bind_dispatch`,
  `bind_root_readiness`: T2, own transaction/CAS implementation.
* `AdmissionUseHooks.check_graph`, `invocation`, `check_script`,
  `authorize_and_claim`: T3. The last receives OpenedRoot and a narrow claim
  callback, not permission to perform arbitrary work. OpenedRoot never owns or
  closes the fd. Binding paths, bytes, dispatch and expected configs are frozen.

T1 raw capture/resolver/context can start from this contract independently of
T2 protected transport/entry routing and T3 use-site/same-fd checks. Each uses
synthetic adapters for the other two; integration depends on all three actual
implementations plus Architecture's separately authored oracle. All retain
normal plan/review/landing gates. No shared consumer file changes in this piece.

## Refusals, tests and consumption

`AdmissionRefused.code` is a closed `RefusalCode` enum; `str(exc)` is only that
constant. Do not export rejected values, parser exception objects/chains, script
inputs or model-bound content. Refusal order is first failed check, not a claim
that every other invariant passed. `wire_schema` covers shape/unknown key;
`unsupported_version`/`unsupported_mode` fence route/version; other codes name
canonical/type/alias/numeric, digest/origin/authority/source/field-set, closure/
graph/position, protection/generation/readiness/custody, rollback/missing and
outside-closure failures. New codes require a reviewed contract change.

Import by ordinary package in an engine adapter, or by `importlib` file location
for a source-only compiler (register module in sys.modules before exec for
standard dataclass support). The latter avoids config/__init__ importing the
ordinary store. Neither codec nor protocols import providers or do any I/O.
Provide the schema bytes explicitly; they must match SCHEMA_SHA256. Schema loads
are caller-controlled and cannot fetch a URL. A consumer must implement both the
shape and semantic rules, or call this codec, not accept schema-only results.

`tests/test_config/fixtures/candidate_admission_v1/` contains independently
handwritten literal inputs and fixed expected bytes/hashes/refusal codes.
Hashes are calculated from those literal bytes with standard-library hashlib,
not this codec. Tests may serialize **mutated inputs**, never manufacture expected
semantic answers with production normalization. The first test combines canonical
round-trip, authority/descriptor, closure, protected transport and fresh ownership.
Remaining controls target changed fields, types, absence/null, aliasing, domains,
origin, authority substitution and unsupported modes. No model/provider, real
config, DB service, credentials, file custody or live send is involved.
