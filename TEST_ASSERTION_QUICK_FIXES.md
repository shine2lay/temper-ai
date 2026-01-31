# Test Assertion Quick Fixes - Immediate Action Items

## 🎯 Quick Win Patterns (Copy-Paste Ready)

### Pattern 1: Replace `>= 1` with Exact Count

**BEFORE:**
```python
assert len(result.violations) >= 1
```

**AFTER:**
```python
assert len(result.violations) == 1, \
    f"Expected 1 violation, got {len(result.violations)}: {[v.message for v in result.violations]}"
```

---

### Pattern 2: Strengthen Violation Assertions

**BEFORE:**
```python
assert len(result.violations) >= 1
assert any("Write()" in v.message for v in result.violations)
```

**AFTER:**
```python
assert len(result.violations) == 1
assert result.violations[0].severity == ViolationSeverity.CRITICAL
assert result.violations[0].policy_name == "forbidden_operations"
assert re.search(r'Write\(\)|file_write', result.violations[0].message)
assert result.violations[0].metadata["pattern_name"] == "file_write_redirect"
assert "Write()" in result.violations[0].remediation_hint
```

---

### Pattern 3: Replace `is not None` with Structure Validation

**BEFORE:**
```python
assert result is not None
```

**AFTER:**
```python
assert result is not None, "Result should not be None"
assert isinstance(result, dict), f"Expected dict, got {type(result)}"
assert "output" in result, "Missing 'output' field"
assert len(result["output"]) > 0, "Output is empty"
```

---

### Pattern 4: Replace `any()` with Specific Item Extraction

**BEFORE:**
```python
assert any("password" in v.message.lower() for v in result.violations)
```

**AFTER:**
```python
password_violations = [v for v in result.violations
                       if re.search(r'\bpassword\b', v.message, re.IGNORECASE)]
assert len(password_violations) == 1, \
    f"Expected 1 password violation, got {len(password_violations)}"
assert password_violations[0].severity >= ViolationSeverity.HIGH
assert password_violations[0].metadata["credential_type"] == "password"
```

---

### Pattern 5: Multiple Violations with Type Checking

**BEFORE:**
```python
assert len(result.violations) >= 2
```

**AFTER:**
```python
assert len(result.violations) == 2, \
    f"Expected 2 violations (file write + dangerous command), got {len(result.violations)}"

violations_by_category = {}
for v in result.violations:
    category = v.metadata.get("category", "unknown")
    violations_by_category[category] = v

assert "file_write" in violations_by_category, "Missing file write violation"
assert "dangerous" in violations_by_category, "Missing dangerous command violation"

assert violations_by_category["file_write"].severity == ViolationSeverity.CRITICAL
assert violations_by_category["dangerous"].severity == ViolationSeverity.CRITICAL
```

---

### Pattern 6: Secret Detection Assertions

**BEFORE:**
```python
assert len(result.violations) >= 3
```

**AFTER:**
```python
assert len(result.violations) == 3, \
    f"Expected 3 secrets (AWS, GitHub, Private Key), got {len(result.violations)}"

secret_types = {v.metadata.get("secret_type") for v in result.violations}
assert secret_types == {"aws_access_key", "github_token", "private_key"}, \
    f"Wrong secret types detected: {secret_types}"

# Verify severity and entropy for each
for violation in result.violations:
    assert violation.severity >= ViolationSeverity.HIGH
    assert violation.metadata.get("entropy", 0) > 3.5, \
        f"Secret {violation.metadata['secret_type']} has low entropy"
```

---

### Pattern 7: Rate Limiting Assertions

**BEFORE:**
```python
assert len(rate_limited) >= 1
```

**AFTER:**
```python
assert len(rate_limited) >= 1, "Expected rate limiting to trigger"

# Verify each rate-limited request has proper metadata
for req in rate_limited:
    assert req.error is not None
    assert "rate limit" in req.error.lower()
    assert req.metadata.get("retry_after") > 0, \
        f"Missing retry_after for rate-limited request: {req.id}"
    assert req.status_code == 429
```

---

### Pattern 8: Tool Execution Assertions

**BEFORE:**
```python
assert len(response.tool_calls) >= 1
```

**AFTER:**
```python
assert len(response.tool_calls) == 1, \
    f"Expected 1 tool call, got {len(response.tool_calls)}"

tool_call = response.tool_calls[0]
assert tool_call.tool_name == "calculator"
assert tool_call.status == "success"
assert "result" in tool_call.output
assert isinstance(tool_call.output["result"], (int, float))
```

