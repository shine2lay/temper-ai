[Home](../index.md) | **Tools** | [LLM Providers](../providers/index.md) | [Agent Types](../agents/index.md) | [Safety Policies](../policies/index.md) | [Topology Strategies](../strategies/index.md)

# `NotionUpsert` Tool

[Back to Tools](index.md)

> Create or update a row in a Notion table target (e.g. a CRM). The row is found by the target's key field: if a row has that key it is updated, otherwise a new row is created, so running again never makes duplicates. `values` maps field names (from the config) or column names to values; omit a field to leave it as is. With `row` (`origin`, or a row's id/URL in that table) that row is updated instead and no key is needed: e.g. move the Status of the task this run was started from.

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
| `table` | string | Yes | A table target name from the Notion config |
| `values` | object | Yes | field or column name -> value; must include the key |
| `row` | string | No | Optional: origin, or a row id/URL of this table, to update |
| `text` | string | No | Optional text to add to the row's page body |

## Usage

Add `NotionUpsert` to an [LLM agent](../agents/llm.md)'s tools list:

```yaml
agent:
  name: my_agent
  type: llm
  tools: [NotionUpsert]
```

## Related

- [LLM Agent](../agents/llm.md) — agents that use tools
- [Safety Policies](../policies/index.md) — gate tool execution
