# Task: m2-02-tool-registry - Implement tool registry and execution system

**Priority:** CRITICAL
**Effort:** 2-3 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

Implement a tool registry system that discovers, registers, and executes tools. Agents should be able to look up tools by name, get tool schemas for LLM prompts, and execute tools safely with proper error handling.

---

## Files to Create

- `src/tools/__init__.py` - Export ToolRegistry
- `src/tools/registry.py` - ToolRegistry class
- `src/tools/executor.py` - ToolExecutor with safety checks
- `tests/test_tools/test_registry.py` - Registry tests

---

## Acceptance Criteria

### Tool Registry
- [x] - [ ] Register tools by name
- [x] - [ ] Auto-discover tools in src/tools/
- [x] - [ ] Get tool by name
- [x] - [ ] List all available tools
- [x] - [ ] Get tool schema for LLM (JSON schema format)
- [x] - [ ] Tool metadata (name, description, parameters, version)

### Tool Executor
- [x] - [ ] Execute tool by name with params
- [x] - [ ] Safety checks before execution
- [x] - [ ] Timeout handling
- [x] - [ ] Error handling and reporting
- [ ] Log execution to observability (later in m2-06)
- [x] - [ ] Return structured result (success, result, error)

### Testing
- [x] - [ ] Test tool registration
- [x] - [ ] Test tool discovery
- [x] - [ ] Test tool execution
- [x] - [ ] Test error handling
- [x] - [ ] Test tool schema generation
- [x] - [ ] Coverage > 85%

---

## Implementation

```python
"""Tool registry and execution system."""
from typing import Dict, Any, Optional, List
from src.tools.base import BaseTool


class ToolRegistry:
    """Registry for managing tools."""

    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}

    def register(self, tool: BaseTool):
        """Register a tool."""
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[BaseTool]:
        """Get tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> List[str]:
        """List all registered tool names."""
        return list(self._tools.keys())

    def get_tool_schema(self, name: str) -> Dict[str, Any]:
        """Get tool schema for LLM."""
        tool = self.get(name)
        if not tool:
            raise ValueError(f"Tool not found: {name}")

        return {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.get_parameters_schema()
        }

    def auto_discover(self):
        """Auto-discover and register tools."""
        # Import all tool classes from src/tools/
        from src.tools.calculator import Calculator
        from src.tools.file_writer import FileWriter
        from src.tools.web_scraper import WebScraper

        for tool_class in [Calculator, FileWriter, WebScraper]:
            self.register(tool_class())


class ToolExecutor:
    """Executes tools with safety checks."""

    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    def execute(self, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute tool with parameters."""
        tool = self.registry.get(tool_name)
        if not tool:
            return {
                "success": False,
                "result": None,
                "error": f"Tool not found: {tool_name}"
            }

        try:
            # Validate params
            if not tool.validate_params(params):
                return {
                    "success": False,
                    "result": None,
                    "error": "Invalid parameters"
                }

            # Execute tool
            result = tool.execute(**params)
            return result

        except Exception as e:
            return {
                "success": False,
                "result": None,
                "error": str(e)
            }
```

---

## Success Metrics

- [x] - [ ] Tool registry implemented
- [x] - [ ] Tools can be registered and retrieved
- [x] - [ ] Tool execution works with all basic tools
- [x] - [ ] Tool schemas generated for LLM prompts
- [x] - [ ] Tests pass > 85% coverage

---

## Dependencies

- **Blocked by:** m1-00-structure, m1-06-basic-tools
- **Blocks:** m2-04-agent-runtime
- **Integrates with:** m1-06-basic-tools (uses BaseTool)

---

## Notes

- Keep it simple for M2 - just registry + execution
- Safety enforcement added later (M4)
- Tool schemas should follow OpenAI function calling format
