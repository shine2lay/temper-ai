# Test Implementation Guide

## Overview

This guide provides best practices, patterns, and strategies for writing effective tests in the Temper AI.

## Test Organization

### Directory Structure

```
tests/
├── test_agents/              # Agent-specific tests
├── test_compiler/            # Workflow compiler tests
├── test_tools/               # Tool registry and execution tests
├── test_observability/       # Observability system tests
├── test_safety/              # Safety policy tests
├── test_benchmarks/          # Performance benchmarks
├── integration/              # Cross-component integration tests
├── conftest.py               # Shared fixtures
└── README.md
```

### Test File Naming

- **Unit tests:** `test_<module_name>.py`
- **Integration tests:** `test_<feature>_integration.py`
- **E2E tests:** `test_<workflow>_e2e.py`
- **Performance:** `test_<component>_performance.py`

### Test Method Naming

Use descriptive names that explain what is being tested:

```python
# Good
def test_tool_registry_raises_error_when_duplicate_tool_registered()
def test_circuit_breaker_opens_after_max_failures()
def test_parallel_agents_complete_faster_than_sequential()

# Bad
def test_registry()
def test_circuit_breaker()
def test_performance()
```

---

## Mock Strategy Decision Tree

### When to Mock

```
Is the dependency:
├─ External API/service? → **MOCK** (use responses, httpretty, or VCR)
├─ Database? → **USE TEST DB** (SQLite in-memory or fixture data)
├─ File system? → **USE TEMP DIRECTORY** (pytest tmp_path fixture)
├─ LLM provider? → **MOCK** (responses are non-deterministic)
├─ Time/random? → **MOCK** (use freezegun, pytest-mock)
├─ Internal business logic? → **USE REAL IMPLEMENTATION**
└─ Slow operation (>100ms)? → **MOCK** (for unit tests)
```

### Mocking Techniques

**1. Monkeypatch (pytest built-in):**
```python
def test_llm_client(monkeypatch):
    def mock_call(*args, **kwargs):
        return {"response": "mocked"}

    monkeypatch.setattr("temper_ai.llm.client.OpenAIClient.call", mock_call)
    # Test logic
```

**2. pytest-mock (unittest.mock wrapper):**
```python
def test_tool_execution(mocker):
    mock_tool = mocker.Mock()
    mock_tool.execute.return_value = ToolResult(success=True)

    registry.register(mock_tool)
    # Test logic
```

**3. responses (HTTP requests):**
```python
import responses

@responses.activate
def test_api_call():
    responses.add(
        responses.POST,
        "https://api.openai.com/v1/completions",
        json={"choices": [{"text": "Hello"}]},
        status=200
    )
    # Test logic
```

---

## Fixture Architecture

### Fixture Hierarchy

```python
# conftest.py - Root fixtures (shared across all tests)
@pytest.fixture(scope="session")
def test_db_engine():
    """SQLite in-memory database for all tests."""
    return create_engine("sqlite:///:memory:")

# Module-level fixtures (test_compiler/conftest.py)
@pytest.fixture
def workflow_config():
    """Sample workflow configuration."""
    return WorkflowConfig(name="test", stages=[...])

# Test-specific fixtures (in test file)
@pytest.fixture
def mock_agent():
    """Mock agent for this test file."""
    return MagicMock(spec=BaseAgent)
```

### Fixture Best Practices

**1. Use descriptive names:**
```python
# Good
@pytest.fixture
def authenticated_user_with_admin_role()

# Bad
@pytest.fixture
def user()
```

**2. Scope appropriately:**
```python
# Session scope (expensive setup, immutable)
@pytest.fixture(scope="session")
def test_database_schema()

# Function scope (default - clean state per test)
@pytest.fixture
def empty_task_queue()
```

**3. Use autouse sparingly:**
```python
# Only for invariant checks or universal setup
@pytest.fixture(autouse=True)
def verify_database_integrity():
    yield
    # Verify no corruption after each test
    assert check_database_integrity()
```

---

## Test Data Generation

### Strategy by Test Type

**Unit Tests:** Minimal, focused data
```python
def test_policy_composition():
    policy1 = SafetyPolicy(name="test1", priority=0)
    policy2 = SafetyPolicy(name="test2", priority=1)
    # Just enough data to test the logic
```

**Integration Tests:** Realistic data sets
```python
@pytest.fixture
def sample_workflow_config():
    return {
        "name": "user_registration",
        "stages": [
            {"name": "validate_email", "agent": "validator"},
            {"name": "create_account", "agent": "creator"},
            {"name": "send_welcome", "agent": "mailer"}
        ]
    }
```

**E2E Tests:** Production-like scenarios
```python
@pytest.fixture
def full_ecommerce_workflow():
    """Complete workflow with realistic user journey."""
    return load_fixture("ecommerce_checkout_flow.yaml")
```

### Data Factories

Use factories for complex object creation:

```python
class AgentFactory:
    @staticmethod
    def create(name="test_agent", **overrides):
        config = {
            "name": name,
            "inference": {"provider": "ollama", "model": "test"},
            "tools": []
        }
        config.update(overrides)
        return StandardAgent(config)

# Usage
def test_agent_execution():
    agent = AgentFactory.create(tools=["calculator"])
    # Test logic
```

---

## Test Patterns

### AAA Pattern (Arrange-Act-Assert)

```python
def test_circuit_breaker_opens_after_failures():
    # Arrange
    breaker = CircuitBreaker(max_failures=3)

    # Act
    for _ in range(3):
        breaker.record_failure()

    # Assert
    assert breaker.state == CircuitBreakerState.OPEN
```

