# Database Test Patterns - Quick Reference

Quick reference for database failure testing patterns in the experimentation module.

---

## Pattern 1: Connection Failure Test

**Use when:** Testing database connection loss during operations

```python
def test_operation_with_connection_failure(experiment_service):
    """Test operation fails gracefully on connection loss."""
    # Setup: Create resources
    exp_id = experiment_service.create_experiment(...)

    # Test: Mock connection failure
    with mock_connection_error():
        with pytest.raises(OperationalError):
            experiment_service.assign_variant("wf-1", exp_id)

    # Verify: No partial state
    with get_session() as session:
        assignment = session.query(...).first()
        assert assignment is None
```

---

## Pattern 2: Transaction Rollback Test

**Use when:** Testing atomic operations that should rollback on error

```python
def test_atomic_operation_rollback(db_manager):
    """Test operation rolls back completely on error."""
    # Test: Operation that fails mid-transaction
    try:
        with db_manager.session() as session:
            entity = Entity(...)
            session.add(entity)
            session.flush()  # Write but don't commit

            raise RuntimeError("Simulated error")
    except RuntimeError:
        pass

    # Verify: Complete rollback
    with db_manager.session() as session:
        assert session.get(Entity, entity_id) is None
```

---

## Pattern 3: Concurrent Operation Test

**Use when:** Testing concurrent database access and race conditions

```python
@pytest.mark.asyncio
async def test_concurrent_operations(db_manager):
    """Test concurrent operations with race conditions."""
    # Setup: Initial state
    create_initial_state()

    # Test: Concurrent operations
    results = []

    async def concurrent_op(idx: int):
        try:
            await asyncio.sleep(0.001)  # Ensure overlap
            with db_manager.session() as session:
                # Perform operation
                session.commit()
                results.append("success")
        except Exception as e:
            results.append(f"error: {type(e).__name__}")

    tasks = [concurrent_op(i) for i in range(N)]
    await asyncio.gather(*tasks, return_exceptions=True)

    # Verify: Expected success rate and data consistency
    success_count = sum(1 for r in results if r == "success")
    assert success_count >= MIN_EXPECTED
```

---

## Pattern 4: Pool Exhaustion Test

**Use when:** Testing connection pool limits with concurrent requests

```python
@pytest.mark.asyncio
async def test_pool_exhaustion(experiment_service):
    """Test service handles pool exhaustion gracefully."""
    # Setup: Experiment
    exp_id = experiment_service.create_experiment(...)

    # Test: Exceed pool capacity
    results = {"success": 0, "failure": 0}

    async def assign(wf_id: str):
        try:
            await asyncio.sleep(0.001)
            experiment_service.assign_variant(wf_id, exp_id)
            results["success"] += 1
        except Exception:
            results["failure"] += 1

    # More tasks than pool size
    tasks = [assign(f"wf-{i}") for i in range(100)]
    await asyncio.gather(*tasks, return_exceptions=True)

    # Verify: Most succeed, data consistent
    assert results["success"] >= 90
```

---

## Pattern 5: Data Integrity Test

**Use when:** Testing constraints (unique, foreign key, not null)

```python
def test_constraint_violation(db_manager):
    """Test constraint enforcement."""
    # Setup: Create entity
    with db_manager.session() as session:
        entity = Entity(id="ent-1", ...)
        session.add(entity)
        session.commit()

    # Test: Violate constraint
    with pytest.raises(IntegrityError):
        with db_manager.session() as session:
            duplicate = Entity(id="ent-1", ...)  # Same ID
            session.add(duplicate)
            session.commit()
```

---

## Pattern 6: Verification Helper

**Use when:** Verifying data integrity after operations

```python
def verify_entity_integrity(session: Session, entity_id: str):
    """Verify entity data integrity."""
    entity = session.get(Entity, entity_id)

    if entity:
        # Check foreign keys exist
        parent = session.get(Parent, entity.parent_id)
        assert parent is not None, "Invalid parent_id"

        # Check data validity
        assert entity.required_field is not None
        assert entity.numeric_field >= 0
```

---

## Pattern 7: No Partial State Verification

**Use when:** Ensuring atomic operations don't leave partial data

```python
def verify_no_partial_state(session: Session, parent_id: str):
    """Verify no orphaned child entities."""
    children = session.query(Child).filter_by(parent_id=parent_id).all()
    assert len(children) == 0, f"Found {len(children)} orphaned children"

    parent = session.get(Parent, parent_id)
    assert parent is None, "Found orphaned parent"
```

---

## Pattern 8: Recovery After Failure

**Use when:** Testing service recovery after database errors

```python
def test_recovery_after_failure(experiment_service, temp_db_file):
    """Test service recovers after database failure."""
    # Setup: Create data
    exp_id = experiment_service.create_experiment(...)

    # Simulate: Connection cycle
    reset_database()
    init_database(database_url=f"sqlite:///{temp_db_file}")

    # Verify: Can continue operations
    assignment = experiment_service.assign_variant("wf-1", exp_id)
    assert assignment is not None
```

---

## Common Assertions

### Success Assertions
```python
# Entity exists
assert entity is not None

# Correct count
assert count == expected_count

# Data matches
assert entity.field == expected_value

# Status correct
assert entity.status == ExpectedStatus.VALUE
```

