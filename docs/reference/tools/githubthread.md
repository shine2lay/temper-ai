[Home](../index.md) | **Tools** | [LLM Providers](../providers/index.md) | [Agent Types](../agents/index.md) | [Safety Policies](../policies/index.md) | [Topology Strategies](../strategies/index.md)

# `GitHubThread` Tool

[Back to Tools](index.md)

> Read a GitHub issue or pull request and its whole conversation: title, text, author, labels, state, and every comment (oldest first) with its author and id. For a pull request also its branches, draft state and reviews. Comments by the app itself are marked by their author, '<app>[bot]'.

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
| `number` | integer | Yes | The issue or pull request number |

## Usage

Add `GitHubThread` to an [LLM agent](../agents/llm.md)'s tools list:

```yaml
agent:
  name: my_agent
  type: llm
  tools: [GitHubThread]
```

## Related

- [LLM Agent](../agents/llm.md) — agents that use tools
- [Safety Policies](../policies/index.md) — gate tool execution
