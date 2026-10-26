# Authoring candidate-admission v1 descriptors (metadata-only compiler, A1)

**Candidate tool only.** It is not an engine adapter, registration, custody
proof, landing or permission to start anything. Accountable lead: Architecture.
The only descriptor and raw-record wire is Temper's
[candidate-admission v1 contract](candidate-admission-contract.md) with its
schema `docs/schemas/candidate-admission-v1.schema.json`. This tool publishes no
other schema; the authoring form below is a convenience input that maps one to
one onto that wire.

Tool: `configs/architecture/bin/context_profile_admission_compile.py`.
Tests: `tests/test_config/test_context_profile_admission_compile.py`.

## Fixed dependencies

| Input | Pin |
|---|---|
| Contract commit / tree (Temper #192) | `caf5c16f6d9965cbcbc8e10653d75e1c47b27340` / `726bf8e8a198f1436bf8caf84bbf2a8115601e47` |
| `docs/candidate-admission-contract.md` | SHA-256 `8932a4b97d0d08bea6a919223f83922804d08486545d94d747886253b5825ba7` |
| `docs/schemas/candidate-admission-v1.schema.json` | SHA-256 `426e1c5a12eafa5a82e64144d25e0fa08d5b844149723ea001a76fe9a0f2041d` |
| `temper_ai/config/admission_contract.py` (codec) | SHA-256 `f9b0f36ed20afaecd12654cd80a203214f3f2d5727f4668fc0c1926fa3df1c34` |
| Oracle #306 `admission_oracles/manifest.json` | SHA-256 `65c388386130b7707cb241be6e5ed59cbf5ebab403e7563051e038c34f696161` (commit `56b833e6`) |
| Oracle #316 `admission_oracles_v1_supplement/manifest.json` | SHA-256 `689771d91ffe15b4ba219a1fea45a81c1c1b55345623fed91997aa4990962374` (commit `7cedfa30`) |

The tool reads the schema and codec bytes once each, refuses
`compiler_contract_pin` if either differs, and only then executes exactly the
verified codec bytes (no second read, no bytecode cache). It never imports
`temper_ai` packages, config stores, providers or the engine.

## Authoring input

`--input DIR` must hold exactly two files (any JSON formatting; duplicate keys,
NaN and infinities are refused):

* `descriptor.json`: the v1 `descriptor` object **without** `records`, where
  each JSON-text member holds its JSON object instead of text:
  `metadata_inputs_json`, `request_options_json`, `graph.workflow_json`,
  `graph.nodes[].node_json`, `graph.nodes[].factory.config_json`,
  `positions[].agent_config_json`, `scripts[].variables_json`. A string there
  is refused (`compiler_input`), so nothing is double-encoded.
* `raw-records.json`: an array of v1 `rawRecord` objects whose `config_json`
  is the record's JSON object.

Everything else is the v1 wire exactly: `format`, `profile`, `mode`
(`external-db-fresh` only), candidate identity, logical run id, execution UUID,
workflow name, workspace path, the source tuple and its four sorted field sets,
the complete effective graph in preorder, all positions in order, all scripts in
graph preorder, `template_sha256`, and each position's explicit `root_policy`.

What the tool does: encodes each object with the codec's CAJ-1, sorts raw
records by `(kind, name)`, derives `records[]` (identity plus `raw_sha256`)
from the actual raw records, and validates everything with the pinned codec,
including the raw closure. What it never does: fill a missing field or default,
resolve references, read live configuration, environment values, a database or
the network, choose a source tuple or custody, or call the result runnable.

Metadata rules carried from the contract:

* `_KNOWN_FIELDS` is the only projection: an engine-owned `frozenset[str]`
  written as a sorted array of unique strings in effective workflow, node and
  inherited script-agent metadata. Anything else, or `_KNOWN_FIELDS` in a raw
  candidate config, is refused (`compiler_known_fields`).
* Exact types: `1`, `1.0` and `true` differ; `null` differs from an absent key.
  Optional native keys that are absent stay absent.
* Origins: DB records have `file_base64: null`. File records are checked by the
  codec (relative path, base64, file SHA-256, git blob), but a descriptor that
  names a non-DB record refuses `unsupported_mode` in `external-db-fresh`.
* Slot labels may repeat across distinct output roots; `(output_root, slot)` and
  `position_id` may not.
* `root_policy: null` is unresolved custody. It is reported, never filled.

## Authority (both modes)

`--authority FILE` holds exactly `expected_descriptor_sha256`,
`expected_source_sha256`, `authorized_caller_label` and `receipt_id`, supplied
out of band by the approving caller. The tool never derives, stores, prints or
offers these values, and a manifest or digest list is not accepted in their
place (`compiler_authority`). Compiling or verifying anything other than the
exact approved bytes refuses `descriptor_authority` (or `source_drift` for the
source pin) without the pins changing. An approver who computes pins must do so
from the reviewed metadata with the contract's domain digests
(`SHA256(b"temper-admission/v1\0" + domain + b"\0" + CAJ-1)`), not from a
submitted candidate's manifest.

## Use

```sh
python3 configs/architecture/bin/context_profile_admission_compile.py compile \
  --input AUTHORING_DIR --output NEW_DIR --authority AUTHORITY.json \
  --schema docs/schemas/candidate-admission-v1.schema.json \
  --codec temper_ai/config/admission_contract.py

python3 configs/architecture/bin/context_profile_admission_compile.py verify \
  --input NEW_DIR --output NEW_VERIFY_DIR --authority AUTHORITY.json \
  --schema docs/schemas/candidate-admission-v1.schema.json \
  --codec temper_ai/config/admission_contract.py
```

`compile` writes `descriptor.json`, `raw-records.json` (canonical v1 bytes) and
`manifest.json` into a directory it creates; it never overwrites
(`compiler_output_exists`). `verify` rechecks those three exact files with the
same out-of-band authority and writes the recomputed manifest as
`verification.json`. The manifest is informational, never authority: format
`context-profile-admission-artifacts/v1`, status
`metadata_verified_not_admitted`, `runnable: false`, mode, custody
(`unresolved` if any root policy is null, else `supplied_not_verified`), counts,
descriptor/source/raw-closure/graph domain digests, contract file hashes and the
two artifact file hashes.

Standard output is one line, `{"code": ..., "runnable": false}`; exit 0 on
success and 2 on refusal. Refusals carry only fixed codes: the codec's
(`descriptor_authority`, `source_drift`, `wire_schema`, `unsupported_version`,
`unsupported_mode`, `closure_mismatch`, `digest_mismatch`, `source_origin`,
`field_set_drift`, `graph_mismatch`, `position_mismatch`,
`aliased_or_cyclic_value`, `noncanonical_bytes`, ...) or the tool's
(`compiler_input`, `compiler_known_fields`, `compiler_authority`,
`compiler_contract_pin`, `compiler_manifest`, `compiler_output_exists`,
`compiler_usage`, `compiler_io`, `compiler_internal`, `invalid_json`,
`duplicate_key`, `nonfinite_number`). No input value, path, label or exception
text is printed.

## Tests and evidence

The tests never take expected answers from the tool or the codec. The tiny case
expects #192's handwritten wire bytes and pins. The 14×3 case decodes the
#306/#316 literals by storage decoding only, checks the decoded output against
them and checks the bytes against a separate stdlib encoder of the float-free
fixture. Controls with the original authority show changed tuples are refused;
semantic-guard controls are re-signed by the test as an independent approver of
a deliberately inconsistent candidate, so each reaches one named codec guard.

After all work is final, the targeted campaign runs once and keeps its original
outputs:

```sh
python3 tests/test_config/test_context_profile_admission_compile.py \
  --evidence-output /explicit/new-directory
```

The directory must not exist. It receives the actual clean and repeated
artifacts, CLI outputs, every control's expected and observed fixed code, and the
unittest log. The compiler-window test guards only that window (explicit
schema/codec reads, stdlib imports, no environment, sockets or subprocesses).
Normal hooks and remote CI are separate checks with their own I/O.

## Limits

* The source tuple in the tests is a synthetic label (the commit/tree the #316
  inventories were read from), not an installed-source attestation.
* The codec does not resolve raw references, so an orphan raw record is caught
  only by the fixed descriptor authority, not by reachability.
* Request ingress consistency (T2) and custody are other owners' work; this tool
  only carries their explicit values.
* Landing needs the #192 contract on master first or together with it; this
  candidate does not land #192's files through its own branch.
