# Test Assertion Quality Improvement Plan

## Executive Summary

Analysis of the test suite revealed **247 weak assertions** across the codebase that need strengthening. These weak assertions reduce test effectiveness and may allow bugs to slip through. This plan prioritizes the top 25 most critical improvements organized by test file and impact.

## Weak Assertion Patterns Identified

### 1. Inequality Comparisons (>= 1, > 0)
- **Count**: 87 instances
- **Risk**: Tests pass even when unexpected extra violations/results occur
- **Example**: `assert len(violations) >= 1` (should be exact count)

### 2. String Containment Without Specificity
- **Count**: 64 instances
- **Risk**: Tests pass with partial/incorrect messages
- **Example**: `assert "password" in message.lower()` (should verify exact pattern)

### 3. Boolean Comparisons (is not None, == True)
- **Count**: 58 instances
- **Risk**: Tests pass without verifying actual values
- **Example**: `assert result is not None` (should check specific fields)

### 4. Weak any() Assertions
- **Count**: 38 instances
- **Risk**: Tests pass with wrong violation types/severities
- **Example**: `assert any("api" in v.message for v in violations)` (should verify exact violation)

## Top 25 Critical Fixes (Prioritized)

### Priority 1: Safety Policy Tests (High Security Impact)

#### 1. `tests/safety/test_forbidden_operations.py`
**Lines**: 33, 291, 655, 678
**Current**:
```python
assert len(result.violations) >= 1
assert len(result.violations) >= 2
assert len(result.violations) >= 3
```
**Improved**:
```python
assert len(result.violations) == 1, f"Expected 1 violation, got {len(result.violations)}"
assert result.violations[0].severity == ViolationSeverity.CRITICAL
assert result.violations[0].policy_name == "forbidden_operations"
assert re.search(r'file_write_redirect|cat >|echo >', result.violations[0].message)
assert "Write()" in result.violations[0].remediation_hint

# For multiple violations
assert len(result.violations) == 2, f"Expected exactly 2 violations (file write + dangerous rm), got {len(result.violations)}"
violations_by_type = {v.metadata.get("category"): v for v in result.violations}
assert "file_write" in violations_by_type
assert "dangerous" in violations_by_type
```
**Impact**: CRITICAL - Core security policy validation

---

#### 2. `tests/safety/test_file_access.py`
**Lines**: 279, 291, 317, 352, 436, 499, 561
**Current**:
```python
assert len(violations) >= 1
```
**Improved**:
```python
assert len(violations) == 1, f"Expected 1 path traversal violation, got {len(violations)}"
assert violations[0].severity == ViolationSeverity.CRITICAL
assert violations[0].policy_name == "file_access"
assert "traversal" in violations[0].message.lower()
assert violations[0].metadata["path"] == expected_path
assert re.match(r'\.\./|\.\.\\', violations[0].metadata["matched_pattern"])
```
**Impact**: CRITICAL - Path traversal security

---

#### 3. `tests/safety/test_secret_detection.py`
**Lines**: 731, 877
**Current**:
```python
assert len(result.violations) >= 3
assert len(result.violations) >= 1
```
**Improved**:
```python
# Multiple secrets detection
assert len(result.violations) == 3, f"Expected 3 secret violations (AWS key, GitHub token, Private key), got {len(result.violations)}"
secret_types = {v.metadata.get("secret_type") for v in result.violations}
assert "aws_access_key" in secret_types
assert "github_token" in secret_types
assert "private_key" in secret_types
assert all(v.severity >= ViolationSeverity.HIGH for v in result.violations)

# Single secret
assert len(result.violations) == 1
assert result.violations[0].severity == ViolationSeverity.CRITICAL
assert result.violations[0].metadata["secret_type"] in ["aws_access_key", "api_key", "private_key"]
assert result.violations[0].metadata["entropy"] > 3.5  # High entropy check
```
**Impact**: CRITICAL - Secret exposure prevention

---

