# Type Hints Guide for Meta-Autonomous Framework

## Overview

This guide covers type hints best practices, benefits, and recommendations for the Meta-Autonomous Framework codebase.

---

## Benefits of Type Hints

### 1. **Improved Code Readability**

Type hints serve as inline documentation:

```python
# Without type hints - unclear what's expected
def process_agent(config):
    return execute(config)

# With type hints - crystal clear
def process_agent(config: AgentConfig) -> ExecutionResult:
    return execute(config)
```

### 2. **Better IDE Support**

- **Autocomplete:** IDEs suggest correct attributes and methods
- **Error Detection:** Catch type errors before runtime
- **Refactoring:** Safer automated refactoring

### 3. **Early Error Detection**

```python
# mypy catches this before runtime
def calculate_cost(tokens: int) -> float:
    return tokens * 0.001

calculate_cost("100")  # Error: Expected int, got str
```

### 4. **Documentation**

Type hints replace verbose docstring parameter descriptions:

```python
# Before
def create_agent(name, model, tools):
    """
    Args:
        name (str): Agent name
        model (str): LLM model identifier
        tools (List[str]): Tool names
    """

# After (self-documenting)
def create_agent(
    name: str,
    model: str,
    tools: List[str]
) -> StandardAgent:
    """Create and return a configured agent."""
```

---

## Best Practices

### 1. **Always Type Function Signatures**

```python
from typing import List, Dict, Optional

# Good
def register_agent(
    agent_id: str,
    config: AgentConfig,
    tools: Optional[List[str]] = None
) -> RegistrationResult:
    pass

# Bad - no type information
def register_agent(agent_id, config, tools=None):
    pass
```

### 2. **Use Specific Types**

```python
from typing import Dict, List, Any

# Bad - too generic
def process_data(data: Dict) -> List:
    pass

# Good - specific structure
def process_data(
    data: Dict[str, Any]
) -> List[ProcessedItem]:
    pass

# Better - use dataclasses or Pydantic
@dataclass
class AgentMetrics:
    llm_calls: int
    tool_calls: int
    tokens: int

def process_data(data: AgentMetrics) -> List[ProcessedItem]:
    pass
```

### 3. **Use Optional for Nullable Values**

```python
from typing import Optional

# Good
def get_agent(agent_id: str) -> Optional[Agent]:
    """Returns None if agent not found."""
    return agents.get(agent_id)

# Bad - unclear if None is valid
def get_agent(agent_id: str) -> Agent:
    return agents.get(agent_id)  # Could be None!
```

### 4. **Type Complex Nested Structures**

```python
from typing import Dict, List, Union

# Complex configuration structure
WorkflowConfig = Dict[str, Union[
    str,
    List[str],
    Dict[str, Any]
]]

def load_workflow(config: WorkflowConfig) -> Workflow:
    pass
```

### 5. **Use TypedDict for Dictionary Schemas**

```python
from typing import TypedDict, List

class AgentConfigDict(TypedDict):
    name: str
    model: str
    tools: List[str]
    temperature: float

def create_from_dict(config: AgentConfigDict) -> Agent:
    # IDE knows exact keys and types
    return Agent(
        name=config["name"],
        model=config["model"]
    )
```

---

## Recommendations for This Codebase

### 1. **Use Pydantic for Configuration**

Already adopted in the framework:

```python
from pydantic import BaseModel, Field

class InferenceConfig(BaseModel):
    provider: str = Field(..., description="LLM provider")
    model: str = Field(..., description="Model identifier")
    temperature: float = Field(0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(2000, gt=0)

# Runtime validation + type checking
config = InferenceConfig(
    provider="ollama",
    model="llama3.2:3b"
)
```

### 2. **Protocol Classes for Interfaces**

Use `Protocol` for duck typing:

```python
from typing import Protocol

class ExecutionEngine(Protocol):
    """Interface that all execution engines must implement."""

    def compile(self, workflow: WorkflowConfig) -> CompiledWorkflow:
        ...

    def execute(
        self,
        workflow: CompiledWorkflow,
        inputs: Dict[str, Any]
    ) -> ExecutionResult:
        ...

# Any class matching this structure is valid
def run_workflow(
    engine: ExecutionEngine,  # Duck-typed interface
    workflow: WorkflowConfig
) -> ExecutionResult:
    compiled = engine.compile(workflow)
    return engine.execute(compiled, {})
```

### 3. **Generic Types for Reusability**

```python
from typing import TypeVar, Generic, List

T = TypeVar('T')

class Repository(Generic[T]):
    """Generic repository pattern."""

    def get(self, id: str) -> Optional[T]:
        pass

    def list(self) -> List[T]:
        pass

    def save(self, item: T) -> None:
        pass

# Type-safe repositories
agent_repo: Repository[Agent] = Repository[Agent]()
task_repo: Repository[Task] = Repository[Task]()

agent = agent_repo.get("agent-1")  # Type: Optional[Agent]
```

### 4. **Async Type Hints**

```python
from typing import AsyncIterator

async def stream_results(
    query: str
) -> AsyncIterator[LLMToken]:
    """Stream LLM tokens as they're generated."""
    async for token in llm_client.stream(query):
        yield token

# Usage
async for token in stream_results("Hello"):
    print(token)  # Type: LLMToken
```

---

## Security Considerations

### 1. **Prevent Type Confusion Attacks**