---

### Pattern 9: Blast Radius Assertions

**BEFORE:**
```python
assert len(result.violations) >= 1
```

**AFTER:**
```python
assert len(result.violations) == 1, \
    f"Expected 1 blast radius violation, got {len(result.violations)}"

violation = result.violations[0]
assert violation.severity == ViolationSeverity.HIGH
assert violation.policy_name == "blast_radius"

# Verify the limit was actually exceeded
assert violation.metadata["files_affected"] > violation.metadata["max_files"], \
    f"Files: {violation.metadata['files_affected']} should exceed max: {violation.metadata['max_files']}"

# Verify message shows the numbers
assert f"{violation.metadata['files_affected']} > {violation.metadata['max_files']}" in violation.message
```

---

### Pattern 10: Boolean Comparisons

**BEFORE:**
```python
assert result.success == True
assert buffer.auto_flush == False
```

**AFTER:**
```python
assert result.success is True, f"Operation failed: {result.error}"
assert buffer.auto_flush is False, "Auto-flush should be disabled"
```

---

## 🔥 Top 5 Files to Fix First (Ordered by Impact)

### 1. tests/safety/test_forbidden_operations.py
- Lines: 33, 291, 655, 678
- Impact: CRITICAL - Core security policy
- Estimated time: 30 minutes

### 2. tests/safety/test_file_access.py
- Lines: 279, 291, 317, 352, 436, 499, 561
- Impact: CRITICAL - Path traversal security
- Estimated time: 45 minutes

### 3. tests/safety/test_secret_detection.py
- Lines: 731, 877, 420, 429, 437, 445
- Impact: CRITICAL - Secret exposure
- Estimated time: 40 minutes

### 4. tests/test_security/test_llm_security.py
- Lines: 361, 395, 417, 432
- Impact: HIGH - LLM security
- Estimated time: 30 minutes

### 5. tests/test_safety/test_safety_policies.py
- Lines: 166, 180, 192, 204, 306
- Impact: HIGH - Policy framework
- Estimated time: 35 minutes

**Total estimated time for critical fixes: ~3 hours**

---

## 📋 Search & Replace Commands

### Find all >= comparisons
```bash
rg "assert len\([^)]+\) >=" tests/
```

### Find all weak is not None checks
```bash
rg "assert \w+ is not None$" tests/
```

### Find all weak any() assertions
```bash
rg "assert any\(" tests/
```

### Find all >= 1 patterns
```bash
rg ">= 1[^0-9]" tests/
```

---

## ✅ Validation Checklist

After fixing each file, verify:

- [ ] Exact counts used instead of >= comparisons
- [ ] All violation fields checked (severity, policy_name, message, metadata)
- [ ] Error messages include debugging context (actual vs expected)
- [ ] Regex used for pattern matching where appropriate
- [ ] Test still passes after strengthening
- [ ] Test fails appropriately when assertions violated

---

## 🚀 One-Liner Fixes (Safest Changes)

These can be applied immediately with minimal risk:

```python
# Change 1: Add error messages to length assertions
- assert len(violations) >= 1
+ assert len(violations) >= 1, f"Expected violations, got none. Context: {context}"

# Change 2: Add field validation to not None checks
- assert result is not None
+ assert result is not None and len(result) > 0, f"Expected non-empty result"

# Change 3: Use is True/False instead of == True/False
- assert value == True
+ assert value is True

# Change 4: Add severity check to violation assertions
- assert len(result.violations) >= 1
+ assert len(result.violations) >= 1 and any(v.severity >= ViolationSeverity.HIGH for v in result.violations)
```

---

## 📊 Progress Tracking

Track your fixes here:

```
Critical Files (Priority 1):
[ ] test_forbidden_operations.py (4 fixes)
[ ] test_file_access.py (7 fixes)
[ ] test_secret_detection.py (6 fixes)
[ ] test_llm_security.py (4 fixes)
[ ] test_safety_policies.py (5 fixes)

High Priority Files (Priority 2):
[ ] test_rate_limit_policy.py (1 fix)
[ ] test_resource_limit_policy.py (2 fixes)
[ ] test_blast_radius.py (1 fix)

Medium Priority Files (Priority 3):
[ ] test_database.py (1 fix)
[ ] test_distributed_tracking.py (2 fixes)
[ ] test_visualize_trace.py (2 fixes)
```

---

**Next Steps**: Start with `tests/safety/test_forbidden_operations.py` and use the patterns above!
