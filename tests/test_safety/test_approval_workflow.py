"""Tests for approval workflow system."""
from datetime import UTC, datetime, timedelta
from time import sleep

import pytest

from src.safety.approval import ApprovalRequest, ApprovalStatus, ApprovalWorkflow
from src.safety.interfaces import SafetyViolation, ViolationSeverity


class TestApprovalRequest:
    """Test ApprovalRequest data class."""

    def test_initialization(self):
        """Test approval request initialization."""
        request = ApprovalRequest(
            action={"tool": "deploy"},
            reason="Production deployment",
            context={"agent": "deployer"}
        )

        assert request.id is not None
        assert request.action == {"tool": "deploy"}
        assert request.reason == "Production deployment"
        assert request.status == ApprovalStatus.PENDING
        assert request.required_approvers == 1
        assert len(request.approvers) == 0

    def test_is_pending(self):
        """Test checking pending status."""
        request = ApprovalRequest()
        assert request.is_pending() is True

        request.status = ApprovalStatus.APPROVED
        assert request.is_pending() is False

    def test_is_approved(self):
        """Test checking approved status."""
        request = ApprovalRequest()
        assert request.is_approved() is False

        request.status = ApprovalStatus.APPROVED
        assert request.is_approved() is True

    def test_is_rejected(self):
        """Test checking rejected status."""
        request = ApprovalRequest()
        assert request.is_rejected() is False

        request.status = ApprovalStatus.REJECTED
        assert request.is_rejected() is True

    def test_is_expired(self):
        """Test checking expired status."""
        request = ApprovalRequest()
        assert request.is_expired() is False

        request.status = ApprovalStatus.EXPIRED
        assert request.is_expired() is True

    def test_has_expired(self):
        """Test checking if request passed expiration time."""
        # No expiration set
        request = ApprovalRequest()
        assert request.has_expired() is False

        # Future expiration
        request.expires_at = datetime.now(UTC) + timedelta(hours=1)
        assert request.has_expired() is False

        # Past expiration
        request.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        assert request.has_expired() is True

    def test_approval_count(self):
        """Test counting approvals."""
        request = ApprovalRequest()
        assert request.approval_count() == 0

        request.approvers = ["alice", "bob"]
        assert request.approval_count() == 2

    def test_needs_more_approvals(self):
        """Test checking if more approvals needed."""
        request = ApprovalRequest(required_approvers=2)
        assert request.needs_more_approvals() is True

        request.approvers = ["alice"]
        assert request.needs_more_approvals() is True

        request.approvers = ["alice", "bob"]
        assert request.needs_more_approvals() is False

    def test_to_dict(self):
        """Test serialization to dictionary."""
        request = ApprovalRequest(
            action={"tool": "test"},
            reason="Test",
            required_approvers=2,
            approvers=["alice"]
        )

        data = request.to_dict()

        assert data["action"] == {"tool": "test"}
        assert data["reason"] == "Test"
        assert data["required_approvers"] == 2
        assert data["approvers"] == ["alice"]
        assert data["status"] == "pending"


class TestApprovalWorkflowInitialization:
    """Test ApprovalWorkflow initialization."""

    def test_init_defaults(self):
        """Test initialization with defaults."""
        workflow = ApprovalWorkflow()

        assert workflow.default_timeout_minutes == 60
        assert workflow.auto_reject_on_timeout is True
        assert workflow.request_count() == 0

    def test_init_custom_timeout(self):
        """Test initialization with custom timeout."""
        workflow = ApprovalWorkflow(default_timeout_minutes=30)

        assert workflow.default_timeout_minutes == 30

    def test_init_auto_reject_disabled(self):
        """Test initialization with auto-reject disabled."""
        workflow = ApprovalWorkflow(auto_reject_on_timeout=False)

        assert workflow.auto_reject_on_timeout is False


