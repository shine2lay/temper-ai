# Task Specification: code-crit-md5-hash-03

## Problem Statement

Using MD5 for hash-based user assignment in experimentation creates collision vulnerabilities. Users can manipulate their assignment by finding hash collisions, compromising experiment integrity and allowing users to game the system to get preferred variants.

MD5 is cryptographically broken and collisions can be generated in seconds with modern tools.

## Context

- **Source:** Code Review Report 2026-02-01 (Critical Issue #3)
- **File Affected:** `src/experimentation/assignment.py:179`
- **Impact:** Experiment integrity compromised, unreliable A/B test results
- **Module:** Experimentation
- **OWASP Category:** A02:2021 - Cryptographic Failures

## Acceptance Criteria

### CORE FUNCTIONALITY
- [ ] Replace MD5 with SHA-256 for user assignment hashing
- [ ] Ensure hash distribution remains uniform
- [ ] Maintain backward compatibility for existing experiments (migration plan)
- [ ] Update all hash-based assignment logic

### SECURITY CONTROLS
- [ ] Use SHA-256 (FIPS 140-2 approved)
- [ ] Verify collision resistance
- [ ] Add hash algorithm version field for future migrations
- [ ] Document cryptographic rationale

### DATA MIGRATION
- [ ] Plan for existing experiment assignments (re-hash or version flag)
- [ ] Option 1: Version field to support both MD5 (legacy) and SHA-256 (new)
- [ ] Option 2: Re-hash all existing assignments (may change user buckets)
- [ ] Document migration strategy chosen

### TESTING
- [ ] Test hash distribution is uniform
- [ ] Test assignment consistency (same user → same bucket)
- [ ] Test collision resistance
- [ ] Verify experiment results are reproducible
- [ ] Test migration strategy

## Implementation Plan

### Step 1: Read Current Implementation

**File:** `src/experimentation/assignment.py:179`

```bash
grep -A 10 -B 5 "hashlib.md5" src/experimentation/assignment.py
```

### Step 2: Replace MD5 with SHA-256

**File:** `src/experimentation/assignment.py`

**Before:**
```python
import hashlib

def assign_user_to_variant(user_id: str, experiment_id: str, num_variants: int) -> int:
    hash_input = f"{experiment_id}:{user_id}"
    hash_value = int(hashlib.md5(hash_input.encode()).hexdigest(), 16)
    return hash_value % num_variants
```

**After:**
```python
import hashlib

def assign_user_to_variant(
    user_id: str,
    experiment_id: str,
    num_variants: int,
    hash_algorithm: str = 'sha256'
) -> int:
    """
    Assign user to experiment variant using consistent hashing.

    Args:
        user_id: Unique user identifier
        experiment_id: Unique experiment identifier
        num_variants: Number of variants in experiment
        hash_algorithm: Hash algorithm to use ('sha256' or 'md5' for legacy)

    Returns:
        Variant index (0 to num_variants-1)

    Note:
        SHA-256 is used by default for collision resistance.
        MD5 support is maintained for backward compatibility only.
    """
    hash_input = f"{experiment_id}:{user_id}"

    if hash_algorithm == 'sha256':
        hash_value = int(hashlib.sha256(hash_input.encode()).hexdigest(), 16)
    elif hash_algorithm == 'md5':
        # Legacy support only - will be removed in future version
        import warnings
        warnings.warn("MD5 is deprecated for experiment assignment", DeprecationWarning)
        hash_value = int(hashlib.md5(hash_input.encode()).hexdigest(), 16)
    else:
        raise ValueError(f"Unsupported hash algorithm: {hash_algorithm}")

    return hash_value % num_variants
```

### Step 3: Update Experiment Configuration

**File:** `src/experimentation/models.py` (or wherever experiments are defined)

Add `hash_algorithm` field to experiment configuration:
```python
@dataclass
class ExperimentConfig:
    id: str
    variants: List[str]
    hash_algorithm: str = 'sha256'  # Default to SHA-256 for new experiments
```

### Step 4: Migration Strategy

**Option A: Version Flag (Recommended for production)**
- Add `hash_algorithm` field to experiment records
- Existing experiments use `md5`, new experiments use `sha256`
- Allows gradual migration without disrupting running experiments

**Option B: Re-hash Everything (Simpler but disruptive)**
- Update all experiments to SHA-256
- Accept that user assignments will change
- Only viable if experiments can be restarted

Document chosen strategy in migration guide.

### Step 5: Update All Call Sites

Search for all uses of `assign_user_to_variant`:
```bash
grep -r "assign_user_to_variant" src/
```

Update to pass hash_algorithm from experiment config.

## Test Strategy

### Unit Tests

**File:** `tests/experimentation/test_assignment_security.py`

```python
import hashlib
import pytest
from src.experimentation.assignment import assign_user_to_variant

def test_sha256_assignment_consistency():
    """Test that same user gets same variant with SHA-256"""
    user_id = "user123"
    experiment_id = "exp_abc"
    num_variants = 4

    assignment1 = assign_user_to_variant(user_id, experiment_id, num_variants, 'sha256')
    assignment2 = assign_user_to_variant(user_id, experiment_id, num_variants, 'sha256')

    assert assignment1 == assignment2

def test_sha256_distribution_uniform():
    """Test that SHA-256 hash distributes users uniformly"""
    experiment_id = "exp_distribution_test"
    num_variants = 10
    num_users = 10000

    variant_counts = [0] * num_variants

    for i in range(num_users):
        variant = assign_user_to_variant(f"user{i}", experiment_id, num_variants, 'sha256')
        variant_counts[variant] += 1

    # Each variant should get ~1000 users (10000 / 10)
    # Allow 20% deviation (800-1200 users per variant)
    expected = num_users / num_variants
    for count in variant_counts:
        assert 0.8 * expected <= count <= 1.2 * expected

def test_sha256_no_collisions():
    """Test that SHA-256 is collision-resistant for typical use case"""
    experiment_id = "exp_collision_test"
    num_users = 100000
    assignments = set()

    for i in range(num_users):
        hash_input = f"{experiment_id}:user{i}"
        hash_hex = hashlib.sha256(hash_input.encode()).hexdigest()
        assignments.add(hash_hex)

    # Should have 100000 unique hashes (no collisions)
    assert len(assignments) == num_users

def test_md5_deprecated_warning():
    """Test that MD5 usage triggers deprecation warning"""
    with pytest.warns(DeprecationWarning, match="MD5 is deprecated"):
        assign_user_to_variant("user123", "exp_abc", 4, 'md5')

def test_invalid_algorithm_raises():
    """Test that invalid hash algorithm raises error"""
    with pytest.raises(ValueError, match="Unsupported hash algorithm"):
        assign_user_to_variant("user123", "exp_abc", 4, 'md4')
```

### Integration Tests

**File:** `tests/experimentation/test_experiment_migration.py`

```python
def test_legacy_md5_experiments_still_work():
    """Test backward compatibility with MD5 experiments"""
    # Create experiment with MD5
    experiment = ExperimentConfig(
        id="legacy_exp",
        variants=["control", "treatment"],
        hash_algorithm="md5"
    )

    # Should still work (with warning)
    with pytest.warns(DeprecationWarning):
        variant = assign_user_to_variant("user123", experiment.id, 2, experiment.hash_algorithm)

    assert variant in [0, 1]

def test_new_sha256_experiments():
    """Test new experiments use SHA-256 by default"""
    experiment = ExperimentConfig(
        id="new_exp",
        variants=["control", "treatment"]
        # hash_algorithm defaults to 'sha256'
    )

    variant = assign_user_to_variant("user123", experiment.id, 2, experiment.hash_algorithm)
    assert variant in [0, 1]
```

## Security Considerations

**Why SHA-256:**
- Collision resistance: No known collisions
- FIPS 140-2 approved
- Standard in industry (Bitcoin, certificates, etc.)
- Only marginally slower than MD5 (negligible for this use case)

**Threats Mitigated:**
1. **Hash collision attacks**: Users can't manipulate variant assignment
2. **Gaming experiments**: Can't choose preferred variant
3. **Data integrity**: Experiment results are trustworthy

**Security Testing:**
- [ ] Verify collision resistance with large sample
- [ ] Test that users can't predict/manipulate variant assignment
- [ ] Ensure hash algorithm can't be overridden maliciously

## Error Handling

**Scenarios:**
1. Unknown hash algorithm → Raise ValueError with clear message
2. Invalid user_id or experiment_id → Log warning, hash anyway (garbage in, consistent garbage out)
3. num_variants = 0 → Raise ValueError (division by zero)

## Success Metrics

- [ ] SHA-256 is used for all new experiments
- [ ] Legacy MD5 experiments still work (backward compatibility)
- [ ] Hash distribution is uniform (within 20% of expected)
- [ ] No collisions in realistic sample size (100k users)
- [ ] All tests pass
- [ ] Security review approves cryptographic choice

## Dependencies

**Blocked by:** None

**Blocks:** None (can be done in parallel)

**Integrates with:** Any experiment creation/update code

## References

- Code Review Report: `.claude-coord/reports/code-review-20260201-002732.md` (lines 94-107)
- OWASP Cryptographic Failures: https://owasp.org/Top10/A02_2021-Cryptographic_Failures/
- CWE-328: Use of Weak Hash
- NIST Hash Functions: https://csrc.nist.gov/projects/hash-functions

## Estimated Effort

**Time:** 3-4 hours
**Complexity:** Medium (code change is simple, migration planning is important)

---

*Priority: CRITICAL (0)*
*Category: Security & Data Integrity*
