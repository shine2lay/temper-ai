# Task: Add database failure recovery tests

## Summary

def test_assignment_creation_with_db_failure(self):
    with patch('src.observability.database.get_session') as mock:
        mock.side_effect = OperationalError('Connection lost')
        with pytest.raises(DatabaseConnectionError):
            create_assignment(experiment_id='exp-1', ...)
        # Verify: rollback occurred, no partial state

**Priority:** CRITICAL  
**Estimated Effort:** 12.0 hours  
**Module:** Experimentation  
**Issues Addressed:** 2

---

## Files to Create

_None_

---

## Files to Modify

- `tests/test_experimentation/test_integration.py` - Add DB connection loss, pool exhaustion, transaction conflict tests
- `tests/test_observability/test_database.py` - Add connection pool exhaustion tests

---

## Acceptance Criteria


### Core Functionality

- [ ] Database connection loss during experiment assignment
- [ ] Connection pool exhaustion scenarios (100 concurrent requests, pool_size=5)
- [ ] Transaction conflicts in concurrent modifications
- [ ] Distributed locking failures
- [ ] Checkpoint corruption scenarios
- [ ] Rollback on database failure

### Testing

- [ ] 15+ database failure scenarios
- [ ] Verify proper error handling and rollback
- [ ] Test with SQLite and PostgreSQL
- [ ] Verify data consistency after failures


---

## Implementation Details

def test_assignment_creation_with_db_failure(self):
    with patch('src.observability.database.get_session') as mock:
        mock.side_effect = OperationalError('Connection lost')
        with pytest.raises(DatabaseConnectionError):
            create_assignment(experiment_id='exp-1', ...)
        # Verify: rollback occurred, no partial state

---

## Test Strategy

Mock database failures at different points. Verify rollback and error handling. Test connection pool exhaustion with concurrent requests.

---

## Success Metrics

- [ ] All DB failures handled gracefully
- [ ] No data corruption on failures
- [ ] Proper rollback verified
- [ ] Connection pool exhaustion detected

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** DatabaseManager, ExperimentAssignment, ObservabilityTracker

---

## Design References

- .claude-coord/reports/test-review-20260130-223857.md#24-database-failure-recovery-not-tested-severity-critical

---

## Notes

CRITICAL for data integrity. No tests for database failures mid-operation.
