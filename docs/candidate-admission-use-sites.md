# Candidate admission: actual use sites (T3)

Status: implementation in progress; source-only, not installed or activated.
Accountable lead: Temper; overall design: Architecture #303. Frozen contract:
`caf5c16f6d9965cbcbc8e10653d75e1c47b27340`.

## Hypothesis, before implementation

H-T3-USE-1: the inert contract currently does not constrain actual scheduling,
factory creation, script rendering or native claim creation. Comparing pinned
expectations to the exact objects consumed at those sites, and serializing
same-opened-fd readiness/current generation with the existing exclusive claim,
should refuse substitutions after preparation. Measure with synthetic real
entrypoints and forbidden-action counters. A mutated graph, context, template,
config, root or stale nonce that still schedules, renders or claims falsifies
this hypothesis. Result: local touched verification PASS (488 tests, including existing native
caller/read/send/persistence and loader tests); ruff and focused mypy PASS.
H-T3-USE-1, H-T3-FIXTURE-1, H-T3-METADATA-1 and H-T3-ENQUEUE-1 HIT on isolated
synthetic adapters. Exact-head full gates/remote PostgreSQL remain pending.
First collection found a runtime type-only
import through `stage.__init__` re-entered the agent registry. Repair hypothesis
H-T3-IMPORT-1: keep WorkflowConfig's annotation import under TYPE_CHECKING so
module loading does not initialize the stage loader. Expected: collection runs;
falsifier: the same import cycle remains. No policy/wire change. HIT: collection
and 479 tests passed; one durable=false negative control stopped in the fixture
codec rather than reaching the consumer. H-T3-FIXTURE-1: pass that deliberately
malformed receipt directly through the synthetic adapter to exercise the
consumer's own revalidation. Expected: consumer refusal before readiness changes;
falsifier: forged readiness installed. Separately, inspection found the native
projection alone can erase frozenset type information. H-T3-METADATA-1: apply the
same exact metadata-type check again inside the claim callback. Expected: a late
native `_KNOWN_FIELDS` type/member change cannot claim; falsifier: claim appears.
H-T3-ENQUEUE-1: parallel batches currently check the batch before constructing the
pool, leaving a substitution window before each submit. Recheck the actual node
immediately at each enqueue, plus the existing worker-entry check. Expected:
a mutation by pool setup cannot enqueue; falsifier: the submit sentinel fires.

H-T3-COMPAT-1: the first full SQLite hook found 278 failures/6 errors; legacy
contexts use dynamic missing-attribute fallbacks, while hooks_for used ordinary
getattr and mistook invented attributes for actual candidate markers. Inspect
attribute declaration before retrieving the three admission fields and the bound
subject marker. Do not special-case a test/mock class. Expected: unchanged legacy
ScriptAgent execution passes, while explicitly assigned bad/missing candidate
markers still refuse before events/tools. Falsifier: either legacy still refuses
or a declared candidate can fall back. HIT: 198 targeted consumer and affected
legacy tests passed, including explicit markers on dynamic contexts. Full-hook
gate remains required.

## Consumer placement

- `stage/executor.py`: compare the entire actual workflow and recursive node
  inventory before topology, policy, dependency or start-event access. Recheck
  before batches, thread-pool enqueue and node entry. Refuse candidate restore,
  supplied initial outputs, resume metadata and cleanup-only continuations.
- `stage/agent_node.py`: compare actual node/config/path and intended registry
  class before calling the original factory; compare returned exact class and
  full config again. Use a separately owned config copy and immutable bindings.
  Candidate invocations do not enter the legacy implicit empty/error retry.
- `stage/stage_node.py`: carry the exact stage binding and subgraph through
  `dataclasses.replace` before applying stage policy or input gates.
- `agent/script_agent.py`: compare template UTF-8 bytes/hash and all final render
  variables (including context defaults) before any input/event log, rewrite or
  render. Only a private metadata copy reaches rendering; the event sink gets a
  separate copy. Unadmitted variables cannot carry body/key/answer paths.
- The scheduler retains the actual successful preparation `NodeResult` identity
  and metadata bytes. Only after its checkpoint save does the T2 adapter verify
  durable checkpoint provenance. Readiness uses the contract's compare-once
  transition; local readiness advances only after a successful transaction.
- `agent/single_call_agent.py`: the native attempt owns its no-follow directory
  and required input-file fds. Each edge is checked against the retained fd;
  complete identities, file sizes/hashes and policy modes/owners are rechecked
  inside the generation fence immediately before the existing O_EXCL claim.
  The hook borrows, never owns/closes/reopens, that root fd. Native input reads
  after claim use the retained file fds. A consumed claim is never undone, even
  on metadata-transaction failure. Existing native validation, durable pre-send
  barriers, single-send and persistence handling are retained.

## Isolated assembly interfaces

`CandidateUse` implements the frozen `AdmissionUseHooks`; `ActualProjection`
provides T1's full graph/node/agent projections without a second normalizer.
`ProtectedUseTransport.current_generation` runs its action under T2's actual
current-generation transaction and commits before returning. Its
`verify_preparation` must verify the exact returned `NodeResult` and the supplied
checkpoint service's durable identity, not trust a public receipt constructor.
`bind_root_readiness` is the frozen transport transition with that verified
preparation. Callbacks allocate the claim only; no provider/network work.

Context construction remains T1-owned. Tests use a dataclass extension with
`admission`, `admission_hooks` and `admission_required`. No runtime registry or
thread-local fallback is used. Missing binding/hooks on a designated candidate
or an already-bound node/agent refuse; ordinary unmarked contexts stay legacy.
V1 must connect the real designation/restore path, projector and transaction
adapter. The local adapter types are not competing wire formats or permissions.

Readiness inventories enumerate the two exact native input paths and every
opened non-root directory ancestor, including ancestors of input files outside
the output directory. Filesystem `/` is the no-follow anchor, not a serialized
path (the frozen v1 path grammar excludes it). Parent array order is retained;
identity sets must be complete, without duplicates. No receipt may add an
unrequested file read. These are synthetic/source checks, not custody receipts.

## Boundary

T1 owns raw capture, projections, loader and shared context construction. T2
owns protected persistence and generation transactions. T3 owns these consumer
checks and uses typed sibling adapters, not unfinished sibling implementations.
Independent stage tests do not establish real T1/T2 composition, durable database
provenance, live custody, permission, provider behavior or release acceptance.
V1 must prove the real composition with Architecture's independent oracle.

No live model, private source, registration, provisioning, deployment or run is
part of this task. Unsupported candidate continuation modes refuse; a separately
authorized fresh descriptor and fresh slot infrastructure attempt is not a
blanket-banned retry. Existing exclusive claim, single-send, authorization,
read and persistence defenses remain in place.
