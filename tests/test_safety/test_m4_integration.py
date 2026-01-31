"""Integration tests for M4 Safety & Governance System.

This test suite validates that all M4 components work together correctly:
- PolicyComposer (multiple policies working in concert)
- ApprovalWorkflow (human-in-the-loop approval)
- RollbackManager (automatic rollback on failure)
- CircuitBreaker & SafetyGate (failure protection)

The tests demonstrate real-world scenarios where multiple safety mechanisms
coordinate to protect the system.
"""
import pytest
import tempfile
from pathlib import Path
from unittest.mock import Mock

from src.safety import (
    PolicyComposer,
    FileAccessPolicy,
    RateLimiterPolicy,
    ApprovalWorkflow,
    ApprovalStatus,
    RollbackManager,
    FileRollbackStrategy,
    CircuitBreaker,
    CircuitBreakerState,
    CircuitBreakerOpen,
    SafetyGate,
    SafetyGateBlocked,
    CircuitBreakerManager,
    ViolationSeverity
)


class TestCompleteSafetyPipeline:
    """Test complete safety pipeline with all M4 components."""

    def test_policy_to_approval_to_execution(self, tmp_path):
        """Test: Policy validation → Approval → Execute → Success."""
        # Setup components
        composer = PolicyComposer()
        composer.add_policy(FileAccessPolicy({
            "allowed_paths": [f"{str(tmp_path)}/**"],
            "denied_paths": ["/etc/**", "/root/**"]
        }))
        approval = ApprovalWorkflow(default_timeout_minutes=60)
        rollback_mgr = RollbackManager()

        # Action to execute
        test_file = tmp_path / "config.yaml"
        test_file.write_text("version: 1.0")
        action = {"tool": "write_file", "path": str(test_file)}
        context = {"agent": "config_updater"}

        # Step 1: Validate policies
        result = composer.validate(action, context)
        assert result.valid is True

        # Step 2: Request approval
        request = approval.request_approval(
            action=action,
            reason="Config update requires approval",
            context=context
        )
        assert request.is_pending()

        # Step 3: Create rollback snapshot
        snapshot = rollback_mgr.create_snapshot(action, context)
        assert snapshot is not None

        # Step 4: Approve
        approval.approve(request.id, approver="admin", reason="Looks good")
        assert request.is_approved()

        # Step 5: Execute action
        test_file.write_text("version: 2.0")
        assert test_file.read_text() == "version: 2.0"

        # Verify workflow completed successfully
        assert approval.is_approved(request.id)
        assert rollback_mgr.snapshot_count() == 1

    def test_policy_violation_blocks_execution(self):
        """Test: Policy violation → Reject → No execution."""
        # Setup
        composer = PolicyComposer()
        composer.add_policy(FileAccessPolicy({
            "allowed_paths": ["/tmp"],
            "denied_paths": ["/etc", "/root"]
        }))

        # Attempt forbidden action
        action = {"tool": "write_file", "path": "/etc/passwd"}
        result = composer.validate(action, {})

        # Should be blocked
        assert result.valid is False
        assert result.has_blocking_violations()

        # Verify violation details (FileAccessPolicy uses CRITICAL severity)
        assert len(result.violations) > 0
        critical_violations = result.get_violations_by_severity(ViolationSeverity.CRITICAL)
        assert len(critical_violations) > 0

    def test_rollback_on_execution_failure(self, tmp_path):
        """Test: Execute → Fail → Automatic rollback."""
        # Setup
        rollback_mgr = RollbackManager()
        test_file = tmp_path / "data.txt"
        test_file.write_text("original data")

        # Create snapshot
        snapshot = rollback_mgr.create_snapshot(
            action={"path": str(test_file)},
            context={}
        )

        # Modify file (simulating action)
        test_file.write_text("corrupted data")
        assert test_file.read_text() == "corrupted data"

        # Execution "fails" - rollback
        result = rollback_mgr.execute_rollback(snapshot.id)

        # Verify rollback
        assert result.success is True
        assert test_file.read_text() == "original data"


