# M4 Safety System - Configuration Guide

**Scope:** M4 Safety System Only (Policies, Approvals, Rollback, Circuit Breakers, Gates)

**For General Framework Configuration:** See [CONFIGURATION.md](CONFIGURATION.md) for agents, workflows, LLM providers, tools, multi-agent coordination, and observability.

**Version:** 1.0
**Last Updated:** 2026-01-27
**Status:** Production Ready

This guide covers all configuration options for the M4 Safety System, with examples and best practices.

---

## Table of Contents

1. [Configuration Overview](#configuration-overview)
2. [Policy Configuration](#policy-configuration)
3. [Approval Workflow Configuration](#approval-workflow-configuration)
4. [Rollback Configuration](#rollback-configuration)
5. [Circuit Breaker Configuration](#circuit-breaker-configuration)
6. [Safety Gate Configuration](#safety-gate-configuration)
7. [Storage Configuration](#storage-configuration)
8. [Logging Configuration](#logging-configuration)
9. [Performance Tuning](#performance-tuning)
10. [Environment-Specific Configs](#environment-specific-configs)

---

## Configuration Overview

### Configuration Methods

M4 supports three configuration methods (in order of precedence):

1. **Programmatic** - Direct configuration in code
2. **Environment Variables** - Via `os.environ`
3. **Configuration Files** - YAML/JSON files

**Example:**
```python
# 1. Programmatic (highest precedence)
composer = PolicyComposer(fail_fast=True)

# 2. Environment variable
os.environ['M4_POLICY_FAIL_FAST'] = 'true'

# 3. Configuration file (lowest precedence)
# config/m4.yaml:
#   policies:
#     fail_fast: true
```

### Configuration File Format

```yaml
# config/m4-config.yaml
m4:
  version: "1.0"
  environment: production  # development, staging, production

  # Component configurations
  policies: { ... }
  approval: { ... }
  rollback: { ... }
  circuit_breakers: { ... }

  # Infrastructure
  storage: { ... }
  logging: { ... }
  metrics: { ... }
```

---

## Policy Configuration

### PolicyComposer Configuration

#### Basic Configuration

```python
from temper_ai.safety import PolicyComposer

composer = PolicyComposer(
    policies=None,              # Initial policies (default: None)
    fail_fast=False,            # Stop after first blocking violation (default: False)
    enable_reporting=True       # Enable detailed reports (default: True)
)
```

#### Configuration File

```yaml
# config/m4-config.yaml
m4:
  policies:
    # Execution mode
    fail_fast: false            # Continue validating after violations
    timeout_seconds: 30         # Max time for validation

    # Default priority for policies without explicit priority
    default_priority: 100

    # Policy-specific configurations
    file_access:
      enabled: true
      priority: 200
      allowed_paths:
        - "/tmp/**"
        - "/var/app/data/**"
      denied_paths:
        - "/etc/**"
        - "/root/**"
        - "/home/**"
      forbidden_extensions:
        - ".exe"
        - ".dll"
        - ".sh"

    blast_radius:
      enabled: true
      priority: 150
      max_files_per_commit: 5
      max_lines_per_file: 200
      forbidden_paths:
        - "temper_ai/safety/**"
        - ".github/**"

    rate_limiter:
      enabled: true
      priority: 100
      windows:
        - duration_minutes: 60
          max_calls: 100
        - duration_minutes: 1440  # 24 hours
          max_calls: 1000
```

#### Loading Policy Configuration

```python
# policy_loader.py
import yaml
from pathlib import Path
from temper_ai.safety import PolicyComposer, FileAccessPolicy, BlastRadiusPolicy

def load_policy_config(config_path: str = "config/m4-config.yaml"):
    """Load policy configuration from file."""
    with open(config_path) as f:
        config = yaml.safe_load(f)

    policy_config = config['m4']['policies']

    # Create composer with configured settings
    composer = PolicyComposer(
        fail_fast=policy_config.get('fail_fast', False)
    )

    # Add FileAccessPolicy if enabled
    if policy_config.get('file_access', {}).get('enabled', True):
        file_config = policy_config['file_access']
        composer.add_policy(FileAccessPolicy({
            'allowed_paths': file_config.get('allowed_paths', []),
            'denied_paths': file_config.get('denied_paths', []),
            'forbidden_extensions': file_config.get('forbidden_extensions', [])
        }))

    # Add BlastRadiusPolicy if enabled
    if policy_config.get('blast_radius', {}).get('enabled', True):
        blast_config = policy_config['blast_radius']
        composer.add_policy(BlastRadiusPolicy({
            'max_files_per_commit': blast_config.get('max_files_per_commit', 5),
            'max_lines_per_file': blast_config.get('max_lines_per_file', 200),
            'forbidden_paths': blast_config.get('forbidden_paths', [])
        }))

    return composer

# Usage
composer = load_policy_config()
```

### Environment Variables

```bash
# Policy execution
export M4_POLICY_FAIL_FAST=true
export M4_POLICY_TIMEOUT_SECONDS=30
export M4_POLICY_DEFAULT_PRIORITY=100

# FileAccessPolicy
export M4_FILE_ACCESS_ALLOWED_PATHS="/tmp/**,/var/app/**"
export M4_FILE_ACCESS_DENIED_PATHS="/etc/**,/root/**"
export M4_FILE_ACCESS_FORBIDDEN_EXTS=".exe,.dll,.sh"

# BlastRadiusPolicy
export M4_BLAST_RADIUS_MAX_FILES=5
export M4_BLAST_RADIUS_MAX_LINES=200
export M4_BLAST_RADIUS_FORBIDDEN_PATHS="temper_ai/safety/**,.github/**"
```

### Custom Policy Configuration

```python
# custom_policy.py
from temper_ai.safety import SafetyPolicy, ValidationResult, SafetyViolation, SafetyViolationSeverity

class CustomPolicy(SafetyPolicy):
    """Custom policy with configurable rules."""

    def __init__(self, config: dict):
        super().__init__(
            name=config.get('name', 'custom_policy'),
            priority=config.get('priority', 100)
        )
        self.max_retries = config.get('max_retries', 3)
        self.allowed_users = set(config.get('allowed_users', []))
        self.require_justification = config.get('require_justification', False)

    def validate(self, action: dict, context: dict) -> ValidationResult:
        violations = []

        # Check user is allowed
        user = context.get('user')
        if user not in self.allowed_users:
            violations.append(SafetyViolation(
                policy_name=self.name,
                severity=SafetyViolationSeverity.HIGH,
                message=f"User '{user}' not in allowed list",
                action=action,
                context=context
            ))

        # Check justification provided
        if self.require_justification and not action.get('justification'):
            violations.append(SafetyViolation(
                policy_name=self.name,
                severity=SafetyViolationSeverity.MEDIUM,
                message="Justification required but not provided",
                action=action,
                context=context
            ))

        return ValidationResult(
            valid=len(violations) == 0,
            violations=violations,
            policy_name=self.name
        )

# Configuration
custom_policy_config = {
    'name': 'production_policy',
    'priority': 150,
    'max_retries': 3,
    'allowed_users': ['admin', 'ops_team', 'senior_engineer'],
    'require_justification': True
}

custom_policy = CustomPolicy(custom_policy_config)
composer.add_policy(custom_policy)
```

---

## Approval Workflow Configuration

### Basic Configuration

```python
from temper_ai.safety import ApprovalWorkflow

approval = ApprovalWorkflow(
    default_timeout_minutes=60,    # Default request timeout (default: 60)
    auto_reject_on_timeout=True    # Auto-reject expired requests (default: True)
)
```

### Configuration File

```yaml
# config/m4-config.yaml
m4:
  approval:
    # Timeout settings
    default_timeout_minutes: 60
    auto_reject_on_timeout: true

    # Approval requirements
    default_required_approvers: 1

    # Environment-specific rules
    environments:
      development:
        required_approvers: 1
        timeout_minutes: 30
      staging:
        required_approvers: 1
        timeout_minutes: 60
      production:
        required_approvers: 2
        timeout_minutes: 120
        allowed_approvers:
          - senior_engineer
          - tech_lead
          - ops_lead

    # Approval categories
    categories:
      deployment:
        required_approvers: 2
        timeout_minutes: 60
        allowed_approvers:
          - tech_lead
          - ops_lead
      database_migration:
        required_approvers: 2
        timeout_minutes: 120
        allowed_approvers:
          - senior_dba
          - tech_lead
      config_change:
        required_approvers: 1
        timeout_minutes: 30

    # Notifications (optional)
    notifications:
      enabled: true
      slack_webhook: "https://hooks.slack.com/services/..."
      email_recipients:
        - ops-team@company.com
```

### Loading Approval Configuration

```python
# approval_loader.py
import yaml
from temper_ai.safety import ApprovalWorkflow

def load_approval_config(config_path: str = "config/m4-config.yaml"):
    """Load approval workflow configuration."""
    with open(config_path) as f:
        config = yaml.safe_load(f)

    approval_config = config['m4']['approval']

    approval = ApprovalWorkflow(
        default_timeout_minutes=approval_config.get('default_timeout_minutes', 60),
        auto_reject_on_timeout=approval_config.get('auto_reject_on_timeout', True)
    )

    return approval, approval_config

# Usage with environment-specific rules
approval, config = load_approval_config()

def request_approval_with_config(action, reason, environment='production'):
    """Request approval using environment-specific configuration."""
    env_config = config['environments'].get(environment, {})

    required_approvers = env_config.get(
        'required_approvers',
        config.get('default_required_approvers', 1)
    )

    timeout_minutes = env_config.get(
        'timeout_minutes',
        config.get('default_timeout_minutes', 60)
    )

    request = approval.request_approval(
        action=action,
        reason=reason,
        required_approvers=required_approvers,
        timeout_minutes=timeout_minutes,
        metadata={'environment': environment}
    )

    return request

# Usage
request = request_approval_with_config(
    action={'tool': 'deploy', 'environment': 'production'},
    reason='Deploy v2.0.0 to production',
    environment='production'
)
```

### Notification Callbacks

```python
# notifications.py
import requests
from temper_ai.safety import ApprovalWorkflow, ApprovalRequest

def send_slack_notification(webhook_url: str, request: ApprovalRequest):
    """Send Slack notification for approval request."""
    message = {
        "text": f"Approval Request: {request.reason}",
        "attachments": [
            {
                "color": "warning",
                "fields": [
                    {"title": "Request ID", "value": request.id, "short": True},
                    {"title": "Required Approvers", "value": str(request.required_approvers), "short": True},
                    {"title": "Expires", "value": request.expires_at.isoformat(), "short": False}
                ]
            }
        ]
    }
    requests.post(webhook_url, json=message)

# Register callbacks
def setup_approval_notifications(approval: ApprovalWorkflow, config: dict):
    """Setup approval notifications based on configuration."""
    if not config.get('notifications', {}).get('enabled', False):
        return

    slack_webhook = config['notifications'].get('slack_webhook')

    def on_approval_request(request: ApprovalRequest):
        if slack_webhook:
            send_slack_notification(slack_webhook, request)

    def on_approval_granted(request: ApprovalRequest):
        if slack_webhook:
            message = {"text": f"✅ Approval granted: {request.reason}"}
            requests.post(slack_webhook, json=message)

    def on_approval_rejected(request: ApprovalRequest):
        if slack_webhook:
            message = {"text": f"❌ Approval rejected: {request.reason}"}
            requests.post(slack_webhook, json=message)

    approval.on_approved(on_approval_granted)
    approval.on_rejected(on_approval_rejected)

# Usage
approval, config = load_approval_config()
setup_approval_notifications(approval, config)
```

### Environment Variables

```bash
# Approval workflow
export M4_APPROVAL_TIMEOUT_MINUTES=60
export M4_APPROVAL_AUTO_REJECT=true
export M4_APPROVAL_REQUIRED_APPROVERS=1

# Notifications
export M4_APPROVAL_SLACK_WEBHOOK="https://hooks.slack.com/..."
export M4_APPROVAL_EMAIL_RECIPIENTS="ops@company.com,dev@company.com"
```

---

## Rollback Configuration

### Basic Configuration

```python
from temper_ai.safety import RollbackManager, FileRollbackStrategy, StateRollbackStrategy, CompositeRollbackStrategy
from pathlib import Path

# Default composite strategy
rollback_mgr = RollbackManager()

# Custom storage path
rollback_mgr = RollbackManager(storage_path=Path("/var/m4/snapshots"))

# Custom strategy
file_strategy = FileRollbackStrategy()
rollback_mgr = RollbackManager(strategy=file_strategy)

# Composite strategy
composite = CompositeRollbackStrategy([
    FileRollbackStrategy(),
    StateRollbackStrategy()
])
rollback_mgr = RollbackManager(strategy=composite)
```

### Configuration File

```yaml
# config/m4-config.yaml
m4:
  rollback:
    # Storage settings
    storage_path: /var/m4/snapshots
    max_snapshots: 1000
    max_snapshot_size_mb: 100

    # Cleanup settings
    cleanup_enabled: true
    cleanup_interval_hours: 24
    max_age_hours: 168  # 7 days

    # Strategy settings
    strategy: composite  # file, state, composite
    strategies:
      file:
        enabled: true
        include_content: true
        max_file_size_mb: 10
      state:
        enabled: true
        max_state_size_kb: 100

    # Compression
    compression_enabled: true
    compression_level: 6  # 1-9, higher = more compression

    # Backup
    backup_enabled: true
    backup_path: /var/m4/backups
    backup_retention_days: 30
```

### Loading Rollback Configuration

```python
# rollback_loader.py
import yaml
from pathlib import Path
from temper_ai.safety import RollbackManager, CompositeRollbackStrategy, FileRollbackStrategy, StateRollbackStrategy

def load_rollback_config(config_path: str = "config/m4-config.yaml"):
    """Load rollback configuration."""
    with open(config_path) as f:
        config = yaml.safe_load(f)

    rollback_config = config['m4']['rollback']

    # Create storage path
    storage_path = Path(rollback_config.get('storage_path', '/tmp/m4/snapshots'))
    storage_path.mkdir(parents=True, exist_ok=True)

    # Create strategy based on configuration
    strategy_type = rollback_config.get('strategy', 'composite')

    if strategy_type == 'file':
        strategy = FileRollbackStrategy()
    elif strategy_type == 'state':
        strategy = StateRollbackStrategy()
    elif strategy_type == 'composite':
        strategies = []
        if rollback_config.get('strategies', {}).get('file', {}).get('enabled', True):
            strategies.append(FileRollbackStrategy())
        if rollback_config.get('strategies', {}).get('state', {}).get('enabled', True):
            strategies.append(StateRollbackStrategy())
        strategy = CompositeRollbackStrategy(strategies)
    else:
        raise ValueError(f"Unknown strategy type: {strategy_type}")

    # Create rollback manager
    rollback_mgr = RollbackManager(
        strategy=strategy,
        storage_path=storage_path
    )

    return rollback_mgr, rollback_config

# Usage
rollback_mgr, config = load_rollback_config()

# Setup automatic cleanup
import schedule
import threading

def cleanup_task():
    """Periodic cleanup task."""
    max_age_hours = config.get('max_age_hours', 168)
    deleted = rollback_mgr.cleanup_old_snapshots(max_age_hours=max_age_hours)
    print(f"Cleaned up {deleted} old snapshots")

if config.get('cleanup_enabled', True):
    interval_hours = config.get('cleanup_interval_hours', 24)
    schedule.every(interval_hours).hours.do(cleanup_task)

    def run_scheduler():
        while True:
            schedule.run_pending()
            time.sleep(60)

    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()
```

### Snapshot Compression

```python
# compression.py
import gzip
import json
from temper_ai.safety import RollbackSnapshot

def compress_snapshot(snapshot: RollbackSnapshot, output_path: Path):
    """Compress snapshot to gzip file."""
    snapshot_dict = {
        'id': snapshot.id,
        'action': snapshot.action,
        'context': snapshot.context,
        'created_at': snapshot.created_at.isoformat(),
        'file_snapshots': snapshot.file_snapshots,
        'state_snapshots': snapshot.state_snapshots,
        'metadata': snapshot.metadata
    }

    with gzip.open(output_path, 'wt', encoding='utf-8') as f:
        json.dump(snapshot_dict, f)

def decompress_snapshot(input_path: Path) -> dict:
    """Decompress snapshot from gzip file."""
    with gzip.open(input_path, 'rt', encoding='utf-8') as f:
        return json.load(f)

# Usage with RollbackManager
def save_compressed_snapshot(rollback_mgr: RollbackManager, snapshot: RollbackSnapshot):
    """Save snapshot with compression."""
    storage_path = Path("/var/m4/snapshots")
    compress_snapshot(snapshot, storage_path / f"{snapshot.id}.json.gz")
```

### Environment Variables

```bash
# Rollback storage
export M4_ROLLBACK_STORAGE_PATH=/var/m4/snapshots
export M4_ROLLBACK_MAX_SNAPSHOTS=1000
export M4_ROLLBACK_MAX_SIZE_MB=100

# Cleanup
export M4_ROLLBACK_CLEANUP_ENABLED=true
export M4_ROLLBACK_CLEANUP_HOURS=24
export M4_ROLLBACK_MAX_AGE_HOURS=168

# Strategy
export M4_ROLLBACK_STRATEGY=composite
export M4_ROLLBACK_FILE_ENABLED=true
export M4_ROLLBACK_STATE_ENABLED=true
```

---

## Circuit Breaker Configuration

### Basic Configuration

```python
from temper_ai.safety import CircuitBreaker, CircuitBreakerManager

# Single circuit breaker
breaker = CircuitBreaker(
    name="database",
    failure_threshold=5,      # Open after 5 failures (default: 5)
    timeout_seconds=60,       # Wait 60s before retry (default: 60)
    success_threshold=2       # Need 2 successes to close (default: 2)
)

# Circuit breaker manager
manager = CircuitBreakerManager()
manager.create_breaker("database", failure_threshold=3, timeout_seconds=300)
manager.create_breaker("cache", failure_threshold=5, timeout_seconds=60)
manager.create_breaker("api", failure_threshold=10, timeout_seconds=30)
```

### Configuration File

```yaml
# config/m4-config.yaml
m4:
  circuit_breakers:
    # Default settings for all breakers
    defaults:
      failure_threshold: 5
      timeout_seconds: 60
      success_threshold: 2

    # Named circuit breakers
    breakers:
      database:
        failure_threshold: 3
        timeout_seconds: 300
        success_threshold: 2
        enabled: true

      cache:
        failure_threshold: 5
        timeout_seconds: 60
        success_threshold: 2
        enabled: true

      api:
        failure_threshold: 10
        timeout_seconds: 30
        success_threshold: 3
        enabled: true

      file_operations:
        failure_threshold: 5
        timeout_seconds: 120
        success_threshold: 2
        enabled: true

    # State change callbacks
    callbacks:
      slack_webhook: "https://hooks.slack.com/..."
      pagerduty_key: "..."

    # Metrics
    metrics:
      enabled: true
      port: 9090
```

### Loading Circuit Breaker Configuration

```python
# breaker_loader.py
import yaml
from temper_ai.safety import CircuitBreakerManager

def load_breaker_config(config_path: str = "config/m4-config.yaml"):
    """Load circuit breaker configuration."""
    with open(config_path) as f:
        config = yaml.safe_load(f)

    breaker_config = config['m4']['circuit_breakers']
    defaults = breaker_config.get('defaults', {})

    manager = CircuitBreakerManager()

    # Create configured breakers
    for name, breaker_cfg in breaker_config.get('breakers', {}).items():
        if not breaker_cfg.get('enabled', True):
            continue

        manager.create_breaker(
            name=name,
            failure_threshold=breaker_cfg.get('failure_threshold', defaults.get('failure_threshold', 5)),
            timeout_seconds=breaker_cfg.get('timeout_seconds', defaults.get('timeout_seconds', 60)),
            success_threshold=breaker_cfg.get('success_threshold', defaults.get('success_threshold', 2))
        )

    return manager, breaker_config

# Usage
manager, config = load_breaker_config()
```

### State Change Callbacks

```python
# breaker_callbacks.py
import requests
from temper_ai.safety import CircuitBreakerState

def setup_breaker_callbacks(manager: CircuitBreakerManager, config: dict):
    """Setup circuit breaker state change callbacks."""
    callbacks_config = config.get('callbacks', {})
    slack_webhook = callbacks_config.get('slack_webhook')

    def on_breaker_state_change(breaker_name: str):
        def callback(old_state: CircuitBreakerState, new_state: CircuitBreakerState):
            message = f"🔴 Circuit breaker '{breaker_name}': {old_state.value} → {new_state.value}"

            # Send Slack notification
            if slack_webhook:
                requests.post(slack_webhook, json={"text": message})

            # Alert if circuit opens
            if new_state == CircuitBreakerState.OPEN:
                alert_ops_team(breaker_name)

        return callback

    # Register callbacks for all breakers
    for breaker_name in manager.list_breakers():
        breaker = manager.get_breaker(breaker_name)
        breaker.on_state_change(on_breaker_state_change(breaker_name))

def alert_ops_team(breaker_name: str):
    """Alert ops team about circuit breaker opening."""
    # Implement alerting logic (PagerDuty, email, etc.)
    pass

# Usage
manager, config = load_breaker_config()
setup_breaker_callbacks(manager, config)
```

### Environment Variables

```bash
# Circuit breaker defaults
export M4_BREAKER_FAILURE_THRESHOLD=5
export M4_BREAKER_TIMEOUT_SECONDS=60
export M4_BREAKER_SUCCESS_THRESHOLD=2

# Named breakers
export M4_BREAKER_DATABASE_THRESHOLD=3
export M4_BREAKER_DATABASE_TIMEOUT=300
export M4_BREAKER_CACHE_THRESHOLD=5
export M4_BREAKER_CACHE_TIMEOUT=60

# Callbacks
export M4_BREAKER_SLACK_WEBHOOK="https://hooks.slack.com/..."
export M4_BREAKER_PAGERDUTY_KEY="..."
```

---

## Safety Gate Configuration

### Basic Configuration

```python
from temper_ai.safety import SafetyGate, CircuitBreaker, PolicyComposer

gate = SafetyGate(
    name="main_gate",
    circuit_breaker=CircuitBreaker("main"),
    policy_composer=PolicyComposer()
)
```

### Configuration File

```yaml
# config/m4-config.yaml
m4:
  safety_gates:
    # Named safety gates
    database_gate:
      enabled: true
      circuit_breaker: database
      policies:
        - file_access
        - blast_radius

    api_gate:
      enabled: true
      circuit_breaker: api
      policies:
        - rate_limiter

    deployment_gate:
      enabled: true
      circuit_breaker: deployment
      policies:
        - file_access
        - blast_radius
      require_approval: true
      approval_config:
        required_approvers: 2
        timeout_minutes: 120
```

### Loading Safety Gate Configuration

```python
# gate_loader.py
import yaml
from temper_ai.safety import SafetyGate, CircuitBreakerManager, PolicyComposer

def load_gate_config(
    config_path: str = "config/m4-config.yaml",
    breaker_mgr: CircuitBreakerManager = None,
    composer: PolicyComposer = None
):
    """Load safety gate configuration."""
    with open(config_path) as f:
        config = yaml.safe_load(f)

    gate_config = config['m4'].get('safety_gates', {})
    gates = {}

    for gate_name, gate_cfg in gate_config.items():
        if not gate_cfg.get('enabled', True):
            continue

        # Get circuit breaker
        breaker_name = gate_cfg.get('circuit_breaker')
        breaker = breaker_mgr.get_breaker(breaker_name) if breaker_name else None

        # Create gate
        gate = SafetyGate(
            name=gate_name,
            circuit_breaker=breaker,
            policy_composer=composer
        )

        gates[gate_name] = gate

    return gates

# Usage
manager = load_breaker_config()[0]
composer = load_policy_config()
gates = load_gate_config(breaker_mgr=manager, composer=composer)

# Use gates
db_gate = gates['database_gate']
can_pass, reasons = db_gate.validate(action, context)
```

---

## Storage Configuration

### Local File Storage

```yaml
# config/m4-config.yaml
m4:
  storage:
    type: local
    path: /var/m4/data
    snapshots_dir: snapshots
    approvals_dir: approvals
    logs_dir: logs

    # Permissions
    file_mode: 0o600
    dir_mode: 0o700

    # Limits
    max_total_size_gb: 100
    max_file_size_mb: 100
```

### Database Storage

```yaml
# config/m4-config.yaml
m4:
  storage:
    type: database

    # PostgreSQL
    postgres:
      host: localhost
      port: 5432
      database: m4
      user: m4_user
      password: "${M4_DB_PASSWORD}"  # From environment
      pool_size: 10
      max_overflow: 20

    # Redis (for state)
    redis:
      host: localhost
      port: 6379
      db: 0
      password: "${M4_REDIS_PASSWORD}"
      max_connections: 50
```

### Cloud Storage

```yaml
# config/m4-config.yaml
m4:
  storage:
    type: cloud

    # S3 (AWS)
    s3:
      bucket: m4-snapshots
      region: us-west-2
      access_key: "${AWS_ACCESS_KEY}"
      secret_key: "${AWS_SECRET_KEY}"
      prefix: production/

    # GCS (Google Cloud)
    gcs:
      bucket: m4-snapshots
      project: my-project
      credentials: /path/to/credentials.json
```

---

## Logging Configuration

### Basic Configuration

```yaml
# config/m4-config.yaml
m4:
  logging:
    level: INFO  # DEBUG, INFO, WARNING, ERROR, CRITICAL
    format: json  # json, text
    output: file  # file, stdout, both

    # File logging
    file:
      path: /var/log/m4/m4.log
      max_size_mb: 100
      backup_count: 10
      rotation: daily  # daily, weekly, size

    # Structured logging fields
    include_fields:
      - timestamp
      - level
      - module
      - function
      - message
      - m4_component
      - m4_action
      - m4_context

    # Log filtering
    filters:
      - exclude_health_checks
      - exclude_metrics
```

### Loading Logging Configuration

```python
# logging_loader.py
import logging
import yaml
import json
from datetime import datetime
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler

def load_logging_config(config_path: str = "config/m4-config.yaml"):
    """Load logging configuration."""
    with open(config_path) as f:
        config = yaml.safe_load(f)

    log_config = config['m4']['logging']

    # Create logger
    logger = logging.getLogger('m4')
    logger.setLevel(getattr(logging, log_config.get('level', 'INFO')))

    # Create formatter
    if log_config.get('format') == 'json':
        formatter = JsonFormatter(log_config.get('include_fields', []))
    else:
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )

    # Create handlers
    output = log_config.get('output', 'file')

    if output in ['file', 'both']:
        file_config = log_config.get('file', {})
        file_path = file_config.get('path', '/var/log/m4/m4.log')

        if file_config.get('rotation') == 'size':
            handler = RotatingFileHandler(
                file_path,
                maxBytes=file_config.get('max_size_mb', 100) * 1024 * 1024,
                backupCount=file_config.get('backup_count', 10)
            )
        else:
            when = file_config.get('rotation', 'daily')[0].upper()  # D, W
            handler = TimedRotatingFileHandler(
                file_path,
                when=when,
                backupCount=file_config.get('backup_count', 10)
            )

        handler.setFormatter(formatter)
        logger.addHandler(handler)

    if output in ['stdout', 'both']:
        handler = logging.StreamHandler()
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger

class JsonFormatter(logging.Formatter):
    """JSON formatter for structured logging."""

    def __init__(self, include_fields):
        super().__init__()
        self.include_fields = include_fields

    def format(self, record):
        log_data = {
            'timestamp': datetime.utcnow().isoformat(),
            'level': record.levelname,
            'message': record.getMessage(),
        }

        if 'module' in self.include_fields:
            log_data['module'] = record.module
        if 'function' in self.include_fields:
            log_data['function'] = record.funcName

        # Add M4-specific fields
        for field in ['m4_component', 'm4_action', 'm4_context']:
            if field in self.include_fields and hasattr(record, field):
                log_data[field] = getattr(record, field)

        return json.dumps(log_data)

# Usage
logger = load_logging_config()
logger.info("M4 initialized", extra={
    'm4_component': 'policy_composer',
    'm4_action': 'validate',
    'm4_context': {'user': 'alice'}
})
```

---

## Performance Tuning

### Optimization Settings

```yaml
# config/m4-config.yaml
m4:
  performance:
    # Policy validation
    policy_validation:
      enable_caching: true
      cache_ttl_seconds: 300
      max_cache_size: 10000

    # Rollback snapshots
    rollback:
      enable_compression: true
      compression_level: 6
      async_snapshots: true

    # Circuit breakers
    circuit_breakers:
      enable_metrics_collection: true
      metrics_buffer_size: 1000

    # Threading
    threading:
      max_workers: 4
      enable_threading: true
```

### Caching Policy Results

```python
# caching.py
from functools import lru_cache
import hashlib
import json

class CachedPolicyComposer:
    """Policy composer with result caching."""

    def __init__(self, composer: PolicyComposer, cache_size: int = 10000):
        self.composer = composer
        self.cache_size = cache_size

    @lru_cache(maxsize=10000)
    def _cached_validate(self, action_hash: str, context_hash: str):
        """Cached validation (requires hashable inputs)."""
        # This is called by validate() with hashed inputs
        return self.composer.validate(
            json.loads(action_hash),
            json.loads(context_hash)
        )

    def validate(self, action: dict, context: dict):
        """Validate with caching."""
        # Hash inputs for caching
        action_hash = hashlib.sha256(
            json.dumps(action, sort_keys=True).encode()
        ).hexdigest()
        context_hash = hashlib.sha256(
            json.dumps(context, sort_keys=True).encode()
        ).hexdigest()

        return self._cached_validate(action_hash, context_hash)

# Usage
cached_composer = CachedPolicyComposer(composer, cache_size=10000)
result = cached_composer.validate(action, context)
```

---

## Environment-Specific Configs

### Development

```yaml
# config/development.yaml
m4:
  environment: development

  policies:
    fail_fast: false  # See all violations

  approval:
    default_timeout_minutes: 30
    required_approvers: 1  # Single approver in dev

  rollback:
    max_age_hours: 24  # Clean up quickly
    cleanup_interval_hours: 1

  circuit_breakers:
    defaults:
      failure_threshold: 10  # More lenient
      timeout_seconds: 30  # Shorter timeout

  logging:
    level: DEBUG
    output: stdout
```

### Production

```yaml
# config/production.yaml
m4:
  environment: production

  policies:
    fail_fast: true  # Stop early for performance

  approval:
    default_timeout_minutes: 120
    required_approvers: 2  # Dual approval in prod
    auto_reject_on_timeout: true

  rollback:
    max_age_hours: 168  # 7 days retention
    cleanup_interval_hours: 24
    backup_enabled: true

  circuit_breakers:
    defaults:
      failure_threshold: 3  # Strict
      timeout_seconds: 300  # Longer recovery time

  logging:
    level: INFO
    format: json
    output: file

  metrics:
    enabled: true
    port: 9090
```

---

**See Also:**
- [M4 Safety Architecture](./M4_SAFETY_ARCHITECTURE.md)
- [M4 API Reference](./M4_API_REFERENCE.md)
- [M4 Deployment Guide](./M4_DEPLOYMENT_GUIDE.md)
