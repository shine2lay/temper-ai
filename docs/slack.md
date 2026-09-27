# Slack — run temper from Slack, and hear back there

Temper runs a Slack bot. From Slack you can find a workflow by what it does,
start it, check on it and stop it, and answer its gates' questions in a form.
Temper tells you when a gate is waiting, a run goes quiet, or a run fails or
finishes, with one thread per run. (It has a [Telegram bot](telegram.md)
too; where each run's messages go is set once for both, in
[notify.md](notify.md).) Nothing needs a public address: the bot
holds an outgoing connection to Slack (Socket Mode) from inside the temper
server.

```
Slack ◀──websocket (Socket Mode, outgoing)──▶ temper server ──▶ runs, gates
  /temper, @temper, buttons                   notices: gate · stuck · failed · finished
```

## Commands

`/temper` is exact: no model works out what you meant (only `ask` uses one,
to read the code):

| Command | What it does |
|---|---|
| `/temper ask <question>` | Answers a question about the code of rollcall, roamee or temper-ai, in the channel for everyone there. See below. |
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

## Questions about the code

`/temper ask can roamee export a trip?`, or the same question to @temper in
plain words (the pick tells a question from a request to run something, and
answers a question straight away, with no button). The `repo_answer`
workflow does the reading:

1. `repos` (script) keeps a read-only shallow copy of each repository at
   GitHub's latest: rollcall `master`, roamee `staging`, temper-ai
   `master`, fetched at most every 10 minutes, under
   `/app/workspaces/readonly/`. The list is in
   `configs/agents/repo_copies.yaml`.
2. `answer` (Sonnet, medium effort, Read/Grep/Glob only, 20 steps, 5
   minutes) reads each repo's capability notes (`.temper/`) first, then the
   code when they don't settle it, and treats the code as the truth when a
   doc disagrees. It ends with the commits it read (`Read: roamee staging
   abc1234`).

An answer takes 10 s to a minute or two and costs about 3–25 cents (plus 1–2
cents for the pick with @temper). It never changes anything, and anyone in the
workspace may ask about any of the three repos. Questions about temper's own
runs go to `/temper status` instead. `repo_answer` runs post no notices; the
answer is the message.

## Notices

| Kind | When | Buttons |
|---|---|---|
| question | a gate is waiting for an answer | **Answer** (a form with its questions), **Approve** / **Reject** (Reject stops the run) |
| stuck | a running run has written no event for `stuck_after` | **Stop run** |
| failed | a run failed; the notice quotes the failed step's own error | |
| finished | a run completed or was cancelled | |

**Answer** opens a form with every question the step asked: a choice is a
list to pick one from, a pick-any question has checkboxes, and each question
has a box for a typed answer, plus one for anything else. Submitting it
continues the run, and the next step gets the answers. **Approve** continues
without answers.

Every notice about a run goes in one thread per place. A run started from
Slack keeps its notices in the thread it was started in. When a gate is
answered anywhere (Slack, Telegram, the dashboard, the API), its message
loses its buttons and says who answered and where. When a quiet run ends, its
"quiet" notice loses its Stop button. A run stopped from Slack says who
stopped it. Runs that were already going when notices were switched on are
left alone.

Where each kind goes is set in the notify file,
`configs/notify/local/notify.yaml`, shared with Telegram: see
[notify.md](notify.md). By default a run's notices go back where it was
started, and a run with no origin (the dashboard, schedules, the API) goes to
the file's `fallback`, e.g. `{slack: {dm: U0123456789}}`. A workflow can
choose its own with a `notify:` block.

