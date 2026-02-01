# M5: Add Baseline Storage Logic to PerformanceAnalyzer

**Date:** 2026-02-01
**Task:** code-med-m5-baseline-storage
**Category:** Feature Enhancement

## What Changed

Added baseline storage and retrieval functionality to `PerformanceAnalyzer` class in M5 self-improvement system.

### Files Modified
- `src/self_improvement/performance_analyzer.py`
  - Added file system-based baseline storage using JSON
  - Added `store_baseline()` method to persist performance profiles
  - Added `retrieve_baseline()` method to load stored baselines
  - Added `delete_baseline()` method to remove stored baselines
  - Added `list_baselines()` method to enumerate all stored baselines
  - Modified `get_baseline()` to check for stored baselines first before calculating
  - Added `baseline_storage_path` parameter to `__init__()`

### Files Created
- `tests/self_improvement/test_baseline_storage.py`
  - Comprehensive test suite for baseline storage functionality
  - 9 test cases covering all storage operations

## Why

The M5 self-improvement system needs to store baseline performance profiles to:
1. Compare current agent performance against historical baselines
2. Detect when performance has degraded or improved
3. Make informed decisions about when to trigger optimization experiments
4. Avoid recalculating baselines repeatedly (performance optimization)

Previously, `get_baseline()` would recalculate the baseline every time it was called, which was inefficient and didn't provide a stable reference point for comparisons.

## Implementation Details

**Storage Mechanism:**
- File-based JSON storage in `.baselines/` directory
- One file per agent: `{agent_name}_baseline.json`
- Uses `AgentPerformanceProfile.to_dict()` / `from_dict()` for serialization
- Auto-generates `profile_id` (UUID) if not present

**Key Methods:**
```python
# Store a baseline (calculates if profile not provided)
analyzer.store_baseline("my_agent", profile)
analyzer.store_baseline("my_agent")  # auto-calculates

# Retrieve stored baseline
baseline = analyzer.retrieve_baseline("my_agent")

# Delete baseline
analyzer.delete_baseline("my_agent")

# List all stored baselines
agents = analyzer.list_baselines()

# Get baseline (checks storage first, then calculates)
baseline = analyzer.get_baseline("my_agent")
```

**Error Handling:**
- Validates agent_name matches profile
- Handles missing files gracefully (returns None)
- Raises clear errors for I/O failures
- Logs all operations for debugging

## Testing

**Test Coverage:**
- Store and retrieve baseline
- Retrieve nonexistent baseline (returns None)
- Delete baseline
- Delete nonexistent baseline
- List all baselines (sorted)
- get_baseline() uses stored baseline
- Auto-generation of profile_id
- Validation of agent_name mismatch
- Persistence across analyzer instances

**All 9 tests passing:**
```
tests/self_improvement/test_baseline_storage.py::TestBaselineStorage::test_store_and_retrieve_baseline PASSED
tests/self_improvement/test_baseline_storage.py::TestBaselineStorage::test_retrieve_nonexistent_baseline PASSED
tests/self_improvement/test_baseline_storage.py::TestBaselineStorage::test_delete_baseline PASSED
tests/self_improvement/test_baseline_storage.py::TestBaselineStorage::test_delete_nonexistent_baseline PASSED
tests/self_improvement/test_baseline_storage.py::TestBaselineStorage::test_list_baselines PASSED
tests/self_improvement/test_baseline_storage.py::TestBaselineStorage::test_get_baseline_uses_stored PASSED
tests/self_improvement/test_baseline_storage.py::TestBaselineStorage::test_store_baseline_profile_id_generated PASSED
tests/self_improvement/test_baseline_storage.py::TestBaselineStorage::test_store_baseline_mismatched_agent_name PASSED
tests/self_improvement/test_baseline_storage.py::TestBaselineStorage::test_baseline_persistence PASSED
```

## Risks

**Low Risk:**
- File-based storage is simple and reliable
- Graceful fallback to calculation if no stored baseline
- Backward compatible (existing code continues to work)
- Storage directory creation is automatic

**Potential Issues:**
- File system I/O could fail (disk full, permissions)
  - Mitigation: Clear error messages, logging
- Multiple analyzer instances could cause file conflicts
  - Mitigation: Simple file locking could be added if needed
- `.baselines/` directory could grow over time
  - Mitigation: Manual cleanup or TTL expiration (future enhancement)

## Future Enhancements

1. **Database Storage:** Move from file-based to database table for better querying
2. **Baseline Versioning:** Store multiple baseline versions with timestamps
3. **Automatic Expiration:** TTL-based cleanup of old baselines
4. **Baseline Comparison:** Built-in diff between current and baseline
5. **Baseline Metadata:** Add tags, descriptions, creation reasons

## Dependencies

**Completed:**
- code-high-m5-performance-analyzer (analyzer exists)
- test-med-m5-phase1-validation (execution data exists)

**Unblocks:**
- test-med-m5-phase2-validation (can now test baseline storage)
- code-med-m5-performance-comparison (will use stored baselines)
