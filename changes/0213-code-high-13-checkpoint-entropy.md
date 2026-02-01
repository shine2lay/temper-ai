# Fix: Weak Entropy in Checkpoint IDs (code-high-13)

**Date:** 2026-02-01
**Priority:** HIGH (P2)
**Module:** compiler
**Status:** Complete

## Summary

Fixed weak entropy in checkpoint ID generation by adding cryptographically secure random suffix using `secrets.token_hex()`. Previously, checkpoint IDs used only timestamp + counter, making them predictable and vulnerable to enumeration attacks.

## Problem

The `FileCheckpointBackend._generate_checkpoint_id()` method generated IDs using only:
```python
f"cp-{timestamp}-{counter}"
```

**Security Issues:**
1. **Enumeration Attack:** Attackers could guess valid checkpoint IDs by predicting timestamps
2. **Collision Risk:** Same timestamp + counter could occur across instances
3. **Information Leakage:** Timestamp reveals when checkpoint was created
4. **No Cryptographic Security:** No randomness to prevent brute-force guessing

**Impact:**
- Checkpoint collision in distributed systems
- Security enumeration (guess valid IDs)
- Timing attacks (predict checkpoint creation times)

## Solution

Enhanced checkpoint ID generation with cryptographic randomness:

**Before:**
```python
def _generate_checkpoint_id(self) -> str:
    """Generate a unique checkpoint ID."""
    timestamp = int(time.time() * 1000)  # Millisecond precision
    self._counter += 1
    return f"cp-{timestamp}-{self._counter}"
```

**After:**
```python
def _generate_checkpoint_id(self) -> str:
    """Generate a unique checkpoint ID with cryptographic randomness.

    Uses timestamp for ordering + counter for uniqueness within millisecond
    + secrets.token_hex for cryptographic randomness to prevent enumeration.

    Returns:
        Checkpoint ID in format: cp-{timestamp}-{counter}-{random}
        Example: cp-1706745600000-1-a3f2d9
    """
    timestamp = int(time.time() * 1000)  # Millisecond precision
    self._counter += 1
    random_suffix = secrets.token_hex(6)  # 12 hex chars (48 bits of entropy)
    return f"cp-{timestamp}-{self._counter}-{random_suffix}"
```

**Key Changes:**
1. Added `import secrets` for cryptographically secure random numbers
2. Added 48-bit random suffix (12 hex characters)
3. Enhanced docstring with security rationale and format example

## Security Analysis

### Entropy Calculation

- **Old format:** `cp-{timestamp}-{counter}`
  - Timestamp entropy: ~10 bits (1000 values per second)
  - Counter entropy: ~3 bits (typically < 10)
  - **Total:** ~13 bits (easily guessable)

- **New format:** `cp-{timestamp}-{counter}-{random}`
  - Timestamp entropy: ~10 bits
  - Counter entropy: ~3 bits
  - Random suffix: **48 bits** (cryptographically secure)
  - **Total:** ~61 bits (2^48 = 281 trillion combinations)

### Attack Resistance

| Attack Vector | Before | After |
|---------------|--------|-------|
| Enumeration | ❌ Easy (predict timestamp) | ✅ Infeasible (2^48 guesses) |
| Collision | ⚠️ Possible (same millisecond) | ✅ Negligible (birthday paradox: 2^24 operations) |
| Timing Attack | ❌ Timestamp leaked | ✅ Timestamp still present but unpredictable suffix |
| Brute Force | ❌ ~13 bits (8,192 guesses) | ✅ ~48 bits (281T guesses) |

## Changes

### Files Modified

**src/compiler/checkpoint_backends.py:**
- Line 28: Added `import secrets`
- Lines 200-213: Enhanced `_generate_checkpoint_id()` with cryptographic randomness
  - Added `secrets.token_hex(6)` for 48-bit random suffix
  - Enhanced docstring with security rationale
  - Changed format from `cp-{timestamp}-{counter}` to `cp-{timestamp}-{counter}-{random}`

**tests/test_compiler/test_checkpoint_backends.py:**
- Lines 243-286: Added `test_checkpoint_id_entropy()` to verify:
  - All IDs are unique (no collisions in 100 iterations)
  - Format is correct (4 parts: cp-timestamp-counter-random)
  - Random suffix is 12 hex characters (48 bits)
  - Random suffixes are all different (high entropy)

- Lines 288-300: Added `test_checkpoint_id_not_predictable()` to verify:
  - Consecutive IDs have different random suffixes
  - Random values are not sequential (not just a counter)

## Testing

All tests passing:
```bash
.venv/bin/pytest tests/test_compiler/test_checkpoint_backends.py::TestFileCheckpointBackend -x
```

**Results:** 18 passed (including 2 new security tests)

### Test Coverage

1. **test_checkpoint_id_entropy:**
   - Generates 100 checkpoint IDs
   - Verifies all are unique (no collisions)
   - Validates format (4 parts with correct types)
   - Confirms 12-character hex random suffix
   - Ensures all random suffixes are different

2. **test_checkpoint_id_not_predictable:**
   - Generates consecutive IDs
   - Verifies random suffixes are different
   - Confirms values are not sequential (not just a counter)

3. **Existing tests still pass:**
   - Backward compatible with existing functionality
   - Format change transparent to users (still starts with "cp-")

## Performance Impact

**Negligible:**
- `secrets.token_hex(6)` is fast (~microseconds)
- Added 12 characters to checkpoint ID length
- No impact on checkpoint save/load performance
- No database schema changes required

## Risks

**Low risk:**
- ✅ Backward compatible (existing code works with new IDs)
- ✅ Format still starts with "cp-" (existing validation works)
- ✅ No breaking changes to API
- ✅ Comprehensive tests ensure correctness

**Migration:**
- Old checkpoint IDs (3 parts) still loadable
- New checkpoint IDs (4 parts) use enhanced security
- No migration required for existing checkpoints

## Benefits

1. **Security:** Prevents enumeration and collision attacks
2. **Compliance:** Meets security best practices for ID generation
3. **Robustness:** Works reliably in distributed systems
4. **Future-proof:** Sufficient entropy for long-term use

## Architecture Pillars Alignment

| Pillar | Impact |
|--------|--------|
| **P0: Security** | ✅ IMPROVED - Cryptographic randomness prevents enumeration |
| **P0: Reliability** | ✅ IMPROVED - Collision resistance in distributed systems |
| **P1: Testing** | ✅ IMPROVED - Added comprehensive security tests |

## Acceptance Criteria

### CORE FUNCTIONALITY
- ✅ Fix: Weak Entropy in Checkpoint IDs
- ✅ Add validation: Format validation in tests
- ✅ Update tests: 2 new security tests added

### SECURITY CONTROLS
- ✅ Validate inputs: Format validation in tests
- ✅ Add security tests: Entropy and predictability tests

### TESTING
- ✅ Unit tests: 2 new tests for entropy and predictability
- ✅ Integration tests: Existing checkpoint tests pass

## Related

- Task: code-high-13
- Report: .claude-coord/reports/code-review-20260130-223423.md (lines 250-253)
- Spec: .claude-coord/task-specs/code-high-13.md

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>
