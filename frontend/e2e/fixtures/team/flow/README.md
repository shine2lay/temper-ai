# Free-flowing team fixtures

Replies of Temper's free-flowing Team API (FLOW E5/E6) for the glance page.
Only `src/lib/teamGlanceAdapter.ts` reads their field names.

## `real/`: Temper's own replies, unchanged

Nine states exported by Temper (FLOW #80) from its real serializers
(`team_routes.team_run` and `events_view`) on synthetic ledger rows. Copied byte
for byte; never edit them. Each state has the run reply
(`GET /api/team/runs/{id}`) and its feed
(`GET /api/team/runs/{id}/events?after=0`):

`working`, `idle`, `share`, `check_in` (the check-in asked), `closing`, `done`,
`done_refused`, `stalled` (phase `quiet`, asked), `failed` (a member's turn
failed after its retry: phase `waiting_for_owner`). Each is its own small run
(execution_id `fixture-flow-<state>`) of one team: lead (the leader), builder
and checker writing a README.

## `real-g6/`: Temper's runs of its own engine, unchanged

Twelve runs Temper made with its real engine and no model (FLOW G6). Each has
the run reply (`<run>.json`) and its feed (`<run>-events.json`). Copied byte
for byte; never edit them. `G6-INPUTS.sha256` is a copy of Temper's manifest,
and `src/__tests__/teamGlanceG6.test.ts` checks every file against it.

`member_question` (one member's question open; you answered another's),
`retry` (Temper's retry of a failed turn; turns ended without a tool call and
at the call cap), `interrupted` and `interrupted_no_end` (the run ended
without the team ending, with and without its elapsed time), `limit_waiting`
(a 5-hour limit: Temper's own wait, nothing for you), `limit_unavailable`
(usage could not be checked), `limit_ready` (a weekly limit with fresh room:
restart or stop?), `limit_ended` (the limit is over), `restart_deferred` (you
said restart before the limit had reset), `conflict` (a file in conflict and
a refused share), `settings_late` (you said go on, then the settings changed
again), `invalid` (an answer that matched no choice; Temper asked again).

Ids, times and sequence numbers change each time Temper remakes them, so no
test depends on them.

## `real-git/`: Temper refusing git over a member's folder (Temper #115)

Two runs captured by `frontend/scripts/capture_team_fixtures.py --only git`
(from the repo root: `uv run --extra dev python frontend/scripts/capture_team_fixtures.py --only git`).
Each is a real free-flowing team on Temper's engine (lead and builder, members
scripted, no model), read mid-run through the Team page's own routes
(`team_routes.team_run` and `team_routes.team_events`) as FastAPI sends them.
Each has the run reply (`<run>.json`) and its feed (`<run>-events.json`); the
script replaces the scratch folder with `/srv/example/scratch`. Never edit
them by hand: rerun the script.

`git_rest` (the builder makes a `.git` of its own: its share is refused with
cause `planted`, its next turn starts after a `sync_refused` with cause
`planted`, and after refusals in two turns in a row Temper rests it: idle
reason `git_refused` with Temper's own note as `idle_note`), `git_writer`
(Temper can't yet rule out a writer in the builder's folder: `sync_refused`
with cause `writer`, that turn doesn't start, the retry does). All three of
#115's fields are captured here; none is derived.

## `derived/`: the states Temper did not send

Made by `node scripts/make_flow_fixtures.mjs` (run from `frontend/`) from one
real reply each, changing only fields Temper's field list defines. To update
from a supplied serializer snapshot, run the same script with
`--import-real <serializer-replies-folder>`: it copies the nine pairs unchanged,
then rebuilds the derived files. Edit the script, not the JSON. Each file's `_fixture` key says
`derived from <real state>: <what changed>`.

`starting`, `start` (only the leader works), `burst` (seven messages at once),
`settings`, `limit` (a 5-hour hold awaiting a fresh allowance check),
`limit_asked` (a weekly hold after reset and a fresh available usage reading),
`limit_spent` (the week still spent at the check), `limit_unavailable` (usage
unreadable at the check), `limit_start_check` (a 5-hour hold whose timed start
check could not read usage: it stays parked and checks again later),
`draining`, `interrupted`, `waiting` (two members' questions for you),
`member_question` (one member's long question while the others keep working),
`check_in_running` (turns finishing before the check-in is asked), `resumed`
(after you guide the check-in), `stopped`, `run_failed` (the whole run failed).

A member's question is Temper's native `ask_owner`: its turn completes, then a
question wait of member scope opens with the question (no reply syntax), header
`<member> asks`, Temper's fixed `note` and one answer, `reply`; only that member
is held. Other waits have `note` null.

Temper's limit questions name the run's kept account (`account.slot`); a fresh
usage reading needs that slot (without one the check is always unavailable).

Every new message has its own `message_id`, and no flow reply has `round` or
`reviews`. A test serves a feed's events past `after`, up to the run reply's
`events_cursor`.
