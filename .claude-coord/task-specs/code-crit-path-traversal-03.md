# Task: Fix path traversal vulnerabilities across modules

## Summary

Fix path traversal vulnerabilities in multiple modules by adding URL decoding, symlink validation, and TOCTOU race protection. Current implementation can be bypassed using URL encoding (%2e%2e), symlinks to sensitive directories, and race conditions between validation and file access.

**Estimated Effort:** 6.0 hours
**Module:** Multiple

---

## Files to Create

_None_

---

## Files to Modify

- `src/tools/base.py` - Enhance ParameterSanitizer.sanitize_path()
- `src/safety/rollback.py` - Add path validation in FileRollbackStrategy
- `src/utils/path_safety.py` - Fix TOCTOU race, symlink handling, encoded paths

---

## Acceptance Criteria

### Core Functionality
- [ ] Decode URL encoding before validation
- [ ] Handle symlinks securely (don't follow or validate target)
- [ ] Use content hashing to prevent TOCTOU
- [ ] Validate resolved paths against allowed directories
- [ ] Centralize all path validation using PathSafetyValidator

### Security Controls
- [ ] Block ../, %2e%2e, Unicode variants (U+2024, U+FF0E)
- [ ] Block symlinks or validate their targets
- [ ] Block UNC paths (\\server\share) and alternate data streams (file.txt:stream)
- [ ] Block absolute paths outside allowed directories
- [ ] Verify file integrity with SHA256 hashing

### Testing
- [ ] Test URL-encoded traversal attempts (%2e%2e%2f)
- [ ] Test symlink attacks (symlink to /etc/passwd)
- [ ] Test Windows-specific paths (UNC, ADS)
- [ ] Test TOCTOU race conditions (concurrent access)
- [ ] Test Unicode path variants

---

## Implementation Details

```python
import urllib.parse
import hashlib
from pathlib import Path
from typing import Tuple

class PathSafetyValidator:
    def __init__(self, allowed_dirs: list[Path]):
        self.allowed_dirs = [d.resolve() for d in allowed_dirs]

    def validate_path(self, path_str: str) -> Tuple[Path, str]:
        """
        Validate path and return (resolved_path, content_hash).

        Args:
            path_str: Path to validate (may be URL-encoded)

        Returns:
            (resolved_path, sha256_hash) if valid

        Raises:
            SecurityError: If path is invalid or dangerous
        """
        # 1. Decode URL encoding
        decoded = urllib.parse.unquote(path_str)

        # 2. Check for dangerous patterns BEFORE resolution
        dangerous = ['..', '%2e', '%2E', '\x00', '\\\\', ':']  # UNC, ADS
        if any(d in decoded for d in dangerous):
            raise SecurityError(f"Dangerous path pattern: {decoded}")

        # 3. Convert to Path and check symlinks
        p = Path(decoded)
        if p.is_symlink():
            # Option 1: Block all symlinks
            raise SecurityError("Symlinks not allowed")
            # Option 2: Validate symlink target
            # target = p.readlink()
            # return self.validate_path(str(target))

        # 4. Resolve path
        try:
            resolved = p.resolve(strict=True)
        except (OSError, RuntimeError):
            raise SecurityError(f"Cannot resolve path: {decoded}")

        # 5. Validate against allowed directories
        if not any(self._is_subpath(resolved, allowed)
                   for allowed in self.allowed_dirs):
            raise SecurityError(f"Path outside allowed directories: {resolved}")

        # 6. Compute content hash to prevent TOCTOU
        if resolved.is_file():
            content_hash = self._hash_file(resolved)
        else:
            content_hash = None

        return resolved, content_hash

    def _is_subpath(self, path: Path, parent: Path) -> bool:
        """Check if path is under parent directory"""
        try:
            path.relative_to(parent)
            return True
        except ValueError:
            return False

    def _hash_file(self, path: Path) -> str:
        """Compute SHA256 hash of file content"""
        sha256 = hashlib.sha256()
        with open(path, 'rb') as f:
            while chunk := f.read(8192):
                sha256.update(chunk)
        return sha256.hexdigest()

    def verify_integrity(self, path: Path, expected_hash: str) -> bool:
        """Verify file hasn't been modified since validation"""
        if not path.is_file():
            return False
        current_hash = self._hash_file(path)
        return current_hash == expected_hash
```

**Integration:** Replace all direct Path() usage with PathSafetyValidator.validate_path()

---

## Test Strategy

1. **URL Encoding Tests:**
   - `..%2f..%2fetc%2fpasswd` → blocked
   - `%2e%2e%2f%2e%2e%2f` → blocked
   - Double encoding: `%252e%252e` → blocked

2. **Symlink Tests:**
   - Create symlink to /etc/passwd → blocked
   - Create symlink chain → blocked
   - Test with relative symlinks → validated

3. **TOCTOU Race Tests:**
   ```python
   # Thread 1: validate path
   path, hash1 = validator.validate_path("file.txt")

   # Thread 2: modify file
   open("file.txt", "w").write("malicious")

   # Thread 1: verify integrity before access
   if validator.verify_integrity(path, hash1):
       # Safe to read
   ```

4. **Windows-Specific Tests:**
   - `\\server\share` → blocked
   - `C:\file.txt:stream` → blocked

---

## Success Metrics

- [ ] No path traversal possible (0 bypasses)
- [ ] Encoded paths blocked (100% detection)
- [ ] Symlink attacks prevented
- [ ] TOCTOU races eliminated
- [ ] Windows paths handled correctly

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** ParameterSanitizer, FileRollbackStrategy, PathSafetyValidator

---

## Design References

- `.claude-coord/reports/code-review-20260128-224245.md#3-path-traversal`

---

## Notes

**Critical** - Affects multiple modules, can expose sensitive files. Attackers can:
- Read /etc/passwd, /etc/shadow, SSH keys
- Access cloud credentials (~/.aws/credentials)
- Overwrite system files
- Bypass access controls

**Key Fixes:**
1. URL decode BEFORE validation
2. Handle symlinks (block or validate target)
3. Use content hashing for TOCTOU protection
4. Centralize validation logic
