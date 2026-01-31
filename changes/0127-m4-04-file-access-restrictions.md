# M4-04: File & Directory Access Restrictions

**Date:** 2026-01-27
**Task:** m4-04
**Type:** Feature - Safety System (P0 Security)
**Impact:** Critical - Prevents unauthorized file system access

## Summary

Implemented comprehensive file and directory access restrictions policy for the M4 safety system. Provides allowlist/denylist modes, path traversal prevention, forbidden directory protection, and pattern-based access control.

## Problem Statement

The safety system needed:
- **Access control** to prevent unauthorized file system access
- **Path traversal prevention** to block ../ attacks
- **System directory protection** (/etc, /sys, /proc, etc.)
- **Secrets protection** (.env files, SSH keys, credentials)
- **Flexible configuration** supporting both allowlist and denylist modes
- **Pattern matching** for complex access rules (wildcards, recursive patterns)

## Solution Overview

Created `FileAccessPolicy` with:
1. **Dual-mode operation**: Allowlist (explicit permissions) or Denylist (explicit denials)
2. **Multi-layer protection**: Path traversal → Forbidden files → Forbidden dirs → Forbidden extensions → Allow/Deny rules
3. **Pattern matching**: Supports wildcards (*), recursive wildcards (**), and directory prefixes
4. **Security defaults**: Blocks system directories and sensitive files by default
5. **Configurable restrictions**: Absolute paths, symlinks, parent traversal, file extensions

### Security Layers

```
File Access Request
    ↓
[1] Path Traversal Check (../)
    ↓
[2] Absolute Path Check
    ↓
[3] Forbidden Files Check (/.env, /etc/passwd, etc.)
    ↓
[4] Forbidden Directories Check (/etc, /sys, /root, etc.)
    ↓
[5] Forbidden Extensions Check (.pem, .key, etc.)
    ↓
[6] Allowlist/Denylist Rules
    ↓
Allow or Deny
```

## Changes

### 1. New Module: src/safety/file_access.py

**Purpose:** File and directory access restriction policy

**Key Class: FileAccessPolicy**

```python
class FileAccessPolicy(BaseSafetyPolicy):
    """Enforces file and directory access restrictions.

    Configuration:
        allowed_paths: Allowlist patterns (if set, enables allowlist mode)
        denied_paths: Denylist patterns (default mode)
        allow_parent_traversal: Allow ../ (default: False)
        allow_symlinks: Allow symlink following (default: False)
        allow_absolute_paths: Allow absolute paths (default: True)
        forbidden_extensions: Additional forbidden extensions
        forbidden_directories: Additional forbidden directories
        case_sensitive: Case-sensitive matching (default: True)
    """
```

**Features:**

#### Path Traversal Prevention
```python
# Blocks any path containing ../
"/project/../etc/passwd"  # BLOCKED
"../../secrets/key.pem"   # BLOCKED
```

#### Forbidden Directories (Defaults)
```python
DEFAULT_FORBIDDEN_DIRS = {
    "/etc",      # System configuration
    "/sys",      # Kernel interface
    "/proc",     # Process information
    "/dev",      # Device files
    "/boot",     # Boot files
    "/root",     # Root home directory
    "/.ssh",     # SSH keys
    "/.aws",     # AWS credentials
    "/.gcp",     # GCP credentials
    "/.azure",   # Azure credentials
}
```

#### Forbidden Files (Defaults)
```python
DEFAULT_FORBIDDEN_FILES = {
    "/.env",
    "/.env.local",
    "/.env.production",
    "/etc/passwd",
    "/etc/shadow",
    "/etc/sudoers",
    "/.bashrc",
    "/.bash_profile",
    "/.zshrc",
}
```

#### Forbidden Extensions (Defaults)
```python
DEFAULT_FORBIDDEN_EXTENSIONS = {
    ".pem",    # PEM certificates
    ".key",    # Private keys
    ".p12",    # PKCS#12 certificates
    ".pfx",    # PFX certificates
    ".crt",    # Certificate files
    ".cer",    # Certificate files
}
```