The Slack file, `configs/slack/local/slack.yaml` (git-ignored, because it
names people's Slack ids), keeps the rest; its old `notify:` and
`workflows:` routes are no longer used. Changes are picked up without a
restart:

```yaml
slack:
  dashboard_url: https://temper.example.com   # run links in @temper's answers
  agents:                 # where the agent tools may post and read
    - dm: U0123456789
```

A destination is `{channel: …, dm: …}`, and each part can be a list. A
channel is an id (`C…`) or `#name`; for a private channel, the bot must be a
member. `dm` is a user id (`U…`).

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

5. Write `configs/slack/local/slack.yaml` (see above) and the Slack places in
   `configs/notify/local/notify.yaml` ([notify.md](notify.md)), and restart
   the server and worker.
6. Check it:

   ```
   temper slack check [--server URL]
   ```

   The check confirms the bot token and the scopes it has, that a socket can
   be opened, and that the config loads, and shows where each kind of notice
   goes (and that every workflow's own `notify:` names places that exist). It then asks the running server (the local one, or `--server URL`)
   whether its socket is connected (`GET /api/slack/status`), and lists
   workflows with no description, which search and @temper can only find by
   name.

## Testing without the browser

Slack blocks automated browsers, so temper's Slack flows are tested
through a private **test entry** on temper's server instead. It takes fake
Slack events (a `/temper` command, a button click, a form being sent, an
@temper message) and handles them exactly like real ones. What temper posts
lands in Slack for real, in the test channel (#temper-qa), and the checks
read it back through Slack's API.

```
temper slack e2e                  # the whole check set, pass/fail with times and cost
temper slack fake command ask what does gate_smoke do? --wait
```

Run them where the bot token and the entry's secret are set, which is the
server container:

```
docker exec -w /app temper-ai-server-1 /app/.venv/bin/temper slack e2e
```

### The check set

`temper slack e2e` runs these in the test channel, one after another, and
prints PASS or FAIL for each, with its time and cost. It exits 1 if any
fails. `--only form,stop` runs some of them.

| Check | What it does, and what must happen |
|---|---|
| `ask` | `/temper ask …`: the answer is posted in the channel for everyone. |
| `mention` | "@temper what does … do?": the answer appears in its thread. |
| `form` | `/temper run notify_probe`. Its question comes with Answer, Approve and Reject. A click on Answer builds the form, and Slack accepts its blocks. Sending the form answers the question, the run finishes with those answers, and the question says who approved it. |
| `approve` | A second notify_probe: Approve moves it on, and it finishes. |
| `reject` | A third: Reject stops it, and the notice says who rejected it. |
| `stop` | A fourth, waiting at its question: the check posts a "quiet run" notice in its thread, and a click on its Stop button stops the run. |

`ask` and `mention` cost what two answers cost (see
[Questions about the code](#questions-about-the-code)). notify_probe uses
no model, so the four runs cost nothing. The whole set takes a few minutes.

### One fake at a time

`temper slack fake` sends one fake event. With `--wait` it prints what came
of it: temper's replies, the forms it built, its event in the inbox, and the
messages in its thread.

```
temper slack fake command run notify_probe --wait
temper slack fake mention what does gate_smoke do? --wait
temper slack fake click <message ts> approve --thread <thread ts> --wait
temper slack fake click <message ts> answer --thread <thread ts> --wait
temper slack fake submit <the Answer click's fake id> --pick q0=1 --wait
```

A click needs the ts of a message temper posted in the test channel (and of
its thread, when it is a reply). The click is built from that message as
Slack's API returns it, so it carries the button temper really posted.
`submit` sends the form an Answer click built, filled in by `--pick`
(`q0=1` picks option 1 of question 0, `q1=0,2` picks two, `q2c=text`
types an answer, `response=text` fills the last box). Without `--pick`,
it fills it in the way the check set does.

### How a fake is handled

A fake goes where a real event goes. It is saved in the
[event inbox](reference/architecture.md#events-from-outside-the-inbox),
marked as a test (its delivery is `test:<id>`, and
`temper events list --source slack` shows it), and it can be replayed like
any other event. Then it goes to the same handler the Slack socket uses.
Only what a fake can't have is swapped:

- **Who.** A fake always acts as the owner (`test_door.user`, else the first
  `dm` under `agents:`), whatever it says. Nothing is ever posted as the
  owner: a fake @temper message is hung on a message the bot posts first.
- **The reply link.** Slack's `response_url` exists only for a real command
  or click. A fake's link points back at temper's server, which keeps what
  temper answers there for an hour. An answer meant for everyone is posted
  in the channel by the bot, as Slack itself would.
- **The form.** A form opens only from a real click, whose trigger lasts 3
  seconds. A fake click's form is still sent to Slack, which checks the
  form's blocks before the trigger, so "invalid trigger" means Slack
  accepted the blocks. The form is kept, so a fake submission can send it.

**What it can't show:** that the form really pops up in Slack. That needs a
real click. Everything before it (which form, with valid blocks) and after
it (sending it, the run carrying on) is checked.

The fakes are built from templates in
`temper_ai/integrations/slack/templates/`, with no tokens in them. The
@temper one is shaped on real events from the inbox. The command, click and
form ones follow Slack's documented shape, because no real one had reached
the inbox yet when they were written.

### Turning it on and off

The entry takes nothing until it has a secret. Set it once in
`~/temper-ai/.env`, then recreate the server:

```
TEMPER_SLACK_TEST_TOKEN=<a long random string>
```

Its routes are under `/api/test/slack` (`GET` says whether it is on, `POST`
takes a fake, `GET /api/test/slack/fakes/<id>` shows what came of one).
Every call needs the secret, as `X-Temper-Test-Token`, or temper's API
token when one is set. The one exception is a fake's reply link, which
temper's server calls itself from inside, as it calls Slack's (the link only
works for an hour). The entry is never on the public hook address. It only
takes fakes for the test channel, and in `configs/slack/local/slack.yaml`:

```yaml
slack:
  test_door: false            # off
  # or:
  test_door:
    channel: "#temper-qa"     # the only channel fakes may use (the default)
    user: U0123456789         # who fakes act as (default: the first agents dm)
```

## Rules

- **Anyone in the workspace can act.** Every start, stop, gate answer and
  pick is logged with the Slack user (table `slack_actions`; also in the
  server log).
- **Only one process may hold the socket**, because Slack hands each event to
  any one open connection. Run any other server on the same app with
  `TEMPER_SLACK=0`. Tests run with it off.
- **Nothing Slack sends is lost.** Each command, click, form, mention and DM
  is saved in temper's event inbox before temper tells Slack it got it (still
  well within Slack's 3 seconds), then handled from there
  ([architecture](reference/architecture.md#events-from-outside-the-inbox)).
  If handling fails or a restart cuts it off, it is tried again, but not once
  it is over 30 minutes old: Slack's link to answer it has expired by then,
  so it is marked "expired". A run it started is never started twice.
  Slack's old verification token is dropped before saving.
  `temper events list --source slack` shows what came and what became of it.
- A missing or bad token, or Slack being down, never stops the server from
  starting. The bot just stays off, and `/api/slack/status` says why.
- Slack starts, stops and answers gates. Nothing merges or deploys from Slack.
