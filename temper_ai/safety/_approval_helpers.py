"""Helper functions for ApprovalWorkflow.

Extracted from ApprovalWorkflow to keep the class below 500 lines and 20 methods.
These are internal implementation details and should not be used directly.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from temper_ai.safety.approval import ApprovalRequest

logger = logging.getLogger(__name__)


def evict_oldest_completed(
    requests: dict[str, ApprovalRequest],
    max_requests: int,
) -> None:
    """Remove oldest requests to stay within max_requests limit.

    SA-07: Evicts completed requests first, then oldest pending requests
    as a fallback to prevent unbounded growth of pending requests.

    Args:
        requests: Dict of request_id -> ApprovalRequest (must be called under lock)
        max_requests: Maximum number of requests to keep
    """
    if len(requests) <= max_requests:
        return
    # Prefer evicting completed/rejected/expired over pending
    completed_ids = [rid for rid, req in requests.items() if not req.is_pending()]
    completed_ids.sort(key=lambda rid: requests[rid].created_at)
    to_remove = len(requests) - max_requests
    for rid in completed_ids[:to_remove]:
        del requests[rid]

    # SA-07: If still over limit (too many pending), evict oldest pending
    if len(requests) > max_requests:
        pending_ids = [rid for rid, req in requests.items() if req.is_pending()]
        pending_ids.sort(key=lambda rid: requests[rid].created_at)
        still_to_remove = len(requests) - max_requests
        for rid in pending_ids[:still_to_remove]:
            del requests[rid]


def check_approver_authorized(
    approver: str,
    request: ApprovalRequest,
    authorized_approvers: frozenset | None,
) -> str | None:
    """Validate that the approver is authorized and not self-approving.

    Args:
        approver: Identity of the approver
        request: The approval request
        authorized_approvers: Set of authorized approvers, or None for no checks

    Returns:
        None if authorized, or an error message string if not.
    """
    if authorized_approvers is None:
        return None

    # Self-approval check: requester cannot approve their own request
    if request.requester and approver == request.requester:
        return f"Self-approval denied: '{approver}' cannot approve their own request"

    # Authorization check
    if approver not in authorized_approvers:
        return f"Unauthorized approver: '{approver}' is not in the authorized approvers list"

    return None


def expire_request(request: ApprovalRequest) -> None:
    """Mark request as expired."""
    if request.is_pending():
        from temper_ai.safety.approval import ApprovalStatus

        request.status = ApprovalStatus.EXPIRED
        request.decision_reason = "Request expired without approval"


def trigger_approved_callbacks(
    request: ApprovalRequest,
    callbacks: list[Callable],
) -> None:
    """Trigger all approved callbacks."""
    for callback in callbacks:
        try:
            callback(request)
        except (
            Exception
        ) as e:  # noqa: BLE001 -- defensive cleanup for arbitrary callback
            # H-12: Log callback errors instead of silently ignoring
            logger.warning("Approval callback failed: %s", e, exc_info=True)


def trigger_rejected_callbacks(
    request: ApprovalRequest,
    callbacks: list[Callable],
) -> None:
    """Trigger all rejected callbacks."""
    for callback in callbacks:
        try:
            callback(request)
        except (
            Exception
        ) as e:  # noqa: BLE001 -- defensive cleanup for arbitrary callback
            # H-12: Log callback errors instead of silently ignoring
            logger.warning("Rejection callback failed: %s", e, exc_info=True)