#### Pattern Matching

Supports flexible pattern matching:

**Exact Match:**
```python
allowed_paths = ["/project/src/main.py"]
# Only /project/src/main.py is allowed
```

**Wildcard (*) - Single Level:**
```python
allowed_paths = ["/project/*.py"]
# Matches: /project/main.py, /project/utils.py
# Doesn't match: /project/src/main.py (nested)
```

**Recursive Wildcard (**) - Multiple Levels:**
```python
allowed_paths = ["/project/**/*.py"]
# Matches: /project/main.py
#          /project/src/main.py
#          /project/src/utils/helper.py
```

**Directory Prefix (trailing /):**
```python
allowed_paths = ["/project/src/"]
# Matches everything under /project/src/
```

#### Dual-Mode Operation

**Allowlist Mode (Explicit Permissions):**
```python
config = {
    "allowed_paths": ["/project/**", "/tmp/**"]
}
policy = FileAccessPolicy(config)

# Allowed:
#   /project/src/main.py
#   /tmp/cache.json
# Denied:
#   /etc/passwd (not in allowlist)
#   /home/user/data.txt (not in allowlist)
```

**Denylist Mode (Explicit Denials):**
```python
config = {
    "denied_paths": ["/secrets/**", "/private/**"]
}
policy = FileAccessPolicy(config)

# Allowed:
#   /project/main.py (not in denylist, not forbidden)
#   /home/user/data.txt
# Denied:
#   /secrets/api_key.txt (in denylist)
#   /etc/passwd (forbidden by default)
```

### 2. Core Methods

#### _validate_impl()
Main validation logic that checks paths through all security layers:
1. Extract paths from action
2. Normalize paths
3. Check path traversal
4. Check absolute path restrictions
5. Check forbidden files
6. Check forbidden directories
7. Check forbidden extensions
8. Apply allowlist/denylist rules

#### _extract_paths()
Extracts file paths from action dictionary:
- Single path: `action["path"]`
- Multiple paths: `action["paths"]`
- Source/destination: `action["source"]`, `action["destination"]`

#### _matches_pattern()
Pattern matching with regex conversion:
- `**` → `(?:.*/)?` (optional path segments)
- `*` → `[^/]*` (characters without slashes)
- Handles wildcards, recursive wildcards, directory prefixes

#### Security Checks
- `_has_parent_traversal()`: Detects ../ in paths
- `_is_forbidden_file()`: Checks against forbidden file list
- `_is_forbidden_directory()`: Checks if path is under forbidden directory
- `_has_forbidden_extension()`: Checks file extension
- `_is_allowed()`: Allowlist pattern matching
- `_is_denied()`: Denylist pattern matching

### 3. Updated: src/safety/__init__.py

**Changes:** Added FileAccessPolicy export

```python
from src.safety.file_access import FileAccessPolicy

__all__ = [
    # ... existing exports ...
    "FileAccessPolicy",
]
```

## Testing

### Test Coverage

**File:** `tests/safety/test_file_access.py` (50 tests)

**Test Categories:**

1. **Basic Tests (4 tests)**
   - Default initialization
   - Allowlist mode setup
   - Denylist mode setup
   - Forbidden defaults verification

2. **Path Traversal Prevention (4 tests)**
   - Block ../ by default
   - Multiple parent references
   - Configurable traversal permission
   - Dot-dot in filenames

3. **Forbidden Directories (6 tests)**
   - /etc/ protection
   - /sys/ protection
   - /proc/ protection
   - /root/ protection
   - Custom forbidden directories
   - Subdirectory protection

4. **Forbidden Files (4 tests)**
   - .env files blocked
   - /etc/passwd blocked
   - /etc/shadow blocked
   - Relative path handling

5. **Forbidden Extensions (4 tests)**
   - .pem files blocked
   - .key files blocked
   - Custom extensions
   - Case-insensitive matching

6. **Allowlist Mode (6 tests)**
   - Exact path matching
   - Not in allowlist blocked
   - Wildcard patterns
   - Recursive wildcard patterns
   - Directory prefix matching
   - Multiple allowed paths

