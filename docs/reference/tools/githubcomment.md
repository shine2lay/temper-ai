[Home](../index.md) | **Tools** | [LLM Providers](../providers/index.md) | [Agent Types](../agents/index.md) | [Safety Policies](../policies/index.md) | [Topology Strategies](../strategies/index.md)

# `GitHubComment` Tool

[Back to Tools](index.md)

> Post a comment in the thread of a GitHub issue or pull request, as temper's GitHub app. Markdown. Returns the comment's id and link.

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

- **Modifies state:** Yes

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `repo` | string | Yes | owner/name, e.g. shine2lay/temper-ai |
| `number` | integer | Yes | The issue or pull request number |
| `body` | string | Yes | The comment (markdown) |

## Usage

Add `GitHubComment` to an [LLM agent](../agents/llm.md)'s tools list:

```yaml
agent:
  name: my_agent
  type: llm
  tools: [GitHubComment]
```

## Related

- [LLM Agent](../agents/llm.md) — agents that use tools
- [Safety Policies](../policies/index.md) — gate tool execution
