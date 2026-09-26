[Home](../index.md) | **Tools** | [LLM Providers](../providers/index.md) | [Agent Types](../agents/index.md) | [Safety Policies](../policies/index.md) | [Topology Strategies](../strategies/index.md)

# `SlackReadThread` Tool

[Back to Tools](index.md)

> Read a Slack thread (its first message and the replies, oldest first) in a channel or DM the Slack config allows, or a thread temper opened for a run.

They act as the temper bot (``SLACK_BOT_TOKEN``), and only where the Slack
config's ``agents:`` list allows (``configs/local/slack.yaml``), so an agent
that reads text written by people cannot be talked into messaging anyone
else. A thread temper opened for a run may also be replied to and read.

``to`` names the place: a channel id (``C…``), ``#name`` from the list, or a
user id (``U…``), which means the bot's DM with that person.

- **Modifies state:** No (read-only)

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `to` | string | Yes | Where: a channel id (C…), #channel-name, or a user id (U…) for a DM |
| `thread_ts` | string | Yes | The ts of the thread's first message |
| `limit` | integer | No | At most this many messages (default 50, max 100) |

## Usage

Add `SlackReadThread` to an [LLM agent](../agents/llm.md)'s tools list:

```yaml
agent:
  name: my_agent
  type: llm
  tools: [SlackReadThread]
```

## Related

- [LLM Agent](../agents/llm.md) — agents that use tools
- [Safety Policies](../policies/index.md) — gate tool execution
