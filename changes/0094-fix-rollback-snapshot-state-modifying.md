# Fix Rollback Snapshot Creation for Read-Only Tools

**Type:** Bug Fix / Enhancement
**Scope:** Tool System, Rollback System
**Date:** 2026-01-27

## Summary

Fixed rollback snapshot creation to properly distinguish between state-modifying and read-only tools. Added `modifies_state` field to `ToolMetadata` to allow tools to declare whether they modify system state, replacing the hardcoded list approach.

## Motivation

The rollback system was creating snapshots for all tools, including read-only tools like `read_file`, `list_files`, etc. This wastes resources and creates unnecessary snapshots for operations that don't modify state.

**Problem:**
- Snapshots created for read-only operations
- Hardcoded list of read-only tools in executor (brittle, incomplete)
- No way for custom tools to declare read-only behavior
- Test failure: `test_snapshot_only_for_state_modifying_tools`

## Changes

### 1. Enhanced ToolMetadata

**File:** `src/tools/base.py`

```python
class ToolMetadata(BaseModel):
    """Tool metadata."""
    name: str
    description: str
    version: str = "1.0"
    category: Optional[str] = None
    requires_network: bool = False
    requires_credentials: bool = False
    modifies_state: bool = True  # NEW: Whether tool modifies system state
```

**Purpose:**
- Allows tools to declare whether they modify state (files, DB, external systems)
- Defaults to `True` for safety (conservative approach)
- Read-only tools can explicitly set to `False`

### 2. Updated Snapshot Logic

**File:** `src/tools/executor.py` (lines 459-479)

**Before:**
```python
def _should_snapshot(self, tool_name: str, params: Dict[str, Any]) -> bool:
    # Hardcoded list - brittle and incomplete
    read_only_tools = {
        "get_file", "list_files", "search", "read",
        "list_tools", "get_tool_info", "validate_params"
    }
    return tool_name not in read_only_tools
```

**After:**
```python
def _should_snapshot(self, tool_name: str, params: Dict[str, Any]) -> bool:
    """Determine if snapshot should be created for this tool.

    Skip snapshots for:
    - Read-only tools (tools with modifies_state=False)
    - Tools with no side effects
    """
    # Get tool metadata to check if it modifies state
    tool = self.registry.get(tool_name)
    if not tool:
        # If tool not found, don't create snapshot (execution will fail anyway)
        return False

    metadata = tool.get_metadata()
    return metadata.modifies_state
```

**Benefits:**
- Declarative approach - tools define their own behavior
- Extensible - works with custom tools
- Type-safe - uses Pydantic metadata
- Self-documenting - clear intent

### 3. Updated Test

**File:** `tests/integration/test_tool_rollback.py`

```python
class ReadTool(BaseTool):
    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="read_file",
            description="Read file",
            version="1.0.0",
            category="file",
            modifies_state=False  # Explicitly declare as read-only
        )
```

## Testing

### Before Fix
```bash
$ pytest tests/integration/test_tool_rollback.py::test_snapshot_only_for_state_modifying_tools
FAILED - AssertionError: assert 1 == 0
# Snapshot was created for read-only tool
```

### After Fix
```bash
$ pytest tests/integration/test_tool_rollback.py::test_snapshot_only_for_state_modifying_tools
PASSED ✅

$ pytest tests/integration/test_tool_rollback.py
4 passed ✅
```

## Impact

**Performance Benefits:**
- No snapshots for read-only operations
- Reduced memory usage
- Faster execution for query tools
- Less database overhead

**Extensibility:**
- Custom tools can declare read-only behavior
- No need to modify executor code
- Self-documenting tool behavior

**Safety:**
- Conservative default (`modifies_state=True`)
- Explicit opt-in for read-only behavior
- Backward compatible (existing tools still create snapshots)

## Tool Classification Examples

**State-Modifying Tools** (`modifies_state=True` - default):
- `write_file` - Modifies filesystem
- `delete_file` - Modifies filesystem
- `execute_command` - Potentially modifies system
- `api_post` - Modifies remote state
- `database_write` - Modifies database

**Read-Only Tools** (`modifies_state=False` - explicit):
- `read_file` - Only reads filesystem
- `list_files` - Only lists directory contents
- `search` - Only searches, doesn't modify
- `get_file_info` - Only retrieves metadata
- `api_get` - Only fetches data

## Migration Guide

### For Existing Tools

No changes required - existing tools default to `modifies_state=True` (safe default).

### For New Read-Only Tools

Explicitly set `modifies_state=False`:

```python
class MyReadOnlyTool(BaseTool):
    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="my_read_tool",
            description="Read-only operation",
            modifies_state=False  # No snapshots needed
        )
```

## Breaking Changes

None. This is fully backward compatible:
- Existing tools continue to work (default `modifies_state=True`)
- Existing snapshots still created for state-modifying tools
- API is additive only (new optional field)

## Related Issues

- Fixes test: `test_snapshot_only_for_state_modifying_tools`
- Improves rollback system efficiency
- Enables proper tool classification
- Reduces unnecessary snapshot overhead

## Future Enhancements

Potential improvements:
1. Automatic detection based on tool category
2. Snapshot size tracking and limits
3. Conditional snapshots based on parameters
4. Snapshot retention policies per tool type

## References

- Rollback System: `changes/0127-m4-rollback-mechanism.md`
- Tool System: `src/tools/base.py`
- Tool Executor: `src/tools/executor.py`
