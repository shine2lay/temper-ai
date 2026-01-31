# Task: Fix cache key collision vulnerability

## Summary

Include system_prompt and tools parameters in LLM cache key generation to prevent cache poisoning. Current implementation only uses prompt text, allowing different requests with different system prompts or tool configurations to share cached responses, potentially exposing sensitive data or returning incorrect tool results.

**Estimated Effort:** 2.0 hours
**Module:** cache

---

## Files to Create

_None_

---

## Files to Modify

- `src/cache/llm_cache.py` - Include system_prompt and tools in cache key generation

---

## Acceptance Criteria

### Core Functionality
- [ ] Add system_prompt parameter to generate_key()
- [ ] Add tools parameter to generate_key()
- [ ] Sort tools list for deterministic hashing
- [ ] Include all parameters in SHA256 hash

### Security Controls
- [ ] Different prompts with different tools get different keys
- [ ] Different system prompts get different keys
- [ ] No cache poisoning possible

### Testing
- [ ] Test same prompt with different system_prompt → different keys
- [ ] Test same prompt with different tools → different keys
- [ ] Test cache isolation between requests
- [ ] Test tools list ordering (sorted vs unsorted) → same key

---

## Implementation Details

```python
import hashlib
import json
from typing import Optional, List, Dict, Any

class LLMCache:
    def generate_key(
        self,
        prompt: str,
        model: str = "claude-3-opus",
        system_prompt: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs
    ) -> str:
        """
        Generate cache key from all request parameters.

        Args:
            prompt: User prompt
            model: Model name
            system_prompt: System prompt (affects response)
            tools: Tool definitions (affects response)
            **kwargs: Additional parameters

        Returns:
            SHA256 hex digest as cache key
        """
        # Build request dict with all parameters
        request = {
            "prompt": prompt,
            "model": model,
            "system_prompt": system_prompt or "",
            "tools": self._normalize_tools(tools or []),
            **kwargs
        }

        # Serialize to JSON (sorted keys for determinism)
        json_str = json.dumps(request, sort_keys=True)

        # Hash with SHA256
        return hashlib.sha256(json_str.encode()).hexdigest()

    def _normalize_tools(self, tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Normalize tools list for deterministic hashing.

        - Sort by tool name
        - Sort keys within each tool dict
        """
        if not tools:
            return []

        # Sort tools by name
        sorted_tools = sorted(tools, key=lambda t: t.get("name", ""))

        # Sort keys within each tool
        normalized = []
        for tool in sorted_tools:
            normalized.append(dict(sorted(tool.items())))

        return normalized
```

**Example Usage:**
```python
cache = LLMCache()

# These get DIFFERENT cache keys (different system prompts)
key1 = cache.generate_key(
    prompt="What is 2+2?",
    system_prompt="You are a math tutor"
)
key2 = cache.generate_key(
    prompt="What is 2+2?",
    system_prompt="You are a comedian"
)
assert key1 != key2

# These get DIFFERENT cache keys (different tools)
key3 = cache.generate_key(
    prompt="Search for Python",
    tools=[{"name": "web_search", "description": "..."}]
)
key4 = cache.generate_key(
    prompt="Search for Python",
    tools=[{"name": "file_search", "description": "..."}]
)
assert key3 != key4

# These get SAME cache key (tools sorted)
key5 = cache.generate_key(
    prompt="Test",
    tools=[{"name": "b"}, {"name": "a"}]
)
key6 = cache.generate_key(
    prompt="Test",
    tools=[{"name": "a"}, {"name": "b"}]
)
assert key5 == key6
```

---

## Test Strategy

1. **System Prompt Isolation Test:**
   - Cache response for prompt="Summarize" with system_prompt="Expert"
   - Request same prompt with system_prompt="Novice"
   - Verify cache miss occurs (different keys)

2. **Tool Isolation Test:**
   - Cache response with web_search tool
   - Request with file_search tool
   - Verify cache miss occurs

3. **Determinism Test:**
   - Generate key with tools=[a, b, c]
   - Generate key with tools=[c, b, a]
   - Verify same key (sorted)

4. **Cache Poisoning Test:**
   - User A: cached response with admin tools
   - User B: request with no tools
   - Verify User B doesn't get User A's cached response

---

## Success Metrics

- [ ] No cache key collisions (100% isolation)
- [ ] Correct cache isolation between different system prompts
- [ ] All parameters affect key generation
- [ ] Deterministic hashing (same inputs → same key)

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** LLMCache, generate_key

---

## Design References

- `.claude-coord/reports/code-review-20260128-224245.md#1-cache-key-collision`

---

## Notes

**Critical** - Cache poisoning can return malicious responses to users. Attack scenarios:
- Admin user caches response with sensitive data
- Regular user gets admin's cached response
- Attacker poisons cache with malicious tool results
- Different tool configurations return wrong cached data

**Impact:** Data leakage, privilege escalation, incorrect responses