class TestCircuitBreakerWithRollback:
    """Test circuit breaker integration with rollback mechanism."""

    def test_circuit_breaker_triggers_rollback(self, tmp_path):
        """Test: Circuit opens → Rollback triggered."""
        # Setup
        breaker = CircuitBreaker(
            name="file_ops",
            failure_threshold=2,
            timeout_seconds=60
        )
        rollback_mgr = RollbackManager()

        test_file = tmp_path / "data.txt"
        test_file.write_text("original")

        # Track rollbacks
        rollbacks_executed = []

        def auto_rollback(snapshot_id):
            result = rollback_mgr.execute_rollback(snapshot_id)
            rollbacks_executed.append(result)

        # Simulate operations with failures
        for i in range(5):
            snapshot = rollback_mgr.create_snapshot(
                action={"path": str(test_file)},
                context={}
            )

            try:
                with breaker():
                    # Modify file
                    test_file.write_text(f"attempt {i}")

                    # Simulate failure for first 2 attempts
                    if i < 2:
                        raise Exception("Operation failed")

            except CircuitBreakerOpen:
                # Circuit opened - trigger rollback
                auto_rollback(snapshot.id)
            except Exception:
                # Execution failed - trigger rollback
                auto_rollback(snapshot.id)

        # Verify circuit opened after failures
        assert breaker.state == CircuitBreakerState.OPEN

        # Verify rollbacks were executed
        assert len(rollbacks_executed) >= 2

        # File should be back to original (from rollbacks)
        assert test_file.read_text() == "original"

    def test_circuit_breaker_prevents_cascading_rollbacks(self, tmp_path):
        """Test: Circuit breaker prevents excessive rollback operations."""
        breaker = CircuitBreaker(
            name="operations",
            failure_threshold=3,
            timeout_seconds=60
        )
        rollback_mgr = RollbackManager()

        test_file = tmp_path / "test.txt"
        test_file.write_text("start")

        attempted_operations = 0
        rejected_operations = 0

        # Attempt 10 operations (circuit should open after 3 failures)
        for i in range(10):
            snapshot = rollback_mgr.create_snapshot(
                action={"path": str(test_file)},
                context={}
            )

            try:
                with breaker():
                    attempted_operations += 1
                    test_file.write_text(f"op {i}")
                    # Always fail
                    raise Exception("Simulated failure")
            except CircuitBreakerOpen:
                # Circuit is open - operation rejected
                rejected_operations += 1
            except Exception:
                # Operation failed
                rollback_mgr.execute_rollback(snapshot.id)

        # Circuit should have opened after 3 failures
        assert attempted_operations == 3
        assert rejected_operations == 7

        # Only 3 rollbacks should have been created (for the 3 attempts)
        assert len(rollback_mgr.get_history()) == 3


class TestSafetyGateCoordination:
    """Test SafetyGate coordinating multiple safety mechanisms."""

    def test_safety_gate_with_all_components(self, tmp_path):
        """Test: Safety gate coordinates breaker, policies, and approval."""
        # Setup components
        breaker = CircuitBreaker("file_ops", failure_threshold=5)
        composer = PolicyComposer()
        composer.add_policy(FileAccessPolicy({
            "allowed_paths": [f"{str(tmp_path)}/**"],
            "denied_paths": ["/etc/**"]
        }))

        gate = SafetyGate(
            name="comprehensive_gate",
            circuit_breaker=breaker,
            policy_composer=composer
        )

        # Test 1: Allowed action passes all checks
        action1 = {"tool": "write_file", "path": str(tmp_path / "allowed.txt")}
        assert gate.can_pass(action1, {}) is True

        # Test 2: Forbidden action blocked by policy
        action2 = {"tool": "write_file", "path": "/etc/passwd"}
        can_pass, reasons = gate.validate(action2, {})
        assert can_pass is False
        assert any("Policy violation" in r for r in reasons)

        # Test 3: Open circuit blocks all actions
        breaker.force_open()
        action3 = {"tool": "write_file", "path": str(tmp_path / "test.txt")}
        can_pass, reasons = gate.validate(action3, {})
        assert can_pass is False
        assert any("Circuit breaker" in r for r in reasons)

    def test_safety_gate_context_manager_integration(self, tmp_path):
        """Test: Safety gate as context manager with all protections."""
        breaker = CircuitBreaker("ops")
        composer = PolicyComposer()
        composer.add_policy(FileAccessPolicy({
            "allowed_paths": [f"{str(tmp_path)}/**"]
        }))

        gate = SafetyGate(
            name="test_gate",
            circuit_breaker=breaker,
            policy_composer=composer
        )

        test_file = tmp_path / "test.txt"
        action = {"tool": "write_file", "path": str(test_file)}

        # Should succeed
        with gate(action=action, context={}):
            test_file.write_text("success")

        assert breaker.metrics.successful_calls == 1

        # Block gate manually
        gate.block("Testing manual block")

        # Should fail
        with pytest.raises(SafetyGateBlocked):
            with gate(action=action, context={}):
                pass


