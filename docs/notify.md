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
| `team_wait` | a free-flowing team asks you something on its Team page ([below](#team-alerts)) | open the Team page and answer there |

The run waits at its gate until someone answers, as long as that takes and
across restarts. The next step gets the answers (`gate.text`,
`gate.answers`, `gate.response`). When a question is answered anywhere (the
dashboard, Slack, Telegram, the API), every other copy loses its buttons and
says who answered and where. Each button answers the wait it was sent for: a
press on a question already answered, or replaced after the run was picked
up again, says so and changes nothing ([gates.md](gates.md)). When a quiet run ends, its "stuck" message
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
4. `defaults:` in the notify file (a kind named nowhere goes to `origin`,
   except `team_wait`, which goes nowhere until a block names it).

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
    team_wait: slack         # Slack places only; off when named nowhere

  fallback:                  # when a run's route comes to nothing (no origin)
    question: slack
    stuck: slack
    failed: slack
    finished: slack

  workflows:                 # per workflow; replaces the kinds it names
    slack_pick: off          # @temper's workflow picker
    repo_answer: off         # the answer to a code question is the message
    nightly_report: {finished: runs}

  quiet_hours: {from: "22:00", to: "07:00", zone: America/Los_Angeles, still_ping: [question, team_wait]}
  nudge: {after: 30m, to: telegram}

  agents: [telegram]         # where the TelegramSend tool may post
```

### Quiet hours

Between `from` and `to` (in `zone`), messages are held and go out together
when the window ends. The kinds in `still_ping` (by default `question` and
`team_wait`, the ones that ask you something) go out anyway. A held team
alert goes out at the window's end only if its team still asks; one whose
wait closed meanwhile is never sent. In Telegram, finished messages are always sent silently (no
sound); questions, failures and stuck runs make a sound.

### Nudges

A question nobody has answered after `after` is also sent to `to`, once,
marked "Nobody has answered this for 30 min". Answering either copy closes
both. Team alerts are never nudged.

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

A limit or disabled-account message is never an answer, and is never read out
of one. When a subscription hands back "You've hit your session limit ·
resets 10:50pm (UTC)" where the answer should be, that account cools until
the reset and the call starts again at once on another; an account whose
organisation has turned subscription access off is taken out of use until
the next restart, and the call starts again the same way. Only when no
account is left does the agent's fallback list and then this wait take over
(a disabled account is never waited for: with none left the step fails and
says so). A response a provider marks as an error never completes a step
either. A sentence counts only when the call reported an error or the
sentence is the whole result of a call that did no work, so an agent that
writes about limits, or quotes these sentences, completes as usual
(`temper_ai/llm/account_messages.py`).

An Anthropic stream that breaks mid-answer (an overload, an API error, a
stalled read) is not an allowance: the call is sent again, waiting 1, 2, 4,
8, 16, 32 seconds and then a minute each time, for up to ten minutes of
waiting in all (`stream_retry_budget_s` in the agent's `provider_config`)
before it fails.

One message goes out per quiet spell. A run that comes back to life by
itself ends the spell and nothing more is said about it; if it goes quiet
again later, that is a new spell and a new message. The same rule
(`temper_ai/runner/quiet.py`) decides the badge and the message, so the
screen and your phone never disagree.

## Team alerts

A free-flowing team (FLOW, [pi-team-messages.md](pi-team-messages.md)) asks
its owner on its Team page. Each wait it asks is a waiting gate, but for a
free-flowing team run the notify loop never sends it as a `question`: the
member's own words would go out in it, with Approve / Reject buttons that
don't fit a team. It sends a `team_wait` alert instead: one fixed sentence
and a link to the run's Team page (`<dashboard_url>/app/team/runs/<run>`).

| The Team page asks | The alert says |
|---|---|
| a member's question | The team is waiting for you: a member's question. Answer on the Team page. |
| a $100 spending check-in | … a spending check-in … |
| whether to restart after a weekly limit | … a usage-limit restart decision … |
| what to tell the leader, when Temper refused to run git over its folder in turns in a row | … the leader's work can't be shared … |
| anything else it asks you | … an owner decision … |

- **Only what the page asks.** The rule is the Team page's own (waits you
  can answer now): a five-hour limit resumes by itself and asks nothing; a
  check-in isn't asked while running work finishes; a closed wait or an
  ended team asks nothing. Teams that work in rounds keep ordinary
  `question` messages, as do gates outside a team.
- **Nothing a member wrote goes out:** no question, detail, answer, tool
  output, member name or goal, in the message, its closing edit or the
  `notify_copies` row (which keeps the wait id, the fixed reason and the
  link). You answer on the Team page; the message has no answer buttons.
- **Once per wait and place**, across restarts. When the wait closes
  (answered, stopped, or the team ended), the message is edited to "No
  longer waiting for you: …". A send Slack rejects, times out on, or
  doesn't confirm is marked failed and not sent again.
- **Slack only**, until a Telegram version of the same alert is built and
  tested: a route naming a Telegram or Notion place sends nothing there.
  With no route (`team_wait` named nowhere) nothing is sent anywhere.
- **Going back to an older temper:** a server from before team alerts
  doesn't know `team_wait`, so it won't use a notify file that names it,
  and sends nothing at all. Take `team_wait` out of the file before such a
  rollback.
- **Read only:** the loop never answers, resumes or retries a team. With the
  Pi step switched off it looks at nothing and every gate goes the ordinary
  way. If it can't read the teams' waits, it sends no team alert, closes
  none, and holds back every step's own wait from the ordinary questions
  until it can.
- **Receipts:** Slack's confirmation (the posted message's `ts`) is kept as
  the time you were told. `temper pi team-alerts <run>` (inside the server
  container) prints them as `{"notices": [{"wait_id", "at", "channel"}]}`,
  one per wait, for FLOW's measure.

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
