"""Occurrence and publication records, not an issuer or a receipt wire format."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Literal, TypeAlias

from ._parameters import (
    AdmissionT,
    DisarmT,
    IntervalT,
    ObservationEpochT,
    ProcessT,
    RootObjectT,
    SelectionT,
    SourceEpochT,
    SubjectT,
    TargetT,
    WitnessT,
)
from ._shape import (
    choice,
    integer,
    items,
    optional_record,
    record,
    references,
    text_fields,
)
from .effects import HostEffect
from .references import RawRef


@dataclass(frozen=True, slots=True)
class LifecycleKey(Generic[SelectionT]):
    selection: SelectionT
    launch_id: str
    operation_id: str

    def __post_init__(self) -> None:
        references(selection=self.selection)
        text_fields(launch_id=self.launch_id, operation_id=self.operation_id)


@dataclass(frozen=True, slots=True)
class RowKey(Generic[SelectionT]):
    selection: SelectionT
    window_id: str
    binding_ref: RawRef
    writer: str
    row: str
    operation: str
    request_id: str
    sequence: int
    request_raw_ref: RawRef

    def __post_init__(self) -> None:
        references(selection=self.selection)
        text_fields(
            window_id=self.window_id,
            writer=self.writer,
            row=self.row,
            operation=self.operation,
            request_id=self.request_id,
        )
        record("binding_ref", self.binding_ref, RawRef)
        record("request_raw_ref", self.request_raw_ref, RawRef)
        integer("sequence", self.sequence, minimum=1)


OperationKey: TypeAlias = LifecycleKey[SelectionT] | RowKey[SelectionT]


@dataclass(frozen=True, slots=True)
class OccurrenceHandle(
    Generic[
        SelectionT,
        WitnessT,
        ProcessT,
        TargetT,
        SourceEpochT,
        ObservationEpochT,
        SubjectT,
        RootObjectT,
    ]
):
    key: OperationKey[SelectionT]
    witness: WitnessT
    admitting_process: ProcessT
    controller: ProcessT | None
    executing_processes: tuple[ProcessT, ...]
    route_witness: WitnessT
    targets: tuple[TargetT, ...]
    source_epoch: SourceEpochT
    observation_epoch: ObservationEpochT
    admission_boundary: HostEffect[SelectionT, TargetT, SubjectT, RootObjectT]
    state: Literal["admitted", "started", "completed", "refused", "failed", "uncertain"]

    def __post_init__(self) -> None:
        record("key", self.key, (LifecycleKey, RowKey))
        references(
            witness=self.witness,
            admitting_process=self.admitting_process,
            route_witness=self.route_witness,
            source_epoch=self.source_epoch,
            observation_epoch=self.observation_epoch,
        )
        items("executing_processes", self.executing_processes)
        items("targets", self.targets)
        record("admission_boundary", self.admission_boundary, HostEffect)
        choice(
            "state",
            self.state,
            ("admitted", "started", "completed", "refused", "failed", "uncertain"),
        )
        if isinstance(self.key, RowKey) and self.controller is None:
            raise ValueError("row occurrence requires controller")
        if self.state in ("started", "completed") and not self.executing_processes:
            raise ValueError("observed execution requires executing_processes")


@dataclass(frozen=True, slots=True)
class RawPublication(
    Generic[
        SelectionT,
        WitnessT,
        ProcessT,
        TargetT,
        SourceEpochT,
        ObservationEpochT,
        SubjectT,
        RootObjectT,
        IntervalT,
    ]
):
    occurrence: OccurrenceHandle[
        SelectionT,
        WitnessT,
        ProcessT,
        TargetT,
        SourceEpochT,
        ObservationEpochT,
        SubjectT,
        RootObjectT,
    ]
    producer_instance: ProcessT
    publisher_instance: ProcessT
    request_raw_ref: RawRef | None
    receipt_raw_ref: RawRef
    evidence_refs: tuple[RawRef, ...]
    window_ref: RawRef | None
    numbered_log_ref: RawRef | None
    current_row_ref: RawRef | None
    publication_steps: tuple[WitnessT, ...]
    observed_interval: IntervalT
    outcome: Literal["success", "app-failure", "host-failure", "refused", "uncertain"]
    cleanup_state: Literal["not-required", "complete", "incomplete", "uncertain"]

    def __post_init__(self) -> None:
        record("occurrence", self.occurrence, OccurrenceHandle)
        references(
            producer_instance=self.producer_instance,
            publisher_instance=self.publisher_instance,
            observed_interval=self.observed_interval,
        )
        record("receipt_raw_ref", self.receipt_raw_ref, RawRef)
        items("evidence_refs", self.evidence_refs, RawRef)
        items("publication_steps", self.publication_steps)
        for name in (
            "request_raw_ref",
            "window_ref",
            "numbered_log_ref",
            "current_row_ref",
        ):
            value = getattr(self, name)
            optional_record(name, value, RawRef)
            if isinstance(self.occurrence.key, RowKey) and value is None:
                raise ValueError(f"row publication requires {name}")
        choice(
            "outcome",
            self.outcome,
            ("success", "app-failure", "host-failure", "refused", "uncertain"),
        )
        choice(
            "cleanup_state",
            self.cleanup_state,
            ("not-required", "complete", "incomplete", "uncertain"),
        )


@dataclass(frozen=True, slots=True)
class ReceiptProvenance(
    Generic[
        WitnessT,
        AdmissionT,
        SelectionT,
        ProcessT,
        TargetT,
        SourceEpochT,
        ObservationEpochT,
        SubjectT,
        RootObjectT,
        IntervalT,
        DisarmT,
    ]
):
    occurrence_witness: WitnessT
    publication_witness: WitnessT
    issuer_scope_ref: AdmissionT
    operation_key: OperationKey[SelectionT]
    producer_instance: ProcessT
    publisher_instance: ProcessT
    raw_publication: RawPublication[
        SelectionT,
        WitnessT,
        ProcessT,
        TargetT,
        SourceEpochT,
        ObservationEpochT,
        SubjectT,
        RootObjectT,
        IntervalT,
    ]
    state: Literal["complete", "incomplete", "uncertain"]
    predecessor: (
        ReceiptProvenance[
            WitnessT,
            AdmissionT,
            SelectionT,
            ProcessT,
            TargetT,
            SourceEpochT,
            ObservationEpochT,
            SubjectT,
            RootObjectT,
            IntervalT,
            DisarmT,
        ]
        | None
    )
    disarm_relation: DisarmT

    def __post_init__(self) -> None:
        references(
            occurrence_witness=self.occurrence_witness,
            publication_witness=self.publication_witness,
            issuer_scope_ref=self.issuer_scope_ref,
            producer_instance=self.producer_instance,
            publisher_instance=self.publisher_instance,
            disarm_relation=self.disarm_relation,
        )
        record("operation_key", self.operation_key, (LifecycleKey, RowKey))
        record("raw_publication", self.raw_publication, RawPublication)
        optional_record("predecessor", self.predecessor, ReceiptProvenance)
        choice("state", self.state, ("complete", "incomplete", "uncertain"))
