# Task: test-crit-checkpoint-01 - Add Checkpoint Rollback Failure Scenarios

**Priority:** CRITICAL
**Effort:** 2.5 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

Add comprehensive test coverage for checkpoint rollback failure scenarios in the compiler's checkpoint manager.

---

## Files to Create

- None

---

## Files to Modify

- `tests/test_compiler/test_checkpoint_manager.py - Add rollback failure scenario tests`

---

## Acceptance Criteria


### Core Functionality
- [ ] Test rollback when checkpoint save fails mid-operation
- [ ] Test partial checkpoint corruption recovery
- [ ] Test rollback during concurrent checkpoint operations
- [ ] Test checkpoint restore failure with state inconsistency
- [ ] Verify state consistency after rollback failures
- [ ] Ensure no partial state left after failed checkpoint

### Testing
- [ ] Unit tests for all 4 rollback failure scenarios
- [ ] Integration test for concurrent rollback isolation
- [ ] Edge case: corrupted checkpoint file detection
- [ ] Edge case: concurrent checkpoint operations
- [ ] Mock checkpoint storage failures

### Security Controls
- [ ] Prevent state corruption from failed rollback
- [ ] Validate checkpoint integrity before restore
- [ ] Ensure rollback atomicity (all-or-nothing)

---

## Implementation Details

```python
def test_checkpoint_save_failure_triggers_rollback():
    """Test that failed save doesn't leave partial state"""
    manager = CheckpointManager()
    with patch('checkpoint.save', side_effect=IOError):
        with pytest.raises(CheckpointError):
            manager.create_checkpoint(state)
    assert not manager.has_partial_checkpoints()

def test_corrupted_checkpoint_recovery():
    """Test handling of corrupted checkpoint files"""
    manager = CheckpointManager()
    checkpoint_path = manager.checkpoint_dir / "corrupted.ckpt"
    checkpoint_path.write_bytes(b"corrupted data")
    with pytest.raises(CorruptedCheckpointError):
        manager.restore(checkpoint_path)

def test_concurrent_checkpoint_rollback_isolation():
    """Test rollback doesn't affect other workflows"""
    manager = CheckpointManager()
    workflow1 = manager.create_checkpoint(state1)
    workflow2 = manager.create_checkpoint(state2)
    manager.rollback(workflow1)
    assert manager.get_state(workflow2) == state2
```

---

## Test Strategy

Use real threading with ThreadPoolExecutor. Mock checkpoint storage to simulate failures. Verify state consistency after all operations.

---

## Success Metrics

- [ ] All 4 rollback scenarios tested
- [ ] Test coverage for checkpoint_manager.py rollback code >90%
- [ ] No flaky tests (all deterministic)
- [ ] Tests run in <500ms total

---

## Dependencies

- **Blocked by:** None
- **Blocks:** None
- **Integrates with:** CheckpointManager, StateManager

---

## Design References

- .claude-coord/reports/test-review-20260128-200844.md - Section 1, Critical Issue #1

---

## Notes

Use ThreadPoolExecutor for real concurrency testing. Clean up corrupted files in teardown.
