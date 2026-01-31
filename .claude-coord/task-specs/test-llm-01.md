# Task: test-llm-01 - Add Circuit Breaker Pattern Tests

**Priority:** CRITICAL
**Effort:** 3-4 hours
**Status:** pending
**Owner:** unassigned
**Category:** LLM Provider Resilience (P0)

---

## Summary
Implement circuit breaker pattern for LLM providers to prevent cascading failures when providers are down or rate-limited.

---

## Files to Create
- `src/llm/circuit_breaker.py` - Circuit breaker implementation

---

## Files to Modify
- `tests/test_agents/test_llm_providers.py` - Add circuit breaker tests
- `src/llm/base.py` - Integrate circuit breaker
- `src/llm/ollama.py`, `openai.py`, `anthropic.py`, `vllm.py` - Add circuit breaker

---

## Acceptance Criteria

### Circuit Breaker States
- [ ] CLOSED state: Normal operation, requests pass through
- [ ] OPEN state: Failures exceeded threshold, fast-fail without calling provider
- [ ] HALF_OPEN state: Test if provider recovered, allow limited requests

### State Transitions
- [ ] CLOSED → OPEN after N consecutive failures (e.g., 5)
- [ ] OPEN → HALF_OPEN after timeout period (e.g., 60 seconds)
- [ ] HALF_OPEN → CLOSED after M successful requests (e.g., 2)
- [ ] HALF_OPEN → OPEN if test request fails

### Failure Detection
- [ ] HTTP 5xx errors trigger circuit breaker
- [ ] Connection timeouts trigger circuit breaker
- [ ] Rate limit errors (429) trigger circuit breaker
- [ ] HTTP 4xx client errors do NOT trigger (user error)

### Fast-Fail Behavior
- [ ] When OPEN, requests fail immediately with CircuitBreakerError
- [ ] No network calls made when circuit is OPEN
- [ ] Error message indicates circuit is open and retry time

### Per-Provider Isolation
- [ ] Each provider has independent circuit breaker
- [ ] Failure in Ollama doesn't affect OpenAI circuit
- [ ] Circuit state persisted across requests (in-memory OK for now)

---

## Implementation Details

```python
# src/llm/circuit_breaker.py
from enum import Enum
from dataclasses import dataclass
from typing import Callable, Any
import time
import threading

class CircuitState(Enum):
    CLOSED = "closed"  # Normal operation
    OPEN = "open"      # Failing, fast-fail
    HALF_OPEN = "half_open"  # Testing recovery

@dataclass
class CircuitBreakerConfig:
    failure_threshold: int = 5  # Failures before opening
    success_threshold: int = 2  # Successes to close from half-open
    timeout: int = 60  # Seconds before trying half-open
    
class CircuitBreaker:
    """Circuit breaker for LLM provider resilience."""
    
    def __init__(self, name: str, config: CircuitBreakerConfig = None):
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time = None
        self.lock = threading.Lock()
    
    def call(self, func: Callable, *args, **kwargs) -> Any:
        """Execute function through circuit breaker."""
        with self.lock:
            if self.state == CircuitState.OPEN:
                if self._should_attempt_reset():
                    self.state = CircuitState.HALF_OPEN
                    self.success_count = 0
                else:
                    raise CircuitBreakerError(
                        f"Circuit breaker OPEN for {self.name}. "
                        f"Retry after {self._time_until_retry():.0f}s"
                    )
        
        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure(e)
            raise
    
    def _on_success(self):
        """Handle successful call."""
        with self.lock:
            self.failure_count = 0
            
            if self.state == CircuitState.HALF_OPEN:
                self.success_count += 1
                if self.success_count >= self.config.success_threshold:
                    self.state = CircuitState.CLOSED
                    self.success_count = 0
    
    def _on_failure(self, error: Exception):
        """Handle failed call."""
        # Only count certain errors
        if not self._should_count_failure(error):
            return
        
        with self.lock:
            self.failure_count += 1
            self.last_failure_time = time.time()
            
            if self.state == CircuitState.HALF_OPEN:
                self.state = CircuitState.OPEN
            elif self.failure_count >= self.config.failure_threshold:
                self.state = CircuitState.OPEN
    
    def _should_count_failure(self, error: Exception) -> bool:
        """Determine if error should count toward circuit breaker."""
        import httpx
        
        # Network/server errors count
        if isinstance(error, (httpx.ConnectError, httpx.TimeoutException)):
            return True
        
        # HTTP 5xx and 429 count
        if isinstance(error, httpx.HTTPStatusError):
            return error.response.status_code >= 500 or error.response.status_code == 429
        
        # Client errors (4xx except 429) don't count
        return False
    
    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to try half-open."""
        if self.last_failure_time is None:
            return True
        return time.time() - self.last_failure_time >= self.config.timeout
    
    def _time_until_retry(self) -> float:
        """Seconds until circuit will try half-open."""
        if self.last_failure_time is None:
            return 0
        elapsed = time.time() - self.last_failure_time
        return max(0, self.config.timeout - elapsed)

class CircuitBreakerError(Exception):
    """Raised when circuit breaker is open."""
    pass
```

