# ADR-0007: M4 Layered Safety System with Composable Policies

**Date:** 2026-01-30
**Status:** Accepted
**Deciders:** Framework Core Team
**Tags:** safety, governance, M4, policies, security, composable

---

## Context

Autonomous agents require safety guardrails before production deployment. Without proper safety mechanisms, agents could perform dangerous operations, consume excessive resources, or leak sensitive data.

**Problem Statement:**
- Autonomous agents can execute arbitrary actions (file writes, API calls, commands)
- Different actions have different risk profiles (file read vs delete)
- Need human approval for high-risk operations
- Must prevent cascading failures and blast radius expansion
- Performance critical: <5ms validation overhead
- Diverse safety requirements: file access, rate limiting, secrets detection, blast radius

**Use Cases:**
1. **File Access Control** - Prevent path traversal and unauthorized file access
2. **Operation Blocking** - Block dangerous commands (rm -rf, drop table)
3. **Rate Limiting** - Prevent resource exhaustion from excessive API calls
4. **Circuit Breaking** - Stop cascading failures when error rate spikes
5. **Secret Detection** - Block actions containing credentials or API keys
6. **Blast Radius** - Limit scope of changes (max files modified)
7. **Approval Workflow** - Human-in-the-loop for high-risk actions

**Key Questions:**
- How do we validate actions before execution without performance impact?
- How do we compose multiple safety policies for a single action?
- How do we extend safety policies without modifying core framework?
- How do we track safety violations for learning loops?

---

## Decision Drivers

- **Safety** - CRITICAL violations must block execution (P0 requirement)
- **Performance** - <5ms overhead for safety checks (P1 requirement)
- **Extensibility** - Easy to add new policies without modifying core (P1 requirement)
- **Composability** - Multiple policies apply to single action (P1 requirement)
- **Observability** - Track all violations for learning loops (P2 requirement)
- **Flexibility** - Different policies for different action types (P2 requirement)
- **Human Oversight** - High-risk actions require approval (P0 requirement)
- **Developer Experience** - Clear policy interface and testing (P2 requirement)

---

## Considered Options

### Option 1: Single Monolithic Safety Validator

**Description:** One large SafetyValidator class with all validation logic.

**Pros:**
- Simple - all logic in one place
- Easy to understand flow
- No indirection
- Fast - direct method calls

**Cons:**
- Hard to extend (modify core class every time)
- Becomes god class (1000+ lines)
- Tight coupling of all safety concerns
- All-or-nothing validation (cannot disable specific checks)
- Testing difficult (mock entire validator)
- Violation tracking mixed with validation logic

**Effort:** Low (2-3 days)

---

### Option 2: Rule Engine (Drools, JSON Rules)

**Description:** Declarative rule engine with JSON/YAML rule definitions.

**Pros:**
- Declarative rules (no code changes)
- Business-friendly syntax
- Runtime rule updates
- Proven technology (Drools)

**Cons:**
- Adds external dependency (Drools JVM, or Python rule engine)
- Learning curve for rule syntax
- Debugging difficult (rule evaluation traces)
- Performance overhead (rule parsing/evaluation)
- Testing complex (mock rule engine)
- Overkill for programmatic policies

**Effort:** High (1-2 weeks)

---

### Option 3: Layered Architecture with Policy Composition

**Description:** Separate SafetyPolicy interface with multiple implementations, composed via PolicyRegistry and PolicyComposer.

**Pros:**
- **Separation of Concerns** - Each policy is independent class
- **Extensibility** - Add new policies without modifying engine
- **Priority-based** - Execute high-priority policies first
- **Fail-fast** - Short-circuit on CRITICAL violations
- **Independent Testing** - Each policy tested in isolation
- **Composability** - Multiple policies per action type
- **Performance** - <5ms for 10 policies with caching

**Cons:**
- More files/classes (7+ policy classes)
- Indirection overhead (registry lookup)
- Policy coordination complexity
- Learning curve for policy interface

**Effort:** Medium (5-6 days)
**Performance:** <1ms single policy, <5ms for 10 policies

---

### Option 4: Aspect-Oriented Programming (AOP) with Decorators

