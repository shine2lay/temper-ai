# Task Specification: code-crit-redis-password-07

## Problem Statement

Redis password is passed as constructor parameter in `LLMCache.__init__()`, which means it may appear in:
- Log messages (object repr)
- Stack traces (exception handling)
- Process listings (`ps aux`, `/proc/<pid>/cmdline`)
- Monitoring systems (APM tools)
- Memory dumps

This creates credential exposure risk. Passwords should be loaded from environment variables or secure secret stores, never passed as function parameters or stored in code.

## Context

- **Source:** Code Review Report 2026-02-01 (Critical Issue #7)
- **File Affected:** `src/cache/llm_cache.py:248`
- **Impact:** Credential exposure in logs, monitoring, stack traces
- **Module:** Cache
- **OWASP Category:** A07:2021 - Identification and Authentication Failures

## Acceptance Criteria

### CORE FUNCTIONALITY
- [ ] Remove `password` parameter from constructor
- [ ] Load Redis password from environment variable
- [ ] Support fallback to no password (local development)
- [ ] Ensure password never appears in logs or repr

### SECURITY CONTROLS
- [ ] Password loaded from `REDIS_PASSWORD` env var
- [ ] No password in constructor parameters
- [ ] No password in instance variables (store connection only)
- [ ] Custom `__repr__` to prevent accidental logging
- [ ] Connection string doesn't expose password

### BACKWARD COMPATIBILITY
- [ ] Provide migration guide for existing code
- [ ] Deprecation warning if password passed to constructor
- [ ] Clear error message if REDIS_PASSWORD not set (when needed)

### TESTING
- [ ] Test with environment variable set
- [ ] Test with no password (local Redis)
- [ ] Test repr doesn't expose password
- [ ] Test connection works correctly
- [ ] Test error handling for missing env var

## Implementation Plan

### Step 1: Read Current Implementation

**File:** `src/cache/llm_cache.py:248`

```bash
grep -B 5 -A 20 "class LLMCache" src/cache/llm_cache.py
```

### Step 2: Remove Password Parameter

**File:** `src/cache/llm_cache.py`

**Before (INSECURE):**
```python
import redis

class LLMCache:
    def __init__(self, host: str = "localhost", port: int = 6379, db: int = 0, password: str = None):
        """
        Initialize LLM cache with Redis connection.

        Args:
            password: Redis password (INSECURE - visible in logs)
        """
        self._client = redis.Redis(
            host=host,
            port=port,
            db=db,
            password=password  # INSECURE
        )
```

**After (SECURE):**
```python
import redis
import os
import logging

logger = logging.getLogger(__name__)

class LLMCache:
    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        password: str = None  # Deprecated, use REDIS_PASSWORD env var
    ):
        """
        Initialize LLM cache with Redis connection.

        Redis password is loaded from REDIS_PASSWORD environment variable
        for security. Passing password as parameter is deprecated.

        Args:
            host: Redis host
            port: Redis port
            db: Redis database number
            password: (DEPRECATED) Use REDIS_PASSWORD env var instead

        Environment Variables:
            REDIS_PASSWORD: Redis password (required for authenticated Redis)

        Raises:
            ValueError: If password is required but not provided via env var
        """
        # Handle deprecated password parameter
        if password is not None:
            import warnings
            warnings.warn(
                "Passing password to LLMCache() is deprecated. "
                "Use REDIS_PASSWORD environment variable instead.",
                DeprecationWarning,
                stacklevel=2
            )
            logger.warning("Redis password passed as parameter (deprecated)")
            redis_password = password
        else:
            # Load from environment (secure approach)
            redis_password = os.getenv('REDIS_PASSWORD')

        # Create Redis connection
        try:
            self._client = redis.Redis(
                host=host,
                port=port,
                db=db,
                password=redis_password,  # May be None for local dev
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
            )

            # Test connection
            self._client.ping()
            logger.info(f"Connected to Redis at {host}:{port}/{db}")

        except redis.AuthenticationError:
            raise ValueError(
                "Redis authentication failed. Set REDIS_PASSWORD environment variable "
                "or ensure Redis doesn't require authentication."
            )
        except redis.ConnectionError as e:
            raise ValueError(f"Failed to connect to Redis at {host}:{port}: {e}")

    def __repr__(self) -> str:
        """
        Safe repr that doesn't expose credentials.
        """
        # Don't include password or connection details
        return f"LLMCache(connected={self._client.ping() if self._client else False})"

    def __str__(self) -> str:
        """Safe string representation"""
        return self.__repr__()
```

### Step 3: Update Documentation

**File:** `README.md` or `docs/cache.md`

Add documentation:
```markdown
## Redis Configuration

### Environment Variables

- `REDIS_PASSWORD`: Redis authentication password (required for authenticated instances)
- `REDIS_HOST`: Redis host (default: localhost)
- `REDIS_PORT`: Redis port (default: 6379)
- `REDIS_DB`: Redis database number (default: 0)

### Example

```bash
# Set Redis password securely
export REDIS_PASSWORD="your-secure-password"

# Run application
python app.py
```

### Local Development (No Password)

For local Redis without authentication:
```bash
# Don't set REDIS_PASSWORD (or set it to empty string)
python app.py
```

### Docker Compose

```yaml
services:
  app:
    environment:
      - REDIS_PASSWORD=${REDIS_PASSWORD}  # Load from .env file
```
```

### Step 4: Update All Usage Sites

```bash
grep -r "LLMCache(" src/
```

Remove any password parameters passed to constructor.

**Migration:**
```python
# Old (INSECURE)
cache = LLMCache(password="secret123")

# New (SECURE)
# Set environment variable first
os.environ['REDIS_PASSWORD'] = "secret123"  # Or load from secret manager
cache = LLMCache()
```

## Test Strategy

### Unit Tests

**File:** `tests/cache/test_llm_cache_security.py`

```python
import pytest
import os
from unittest.mock import patch, MagicMock
from src.cache.llm_cache import LLMCache

def test_password_loaded_from_env_var(monkeypatch):
    """Test that password is loaded from environment"""
    monkeypatch.setenv('REDIS_PASSWORD', 'test-password')

    with patch('redis.Redis') as mock_redis:
        mock_client = MagicMock()
        mock_redis.return_value = mock_client

        cache = LLMCache()

        # Verify Redis was called with password from env
        mock_redis.assert_called_once()
        call_kwargs = mock_redis.call_args.kwargs
        assert call_kwargs['password'] == 'test-password'

def test_no_password_for_local_dev(monkeypatch):
    """Test that local Redis without password works"""
    # Ensure REDIS_PASSWORD is not set
    monkeypatch.delenv('REDIS_PASSWORD', raising=False)

    with patch('redis.Redis') as mock_redis:
        mock_client = MagicMock()
        mock_redis.return_value = mock_client

        cache = LLMCache()

        # Verify Redis was called with password=None
        call_kwargs = mock_redis.call_args.kwargs
        assert call_kwargs['password'] is None

def test_deprecated_password_parameter_shows_warning():
    """Test that passing password shows deprecation warning"""
    with patch('redis.Redis') as mock_redis:
        mock_client = MagicMock()
        mock_redis.return_value = mock_client

        with pytest.warns(DeprecationWarning, match="deprecated"):
            cache = LLMCache(password="old-style")

def test_repr_does_not_expose_password(monkeypatch):
    """Test that repr/str don't leak credentials"""
    monkeypatch.setenv('REDIS_PASSWORD', 'secret-password-123')

    with patch('redis.Redis') as mock_redis:
        mock_client = MagicMock()
        mock_client.ping.return_value = True
        mock_redis.return_value = mock_client

        cache = LLMCache()

        # Check repr and str don't contain password
        repr_str = repr(cache)
        str_str = str(cache)

        assert 'secret-password-123' not in repr_str
        assert 'secret-password-123' not in str_str
        assert 'password' not in repr_str.lower()

def test_auth_error_provides_helpful_message(monkeypatch):
    """Test that auth failure has clear error message"""
    monkeypatch.delenv('REDIS_PASSWORD', raising=False)

    with patch('redis.Redis') as mock_redis:
        import redis as redis_module
        mock_redis.return_value.ping.side_effect = redis_module.AuthenticationError()

        with pytest.raises(ValueError, match="REDIS_PASSWORD environment variable"):
            cache = LLMCache()

def test_connection_error_provides_helpful_message():
    """Test that connection failure has clear error message"""
    with patch('redis.Redis') as mock_redis:
        import redis as redis_module
        mock_redis.return_value.ping.side_effect = redis_module.ConnectionError("Connection refused")

        with pytest.raises(ValueError, match="Failed to connect"):
            cache = LLMCache()
```

### Integration Tests

**File:** `tests/cache/test_llm_cache_integration.py`

```python
import pytest
import os

@pytest.mark.integration
def test_real_redis_connection_with_env_var():
    """Integration test with real Redis (requires test instance)"""
    if 'REDIS_PASSWORD' not in os.environ:
        pytest.skip("REDIS_PASSWORD not set")

    cache = LLMCache()

    # Test basic operations work
    cache.set("test-key", "test-value")
    assert cache.get("test-key") == "test-value"
```

## Security Considerations

**Why Environment Variables:**
- Not visible in logs (unless explicitly logged)
- Not in stack traces
- Not in process arguments
- Can be managed by secret management systems
- Can be rotated without code changes

**Best Practices:**
- Use secret management (AWS Secrets Manager, HashiCorp Vault, etc.)
- Rotate credentials regularly
- Use least-privilege Redis user (not admin)
- Enable Redis AUTH and TLS

**Defense in Depth:**
- ✅ Load from environment (this task)
- ✅ No password in logs (custom repr)
- 🔄 Consider: Integrate with secret manager (future)
- 🔄 Consider: Redis TLS (separate task)

## Error Handling

**Clear error messages:**
```python
# Good: Actionable
raise ValueError("Set REDIS_PASSWORD environment variable")

# Bad: Vague
raise Exception("Auth failed")
```

## Success Metrics

- [ ] No password parameters in code
- [ ] Environment variable approach works
- [ ] Deprecation warnings for old code
- [ ] repr/str don't leak passwords
- [ ] All tests pass
- [ ] Documentation updated
- [ ] Security audit approves

## Dependencies

**Blocked by:** None

**Blocks:** None (can be done in parallel)

**Related:** code-crit-redis-flush-08 (both Redis cache security issues)

## References

- Code Review Report: `.claude-coord/reports/code-review-20260201-002732.md` (lines 174-189)
- OWASP Secrets Management: https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html
- Twelve-Factor App: https://12factor.net/config

## Estimated Effort

**Time:** 2-3 hours
**Complexity:** Low-Medium (straightforward change, testing is important)

---

*Priority: CRITICAL (0)*
*Category: Security (Credential Management)*
