[Home](../index.md) | **Tools** | [LLM Providers](../providers/index.md) | [Agent Types](../agents/index.md) | [Safety Policies](../policies/index.md) | [Topology Strategies](../strategies/index.md)

# `GitHubPullDiff` Tool

[Back to Tools](index.md)

> Read what a GitHub pull request changes: every file with its status and line counts, and the patch of each (the unified diff), up to max_chars in all.

Everything they post shows as the app (``<app>[bot]``), never as the owner:
they call GitHub with the app's installation token for the repository
(integrations.github.app), which only temper's own code can make. An agent
names the repository and the number; it never sees a key or a token. They
work on the repositories the app is installed on and nowhere else (GitHub
refuses the rest).

* GitHubThread   -- an issue or pull request and its whole conversation.
* GitHubPullDiff -- the files a pull request changes, with their patches.
* GitHubFiles    -- a file of the repository, or a directory's entries.
* GitHubComment  -- one comment in an issue's or pull request's thread.
* GitHubReview   -- a review of a pull request that only comments. It cannot
  approve, request changes or merge: the review's event is always COMMENT,
  whatever the agent asks.

Nothing here closes, labels, edits or merges anything.

- **Modifies state:** No (read-only)

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `repo` | string | Yes | owner/name, e.g. shine2lay/temper-ai |
| `number` | integer | Yes | The pull request number |
| `max_chars` | integer | No | Most patch text to return (default 60000) |

## Usage

Add `GitHubPullDiff` to an [LLM agent](../agents/llm.md)'s tools list:

```yaml
agent:
  name: my_agent
  type: llm
  tools: [GitHubPullDiff]
```

## Related

- [LLM Agent](../agents/llm.md) — agents that use tools
- [Safety Policies](../policies/index.md) — gate tool execution
