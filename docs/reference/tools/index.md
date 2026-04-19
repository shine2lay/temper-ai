[Home](../index.md) | **Tools** | [LLM Providers](../providers/index.md) | [Agent Types](../agents/index.md) | [Safety Policies](../policies/index.md) | [Topology Strategies](../strategies/index.md)

# Tools Reference

_Auto-generated from code. Do not edit manually._

Temper AI includes **12 built-in tools**. Agents reference tools by name in their [agent config](../agents/llm.md).

Tool execution is gated by [safety policies](../policies/index.md) — see [File Access](../policies/file_access.md) and [Forbidden Ops](../policies/forbidden_ops.md).

| Name | Description |
|------|-------------|
| [`AddNode`](addnode.md) | Add a new node to the running workflow graph. Called during an agent's run to dispatch follow-up work conditionally (use when the decision can't be expressed as a declarative Jinja template over your output). The new node is queued and inserted into the DAG atomically after your agent completes, alongside any `dispatch:` block from your config. Safety caps (max_children_per_dispatch, max_dispatch_depth, etc.) apply to the merged batch. |
| [`Bash`](bash.md) | Execute a shell command and return its output. |
| [`Calculator`](calculator.md) | Evaluate a mathematical expression safely. Supports arithmetic, sqrt, sin, cos, tan, log, exp, abs, round, min, max, pi, e. |
| [`Delegate`](delegate.md) | Run one or more agents as sub-tasks. Each task specifies an agent name and inputs. Results are returned as JSON. Use this to delegate work to specialized agents and get their output back. |
| [`FileAppend`](fileappend.md) | Append text to the end of a file. The file must already exist. Use this instead of FileWriter when you want to add a new section to an existing file without rewriting it. |
| [`FileEdit`](fileedit.md) | Replace exact text in an existing file. Provide the exact text to find (old_text) and what to replace it with (new_text). The old_text must match exactly once in the file, including whitespace and indentation. Include a few surrounding lines in old_text to make it unique. Use replace_all=true to replace all occurrences (e.g., renaming a variable). |
| [`FileWriter`](filewriter.md) | Write content to a file. Creates parent directories if needed. |
| [`QueryRunState`](queryrunstate.md) | Return the state of nodes in the current workflow run. Returns a JSON list of nodes with their status ('running', 'completed', 'failed') and, for completed nodes, their output and structured_output. Use this to discover what upstream nodes have produced before making decisions — e.g. before dispatching new work based on earlier agents' results. Outputs are truncated by default; pass truncate_chars=0 to disable. |
| [`RemoveNode`](removenode.md) | Remove a still-pending node from the running workflow graph. Called during an agent's run when the agent determines a downstream node shouldn't execute (e.g., a placeholder that turned out unnecessary). The target is marked SKIPPED; any further-downstream nodes whose input_map refs it will cascade to skipped too. Only pending nodes can be removed — already-started nodes are unaffected. |
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
