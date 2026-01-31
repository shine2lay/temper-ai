# Task: test-security-03 - Add Output Sanitization Tests

**Priority:** CRITICAL
**Effort:** 2-3 hours
**Status:** pending
**Owner:** unassigned
**Category:** Security Testing (P0)

---

## Summary
Add comprehensive tests for output sanitization to ensure secrets, PII, and sensitive data are properly redacted from LLM outputs.

---

## Files to Modify
- `tests/test_security/test_llm_security.py` - Add sanitization test cases
- `src/security/llm_security.py` - Enhance OutputSanitizer if needed

---

## Acceptance Criteria

### Secret Detection & Redaction
- [ ] Test redaction of OpenAI API keys (sk-*)
- [ ] Test redaction of Anthropic API keys (sk-ant-*)
- [ ] Test redaction of GitHub tokens (ghp_, gho_, ghs_)
- [ ] Test redaction of AWS credentials
- [ ] Test redaction of generic high-entropy strings (likely secrets)
- [ ] Test redaction of passwords in various formats
- [ ] Test redaction of database connection strings

### PII Detection & Redaction
- [ ] Test redaction of SSNs (123-45-6789 format)
- [ ] Test redaction of credit card numbers
- [ ] Test redaction of email addresses
- [ ] Test redaction of phone numbers
- [ ] Test redaction of IP addresses (optional based on policy)

### Edge Cases
- [ ] Test partial secret redaction (don't break formatting)
- [ ] Test multiple secrets in same output
- [ ] Test secrets in code blocks
- [ ] Test secrets in JSON/XML/YAML output
- [ ] Test Unicode/emoji in secrets
- [ ] Test URL-encoded secrets

### Performance
- [ ] Sanitization of 10KB output in <10ms
- [ ] Memory efficient for large outputs (1MB+)

---

## Implementation Details

```python
# tests/test_security/test_llm_security.py

def test_output_sanitizer_redacts_all_secret_types():
    """Test sanitizer redacts all supported secret types."""
    sanitizer = OutputSanitizer()
    
    test_cases = [
        ("OpenAI key: sk-1234567890abcdefghijklmnopqrstuvwxyz123456789012", "OPENAI_KEY"),
        ("Anthropic: sk-ant-api03-" + "x" * 95, "ANTHROPIC_KEY"),
        ("GitHub token: ghp_abcdefghijklmnopqrstuvwxyz123456", "GITHUB_TOKEN"),
        ("AWS key: AKIAIOSFODNN7EXAMPLE", "AWS_KEY"),
        ("Password: SuperSecret123!", "PASSWORD"),
        ("DB: postgres://user:pass@localhost:5432/db", "CONNECTION_STRING"),
    ]
    
    for output, secret_type in test_cases:
        sanitized = sanitizer.sanitize(output)
        # Verify redaction occurred
        assert "[REDACTED" in sanitized, f"Failed to redact {secret_type}"
        # Verify original secret NOT present
        assert not any(
            secret in sanitized
            for secret in ["sk-", "ghp_", "AKIAI", "SuperSecret"]
        )

def test_output_sanitizer_preserves_formatting():
    """Test sanitizer preserves output structure while redacting."""
    sanitizer = OutputSanitizer()
    
    output = """
    Here's your API key: sk-1234567890abcdefghijklmnopqrstuvwxyz123456789012
    
    And your config:
    {
        "api_key": "sk-1234567890abcdefghijklmnopqrstuvwxyz123456789012",
        "email": "user@example.com"
    }
    """
    
    sanitized = sanitizer.sanitize(output)
    
    # Should preserve JSON structure
    assert "{" in sanitized
    assert '"api_key"' in sanitized
    # But redact values
    assert "sk-" not in sanitized
    assert "[REDACTED" in sanitized

def test_output_sanitizer_handles_multiple_secrets():
    """Test sanitizer redacts multiple different secrets."""
    sanitizer = OutputSanitizer()
    
    output = """
    API Key: sk-abc123
    GitHub: ghp_xyz789
    Email: admin@company.com
    SSN: 123-45-6789
    """
    
    sanitized = sanitizer.sanitize(output)
    
    # All should be redacted
    assert sanitized.count("[REDACTED") >= 4
    assert "sk-" not in sanitized
    assert "ghp_" not in sanitized
    assert "admin@" not in sanitized
    assert "123-45-6789" not in sanitized

def test_output_sanitizer_performance():
    """Test sanitizer performs well on large outputs."""
    import time
    sanitizer = OutputSanitizer()
    
    # 10KB output with embedded secrets
    large_output = ("Normal text. " * 500) + "API key: sk-test123"
    
    start = time.time()
    sanitized = sanitizer.sanitize(large_output)
    elapsed_ms = (time.time() - start) * 1000
    
    assert elapsed_ms < 10, f"Sanitization too slow: {elapsed_ms:.2f}ms"
    assert "sk-test" not in sanitized
```

---

## Test Strategy
- Test with common secret patterns from detect-secrets library
- Test with real leaked credentials from Have I Been Pwned patterns
- Test with code snippets containing secrets
- Benchmark on large LLM outputs (API responses, code generation)

---

## Success Metrics
- [ ] All common secret types detected and redacted
- [ ] Zero false negatives on high-confidence secrets
- [ ] Performance: <10ms for 10KB output
- [ ] Coverage of OutputSanitizer >90%

---

## Dependencies
- **Blocked by:** test-security-01 (needs OutputSanitizer implementation)
- **Blocks:** None
- **Integrates with:** src/agents/standard_agent.py (post-processing)

---

## Design References
- detect-secrets patterns: https://github.com/Yelp/detect-secrets
- Common secret formats: https://github.com/trufflesecurity/trufflehog
- QA Report: test_llm_security.py - Output Sanitization (P0)