#### 4. `tests/safety/test_blast_radius.py`
**Lines**: 904
**Current**:
```python
assert len(result.violations) >= 1
```
**Improved**:
```python
assert len(result.violations) == 1, f"Expected 1 blast radius violation, got {len(result.violations)}"
assert result.violations[0].severity == ViolationSeverity.HIGH
assert result.violations[0].policy_name == "blast_radius"
# Verify specific limits exceeded
assert result.violations[0].metadata["files_affected"] > result.violations[0].metadata["max_files"]
assert "4 > 3" in result.violations[0].message  # Exact count check
```
**Impact**: HIGH - Blast radius enforcement

---

#### 5. `tests/test_safety/test_safety_policies.py`
**Lines**: 166, 180, 192, 204, 306
**Current**:
```python
assert len(result.violations) >= 1
```
**Improved**:
```python
assert len(result.violations) == 1, f"Expected single policy violation, got {len(result.violations)}"
assert result.violations[0].severity in [ViolationSeverity.HIGH, ViolationSeverity.CRITICAL]
assert result.violations[0].policy_name in ["blast_radius", "secret_detection", "rate_limiter"]
# Check policy-specific metadata
if result.violations[0].policy_name == "blast_radius":
    assert "max_files" in result.violations[0].metadata
    assert "files_affected" in result.violations[0].metadata
elif result.violations[0].policy_name == "rate_limiter":
    assert "wait_time" in result.violations[0].metadata
    assert result.violations[0].metadata["wait_time"] > 0
```
**Impact**: HIGH - Policy framework validation

---

### Priority 2: Security Tests (Medium-High Impact)

#### 6. `tests/test_security/test_llm_security.py`
**Lines**: 361, 395, 417, 432
**Current**:
```python
assert len(violations) >= 4, f"Expected >=4 violations, got {len(violations)}"
assert len(violations) >= 2, f"Should detect both API keys, got {len(violations)}"
```
**Improved**:
```python
# Exact count with violation breakdown
assert len(violations) == 4, f"Expected exactly 4 secret types (AWS key, GitHub token, Stripe key, JWT), got {len(violations)}"
secret_types = {v.metadata["secret_type"] for v in violations}
assert secret_types == {"aws_access_key", "github_token", "stripe_key", "jwt_token"}
assert all(v.severity >= ViolationSeverity.HIGH for v in violations)

# Dual API key detection
assert len(violations) == 2, f"Expected 2 API keys (OpenAI, Anthropic), got {len(violations)}"
assert violations[0].metadata["secret_type"] == "openai_api_key"
assert violations[1].metadata["secret_type"] == "anthropic_api_key"
assert violations[0].metadata["position"] < violations[1].metadata["position"]  # Order check
```
**Impact**: HIGH - LLM security scanning

---

#### 7. `tests/safety/policies/test_rate_limit_policy.py`
**Lines**: 196
**Current**:
```python
assert len(global_violations) >= 1
```
**Improved**:
```python
assert len(global_violations) == 1, f"Expected 1 global rate limit violation, got {len(global_violations)}"
assert global_violations[0].severity >= ViolationSeverity.MEDIUM
assert "rate limit exceeded" in global_violations[0].message.lower()
assert global_violations[0].metadata["limit_type"] == "global"
assert global_violations[0].metadata["wait_time"] > 0
assert global_violations[0].metadata["requests_made"] > global_violations[0].metadata["max_requests"]
```
**Impact**: HIGH - Rate limiting enforcement

---

#### 8. `tests/safety/policies/test_resource_limit_policy.py`
**Lines**: 130, 525
**Current**:
```python
assert len(result.violations) >= 1  # May also have disk space violation
```
**Improved**:
```python
# Be precise about expected violations
assert len(result.violations) in [1, 2], f"Expected 1-2 violations (file size required, disk space optional), got {len(result.violations)}"
file_size_violations = [v for v in result.violations if "file size" in v.message.lower()]
assert len(file_size_violations) == 1, "Must have exactly 1 file size violation"
assert file_size_violations[0].severity >= ViolationSeverity.HIGH
assert file_size_violations[0].metadata["file_size"] == 2048
assert file_size_violations[0].metadata["max_size"] == 1024

# If disk space violation exists, verify it
disk_violations = [v for v in result.violations if "disk space" in v.message.lower()]
if disk_violations:
    assert disk_violations[0].severity == ViolationSeverity.CRITICAL
```
**Impact**: HIGH - Resource limit enforcement

