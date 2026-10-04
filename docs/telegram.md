# Telegram — run temper from Telegram, and hear back there

Temper runs a Telegram bot that works like its [Slack app](slack.md): you can
find a workflow, start it, check on it and stop it, ask about the code, and
answer a run's questions right in the chat. Each run's messages stay
together as replies under its first message. Nothing needs a public
address: the temper server asks Telegram for new messages itself (long
polling).

```
Telegram ◀──HTTPS (getUpdates, outgoing)──▶ temper server ──▶ runs, gates
  /commands, plain words, buttons            questions · stuck · failed · finished
```

Where each run's questions and notices go (Telegram, Slack, both, back where
it was started) is the shared notify file: see [notify.md](notify.md).

## Who can use it

- **The owners**, in their private chat with the bot (`owners:` below).
- **Any group an owner adds the bot to.** In a group, anyone may use it. The
  bot leaves at once a group that someone else added it to.
- Anyone else who writes to the bot privately gets no answer; `temper
  telegram check` lists them.

In a group the bot acts on commands, on messages that mention it
(`@your_bot …`), and on replies to its own messages; other talk is ignored.

## Commands

| Command | What it does |
|---|---|
| `/ask <question>` | Answers a question about the code of rollcall, roamee or temper-ai (the `repo_answer` workflow, 3–25 cents). |
| `/search <words>` | Workflows whose name, description or inputs match, with their inputs. |
| `/list` | Every workflow. |
| `/run <workflow> key=value …` | Starts a run. Values are checked against the workflow's inputs; quotes work (`topic="two words"`). The run's questions and notices then come here, as replies to the "started" message. |
| `/status [id]` | One run (any unique start of its id), or everything going now. |
| `/stop <id>` | Cancels a run. |
| `/help` | This list. |

**Plain words** (or a mention in a group): temper picks a workflow and its
inputs from what you wrote (the same `slack_pick` model Slack uses, one or two
cents) and shows the proposal with **Start** / **Cancel**. Nothing runs until
someone presses Start. When something is missing it asks; reply to its
message to carry on. A question about the code is answered straight away.

## Answering a question

When a run's gate is waiting, its message shows what the step said and each
of its questions:

- a question with choices has a button per choice (tap again to change it);
- a pick-any question has toggle buttons (☑️ / ⬜);
- **Type an answer** (or simply replying to the message) takes a typed
  answer for the current question; **Next** / **Back** move between
  questions;
- **Approve** continues the run with the answers; **Reject** asks once more,
  then stops the run.

When it is answered anywhere else (the dashboard, Slack, the API), the
message loses its buttons and says who answered and where. If the run was
not running (temper restarted while it waited), **Approve** keeps the answer
and resumes the run, which goes on with it without asking again
([gates.md](gates.md)).

## Agent tool

`TelegramSend` sends a message as the bot, either to `origin` (the chat the
run was started from, under the run's first message) or to a place the
notify file's `agents:` list names. Chat ids are refused, so text an agent
reads can't talk it into messaging anyone else.

## Setup

1. **The bot.** In Telegram, message @BotFather: `/newbot`, a name, and a
   free username ending in `bot`. It answers with the token.
2. Put the token in `.env` yourself, never in chat or git:

   ```
   TELEGRAM_BOT_TOKEN=123456:ABC...
   ```

3. **Who may use it.** Send the bot `/start` from your own account, then
   write `configs/telegram/local/telegram.yaml` (git-ignored; the format is
   in `configs/telegram/telegram.yaml`):

   ```yaml
   telegram:
     owners: [123456789]       # your Telegram user id
     groups: []                # groups allowed even with no owner in them
     zone: America/Los_Angeles # times in messages
   ```

   Your user id is in `temper telegram check` once you have written to the
   bot (it lists refused chats), or ask @userinfobot.
4. **Where messages go.** Add places to `configs/notify/local/notify.yaml`
   ([notify.md](notify.md)), e.g. `telegram: {telegram: 123456789}`.
5. Restart the server and worker, then check it:

   ```
   temper telegram check [--server URL]
   ```

   It confirms the token and the bot's name, that no webhook blocks polling,
   who may use the bot, that the running server is polling
   (`GET /api/telegram/status`), which chats the bot talks in and which were
   refused, and that the notify file's Telegram places are chats the bot can
   reach.

## Rules

- **Only one process may poll the bot.** Telegram answers a second one with
  "409 Conflict". Run any other server on the same bot with
  `TEMPER_TELEGRAM=0`. Tests run with it off.
- Messages sent while temper was down for more than 10 minutes are skipped,
  not acted on late (they are kept in the event inbox as "skipped").
- **Nothing Telegram sends is lost.** Each update is saved in temper's event
  inbox before temper tells Telegram it has it, then handled from there
  ([architecture](reference/architecture.md#events-from-outside-the-inbox)).
  If saving fails, Telegram sends the same updates again on the next poll. If
  handling fails or a restart cuts it off, it is tried again, and a run it
  already started is not started twice.
  `temper events list --source telegram` shows what came and what became of it.
- Every start, stop, answer and pick is logged with the Telegram user
  (table `telegram_actions`).
- A missing or bad token, or Telegram being down, never stops the server from
  starting; the bot stays off and `/api/telegram/status` says why.
- Telegram starts, stops and answers gates. Nothing merges or deploys from
  Telegram.
