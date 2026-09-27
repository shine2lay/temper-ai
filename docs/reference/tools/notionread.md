[Home](../index.md) | **Tools** | [LLM Providers](../providers/index.md) | [Agent Types](../agents/index.md) | [Safety Policies](../policies/index.md) | [Topology Strategies](../strategies/index.md)

# `NotionRead` Tool

[Back to Tools](index.md)

> Read a Notion page or table row as text (title, row properties, body including tables), or a table's columns and rows. `what` is a target name from the Notion config, `origin` (the page this run started from), a page/table id, or a Notion URL.

They act as the "Temper" Notion connection (``NOTION_TOKEN``), so they see
only pages shared with it. Writes and comments go only to the configured
targets (``configs/notion/local/notion.yaml``), pages under a target page,
rows of a target table, and the page this run was started from. There is
no delete or archive.

A target is named ("crm"), or given as a page id or Notion URL. With the
tool option ``scope: answer`` (as repo_answer uses), search and read are
limited to the config's ``answer_from`` pages.

- **Modifies state:** No (read-only)

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `what` | string | Yes | Target name, origin, id or URL |
| `rows` | integer | No | For a table: at most this many rows (default 50) |
| `comments` | boolean | No | For a page: also list its comments (who, id, text) |

## Usage

Add `NotionRead` to an [LLM agent](../agents/llm.md)'s tools list:

```yaml
agent:
  name: my_agent
  type: llm
  tools: [NotionRead]
```

## Related

- [LLM Agent](../agents/llm.md) — agents that use tools
- [Safety Policies](../policies/index.md) — gate tool execution
