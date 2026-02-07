"""Approval workflow system for high-risk actions.

This module provides an approval workflow that intercepts high-risk actions,
requests human approval, and manages approval/rejection decisions.

Key Features:
- Approval request creation and tracking
- Multiple approval strategies (single, multi-approver, consensus)
- Timeout handling with automatic rejection
- Integration with safety policy violations
- Approval history and audit trail

Example:
    >>> workflow = ApprovalWorkflow()
    >>> request = workflow.request_approval(
    ...     action={"tool": "deploy", "environment": "production"},
    ...     reason="Production deployment requires approval",
    ...     context={"agent": "deployer", "severity": ViolationSeverity.HIGH}
    ... )
    >>> # Later, after human review
    >>> workflow.approve(request.id, approver="alice")
    >>> result = workflow.get_result(request.id)
"""
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
import threading
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

from src.safety.interfaces import SafetyViolation


class ApprovalStatus(Enum):
    """Status of an approval request.

    States:
        PENDING: Awaiting approval
        APPROVED: Approved by required number of approvers
        REJECTED: Rejected by an approver
        EXPIRED: Timeout reached without approval
        CANCELLED: Request was cancelled
    """
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


@dataclass
class ApprovalRequest:
    """Represents a request for approval of a high-risk action.

    Attributes:
        id: Unique request identifier
        action: Action requiring approval
        reason: Why approval is required
        context: Execution context (agent, stage, workflow, etc.)
        violations: Safety violations that triggered this request
        status: Current approval status
        created_at: When request was created
        expires_at: When request expires (auto-reject)
        required_approvers: Number of approvals needed
        approvers: List of users who approved
        rejecters: List of users who rejected
        decision_reason: Reason for approval/rejection
        metadata: Additional request metadata
    """
    id: str = field(default_factory=lambda: str(uuid4()))
    action: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    requester: Optional[str] = None
    context: Dict[str, Any] = field(default_factory=dict)
    violations: List[SafetyViolation] = field(default_factory=list)
    status: ApprovalStatus = ApprovalStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    expires_at: Optional[datetime] = None
    required_approvers: int = 1
    approvers: List[str] = field(default_factory=list)
    rejecters: List[str] = field(default_factory=list)
    decision_reason: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_pending(self) -> bool:
        """Check if request is still pending."""
        return self.status == ApprovalStatus.PENDING

    def is_approved(self) -> bool:
        """Check if request was approved."""
        return self.status == ApprovalStatus.APPROVED

    def is_rejected(self) -> bool:
        """Check if request was rejected."""
        return self.status == ApprovalStatus.REJECTED

    def is_expired(self) -> bool:
        """Check if request expired."""
        return self.status == ApprovalStatus.EXPIRED

    def has_expired(self) -> bool:
        """Check if request has passed expiration time."""
        if self.expires_at is None:
            return False
        return datetime.now(UTC) >= self.expires_at

    def approval_count(self) -> int:
        """Get number of approvals received."""
        return len(self.approvers)

    def needs_more_approvals(self) -> bool:
        """Check if more approvals are needed."""
        return self.approval_count() < self.required_approvers

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "action": self.action,
            "reason": self.reason,
            "context": self.context,
            "violations": [v.to_dict() for v in self.violations],
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "required_approvers": self.required_approvers,
            "approvers": self.approvers,
            "rejecters": self.rejecters,
            "decision_reason": self.decision_reason,
            "metadata": self.metadata
        }


