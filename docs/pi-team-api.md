# The Team page's API (`/api/team`)

The Team page starts a team trial from a form, shows where it is, and lets the owner answer
its questions and message its members. These routes are its API, built to Architecture's M3
contract (`pi-agent-proofs/M3/contract.md`, `api.json`). The page itself is Frontend's.

Everything here is behind `TEMPER_PI_AGENT` (default off). The router
(`temper_ai/api/team_routes.py`) is added only when the switch is on when the server
starts (`include_team_routes`); with it off every `/api/team/...` path answers 404 and
nothing of it is imported. The team itself runs as described in
[pi-team-runtime.md](pi-team-runtime.md).

## Routes

| Route | What it does |
| --- | --- |
| `GET /api/team/status` | the form's defaults and limits, the tools, whether Bash may be given, the allowed project folders, the guard's mode |
| `GET /api/team/roles` | the roles a member can take: id, title, about, has_home_chat, problems (nothing else of a role's folder) |
| `POST /api/team/check` | every check a start makes, field by field; writes nothing |
| `POST /api/team/trials` | start a trial in one call (201) |
| `GET /api/team/trials` | trials, newest first (`limit`, `offset`, `state`) |
| `GET /api/team/runs/{execution_id}` | one trial's run: the whole state the page draws |
| `GET /api/team/runs/{execution_id}/events?after=0&limit=200` | cursor feed: events, cursor, more and UTC as_of |
| `GET /api/team/runs/{execution_id}/messages/{message_id}` | the full text of one message |
| `GET /api/team/runs/{execution_id}/version` | the team's newest version, from its stored version record (`team_version`) |
| `GET /api/team/runs/{execution_id}/boxes` | every named box turn for the watch's continuity check (named API key required) |
| `POST /api/team/runs/{execution_id}/waits/{wait_id}/answer` | answer the open question Temper asks |
| `POST /api/team/runs/{execution_id}/messages` | message a member as the owner (201) |

Errors follow `api.json`'s conventions: `400 {problem}` for one bad field, `400
{problems, notes}` from a check, `404 {detail}`, `409 {reason, message, ...}`.

**Where the role list comes from (ADR-M4-21).** The server is the run boxes' template, so it
holds no Pi folder. The status, roles, check and start routes read the role cards and the
route, add-on and search-tool names from the Pi lane view that pi-worker publishes
([pi-lane.md](pi-lane.md), "The Pi lane view"), never the disk. With no current view
(pi-worker stopped, or its preflight failing), `roles_configured` is false, and
`roles_problem`, `GET /roles`' `problem` and a check's `roles` finding say "the Pi lane isn't
running or hasn't passed its checks, so the server has no current role list from it
(<why>)". The replies keep their shapes. The view only lets the page offer a start: the Pi
lane checks the roles again on its own disk when its run process loads the workflow and when
the team starts.

### Who did it (#45)

There is no second guard and no `by` in any body. Starting a trial counts as a run start
(`require_caller_may("start")`); answers and messages count as decisions
(`require_caller_may("approve")`), so with `TEMPER_API_GUARD=enforce` they need one of the
server's named keys ([api-access.md](api-access.md)) and a run box's own key can't do them.
Page reads are open. The watch-only `/runs/{execution_id}/boxes` read always
requires a named API key, even with the write guard off; it uses the same hashed
keys as cancel. Every write records a `caller.action` event (start, answer,
message), and the run page's cancel records its own.

The box read returns `{execution_id, boxes: [{box_name, turn_id, started_at,
ended_at, created}]}` from every named `pi_turns` row for this run, including
past attempts, sorted by start time and turn id. Times have an explicit UTC
zone. `created` is `true` for a settled turn's receipt confirming creation;
`false` requires both `created: false` and `creation_attempted: false` in that
receipt. Anything uncertain is `null`: the older `created: false` alone also
covers a Docker-create timeout and cannot prove the container never existed.
Current older receipts therefore need PASS evidence even when they say false.
Only a proven `false` on a settled turn can excuse missing watch evidence.
No member output, prompts, tokens or full receipts are returned.
There is no pagination that could hide an earlier gap box. See
[pi-watch-stop.md](pi-watch-stop.md) for the continuity rule.

`by` is the caller's name: `owner` for the names in `owner_callers` (below), another named
caller by its name (`temper-ci`, `autopilot`; names are not secrets, hashes never leave the
server), or `unknown caller`. `source` is for display only, never to decide who acted:
`team_page` (a `/api/team` route), `run_page` (another HTTP route called with the
dashboard's own Origin), `chat` (a temper MCP tool, Slack, Telegram), `api` (any other
HTTP) or `unknown`.

### Request ids

Start, answer and message take a `request_id` (any unique text, the same on a retry). The
same id with the same body gives the first result again with `repeated: true`; the same id
with a different body is refused with `409 {reason: "request_id_reused"}` and nothing is
done. A start's id is kept on its trial row (`pi_team_trials.request_id`, unique), an
answer's or message's in `pi_team_requests`; a message also uses it as the ledger's
`dedupe_key`.

## Starting a trial

`POST /api/team/trials` with `{request_id, goal, members: [{role, name?, tools?}], leader,
pause_every_usd?, max_parallel?, communication?, project_path?}`. The check-in defaults to
$100 and the parallel cap to every member. Non-null `pause_after_rounds` is refused; a null
field sent by the old form is ignored:


1. The trial gets a 12-hex-character id. Its workflow `team-trial-<id>` has one team stage,
   `trial` (node `trial.team`), whose outputs map the node's typed outcome; each member gets
   an agent config `team-trial-<id>-<member>` with `name: <member>` inside. A member with
   no name takes its role's id, unless that is reserved.
2. Everything is checked in memory first: the member rows, the goal's length, `check_team`
   (names, tools, Bash, roles, routes, add-ons, the goal), the project folder, and the run
   start's own check on the built workflow. Any problem gives `400 {problems, notes}` and
   nothing is saved.
3. The configs and the trial row are saved in one transaction, and the run starts through
   `POST /api/runs`' own start code with the input `goal` and the project as its workspace.
   If that start refuses or raises, what was saved is removed again.

A trial's configs are frozen: Studio refuses to write or delete a `team-trial-` name, the
configs/ importer skips such a file (and logs it), and `temper check` reports it. Nothing
deletes them on day one, so a trial's run can be resumed or forked.

### Problems and notes by field (E20)

`team_check` and every 400 of a start give `problems` and non-blocking `notes` as `[{field,
member?, text}]`. `text` is the engine's sentence word for word, with its `<where>:` prefix,
so chat and the page read the same words. `field` is the form's field (`goal`, `members`,
`leader`, `communication`, `pause_every_usd`, `max_parallel`, `project_path`, or null) and `member` the
member row's name; both come from where the problem was found, never from the sentence.

### Project folders (M4 item 0)

A trial may name a project folder, which must be inside `project_roots`. The settings are
in `configs/team/team.yaml` (tracked: `project_roots: []`, `owner_callers:
[owner-dashboard]`) and `configs/team/local/team.yaml` (git-ignored; the owner writes it at
switch-on, with absolute host paths, because `~` is `/app` inside the containers). A key in
the local file replaces the tracked one. A root is a folder (`/home/me/rollcall`) or its
direct children (`/home/me/projects/*`). The configs/ importer never reads `configs/team/`
(by its path from the configs root, so a deeper `team/` folder still loads).

The folder is checked at two levels:

- **By its text**, everywhere: a full path, no `..`, no spaces or control characters,
  inside a listed root.
- **For real**, only where the folder can be seen: after links it is still inside a root,
  it is the top of a git work tree, its git folder and common git folder are inside the
  roots, it has a commit, and no tracked file has uncommitted changes.

The server is the run boxes' template, so no project folder is mounted into it. When the
folder isn't visible there, `team_check` and a start run the text check and add the note
"folder checks run when the Pi lane starts the team" instead of refusing. The real check
runs where the team runs, at the team node's start, before any copy or model call; a folder
it can't see is refused there as "project: <path> isn't reachable inside Temper".

## A trial's run

`GET /api/team/runs/{execution_id}` follows contract section 5:

- `run_status` (the run list's own status), `state` (`didnt_start`, `starting`, `running`,
  `paused`, `quiet`, `member_waiting`, `settings_changed`, `interrupted`, `done`, `stopped`,
  `failed`), the
  trial's input, explicit `kind: flow | rounds`, and each member with its activity, turns, cost, model and the
  model and thinking its turns really used (`effective`, from the turn receipt; `unknown`
  on older rows).
- `account`: the run's one account by slot label, as the Pi lane recorded it at its first
  claim (`{slot, picked_at, by, capacity, room}`; never an email or an account id), else
  `null`. `by` is `room` (picked by the account-room file's figures, which are in `room`;
  `capacity` is `null`) or `settings_order` (the first allowed slot in the settings' order
  with no capacity check, ADR-M4-19: `capacity` is `not_checked` and `room` is `null`; no
  figure is ever made up). Each turn's `account_slot` is in the timeline and each member's
  `last_turn` ([pi-trial-safety.md](pi-trial-safety.md)).
- `open_waits`: every open question, in the order Temper asks them (a settings wait
  first, then oldest first). Flow member questions can each have `asked: true` and an
  `event_id`; each holds only its member. Settings questions take precedence. Old round
  records retain their first-question-only shape. A member's question shows as `kind: question`.
  Flow waits add `scope: member | team` and first-sentence `words` (at most 160 characters). Each wait has its `question` without reply syntax,
  the chat's `reply_hint` apart ("Reply 'continue', 'guide: <what to tell design>', or
  'stop'."), its `answers` with `needs_text` (`required`, `optional`, `none`), and
  `asked_again` (how many times a recovery or settings question was asked again after an
  answer that named no choice).
- A settings wait (`kind: settings`; the run's `state` is `settings_changed` while it is
  the one asked; SW-85, M3 E24, [pi-agent.md](pi-agent.md) "Settings changed while a
  conversation waits") also carries its typed fields, so the page builds its Setting |
  Was | Now table from them and never reads the question:
  - `settings_changes`: one entry per changed setting, `{scope, member, key, value_kind,
    old, new}`. `scope` is `team` (then `member` is null) or `member` (the member's
    name). `value_kind` is `text` for `pi_version`, `image`, `provider`, `model` and
    `thinking`, and `sha256` (a full 64-hex digest) for every other key:
    `extensions.<name>`, `add_ons.<name>`, `agent_config_sha256`, `team`, `tools`,
    `route_host`, `workflow`, `cwd`. Never a file's contents or an environment value.
  - `pins`: one entry per member it re-pins, `{member, pin_old, pin_new}`: the full sha256
    of the member's pin before and after, the exact values `go on` checks and pins.

  Every other wait has `settings_changes: null` and `pins: null`.
- Flow usage limits are team holds. A timer only schedules a fresh read-only usage check
  on the kept account; it is not permission to start. Only verified available usage allows
  five-hour automatic resume or a weekly/unknown `restart`/`stop` question. Unavailable,
  stale, expired-sign-in or still-exhausted readings keep waiting without expiry, with
  another check scheduled (15 minutes when no usable reset is known). A delayed weekly
  restart answer is checked again before clearing the hold.
  Phase adds `usage`, `usage_checked_at`, `resume_verified` and `blocked_windows`;
  `reason` names an unavailable reading's fixed code. `resumes_at` is the next check time,
  not a restart permission. Answerable flow limit waits carry those same fields. Before
  verification the hold appears in phase, not as an answerable question. Historical
  recovery waits retain their `account_slot`, `limit` and `resets` fields.
- A typed `timeline` (flow adds share, idle, wake, closing, done_refused and conflict;
  old round records keep `reviews`, `round` and the old entries): message, review_round, view, decision,
  owner_wait, owner_answer, member_turn; plus `message_kind`, `round`, `decision`,
  `wait_kind`; an owner_answer carries `answered_by` and `answered_source`; the settings
  answer is an owner_answer with `wait_kind: settings` and its `answer`, `go on` or
  `stop`, with `applied: false` in its data when a go on re-pinned nothing because the
  settings changed again; the answer it held, the one that reopened the team, shows once,
  after the go on, as its own owner_answer, and never after a stop), the
  `owner_actions` (start, answer, message, stop with `by` and `source`), and the
  `outcome`.
- The outcome is read only from `pi_team_outcomes`: `decision` (`done`, `stopped`,
  `cancelled`, `failed`, `didnt_start`), `reason`, `owner_words`, `problems`, `by`, `at`
  and, when done, the shared commit, summary, ordered shares, per-member turns, cost,
  file hashes and the trial's `branch`. Historical round outcomes keep their `objections`. The node's
  `structured_output` gets a copy for workflow outputs, but the API never reads it back.

Flow replies also include `phase` (name/words/since/running/asked/reset information),
`as_of`, `started_at`, frozen ended `elapsed_s`, `last_activity_at`, `spend` (total, baseline,
next check-in and history), `you` (count/first owner question), `counts`, `links`, `work`
(latest shared version and share history), `events_cursor` and visible `events_total`.
Members add state/since, current `on`, live tools, ready-message count, last sent message,
last share, conflicts, idle reason/note and last-turn error. A raw event cursor can exceed the
visible count because internal bookkeeping is not shown. Flow omits `round` and `reviews`.

`GET /api/team/trials` lists `{trial_id, execution_id, kind, workflow, goal_first_line, leader,
members, state, decision, run_status, cost_usd, started_at, started_by, ended_at}` (old rounds retain `round`),
newest first.

Every time the Team API sends, in every route and every reply, is ISO 8601 in UTC with the
offset written out (`2026-10-06T09:28:00.882441+00:00`); the page shows it in the owner's
zone. `owner_actions` are sorted by that moment, oldest first.

## The team's version (`team_version`)

`GET /api/team/runs/{execution_id}/version` follows contract section 5's `team_version`. It is
served from the newest version record `pi-worker` stored (a share, a completed Project,
or a historical review), never read live from a copy. `?version_no=N` selects a flow share:


`{commit, start_commit, kind, review_id, round, made_by, files: [{path, sha256}],
files_total, diff, diff_bytes, truncated, note, withheld, branch, made_at}`. The diff is
against the start commit and cut at 200,000 bytes (`truncated: true` and a `note` say so). A
version the token scan stopped has no files and no diff, and `withheld: {rules, paths}`
names why. `branch` is the approved branch's name once made, else `null`. `404 {detail: "the
team has made no version yet"}` before the first record; like every route here, `404` while
the switch is off.

## Answering

`POST .../waits/{wait_id}/answer` with `{request_id, answer, text}`. The answer must be one
of the wait's own: the pause `continue`, `guide` (words required), `stop` (words optional);
stalled `nudge` (optional words), `stop`; a cut-off turn `accept`, `retry`, `stop`; a failed
turn `retry`, `stop`; a member's question `reply` (words required); a settings wait `go on`
("The team carries on with the new settings, then your last answer is applied.", no words)
and `stop` (words optional). While a settings wait is open, the answer it holds can't be
given again: that wait is a later one, not asked yet (409). It is checked before
anything is recorded, then decided through the approve route's own code
(`routes.approve_wait`, which `POST /api/runs/{id}/approve/{node}` also calls) as a
typed response.

| Answer | Reply |
| --- | --- |
| taken | `200 {status: "approved", wait_id, event_id, answer, text, repeated, carries_on, needs_resume, message?, by, at}` |
| not one of its answers | `400 {problem: "'<word>' is not an answer to this question (answers: <list>)"}` |
| guide without words | `400 {problem: "'guide' needs the words to pass to <leader>"}` |
| over its limit | `400 {problem: "the guidance is too long (<n> characters; at most 20000)"}` (also "the nudge", "the reply", "the reason for stopping") |
| a later wait, not asked yet | `409 {reason: "not_asked_yet", message}` |
| already answered | `409 {reason: "already_answered", answered_by, answered_at, answered_source, ...}` |
| no such open wait | `404 {detail: "That question is no longer open"}` |

A stop at the pause, at a stalled wait or at a settings wait, with or without words, ends
the run **cancelled** (an owner's decision, not a failure), with the outcome `stopped`, the
neutral reason ("stopped at the check-in at $<N>", "stopped when the team had nothing
left to do", "stopped when the team's settings changed since its conversations started
(<member>: <keys>; ...)"), the words as `owner_words` and `by` whoever answered. After a
settings stop, the answer it held is never applied. A stop at a recovery wait
follows a failed or cut-off turn and stays failed.

## Messages

`POST .../messages` with `{request_id, to, body}` posts as the owner. A run hold or that
recipient's member wait reports `held` / `after_open_wait`; an unrelated member wait does
not hold it. Otherwise it reports `pending` / `next_turn`; a running flow inbox can receive
it in its current turn. Old round records keep their whole-team hold description. Refusals: `400` "'<to>' is not a member of this team
(members: <names>)", "the message is empty", "the message is too long (<n> characters; at
most 20000)"; `409` `team_ended` "the team has ended; nothing was sent", `team_not_started`
"the team has not started yet; nothing was sent", `member_ended` "'<to>' has left the team;
nothing was sent".

## Limits

`team_status.limits`: `goal_max_chars` 20000, `message_max_chars` 20000, `guide_max_chars`
20000, `reply_max_chars` 20000, `nudge_max_chars` 4000, `stop_reason_max_chars` 2000,
`name_pattern` `^[a-z][a-z0-9_-]{0,39}$`, `reserved_names`, and
`pause_every_usd: {min: 1, max: 10000}`. The server enforces them. The
cancel route's `reason` is limited to 2000 characters for every run (`400 {problem: "the
reason is too long (<n> characters; at most 2000)"}`, nothing cancelled); a team's
cancel reason becomes its outcome's `owner_words`.

## The approved branch (E10)

When a trial with a project ends done, Temper makes a local branch `team/<trial_id>` at the
approved commit in the source repository: create-only, never forced, pushed or checked out,
and the working tree and index are left alone. With a host helper socket in the box config
(`host_helper_socket`), the helper's `branch <repo> <leader git dir> <commit> <trial_id>`
verb makes it (`docs/pi-host-helper.md`); otherwise Temper makes it itself with its
hardened git. The done record's
`branch` is `{name, made, why}`: a branch already at that commit counts as made; one
elsewhere gives `made: false, why: "exists"`; a refusal or any other failure gives the why,
and done stays done.

## Tests (no model, no network)

`tests/test_runner/pi_team/test_team_versions.py` (version records, the route's record, the
token scan's ways out), `tests/test_runner/pi_parking/test_team_api.py` (the in-process unit-test harness with scripted members; no separate running server), `test_team_outcomes.py` (outcome rows, E18's cancelled stops, the
node-start folder refusal, pick plus words), `tests/test_pi_agent/test_team_settings.py`
(settings, folders, branch through a fake helper socket), `tests/test_api/test_gates.py`
(the approve core and the cancel reason's limit), `test_studio_trial_names.py`,
`tests/test_config/test_importer.py` and `tests/test_cli/test_check_team_settings.py`.

```bash
uv run pytest tests/test_runner/pi_parking tests/test_pi_agent tests/test_api tests/test_config
TEMPER_TEST_DATABASE_URL="$(scripts/test-postgres.sh url)" uv run pytest tests/test_runner/pi_parking
```

## Not built yet

`team_debrief`, `edges` communication and deleting a trial's configs.
Only the configured live Temper is used for any real run; tests never start a second copy.
