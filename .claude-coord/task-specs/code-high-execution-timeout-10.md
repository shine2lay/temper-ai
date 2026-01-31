# Task: Add execution timeouts to prevent unbounded loops

## Summary

Implement total execution timeout, token budget limits, and API call count limits in StandardAgent to prevent unbounded loops and runaway costs. Current implementation has no timeout on agent.execute(), allowing infinite loops that exhaust resources and incur unlimited costs.

**Estimated Effort:** 4.0 hours
**Module:** agents

---

## Files to Create

_None_

---

## Files to Modify

- `src/agents/standard_agent.py` - Implement total execution timeout and cost budgets

---

## Acceptance Criteria

### Core Functionality
- [ ] Total execution timeout (5 minutes default)
- [ ] Token budget limits (per agent, per user)
- [ ] API call count limits
- [ ] Circuit breakers per agent

### Security Controls
- [ ] No infinite loops
- [ ] Resource consumption bounded
- [ ] Cost controls enforced

### Testing
- [ ] Test with loops that exceed timeout
- [ ] Test with high token consumption
- [ ] Test circuit breaker activation
- [ ] Test graceful timeout handling

---

## Implementation Details

```python
import signal
import time
from typing import Optional, Dict, Any
from contextlib import contextmanager


class ExecutionTimeout(Exception):
    """Raised when execution exceeds timeout"""
    pass


class BudgetExceeded(Exception):
    """Raised when budget limits exceeded"""
    pass


class TokenBudget:
    """Track and enforce token budgets"""

    def __init__(
        self,
        max_tokens: int = 100_000,
        max_cost: float = 10.0,  # dollars
        max_api_calls: int = 100
    ):
        self.max_tokens = max_tokens
        self.max_cost = max_cost
        self.max_api_calls = max_api_calls

        # Current usage
        self.tokens_used = 0
        self.cost_incurred = 0.0
        self.api_calls_made = 0

    def check_budget(self):
        """
        Check if budget limits exceeded.

        Raises:
            BudgetExceeded: If any limit exceeded
        """
        if self.tokens_used > self.max_tokens:
            raise BudgetExceeded(
                f"Token limit exceeded: {self.tokens_used} > {self.max_tokens}"
            )

        if self.cost_incurred > self.max_cost:
            raise BudgetExceeded(
                f"Cost limit exceeded: ${self.cost_incurred:.2f} > ${self.max_cost:.2f}"
            )

        if self.api_calls_made > self.max_api_calls:
            raise BudgetExceeded(
                f"API call limit exceeded: {self.api_calls_made} > {self.max_api_calls}"
            )

    def record_usage(self, tokens: int, cost: float):
        """Record API usage and check budget"""
        self.tokens_used += tokens
        self.cost_incurred += cost
        self.api_calls_made += 1
        self.check_budget()

    def get_usage(self) -> Dict[str, Any]:
        """Get current usage stats"""
        return {
            "tokens_used": self.tokens_used,
            "tokens_remaining": self.max_tokens - self.tokens_used,
            "cost_incurred": self.cost_incurred,
            "cost_remaining": self.max_cost - self.cost_incurred,
            "api_calls_made": self.api_calls_made,
            "api_calls_remaining": self.max_api_calls - self.api_calls_made,
        }


class CircuitBreaker:
    """Circuit breaker to prevent cascading failures"""

    def __init__(
        self,
        failure_threshold: int = 5,
        timeout: float = 60.0,
        expected_exception: type = Exception
    ):
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.expected_exception = expected_exception

        self.failure_count = 0
        self.last_failure_time: Optional[float] = None
        self.state = "closed"  # closed, open, half-open

    def call(self, func, *args, **kwargs):
        """
        Call function with circuit breaker protection.

        Raises:
            Exception: If circuit is open
        """
        if self.state == "open":
            # Check if timeout expired
            if time.time() - self.last_failure_time > self.timeout:
                self.state = "half-open"
            else:
                raise Exception(f"Circuit breaker open (too many failures)")

        try:
            result = func(*args, **kwargs)

            # Success - reset counter
            if self.state == "half-open":
                self.state = "closed"
            self.failure_count = 0

            return result

        except self.expected_exception as e:
            # Failure - increment counter
            self.failure_count += 1
            self.last_failure_time = time.time()

            if self.failure_count >= self.failure_threshold:
                self.state = "open"

            raise


@contextmanager
def execution_timeout(seconds: int):
    """
    Context manager for execution timeout.

    Args:
        seconds: Timeout in seconds

    Raises:
        ExecutionTimeout: If execution exceeds timeout
    """
    def timeout_handler(signum, frame):
        raise ExecutionTimeout(f"Execution exceeded {seconds} seconds")

    # Set alarm
    old_handler = signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(seconds)

    try:
        yield
    finally:
        # Reset alarm
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)


class StandardAgent:
    """Agent with execution timeouts and budget controls"""

    DEFAULT_TIMEOUT = 300  # 5 minutes

    def __init__(
        self,
        timeout: int = DEFAULT_TIMEOUT,
        token_budget: Optional[TokenBudget] = None,
        circuit_breaker: Optional[CircuitBreaker] = None
    ):
        self.timeout = timeout
        self.token_budget = token_budget or TokenBudget()
        self.circuit_breaker = circuit_breaker or CircuitBreaker()

    def execute(self, task: str, **kwargs) -> Dict[str, Any]:
        """
        Execute task with timeout and budget controls.

        Args:
            task: Task description
            **kwargs: Task parameters

        Returns:
            Execution result

        Raises:
            ExecutionTimeout: If execution exceeds timeout
            BudgetExceeded: If budget limits exceeded
        """
        start_time = time.time()

        try:
            with execution_timeout(self.timeout):
                result = self._execute_with_budget(task, **kwargs)

            execution_time = time.time() - start_time

            return {
                "result": result,
                "execution_time": execution_time,
                "budget_usage": self.token_budget.get_usage(),
            }

        except ExecutionTimeout:
            # Log timeout
            import logging
            logging.error(f"Task execution timeout after {self.timeout}s: {task}")
            raise

        except BudgetExceeded as e:
            # Log budget exceeded
            import logging
            logging.error(f"Budget exceeded: {e}")
            raise

    def _execute_with_budget(self, task: str, **kwargs) -> Any:
        """Execute task with budget tracking"""

        # Example execution loop
        for step in range(100):  # Max 100 steps
            # Check budget before each API call
            self.token_budget.check_budget()

            # Make API call (example)
            result = self.circuit_breaker.call(
                self._call_llm,
                prompt=f"Step {step}: {task}"
            )

            # Record usage
            tokens = result.get("usage", {}).get("total_tokens", 0)
            cost = self._calculate_cost(tokens)
            self.token_budget.record_usage(tokens, cost)

            # Check if task complete
            if self._is_complete(result):
                return result

        raise Exception("Task not complete after 100 steps")

    def _call_llm(self, prompt: str) -> Dict[str, Any]:
        """Make LLM API call"""
        # Implementation depends on provider
        pass

    def _calculate_cost(self, tokens: int) -> float:
        """Calculate cost from token usage"""
        # Example: $0.03 per 1K tokens
        return (tokens / 1000) * 0.03

    def _is_complete(self, result: Dict[str, Any]) -> bool:
        """Check if task is complete"""
        # Implementation depends on task
        pass
```