### Parameterized Tests

```python
@pytest.mark.parametrize("failures,expected_state", [
    (0, CircuitBreakerState.CLOSED),
    (2, CircuitBreakerState.CLOSED),
    (3, CircuitBreakerState.OPEN),
    (5, CircuitBreakerState.OPEN),
])
def test_circuit_breaker_states(failures, expected_state):
    breaker = CircuitBreaker(max_failures=3)
    for _ in range(failures):
        breaker.record_failure()
    assert breaker.state == expected_state
```

### Error Testing

```python
def test_tool_registry_raises_on_duplicate():
    registry = ToolRegistry()
    tool = Calculator()
    registry.register(tool)

    # Test that duplicate registration raises error
    with pytest.raises(ToolRegistryError, match="already registered"):
        registry.register(tool)
```

---

## Anti-Patterns to Avoid

### 1. **Testing Implementation Details**
```python
# Bad - tests internal variable names
def test_policy_composer():
    composer = PolicyComposer()
    assert len(composer._policies) == 0  # Don't test private attributes

# Good - tests public behavior
def test_policy_composer_starts_empty():
    composer = PolicyComposer()
    assert composer.policy_count() == 0
```

### 2. **Test Interdependence**
```python
# Bad - test B depends on test A running first
class TestWorkflow:
    def test_a_create_workflow(self):
        self.workflow = create_workflow()  # Sets instance variable

    def test_b_execute_workflow(self):
        result = self.workflow.execute()  # Uses workflow from test_a

# Good - each test is independent
class TestWorkflow:
    @pytest.fixture
    def workflow(self):
        return create_workflow()

    def test_create_workflow(self, workflow):
        assert workflow is not None

    def test_execute_workflow(self, workflow):
        result = workflow.execute()
```

### 3. **Overly Complex Setup**
```python
# Bad - hard to understand what's being tested
def test_multi_agent_workflow():
    db = setup_database()
    agents = create_agents(db)
    workflow = create_workflow(agents)
    config = load_config("complex.yaml")
    executor = create_executor(workflow, config, db)
    # ... 20 more lines of setup

# Good - use fixtures and factories
def test_multi_agent_workflow(workflow_executor, sample_config):
    result = workflow_executor.run(sample_config)
    assert result.success
```

### 4. **Ignoring Test Failures**
```python
# Bad - silencing failures without investigation
@pytest.mark.skip(reason="flaky test")
def test_concurrency():
    # Test sometimes fails...
    pass

# Good - fix the root cause
def test_concurrency(db_with_wal_mode):
    # SQLite WAL mode eliminates race conditions
    # Test now deterministic
```

---

## Performance Testing

### Benchmarking with pytest-benchmark

```python
def test_parallel_agent_speedup(benchmark):
    config = ParallelWorkflowConfig(agents=3)

    result = benchmark(execute_workflow, config)

    # Assert performance
    assert result.duration_seconds < 25  # Target: 2.25x speedup
```

### Load Testing

```python
@pytest.mark.slow
def test_coordination_service_handles_100_concurrent_agents():
    agents = [create_agent(f"agent-{i}") for i in range(100)]

    with ThreadPoolExecutor(max_workers=100) as executor:
        futures = [executor.submit(agent.register) for agent in agents]
        results = [f.result() for f in futures]

    assert all(r.success for r in results)
```

---

## Edge Case Documentation

### Template for Task Specs

```markdown
## Edge Cases

### Input Edges
- Empty input: `validate_email("")` → ValueError
- Null input: `validate_email(None)` → TypeError
- Maximum length: `validate_email("a" * 1000)` → ValueError
- Special characters: `validate_email("test@🚀.com")` → depends on spec

### Error Edges
- Network timeout → retry with backoff
- Database locked → wait and retry (SQLite WAL mode)
- Invalid API key → fail fast with clear error

### Concurrency Edges
- Two agents claim same task → second fails with "already claimed"
- Agent crashes mid-task → orphaned lock cleaned up after TTL
- File edited by two agents → second agent blocked by file lock

### Security Edges
- Path traversal: `../../../etc/passwd` → blocked by file access policy
- Code injection: `eval()` in tool input → blocked by forbidden operations
- Secret in prompt → detected and redacted by secret detection policy
```

---

## Continuous Integration

### Pre-commit Hooks

```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: pytest-unit
        name: Run unit tests
        entry: pytest tests/ -m "not slow"
        language: system
        pass_filenames: false

      - id: check-test-coverage
        name: Check test coverage
        entry: pytest --cov=src --cov-fail-under=80
        language: system
        pass_filenames: false
```

### CI Pipeline

```yaml
# .github/workflows/test.yml
name: Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Run tests
        run: |
          pytest tests/ -v --cov=src --cov-report=xml
      - name: Upload coverage
        uses: codecov/codecov-action@v2
```

---

## Test Maintenance

### Regular Reviews

- **Monthly:** Review and update flaky tests
- **Per milestone:** Add tests for new features
- **Before release:** Run full test suite including slow/benchmark tests

### Test Metrics to Track

- **Coverage:** Maintain > 80% line coverage
- **Speed:** Unit tests < 5s, integration tests < 30s
- **Flakiness:** < 1% failure rate on passing builds

---

## Resources

- **pytest Documentation:** https://docs.pytest.org/
- **Testing Best Practices:** https://testautomationu.applitools.com/
- **Framework Test Examples:** `tests/` directory
- **Mock Strategy:** See `tests/conftest.py` for patterns

---

**Last Updated:** 2026-02-01
**Maintained by:** Temper AI Team
