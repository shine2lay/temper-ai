# Task: test-crit-database-01 - Add Database Transaction Constraint Violation Tests

**Priority:** CRITICAL
**Effort:** 2 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

Add comprehensive tests for database transaction rollback on constraint violations.

---

## Files to Create

- None

---

## Files to Modify

- `tests/test_observability/test_database.py - Add constraint violation tests`

---

## Acceptance Criteria


### Core Functionality
- [ ] Test foreign key constraint violations trigger rollback
- [ ] Test unique constraint violations on non-PK fields
- [ ] Test check constraint failures
- [ ] Test transaction isolation level handling
- [ ] Verify rollback cleanup (no partial data)

### Testing
- [ ] Unit tests for each constraint type violation
- [ ] Integration test for transaction rollback atomicity
- [ ] Edge case: nested transaction rollback
- [ ] Edge case: constraint violation in batch insert

### Security Controls
- [ ] Ensure rollback prevents data corruption
- [ ] Validate referential integrity maintained

---

## Implementation Details

```python
def test_foreign_key_constraint_violation_rollback():
    """Test FK violation triggers rollback"""
    session = get_test_session()
    with pytest.raises(IntegrityError, match="foreign key"):
        session.add(ChildRecord(parent_id=9999))  # Non-existent parent
        session.commit()
    session.rollback()
    assert session.query(ChildRecord).count() == 0

def test_unique_constraint_violation_non_pk_fields():
    """Test unique constraint on non-PK field"""
    session = get_test_session()
    session.add(User(email="test@example.com"))
    session.commit()
    with pytest.raises(IntegrityError, match="unique"):
        session.add(User(email="test@example.com"))
        session.commit()
```

---

## Test Strategy

Use real database transactions. Test each constraint type. Verify rollback cleanup.

---

## Success Metrics

- [ ] All 4 constraint types tested
- [ ] Test coverage for database.py constraint handling >85%
- [ ] All tests use real database (not mocks)
- [ ] Tests run in <1 second total

---

## Dependencies

- **Blocked by:** None
- **Blocks:** None
- **Integrates with:** DatabaseSession, TransactionManager

---

## Design References

- .claude-coord/reports/test-review-20260128-200844.md - Section 1, Critical Issue #3

---

## Notes

Use test database with transaction isolation. Clean up test data in teardown.