**Description:** Use Python decorators to weave safety checks into action execution.

**Pros:**
- Clean separation via @decorators
- Automatic application
- Familiar Python pattern
- No explicit calls

**Cons:**
- Python AOP support limited
- Debugging difficult (hidden execution flow)
- Hard to compose multiple decorators
- Decorator order matters (fragile)
- Testing complex (mock decorated functions)
- Performance overhead (decorator chain)

**Effort:** Medium-High (6-8 days)

---

## Decision Outcome

**Chosen Option:** Option 3: Layered Architecture with Policy Composition

**Justification:**

We selected the layered architecture because it provides the best balance of extensibility, performance, and maintainability:

1. **Separation of Concerns** - Each policy is a focused, testable class
2. **Extensibility** - Add new policies without modifying ActionPolicyEngine
3. **Performance** - <1ms per policy, <5ms for 10 policies (cache optimization)
4. **Fail-Fast** - Short-circuit on CRITICAL violations saves time
5. **Priority** - Execute high-priority policies first (security before perf)
6. **Testability** - 177 tests with 100% coverage achieved
7. **Observability** - Built-in violation tracking
8. **ROI** - 5-6 day investment delivers production-ready safety

**Measured Performance:**
- Single policy validation: <1ms
- 10 policies validation: <5ms
- Cache hit validation: <0.1ms
- Overhead: <1% for most operations

**Decision Factors:**
- Monolithic validator would become unmaintainable (god class anti-pattern)
- Rule engine adds complexity without benefit for programmatic policies
- AOP/decorators hide execution flow, harder to debug
- Layered architecture is standard industry pattern (proven)

---

## Consequences

### Positive

- **Production Safety** - Safe autonomous operation with <1% overhead
- **Performance** - <5ms validation for 10 policies (P1 requirement met)
- **Extensibility** - 6 policy types implemented, easy to add more
- **Test Coverage** - 100% coverage with 177 tests
- **Documentation** - 3,650+ lines of comprehensive documentation
- **Human Oversight** - High-risk actions require approval workflow
- **Circuit Breaking** - Prevents cascading failures
- **Rollback** - Failed operations can be rolled back
- **Metrics** - All violations tracked for observability

### Negative

- **Complexity** - More files/classes than monolithic validator
- **Indirection** - Registry and composer add layers
- **Learning Curve** - Developers must learn SafetyPolicy interface
- **Coordination** - Multiple policies must coordinate priority/execution

### Neutral

- **Interface Contract** - Policies must implement SafetyPolicy interface
- **Registration** - Action types must be registered in PolicyRegistry
- **Synchronous** - Validation is synchronous (async support if needed later)

---

## Implementation Notes

**Architecture:**

```python
# Policy Interface
class SafetyPolicy(ABC):
    name: str
    priority: int  # Higher = executed first

    @abstractmethod
    def validate(self, action: Action, context: Context) -> ValidationResult:
        """Validate action against safety policy."""
        pass

# Layered execution flow
Agent Action Request
      ↓
ActionPolicyEngine (orchestration)
      ↓
PolicyRegistry (lookup by action type)
      ↓
PolicyComposer (execute multiple policies)
      ↓
Individual SafetyPolicy implementations
      ↓
ValidationResult (allow/block + violations)
```

**Core Components:**

1. **SafetyPolicy Interface** (`src/safety/interfaces.py` - 100 lines)
   - Abstract base class for all policies
   - Severity levels: CRITICAL, HIGH, MEDIUM, LOW, INFO
   - ValidationResult with allow/block + violation details

2. **PolicyRegistry** (`src/safety/policy_registry.py` - 100+ lines)
   - Register policies by action type
   - Global policies (apply to all actions)
   - Priority-based ordering
   - Policy lookup by action type

3. **PolicyComposer** (`src/safety/composition.py` - 80+ lines)
   - Execute multiple policies in priority order
   - Fail-fast mode: stop on first CRITICAL violation
   - Complete mode: run all policies, aggregate violations
   - Short-circuit optimization

