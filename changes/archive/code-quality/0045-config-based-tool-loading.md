# Implement Config-Based Tool Loading (cq-p3-02)

**Date:** 2026-01-27
**Type:** Security Enhancement / Code Quality
**Priority:** P3
**Completed by:** agent-858f9f

## Summary
Replaced automatic tool discovery with config-driven tool loading for better security control and explicit tool permissions per agent.

## Problem
The `StandardAgent._create_tool_registry()` method was using auto-discovery to load ALL available tools, regardless of what the agent configuration specified:

```python
def _create_tool_registry(self) -> ToolRegistry:
    registry = ToolRegistry(auto_discover=False)
    # TODO: In full implementation, load specific tools from config
    # For now, use auto-discovery for simplicity
    registry.auto_discover()  # Loads ALL tools
    return registry
```

**Security Issues:**
- Agent configs specified tools list, but it was ignored
- All agents had access to all tools (principle of least privilege violation)
- No control over which tools an agent can use
- Harder to audit what tools an agent might execute

## Solution

### 1. Config-Driven Tool Loading
Implemented `_load_tools_from_config()` method that:
- Reads `tools` list from agent configuration
- Validates tool names against allowlist (`AVAILABLE_TOOLS`)
- Imports and instantiates only requested tools
- Raises `ValueError` for unknown/disallowed tools

### 2. Allowlist-Based Security
Created explicit mapping of allowed tools:
```python
AVAILABLE_TOOLS = {
    'WebScraper': 'src.tools.web_scraper.WebScraper',
    'Calculator': 'src.tools.calculator.Calculator',
    'FileWriter': 'src.tools.file_writer.FileWriter',
}
```

Benefits:
- **Security**: Only vetted, approved tools can be loaded
- **Explicit**: Developer must consciously add tools to allowlist
- **Auditable**: Easy to see what tools are available system-wide

### 3. Backward Compatibility
Falls back to auto-discovery if `tools` list is empty:
```python
if not configured_tools:
    # No tools configured - use auto-discovery for backward compatibility
    registry.auto_discover()
```

### 4. Support for Tool Configuration
Handles both formats from config:
- Simple string: `tools: ["Calculator"]`
- ToolReference with config: `tools: [{name: "Calculator", config: {...}}]`

(Config overrides not yet implemented but structure supports it)

## Files Modified
- `src/agents/standard_agent.py`
  - Updated `_create_tool_registry()` to use config-based loading
  - Added `_load_tools_from_config()` method
  - Added `AVAILABLE_TOOLS` mapping

## Testing
Verified with `simple_researcher.yaml` config:
- Config specifies: `tools: ["Calculator"]`
- Agent loads: Only Calculator
- WebScraper and FileWriter NOT loaded ✓
- Correct tool available for execution ✓

## Security Benefits
1. **Principle of Least Privilege**: Agents only get tools they need
2. **Explicit Permissions**: Must declare tools in config
3. **Audit Trail**: Config shows exactly what tools agent can use
4. **Attack Surface Reduction**: Limits available tools if agent is compromised
5. **Tool Allowlist**: Unknown tools cannot be loaded by modifying config

## Impact
- **Security**: ✓ Improved - Explicit tool permissions per agent
- **Performance**: Negligible - Same number of tool instances
- **Backward Compatibility**: ✓ Maintained - Falls back to auto-discovery
- **Config Migration**: None needed - existing configs already specify tools

## Future Enhancements
- [ ] Pass `tool_config` from ToolReference to tool constructor
- [ ] Add runtime tool permission validation in executor
- [ ] Add audit logging for tool loading/execution
- [ ] Support dynamic tool loading from external sources

## Related
- Task: cq-p3-02
- Security: Implements least privilege for tool access
- Example config: `configs/agents/simple_researcher.yaml` line 52
