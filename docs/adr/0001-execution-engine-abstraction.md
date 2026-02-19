# ADR-0001: Execution Engine Abstraction Layer

**Date:** 2026-01-27
**Status:** Accepted
**Deciders:** Framework Core Team, solution-architect specialist
**Tags:** architecture, execution, decoupling, M2.5

---

## Context

After completing Milestone 2 (M2), the framework had a working workflow execution system built directly on LangGraph. However, the system was tightly coupled to LangGraph's API, creating several risks:

**Problem Statement:**
- The framework was vendor-locked to LangGraph with no ability to switch execution backends
- Future features (M5+) like convergence detection and self-modifying workflows would be difficult to implement with LangGraph's architecture
- No way to experiment with alternative execution engines (Temporal, Ray, custom implementations)
- Migration to a different engine at M6+ would require 17-24 weeks of refactoring effort

**Current Situation (M2):**
```python
# Direct LangGraph usage - tightly coupled
from temper_ai.compiler.langgraph_compiler import LangGraphCompiler
compiler = LangGraphCompiler(tool_registry, config_loader)
graph = compiler.compile(workflow_config)
result = graph.invoke({"topic": "TypeScript"})
```

**Key Questions:**
1. Should we decouple from LangGraph now (at M2.5) or wait until we need it (M5+)?
2. What abstraction level prevents vendor lock-in without over-engineering?
3. Can we maintain 100% backward compatibility with M2?
4. What's the ROI of decoupling now vs. later?

---

## Decision Drivers

- **Vendor Lock-In Risk** - HIGH: Complete dependence on LangGraph's API and evolution
- **M5+ Feature Enablement** - Convergence detection, meta-circular execution, self-modifying workflows require custom execution logic
- **Migration Cost** - At M6: 24 weeks without abstraction vs. 6.5 weeks with abstraction
- **Experimentation** - Need to A/B test execution engines in production
- **Backward Compatibility** - M2 workflows must continue working unchanged
- **Development Time** - Current investment (1.5 days) vs. future migration time (61.5 days saved)
- **ROI** - 41× return on investment

---

## Considered Options

### Option 1: Continue Direct LangGraph Usage (Status Quo)

**Description:** Keep using LangGraph directly as in M2, defer abstraction until needed.

**Pros:**
- Zero immediate effort required
- No risk of abstraction errors
- Simple and straightforward

**Cons:**
- Vendor lock-in to LangGraph continues
- M5+ features blocked or very difficult to implement
- Migration at M6 requires 17-24 weeks of refactoring
- Experimental engines impossible
- High long-term cost and risk

**Effort:** None now, but 17-24 weeks later

---

### Option 2: Lightweight Abstraction Layer (Adapter Pattern)

**Description:** Add a thin ExecutionEngine interface that wraps LangGraph without changing M2 code. Use adapter pattern to preserve existing functionality.

**Pros:**
- **Decoupling:** Framework independent of LangGraph API
- **Backward Compatible:** Zero changes to M2 workflows or tests
- **Low Risk:** Adapter wraps existing code, no refactoring
- **Low Overhead:** <1ms performance impact
- **M5+ Ready:** Enables convergence detection and custom engines
- **ROI: 41×** - 1.5 days saves 61.5 days on future migrations
- **Experimentation:** Can now build custom engines and A/B test

**Cons:**
- 1.5 days of development time now
- Adds one layer of indirection (minimal complexity)
- Need to maintain adapter wrapper

**Effort:** 1.5 days (LOW)

---

### Option 3: Full Execution Framework Replacement

**Description:** Replace LangGraph entirely with a custom execution framework now.

**Pros:**
- Complete control over execution engine
- No vendor dependencies at all
- Perfect fit for framework's needs

**Cons:**
- **Massive Effort:** 4-6 weeks to build custom engine
- **High Risk:** Complex, bug-prone, requires extensive testing
- **Premature:** Don't yet know all requirements for M5+
- **Maintenance Burden:** Now maintaining entire execution engine
- **Over-Engineering:** Solving problems we don't have yet

**Effort:** 4-6 weeks (HIGH)

---

## Decision Outcome

**Chosen Option:** Option 2: Lightweight Abstraction Layer (Adapter Pattern)

**Justification:**

The lightweight abstraction layer using the adapter pattern provides the perfect balance:

1. **Minimal Investment, Maximum Return** - 1.5 days investment saves 61.5 days on future migrations (41× ROI)

2. **Zero Breaking Changes** - Adapter wraps existing LangGraph code, maintaining 100% backward compatibility with M2

