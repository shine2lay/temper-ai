# Plan: Agent Runtime Input Validation

## Problem

`BaseAgent._validate_input()` only checks that `input_data` is a dict. No
validation of actual content — missing keys, wrong types, empty values. Errors
surface late as Jinja undefined variables or silent empty strings.

Agents need to be callable dynamically (not just through the static DAG), so
they can't rely on compile-time wiring checks. The agent itself must validate
its own inputs defensively.

## Design

### Extend `_validate_input()` in BaseAgent

When the agent has declared `inputs` (via `AgentIODeclaration`), validate
`input_data` against them:

1. **Required inputs present** — key exists in `input_data`
2. **Type check** — value matches declared type (string, list, dict, number, boolean, any)
3. **Apply defaults** — missing optional inputs get their declared default value
4. **Clear errors** — "Agent 'X' missing required input 'Y'" not a Jinja traceback

When no `inputs` declared (legacy agents), behavior unchanged — just the existing
dict type check.

```python
def _validate_input(self, input_data, context=None):
    # Existing type checks
    if input_data is None:
        raise ValueError("input_data cannot be None")
    if not isinstance(input_data, dict):
        raise TypeError(...)

    # New: validate against declared inputs
    declared = self.config.agent.inputs
    if not declared:
        return  # legacy agent, no declarations

    errors = []
    for name, decl in declared.items():
        if name not in input_data:
            if decl.required and decl.default is None:
                errors.append(f"missing required input '{name}'")
            elif decl.default is not None:
                input_data[name] = decl.default
            continue
        if decl.type != "any":
            _check_type(input_data[name], decl.type, name, errors)

    if errors:
        raise ValueError(
            f"Agent '{self.name}' input validation failed: {'; '.join(errors)}"
        )
```

### Type checking helper

```python
_TYPE_MAP = {
    "string": str,
    "list": list,
    "dict": dict,
    "number": (int, float),
    "boolean": bool,
}

def _check_type(value, declared_type, name, errors):
    expected = _TYPE_MAP.get(declared_type)
    if expected and not isinstance(value, expected):
        errors.append(
            f"input '{name}' expected {declared_type}, "
            f"got {type(value).__name__}"
        )
```

## File Changes

| File | Change |
|---|---|
| `temper_ai/agent/base_agent.py` | Extend `_validate_input()` with declared input checks, add `_check_type()` helper |

## Depends On

- `AgentIODeclaration` schema on `AgentConfigInner` (from compile-time-agent-io-validation plan)
- Without declarations, this is a no-op — backward compatible

## Verification

- Legacy agents (no declarations) behave unchanged
- Agent with declared required input raises clear error when missing
- Optional input with default gets default applied
- Type mismatch raises clear error
- Agent callable from any context (DAG, dynamic, test) with same validation
