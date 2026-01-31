# Task: Fix Jinja2 template injection vulnerability

## Summary

Add variable validation and type checking to prevent Server-Side Template Injection (SSTI) in PromptEngine. Current implementation allows untrusted user input to be rendered in Jinja2 templates, potentially allowing attackers to access Python internals, execute arbitrary code, and escape the sandbox.

**Estimated Effort:** 4.0 hours
**Module:** agents

---

## Files to Create

_None_

---

## Files to Modify

- `src/agents/prompt_engine.py` - Add variable validation and type checking

---

## Acceptance Criteria

### Core Functionality
- [ ] Whitelist allowed variable types (str, int, float, bool, list, dict)
- [ ] Validate all variables before rendering
- [ ] Add size limits (100KB per variable)
- [ ] Consider string.Template for untrusted input

### Security Controls
- [ ] SSTI attacks blocked ({{config}}, {{''.__class__}})
- [ ] No access to Python internals
- [ ] Sandbox escape prevention

### Testing
- [ ] Test with SSTI payloads ({{config}}, {{''.__class__}})
- [ ] Test with oversized variables (>100KB)
- [ ] Test with dangerous types (functions, classes)
- [ ] Fuzz test with Burp SSTI payloads
- [ ] Test polyglot payloads (work in multiple template engines)

---

## Implementation Details

```python
from jinja2.sandbox import ImmutableSandboxedEnvironment
from typing import Any, Dict
import string

class PromptEngine:
    ALLOWED_TYPES = (str, int, float, bool, list, dict, type(None))
    MAX_VAR_SIZE = 100 * 1024  # 100KB

    def __init__(self):
        # Use ImmutableSandboxedEnvironment for safety
        self.jinja_env = ImmutableSandboxedEnvironment(
            autoescape=True,
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def render_template(
        self,
        template_str: str,
        variables: Dict[str, Any],
        use_safe_mode: bool = True
    ) -> str:
        """
        Render Jinja2 template with validated variables.

        Args:
            template_str: Template string
            variables: Template variables
            use_safe_mode: If True, use string.Template for untrusted input

        Returns:
            Rendered template

        Raises:
            ValueError: If variables are invalid or dangerous

        WARNING: This method renders Jinja2 templates. While we use
        ImmutableSandboxedEnvironment and validate inputs, SSTI is still
        possible if variables contain malicious content. For untrusted
        user input, set use_safe_mode=True to use string.Template instead.
        """
        # Validate variables
        self._validate_variables(variables)

        # For untrusted input, use safe string.Template
        if use_safe_mode:
            return self._render_safe_template(template_str, variables)

        # Otherwise use Jinja2 with sandboxing
        template = self.jinja_env.from_string(template_str)
        return template.render(**variables)

    def _validate_variables(self, variables: Dict[str, Any]) -> None:
        """
        Validate template variables for safety.

        Raises:
            ValueError: If any variable is invalid
        """
        for key, value in variables.items():
            # Check type against whitelist
            if not isinstance(value, self.ALLOWED_TYPES):
                raise ValueError(
                    f"Variable '{key}' has disallowed type: {type(value).__name__}. "
                    f"Allowed types: {[t.__name__ for t in self.ALLOWED_TYPES]}"
                )

            # Check size
            size = self._get_size(value)
            if size > self.MAX_VAR_SIZE:
                raise ValueError(
                    f"Variable '{key}' exceeds size limit: {size} > {self.MAX_VAR_SIZE}"
                )

            # Recursively validate nested structures
            if isinstance(value, dict):
                self._validate_variables(value)
            elif isinstance(value, list):
                for i, item in enumerate(value):
                    self._validate_variables({f"{key}[{i}]": item})

    def _get_size(self, obj: Any) -> int:
        """Estimate object size in bytes"""
        if isinstance(obj, str):
            return len(obj.encode())
        elif isinstance(obj, (int, float, bool, type(None))):
            return 8
        elif isinstance(obj, (list, tuple)):
            return sum(self._get_size(item) for item in obj)
        elif isinstance(obj, dict):
            return sum(self._get_size(k) + self._get_size(v)
                      for k, v in obj.items())
        return 0

    def _render_safe_template(
        self,
        template_str: str,
        variables: Dict[str, Any]
    ) -> str:
        """
        Render template using safe string.Template (no code execution).

        string.Template only supports simple ${var} substitution,
        no expressions or filters. Much safer for untrusted input.
        """
        template = string.Template(template_str)
        return template.safe_substitute(variables)
```

**Migration Path:**
```python
# OLD - Unsafe for untrusted input
engine.render_template(user_template, {"name": user_input})

# NEW - Safe mode for untrusted input
engine.render_template(user_template, {"name": user_input}, use_safe_mode=True)

# NEW - Jinja2 mode only for trusted templates
engine.render_template(trusted_template, validated_vars, use_safe_mode=False)
```

---

## Test Strategy

1. **SSTI Payload Tests:**
   ```python
   payloads = [
       "{{config}}",
       "{{''.__class__}}",
       "{{''.__class__.__mro__[1].__subclasses__()}}",
       "{{request.application.__globals__}}",
       "{{lipsum.__globals__}}",
       "{{cycler.__init__.__globals__}}",
   ]

   for payload in payloads:
       with pytest.raises(ValueError):
           engine.render_template(payload, {})
   ```

2. **Type Validation Tests:**
   - Pass function object → ValueError
   - Pass class object → ValueError
   - Pass module object → ValueError

3. **Size Limit Tests:**
   - Pass 200KB string → ValueError
   - Pass large nested dict → ValueError

4. **Burp Collaborator Test:**
   - Test with payloads that attempt DNS lookups
   - Verify no external connections possible

5. **Polyglot Tests:**
   - Test payloads that work in Jinja2/Django/Flask
   - Verify all blocked

---

## Success Metrics

- [ ] All SSTI attacks fail (100% blocked)
- [ ] Sandbox remains secure (no Python access)
- [ ] Security tests pass (0 bypasses)
- [ ] Safe mode available for untrusted input

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** PromptEngine, render_template

---

## Design References

- `.claude-coord/reports/code-review-20260128-224245.md#3-template-injection`

---

## Notes

**Critical** - SSTI can lead to arbitrary code execution. Attack vectors:
- Access Python builtins via `__class__.__mro__`
- Execute shell commands via `os.popen`
- Read sensitive files
- Bypass sandbox using import tricks

**Defense Layers:**
1. ImmutableSandboxedEnvironment (Jinja2 feature)
2. Type whitelist validation
3. Size limits
4. Safe mode (string.Template) for untrusted input

**Recommendation:** Default to safe mode (use_safe_mode=True) unless template source is trusted.
