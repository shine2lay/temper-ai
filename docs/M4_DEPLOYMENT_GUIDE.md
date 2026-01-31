# M4 Safety System - Deployment Guide

**Version:** 1.0
**Last Updated:** 2026-01-27
**Status:** Production Ready

This guide covers deploying the M4 Safety System in various environments, from development to production.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Installation](#installation)
3. [Deployment Architectures](#deployment-architectures)
4. [Configuration](#configuration)
5. [Integration Patterns](#integration-patterns)
6. [Scaling Considerations](#scaling-considerations)
7. [Monitoring and Observability](#monitoring-and-observability)
8. [Production Checklist](#production-checklist)
9. [Troubleshooting](#troubleshooting)

---

## Prerequisites

### System Requirements

**Minimum:**
- Python 3.11+
- 512MB RAM
- 1 CPU core
- 10GB disk space

**Recommended (Production):**
- Python 3.11+
- 4GB+ RAM
- 4+ CPU cores
- 100GB+ disk space (for snapshots and logs)

### Dependencies

```bash
# Core dependencies
pip install -r requirements.txt

# Development dependencies
pip install -r requirements-dev.txt
```

### Python Packages

```
# requirements.txt
uuid>=1.30
dataclasses>=0.6  # Not needed for Python 3.11+ (built-in since 3.7)
typing-extensions>=4.0
pathlib>=1.0
```

---

## Installation

### Method 1: Development Installation

```bash
# Clone repository
git clone https://github.com/your-org/meta-autonomous-framework.git
cd meta-autonomous-framework

# Install in development mode
pip install -e .

# Verify installation
python -c "from src.safety import PolicyComposer; print('M4 installed successfully')"

# Run tests
pytest tests/test_safety/ -v
```

### Method 2: Production Installation

```bash
# Install from PyPI (when published)
pip install meta-autonomous-framework

# Or install from wheel
pip install meta_autonomous_framework-1.0.0-py3-none-any.whl

# Verify installation
python -c "from src.safety import *; print('M4 ready for production')"
```

### Method 3: Docker Installation

```dockerfile
# Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install M4
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ src/
COPY examples/ examples/

# Run example
CMD ["python", "examples/m4_safety_complete_workflow.py"]
```

```bash
# Build and run
docker build -t m4-safety .
docker run m4-safety
```

---

## Deployment Architectures

### Architecture 1: Single-Process Deployment

**Use Case:** Development, small applications, single-agent systems

**Characteristics:**
- All M4 components in same process
- No network overhead
- Simplest deployment
- Limited scalability

**Diagram:**
```
┌─────────────────────────────────────┐
│       Application Process           │
│                                     │
│  ┌─────────────────────────────┐   │
│  │     M4 Components            │   │
│  │  • PolicyComposer            │   │
│  │  • ApprovalWorkflow          │   │
│  │  • RollbackManager           │   │
│  │  • CircuitBreakerManager     │   │
│  └─────────────────────────────┘   │
│           │                         │
│           ▼                         │
│  ┌─────────────────────────────┐   │
│  │   File Storage (Local)       │   │
│  │  • Snapshots                 │   │
│  │  • Approval logs             │   │
│  └─────────────────────────────┘   │
└─────────────────────────────────────┘
```

**Implementation:**

```python
# main.py - Single-process deployment
from src.safety import (
    PolicyComposer,
    ApprovalWorkflow,
    RollbackManager,
    CircuitBreakerManager
)

# Initialize all components in-process
composer = PolicyComposer()
approval = ApprovalWorkflow()
rollback_mgr = RollbackManager()
breaker_mgr = CircuitBreakerManager()

# Create safety gates
gate = breaker_mgr.create_gate(
    name="main_gate",
    breaker_name="main",
    policy_composer=composer
)

# Use in application
def execute_action(action, context):
    can_pass, reasons = gate.validate(action, context)
    if not can_pass:
        raise Exception(f"Blocked: {'; '.join(reasons)}")

    snapshot = rollback_mgr.create_snapshot(action, context)
    try:
        # Execute action
        perform_operation()
    except Exception:
        rollback_mgr.execute_rollback(snapshot.id)
        raise
```

**Pros:**
- Simple setup
- No network latency
- Easy debugging

**Cons:**
- No horizontal scaling
- Single point of failure
- Limited resource isolation

---

### Architecture 2: Multi-Process with Shared State

**Use Case:** Multi-agent systems, distributed applications

**Characteristics:**
- M4 components distributed across processes
- Shared state via database/cache
- Better scalability
- Requires coordination

**Diagram:**
```
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│   Agent 1    │  │   Agent 2    │  │   Agent 3    │
│              │  │              │  │              │
│ M4 Client    │  │ M4 Client    │  │ M4 Client    │
└──────┬───────┘  └──────┬───────┘  └──────┬───────┘
       │                 │                 │
       └─────────────────┼─────────────────┘
                         │
                         ▼
         ┌───────────────────────────────┐
         │     M4 Service Layer          │
         │  • PolicyComposer (shared)    │
         │  • ApprovalWorkflow (shared)  │
         │  • RollbackManager (shared)   │
         │  • CircuitBreakerManager      │
         └───────────────┬───────────────┘
                         │
                         ▼
         ┌───────────────────────────────┐
         │   Shared Storage              │
         │  • Redis (state)              │
         │  • PostgreSQL (approvals)     │
         │  • S3 (snapshots)             │
         └───────────────────────────────┘
```

**Implementation:**

```python
# m4_service.py - Centralized M4 service
from flask import Flask, request, jsonify
from src.safety import PolicyComposer, ApprovalWorkflow

app = Flask(__name__)

# Shared M4 components
composer = PolicyComposer()
approval = ApprovalWorkflow()

@app.route('/validate', methods=['POST'])
def validate():
    data = request.json
    result = composer.validate(data['action'], data['context'])
    return jsonify(result.to_dict())

@app.route('/request_approval', methods=['POST'])
def request_approval():
    data = request.json
    req = approval.request_approval(
        action=data['action'],
        reason=data['reason'],
        required_approvers=data.get('required_approvers', 1)
    )
    return jsonify({'request_id': req.id})

@app.route('/approve', methods=['POST'])
def approve():
    data = request.json
    approval.approve(data['request_id'], data['approver'])
    return jsonify({'status': 'approved'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
```

```python
# agent.py - Agent using M4 service
import requests

class M4Client:
    def __init__(self, service_url):
        self.service_url = service_url

    def validate(self, action, context):
        response = requests.post(
            f"{self.service_url}/validate",
            json={'action': action, 'context': context}
        )
        return response.json()

    def request_approval(self, action, reason, required_approvers=1):
        response = requests.post(
            f"{self.service_url}/request_approval",
            json={
                'action': action,
                'reason': reason,
                'required_approvers': required_approvers
            }
        )
        return response.json()['request_id']

# Use in agent
m4 = M4Client('http://m4-service:5000')
result = m4.validate(action, context)
```

**Pros:**
- Horizontal scaling
- Process isolation
- Centralized monitoring

**Cons:**
- Network overhead
- More complex setup
- Requires service orchestration

---

### Architecture 3: Kubernetes Deployment

**Use Case:** Cloud-native applications, microservices

**Characteristics:**
- M4 as Kubernetes service
- Auto-scaling
- High availability
- Cloud-native observability

**Diagram:**
```
┌─────────────────────────────────────────────────────────┐
│                    Kubernetes Cluster                    │
│                                                          │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐       │
│  │  Agent Pod │  │  Agent Pod │  │  Agent Pod │       │
│  │            │  │            │  │            │       │
│  │ M4 Client  │  │ M4 Client  │  │ M4 Client  │       │
│  └─────┬──────┘  └─────┬──────┘  └─────┬──────┘       │
│        │                │                │              │
│        └────────────────┼────────────────┘              │
│                         │                               │
│                         ▼                               │
│         ┌───────────────────────────────┐              │
│         │   M4 Service (Deployment)     │              │
│         │   • Replicas: 3               │              │
│         │   • Load Balanced             │              │
│         └───────────────┬───────────────┘              │
│                         │                               │
│                         ▼                               │
│         ┌───────────────────────────────┐              │
│         │   Persistent Storage          │              │
│         │   • PVC for snapshots         │              │
│         │   • Redis for state           │              │
│         │   • Postgres for approvals    │              │
│         └───────────────────────────────┘              │
└─────────────────────────────────────────────────────────┘
```

**Implementation:**

```yaml
# k8s/m4-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: m4-safety-service
  labels:
    app: m4-safety
spec:
  replicas: 3
  selector:
    matchLabels:
      app: m4-safety
  template:
    metadata:
      labels:
        app: m4-safety
    spec:
      containers:
      - name: m4-service
        image: your-registry/m4-safety:1.0
        ports:
        - containerPort: 5000
        env:
        - name: REDIS_URL
          value: "redis://redis-service:6379"
        - name: POSTGRES_URL
          valueFrom:
            secretKeyRef:
              name: m4-secrets
              key: postgres-url
        resources:
          requests:
            memory: "512Mi"
            cpu: "250m"
          limits:
            memory: "2Gi"
            cpu: "1000m"
        livenessProbe:
          httpGet:
            path: /health
            port: 5000
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /ready
            port: 5000
          initialDelaySeconds: 10
          periodSeconds: 5
        volumeMounts:
        - name: snapshots
          mountPath: /app/snapshots
      volumes:
      - name: snapshots
        persistentVolumeClaim:
          claimName: m4-snapshots-pvc
---
apiVersion: v1
kind: Service
metadata:
  name: m4-safety-service
spec:
  selector:
    app: m4-safety
  ports:
  - protocol: TCP
    port: 5000
    targetPort: 5000
  type: ClusterIP
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: m4-snapshots-pvc
spec:
  accessModes:
  - ReadWriteMany
  resources:
    requests:
      storage: 100Gi
  storageClassName: fast-ssd
```

```bash
# Deploy to Kubernetes
kubectl apply -f k8s/m4-deployment.yaml

# Scale deployment
kubectl scale deployment m4-safety-service --replicas=5

# Check status
kubectl get pods -l app=m4-safety
kubectl logs -l app=m4-safety --tail=100
```

**Pros:**
- Auto-scaling
- High availability
- Rolling updates
- Cloud-native monitoring

**Cons:**
- Kubernetes complexity
- Higher resource usage
- Requires K8s expertise

---

## Configuration

### Environment Variables

```bash
# Core Configuration
M4_STORAGE_PATH=/var/m4/snapshots
M4_LOG_LEVEL=INFO
M4_ENABLE_METRICS=true

# Policy Configuration
M4_POLICY_FAIL_FAST=false
M4_POLICY_TIMEOUT_SECONDS=30

# Approval Configuration
M4_APPROVAL_TIMEOUT_MINUTES=60
M4_APPROVAL_AUTO_REJECT=true

# Rollback Configuration
M4_ROLLBACK_MAX_SNAPSHOTS=1000
M4_ROLLBACK_CLEANUP_HOURS=24

# Circuit Breaker Configuration
M4_BREAKER_FAILURE_THRESHOLD=5
M4_BREAKER_TIMEOUT_SECONDS=60
M4_BREAKER_SUCCESS_THRESHOLD=2

# Database Configuration (for multi-process)
M4_REDIS_URL=redis://localhost:6379
M4_POSTGRES_URL=postgresql://user:pass@localhost/m4
```

### Configuration File

```yaml
# config/m4-config.yaml
m4:
  # Storage
  storage:
    path: /var/m4/snapshots
    max_snapshots: 1000
    cleanup_hours: 24

  # Logging
  logging:
    level: INFO
    format: json
    output: /var/log/m4/m4.log

  # Metrics
  metrics:
    enabled: true
    port: 9090
    endpoint: /metrics

  # Policies
  policies:
    fail_fast: false
    timeout_seconds: 30
    default_priority: 100

  # Approval
  approval:
    timeout_minutes: 60
    auto_reject_on_timeout: true
    required_approvers: 1

  # Circuit Breakers
  circuit_breakers:
    failure_threshold: 5
    timeout_seconds: 60
    success_threshold: 2
    default_breakers:
      - name: database
        failure_threshold: 3
        timeout_seconds: 300
      - name: file_ops
        failure_threshold: 5
        timeout_seconds: 60
      - name: api_calls
        failure_threshold: 10
        timeout_seconds: 30
```

### Loading Configuration

```python
# config_loader.py
import yaml
import os
from pathlib import Path

def load_m4_config(config_path: str = None):
    """Load M4 configuration from file or environment."""

    # Default config path
    if config_path is None:
        config_path = os.getenv('M4_CONFIG_PATH', 'config/m4-config.yaml')

    # Load from file
    if Path(config_path).exists():
        with open(config_path) as f:
            config = yaml.safe_load(f)
    else:
        config = {}

    # Override with environment variables
    config.setdefault('m4', {})

    if 'M4_STORAGE_PATH' in os.environ:
        config['m4'].setdefault('storage', {})['path'] = os.environ['M4_STORAGE_PATH']

    if 'M4_LOG_LEVEL' in os.environ:
        config['m4'].setdefault('logging', {})['level'] = os.environ['M4_LOG_LEVEL']

    return config

# Initialize M4 with configuration
config = load_m4_config()

from src.safety import RollbackManager, ApprovalWorkflow, CircuitBreakerManager

rollback_mgr = RollbackManager(
    storage_path=Path(config['m4']['storage']['path'])
)

approval = ApprovalWorkflow(
    default_timeout_minutes=config['m4']['approval']['timeout_minutes'],
    auto_reject_on_timeout=config['m4']['approval']['auto_reject_on_timeout']
)

breaker_mgr = CircuitBreakerManager()
for breaker_config in config['m4']['circuit_breakers']['default_breakers']:
    breaker_mgr.create_breaker(**breaker_config)
```

---

## Integration Patterns

### Pattern 1: Middleware Integration

```python
# middleware.py - Flask middleware
from flask import Flask, request, g
from src.safety import SafetyGate, PolicyComposer, CircuitBreaker

app = Flask(__name__)

# Initialize M4
composer = PolicyComposer()
breaker = CircuitBreaker("api")
gate = SafetyGate("api_gate", circuit_breaker=breaker, policy_composer=composer)

@app.before_request
def m4_safety_check():
    """Check all requests through M4 safety gate."""
    action = {
        'tool': 'api_call',
        'method': request.method,
        'path': request.path,
        'data': request.get_json(silent=True)
    }
    context = {
        'user': request.headers.get('X-User'),
        'ip': request.remote_addr
    }

    can_pass, reasons = gate.validate(action, context)
    if not can_pass:
        return {'error': 'Request blocked', 'reasons': reasons}, 403

    # Store for after_request
    g.m4_action = action
    g.m4_context = context

@app.after_request
def m4_record_success(response):
    """Record successful requests."""
    if response.status_code < 400:
        breaker.record_success()
    else:
        breaker.record_failure()
    return response
```

### Pattern 2: Decorator Integration

```python
# decorators.py - M4 decorators
from functools import wraps
from src.safety import SafetyGate, RollbackManager

def with_m4_safety(gate: SafetyGate, rollback_mgr: RollbackManager):
    """Decorator for M4 safety checks."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            action = {
                'tool': func.__name__,
                'args': args,
                'kwargs': kwargs
            }
            context = {'function': func.__module__}

            # Validate through gate
            can_pass, reasons = gate.validate(action, context)
            if not can_pass:
                raise Exception(f"Blocked: {'; '.join(reasons)}")

            # Create rollback snapshot
            snapshot = rollback_mgr.create_snapshot(action, context)

            try:
                result = func(*args, **kwargs)
                return result
            except Exception:
                rollback_mgr.execute_rollback(snapshot.id)
                raise

        return wrapper
    return decorator

# Usage
@with_m4_safety(gate, rollback_mgr)
def risky_operation(file_path: str):
    """Operation protected by M4."""
    # ... implementation ...
```

### Pattern 3: Context Manager Integration

```python
# context_managers.py - M4 context managers
from contextlib import contextmanager
from src.safety import SafetyGate, RollbackManager, ApprovalWorkflow

@contextmanager
def m4_protected_operation(
    action: dict,
    context: dict,
    gate: SafetyGate,
    approval: ApprovalWorkflow,
    rollback_mgr: RollbackManager,
    require_approval: bool = False
):
    """Context manager for M4-protected operations."""

    # Step 1: Validate through gate
    can_pass, reasons = gate.validate(action, context)
    if not can_pass:
        raise Exception(f"Blocked by safety gate: {'; '.join(reasons)}")

    # Step 2: Request approval if required
    if require_approval:
        request = approval.request_approval(
            action=action,
            reason=f"Approval required for {action.get('tool')}",
            context=context
        )
        # Wait for approval (in production, this would be async)
        if not request.is_approved():
            raise Exception("Approval not granted")

    # Step 3: Create rollback snapshot
    snapshot = rollback_mgr.create_snapshot(action, context)

    try:
        yield snapshot
    except Exception as e:
        # Rollback on failure
        result = rollback_mgr.execute_rollback(snapshot.id)
        if not result.success:
            print(f"Warning: Rollback failed: {result.errors}")
        raise

# Usage
with m4_protected_operation(action, context, gate, approval, rollback_mgr):
    perform_risky_operation()
```

---

## Scaling Considerations

### Horizontal Scaling

**Policy Validation:**
- Stateless - scales linearly
- No coordination needed
- Can cache policy results

**Approval Workflow:**
- Requires shared state (database)
- Use Redis for request queuing
- PostgreSQL for persistence

**Rollback Manager:**
- Snapshots stored in shared storage (S3, NFS)
- Local cache for frequently accessed snapshots
- Cleanup job runs periodically

**Circuit Breakers:**
- Per-service breakers in shared state (Redis)
- Use distributed locks for state transitions
- Aggregate metrics across instances

### Vertical Scaling

**Memory:**
- Base: 512MB per instance
- +50MB per 1000 policies
- +100MB per 10000 snapshots
- +50MB per 1000 approval requests

**CPU:**
- Policy validation: CPU-bound
- 1 core handles ~10000 validations/sec
- Circuit breaker: minimal CPU (<1%)

**Disk:**
- Snapshots: ~10KB per snapshot (average)
- Logs: ~100MB/day (default logging)
- Approvals: ~1KB per request

### Performance Tuning

```python
# performance_config.py
from src.safety import PolicyComposer, RollbackManager

# 1. Enable fail-fast for faster validation
composer = PolicyComposer(fail_fast=True)

# 2. Limit snapshot size
rollback_mgr = RollbackManager()
rollback_mgr.cleanup_old_snapshots(max_age_hours=12)

# 3. Cache policy results
from functools import lru_cache

@lru_cache(maxsize=10000)
def cached_validate(action_hash, context_hash):
    return composer.validate(action, context)

# 4. Use connection pooling for multi-process
import redis
redis_pool = redis.ConnectionPool(host='localhost', port=6379, max_connections=50)
redis_client = redis.Redis(connection_pool=redis_pool)
```

---

## Monitoring and Observability

### Metrics

```python
# metrics.py - Prometheus metrics
from prometheus_client import Counter, Gauge, Histogram, start_http_server
from src.safety import PolicyComposer, CircuitBreakerManager

# Policy metrics
policy_validations = Counter('m4_policy_validations_total', 'Total policy validations', ['result'])
policy_violations = Counter('m4_policy_violations_total', 'Total policy violations', ['severity'])
policy_duration = Histogram('m4_policy_duration_seconds', 'Policy validation duration')

# Approval metrics
approval_requests = Counter('m4_approval_requests_total', 'Total approval requests')
approval_status = Gauge('m4_approval_pending', 'Number of pending approvals')

# Rollback metrics
rollback_snapshots = Gauge('m4_rollback_snapshots', 'Number of rollback snapshots')
rollback_executions = Counter('m4_rollback_executions_total', 'Total rollback executions', ['status'])

# Circuit breaker metrics
breaker_state = Gauge('m4_breaker_state', 'Circuit breaker state', ['breaker', 'state'])
breaker_calls = Counter('m4_breaker_calls_total', 'Total breaker calls', ['breaker', 'result'])

def record_metrics(composer, approval, rollback_mgr, breaker_mgr):
    """Update M4 metrics."""
    # Policy metrics
    for policy_name in composer.list_policies():
        policy = composer.get_policy(policy_name)
        # Record metrics from policy

    # Approval metrics
    approval_status.set(len(approval.list_pending_requests()))

    # Rollback metrics
    rollback_snapshots.set(rollback_mgr.snapshot_count())

    # Circuit breaker metrics
    for breaker_name in breaker_mgr.list_breakers():
        breaker = breaker_mgr.get_breaker(breaker_name)
        breaker_state.labels(breaker=breaker_name, state=breaker.state.value).set(1)

# Start metrics server
start_http_server(9090)
```

### Logging

```python
# logging_config.py
import logging
import json
from datetime import datetime

class M4JsonFormatter(logging.Formatter):
    """JSON formatter for M4 logs."""
    def format(self, record):
        log_data = {
            'timestamp': datetime.utcnow().isoformat(),
            'level': record.levelname,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno
        }
        if hasattr(record, 'm4_action'):
            log_data['m4_action'] = record.m4_action
        if hasattr(record, 'm4_context'):
            log_data['m4_context'] = record.m4_context
        return json.dumps(log_data)

# Configure logging
logger = logging.getLogger('m4')
handler = logging.FileHandler('/var/log/m4/m4.log')
handler.setFormatter(M4JsonFormatter())
logger.addHandler(handler)
logger.setLevel(logging.INFO)

# Use in M4 components
logger.info('Policy validation failed', extra={
    'm4_action': action,
    'm4_context': context
})
```

### Health Checks

```python
# health.py - Health check endpoints
from flask import Flask, jsonify
from src.safety import PolicyComposer, ApprovalWorkflow, CircuitBreakerManager

app = Flask(__name__)

@app.route('/health')
def health():
    """Basic health check."""
    return jsonify({'status': 'healthy'})

@app.route('/ready')
def ready():
    """Readiness check - verify all components initialized."""
    try:
        # Check if M4 components are initialized
        assert composer is not None
        assert approval is not None
        assert breaker_mgr is not None

        # Check if storage is accessible
        rollback_mgr.list_snapshots()

        return jsonify({'status': 'ready'})
    except Exception as e:
        return jsonify({'status': 'not ready', 'error': str(e)}), 503

@app.route('/status')
def status():
    """Detailed status information."""
    return jsonify({
        'policies': len(composer.list_policies()),
        'pending_approvals': len(approval.list_pending_requests()),
        'snapshots': rollback_mgr.snapshot_count(),
        'circuit_breakers': {
            name: breaker_mgr.get_breaker(name).state.value
            for name in breaker_mgr.list_breakers()
        }
    })
```

---

## Production Checklist

### Pre-Deployment

- [ ] All tests passing (`pytest tests/test_safety/ -v`)
- [ ] Configuration reviewed and validated
- [ ] Storage paths configured and accessible
- [ ] Database connections tested (if multi-process)
- [ ] Metrics endpoint accessible
- [ ] Health checks responding
- [ ] Log rotation configured
- [ ] Backup strategy defined
- [ ] Rollback plan documented

### Security

- [ ] Secrets stored in secure vault (not environment variables)
- [ ] File permissions restricted (snapshots, logs)
- [ ] Network policies configured (if Kubernetes)
- [ ] TLS enabled for service communication
- [ ] Authentication configured for approval workflow
- [ ] Audit logging enabled
- [ ] Rate limiting configured

### Performance

- [ ] Load testing completed
- [ ] Resource limits configured
- [ ] Caching strategy implemented
- [ ] Database indexes created
- [ ] Snapshot cleanup scheduled
- [ ] Metrics collection tested
- [ ] Alert thresholds configured

### Monitoring

- [ ] Prometheus metrics exported
- [ ] Grafana dashboards created
- [ ] Alerts configured (PagerDuty, Slack, etc.)
- [ ] Log aggregation configured (ELK, Splunk, etc.)
- [ ] SLIs/SLOs defined
- [ ] Error budget calculated
- [ ] On-call runbook created

### Documentation

- [ ] Architecture diagram updated
- [ ] API documentation published
- [ ] Configuration examples documented
- [ ] Troubleshooting guide created
- [ ] Runbook for common issues
- [ ] Contact information for support

---

## Troubleshooting

### Issue: Policy validation slow

**Symptoms:**
- Policy validation taking >100ms
- High CPU usage during validation

**Diagnosis:**
```python
# Enable profiling
import cProfile
cProfile.run('composer.validate(action, context)')
```

**Solutions:**
1. Enable fail-fast mode: `composer.set_fail_fast(True)`
2. Reduce number of policies
3. Optimize policy logic
4. Cache validation results

---

### Issue: Approval requests timing out

**Symptoms:**
- Approval requests automatically rejected
- Approvers not receiving notifications

**Diagnosis:**
```python
# Check pending approvals
pending = approval.list_pending_requests()
for req in pending:
    print(f"{req.id}: expires at {req.expires_at}")
```

**Solutions:**
1. Increase timeout: `approval = ApprovalWorkflow(default_timeout_minutes=120)`
2. Implement approval notifications
3. Check approval callback registration
4. Verify approval workflow is running

---

### Issue: Circuit breaker stuck open

**Symptoms:**
- Circuit breaker remains open
- Operations blocked indefinitely

**Diagnosis:**
```python
# Check breaker state
breaker = breaker_mgr.get_breaker("service")
print(f"State: {breaker.state.value}")
print(f"Metrics: {breaker.metrics}")
```

**Solutions:**
1. Manually reset: `breaker.force_close()`
2. Verify service is healthy
3. Adjust timeout: `breaker.timeout_seconds = 300`
4. Check failure threshold: `breaker.failure_threshold = 10`

---

### Issue: Rollback snapshots consuming disk space

**Symptoms:**
- Disk usage increasing
- Many old snapshots

**Diagnosis:**
```bash
# Check snapshot directory size
du -sh /var/m4/snapshots

# Count snapshots
python -c "from src.safety import RollbackManager; mgr = RollbackManager(); print(mgr.snapshot_count())"
```

**Solutions:**
1. Run cleanup: `rollback_mgr.cleanup_old_snapshots(max_age_hours=12)`
2. Schedule periodic cleanup (cron job)
3. Reduce snapshot retention
4. Use compression for snapshot storage

---

### Issue: M4 service not starting

**Symptoms:**
- Service fails to start
- Health check failing

**Diagnosis:**
```bash
# Check logs
tail -f /var/log/m4/m4.log

# Check configuration
python -c "from config_loader import load_m4_config; print(load_m4_config())"

# Verify dependencies
python -c "from src.safety import *; print('OK')"
```

**Solutions:**
1. Verify Python version (3.11+)
2. Check storage path exists and is writable
3. Verify database connectivity (if multi-process)
4. Review configuration file syntax
5. Check for conflicting ports

---

## Next Steps

After deployment:

1. **Monitor metrics** - Watch for anomalies in validation times, approval rates, circuit breaker state
2. **Review logs** - Check for errors, warnings, unexpected behavior
3. **Test rollback** - Verify rollback works in production environment
4. **Tune configuration** - Adjust thresholds based on observed behavior
5. **Document learnings** - Update runbook with production-specific issues

---

**See Also:**
- [M4 Safety Architecture](./M4_SAFETY_ARCHITECTURE.md)
- [M4 API Reference](./M4_API_REFERENCE.md)
- [M4 Configuration Guide](./M4_CONFIGURATION_GUIDE.md) (coming next)
