"""Rules for linked receipts, shared by the service, adapters and the conformance kit.

One job: decide, from two receipts, whether a predecessor matches (exactly,
``None`` included) and whether a continuation row names the row it needs.
Pure functions; no store, no authentication. Whether a receipt is linked in a
window's chain is the ``HostProvenance`` adapter's own check
(``HostProvenance.verify_linked_receipt``).
"""

from typing import cast

from p3_host_contracts import ReceiptProvenance as _ReceiptProvenanceRecord
from p3_host_contracts import RowKey as _RowKeyRecord

from .boundary_types import REQUIRED_PREDECESSOR_ROW
from .host_types import OperationKey, ReceiptProvenance, RowKey
from .refusals import RefusalCode


def exact_receipt_equal(
    first: ReceiptProvenance | None, second: ReceiptProvenance | None
) -> bool:
    """True only for two ``ReceiptProvenance`` records of exactly that class, equal.

    Both type checks are needed: a subclass that overrides ``__eq__`` is asked
    first by ``==`` from either side. Nested records compare with dataclass
    equality, which is class-exact, so a subclass deeper in a predecessor
    chain is unequal too.
    """
    return (
        type(first) is _ReceiptProvenanceRecord
        and type(second) is _ReceiptProvenanceRecord
        and first == second
    )


def linked_predecessor_mismatch(
    caller: ReceiptProvenance | None, linked: ReceiptProvenance | None
) -> RefusalCode | None:
    """Exact predecessor match both ways, ``None`` included (ruling C2).

    Caller names none but one is linked -> PRIOR_MISSING. Caller names one but
    none is linked, or the two are not exactly equal -> PRIOR_UNVERIFIED.
    """
    if caller is None and linked is None:
        return None
    if caller is None:
        return RefusalCode.PRIOR_MISSING
    if not exact_receipt_equal(caller, linked):
        return RefusalCode.PRIOR_UNVERIFIED
    return None


def is_successful_row_receipt(receipt: ReceiptProvenance) -> bool:
    """A complete, successful receipt of a completed row occurrence."""
    return (
        type(receipt) is _ReceiptProvenanceRecord
        and type(receipt.operation_key) is _RowKeyRecord
        and receipt.state == "complete"
        and receipt.raw_publication.outcome == "success"
        and receipt.raw_publication.occurrence.state == "completed"
        and receipt.raw_publication.occurrence.key == receipt.operation_key
    )


def continuation_predecessor_refusal(
    key: OperationKey, predecessor: ReceiptProvenance | None
) -> RefusalCode | None:
    """``REQUIRED_PREDECESSOR_ROW`` rule on the predecessor a receipt names.

    Not a continuation row -> None. No predecessor -> PRIOR_MISSING. A
    predecessor that is not a successful receipt of the required row in the
    same selection revision and window -> PRIOR_UNVERIFIED.
    """
    if type(key) is not _RowKeyRecord:
        return None
    required_row = REQUIRED_PREDECESSOR_ROW.get(key.row)
    if required_row is None:
        return None
    if predecessor is None:
        return RefusalCode.PRIOR_MISSING
    if not is_successful_row_receipt(predecessor):
        return RefusalCode.PRIOR_UNVERIFIED
    # is_successful_row_receipt holds the predecessor's key to exactly RowKey.
    predecessor_key = cast(RowKey, predecessor.operation_key)
    if (
        predecessor_key.row != required_row
        or predecessor_key.selection.selection_revision
        != key.selection.selection_revision
        or predecessor_key.window_id != key.window_id
    ):
        return RefusalCode.PRIOR_UNVERIFIED
    return None


__all__ = [
    "continuation_predecessor_refusal",
    "exact_receipt_equal",
    "is_successful_row_receipt",
    "linked_predecessor_mismatch",
]