```python
# tests/test_agents/test_llm_providers.py

def test_llm_circuit_breaker_opens_after_failures():
    """Test circuit breaker opens after repeated failures."""
    llm = OllamaLLM(model="test", base_url="http://localhost:11434")
    
    # Mock repeated failures
    with patch.object(llm.client, 'post', side_effect=httpx.ConnectError("Connection refused")):
        # Trigger 5 failures
        for i in range(5):
            with pytest.raises(httpx.ConnectError):
                llm.complete("test")
        
        # Next call should fail fast with circuit breaker error
        with pytest.raises(CircuitBreakerError, match="Circuit breaker OPEN"):
            llm.complete("test")

def test_llm_circuit_breaker_half_open_recovery():
    """Test circuit breaker recovers through half-open state."""
    llm = OllamaLLM(model="test")
    breaker = llm._circuit_breaker
    
    # Open the circuit
    breaker.state = CircuitState.OPEN
    breaker.last_failure_time = time.time() - 61  # Past timeout
    
    # Mock successful response
    with patch.object(llm.client, 'post', return_value=Mock(
        status_code=200,
        json=lambda: {"response": "test"}
    )):
        # First call moves to HALF_OPEN
        llm.complete("test")
        assert breaker.state == CircuitState.HALF_OPEN
        
        # Second successful call closes circuit
        llm.complete("test")
        assert breaker.state == CircuitState.CLOSED

def test_llm_circuit_breaker_isolated_per_provider():
    """Test each provider has independent circuit breaker."""
    ollama = OllamaLLM(model="test")
    openai = OpenAILLM(model="gpt-4", api_key="test")
    
    # Fail Ollama circuit
    with patch.object(ollama.client, 'post', side_effect=httpx.ConnectError("Refused")):
        for _ in range(5):
            with pytest.raises(httpx.ConnectError):
                ollama.complete("test")
    
    # Ollama circuit should be OPEN
    assert ollama._circuit_breaker.state == CircuitState.OPEN
    
    # OpenAI circuit should still be CLOSED
    assert openai._circuit_breaker.state == CircuitState.CLOSED
```

---

## Test Strategy
- Unit test circuit breaker state machine independently
- Integration test with each LLM provider
- Test concurrent requests don't cause race conditions
- Test circuit reset after timeout

---

## Success Metrics
- [ ] Circuit breaker prevents cascading failures
- [ ] Fast-fail reduces latency when provider is down
- [ ] Circuit auto-recovers when provider is healthy
- [ ] Coverage of circuit_breaker.py >95%
- [ ] All LLM providers use circuit breaker

---

## Dependencies
- **Blocked by:** None (can work in parallel)
- **Blocks:** None
- **Integrates with:** All LLM providers

---

## Design References
- Circuit Breaker Pattern: https://martinfowler.com/bliki/CircuitBreaker.html
- Resilience patterns: https://learn.microsoft.com/en-us/azure/architecture/patterns/circuit-breaker
- QA Report: test_llm_providers.py - Circuit Breaker (P0)
