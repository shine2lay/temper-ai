# Task: Implement prompt/response sanitization before storage

## Summary

Add _sanitize_sensitive_data() method to ExecutionTracker to detect and redact API keys, PII, and oversized content before storing LLM prompts/responses. Current implementation logs everything to database, creating GDPR/HIPAA compliance risks and credential exposure.

**Estimated Effort:** 6.0 hours
**Module:** observability

---

## Files to Create

_None_

---

## Files to Modify

- `src/observability/tracker.py` - Add sanitization before storing LLM prompts/responses

---

## Acceptance Criteria

### Core Functionality
- [ ] Detect and redact API keys (sk-*, xox*, AKIA*)
- [ ] Detect and mask PII (emails, SSNs, credit cards)
- [ ] Truncate excessively long prompts (>10KB)
- [ ] Add is_sanitized flag to track processing

### Security Controls
- [ ] No API keys in database
- [ ] No PII in database
- [ ] Compliance with GDPR/HIPAA

### Testing
- [ ] Test with prompts containing API keys
- [ ] Test with PII patterns (emails, SSNs, credit cards)
- [ ] Test with oversized content (>10KB)
- [ ] Verify redaction completeness (query DB, check no secrets)

---

## Implementation Details

```python
import re
from typing import Dict, Any

class DataSanitizer:
    """Sanitize sensitive data before storage"""

    MAX_CONTENT_SIZE = 10 * 1024  # 10KB

    # Secret patterns (from secret_detection.py)
    SECRET_PATTERNS = {
        "openai_key": re.compile(r"\bsk-[a-zA-Z0-9]{20,64}\b"),
        "aws_key": re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
        "github_token": re.compile(r"\bgh[ps]_[a-zA-Z0-9]{36,}\b"),
        "slack_token": re.compile(r"\bxox[baprs]-[a-zA-Z0-9\-]{10,100}\b"),
        "generic_key": re.compile(r"\b(?:api[_-]?key|token)\s*[:=]\s*([a-zA-Z0-9_\-]{20,64})\b", re.IGNORECASE),
    }

    # PII patterns
    PII_PATTERNS = {
        "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),
        "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
        "credit_card": re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b"),
        "phone": re.compile(r"\b(?:\+1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),
        "ipv4": re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    }

    @classmethod
    def sanitize(cls, content: str) -> tuple[str, bool]:
        """
        Sanitize content by redacting secrets and PII.

        Args:
            content: Content to sanitize

        Returns:
            (sanitized_content, was_modified) tuple
        """
        if not content:
            return content, False

        original = content
        modified = False

        # 1. Truncate if too large
        if len(content) > cls.MAX_CONTENT_SIZE:
            content = content[:cls.MAX_CONTENT_SIZE] + "\n[TRUNCATED]"
            modified = True

        # 2. Redact secrets
        for name, pattern in cls.SECRET_PATTERNS.items():
            if pattern.search(content):
                content = pattern.sub(f"[REDACTED_{name.upper()}]", content)
                modified = True

        # 3. Mask PII
        for name, pattern in cls.PII_PATTERNS.items():
            if pattern.search(content):
                if name == "email":
                    # Preserve domain for debugging
                    content = pattern.sub(lambda m: f"[EMAIL@{m.group(0).split('@')[1]}]", content)
                else:
                    content = pattern.sub(f"[REDACTED_{name.upper()}]", content)
                modified = True

        return content, modified


class ExecutionTracker:
    """Track execution with sanitized data"""

    def __init__(self):
        self.sanitizer = DataSanitizer()

    def track_llm_call(
        self,
        prompt: str,
        response: str,
        model: str,
        system_prompt: str = None,
        **metadata
    ) -> Dict[str, Any]:
        """
        Track LLM call with sanitization.

        Args:
            prompt: User prompt
            response: LLM response
            model: Model name
            system_prompt: System prompt
            **metadata: Additional metadata

        Returns:
            Tracking record with sanitized data
        """
        # Sanitize all text fields
        sanitized_prompt, prompt_modified = self.sanitizer.sanitize(prompt)
        sanitized_response, response_modified = self.sanitizer.sanitize(response)

        if system_prompt:
            sanitized_system, system_modified = self.sanitizer.sanitize(system_prompt)
        else:
            sanitized_system = None
            system_modified = False

        # Create tracking record
        record = {
            "prompt": sanitized_prompt,
            "response": sanitized_response,
            "system_prompt": sanitized_system,
            "model": model,
            "is_sanitized": prompt_modified or response_modified or system_modified,
            "metadata": metadata,
        }

        # Store in database
        self._store_record(record)

        return record

    def _store_record(self, record: Dict[str, Any]):
        """Store record in database"""
        # Implementation depends on database backend
        pass


# Example usage
tracker = ExecutionTracker()

# These will be sanitized before storage
tracker.track_llm_call(
    prompt="Use this key: sk-abcd1234efgh5678ijkl9012mnop3456",
    response="I'll use that API key...",
    model="claude-3-opus"
)
# Stored as: "Use this key: [REDACTED_OPENAI_KEY]"

tracker.track_llm_call(
    prompt="Send results to john.doe@example.com",
    response="OK, sending to that email...",
    model="claude-3-opus"
)
# Stored as: "Send results to [EMAIL@example.com]"
```

