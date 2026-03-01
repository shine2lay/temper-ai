# Plan: Unified Pre-Compile Validation

## Problem

Config validation happens in two places at two different times:

1. **Runtime** (`runtime.py:764`): `validate_references()` — checks that stage,
   agent, and tool names resolve to real configs. Runs before `compile()`.

2. **Engine** (`dynamic_engine.py:291`): `_validate_all_configs()` — Pydantic schema
   validation, agent I/O wiring checks. Runs inside `compile()`.

This means:
- The engine does validation work that isn't its responsibility
- `compile()` can't assume valid input — it has to validate first
- Two separate error-collection passes over the same configs
- Adding new validation requires knowing which layer to put it in

## Current Flow

```
load_config → adapt_lifecycle → setup_infrastructure
  → validate_references()          ← runtime: do names exist?
  → compile()
      → _validate_all_configs()    ← engine: are schemas valid? is I/O wired?
      → build DAG
      → return compiled workflow
  → execute
```

## Proposed Flow

```
load_config → adapt_lifecycle → setup_infrastructure
  → validate_all()                 ← single pass: references + schemas + I/O
  → compile()                      ← assumes valid configs, just builds DAG
  → execute
```

## Design

### `validate_all()` on PipelineRuntime

Replaces `validate_references()`. Runs three checks in order:

1. **Reference validation** — existing `validate_references()` logic (do names exist?)
2. **Schema validation** — Pydantic parsing of stage and agent configs (are they well-formed?)
3. **I/O wiring validation** — agent input/output declarations match stage wiring

All three collect errors into the same list and raise one `ConfigValidationError`.

```python
def validate_all(
    self,
    workflow_config: dict[str, Any],
    infra: InfrastructureBundle,
) -> None:
    """Validate all configs before compilation.

    Checks references, schemas, and I/O wiring in a single pass.
    Raises ConfigValidationError with all errors collected.
    """
    errors = []
    self._validate_references(workflow_config, infra, errors)
    self._validate_schemas(workflow_config, infra, errors)
    self._validate_agent_io(workflow_config, infra, errors)
    if errors:
        raise ConfigValidationError(format_error_report(errors))
```

### Engine `compile()` drops validation

`_validate_all_configs()`, `_validate_stage_config()`, `_validate_agent_configs_for_stage()`,
and `_validate_agent_io()` are removed from the engine. The engine's `compile()` just
loads configs and builds the DAG.

### Validation helpers extracted

The existing validation logic from the engine moves to a standalone module:

`temper_ai/workflow/validation.py`

This module has no dependency on the engine — it takes a config_loader and
workflow_config dict, validates everything, returns errors. Both runtime and
engine can import it, but only runtime calls it.

## File Changes

| File | Change |
|---|---|
| `temper_ai/workflow/validation.py` | **New** — extracted validation logic (schemas, I/O, references) |
| `temper_ai/workflow/runtime.py` | `validate_references()` → `validate_all()`, calls `validation.py` |
| `temper_ai/workflow/engines/dynamic_engine.py` | Remove `_validate_all_configs()` and related methods from `compile()` |
| `temper_ai/workflow/engines/_validation_helpers.py` | Move to `temper_ai/workflow/validation.py` or import from it |

## Implementation Order

1. **Extract** — move validation logic from engine to `workflow/validation.py`
2. **Wire** — `runtime.validate_all()` calls the extracted module
3. **Remove** — delete validation methods from engine's `compile()`
4. **Test** — existing validation tests pass, invalid configs caught before compile

## Verification

- Invalid stage/agent references still caught with fuzzy suggestions
- Pydantic schema errors still caught and reported
- Agent I/O wiring errors still caught
- All errors reported in one batch (not fail-fast)
- `compile()` no longer raises validation errors
- Existing tests pass
