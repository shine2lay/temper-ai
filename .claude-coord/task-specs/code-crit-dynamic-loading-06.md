# Task: Secure dynamic tool loading mechanism

## Summary

Add strict validation, cryptographic signatures, and sandboxing for _load_tools_from_config in StandardAgent. Current implementation uses eval() and getattr() with user-controlled input, allowing arbitrary code execution in multi-tenant environments.

**Estimated Effort:** 5.0 hours
**Module:** agents

---

## Files to Create

_None_

---

## Files to Modify

- `src/agents/standard_agent.py` - Add strict validation, signatures, sandboxing for _load_tools_from_config

---

## Acceptance Criteria

### Core Functionality
- [ ] Strict regex validation for tool names ([a-zA-Z0-9_]+)
- [ ] Plugin registry with cryptographic signatures
- [ ] Sandbox tool execution in separate processes
- [ ] Audit logging for all tool loads

### Security Controls
- [ ] Malicious tools cannot be loaded
- [ ] Tool execution isolated
- [ ] All loads audited

### Testing
- [ ] Test with invalid tool names (shell metacharacters)
- [ ] Test with malicious tool classes
- [ ] Test signature verification
- [ ] Test sandbox isolation

---

## Implementation Details

```python
import re
import hmac
import hashlib
import multiprocessing
from typing import Dict, Any

class ToolRegistry:
    """Secure registry for plugin tools with signature verification"""

    TOOL_NAME_PATTERN = re.compile(r'^[a-zA-Z0-9_]+$')

    def __init__(self, public_key: bytes):
        self.public_key = public_key
        self.registered_tools: Dict[str, Any] = {}

    def register_tool(self, name: str, tool_class: type, signature: bytes):
        """
        Register a tool with signature verification.

        Args:
            name: Tool name (alphanumeric + underscore only)
            tool_class: Tool class
            signature: HMAC signature of tool class bytecode

        Raises:
            ValueError: If tool name invalid or signature verification fails
        """
        # Validate tool name
        if not self.TOOL_NAME_PATTERN.match(name):
            raise ValueError(f"Invalid tool name: {name}")

        # Verify signature
        tool_bytecode = tool_class.__code__.co_code
        expected_signature = hmac.new(
            self.public_key,
            tool_bytecode,
            hashlib.sha256
        ).digest()

        if not hmac.compare_digest(signature, expected_signature):
            raise ValueError(f"Invalid signature for tool: {name}")

        # Register tool
        self.registered_tools[name] = tool_class

        # Audit log
        self._audit_log("TOOL_REGISTERED", name)

    def get_tool(self, name: str) -> type:
        """Get registered tool by name"""
        if name not in self.registered_tools:
            raise ValueError(f"Tool not registered: {name}")
        return self.registered_tools[name]

    def _audit_log(self, event: str, tool_name: str):
        """Log security events to audit trail"""
        import logging
        audit_logger = logging.getLogger("security.audit")
        audit_logger.info(f"{event}: {tool_name}")


class SandboxedToolExecutor:
    """Execute tools in isolated subprocess"""

    @staticmethod
    def execute(tool_class: type, method: str, *args, **kwargs) -> Any:
        """
        Execute tool method in sandbox.

        Args:
            tool_class: Tool class to instantiate
            method: Method name to call
            *args, **kwargs: Method arguments

        Returns:
            Method result

        Raises:
            RuntimeError: If execution fails or timeout
        """
        def _run_in_sandbox(queue, tool_class, method, args, kwargs):
            try:
                tool = tool_class()
                result = getattr(tool, method)(*args, **kwargs)
                queue.put(("success", result))
            except Exception as e:
                queue.put(("error", str(e)))

        # Create queue for result
        queue = multiprocessing.Queue()

        # Run in separate process
        process = multiprocessing.Process(
            target=_run_in_sandbox,
            args=(queue, tool_class, method, args, kwargs)
        )

        process.start()
        process.join(timeout=30)  # 30 second timeout

        if process.is_alive():
            process.terminate()
            raise RuntimeError("Tool execution timeout")

        if not queue.empty():
            status, result = queue.get()
            if status == "success":
                return result
            else:
                raise RuntimeError(f"Tool execution failed: {result}")

        raise RuntimeError("Tool execution failed: no result")


class StandardAgent:
    def __init__(self):
        self.tool_registry = ToolRegistry(public_key=self._load_public_key())
        self.tool_executor = SandboxedToolExecutor()

    def _load_tools_from_config(self, config: Dict[str, Any]):
        """
        Load tools from config with security controls.

        Args:
            config: Tool configuration

        Raises:
            ValueError: If tool loading fails validation
        """
        for tool_name in config.get("tools", []):
            # Validate tool name
            if not ToolRegistry.TOOL_NAME_PATTERN.match(tool_name):
                raise ValueError(f"Invalid tool name: {tool_name}")

            # Get tool from registry (must be pre-registered)
            tool_class = self.tool_registry.get_tool(tool_name)

            # Store for later use
            self._tools[tool_name] = tool_class

    def execute_tool(self, tool_name: str, method: str, *args, **kwargs):
        """Execute tool method in sandbox"""
        if tool_name not in self._tools:
            raise ValueError(f"Tool not loaded: {tool_name}")

        tool_class = self._tools[tool_name]
        return self.tool_executor.execute(tool_class, method, *args, **kwargs)
```

---

## Test Strategy

1. **Invalid Name Tests:**
   - `tool_name = "../../malicious"` → ValueError
   - `tool_name = "$(whoami)"` → ValueError
   - `tool_name = "tool;rm -rf /"` → ValueError

2. **Signature Verification Tests:**
   - Load tool without valid signature → ValueError
   - Load tool with tampered signature → ValueError
   - Load tool with valid signature → success

3. **Sandbox Isolation Tests:**
   - Tool attempts to access parent process memory → fails
   - Tool attempts to write to filesystem → isolated
   - Tool execution timeout → terminated safely

4. **Audit Logging Tests:**
   - Verify all tool loads logged to security.audit
   - Verify failed attempts logged

---

## Success Metrics

- [ ] Only signed tools load (100% signature verification)
- [ ] Tool execution isolated (0 parent process access)
- [ ] Security audit complete (all events logged)
- [ ] No arbitrary code execution possible

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** StandardAgent, _load_tools_from_config, AVAILABLE_TOOLS

---

## Design References

- `.claude-coord/reports/code-review-20260128-224245.md#1-arbitrary-code-execution`

---

## Notes

**Critical** - Arbitrary code execution risk in multi-tenant environments. Attack scenarios:
- Load malicious tool that steals credentials
- Execute shell commands via tool injection
- Access other users' data
- Install backdoors

**Defense Layers:**
1. Tool name validation (alphanumeric only)
2. Cryptographic signature verification
3. Process-level sandboxing (multiprocessing)
4. Audit logging
