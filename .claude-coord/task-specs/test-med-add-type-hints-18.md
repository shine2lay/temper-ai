# Task: test-med-add-type-hints-18 - Add type hints to test helper functions

**Priority:** NORMAL
**Effort:** 6 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

from typing import Generator, Iterator
import pytest

@pytest.fixture
def db() -> Iterator[DatabaseManager]:
    '''Database fixture with type hint'''
    manager = init_database('sqlite:///:memory:')
    yield manager
    manager.close()

def create_realistic_agent(name: str, tools: list[str]) -> AgentConfig:
    '''Helper with type hints'''
    return AgentConfig(name=name, tools=tools)

**Module:** Code Quality
**Issues Addressed:** 5

---

## Files to Create

_None_

---

## Files to Modify

- `tests/fixtures/*.py` - Add type hints to fixtures
- `tests/test_utils/*.py` - Add type hints to helpers

---

## Acceptance Criteria

### Core Functionality

- [ ] All fixture functions have return type hints
- [ ] All test helper functions have type hints
- [ ] Use typing.Generator for generator fixtures
- [ ] Run mypy on test code
- [ ] No type errors in tests

### Testing

- [ ] mypy passes on tests/
- [ ] All helpers have type hints
- [ ] Type hints improve IDE autocomplete
- [ ] All tests pass

---

## Implementation Details

from typing import Generator, Iterator
import pytest

@pytest.fixture
def db() -> Iterator[DatabaseManager]:
    '''Database fixture with type hint'''
    manager = init_database('sqlite:///:memory:')
    yield manager
    manager.close()

def create_realistic_agent(name: str, tools: list[str]) -> AgentConfig:
    '''Helper with type hints'''
    return AgentConfig(name=name, tools=tools)

---

## Test Strategy

Add type hints to all helpers. Run mypy. Fix type errors. Verify tests pass.

---

## Success Metrics

- [ ] All helpers have type hints
- [ ] mypy passes on tests/
- [ ] Better IDE autocomplete
- [ ] All tests pass

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** mypy

---

## Design References

- .claude-coord/reports/test-review-20260130-223857.md#code-style

---

## Notes

Type hints improve code quality and catch bugs earlier.
