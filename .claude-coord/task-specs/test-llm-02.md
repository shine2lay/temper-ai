# Task: test-llm-02 - Add Token Limit Enforcement Tests

**Priority:** HIGH
**Effort:** 2-3 hours
**Status:** pending
**Owner:** unassigned
**Category:** LLM Provider Resilience (P1)

---

## Summary
Add tests to ensure LLM providers enforce token limits and reject requests exceeding max_tokens configuration.

---

## Files to Modify
- `tests/test_agents/test_llm_providers.py` - Add token limit tests
- `src/llm/base.py`, `openai.py`, `anthropic.py`, `ollama.py` - Add validation

---

## Acceptance Criteria

### Request Validation
- [ ] Test requests exceeding max_tokens are rejected before API call
- [ ] Test token counting for input prompts
- [ ] Test combined prompt + max_completion_tokens validation
- [ ] Test model-specific token limits (gpt-4: 8K, gpt-4-turbo: 128K, etc.)

### Error Handling
- [ ] Clear error message indicating token limit exceeded
- [ ] Include actual token count and limit in error
- [ ] Suggest truncation or model upgrade

### Provider-Specific Limits
- [ ] OpenAI: Respect model context windows
- [ ] Anthropic: Respect Claude model limits (200K for Opus)
- [ ] Ollama: Respect model context from model info
- [ ] vLLM: Respect configured limits

---

## Implementation Details

```python
# tests/test_agents/test_llm_providers.py

def test_llm_provider_enforces_token_limits():
    """Test that providers reject requests exceeding token limits."""
    llm = OpenAILLM(model="gpt-4", api_key="test", max_tokens=8192)
    
    # Try to request more than max_tokens
    huge_prompt = "x" * 100000  # ~100K tokens
    
    with pytest.raises(LLMError, match="Token limit exceeded"):
        llm.complete(huge_prompt, max_tokens=1000000)

def test_llm_provider_counts_tokens_accurately():
    """Test token counting is accurate for different providers."""
    llm = OpenAILLM(model="gpt-4", api_key="test")
    
    # Known token counts
    test_cases = [
        ("Hello world", 2),
        ("This is a test prompt", 5),
    ]
    
    for text, expected_tokens in test_cases:
        token_count = llm.count_tokens(text)
        # Allow ±1 token variance due to encoding
        assert abs(token_count - expected_tokens) <= 1

def test_llm_provider_model_specific_limits():
    """Test model-specific token limits are respected."""
    test_cases = [
        ("gpt-4", 8192),
        ("gpt-4-turbo", 128000),
        ("claude-3-opus", 200000),
        ("claude-3-sonnet", 200000),
    ]
    
    for model, expected_limit in test_cases:
        if "gpt" in model:
            llm = OpenAILLM(model=model, api_key="test")
        else:
            llm = AnthropicLLM(model=model, api_key="test")
        
        assert llm.max_tokens == expected_limit

def test_llm_provider_helpful_error_message():
    """Test error message includes helpful details."""
    llm = OpenAILLM(model="gpt-4", api_key="test", max_tokens=8192)
    
    try:
        llm.complete("x" * 100000, max_tokens=10000)
    except LLMError as e:
        error_msg = str(e)
        # Should include actual count and limit
        assert "8192" in error_msg or "8,192" in error_msg
        # Should suggest action
        assert "truncate" in error_msg.lower() or "reduce" in error_msg.lower()
```

---

## Test Strategy
- Use tiktoken for accurate OpenAI token counting
- Use Anthropic's tokenizer for Claude models
- Test edge cases (empty strings, Unicode, special tokens)
- Benchmark token counting performance

---

## Success Metrics
- [ ] All providers enforce token limits
- [ ] Token counting accuracy >99%
- [ ] Clear error messages guide users
- [ ] Coverage of token validation >90%

---

## Dependencies
- **Blocked by:** None
- **Blocks:** None
- **Integrates with:** All LLM providers

---

## Design References
- OpenAI token limits: https://platform.openai.com/docs/models
- Anthropic limits: https://docs.anthropic.com/claude/docs/models-overview
- tiktoken: https://github.com/openai/tiktoken
- QA Report: test_llm_providers.py - Token Limits (P1)
