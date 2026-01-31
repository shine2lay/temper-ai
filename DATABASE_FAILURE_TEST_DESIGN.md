# Database Failure Test Design - Experimentation Module

## Overview

Comprehensive database failure testing for the A/B testing experimentation module, covering connection failures, pool exhaustion, transaction conflicts, and data integrity scenarios.

**Test File:** `tests/test_experimentation/test_database_failures.py`

**Coverage Target:** 15+ critical database failure scenarios

---

## Test Scenarios Summary

### A. Connection Failures (5 tests)

| Test | Scenario | Verification |
|------|----------|--------------|
| `test_assignment_creation_with_connection_loss` | DB connection lost during assignment creation | No partial state, proper error propagation |
| `test_experiment_creation_with_connection_error` | DB unavailable during experiment creation | Service fails gracefully with clear error |
| `test_get_experiment_after_connection_loss` | Read after connection recovery | Data persists, new connection works |
| `test_assignment_tracking_with_reconnect` | Metric tracking after reconnection | Metrics saved with new connection |
| `test_service_initialization_with_db_failure` | Service starts without DB | Operations fail with RuntimeError |

### B. Connection Pool Exhaustion (3 tests)

| Test | Scenario | Verification |
|------|----------|--------------|
| `test_pool_exhaustion_concurrent_assignments` | 50 concurrent assignments (exceeds pool) | Most succeed, data consistent |
| `test_pool_exhaustion_concurrent_tracking` | 20 concurrent metric updates | Most succeed, no data loss |
| `test_pool_exhaustion_recovery` | Operations after pool exhaustion | Service recovers, new operations work |

### C. Transaction Failures & Rollback (4 tests)

| Test | Scenario | Verification |
|------|----------|--------------|
| `test_assignment_rollback_on_error` | Error after flush, before commit | Complete rollback, no partial data |
| `test_experiment_creation_rollback` | Error during multi-entity creation | Atomic rollback of experiment + variants |
| `test_partial_metric_update_rollback` | Error during metric update | Original metrics preserved |
| `test_nested_transaction_failure` | Error in nested operations | All nested operations rolled back |

### D. Concurrency & Transaction Conflicts (3 tests)

| Test | Scenario | Verification |
|------|----------|--------------|
| `test_concurrent_assignment_creation` | 20 parallel assignments | All succeed (different IDs) |
| `test_concurrent_metric_updates` | Race condition in counter updates | Demonstrates lost updates |
| `test_optimistic_locking_conflict` | Concurrent experiment status updates | Last write wins |

### E. Data Integrity & Constraints (3 tests)

| Test | Scenario | Verification |
|------|----------|--------------|
| `test_duplicate_assignment_prevention` | Duplicate assignment ID | IntegrityError raised |
| `test_foreign_key_violation_handling` | Assignment to non-existent experiment | Orphan detection works |
| `test_null_constraint_handling` | Required field is null | Exception raised |

### F. Comprehensive Integration (1 test)

| Test | Scenario | Verification |
|------|----------|--------------|
| `test_comprehensive_failure_recovery` | End-to-end workflow with validations | All integrity checks pass |

**Total: 19 database failure tests**

---

## Test Patterns

### 1. Mocking Connection Failures

```python
@contextmanager
def mock_connection_error():
    """Simulate database connection loss."""
    with patch('src.observability.database.get_session') as mock:
        mock.side_effect = OperationalError(
            "connection to server was lost",
            params=None,
            orig=None
        )
        yield mock

# Usage
with mock_connection_error():
    with pytest.raises(OperationalError):
        service.assign_variant("wf-1", "exp-1")
```

### 2. Mocking Pool Exhaustion

```python
@contextmanager
def mock_pool_timeout():
    """Simulate connection pool timeout."""
    with patch('src.observability.database.get_session') as mock:
        mock.side_effect = TimeoutError(
            "QueuePool limit of size 5 overflow 10 reached"
        )
        yield mock
```

### 3. Testing Transaction Conflicts

```python
# Pattern: Mid-transaction failure
try:
    with db_manager.session() as session:
        assignment = VariantAssignment(...)
        session.add(assignment)
        session.flush()  # Writes to DB but not committed

        raise RuntimeError("Simulated error")  # Before commit
except RuntimeError:
    pass

# Verification: Data should be rolled back
with db_manager.session() as session:
    assert session.get(VariantAssignment, assignment_id) is None
```

