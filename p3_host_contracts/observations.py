"""Observation data and joins; no collection, coverage decision or comparison."""

from dataclasses import dataclass
from typing import Generic, Literal

from ._parameters import (
    BirthT,
    ComparisonT,
    ContainerT,
    CoverageT,
    EventRangeT,
    FieldsT,
    GapT,
    GrantT,
    IntervalT,
    ObservationEpochT,
    ObservedT,
    ProcessT,
    ReviewedT,
    RootObjectT,
    SelectionT,
    SourceEpochT,
    SubjectT,
    TargetT,
    WatchT,
    WitnessT,
)
from ._shape import choice, items, record, references, text_fields
from .effects import HostEffect
from .process_roots import ProcessInstance, RootBinding, RootScope
from .references import RawRef


@dataclass(frozen=True, slots=True)
class ObservationScope(
    Generic[SelectionT, SubjectT, RootObjectT, FieldsT, ReviewedT, TargetT, IntervalT]
):
    selection: SelectionT
    phase: Literal["A", "B", "C"]
    subjects: tuple[SubjectT, ...]
    root_scopes: tuple[RootScope[SubjectT, RootObjectT], ...]
    purpose: str
    permitted_fields: FieldsT
    reviewed: ReviewedT
    protected_effects: tuple[
        HostEffect[SelectionT, TargetT, SubjectT, RootObjectT], ...
    ]
    interval: IntervalT

    def __post_init__(self) -> None:
        references(
            selection=self.selection,
            permitted_fields=self.permitted_fields,
            reviewed=self.reviewed,
            interval=self.interval,
        )
        choice("phase", self.phase, ("A", "B", "C"))
        text_fields(purpose=self.purpose)
        items("subjects", self.subjects)
        items("root_scopes", self.root_scopes, RootScope)
        items("protected_effects", self.protected_effects, HostEffect)


@dataclass(frozen=True, slots=True)
class HostObservation(
    Generic[
        SelectionT,
        WitnessT,
        BirthT,
        ProcessT,
        ObservedT,
        ContainerT,
        RootObjectT,
        GrantT,
        IntervalT,
        SourceEpochT,
        ObservationEpochT,
        EventRangeT,
        CoverageT,
        GapT,
    ]
):
    selection: SelectionT
    process_instances: tuple[
        ProcessInstance[WitnessT, BirthT, ProcessT, ObservedT, ContainerT], ...
    ]
    roots: tuple[RootBinding[RootObjectT, ProcessT, WitnessT, GrantT, IntervalT], ...]
    observed: ObservedT
    source_epoch: SourceEpochT
    observation_epoch: ObservationEpochT
    event_range: EventRangeT
    observed_interval: IntervalT
    coverage: CoverageT
    gaps: tuple[GapT, ...]
    native_witness: WitnessT

    def __post_init__(self) -> None:
        references(
            selection=self.selection,
            observed=self.observed,
            source_epoch=self.source_epoch,
            observation_epoch=self.observation_epoch,
            event_range=self.event_range,
            observed_interval=self.observed_interval,
            coverage=self.coverage,
            native_witness=self.native_witness,
        )
        items("process_instances", self.process_instances, ProcessInstance)
        items("roots", self.roots, RootBinding)
        items("gaps", self.gaps)


@dataclass(frozen=True, slots=True)
class HostCoverage(
    Generic[
        SelectionT,
        WitnessT,
        BirthT,
        ProcessT,
        ObservedT,
        ContainerT,
        RootObjectT,
        GrantT,
        IntervalT,
        SourceEpochT,
        ObservationEpochT,
        EventRangeT,
        CoverageT,
        GapT,
        ComparisonT,
        TargetT,
        SubjectT,
        WatchT,
    ]
):
    observation: HostObservation[
        SelectionT,
        WitnessT,
        BirthT,
        ProcessT,
        ObservedT,
        ContainerT,
        RootObjectT,
        GrantT,
        IntervalT,
        SourceEpochT,
        ObservationEpochT,
        EventRangeT,
        CoverageT,
        GapT,
    ]
    comparison: ComparisonT
    native_binding: WitnessT
    through_boundary: HostEffect[SelectionT, TargetT, SubjectT, RootObjectT]
    live_watch: WatchT

    def __post_init__(self) -> None:
        record("observation", self.observation, HostObservation)
        references(
            comparison=self.comparison,
            native_binding=self.native_binding,
            live_watch=self.live_watch,
        )
        record("through_boundary", self.through_boundary, HostEffect)


@dataclass(frozen=True, slots=True)
class HostClosureJoin(Generic[SelectionT, ReviewedT, ObservedT, ComparisonT, WitnessT]):
    selection: SelectionT
    candidate_ref: RawRef
    host_review: ReviewedT
    worker_review_ref: ReviewedT
    host_observed: ObservedT
    worker_observed_ref: ObservedT
    comparison: ComparisonT
    native_witness: WitnessT

    def __post_init__(self) -> None:
        references(
            selection=self.selection,
            host_review=self.host_review,
            worker_review_ref=self.worker_review_ref,
            host_observed=self.host_observed,
            worker_observed_ref=self.worker_observed_ref,
            comparison=self.comparison,
            native_witness=self.native_witness,
        )
        record("candidate_ref", self.candidate_ref, RawRef)
