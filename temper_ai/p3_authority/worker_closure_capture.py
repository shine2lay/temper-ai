"""P3 T5-N3W: deterministic worker runtime LoadedClosureEnvelope and GitProvenance capture.

Produces the worker-half ``LoadedClosureEnvelope`` and ``Repository`` / ``GitProvenance``
records defined by ``p3_source_closure/records.py`` across the opt-in launch/bootstrap
adapters (``DockerLaunchObservationAdapter``, ``EarlyBootstrapObservationHook``,
``RunnerBootstrapObservationHook``, ``BashChildLaunchAdapter``,
``ScriptLaunchObservationAdapter``), ``CoverageBookkeeper``, and
``ChildRegistrationRegistry``.

Inert and opt-in only:
- Runs without a ``WorkerClosureCollector`` attached to the adapters execute
  byte-for-byte unchanged.
- Never counts ``box_profile.closure`` or an unverified launcher registration
  (``refuse_surrogate_child_registration``) as complete coverage or authentic origin.
- ``WRITES_ADMITTED`` remains ``False``.
"""

from __future__ import annotations

import hashlib
import os
import struct
import zlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal

from p3_source_closure import (
    Checkpoint,
    ClosureBinding,
    ClosureBoundary,
    ClosureEnvelope,
    ContentIdentity,
    Entrypoint,
    EvidenceRef,
    GitProvenance,
    LoadedClosureEnvelope,
    LoadEvent,
    N3Coverage,
    NativeClosureExpectation,
    ProcessObservation,
    ProcessProfile,
    Repository,
    ReviewedSourceGraph,
    SourceClosureComparison,
    SourceGraph,
    SourceNode,
    TargetRefused,
    VerifiedClosureOrigins,
    VerifiedOriginFact,
    compare_loaded_source,
    validate_loaded_envelope,
    validate_reviewed_graph,
)
from p3_source_closure import (
    ProcessInstance as ClosureProcessInstance,
)
from p3_source_closure.parsing import byte_identity, claim_identity, to_wire
from p3_source_closure.provenance import Findings, check_provenance
from temper_ai.p3_authority.child_registration import (
    NON_PROVIDER_REGISTRATION_SOURCES,
    VERIFIED_LAUNCHER_REGISTRATION_SOURCE,
    RegisteredChildEntry,
    refuse_surrogate_child_registration,
    refuse_unpaired_process_instances,
)
from temper_ai.p3_authority.contract import (
    AcceptedData,
    Boundary,
    DecisionEvidence,
    JobKey,
    NativeEventRange,
    Refusal,
    RefusalCode,
    Result,
    RetryKind,
    WorkerObservation,
)
from temper_ai.p3_authority.coverage_bookkeeping import (
    ALL_N3_COVERAGE_CATEGORIES,
    AUTHENTICATED_STREAM_MECHANISMS,
    CoverageBookkeeper,
    comparison_to_refusal,
    make_refusal,
)

WORKER_CLOSURE_COLLECTOR_ID = "temper-worker-closure-collector"
WORKER_CLOSURE_COLLECTOR_VERSION = "collector-v1"
WORKER_CLOSURE_MECHANISM = "synthetic-combined-launch-load-fence"
WORKER_CLOSURE_EVIDENCE_SCHEMA = "synthetic-evidence/1"
WORKER_CLOSURE_SUPPLIER = "temper-worker-closure-custody"

_HEX40_CHARS = frozenset("0123456789abcdef")


def _is_hex40(value: str) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 40
        and all(ch in _HEX40_CHARS for ch in value)
    )


def byte_content_identity(raw: bytes | str) -> ContentIdentity:
    """Landed ``byte_identity`` over raw bytes, or over a string's UTF-8 bytes."""
    return byte_identity(raw.encode("utf-8") if isinstance(raw, str) else raw)


ObservedLoadKind = Literal["load", "cache"]
StreamEventKind = Literal["start", "load", "cache", "child", "end"]


@dataclass(frozen=True, slots=True, kw_only=True)
class ObservedLoad:
    """One load the observer saw: node id, the loaded bytes' identity and its event kind.

    ``event_kind`` is ``"cache"`` when the executed bytes were cached code (a
    ``__pycache__`` .pyc; see ``executed_python_code.observe_python_module_execution``),
    else ``"load"``. A load carries no coverage category: what the observer watched is
    its own sealed scope record (the process's ``Checkpoint``), never a load label.
    """

    node_id: str
    loaded: ContentIdentity
    event_kind: ObservedLoadKind = "load"

    def __post_init__(self) -> None:
        if not isinstance(self.node_id, str) or not self.node_id:
            raise ValueError("ObservedLoad.node_id must be a non-empty string")
        if not isinstance(self.loaded, ContentIdentity):
            raise ValueError("ObservedLoad.loaded must be a ContentIdentity")
        if self.event_kind not in ("load", "cache"):
            raise ValueError("ObservedLoad.event_kind must be 'load' or 'cache'")


