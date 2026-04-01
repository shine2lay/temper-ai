[Home](../index.md) | **Tools** | [LLM Providers](../providers/index.md) | [Agent Types](../agents/index.md) | [Safety Policies](../policies/index.md) | [Topology Strategies](../strategies/index.md)

# `http` Tool

[Back to Tools](index.md)

> Make HTTP requests to APIs. Returns status code and response body.

Provides a structured interface for GET/POST/PUT/DELETE requests.
Configurable timeout and URL allowlist for safety.

- **Modifies state:** No (read-only)

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `method` | `GET` \| `POST` \| `PUT` \| `DELETE` \| `PATCH` | Yes | HTTP method |
| `url` | string | Yes | Full URL to request |
| `headers` | object | No | Optional request headers |
| `body` | string | No | Optional request body (for POST/PUT/PATCH) |

## Config Options

These are set via the tool config dict, not YAML.

| Option | Type | Default |
|--------|------|---------|
| `timeout` | int | 30 |
| `allowed_domains` | list[str] | None | None |

## Usage

Add `http` to an [LLM agent](../agents/llm.md)'s tools list:

```yaml
agent:
  name: my_agent
  type: llm
  tools: [http]
```

## Related

- [LLM Agent](../agents/llm.md) — agents that use tools
- [Safety Policies](../policies/index.md) — gate tool execution
