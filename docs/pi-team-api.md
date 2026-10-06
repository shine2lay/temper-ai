# The Team page's API (`/api/team`) — switched off

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
| `GET /api/team/runs/{execution_id}/messages/{message_id}` | the full text of one message |
| `POST /api/team/runs/{execution_id}/waits/{wait_id}/answer` | answer the open question Temper asks |
| `POST /api/team/runs/{execution_id}/messages` | message a member as the owner (201) |

Errors follow `api.json`'s conventions: `400 {problem}` for one bad field, `400
{problems, notes}` from a check, `404 {detail}`, `409 {reason, message, ...}`.

### Who did it (#45)

There is no second guard and no `by` in any body. Starting a trial counts as a run start
(`require_caller_may("start")`); answers and messages count as decisions
(`require_caller_may("approve")`), so with `TEMPER_API_GUARD=enforce` they need one of the
server's named keys ([api-access.md](api-access.md)) and a run box's own key can't do them.
Reads are open. Every write records a `caller.action` event (start, answer, message), and
the run page's cancel records its own.

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
pause_after_rounds, communication?, project_path?}`:

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
`leader`, `communication`, `pause_after_rounds`, `project_path`, or null) and `member` the
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
  `paused`, `quiet`, `member_waiting`, `interrupted`, `done`, `stopped`, `failed`), the
  trial's input, `round`, and each member with its activity, turns, cost, model and the
  model and thinking its turns really used (`effective`, from the turn receipt; `unknown`
  on older rows).
- `open_waits`: every open question, in the order Temper asks them (oldest first). The
  first has `asked: true` and its `event_id`; the others wait behind it with `event_id:
  null`. Any open wait holds every member's turn. A member's question shows as `kind:
  question`. Each wait has its `question` without reply syntax, the chat's `reply_hint`
  apart ("Reply 'continue', 'guide: <what to tell design>', or 'stop'."), and its
  `answers` with `needs_text` (`required`, `optional`, `none`).
- `reviews`, a typed `timeline` (`entry`: message, review_round, view, decision,
  owner_wait, owner_answer, member_turn; plus `message_kind`, `round`, `decision`,
  `wait_kind`; an owner_answer carries `answered_by` and `answered_source`), the
  `owner_actions` (start, answer, message, stop with `by` and `source`), and the
  `outcome`.
- The outcome is read only from `pi_team_outcomes`: `decision` (`done`, `stopped`,
  `cancelled`, `failed`, `didnt_start`), `reason`, `owner_words`, `problems`, `by`, `at`
  and, when done, the done record with its `objections` (reviewers whose view of the
  approved version wasn't `satisfied`) and the trial's `branch`. The node's
  `structured_output` gets a copy for workflow outputs, but the API never reads it back.

`GET /api/team/trials` lists `{trial_id, execution_id, workflow, goal_first_line, leader,
members, state, decision, run_status, round, cost_usd, started_at, started_by, ended_at}`,
newest first.

## Answering

`POST .../waits/{wait_id}/answer` with `{request_id, answer, text}`. The answer must be one
of the wait's own: the pause `continue`, `guide` (words required), `stop` (words optional);
stalled `nudge` (optional words), `stop`; a cut-off turn `accept`, `retry`, `stop`; a failed
turn `retry`, `stop`; a member's question `reply` (words required). It is checked before
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

A stop at the pause or at a stalled wait, with or without words, ends the run
**cancelled** (an owner's decision, not a failure), with the outcome `stopped`, the neutral
reason ("stopped at the pause after round <N>", "stopped when the team had nothing left to
do"), the words as `owner_words` and `by` whoever answered. A stop at a recovery wait
follows a failed or cut-off turn and stays failed.

## Messages

`POST .../messages` with `{request_id, to, body}` posts as the owner. While any wait is open
the message is `held` and delivers `after_open_wait`; otherwise it is `pending` and reaches
the member at its `next_turn`. Refusals: `400` "'<to>' is not a member of this team
(members: <names>)", "the message is empty", "the message is too long (<n> characters; at
most 20000)"; `409` `team_ended` "the team has ended; nothing was sent", `team_not_started`
"the team has not started yet; nothing was sent", `member_ended` "'<to>' has left the team;
nothing was sent".

## Limits

`team_status.limits`: `goal_max_chars` 20000, `message_max_chars` 20000, `guide_max_chars`
20000, `reply_max_chars` 20000, `nudge_max_chars` 4000, `stop_reason_max_chars` 2000,
`name_pattern` `^[a-z][a-z0-9_-]{0,39}$`, `reserved_names`. The server enforces them. The
cancel route's `reason` is limited to 2000 characters for every run (`400 {problem: "the
reason is too long (<n> characters; at most 2000)"}`, nothing cancelled); a team's
cancel reason becomes its outcome's `owner_words`.

## The approved branch (E10)

When a trial with a project ends done, Temper makes a local branch `team/<trial_id>` at the
approved commit in the source repository: create-only, never forced, pushed or checked out,
and the working tree and index are left alone. With a host helper socket in the box config
(`host_helper_socket`), the helper's `branch <repo> <leader git dir> <commit> <trial_id>`
verb makes it; otherwise Temper makes it itself with its hardened git. The done record's
`branch` is `{name, made, why}`: a branch already at that commit counts as made; one
elsewhere gives `made: false, why: "exists"`; a refusal or any other failure gives the why,
and done stays done.

## Tests (no model, no network)

`tests/test_runner/pi_parking/test_team_api.py` (every route on a real in-process Temper
with scripted members), `test_team_outcomes.py` (outcome rows, E18's cancelled stops, the
node-start folder refusal, pick plus words), `tests/test_pi_agent/test_team_settings.py`
(settings, folders, branch through a fake helper socket), `tests/test_api/test_gates.py`
(the approve core and the cancel reason's limit), `test_studio_trial_names.py`,
`tests/test_config/test_importer.py` and `tests/test_cli/test_check_team_settings.py`.

```bash
uv run pytest tests/test_runner/pi_parking tests/test_pi_agent tests/test_api tests/test_config
TEMPER_TEST_DATABASE_URL="$(scripts/test-postgres.sh url)" uv run pytest tests/test_runner/pi_parking
```

## Not built yet

`team_version` and `team_debrief`, `edges` communication, deleting a trial's configs, and
switching it on anywhere but a private test copy.
