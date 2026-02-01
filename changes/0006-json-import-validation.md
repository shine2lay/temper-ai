# Change Documentation: Add JSON Import Validation

## Summary

**Status:** COMPLETED
**Task:** code-crit-unsafe-deserial-09
**Issue:** Unsafe JSON deserialization could cause data corruption
**Fix:** Added type validation and structure checks

## Problem Statement

`Database.import_from_json()` loaded JSON without validation, risking:
- Data corruption from malformed JSON
- Type confusion errors
- Missing required fields
- Invalid database state

**Note:** The code already used parameterized queries (✅ SQL injection safe) and transactions (✅ atomic). The main missing piece was input validation.

## Changes Made

**File:** `.claude-coord/coord_service/database.py:688-747`

### Added Validation

```python
def import_from_json(self, json_path: str):
    """Import state from JSON file with validation."""

    # NEW: Validate top-level structure
    if not isinstance(state, dict):
        raise ValueError("JSON must be a dictionary")

    # NEW: Validate agents
    agents_data = state.get("agents", {})
    if not isinstance(agents_data, dict):
        raise ValueError("'agents' must be a dictionary")

    for agent_id, agent_data in agents_data.items():
        # Validate agent ID type
        if not isinstance(agent_id, str):
            raise ValueError(f"Agent ID must be string")

        # Validate agent data structure
        if not isinstance(agent_data, dict):
            raise ValueError(f"Agent data must be dict")

        # Validate required fields
        if 'pid' not in agent_data:
            raise ValueError(f"Agent missing required field 'pid'")

        # Validate pid type and value
        if not isinstance(agent_data['pid'], int) or agent_data['pid'] <= 0:
            raise ValueError(f"Agent pid must be positive integer")

    # Similar validation for tasks and locks...
```

## Security Improvements

| Protection | Before | After |
|------------|--------|-------|
| **SQL Injection** | ✅ Parameterized queries | ✅ Still safe |
| **Type Validation** | ❌ None | ✅ Full validation |
| **Required Fields** | ❌ No checks | ✅ Validated |
| **Structure Validation** | ❌ Assumed valid | ✅ Explicit checks |
| **Atomic Import** | ✅ Transaction | ✅ Still atomic |

## Testing

**Validation Tests:**
```python
# Valid JSON - should work
valid_json = {
    "agents": {"agent1": {"pid": 1234}},
    "tasks": {"task1": {"subject": "Test", "description": "Desc"}},
    "locks": {}
}

# Invalid: wrong type
invalid_json = {"agents": []}  # Should be dict
# Raises: ValueError: 'agents' must be a dictionary

# Invalid: missing required field
invalid_json = {"agents": {"agent1": {}}}  # Missing pid
# Raises: ValueError: Agent agent1 missing required field 'pid'

# Invalid: wrong pid type
invalid_json = {"agents": {"agent1": {"pid": "not_an_int"}}}
# Raises: ValueError: Agent agent1 pid must be positive integer
```

## Impact

✅ **Defense in Depth:** Multiple validation layers
✅ **Clear Errors:** Specific error messages guide users
✅ **No Breaking Changes:** Validates correctly formatted JSON
✅ **Backward Compatible:** Existing valid JSON still works

## References

- Task: `.claude-coord/task-specs/code-crit-unsafe-deserial-09.md`
- File: `.claude-coord/coord_service/database.py:688-747`

---

**Completed:** 2026-02-01
**Impact:** Data corruption prevention
**Breaking:** No (only rejects invalid JSON)