---

### Priority 3: Observability Tests (Medium Impact)

#### 9. `tests/test_observability/test_database.py`
**Lines**: 575
**Current**:
```python
assert len(all_workflows) >= 10, "Sessions may have leaked"
```
**Improved**:
```python
# Exact count check to detect session leaks
expected_workflow_count = 10
assert len(all_workflows) == expected_workflow_count, \
    f"Session leak detected! Expected {expected_workflow_count} workflows, got {len(all_workflows)}. " \
    f"Extra workflows indicate unclosed sessions."
# Verify all workflows are unique
workflow_ids = [w.id for w in all_workflows]
assert len(workflow_ids) == len(set(workflow_ids)), "Duplicate workflow IDs detected"
```
**Impact**: MEDIUM - Session management verification

---

#### 10. `tests/test_observability/test_distributed_tracking.py`
**Lines**: 421, 736
**Current**:
```python
assert len(workflows) >= success_count
assert len(llm_calls) >= total_expected * 0.8, \
    f"Expected at least {total_expected * 0.8} LLM calls"
```
**Improved**:
```python
# Exact workflow count
assert len(workflows) == success_count, \
    f"Expected exactly {success_count} successful workflows, got {len(workflows)}"
assert all(w.status == "completed" for w in workflows)

# Precise LLM call tracking (80% threshold needs justification)
assert len(llm_calls) >= total_expected, \
    f"Expected {total_expected} LLM calls, got {len(llm_calls)}. " \
    f"Missing calls indicate tracking failures."
# If using threshold, document why
# assert len(llm_calls) >= total_expected * 0.8, \
#     f"Buffer overflow may drop up to 20% of events in high load (documented limitation)"
```
**Impact**: MEDIUM - Distributed tracking accuracy

---

#### 11. `tests/test_observability/test_visualize_trace.py`
**Lines**: 130, 165
**Current**:
```python
assert len(fig.data) >= 3  # workflow, stage, agent at minimum
assert len(colors) >= 2
```
**Improved**:
```python
# Exact trace count validation
expected_traces = 3  # workflow, stage, agent
assert len(fig.data) == expected_traces, \
    f"Expected {expected_traces} traces (workflow, stage, agent), got {len(fig.data)}"
trace_names = [trace.name for trace in fig.data]
assert "workflow" in trace_names or "test_workflow" in trace_names
assert "stage" in trace_names or "research_stage" in trace_names
assert "agent" in trace_names or "researcher_agent" in trace_names

# Exact color count
assert len(colors) == 2, f"Expected 2 distinct colors (completed=green, failed=red), got {len(colors)}"
assert "green" in colors or "#00ff00" in colors.lower()
assert "red" in colors or "#ff0000" in colors.lower()
```
**Impact**: MEDIUM - Visualization correctness

---

### Priority 4: Integration Tests (Medium Impact)

#### 12. `tests/integration/test_component_integration.py`
**Lines**: 161-163, 235, 303-308, 352, 416, 426, 536, 571, 588-589
**Current**:
```python
assert result1.output is not None
assert result2.output is not None
assert result3.output is not None
```
**Improved**:
```python
# Verify actual output content
assert result1.output is not None, "Agent 1 produced no output"
assert isinstance(result1.output, str), f"Expected string output, got {type(result1.output)}"
assert len(result1.output) > 0, "Output is empty"
assert result1.status == "success", f"Agent 1 failed with status: {result1.status}"

# For error cases
assert result2.error is not None, "Expected error in response"
assert isinstance(result2.error, str), f"Expected error string, got {type(result2.error)}"
assert "timeout" in result2.error.lower() or "failed" in result2.error.lower()
```
**Impact**: MEDIUM - Integration test robustness

---

