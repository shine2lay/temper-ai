# Task: test-llm-03 - Add Provider Failover Tests

**Priority:** HIGH
**Effort:** 3-4 hours
**Status:** pending
**Owner:** unassigned
**Category:** LLM Provider Resilience (P1)

---

## Summary
Implement and test provider failover mechanism to automatically switch to backup provider when primary fails.

---

## Files to Create
- `src/llm/failover.py` - Failover provider implementation

---

## Files to Modify
- `tests/test_agents/test_llm_providers.py` - Add failover tests
- `src/agents/standard_agent.py` - Support failover configuration

---

## Acceptance Criteria

### Failover Configuration
- [ ] Support ordered list of fallback providers
- [ ] Example: [Ollama, OpenAI, Anthropic]
- [ ] Configure per-agent or globally

### Automatic Failover
- [ ] When primary fails, try first fallback
- [ ] Continue through fallback list until success
- [ ] Return error only if all providers fail
- [ ] Log which provider was used

### Failure Conditions
- [ ] Connection errors trigger failover
- [ ] Timeouts trigger failover
- [ ] Rate limits trigger failover
- [ ] 5xx errors trigger failover
- [ ] 4xx errors do NOT trigger (user error)

### State Management
- [ ] Track which provider last succeeded
- [ ] Periodically retry primary provider
- [ ] Sticky sessions (same provider for conversation)

---

## Implementation Details

```python
# src/llm/failover.py
from typing import List
from src.llm.base import BaseLLM, LLMError
import logging

logger = logging.getLogger(__name__)

class FailoverProvider:
    """LLM provider with automatic failover."""
    
    def __init__(self, providers: List[BaseLLM], sticky_session: bool = True):
        if not providers:
            raise ValueError("At least one provider required")
        
        self.providers = providers
        self.sticky_session = sticky_session
        self.last_successful_index = 0
    
    def complete(self, prompt: str, **kwargs) -> str:
        """Complete with failover to backup providers."""
        errors = []
        
        # Try providers in order
        start_index = self.last_successful_index if self.sticky_session else 0
        
        for i in range(len(self.providers)):
            index = (start_index + i) % len(self.providers)
            provider = self.providers[index]
            
            try:
                logger.info(f"Attempting provider: {provider.model}")
                result = provider.complete(prompt, **kwargs)
                
                # Success - remember this provider
                self.last_successful_index = index
                logger.info(f"Success with provider: {provider.model}")
                
                return result
                
            except Exception as e:
                logger.warning(f"Provider {provider.model} failed: {e}")
                errors.append(f"{provider.model}: {e}")
                
                # Check if we should failover
                if not self._should_failover(e):
                    raise
        
        # All providers failed
        raise LLMError(
            f"All providers failed. Errors: {'; '.join(errors)}"
        )
    
    def _should_failover(self, error: Exception) -> bool:
        """Determine if error should trigger failover."""
        import httpx
        
        # Network/timeout errors should failover
        if isinstance(error, (httpx.ConnectError, httpx.TimeoutException)):
            return True
        
        # Rate limits should failover
        if isinstance(error, httpx.HTTPStatusError):
            if error.response.status_code in [429, 503, 504]:
                return True
        
        # Client errors should NOT failover
        return False
```

```python
# tests/test_agents/test_llm_providers.py

def test_llm_failover_to_backup_provider():
    """Test failover switches to backup when primary fails."""
    primary = OllamaLLM(model="primary")
    backup = OpenAILLM(model="gpt-4", api_key="test")
    
    failover = FailoverProvider(providers=[primary, backup])
    
    # Mock primary failure, backup success
    with patch.object(primary, 'complete', side_effect=httpx.ConnectError("Down")):
        with patch.object(backup, 'complete', return_value="Success"):
            result = failover.complete("test")
    
    assert result == "Success"
    assert failover.last_successful_index == 1  # Backup was used

def test_llm_failover_retries_all_providers():
    """Test failover tries all providers before failing."""
    providers = [
        OllamaLLM(model="llama"),
        OpenAILLM(model="gpt-4", api_key="test"),
        AnthropicLLM(model="claude-3", api_key="test"),
    ]
    
    failover = FailoverProvider(providers=providers)
    
    # Mock all failures
    for provider in providers:
        provider.complete = Mock(side_effect=httpx.ConnectError("Down"))
    
    # Should fail after trying all 3
    with pytest.raises(LLMError, match="All providers failed"):
        failover.complete("test")
    
    # Verify all were tried
    for provider in providers:
        provider.complete.assert_called_once()

def test_llm_failover_sticky_session():
    """Test sticky session uses last successful provider."""
    providers = [
        OllamaLLM(model="primary"),
        OpenAILLM(model="backup", api_key="test"),
    ]
    
    failover = FailoverProvider(providers=providers, sticky_session=True)
    
    # First call succeeds with backup
    with patch.object(providers[0], 'complete', side_effect=httpx.ConnectError("Down")):
        with patch.object(providers[1], 'complete', return_value="OK"):
            failover.complete("test")
    
    # Second call should try backup FIRST (sticky)
    with patch.object(providers[1], 'complete', return_value="OK") as backup_mock:
        failover.complete("test")
    
    # Backup should be called, primary should not
    backup_mock.assert_called_once()

def test_llm_failover_does_not_trigger_on_client_error():
    """Test failover does NOT trigger on client errors (4xx)."""
    primary = OpenAILLM(model="gpt-4", api_key="test")
    backup = AnthropicLLM(model="claude-3", api_key="test")
    
    failover = FailoverProvider(providers=[primary, backup])
    
    # Mock 400 Bad Request (client error)
    error = httpx.HTTPStatusError("Bad request", request=Mock(), response=Mock(status_code=400))
    with patch.object(primary, 'complete', side_effect=error):
        with patch.object(backup, 'complete', return_value="OK") as backup_mock:
            # Should raise without trying backup
            with pytest.raises(httpx.HTTPStatusError):
                failover.complete("test")
            
            # Backup should NOT be called
            backup_mock.assert_not_called()
```

---

## Test Strategy
- Test all failure scenarios (connection, timeout, rate limit)
- Test sticky session behavior
- Test provider preference after recovery
- Integration test with real agent

---

## Success Metrics
- [ ] Failover successful for all transient errors
- [ ] No failover for client errors
- [ ] Coverage of failover.py >95%
- [ ] Integration with StandardAgent working

---

## Dependencies
- **Blocked by:** None
- **Blocks:** None
- **Integrates with:** src/agents/standard_agent.py

---

## Design References
- Retry patterns: https://aws.amazon.com/builders-library/timeouts-retries-and-backoff-with-jitter/
- QA Report: test_llm_providers.py - Provider Failover (P1)
