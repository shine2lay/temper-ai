[Home](../index.md) | **Tools** | [LLM Providers](../providers/index.md) | [Agent Types](../agents/index.md) | [Safety Policies](../policies/index.md) | [Topology Strategies](../strategies/index.md)

# `NotionWrite` Tool

[Back to Tools](index.md)

> Write to Notion as temper: create a new page under a page, or append text to a page. `where` is a page target name, `origin`, or a page id/URL that is a target or under one. Text is Markdown-ish (# headings, - bullets, 1. numbers, - [ ] to-dos, > quotes, ``` code).

They act as the "Temper" Notion connection (``NOTION_TOKEN``), so they see
only pages shared with it. Writes and comments go only to the configured
targets (``configs/notion/local/notion.yaml``), pages under a target page,
rows of a target table, and the page this run was started from. There is
no delete or archive.

A target is named ("crm"), or given as a page id, a Notion URL or the page's
exact title. With the tool option ``scope: answer`` (as repo_answer uses), search and read are
limited to the config's ``answer_from`` pages.

- **Modifies state:** Yes

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `where` | string | Yes | Page target name, origin, id, URL or exact title |
| `mode` | `new_page` \| `append` | Yes | new_page: a child page titled `title`; append: add to the page |
| `title` | string | No | The new page's title (new_page) |
| `text` | string | Yes | The content |

## Usage

Add `NotionWrite` to an [LLM agent](../agents/llm.md)'s tools list:

```yaml
agent:
  name: my_agent
  type: llm
  tools: [NotionWrite]
```

## Related

- [LLM Agent](../agents/llm.md) — agents that use tools
- [Safety Policies](../policies/index.md) — gate tool execution