class ApprovalWorkflow:
    """Manages approval workflow for high-risk actions.

    Handles creation, tracking, and resolution of approval requests.
    Supports timeout, multiple approvers, and approval callbacks.

    Example:
        >>> workflow = ApprovalWorkflow(default_timeout_minutes=30)
        >>>
        >>> # Request approval
        >>> request = workflow.request_approval(
        ...     action={"tool": "delete_database", "database": "production"},
        ...     reason="Database deletion requires approval",
        ...     required_approvers=2
        ... )
        >>>
        >>> # Approve
        >>> workflow.approve(request.id, approver="alice")
        >>> workflow.approve(request.id, approver="bob")
        >>>
        >>> # Check result
        >>> if workflow.is_approved(request.id):
        ...     print("Action approved, proceeding...")
    """

    # Maximum stored requests to prevent unbounded memory growth
    MAX_REQUESTS = 10000

    def __init__(
        self,
        default_timeout_minutes: int = 60,
        auto_reject_on_timeout: bool = True,
        max_requests: int = MAX_REQUESTS,
        authorized_approvers: Optional[List[str]] = None,
    ):
        """Initialize approval workflow.

        Args:
            default_timeout_minutes: Default timeout for approval requests
            auto_reject_on_timeout: Automatically reject expired requests
            max_requests: Maximum stored requests before oldest are evicted
            authorized_approvers: List of authorized approver identifiers.
                If None, no authorization checks are performed (backward compat).
                If set, only listed approvers can approve/reject, and
                self-approval (requester == approver) is blocked.
        """
        self.default_timeout_minutes = default_timeout_minutes
        self.auto_reject_on_timeout = auto_reject_on_timeout
        self._max_requests = max_requests
        self._authorized_approvers: Optional[frozenset[str]] = (
            frozenset(authorized_approvers) if authorized_approvers is not None else None
        )
        self._lock = threading.Lock()  # C-02: Protect _requests dict from race conditions
        self._requests: Dict[str, ApprovalRequest] = {}
        self._on_approved_callbacks: List[Callable[[ApprovalRequest], None]] = []
        self._on_rejected_callbacks: List[Callable[[ApprovalRequest], None]] = []

    def request_approval(
        self,
        action: Dict[str, Any],
        reason: str,
        context: Optional[Dict[str, Any]] = None,
        violations: Optional[List[SafetyViolation]] = None,
        required_approvers: int = 1,
        timeout_minutes: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
        requester: Optional[str] = None,
    ) -> ApprovalRequest:
        """Create a new approval request.

        Args:
            action: Action requiring approval
            reason: Why approval is required
            context: Execution context
            violations: Safety violations that triggered this request
            required_approvers: Number of approvals needed (default: 1)
            timeout_minutes: Custom timeout (uses default if None)
            metadata: Additional request metadata
            requester: Identity of the agent/user requesting approval.
                Used for self-approval prevention when authorized_approvers is set.

        Returns:
            ApprovalRequest object

        Example:
            >>> request = workflow.request_approval(
            ...     action={"tool": "deploy", "env": "prod"},
            ...     reason="Production deployment",
            ...     required_approvers=2,
            ...     timeout_minutes=30
            ... )
        """
        timeout = timeout_minutes if timeout_minutes is not None else self.default_timeout_minutes
        expires_at = datetime.now(UTC) + timedelta(minutes=timeout)

        request = ApprovalRequest(
            action=action,
            reason=reason,
            requester=requester,
            context=context or {},
            violations=violations or [],
            expires_at=expires_at,
            required_approvers=required_approvers,
            metadata=metadata or {}
        )

        with self._lock:
            self._requests[request.id] = request

            # Evict oldest completed requests when over limit
            if len(self._requests) > self._max_requests:
                self._evict_oldest_completed()

        return request

    def _evict_oldest_completed(self) -> None:
        """Remove oldest requests to stay within max_requests limit.

        SA-07: Evicts completed requests first, then oldest pending requests
        as a fallback to prevent unbounded growth of pending requests.

        C-02: MUST be called while holding self._lock (caller's responsibility).
        This method is private and only called from request_approval() which
        already holds the lock.
        """
        if len(self._requests) <= self._max_requests:
            return
        # Prefer evicting completed/rejected/expired over pending
        completed_ids = [
            rid for rid, req in self._requests.items()
            if not req.is_pending()
        ]
        # Sort by creation time (oldest first) - request.id contains UUID so use created_at
        completed_ids.sort(key=lambda rid: self._requests[rid].created_at)
        to_remove = len(self._requests) - self._max_requests
        for rid in completed_ids[:to_remove]:
            del self._requests[rid]

        # SA-07: If still over limit (too many pending), evict oldest pending
        if len(self._requests) > self._max_requests:
            pending_ids = [
                rid for rid, req in self._requests.items()
                if req.is_pending()
            ]
            pending_ids.sort(key=lambda rid: self._requests[rid].created_at)
            still_to_remove = len(self._requests) - self._max_requests
            for rid in pending_ids[:still_to_remove]:
                del self._requests[rid]

    def _check_approver_authorized(self, approver: str, request: ApprovalRequest) -> Optional[str]:
        """Validate that the approver is authorized and not self-approving.

        Args:
            approver: Identity of the approver
            request: The approval request

        Returns:
            None if authorized, or an error message string if not.
        """
        if self._authorized_approvers is None:
            return None

        # Self-approval check: requester cannot approve their own request
        if request.requester and approver == request.requester:
            return (
                f"Self-approval denied: '{approver}' cannot approve their own request"
            )

        # Authorization check
        if approver not in self._authorized_approvers:
            return (
                f"Unauthorized approver: '{approver}' is not in the authorized approvers list"
            )

        return None

    def approve(
        self,
        request_id: str,
        approver: str,
        reason: Optional[str] = None
    ) -> bool:
        """Approve a request.

        Args:
            request_id: ID of request to approve
            approver: Name/ID of approver
            reason: Optional reason for approval

        Returns:
            True if approval was accepted, False if request not found/not pending

        Raises:
            PermissionError: If approver is not authorized or is self-approving

        Example:
            >>> workflow.approve("req-123", approver="alice", reason="Looks good")
        """
        with self._lock:
            request = self._requests.get(request_id)
            if not request:
                return False

            # Check if expired
            if self.auto_reject_on_timeout and request.has_expired():
                self._expire_request(request)
                return False

            # Can only approve pending requests
            if not request.is_pending():
                return False

            # Authorization check
            error = self._check_approver_authorized(approver, request)
            if error:
                raise PermissionError(error)

            # Add approver (avoid duplicates)
            if approver not in request.approvers:
                request.approvers.append(approver)

            # Check if we have enough approvals
            if not request.needs_more_approvals():
                request.status = ApprovalStatus.APPROVED
                request.decision_reason = reason
                self._trigger_approved_callbacks(request)

            return True

    def reject(
        self,
        request_id: str,
        rejecter: str,
        reason: Optional[str] = None
    ) -> bool:
        """Reject a request.

        Args:
            request_id: ID of request to reject
            rejecter: Name/ID of rejecter
            reason: Optional reason for rejection

        Returns:
            True if rejection was accepted, False if request not found/not pending

        Raises:
            PermissionError: If rejecter is not authorized

        Example:
            >>> workflow.reject("req-123", rejecter="bob", reason="Too risky")
        """
        with self._lock:
            request = self._requests.get(request_id)
            if not request:
                return False

            # Can only reject pending requests
            if not request.is_pending():
                return False

            # Authorization check (self-rejection is allowed — rejecting your own
            # request is not a security risk, unlike self-approval)
            if self._authorized_approvers is not None:
                if rejecter not in self._authorized_approvers:
                    raise PermissionError(
                        f"Unauthorized rejecter: '{rejecter}' is not in the authorized approvers list"
                    )

            # Add rejecter
            if rejecter not in request.rejecters:
                request.rejecters.append(rejecter)

            # One rejection is enough to reject the request
            request.status = ApprovalStatus.REJECTED
            request.decision_reason = reason
            self._trigger_rejected_callbacks(request)

            return True

    def cancel(self, request_id: str, reason: Optional[str] = None) -> bool:
        """Cancel a pending request.

        Args:
            request_id: ID of request to cancel
            reason: Optional reason for cancellation

        Returns:
            True if request was cancelled, False if not found/not pending
        """
        with self._lock:
            request = self._requests.get(request_id)
            if not request:
                return False

            if not request.is_pending():
                return False

            request.status = ApprovalStatus.CANCELLED
            request.decision_reason = reason
            return True

    def get_request(self, request_id: str) -> Optional[ApprovalRequest]:
        """Get an approval request by ID.

        Args:
            request_id: Request ID

        Returns:
            ApprovalRequest if found, None otherwise
        """
        with self._lock:
            return self._requests.get(request_id)

    def is_approved(self, request_id: str) -> bool:
        """Check if request is approved.

        Args:
            request_id: Request ID

        Returns:
            True if approved, False otherwise
        """
        with self._lock:
            request = self._requests.get(request_id)
            return request.is_approved() if request else False

    def is_rejected(self, request_id: str) -> bool:
        """Check if request is rejected.

        Args:
            request_id: Request ID

        Returns:
            True if rejected, False otherwise
        """
        with self._lock:
            request = self._requests.get(request_id)
            return request.is_rejected() if request else False

    def is_pending(self, request_id: str) -> bool:
        """Check if request is still pending.

        Args:
            request_id: Request ID

        Returns:
            True if pending, False otherwise
        """
        with self._lock:
            request = self._requests.get(request_id)
            if not request:
                return False

            # Check expiration
            if self.auto_reject_on_timeout and request.has_expired():
                self._expire_request(request)
                return False

            return request.is_pending()

    def list_pending_requests(self) -> List[ApprovalRequest]:
        """Get all pending approval requests.

        Returns:
            List of pending ApprovalRequest objects
        """
        with self._lock:
            pending = []
            for request in self._requests.values():
                if request.is_pending():
                    # Check expiration
                    if self.auto_reject_on_timeout and request.has_expired():
                        self._expire_request(request)
                    else:
                        pending.append(request)
            return pending

    def cleanup_expired_requests(self) -> int:
        """Expire all requests past their timeout.

        Returns:
            Number of requests expired
        """
        if not self.auto_reject_on_timeout:
            return 0

        with self._lock:
            expired_count = 0
            for request in list(self._requests.values()):
                if request.is_pending() and request.has_expired():
                    self._expire_request(request)
                    expired_count += 1

            return expired_count

    def on_approved(self, callback: Callable[[ApprovalRequest], None]) -> None:
        """Register callback for when requests are approved.

        Args:
            callback: Function to call when request is approved

        Example:
            >>> def notify_approved(request):
            ...     print(f"Request {request.id} approved")
            >>> workflow.on_approved(notify_approved)
        """
        self._on_approved_callbacks.append(callback)

    def on_rejected(self, callback: Callable[[ApprovalRequest], None]) -> None:
        """Register callback for when requests are rejected.

        Args:
            callback: Function to call when request is rejected

        Example:
            >>> def notify_rejected(request):
            ...     print(f"Request {request.id} rejected: {request.decision_reason}")
            >>> workflow.on_rejected(notify_rejected)
        """
        self._on_rejected_callbacks.append(callback)

    def _expire_request(self, request: ApprovalRequest) -> None:
        """Mark request as expired."""
        if request.is_pending():
            request.status = ApprovalStatus.EXPIRED
            request.decision_reason = "Request expired without approval"
            self._trigger_rejected_callbacks(request)

    def _trigger_approved_callbacks(self, request: ApprovalRequest) -> None:
        """Trigger all approved callbacks."""
        for callback in self._on_approved_callbacks:
            try:
                callback(request)
            except Exception as e:
                # H-12: Log callback errors instead of silently ignoring
                logger.warning("Approval callback failed: %s", e, exc_info=True)

    def _trigger_rejected_callbacks(self, request: ApprovalRequest) -> None:
        """Trigger all rejected callbacks."""
        for callback in self._on_rejected_callbacks:
            try:
                callback(request)
            except Exception as e:
                # H-12: Log callback errors instead of silently ignoring
                logger.warning("Rejection callback failed: %s", e, exc_info=True)

    def clear_requests(self) -> None:
        """Clear all approval requests. Use with caution!"""
        with self._lock:
            self._requests.clear()

    def request_count(self) -> int:
        """Get total number of requests."""
        with self._lock:
            return len(self._requests)

    def __repr__(self) -> str:
        """String representation."""
        with self._lock:
            return (
                f"ApprovalWorkflow("
                f"requests={len(self._requests)}, "
                f"timeout={self.default_timeout_minutes}min, "
                f"auto_reject={self.auto_reject_on_timeout})"
            )


class NoOpApprover(ApprovalWorkflow):
    """Auto-approving workflow for development environments.

    Immediately approves all requests upon creation, bypassing
    human review. Suitable only for development and testing.
    """

    def request_approval(
        self,
        action: Dict[str, Any],
        reason: str,
        context: Optional[Dict[str, Any]] = None,
        violations: Optional[List[SafetyViolation]] = None,
        required_approvers: int = 1,
        timeout_minutes: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
        requester: Optional[str] = None,
    ) -> ApprovalRequest:
        """Create and immediately approve an approval request."""
        request = super().request_approval(
            action=action,
            reason=reason,
            context=context,
            violations=violations,
            required_approvers=required_approvers,
            timeout_minutes=timeout_minutes,
            metadata=metadata,
            requester=requester,
        )
        request.status = ApprovalStatus.APPROVED
        request.decision_reason = "Auto-approved by NoOpApprover"
        request.approvers = ["NoOpApprover"]
        return request
