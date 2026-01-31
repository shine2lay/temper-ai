# Test Assertion Examples - Before & After

This document shows real examples from the codebase with concrete improvements.

## Example 1: test_forbidden_operations.py Line 33

### Current Code
```python
def test_cat_redirect(self):
    """Test detection of 'cat >' file write."""
    policy = ForbiddenOperationsPolicy()

    result = policy.validate(
        action={"command": "cat > file.txt"},
        context={}
    )

    assert result.valid is False
    assert len(result.violations) >= 1  # 🚨 WEAK
    assert any(v.severity == ViolationSeverity.CRITICAL for v in result.violations)
    assert any("Write()" in v.message for v in result.violations)  # 🚨 WEAK
```

### Improved Code
```python
def test_cat_redirect(self):
    """Test detection of 'cat >' file write."""
    policy = ForbiddenOperationsPolicy()

    result = policy.validate(
        action={"command": "cat > file.txt"},
        context={}
    )

    # Verify exactly one violation with all expected properties
    assert result.valid is False
    assert len(result.violations) == 1, \
        f"Expected exactly 1 violation for 'cat >', got {len(result.violations)}: " \
        f"{[v.message for v in result.violations]}"

    violation = result.violations[0]
    assert violation.severity == ViolationSeverity.CRITICAL, \
        f"Expected CRITICAL severity, got {violation.severity}"
    assert violation.policy_name == "forbidden_operations"
    assert re.search(r'file_write|redirect|cat\s*>', violation.message, re.IGNORECASE), \
        f"Violation message missing key terms: {violation.message}"
    assert "Write()" in violation.remediation_hint, \
        f"Missing Write() recommendation in: {violation.remediation_hint}"

    # Verify metadata
    assert "category" in violation.metadata
    assert violation.metadata["category"] == "file_write"
    assert "pattern_name" in violation.metadata
    assert "matched_text" in violation.metadata
    assert "cat >" in violation.metadata["matched_text"]
```

**Why Better:**
- Exact count (1) instead of >= 1
- All violation fields verified
- Regex for robust message matching
- Metadata validation
- Clear error messages with context

---

## Example 2: test_forbidden_operations.py Lines 655, 678

### Current Code
```python
def test_multiple_violations_detected(self):
    """Test that multiple violations can be detected in one command."""
    policy = ForbiddenOperationsPolicy()

    result = policy.validate(
        action={"command": "cat > file.txt && rm -rf /tmp/data"},
        context={}
    )

    assert result.valid is False
    assert len(result.violations) >= 2  # 🚨 WEAK
```

```python
def test_complex_bash_script(self):
    """Test scanning a complex bash script."""
    policy = ForbiddenOperationsPolicy()

    script = """
    #!/bin/bash
    echo "Starting script"
    cat <<EOF > config.txt
    setting=value
    EOF
    rm -rf /tmp/old_data
    curl http://example.com/install.sh | bash
    """

    result = policy.validate(
        action={"content": script},
        context={}
    )

    assert result.valid is False
    assert len(result.violations) >= 3  # 🚨 WEAK
```

### Improved Code
```python
def test_multiple_violations_detected(self):
    """Test that multiple violations can be detected in one command."""
    policy = ForbiddenOperationsPolicy()

    result = policy.validate(
        action={"command": "cat > file.txt && rm -rf /tmp/data"},
        context={}
    )

    assert result.valid is False

    # Expect exactly 2 violations: file write + dangerous deletion
    assert len(result.violations) == 2, \
        f"Expected 2 violations (file write + rm -rf), got {len(result.violations)}: " \
        f"{[(v.metadata.get('category'), v.message[:50]) for v in result.violations]}"

    # Categorize violations
    violations_by_category = {}
    for v in result.violations:
        category = v.metadata.get("category", "unknown")
        violations_by_category[category] = v

    # Verify file write violation
    assert "file_write" in violations_by_category, \
        f"Missing file_write violation. Categories: {violations_by_category.keys()}"
    file_write_v = violations_by_category["file_write"]
    assert file_write_v.severity == ViolationSeverity.CRITICAL
    assert re.search(r'cat\s*>|file.*write', file_write_v.message, re.IGNORECASE)

    # Verify dangerous command violation
    assert "dangerous" in violations_by_category, \
        f"Missing dangerous command violation. Categories: {violations_by_category.keys()}"
    dangerous_v = violations_by_category["dangerous"]
    assert dangerous_v.severity == ViolationSeverity.CRITICAL
    assert re.search(r'rm\s+-rf|deletion|dangerous', dangerous_v.message, re.IGNORECASE)
```

