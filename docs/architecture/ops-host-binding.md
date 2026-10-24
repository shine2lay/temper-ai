# ops_host_binding: whole selections and actual bytes, as UNTRUSTED data (P2)

`configs/architecture/bin/ops_host_binding.py` is P2 of the Project 3 host-client
source plan (r5 packet, ABI A0/A1/A3/A7, CASE-REQUIREMENTS F2). It checks supplied
data and returns a `CandidateTarget` whose trust is always `UNTRUSTED`. It is not a
TrustedContext, not a VerifiedExpectedTarget and not a production admission API;
P5 and the native checks decide whether a candidate can ever be used.

Every file is read through the received P1 reader,
`configs/architecture/bin/ops_host_binding_files.py` (R1, landed 848c3c00). The
module imports it from its own folder and refuses to load if that file is
anything else. P2 runs no subprocess, Git command, exec or object-store read and
never lists a folder. It does not import, copy or run any producer code: the four
grammar APIs are its own implementation of the M01 clauses.

## API

| Call | Returns | Refuses with |
|---|---|---|
| `loads_publication(raw)` / `validate_publication(value)` | `{"trust": "UNTRUSTED", "value": fresh copy}` | PUBLICATION_INVALID, SCHEMA_MISMATCH |
| `loads_expected_binding(raw)` / `validate_expected_binding(value)` | the same | BINDING_INVALID, SCHEMA_MISMATCH |
| `load_project_candidate(data_context, *, uid)` | `CandidateTarget` (route project) | any of the eleven codes but ISSUER_UNTRUSTED |
| `load_calibration_candidate(data_context, *, uid)` | `CandidateTarget` (route calibration) | the same |
| `recheck_candidate(candidate, boundary)` | `None` | SOURCE_DRIFT, EVIDENCE_INVALID |

`boundary` is exactly one of `load-complete`, `receiving`, `before-count`. The
loader itself rechecks at load-complete before it returns; the caller rechecks at
receiving and again just before counting. A recheck never changes trust.

`TargetRefused` is this module's own `ValueError`; its args, str and repr hold
only the code, so no path, hash or byte reaches a message or a log. The eleven
codes are R1's, in R1's order and with the meanings of ABI A7.
`TARGET_ISSUER_UNTRUSTED` is never raised here: no native issuer is judged.

## The data a caller supplies (ABI A3.1)

Everything is explicit. Nothing is inferred from a folder, a default or a name.

| Key | Shape | Checked against |
|---|---|---|
| `window` | AbsRef | its hash equals `expected_window_sha256` (else BINDING_INVALID); read first, through R1, with its declared length and hash (else PUBLICATION_INVALID) |
| `expected_window_sha256` | 64 hex | the window AbsRef |
| `publication` | AbsRef, basename `PUBLICATION.json` | its folder is the QA root; every relative Ref resolves under it |
| `expected_binding` | project: exactly mode, project_id, run_id, build_sums_sha256, kit_id, kit_sha256; calibration: exactly mode, manifest_sha256, entry, build_sums_sha256, calibration_run | equal, by type and value, to the window's `binding` |
| `m01_record`, `m02_record`, `security_records` | AbsRefs (one or more security records) | opaque: their bytes are never interpreted |
| `record_subjects` | one `{record, byte_offset, byte_length, expected_subject}` per record | the record's span equals the subject's bytes exactly |
| `release_roots` | `[{repository, root}]`, one per closure repository | the closure's repository roots |
| `kit_evidence` | `{root, kit, sums, files, file_count}` | the binding's kit and SUMS hashes and the SUMS lines |
| `calibration_manifest` (calibration) | AbsRef | exactly one Ref the publication lists |
| `expected_draft_kit_id` (calibration) | string | the manifest's `draft_kit_id` |
| `expected_calibration_selection` (calibration) | the fifteen keys | the selected entry, the five-key binding and the window |

`kit_evidence.kit` is a Ref in the project route and exactly `null` in the
calibration route. `files` lists every domain file as `{ref, mode}`, sorted and
unique by path, and `file_count` equals its length. The domain is exactly the
names in the SUMS file: each line is `<64 lowercase hex>  <name>`, the name has no
control character, backslash, leading `/` or empty, `.` or `..` part, and no name
repeats. A physical file under the kit root outside that domain is never read.
P2 does not change the six pin meanings or the kit byte domain, and it does not
derive a raw kit projection: it compares the bytes it is given.

