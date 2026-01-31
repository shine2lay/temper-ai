# M4 Safety System - API Reference

**Version:** 1.0
**Last Updated:** 2026-01-27
**Status:** Production Ready

This document provides comprehensive API documentation for all M4 Safety System components.

---

## Table of Contents

1. [Policy Composition](#policy-composition)
   - [PolicyComposer](#policycomposer)
   - [CompositeValidationResult](#compositevalidationresult)
2. [Approval Workflow](#approval-workflow)
   - [ApprovalWorkflow](#approvalworkflow)
   - [ApprovalRequest](#approvalrequest)
   - [ApprovalStatus](#approvalstatus)
3. [Rollback Management](#rollback-management)
   - [RollbackManager](#rollbackmanager)
   - [RollbackSnapshot](#rollbacksnapshot)
   - [RollbackResult](#rollbackresult)
   - [RollbackStrategy](#rollbackstrategy)
4. [Circuit Breakers](#circuit-breakers)
   - [CircuitBreaker](#circuitbreaker)
   - [CircuitBreakerState](#circuitbreakerstate)
   - [CircuitBreakerMetrics](#circuitbreakermetrics)
   - [SafetyGate](#safetygate)
   - [CircuitBreakerManager](#circuitbreakermanager)
5. [Exceptions](#exceptions)

---

## Policy Composition

### PolicyComposer

**Module:** `src.safety.composition`

**Description:** Combines multiple safety policies and validates actions against all of them. Supports priority-based execution and fail-fast mode.

#### Constructor

```python
def __init__(
    self,
    policies: Optional[List[SafetyPolicy]] = None,
    fail_fast: bool = False,
    enable_reporting: bool = True
)
```

**Parameters:**
- `policies` (List[SafetyPolicy], optional): Initial list of policies to add
- `fail_fast` (bool, default=False): If True, stop validation after first blocking violation
- `enable_reporting` (bool, default=True): Enable detailed execution reporting

**Example:**
```python
from src.safety import PolicyComposer, FileAccessPolicy, BlastRadiusPolicy

composer = PolicyComposer(fail_fast=False)
composer.add_policy(FileAccessPolicy({...}))
composer.add_policy(BlastRadiusPolicy({...}))
```

#### Methods

##### `add_policy(policy: SafetyPolicy) -> None`

Add a policy to the composition.

**Parameters:**
- `policy` (SafetyPolicy): Policy instance to add

**Raises:**
- `ValueError`: If policy is None or not a SafetyPolicy instance
- `ValueError`: If policy with same name already exists

**Example:**
```python
composer.add_policy(FileAccessPolicy({"allowed_paths": ["/tmp/**"]}))
```

---

##### `remove_policy(name: str) -> bool`

Remove a policy by name.

**Parameters:**
- `name` (str): Name of policy to remove

**Returns:**
- `bool`: True if policy was removed, False if not found

**Example:**
```python
removed = composer.remove_policy("file_access_policy")
```

---

##### `get_policy(name: str) -> Optional[SafetyPolicy]`

Get a policy by name.

**Parameters:**
- `name` (str): Name of policy

**Returns:**
- `Optional[SafetyPolicy]`: Policy if found, None otherwise

**Example:**
```python
policy = composer.get_policy("file_access_policy")
if policy:
    print(f"Found policy: {policy.name}")
```

---

##### `validate(action: Dict[str, Any], context: Dict[str, Any]) -> CompositeValidationResult`

Validate an action against all policies.

**Parameters:**
- `action` (Dict[str, Any]): Action to validate
- `context` (Dict[str, Any]): Context information

**Returns:**
- `CompositeValidationResult`: Composite validation result

**Behavior:**
- Policies are executed in priority order (highest first)
- If `fail_fast=True`, stops after first blocking violation
- Policy exceptions are caught and converted to CRITICAL violations
- Returns aggregated result from all policies

**Example:**
```python
result = composer.validate(
    action={"tool": "write_file", "path": "/tmp/test.txt"},
    context={"user": "alice"}
)

if result.valid:
    print("Action allowed")
else:
    for violation in result.violations:
        print(f"Violation: {violation.message}")
```

---

##### `list_policies() -> List[str]`

Get names of all registered policies.

**Returns:**
- `List[str]`: List of policy names in priority order

**Example:**
```python
policies = composer.list_policies()
print(f"Registered policies: {', '.join(policies)}")
```

---

##### `clear_policies() -> None`

Remove all policies.

**Example:**
```python
composer.clear_policies()
assert len(composer.list_policies()) == 0
```

---

**Note:** The `fail_fast` behavior is configured in the constructor. To change fail-fast mode after creation, set the `fail_fast` attribute directly:

```python
# Initialize with fail-fast disabled
composer = PolicyComposer(fail_fast=False)

# Enable fail-fast later if needed
composer.fail_fast = True

# Disable fail-fast
composer.fail_fast = False
```

---

### CompositeValidationResult

**Module:** `src.safety.composition`

**Description:** Result of validating an action against multiple policies.

#### Attributes

```python
@dataclass
class CompositeValidationResult:
    valid: bool                                    # Overall validation result
    violations: List[SafetyViolation]              # All violations found
    policy_results: Dict[str, ValidationResult]    # Per-policy results
    policies_evaluated: int                        # Number of policies evaluated
    policies_skipped: int                          # Number of policies skipped (fail-fast)
    execution_order: List[str]                     # Order policies were executed
    timestamp: datetime                            # When validation occurred
```

#### Methods

##### `has_blocking_violations() -> bool`

Check if any blocking violations were found.

**Returns:**
- `bool`: True if any violations are CRITICAL or HIGH severity

**Example:**
```python
result = composer.validate(action, context)
if result.has_blocking_violations():
    print("Action blocked by safety policies")
    for v in result.violations:
        if v.severity in [SafetyViolationSeverity.CRITICAL, SafetyViolationSeverity.HIGH]:
            print(f"  - {v.message}")
```

---

##### `to_dict() -> Dict[str, Any]`

Convert result to dictionary for serialization.

**Returns:**
- `Dict[str, Any]`: Dictionary representation

**Example:**
```python
result = composer.validate(action, context)
result_dict = result.to_dict()
json.dumps(result_dict)  # Serialize to JSON
```

---

## Approval Workflow

### ApprovalWorkflow

**Module:** `src.safety.approval`

**Description:** Manages human approval workflow for high-risk actions. Supports multi-approver consensus, timeouts, and callbacks.

#### Constructor

```python
def __init__(
    self,
    default_timeout_minutes: int = 60,
    auto_reject_on_timeout: bool = True
)
```

**Parameters:**
- `default_timeout_minutes` (int, default=60): Default timeout for approval requests
- `auto_reject_on_timeout` (bool, default=True): Auto-reject expired requests

**Example:**
```python
from src.safety import ApprovalWorkflow

workflow = ApprovalWorkflow(
    default_timeout_minutes=30,
    auto_reject_on_timeout=True
)
```

#### Methods

##### `request_approval(...) -> ApprovalRequest`

Request approval for an action.

```python
def request_approval(
    self,
    action: Dict[str, Any],
    reason: str,
    context: Optional[Dict[str, Any]] = None,
    required_approvers: int = 1,
    timeout_minutes: Optional[int] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> ApprovalRequest
```

**Parameters:**
- `action` (Dict[str, Any]): Action requiring approval
- `reason` (str): Reason for approval request
- `context` (Dict[str, Any], optional): Additional context
- `required_approvers` (int, default=1): Number of approvals needed
- `timeout_minutes` (int, optional): Timeout (uses default if not specified)
- `metadata` (Dict[str, Any], optional): Custom metadata

**Returns:**
- `ApprovalRequest`: Created approval request

**Raises:**
- `ValueError`: If reason is empty or required_approvers < 1

**Example:**
```python
request = workflow.request_approval(
    action={"tool": "deploy", "environment": "production"},
    reason="Production deployment requires approval",
    required_approvers=2,
    timeout_minutes=60
)
print(f"Request ID: {request.id}")
```

---

##### `approve(request_id: str, approver: str, reason: Optional[str] = None) -> None`

Approve a request.

**Parameters:**
- `request_id` (str): Request ID
- `approver` (str): Approver identifier
- `reason` (str, optional): Approval reason

**Raises:**
- `ValueError`: If request not found or already resolved
- `ValueError`: If approver already approved

**Example:**
```python
workflow.approve(
    request_id=request.id,
    approver="senior_engineer",
    reason="Changes reviewed and approved"
)
```

---

##### `reject(request_id: str, rejector: str, reason: Optional[str] = None) -> None`

Reject a request.

**Parameters:**
- `request_id` (str): Request ID
- `rejector` (str): Rejector identifier
- `reason` (str, optional): Rejection reason

**Raises:**
- `ValueError`: If request not found or already resolved

**Example:**
```python
workflow.reject(
    request_id=request.id,
    rejector="security_lead",
    reason="Potential security risk detected"
)
```

---

##### `cancel(request_id: str, reason: Optional[str] = None) -> None`

Cancel a request.

**Parameters:**
- `request_id` (str): Request ID
- `reason` (str, optional): Cancellation reason

**Raises:**
- `ValueError`: If request not found or already resolved

**Example:**
```python
workflow.cancel(request.id, reason="Action no longer needed")
```

---

##### `get_request(request_id: str) -> Optional[ApprovalRequest]`

Get a request by ID.

**Parameters:**
- `request_id` (str): Request ID

**Returns:**
- `Optional[ApprovalRequest]`: Request if found, None otherwise

**Example:**
```python
request = workflow.get_request(request_id)
if request:
    print(f"Status: {request.status.value}")
```

---

##### `list_pending_requests() -> List[ApprovalRequest]`

Get all pending requests.

**Returns:**
- `List[ApprovalRequest]`: List of pending requests

**Example:**
```python
pending = workflow.list_pending_requests()
for request in pending:
    print(f"Pending: {request.id} - {request.reason}")
```

---

##### `cleanup_expired_requests() -> int`

Mark expired requests as expired (or rejected if auto_reject_on_timeout=True).

**Returns:**
- `int`: Number of requests expired

**Example:**
```python
expired_count = workflow.cleanup_expired_requests()
print(f"Expired {expired_count} requests")
```

---

##### `on_approved(callback: Callable[[ApprovalRequest], None]) -> None`

Register callback for approval events.

**Parameters:**
- `callback` (Callable): Function to call when request is approved

**Example:**
```python
def on_approval(request: ApprovalRequest):
    print(f"Approved: {request.id}")
    send_notification(request)

workflow.on_approved(on_approval)
```

---

##### `on_rejected(callback: Callable[[ApprovalRequest], None]) -> None`

Register callback for rejection events.

**Parameters:**
- `callback` (Callable): Function to call when request is rejected

**Example:**
```python
def on_rejection(request: ApprovalRequest):
    print(f"Rejected: {request.id}")
    rollback_changes()

workflow.on_rejected(on_rejection)
```

---

### ApprovalRequest

**Module:** `src.safety.approval`

**Description:** Represents a single approval request.

#### Attributes

```python
@dataclass
class ApprovalRequest:
    id: str                              # Unique request ID
    action: Dict[str, Any]               # Action requiring approval
    reason: str                          # Reason for request
    context: Dict[str, Any]              # Additional context
    status: ApprovalStatus               # Current status
    required_approvers: int              # Number of approvals needed
    approvers: List[str]                 # List of approvers
    rejection_reason: Optional[str]      # Rejection reason if rejected
    created_at: datetime                 # When request was created
    expires_at: Optional[datetime]       # Expiration time
    resolved_at: Optional[datetime]      # When resolved
    metadata: Dict[str, Any]             # Custom metadata
```

#### Methods

##### `is_pending() -> bool`

Check if request is pending.

**Returns:**
- `bool`: True if status is PENDING

---

##### `is_approved() -> bool`

Check if request is approved.

**Returns:**
- `bool`: True if status is APPROVED

---

##### `is_rejected() -> bool`

Check if request is rejected.

**Returns:**
- `bool`: True if status is REJECTED

---

##### `is_expired() -> bool`

Check if request is expired.

**Returns:**
- `bool`: True if status is EXPIRED or current time > expires_at

---

##### `approval_count() -> int`

Get number of approvals received.

**Returns:**
- `int`: Number of approvers

---

##### `needs_more_approvals() -> bool`

Check if more approvals are needed.

**Returns:**
- `bool`: True if approval_count < required_approvers

---

### ApprovalStatus

**Module:** `src.safety.approval`

**Description:** Status of an approval request.

```python
class ApprovalStatus(Enum):
    PENDING = "pending"       # Awaiting approval
    APPROVED = "approved"     # Approved by all required approvers
    REJECTED = "rejected"     # Rejected
    EXPIRED = "expired"       # Timed out
    CANCELLED = "cancelled"   # Cancelled before resolution
```

---

## Rollback Management

### RollbackManager

**Module:** `src.safety.rollback`

**Description:** Manages state snapshots and rollback operations. Supports file rollback, state rollback, and composite strategies.

#### Constructor

```python
def __init__(
    self,
    strategy: Optional[RollbackStrategy] = None,
    storage_path: Optional[Path] = None
)
```

**Parameters:**
- `strategy` (RollbackStrategy, optional): Rollback strategy (default: CompositeRollbackStrategy with File + State)
- `storage_path` (Path, optional): Path for snapshot storage (default: temp directory)

**Example:**
```python
from src.safety import RollbackManager, FileRollbackStrategy

# Use default composite strategy
manager = RollbackManager()

# Use custom strategy
file_strategy = FileRollbackStrategy()
manager = RollbackManager(strategy=file_strategy)
```

#### Methods

##### `create_snapshot(action: Dict[str, Any], context: Dict[str, Any]) -> RollbackSnapshot`

Create a snapshot of current state.

**Parameters:**
- `action` (Dict[str, Any]): Action about to be performed
- `context` (Dict[str, Any]): Context information

**Returns:**
- `RollbackSnapshot`: Created snapshot

**Example:**
```python
snapshot = manager.create_snapshot(
    action={"tool": "write_file", "path": "/tmp/test.txt"},
    context={"user": "alice"}
)
print(f"Snapshot ID: {snapshot.id}")
```

---

##### `execute_rollback(snapshot_id: str) -> RollbackResult`

Execute rollback to a snapshot.

**Parameters:**
- `snapshot_id` (str): Snapshot ID to rollback to

**Returns:**
- `RollbackResult`: Rollback result

**Raises:**
- `ValueError`: If snapshot not found

**Example:**
```python
try:
    risky_operation()
except Exception:
    result = manager.execute_rollback(snapshot.id)
    if result.success:
        print("Rollback successful")
    else:
        print(f"Rollback failed: {result.errors}")
```

---

##### `get_snapshot(snapshot_id: str) -> Optional[RollbackSnapshot]`

Get a snapshot by ID.

**Parameters:**
- `snapshot_id` (str): Snapshot ID

**Returns:**
- `Optional[RollbackSnapshot]`: Snapshot if found

**Example:**
```python
snapshot = manager.get_snapshot(snapshot_id)
if snapshot:
    print(f"Created: {snapshot.created_at}")
```

---

##### `list_snapshots() -> List[RollbackSnapshot]`

List all snapshots.

**Returns:**
- `List[RollbackSnapshot]`: All snapshots

**Example:**
```python
snapshots = manager.list_snapshots()
for snap in snapshots:
    print(f"{snap.id}: {snap.created_at}")
```

---

##### `get_history() -> List[RollbackResult]`

Get rollback execution history.

**Returns:**
- `List[RollbackResult]`: All rollback results

**Example:**
```python
history = manager.get_history()
for result in history:
    print(f"{result.snapshot_id}: {result.status.value}")
```

---

##### `snapshot_count() -> int`

Get number of snapshots.

**Returns:**
- `int`: Number of snapshots

---

### RollbackSnapshot

**Module:** `src.safety.rollback`

**Description:** Represents a state snapshot.

#### Attributes

```python
@dataclass
class RollbackSnapshot:
    id: str                              # Unique snapshot ID
    action: Dict[str, Any]               # Action that created snapshot
    context: Dict[str, Any]              # Context information
    created_at: datetime                 # When snapshot was created
    file_snapshots: Dict[str, str]       # {file_path: content}
    state_snapshots: Dict[str, Any]      # {key: value}
    metadata: Dict[str, Any]             # Custom metadata
```

---

### RollbackResult

**Module:** `src.safety.rollback`

**Description:** Result of a rollback operation.

#### Attributes

```python
@dataclass
class RollbackResult:
    snapshot_id: str                     # Snapshot that was rolled back
    status: RollbackStatus               # Result status
    reverted_items: List[str]            # Successfully reverted items
    failed_items: List[str]              # Failed items
    errors: List[str]                    # Error messages
    executed_at: datetime                # When rollback was executed
```

#### Properties

##### `success -> bool`

Check if rollback was successful.

**Returns:**
- `bool`: True if status is COMPLETED

---

### RollbackStatus

**Module:** `src.safety.rollback`

**Description:** Status of a rollback operation.

```python
class RollbackStatus(Enum):
    PENDING = "pending"       # Not yet executed
    COMPLETED = "completed"   # All items reverted
    FAILED = "failed"         # All items failed
    PARTIAL = "partial"       # Some items reverted, some failed
```

---

### RollbackStrategy

**Module:** `src.safety.rollback`

**Description:** Abstract base class for rollback strategies.

#### Methods

##### `create_snapshot(action: Dict[str, Any], context: Dict[str, Any]) -> RollbackSnapshot`

Create a snapshot. Must be implemented by subclasses.

---

##### `execute_rollback(snapshot: RollbackSnapshot) -> RollbackResult`

Execute rollback. Must be implemented by subclasses.

---

#### Built-in Strategies

**FileRollbackStrategy:**
- Captures file contents before modification
- Restores files on rollback
- Deletes newly created files

**StateRollbackStrategy:**
- Captures arbitrary state dictionaries
- Restores state on rollback

**CompositeRollbackStrategy:**
- Combines multiple strategies
- Executes all strategies on snapshot/rollback

**Example:**
```python
from src.safety.rollback import (
    CompositeRollbackStrategy,
    FileRollbackStrategy,
    StateRollbackStrategy
)

composite = CompositeRollbackStrategy([
    FileRollbackStrategy(),
    StateRollbackStrategy()
])

manager = RollbackManager(strategy=composite)
```

---

## Circuit Breakers

### CircuitBreaker

**Module:** `src.safety.circuit_breaker`

**Description:** Implements circuit breaker pattern to prevent cascading failures. Three states: CLOSED, OPEN, HALF_OPEN.

#### Constructor

```python
def __init__(
    self,
    name: str,
    failure_threshold: int = 5,
    timeout_seconds: int = 60,
    success_threshold: int = 2
)
```

**Parameters:**
- `name` (str): Circuit breaker name
- `failure_threshold` (int, default=5): Failures before opening
- `timeout_seconds` (int, default=60): Wait time before attempting recovery
- `success_threshold` (int, default=2): Successes needed to close from HALF_OPEN

**Example:**
```python
from src.safety import CircuitBreaker

breaker = CircuitBreaker(
    name="database_operations",
    failure_threshold=3,
    timeout_seconds=300,
    success_threshold=2
)
```

#### Methods

##### `record_success() -> None`

Record a successful operation.

**Behavior:**
- If HALF_OPEN: increment success count, close circuit if threshold reached
- If CLOSED: reset failure count

**Example:**
```python
try:
    execute_operation()
    breaker.record_success()
except Exception as e:
    breaker.record_failure(e)
```

---

##### `record_failure(error: Optional[Exception] = None) -> None`

Record a failed operation.

**Parameters:**
- `error` (Exception, optional): Exception that caused failure

**Behavior:**
- If CLOSED: increment failure count, open circuit if threshold reached
- If HALF_OPEN: immediately open circuit
- If OPEN: no change

**Example:**
```python
try:
    execute_operation()
except Exception as e:
    breaker.record_failure(e)
    raise
```

---

##### `can_execute() -> bool`

Check if operation can execute.

**Returns:**
- `bool`: True if circuit is CLOSED or HALF_OPEN

**Behavior:**
- If OPEN and timeout elapsed: transition to HALF_OPEN
- Otherwise: return based on current state

**Example:**
```python
if breaker.can_execute():
    execute_operation()
else:
    print("Circuit is open - operation blocked")
```

---

##### `force_open() -> None`

Manually open the circuit.

**Example:**
```python
# Emergency: force circuit open
breaker.force_open()
```

---

##### `reset() -> None`

Reset circuit to initial state (CLOSED, zero counters).

**Example:**
```python
breaker.reset()
assert breaker.state == CircuitBreakerState.CLOSED
```

---

##### `__call__() -> ContextManager`

Use as context manager.

**Behavior:**
- Checks if operation can execute (raises CircuitBreakerOpen if not)
- Records success/failure based on exception

**Raises:**
- `CircuitBreakerOpen`: If circuit is open

**Example:**
```python
try:
    with breaker():
        execute_risky_operation()
except CircuitBreakerOpen:
    print("Circuit is open")
except Exception as e:
    print(f"Operation failed: {e}")
```

---

##### `on_state_change(callback: Callable[[CircuitBreakerState, CircuitBreakerState], None]) -> None`

Register callback for state changes.

**Parameters:**
- `callback` (Callable): Function(old_state, new_state)

**Example:**
```python
def on_state_change(old_state, new_state):
    print(f"Circuit {breaker.name}: {old_state.value} → {new_state.value}")
    alert_ops_team(breaker.name, new_state)

breaker.on_state_change(on_state_change)
```

---

#### Properties

##### `state -> CircuitBreakerState`

Get current state.

**Returns:**
- `CircuitBreakerState`: Current state (CLOSED, OPEN, or HALF_OPEN)

---

##### `metrics -> CircuitBreakerMetrics`

Get current metrics.

**Returns:**
- `CircuitBreakerMetrics`: Metrics snapshot

---

### CircuitBreakerState

**Module:** `src.safety.circuit_breaker`

**Description:** Circuit breaker states.

```python
class CircuitBreakerState(Enum):
    CLOSED = "closed"           # Normal operation
    OPEN = "open"               # Blocking all requests
    HALF_OPEN = "half_open"     # Testing if service recovered
```

---

### CircuitBreakerMetrics

**Module:** `src.safety.circuit_breaker`

**Description:** Metrics for circuit breaker.

#### Attributes

```python
@dataclass
class CircuitBreakerMetrics:
    total_calls: int              # Total operations attempted
    successful_calls: int         # Successful operations
    failed_calls: int             # Failed operations
    rejected_calls: int           # Rejected by open circuit
    last_failure_time: Optional[datetime]
    last_success_time: Optional[datetime]
```

#### Methods

##### `success_rate() -> float`

Calculate success rate.

**Returns:**
- `float`: Success rate (0.0 to 1.0), or 0.0 if no calls

**Example:**
```python
metrics = breaker.metrics
print(f"Success rate: {metrics.success_rate():.1%}")
```

---

##### `failure_rate() -> float`

Calculate failure rate.

**Returns:**
- `float`: Failure rate (0.0 to 1.0), or 0.0 if no calls

---

### SafetyGate

**Module:** `src.safety.circuit_breaker`

**Description:** Coordinates multiple safety mechanisms (circuit breaker + policy validation). Provides unified entry point for safety checks.

#### Constructor

```python
def __init__(
    self,
    name: str,
    circuit_breaker: Optional[CircuitBreaker] = None,
    policy_composer: Optional[PolicyComposer] = None
)
```

**Parameters:**
- `name` (str): Gate name
- `circuit_breaker` (CircuitBreaker, optional): Circuit breaker to use
- `policy_composer` (PolicyComposer, optional): Policy composer to use

**Example:**
```python
from src.safety import SafetyGate, CircuitBreaker, PolicyComposer

gate = SafetyGate(
    name="database_gate",
    circuit_breaker=CircuitBreaker("db_ops"),
    policy_composer=PolicyComposer()
)
```

#### Methods

##### `can_pass(action: Dict[str, Any], context: Dict[str, Any]) -> bool`

Quick check if action can pass.

**Parameters:**
- `action` (Dict[str, Any]): Action to validate
- `context` (Dict[str, Any]): Context information

**Returns:**
- `bool`: True if action can pass all checks

**Example:**
```python
if gate.can_pass(action, context):
    execute_action()
```

---

##### `validate(action: Dict[str, Any], context: Dict[str, Any]) -> Tuple[bool, List[str]]`

Detailed validation with reasons.

**Parameters:**
- `action` (Dict[str, Any]): Action to validate
- `context` (Dict[str, Any]): Context information

**Returns:**
- `Tuple[bool, List[str]]`: (can_pass, reasons)

**Example:**
```python
can_pass, reasons = gate.validate(action, context)
if not can_pass:
    for reason in reasons:
        print(f"Blocked: {reason}")
```

---

##### `__call__(action: Dict[str, Any], context: Dict[str, Any]) -> ContextManager`

Use as context manager.

**Parameters:**
- `action` (Dict[str, Any]): Action to validate
- `context` (Dict[str, Any]): Context information

**Raises:**
- `SafetyGateBlocked`: If validation fails

**Example:**
```python
try:
    with gate(action=action, context=context):
        execute_action()
except SafetyGateBlocked as e:
    print(f"Blocked: {e}")
```

---

### CircuitBreakerManager

**Module:** `src.safety.circuit_breaker`

**Description:** Manages multiple circuit breakers. Provides centralized control and monitoring.

#### Constructor

```python
def __init__(self)
```

**Example:**
```python
from src.safety import CircuitBreakerManager

manager = CircuitBreakerManager()
```

#### Methods

##### `create_breaker(...) -> CircuitBreaker`

Create a new circuit breaker.

```python
def create_breaker(
    self,
    name: str,
    failure_threshold: int = 5,
    timeout_seconds: int = 60,
    success_threshold: int = 2
) -> CircuitBreaker
```

**Parameters:**
- `name` (str): Circuit breaker name
- `failure_threshold` (int, default=5): Failures before opening
- `timeout_seconds` (int, default=60): Recovery timeout
- `success_threshold` (int, default=2): Successes needed to close

**Returns:**
- `CircuitBreaker`: Created circuit breaker

**Raises:**
- `ValueError`: If breaker with name already exists

**Example:**
```python
db_breaker = manager.create_breaker(
    name="database",
    failure_threshold=3,
    timeout_seconds=300
)
```

---

##### `get_breaker(name: str) -> Optional[CircuitBreaker]`

Get a circuit breaker by name.

**Parameters:**
- `name` (str): Circuit breaker name

**Returns:**
- `Optional[CircuitBreaker]`: Breaker if found

**Example:**
```python
breaker = manager.get_breaker("database")
if breaker:
    print(f"State: {breaker.state.value}")
```

---

##### `remove_breaker(name: str) -> bool`

Remove a circuit breaker.

**Parameters:**
- `name` (str): Circuit breaker name

**Returns:**
- `bool`: True if removed, False if not found

**Example:**
```python
removed = manager.remove_breaker("database")
```

---

##### `list_breakers() -> List[str]`

List all circuit breaker names.

**Returns:**
- `List[str]`: List of breaker names

**Example:**
```python
breakers = manager.list_breakers()
for name in breakers:
    print(f"Breaker: {name}")
```

---

##### `get_all_metrics() -> Dict[str, Dict[str, Any]]`

Get metrics for all circuit breakers.

**Returns:**
- `Dict[str, Dict[str, Any]]`: {breaker_name: metrics_dict}

**Example:**
```python
all_metrics = manager.get_all_metrics()
for name, metrics in all_metrics.items():
    print(f"{name}: {metrics['success_rate']:.1%}")
```

---

##### `reset_all() -> None`

Reset all circuit breakers.

**Example:**
```python
# After system recovery
manager.reset_all()
```

---

##### `create_gate(...) -> SafetyGate`

Create a safety gate linked to a circuit breaker.

```python
def create_gate(
    self,
    name: str,
    breaker_name: str,
    policy_composer: Optional[PolicyComposer] = None
) -> SafetyGate
```

**Parameters:**
- `name` (str): Gate name
- `breaker_name` (str): Name of circuit breaker to use
- `policy_composer` (PolicyComposer, optional): Policy composer

**Returns:**
- `SafetyGate`: Created safety gate

**Raises:**
- `ValueError`: If breaker doesn't exist

**Example:**
```python
gate = manager.create_gate(
    name="db_gate",
    breaker_name="database",
    policy_composer=composer
)
```

---

## Exceptions

### CircuitBreakerOpen

**Module:** `src.safety.circuit_breaker`

**Description:** Raised when circuit breaker is open.

```python
class CircuitBreakerOpen(Exception):
    """Circuit breaker is open - operation blocked."""
```

**Example:**
```python
try:
    with breaker():
        execute_operation()
except CircuitBreakerOpen as e:
    print(f"Circuit is open: {e}")
```

---

### SafetyGateBlocked

**Module:** `src.safety.circuit_breaker`

**Description:** Raised when safety gate blocks an action.

```python
class SafetyGateBlocked(Exception):
    """Safety gate blocked action - validation failed."""
```

**Example:**
```python
try:
    with gate(action=action, context=context):
        execute_action()
except SafetyGateBlocked as e:
    print(f"Gate blocked: {e}")
```

---

## Complete Example

```python
from src.safety import (
    PolicyComposer,
    FileAccessPolicy,
    ApprovalWorkflow,
    RollbackManager,
    CircuitBreakerManager
)

# Setup all M4 components
manager = CircuitBreakerManager()
manager.create_breaker("database", failure_threshold=3)

composer = PolicyComposer()
composer.add_policy(FileAccessPolicy({
    "allowed_paths": ["/tmp/**"],
    "denied_paths": ["/etc/**"]
}))

approval = ApprovalWorkflow()
rollback_mgr = RollbackManager()

gate = manager.create_gate(
    name="db_gate",
    breaker_name="database",
    policy_composer=composer
)

# Execute with full safety checks
action = {"tool": "db_migration", "script": "/tmp/migration.sql"}
context = {"user": "admin"}

try:
    # Step 1: Safety gate validation
    can_pass, reasons = gate.validate(action, context)
    if not can_pass:
        raise Exception(f"Blocked: {'; '.join(reasons)}")

    # Step 2: Request approval
    request = approval.request_approval(
        action=action,
        reason="Production database migration",
        required_approvers=2
    )
    approval.approve(request.id, approver="dba")
    approval.approve(request.id, approver="tech_lead")

    # Step 3: Create rollback snapshot
    snapshot = rollback_mgr.create_snapshot(action, context)

    # Step 4: Execute through circuit breaker
    db_breaker = manager.get_breaker("database")
    with db_breaker():
        execute_migration()

    print("✓ Migration successful")

except Exception as e:
    print(f"✗ Migration failed: {e}")
    result = rollback_mgr.execute_rollback(snapshot.id)
    if result.success:
        print("✓ Rollback successful")
```

---

## Type Hints

All M4 components use Python type hints for better IDE support:

```python
from typing import Dict, Any, List, Optional, Tuple, Callable

# Example function signature
def validate(
    action: Dict[str, Any],
    context: Dict[str, Any]
) -> CompositeValidationResult:
    ...
```

---

## Thread Safety

All M4 components are thread-safe:

- **PolicyComposer**: Thread-safe policy list operations
- **ApprovalWorkflow**: Thread-safe request management
- **RollbackManager**: Thread-safe snapshot operations
- **CircuitBreaker**: Thread-safe state transitions
- **SafetyGate**: Thread-safe validation

Use `threading.Lock` for custom integrations.

---

## Serialization

All result types support dictionary serialization:

```python
# Convert to dict
result_dict = result.to_dict()

# Serialize to JSON
import json
json.dumps(result_dict)
```

---

## Performance Characteristics

| Component | Operation | Average Time |
|-----------|-----------|--------------|
| PolicyComposer | validate (1 policy) | <1ms |
| PolicyComposer | validate (10 policies) | <5ms |
| ApprovalWorkflow | request_approval | <1ms |
| ApprovalWorkflow | approve | <1ms |
| RollbackManager | create_snapshot (5 files) | <10ms |
| RollbackManager | execute_rollback (5 files) | <20ms |
| CircuitBreaker | record_success/failure | <100μs |
| CircuitBreaker | context manager overhead | <100μs |
| SafetyGate | validate (all checks) | <2ms |

---

**See Also:**
- [M4 Safety Architecture](./M4_SAFETY_ARCHITECTURE.md)
- [M4 Integration Tests](../tests/test_safety/test_m4_integration.py)
- [Complete Workflow Example](../examples/m4_safety_complete_workflow.py)
