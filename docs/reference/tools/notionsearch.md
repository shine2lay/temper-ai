[Home](../index.md) | **Tools** | [LLM Providers](../providers/index.md) | [Agent Types](../agents/index.md) | [Safety Policies](../policies/index.md) | [Topology Strategies](../strategies/index.md)

# `NotionSearch` Tool

[Back to Tools](index.md)

> Search Notion pages and tables shared with temper by title. Returns each match's title, kind (page or table), id and url; read one with NotionRead.

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
| `query` | string | Yes | Words in the title (empty lists recent pages) |
| `kind` | `any` \| `page` \| `table` | No | Only pages or tables |
| `limit` | integer | No | At most this many (default 10, max 50) |

## Usage

Add `NotionSearch` to an [LLM agent](../agents/llm.md)'s tools list:

```yaml
agent:
  name: my_agent
  type: llm
  tools: [NotionSearch]
```

## Related

- [LLM Agent](../agents/llm.md) — agents that use tools
- [Safety Policies](../policies/index.md) — gate tool execution