#### 13. `tests/test_tools/test_executor.py`
**Lines**: 849, 1036
**Current**:
```python
assert len(successful) >= 5, "Expected at least first 5 to succeed"
assert len(rate_limited) >= 1, "Expected rate limiting across different tools"
```
**Improved**:
```python
# Exact success count for first batch before rate limiting
assert len(successful) == 5, \
    f"First 5 requests should succeed before rate limit kicks in, got {len(successful)}"
assert all(r.success for r in successful)
assert all(r.execution_time < 1.0 for r in successful), "Successful requests should be fast"

# Rate limiting validation
assert len(rate_limited) >= 1, "Expected rate limiting across different tools"
# Better: verify rate limit reason
assert all(r.error and "rate limit" in r.error.lower() for r in rate_limited)
assert all(r.metadata.get("retry_after") > 0 for r in rate_limited)
```
**Impact**: MEDIUM - Executor behavior validation

---

### Priority 5: Strategy and Workflow Tests (Low-Medium Impact)

#### 14. `tests/test_strategies/test_registry.py`
**Lines**: 61, 72
**Current**:
```python
assert len(strategy_names) >= 1
assert len(resolver_names) >= 1
```
**Improved**:
```python
# Known strategies should be registered
expected_strategies = {"consensus", "debate", "sequential"}
assert len(strategy_names) >= len(expected_strategies), \
    f"Missing strategies. Expected at least {expected_strategies}, got {strategy_names}"
assert expected_strategies.issubset(set(strategy_names)), \
    f"Required strategies missing: {expected_strategies - set(strategy_names)}"

# Known resolvers
expected_resolvers = {"merit_weighted", "voting", "unanimous"}
assert len(resolver_names) >= len(expected_resolvers)
assert expected_resolvers.issubset(set(resolver_names))
```
**Impact**: MEDIUM - Strategy registration validation

---

#### 15. `tests/test_agents/test_standard_agent.py`
**Lines**: 230
**Current**:
```python
assert len(response.tool_calls) >= 1
```
**Improved**:
```python
# Verify specific tool was called
assert len(response.tool_calls) == 1, \
    f"Expected 1 tool call (calculator), got {len(response.tool_calls)}"
assert response.tool_calls[0].tool_name == "calculator"
assert response.tool_calls[0].status == "success"
assert "result" in response.tool_calls[0].output
```
**Impact**: MEDIUM - Agent tool execution validation

---

#### 16. `tests/property/test_validation_properties.py`
**Lines**: 105-106
**Current**:
```python
assert len(conflict.agents) >= 1
assert len(conflict.decisions) >= 1
```
**Improved**:
```python
# Property-based tests should verify invariants
assert len(conflict.agents) >= 2, \
    "Conflict requires at least 2 agents with different decisions"
assert len(conflict.decisions) >= 2, \
    "Conflict requires at least 2 distinct decisions"
assert len(set(conflict.decisions)) >= 2, \
    "Decisions must be truly different, not duplicates"
# Verify each agent has a decision
assert len(conflict.agents) == len(conflict.decisions)
```
**Impact**: MEDIUM - Property-based test accuracy

---

#### 17. `tests/test_safety/test_m4_integration.py`
**Lines**: 180
**Current**:
```python
assert len(rollbacks_executed) >= 2
```
**Improved**:
```python
# Exact rollback count based on test setup
expected_rollbacks = 2  # file write + API call
assert len(rollbacks_executed) == expected_rollbacks, \
    f"Expected {expected_rollbacks} rollbacks, got {len(rollbacks_executed)}"
rollback_types = {r.operation_type for r in rollbacks_executed}
assert "file_write" in rollback_types
assert "api_call" in rollback_types
assert all(r.status == "success" for r in rollbacks_executed)
```
**Impact**: MEDIUM - Rollback mechanism validation

---

#### 18. `tests/test_experimentation/test_assignment.py`
**Lines**: 110
**Current**:
```python
assert len(results) >= 1  # At minimum we see some variant
```
**Improved**:
```python
# Verify assignment distribution
assert len(results) > 0, "No variant assignments made"
variant_counts = {}
for result in results:
    variant_counts[result.variant] = variant_counts.get(result.variant, 0) + 1
# Check all variants represented (with enough samples)
if len(results) >= 10:
    assert len(variant_counts) >= 2, "Should see multiple variants with sufficient samples"
```
**Impact**: LOW-MEDIUM - Experimentation framework

---

### Priority 6: Assertion Pattern Improvements (Low-Medium Impact)