class TestRequestApproval:
    """Test creating approval requests."""

    def test_request_approval_basic(self):
        """Test basic approval request creation."""
        workflow = ApprovalWorkflow()

        request = workflow.request_approval(
            action={"tool": "deploy"},
            reason="Production deployment"
        )

        assert request is not None
        assert request.action == {"tool": "deploy"}
        assert request.reason == "Production deployment"
        assert request.is_pending() is True
        assert workflow.request_count() == 1

    def test_request_approval_with_context(self):
        """Test approval request with context."""
        workflow = ApprovalWorkflow()

        request = workflow.request_approval(
            action={"tool": "delete"},
            reason="Delete operation",
            context={"agent": "admin", "stage": "cleanup"}
        )

        assert request.context == {"agent": "admin", "stage": "cleanup"}

    def test_request_approval_with_violations(self):
        """Test approval request with safety violations."""
        violation = SafetyViolation(
            policy_name="test_policy",
            severity=ViolationSeverity.HIGH,
            message="High risk action",
            action="deploy",
            context={}
        )

        workflow = ApprovalWorkflow()
        request = workflow.request_approval(
            action={"tool": "deploy"},
            reason="Safety violation detected",
            violations=[violation]
        )

        assert len(request.violations) == 1
        assert request.violations[0].policy_name == "test_policy"

    def test_request_approval_with_multiple_approvers(self):
        """Test approval request requiring multiple approvers."""
        workflow = ApprovalWorkflow()

        request = workflow.request_approval(
            action={"tool": "deploy"},
            reason="Critical operation",
            required_approvers=3
        )

        assert request.required_approvers == 3
        assert request.needs_more_approvals() is True

    def test_request_approval_custom_timeout(self):
        """Test approval request with custom timeout."""
        workflow = ApprovalWorkflow(default_timeout_minutes=60)

        request = workflow.request_approval(
            action={"tool": "deploy"},
            reason="Test",
            timeout_minutes=15
        )

        # Timeout should be ~15 minutes from now
        time_until_expiry = request.expires_at - datetime.now(UTC)
        assert 14 <= time_until_expiry.total_seconds() / 60 <= 16


class TestApprove:
    """Test approving requests."""

    def test_approve_basic(self):
        """Test basic approval."""
        workflow = ApprovalWorkflow()
        request = workflow.request_approval(
            action={"tool": "deploy"},
            reason="Test"
        )

        success = workflow.approve(request.id, approver="alice")

        assert success is True
        assert "alice" in request.approvers
        assert request.is_approved() is True

    def test_approve_with_reason(self):
        """Test approval with reason."""
        workflow = ApprovalWorkflow()
        request = workflow.request_approval(
            action={"tool": "deploy"},
            reason="Test"
        )

        workflow.approve(request.id, approver="alice", reason="Looks good")

        assert request.decision_reason == "Looks good"

    def test_approve_multiple_approvers(self):
        """Test approval requiring multiple approvers."""
        workflow = ApprovalWorkflow()
        request = workflow.request_approval(
            action={"tool": "deploy"},
            reason="Test",
            required_approvers=2
        )

        # First approval - still pending
        workflow.approve(request.id, approver="alice")
        assert request.is_pending() is True
        assert request.approval_count() == 1

        # Second approval - now approved
        workflow.approve(request.id, approver="bob")
        assert request.is_approved() is True
        assert request.approval_count() == 2

    def test_approve_duplicate_approver(self):
        """Test that same approver can't approve twice."""
        workflow = ApprovalWorkflow()
        request = workflow.request_approval(
            action={"tool": "deploy"},
            reason="Test",
            required_approvers=2
        )

        workflow.approve(request.id, approver="alice")
        workflow.approve(request.id, approver="alice")  # Second time

        assert request.approval_count() == 1

    def test_approve_nonexistent_request(self):
        """Test approving request that doesn't exist."""
        workflow = ApprovalWorkflow()

        success = workflow.approve("nonexistent-id", approver="alice")

        assert success is False

    def test_approve_already_approved_request(self):
        """Test approving already approved request."""
        workflow = ApprovalWorkflow()
        request = workflow.request_approval(
            action={"tool": "deploy"},
            reason="Test"
        )

        workflow.approve(request.id, approver="alice")
        assert request.is_approved() is True

        # Try to approve again
        success = workflow.approve(request.id, approver="bob")

        assert success is False

    def test_approve_rejected_request(self):
        """Test approving already rejected request."""
        workflow = ApprovalWorkflow()
        request = workflow.request_approval(
            action={"tool": "deploy"},
            reason="Test"
        )

        workflow.reject(request.id, rejecter="alice")
        assert request.is_rejected() is True

        # Try to approve
        success = workflow.approve(request.id, approver="bob")

        assert success is False


