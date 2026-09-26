# Slack — run temper from Slack, and hear back there

Temper runs a Slack bot. From Slack you can find a workflow by what it does,
start it, check on it and stop it, and answer its gates with a button. Temper
tells you when a gate is waiting, a run goes quiet, or a run fails or
finishes, with one thread per run. Nothing needs a public address: the bot
holds an outgoing connection to Slack (Socket Mode) from inside the temper
server.

```
Slack ◀──websocket (Socket Mode, outgoing)──▶ temper server ──▶ runs, gates
  /temper, @temper, buttons                   notices: gate · stuck · failed · finished
```

## Commands

`/temper` is exact and uses no model:

| Command | What it does |
|---|---|
| `/temper search <words>` | Workflows whose name, description or inputs match, with their inputs. Name matches first. |
| `/temper list` | Every workflow; ones with no description are flagged. |
| `/temper run <workflow> key=value …` | Starts a run and opens its thread in this conversation. Values are checked against the workflow's inputs first; quotes work (`msg="two words"`). |
| `/temper status [id]` | One run (any unique start of its id), or everything running and waiting. |
| `/temper stop <id>` | Stops a run, and says so in its thread. |
| `/temper help` | This list. |

**@temper in plain words** (in a channel it's in, or a DM with it): temper
searches the workflows and a small model (`slack_pick`, Sonnet, low effort,
one or two cents) picks one and fills in its inputs from what you wrote. You get
the proposal with **Start it** / **Cancel**, and nothing runs until you
click. When an input is missing it asks instead of guessing; reply in the
thread and it carries on from there.

The same search is `GET /api/workflows/search?q=…` and the MCP tool
`search_workflows`.

## Notices

| Kind | When | Buttons |
|---|---|---|
| gate | a gate is waiting for an answer | **Approve** / **Reject** (Reject stops the run) |
| stuck | a running run has written no event for `stuck_after` | **Stop run** |
| failed | a run failed; the notice quotes the failed step's own error | |
| finished | a run completed or was cancelled | |

Every notice about a run goes in one thread per destination. A run started
from Slack keeps its notices in the thread it was started in. When a gate is
answered anywhere (Slack, the dashboard, the API), its message loses its
buttons and says who answered. When a quiet run ends, its "quiet" notice loses
its Stop button. A run stopped from Slack says who stopped it. Runs that were
already going when Slack was switched on are left alone.

Where each kind goes is set in `configs/slack/local/slack.yaml` (git-ignored,
because it names people's Slack ids). When that file doesn't exist,
`configs/slack/slack.yaml` is used instead; it documents the format and sends
nothing. Changes are picked up without a restart:

```yaml
slack:
  dashboard_url: https://temper.example.com   # run links in messages
  stuck_after: 45m
  notify:
    gate: {dm: U0123456789}
    stuck: {dm: U0123456789}
    failed: {dm: U0123456789, channel: "#runs"}
    finished: {channel: "#runs"}
  workflows:              # per workflow; replaces the default for the kinds it names
    noisy_probe: off
    slack_pick: off       # the @temper picker itself
  agents:                 # where the agent tools may post and read
    - dm: U0123456789
```

A destination is `{channel: …, dm: …}`, and each part can be a list. A
channel is an id (`C…`) or `#name`; for a private channel, the bot must be a
member. `dm` is a user id (`U…`). `off` sends nothing.

## Agent tools

`SlackPost`, `SlackReply` and `SlackReadThread` post, reply in a thread and
read a thread, as the bot. An agent can reach only the places on the
`agents:` list, plus threads temper opened for a run, so text an agent reads
can't talk it into messaging anyone else.

## Setup

Once, by a Slack workspace admin:

1. **The app.** api.slack.com/apps → *Create New App* → *From a manifest*,
   pick the workspace, paste:

   ```yaml
   display_information:
     name: Temper
   features:
     bot_user:
       display_name: temper
       always_online: true
     slash_commands:
       - command: /temper
         description: Find, start, check and stop temper workflows
         usage_hint: search <words> | list | run <workflow> key=value | status [id] | stop <id>
         should_escape: false
   oauth_config:
     scopes:
       bot: [app_mentions:read, channels:history, channels:read, chat:write, chat:write.public,
             commands, groups:history, im:history, im:write, users:read]
   settings:
     event_subscriptions:
       bot_events: [app_mention, message.im]
     interactivity:
       is_enabled: true
     socket_mode_enabled: true
   ```

2. **Install** it to the workspace (*Install App*), and copy the **Bot User
   OAuth Token** (`xoxb-…`).
3. **App-level token.** *Basic Information* → *App-Level Tokens* →
   *Generate*, with the scope `connections:write`. Copy it (`xapp-…`).
4. Put both tokens in `.env` yourself, never in chat or git:

   ```
   SLACK_BOT_TOKEN=xoxb-...
   SLACK_APP_TOKEN=xapp-...
   ```

5. Write `configs/slack/local/slack.yaml` (see above), and restart the server
   and worker.
6. Check it:

   ```
   temper slack check [--server URL]
   ```

   The check confirms the bot token and the scopes it has, that a socket can
   be opened, and that the config loads, and shows where each kind of notice
   goes. It then asks the running server (the local one, or `--server URL`)
   whether its socket is connected (`GET /api/slack/status`), and lists
   workflows with no description, which search and @temper can only find by
   name.

## Rules

- **Anyone in the workspace can act.** Every start, stop, gate answer and
  pick is logged with the Slack user (table `slack_actions`; also in the
  server log).
- **Only one process may hold the socket**, because Slack hands each event to
  any one open connection. Run any other server on the same app with
  `TEMPER_SLACK=0`. Tests run with it off.
- A missing or bad token, or Slack being down, never stops the server from
  starting. The bot just stays off, and `/api/slack/status` says why.
- Slack starts, stops and answers gates. Nothing merges or deploys from Slack.
