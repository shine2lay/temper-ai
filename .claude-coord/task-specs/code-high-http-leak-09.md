# Task: Fix HTTP client memory leak

## Summary

Enforce context manager usage and add connection monitoring to prevent HTTP client memory leaks in LLMProvider. Current implementation creates httpx.Client instances without proper cleanup, causing file descriptor exhaustion and memory leaks in production.

**Estimated Effort:** 3.0 hours
**Module:** agents

---

## Files to Create

_None_

---

## Files to Modify

- `src/agents/llm_providers.py` - Enforce context manager usage, add monitoring

---

## Acceptance Criteria

### Core Functionality
- [ ] Mandate 'with' statement usage for httpx.Client
- [ ] Add warnings for unclosed clients
- [ ] Implement connection monitoring
- [ ] Add shutdown hooks

### Security Controls
- [ ] No connection leaks
- [ ] File descriptor limits respected
- [ ] Graceful shutdown

### Testing
- [ ] Test connection pool exhaustion scenarios
- [ ] Monitor file descriptors during tests (lsof)
- [ ] Test shutdown under load
- [ ] Verify warnings appear for unclosed clients

---

## Implementation Details

```python
import httpx
import weakref
import warnings
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class HTTPClientManager:
    """
    Managed HTTP client with automatic cleanup.

    Usage:
        # CORRECT - Using context manager
        with HTTPClientManager() as client:
            response = client.get("https://api.example.com")

        # WRONG - Manual management (will warn)
        manager = HTTPClientManager()
        client = manager.client  # ResourceWarning if not closed
    """

    # Track all active clients for monitoring
    _active_clients = set()

    def __init__(self, timeout: float = 30.0, max_connections: int = 100):
        self.timeout = timeout
        self.max_connections = max_connections
        self._client: Optional[httpx.Client] = None
        self._closed = False

        # Register for monitoring
        HTTPClientManager._active_clients.add(weakref.ref(self, self._cleanup_callback))

    @property
    def client(self) -> httpx.Client:
        """Get HTTP client (creates if needed)"""
        if self._client is None:
            self._client = httpx.Client(
                timeout=self.timeout,
                limits=httpx.Limits(
                    max_keepalive_connections=self.max_connections,
                    max_connections=self.max_connections * 2
                )
            )
            logger.debug(f"Created HTTP client (active: {len(HTTPClientManager._active_clients)})")
        return self._client

    def close(self):
        """Close HTTP client and release resources"""
        if self._client is not None and not self._closed:
            self._client.close()
            self._closed = True
            logger.debug("Closed HTTP client")

    def __enter__(self):
        """Context manager entry"""
        return self.client

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - always cleanup"""
        self.close()

    def __del__(self):
        """Destructor - warn if not properly closed"""
        if self._client is not None and not self._closed:
            warnings.warn(
                f"HTTPClientManager was not properly closed. "
                f"Use 'with HTTPClientManager() as client:' to ensure cleanup.",
                ResourceWarning,
                stacklevel=2
            )
            self.close()

    @staticmethod
    def _cleanup_callback(ref):
        """Callback for weakref cleanup"""
        HTTPClientManager._active_clients.discard(ref)

    @classmethod
    def get_active_count(cls) -> int:
        """Get number of active HTTP clients"""
        # Remove dead references
        cls._active_clients = {ref for ref in cls._active_clients if ref() is not None}
        return len(cls._active_clients)


class LLMProvider:
    """Base class for LLM providers with proper resource management"""

    def __init__(self):
        self._client_manager: Optional[HTTPClientManager] = None

    def _get_client(self) -> httpx.Client:
        """
        Get HTTP client (DEPRECATED - use _execute_request instead).

        This method is kept for backward compatibility but should not be used.
        Use _execute_request which handles context management automatically.
        """
        warnings.warn(
            "Direct client access is deprecated. Use _execute_request() instead.",
            DeprecationWarning,
            stacklevel=2
        )

        if self._client_manager is None:
            self._client_manager = HTTPClientManager()

        return self._client_manager.client

    def _execute_request(self, method: str, url: str, **kwargs):
        """
        Execute HTTP request with automatic resource management.

        Args:
            method: HTTP method (GET, POST, etc.)
            url: Request URL
            **kwargs: Additional request arguments

        Returns:
            httpx.Response
        """
        with HTTPClientManager() as client:
            return client.request(method, url, **kwargs)

    def close(self):
        """Close provider and cleanup resources"""
        if self._client_manager is not None:
            self._client_manager.close()

    def __enter__(self):
        """Context manager support"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager cleanup"""
        self.close()


class OpenAIProvider(LLMProvider):
    """OpenAI provider with proper resource management"""

    def generate(self, prompt: str, **kwargs):
        """Generate completion"""
        response = self._execute_request(
            "POST",
            "https://api.openai.com/v1/completions",
            json={"prompt": prompt, **kwargs}
        )
        return response.json()


class AnthropicProvider(LLMProvider):
    """Anthropic provider with proper resource management"""

    def generate(self, prompt: str, **kwargs):
        """Generate completion"""
        response = self._execute_request(
            "POST",
            "https://api.anthropic.com/v1/messages",
            json={"messages": [{"role": "user", "content": prompt}], **kwargs}
        )
        return response.json()


# Monitoring utility
def monitor_http_resources():
    """
    Monitor HTTP client resources.

    Returns:
        dict with resource usage stats
    """
    import psutil
    process = psutil.Process()

    return {
        "active_clients": HTTPClientManager.get_active_count(),
        "open_files": len(process.open_files()),
        "connections": len(process.connections()),
    }
```

