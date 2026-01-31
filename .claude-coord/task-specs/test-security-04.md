# Task: test-security-04 - Add Template Injection Prevention Tests

**Priority:** CRITICAL
**Effort:** 2-3 hours
**Status:** pending
**Owner:** unassigned
**Category:** Security Testing (P0)

---

## Summary
Add tests to ensure Jinja2 template engine prevents template injection attacks where user input could execute arbitrary code.

---

## Files to Modify
- `tests/test_compiler/test_prompt_engine.py` - Add injection prevention tests
- `src/compiler/prompt_engine.py` - Add sandboxing if needed

---

## Acceptance Criteria

### Injection Prevention
- [ ] Test user input cannot inject Jinja2 code
- [ ] Test {{ }} delimiters are escaped in user input
- [ ] Test {% %} statements are escaped in user input
- [ ] Test system functions (os, sys, eval) are not accessible
- [ ] Test file system access is restricted
- [ ] Test import statements are blocked

### Sandboxing
- [ ] Test template runs in restricted Jinja2 sandbox
- [ ] Test dangerous filters are disabled (attr, getitem on objects)
- [ ] Test only whitelisted filters/functions available
- [ ] Test environment variables not accessible

### Edge Cases
- [ ] Test nested template injection attempts
- [ ] Test Unicode escaping bypass attempts
- [ ] Test macro abuse prevention

---

## Implementation Details

```python
# tests/test_compiler/test_prompt_engine.py

def test_prompt_engine_prevents_template_injection():
    """Test that user input cannot inject template code."""
    engine = PromptEngine()
    
    # User tries to inject Jinja2 code
    malicious_inputs = [
        "{{ system.exit(0) }}",
        "{{ ''.__class__.__mro__[1].__subclasses__() }}",
        "{% for item in system.modules %}{{ item }}{% endfor %}",
        "{{ config.from_pyfile('/etc/passwd') }}",
    ]
    
    template = "User said: {{ user_input }}"
    
    for malicious in malicious_inputs:
        result = engine.render(template, {"user_input": malicious})
        
        # Should render as literal text, not execute
        assert malicious in result or "[BLOCKED]" in result
        # System should not be accessible
        assert "system" not in str(engine.environment.globals.keys())

def test_prompt_engine_sandboxes_templates():
    """Test templates run in restricted sandbox."""
    from jinja2.sandbox import SandboxedEnvironment
    engine = PromptEngine()
    
    # Verify using sandboxed environment
    assert isinstance(engine.environment, SandboxedEnvironment)
    
    # Dangerous operations should fail
    dangerous_template = "{{ ().__class__.__bases__[0].__subclasses__() }}"
    
    with pytest.raises(SecurityError):
        engine.render(dangerous_template, {})

def test_prompt_engine_restricts_dangerous_filters():
    """Test dangerous Jinja2 filters are disabled."""
    engine = PromptEngine()
    
    # 'attr' filter can be abused
    template = "{{ user_input|attr('__class__') }}"
    
    with pytest.raises((SecurityError, UndefinedError)):
        engine.render(template, {"user_input": "test"})
```

---

## Test Strategy
- Test against SSTI (Server-Side Template Injection) payloads
- Verify Jinja2 SandboxedEnvironment is used
- Test with payloads from PayloadsAllTheThings repo

---

## Success Metrics
- [ ] All template injection attempts blocked
- [ ] Jinja2 sandbox properly configured
- [ ] No access to Python internals from templates
- [ ] Coverage of prompt_engine.py security >90%

---

## Dependencies
- **Blocked by:** None (can work in parallel)
- **Blocks:** None
- **Integrates with:** src/compiler/prompt_engine.py

---

## Design References
- Jinja2 Sandbox: https://jinja.palletsprojects.com/en/3.1.x/sandbox/
- SSTI Payloads: https://github.com/swisskyrepo/PayloadsAllTheThings/tree/master/Server%20Side%20Template%20Injection
- QA Report: test_prompt_engine.py - Template Injection (P0)
