# P3 authority source contract

This is a **SOURCE-ONLY, UNLANDED candidate**, not an installed authority service.
Its import surface is `temper_ai.p3_authority.contract`. There is no issuer,
authenticated observer, registry implementation, RPC endpoint, production
binding, count permission or write permission. Missing capabilities are
unavailable, not a successful empty observation.

## Distribution and ownership

One existing `temper-ai` distribution includes three package roots:

| Package | Owner | Interface |
| --- | --- | --- |
| `p3_host_contracts` | Ops | 19 immutable host records and `OperationKey`; 22 independent external-role parameters |
| `p3_source_closure` | Systems | reviewed/loaded records, epochs, coverage/gaps, parsers and the single comparator |
| `temper_ai.p3_authority` | Temper | native reference protocols, canonical generic bindings, service/provider ports, decisions and closed refusals |

The supplier leaves are stdlib-only and import neither Temper nor adapters.
Temper binds their actual classes; it does not subclass/copy their records,
wrap their parser/comparator, or modify the frozen candidate admission wire.
Higher-level services/adapters consume these leaves. No dependency cycle,
`sys.path` mutation, separate distribution or version bump is introduced.
Runtime/dev dependencies remain in the existing `uv.lock`. Pin the reviewed
repository revision and the wheel built from it: project version `0.1.0` alone
does not identify code. Installed proof must use that non-editable wheel outside
all source checkouts, not an editable install or `PYTHONPATH` workaround.

```python
from temper_ai.p3_authority.contract import (
    NativeHostJoin, P3AuthorityRegistry, P3NativeBoundary,
    SelectedHostJob, HostObservation, Result, Refusal, RefusalCode,
)
```

`get_origin(SelectedHostJob)` is the original `p3_host_contracts.SelectedHostJob`
class. Systems exports retain exact object identity, including
`compare_loaded_source`. The N3 config-path entrypoint is an adapter; legacy
`qa-ops-host-source-closure/1` source invocation and parser remain unchanged.
See `p3-host-contracts.md` and `ops-host-source-comparison.md` for supplier maps.

## Module/API map

- `references`: abstract, non-runtime-checkable native identities, authenticated
  peer/session, permission, observation session and witness references. A
  structural match never authenticates a channel or reference.
- `selection`: immutable independent authority/job/selection data, reusing
  candidate `DispatchIdentity`. Project `run_id` is not an execution UUID.
  Calibration explicitly binds the whole manifest and entry/run/round/copy.
- `refusals`: 33 closed codes; phase, retry, admission/effect/sequence histories
  are mandatory. `counted` is fixed false. Enum fields reject foreign types and
  strings with a fixed value-free exception; no decoder or policy is installed.
- `results`: `AcceptedData[T] | Refusal`; mandatory `DecisionEvidence` describes
  source data, not authenticated success. No implicit successful result.
- `host_types`: all canonical Ops generics bind each external role separately
  to Temper reference protocols or exact Systems types. `HostProjectSelection`
  and `HostCalibrationSelection` distinguish Ops wire records from Temper's
  independent registry selection records; neither replaces the other.
- `boundary_types`: distinct data for actual creation, worker and root
  observation, grants, receiving, current binding, phase decisions and count.
  A future scope cannot substitute for actual object identity. `NativeReceive`
  aliases `VerifiedReceiptBinding`, never `CountDecision`.
- `host_ports`: `NativeHostJoin`'s nine abstract methods, `HostObserver`,
  `HostProvenance`, `SharedN3`, and provider aliases. No concrete host collector.
- `service_ports`: `IssuerVerifier`, `P3AuthorityRegistry`, `P3NativeBoundary`,
  `WorkerObserver`, `RootObserver`; every operation is abstract and mandatory.
- `contract`: explicit facade of these types and actual canonical suppliers.
  Initialization adds no registration, provider or runtime configuration.

The nine host ports are `select_host_job`, `permit_observation`,
`open_observation`, `observe`, `recheck_effect`, `witness_event`,
`lookup_occurrence`, `verify_publication`, and `receive`. Their fully resolved
annotations define the source interface. Providers must return a `Refusal` with
actual history when unavailable; there is no usable default provider. An
incomplete subclass cannot be instantiated as an implementation.

## Trust and lifecycle distinctions

These are typed Python source interfaces, **not native wire decoders**. They do
not authenticate constructors or enforce a remote service policy. The future
service must reject unknown versions/extra fields, foreign owners, stale
revisions and invalid phase/effect combinations before effects. Do not unpack
untrusted dictionaries into constructors and call that verification. Ordinary
Python call errors are not a safe remote diagnostic envelope.

Authentication evidence, collection permission, observation facts, native
publication receiving, assessment and final count remain distinct. A matching
type, serialized flag, file owner or digest grants none of them. Collection must
be authorized before any protected read. Host/worker processes and publication/
host-evidence roots retain different fields. Actor identity is not expected
file ownership. Future A scopes do not replace observed B/C object identities.

Pre-admission refusal preserves `unused`; committed admission preserves `used`;
uncertain commit preserves `unknown`. Lifecycle has `not_applicable`, not a
fabricated row sequence. Refusal cannot erase partial creation/admitted work.
Actual D-1 occurrence and receiving precede D-5; the contract represents that
history, but tests of its types do **not** prove effect fencing or order checks.
`CandidateBindings` and the existing candidate wire remain owned by their
current modules, not copied into this contract.

## Versions and shared cases

Keep domains distinct: `p3-native-decision/1`, `p3-reviewed-source-graph/1`,
`p3-reviewed-loaded-closure/1`, legacy `qa-ops-host-source-closure/1`, explicit
Ops inspect `/1` or `/2`, unchanged request/receipt `/1`, and shared corpus
`ops-host-compat-corpus/1`. No silent widening or second parser.

Contract cases use the corpus owner's additive registration surface and new
`temper.t3.*` IDs, with exact source/recipe/oracle pins. Raw originals/oracles
remain unchanged; synthetic source tests are not a private replacement corpus.
The older `ops-host-io/1` harness is not the designated corpus. Final corpus
conformance requires its actual supplier manifest and registration acceptance;
source coding and synthetic tests do not require native values.

## Import and test limits

The opening combined test exercises canonical records and all nine host ports
through an explicit test-only provider. Negative twins preserve unavailable
results and separate histories. Every new executable enum guard has semantic
deletion and prefix/contains-loosening bites. Port annotations must fully
resolve; imported foreign classes retain their original identity/parameter map.
Tests of representability are not native permission, live observations or
service-policy enforcement.

Cold import spies separate normal module reads from runtime effects. Existing
parent `temper_ai` initialization strips GitHub server-secret environment
entries; this defense is retained. Candidate types transitively load config/ORM
declarations, not an engine/session. Bounded spies cover SQL and HTTP client
construction, socket/process/sqlite contact and prohibited startup composition.
They are not a proof against arbitrary future providers or every possible
registration path. Failure tests keep child stdout/stderr/argv out of assertion
values and check verbose-output canaries. No live database or separate Temper
server is used. Current results and artifact identities are in the private
candidate handoff, not implied by these test descriptions.

## Release limits

N1–N8 remain unresolved; R-1/R-1i/D-1/D-5 remain UNQUALIFIED; P5 remains UNTRUSTED;
writes remain false. No native providers are installed. Source/interface review
is not native receiving, activation or owner consent.

A separately authorized future landing needs applicable exact-head Architecture
and Security rulings and the current required checks. Its normal path is detached
`systemd-run --user` with `UMask=0022` running `wt land`, which auto-deploys.
**Do not run that path in this source-only task.**