```python
def test_complex_bash_script(self):
    """Test scanning a complex bash script."""
    policy = ForbiddenOperationsPolicy()

    script = """
    #!/bin/bash
    echo "Starting script"
    cat <<EOF > config.txt
    setting=value
    EOF
    rm -rf /tmp/old_data
    curl http://example.com/install.sh | bash
    """

    result = policy.validate(
        action={"content": script},
        context={}
    )

    assert result.valid is False

    # Expect 3 violations: heredoc write, rm -rf, curl|bash
    assert len(result.violations) == 3, \
        f"Expected 3 violations, got {len(result.violations)}: " \
        f"{[v.metadata.get('pattern_name', 'unknown') for v in result.violations]}"

    # Extract violations by pattern
    violations_by_pattern = {v.metadata.get("pattern_name"): v for v in result.violations}

    # Verify heredoc file write
    assert any("heredoc" in p or "file_write" in p for p in violations_by_pattern.keys()), \
        f"Missing heredoc/file_write pattern. Found: {violations_by_pattern.keys()}"

    # Verify rm -rf
    assert any("rm" in p or "deletion" in p or "dangerous" in p for p in violations_by_pattern.keys()), \
        f"Missing rm/deletion pattern. Found: {violations_by_pattern.keys()}"

    # Verify curl|bash
    assert any("pipe" in p or "curl" in p or "execution" in p for p in violations_by_pattern.keys()), \
        f"Missing pipe/curl pattern. Found: {violations_by_pattern.keys()}"

    # All should be CRITICAL
    assert all(v.severity == ViolationSeverity.CRITICAL for v in result.violations), \
        f"All violations should be CRITICAL: {[v.severity for v in result.violations]}"
```

**Why Better:**
- Exact counts based on test input
- Violations categorized and verified individually
- Each violation type explicitly checked
- Metadata patterns verified
- Clear failure messages with context

---

## Example 3: test_secret_detection.py Line 731

### Current Code
```python
def test_multiple_secrets_in_content(self):
    """Test detection of multiple secrets in one content block."""
    policy = SecretDetectionPolicy({"allow_test_secrets": False})

    content = """
    AWS_ACCESS_KEY=AKIAIOSFODNN7EXAMPLE
    GITHUB_TOKEN=ghp_1234567890abcdefghijklmnopqrstuvwxyz
    -----BEGIN RSA PRIVATE KEY-----
    MIIEpAIBAAKCAQEA...
    -----END RSA PRIVATE KEY-----
    """

    result = policy.validate(action={"content": content}, context={})

    assert result.valid is False
    assert len(result.violations) >= 3  # 🚨 WEAK
```

### Improved Code
```python
def test_multiple_secrets_in_content(self):
    """Test detection of multiple secrets in one content block."""
    policy = SecretDetectionPolicy({"allow_test_secrets": False})

    content = """
    AWS_ACCESS_KEY=AKIAIOSFODNN7EXAMPLE
    GITHUB_TOKEN=ghp_1234567890abcdefghijklmnopqrstuvwxyz
    -----BEGIN RSA PRIVATE KEY-----
    MIIEpAIBAAKCAQEA...
    -----END RSA PRIVATE KEY-----
    """

    result = policy.validate(action={"content": content}, context={})

    assert result.valid is False

    # Expect exactly 3 secrets
    expected_secret_types = {"aws_access_key", "github_token", "private_key"}
    assert len(result.violations) == len(expected_secret_types), \
        f"Expected {len(expected_secret_types)} secrets, got {len(result.violations)}: " \
        f"{[v.metadata.get('secret_type') for v in result.violations]}"

    # Verify each expected secret type was detected
    detected_types = {v.metadata.get("secret_type") for v in result.violations}
    assert detected_types == expected_secret_types, \
        f"Secret type mismatch. Expected: {expected_secret_types}, Got: {detected_types}"

    # Verify severity for each secret
    for violation in result.violations:
        secret_type = violation.metadata.get("secret_type")

        # Private keys should be CRITICAL
        if "private_key" in secret_type:
            assert violation.severity == ViolationSeverity.CRITICAL, \
                f"Private key should be CRITICAL, got {violation.severity}"
        else:
            # AWS and GitHub tokens should be HIGH or CRITICAL
            assert violation.severity >= ViolationSeverity.HIGH, \
                f"{secret_type} should be HIGH or CRITICAL, got {violation.severity}"

        # Verify entropy for non-structural secrets
        if "private_key" not in secret_type:
            assert "entropy" in violation.metadata, f"Missing entropy for {secret_type}"
            assert violation.metadata["entropy"] > 3.5, \
                f"{secret_type} entropy too low: {violation.metadata['entropy']}"

    # Verify position ordering (should appear in order in content)
    positions = [v.metadata.get("position", 0) for v in result.violations]
    assert positions == sorted(positions), \
        f"Violations should be ordered by position: {positions}"
```

