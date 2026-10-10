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