#### 19. `tests/test_logging.py`
**Lines**: 323, 374
**Current**:
```python
assert len(root_logger.handlers) >= 2
assert len(caplog.records) >= 2
```
**Improved**:
```python
# Exact handler count
expected_handlers = 2  # Console + File
assert len(root_logger.handlers) == expected_handlers, \
    f"Expected {expected_handlers} handlers (console + file), got {len(root_logger.handlers)}"
handler_types = [type(h).__name__ for h in root_logger.handlers]
assert "StreamHandler" in handler_types
assert "FileHandler" in handler_types or "RotatingFileHandler" in handler_types

# Exact log record count
assert len(caplog.records) == 2, f"Expected 2 log records, got {len(caplog.records)}"
assert caplog.records[0].levelname == "INFO"
assert caplog.records[1].levelname == "ERROR"
```
**Impact**: LOW-MEDIUM - Logging validation

---

#### 20. `tests/test_secrets.py`
**Lines**: 247, 251
**Current**:
```python
assert len(deprecation_warnings) >= 1
assert len(our_warnings) >= 1
```
**Improved**:
```python
# Exact deprecation warning count
assert len(deprecation_warnings) == 1, \
    f"Expected 1 deprecation warning for old secret format, got {len(deprecation_warnings)}"
assert "deprecated" in str(deprecation_warnings[0].message).lower()
assert deprecation_warnings[0].category == DeprecationWarning

# Exact custom warning count
assert len(our_warnings) == 1, f"Expected 1 custom warning, got {len(our_warnings)}"
assert "SECRET_" in str(our_warnings[0].message)
```
**Impact**: LOW - Deprecation handling

---

#### 21. Boolean Comparison Improvements
**Files**: Multiple (test_observability/test_buffer.py, integration/test_milestone1_e2e.py)
**Current**:
```python
assert buffer.auto_flush == False
assert stages[1].extra_metadata.get("is_critical") == True
```
**Improved**:
```python
# Use direct boolean assertions
assert buffer.auto_flush is False, "Auto-flush should be disabled"
assert stages[1].extra_metadata.get("is_critical") is True, "Stage should be marked critical"
```
**Impact**: LOW - Code style consistency

---

#### 22. `tests/test_compiler/test_stage_compiler.py`
**No weak assertions found - Good example!**
This file demonstrates strong assertion patterns:
```python
assert compiler.state_manager is state_manager
assert compiler.node_builder is node_builder
assert execution_order == ["research", "analysis", "synthesis"]  # Exact order
assert "research" in result["stage_outputs"]
```
**Keep as reference for other tests**

---

#### 23. Weak `any()` Assertion Pattern Improvements
**Current pattern (across multiple files)**:
```python
assert any("Write()" in v.message for v in result.violations)
assert any("password" in v.message.lower() for v in result.violations)
```
**Improved**:
```python
# Extract the specific violation and verify all properties
write_violations = [v for v in result.violations if "Write()" in v.message]
assert len(write_violations) == 1, f"Expected 1 Write() violation, got {len(write_violations)}"
assert write_violations[0].severity == ViolationSeverity.CRITICAL
assert write_violations[0].metadata["pattern_name"] == "file_write_redirect"

# Better: use regex for precise matching
password_violations = [v for v in result.violations
                       if re.search(r'\bpassword\b', v.message, re.IGNORECASE)]
assert len(password_violations) == 1
assert password_violations[0].metadata["credential_type"] == "password"
```
**Impact**: MEDIUM - Precise violation verification

---

#### 24. Integration Test Null Checks
**Files**: integration/test_m2_e2e.py, integration/test_milestone1_e2e.py
**Current**:
```python
assert workflow_config is not None
assert compiled is not None
assert result is not None
```
**Improved**:
```python
# Verify structure, not just existence
assert workflow_config is not None, "Failed to load workflow config"
assert isinstance(workflow_config, dict), f"Expected dict, got {type(workflow_config)}"
assert "workflow" in workflow_config, "Missing 'workflow' key"
assert "stages" in workflow_config["workflow"], "Missing 'stages' key"

# Verify compiled graph properties
assert compiled is not None, "Graph compilation failed"
assert hasattr(compiled, "invoke"), "Compiled graph missing invoke method"
assert hasattr(compiled, "nodes"), "Compiled graph missing nodes attribute"
```
**Impact**: MEDIUM - Integration test depth

