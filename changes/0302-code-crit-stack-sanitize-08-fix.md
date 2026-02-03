# code-crit-stack-sanitize-08: Stack Trace Sanitization

## Problem
`ExecutionTracker._get_stack_trace()` stored raw `traceback.format_exc()` output
directly to the database. Stack traces can contain sensitive local variable values
(API keys, passwords, tokens, user data) that get embedded in frames.

## Fix
One-line change in `_get_stack_trace()`: pipe the raw traceback through the
existing `DataSanitizer.sanitize_text()` before returning. The sanitizer already
handles redaction of API keys, passwords, JWTs, emails, and other secrets using
compiled regex patterns.

Before:
```python
return traceback.format_exc()
```

After:
```python
raw_trace = traceback.format_exc()
return self.sanitizer.sanitize_text(raw_trace, context="stack_trace").sanitized_text
```

## Files Changed
- `src/observability/tracker.py` - `_get_stack_trace()` method (line 831)

## Testing
- 171 sanitization-related tests pass (9 pre-existing failures in test_llm_sanitization.py from unrelated DB issue)
- Manual verification: `sk-proj-*` keys correctly redacted to `[GENERIC_API_KEY_REDACTED]`
