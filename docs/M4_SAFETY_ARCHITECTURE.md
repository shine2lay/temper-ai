# M4 Safety & Governance System - Architecture Documentation

## Overview

The M4 Safety & Governance System provides comprehensive, multi-layered protection for autonomous agent operations. It implements defense-in-depth through policy composition, human approval workflows, automatic rollback, and circuit breaker protection.

**Version:** 1.0.0
**Status:** Production Ready
**Last Updated:** 2026-01-27

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Core Components](#core-components)
- [Component Interactions](#component-interactions)
- [Data Flow](#data-flow)
- [Deployment Architecture](#deployment-architecture)
- [Security Model](#security-model)
- [Performance Characteristics](#performance-characteristics)

---

## Architecture Overview

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     User / Agent Application                     │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                      M4 Safety Gateway                           │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────┐   │
│  │ SafetyGate   │  │ PolicyComp.  │  │ CircuitBreaker     │   │
│  │ (Entry Point)│→ │ (Validation) │→ │ (Failure Protect.) │   │
│  └──────────────┘  └──────────────┘  └────────────────────┘   │
└────────────────────────────┬────────────────────────────────────┘
                             │
                ┌────────────┼────────────┐
                ▼            ▼            ▼
    ┌─────────────────┐ ┌──────────┐ ┌─────────────┐
    │ ApprovalWorkflow│ │ Rollback │ │ Observability│
    │ (Human-in-Loop) │ │ Manager  │ │  (Metrics)   │
    └─────────────────┘ └──────────┘ └─────────────┘
```

### Design Principles

1. **Defense in Depth**: Multiple independent safety layers
2. **Fail-Safe Defaults**: Block by default, allow explicitly
3. **Composability**: Components work independently or together
4. **Observable**: Full metrics and audit trail
5. **Non-Blocking**: Minimal performance overhead
6. **Extensible**: Easy to add custom policies and strategies

### Safety Layers

| Layer | Component | Purpose | Failure Mode |
|-------|-----------|---------|--------------|
| 1 | **Policy Validation** | Enforce rules (file access, rate limits, etc.) | BLOCK action |
| 2 | **Circuit Breaker** | Prevent cascading failures | BLOCK action |
| 3 | **Approval Workflow** | Human oversight for high-risk actions | WAIT for approval |
| 4 | **Execution** | Perform action with monitoring | Execute with tracking |
| 5 | **Rollback** | Automatic recovery on failure | REVERT changes |

---

## Core Components

### 1. PolicyComposer

**Purpose:** Validates actions against multiple safety policies in priority order.

**Architecture:**
```
┌──────────────────────────────────────┐
│         PolicyComposer                │
│                                       │
│  ┌─────────────────────────────┐    │
│  │ Policies (sorted by priority)│    │
│  │                               │    │
│  │  Priority 1000: Security      │    │
│  │  Priority  900: Secrets       │    │
│  │  Priority  800: File Access   │    │
│  │  Priority  500: Rate Limit    │    │
│  │  Priority  100: Custom        │    │
│  └─────────────────────────────┘    │
│                                       │
│  Modes:                               │
│  • fail_fast: Stop on first violation │
│  • complete: Collect all violations   │
└──────────────────────────────────────┘
```

**Key Features:**
- Priority-based policy execution (highest first)
- Fail-fast or complete validation modes
- Exception handling (policy failures → CRITICAL violations)
- Async support for I/O-bound policies
- Violation aggregation and filtering

**Usage Pattern:**
```python
composer = PolicyComposer(fail_fast=False)
composer.add_policy(SecretDetectionPolicy())     # Priority: 900
composer.add_policy(FileAccessPolicy({...}))     # Priority: 800
composer.add_policy(RateLimiterPolicy({...}))    # Priority: 500

result = composer.validate(action, context)
if result.has_blocking_violations():
    handle_violations(result.violations)
```

### 2. ApprovalWorkflow

**Purpose:** Human-in-the-loop approval for high-risk actions.

**Architecture:**
```
┌──────────────────────────────────────────────┐
│         ApprovalWorkflow                      │
│                                               │
│  Request States:                              │
│  ┌─────────┐  ┌──────────┐  ┌──────────┐   │
│  │ PENDING │→ │ APPROVED │→ │ EXECUTED │   │
│  └─────────┘  └──────────┘  └──────────┘   │
│       ↓                                       │
│  ┌─────────┐                                 │
│  │REJECTED │                                  │
│  └─────────┘                                 │
│       ↓                                       │
│  ┌─────────┐                                 │
│  │ EXPIRED │                                  │
│  └─────────┘                                 │
│                                               │
│  Features:                                    │
│  • Multi-approver support                    │
│  • Timeout with auto-reject                  │
│  • Callbacks (on_approved, on_rejected)      │
│  • Safety violation integration              │
└──────────────────────────────────────────────┘
```

**Key Features:**
- Multi-approver consensus (require N approvals)
- Timeout-based auto-rejection
- Approval/rejection callbacks for notifications
- Complete audit trail (who, when, why)
- Integration with safety violations

**Usage Pattern:**
```python
workflow = ApprovalWorkflow(
    default_timeout_minutes=60,
    auto_reject_on_timeout=True
)

request = workflow.request_approval(
    action={"tool": "deploy", "env": "production"},
    reason="Production deployment requires approval",
    required_approvers=2
)

# Human approval
workflow.approve(request.id, approver="tech_lead", reason="Looks good")
workflow.approve(request.id, approver="ops_lead", reason="Infrastructure ready")

if workflow.is_approved(request.id):
    execute_action()
```

### 3. RollbackManager

**Purpose:** Automatic state capture and rollback on failures.

**Architecture:**
```
┌────────────────────────────────────────────┐
│        RollbackManager                      │
│                                             │
│  Strategies:                                │
│  ┌──────────────────────────────────┐     │
│  │ FileRollbackStrategy             │     │
│  │ • Captures file contents         │     │
│  │ • Restores on rollback           │     │
│  │ • Deletes created files          │     │
│  └──────────────────────────────────┘     │
│                                             │
│  ┌──────────────────────────────────┐     │
│  │ StateRollbackStrategy            │     │
│  │ • Captures in-memory state       │     │
│  │ • Custom state getters           │     │
│  └──────────────────────────────────┘     │
│                                             │
│  ┌──────────────────────────────────┐     │
│  │ CompositeRollbackStrategy        │     │
│  │ • Combines multiple strategies   │     │
│  │ • Aggregates results             │     │
│  └──────────────────────────────────┘     │
└────────────────────────────────────────────┘
```

**Key Features:**
- Multiple rollback strategies (file, state, custom)
- Snapshot metadata tracking
- Partial rollback handling
- Rollback history and audit
- Custom strategy extensibility

**Usage Pattern:**
```python
rollback_mgr = RollbackManager()

# Before risky operation
snapshot = rollback_mgr.create_snapshot(
    action={"tool": "update_config", "file": "/etc/app.conf"},
    context={"agent": "config_manager"}
)

try:
    execute_risky_operation()
except Exception:
    # Rollback on failure
    result = rollback_mgr.execute_rollback(snapshot.id)
    if result.success:
        logger.info("Rolled back successfully")
```

### 4. CircuitBreaker

**Purpose:** Prevent cascading failures through automatic failure detection.

**Architecture:**
```
┌──────────────────────────────────────────────┐
│         CircuitBreaker                        │
│                                               │
│  State Machine:                               │
│                                               │
│    ┌─────────┐                               │
│    │ CLOSED  │ (Normal operation)            │
│    │         │ Allow all requests            │
│    └────┬────┘                               │
│         │                                     │
│         │ N failures                          │
│         ▼                                     │
│    ┌─────────┐                               │
│    │  OPEN   │ (Failure detected)            │
│    │         │ Block all requests            │
│    └────┬────┘                               │
│         │                                     │
│         │ Timeout elapsed                     │
│         ▼                                     │
│    ┌──────────┐                              │
│    │HALF_OPEN │ (Testing recovery)           │
│    │          │ Allow limited requests       │
│    └────┬─────┘                              │
│         │                                     │
│    Success │ Failure                          │
│         │                                     │
│    ┌────▼──┐ │                               │
│    │CLOSED │ │                                │
│    └───────┘ │                                │
│              ▼                                 │
│         ┌─────────┐                           │
│         │  OPEN   │                           │
│         └─────────┘                           │
└──────────────────────────────────────────────┘
```

**Key Features:**
- Three-state pattern (CLOSED → OPEN → HALF_OPEN)
- Configurable failure threshold
- Automatic recovery testing
- Metrics tracking (success/failure rates)
- Thread-safe implementation

**Usage Pattern:**
```python
breaker = CircuitBreaker(
    name="external_api",
    failure_threshold=5,      # Open after 5 failures
    timeout_seconds=60,        # Wait 60s before retry
    success_threshold=2        # Need 2 successes to close
)

try:
    with breaker():
        call_external_api()
except CircuitBreakerOpen:
    use_fallback_logic()
```

### 5. SafetyGate

**Purpose:** Unified entry point coordinating all safety mechanisms.

**Architecture:**
```
┌────────────────────────────────────────────┐
│          SafetyGate                         │
│                                             │
│  Validation Chain:                          │
│                                             │
│  1. Manual Block Check                     │
│      ↓                                      │
│  2. Circuit Breaker Check                  │
│      ↓                                      │
│  3. Policy Validation                      │
│      ↓                                      │
│  4. Result: PASS or BLOCKED (with reasons) │
│                                             │
│  Usage Modes:                               │
│  • can_pass() → boolean                    │
│  • validate() → (bool, reasons)            │
│  • context manager → raise on block        │
└────────────────────────────────────────────┘
```

**Key Features:**
- Single validation point for multiple checks
- Detailed block reasons
- Manual block/unblock capability
- Context manager support
- Integrates circuit breaker + policies

**Usage Pattern:**
```python
gate = SafetyGate(
    name="production_gate",
    circuit_breaker=breaker,
    policy_composer=composer
)

# Simple check
if gate.can_pass(action, context):
    execute_action()

# Detailed validation
can_pass, reasons = gate.validate(action, context)
if not can_pass:
    logger.warning(f"Blocked: {'; '.join(reasons)}")

# Context manager
with gate(action=action, context=context):
    execute_action()
```

---

## Component Interactions

### Typical Request Flow

```
┌──────────────┐
│ User Action  │
└──────┬───────┘
       │
       ▼
┌─────────────────────────────────────────────┐
│ 1. SafetyGate Entry                          │
│    • Check manual block                      │
│    • Check circuit breaker state             │
└──────┬──────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────┐
│ 2. PolicyComposer Validation                 │
│    • Execute policies by priority            │
│    • Aggregate violations                    │
│    • Return validation result                │
└──────┬──────────────────────────────────────┘
       │
       ├─ BLOCKED → Return error
       │
       ▼ ALLOWED
┌─────────────────────────────────────────────┐
│ 3. ApprovalWorkflow (if required)            │
│    • Create approval request                 │
│    • Wait for human approval                 │
│    • Check timeout                            │
└──────┬──────────────────────────────────────┘
       │
       ├─ REJECTED/EXPIRED → Return error
       │
       ▼ APPROVED
┌─────────────────────────────────────────────┐
│ 4. RollbackManager Snapshot                  │
│    • Capture pre-action state                │
│    • Store snapshot for recovery             │
└──────┬──────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────┐
│ 5. Execute Action (via CircuitBreaker)       │
│    • Execute within circuit breaker          │
│    • Track success/failure                   │
└──────┬──────────────────────────────────────┘
       │
       ├─ SUCCESS → Record success, return result
       │
       ▼ FAILURE
┌─────────────────────────────────────────────┐
│ 6. Automatic Rollback                        │
│    • Execute rollback strategy               │
│    • Restore previous state                  │
│    • Log rollback result                     │
└─────────────────────────────────────────────┘
```

### Component Dependencies

```
┌─────────────────┐
│  SafetyGate     │ (Orchestrator)
└────────┬────────┘
         │
    ┌────┴─────┬────────────┬──────────────┐
    │          │            │              │
    ▼          ▼            ▼              ▼
┌──────┐  ┌────────┐  ┌─────────┐  ┌──────────┐
│Policy│  │Circuit │  │Approval │  │Rollback  │
│Comp. │  │Breaker │  │Workflow │  │Manager   │
└──────┘  └────────┘  └─────────┘  └──────────┘
    │          │            │              │
    └──────────┴────────────┴──────────────┘
                     │
                     ▼
            ┌─────────────────┐
            │  Observability   │
            │  (Metrics/Logs)  │
            └─────────────────┘
```

---

## Data Flow

### 1. Policy Validation Flow

```
Action + Context
    ↓
PolicyComposer
    ↓
For each policy (priority order):
    ├─ Execute policy.validate()
    ├─ Collect violations
    └─ If fail_fast and violations: STOP
    ↓
Aggregate Results
    ├─ CompositeValidationResult
    ├─ • valid: bool
    ├─ • violations: List[SafetyViolation]
    ├─ • policy_results: Dict
    ├─ • policies_evaluated: int
    └─ • execution_order: List[str]
```

### 2. Approval Workflow Flow

```
Approval Request
    ├─ action: Dict
    ├─ reason: str
    ├─ required_approvers: int
    ├─ timeout: datetime
    └─ violations: List[SafetyViolation]
    ↓
Store Request (PENDING)
    ↓
Wait for Approvals
    ↓
On Each Approval:
    ├─ Add approver to list
    ├─ Check if enough approvals
    └─ If yes: PENDING → APPROVED
    ↓
On Timeout:
    └─ PENDING → EXPIRED (if auto_reject)
    ↓
On Rejection:
    └─ PENDING → REJECTED
```

### 3. Rollback Flow

```
Create Snapshot:
    ├─ action: Dict
    ├─ context: Dict
    ├─ strategy: RollbackStrategy
    └─ Execute strategy.create_snapshot()
        ├─ File snapshots: {path: content}
        ├─ State snapshots: {key: value}
        └─ Metadata: Dict
    ↓
Store Snapshot
    ↓
On Rollback Request:
    ├─ Retrieve snapshot
    ├─ Validate rollback is safe
    └─ Execute strategy.execute_rollback()
        ├─ Restore files
        ├─ Restore state
        ├─ Track success/failures
        └─ Return RollbackResult
```

### 4. Circuit Breaker Flow

```
Request Execution:
    ↓
Check State:
    ├─ CLOSED → Allow
    ├─ OPEN → Check timeout
    │   ├─ Timeout elapsed → HALF_OPEN, Allow
    │   └─ Not elapsed → REJECT
    └─ HALF_OPEN → Allow (limited)
    ↓
Execute:
    ├─ SUCCESS:
    │   ├─ CLOSED: continue
    │   └─ HALF_OPEN: increment success
    │       └─ Enough successes? → CLOSED
    └─ FAILURE:
        ├─ CLOSED: increment failures
        │   └─ Threshold reached? → OPEN
        └─ HALF_OPEN: → OPEN (immediate)
```

---

## Deployment Architecture

### Single-Process Deployment

```
┌────────────────────────────────────────┐
│         Application Process             │
│                                         │
│  ┌────────────────────────────────┐   │
│  │ M4 Safety System (In-Process)  │   │
│  │                                 │   │
│  │  • PolicyComposer              │   │
│  │  • ApprovalWorkflow            │   │
│  │  • RollbackManager             │   │
│  │  • CircuitBreakerManager       │   │
│  └────────────────────────────────┘   │
│                                         │
│  ┌────────────────────────────────┐   │
│  │  Application Logic              │   │
│  └────────────────────────────────┘   │
└────────────────────────────────────────┘
```

**Use Cases:**
- Single-agent applications
- Development/testing environments
- Low-scale deployments

**Pros:**
- Simple setup
- No network overhead
- Easy debugging

**Cons:**
- No shared state across processes
- No centralized approval queue
- Limited scalability

### Multi-Process Deployment (Shared State)

```
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│  Agent 1     │  │  Agent 2     │  │  Agent N     │
│              │  │              │  │              │
│  M4 Client   │  │  M4 Client   │  │  M4 Client   │
└──────┬───────┘  └──────┬───────┘  └──────┬───────┘
       │                 │                 │
       └─────────────────┼─────────────────┘
                         │
                         ▼
              ┌─────────────────────┐
              │  M4 Safety Service   │
              │                      │
              │  • Shared Policies   │
              │  • Approval Queue    │
              │  • Circuit Breakers  │
              │  • Rollback Storage  │
              └──────────┬───────────┘
                         │
                         ▼
              ┌─────────────────────┐
              │  Persistent Storage  │
              │  (Redis/PostgreSQL)  │
              └─────────────────────┘
```

**Use Cases:**
- Multi-agent systems
- Production deployments
- Coordinated safety enforcement

**Pros:**
- Shared safety state
- Centralized approval queue
- Coordinated circuit breakers
- Scalable architecture

**Cons:**
- More complex setup
- Network latency
- Additional infrastructure

### Kubernetes Deployment

```
┌────────────────────────────────────────────────┐
│              Kubernetes Cluster                 │
│                                                 │
│  ┌──────────────────────────────────────────┐ │
│  │       M4 Safety Service Deployment        │ │
│  │                                            │ │
│  │  ┌─────────┐  ┌─────────┐  ┌─────────┐  │ │
│  │  │ Pod 1   │  │ Pod 2   │  │ Pod N   │  │ │
│  │  │ M4 API  │  │ M4 API  │  │ M4 API  │  │ │
│  │  └─────────┘  └─────────┘  └─────────┘  │ │
│  │                                            │ │
│  └──────────────────┬─────────────────────────┘ │
│                     │                            │
│  ┌──────────────────▼─────────────────────────┐ │
│  │         Service (LoadBalancer)              │ │
│  └──────────────────┬─────────────────────────┘ │
│                     │                            │
│  ┌──────────────────▼─────────────────────────┐ │
│  │    Persistent Volume (Snapshots/Approvals) │ │
│  └────────────────────────────────────────────┘ │
│                                                  │
│  ┌────────────────────────────────────────────┐ │
│  │    Redis (Circuit Breaker State)           │ │
│  └────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────┘
```

**Features:**
- High availability (multiple replicas)
- Auto-scaling based on load
- Persistent storage for state
- Service mesh integration
- Health checks and monitoring

---

## Security Model

### Threat Model

**Protected Against:**
1. **Unauthorized file access** - FileAccessPolicy
2. **Secret exposure** - SecretDetectionPolicy
3. **Rate limit bypass** - RateLimiterPolicy + CircuitBreaker
4. **Cascading failures** - CircuitBreaker
5. **Unauthorized changes** - ApprovalWorkflow
6. **Data corruption** - RollbackManager

**Out of Scope:**
- Network-level attacks (use firewall/WAF)
- Authentication/Authorization (use IAM)
- Encryption at rest (use database encryption)

### Security Controls

| Control | Implementation | Enforcement Point |
|---------|----------------|-------------------|
| **Input Validation** | Policy validation | PolicyComposer |
| **Access Control** | FileAccessPolicy | Policy layer |
| **Approval Required** | ApprovalWorkflow | Workflow layer |
| **Audit Trail** | All components log | Observability layer |
| **Rollback Capability** | RollbackManager | Recovery layer |
| **Rate Limiting** | RateLimiterPolicy + CircuitBreaker | Policy + Breaker |

### Audit Trail

All M4 components generate audit events:

```python
# Policy violations
{
    "event": "policy_violation",
    "policy": "file_access",
    "severity": "HIGH",
    "action": {"tool": "write_file", "path": "/etc/passwd"},
    "context": {"agent": "writer"},
    "timestamp": "2026-01-27T12:00:00Z"
}

# Approval requests
{
    "event": "approval_requested",
    "request_id": "req-123",
    "action": {"tool": "deploy"},
    "required_approvers": 2,
    "timestamp": "2026-01-27T12:00:00Z"
}

# Circuit breaker state changes
{
    "event": "circuit_breaker_opened",
    "breaker": "external_api",
    "old_state": "closed",
    "new_state": "open",
    "failure_count": 5,
    "timestamp": "2026-01-27T12:00:00Z"
}

# Rollbacks
{
    "event": "rollback_executed",
    "snapshot_id": "snap-456",
    "success": true,
    "reverted_items": 3,
    "timestamp": "2026-01-27T12:00:00Z"
}
```

---

## Performance Characteristics

### Latency Benchmarks

| Operation | Avg Latency | P95 Latency | P99 Latency |
|-----------|-------------|-------------|-------------|
| Policy Validation | <1ms | <2ms | <5ms |
| Circuit Breaker Check | <100μs | <200μs | <500μs |
| Safety Gate Validation | <2ms | <4ms | <8ms |
| Rollback Snapshot (file) | <5ms | <10ms | <20ms |
| Approval Request Creation | <1ms | <2ms | <5ms |

**Test Conditions:**
- MacBook Pro M1, 16GB RAM
- 1,000-10,000 iterations per test
- Single-threaded execution
- In-memory storage

### Throughput

| Component | Operations/sec |
|-----------|----------------|
| PolicyComposer | >10,000 |
| CircuitBreaker | >100,000 |
| SafetyGate | >5,000 |
| RollbackManager | >1,000 |

### Memory Footprint

| Component | Base Memory | Per-Item Memory |
|-----------|-------------|-----------------|
| PolicyComposer | ~1KB | ~100B per policy |
| ApprovalWorkflow | ~2KB | ~500B per request |
| RollbackManager | ~1KB | ~1-10KB per snapshot |
| CircuitBreaker | ~500B | Negligible |

### Scaling Characteristics

- **PolicyComposer**: Linear scaling with number of policies
- **CircuitBreaker**: Constant time operations (O(1))
- **ApprovalWorkflow**: Linear with number of pending requests
- **RollbackManager**: Linear with snapshot size

### Optimization Tips

1. **Use fail_fast mode** for performance-critical paths
2. **Limit snapshot size** by excluding large files
3. **Configure appropriate timeouts** to avoid blocking
4. **Use circuit breakers** to prevent slow external calls
5. **Batch approval checks** when processing multiple items

---

## Best Practices

### 1. Policy Configuration

✅ **DO:**
- Order policies by priority (security first)
- Use specific error messages with remediation hints
- Enable fail_fast for performance-critical paths
- Test policies in isolation before composing

❌ **DON'T:**
- Create circular dependencies between policies
- Use overly broad policy rules
- Skip exception handling in custom policies

### 2. Approval Workflow

✅ **DO:**
- Set reasonable timeouts (30-60 minutes)
- Require multiple approvers for critical operations
- Provide clear approval reasons
- Log all approval decisions

❌ **DON'T:**
- Use infinite timeouts
- Allow self-approval
- Skip approval for production changes

### 3. Rollback Strategy

✅ **DO:**
- Create snapshots before all risky operations
- Test rollback procedures regularly
- Handle partial rollback failures gracefully
- Clean up old snapshots periodically

❌ **DON'T:**
- Snapshot excessively large data
- Assume rollback always succeeds
- Skip rollback validation

### 4. Circuit Breaker

✅ **DO:**
- Set failure thresholds based on SLOs
- Use appropriate timeout values
- Monitor circuit breaker state changes
- Test recovery procedures

❌ **DON'T:**
- Use too-low failure thresholds (false positives)
- Use too-high thresholds (delayed detection)
- Ignore open circuit breakers

---

## Appendix

### Component Version Matrix

| Component | Version | Status | Dependencies |
|-----------|---------|--------|--------------|
| PolicyComposer | 1.0.0 | Stable | SafetyPolicy |
| ApprovalWorkflow | 1.0.0 | Stable | - |
| RollbackManager | 1.0.0 | Stable | - |
| CircuitBreaker | 1.0.0 | Stable | - |
| SafetyGate | 1.0.0 | Stable | All above |

### Change History

- **2026-01-27**: Initial 1.0.0 release
  - PolicyComposer with priority-based execution
  - ApprovalWorkflow with multi-approver support
  - RollbackManager with file/state strategies
  - CircuitBreaker with three-state pattern
  - SafetyGate coordinating all components

### References

- [M4 API Reference](./M4_API_REFERENCE.md)
- [M4 Deployment Guide](./M4_DEPLOYMENT_GUIDE.md)
- [M4 Configuration Guide](./M4_CONFIGURATION_GUIDE.md)
- [Integration Tests](../tests/test_safety/test_m4_integration.py)
- [Complete Workflow Example](../examples/m4_safety_complete_workflow.py)
