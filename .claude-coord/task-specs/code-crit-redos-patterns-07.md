# Task: Fix ReDoS vulnerabilities in security patterns

## Summary

Rewrite regex patterns in secret_detection.py and llm_security.py to avoid catastrophic backtracking. Current patterns use nested quantifiers that cause exponential time complexity on malicious input, enabling ReDoS (Regular Expression Denial of Service) attacks.

**Estimated Effort:** 3.0 hours
**Module:** security

---

## Files to Create

_None_

---

## Files to Modify

- `src/safety/secret_detection.py` - Rewrite regex patterns to avoid catastrophic backtracking
- `src/security/llm_security.py` - Fix injection detection patterns

---

## Acceptance Criteria

### Core Functionality
- [ ] Use atomic groups (?> ...)
- [ ] Replace nested quantifiers with specific character classes
- [ ] Add regex timeout support
- [ ] Validate input length before regex matching

### Security Controls
- [ ] No ReDoS possible
- [ ] All patterns complete in O(n) time
- [ ] Timeouts prevent DoS

### Testing
- [ ] Test with ReDoS payloads (evil regex patterns)
- [ ] Benchmark pattern performance
- [ ] Test with 100KB inputs
- [ ] Use rxxr2 tool to analyze patterns

---

## Implementation Details

```python
import re
import regex  # regex library supports timeouts

class SecretDetection:
    """Detect secrets with ReDoS-safe patterns"""

    # Maximum input size (prevent memory exhaustion)
    MAX_INPUT_SIZE = 100_000

    # ReDoS-safe patterns (no nested quantifiers)
    PATTERNS = {
        # BAD: r"ignore[\s._\-|]+(all[\s._\-|]+)?"
        # GOOD: Use word boundaries and specific patterns
        "prompt_injection": regex.compile(
            r"\bignore\s+all\s+previous\b",
            regex.IGNORECASE,
            timeout=1.0  # 1 second timeout
        ),

        # BAD: r"(api[_-]?key|token)[:\s]*([\w\-]+)"
        # GOOD: Limit quantifiers, use specific char classes
        "api_key": regex.compile(
            r"\b(?:api[_-]?key|token)\s*[:=]\s*([a-zA-Z0-9_\-]{20,64})\b",
            regex.IGNORECASE,
            timeout=1.0
        ),

        # BAD: r"(sk-[a-zA-Z0-9]+)"
        # GOOD: Specify exact length range
        "openai_key": regex.compile(
            r"\bsk-[a-zA-Z0-9]{20,64}\b",
            timeout=1.0
        ),

        # BAD: r"(AKIA[A-Z0-9]+)"
        # GOOD: AWS keys have fixed format
        "aws_key": regex.compile(
            r"\bAKIA[A-Z0-9]{16}\b",
            timeout=1.0
        ),

        # BAD: r"(password|passwd|pwd)[:\s]*([^\s]+)"
        # GOOD: Limit what matches, use atomic group
        "password": regex.compile(
            r"\b(?:password|passwd|pwd)\s*[:=]\s*(?>[a-zA-Z0-9@#$%^&*]{8,32})\b",
            regex.IGNORECASE,
            timeout=1.0
        ),
    }

    @classmethod
    def detect(cls, content: str) -> list[tuple[str, str]]:
        """
        Detect secrets in content.

        Args:
            content: Content to scan

        Returns:
            List of (pattern_name, matched_value) tuples

        Raises:
            ValueError: If content too large
        """
        # Validate size
        if len(content) > cls.MAX_INPUT_SIZE:
            raise ValueError(f"Content exceeds max size: {len(content)} > {cls.MAX_INPUT_SIZE}")

        detections = []

        for name, pattern in cls.PATTERNS.items():
            try:
                matches = pattern.findall(content)
                for match in matches:
                    # Extract actual secret (may be in capture group)
                    secret = match if isinstance(match, str) else match[0]
                    detections.append((name, secret))
            except TimeoutError:
                # Pattern timeout - log and skip
                import logging
                logging.warning(f"Regex timeout for pattern: {name}")
                continue

        return detections


class PromptInjectionDetector:
    """Detect prompt injection with ReDoS-safe patterns"""

    MAX_INPUT_SIZE = 100_000

    # ReDoS-safe patterns
    INJECTION_PATTERNS = [
        # Simple word boundary patterns (O(n) time)
        regex.compile(r"\bignore\s+all\s+previous\b", regex.IGNORECASE, timeout=1.0),
        regex.compile(r"\bforget\s+(?:all|previous)\s+instructions\b", regex.IGNORECASE, timeout=1.0),
        regex.compile(r"\bdisregard\s+(?:all|previous)\b", regex.IGNORECASE, timeout=1.0),

        # Use atomic groups for complex patterns
        regex.compile(r"\bsystem\s*:\s*(?>[a-z\s]{5,50})\b", regex.IGNORECASE, timeout=1.0),
    ]

    @classmethod
    def detect(cls, prompt: str) -> bool:
        """
        Check if prompt contains injection attempt.

        Args:
            prompt: User prompt

        Returns:
            True if injection detected

        Raises:
            ValueError: If prompt too large
        """
        if len(prompt) > cls.MAX_INPUT_SIZE:
            raise ValueError(f"Prompt too large: {len(prompt)}")

        for pattern in cls.INJECTION_PATTERNS:
            try:
                if pattern.search(prompt):
                    return True
            except TimeoutError:
                # Timeout = suspicious, treat as injection
                return True

        return False
```

