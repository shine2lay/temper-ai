# Task: test-regression-suite - Regression Test Framework

**Priority:** MEDIUM
**Effort:** 2-3 days
**Status:** pending
**Owner:** unassigned

---

## Summary
Create regression test suite to prevent known bugs from reappearing.

---

## Files to Create
- `tests/regression/test_config_loading_regression.py` - Config bugs
- `tests/regression/test_tool_execution_regression.py` - Tool bugs
- `tests/regression/test_integration_regression.py` - Integration bugs
- `tests/regression/test_performance_regression.py` - Performance regressions

---

## Acceptance Criteria

### Regression Tests
- [ ] Test for config loading bugs (from 22 failures)
- [ ] Test for tool execution bugs (from 4 failures)
- [ ] Test for integration bugs (from 9 failures)
- [ ] Performance regression benchmarks
- [ ] Memory leak regression tests

### Framework
- [ ] Regression tests run in CI
- [ ] Performance benchmarks have baselines
- [ ] Tests document the original bug
- [ ] Tests link to issue/PR that fixed bug

### Testing
- [ ] 25 regression tests implemented
- [ ] All current failures covered
- [ ] Performance baselines established

---

## Implementation Details

```python
# tests/regression/test_config_loading_regression.py

class TestConfigLoadingRegression:
    """Regression tests for config loading bugs."""
    
    def test_env_var_substitution_regression(self):
        """
        Regression test for environment variable substitution.
        
        Bug: Environment variables with ${VAR} syntax not expanding.
        Fixed in: PR #XXX
        Affects: 6 tests in test_config_loader.py
        """
        config_yaml = """
agent:
  name: "${TEST_AGENT_NAME}"
  model: "${MODEL:-llama3.2:3b}"
"""
        # Test passes after fix
        pass
```

```python
# tests/regression/test_performance_regression.py

import pytest
import time

class TestPerformanceRegression:
    """Performance regression tests."""
    
    def test_consensus_performance_baseline(self):
        """Test consensus synthesis completes in <10ms."""
        strategy = ConsensusStrategy()
        outputs = create_test_outputs(count=5)
        
        start = time.time()
        result = strategy.synthesize(outputs, {})
        elapsed = time.time() - start
        
        # Baseline: should be <10ms
        assert elapsed < 0.010, f"Regression! Took {elapsed*1000:.2f}ms"
```

---

## Success Metrics
- [ ] 25 regression tests implemented
- [ ] All known bugs covered
- [ ] Performance baselines established
- [ ] Tests prevent bug reoccurrence

---

## Dependencies
- **Blocked by:** test-fix-failures-01, 02, 03, 04
- **Blocks:** None

---

## Design References
- TDD Architect Report: Regression Test Scenarios
- QA Engineer Report: All failing tests