**Usage:**
```python
# Create agent with limits
agent = StandardAgent(
    timeout=300,  # 5 minutes
    token_budget=TokenBudget(
        max_tokens=50_000,
        max_cost=5.0,  # $5
        max_api_calls=50
    )
)

# Execute with automatic timeout and budget enforcement
try:
    result = agent.execute("Analyze this large dataset")
    print(f"Success: {result['budget_usage']}")
except ExecutionTimeout:
    print("Task took too long")
except BudgetExceeded as e:
    print(f"Budget exceeded: {e}")
```

---

## Test Strategy

1. **Timeout Test:**
   ```python
   def test_execution_timeout():
       agent = StandardAgent(timeout=2)  # 2 second timeout

       def infinite_loop_task(task):
           while True:
               time.sleep(0.1)

       agent._execute_with_budget = infinite_loop_task

       with pytest.raises(ExecutionTimeout):
           agent.execute("infinite loop")
   ```

2. **Token Budget Test:**
   ```python
   def test_token_budget():
       budget = TokenBudget(max_tokens=1000)
       agent = StandardAgent(token_budget=budget)

       # Simulate high token usage
       def high_token_task(task):
           for _ in range(20):
               budget.record_usage(tokens=100, cost=0.03)
           return {"status": "complete"}

       agent._execute_with_budget = high_token_task

       with pytest.raises(BudgetExceeded):
           agent.execute("high token task")
   ```

3. **Circuit Breaker Test:**
   ```python
   def test_circuit_breaker():
       breaker = CircuitBreaker(failure_threshold=3)

       def failing_function():
           raise Exception("API error")

       # Should fail 3 times then open circuit
       for _ in range(3):
           with pytest.raises(Exception):
               breaker.call(failing_function)

       # Circuit should now be open
       assert breaker.state == "open"

       # Next call should fail immediately
       with pytest.raises(Exception, match="Circuit breaker open"):
           breaker.call(failing_function)
   ```

4. **Graceful Timeout Test:**
   ```python
   def test_graceful_timeout():
       agent = StandardAgent(timeout=5)

       start = time.time()
       with pytest.raises(ExecutionTimeout):
           agent.execute("long task")
       elapsed = time.time() - start

       # Should timeout at ~5 seconds (not much later)
       assert 5.0 <= elapsed < 6.0
   ```

---

## Success Metrics

- [ ] All executions complete within timeout
- [ ] Budgets enforced (no overruns)
- [ ] No runaway costs (limited to budget)
- [ ] Circuit breaker prevents cascading failures

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** StandardAgent, execute, TokenBudget

---

## Design References

- `.claude-coord/reports/code-review-20260128-224245.md#7-unbounded-tool-execution`

---

## Notes

**High** - Prevents DoS and runaway costs. Issues without timeouts:
1. **Infinite Loops:** Agent loops forever → thread blocked → service unavailable
2. **Cost Overruns:** No budget limit → $10K API bill → financial damage
3. **Resource Exhaustion:** Long-running tasks → memory leak → OOM crash
4. **Cascading Failures:** One agent failure → retry storm → all agents fail

**Production Incidents:**
- Agent looped for 24 hours → $15K API bill
- Memory leak in long task → OOM crash → service down
- Retry storm → rate limits → all requests fail

**Prevention:**
- Always set execution timeout (default: 5 min)
- Always set token budget (per-user limits)
- Use circuit breaker for API calls
- Monitor and alert on budget usage
