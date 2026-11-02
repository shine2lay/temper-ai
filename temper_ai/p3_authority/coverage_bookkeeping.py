"""Synthetic-stream coverage bookkeeping and Systems N3 comparator delegation for P3 T4.

Tracks sequence/epoch/loss continuity, per-process required versus permitted
loads, parent-child linkage, bootstrap/generated/cache/runtime/native/dynamic/
control_plane/effect_fence category gaps, and causal boundary acknowledgements
over supplied authenticated synthetic streams.

Semantic source-closure comparison is delegated exclusively to Systems' pure
``p3_source_closure.compare_loaded_source`` implementation via ``SharedN3``.
No second comparator, production collector, or native authority is implemented
here.
"""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from typing import Final, Protocol

from p3_source_closure import (
    Checkpoint,
    LoadedClosureEnvelope,
    LoadEvent,
    N3Coverage,
    N3Gap,
    N3ObservationEpoch,
    NativeClosureExpectation,
    ProcessObservation,
    ProcessProfile,
    ReviewedSourceGraph,
    SourceClosureComparison,
    VerifiedClosureOrigins,
    compare_loaded_source,
)
from temper_ai.p3_authority.contract import (
    AcceptedData,
    AdmissionState,
    Boundary,
    DecisionEvidence,
    EffectState,
    NativeEventRange,
    NativeSelection,
    Phase,
    Refusal,
    RefusalCode,
    Result,
    RetryKind,
    SequenceUse,
    SharedN3,
)

ALL_N3_COVERAGE_CATEGORIES: Final[tuple[N3Coverage, ...]] = (
    "launch",
    "bootstrap",
    "python",
    "generated",
    "cache",
    "native",
    "dynamic",
    "children",
    "control_plane",
    "effect_fence",
)

AUTHENTICATED_STREAM_MECHANISMS: Final[frozenset[str]] = frozenset(
    {
        "synthetic-combined-launch-load-fence",
        "authenticated_synthetic_stream",
    }
)

NON_COMPLETE_CAPTURE_MECHANISMS: Final[frozenset[str]] = frozenset(
    {
        "late_proc_snapshot",
        "sys_modules_poll",
        "disk_tree_digest",
        "box_view_startup",
        "box_guard_classify",
        "box_bootstrap_env",
        "box_profile_closure",
        "unverified_collector",
    }
)


def boundary_to_phase(boundary: Boundary) -> Phase:
    """Map an N3 BoundaryPhase literal to its canonical P3 Phase enum (A, B, C)."""
    if boundary in ("A_PRE_CREATE", "A_PRE_ARM"):
        return Phase.A
    if boundary == "B_PRE_REQUEST":
        return Phase.B
    return Phase.C