4. **ActionPolicyEngine** (`src/safety/action_policy_engine.py` - 150+ lines)
   - Orchestration layer
   - Result caching (60s TTL)
   - Short-circuit on CRITICAL violations
   - Observability integration

**Implemented Policy Types:**

| Policy | Purpose | Priority | Files |
|--------|---------|----------|-------|
| FileAccessPolicy | Path traversal protection | 100 | src/safety/file_access.py |
| ForbiddenOperationsPolicy | Block dangerous commands | 90 | src/safety/forbidden_ops.py |
| SecretDetectionPolicy | Credential scanning | 80 | src/safety/secret_detection.py |
| RateLimitPolicy | Token bucket rate limiting | 70 | src/safety/rate_limit.py |
| CircuitBreakerPolicy | Failure rate thresholds | 60 | src/safety/circuit_breaker.py |
| BlastRadiusPolicy | Scope limiting | 50 | src/safety/blast_radius.py |

**Severity Levels:**

| Level | Priority | Action | Use Case |
|-------|----------|--------|----------|
| CRITICAL | 5 | Block immediately, no retry | rm -rf /, drop table |
| HIGH | 4 | Require approval/escalation | File writes, API changes |
| MEDIUM | 3 | Warning + logging | Large file reads |
| LOW | 2 | Logging only | Info messages |
| INFO | 1 | Informational | Audit trail |

**Configuration:**

```yaml
safety:
  policies:
    file_access:
      enabled: true
      allowed_paths:
        - /app/data
        - /tmp
      denied_paths:
        - /etc
        - /root

    rate_limit:
      enabled: true
      tokens_per_minute: 60
      burst_size: 10

    circuit_breaker:
      enabled: true
      failure_threshold: 0.5
      min_requests: 10
      timeout_seconds: 60

    blast_radius:
      enabled: true
      max_files_modified: 10
      max_lines_modified: 1000
```

**Performance Characteristics:**

| Metric | Value |
|--------|-------|
| Single policy | <1ms |
| 10 policies | <5ms |
| Cache hit | <0.1ms |
| Overhead | <1% |
| Memory | ~500KB (policy registry) |

**Action Items:**
- [x] Define SafetyPolicy interface
- [x] Implement PolicyRegistry
- [x] Implement PolicyComposer
- [x] Implement ActionPolicyEngine
- [x] Implement 6 core policies (FileAccess, ForbiddenOps, Secrets, RateLimit, CircuitBreaker, BlastRadius)
- [x] Add approval workflow for HIGH severity
- [x] Add rollback mechanism
- [x] Add observability tracking
- [x] Achieve 100% test coverage (177 tests)
- [x] Write comprehensive documentation (3,650+ lines)

---

## Related Decisions

- [ADR-0001: Execution Engine Abstraction](./0001-execution-engine-abstraction.md) - Safety layer independent of engine
- [ADR-0003: Multi-Agent Collaboration Strategies](./0003-multi-agent-collaboration-strategies.md) - Safety applies to agent actions
- [ADR-0004: Observability Database Schema](./0004-observability-database-schema.md) - Track safety violations
- [ADR-0006: M3 Parallel Execution Architecture](./0006-m3-parallel-execution-architecture.md) - Safety applies to parallel agents

---

## References

- [Milestone 4 Completion Report](../milestones/milestone4_completion.md)
- [Safety System Guide](../features/safety/safety_system_guide.md)
- [Policy Development Guide](../features/safety/policy_development_guide.md)
- [Safety Policy Interface](../../src/safety/interfaces.py)
- [Implementation: src/safety/](../../src/safety/)
- [TECHNICAL_SPECIFICATION.md](../../TECHNICAL_SPECIFICATION.md) - M4 specification
- [Design Patterns: Strategy Pattern](https://refactoring.guru/design-patterns/strategy)
- [Design Patterns: Composite Pattern](https://refactoring.guru/design-patterns/composite)
- [Design Patterns: Registry Pattern](https://martinfowler.com/eaaCatalog/registry.html)

---

## Update History

| Date | Author | Change |
|------|--------|--------|
| 2026-01-30 | agent-cf221d | Initial decision record (backfilled from M4 implementation) |
