# Task: Add comprehensive error handling tests

## Summary

def test_disk_full_during_database_write(self):
    with patch('sqlite3.connect') as mock_connect:
        mock_connect.side_effect = sqlite3.OperationalError('disk I/O error')
        with pytest.raises(DatabaseWriteError) as exc:
            db.write_workflow_execution(...)
        assert 'disk full' in str(exc.value).lower()
        # Verify: rollback occurred, no partial state

**Priority:** HIGH  
**Estimated Effort:** 12.0 hours  
**Module:** Error Handling  
**Issues Addressed:** 10

---

## Files to Create

- `tests/test_error_handling/test_comprehensive_errors.py` - Network, disk, resource exhaustion error tests

---

## Files to Modify

_None_

---

## Acceptance Criteria


### Core Functionality

- [ ] Network failures (connection refused, timeout, DNS)
- [ ] Disk full during file write/DB write
- [ ] Permission denied during rollback
- [ ] Resource exhaustion (file descriptors, threads)
- [ ] Partial network reads (incomplete HTTP)
- [ ] Signal handling (SIGTERM, SIGINT)
- [ ] Clock skew in timestamp comparisons
- [ ] Out of memory scenarios

### Testing

- [ ] 40+ error scenarios
- [ ] Mock each error type
- [ ] Verify graceful degradation
- [ ] Verify error messages helpful


---

## Implementation Details

def test_disk_full_during_database_write(self):
    with patch('sqlite3.connect') as mock_connect:
        mock_connect.side_effect = sqlite3.OperationalError('disk I/O error')
        with pytest.raises(DatabaseWriteError) as exc:
            db.write_workflow_execution(...)
        assert 'disk full' in str(exc.value).lower()
        # Verify: rollback occurred, no partial state

---

## Test Strategy

Mock each error type. Verify graceful handling. Test error messages. Verify rollback/cleanup.

---

## Success Metrics

- [ ] 40+ error scenarios tested
- [ ] All handled gracefully
- [ ] Helpful error messages
- [ ] Proper cleanup verified

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** _None_

---

## Design References

- .claude-coord/reports/test-review-20260130-223857.md#51-error-handling-gaps

---

## Notes

Important for production robustness. Many error paths not tested.
