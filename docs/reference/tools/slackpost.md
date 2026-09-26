[Home](../index.md) | **Tools** | [LLM Providers](../providers/index.md) | [Agent Types](../agents/index.md) | [Safety Policies](../policies/index.md) | [Topology Strategies](../strategies/index.md)

# `SlackPost` Tool

[Back to Tools](index.md)

> Post a new message in Slack, as the temper bot, to a channel or person the Slack config allows. Returns the message's channel and ts (use them with SlackReply).

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
| `text` | string | Yes | The message (Slack mrkdwn) |

## Usage

Add `SlackPost` to an [LLM agent](../agents/llm.md)'s tools list:

```yaml
agent:
  name: my_agent
  type: llm
  tools: [SlackPost]
```

## Related

- [LLM Agent](../agents/llm.md) — agents that use tools
- [Safety Policies](../policies/index.md) — gate tool execution