def make_refusal(
    code: RefusalCode,
    boundary: Boundary,
    *,
    retry_kind: RetryKind = RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
    admission_state: AdmissionState = AdmissionState.NOT_ADMITTED,
    effect_state: EffectState = EffectState.NONE,
    sequence_use: SequenceUse = SequenceUse.UNUSED,
) -> Refusal:
    """Build a canonical 6-enum Refusal for the given boundary."""
    return Refusal(
        code=code,
        phase=boundary_to_phase(boundary),
        retry_kind=retry_kind,
        admission_state=admission_state,
        effect_state=effect_state,
        sequence_use=sequence_use,
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class ProcessCoverageSummary:
    """Bookkeeping summary for one observed process in a LoadedClosureEnvelope."""

    profile_id: str
    instance_id: str
    epoch: str
    first_sequence: int
    last_sequence: int
    last_event_id: str
    loss_count: int
    sealed: bool
    loaded_node_ids: frozenset[str]
    spawned_children: tuple[str, ...]
    coverage: tuple[N3Coverage, ...]
    gaps: tuple[N3Gap, ...]


class CoverageBookkeeper:
    """Bookkeeps supplied authenticated synthetic load streams and checkpoints.

    Never reads ``/proc``, ``sys.modules``, or disk trees. Refuses late starts,
    unverified collector mechanisms, sequence gaps/reorders/contradictory
    duplicates, positive loss counts, missing coverage categories, unpermitted
    or missing required loads, missing child observations, and stale frontiers.
    """

    def __init__(
        self,
        *,
        required_categories: tuple[N3Coverage, ...] = ALL_N3_COVERAGE_CATEGORIES,
    ) -> None:
        self._required_categories = required_categories
        self._summaries: dict[str, ProcessCoverageSummary] = {}

    @property
    def summaries(self) -> dict[str, ProcessCoverageSummary]:
        return dict(self._summaries)

    def verify_envelope(
        self,
        envelope: LoadedClosureEnvelope,
        *,
        boundary: Boundary,
        load_stream_refs: tuple[NativeEventRange, ...],
        reviewed_graph: ReviewedSourceGraph | None = None,
        since_cursor: N3ObservationEpoch | None = None,
        registered_child_ids: frozenset[str] = frozenset(),
        evidence: DecisionEvidence,
    ) -> Result[tuple[ProcessCoverageSummary, ...]]:
        """Validate all process observations and stream continuity in ``envelope``."""
        raw_env = envelope.envelope
        if raw_env.schema != "p3-reviewed-loaded-closure/1":
            return make_refusal(
                RefusalCode.CLOSURE_VERSION,
                boundary,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )
        if raw_env.boundary.phase != boundary:
            return make_refusal(
                RefusalCode.OBSERVATION_GAP,
                boundary,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
            )
        if not raw_env.process_observations:
            return make_refusal(RefusalCode.CLOSURE_INCOMPLETE, boundary)
        if not load_stream_refs:
            return make_refusal(RefusalCode.OBSERVATION_GAP, boundary)

        # Check stream ranges for reported loss or inverted sequence numbers
        for stream_range in load_stream_refs:
            if (
                not stream_range.continuity_witness.witness_reference
                or stream_range.first_sequence < 0
                or stream_range.last_sequence < stream_range.first_sequence
            ):
                return make_refusal(RefusalCode.OBSERVATION_GAP, boundary)
            if stream_range.lost_events is None or stream_range.lost_events > 0:
                return make_refusal(RefusalCode.OBSERVATION_GAP, boundary)

        profiles_by_id: dict[str, ProcessProfile] = {}
        if reviewed_graph is not None:
            if reviewed_graph.graph.schema != "p3-reviewed-source-graph/1":
                return make_refusal(
                    RefusalCode.CLOSURE_VERSION,
                    boundary,
                    retry_kind=RetryKind.NOT_APPLICABLE,
                )
            for prof in reviewed_graph.graph.process_profiles:
                profiles_by_id[prof.id] = prof

        observed_by_instance: dict[str, ProcessObservation] = {}
        observed_by_profile: dict[str, ProcessObservation] = {}
        computed_summaries: list[ProcessCoverageSummary] = []

        for proc_obs in raw_env.process_observations:
            res = self._verify_process_observation(
                proc_obs,
                boundary=boundary,
                profile=profiles_by_id.get(proc_obs.profile_id),
                evidence=evidence,
            )
            if isinstance(res, Refusal):
                return res
            summary = res.data
            computed_summaries.append(summary)
            observed_by_instance[proc_obs.instance.instance_id] = proc_obs
            observed_by_profile[proc_obs.profile_id] = proc_obs

        # Check parent-child linkage and child coverage (N3-14)
        for proc_obs in raw_env.process_observations:
            for child_ref in proc_obs.checkpoint.child_frontier:
                if (
                    child_ref not in observed_by_instance
                    and child_ref not in observed_by_profile
                ):
                    return make_refusal(RefusalCode.CLOSURE_INCOMPLETE, boundary)

        for reg_child_id in registered_child_ids:
            if (
                reg_child_id not in observed_by_instance
                and reg_child_id not in observed_by_profile
            ):
                return make_refusal(RefusalCode.CLOSURE_INCOMPLETE, boundary)

        # Check since_cursor frontier progression (N3-09 / N3-12 stale frontier)
        if since_cursor is not None:
            cursor_inst_id = since_cursor.instance.instance_id
            matching_obs = observed_by_instance.get(cursor_inst_id)
            if matching_obs is None:
                return make_refusal(RefusalCode.OBSERVATION_GAP, boundary)
            cp = matching_obs.checkpoint
            if (
                cp.epoch != since_cursor.frontier.epoch
                or cp.last_sequence < since_cursor.frontier.last_sequence
            ):
                return make_refusal(RefusalCode.OBSERVATION_GAP, boundary)
            if (
                cp.last_sequence == since_cursor.frontier.last_sequence
                and cp.last_event_id != since_cursor.frontier.last_event_id
            ):
                return make_refusal(RefusalCode.OBSERVATION_GAP, boundary)

        for item in computed_summaries:
            self._summaries[item.instance_id] = item

        return AcceptedData(data=tuple(computed_summaries), evidence=evidence)

    def _verify_process_observation(
        self,
        proc_obs: ProcessObservation,
        *,
        boundary: Boundary,
        profile: ProcessProfile | None,
        evidence: DecisionEvidence,
    ) -> Result[ProcessCoverageSummary]:
        # 1. Collector provenance & capture mechanism
        if proc_obs.process_ref is None or proc_obs.collector_ref is None:
            return make_refusal(RefusalCode.OBSERVATION_GAP, boundary)
        if proc_obs.mechanism in NON_COMPLETE_CAPTURE_MECHANISMS:
            return make_refusal(RefusalCode.CLOSURE_INCOMPLETE, boundary)
        if proc_obs.mechanism not in AUTHENTICATED_STREAM_MECHANISMS:
            return make_refusal(RefusalCode.CLOSURE_INCOMPLETE, boundary)

        cp: Checkpoint = proc_obs.checkpoint
        if cp.initial_state_ref is None or cp.checkpoint_ref is None:
            return make_refusal(RefusalCode.OBSERVATION_GAP, boundary)
        if cp.boundary.phase != boundary:
            return make_refusal(RefusalCode.OBSERVATION_GAP, boundary)
        if cp.loss_count > 0 or not cp.sealed:
            return make_refusal(RefusalCode.OBSERVATION_GAP, boundary)

        # 2. Coverage categories & explicit gaps
        if cp.gaps:
            if "effect_fence" in cp.gaps or "control_plane" in cp.gaps:
                return make_refusal(RefusalCode.OBSERVATION_GAP, boundary)
            return make_refusal(RefusalCode.CLOSURE_INCOMPLETE, boundary)

        present_coverage = frozenset(cp.coverage)
        for required_cat in self._required_categories:
            if required_cat not in present_coverage:
                if required_cat in ("effect_fence", "control_plane"):
                    return make_refusal(RefusalCode.OBSERVATION_GAP, boundary)
                return make_refusal(RefusalCode.CLOSURE_INCOMPLETE, boundary)

        # 3. Event stream continuity (starts at sequence 0 with 'start' before python loads)
        events: tuple[LoadEvent, ...] = proc_obs.events
        if not events or cp.first_sequence != 0:
            return make_refusal(RefusalCode.OBSERVATION_GAP, boundary)
        if events[0].sequence != 0 or events[0].kind != "start":
            # Late attach after interpreter start cannot establish bootstrap coverage
            return make_refusal(RefusalCode.OBSERVATION_GAP, boundary)

        seen_by_seq: dict[int, LoadEvent] = {}
        loaded_nodes: set[str] = set()
        spawned_children: list[str] = []
        expected_seq = 0

        for ev in events:
            if ev.origin_ref is None:
                return make_refusal(RefusalCode.OBSERVATION_GAP, boundary)
            if ev.sequence in seen_by_seq:
                prior = seen_by_seq[ev.sequence]
                if (
                    prior.event_id != ev.event_id
                    or prior.kind != ev.kind
                    or prior.node_id != ev.node_id
                    or prior.loaded != ev.loaded
                ):
                    return make_refusal(RefusalCode.OBSERVATION_GAP, boundary)
                continue
            if ev.sequence != expected_seq:
                return make_refusal(RefusalCode.OBSERVATION_GAP, boundary)
            seen_by_seq[ev.sequence] = ev
            expected_seq += 1

            if ev.node_id is not None:
                loaded_nodes.add(ev.node_id)
            if ev.kind == "child" and ev.child_instance is not None:
                spawned_children.append(ev.child_instance)

        last_ev = events[-1]
        if cp.last_sequence != last_ev.sequence or cp.last_event_id != last_ev.event_id:
            return make_refusal(RefusalCode.OBSERVATION_GAP, boundary)

        # 4. Required vs allowed loads when ReviewedSourceGraph ProcessProfile is provided
        if profile is not None:
            allowed = frozenset(profile.allowed_node_ids) | frozenset(profile.runtime_nodes)
            required = frozenset(profile.required_load_ids) | frozenset(profile.runtime_nodes)
            if not loaded_nodes.issubset(allowed):
                return make_refusal(RefusalCode.CLOSURE_MISMATCH, boundary)
            if not required.issubset(loaded_nodes):
                return make_refusal(RefusalCode.CLOSURE_INCOMPLETE, boundary)

        summary = ProcessCoverageSummary(
            profile_id=proc_obs.profile_id,
            instance_id=proc_obs.instance.instance_id,
            epoch=cp.epoch,
            first_sequence=cp.first_sequence,
            last_sequence=cp.last_sequence,
            last_event_id=cp.last_event_id,
            loss_count=cp.loss_count,
            sealed=cp.sealed,
            loaded_node_ids=frozenset(loaded_nodes),
            spawned_children=tuple(spawned_children),
            coverage=cp.coverage,
            gaps=cp.gaps,
        )
        return AcceptedData(data=summary, evidence=evidence)


class N3OriginResolverPort(Protocol):
    """Port supplying authenticated NativeClosureExpectation and VerifiedClosureOrigins for SharedN3."""

    @abstractmethod
    def resolve_closure_inputs(
        self,
        *,
        selection: NativeSelection,
        boundary: Boundary,
        reviewed: ReviewedSourceGraph,
        observed: LoadedClosureEnvelope,
    ) -> Result[tuple[NativeClosureExpectation, VerifiedClosureOrigins]]: ...


def comparison_to_refusal(
    comparison: SourceClosureComparison,
    boundary: Boundary,
) -> Refusal:
    """Map a non-MATCH Systems SourceClosureComparison to the canonical Refusal."""
    reasons = set(comparison.reasons)
    if comparison.disposition == "REFUSED":
        if "BINDING" in reasons:
            return make_refusal(
                RefusalCode.SUBJECT_MISMATCH,
                boundary,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
            )
        if "PROCESS_INSTANCE" in reasons:
            return make_refusal(
                RefusalCode.RUNTIME_CHANGED,
                boundary,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
            )
        return make_refusal(
            RefusalCode.CLOSURE_MISMATCH,
            boundary,
            retry_kind=RetryKind.NEW_BINDING_REQUIRED,
        )
    if "SEQUENCE_GAP" in reasons or "STALE_FRONTIER" in reasons or "OBSERVER_ORIGIN" in reasons:
        return make_refusal(RefusalCode.OBSERVATION_GAP, boundary)
    return make_refusal(RefusalCode.CLOSURE_INCOMPLETE, boundary)


class SharedN3Adapter(SharedN3):
    """Delegates source-closure comparison exclusively to Systems' ``compare_loaded_source``.

    Never implements a second comparator. When ``origin_resolver`` is absent or
    returns a Refusal, returns ``Refusal(code=RefusalCode.AUTHORITY_UNAVAILABLE, ...)``
    or the resolver's refusal.
    """

    def __init__(
        self,
        *,
        origin_resolver: N3OriginResolverPort | None = None,
        require_match: bool = False,
    ) -> None:
        self._origin_resolver = origin_resolver
        self._require_match = require_match

    def compare(
        self,
        reviewed: ReviewedSourceGraph,
        observed: LoadedClosureEnvelope,
        *,
        selection: NativeSelection,
        boundary: Boundary,
    ) -> Result[SourceClosureComparison]:
        if self._origin_resolver is None:
            return make_refusal(RefusalCode.AUTHORITY_UNAVAILABLE, boundary)
        resolved = self._origin_resolver.resolve_closure_inputs(
            selection=selection,
            boundary=boundary,
            reviewed=reviewed,
            observed=observed,
        )
        if isinstance(resolved, Refusal):
            return resolved
        expected, verified = resolved.data
        comparison = compare_loaded_source(
            reviewed,
            observed,
            expected=expected,
            verified=verified,
        )
        if self._require_match and comparison.disposition != "MATCH":
            return comparison_to_refusal(comparison, boundary)
        return AcceptedData(data=comparison, evidence=resolved.evidence)
