# Task Specification: code-crit-log-injection-06

## Problem Statement

Incomplete sanitization in logging doesn't handle multi-line log injection via URL encoding, Unicode escapes, or other bypasses. Attackers can inject fake log entries, poison log aggregation systems, and evade detection by splitting log entries across lines or using encoded characters.

Example attack: `username=admin%0A[ERROR] Fake security violation%0A`

## Context

- **Source:** Code Review Report 2026-02-01 (Critical Issue #6)
- **File Affected:** `src/utils/logging.py:75`
- **Impact:** Log poisoning, compromised log aggregation, security monitoring bypass
- **Module:** Utils
- **OWASP Category:** A03:2021 - Injection (Log Injection)
- **CWE:** CWE-117: Improper Output Neutralization for Logs

## Acceptance Criteria

### CORE FUNCTIONALITY
- [ ] Use whitelist approach: only allow printable ASCII + safe whitespace
- [ ] Escape all control characters (0x00-0x1F except safe ones)
- [ ] Handle newlines, carriage returns, tabs explicitly
- [ ] Prevent URL-encoded injection (%0A, %0D, etc.)
- [ ] Handle Unicode escapes (\n, \r, \t, etc.)

### SECURITY CONTROLS
- [ ] Block log injection via newlines
- [ ] Block log injection via carriage returns
- [ ] Escape control characters as hex (\x0A format)
- [ ] Validate and escape BEFORE logging
- [ ] Preserve legitimate whitespace (spaces, safe tabs)

### LOGGING SAFETY
- [ ] One log entry = one line (no multi-line injections)
- [ ] Log output is parseable by SIEM/log aggregators
- [ ] Sensitive data still redacted (existing functionality)
- [ ] Escaped output is readable for debugging

### TESTING
- [ ] Test newline injection blocked
- [ ] Test URL-encoded injection blocked
- [ ] Test Unicode escape injection blocked
- [ ] Test legitimate logs still work
- [ ] Test edge cases (empty strings, only whitespace, etc.)

## Implementation Plan

### Step 1: Read Current Implementation

**File:** `src/utils/logging.py:75`

```bash
grep -B 10 -A 20 "_redact_secrets" src/utils/logging.py
```

Understand current sanitization logic and gaps.

### Step 2: Implement Comprehensive Sanitization

**File:** `src/utils/logging.py`

**Before (INCOMPLETE):**
```python
def _redact_secrets(self, text: str) -> str:
    # Incomplete: doesn't handle encoded newlines
    text = text.replace('\n', ' ')
    # ... rest of redaction
    return text
```

**After (COMPREHENSIVE):**
```python
import re
from typing import Optional

# Precompile regex patterns for performance
_SENSITIVE_PATTERNS = [
    (re.compile(r'(password|passwd|pwd)[=:]\s*\S+', re.IGNORECASE), r'\1=[REDACTED]'),
    (re.compile(r'(api[_-]?key|apikey|token)[=:]\s*\S+', re.IGNORECASE), r'\1=[REDACTED]'),
    (re.compile(r'(secret|credential)[=:]\s*\S+', re.IGNORECASE), r'\1=[REDACTED]'),
]

def _sanitize_for_logging(text: str, max_length: int = 10000) -> str:
    """
    Sanitize text for safe logging by:
    1. Removing control characters that could inject fake log entries
    2. Escaping special characters
    3. Redacting sensitive data
    4. Limiting length to prevent log flooding

    Args:
        text: Input text to sanitize
        max_length: Maximum allowed length (prevents DoS)

    Returns:
        Sanitized text safe for logging (single line, no injection)
    """
    if not text:
        return ""

    # Truncate if too long (DoS prevention)
    if len(text) > max_length:
        text = text[:max_length] + "...[TRUNCATED]"

    # Step 1: Whitelist approach - only allow printable ASCII + safe whitespace
    # Convert all characters to safe equivalents
    sanitized_chars = []
    for char in text:
        if char.isprintable() and ord(char) < 128:
            # Allow printable ASCII
            sanitized_chars.append(char)
        elif char in (' ', '\t'):
            # Allow spaces and tabs
            sanitized_chars.append(char)
        elif char in ('\n', '\r'):
            # Escape newlines/carriage returns (prevent log injection)
            sanitized_chars.append('\\n' if char == '\n' else '\\r')
        else:
            # Escape all other control characters and non-ASCII
            sanitized_chars.append(f'\\x{ord(char):02x}')

    text = ''.join(sanitized_chars)

    # Step 2: Handle URL-encoded injection attempts
    # Decode and re-escape to prevent %0A bypasses
    try:
        import urllib.parse
        decoded = urllib.parse.unquote(text)
        # If decoding changed anything, it might be an injection attempt
        if decoded != text:
            # Re-sanitize the decoded version
            text = _sanitize_for_logging(decoded, max_length)
    except Exception:
        # If URL decoding fails, use original text (already sanitized above)
        pass

    # Step 3: Redact sensitive data
    text = _redact_secrets(text)

    return text

def _redact_secrets(text: str) -> str:
    """
    Redact sensitive data like passwords, API keys, tokens.

    Note: This should be called AFTER _sanitize_for_logging to ensure
    injection is prevented first.
    """
    for pattern, replacement in _SENSITIVE_PATTERNS:
        text = pattern.sub(replacement, text)

    return text

# Update existing logging methods to use new sanitization
def info(self, message: str, **kwargs):
    """Log info message with sanitization"""
    safe_message = _sanitize_for_logging(message)
    safe_kwargs = {k: _sanitize_for_logging(str(v)) for k, v in kwargs.items()}
    self.logger.info(safe_message, **safe_kwargs)

def error(self, message: str, **kwargs):
    """Log error message with sanitization"""
    safe_message = _sanitize_for_logging(message)
    safe_kwargs = {k: _sanitize_for_logging(str(v)) for k, v in kwargs.items()}
    self.logger.error(safe_message, **safe_kwargs)

# Similar for debug, warning, critical...
```

### Step 3: Add Security Tests

Create comprehensive test suite to verify injection is blocked.

### Step 4: Update All Logging Call Sites

Search for direct logger usage that bypasses sanitization:
```bash
grep -r "logger\.info\|logger\.error\|logger\.warning" src/
```

Ensure all logging goes through safe wrapper methods.

## Test Strategy

### Unit Tests

**File:** `tests/utils/test_logging_security.py`

```python
import pytest
from src.utils.logging import _sanitize_for_logging

def test_newline_injection_blocked():
    """Test that newline injection is escaped"""
    malicious = "username=admin\n[ERROR] Fake error\nAnother line"
    sanitized = _sanitize_for_logging(malicious)

    # Newlines should be escaped
    assert '\n' not in sanitized
    assert '\\n' in sanitized

def test_carriage_return_injection_blocked():
    """Test that carriage return injection is escaped"""
    malicious = "username=admin\r[ERROR] Fake error"
    sanitized = _sanitize_for_logging(malicious)

    assert '\r' not in sanitized
    assert '\\r' in sanitized

def test_url_encoded_newline_blocked():
    """Test that URL-encoded newline (%0A) is blocked"""
    malicious = "username=admin%0A[ERROR] Fake error"
    sanitized = _sanitize_for_logging(malicious)

    # After decoding and re-sanitizing, newline should be escaped
    assert '\n' not in sanitized
    # Should see escaped newline
    assert '\\n' in sanitized or '\\x0a' in sanitized.lower()

def test_unicode_escape_newline_blocked():
    """Test that Unicode escapes are handled"""
    malicious = "username=admin\\n[ERROR] Fake error"
    sanitized = _sanitize_for_logging(malicious)

    # Should preserve the literal backslash-n or escape it further
    assert '\n' not in sanitized

def test_control_characters_escaped():
    """Test that control characters are escaped as hex"""
    malicious = "data\x00\x01\x02\x1F"
    sanitized = _sanitize_for_logging(malicious)

    # Control chars should be escaped
    assert '\\x00' in sanitized
    assert '\\x01' in sanitized
    assert '\\x02' in sanitized
    assert '\\x1f' in sanitized

def test_legitimate_logs_preserved():
    """Test that normal log messages work correctly"""
    normal = "User logged in successfully from IP 192.168.1.1"
    sanitized = _sanitize_for_logging(normal)

    # Should be unchanged (all printable ASCII)
    assert sanitized == normal

def test_sensitive_data_redacted():
    """Test that sensitive data is still redacted"""
    sensitive = "Login attempt with password=secret123 failed"
    sanitized = _sanitize_for_logging(sensitive)

    assert 'secret123' not in sanitized
    assert '[REDACTED]' in sanitized

def test_empty_string_handled():
    """Test that empty string is handled safely"""
    assert _sanitize_for_logging("") == ""

def test_oversized_input_truncated():
    """Test that huge inputs are truncated"""
    huge = "A" * 20000
    sanitized = _sanitize_for_logging(huge, max_length=10000)

    assert len(sanitized) <= 10100  # max_length + truncation message
    assert '[TRUNCATED]' in sanitized

def test_mixed_safe_and_unsafe_chars():
    """Test handling of mixed safe/unsafe characters"""
    mixed = "Safe text\nUnsafe\rMore\x00Data"
    sanitized = _sanitize_for_logging(mixed)

    assert 'Safe text' in sanitized
    assert '\n' not in sanitized
    assert '\r' not in sanitized
    assert '\x00' not in sanitized
```

### Integration Tests

**File:** `tests/utils/test_logging_integration.py`

```python
import logging
import io
from src.utils.logging import SafeLogger

def test_log_injection_attack_in_real_logs():
    """Test that log injection doesn't create fake entries in real logger"""
    # Capture log output
    log_stream = io.StringIO()
    handler = logging.StreamHandler(log_stream)
    handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))

    logger = SafeLogger('test')
    logger.logger.addHandler(handler)

    # Attempt log injection
    logger.info("User input: admin\n[ERROR] Fake security violation")

    # Get logged output
    output = log_stream.getvalue()

    # Should be one line (INFO), not two lines (INFO + ERROR)
    lines = output.strip().split('\n')
    assert len(lines) == 1, f"Log injection created {len(lines)} entries"
    assert lines[0].startswith('INFO:')
    assert '[ERROR]' in lines[0]  # Should be part of the message, not separate entry
```

## Security Considerations

**Attack Vectors Mitigated:**
1. **Newline injection** (`\n`, `%0A`, `\u000A`)
2. **Carriage return injection** (`\r`, `%0D`)
3. **Null byte injection** (`\x00`)
4. **Control character injection** (any 0x00-0x1F except safe ones)
5. **Unicode escape injection** (`\n`, `\r`)

**Defense in Depth:**
- Whitelist approach (safest)
- Explicit escaping
- URL decode + re-sanitize
- Length limiting (DoS prevention)
- Sensitive data redaction

## Error Handling

**Scenarios:**
1. Non-string input → Convert to string first
2. URL decoding fails → Use original (already sanitized)
3. Empty string → Return empty string safely

## Success Metrics

- [ ] All injection tests pass
- [ ] No multi-line log entries from user input
- [ ] SIEM/log aggregators parse logs correctly
- [ ] Legitimate logs still readable
- [ ] Performance impact <5% (sanitization is fast)
- [ ] Security audit approves implementation

## Dependencies

**Blocked by:** None

**Blocks:** None (can be done in parallel)

**Integrates with:** All logging throughout codebase

## References

- Code Review Report: `.claude-coord/reports/code-review-20260201-002732.md` (lines 154-171)
- OWASP Log Injection: https://owasp.org/www-community/attacks/Log_Injection
- CWE-117: https://cwe.mitre.org/data/definitions/117.html
- OWASP Logging Cheat Sheet: https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html

## Estimated Effort

**Time:** 3-4 hours
**Complexity:** Medium (sanitization logic is intricate, testing is critical)

---

*Priority: CRITICAL (0)*
*Category: Security (Log Injection Prevention)*