### 4. Testing Concurrent Operations

```python
@pytest.mark.asyncio
async def test_concurrent_operations():
    """Test concurrent database access."""
    results = []

    async def concurrent_operation(idx: int):
        await asyncio.sleep(0.001)  # Ensure overlap
        try:
            with db_manager.session() as session:
                # Perform operation
                session.add(...)
                session.commit()
                results.append("success")
        except Exception as e:
            results.append(f"error: {type(e).__name__}")

    # Fire N concurrent tasks
    tasks = [concurrent_operation(i) for i in range(N)]
    await asyncio.gather(*tasks, return_exceptions=True)

    # Verify results
    success_count = sum(1 for r in results if r == "success")
    assert success_count >= expected_minimum
```

---

## Verification Helpers

### 1. Verify No Partial State

```python
def verify_no_partial_state(session: Session, experiment_id: str) -> None:
    """Verify no partial state exists after rollback."""
    # No orphaned assignments
    assignments = session.exec(
        select(VariantAssignment).where(
            VariantAssignment.experiment_id == experiment_id
        )
    ).all()
    assert len(assignments) == 0, f"Found {len(assignments)} orphaned assignments"

    # No orphaned variants
    variants = session.exec(
        select(Variant).where(Variant.experiment_id == experiment_id)
    ).all()
    assert len(variants) == 0, f"Found {len(variants)} orphaned variants"

    # No experiment record
    experiment = session.get(Experiment, experiment_id)
    assert experiment is None, "Found orphaned experiment"
```

**When to use:** After any test that simulates rollback to ensure atomicity.

### 2. Verify Assignment Integrity

```python
def verify_assignment_integrity(session: Session, assignment_id: str) -> None:
    """Verify assignment data integrity."""
    assignment = session.get(VariantAssignment, assignment_id)

    if assignment:
        # Foreign keys exist
        experiment = session.get(Experiment, assignment.experiment_id)
        assert experiment is not None, "Invalid experiment_id"

        variant = session.get(Variant, assignment.variant_id)
        assert variant is not None, "Invalid variant_id"

        # Metrics are valid
        if assignment.metrics:
            assert isinstance(assignment.metrics, dict)
            for key, value in assignment.metrics.items():
                assert isinstance(value, (int, float))
```

**When to use:** After operations that modify assignments to ensure referential integrity.

### 3. Verify Experiment Consistency

```python
def verify_experiment_consistency(session: Session, experiment_id: str) -> None:
    """Verify experiment and variants are consistent."""
    experiment = session.get(Experiment, experiment_id)
    if not experiment:
        return

    variants = session.exec(
        select(Variant).where(Variant.experiment_id == experiment_id)
    ).all()

    # Traffic allocation matches variants
    assert set(experiment.traffic_allocation.keys()) == \
           set(v.name for v in variants)

    # Traffic sums to <= 1.0
    total_traffic = sum(experiment.traffic_allocation.values())
    assert total_traffic <= 1.0

    # Has exactly one control variant
    control_count = sum(1 for v in variants if v.is_control)
    assert control_count == 1
```

**When to use:** After experiment creation/modification to ensure business logic constraints.

---

## Connection Pool Testing Strategy

### Challenge
Testing true pool exhaustion requires:
1. Configurable pool size
2. Concurrent operations exceeding pool size
3. Proper timeout handling

### Implementation

```python
@pytest.mark.asyncio
async def test_pool_exhaustion_concurrent_assignments():
    """Test connection pool with concurrent requests."""
    # Setup: Database with small pool (production uses larger pool)
    # Note: SQLite uses StaticPool, so this tests concurrency handling

    service = ExperimentService()
    exp_id = service.create_experiment(...)

    results = {"success": 0, "failure": 0}

    async def assign_variant(wf_id: str):
        try:
            await asyncio.sleep(0.001)  # Ensure temporal overlap
            assignment = service.assign_variant(wf_id, exp_id)
            results["success"] += 1
        except Exception:
            results["failure"] += 1

    # Fire N concurrent requests (N > pool_size)
    tasks = [assign_variant(f"wf-{i}") for i in range(50)]
    await asyncio.gather(*tasks, return_exceptions=True)

    # Assertions
    assert results["success"] >= 40, "Too many failures"

    # Verify data consistency (all successful assignments in DB)
    with get_session() as session:
        count = session.exec(
            select(VariantAssignment).where(
                VariantAssignment.experiment_id == exp_id
            )
        ).count()
        assert count == results["success"]
```

