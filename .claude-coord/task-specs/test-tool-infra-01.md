# Task: test-tool-infra-01 - Add Tool Version Conflict Tests

**Priority:** NORMAL
**Effort:** 2 hours
**Status:** pending
**Owner:** unassigned
**Category:** Tool Infrastructure (P2)

---

## Summary
Test that tool registry handles version conflicts gracefully.

---

## Files to Modify
- `tests/test_tools/test_registry.py` - Add version conflict tests
- `src/tools/registry.py` - Add version handling if needed

---

## Acceptance Criteria

### Version Handling
- [ ] Tools can specify version (e.g., "1.0.0")
- [ ] Registry detects version conflicts
- [ ] Can request specific tool version
- [ ] Default to latest version

---

## Implementation Details

```python
def test_tool_registry_version_conflicts():
    """Test registry handles tool version conflicts."""
    registry = ToolRegistry()
    
    tool_v1 = TestTool(name="search", version="1.0.0")
    tool_v2 = TestTool(name="search", version="2.0.0")
    
    registry.register(tool_v1)
    registry.register(tool_v2)
    
    # Default to latest version
    tool = registry.get("search")
    assert tool.version == "2.0.0"
    
    # Can request specific version
    tool_old = registry.get("search", version="1.0.0")
    assert tool_old.version == "1.0.0"
```

---

## Success Metrics
- [ ] Version conflicts handled
- [ ] Can specify tool version

---

## Dependencies
- **Blocked by:** None
- **Blocks:** None

---

## Design References
- QA Report: test_registry.py - Version Conflicts (P2)