class TestMultiServiceProtection:
    """Test managing multiple services with circuit breakers."""

    def test_manager_coordinates_multiple_breakers(self):
        """Test: Manager coordinates circuit breakers for multiple services."""
        manager = CircuitBreakerManager()

        # Create breakers for different services
        services = {
            "database": {"threshold": 3, "timeout": 30},
            "cache": {"threshold": 5, "timeout": 10},
            "api": {"threshold": 10, "timeout": 60}
        }

        for name, config in services.items():
            manager.create_breaker(
                name,
                failure_threshold=config["threshold"],
                timeout_seconds=config["timeout"]
            )

        # Simulate failures on database
        db_breaker = manager.get_breaker("database")
        for _ in range(3):
            db_breaker.record_failure()

        # Database circuit should be open
        assert db_breaker.state == CircuitBreakerState.OPEN

        # Other circuits should be closed
        assert manager.get_breaker("cache").state == CircuitBreakerState.CLOSED
        assert manager.get_breaker("api").state == CircuitBreakerState.CLOSED

        # Check aggregated metrics
        metrics = manager.get_all_metrics()
        assert metrics["database"]["failed_calls"] == 3
        assert metrics["cache"]["failed_calls"] == 0
        assert metrics["api"]["failed_calls"] == 0

    def test_manager_with_safety_gates(self, tmp_path):
        """Test: Manager creates gates linked to breakers."""
        manager = CircuitBreakerManager()

        # Create breakers
        manager.create_breaker("file_ops", failure_threshold=3)
        manager.create_breaker("network_ops", failure_threshold=5)

        # Create gates
        file_gate = manager.create_gate(
            name="file_gate",
            breaker_name="file_ops"
        )
        network_gate = manager.create_gate(
            name="network_gate",
            breaker_name="network_ops"
        )

        # Both gates should have their breakers
        assert file_gate.circuit_breaker.name == "file_ops"
        assert network_gate.circuit_breaker.name == "network_ops"

        # Test file gate
        action = {"tool": "write_file", "path": str(tmp_path / "test.txt")}
        with file_gate(action=action, context={}):
            pass

        # File breaker should have 1 success
        assert manager.get_breaker("file_ops").metrics.successful_calls == 1


class TestRealWorldDeploymentWorkflow:
    """Test real-world production deployment workflow with all safety mechanisms."""

    def test_production_deployment_workflow(self, tmp_path):
        """Test: Complete production deployment with all safety checks."""
        # Setup all components
        manager = CircuitBreakerManager()

        # Circuit breakers for services
        manager.create_breaker("deployment_service", failure_threshold=3, timeout_seconds=300)

        # Policies
        composer = PolicyComposer()
        composer.add_policy(FileAccessPolicy({
            "allowed_paths": [f"{str(tmp_path)}/**"],
            "denied_paths": ["/etc/**", "/root/**"]
        }))
        # Note: RateLimiterPolicy doesn't have max_calls config, skip for now
        # composer.add_policy(RateLimiterPolicy({}))

        # Approval workflow
        approval = ApprovalWorkflow(default_timeout_minutes=60)

        # Rollback manager
        rollback_mgr = RollbackManager()

        # Safety gate
        deploy_gate = manager.create_gate(
            name="deployment_gate",
            breaker_name="deployment_service",
            policy_composer=composer
        )

        # Deployment action
        deploy_file = tmp_path / "app.config"
        deploy_file.write_text("version: 1.0\nenv: staging")

        action = {
            "tool": "deploy",
            "environment": "production",
            "config": str(deploy_file)
        }
        context = {
            "agent": "deployment_bot",
            "user": "admin",
            "timestamp": "2026-01-27T12:00:00Z"
        }

        # Step 1: Validate through safety gate
        can_pass, reasons = deploy_gate.validate(action, context)
        assert can_pass is True

        # Step 2: Request approval (production deployments need approval)
        request = approval.request_approval(
            action=action,
            reason="Production deployment requires dual approval",
            context=context,
            required_approvers=2
        )

        # Step 3: Create rollback snapshot
        snapshot = rollback_mgr.create_snapshot(action, context)

        # Step 4: Get approvals
        approval.approve(request.id, approver="tech_lead", reason="Code reviewed")
        assert request.is_pending()  # Need 2 approvals

        approval.approve(request.id, approver="ops_lead", reason="Infrastructure ready")
        assert request.is_approved()  # Now approved

        # Step 5: Execute deployment through circuit breaker
        deployment_breaker = manager.get_breaker("deployment_service")

        try:
            with deployment_breaker():
                # Simulate deployment
                deploy_file.write_text("version: 2.0\nenv: production")
                deployment_success = True
        except Exception as e:
            deployment_success = False
            # Rollback on failure
            rollback_mgr.execute_rollback(snapshot.id)

        # Verify successful deployment
        assert deployment_success is True
        assert deployment_breaker.metrics.successful_calls == 1
        assert deploy_file.read_text() == "version: 2.0\nenv: production"

    def test_deployment_rejection_with_rollback(self, tmp_path):
        """Test: Deployment rejected → No execution → No rollback needed."""
        # Setup
        composer = PolicyComposer()
        composer.add_policy(FileAccessPolicy({
            "allowed_paths": [f"{str(tmp_path)}/**"],
            "denied_paths": ["/production/**"]
        }))
        approval = ApprovalWorkflow()

        # Attempt forbidden deployment (use "path" key for FileAccessPolicy)
        action = {"tool": "deploy", "path": "/production/critical-service"}

        # Step 1: Policy check fails
        result = composer.validate(action, {})
        assert result.valid is False

        # Step 2: Request approval anyway (for audit trail)
        request = approval.request_approval(
            action=action,
            reason="Deployment blocked by policy",
            violations=result.violations
        )

        # Step 3: Reject
        approval.reject(request.id, rejecter="security_team", reason="Policy violation")

        # Verify rejection
        assert request.is_rejected()

        # No execution, no rollback needed