7. **Denylist Mode (3 tests)**
   - Denied paths blocked
   - Not in denylist allowed
   - Wildcard matching

8. **Absolute/Relative Paths (3 tests)**
   - Absolute paths by default
   - Blocking absolute paths
   - Relative path support

9. **Batch Operations (3 tests)**
   - Multiple paths validation
   - Batch with violations
   - Source/destination paths

10. **Case Sensitivity (2 tests)**
    - Case-sensitive by default
    - Case-insensitive mode

11. **Complex Scenarios (3 tests)**
    - Strict project isolation
    - Read-only access patterns
    - Temporary file access

12. **Violation Metadata (3 tests)**
    - Path in metadata
    - Violation type in metadata
    - Remediation hints

13. **Edge Cases (5 tests)**
    - Empty paths
    - Root path
    - Actions without paths
    - Special characters
    - Unicode paths

### Test Results

```
tests/safety/test_file_access.py: 50 passed
All safety tests: 155 passed
```

### Coverage Metrics

```
src/safety/file_access.py:     96% coverage (133 lines, 5 missed)
tests/safety/test_file_access.py: 600+ lines of test code
```

**Coverage exceeds >90% requirement** ✅

## Usage Examples

### Example 1: Strict Project Isolation

```python
from src.safety.file_access import FileAccessPolicy

# Restrict agent to project directory only
config = {
    "allowed_paths": ["/home/user/project/**"],
    "allow_parent_traversal": False,
    "allow_symlinks": False
}
policy = FileAccessPolicy(config)

# Allowed
result = policy.validate(
    action={"operation": "read", "path": "/home/user/project/src/main.py"},
    context={"agent": "coder"}
)
assert result.valid

# Blocked - path traversal
result = policy.validate(
    action={"operation": "read", "path": "/home/user/project/../.ssh/id_rsa"},
    context={"agent": "coder"}
)
assert not result.valid  # Path traversal detected

# Blocked - outside project
result = policy.validate(
    action={"operation": "read", "path": "/etc/passwd"},
    context={"agent": "coder"}
)
assert not result.valid  # Not in allowlist
```

### Example 2: Temporary Files Only

```python
# Allow access only to temporary directories
config = {
    "allowed_paths": ["/tmp/**", "/var/tmp/**"]
}
policy = FileAccessPolicy(config)

# Allowed
result = policy.validate(
    action={"operation": "write", "path": "/tmp/output.txt"},
    context={}
)
assert result.valid

# Blocked
result = policy.validate(
    action={"operation": "write", "path": "/home/user/output.txt"},
    context={}
)
assert not result.valid
```

### Example 3: Block Secrets and Credentials

```python
# Deny access to secrets directories
config = {
    "denied_paths": ["/secrets/**", "/credentials/**"],
    "forbidden_extensions": [".secret", ".private"]
}
policy = FileAccessPolicy(config)

# Blocked - in denylist
result = policy.validate(
    action={"operation": "read", "path": "/secrets/api_key.txt"},
    context={}
)
assert not result.valid

# Blocked - forbidden extension
result = policy.validate(
    action={"operation": "read", "path": "/data/config.secret"},
    context={}
)
assert not result.valid

# Allowed
result = policy.validate(
    action={"operation": "read", "path": "/data/config.json"},
    context={}
)
assert result.valid
```

### Example 4: Batch File Operations

```python
config = {
    "allowed_paths": ["/project/**"]
}
policy = FileAccessPolicy(config)

# Validate multiple paths at once
result = policy.validate(
    action={
        "operation": "batch_read",
        "paths": [
            "/project/src/main.py",
            "/project/src/utils.py",
            "/project/tests/test_main.py"
        ]
    },
    context={}
)

assert result.valid
assert result.metadata["paths_checked"] == 3
```

### Example 5: Copy/Move Operations

