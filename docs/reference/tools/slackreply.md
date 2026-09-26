[Home](../index.md) | **Tools** | [LLM Providers](../providers/index.md) | [Agent Types](../agents/index.md) | [Safety Policies](../policies/index.md) | [Topology Strategies](../strategies/index.md)

# `SlackReply` Tool

[Back to Tools](index.md)

> Reply in a Slack thread, as the temper bot. The thread is the ts of its first message, in a channel or DM the Slack config allows, or a thread temper opened for a run.

They act as the temper bot (``SLACK_BOT_TOKEN``), and only where the Slack
config's ``agents:`` list allows (``configs/local/slack.yaml``), so an agent
that reads text written by people cannot be talked into messaging anyone
else. A thread temper opened for a run may also be replied to and read.

``to`` names the place: a channel id (``C…``), ``#name`` from the list, or a
user id (``U…``), which means the bot's DM with that person.

- **Modifies state:** Yes

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `to` | string | Yes | Where: a channel id (C…), #channel-name, or a user id (U…) for a DM |
| `thread_ts` | string | Yes | The ts of the thread's first message |
| `text` | string | Yes | The reply (Slack mrkdwn) |

## Usage

Add `SlackReply` to an [LLM agent](../agents/llm.md)'s tools list:

```yaml
agent:
  name: my_agent
  type: llm
  tools: [SlackReply]
```

## Related

- [LLM Agent](../agents/llm.md) — agents that use tools
- [Safety Policies](../policies/index.md) — gate tool execution
