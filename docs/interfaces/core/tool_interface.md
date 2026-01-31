# Tool Interface

## Overview

Tools are executable capabilities that agents can use during execution. The tool interface defines how tools are discovered, registered, and executed with safety checks and observability.

## Interface Definition

```python
from abc import ABC, abstractmethod
from typing import Dict, Any


class BaseTool(ABC):
    """Abstract base class for all tools."""

    name: str                # Tool identifier
    description: str         # What the tool does
    version: str = "1.0"     # Tool version

    @abstractmethod
    def execute(self, **params) -> Dict[str, Any]:
        """Execute tool with parameters.

        Args:
            **params: Tool-specific parameters

        Returns:
            Dict with:
                - success: bool
                - result: Any (tool output)
                - error: Optional[str]
        """
        pass

    def validate_params(self, params: Dict[str, Any]) -> bool:
        """Validate input parameters.

        Args:
            params: Parameters to validate

        Returns:
            True if valid

        Raises:
            ValueError: If params invalid
        """
        return True

    def get_parameters_schema(self) -> Dict[str, Any]:
        """Get JSON schema for parameters.

        Returns:
            JSON schema dict for LLM function calling
        """
        return {}
```

## Built-in Tools

### Calculator

```python
class Calculator(BaseTool):
    """Safe arithmetic calculator."""

    name = "Calculator"
    description = "Performs basic arithmetic operations"
    version = "1.0"

    def execute(self, expression: str) -> Dict[str, Any]:
        """Evaluate math expression safely."""
        try:
            # Use ast.literal_eval or custom parser (not eval!)
            result = self._safe_eval(expression)
            return {
                "success": True,
                "result": result,
                "error": None
            }
        except Exception as e:
            return {
                "success": False,
                "result": None,
                "error": f"Calculation error: {str(e)}"
            }

    def _safe_eval(self, expression: str) -> float:
        """Safely evaluate arithmetic expression."""
        import ast
        import operator

        # Allowed operations
        ops = {
            ast.Add: operator.add,
            ast.Sub: operator.sub,
            ast.Mult: operator.mul,
            ast.Div: operator.truediv,
        }

        def eval_expr(node):
            if isinstance(node, ast.Num):
                return node.n
            elif isinstance(node, ast.BinOp):
                return ops[type(node.op)](
                    eval_expr(node.left),
                    eval_expr(node.right)
                )
            else:
                raise ValueError("Unsupported operation")

        tree = ast.parse(expression, mode='eval')
        return eval_expr(tree.body)

    def get_parameters_schema(self) -> Dict[str, Any]:
        """Get schema for LLM."""
        return {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "Math expression to evaluate (e.g., '2 + 2')"
                }
            },
            "required": ["expression"]
        }
```

### FileWriter

```python
class FileWriter(BaseTool):
    """Write content to files with safety checks."""

    name = "FileWriter"
    description = "Writes content to a file"
    version = "1.0"

    FORBIDDEN_PATHS = ["/etc", "/sys", "/proc", "/dev"]

    def execute(self, file_path: str, content: str) -> Dict[str, Any]:
        """Write content to file."""
        try:
            # Safety checks
            if not self._is_safe_path(file_path):
                return {
                    "success": False,
                    "result": None,
                    "error": f"Forbidden path: {file_path}"
                }

            # Create parent directories
            from pathlib import Path
            path = Path(file_path)
            path.parent.mkdir(parents=True, exist_ok=True)

            # Write file
            path.write_text(content)

            return {
                "success": True,
                "result": f"Written {len(content)} bytes to {file_path}",
                "error": None
            }
        except Exception as e:
            return {
                "success": False,
                "result": None,
                "error": str(e)
            }

    def _is_safe_path(self, path: str) -> bool:
        """Check if path is safe to write."""
        for forbidden in self.FORBIDDEN_PATHS:
            if path.startswith(forbidden):
                return False
        return True

    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to file to write"
                },
                "content": {
                    "type": "string",
                    "description": "Content to write to file"
                }
            },
            "required": ["file_path", "content"]
        }
```

### WebScraper

```python
class WebScraper(BaseTool):
    """Fetch and extract text from web pages."""

    name = "WebScraper"
    description = "Fetches content from a URL"
    version = "1.0"

    def __init__(self):
        self.session = httpx.Client(timeout=10)
        self.user_agent = "MetaAutonomousFramework/1.0"

    def execute(self, url: str) -> Dict[str, Any]:
        """Fetch and extract text from URL."""
        try:
            # Rate limiting check (basic)
            # TODO: Implement proper rate limiting

            # Fetch page
            response = self.session.get(
                url,
                headers={"User-Agent": self.user_agent}
            )
            response.raise_for_status()

            # Extract text
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(response.text, 'html.parser')

            # Remove scripts and styles
            for script in soup(["script", "style"]):
                script.decompose()

            text = soup.get_text(separator='\n', strip=True)

            return {
                "success": True,
                "result": text[:5000],  # Limit to 5KB
                "error": None
            }
        except Exception as e:
            return {
                "success": False,
                "result": None,
                "error": str(e)
            }

    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL to fetch content from"
                }
            },
            "required": ["url"]
        }
```