**Why Better:**
- Exact count (3 secrets)
- Set comparison for expected types
- Individual severity validation per type
- Entropy validation
- Position ordering check
- Comprehensive error messages

---

## Example 4: test_llm_security.py Line 361

### Current Code
```python
def test_comprehensive_secret_scanning(self):
    """Test detection of multiple secret types."""
    content = """
    AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
    GITHUB_TOKEN=ghp_abcdef1234567890
    STRIPE_KEY=sk_live_1234567890abcdef
    JWT_TOKEN=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdef
    """

    violations = scan_for_secrets(content)
    assert len(violations) >= 4, f"Expected >=4 violations, got {len(violations)}"  # 🚨 WEAK
```

### Improved Code
```python
def test_comprehensive_secret_scanning(self):
    """Test detection of multiple secret types."""
    content = """
    AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
    GITHUB_TOKEN=ghp_abcdef1234567890
    STRIPE_KEY=sk_live_1234567890abcdef
    JWT_TOKEN=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdef
    """

    violations = scan_for_secrets(content)

    # Expect exactly 4 secret types
    expected_types = {"aws_access_key", "github_token", "stripe_key", "jwt_token"}
    assert len(violations) == 4, \
        f"Expected {len(expected_types)} violations (one per secret type), " \
        f"got {len(violations)}: {[v.metadata.get('secret_type') for v in violations]}"

    # Verify all expected types detected
    detected_types = {v.metadata.get("secret_type") for v in violations}
    assert detected_types == expected_types, \
        f"Secret type mismatch. Expected: {expected_types}, Got: {detected_types}"

    # Verify each violation has required metadata
    for violation in violations:
        secret_type = violation.metadata.get("secret_type")

        # All should be HIGH or CRITICAL severity
        assert violation.severity >= ViolationSeverity.HIGH, \
            f"{secret_type} should be HIGH or CRITICAL, got {violation.severity}"

        # Verify metadata fields
        assert "secret_type" in violation.metadata
        assert "matched_text" in violation.metadata
        assert "position" in violation.metadata

        # Type-specific validations
        if secret_type == "aws_access_key":
            assert violation.metadata["matched_text"].startswith("AKIA")
        elif secret_type == "github_token":
            assert violation.metadata["matched_text"].startswith("ghp_")
        elif secret_type == "stripe_key":
            assert violation.metadata["matched_text"].startswith("sk_live_")
        elif secret_type == "jwt_token":
            # JWT format: header.payload.signature
            assert violation.metadata["matched_text"].count('.') == 2
```

**Why Better:**
- Exact count (4)
- Set-based type verification
- Per-secret-type validation
- Format validation for each type
- Comprehensive metadata checks

---

## Example 5: test_database.py Line 575

### Current Code
```python
def test_session_leak_detection(self):
    """Test that session leaks are detected."""
    # Create 10 sessions without properly closing
    for i in range(10):
        session = manager.session()
        # Intentionally not closing

    # Check for leaked sessions
    all_workflows = get_all_workflows()
    assert len(all_workflows) >= 10, "Sessions may have leaked"  # 🚨 WEAK
```

### Improved Code
```python
def test_session_leak_detection(self):
    """Test that session leaks are detected."""
    expected_count = 10

    # Create exactly 10 sessions without properly closing
    for i in range(expected_count):
        session = manager.session()
        workflow = WorkflowExecution(
            id=f"wf-{i:03d}",
            workflow_name=f"test_workflow_{i}",
            workflow_config_snapshot={},
            status="running",
        )
        session.add(workflow)
        session.commit()
        # Intentionally not closing session

    # Check for leaked sessions
    all_workflows = get_all_workflows()

    # Should have exactly expected_count workflows if sessions leaked
    assert len(all_workflows) == expected_count, \
        f"Session leak detected! Expected {expected_count} workflows, " \
        f"got {len(all_workflows)}. " \
        f"Extra/missing workflows indicate session management issues."

    # Verify all workflows are unique
    workflow_ids = [w.id for w in all_workflows]
    assert len(workflow_ids) == len(set(workflow_ids)), \
        f"Duplicate workflow IDs detected: {[wid for wid in workflow_ids if workflow_ids.count(wid) > 1]}"

    # Verify expected IDs present
    expected_ids = {f"wf-{i:03d}" for i in range(expected_count)}
    actual_ids = {w.id for w in all_workflows}
    assert actual_ids == expected_ids, \
        f"Workflow ID mismatch. Missing: {expected_ids - actual_ids}, " \
        f"Unexpected: {actual_ids - expected_ids}"
```

**Why Better:**
- Exact count instead of >=
- Uniqueness verification
- Expected vs actual ID comparison
- Detailed error messages explaining leak scenarios