def make_evidence_ref(
    record_id: str,
    *,
    schema: str = WORKER_CLOSURE_EVIDENCE_SCHEMA,
    supplier: str = WORKER_CLOSURE_SUPPLIER,
    content: ContentIdentity | None = None,
) -> EvidenceRef:
    """Build a canonical p3_source_closure EvidenceRef."""
    return EvidenceRef(
        schema=schema,
        content=content if content is not None else byte_content_identity(record_id),
        supplier=supplier,
        record_id=record_id,
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class CapturedGitCheckoutProvenance:
    """Captured clean Git checkout Repository, GitProvenance records, and membership facts."""

    repository: Repository
    provenances: tuple[GitProvenance, ...]
    nodes: tuple[SourceNode, ...]
    membership_facts: tuple[VerifiedOriginFact, ...]


def _read_git_loose_object(objects_dir: Path, oid: str) -> tuple[bytes, bytes]:
    obj_path = objects_dir / oid[:2] / oid[2:]
    raw = zlib.decompress(obj_path.read_bytes())
    hdr, _, body = raw.partition(b"\x00")
    return hdr, body


def _read_git_tree_blobs(
    objects_dir: Path, tree_oid: str, prefix: str = ""
) -> dict[str, tuple[str, str]]:
    hdr, body = _read_git_loose_object(objects_dir, tree_oid)
    if not hdr.startswith(b"tree "):
        raise ValueError(f"Not a tree object: {tree_oid}")
    out: dict[str, tuple[str, str]] = {}
    pos = 0
    while pos < len(body):
        nul = body.index(b"\x00", pos)
        mode_name = body[pos:nul].decode("utf-8")
        raw_mode, _, name = mode_name.partition(" ")
        entry_oid = body[nul + 1 : nul + 21].hex()
        pos = nul + 21
        rel = f"{prefix}/{name}" if prefix else name
        if raw_mode in ("40000", "040000"):
            out.update(_read_git_tree_blobs(objects_dir, entry_oid, rel))
        else:
            norm_mode = raw_mode.zfill(6)
            out[rel] = (norm_mode, entry_oid)
    return out


def _read_git_index_blobs(index_path: Path) -> dict[str, str]:
    data = index_path.read_bytes()
    if len(data) < 12:
        raise ValueError("Truncated git index")
    sig, _version, count = struct.unpack(">4sII", data[:12])
    if sig != b"DIRC":
        raise ValueError("Invalid git index")
    pos = 12
    entries: dict[str, str] = {}
    for _ in range(count):
        entry_start = pos
        oid = data[pos + 40 : pos + 60].hex()
        flags = struct.unpack(">H", data[pos + 60 : pos + 62])[0]
        pos += 62
        if flags & 0x4000:
            pos += 2
        nul = data.index(b"\x00", pos)
        name = data[pos:nul].decode("utf-8")
        entries[name] = oid
        entry_len = (nul + 1) - entry_start
        pad = (8 - (entry_len % 8)) % 8
        pos = nul + 1 + pad
    return entries


def _inspect_git_checkout(
    root: Path,
) -> tuple[str, str, dict[str, tuple[str, str]], bool] | None:
    dot_git = root / ".git"
    if dot_git.is_symlink():
        return None
    if dot_git.is_dir():
        git_dir = common_dir = dot_git
    elif dot_git.is_file():
        lines = dot_git.read_text(encoding="utf-8", errors="replace").splitlines()
        if not lines or not lines[0].startswith("gitdir: "):
            return None
        git_dir = (root / lines[0][len("gitdir: ") :].strip()).resolve()
        cfile = git_dir / "commondir"
        common_dir = (
            (git_dir / cfile.read_text(encoding="utf-8").strip()).resolve()
            if cfile.is_file()
            else git_dir
        )
    else:
        return None

    head_file = git_dir / "HEAD"
    if not head_file.is_file():
        return None
    head_raw = head_file.read_text(encoding="utf-8").strip()
    commit_sha: str | None = None
    if head_raw.startswith("ref: "):
        ref_name = head_raw[5:].strip()
        for base in (git_dir, common_dir):
            ref_path = base / ref_name
            if ref_path.is_file():
                commit_sha = ref_path.read_text(encoding="utf-8").strip()
                break
        if commit_sha is None and (common_dir / "packed-refs").is_file():
            for line in (
                (common_dir / "packed-refs").read_text(encoding="utf-8").splitlines()
            ):
                if line and not line.startswith(("#", "^")):
                    parts = line.strip().split(" ")
                    if len(parts) == 2 and parts[1] == ref_name:
                        commit_sha = parts[0]
                        break
    else:
        commit_sha = head_raw

    if commit_sha is None or not _is_hex40(commit_sha):
        return None

    objects_dir = common_dir / "objects"
    try:
        chdr, cbody = _read_git_loose_object(objects_dir, commit_sha)
        if not chdr.startswith(b"commit "):
            return None
        tree_lines = [
            ln.split(" ", 1)[1].strip()
            for ln in cbody.decode("utf-8", errors="replace").splitlines()
            if ln.startswith("tree ")
        ]
        if not tree_lines or not _is_hex40(tree_lines[0]):
            return None
        tree_sha = tree_lines[0]
        ls_blobs = _read_git_tree_blobs(objects_dir, tree_sha)
        idx_path = git_dir / "index"
        idx_blobs = (
            _read_git_index_blobs(idx_path)
            if idx_path.is_file()
            else {k: v[1] for k, v in ls_blobs.items()}
        )
    except (OSError, ValueError, zlib.error, struct.error):
        return None

    tree_oids = {k: v[1] for k, v in ls_blobs.items()}
    disk_oids: dict[str, str] = {}
    clean = idx_blobs == tree_oids
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        cur = Path(dirpath)
        if cur == root and ".git" in dirnames:
            dirnames.remove(".git")
        for dname in list(dirnames):
            if (cur / dname).is_symlink():
                clean = False
        for fname in filenames:
            if cur == root and fname == ".git":
                continue
            fpath = cur / fname
            if fpath.is_symlink() or not fpath.is_file():
                clean = False
                continue
            raw = fpath.read_bytes()
            rel = fpath.relative_to(root).as_posix()
            hdr = f"blob {len(raw)}\x00".encode("ascii")
            disk_oids[rel] = hashlib.sha1(hdr + raw).hexdigest()
    if disk_oids != tree_oids:
        clean = False

    return commit_sha, tree_sha, ls_blobs, clean


def capture_git_checkout_provenance(
    *,
    repo_root: str | Path,
    repo_id: str = "repo",
    role: str = "temper",
    tracked_files: Sequence[tuple[str, str]] = (),
    boundary: Boundary = "C_PRE_EXECUTION",
    evidence: DecisionEvidence,
) -> Result[CapturedGitCheckoutProvenance]:
    """Deterministically capture Repository and GitProvenance from a clean Git checkout.

    Fails closed:
    - missing/invalid git checkout or non-hex40 HEAD/tree -> ``RefusalCode.OBSERVATION_GAP``
    - dirty working tree or untracked files -> ``RefusalCode.SOURCE_CHANGED``
    - ``check_provenance`` contradiction -> ``RefusalCode.SOURCE_CHANGED``
    """
    path = Path(repo_root)
    if not path.is_dir():
        return make_refusal(RefusalCode.OBSERVATION_GAP, boundary)

    inspected = _inspect_git_checkout(path)
    if inspected is None:
        return make_refusal(RefusalCode.OBSERVATION_GAP, boundary)

    commit_sha, tree_sha, ls_blobs, worktree_clean = inspected
    if not worktree_clean:
        return make_refusal(
            RefusalCode.SOURCE_CHANGED,
            boundary,
            retry_kind=RetryKind.NEW_BINDING_REQUIRED,
        )

    repo = Repository(
        id=repo_id,
        owner=role,  # type: ignore[arg-type]
        object_format="sha1",
        commit=commit_sha,
        tree=tree_sha,
    )

    file_pairs = (
        list(tracked_files)
        if tracked_files
        else [
            (
                Path(rp).stem
                if rp.endswith(".py") and "/" not in rp
                else rp.replace("/", "."),
                rp,
            )
            for rp in sorted(ls_blobs)
        ]
    )
    provs: list[GitProvenance] = []
    nodes: list[SourceNode] = []
    facts: list[VerifiedOriginFact] = []

    for node_id, rel_path in file_pairs:
        if rel_path not in ls_blobs:
            return make_refusal(
                RefusalCode.SOURCE_CHANGED,
                boundary,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
            )
        mode, blob_sha = ls_blobs[rel_path]
        if mode not in ("100644", "100755", "120000", "160000") or not _is_hex40(
            blob_sha
        ):
            return make_refusal(RefusalCode.OBSERVATION_GAP, boundary)
        raw_bytes = (path / rel_path).read_bytes()
        content_id = byte_content_identity(raw_bytes)
        mem_ref = make_evidence_ref(f"membership-{node_id}")
        gp = GitProvenance(
            tag="git",
            repository=repo_id,
            commit=commit_sha,
            tree=tree_sha,
            path=rel_path,
            mode=mode,  # type: ignore[arg-type]
            object_id=blob_sha,
            membership_ref=mem_ref,
            target_chain=(),
            representation="regular",
        )
        node = SourceNode(
            id=node_id,
            kind="git_source",
            content=content_id,
            logical_origin=rel_path,
            mode=mode,
            provenance=gp,
        )
        provs.append(gp)
        nodes.append(node)
        facts.append(
            VerifiedOriginFact(
                ref=mem_ref,
                purpose="membership",
                claim=claim_identity((repo, node)),
            )
        )

    if not nodes:
        return make_refusal(RefusalCode.CLOSURE_INCOMPLETE, boundary)

    # Check provenance via p3_source_closure.provenance.check_provenance
    policy_ref = make_evidence_ref("policy-git-check")
    check_graph = SourceGraph(
        schema="p3-reviewed-source-graph/1",
        graph_id="git-provenance-check",
        repositories=(repo,),
        nodes=tuple(nodes),
        edges=(),
        entrypoints=(
            Entrypoint("worker-entry", "worker", nodes[0].id, "main:run", ()),
        ),
        process_profiles=(
            ProcessProfile(
                "worker",
                "worker",
                ("worker-entry",),
                (nodes[0].id,),
                tuple(n.id for n in nodes),
                (nodes[0].id,),
                (),
                policy_ref,
            ),
        ),
        completeness_review_ref=make_evidence_ref("review-git-check"),
    )
    policy_fact = VerifiedOriginFact(
        ref=policy_ref,
        purpose="policy",
        claim=claim_identity(check_graph.process_profiles[0]),
    )
    findings = Findings(
        VerifiedClosureOrigins(
            reviewed_bytes=claim_identity(check_graph),
            observed_bytes=None,
            expectation=None,
            validity_checkpoint=None,
            facts=(*facts, policy_fact),
        )
    )
    check_provenance(check_graph, findings)
    if findings.contradictions or findings.gaps:
        return make_refusal(
            RefusalCode.SOURCE_CHANGED,
            boundary,
            retry_kind=RetryKind.NEW_BINDING_REQUIRED,
        )

    return AcceptedData(
        data=CapturedGitCheckoutProvenance(
            repository=repo,
            provenances=tuple(provs),
            nodes=tuple(nodes),
            membership_facts=tuple(facts),
        ),
        evidence=evidence,
    )


def stream_event(
    profile_id: str,
    sequence: int,
    *,
    kind: StreamEventKind,
    node_id: str | None = None,
    loaded: ContentIdentity | None = None,
    loader: str = "loader-v1",
    child_instance: str | None = None,
) -> LoadEvent:
    """One process stream's event at ``sequence``; ids and origin refs follow the profile."""
    return LoadEvent(
        sequence=sequence,
        event_id=f"{profile_id}-{sequence}",
        kind=kind,
        node_id=node_id,
        loaded=loaded,
        loader=loader,
        representation="bytes",
        child_instance=child_instance,
        origin_ref=make_evidence_ref(f"{profile_id}-event-{sequence}"),
    )


def refuse_missing_coverage(
    coverage: set[N3Coverage] | frozenset[N3Coverage], boundary: Boundary
) -> Refusal | None:
    """Refuse a process missing any ``ALL_N3_COVERAGE_CATEGORIES`` entry; ``None`` if complete.

    An unobserved effect fence or control plane is an observation gap; any other
    missing category leaves the closure incomplete.
    """
    missing = [cat for cat in ALL_N3_COVERAGE_CATEGORIES if cat not in coverage]
    if not missing:
        return None
    if "effect_fence" in missing or "control_plane" in missing:
        return make_refusal(RefusalCode.OBSERVATION_GAP, boundary)
    return make_refusal(RefusalCode.CLOSURE_INCOMPLETE, boundary)


def refuse_observer_scope_shortfall(
    checkpoint: object,
    *,
    epoch: str,
    events: Sequence[LoadEvent],
    child_frontier: tuple[str, ...],
    closure_boundary: ClosureBoundary,
    boundary: Boundary,
) -> Refusal | None:
    """Refuse an observer scope record that doesn't seal the recorded stream; ``None`` if it does.

    A fail-fast pre-check; the comparator stays the final decider. A scope for
    another epoch, interval, child frontier or boundary, an unsealed or lossy
    scope, or one without its refs is an observation gap. A category the scope
    lacks or lists in ``gaps`` is uncovered: ``refuse_missing_coverage`` refuses it.
    """
    if not isinstance(checkpoint, Checkpoint) or not events:
        return make_refusal(RefusalCode.OBSERVATION_GAP, boundary)
    if (
        checkpoint.epoch != epoch
        or checkpoint.first_sequence != 0
        or checkpoint.last_sequence != len(events) - 1
        or checkpoint.last_event_id != events[-1].event_id
        or checkpoint.child_frontier != child_frontier
        or checkpoint.boundary != closure_boundary
        or not checkpoint.sealed
        or checkpoint.loss_count != 0
        or checkpoint.initial_state_ref is None
        or checkpoint.checkpoint_ref is None
    ):
        return make_refusal(RefusalCode.OBSERVATION_GAP, boundary)
    covered = frozenset(cat for cat in checkpoint.coverage if cat not in checkpoint.gaps)
    return refuse_missing_coverage(covered, boundary)


@dataclass(frozen=True, slots=True, kw_only=True)
class _RecordedStream:
    """One process's recorded stream at seal time, before its observer scope is added."""

    profile_id: str
    instance: ClosureProcessInstance
    epoch: str
    entrypoint_ids: tuple[str, ...]
    runtime_nodes: tuple[str, ...]
    events: tuple[LoadEvent, ...]
    child_frontier: tuple[str, ...]
    state: Literal["running", "terminated"]


@dataclass(slots=True, kw_only=True)
class _ChildStream:
    """A verified child's stream while the collector runs; sealed by ``build_envelope``."""

    profile_id: str
    instance: ClosureProcessInstance
    epoch: str
    entrypoint_ids: tuple[str, ...]
    runtime_nodes: tuple[str, ...]
    events: list[LoadEvent] = field(default_factory=list)
    terminated: bool = False

    def append(
        self,
        *,
        kind: StreamEventKind,
        node_id: str | None = None,
        loaded: ContentIdentity | None = None,
        loader: str = "loader-v1",
    ) -> LoadEvent:
        event = stream_event(
            self.profile_id,
            len(self.events),
            kind=kind,
            node_id=node_id,
            loaded=loaded,
            loader=loader,
        )
        self.events.append(event)
        return event


class WorkerClosureCollector:
    """Opt-in collector assembling the worker-half LoadedClosureEnvelope.

    Guard invariants:
    - Never counts ``box_profile.closure`` as complete coverage or a verified load.
    - Never counts an unverified/surrogate launcher registration
      (``refuse_surrogate_child_registration``) as complete coverage or authentic origin.
    - Binds the closure to the authenticated ``WorkerObservation``: worker process
      pairing, selection, job revision, dispatch identity and route.
    - Builds no coverage: each process's ``Checkpoint`` (coverage, gaps, interval,
      seal, refs) is the observer's own sealed scope record, copied verbatim at
      ``build_envelope`` after it is checked against the recorded stream.
    - Validates the resulting ``LoadedClosureEnvelope`` with ``validate_loaded_envelope``
      and requires all 10 ``ALL_N3_COVERAGE_CATEGORIES`` in every process's scope.
    """

    def __init__(
        self,
        *,
        binding: ClosureBinding,
        closure_boundary: ClosureBoundary,
        reviewed_graph_ref: EvidenceRef,
        graph_id: str,
        worker_instance: ClosureProcessInstance,
        worker_profile_id: str = "worker",
        worker_entrypoint_ids: tuple[str, ...] = ("worker-entry",),
        worker_runtime_nodes: tuple[str, ...] = ("interpreter-worker", "stdlib-worker"),
        collector_id: str = WORKER_CLOSURE_COLLECTOR_ID,
        collector_version: str = WORKER_CLOSURE_COLLECTOR_VERSION,
        mechanism: str = WORKER_CLOSURE_MECHANISM,
        envelope_id: str = "envelope-worker-1",
        evidence: DecisionEvidence,
    ) -> None:
        self._binding = binding
        self._closure_boundary = closure_boundary
        self._reviewed_graph_ref = reviewed_graph_ref
        self._graph_id = graph_id
        self._worker_instance = worker_instance
        self._worker_profile_id = worker_profile_id
        self._worker_entrypoint_ids = worker_entrypoint_ids
        self._worker_runtime_nodes = worker_runtime_nodes
        self._collector_id = collector_id
        self._collector_version = collector_version
        self._mechanism = mechanism
        self._envelope_id = envelope_id
        self._worker_epoch: str | None = None
        self._evidence = evidence

        self._launch_observed = False
        self._early_bootstrap_observed = False
        self._runner_bootstrap_observed = False
        self._late_attach_tainted = False
        self._surrogate_registration_tainted = False
        self._box_profile_closure_ignored = False

        self._worker_events: list[LoadEvent] = []
        self._children: dict[str, _ChildStream] = {}
        self._child_frontier_ids: list[str] = []

    @property
    def box_profile_closure_ignored(self) -> bool:
        return self._box_profile_closure_ignored

    @property
    def surrogate_registration_tainted(self) -> bool:
        return self._surrogate_registration_tainted

    @property
    def recorded_streams(self) -> dict[str, tuple[LoadEvent, ...]]:
        """Each process's recorded events by closure instance id; empty before a launch."""
        streams = {
            child.instance.instance_id: tuple(child.events) for child in self._children.values()
        }
        if self._worker_events:
            streams = {self._worker_instance.instance_id: tuple(self._worker_events), **streams}
        return streams

    def _append_worker_event(
        self,
        *,
        kind: StreamEventKind,
        node_id: str | None = None,
        loaded: ContentIdentity | None = None,
        loader: str = "loader-v1",
        child_instance: str | None = None,
    ) -> LoadEvent:
        ev = stream_event(
            self._worker_profile_id,
            len(self._worker_events),
            kind=kind,
            node_id=node_id,
            loaded=loaded,
            loader=loader,
            child_instance=child_instance,
        )
        self._worker_events.append(ev)
        return ev

    def _append_worker_loads(self, loads: Sequence[ObservedLoad]) -> tuple[LoadEvent, ...]:
        added: list[LoadEvent] = []
        for load in loads:
            added.append(
                self._append_worker_event(
                    kind=load.event_kind, node_id=load.node_id, loaded=load.loaded
                )
            )
        return tuple(added)

    def _refuse_unbound_observation(
        self, observation: WorkerObservation, boundary: Boundary
    ) -> Refusal | None:
        """Refuse unless the closure binding names the observed worker and its job."""
        unpaired = refuse_unpaired_process_instances(
            observation.worker_instance, self._worker_instance, boundary=boundary
        )
        if unpaired is not None:
            return unpaired
        binding = self._binding
        job = observation.job
        if (
            observation.selection_revision != binding.selection_revision
            or job.selection_revision != binding.selection_revision
        ):
            return make_refusal(
                RefusalCode.SELECTION_CHANGED,
                boundary,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
            )
        if getattr(job, "route", binding.route) != binding.route:
            return make_refusal(
                RefusalCode.ROUTE_UNSUPPORTED,
                boundary,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )
        target = job.pre_dispatch_or_running_job
        if not isinstance(target, JobKey):
            # A pre-dispatch job has no dispatch nonce or attempt to bind.
            return make_refusal(
                RefusalCode.DISPATCH_CHANGED,
                boundary,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
            )
        if target.job_revision != binding.job_revision:
            return make_refusal(
                RefusalCode.SELECTION_CHANGED,
                boundary,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
            )
        dispatch = target.dispatch
        if (
            dispatch.execution_uuid != binding.execution_uuid
            or dispatch.dispatch_nonce != binding.dispatch_nonce
            or dispatch.running_attempt != binding.attempt
        ):
            return make_refusal(
                RefusalCode.DISPATCH_CHANGED,
                boundary,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
            )
        return None

    def record_docker_launch(
        self,
        *,
        execution_id: str,
        container_id: str,
        worker_observation: WorkerObservation,
        runtime_loads: Sequence[ObservedLoad] = (),
        boundary: Boundary = "A_PRE_CREATE",
    ) -> Result[LoadEvent]:
        if execution_id != self._binding.execution_uuid:
            return make_refusal(
                RefusalCode.DISPATCH_CHANGED,
                boundary,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
            )
        if (
            self._worker_instance.container_identity is not None
            and container_id != self._worker_instance.container_identity
        ):
            return make_refusal(
                RefusalCode.RUNTIME_CHANGED,
                boundary,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
            )
        unbound = self._refuse_unbound_observation(worker_observation, boundary)
        if unbound is not None:
            return unbound
        self._worker_epoch = worker_observation.worker_instance.exec_generation.witness_reference
        self._launch_observed = True
        ev = self._append_worker_event(kind="start", loader="trusted-launch")
        self._append_worker_loads(runtime_loads)
        return AcceptedData(data=ev, evidence=self._evidence)

    def record_early_bootstrap(
        self,
        *,
        execution_id: str,
        had_box_profile: bool,
        bootstrap_loads: Sequence[ObservedLoad] = (),
        use_box_profile_closure_as_complete: bool = False,
        boundary: Boundary = "B_PRE_REQUEST",
    ) -> Result[tuple[LoadEvent, ...]]:
        if not self._launch_observed or execution_id != self._binding.execution_uuid:
            self._late_attach_tainted = True
            return make_refusal(RefusalCode.OBSERVATION_GAP, boundary)
        if had_box_profile or use_box_profile_closure_as_complete:
            # Guard invariant: box_profile.closure never counts as complete coverage.
            self._box_profile_closure_ignored = True
            if use_box_profile_closure_as_complete and not bootstrap_loads:
                return make_refusal(RefusalCode.CLOSURE_INCOMPLETE, boundary)
        if not bootstrap_loads:
            return make_refusal(RefusalCode.CLOSURE_INCOMPLETE, boundary)
        added = self._append_worker_loads(bootstrap_loads)
        self._early_bootstrap_observed = True
        return AcceptedData(data=added, evidence=self._evidence)

    def record_runner_bootstrap(
        self,
        *,
        execution_id: str,
        loads: Sequence[ObservedLoad] = (),
        boundary: Boundary = "B_PRE_REQUEST",
    ) -> Result[tuple[LoadEvent, ...]]:
        if (
            not self._launch_observed
            or not self._early_bootstrap_observed
            or execution_id != self._binding.execution_uuid
        ):
            self._late_attach_tainted = True
            return make_refusal(RefusalCode.OBSERVATION_GAP, boundary)
        if not loads:
            return make_refusal(RefusalCode.CLOSURE_INCOMPLETE, boundary)
        added = self._append_worker_loads(loads)
        self._runner_bootstrap_observed = True
        return AcceptedData(data=added, evidence=self._evidence)

    def record_script_launch(
        self,
        *,
        agent_name: str,
        run_id: str,
        boundary: Boundary = "C_PRE_EXECUTION",
    ) -> Result[None]:
        _ = agent_name
        if (
            not self._runner_bootstrap_observed
            or run_id != self._binding.execution_uuid
        ):
            self._late_attach_tainted = True
            return make_refusal(RefusalCode.OBSERVATION_GAP, boundary)
        return AcceptedData(data=None, evidence=self._evidence)

    def record_surrogate_registration_attempt(
        self,
        *,
        surrogate_kind: str,
        boundary: Boundary = "C_PRE_EXECUTION",
    ) -> Refusal:
        """Taint collector and refuse surrogate/unverified launcher registration."""
        self._surrogate_registration_tainted = True
        return refuse_surrogate_child_registration(
            surrogate_kind=surrogate_kind,
            boundary=boundary,
        )

    def refuse_child_spawn_before_registration(
        self,
        *,
        closure_instance: ClosureProcessInstance,
        registration_source: str = VERIFIED_LAUNCHER_REGISTRATION_SOURCE,
        boundary: Boundary = "C_PRE_EXECUTION",
    ) -> Refusal | None:
        """Every refusal ``record_verified_child_spawn`` gives, checked before any registry write.

        A launch adapter calls it before registering the child, so a child the
        closure refuses is never left in the registry. A refusal taints the
        collector exactly as the record call would; ``None`` records nothing.
        """
        if (
            registration_source in NON_PROVIDER_REGISTRATION_SOURCES
            or registration_source != VERIFIED_LAUNCHER_REGISTRATION_SOURCE
        ):
            return self.record_surrogate_registration_attempt(
                surrogate_kind=registration_source,
                boundary=boundary,
            )
        if not self._runner_bootstrap_observed:
            self._late_attach_tainted = True
            return make_refusal(RefusalCode.OBSERVATION_GAP, boundary)
        if self._mechanism not in AUTHENTICATED_STREAM_MECHANISMS:
            return make_refusal(RefusalCode.CLOSURE_INCOMPLETE, boundary)
        if closure_instance.parent_instance != self._worker_instance.instance_id:
            return make_refusal(
                RefusalCode.SUBJECT_MISMATCH,
                boundary,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
            )
        return None

    def record_verified_child_spawn(
        self,
        *,
        entry: RegisteredChildEntry,
        registration_source: str = VERIFIED_LAUNCHER_REGISTRATION_SOURCE,
        child_profile_id: str = "child",
        child_entrypoint_ids: tuple[str, ...] = ("child-entry",),
        child_runtime_nodes: tuple[str, ...] = ("interpreter-worker", "stdlib-worker"),
        child_runtime_loads: Sequence[ObservedLoad] = (),
        child_loads: Sequence[ObservedLoad] = (),
        boundary: Boundary = "C_PRE_EXECUTION",
    ) -> Result[LoadEvent]:
        """Record a verified child birth: the worker's child event and the child's stream.

        The child's stream starts at the verified registration and holds its
        observed loads; its coverage is the observer's sealed scope record, given
        to ``build_envelope``.
        """
        refused = self.refuse_child_spawn_before_registration(
            closure_instance=entry.closure_instance,
            registration_source=registration_source,
            boundary=boundary,
        )
        if refused is not None:
            return refused
        c_inst = entry.closure_instance
        worker_event = self._append_worker_event(
            kind="child",
            loader="trusted-launch",
            child_instance=c_inst.instance_id,
        )
        if c_inst.instance_id not in self._child_frontier_ids:
            self._child_frontier_ids.append(c_inst.instance_id)

        child = _ChildStream(
            profile_id=child_profile_id,
            instance=c_inst,
            epoch=entry.host_instance.exec_generation.witness_reference,
            entrypoint_ids=child_entrypoint_ids or (f"{child_profile_id}-entry",),
            runtime_nodes=child_runtime_nodes or self._worker_runtime_nodes,
        )
        child.append(kind="start", loader="trusted-launch")
        for load in (*child_runtime_loads, *child_loads):
            child.append(kind=load.event_kind, node_id=load.node_id, loaded=load.loaded)
        self._children[c_inst.instance_id] = child
        return AcceptedData(data=worker_event, evidence=self._evidence)

    def record_child_termination(
        self,
        *,
        child_instance_id: str,
        boundary: Boundary = "C_PRE_EXECUTION",
    ) -> Result[LoadEvent]:
        """Close a recorded child's stream with its observed end.

        The child is sealed as ``terminated`` only after this; an unknown or
        already closed child is a gap.
        """
        child = self._children.get(child_instance_id)
        if child is None or child.terminated:
            return make_refusal(RefusalCode.OBSERVATION_GAP, boundary)
        end_event = child.append(kind="end", loader="trusted-launch")
        child.terminated = True
        return AcceptedData(data=end_event, evidence=self._evidence)

    def build_envelope(
        self,
        *,
        observer_checkpoints: Mapping[str, Checkpoint],
        boundary: Boundary | None = None,
    ) -> Result[LoadedClosureEnvelope]:
        """Seal the recorded streams into the worker half, each with its observer's scope.

        ``observer_checkpoints`` maps every recorded process's closure instance id
        to the observer's own sealed ``Checkpoint`` for it. The collector checks
        each against the recorded stream (``refuse_observer_scope_shortfall``),
        then copies it verbatim; it builds no coverage, interval or seal itself.
        """
        eff_boundary: Boundary = boundary or self._closure_boundary.phase
        if self._late_attach_tainted or not (
            self._launch_observed
            and self._early_bootstrap_observed
            and self._runner_bootstrap_observed
        ):
            return make_refusal(RefusalCode.OBSERVATION_GAP, eff_boundary)
        if self._surrogate_registration_tainted:
            return refuse_surrogate_child_registration(
                surrogate_kind="surrogate_tainted",
                boundary=eff_boundary,
            )
        if self._mechanism not in AUTHENTICATED_STREAM_MECHANISMS:
            return make_refusal(RefusalCode.CLOSURE_INCOMPLETE, eff_boundary)

        if not self._worker_events or self._worker_epoch is None:
            return make_refusal(RefusalCode.CLOSURE_INCOMPLETE, eff_boundary)
        streams = self._recorded_process_streams(self._worker_epoch)
        recorded_ids = {stream.instance.instance_id for stream in streams}
        if not recorded_ids <= set(observer_checkpoints):
            # A recorded process the observer sealed no scope for.
            return make_refusal(RefusalCode.OBSERVATION_GAP, eff_boundary)
        if set(observer_checkpoints) != recorded_ids:
            # The observer sealed a process the collector never recorded.
            return make_refusal(RefusalCode.CLOSURE_INCOMPLETE, eff_boundary)
        for stream in streams:
            shortfall = refuse_observer_scope_shortfall(
                observer_checkpoints[stream.instance.instance_id],
                epoch=stream.epoch,
                events=stream.events,
                child_frontier=stream.child_frontier,
                closure_boundary=self._closure_boundary,
                boundary=eff_boundary,
            )
            if shortfall is not None:
                return shortfall
        processes = tuple(
            self._sealed_observation(stream, observer_checkpoints[stream.instance.instance_id])
            for stream in streams
        )
        raw_env = ClosureEnvelope(
            schema="p3-reviewed-loaded-closure/1",
            envelope_id=self._envelope_id,
            reviewed_graph=self._reviewed_graph_ref,
            legacy_links=(),
            binding=self._binding,
            boundary=self._closure_boundary,
            process_observations=processes,
            provenance_refs=(),
        )
        try:
            validated = validate_loaded_envelope(to_wire(raw_env))
        except TargetRefused as exc:
            code = (
                RefusalCode.CLOSURE_VERSION
                if exc.code == "TARGET_SCHEMA_MISMATCH"
                else RefusalCode.CLOSURE_INCOMPLETE
            )
            return make_refusal(code, eff_boundary)
        return AcceptedData(data=validated, evidence=self._evidence)

    def _recorded_process_streams(self, worker_epoch: str) -> tuple[_RecordedStream, ...]:
        """The worker's stream, then each verified child's, as recorded so far."""
        worker = _RecordedStream(
            profile_id=self._worker_profile_id,
            instance=self._worker_instance,
            epoch=worker_epoch,
            entrypoint_ids=self._worker_entrypoint_ids,
            runtime_nodes=self._worker_runtime_nodes,
            events=tuple(self._worker_events),
            child_frontier=tuple(self._child_frontier_ids),
            state="running",
        )
        children = tuple(
            _RecordedStream(
                profile_id=child.profile_id,
                instance=child.instance,
                epoch=child.epoch,
                entrypoint_ids=child.entrypoint_ids,
                runtime_nodes=child.runtime_nodes,
                events=tuple(child.events),
                child_frontier=(),
                state="terminated" if child.terminated else "running",
            )
            for child in self._children.values()
        )
        return (worker, *children)

    def _sealed_observation(
        self, stream: _RecordedStream, observer_checkpoint: Checkpoint
    ) -> ProcessObservation:
        """One process's observation: its recorded stream and the observer's scope, verbatim."""
        return ProcessObservation(
            profile_id=stream.profile_id,
            instance=stream.instance,
            binding=self._binding,
            graph_id=self._graph_id,
            entrypoint_ids=stream.entrypoint_ids,
            runtime_nodes=stream.runtime_nodes,
            collector_id=self._collector_id,
            collector_version=self._collector_version,
            mechanism=self._mechanism,
            process_ref=make_evidence_ref(f"process-{stream.profile_id}"),
            collector_ref=make_evidence_ref(f"collector-{stream.profile_id}"),
            events=stream.events,
            checkpoint=observer_checkpoint,
            state=stream.state,
        )



def _target_refusal(
    exc: TargetRefused, otherwise: RefusalCode, boundary: Boundary
) -> Refusal:
    """Map a landed validator refusal: schema/version mismatch -> CLOSURE_VERSION."""
    code = (
        RefusalCode.CLOSURE_VERSION
        if exc.code == "TARGET_SCHEMA_MISMATCH"
        else otherwise
    )
    return make_refusal(code, boundary, retry_kind=RetryKind.NOT_APPLICABLE)


@dataclass(frozen=True, slots=True)
class DualRoleEnvelope:
    """Worker and peer (host) halves merged into one envelope for the comparator.

    ``observed_bytes`` is derived, never supplied: it is the merged envelope's
    content identity only when both halves' supplied observer identities equal
    their own ``content``. When either half's identity is unavailable (``None``)
    it stays ``None``, so ``compare_loaded_source`` returns UNKNOWN
    ``OBSERVER_ORIGIN``, never MATCH.
    """

    envelope: LoadedClosureEnvelope
    observed_bytes: ContentIdentity | None


def merge_dual_role_halves(
    *,
    worker_envelope: LoadedClosureEnvelope,
    worker_observed_bytes: ContentIdentity | None,
    peer_envelope: LoadedClosureEnvelope | None,
    peer_observed_bytes: ContentIdentity | None,
    boundary: Boundary,
    evidence: DecisionEvidence,
) -> Result[DualRoleEnvelope]:
    """Check both halves and their observer identities, then merge them.

    Each half is revalidated and only the validated value is used: a half's
    ``content`` field is caller-set (``LoadedClosureEnvelope`` binds it to
    nothing), so it must equal the content identity of the half's own bytes.

    Fails closed, before merging:
    - a half fails ``validate_loaded_envelope`` -> ``CLOSURE_VERSION`` for a
      schema/version mismatch (one accepted envelope schema, so validated halves
      share it), else ``CLOSURE_INCOMPLETE``; missing peer -> ``CLOSURE_INCOMPLETE``
    - a half's ``content`` field differs from its validated content (stale or
      forged) -> ``CLOSURE_MISMATCH``
    - peer ``binding`` or ``boundary`` differs from the worker's -> ``SUBJECT_MISMATCH``
    - peer ``reviewed_graph`` or ``legacy_links`` differs -> ``CLOSURE_MISMATCH``
    - a supplied half observer identity differs from that half's validated
      content -> ``CLOSURE_MISMATCH`` (REFUSED ``OBSERVER_ORIGIN``)

    The merged envelope keeps the shared fields, puts the peer's observations
    before the worker's, keeps every distinct provenance ref of both halves
    (peer first) and gets the id ``"<worker envelope_id>+<peer envelope_id>"``.
    """
    try:
        worker_validated = validate_loaded_envelope(to_wire(worker_envelope.envelope))
    except TargetRefused as exc:
        return _target_refusal(exc, RefusalCode.CLOSURE_INCOMPLETE, boundary)
    if peer_envelope is None:
        return make_refusal(RefusalCode.CLOSURE_INCOMPLETE, boundary)
    try:
        peer_validated = validate_loaded_envelope(to_wire(peer_envelope.envelope))
    except TargetRefused as exc:
        return _target_refusal(exc, RefusalCode.CLOSURE_INCOMPLETE, boundary)
    if (
        worker_envelope.content != worker_validated.content
        or peer_envelope.content != peer_validated.content
    ):
        return make_refusal(
            RefusalCode.CLOSURE_MISMATCH,
            boundary,
            retry_kind=RetryKind.NEW_BINDING_REQUIRED,
        )

    worker, peer = worker_validated.envelope, peer_validated.envelope
    if peer.binding != worker.binding or peer.boundary != worker.boundary:
        return make_refusal(
            RefusalCode.SUBJECT_MISMATCH,
            boundary,
            retry_kind=RetryKind.NEW_BINDING_REQUIRED,
        )
    if (
        peer.reviewed_graph != worker.reviewed_graph
        or peer.legacy_links != worker.legacy_links
    ):
        return make_refusal(
            RefusalCode.CLOSURE_MISMATCH,
            boundary,
            retry_kind=RetryKind.NEW_BINDING_REQUIRED,
        )
    for supplied, half in (
        (worker_observed_bytes, worker_validated),
        (peer_observed_bytes, peer_validated),
    ):
        if supplied is not None and supplied != half.content:
            return make_refusal(
                RefusalCode.CLOSURE_MISMATCH,
                boundary,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
            )

    provenance_refs: list[EvidenceRef] = []
    for ref in (*peer.provenance_refs, *worker.provenance_refs):
        if ref not in provenance_refs:
            provenance_refs.append(ref)
    merged_inner = replace(
        worker,
        envelope_id=f"{worker.envelope_id}+{peer.envelope_id}",
        process_observations=(*peer.process_observations, *worker.process_observations),
        provenance_refs=tuple(provenance_refs),
    )
    try:
        merged = validate_loaded_envelope(to_wire(merged_inner))
    except TargetRefused as exc:
        return _target_refusal(exc, RefusalCode.CLOSURE_INCOMPLETE, boundary)
    both_verified = (
        worker_observed_bytes is not None and peer_observed_bytes is not None
    )
    return AcceptedData(
        data=DualRoleEnvelope(
            envelope=merged,
            observed_bytes=merged.content if both_verified else None,
        ),
        evidence=evidence,
    )


def verify_and_compare_worker_closure(
    *,
    reviewed_graph: ReviewedSourceGraph,
    worker_envelope: LoadedClosureEnvelope,
    worker_observed_bytes: ContentIdentity | None,
    peer_envelope: LoadedClosureEnvelope | None,
    peer_observed_bytes: ContentIdentity | None,
    expectation: NativeClosureExpectation,
    verified_origins: VerifiedClosureOrigins,
    bookkeeper: CoverageBookkeeper,
    load_stream_refs: tuple[NativeEventRange, ...],
    boundary: Boundary = "C_PRE_EXECUTION",
    evidence: DecisionEvidence,
) -> Result[SourceClosureComparison]:
    """Validate the reviewed graph and both halves, check dual-role coverage, and compare.

    ``worker_observed_bytes`` and ``peer_observed_bytes`` are each half's verified
    observer identity (``None`` when its provider is unavailable).
    ``verified_origins`` carries the shared origins (reviewed bytes, expectation,
    validity checkpoint, facts); its ``observed_bytes`` must be ``None``: the
    merged envelope's observer origin is derived by ``merge_dual_role_halves``,
    never supplied or synthesized.

    The reviewed graph is revalidated and only the validated value reaches the
    bookkeeper and the comparator.

    Fails closed:
    - supplied ``verified_origins.observed_bytes`` -> ``CLOSURE_MISMATCH``
    - schema/version mismatch -> ``CLOSURE_VERSION``
    - reviewed graph ``content`` field differs from its validated content (stale
      or forged) -> ``CLOSURE_MISMATCH``
    - any ``merge_dual_role_halves`` refusal
    - missing host or container role -> ``CLOSURE_INCOMPLETE``
    - ``UNKNOWN`` or ``REFUSED`` from ``compare_loaded_source`` -> mapped via
      ``comparison_to_refusal`` (never mapped to ``MATCH``); a half without an
      observer identity gives UNKNOWN ``OBSERVER_ORIGIN`` -> ``OBSERVATION_GAP``.
    """
    if verified_origins.observed_bytes is not None:
        return make_refusal(
            RefusalCode.CLOSURE_MISMATCH,
            boundary,
            retry_kind=RetryKind.NEW_BINDING_REQUIRED,
        )
    try:
        reviewed_validated = validate_reviewed_graph(to_wire(reviewed_graph.graph))
    except TargetRefused as exc:
        return _target_refusal(exc, RefusalCode.CLOSURE_MISMATCH, boundary)
    if reviewed_graph.content != reviewed_validated.content:
        return make_refusal(
            RefusalCode.CLOSURE_MISMATCH,
            boundary,
            retry_kind=RetryKind.NEW_BINDING_REQUIRED,
        )

    dual = merge_dual_role_halves(
        worker_envelope=worker_envelope,
        worker_observed_bytes=worker_observed_bytes,
        peer_envelope=peer_envelope,
        peer_observed_bytes=peer_observed_bytes,
        boundary=boundary,
        evidence=evidence,
    )
    if isinstance(dual, Refusal):
        return dual
    merged_envelope = dual.data.envelope

    bk_res = bookkeeper.verify_envelope(
        merged_envelope,
        boundary=boundary,
        load_stream_refs=load_stream_refs,
        reviewed_graph=reviewed_validated,
        require_dual_role=True,
        evidence=evidence,
    )
    if isinstance(bk_res, Refusal):
        return bk_res

    merged_origins = replace(verified_origins, observed_bytes=dual.data.observed_bytes)
    try:
        comparison = compare_loaded_source(
            reviewed_validated,
            merged_envelope,
            expected=expectation,
            verified=merged_origins,
        )
    except TargetRefused as exc:
        return _target_refusal(exc, RefusalCode.CLOSURE_MISMATCH, boundary)

    if comparison.disposition != "MATCH" or comparison.reasons:
        return comparison_to_refusal(comparison, boundary)
    return AcceptedData(data=comparison, evidence=evidence)
