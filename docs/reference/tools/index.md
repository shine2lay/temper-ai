[Home](../index.md) | **Tools** | [LLM Providers](../providers/index.md) | [Agent Types](../agents/index.md) | [Safety Policies](../policies/index.md) | [Topology Strategies](../strategies/index.md)

# Tools Reference

_Auto-generated from code. Do not edit manually._

Temper AI includes **17 built-in tools**. Agents reference tools by name in their [agent config](../agents/llm.md).

Tool execution is gated by [safety policies](../policies/index.md) — see [File Access](../policies/file_access.md) and [Forbidden Ops](../policies/forbidden_ops.md).

## Workspace

Every tool call runs in a **workspace**: the node's `workspace_path` input when it has one (typically a worktree an earlier node made, mapped in the workflow), else the run's (`--workspace` on the CLI, `workspace_path` on `POST /api/runs`). Path parameters must stay inside it, relative paths resolve against it, and `Bash` and `git` run in it. A node's workspace must itself lie inside the run's when the run has one — the value can come from another node's output, and a node cannot move the sandbox.

Tools that take a path (`Read`, `Write`, `Edit`, `Grep`, `Glob`) do not run with no workspace at all; the refusal says how to give the node one. `Bash` has no path to judge and is governed by its command allowlist either way, so a script node that *creates* the worktree can run before there is a workspace.

### Scratch directory

Each run has one other place its tools may use: a scratch directory, made the first time a path strays outside the workspace and named in that refusal (`Temporary files belong in this run's scratch directory '/tmp/temper-scratch-…'`). Nearly every stray is a node wanting somewhere for a temporary file — a commit message, a diff to review — and a node told only *no* has been seen put the file there through `Bash` instead. The nodes of one run share it; runs do not. It is removed when the run ends: anything a node wants kept belongs in the workspace.

### What the sandbox is

The path check is a guardrail against a node *straying*, not a boundary against a model that wants out: `Bash` can reach anything the container can, subject only to its allowlist. The boundary that holds against intent is the container the run executes in, plus that allowlist. Do not rest a policy decision on the workspace check alone.

Which container that is depends on the worker's `TEMPER_SPAWNER`. With `docker`, every run gets a container of its own: the worker's image, environment and read-only mounts, only the run's workspace writable (plus its git main repository when the workspace is a worktree), its own `/tmp`, and never the docker socket — see `temper_ai/spawner/docker_spawner.py`. With `subprocess` (the default) runs share the worker container, and `Bash` reaches whatever the worker can, including every other run's workspace.

| Name | Description |
|------|-------------|
| [`AddNode`](addnode.md) | Add a new node to the running workflow graph. Called during an agent's run to dispatch follow-up work conditionally (use when the decision can't be expressed as a declarative Jinja template over your output). The new node is queued and inserted into the DAG atomically after your agent completes, alongside any `dispatch:` block from your config. Safety caps (max_children_per_dispatch, max_dispatch_depth, etc.) apply to the merged batch. |
| [`Bash`](bash.md) | Execute a shell command and return its output. |
| [`Calculator`](calculator.md) | Evaluate a mathematical expression safely. Supports arithmetic, sqrt, sin, cos, tan, log, exp, abs, round, min, max, pi, e. |
| [`Delegate`](delegate.md) | Run one or more agents as sub-tasks. Each task specifies an agent name and inputs. Results are returned as JSON. Use this to delegate work to specialized agents and get their output back. |
| [`Edit`](edit.md) | Edit a file by exact string replacement. Pass several disjoint edits in one call — they are applied together or not at all. Each old_text must appear exactly once (include surrounding lines to make it unique) unless replace_all is set. Use Write to create a file or replace it wholesale. |
| [`Glob`](glob.md) | Find files by name pattern, e.g. '**/*.py' or 'src/**/test_*.ts'. Returns up to 200 paths (raise with limit), newest first. Skips anything the repo's .gitignore excludes, plus .git, node_modules, __pycache__, virtualenvs and build output. Use Grep to search file contents. |
| [`Grep`](grep.md) | Search file contents with a regular expression. Returns 'path:line: text' for up to 200 matches (raise with limit), then reports how many were omitted. Skips anything the repo's .gitignore excludes, plus .git, node_modules, __pycache__, virtualenvs and build output. Prefer this over running grep through Bash: that output is unbounded. |
| [`LinearMoveIssue`](linearmoveissue.md) | Move a Linear issue to another workflow state, e.g. 'In Progress' when you start work and 'In Review' when its pull request is open. Changes the issue's state and nothing else. |
| [`OpenPullRequest`](openpullrequest.md) | Push the branch checked out in a task's git worktree to GitHub and open a pull request for it into `base`. Returns the PR's URL. If a PR for the branch is already open, pushes the new commits and returns that PR. It never merges, never force-pushes, and refuses protected branches (main, master, staging, ...). |
| [`QueryRunState`](queryrunstate.md) | Return the state of nodes in the current workflow run. Returns a JSON list of nodes with their status ('running', 'completed', 'failed') and, for completed nodes, their output and structured_output. Use this to discover what upstream nodes have produced before making decisions — e.g. before dispatching new work based on earlier agents' results. Outputs are truncated by default; pass truncate_chars=0 to disable. |
| [`Read`](read.md) | Read the contents of a text file. Output is capped at 2000 lines or 50KB (whichever comes first); when a file is longer the result ends with the offset to continue from. Use offset/limit to read a specific range instead of the whole file. Prefer this over running `cat` through Bash: that returns the entire file and can exhaust the context in one call. |
| [`RemoveNode`](removenode.md) | Remove a still-pending node from the running workflow graph. Called during an agent's run when the agent determines a downstream node shouldn't execute (e.g., a placeholder that turned out unnecessary). The target is marked SKIPPED; any further-downstream nodes whose input_map refs it will cascade to skipped too. Only pending nodes can be removed — already-started nodes are unaffected. |
| [`WebFetch`](webfetch.md) | Fetch a web page and return its readable text — scripts, styles, nav and footers removed. Use this to read documentation, articles and API pages. JSON responses are returned formatted. Output is capped (default 30k characters) and says so when truncated. Use the http tool instead when you need the raw body, headers or a non-GET method. |
| [`WebSearch`](websearch.md) | Search the web. Returns titles, URLs, and snippets for the query. |
| [`Write`](write.md) | Write content to a file, creating parent directories as needed. Overwrites by default; set append=true to add to the end instead. To change part of an existing file use Edit, which does not require rewriting the whole file. |
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
