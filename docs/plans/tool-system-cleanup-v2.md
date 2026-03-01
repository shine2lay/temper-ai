# Plan: Tool System Cleanup v2

Supersedes `tool-system-cleanup.md` with refined design from deeper discussion.

## Key Design Decisions (what changed from v1)

1. **ToolRegistry class is deleted** — not refactored. Executor holds a plain
   `dict[str, BaseTool]` with lazy instantiation. The registry adds versioning
   and register/unregister ceremony that nobody uses.

2. **Policy enforcement moves to tool classes** — each tool knows its own policy
   keys. Bash validates `allowed_commands`, FileWriter validates `workspace_root`.
   The executor passes policy through, doesn't interpret it.

3. **Dialogue helpers use existing agent cache** — `_dialogue_helpers.py` bypasses
   the per-execution `_agent_cache`. After infra is on ContextVar, dialogue helpers
   can reuse cached agents across rounds.

## Problems (same as v1, plus)

### 8. Dialogue helpers bypass agent cache

`_dialogue_helpers.py:255` and `:796` call `AgentFactory.create()` directly every
dialogue round, bypassing `load_or_cache_agent()` from `_agent_execution.py`.
3-round debate with 3 agents = 9 fresh agent instances.

This is a consequence of problems #2 and #7 — agents can't be reused because
`_setup()` extracts infra from `input_data` on every execution.

## Proposed Design

### Remove ToolRegistry, executor owns singletons

`TOOL_CLASSES` stays as class lookup. `ToolExecutor` holds lazy singleton dict:

```python
# Inside ToolExecutor
_tool_instances: dict[str, BaseTool] = {}

def _get_tool(self, name: str) -> BaseTool:
    if name not in self._tool_instances:
        cls = TOOL_CLASSES.get(name)
        if cls is None:
            raise ToolNotFoundError(name)
        self._tool_instances[name] = cls()
    return self._tool_instances[name]
```

MCP tools: session-holding, per-credential, managed by `MCPManager`. Not singletons.

### Tool schemas from classes

Agent declares tool names. Schemas built from `TOOL_CLASSES` without instantiation:

```python
def get_tool_schemas(tool_names: list[str]) -> list[dict]:
    from temper_ai.tools import TOOL_CLASSES
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": TOOL_CLASSES[name].description,
                "parameters": TOOL_CLASSES[name].get_parameters_schema_cls(),
            },
        }
        for name in tool_names
        if name in TOOL_CLASSES
    ]
```

### Policy: executor passes, tool enforces

```
executor.execute("Bash", params, policy={"allowed_commands": ["cat", "ls"]})
  → safety stack (circuit breaker, rate limiter)
  → Bash.execute(params, policy)  # Bash validates allowed_commands itself
```

Responsibility split:
- **Executor**: safety stack (system-wide) + singleton lookup + passes policy
- **Tool class**: enforces its own policy keys
- **Agent config**: declares tools + policy (unchanged YAML)

### Rename confused functions

| Current | Proposed | Reason |
|---|---|---|
| `execute_single_tool()` | `route_tool_call()` | Parses, validates, routes. Doesn't execute. |
| `execute_via_executor()` | `execute_tool()` | Actual execution through safety stack. |
| `execute_tools()` | `route_tool_calls()` | Dispatches multiple calls. |

### ExecutionContext carries infrastructure

Extend `ExecutionContext` with `tracker`, `tool_executor`, `stream_callback`.
Set via `ContextVar` at pipeline start. Remove `InfrastructureContext`.

### Dialogue helpers use agent cache

`_dialogue_helpers.py` calls `load_or_cache_agent()` instead of direct
`AgentFactory.create()`. Same cache sequential/parallel paths use.

## File Changes

| File | Change |
|---|---|
| `temper_ai/tools/registry.py` | **Delete** |
| `temper_ai/tools/executor.py` | Owns `dict[str, BaseTool]` singletons, accepts `policy`, passes to tool |
| `temper_ai/tools/base.py` | `execute()` accepts optional `policy` dict; class-level schema methods |
| `temper_ai/tools/loader.py` | Simplify — remove instantiation/unregister dance |
| `temper_ai/llm/_tool_execution.py` | Rename functions, pass agent policy to executor |
| `temper_ai/llm/_schemas.py` | Accept tool names/classes instead of instances |
| `temper_ai/llm/service.py` | Update renamed function refs, pass tool names not instances |
| `temper_ai/agent/base_agent.py` | Remove `_create_tool_registry()`, `_sync_tool_configs_to_executor()`. Agent holds tool names + policy dict |
| `temper_ai/agent/standard_agent.py` | Tool names for schemas, policy to executor at call time |
| `temper_ai/shared/core/context.py` | Extend `ExecutionContext` with infra fields |
| `temper_ai/workflow/domain_state.py` | Remove `InfrastructureContext` |
| `temper_ai/workflow/runtime.py` | Set `ExecutionContext` via `ContextVar` at pipeline start |
| `temper_ai/stage/executors/*.py` | Read infra from `ExecutionContext` |
| `temper_ai/stage/executors/_dialogue_helpers.py` | Use `load_or_cache_agent()` |

## Implementation Order

1. **Rename functions** — mechanical, no behavior change
2. **Schema building from classes** — decouple from tool instances
3. **Policy on tool classes** — `BaseTool.execute()` accepts `policy`, each tool enforces its own
4. **Delete ToolRegistry, singleton dict on executor** — policy passed at call time
5. **Remove per-agent registry** — agents hold tool names + policy, not registry
6. **ExecutionContext with infrastructure** — remove prop drilling
7. **Remove InfrastructureContext** — dead code
8. **Dialogue helpers use cache** — use `load_or_cache_agent()`

## Verification

- Existing tool tests pass with renamed functions
- Agent with `tools: [Bash]` gets only Bash schema in LLM call
- `Bash.execute(params, policy={"allowed_commands": ["cat"]})` blocks `rm`
- Parallel agents with different Bash policies don't interfere
- MCP tools still work (session-based, not singleton)
- Dialogue rounds reuse agent instances from cache
- Full workflow run produces same results as before