3. **Enables M5+ Features** - Creates foundation for convergence detection, self-modifying workflows, meta-circular execution without LangGraph constraints

4. **Low Risk** - No refactoring of M2 code required, just wrapping existing functionality

5. **Experimentation Ready** - Can now build custom engines for research and A/B testing in production

6. **Right Timing** - At M2.5, coupling to LangGraph is minimal (only ~200 lines). Waiting until M6 would mean 2000+ lines to refactor.

**Decision Factors:**
- Migration cost without abstraction (M6): **17-24 weeks**
- Migration cost with abstraction (M6): **6.5 weeks**
- Time saved: **61.5 days** (10.5-17.5 weeks)
- Investment cost: **1.5 days**
- **ROI: 41× return**

The decision is a strategic investment with exceptional ROI that prevents vendor lock-in while maintaining backward compatibility.

---

## Consequences

### Positive

- **Vendor Independence** - Can switch from LangGraph to alternatives (Temporal, Ray, custom) with 6.5 weeks effort instead of 24 weeks
- **M5+ Features Enabled** - Convergence detection, self-modifying workflows, meta-circular execution now feasible
- **Experimentation** - Custom engines for research and production A/B testing
- **Testing** - Mock engines for fast unit testing without real LLM calls
- **Optimization** - Engine-specific optimizations without changing workflow definitions
- **Low Overhead** - <1ms performance impact per stage execution
- **Backward Compatible** - All M2 workflows and tests work unchanged

### Negative

- **Complexity** - One additional layer of indirection (ExecutionEngine → LangGraph)
- **Maintenance** - Need to maintain adapter wrapper (but minimal, ~150 lines)
- **Learning Curve** - Developers need to understand abstraction layer
- **Documentation** - Need to document engine interface and custom engine creation

### Neutral

- **Engine Selection** - LangGraph remains default engine (no change in behavior)
- **Plugin System** - Custom engines can be added via registry (new capability, optional)

---

## Implementation Notes

**Architecture:**

```
Workflow Definition (YAML)
       ↓
WorkflowCompiler
       ↓
ExecutionEngine (abstract interface)
       ↓
LangGraphAdapter | CustomEngine | MockEngine
       ↓
Actual Execution Backend
```

**Key Components:**

1. **ExecutionEngine Interface** (`temper_ai/compiler/execution_engine.py`)
   - `compile(workflow_config)` → CompiledWorkflow
   - `execute(compiled_workflow, input_data, mode)` → result
   - `supports_feature(feature)` → bool

2. **LangGraph Adapter** (`temper_ai/compiler/langgraph_engine.py`)
   - Wraps existing LangGraphCompiler
   - Implements ExecutionEngine interface
   - Zero changes to M2 code

3. **Engine Registry** (`temper_ai/compiler/engine_registry.py`)
   - Factory pattern for engine selection
   - Config-based and programmatic APIs
   - Plugin architecture for custom engines

**Migration Strategy:**

1. Create abstraction interfaces (ExecutionEngine, CompiledWorkflow)
2. Build LangGraph adapter wrapping existing code (no M2 changes)
3. Create EngineRegistry for runtime selection
4. Update imports to use registry instead of direct LangGraph
5. Verify all M2 tests still pass (100% backward compatibility)

**Action Items:**
- [x] Create ExecutionEngine interface
- [x] Implement LangGraph adapter
- [x] Create EngineRegistry factory
- [x] Update all imports
- [x] Verify backward compatibility (all M2 tests passing)
- [x] Document architecture and custom engine tutorial

---

## Related Decisions

- [ADR-0002: LangGraph as Initial Engine](./0002-langgraph-as-initial-engine.md) - Why LangGraph was chosen for M2
- [ADR-0005: YAML-Based Configuration](./0005-yaml-based-configuration.md) - Workflow definition format

---

## References

- [Milestone 2.5 Completion Report](../milestones/milestone2.5_completion.md)
- [Execution Engine Architecture](../features/execution/execution_engine_architecture.md)
- [Custom Engine Guide](../features/execution/custom_engine_guide.md)
- [Adapter Pattern](https://refactoring.guru/design-patterns/adapter) - Design pattern documentation
- [TECHNICAL_SPECIFICATION.md](../../TECHNICAL_SPECIFICATION.md) - Section on execution engines

---

## Update History

| Date | Author | Change |
|------|--------|--------|
| 2026-01-27 | Framework Core Team | Initial draft |
| 2026-01-28 | agent-d6e90e | Backfilled from M2.5 completion |
