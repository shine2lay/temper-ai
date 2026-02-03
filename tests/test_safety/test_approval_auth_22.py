"""Tests for code-high-approval-auth-22.

Verifies that ApprovalWorkflow enforces approver authorization and
prevents self-approval when authorized_approvers is configured.
"""

import pytest

from src.safety.approval import ApprovalWorkflow, ApprovalStatus


@pytest.fixture
def authorized_workflow():
    """Workflow with authorized approvers configured."""
    return ApprovalWorkflow(authorized_approvers=["alice", "bob"])


class TestAuthorizedApproval:
    """Verify that only authorized approvers can approve requests."""

    def test_authorized_approver_succeeds(self, authorized_workflow):
        """An authorized approver should successfully approve a request."""
        request = authorized_workflow.request_approval(
            action={"tool": "deploy"},
            reason="Production deployment",
            requester="agent-1",
        )

        result = authorized_workflow.approve(request.id, approver="alice")

        assert result is True
        assert request.is_approved()
        assert "alice" in request.approvers

    def test_unauthorized_approver_raises(self, authorized_workflow):
        """An unauthorized approver should be rejected with PermissionError."""
        request = authorized_workflow.request_approval(
            action={"tool": "deploy"},
            reason="Test",
            requester="agent-1",
        )

        with pytest.raises(PermissionError, match="Unauthorized approver"):
            authorized_workflow.approve(request.id, approver="eve")

        # Request should still be pending
        assert request.is_pending()
        assert "eve" not in request.approvers

    def test_self_approval_blocked(self, authorized_workflow):
        """Requester cannot approve their own request."""
        # Alice is an authorized approver, but she's also the requester
        request = authorized_workflow.request_approval(
            action={"tool": "deploy"},
            reason="Test",
            requester="alice",
        )

        with pytest.raises(PermissionError, match="Self-approval denied"):
            authorized_workflow.approve(request.id, approver="alice")

        assert request.is_pending()

    def test_self_approval_allowed_without_config(self):
        """Without authorized_approvers, self-approval is not checked."""
        workflow = ApprovalWorkflow()  # No authorized_approvers
        request = workflow.request_approval(
            action={"tool": "deploy"},
            reason="Test",
            requester="alice",
        )

        result = workflow.approve(request.id, approver="alice")

        assert result is True
        assert request.is_approved()


class TestAuthorizedRejection:
    """Verify rejection authorization checks."""

    def test_authorized_rejecter_succeeds(self, authorized_workflow):
        """An authorized rejecter should successfully reject a request."""
        request = authorized_workflow.request_approval(
            action={"tool": "deploy"},
            reason="Test",
            requester="agent-1",
        )

        result = authorized_workflow.reject(request.id, rejecter="bob", reason="Too risky")

        assert result is True
        assert request.is_rejected()
        assert "bob" in request.rejecters

    def test_unauthorized_rejecter_raises(self, authorized_workflow):
        """An unauthorized rejecter should be rejected with PermissionError."""
        request = authorized_workflow.request_approval(
            action={"tool": "deploy"},
            reason="Test",
            requester="agent-1",
        )

        with pytest.raises(PermissionError, match="Unauthorized rejecter"):
            authorized_workflow.reject(request.id, rejecter="eve")

        assert request.is_pending()

    def test_self_rejection_allowed(self, authorized_workflow):
        """Requester can reject their own request (self-rejection is safe)."""
        # Bob is authorized and is the requester — self-rejection should work
        request = authorized_workflow.request_approval(
            action={"tool": "deploy"},
            reason="Test",
            requester="bob",
        )

        result = authorized_workflow.reject(request.id, rejecter="bob")

        assert result is True
        assert request.is_rejected()


class TestEmptyAuthorizedApprovers:
    """Verify behavior when authorized_approvers is an empty list."""

    def test_empty_list_blocks_all_approvals(self):
        """Empty authorized_approvers list should block all approvals."""
        workflow = ApprovalWorkflow(authorized_approvers=[])
        request = workflow.request_approval(
            action={"tool": "deploy"},
            reason="Test",
            requester="agent-1",
        )

        with pytest.raises(PermissionError, match="Unauthorized approver"):
            workflow.approve(request.id, approver="alice")

        assert request.is_pending()

    def test_empty_list_blocks_all_rejections(self):
        """Empty authorized_approvers list should block all rejections."""
        workflow = ApprovalWorkflow(authorized_approvers=[])
        request = workflow.request_approval(
            action={"tool": "deploy"},
            reason="Test",
        )

        with pytest.raises(PermissionError, match="Unauthorized rejecter"):
            workflow.reject(request.id, rejecter="alice")


class TestMultiApproverAuthorization:
    """Verify authorization with multi-approver requests."""

    def test_multi_approver_all_authorized(self):
        """Multiple authorized approvers can approve the same request."""
        workflow = ApprovalWorkflow(authorized_approvers=["alice", "bob", "carol"])
        request = workflow.request_approval(
            action={"tool": "deploy"},
            reason="Test",
            required_approvers=2,
            requester="agent-1",
        )

        workflow.approve(request.id, approver="alice")
        assert request.is_pending()

        workflow.approve(request.id, approver="bob")
        assert request.is_approved()

    def test_multi_approver_one_unauthorized(self):
        """One unauthorized approver among multiple should be blocked."""
        workflow = ApprovalWorkflow(authorized_approvers=["alice", "bob"])
        request = workflow.request_approval(
            action={"tool": "deploy"},
            reason="Test",
            required_approvers=2,
            requester="agent-1",
        )

        workflow.approve(request.id, approver="alice")

        with pytest.raises(PermissionError, match="Unauthorized approver"):
            workflow.approve(request.id, approver="eve")

        # Only alice approved, request still pending
        assert request.is_pending()
        assert request.approval_count() == 1


class TestRequesterTracking:
    """Verify requester field is stored and accessible."""

    def test_requester_stored_on_request(self):
        """Requester identity should be stored on the ApprovalRequest."""
        workflow = ApprovalWorkflow(authorized_approvers=["alice"])
        request = workflow.request_approval(
            action={"tool": "deploy"},
            reason="Test",
            requester="agent-deployer",
        )

        assert request.requester == "agent-deployer"

    def test_requester_none_by_default(self):
        """Requester should default to None for backward compatibility."""
        workflow = ApprovalWorkflow()
        request = workflow.request_approval(
            action={"tool": "deploy"},
            reason="Test",
        )

        assert request.requester is None

    def test_no_self_approval_check_when_requester_is_none(self):
        """When requester is None, self-approval check is skipped."""
        workflow = ApprovalWorkflow(authorized_approvers=["alice"])
        request = workflow.request_approval(
            action={"tool": "deploy"},
            reason="Test",
            # No requester specified
        )

        result = workflow.approve(request.id, approver="alice")
        assert result is True
        assert request.is_approved()