```python
config = {
    "allowed_paths": ["/project/**"]
}
policy = FileAccessPolicy(config)

# Validate both source and destination
result = policy.validate(
    action={
        "operation": "copy",
        "source": "/project/data.txt",
        "destination": "/project/backup/data.txt"
    },
    context={}
)

assert result.valid
assert result.metadata["paths_checked"] == 2  # Both paths checked
```

## Design Decisions

### 1. Allowlist vs Denylist Modes

**Rationale:**
- **Allowlist (more secure)**: Default deny, explicit allow
- **Denylist (more flexible)**: Default allow, explicit deny
- Auto-detect mode based on configuration
- Allowlist recommended for production

### 2. Multi-Layer Security

**Rationale:**
- Defense in depth - multiple checks catch different attack vectors
- Ordered checks (traversal first, then forbidden, then rules) for performance
- Each check can short-circuit to deny

### 3. Default Forbidden Paths

**Rationale:**
- Sane security defaults protect common sensitive locations
- Users can extend defaults without disabling protection
- Covers Linux, macOS, and common cloud credential locations

### 4. Pattern Matching with Regex

**Rationale:**
- Glob patterns are familiar to users
- Regex conversion enables complex matching
- Non-greedy matching (.*?) prevents over-matching
- Placeholder technique avoids replacement conflicts

### 5. Case Sensitivity Control

**Rationale:**
- Linux/macOS are case-sensitive by default
- Windows compatibility via case-insensitive mode
- Explicit configuration prevents surprises

### 6. Highest Priority (95)

**Rationale:**
- File access is a critical security control
- Should execute before other policies
- Blast radius (90) runs after to check scope

## Security Analysis

### Attack Vectors Mitigated

✅ **Path Traversal**: `..` / detection prevents directory escape
✅ **Absolute Path Abuse**: Optional restriction to relative paths only
✅ **System File Access**: Default blocks /etc, /sys, /proc, /dev, /boot, /root
✅ **Credential Theft**: Blocks .env, .ssh, .aws, .gcp, .azure
✅ **Certificate Extraction**: Blocks .pem, .key, .p12, .pfx, .crt, .cer
✅ **Config File Tampering**: Protects /etc/passwd, /etc/shadow, /etc/sudoers

### Defense in Depth

Multiple layers ensure comprehensive protection:
1. **Path traversal check** catches escape attempts
2. **Forbidden file check** protects specific sensitive files
3. **Forbidden directory check** protects entire directory trees
4. **Forbidden extension check** protects file types
5. **Allowlist/denylist rules** provide flexible policy enforcement

### Known Limitations

⚠️ **Symlink Following**: Policy doesn't resolve symlinks (relies on OS/runtime)
⚠️ **Time-of-Check vs Time-of-Use (TOCTOU)**: Gap between validation and access
⚠️ **Case Sensitivity**: Default case-sensitive may miss variants on case-insensitive systems

**Mitigations:**
- `allow_symlinks=False` documents restriction
- TOCTOU minimized by immediate validation
- Case-insensitive mode available for Windows

## Integration with Other Components

### With Exceptions (M4-03)

```python
from src.safety.exceptions import AccessDeniedViolation

class FileAccessPolicy(BaseSafetyPolicy):
    def _validate_impl(self, action, context):
        # ... validation logic ...

        if not_allowed:
            # Create exception for integration
            exc = AccessDeniedViolation(
                policy_name=self.name,
                message=f"Access denied to {path}",
                action=str(action),
                context=context,
                metadata={"path": path}
            )
            # Report and return violation
            self.report_violation(exc.violation)
            return ValidationResult(
                valid=False,
                violations=[exc.violation],
                policy_name=self.name
            )
```

### With Observability (M1)

Violations automatically reported to observability system via `report_violation()`:

```python
{
    "policy_name": "file_access",
    "severity": "CRITICAL",
    "message": "Access to forbidden directory: /etc/passwd",
    "action": "read_file",
    "context": {"agent": "researcher", "stage": "research"},
    "timestamp": "2026-01-27T...",
    "metadata": {
        "path": "/etc/passwd",
        "violation": "forbidden_directory"
    }
}
```