Type hints help prevent security vulnerabilities:

```python
# Without type hints - SQL injection risk
def get_user(user_id):
    query = f"SELECT * FROM users WHERE id = {user_id}"
    # Vulnerable if user_id is "1 OR 1=1"

# With type hints - enforces safety
def get_user(user_id: int) -> Optional[User]:
    # Type checker ensures user_id is int
    query = "SELECT * FROM users WHERE id = ?"
    return db.execute(query, (user_id,))
```

### 2. **Validate External Data**

```python
from pydantic import BaseModel, validator

class UserInput(BaseModel):
    email: str
    age: int

    @validator('email')
    def validate_email(cls, v):
        if '@' not in v:
            raise ValueError('Invalid email')
        return v

    @validator('age')
    def validate_age(cls, v):
        if v < 0 or v > 150:
            raise ValueError('Invalid age')
        return v

# Safe - validated and typed
def process_signup(data: UserInput) -> User:
    # data.email is guaranteed valid
    return create_user(data.email, data.age)
```

### 3. **Type-Safe Enums**

```python
from enum import Enum

class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"

def process_approval(status: ApprovalStatus) -> bool:
    # Only valid enum values accepted
    if status == ApprovalStatus.APPROVED:
        return True
    return False

# Type error - won't compile
process_approval("maybe")  # Error!

# Correct
process_approval(ApprovalStatus.APPROVED)  # OK
```

---

## Common Patterns in This Codebase

### Pattern 1: Builder Pattern with Types

```python
class AgentBuilder:
    """Type-safe agent builder."""

    def __init__(self) -> None:
        self._config: Dict[str, Any] = {}

    def with_model(self, model: str) -> 'AgentBuilder':
        self._config['model'] = model
        return self

    def with_tools(self, tools: List[str]) -> 'AgentBuilder':
        self._config['tools'] = tools
        return self

    def build(self) -> Agent:
        return Agent(**self._config)

# Type-safe fluent API
agent = (AgentBuilder()
    .with_model("llama3.2:3b")
    .with_tools(["calculator"])
    .build())
```

### Pattern 2: Result Types

```python
from typing import Union, Generic, TypeVar
from dataclasses import dataclass

T = TypeVar('T')
E = TypeVar('E')

@dataclass
class Ok(Generic[T]):
    value: T

@dataclass
class Err(Generic[E]):
    error: E

Result = Union[Ok[T], Err[E]]

def execute_tool(
    tool_name: str
) -> Result[ToolResult, ToolError]:
    try:
        result = registry.execute(tool_name)
        return Ok(result)
    except Exception as e:
        return Err(ToolError(str(e)))

# Type-safe error handling
result = execute_tool("calculator")
if isinstance(result, Ok):
    print(result.value)  # Type: ToolResult
else:
    print(result.error)  # Type: ToolError
```

### Pattern 3: Callback Types

```python
from typing import Callable

# Type-safe callbacks
ProgressCallback = Callable[[int, int], None]  # (current, total)
ErrorHandler = Callable[[Exception], bool]  # Return True to continue

def execute_workflow(
    workflow: Workflow,
    on_progress: Optional[ProgressCallback] = None,
    on_error: Optional[ErrorHandler] = None
) -> ExecutionResult:
    if on_progress:
        on_progress(0, 10)  # Type-checked
    # ...
```

---

## Type Checking Tools

### 1. **mypy (Recommended)**

```bash
# Install
pip install mypy

# Run type checker
mypy src/

# With strict mode
mypy --strict src/

# Check specific file
mypy src/agents/standard_agent.py
```

**Configuration** (`pyproject.toml`):
```toml
[tool.mypy]
python_version = "3.11"
warn_return_any = true
warn_unused_configs = true
disallow_untyped_defs = true
```

### 2. **pyright**

```bash
# Install
npm install -g pyright

# Run
pyright src/
```

### 3. **Pydantic for Runtime Validation**

```python
from pydantic import BaseModel, ValidationError

class Config(BaseModel):
    name: str
    count: int

try:
    config = Config(name="test", count="invalid")
except ValidationError as e:
    print(e.json())  # Detailed validation errors
```

---

## Migration Strategy

For existing untyped code:

### Step 1: Start with Function Signatures

```python
# Before
def process(data):
    return transform(data)

# Step 1: Add basic types
def process(data: dict) -> dict:
    return transform(data)

# Step 2: More specific
def process(data: Dict[str, Any]) -> ProcessedData:
    return transform(data)
```

### Step 2: Add Return Type Annotations

```python
# Prioritize public APIs
def public_api(input: str) -> Result:  # Type this first
    return _internal_helper(input)  # Type this later

def _internal_helper(input):  # OK to leave untyped initially
    pass
```

### Step 3: Gradually Increase Coverage

```bash
# Track progress
mypy --strict src/ 2>&1 | wc -l

# Goal: Reduce errors to zero over time
```

---

## Resources

- **Official Typing Docs:** https://docs.python.org/3/library/typing.html
- **mypy Documentation:** https://mypy.readthedocs.io/
- **PEP 484 (Type Hints):** https://peps.python.org/pep-0484/
- **Pydantic Docs:** https://docs.pydantic.dev/

---

**Last Updated:** 2026-02-01

**Note:** This consolidates the previous `type_hints_*.txt` files into a comprehensive guide.
