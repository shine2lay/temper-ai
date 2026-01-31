# Task: m1-06-basic-tools - Implement basic tools (WebScraper, FileWriter, Calculator)

**Priority:** NORMAL
**Effort:** 2-3 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

Implement three basic tools for testing: Calculator (simple math), FileWriter (write text files), and WebScraper (fetch web pages). Each tool should follow the tool interface pattern and include safety checks.

---

## Files to Create

- `src/tools/base.py` - BaseTool abstract class
- `src/tools/calculator.py` - Calculator tool implementation
- `src/tools/file_writer.py` - FileWriter tool implementation
- `src/tools/web_scraper.py` - WebScraper tool implementation
- `tests/test_tools/test_calculator.py` - Calculator tests
- `tests/test_tools/test_file_writer.py` - FileWriter tests
- `tests/test_tools/test_web_scraper.py` - WebScraper tests

---

## Acceptance Criteria

### Base Tool Interface
- [ ] BaseTool abstract class with execute() method
- [ ] Tool metadata (name, description, version)
- [ ] Input/output type definitions
- [ ] Safety check hooks
- [ ] Error handling

### Calculator Tool
- [ ] Evaluate basic math expressions (add, subtract, multiply, divide)
- [ ] Safe evaluation (no eval(), use ast.literal_eval or similar)
- [ ] Error handling for division by zero, invalid expressions
- [ ] Tests cover all operations

### FileWriter Tool
- [ ] Write content to file path
- [ ] Safety: Prevent writing to dangerous paths (/etc, /sys, etc.)
- [ ] Safety: Require approval for overwriting existing files
- [ ] Create parent directories if needed
- [ ] Tests cover valid/invalid paths

### WebScraper Tool
- [ ] Fetch URL content with requests/httpx
- [ ] Extract text from HTML (BeautifulSoup)
- [ ] Rate limiting (max N requests per minute)
- [ ] Timeout handling
- [ ] User-agent header
- [ ] Tests with mock HTTP responses

### Testing
- [ ] Unit tests for each tool
- [ ] Test success cases
- [ ] Test error cases
- [ ] Test safety checks
- [ ] Coverage > 85%

---

## Implementation Snippet

```python
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional


class BaseTool(ABC):
    """Base class for all tools."""

    name: str
    description: str
    version: str = "1.0"

    @abstractmethod
    def execute(self, **params) -> Dict[str, Any]:
        """Execute tool with given parameters.

        Returns:
            Dict with "success": bool, "result": Any, "error": Optional[str]
        """
        pass

    def validate_params(self, params: Dict[str, Any]) -> bool:
        """Validate input parameters."""
        return True


class Calculator(BaseTool):
    """Simple calculator tool."""

    name = "Calculator"
    description = "Performs basic arithmetic operations"

    def execute(self, expression: str) -> Dict[str, Any]:
        """Evaluate math expression safely."""
        try:
            # Use ast.literal_eval or safer alternative
            result = self._safe_eval(expression)
            return {"success": True, "result": result, "error": None}
        except Exception as e:
            return {"success": False, "result": None, "error": str(e)}

    def _safe_eval(self, expression: str) -> float:
        """Safely evaluate math expression."""
        # Implementation here (use ast module, not eval())
        pass
```

---

## Success Metrics

- [ ] All 3 tools implemented and working
- [ ] Safety checks prevent dangerous operations
- [ ] Tests pass > 85% coverage
- [ ] Tools can be used in integration test

---

## Dependencies

- **Blocked by:** m1-00-structure
- **Blocks:** m1-07-integration

---

## Design References

- TECHNICAL_SPECIFICATION.md Section 4: Tool Configuration Schema

---

## Notes

- Keep tools simple for Milestone 1
- More complex tools in later milestones (GitHub, Database, etc.)
- Safety is critical - prevent path traversal, code injection, etc.
