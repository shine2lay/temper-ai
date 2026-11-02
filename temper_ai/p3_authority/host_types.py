"""Bind canonical Ops generic records; no copied records or foreign parser.

Supplier leaves never import this module. Native reference implementations are
unconfigured; binding their abstract interfaces does not create capabilities.
The host inventory selections differ from the full independent registry records.
"""

from typing import TypeAlias

import p3_host_contracts as host
from p3_source_closure import (
    LoadedClosureEnvelope,
    N3Coverage,
    N3Gap,
    N3ObservationEpoch,
    N3SourceEpoch,
    ReviewedSourceGraph,
    SourceClosureComparison,
)

from .references import (
    NativeAdmission,
    NativeBirthIdentity,
    NativeContainerIdentity,
    NativeDisarmRelation,
    NativeEffectTarget,
    NativeEventRange,
    NativeGrantRef,
    NativeInterval,
    NativeObservationFields,
    NativeProcessRef,
    NativeRootObject,
    NativeSelection,
    NativeSubject,
    NativeWitness,
    ObservationSession,
)

RawRef = host.RawRef
HostProjectSelection = host.ProjectSelection
HostCalibrationSelection = host.CalibrationSelection
CallerSelection: TypeAlias = host.CallerSelection[ReviewedSourceGraph]
SelectedHostJob: TypeAlias = host.SelectedHostJob[NativeSelection, ReviewedSourceGraph]
ProcessInstance: TypeAlias = host.ProcessInstance[
    NativeWitness, NativeBirthIdentity, NativeProcessRef, LoadedClosureEnvelope,
    NativeContainerIdentity,
]
RootScope: TypeAlias = host.RootScope[NativeSubject, NativeRootObject]
RootBinding: TypeAlias = host.RootBinding[
    NativeRootObject, NativeProcessRef, NativeWitness, NativeGrantRef, NativeInterval,
]
ObservationScope: TypeAlias = host.ObservationScope[
    NativeSelection, NativeSubject, NativeRootObject, NativeObservationFields,
    ReviewedSourceGraph, NativeEffectTarget, NativeInterval,
]
HostObservation: TypeAlias = host.HostObservation[
    NativeSelection, NativeWitness, NativeBirthIdentity, NativeProcessRef,
    LoadedClosureEnvelope, NativeContainerIdentity, NativeRootObject, NativeGrantRef,
    NativeInterval, N3SourceEpoch, N3ObservationEpoch, NativeEventRange, N3Coverage, N3Gap,
]
HostCoverage: TypeAlias = host.HostCoverage[
    NativeSelection, NativeWitness, NativeBirthIdentity, NativeProcessRef,
    LoadedClosureEnvelope, NativeContainerIdentity, NativeRootObject, NativeGrantRef,
    NativeInterval, N3SourceEpoch, N3ObservationEpoch, NativeEventRange, N3Coverage,
    N3Gap, SourceClosureComparison, NativeEffectTarget, NativeSubject, ObservationSession,
]
HostEffect: TypeAlias = host.HostEffect[
    NativeSelection, NativeEffectTarget, NativeSubject, NativeRootObject,
]
EffectLease: TypeAlias = host.EffectLease[
    NativeAdmission, NativeSelection, NativeEffectTarget, NativeSubject,
    NativeRootObject, NativeProcessRef, N3SourceEpoch, N3ObservationEpoch,
    NativeInterval, NativeWitness,
]
LifecycleKey: TypeAlias = host.LifecycleKey[NativeSelection]
RowKey: TypeAlias = host.RowKey[NativeSelection]
OperationKey: TypeAlias = host.OperationKey[NativeSelection]
OccurrenceHandle: TypeAlias = host.OccurrenceHandle[
    NativeSelection, NativeWitness, NativeProcessRef, NativeEffectTarget,
    N3SourceEpoch, N3ObservationEpoch, NativeSubject, NativeRootObject,
]
RawPublication: TypeAlias = host.RawPublication[
    NativeSelection, NativeWitness, NativeProcessRef, NativeEffectTarget,
    N3SourceEpoch, N3ObservationEpoch, NativeSubject, NativeRootObject, NativeInterval,
]
ReceiptProvenance: TypeAlias = host.ReceiptProvenance[
    NativeWitness, NativeAdmission, NativeSelection, NativeProcessRef,
    NativeEffectTarget, N3SourceEpoch, N3ObservationEpoch, NativeSubject,
    NativeRootObject, NativeInterval, NativeDisarmRelation,
]
HostClosureJoin: TypeAlias = host.HostClosureJoin[
    NativeSelection, ReviewedSourceGraph, LoadedClosureEnvelope,
    SourceClosureComparison, NativeWitness,
]