class TestReject:
    """Test rejecting requests."""

    def test_reject_basic(self):
        """Test basic rejection."""
        workflow = ApprovalWorkflow()
        request = workflow.request_approval(
            action={"tool": "deploy"},
            reason="Test"
        )

        success = workflow.reject(request.id, rejecter="alice")

        assert success is True
        assert "alice" in request.rejecters
        assert request.is_rejected() is True

    def test_reject_with_reason(self):
        """Test rejection with reason."""
        workflow = ApprovalWorkflow()
        request = workflow.request_approval(
            action={"tool": "deploy"},
            reason="Test"
        )

        workflow.reject(request.id, rejecter="alice", reason="Too risky")

        assert request.decision_reason == "Too risky"

    def test_reject_nonexistent_request(self):
        """Test rejecting request that doesn't exist."""
        workflow = ApprovalWorkflow()

        success = workflow.reject("nonexistent-id", rejecter="alice")

        assert success is False

    def test_reject_already_approved_request(self):
        """Test rejecting already approved request."""
        workflow = ApprovalWorkflow()
        request = workflow.request_approval(
            action={"tool": "deploy"},
            reason="Test"
        )

        workflow.approve(request.id, approver="alice")

        # Try to reject
        success = workflow.reject(request.id, rejecter="bob")

        assert success is False


class TestCancel:
    """Test cancelling requests."""

    def test_cancel_basic(self):
        """Test basic cancellation."""
        workflow = ApprovalWorkflow()
        request = workflow.request_approval(
            action={"tool": "deploy"},
            reason="Test"
        )

        success = workflow.cancel(request.id)

        assert success is True
        assert request.status == ApprovalStatus.CANCELLED

    def test_cancel_with_reason(self):
        """Test cancellation with reason."""
        workflow = ApprovalWorkflow()
        request = workflow.request_approval(
            action={"tool": "deploy"},
            reason="Test"
        )

        workflow.cancel(request.id, reason="No longer needed")

        assert request.decision_reason == "No longer needed"

    def test_cancel_nonexistent_request(self):
        """Test cancelling nonexistent request."""
        workflow = ApprovalWorkflow()

        success = workflow.cancel("nonexistent-id")

        assert success is False

    def test_cancel_already_approved_request(self):
        """Test cancelling already approved request."""
        workflow = ApprovalWorkflow()
        request = workflow.request_approval(
            action={"tool": "deploy"},
            reason="Test"
        )

        workflow.approve(request.id, approver="alice")

        success = workflow.cancel(request.id)

        assert success is False


class TestTimeout:
    """Test timeout handling."""

    def test_expired_request_auto_rejected(self):
        """Test that expired requests are auto-rejected."""
        workflow = ApprovalWorkflow(default_timeout_minutes=0)

        request = workflow.request_approval(
            action={"tool": "deploy"},
            reason="Test",
            timeout_minutes=0  # Immediate expiration
        )

        # Wait a moment
        sleep(0.1)

        # Check if expired
        is_pending = workflow.is_pending(request.id)

        assert is_pending is False
        assert request.is_expired() is True

    def test_cleanup_expired_requests(self):
        """Test cleanup of expired requests."""
        workflow = ApprovalWorkflow(default_timeout_minutes=0)

        # Create several requests that expire immediately
        for i in range(5):
            workflow.request_approval(
                action={"tool": f"action{i}"},
                reason="Test",
                timeout_minutes=0
            )

        sleep(0.1)

        # Cleanup
        expired_count = workflow.cleanup_expired_requests()

        assert expired_count == 5

    def test_auto_reject_disabled(self):
        """Test that auto-reject can be disabled."""
        workflow = ApprovalWorkflow(
            default_timeout_minutes=0,
            auto_reject_on_timeout=False
        )

        request = workflow.request_approval(
            action={"tool": "deploy"},
            reason="Test",
            timeout_minutes=0
        )

        sleep(0.1)

        # Should still be pending (auto-reject disabled)
        assert request.is_pending() is True


