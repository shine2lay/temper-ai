# Task: Strengthen command injection sanitization

## Summary

Enhance ParameterSanitizer.sanitize_command() with Unicode normalization and expanded patterns to prevent command injection via homoglyphs, command substitution variants, and brace expansion. Current implementation can be bypassed using Unicode characters that look like ASCII but have different codepoints (e.g., U+FF1B looks like semicolon).

**Estimated Effort:** 3.0 hours
**Module:** tools

---

## Files to Create

_None_

---

## Files to Modify

- `src/tools/base.py` - Enhance ParameterSanitizer.sanitize_command() with Unicode normalization and expanded patterns

---

## Acceptance Criteria

### Core Functionality
- [ ] Add Unicode NFKC normalization to prevent homoglyph attacks
- [ ] Block $(...), ${...}, {...} patterns
- [ ] Block null bytes and validate length
- [ ] Expand dangerous pattern list (backticks, pipes, redirects, etc.)

### Security Controls
- [ ] Use subprocess with shell=False only
- [ ] Maintain command allowlist for known-safe commands
- [ ] Add docstring warning about shell=True danger
- [ ] Reject any command not in allowlist

### Testing
- [ ] Test with Unicode homoglyphs (U+FF1B, U+FF5C)
- [ ] Test command substitution variants: $(cmd), `cmd`, ${cmd}
- [ ] Test brace expansion patterns: {a,b}, {1..10}
- [ ] Fuzz test with OWASP command injection payloads
- [ ] Test null byte injection: cmd\x00malicious

---

## Implementation Details

```python
import unicodedata
import re
from typing import List

class ParameterSanitizer:
    # Allowlist of safe commands
    ALLOWED_COMMANDS = {"ls", "cat", "grep", "find", "echo"}

    # Dangerous patterns (after normalization)
    DANGEROUS_PATTERNS = [
        r"\$\(",      # Command substitution
        r"\$\{",      # Variable expansion
        r"`",         # Backtick substitution
        r"\{.*\}",    # Brace expansion
        r"[;&|<>]",   # Shell metacharacters
        r"\x00",      # Null byte
        r"\\[xX][0-9a-fA-F]{2}",  # Hex escape
    ]

    @staticmethod
    def sanitize_command(command: str, max_length: int = 1000) -> str:
        """
        Sanitize command string to prevent injection.

        WARNING: This function does NOT make shell=True safe.
        ALWAYS use subprocess.run(..., shell=False) with argument lists.

        Args:
            command: Command to sanitize
            max_length: Maximum allowed length

        Returns:
            Sanitized command

        Raises:
            ValueError: If command is dangerous or invalid
        """
        if not command or len(command) > max_length:
            raise ValueError(f"Invalid command length: {len(command)}")

        # Normalize Unicode to canonical form (prevents homoglyph attacks)
        normalized = unicodedata.normalize('NFKC', command)

        # Check for dangerous patterns
        for pattern in ParameterSanitizer.DANGEROUS_PATTERNS:
            if re.search(pattern, normalized):
                raise ValueError(f"Dangerous pattern detected: {pattern}")

        # Extract command name and validate against allowlist
        cmd_name = normalized.split()[0] if normalized else ""
        if cmd_name not in ParameterSanitizer.ALLOWED_COMMANDS:
            raise ValueError(f"Command not in allowlist: {cmd_name}")

        return normalized
```

**Usage Pattern:**
```python
# CORRECT - shell=False with list arguments
sanitized = ParameterSanitizer.sanitize_command(user_input)
subprocess.run([sanitized], shell=False)

# WRONG - Never use shell=True
subprocess.run(command, shell=True)  # DANGEROUS!
```

---

## Test Strategy

1. **Unicode Homoglyph Tests:**
   - Test with U+FF1B (fullwidth semicolon) → should be normalized and blocked
   - Test with U+FF5C (fullwidth vertical bar) → should be normalized and blocked
   - Test with mixed ASCII and Unicode → should normalize before checking

2. **Command Substitution Tests:**
   - `ls $(whoami)` → blocked
   - `ls \`whoami\`` → blocked
   - `ls ${HOME}` → blocked

3. **Brace Expansion Tests:**
   - `ls {a,b,c}` → blocked
   - `ls file{1..10}` → blocked

4. **OWASP Fuzzing:**
   - Run all OWASP command injection test vectors
   - Verify 100% detection rate

5. **Property-Based Testing:**
   - Use hypothesis library to generate random payloads
   - Verify all malicious patterns detected

---

## Success Metrics

- [ ] All OWASP test vectors blocked (100% detection)
- [ ] Unicode attacks prevented (homoglyphs normalized)
- [ ] No false negatives (all dangerous commands caught)
- [ ] No false positives (safe commands allowed)

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** ParameterSanitizer, all tool execute methods

---

## Design References

- `.claude-coord/reports/code-review-20260128-224245.md#2-command-injection`

---

## Notes

**Critical** - Command injection can lead to full system compromise. Attackers can:
- Execute arbitrary commands
- Read/modify sensitive files
- Install backdoors
- Pivot to other systems

**Key Principle:** Defense in depth - normalize input, check patterns, use allowlist, AND use shell=False.
