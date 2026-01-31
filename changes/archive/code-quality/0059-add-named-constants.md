# Add Named Constants (cq-p1-08) - Partial Completion

**Date:** 2026-01-27
**Type:** Code Quality / Maintainability
**Priority:** P3
**Completed by:** agent-858f9f
**Status:** Partially completed (2 of 3 files)

## Summary
Extracted magic numbers to named module-level constants with documentation explaining rationale for each value. Completed for `config_loader.py` and `web_scraper.py`. **Note:** `standard_agent.py` could not be completed as it was locked by agent-1e0126.

## Problem
Magic numbers scattered throughout codebase with no explanation:

**Issues:**
- ❌ Hard to understand why specific values were chosen
- ❌ Difficult to update values consistently
- ❌ No documentation of security/performance rationale
- ❌ Hard to spot bugs (e.g., is 300 seconds intentional?)
- ❌ Poor maintainability

**Example Problems:**
```python
# config_loader.py
if len(value) > 10 * 1024:  # What is 10KB? Why this limit?
    raise ConfigValidationError(...)

# web_scraper.py
time_window=60  # 60 what? Why 60?
le=300  # Max timeout? Why 300 seconds?
```

## Solution

### 1. Config Loader Constants (`src/compiler/config_loader.py`)

#### Added Constants
```python
# Maximum config file size (10MB) to prevent memory exhaustion from malicious configs
MAX_CONFIG_SIZE = 10 * 1024 * 1024

# Maximum environment variable value length (10KB) to prevent DoS attacks
# Rationale: Most legitimate env vars are <1KB. 10KB allows for large JWTs/keys
# while preventing memory exhaustion from ${VAR} expansion attacks
MAX_ENV_VAR_SIZE = 10 * 1024
```

#### Updated Usage
```python
# Before
if len(value) > 10 * 1024:  # 10KB limit
    raise ConfigValidationError(
        f"Environment variable '{var_name}' value too long: {len(value)} bytes (max: 10KB)"
    )

# After
if len(value) > MAX_ENV_VAR_SIZE:
    raise ConfigValidationError(
        f"Environment variable '{var_name}' value too long: {len(value)} bytes (max: {MAX_ENV_VAR_SIZE} bytes)"
    )
```

### 2. Web Scraper Constants (`src/tools/web_scraper.py`)

#### Added Constants
```python
# Validation constants for web scraper parameters
# Rationale for URL length limits:
# - Min 10 chars ensures valid URL (e.g., "http://a.b")
# - Max 2000 chars prevents DoS while supporting long query strings
URL_MIN_LENGTH = 10
URL_MAX_LENGTH = 2000

# Max timeout: 5 minutes prevents indefinite hangs while allowing slow endpoints
# Typical use: Large files, slow APIs, or high-latency connections
MAX_TIMEOUT_SECONDS = 300

# User-Agent max length: 500 chars is reasonable for custom UA strings
# Prevents header injection attacks and excessive memory usage
USER_AGENT_MAX_LENGTH = 500

# Rate limit time window: 60 seconds (1 minute) for request counting
# Matches DEFAULT_RATE_LIMIT of 10 requests per minute
RATE_LIMIT_WINDOW_SECONDS = 60
```

#### Updated Usage

**Pydantic Field Validation:**
```python
# Before
url: str = Field(
    ...,
    min_length=10,
    max_length=2000
)
timeout: int = Field(
    default=30,
    gt=0,
    le=300  # Max 5 minutes
)
user_agent: Optional[str] = Field(
    default=None,
    max_length=500
)

# After
url: str = Field(
    ...,
    min_length=URL_MIN_LENGTH,
    max_length=URL_MAX_LENGTH
)
timeout: int = Field(
    default=30,
    gt=0,
    le=MAX_TIMEOUT_SECONDS
)
user_agent: Optional[str] = Field(
    default=None,
    max_length=USER_AGENT_MAX_LENGTH
)
```

**Rate Limiter Initialization:**
```python
# Before
self.rate_limiter = RateLimiter(
    max_requests=self.DEFAULT_RATE_LIMIT,
    time_window=60  # 1 minute
)

# After
self.rate_limiter = RateLimiter(
    max_requests=self.DEFAULT_RATE_LIMIT,
    time_window=RATE_LIMIT_WINDOW_SECONDS
)
```