## Tool Registry

```python
class ToolRegistry:
    """Registry for managing tools."""

    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}

    def register(self, tool: BaseTool):
        """Register a tool."""
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[BaseTool]:
        """Get tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> List[str]:
        """List all registered tool names."""
        return list(self._tools.keys())

    def get_tool_schema(self, name: str) -> Dict[str, Any]:
        """Get tool schema for LLM.

        Returns schema in OpenAI function calling format.
        """
        tool = self.get(name)
        if not tool:
            raise ValueError(f"Tool not found: {name}")

        return {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.get_parameters_schema()
        }

    def auto_discover(self):
        """Auto-discover and register built-in tools."""
        from src.tools.calculator import Calculator
        from src.tools.file_writer import FileWriter
        from src.tools.web_scraper import WebScraper

        for tool_class in [Calculator, FileWriter, WebScraper]:
            self.register(tool_class())
```

## Tool Execution Flow

```
ToolRegistry.get(tool_name)
    │
    ├─ Lookup tool by name
    │
    ▼
BaseTool instance
    │
    ├─ validate_params(params)
    │      ├─ Check required fields
    │      ├─ Validate types
    │      └─ Check safety constraints
    │
    ├─ execute(**params)
    │      ├─ Run tool logic
    │      ├─ Apply safety checks
    │      ├─ Handle errors
    │      └─> Return result dict
    │
    └─> {success: bool, result: Any, error: str}
```

## Usage Example

```python
from src.tools.registry import ToolRegistry

# Initialize registry
registry = ToolRegistry()
registry.auto_discover()

# Get tool
calculator = registry.get("Calculator")

# Execute
result = calculator.execute(expression="2 + 2 * 3")

if result["success"]:
    print(f"Result: {result['result']}")  # 8
else:
    print(f"Error: {result['error']}")

# Get schema for LLM
schema = registry.get_tool_schema("Calculator")
print(schema)
# {
#   "name": "Calculator",
#   "description": "Performs basic arithmetic operations",
#   "parameters": {...}
# }
```

## Safety Considerations

### Path Traversal Prevention
```python
# FileWriter checks for forbidden paths
FORBIDDEN_PATHS = ["/etc", "/sys", "/proc", "/dev"]

def _is_safe_path(self, path: str) -> bool:
    for forbidden in self.FORBIDDEN_PATHS:
        if path.startswith(forbidden):
            return False
    return True
```

### Rate Limiting
```python
# WebScraper should implement rate limiting
class WebScraper:
    def __init__(self):
        self.last_request = {}
        self.min_delay = 1.0  # seconds

    def _check_rate_limit(self, domain: str):
        now = time.time()
        last = self.last_request.get(domain, 0)
        if now - last < self.min_delay:
            raise RateLimitError(f"Too fast for {domain}")
        self.last_request[domain] = now
```

### Input Validation
```python
# Calculator uses AST parsing (not eval!)
def _safe_eval(self, expression: str):
    import ast
    # Only allow specific operations
    # No function calls, no imports, no assignments
    tree = ast.parse(expression, mode='eval')
    return eval_expr(tree.body)
```

## Tool Schema Format (for LLMs)

Tools use OpenAI function calling format:

```json
{
  "name": "Calculator",
  "description": "Performs basic arithmetic operations",
  "parameters": {
    "type": "object",
    "properties": {
      "expression": {
        "type": "string",
        "description": "Math expression to evaluate"
      }
    },
    "required": ["expression"]
  }
}
```

This allows LLMs to generate valid tool calls:
```
I'll use Calculator to compute 2+2:
{"name": "Calculator", "params": {"expression": "2 + 2"}}
```

## Configuration

```yaml
# In agent config
tools:
  - Calculator
  - FileWriter
  - WebScraper
  # Or with overrides:
  - name: FileWriter
    max_file_size: 10000
    allowed_extensions: [".txt", ".md"]
```

## Future Tools (M3+)

- **GitHubTool** - Create issues, PRs, commits
- **DatabaseTool** - Query databases
- **EmailTool** - Send emails
- **SlackTool** - Post to Slack
- **JiraTool** - Manage Jira tickets
- **DockerTool** - Manage containers
- **ShellTool** - Execute shell commands (high safety requirements)

## Related Documentation

- [Agent Interface](./agent_interface.md)
- [Safety System](../architecture/safety_system.md) (M4)