---

## Test Strategy

1. **API Key Detection Tests:**
   ```python
   test_cases = [
       ("sk-1234567890abcdefghij", "[REDACTED_OPENAI_KEY]"),
       ("AKIAIOSFODNN7EXAMPLE", "[REDACTED_AWS_KEY]"),
       ("xoxb-1234-5678-abcd", "[REDACTED_SLACK_TOKEN]"),
   ]

   for input_text, expected in test_cases:
       sanitized, modified = sanitizer.sanitize(f"Use key: {input_text}")
       assert "[REDACTED" in sanitized
       assert input_text not in sanitized
       assert modified is True
   ```

2. **PII Detection Tests:**
   ```python
   pii_tests = [
       ("john@example.com", "[EMAIL@example.com]"),
       ("123-45-6789", "[REDACTED_SSN]"),
       ("4111-1111-1111-1111", "[REDACTED_CREDIT_CARD]"),
   ]

   for pii, expected in pii_tests:
       sanitized, _ = sanitizer.sanitize(pii)
       assert pii not in sanitized
       assert "[REDACTED" in sanitized or "[EMAIL" in sanitized
   ```

3. **Database Verification:**
   ```python
   # Insert test data with secrets
   tracker.track_llm_call(
       prompt="My API key is sk-test123456789",
       response="OK",
       model="test"
   )

   # Query database directly
   records = db.query("SELECT prompt FROM llm_calls")

   # Verify no secrets in database
   for record in records:
       assert "sk-" not in record["prompt"]
       assert "AKIA" not in record["prompt"]
       assert "@" not in record["prompt"] or "[EMAIL@" in record["prompt"]
   ```

4. **Truncation Tests:**
   ```python
   large_prompt = "a" * 20_000  # 20KB
   sanitized, modified = sanitizer.sanitize(large_prompt)

   assert len(sanitized) <= 10_240  # 10KB + [TRUNCATED]
   assert "[TRUNCATED]" in sanitized
   assert modified is True
   ```

---

## Success Metrics

- [ ] Zero secrets in database (100% redaction)
- [ ] PII detection >95% accuracy
- [ ] Compliance requirements met (GDPR, HIPAA)
- [ ] No false positives on legitimate content

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** ExecutionTracker, track_llm_call

---

## Design References

- `.claude-coord/reports/code-review-20260128-224245.md#1-sensitive-data-logging`

---

## Notes

**Critical** - GDPR/HIPAA compliance risk, credential exposure. Issues:
1. **Credential Leakage:** API keys in logs → attackers access APIs
2. **PII Exposure:** User emails/SSNs in logs → GDPR violations
3. **Compliance:** HIPAA requires PII redaction → fines if not implemented
4. **Data Breach:** Database dump exposes all secrets/PII

**Compliance Requirements:**
- **GDPR:** Right to be forgotten, data minimization, PII protection
- **HIPAA:** PHI must be encrypted or redacted in logs
- **PCI DSS:** Credit card numbers must never be stored in logs

**Implementation Notes:**
- Sanitize BEFORE database insert (not on read)
- Set `is_sanitized` flag for auditability
- Preserve partial info for debugging (e.g., email domain)
- Log sanitization events to audit trail
