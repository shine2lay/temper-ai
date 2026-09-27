[Home](../index.md) | **Tools** | [LLM Providers](../providers/index.md) | [Agent Types](../agents/index.md) | [Safety Policies](../policies/index.md) | [Topology Strategies](../strategies/index.md)

# `NotionComment` Tool

[Back to Tools](index.md)

> Comment on a Notion page as temper: `origin` (the page this run started from), a page target name, or a page id/URL that is a target, under one, or a row of a table target.

They act as the "Temper" Notion connection (``NOTION_TOKEN``), so they see
only pages shared with it. Writes and comments go only to the configured
targets (``configs/notion/local/notion.yaml``), pages under a target page,
rows of a target table, and the page this run was started from. There is
no delete or archive.

A target is named ("crm"), or given as a page id or Notion URL. With the
tool option ``scope: answer`` (as repo_answer uses), search and read are
limited to the config's ``answer_from`` pages.

- **Modifies state:** Yes

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `where` | string | Yes | origin, target name, page id or URL |
| `text` | string | Yes | The comment |

## Usage

Add `NotionComment` to an [LLM agent](../agents/llm.md)'s tools list:

```yaml
agent:
  name: my_agent
  type: llm
  tools: [NotionComment]
```

## Related

- [LLM Agent](../agents/llm.md) — agents that use tools
- [Safety Policies](../policies/index.md) — gate tool execution