## Files Modified

### Completed:
- **`src/compiler/config_loader.py`**
  - Added: `MAX_ENV_VAR_SIZE` constant with documentation
  - Updated: Environment variable validation (line ~411)

- **`src/tools/web_scraper.py`**
  - Added: 5 new constants (URL_MIN_LENGTH, URL_MAX_LENGTH, MAX_TIMEOUT_SECONDS, USER_AGENT_MAX_LENGTH, RATE_LIMIT_WINDOW_SECONDS)
  - Updated: WebScraperParams field validation
  - Updated: RateLimiter initialization

### Blocked:
- **`src/agents/standard_agent.py`** - Could not complete
  - File locked by agent-1e0126
  - Needs constants for:
    - `cost_per_1k_tokens = 0.002` → `COST_PER_1K_TOKENS`
    - `/ 1000.0` → `TOKENS_PER_UNIT`
  - Recommended follow-up task or retry after agent-1e0126 completes

## Testing

### Test Results
```
Test 1: Config Loader Constants...
  ✓ MAX_CONFIG_SIZE = 10,485,760 bytes (10MB)
  ✓ MAX_ENV_VAR_SIZE = 10,240 bytes (10KB)

Test 2: Web Scraper Constants...
  ✓ URL_MIN_LENGTH = 10
  ✓ URL_MAX_LENGTH = 2000
  ✓ MAX_TIMEOUT_SECONDS = 300s (5 minutes)
  ✓ USER_AGENT_MAX_LENGTH = 500
  ✓ RATE_LIMIT_WINDOW_SECONDS = 60s

Test 3: Constants Usage in Validation...
  ✓ Short URL rejected: ValidationError
  ✓ Long URL rejected: ValidationError
  ✓ High timeout rejected: ValidationError
  ✓ Valid parameters accepted

Test 4: Rate Limiter Initialization...
  ✓ Rate limiter uses RATE_LIMIT_WINDOW_SECONDS = 60s

✅ ALL TESTS PASSED (for completed files)
```

### Validation Tests
```python
# Test URL length validation uses constant
params = WebScraperParams(url="http://x")  # < URL_MIN_LENGTH
# Raises ValidationError ✓

# Test timeout validation uses constant
params = WebScraperParams(url="http://example.com", timeout=301)  # > MAX_TIMEOUT_SECONDS
# Raises ValidationError ✓

# Test rate limiter uses constant
scraper = WebScraper()
assert scraper.rate_limiter.time_window == RATE_LIMIT_WINDOW_SECONDS  # ✓
```

## Benefits

### 1. Self-Documenting Code
```python
# Before: What does 300 mean?
le=300

# After: Clear meaning and rationale
le=MAX_TIMEOUT_SECONDS  # With comment: "5 minutes prevents hangs"
```

### 2. Easy to Update
```python
# Before: Find and replace all "300" (might miss some, change wrong ones)
# After: Update MAX_TIMEOUT_SECONDS in one place
```

### 3. Consistent Values
```python
# Before: Timeout might be 300 in one place, 60 in another
# After: All timeouts reference same constant (if appropriate)
```

### 4. Rationale Documentation
Every constant now has comment explaining:
- **Why this value?** (Security, performance, usability)
- **What does it prevent?** (DoS, hangs, injection)
- **Trade-offs** (10KB allows JWTs but prevents abuse)

### 5. Easier Code Review
```python
# Reviewer sees:
MAX_TIMEOUT_SECONDS = 300
# Comment: "5 minutes prevents indefinite hangs while allowing slow endpoints"

# Reviewer immediately understands reasoning
```

## Constants Added - Summary

| Constant | Value | File | Purpose |
|----------|-------|------|---------|
| `MAX_ENV_VAR_SIZE` | 10KB | config_loader.py | Prevent DoS from env var expansion |
| `URL_MIN_LENGTH` | 10 | web_scraper.py | Ensure valid URL format |
| `URL_MAX_LENGTH` | 2000 | web_scraper.py | Prevent DoS while allowing long URLs |
| `MAX_TIMEOUT_SECONDS` | 300 | web_scraper.py | Prevent hangs (5 min max) |
| `USER_AGENT_MAX_LENGTH` | 500 | web_scraper.py | Prevent header injection |
| `RATE_LIMIT_WINDOW_SECONDS` | 60 | web_scraper.py | Time window for rate limiting |