**Key Changes:**
1. Use `regex` library (supports timeout parameter)
2. Add `.MAX_INPUT_SIZE` validation
3. Replace nested quantifiers with specific character classes
4. Use word boundaries `\b` instead of complex patterns
5. Use atomic groups `(?>...)` where needed
6. Catch TimeoutError and handle gracefully

---

## Test Strategy

1. **ReDoS Payload Generation:**
   ```python
   # Generate evil string for pattern r"a*b*c*d*e*"
   evil = "a" * 50 + "b" * 50 + "c" * 50 + "d" * 50 + "X"

   # Should timeout or complete quickly (not hang forever)
   with pytest.raises(TimeoutError):
       pattern.search(evil)
   ```

2. **Performance Benchmarking:**
   ```python
   import time

   for size in [100, 1000, 10000, 100000]:
       content = "legitimate text " * (size // 16)
       start = time.time()
       SecretDetection.detect(content)
       elapsed = time.time() - start

       # Should scale linearly (O(n))
       assert elapsed < size / 10000  # 10k chars per second minimum
   ```

3. **rxxr2 Analysis:**
   ```bash
   # Use rxxr2 tool to analyze patterns for ReDoS
   rxxr2 "ignore[\s._\-|]+(all[\s._\-|]+)?"  # Should report vulnerability
   rxxr2 "\bignore\s+all\s+previous\b"  # Should report safe
   ```

4. **Legitimate Input Tests:**
   - Verify no false positives on normal text
   - Verify detection still works for real secrets

---

## Success Metrics

- [ ] All patterns complete in <1ms per call
- [ ] No timeouts on legitimate input (0 false positives)
- [ ] ReDoS attacks timeout safely (no service hang)
- [ ] Linear time complexity verified (O(n))

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** SecretDetection, PromptInjectionDetector

---

## Design References

- `.claude-coord/reports/code-review-20260128-224245.md#3-redos-vulnerability`

---

## Notes

**Critical** - ReDoS can cause service outages. Attack scenarios:
- Attacker sends crafted input → regex hangs → thread blocked
- Multiple requests → all threads blocked → service down
- No CPU limit → 100% CPU usage

**Example Evil Pattern:**
```python
# BAD - Nested quantifiers cause exponential backtracking
pattern = r"(a+)+(b+)+(c+)+"
evil_input = "a" * 50 + "b" * 50 + "X"  # No 'c' → exponential backtracking

# GOOD - Atomic groups prevent backtracking
pattern = r"(?>a+)(?>b+)(?>c+)"
```

**Dependencies:**
- Install `regex` library: `pip install regex`
- Use `timeout` parameter on all patterns