class TestQueryMethods:
    """Test querying approval status."""

    def test_get_request(self):
        """Test getting request by ID."""
        workflow = ApprovalWorkflow()
        request = workflow.request_approval(
            action={"tool": "deploy"},
            reason="Test"
        )

        retrieved = workflow.get_request(request.id)

        assert retrieved is request

    def test_get_nonexistent_request(self):
        """Test getting nonexistent request."""
        workflow = ApprovalWorkflow()

        retrieved = workflow.get_request("nonexistent-id")

        assert retrieved is None

    def test_is_approved(self):
        """Test is_approved check."""
        workflow = ApprovalWorkflow()
        request = workflow.request_approval(
            action={"tool": "deploy"},
            reason="Test"
        )

        assert workflow.is_approved(request.id) is False

        workflow.approve(request.id, approver="alice")

        assert workflow.is_approved(request.id) is True

    def test_is_rejected(self):
        """Test is_rejected check."""
        workflow = ApprovalWorkflow()
        request = workflow.request_approval(
            action={"tool": "deploy"},
            reason="Test"
        )

        assert workflow.is_rejected(request.id) is False

        workflow.reject(request.id, rejecter="alice")

        assert workflow.is_rejected(request.id) is True

    def test_list_pending_requests(self):
        """Test listing pending requests."""
        workflow = ApprovalWorkflow()

        # Create some requests
        req1 = workflow.request_approval(action={"tool": "a"}, reason="Test")
        req2 = workflow.request_approval(action={"tool": "b"}, reason="Test")
        req3 = workflow.request_approval(action={"tool": "c"}, reason="Test")

        # Approve one, reject another
        workflow.approve(req1.id, approver="alice")
        workflow.reject(req2.id, rejecter="bob")

        # Only req3 should be pending
        pending = workflow.list_pending_requests()

        assert len(pending) == 1
        assert pending[0].id == req3.id


class TestCallbacks:
    """Test approval/rejection callbacks."""

    def test_on_approved_callback(self):
        """Test callback when request is approved."""
        workflow = ApprovalWorkflow()
        callback_called = []

        def on_approved(request):
            callback_called.append(request.id)

        workflow.on_approved(on_approved)

        request = workflow.request_approval(
            action={"tool": "deploy"},
            reason="Test"
        )

        workflow.approve(request.id, approver="alice")

        assert len(callback_called) == 1
        assert callback_called[0] == request.id

    def test_on_rejected_callback(self):
        """Test callback when request is rejected."""
        workflow = ApprovalWorkflow()
        callback_called = []

        def on_rejected(request):
            callback_called.append(request.id)

        workflow.on_rejected(on_rejected)

        request = workflow.request_approval(
            action={"tool": "deploy"},
            reason="Test"
        )

        workflow.reject(request.id, rejecter="alice")

        assert len(callback_called) == 1
        assert callback_called[0] == request.id

    def test_callback_exception_doesnt_break_workflow(self):
        """Test that callback exceptions don't break workflow."""
        workflow = ApprovalWorkflow()

        def failing_callback(request):
            raise RuntimeError("Callback failed")

        workflow.on_approved(failing_callback)

        request = workflow.request_approval(
            action={"tool": "deploy"},
            reason="Test"
        )

        # Should not raise exception
        workflow.approve(request.id, approver="alice")

        assert request.is_approved() is True


class TestUtilityMethods:
    """Test utility methods."""

    def test_clear_requests(self):
        """Test clearing all requests."""
        workflow = ApprovalWorkflow()

        for i in range(5):
            workflow.request_approval(
                action={"tool": f"action{i}"},
                reason="Test"
            )

        assert workflow.request_count() == 5

        workflow.clear_requests()

        assert workflow.request_count() == 0

    def test_repr(self):
        """Test string representation."""
        workflow = ApprovalWorkflow(default_timeout_minutes=30)

        repr_str = repr(workflow)

        assert "ApprovalWorkflow" in repr_str
        assert "timeout=30min" in repr_str


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
