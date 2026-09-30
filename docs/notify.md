# Notify — where a run's questions and notices go

Temper tells people about their runs in Slack and Telegram: a gate waiting
for an answer, a run gone quiet, a run that failed or finished. One shared
layer decides where each message goes, so Slack and Telegram (and later
Notion) behave the same way, and a workflow can choose its own.

```
runs, gates ──▶ notify loop (in the server, every 15 s) ──▶ Slack   (sender)
                  where? origin · workflow · run · defaults   ──▶ Telegram (sender)
                  when?  quiet hours · nudges
```

## Kinds of message

| Kind | When | What you can do there |
|---|---|---|
| `question` | a gate is waiting, with the questions its step asked | answer them, then **Approve**, or **Reject** (stops the run) |
| `stuck` | a running run has written no event for `stuck_after`, or for its workflow's own `quiet_after` | **Stop run** |
| `failed` | a run failed; the message quotes the failed step's own error | |
| `finished` | a run completed or was cancelled | |

The run waits at its gate until someone answers, as long as that takes and
across restarts. The next step gets the answers (`gate.text`,
`gate.answers`, `gate.response`). When a question is answered anywhere (the
dashboard, Slack, Telegram, the API), every other copy loses its buttons and
says who answered and where. When a quiet run ends, its "stuck" message
says so and loses its Stop button.

## Where a message goes

A **route** is:

- `origin`: back where the run was started, as a reply in that Slack thread
  or under the run's first message in that Telegram chat, or as a comment
  on the Notion page the run was started from ([notion.md](notion.md));
- a **place name** from the notify file (`slack`, `telegram`, `team` …);
- a list of those: `[origin, telegram]`;
- `off`.

A run started from the dashboard, a schedule or the API has no origin. When
its route comes to nothing, the file's `fallback` for that kind is used. A
message never goes twice to the same place, even when two names point at
the same chat.

The most specific setting wins, one kind at a time:

1. the run's own: `POST /api/runs {"workflow": …, "notify": {"finished": "off"}}`;
2. its workflow file's `notify:` block;
3. `workflows:` in the notify file;
4. `defaults:` in the notify file (a kind named nowhere goes to `origin`).

In a workflow file:

```yaml
workflow:
  name: nightly_report
  notify:
    question: [origin, telegram]
    failed: telegram
    finished: slack
    quiet_hours: off              # this one pings at any hour
  nodes: …
```

Only place names go in a workflow, never ids, so the same workflow works in
any install. A name the notify file doesn't define fails the config import,
and `temper slack check` / `temper telegram check` list it.

## The notify file

`configs/notify/local/notify.yaml` (git-ignored, because it holds Slack and
Telegram ids). When it doesn't exist, the tracked `configs/notify/notify.yaml`
is used; it names no places, so it only answers a run where it was started.
Changes are picked up without a restart; a change that breaks the file is
ignored (the last good one stays) and the checks say why.

```yaml
notify:
  dashboard_url: https://temper.example.com   # run links in messages
  stuck_after: 45m

  places:
    slack:    {slack: {dm: U0123ABCD}}         # the bot's DM with a person
    runs:     {slack: {channel: C0123ABCD}}    # a channel id, or "#name"
    telegram: {telegram: 123456789}            # a Telegram chat id
    team:     {telegram: -1001234567890}       # a group (negative id)
    qa-page:  {notion: qa}                     # a Notion page target (comments)

  defaults:                  # every run, unless something closer says otherwise
    question: origin
    stuck: origin
    failed: [origin, telegram]
    finished: origin

  fallback:                  # when a run's route comes to nothing (no origin)
    question: slack
    stuck: slack
    failed: slack
    finished: slack

  workflows:                 # per workflow; replaces the kinds it names
    slack_pick: off          # @temper's workflow picker
    repo_answer: off         # the answer to a code question is the message
    nightly_report: {finished: runs}

  quiet_hours: {from: "22:00", to: "07:00", zone: America/Los_Angeles, still_ping: [question]}
  nudge: {after: 30m, to: telegram}

  agents: [telegram]         # where the TelegramSend tool may post
```

### Quiet hours

Between `from` and `to` (in `zone`), messages are held and go out together
when the window ends. The kinds in `still_ping` (by default just `question`)
go out anyway. In Telegram, finished messages are always sent silently (no
sound); questions, failures and stuck runs make a sound.

### Nudges

A question nobody has answered after `after` is also sent to `to`, once,
marked "Nobody has answered this for 30 min". Answering either copy closes
both.

Both can be set in the file (for every run), per workflow in `workflows:`,
in a workflow file, or for one run; `quiet_hours: off` / `nudge: off` turns
them off there.

## When a run counts as quiet

A run is quiet when it is still marked `running` and has written no event
for longer than its threshold: `stuck_after` in this file (45 minutes), or
the workflow's own `quiet_after`, which wins where it is set:

```yaml
name: epd_loop
quiet_after: 2h        # a deploy step of this one really does take hours
```

Ten minutes of silence is alarming in a one-minute run and ordinary in a
build, so the number belongs with the workflow. `quiet_after` takes `90s`,
`30m`, `2h`, `1d` or a number of seconds.

A run parked at a gate is **never** quiet, however long it waits: it is
waiting for a person, which is the run doing its job. The run list and the
run page say so, with how long it has been waiting ("needs you, 10h"),
because a question nobody has answered since this morning is the thing that
actually goes unnoticed. A run that has gone quiet shows "quiet for 2h 14m"
and the last thing it did.

A run waiting for the **model allowance** is never quiet either, and never
"needs you". Every account has a ceiling; when all of them are spent at once
the run sets itself aside and carries on by itself when the allowance
reopens, showing "waiting for allowance, back around 14:20" until it does.
Nobody is being asked anything, so no message goes out.

How long a run may wait is capped — six hours by default, which covers the
rolling window. Past that it fails as it always did, because a run holding
its worktree and its branch for three days is worse than one that fails and
is resumed. A workflow prepared to sit out a weekly reset says so:

```yaml
name: epd_loop
wait_for_allowance: 2d   # or `0` / `false` to never wait
```

It takes the same durations as `quiet_after`.

One message goes out per quiet spell. A run that comes back to life by
itself ends the spell and nothing more is said about it; if it goes quiet
again later, that is a new spell and a new message. The same rule
(`temper_ai/runner/quiet.py`) decides the badge and the message, so the
screen and your phone never disagree.

## Status and checks

- `GET /api/notify/status`: whether the loop runs, which places are on,
  how many messages were sent and held, and the file in use.
- `temper slack check`, `temper telegram check`, `temper notion check`: the file's places and
  routes, every workflow's own `notify:`, and whether the server sends there.

## Rules

- **Only one server may run the loop** against a database, or messages go
  out twice. Run any other server with `TEMPER_NOTIFY=0`.
- Every message is claimed in the database (table `notify_copies`) before it
  is sent, so a restart never sends one twice, and a question answered while
  the server was down is closed everywhere when it comes back.
- Runs that were already going when the loop first started are left alone.
- The loop never starts or stops anything by itself; only people pressing
  buttons do.
