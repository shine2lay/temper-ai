"""Named effect descriptions and references to externally issued admissions."""

from dataclasses import dataclass
from typing import Generic, Literal, get_args

from ._parameters import (
    AdmissionT,
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
from ._shape import choice, items, record, references, text_fields
from .process_roots import RootScope

_EffectKind = Literal[
    "create",
    "copy",
    "network",
    "container",
    "proof",
    "publish-window",
    "register",
    "arm",
    "stop",
    "cleanup",
    "publish-request",
    "admit-row",
    "execute-row",
    "start",
    "signal",
    "probe",
    "case",
    "publish-receipt",
    "receive",
    "count",
]


@dataclass(frozen=True, slots=True)
class HostEffect(Generic[SelectionT, TargetT, SubjectT, RootObjectT]):
    kind: _EffectKind
    selection: SelectionT
    target: TargetT
    operation: str
    actor: SubjectT
    purpose: str
    roots: tuple[RootScope[SubjectT, RootObjectT], ...]
    boundary: str

    def __post_init__(self) -> None:
        choice("kind", self.kind, get_args(_EffectKind))
        references(selection=self.selection, target=self.target, actor=self.actor)
        text_fields(
            operation=self.operation, purpose=self.purpose, boundary=self.boundary
        )
        items("roots", self.roots, RootScope)


@dataclass(frozen=True, slots=True)
class EffectLease(
    Generic[
        AdmissionT,
        SelectionT,
        TargetT,
        SubjectT,
        RootObjectT,
        ProcessT,
        SourceEpochT,
        ObservationEpochT,
        IntervalT,
        WitnessT,
    ]
):
    native_admission: AdmissionT
    effect: HostEffect[SelectionT, TargetT, SubjectT, RootObjectT]
    actor_instance: ProcessT
    source_epoch: SourceEpochT
    observation_epoch: ObservationEpochT
    validity: IntervalT
    revocation_revision: WitnessT
    boundary_token: WitnessT

    def __post_init__(self) -> None:
        references(
            native_admission=self.native_admission,
            actor_instance=self.actor_instance,
            source_epoch=self.source_epoch,
            observation_epoch=self.observation_epoch,
            validity=self.validity,
            revocation_revision=self.revocation_revision,
            boundary_token=self.boundary_token,
        )
        record("effect", self.effect, HostEffect)
