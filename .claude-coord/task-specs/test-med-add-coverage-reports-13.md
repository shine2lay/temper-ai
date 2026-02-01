# Task: test-med-add-coverage-reports-13 - Add test coverage reporting to CI pipeline

**Priority:** NORMAL
**Effort:** 4 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

# pytest.ini
[pytest]
addopts = --cov=src --cov-report=html --cov-report=term --cov-fail-under=66

# .github/workflows/test.yml
- run: pytest --cov --cov-report=xml
- uses: codecov/codecov-action@v3

**Module:** CI/CD
**Issues Addressed:** 3

---

## Files to Create

- `.github/workflows/coverage.yml` - Coverage CI workflow

---

## Files to Modify

- `.github/workflows/test.yml` - Add coverage reporting
- `pytest.ini` - Configure coverage thresholds

---

## Acceptance Criteria

### Core Functionality

- [ ] Coverage collected on every CI run
- [ ] Coverage report uploaded to Codecov/Coveralls
- [ ] Coverage badge in README
- [ ] Fail CI if coverage drops >2%
- [ ] HTML coverage report artifacts

### Testing

- [ ] Coverage report generated successfully
- [ ] Coverage threshold enforced
- [ ] Reports accessible in CI artifacts
- [ ] Badge shows current coverage

---

## Implementation Details

# pytest.ini
[pytest]
addopts = --cov=src --cov-report=html --cov-report=term --cov-fail-under=66

# .github/workflows/test.yml
- run: pytest --cov --cov-report=xml
- uses: codecov/codecov-action@v3

---

## Test Strategy

Configure pytest-cov. Add to CI. Upload to coverage service. Verify reports generated.

---

## Success Metrics

- [ ] Coverage tracked in CI
- [ ] Reports accessible
- [ ] Threshold enforced
- [ ] Badge visible

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** pytest-cov, Codecov

---

## Design References

- .claude-coord/reports/test-review-20260130-223857.md#test-metrics

---

## Notes

Essential for tracking coverage progress and preventing regressions.