**Usage:**
```python
# CORRECT - Context manager ensures cleanup
with OpenAIProvider() as provider:
    result = provider.generate("Hello")

# CORRECT - Manual cleanup
provider = OpenAIProvider()
try:
    result = provider.generate("Hello")
finally:
    provider.close()

# WRONG - No cleanup (will leak and warn)
provider = OpenAIProvider()
result = provider.generate("Hello")
# ResourceWarning: HTTPClientManager was not properly closed
```

---

## Test Strategy

1. **Connection Leak Test:**
   ```python
   import psutil

   def test_no_connection_leak():
       process = psutil.Process()
       initial_fds = len(process.open_files())

       # Create and use 1000 clients
       for _ in range(1000):
           with OpenAIProvider() as provider:
               provider.generate("test")

       final_fds = len(process.open_files())

       # Should not accumulate file descriptors
       assert final_fds - initial_fds < 10  # Allow some variance
   ```

2. **Resource Warning Test:**
   ```python
   def test_resource_warning():
       with warnings.catch_warnings(record=True) as w:
           warnings.simplefilter("always")

           # Create client without cleanup
           provider = OpenAIProvider()
           provider.generate("test")
           del provider  # Trigger __del__

           # Should warn about unclosed client
           assert len(w) == 1
           assert issubclass(w[0].category, ResourceWarning)
           assert "not properly closed" in str(w[0].message)
   ```

3. **Monitoring Test:**
   ```python
   def test_monitoring():
       initial_stats = monitor_http_resources()

       clients = []
       for _ in range(10):
           manager = HTTPClientManager()
           _ = manager.client  # Force creation
           clients.append(manager)

       current_stats = monitor_http_resources()

       # Should track active clients
       assert current_stats["active_clients"] == initial_stats["active_clients"] + 10

       # Cleanup
       for client in clients:
           client.close()
   ```

4. **Graceful Shutdown Test:**
   ```python
   def test_graceful_shutdown():
       # Start multiple concurrent requests
       providers = [OpenAIProvider() for _ in range(10)]

       # Shutdown all
       for provider in providers:
           provider.close()

       # Verify all cleaned up
       assert HTTPClientManager.get_active_count() == 0
   ```

---

## Success Metrics

- [ ] No fd leaks after 10K requests
- [ ] Warnings visible in logs for unclosed clients
- [ ] Cleanup hooks execute properly
- [ ] Monitoring shows accurate resource usage

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** LLMProvider, OpenAIProvider, AnthropicProvider

---

## Design References

- `.claude-coord/reports/code-review-20260128-224245.md#6-memory-leak-http`

---

## Notes

**High** - Resource leaks cause production crashes. Issues:
1. **File Descriptor Exhaustion:** Each unclosed client holds FDs → system limit (1024) → cannot accept connections
2. **Memory Leak:** Connection pools not released → OOM
3. **Thread Starvation:** Background cleanup threads accumulate → thread exhaustion

**Typical Production Failure:**
```
OSError: [Errno 24] Too many open files
```

**Prevention:**
- Always use context managers (`with` statement)
- Add ResourceWarning in __del__
- Monitor active client count
- Set connection pool limits
