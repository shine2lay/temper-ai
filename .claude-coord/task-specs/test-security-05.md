# Task: test-security-05 - Add YAML Bomb Prevention Tests

**Priority:** CRITICAL
**Effort:** 2 hours
**Status:** pending
**Owner:** unassigned
**Category:** Security Testing (P0)

---

## Summary
Add tests to prevent YAML bomb attacks (exponential expansion) and symlink traversal attacks in configuration loading.

---

## Files to Modify
- `tests/test_compiler/test_config_security.py` - Add YAML bomb and symlink tests
- `src/compiler/config_loader.py` - Add protection if needed

---

## Acceptance Criteria

### YAML Bomb Prevention
- [ ] Test detection of YAML anchor/alias expansion bombs
- [ ] Test size limits on expanded YAML (e.g., <10MB after expansion)
- [ ] Test depth limits on nested structures (e.g., <100 levels)
- [ ] Test recursive reference detection

### Symlink Attack Prevention
- [ ] Test symlinks to /etc are rejected
- [ ] Test symlinks outside project directory are rejected
- [ ] Test symlink traversal attacks are blocked
- [ ] Test relative path symlinks are validated

### Resource Limits
- [ ] Test maximum file size enforcement
- [ ] Test maximum parse time limits
- [ ] Test memory usage limits during parse

---

## Implementation Details

```python
# tests/test_compiler/test_config_security.py

def test_config_loader_prevents_yaml_bomb():
    """Test that YAML bombs are detected and rejected."""
    yaml_bomb = """
a: &a ["a","a","a","a","a","a","a","a","a"]
b: &b [*a,*a,*a,*a,*a,*a,*a,*a,*a]
c: &c [*b,*b,*b,*b,*b,*b,*b,*b,*b]
d: &d [*c,*c,*c,*c,*c,*c,*c,*c,*c]
e: &e [*d,*d,*d,*d,*d,*d,*d,*d,*d]
"""
    
    config_file = tmp_path / "bomb.yaml"
    config_file.write_text(yaml_bomb)
    
    with pytest.raises(ConfigValidationError, match="YAML expansion|too large"):
        config_loader.load_config(config_file)

def test_config_loader_limits_nested_depth():
    """Test deeply nested YAML is rejected."""
    # Create 200-level nested structure
    nested = "key: " + "\n  ".join(["nested: "] * 200) + "value"
    
    config_file = tmp_path / "deep.yaml"
    config_file.write_text(nested)
    
    with pytest.raises(ConfigValidationError, match="depth|nesting"):
        config_loader.load_config(config_file)

def test_config_loader_rejects_symlink_traversal(tmp_path):
    """Test that symlinks cannot be used for path traversal."""
    # Create symlink to /etc
    symlink_path = tmp_path / "prompts" / "evil_link"
    symlink_path.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        symlink_path.symlink_to("/etc")
    except OSError:
        pytest.skip("Cannot create symlinks on this system")
    
    with pytest.raises(ConfigValidationError, match="symlink|traversal"):
        config_loader.load_prompt_template("evil_link/passwd")

def test_config_loader_enforces_size_limits():
    """Test maximum file size is enforced."""
    # Create 100MB config file
    huge_config = "key: " + ("x" * 100_000_000)
    config_file = tmp_path / "huge.yaml"
    config_file.write_text(huge_config)
    
    with pytest.raises(ConfigValidationError, match="size|too large"):
        config_loader.load_config(config_file)
```

---

## Test Strategy
- Test with known YAML bomb patterns
- Test with symlink attacks on both Unix and Windows
- Benchmark parse time limits
- Test memory usage during parse

---

## Success Metrics
- [ ] YAML bomb attacks prevented
- [ ] Symlink traversal attacks blocked
- [ ] Size and depth limits enforced
- [ ] Coverage of config_loader.py security >90%

---

## Dependencies
- **Blocked by:** None (can work in parallel)
- **Blocks:** None
- **Integrates with:** src/compiler/config_loader.py

---

## Design References
- YAML Bomb: https://en.wikipedia.org/wiki/Billion_laughs_attack
- YAML Security: https://github.com/yaml/pyyaml/wiki/PyYAML-yaml.load(input)-Deprecation
- QA Report: test_config_security.py - YAML Bomb (P0)