### Failure Assertions
```python
# Exception raised
with pytest.raises(SpecificError):
    operation()

# Entity doesn't exist
assert entity is None

# No partial data
assert len(orphans) == 0

# Error message correct
assert "expected text" in str(exc_info.value)
```

### Data Integrity Assertions
```python
# Foreign keys valid
assert session.get(Parent, entity.parent_id) is not None

# Constraints satisfied
assert total <= 1.0
assert count >= 1

# Types correct
assert isinstance(entity.field, ExpectedType)
```

---

## Mock Helpers

### Mock Connection Error
```python
@contextmanager
def mock_connection_error():
    with patch('src.observability.database.get_session') as mock:
        mock.side_effect = OperationalError(
            "connection lost", None, None
        )
        yield mock
```

### Mock Pool Timeout
```python
@contextmanager
def mock_pool_timeout():
    with patch('src.observability.database.get_session') as mock:
        mock.side_effect = TimeoutError(
            "QueuePool limit reached"
        )
        yield mock
```

### Mock Transaction Conflict
```python
@contextmanager
def mock_transaction_conflict():
    def failing_commit(self):
        raise OperationalError(
            "could not serialize access", None, None
        )

    with patch.object(Session, 'commit', failing_commit):
        yield
```

---

## Fixture Patterns

### Temp Database
```python
@pytest.fixture
def temp_db_file():
    """Temporary database file."""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name
    yield db_path
    Path(db_path).unlink(missing_ok=True)
```

### Database Manager
```python
@pytest.fixture
def db_manager(temp_db_file):
    """Database manager with temp DB."""
    manager = DatabaseManager(database_url=f"sqlite:///{temp_db_file}")
    manager.create_all_tables()
    yield manager
```

### Service with DB
```python
@pytest.fixture
def experiment_service(temp_db_file):
    """Service with initialized database."""
    reset_database()
    init_database(database_url=f"sqlite:///{temp_db_file}")

    service = ExperimentService()
    service.initialize()

    yield service

    service.shutdown()
    reset_database()
```

---

## Async Test Patterns

### Basic Async Test
```python
@pytest.mark.asyncio
async def test_async_operation():
    """Test async operation."""
    result = await async_function()
    assert result is not None
```

### Concurrent Tasks
```python
@pytest.mark.asyncio
async def test_concurrent():
    """Test concurrent operations."""
    tasks = [async_op(i) for i in range(N)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    success_count = sum(1 for r in results if not isinstance(r, Exception))
    assert success_count >= MIN_EXPECTED
```

### With Sleep for Overlap
```python
async def concurrent_operation():
    await asyncio.sleep(0.001)  # Ensure temporal overlap
    # Perform operation
    await asyncio.sleep(0.002)  # Increase race window
    # Complete operation
```

---

## Common Test Structure

```python
class TestFeature:
    """Test feature with database."""

    def test_success_case(self, fixture):
        """Test successful operation."""
        # Setup
        setup_data()

        # Execute
        result = operation()

        # Verify
        assert result is not None
        verify_integrity()

    def test_failure_case(self, fixture):
        """Test operation failure."""
        # Setup
        setup_data()

        # Execute with expected failure
        with pytest.raises(ExpectedError):
            operation_that_fails()

        # Verify no side effects
        verify_no_changes()

    @pytest.mark.asyncio
    async def test_concurrent_case(self, fixture):
        """Test concurrent operations."""
        # Setup
        setup_data()

        # Execute concurrently
        tasks = [concurrent_op(i) for i in range(N)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Verify
        verify_consistency()
```

---

## Checklist for New DB Tests

- [ ] Test both success and failure paths
- [ ] Verify no partial state after rollback
- [ ] Check data integrity with helper functions
- [ ] Test concurrent access if applicable
- [ ] Verify error messages are informative
- [ ] Test recovery after failure
- [ ] Clean up test data (fixtures handle this)
- [ ] Add docstring explaining what's tested
- [ ] Run test in isolation (`pytest test_file.py::test_name`)
- [ ] Verify test coverage with `--cov`

---

## Running Tests

```bash
# Single test
pytest path/to/test.py::TestClass::test_method -v

# Test class
pytest path/to/test.py::TestClass -v

# All async tests
pytest path/to/test.py -k "async" -v

# With coverage
pytest path/to/test.py --cov=src.module --cov-report=html

# Verbose output
pytest path/to/test.py -vv -s

# Stop on first failure
pytest path/to/test.py -x
```

---

## Common Pitfalls

1. **Forgetting to reset database** between tests
   - Use `reset_database()` fixture or autouse fixture

2. **Not using `await` in async tests**
   - Always `await` async functions
   - Use `@pytest.mark.asyncio`

3. **Race conditions in concurrent tests**
   - Add small `await asyncio.sleep()` delays
   - Test may be flaky - increase delays or retry logic

4. **Foreign key constraints not enforced**
   - SQLite doesn't enforce FK by default
   - Test with PostgreSQL or use verification helpers

5. **Not testing rollback**
   - Use `session.flush()` before simulated error
   - Verify entity doesn't exist after rollback

6. **Incomplete verification**
   - Always check both success and cleanup
   - Use integrity verification helpers

---

## Resources

- **Test file:** `tests/test_experimentation/test_database_failures.py`
- **Design doc:** `DATABASE_FAILURE_TEST_DESIGN.md`
- **Database module:** `src/observability/database.py`
- **Service module:** `src/experimentation/service.py`
