# Task: test-high-observability-02 - Fix Incomplete Migration and N+1 Query Tests

**Priority:** HIGH
**Effort:** 2 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

Complete migration rollback verification tests and add actual query count verification for N+1 query detection tests.

---

## Files to Create

- None

---

## Files to Modify

- `tests/test_observability/test_migrations.py - Complete rollback verification`
- `tests/test_observability/test_n_plus_one.py - Add query count verification`

---

## Acceptance Criteria


### Core Functionality
- [ ] Complete migration rollback verification (currently incomplete)
- [ ] Add actual query count verification to N+1 tests
- [ ] Verify database state after rollback
- [ ] Test forward and backward migrations
- [ ] Detect N+1 queries with query counters

### Testing
- [ ] Migration: apply migration, rollback, verify state restored
- [ ] N+1: count queries, assert exact count (not approximate)
- [ ] Edge case: partial migration failure
- [ ] Edge case: N+1 in nested relationships

---

## Implementation Details

```python
def test_migration_rollback_verification():
    """Test migration rollback restores previous state"""
    # Capture initial state
    initial_schema = get_database_schema()

    # Apply migration
    run_migration("0001_add_user_table")
    assert table_exists("users")

    # Rollback migration
    rollback_migration("0001_add_user_table")

    # Verify state restored
    final_schema = get_database_schema()
    assert final_schema == initial_schema
    assert not table_exists("users")

def test_n_plus_one_query_actual_count():
    """Test N+1 query detection with actual query counting"""
    with query_counter() as counter:
        # Load 10 users
        users = User.query.all()  # 1 query
        # Access related posts (N+1 problem if not eager loaded)
        for user in users:
            _ = user.posts.all()  # Should be 1 query with eager load, 10 without

    # Without eager loading: 1 + 10 = 11 queries
    # With eager loading: 1 + 1 = 2 queries
    assert counter.count == 2, f"N+1 detected: {counter.count} queries"
```

---

## Test Strategy

Test migration forward and backward. Count actual queries. Verify state restoration.

---

## Success Metrics

- [ ] Migration rollback fully tested
- [ ] N+1 query detection working
- [ ] Query counts verified (not approximate)

---

## Dependencies

- **Blocked by:** None
- **Blocks:** None
- **Integrates with:** MigrationManager, QueryCounter

---

## Design References

- .claude-coord/reports/test-review-20260128-200844.md - Section 2, High Issues #5-6

---

## Notes

Use SQLAlchemy query counter. Test both forward and backward migrations.
