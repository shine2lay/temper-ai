# Task: test-high-security-config-01 - Add Config Security SSTI and Deserialization Tests

**Priority:** HIGH
**Effort:** 2.5 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

Add tests for Server-Side Template Injection (SSTI) in Jinja templates and YAML deserialization gadgets.

---

## Files to Create

- None

---

## Files to Modify

- `tests/test_compiler/test_config_security.py - Add SSTI and deserialization tests`

---

## Acceptance Criteria


### Core Functionality
- [ ] Test SSTI in Jinja templates is blocked
- [ ] Test YAML deserialization gadgets are prevented
- [ ] Test Pickle/JSON deserialization exploits blocked
- [ ] Verify template sandboxing works

### Testing
- [ ] Test SSTI payloads ({{ }}, {% %} exploitation)
- [ ] Test YAML !!python/object exploits
- [ ] Test Pickle arbitrary code execution
- [ ] Edge case: nested template injection

### Security Controls
- [ ] Jinja sandbox mode enforced
- [ ] YAML safe_load used (not load)
- [ ] Pickle loading disabled for untrusted data

---

## Implementation Details

```python
def test_ssti_in_jinja_templates_blocked():
    """Test SSTI is prevented"""
    malicious_template = "{{ config.items() }}"
    with pytest.raises(TemplateSecurityError):
        render_template(malicious_template, context={})

def test_yaml_deserialization_gadget_prevention():
    """Test YAML gadgets blocked"""
    malicious_yaml = "!!python/object/apply:os.system ['ls']"
    with pytest.raises(YAMLDeserializationError):
        yaml.safe_load(malicious_yaml)
```

---

## Test Strategy

Test SSTI payloads. Test YAML/Pickle exploits. Verify sandboxing.

---

## Success Metrics

- [ ] All SSTI attacks blocked
- [ ] YAML gadgets prevented
- [ ] Sandbox enforced

---

## Dependencies

- **Blocked by:** None
- **Blocks:** None
- **Integrates with:** TemplateEngine, ConfigLoader

---

## Design References

- .claude-coord/reports/test-review-20260128-200844.md - Section 2, High Issue #2

---

## Notes

Use Jinja2 sandbox. Always use yaml.safe_load, never yaml.load.
