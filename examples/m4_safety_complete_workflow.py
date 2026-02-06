"""Complete M4 Safety System Workflow Example.

This example demonstrates all M4 safety components working together in a
realistic production deployment scenario:

1. PolicyComposer - validates against multiple policies
2. ApprovalWorkflow - requires human approval
3. RollbackManager - automatic rollback on failure
4. CircuitBreaker & SafetyGate - prevents cascading failures

Scenario: Production database schema migration with full safety checks
"""
import tempfile
from pathlib import Path

from src.safety import (
    ApprovalWorkflow,
    CircuitBreakerManager,
    CircuitBreakerOpen,
    FileAccessPolicy,
    PolicyComposer,
    RollbackManager,
    SafetyGateBlocked,
)


def production_database_migration_workflow():
    """
    Complete workflow for safe production database migration.

    Safety Layers:
    1. Circuit Breaker - protects database from cascading failures
    2. File Access Policy - ensures migration scripts are in approved locations
    3. Approval Workflow - requires dual approval for production changes
    4. Rollback Manager - automatic rollback if migration fails
    """
    print("=" * 70)
    print("M4 Safety System - Production Database Migration Workflow")
    print("=" * 70)

    # Create temporary directories for example
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        # Setup: Initialize all M4 components
        print("\n[SETUP] Initializing M4 safety components...")

        # 1. Circuit Breaker Manager
        manager = CircuitBreakerManager()
        manager.create_breaker(
            name="database_operations",
            failure_threshold=3,      # Open after 3 failures
            timeout_seconds=300,       # Wait 5 min before retry
            success_threshold=2        # Need 2 successes to close
        )

        # 2. Policy Composer with File Access Policy
        composer = PolicyComposer()
        composer.add_policy(FileAccessPolicy({
            "allowed_paths": [f"{str(migrations_dir)}/**"],  # Only migrations dir
            "denied_paths": ["/etc/**", "/root/**", "/production/database/**"],
            "forbidden_extensions": [".exe", ".dll", ".sh"]  # No executables
        }))

        # 3. Approval Workflow
        approval = ApprovalWorkflow(
            default_timeout_minutes=60,
            auto_reject_on_timeout=True
        )

        # 4. Rollback Manager
        rollback_mgr = RollbackManager()

        # 5. Safety Gate (coordinates all checks)
        gate = manager.create_gate(
            name="database_migration_gate",
            breaker_name="database_operations",
            policy_composer=composer
        )

        print("✓ All M4 components initialized\n")

        # === SCENARIO 1: Successful Migration ===
        print("=" * 70)
        print("SCENARIO 1: Successful Database Migration")
        print("=" * 70)

        # Create migration script
        migration_file = migrations_dir / "001_add_user_table.sql"
        migration_file.write_text("""
            CREATE TABLE users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(255) NOT NULL,
                email VARCHAR(255) NOT NULL,
                created_at TIMESTAMP DEFAULT NOW()
            );
        """)

        action = {
            "tool": "execute_migration",
            "script": str(migration_file),
            "environment": "production",
            "database": "main"
        }
        context = {
            "agent": "migration_bot",
            "user": "db_admin",
            "timestamp": "2026-01-27T15:00:00Z"
        }

        try:
            # Step 1: Safety Gate Validation
            print("\n[Step 1] Safety Gate Validation...")
            can_pass, reasons = gate.validate(action, context)

            if not can_pass:
                print(f"✗ Safety gate blocked: {'; '.join(reasons)}")
                return
            print("✓ Safety gate validation passed")

            # Step 2: Request Approval
            print("\n[Step 2] Requesting Approval...")
            request = approval.request_approval(
                action=action,
                reason="Production database schema migration requires dual approval",
                context=context,
                required_approvers=2,
                timeout_minutes=60
            )
            print(f"✓ Approval request created: {request.id}")
            print(f"  Status: {request.status.value}")
            print(f"  Required approvers: {request.required_approvers}")

            # Simulate approvals
            print("\n[Step 2a] First approval...")
            approval.approve(request.id, approver="senior_dba", reason="Schema reviewed - looks good")
            print(f"  Approvers: {request.approvers}")
            print(f"  Status: {request.status.value}")

            print("\n[Step 2b] Second approval...")
            approval.approve(request.id, approver="tech_lead", reason="Migration tested in staging")
            print(f"  Approvers: {request.approvers}")
            print(f"  Status: {request.status.value}")

            if not request.is_approved():
                print("✗ Migration not approved")
                return
            print("✓ Migration approved by all required approvers\n")

            # Step 3: Create Rollback Snapshot
            print("[Step 3] Creating Rollback Snapshot...")
            snapshot = rollback_mgr.create_snapshot(action, context)
            print(f"✓ Snapshot created: {snapshot.id}")
            print(f"  File snapshots: {len(snapshot.file_snapshots)}")
            print(f"  Created at: {snapshot.created_at}\n")

            # Step 4: Execute Migration through Circuit Breaker
            print("[Step 4] Executing Migration...")
            db_breaker = manager.get_breaker("database_operations")

            with db_breaker():
                # Simulate migration execution
                print("  → Connecting to production database...")
                print("  → Executing migration script...")
                print("  → Creating users table...")
                migration_success = True  # Simulated success

            print("✓ Migration executed successfully")
            print("  Circuit breaker metrics:")
            print(f"    - State: {db_breaker.state.value}")
            print(f"    - Successful calls: {db_breaker.metrics.successful_calls}")
            print(f"    - Total calls: {db_breaker.metrics.total_calls}\n")

        except CircuitBreakerOpen as e:
            print(f"✗ Circuit breaker is open: {e}")
            print("  Database is experiencing issues - migration blocked")

        except SafetyGateBlocked as e:
            print(f"✗ Safety gate blocked migration: {e}")

        except Exception as e:
            print(f"✗ Migration failed: {e}")
            print("\n[ROLLBACK] Initiating automatic rollback...")
            result = rollback_mgr.execute_rollback(snapshot.id)

            if result.success:
                print("✓ Rollback completed successfully")
                print(f"  Reverted items: {len(result.reverted_items)}")
            else:
                print("✗ Rollback failed")
                print(f"  Errors: {result.errors}")

        # === SCENARIO 2: Rejected Migration ===
        print("\n" + "=" * 70)
        print("SCENARIO 2: Rejected Migration (Policy Violation)")
        print("=" * 70)

        # Attempt forbidden action (use "path" key for FileAccessPolicy)
        forbidden_action = {
            "tool": "execute_migration",
            "path": "/etc/passwd",  # Forbidden path!
            "environment": "production"
        }

        print("\n[Step 1] Safety Gate Validation...")
        can_pass, reasons = gate.validate(forbidden_action, context)

        if not can_pass:
            print("✗ Safety gate blocked migration")
            for i, reason in enumerate(reasons, 1):
                print(f"  {i}. {reason}")
            print("\n✓ Malicious migration attempt prevented by safety policies")
        else:
            print("✗ Safety gate should have blocked this!")

        # === SCENARIO 3: Circuit Breaker Protection ===
        print("\n" + "=" * 70)
        print("SCENARIO 3: Circuit Breaker Prevents Cascading Failures")
        print("=" * 70)

        print("\n[Simulation] Triggering database failures...")
        db_breaker = manager.get_breaker("database_operations")

        # Simulate 3 failures
        for i in range(3):
            try:
                with db_breaker():
                    # Simulate database failure
                    raise Exception(f"Database connection timeout (attempt {i+1})")
            except Exception as e:
                print(f"  Failure {i+1}: {e}")

        print(f"\n✓ Circuit breaker opened after {db_breaker.metrics.failed_calls} failures")
        print(f"  State: {db_breaker.state.value}")

        # Attempt operation with open circuit
        print("\n[Test] Attempting operation with open circuit...")
        try:
            with db_breaker():
                print("  This should not execute")
        except CircuitBreakerOpen:
            print("✓ Operation blocked - circuit breaker is open")
            print("  Prevented cascading failures to already-failing database")

        # === SUMMARY ===
        print("\n" + "=" * 70)
        print("SUMMARY: M4 Safety System Performance")
        print("=" * 70)

        # Approval Workflow Summary
        print("\nApproval Workflow:")
        print(f"  Total requests: {approval.request_count()}")
        pending = approval.list_pending_requests()
        print(f"  Pending: {len(pending)}")

        # Circuit Breaker Summary
        all_metrics = manager.get_all_metrics()
        print("\nCircuit Breaker Metrics:")
        for name, metrics in all_metrics.items():
            print(f"  {name}:")
            print(f"    - State: {manager.get_breaker(name).state.value}")
            print(f"    - Success rate: {metrics['success_rate']:.1%}")
            print(f"    - Total calls: {metrics['total_calls']}")
            print(f"    - Failed: {metrics['failed_calls']}")
            print(f"    - Rejected: {metrics['rejected_calls']}")

        # Rollback Summary
        print("\nRollback Manager:")
        print(f"  Snapshots created: {rollback_mgr.snapshot_count()}")
        print(f"  Rollbacks executed: {len(rollback_mgr.get_history())}")

        print("\n" + "=" * 70)
        print("M4 Safety System Demo Complete")
        print("=" * 70)


if __name__ == "__main__":
    production_database_migration_workflow()
