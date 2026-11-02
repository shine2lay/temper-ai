"""Canonical host data records with opaque, independently bound reference roles.

No native authority, source comparison, wire format, I/O or service dependency.
Import from this surface; providers supply the generic arguments independently.
"""

from .effects import EffectLease, HostEffect
from .observations import (
    HostClosureJoin,
    HostCoverage,
    HostObservation,
    ObservationScope,
)
from .process_roots import ProcessInstance, RootBinding, RootScope
from .publication import (
    LifecycleKey,
    OccurrenceHandle,
    OperationKey,
    RawPublication,
    ReceiptProvenance,
    RowKey,
)
from .references import RawRef
from .selection import (
    CalibrationSelection,
    CallerSelection,
    ProjectSelection,
    SelectedHostJob,
)

__all__ = (
    "RawRef",
    "ProjectSelection",
    "CalibrationSelection",
    "CallerSelection",
    "SelectedHostJob",
    "ProcessInstance",
    "RootScope",
    "RootBinding",
    "ObservationScope",
    "HostObservation",
    "HostCoverage",
    "HostEffect",
    "EffectLease",
    "LifecycleKey",
    "RowKey",
    "OperationKey",
    "OccurrenceHandle",
    "RawPublication",
    "ReceiptProvenance",
    "HostClosureJoin",
)