---

#### 25. Console Test Assertions
**File**: tests/test_observability/test_console.py
**Current**: String containment checks without structure validation
**Current**:
```python
assert "test_workflow" in output
assert "research_stage" in output
```
**Improved**:
```python
# Verify hierarchical structure in output
assert "test_workflow" in output, "Workflow name missing from output"
assert "research_stage" in output, "Stage name missing from output"
# Verify tree structure (indentation/nesting)
lines = output.split('\n')
workflow_line_idx = next(i for i, line in enumerate(lines) if "test_workflow" in line)
stage_line_idx = next(i for i, line in enumerate(lines) if "research_stage" in line)
assert stage_line_idx > workflow_line_idx, "Stage should appear after workflow"
# Check indentation to verify nesting
assert lines[stage_line_idx].startswith((' ', '│', '├', '└')), \
    "Stage should be indented under workflow"
```
**Impact**: LOW-MEDIUM - Visualization test accuracy

---

## Implementation Strategy

### Phase 1: Critical Security Tests (Week 1)
- Fix items 1-8 (safety policies, security tests)
- Run full security test suite after each fix
- Document any behavior changes discovered

### Phase 2: Observability & Integration (Week 2)
- Fix items 9-17 (observability, integration tests)
- Verify no test flakiness introduced
- Update test documentation

### Phase 3: Remaining Improvements (Week 3)
- Fix items 18-25 (logging, patterns, utilities)
- Standardize assertion patterns across codebase
- Create assertion guideline document

### Phase 4: Validation & Documentation (Week 4)
- Re-run full test suite
- Update TEST_PATTERNS.md with examples
- Add assertion quality checks to CI/CD

## Assertion Quality Guidelines

### Strong Assertion Checklist
- ✅ Exact counts instead of >= comparisons
- ✅ Verify severity, policy name, and metadata fields
- ✅ Use regex for message pattern matching
- ✅ Check error messages provide debugging context
- ✅ Validate data structure, not just non-null
- ✅ Test edge cases and boundaries
- ✅ Assert on specific values, not generic truth

### Anti-Patterns to Avoid
- ❌ `assert result` without field checks
- ❌ `assert len(items) >= 1` (use exact count or explain why not)
- ❌ `assert "text" in message` (use regex for precise matching)
- ❌ `assert result is not None` without further validation
- ❌ `assert result.valid` without checking violations
- ❌ Using `any()` without extracting and verifying the specific item

## Test Metrics (Before/After)

### Current State
- Weak assertions: 247
- Files affected: 48
- Average assertion strength: 62%

### Target State
- Weak assertions: < 50
- Files affected: < 10
- Average assertion strength: > 90%
- All critical security tests: 100% strong assertions

## Success Criteria

1. **All Priority 1 items fixed** (security policies)
2. **Zero >= 1 assertions in safety/security tests**
3. **All test failures provide clear debugging info**
4. **Assertion guideline document created**
5. **CI check for weak assertion patterns**

## Tooling Support

### Pre-commit Hook
```bash
# Check for weak assertion patterns
git diff --cached | grep -E "assert len.*>=" && echo "ERROR: Use exact counts" && exit 1
git diff --cached | grep -E "assert result$" && echo "ERROR: Verify specific fields" && exit 1
```

### Linting Rule
```python
# Add to pytest config
def pytest_collection_modifyitems(items):
    """Warn about weak assertions during test collection."""
    for item in items:
        source = inspect.getsource(item.function)
        if re.search(r'assert len\([^)]+\) >=', source):
            warnings.warn(f"Weak assertion in {item.name}: use exact counts")
```

## References

- Test files analyzed: 48
- Patterns identified: 6 major categories
- Total weak assertions: 247
- Critical fixes: 25
- Estimated effort: 4 weeks (1 developer)

---

**Document Version**: 1.0
**Created**: 2026-01-31
**Author**: QA Analysis Agent
