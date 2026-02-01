# Task Specification: code-crit-redos-regex-05

## Problem Statement

Regex pattern `[A-Za-z0-9+/]{40,500}={0,2}` for Base64 detection can cause catastrophic backtracking (ReDoS - Regular Expression Denial of Service) with specially crafted input. An attacker can hang the application by providing malicious input that causes exponential regex matching time.

For example, a string of 500+ valid Base64 characters followed by an invalid character can cause seconds or minutes of CPU time.

## Context

- **Source:** Code Review Report 2026-02-01 (Critical Issue #5)
- **File Affected:** `src/tools/web_scraper.py:408`
- **Impact:** Denial of service, application hangs, CPU exhaustion
- **Module:** Tools
- **OWASP Category:** A03:2021 - Injection (ReDoS)
- **CWE:** CWE-1333: Inefficient Regular Expression Complexity

## Acceptance Criteria

### CORE FUNCTIONALITY
- [ ] Reduce regex upper bound from 500 to safe limit (≤100)
- [ ] Maintain Base64 detection functionality
- [ ] Prevent catastrophic backtracking
- [ ] Ensure regex completes in O(n) time, not O(2^n)

### SECURITY CONTROLS
- [ ] ReDoS attack is prevented
- [ ] Input validation limits string length before regex
- [ ] Timeout protection for regex matching (defense in depth)
- [ ] Log potential ReDoS attempts

### PERFORMANCE
- [ ] Regex matching completes in <10ms for typical inputs
- [ ] No performance regression for legitimate use cases
- [ ] Benchmark with large inputs (up to 10KB)

### TESTING
- [ ] Test with malicious ReDoS payloads
- [ ] Test with legitimate Base64 strings
- [ ] Test with mixed valid/invalid input
- [ ] Benchmark regex performance
- [ ] Fuzz testing with random inputs

## Implementation Plan

### Step 1: Read Current Implementation

**File:** `src/tools/web_scraper.py:408`

```bash
grep -B 5 -A 5 "\[A-Za-z0-9+/\]" src/tools/web_scraper.py
```

### Step 2: Fix Regex Pattern

**File:** `src/tools/web_scraper.py`

**Before (VULNERABLE):**
```python
import re

def sanitize_message(message: str) -> str:
    # VULNERABLE: {40,500} allows catastrophic backtracking
    message = re.sub(
        r'[A-Za-z0-9+/]{40,500}={0,2}',
        '[REDACTED-BASE64]',
        message
    )
    return message
```

**After (FIXED):**
```python
import re

# Precompile regex for performance
_BASE64_PATTERN = re.compile(
    r'[A-Za-z0-9+/]{40,100}={0,2}',  # Reduced from 500 to 100
    re.MULTILINE
)

def sanitize_message(message: str, max_length: int = 100000) -> str:
    """
    Sanitize message by redacting Base64-encoded data.

    Args:
        message: Input message to sanitize
        max_length: Maximum message length to prevent DoS (default 100KB)

    Returns:
        Sanitized message with Base64 strings redacted

    Raises:
        ValueError: If message exceeds max_length
    """
    # Input validation: prevent DoS with huge strings
    if len(message) > max_length:
        raise ValueError(f"Message too long: {len(message)} > {max_length}")

    # Use fixed regex with safe upper bound
    message = _BASE64_PATTERN.sub('[REDACTED-BASE64]', message)

    return message
```

**Rationale for changes:**
- `{40,500}` → `{40,100}`: Reduces backtracking search space
- Pre-compile regex: Performance optimization
- Input length validation: Additional DoS protection
- Clear docstring: Documents security considerations

### Step 3: Consider Alternative Approaches

**Option A: Non-backtracking regex (Python 3.11+)**
```python
import regex  # pip install regex

# Possessive quantifier prevents backtracking
pattern = regex.compile(r'[A-Za-z0-9+/]{40,100}+={0,2}')
```

**Option B: Atomic grouping**
```python
# Atomic group - no backtracking
pattern = re.compile(r'(?>[A-Za-z0-9+/]{40,100})={0,2}')
```

**Option C: Timeout protection (defense in depth)**
```python
import signal

def regex_with_timeout(pattern, string, timeout_seconds=1):
    """Apply regex with timeout to prevent ReDoS"""
    # Implementation using signal.alarm() or threading.Timer
    # ...
```

Choose safest option available for Python version in use.

### Step 4: Add Monitoring

Log potential ReDoS attempts:
```python
import time
import logging

def sanitize_message(message: str, max_length: int = 100000) -> str:
    if len(message) > max_length:
        logging.warning(f"Potential ReDoS attempt: message length {len(message)}")
        raise ValueError(f"Message too long: {len(message)} > {max_length}")

    start_time = time.time()
    result = _BASE64_PATTERN.sub('[REDACTED-BASE64]', message)
    duration = time.time() - start_time

    if duration > 0.1:  # 100ms threshold
        logging.warning(f"Slow regex matching: {duration:.3f}s for {len(message)} chars")

    return result
```

## Test Strategy

### Unit Tests

**File:** `tests/tools/test_web_scraper_redos.py`

```python
import pytest
import time
from src.tools.web_scraper import sanitize_message

def test_redos_attack_prevented():
    """Test that ReDoS attack payload doesn't hang"""
    # Malicious payload: valid Base64 chars followed by invalid char
    # This would cause catastrophic backtracking with {40,500}
    malicious = 'A' * 500 + 'X'

    start = time.time()
    result = sanitize_message(malicious)
    duration = time.time() - start

    # Should complete in <100ms (not seconds/minutes)
    assert duration < 0.1, f"Regex took {duration}s - possible ReDoS vulnerability"

def test_legitimate_base64_redacted():
    """Test that legitimate Base64 is still redacted"""
    # Valid Base64 string (40-100 chars)
    message = "Token: " + "A" * 60 + "=="
    result = sanitize_message(message)

    assert '[REDACTED-BASE64]' in result
    assert 'A' * 60 not in result

def test_short_base64_not_redacted():
    """Test that short Base64 strings (<40 chars) are not redacted"""
    message = "Short: " + "A" * 30 + "=="
    result = sanitize_message(message)

    # Should NOT be redacted (below 40 char threshold)
    assert 'A' * 30 in result

def test_oversized_input_rejected():
    """Test that huge inputs are rejected (DoS protection)"""
    huge_message = "A" * 200000  # 200KB

    with pytest.raises(ValueError, match="Message too long"):
        sanitize_message(huge_message, max_length=100000)

def test_performance_benchmark():
    """Benchmark regex performance with various input sizes"""
    for size in [100, 1000, 10000]:
        message = "A" * size

        start = time.time()
        sanitize_message(message)
        duration = time.time() - start

        # Should complete in O(n) time
        assert duration < size * 0.001, f"Performance degraded for {size} chars"

@pytest.mark.parametrize("length", [40, 60, 80, 100])
def test_various_base64_lengths(length):
    """Test redaction works for various Base64 lengths"""
    message = "Data: " + "A" * length + "=="
    result = sanitize_message(message)

    assert '[REDACTED-BASE64]' in result
```

### Fuzz Testing

**File:** `tests/tools/test_web_scraper_fuzz.py`

```python
import hypothesis
from hypothesis import given, strategies as st
import time

@given(st.text(min_size=0, max_size=10000))
def test_fuzz_sanitize_message(text):
    """Fuzz test with random inputs"""
    start = time.time()

    try:
        result = sanitize_message(text)
        duration = time.time() - start

        # Should never take more than 100ms
        assert duration < 0.1, f"Regex took {duration}s on input length {len(text)}"

    except ValueError as e:
        # Expected for oversized inputs
        assert "too long" in str(e)
```

### Security Tests

**File:** `tests/tools/test_redos_security.py`

```python
import pytest
import time

# Known ReDoS attack patterns
REDOS_PAYLOADS = [
    'A' * 500 + 'X',                    # Long valid prefix + invalid char
    'A' * 250 + 'X' * 250,              # Mixed pattern
    ('A' * 100 + '=') * 5 + 'X',        # Repeated pattern
    'AAAA' * 125 + 'X',                 # Quadrupled pattern
]

@pytest.mark.parametrize("payload", REDOS_PAYLOADS)
def test_redos_payloads_complete_quickly(payload):
    """Test known ReDoS patterns complete in reasonable time"""
    start = time.time()
    result = sanitize_message(payload)
    duration = time.time() - start

    assert duration < 0.1, f"ReDoS payload took {duration}s"
```

## Error Handling

**Scenarios:**
1. Oversized input → Raise ValueError with clear message
2. Slow regex (>100ms) → Log warning with timing info
3. Regex compilation error → Fail fast at module import

## Success Metrics

- [ ] ReDoS payloads complete in <100ms
- [ ] Legitimate Base64 still redacted correctly
- [ ] No performance regression (<10ms for typical inputs)
- [ ] All security tests pass
- [ ] Fuzz testing passes (10,000+ random inputs)
- [ ] Code review confirms ReDoS is fixed

## Dependencies

**Blocked by:** None

**Blocks:** None (can be done in parallel)

**Optional:** Consider `regex` library for advanced features (Python 3.11+ not required)

## References

- Code Review Report: `.claude-coord/reports/code-review-20260201-002732.md` (lines 134-150)
- OWASP ReDoS: https://owasp.org/www-community/attacks/Regular_expression_Denial_of_Service_-_ReDoS
- CWE-1333: https://cwe.mitre.org/data/definitions/1333.html
- Regex Performance: https://www.regular-expressions.info/catastrophic.html

## Estimated Effort

**Time:** 2-3 hours
**Complexity:** Low-Medium (simple fix, thorough testing needed)

---

*Priority: CRITICAL (0)*
*Category: Security (DoS Prevention)*