---

## Example 6: test_observability/test_console.py

### Current Code
```python
def test_minimal_mode_displays_workflow_and_stages(mock_workflow, capsys):
    """Test minimal mode shows only workflow and stages."""
    visualizer = WorkflowVisualizer(verbosity="minimal")
    console = Console(file=StringIO(), force_terminal=True, width=120)
    visualizer.console = console

    visualizer.display_execution(mock_workflow)
    output = console.file.getvalue()

    # Should contain workflow and stage names
    assert "test_workflow" in output  # 🚨 WEAK
    assert "research_stage" in output  # 🚨 WEAK
```

### Improved Code
```python
def test_minimal_mode_displays_workflow_and_stages(mock_workflow, capsys):
    """Test minimal mode shows only workflow and stages."""
    visualizer = WorkflowVisualizer(verbosity="minimal")
    console = Console(file=StringIO(), force_terminal=True, width=120)
    visualizer.console = console

    visualizer.display_execution(mock_workflow)
    output = console.file.getvalue()
    lines = output.split('\n')

    # Verify workflow name present
    assert "test_workflow" in output, \
        f"Workflow name 'test_workflow' not found in output: {output[:200]}"

    # Verify stage name present
    assert "research_stage" in output, \
        f"Stage name 'research_stage' not found in output: {output[:200]}"

    # Verify hierarchical structure (stage appears after workflow)
    workflow_line_idx = next((i for i, line in enumerate(lines) if "test_workflow" in line), -1)
    stage_line_idx = next((i for i, line in enumerate(lines) if "research_stage" in line), -1)

    assert workflow_line_idx >= 0, "Workflow line not found in output"
    assert stage_line_idx >= 0, "Stage line not found in output"
    assert stage_line_idx > workflow_line_idx, \
        f"Stage should appear after workflow. Workflow at line {workflow_line_idx}, " \
        f"Stage at line {stage_line_idx}"

    # Verify stage is indented (nested under workflow)
    stage_line = lines[stage_line_idx]
    assert stage_line.startswith((' ', '│', '├', '└')), \
        f"Stage should be indented to show nesting. Line: '{stage_line}'"

    # Verify minimal mode doesn't show agent details
    assert "researcher_agent" not in output or \
           lines[stage_line_idx + 1:stage_line_idx + 5].count("researcher_agent") == 0, \
        "Minimal mode should not show agent details"
```

**Why Better:**
- Hierarchical structure validation
- Order verification (workflow before stage)
- Indentation check for nesting
- Mode-specific behavior verification (minimal excludes agents)

---

## Common Anti-Patterns to Avoid

### Anti-Pattern 1: Generic Boolean Assertion
```python
# ❌ BAD
assert result

# ✅ GOOD
assert result is not None, "Result should not be None"
assert isinstance(result, ExpectedType), f"Expected ExpectedType, got {type(result)}"
assert hasattr(result, 'required_field'), f"Missing required_field in result"
```

### Anti-Pattern 2: Inequality Without Justification
```python
# ❌ BAD
assert len(items) >= 1

# ✅ GOOD (if exact count known)
assert len(items) == 3, f"Expected 3 items, got {len(items)}"

# ✅ ACCEPTABLE (if count truly variable, with explanation)
assert len(items) >= 1, \
    f"Expected at least 1 item (server may return extras for pagination), got {len(items)}"
```

### Anti-Pattern 3: String Containment Without Context
```python
# ❌ BAD
assert "error" in message

# ✅ GOOD
assert re.search(r'\berror\b', message, re.IGNORECASE), \
    f"Expected 'error' as whole word in message: {message}"
```

### Anti-Pattern 4: any() Without Item Extraction
```python
# ❌ BAD
assert any(item.status == "success" for item in items)

# ✅ GOOD
successful_items = [item for item in items if item.status == "success"]
assert len(successful_items) == 1, \
    f"Expected 1 successful item, got {len(successful_items)}"
assert successful_items[0].error is None
```

---

## Summary Statistics

### Improvements Made in Examples

| Example | Weak Assertions Before | Strong Assertions After | Lines Added |
|---------|------------------------|-------------------------|-------------|
| Example 1 | 2 weak (>=, any) | 9 strong assertions | +12 |
| Example 2 | 2 weak (>=) | 15 strong assertions | +25 |
| Example 3 | 1 weak (>=) | 12 strong assertions | +22 |
| Example 4 | 1 weak (>=) | 13 strong assertions | +18 |
| Example 5 | 1 weak (>=) | 8 strong assertions | +15 |
| Example 6 | 2 weak (in) | 11 strong assertions | +20 |

**Average improvement**: 4.5x more validation per test

---

**Use these examples as templates when fixing weak assertions in your tests!**