`record_subjects` closes the opaque records: every record identity has exactly
one association, offsets and lengths are exact integers (a bool is refused even
when it equals the valid number), the span ends inside the record, and the
subject's length equals `byte_length`. The comparison is raw bytes: no
whitespace, newline or Unicode normalisation.

## Order of checks

1. Context shape, kit_evidence shape, record_subjects shape (CONTEXT_MISSING,
   REVIEW_MISSING). No file is read before this.
2. The window: hash, then the R1 read, then the expected binding against it.
   Calibration: the fifteen-key selection against the window's selection and its
   top-level receipt path and hash.
3. The publication: grammar, then a registry of one identity per QA-root path for
   every Ref reachable from it (a second, different identity is
   PUBLICATION_INVALID).
4. Project: the whole table (every row's grammar, exact binding path, unique
   selector four-tuples) before selection; zero matches SELECTOR_MISSING, several
   SELECTOR_AMBIGUOUS. Calibration: the supplied manifest Ref must be listed; the
   whole manifest (discriminator, every entry, unique entry ids, unique data
   folders, reuse only of earlier entries, path id equal to `calibration_id`)
   before selection; then the selected entry against the kit evidence, the
   window and the fifteen-key selection.
5. The binding: read by the exact Ref the selected row or entry names, with no
   fallback; its grammar, fixed pins and target literals.
6. kit_evidence: SUMS, kit (project) and every domain file read through R1 with
   their declared modes; hashes against the binding; SUMS lines against the files.
7. record_subjects: each record and subject read; spans compared.
8. The supplied closure: authority, schema, Security and closure documents read;
   repositories, nodes (Git blob ids recomputed from the bytes read), edges
   (acyclic, every endpoint resolved), entry points, the six window pins, each
   schema copy equal to a closure node, the runtime executable and every stdlib
   file; then the QA cohort: every file, every resolved reference, the original
   inventory, index and every original's expectation. Unknown and
   intentional-negative cells are kept exactly as given, never followed or fixed.
9. Recheck of every read (load-complete) and of the identities recomputed from the
   retained bytes.

A one-value fault reaches its own guard first; CASE-REQUIREMENTS F2 names the
code for each.

## Native versus data

`required_native_checks` is always these five, in this order; nothing in P2 can
resolve or switch them off:

1. NATIVE_ISSUER_SCOPE_SUBJECT_CONDITIONS
2. INDEPENDENT_JOB_KIT_CALIBRATION_SELECTION
3. REVIEWED_BOOTSTRAP_COMPLETE_DEPENDENCIES_GIT_MEMBERSHIP_AND_ACTUAL_LOADED_SOURCE
4. SELECTED_RUNTIME_UID_NAMESPACE_CONTAINER_MOUNTS_GRANTS_AND_BOTH_ROOTS_ACCESS
5. EXACT_QA_PUBLICATION_COHORT_ALL_ORIGINAL_EXPECTATIONS_M02_AND_SECURITY_RECEIVING

P2 shows that supplied bytes agree with each other. It does not show who issued
them, that QA published them, that a job or kit was independently selected, that
a commit or tree contains the nodes, that the code was what ran, which runtime,
UID, namespace, mounts or grants apply, or that Security received anything. The
S4 receipt is compared as data (path, hash, id) and never read.

## Security ceilings (carried from R1's receiving, 8299d537)

- Close covers attempts on ordinary paths only; it is not physical-close or
  leak proof.
- Precheck and open are not atomic.
- Folders above each supplied root are not certified.
- A same-UID writer is not excluded.
- FileRead, Stamp, UID, mode and hash are data, not capabilities.

P2 claims nothing beyond these. Its candidate carries R1 FileReads only as data
for the rechecks.

## Residuals

- Loader tests use synthetic authority and Security22 review pins, because a
  synthetic root cannot hold files with the real pinned hashes; the grammar tests
  use the real pins. Loading over the real authority bytes is not shown here.
- The window is parsed as strict JSON but only the members P2 compares are
  checked; full window validation is P5's.
- Git membership of nodes, edge classification against file contents (M02), the
  real raw kit projection and every native check stay open.
- No real QA publication, private evidence, root or S4 receipt was read.

## Tests

`tests/test_architecture/test_ops_host_binding.py` builds every case under
pytest's `tmp_path` with its own builder (no shared fixture). Each F2 ID has, per
variant, an N test with its one expected code (or stated pass) and a C test on the
clean twin; the drift cases cover seventeen observation kinds at each of the three
boundaries; the bites switch off the actual whole-table, whole-manifest and
subject guards and show the refusal is lost while the clean twin is unchanged.
