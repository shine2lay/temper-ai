# Plan: Tool System Cleanup

## Context

The tool system has accumulated several design issues discovered during a full
flow walkthrough of the agent execution path. This plan captures all identified
problems and proposed fixes.

## Problems

### 1. Three tool registries per run

Engine creates a `ToolRegistry` (inside `ToolExecutor` safety stack). Each agent
creates another `ToolRegistry` with fresh tool instances. Config from agent
registry gets synced to executor registry via `_sync_tool_configs_to_executor()`.

- Agent registry exists only to provide LLM tool schemas (name, description, params schema)
- Executor registry exists only to run tools through the safety stack
- The sync step copies per-agent config from one to the other
- **Race condition**: parallel agents syncing different configs to the same executor
  tool instance (last write wins)

### 2. Per-agent policy baked into tool instances

Agent-specific constraints (`allowed_commands`, `workspace_root`) are stored as
mutable `config` on tool instances. This is why each agent needs its own instances.
These are really execution policies, not tool state.

### 3. Registry used as a filtered list

`_create_tool_registry()` lazy-loads tools from `TOOL_CLASSES`, then unregisters
everything not in the agent's config. All it actually needs is "give me schemas
for these N tool names."

### 4. Confusing function names in `_tool_execution.py`

- `execute_single_tool()` doesn't execute — it parses, validates, checks safety
  mode, then delegates to `execute_via_executor()`
- `execute_via_executor()` is the actual execution through the safety stack
- Two functions for what's conceptually one step

### 5. Tool schemas only need static data

`build_native_tool_defs()` and `build_text_schemas()` read `tool.name`,
`tool.description`, `tool.get_parameters_schema()`, `tool.get_result_schema()`.
All of these are class-level / static — no runtime config needed. Full tool
instantiation is unnecessary for schema building.

### 6. InfrastructureContext exists but is unused

`InfrastructureContext` in `domain_state.py` was designed to hold `tracker`,
`tool_registry`, `config_loader`, `visualizer`. Zero instantiations outside its
docstring. Instead these objects are prop-drilled through state dicts across 5 layers.

### 7. Infrastructure prop-drilled through input_data

`tracker`, `tool_executor`, `stream_callback` are created at pipeline start, stuffed
into the workflow state dict, drilled through executor → stage → helpers → agent.
`_setup()` extracts them from `input_data`, which mixes infrastructure with
business data.

## Proposed Design

### Tool instances are singletons

Built-in tools (Bash, FileWriter, Calculator, etc.) are stateless. One instance
shared across all agents. Per-agent config (`allowed_commands`, `workspace_root`)
is not stored on the tool — it's passed at execution time as policy.

Session-holding tools (MCP) are per-credential, managed by `MCPManager` separately.

### Tool schemas without instantiation

Schema building reads from `TOOL_CLASSES` directly or from a lightweight schema
cache. No need to instantiate tools just to read their class-level metadata.

```python
def get_tool_schemas(tool_names: list[str]) -> list[dict]:
    """Build LLM tool schemas for the given tool names."""
    from temper_ai.tools import TOOL_CLASSES
    schemas = []
    for name in tool_names:
        tool_class = TOOL_CLASSES.get(name)
        if tool_class is None:
            continue
        # These are all class-level, no instance needed
        schemas.append({
            "type": "function",
            "function": {
                "name": name,
                "description": tool_class.description,
                "parameters": tool_class.get_parameters_schema_cls(),
            },
        })
    return schemas
```

### One registry, policy passed at execution time

```
ToolExecutor.execute(
    tool_name="Bash",
    params={"command": "ls -la"},
    policy={"allowed_commands": ["cat", "ls"], "workspace_root": "/path"}
)
```

The executor:
1. Gets the singleton tool from the shared registry
2. Validates params against the agent's policy
3. Runs through safety stack (circuit breaker, rate limiter, action policy)
4. Calls `tool.execute(params)`

Agent config still declares tools with policy:
```yaml
tools:
  - name: Bash
    config:
      allowed_commands: [cat, ls]
      workspace_root: "{{ workspace_path }}"
```

But the `config` block is treated as policy/constraints, not tool instance state.

### Rename confused functions

| Current | Proposed | Reason |
|---|---|---|
| `execute_single_tool()` | `route_tool_call()` | Parses, validates, checks safety mode, routes to executor. Doesn't execute. |
| `execute_via_executor()` | `execute_tool()` | The actual execution through the safety stack. |
| `execute_tools()` | `route_tool_calls()` | Dispatches multiple calls (serial or parallel). |

### ExecutionContext carries infrastructure

Extend `ExecutionContext` to carry `tracker`, `tool_executor`, `stream_callback`.
Set once at pipeline start via `ContextVar`, accessible anywhere without prop
drilling. `InfrastructureContext` is removed (merged into `ExecutionContext`).

IDs (`stage_id`, `agent_id`) change at each scope level — handled by setting new
`ContextVar` tokens that revert when the scope exits.

## File Changes

| File | Change |
|---|---|
| `temper_ai/llm/_tool_execution.py` | Rename `execute_single_tool` → `route_tool_call`, `execute_via_executor` → `execute_tool`, `execute_tools` → `route_tool_calls` |
| `temper_ai/llm/service.py` | Update references to renamed functions |
| `temper_ai/llm/_schemas.py` | Accept tool names/classes instead of tool instances |
| `temper_ai/tools/registry.py` | Singleton tool instances, policy not stored on tools |
| `temper_ai/tools/executor.py` | Accept policy at execution time, validate against policy |
| `temper_ai/tools/base.py` | Class-level schema methods (no instance needed) |
| `temper_ai/agent/base_agent.py` | Remove `_create_tool_registry()`, remove `_sync_tool_configs_to_executor()`. Agent holds tool names + policy config, not a registry |
| `temper_ai/agent/standard_agent.py` | Use tool names from config for schema building instead of registry. Pass policy to executor at call time |
| `temper_ai/shared/core/context.py` | Extend `ExecutionContext` with infrastructure fields (tracker, tool_executor, stream_callback). Remove `InfrastructureContext` |
| `temper_ai/workflow/domain_state.py` | Remove `InfrastructureContext` |
| `temper_ai/workflow/runtime.py` | Set `ExecutionContext` via `ContextVar` at pipeline start |
| `temper_ai/stage/executors/*.py` | Read infrastructure from `ExecutionContext` instead of state dict |
| `temper_ai/tools/loader.py` | Simplify — no more `load_tools_from_config` instantiation/unregister dance |

## Implementation Order

1. **Rename functions** — mechanical, low risk, no behavior change
2. **Schema building from classes** — decouple schema generation from tool instances
3. **Singleton registry + policy at execution** — remove per-agent registries
4. **ExecutionContext with infrastructure** — remove prop drilling
5. **Remove InfrastructureContext** — dead code cleanup

## Verification

- Existing tool tests pass with renamed functions
- Agent with `tools: [Bash]` gets only Bash schema in LLM call
- Agent with `allowed_commands: [cat, ls]` blocks `rm` at execution time
- Parallel agents with different Bash policies don't interfere
- MCP tools still work (session-based, not singleton)
- Full workflow run produces same results as before
