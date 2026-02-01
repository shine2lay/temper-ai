# Task: test-med-consolidate-test-fixtures-07 - Consolidate duplicate test fixtures into shared conftest

**Priority:** NORMAL
**Effort:** 6 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

# tests/conftest.py
import pytest

@pytest.fixture
def db():
    '''Shared database fixture for all tests'''
    return init_database('sqlite:///:memory:')

@pytest.fixture
def mock_llm():
    '''Shared mock LLM for all tests'''
    return Mock(spec=LLMProvider)

**Module:** Testing Infrastructure
**Issues Addressed:** 5

---

## Files to Create

- `tests/conftest.py` - Shared fixtures for all tests

---

## Files to Modify

- `tests/test_compiler/conftest.py` - Move shared fixtures to root conftest
- `tests/test_safety/conftest.py` - Move shared fixtures to root conftest
- `tests/regression/conftest.py` - Remove duplicate fixtures

---

## Acceptance Criteria

### Core Functionality

- [ ] Create tests/conftest.py with shared fixtures
- [ ] Move duplicate fixtures (db, mock_llm, temp_dir) to root
- [ ] Remove duplicate fixtures from module conftest files
- [ ] Ensure all tests can access shared fixtures
- [ ] Document fixture purpose in docstrings

### Testing

- [ ] All tests pass with consolidated fixtures
- [ ] No fixture conflicts
- [ ] Fixtures properly scoped (function/module/session)

---

## Implementation Details

# tests/conftest.py
import pytest

@pytest.fixture
def db():
    '''Shared database fixture for all tests'''
    return init_database('sqlite:///:memory:')

@pytest.fixture
def mock_llm():
    '''Shared mock LLM for all tests'''
    return Mock(spec=LLMProvider)

---

## Test Strategy

Identify duplicate fixtures. Move to root conftest. Remove from modules. Verify all tests pass.

---

## Success Metrics

- [ ] No duplicate fixtures
- [ ] All shared fixtures in root conftest
- [ ] All tests pass
- [ ] Clear fixture documentation

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** pytest

---

## Design References

- .claude-coord/reports/test-review-20260130-223857.md#test-organization

---

## Notes

Reduces duplication and ensures consistent test setup.