## Documentation Rationale

Each constant includes comments explaining:

### Security Rationale
- `MAX_ENV_VAR_SIZE`: Prevents memory exhaustion attacks via ${VAR} expansion
- `URL_MAX_LENGTH`: Prevents DoS from extremely long URLs
- `USER_AGENT_MAX_LENGTH`: Prevents header injection attacks

### Performance Rationale
- `MAX_TIMEOUT_SECONDS`: Balances responsiveness vs allowing slow endpoints
- `RATE_LIMIT_WINDOW_SECONDS`: Standard 1-minute window for rate counting

### Usability Rationale
- `URL_MIN_LENGTH`: Ensures URL is valid format ("http://a.b" minimum)
- 10KB env vars: Large enough for JWTs/keys, small enough to prevent abuse

## Usage Examples

### Reading Constants
```python
from src.compiler.config_loader import MAX_ENV_VAR_SIZE, MAX_CONFIG_SIZE

# Check limits
print(f"Max env var size: {MAX_ENV_VAR_SIZE:,} bytes")
print(f"Max config size: {MAX_CONFIG_SIZE:,} bytes")
```

### Using in Validation
```python
from src.tools.web_scraper import URL_MAX_LENGTH, MAX_TIMEOUT_SECONDS

# Pydantic field validation
url: str = Field(..., max_length=URL_MAX_LENGTH)
timeout: int = Field(default=30, le=MAX_TIMEOUT_SECONDS)

# Runtime validation
if len(url) > URL_MAX_LENGTH:
    raise ValueError(f"URL too long (max: {URL_MAX_LENGTH})")
```

### Referencing in Documentation
```python
def fetch_url(url: str, timeout: int = 30):
    """
    Fetch URL with timeout.

    Args:
        url: URL to fetch (max {URL_MAX_LENGTH} chars)
        timeout: Timeout in seconds (max {MAX_TIMEOUT_SECONDS})
    """
```

## Incomplete Work

### `src/agents/standard_agent.py` (Blocked by agent-1e0126)

**Magic numbers that still need extraction:**

1. **Line ~757:** Cost calculation
```python
# Current (magic number)
cost_per_1k_tokens = 0.002  # $0.002 per 1K tokens

# Recommended constant
# Cost per 1000 tokens (default estimate, varies by model)
# Rationale: GPT-3.5-turbo pricing as baseline. Should be configurable per model.
COST_PER_1K_TOKENS = 0.002

# Usage
cost_per_1k_tokens = COST_PER_1K_TOKENS
```

2. **Line ~758:** Token unit conversion
```python
# Current (magic number)
return (llm_response.total_tokens / 1000.0) * cost_per_1k_tokens

# Recommended constant
# Number of tokens per pricing unit (most LLM APIs price per 1K tokens)
TOKENS_PER_PRICING_UNIT = 1000.0

# Usage
return (llm_response.total_tokens / TOKENS_PER_PRICING_UNIT) * cost_per_1k_tokens
```

**Recommendation:** Create follow-up task or retry after agent-1e0126 releases lock.

## Performance Impact
- **No performance impact** - Constants resolved at module import time
- **Memory:** Negligible (few integer/float values)
- **Benefit:** Improved maintainability and readability

## Backward Compatibility
- ✅ No breaking changes
- ✅ Constants are module-level, not part of public API
- ✅ Existing code continues to work
- ✅ New code can use constants immediately

## Future Enhancements
- [ ] Complete `standard_agent.py` constants (blocked)
- [ ] Add constants for other magic numbers in codebase
- [ ] Consider configuration file for adjustable constants
- [ ] Add constants validation tests
- [ ] Extract more magic strings (not just numbers)
- [ ] Create constants style guide

## Related
- Task: cq-p1-08 (partially complete - 2 of 3 files)
- Category: Code quality - Maintainability
- Pattern: Named constants over magic numbers
- Improves: Readability, maintainability, documentation
- Blocked by: agent-1e0126 (lock on standard_agent.py)
- Follow-up: Complete standard_agent.py constants
