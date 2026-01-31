# Remove ServiceFactory References from Security Docs

**Date:** 2026-01-31
**Task:** docs-crit-import-04
**Priority:** P1 (Critical)
**Category:** Documentation - Code Mismatch

## Summary

Removed references to non-existent `ServiceFactory` class from security documentation. The documentation was using a service factory pattern that doesn't exist in the codebase, causing ImportError when users copied examples.

## Changes Made

### docs/security/M4_SAFETY_SYSTEM.md

**1. Replaced "Service Factory Registration" section (lines 480-494):**

**Before:**
```python
from src.core.service_factory import ServiceFactory
from src.safety.action_policy_engine import ActionPolicyEngine
from src.safety.policy_registry import PolicyRegistry

# Register policy registry
registry = PolicyRegistry()
ServiceFactory.register_service('policy_registry', registry, singleton=True)

# Register policy engine
engine = ActionPolicyEngine(registry, config=engine_config)
ServiceFactory.register_service('action_policy_engine', engine, singleton=True)
```

**After:**
```python
from src.safety.action_policy_engine import ActionPolicyEngine
from src.safety.policy_registry import PolicyRegistry

# Create policy registry
registry = PolicyRegistry()

# Create policy engine
engine = ActionPolicyEngine(registry, config=engine_config)

# Use the engine and registry in your application
# These instances can be stored and reused as needed
```

**2. Fixed AgentExecutor initialization (line 453):**

**Before:**
```python
def __init__(self, ...):
    self.policy_engine = ServiceFactory.get_service('action_policy_engine')
```

**After:**
```python
def __init__(self, policy_engine: ActionPolicyEngine, ...):
    self.policy_engine = policy_engine
```

## Impact

**Before:**
- Users copying examples would get `ModuleNotFoundError: No module named 'src.core.service_factory'`
- Integration examples were completely broken

**After:**
- All code examples use direct instantiation (actual pattern used in codebase)
- Examples show dependency injection pattern for ActionPolicyEngine
- No more non-existent imports

## Testing Performed

```bash
# Verified ServiceFactory doesn't exist
ls src/core/
# Output: __init__.py  __pycache__  service.py (no service_factory.py)

# Verified actual usage pattern in codebase
grep "PolicyRegistry()" src -r
# Found direct instantiation in docstrings

# Verified no more ServiceFactory references
grep -r "ServiceFactory" docs/
# No matches found
```

## Files Modified

- `docs/security/M4_SAFETY_SYSTEM.md` - Removed ServiceFactory, updated to direct instantiation

## Risks

**None** - Documentation-only change with no code modifications

## Follow-up Tasks

None required. All ServiceFactory references have been removed from security documentation.

## Notes

- The actual pattern in the codebase is direct instantiation of PolicyRegistry and ActionPolicyEngine
- The AgentExecutor now uses dependency injection for the policy engine (cleaner pattern)
- Service factory pattern may have been planned but was never implemented
- This aligns documentation with actual codebase implementation