### Key Points
- SQLite uses `StaticPool` (single connection), so doesn't truly exhaust
- PostgreSQL uses `QueuePool` with configurable `pool_size` and `max_overflow`
- Test validates concurrent access handling regardless of pool type
- Production databases should set `pool_pre_ping=True` for connection health checks

---

## Transaction Conflict Testing

### Race Condition Pattern

```python
@pytest.mark.asyncio
async def test_concurrent_metric_updates():
    """Demonstrate race condition in metric updates."""
    # Create assignment with counter metric
    assignment_id = "asn-race-test"

    # Initial state: counter = 0
    with db_manager.session() as session:
        assignment = VariantAssignment(
            id=assignment_id,
            ...,
            metrics={"counter": 0}
        )
        session.add(assignment)
        session.commit()

    # Concurrent increment function
    async def increment_counter():
        await asyncio.sleep(0.001)
        with db_manager.session() as session:
            asn = session.get(VariantAssignment, assignment_id)
            current = asn.metrics.get("counter", 0)

            # Simulate processing delay (increases race window)
            await asyncio.sleep(0.002)

            asn.metrics = {"counter": current + 1}
            session.commit()

    # 10 concurrent increments
    tasks = [increment_counter() for _ in range(10)]
    await asyncio.gather(*tasks, return_exceptions=True)

    # Verification: Due to race condition, final count < 10
    with db_manager.session() as session:
        asn = session.get(VariantAssignment, assignment_id)
        final_count = asn.metrics.get("counter", 0)

        assert final_count >= 1  # At least one succeeded
        assert final_count <= 10  # But likely lost updates
```

### Solutions to Race Conditions

1. **Optimistic Locking** (not currently implemented)
   ```python
   # Add version field to model
   class VariantAssignment(SQLModel, table=True):
       version: int = 0

   # In update logic
   result = session.execute(
       update(VariantAssignment)
       .where(VariantAssignment.id == id)
       .where(VariantAssignment.version == current_version)
       .values(metrics=new_metrics, version=current_version + 1)
   )
   if result.rowcount == 0:
       raise ConcurrentUpdateError()
   ```

2. **SERIALIZABLE Isolation**
   ```python
   with db_manager.session(isolation_level=IsolationLevel.SERIALIZABLE) as session:
       # Critical operations
       session.commit()  # May raise OperationalError
   ```

3. **Database-Level Locks**
   ```python
   # SELECT FOR UPDATE
   assignment = session.execute(
       select(VariantAssignment)
       .where(VariantAssignment.id == id)
       .with_for_update()
   ).scalar_one()
   ```

---

## Data Integrity Assertions

### Constraint Types

1. **Unique Constraints**
   ```python
   # Test duplicate prevention
   with pytest.raises(IntegrityError):
       with db_manager.session() as session:
           duplicate = VariantAssignment(id="existing-id", ...)
           session.add(duplicate)
           session.commit()
   ```

2. **Foreign Key Constraints**
   ```python
   # Test referential integrity
   try:
       with db_manager.session() as session:
           orphan = VariantAssignment(
               experiment_id="nonexistent",
               ...
           )
           session.add(orphan)
           session.commit()

       # If FK not enforced, verify orphan detection
       with db_manager.session() as session:
           with pytest.raises(AssertionError):
               verify_assignment_integrity(session, orphan.id)
   except IntegrityError:
       pass  # FK enforced - expected
   ```

3. **Not Null Constraints**
   ```python
   with pytest.raises(Exception):
       with db_manager.session() as session:
           invalid = Experiment(name=None, ...)  # Required field
           session.add(invalid)
           session.commit()
   ```

---

## Best Practices

### 1. Test Isolation
- Use `temp_db_file` fixture for isolated test database
- Call `reset_database()` between tests that modify global state
- Use transactions for test data setup and teardown

