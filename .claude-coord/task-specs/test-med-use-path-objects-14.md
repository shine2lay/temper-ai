# Task: test-med-use-path-objects-14 - Replace hard-coded string paths with Path objects

**Priority:** NORMAL
**Effort:** 6 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

# Before
import os
path = os.path.join('/tmp', 'test', 'file.txt')
if os.path.exists(path):
    os.remove(path)

# After
from pathlib import Path
path = Path('/tmp') / 'test' / 'file.txt'
if path.exists():
    path.unlink()

**Module:** Code Quality
**Issues Addressed:** 8

---

## Files to Create

_None_

---

## Files to Modify

- `tests/test_utils/test_path_safety.py` - Use pathlib.Path
- `tests/test_tools/test_file_writer.py` - Use pathlib.Path
- `tests/regression/*.py` - Use pathlib.Path for temp files

---

## Acceptance Criteria

### Core Functionality

- [ ] Replace '/tmp/...' with Path('/tmp')
- [ ] Replace string path manipulation with Path methods
- [ ] Use Path.home(), Path.cwd() instead of os.path
- [ ] Path operations more readable (path / 'file' vs os.path.join)
- [ ] Cross-platform compatibility improved

### Testing

- [ ] All tests pass with Path objects
- [ ] No hard-coded string paths
- [ ] Tests work on Windows/Mac/Linux
- [ ] Path operations more readable

---

## Implementation Details

# Before
import os
path = os.path.join('/tmp', 'test', 'file.txt')
if os.path.exists(path):
    os.remove(path)

# After
from pathlib import Path
path = Path('/tmp') / 'test' / 'file.txt'
if path.exists():
    path.unlink()

---

## Test Strategy

Replace string paths with Path objects. Verify tests pass on multiple platforms.

---

## Success Metrics

- [ ] No hard-coded string paths
- [ ] All path ops use Path
- [ ] Cross-platform tests pass
- [ ] More readable code

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** _None_

---

## Design References

- .claude-coord/reports/test-review-20260130-223857.md#code-style

---

## Notes

Path objects are more Pythonic and cross-platform compatible.
