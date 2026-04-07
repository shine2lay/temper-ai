[Home](../index.md) | **Tools** | [LLM Providers](../providers/index.md) | [Agent Types](../agents/index.md) | [Safety Policies](../policies/index.md) | [Topology Strategies](../strategies/index.md)

# Tools Reference

_Auto-generated from code. Do not edit manually._

Temper AI includes **9 built-in tools**. Agents reference tools by name in their [agent config](../agents/llm.md).

Tool execution is gated by [safety policies](../policies/index.md) — see [File Access](../policies/file_access.md) and [Forbidden Ops](../policies/forbidden_ops.md).

| Name | Description |
|------|-------------|
| [`Bash`](bash.md) | Execute a shell command and return its output. |
| [`Calculator`](calculator.md) | Evaluate a mathematical expression safely. Supports arithmetic, sqrt, sin, cos, tan, log, exp, abs, round, min, max, pi, e. |
| [`Delegate`](delegate.md) | Run one or more agents as sub-tasks. Each task specifies an agent name and inputs. Results are returned as JSON. Use this to delegate work to specialized agents and get their output back. |
| [`FileAppend`](fileappend.md) | Append text to the end of a file. The file must already exist. Use this instead of FileWriter when you want to add a new section to an existing file without rewriting it. |
| [`FileEdit`](fileedit.md) | Replace exact text in an existing file. Provide the exact text to find (old_text) and what to replace it with (new_text). The old_text must match exactly once in the file, including whitespace and indentation. Include a few surrounding lines in old_text to make it unique. Use replace_all=true to replace all occurrences (e.g., renaming a variable). |
| [`FileWriter`](filewriter.md) | Write content to a file. Creates parent directories if needed. |
| [`WebSearch`](websearch.md) | Search the web. Returns titles, URLs, and snippets for the query. |
| [`git`](git.md) | Run git commands in the workspace (status, diff, add, commit, push, etc.) |
| [`http`](http.md) | Make HTTP requests to APIs. Returns status code and response body. |

## Extending

Implement `BaseTool` and register it. Any [LLM agent](../agents/llm.md) can then list it in `tools:`.

```python
from temper_ai.tools import register_tool, BaseTool, ToolResult

class MyTool(BaseTool):
    name = "MyTool"
    description = "What this tool does"
    parameters = {  # JSON Schema
        "type": "object",
        "properties": { ... },
        "required": [ ... ],
    }

    def execute(self, **params) -> ToolResult:
        return ToolResult(success=True, result="done")

register_tool("MyTool", MyTool)
```