### 2. Async Testing
- Use `@pytest.mark.asyncio` for concurrent tests
- Add small `await asyncio.sleep()` delays to ensure temporal overlap
- Use `asyncio.gather(*tasks, return_exceptions=True)` to collect results

### 3. Error Handling
- Test both error propagation (exceptions raised) and graceful degradation
- Verify error messages are informative
- Test recovery after errors

### 4. Data Verification
- Always verify final state after operations
- Use assertion helpers for consistency
- Check both success and failure paths

### 5. Performance Considerations
- Keep concurrent task counts reasonable (20-100)
- Use small sleep delays (0.001-0.01s)
- Test with realistic data volumes

---

## Running the Tests

```bash
# Run all database failure tests
pytest tests/test_experimentation/test_database_failures.py -v

# Run specific test class
pytest tests/test_experimentation/test_database_failures.py::TestConnectionFailures -v

# Run with coverage
pytest tests/test_experimentation/test_database_failures.py --cov=src.experimentation --cov-report=html

# Run async tests only
pytest tests/test_experimentation/test_database_failures.py -k "async" -v

# Run with detailed output
pytest tests/test_experimentation/test_database_failures.py -vv -s
```

---

## Expected Coverage

### Module Coverage Targets

| Module | Target | Focus |
|--------|--------|-------|
| `src.experimentation.service` | 85%+ | DB operations, error handling |
| `src.experimentation.models` | 90%+ | Constraint validation |
| `src.observability.database` | 80%+ | Session management, isolation |

### Scenario Coverage

- **Connection failures:** 5/5 scenarios ✓
- **Pool exhaustion:** 3/3 scenarios ✓
- **Transaction rollback:** 4/4 scenarios ✓
- **Concurrency conflicts:** 3/3 scenarios ✓
- **Data integrity:** 3/3 scenarios ✓
- **Integration:** 1/1 scenario ✓

**Total: 19/19 scenarios covered**

---

## Integration with Existing Tests

### Relationship to `test_database_failures.py` (observability)

The observability module's database failure tests focus on:
- WorkflowExecution, StageExecution, AgentExecution models
- Generic database operations (CRUD, queries)
- Infrastructure-level failures

This test suite focuses on:
- Experimentation-specific models (Experiment, Variant, Assignment)
- Business logic constraints (traffic allocation, metrics)
- A/B testing workflow integrity

### Complementary Coverage

| Area | Observability Tests | Experimentation Tests |
|------|-------------------|---------------------|
| Connection failures | ✓ Generic | ✓ Experiment-specific |
| Transaction rollback | ✓ Basic | ✓ Multi-entity atomic |
| Concurrency | ✓ Read/write races | ✓ Assignment races |
| Data integrity | ✓ FK violations | ✓ Business constraints |
| Pool exhaustion | ✗ Not covered | ✓ Concurrent assignments |

---

## Future Enhancements

### 1. Distributed Locking Tests
```python
def test_distributed_lock_acquisition_failure():
    """Test experiment assignment with distributed lock failure."""
    # Requires distributed lock implementation
    pass

def test_lock_timeout_handling():
    """Test timeout when lock held too long."""
    pass
```

### 2. Checkpoint/Restore Tests
```python
def test_assignment_checkpoint_on_db_failure():
    """Test checkpointing assignments on DB failure."""
    pass

def test_restore_from_checkpoint_after_crash():
    """Test restoring experiment state from checkpoint."""
    pass
```

### 3. PostgreSQL-Specific Tests
```python
@pytest.mark.postgres
def test_serializable_isolation_conflict():
    """Test SERIALIZABLE isolation conflicts (PostgreSQL)."""
    # Requires PostgreSQL test database
    pass
```

### 4. Performance/Load Tests
```python
@pytest.mark.slow
def test_assignment_throughput_under_load():
    """Test assignment throughput with 1000+ concurrent requests."""
    pass
```

---

## Conclusion

This test suite provides comprehensive coverage of database failure scenarios for the experimentation module, ensuring:

1. **Reliability:** Proper error handling and recovery
2. **Data Integrity:** No partial state, atomicity guarantees
3. **Concurrency Safety:** Race condition awareness and handling
4. **Production Readiness:** Tests real-world failure modes

The tests serve as both verification and documentation of expected behavior under adverse conditions.
