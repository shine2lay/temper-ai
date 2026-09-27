[Home](../index.md) | **Tools** | [LLM Providers](../providers/index.md) | [Agent Types](../agents/index.md) | [Safety Policies](../policies/index.md) | [Topology Strategies](../strategies/index.md)

# `TelegramSend` Tool

[Back to Tools](index.md)

> Send a message in Telegram, as temper's bot, to a place the notify config lets agents use (by its name, e.g. "telegram"), or to "origin": the Telegram chat this run was started from, as a reply under the run's first message. Text may use *bold*, `code` and ``` blocks.

It may post only to a place the notify config names in its ``agents:``
list (configs/notify/local/notify.yaml), or to ``origin``: the Telegram
chat the run was started from, as a reply under the run's first message.
Chat ids are never accepted, so an agent that reads text written by people
cannot be talked into messaging anyone else.

- **Modifies state:** Yes

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `to` | string | Yes | A place name from the notify config's agents: list, or origin |
| `text` | string | Yes | The message |

## Usage

Add `TelegramSend` to an [LLM agent](../agents/llm.md)'s tools list:

```yaml
agent:
  name: my_agent
  type: llm
  tools: [TelegramSend]
```

## Related

- [LLM Agent](../agents/llm.md) — agents that use tools
- [Safety Policies](../policies/index.md) — gate tool execution
