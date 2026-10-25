# Candidate raw capture and snapshot adapter (T1)

This is an **unwired, source-only** implementation of the [v1 contract](candidate-admission-contract.md).
It does not install admission, authorize execution, allocate or verify custody, read deployment configs,
change access, or enable a start route. Only `external-db-fresh` is prospective. Classified capture is
an identity API, **not a classified launch**. Normal loader/store behavior remains unchanged.

## Hypothesis

H-T1-RAW-1, written before implementation: capture before transformation, immutable closure ownership,
and complete typed comparisons against independently supplied authority should make substitutions,
alias mutation, ordinary reloads, missing/extra references and changed fields refuse. Any changed
source/config/field/reference accepted as its original, or self-generated expectations passing as
independent authority, falsifies this. Tests use only owned synthetic rows/files and handwritten
raw/effective literals. No provider, model, script or native attempt is run.

## Capture and ownership

`ConfigStore.get_raw_record(name, config_type, *, transaction) -> (dict, str)` requires the caller's
active SQLModel Session transaction. It selects `Config.config` and the separate `schema_version`
as columns, not an ORM identity-map object. Postgres uses a shared row lock; SQLite uses its existing
transaction. It canonicalizes and copies while still in that transaction. No session is opened,
committed or closed by this method; it never substitutes, invents authoring YAML or falls back to
classified files. The caller owns the transaction's lifecycle, isolation and authorization.

`RawCapture(codec, authority, store).capture(descriptor, *, transaction) -> tuple[RawRecord, ...]`
revalidates the descriptor against **separate** `DescriptorAuthority`, reads the exact ordered
inventory, and checks every raw identity. Existing classified guard activation refuses DB capture.
`SnapshotResolver(codec, descriptor, records, *, authority)` owns the codec's complete closed
`RawClosure`. Its loader-compatible `get(name, config_type)` parses fresh immutable bytes each time.
There is no backing store, fallback, mutable mapping alias or lookup outside the closed inventory.

`capture_classified_record(codec, *, guard, name, config_type, launch_id)` requires the actual active
`Guard`. `Guard.raw_config_record` uses only bytes read/verified by existing guard activation; no
reopen or new access occurs. It rechecks the retained classified path/config inventory and Git blob
identity, so mutating its public mapping cannot replace identity. The adapter rejects duplicate
keys, all YAML aliases (even scalar aliases), non-string keys and non-JSON values, and retains the
existing size/depth/node limits. It derives `config_json` from those **same** bytes. Origin also binds
byte SHA256, Git blob SHA1, relative path and the already-authorized caller's launch label. Neither
that label nor a hash is authority. No DB fallback is possible on a parse/access/source refusal.

## Candidate-only load and complete projections

```python
source_inventory(*, engine_commit: str, engine_tree: str,
                 request_fields: tuple[str, ...]) -> FrozenJSON
load_candidate(codec, descriptor, closure, *, authority, source)
    -> tuple[list[Node], WorkflowConfig, FrozenJSON]
project_graph(nodes, workflow, *, source) -> FrozenJSON
project_node(config, *, source) -> FrozenJSON
project_agent(config) -> FrozenJSON
```

The source assembler is **not source discovery**. The ingress/restore adapter supplies measured
installed Git commit/tree and its actual request-field inventory, never values copied from the
candidate descriptor. T1 checks the full supplied source against independent authority and current
workflow/node/native inventories. Authentication and trust in the installed-source measurement are
external responsibilities; synthetic sibling facts in unit tests are not installed-source evidence.

Before ordinary parsing can discard information, raw validation rejects unknown keys, wrong exact
types (including bool as int), unsupported schema, substitutions, noncanonical refs, cycles,
unreachable extra records, dynamic topology/template nodes and nested start capability. Canonical
refs are `agents/<name>`, `stages/<name>`, `workflows/<name>`; no bare/singular/basename alias and no
stage-to-workflow fallback. Workflow-as-stage refs reject workflow-only policies that cannot survive
that conversion. Static stages, ScriptAgent and single_call are supported. No global token/model
value rule is added; ordinary noncandidate loaders keep their structural semantics.

The script exception applies **only** to the exact `script_template` field of a script record,
whose template bytes and variables are independently pinned. It allows named scalar metadata
interpolations and ScriptAgent's existing `env` filter, not general Jinja or `${...}`. Identical text
in another raw key is not exempt. These are pre-execution structural checks; actual script-variable
provenance, renderer-bound inputs and use-time comparisons belong to T3.

A fresh snapshot-only GraphLoader resolves the actual nodes. Ref-resolved WorkflowConfig/stage
configs contain the actual resolved child configs rather than stale refs. The complete projection
includes **every dataclass field**, policies, nulls, nested nodes, preorder paths, registered actual
factory classes and complete effective agent mappings, including all native optional values.
Inherited script metadata stays present. `_KNOWN_FIELDS` alone has the contract's special projection:
actual exact `frozenset[str]`, complete accepted-key membership, then a sorted string array. Raw lists,
sets, omitted members, candidate-supplied fields and every other non-JSON value refuse. All other
values preserve exact JSON type and optional absence. No generic coercion or dropped field is used.
The entire graph must equal independent descriptor expectations, not expectations derived from raw
configs or the loader. The returned objects may be mutable for existing execution; the snapshot and
returned projection own immutable bytes. T3 must recheck actual objects before every use.

## Context and composition boundary

`ExecutionContext.admission: CandidateInvocationBinding | None = None` is optional and has a lazy
runtime type check, avoiding the config/database/shared import cycle. Its value is frozen and owns
immutable descriptor/closure/expected bytes. `dataclasses.replace` preserves it. T3 must derive the
actual child path rather than treat a parent's inherited binding as child authorization. Context and
public dataclass construction are data, not unforgeable capabilities.

T2 owns entry routing, transaction install/restore and protected transport; T3 owns scheduler,
factory, script, readiness and native same-fd checks. They can compile against these interfaces with
synthetic sibling adapters. Real composition and independent-oracle validation belong to V1. No
source-only check claims admission/binding-MET, actual custody, landing, deployment or a hold waiver.
Separately approved labelled infrastructure re-attempts use fresh descriptors and slots; this code
neither resends a consumed slot nor replaces a malformed answer.

## Tests and operation

The opening combined test is in `tests/test_database/test_admission_capture.py`: uncommitted raw
capture → closed snapshot → actual resolved projection → immutable context replacement, then
rollback/alias mutation and independent repeat parsing. This existing database-tier directory runs
on SQLite locally and Postgres in CI. `tests/test_config/admission_cases.py` is a separate handwritten
literal oracle; it uses only ordinary JSON and hashlib for identities. It does not call production
normalization to construct expected semantics. Dedicated tests cover raw/effective/source/ref/type/
script/guard mutations and demonstrate disabled-boundary failures in memory. Existing legacy tests
remain. Only metadata refusal codes escape; rejected values and parser traces are not exported.

Run with the locked environment, SQLite locally; mandatory exact-head remote Postgres and all other
required checks remain. No second Temper, local Postgres/browser, provider call or live-store read is
needed. This document describes source interfaces, not a passing CI or deployment receipt.