## Files Modified

### Created
- `src/safety/file_access.py` (493 lines, 96% coverage)
- `tests/safety/test_file_access.py` (600+ lines, 50 tests)

### Modified
- `src/safety/__init__.py` (+1 import, +1 export)

### Test Results
- **New Tests:** 50
- **Total Safety Tests:** 155
- **All Passed:** ✅
- **Coverage:** 96% (src/safety/file_access.py)

## Acceptance Criteria

✅ **File access policy with allowlist/denylist**
- Both modes implemented
- Auto-detection based on config
- Pattern matching with wildcards

✅ **Forbidden paths protection**
- Default forbidden directories (/etc, /sys, /proc, /root, etc.)
- Default forbidden files (/.env, /etc/passwd, etc.)
- Default forbidden extensions (.pem, .key, etc.)
- Customizable extensions

✅ **Path traversal prevention**
- Detects ../ in paths
- Blocks by default
- Configurable override

✅ **Pattern matching**
- Wildcards (*) for single level
- Recursive wildcards (**) for multiple levels
- Directory prefix matching (/)
- Exact path matching

✅ **Comprehensive tests with >90% coverage**
- 50 tests covering all features
- 96% code coverage
- All tests passing

## Next Steps

### Immediate
- **m4-05:** Rate Limiting Service (uses RateLimitViolation)
- **m4-06:** Resource Consumption Limits (uses ResourceLimitViolation)
- **m4-07:** Forbidden Operations (uses ForbiddenOperationViolation)
- **m4-08:** Action Policy Engine (composes all policies)

### Future Enhancements
1. **Symlink Resolution**: Resolve and validate symlink targets
2. **Real-Time Monitoring**: Track file access patterns
3. **Anomaly Detection**: Machine learning for unusual access patterns
4. **Audit Logging**: Detailed access logs for compliance
5. **Performance Optimization**: Cache pattern matching results

## Documentation

**Module Docstrings:** Comprehensive with examples
**Class Docstrings:** Complete configuration guide
**Method Docstrings:** Full parameter and return descriptions
**Usage Examples:** 5 real-world scenarios documented

## Deployment Notes

### Backward Compatibility
✅ Fully backward compatible
- New policy, no existing dependencies
- Opt-in usage
- No breaking changes

### Configuration Recommendations

**Development:**
```python
config = {
    "allowed_paths": ["/project/**", "/tmp/**"],
    "allow_parent_traversal": False
}
```

**Production:**
```python
config = {
    "allowed_paths": ["/app/**", "/data/**"],
    "allow_parent_traversal": False,
    "allow_symlinks": False,
    "allow_absolute_paths": True
}
```

**Testing:**
```python
config = {
    "denied_paths": [],  # Minimal restrictions
    "allow_parent_traversal": True  # If needed for test fixtures
}
```

### Performance Impact
✅ Minimal - O(n) where n = number of patterns
- Pattern matching optimized with early exits
- Regex compilation happens once per pattern
- No external I/O (doesn't check if files exist)

### Security Recommendations

1. **Use Allowlist Mode in Production**: More secure, explicit permissions
2. **Disable Parent Traversal**: Prevents directory escape attacks
3. **Review Default Forbidden Paths**: Ensure they match your environment
4. **Add Custom Forbidden Paths**: Protect application-specific sensitive locations
5. **Monitor Violations**: Set up alerts for repeated access denials

## Conclusion

FileAccessPolicy provides robust file system access control with:
- **Defense in depth** through multiple security layers
- **Flexible configuration** supporting allowlist and denylist modes
- **Pattern matching** for complex access rules
- **Security defaults** protecting common sensitive locations
- **96% test coverage** ensuring reliability

**Unblocks:**
- m4-08: Action Policy Engine (needs file access control)
- m4-14: M4 Integration (needs all policies)

**Integrates with:**
- M4-03: Exception hierarchy (AccessDeniedViolation)
- M1: Observability (violation reporting)
- M2: Base safety policy framework
