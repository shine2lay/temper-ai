# Task: m2-03-prompt-engine - Implement prompt template rendering engine

**Priority:** CRITICAL  
**Effort:** 1-2 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

Implement prompt template rendering with Jinja2-style variable substitution. Support loading templates from files or inline strings, variable injection, and tool schema formatting for function calling.

---

## Files to Create

- `src/agents/prompt_engine.py` - PromptEngine class
- `tests/test_agents/test_prompt_engine.py` - Tests

---

## Acceptance Criteria

- [x] - [ ] Render templates with {{variable}} syntax
- [x] - [ ] Load templates from files (configs/prompts/*.txt)
- [x] - [ ] Load inline templates from config
- [x] - [ ] Inject system variables (agent_name, tools_available, etc.)
- [x] - [ ] Format tool schemas for LLM function calling
- [x] - [ ] Support conditional blocks (if/else)
- [x] - [ ] Tests for all template features
- [x] - [ ] Coverage > 85%

---

## Implementation

```python
from jinja2 import Template
from typing import Dict, Any, List

class PromptEngine:
    """Renders prompts from templates."""
    
    def render(self, template: str, variables: Dict[str, Any]) -> str:
        """Render template with variables."""
        jinja_template = Template(template)
        return jinja_template.render(**variables)
    
    def render_with_tools(self, template: str, variables: Dict[str, Any], 
                         tool_schemas: List[Dict]) -> str:
        """Render with tool schemas injected."""
        variables["tools"] = self._format_tool_schemas(tool_schemas)
        return self.render(template, variables)
    
    def _format_tool_schemas(self, schemas: List[Dict]) -> str:
        """Format tool schemas for prompt."""
        # Format as JSON or human-readable list
        pass
```

---

## Success Metrics

- [x] - [ ] Template rendering works
- [x] - [ ] Variables injected correctly
- [x] - [ ] Tool schemas formatted properly
- [x] - [ ] Tests pass > 85%

---

## Dependencies

- **Blocked by:** m1-00-structure
- **Blocks:** m2-04-agent-runtime