class TestFailureRecoveryScenarios:
    """Test various failure and recovery scenarios."""

    def test_circuit_breaker_automatic_recovery(self):
        """Test: Circuit opens → Timeout → Half-open → Recovery."""
        import time

        breaker = CircuitBreaker(
            name="recovery_test",
            failure_threshold=2,
            timeout_seconds=1,  # Short timeout for testing
            success_threshold=2
        )

        # Fail twice to open circuit
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.state == CircuitBreakerState.OPEN

        # Wait for timeout
        time.sleep(1.1)

        # Should transition to half-open
        assert breaker.state == CircuitBreakerState.HALF_OPEN

        # Two successes to close
        breaker.record_success()
        breaker.record_success()
        assert breaker.state == CircuitBreakerState.CLOSED

    def test_partial_rollback_handling(self, tmp_path):
        """Test: Rollback with partial failures."""
        rollback_mgr = RollbackManager()

        # Create files
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "subdir"  # Directory (will cause rollback failure)
        file2.mkdir()

        file1.write_text("original1")

        # Create snapshot with both
        snapshot = rollback_mgr.create_snapshot(
            action={"files": [str(file1), str(file2)]},
            context={}
        )

        # Manually add snapshots for both
        snapshot.file_snapshots[str(file1)] = "original1"
        snapshot.file_snapshots[str(file2)] = "content2"  # Can't write to directory
        snapshot.metadata[f"{str(file1)}_existed"] = True
        snapshot.metadata[f"{str(file2)}_existed"] = True

        # Modify file1
        file1.write_text("modified1")

        # Rollback (file2 will fail)
        result = rollback_mgr.execute_rollback(snapshot.id)

        # Should be partial success
        assert result.success is False
        assert result.status.value == "partial"
        assert str(file1) in result.reverted_items
        assert str(file2) in result.failed_items


class TestPerformanceAndOverhead:
    """Test performance and overhead of safety mechanisms."""

    def test_policy_validation_performance(self):
        """Test: Policy validation overhead is acceptable."""
        import time

        composer = PolicyComposer()
        composer.add_policy(FileAccessPolicy({
            "allowed_paths": ["/tmp"],
            "denied_paths": ["/etc"]
        }))

        action = {"tool": "write_file", "path": "/tmp/test.txt"}
        context = {}

        # Measure validation time
        iterations = 1000
        start = time.time()

        for _ in range(iterations):
            composer.validate(action, context)

        elapsed = time.time() - start
        avg_time = (elapsed / iterations) * 1000  # ms

        # Should be fast (<1ms per validation)
        assert avg_time < 1.0

    def test_circuit_breaker_overhead(self):
        """Test: Circuit breaker overhead is minimal."""
        import time

        breaker = CircuitBreaker("perf_test")

        # Measure context manager overhead
        iterations = 10000
        start = time.time()

        for _ in range(iterations):
            with breaker():
                pass  # No-op

        elapsed = time.time() - start
        avg_time = (elapsed / iterations) * 1000000  # microseconds

        # Should be very fast (<100μs per call)
        assert avg_time < 100


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
