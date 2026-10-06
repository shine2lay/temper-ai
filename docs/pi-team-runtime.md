# The team runtime: leader mode and review rounds — switched off

A `strategy: team` stage ([pi-agent.md](pi-agent.md), "A team stage") runs as one node,
`<stage>.team`. That node runs the leader loop (`temper_ai/pi_agent/team_leader.py`,
`LeaderTeam`, `run_team_node`), built on the team's messages and inboxes
([pi-team-messages.md](pi-team-messages.md)) to Architecture's rules (R2 B7–B16, PARK P1/P2,
the T4T5 bindings, `pi-agent-proofs/M1/answer-1.md`).

Everything is behind `TEMPER_PI_AGENT` (default off). With it off, a new run of a team stage
is refused at load ("Unknown strategy: 'team'") and nothing here is imported; a team run
that was parked waits instead, "Pi switched off", until the switch is back on (M4 SW-32,
[pi-agent.md](pi-agent.md)). A run box never gets the switch (M4 SW-42,
[boxes.md](boxes.md)): Pi steps are to run only in the Pi lane, which isn't built yet.

## Starting

The team node runs `check_team` again when it starts, with the goal it was handed, because
a resume or a fork never runs the run-start check and a goal mapped from an earlier node is
only seen here. A run with a workspace also gets the project folder's real check here
([pi-team-api.md](pi-team-api.md), "Project folders"): this is where the team runs, so
this is the check that counts, and a folder it can't see is "project: <path> isn't
reachable inside Temper". Any problem fails the node red before any copy or model call:
"the team can't start: <problems>" when no turn of this team has begun yet (outcome
`didnt_start`), "the team can't go on: <problems>" when a resume finds it broken after
turns ran (outcome `failed`). The goal comes from the run's filled inputs, so a declared
`default:` counts (docs/reference/workflow-inputs.md).

Then the team opens (`Team.open`, which refuses reserved member names again as a backstop),
each member gets its own snapshot of its role folder (M4 SW-25, [pi-agent.md](pi-agent.md)
"The worker box"), each member gets its own git copy of the project, and the leader is sent
the goal. A refused snapshot fails the node before any turn: "the team can't open: member
<m>'s role snapshot was refused: <why>"; nothing is on record, so the next attempt copies
afresh. A database whose `pi_` tables Pi doesn't know fails it before anything: "Pi
refused this database: <why>" (M4 SW-13). A team node may be a workflow's first node.

When a team reopens (every owner answer starts a new attempt), it checks every member's pin
against what the configs and the box say now. A changed set of members (one added, removed
or renamed, or a member given another role) is refused: "team settings changed since the
team started (members); refusing to reopen its conversations" (or "(the role of <m>)"),
because a conversation can't be carried into a different team. Any other change, to the
team's settings or to a member's, is asked about at a settings wait (below).

**Project copies** (`ProjectCopies`): each member works on a clone of the run's workspace,
committed content only, in its own folder. The copies' git data is kept outside every
member's folder, so nothing a member writes can change how Temper's git runs. Untracked and
ignored files (`.env`) are never copied; a workspace with uncommitted changes is refused
with the reason. The copies are separate, but the project is shared: Temper moves every
reviewer's copy to the leader's review commit. That reopens A7's shared-file side channel
(the leader can pass anything to the reviewers through the files it commits, outside the
message rules), which the first slice accepts. Every git step checks the member's working
folder without following links and refuses one that is a link ("the member's working folder
<path> is a link; Temper does not follow links in a member's folder", M4 SW-51): git would
follow it, into `/etc` or another member's copy.

## A round

1. The leader calls `request_review` (with a short note).
2. Once the leader's turn has finished, Temper commits the leader's copy and moves each
   reviewer's copy to that commit, so everyone sees exactly that version, and sends each
   reviewer a review request naming the review id.
3. Each reviewer calls `give_view`: `satisfied` or `changes`, with a short note.
4. When every asked reviewer has given a view, Temper passes the views to the leader, one
   message per view, from its reviewer. A reviewer whose turn fails gives no view, and that
   shows red.
5. The leader calls `decide`: `done` (with a summary) or `keep_going`.

A review-tool call is recorded with the calling turn (`pi_team_acts`) and counts only once
that turn has finished (completed, or accepted at a recovery wait). Temper
carries it out before the team's next turn, on every path: the loop, a resume after a park,
a restart. A call from a turn that failed, was retried or was cancelled never counts.

Tools: the leader has `request_review` and `decide`, the reviewers `give_view`, and every
member the messaging tool from #37. Each member's framing carries a fixed note naming
exactly its tools and saying that notes, memory, questions to the owner and the queue tools
aren't available in a Temper run, so lessons and questions go in the reply.

## Done (R2 B9)

Only Temper records done. The leader's `done` counts only if its copy is still exactly the
review commit Temper made, and no work for the leader arrived after its deciding turn
began. Otherwise it is refused with a plain reason and counts as a keep-going.

The done record is the node's `structured_output` for later nodes: `decision`,
`review_id`, `round`, `version` (`commit` plus file hashes), each reviewer's last view
(`views`), the leader's `summary`, the number of `rounds`, the `cost`, the project copy's
record and the `leader`, plus `objections` (each reviewer whose view of the approved
version wasn't `satisfied`: `changes`, or `none` with its last earlier view) and, for a
Team page trial with a project, the approved `branch` ([pi-team-api.md](pi-team-api.md)).
After done, Temper takes no new work: pending messages are marked undelivered and late
sends are refused.

## The typed outcome (`pi_team_outcomes`)

Every way the node ends writes one row per team: `decision` (`done`, `stopped`,
`cancelled`, `failed`, `didnt_start`), `reason`, `owner_words`, `problems` (a list, never
split out of joined text), `by` (the caller's name), its display source, the done record
and when. It is the only source of the outcome; the node's `structured_output` gets a copy
for workflow outputs. `didnt_start` means no member turn of that team ever began. A cancel
that ends a parked run never runs the node again, so the cancel itself settles the row
(`end_teams_on_cancel` and the start-up sweep), with the cancel's caller and reason.

The reasons are neutral engine text that never names who stopped the team; who did it is
`by`, shown beside it:

- "the run was cancelled"
- "stopped at the pause after round <N>"
- "stopped when the team had nothing left to do"
- "stopped when the team's settings changed since its conversations started (<member>:
  <keys>; ...)", with `whole team: team` for the team's own settings
- "<member> turn <n> failed and the team was stopped", or for a cut-off turn "<member>
  turn <n> did not finish and the team was stopped"
- "the team was stopped" when no decided stop is found
- "the team can't start: <problems>" / "the team can't go on: <problems>"

## Owner waits

Every owner wait the team opens is one `pi_waits` row, written before it is asked, then
asked through `ask_owner` (temper_ai/stage/step_waits.py) under that row's own id, by the one
bridge `temper_ai/pi_agent/owner_waits.py` `ask_owner_for_wait`. Each wait has a new id,
never reused across rounds, stalled waits or recoveries. In a Pi workflow (team workflows
always are) an unanswered wait parks the run: no worker, thread or child process is held,
and the owner's answer carries the run on, through the team node again, from the tables. No
finished turn is run again. Team code never catches `RunParked`.

- **The pause** (R2 B10): after `pause_after_rounds` keep-goings in a row (required, no
  default), the same run pauses and stays unfinished. It is labelled
  `pause-after-round-N`. The owner answers `continue`, `guide: <text for the leader>` or
  `stop`, which may carry words (up to 2000 characters, kept as the outcome's
  `owner_words`); continue and guide restart the count. Anything else is not taken as an
  answer and the owner is asked again. A picked option counts as the choice and the typed
  text as its words. It never expires, resumes or cancels by itself, and it is never a
  generated gate node with a loop back: there is no overall round limit, and a team stage
  takes no `timeout_seconds` and no failure hold.
- **Stalled**: nothing is running, nothing waits to be delivered, no review is open and the
  leader hasn't said done. The owner answers `nudge` (optionally with words for the leader)
  or `stop` (optionally with words, as at the pause).

- **Settings changed** (SW-85, M3 E24): a deploy changed a member's settings or the team's
  while the team waited ([pi-agent.md](pi-agent.md) "Settings changed while a conversation
  waits"). When the team reopens, Temper opens one `settings` wait for the whole team
  before anything else: before any decided act is carried out, before the other open
  waits and before any turn. Its typed fields list each changed member's settings (scope
  `member`) and a changed team digest (scope `team`, member null), with each named
  member's old and new pin digests. The answer that reopened the team is held. `go on`
  re-pins every member the wait named, in one transaction, and only if each stored pin is
  still the one the wait named; then the held answer is applied as it would have been.
  If the settings changed again meanwhile, nothing is re-pinned (`applied: false`) and a
  new settings wait names the newer settings. `stop` (optionally with words, kept as
  `owner_words`) ends the team `stopped` and the run cancelled, as at the pause; the held
  answer is never applied. Anything else decides nothing and the owner is asked again.

A wait keeps its question and the chat's reply syntax apart (`question`, `reply_hint`);
Slack, Telegram and the run page show the two together, the same text as before. Any open
wait of any kind holds every member's turn, and Temper asks the open waits one at a time:
a settings wait first, then the rest oldest first.
- **Recovery** (R2 B11): a turn that was cut off, or whose result is uncertain (including
  the 900 s hang guard), opens a recovery wait that pauses the whole team. A cut-off turn is
  answered `accept`, `retry` or `stop`; a failed turn `retry` or `stop`. Retry re-sends the
  turn with the same message ids; stop ends the team red, never done. A picked option on
  the run page counts the same as typing it. Any other answer (empty, another word,
  `accept` at a failed turn) decides nothing: the owner is asked again, at a new wait for
  the same turn.
- **Owner questions** from a member are answered back to that member.

## Ending

| How it ended | Team node | Stage | Run |
| --- | --- | --- | --- |
| done | completed, with the done record | completed | goes on |
| stop at the pause, when stalled or at a settings wait | cancelled: "stopped at the pause after round <N>" / "stopped when the team had nothing left to do" / "stopped when the team's settings changed since its conversations started (...)" (outcome `stopped`) | cancelled | cancelled |
| stop at a recovery wait | failed: "<member> turn <n> failed and the team was stopped" (outcome `stopped`) | failed | failed |
| a member's turn failed, the team ended early | failed, with the reason | failed | failed |
| cancelled | cancelled; queued and held messages undelivered (B12) | cancelled | cancelled |

A failed team node fails its stage too, never completed (B13); the tolerant stage rule
stays for every other stage (`fails_stage` on the node, `stage/executor.py`).

An owner's stop at the pause, when stalled or at a settings wait is a decision, not a
failure, so the run ends
cancelled with the stop's own reason, not "Workflow cancelled by user": the node never sets
the run's cancel signal. The workflow's ending (`stage/executor.py`
`_build_final_result`) counts a stage that ended cancelled, with no failed node beside it,
as a cancelled run with that node's reason. The same rule ends a Pi step or team cancelled
by another attempt as cancelled, where it used to read completed. A cancelled run is never
picked up again, and a resume of it starts nothing. A stop at a recovery wait follows a
failed or cut-off turn and stays failed.

A cancelled run's team is ended again later if the process died between ending the run row
and ending its team (`runner/parked.py` `_end_pi_teams`, `end_cancelled_pi_teams`): when a
team opens, at start-up (`carry_on_at_startup`) and in the trim sweep. Ending is re-runnable,
so its queued and held messages are always marked undelivered in the end. A run cancelled
while the Pi switch is off ends at once, but nothing of Pi is loaded to end its team: the
team's rows end at the first sweep once the switch is back on (M4 SW-09, T4T5 G-a).

## The run view

The team node's row carries `collaboration_events`, the stage view's Collaboration fold:
messages sender to receiver (with id, delivery count, a short preview), each review round with
its version and views, each owner wait with its answer, and the decision. It is rebuilt from
the tables at each step of the loop, so a resumed run shows the whole story. Members' turns
show as the node's children, with their model, thinking and cost; failures are red.

## Settings read back (R2 B16, LR8)

Before a member's first model call, its turn checks the running Pi's settings against the
pins (provider, model, thinking, tools, role, add-ons, image) and refuses the member on any
mismatch. Every listed add-on is read back as loaded: `pi-tldr` by its `tldr` tool,
`pi-image-trim` by the box's launch record (its extension entry in the command and
`PI_IMAGE_TRIM` not off), since it brings no tool or command of its own.

## Tests (no model, no network)

`tests/test_runner/pi_team/` (leader loop units, project copies, stage rows, and #37's
tables) and `tests/test_runner/pi_parking/test_team_runs.py` (whole workflows on the test
server: done, P1 counts while paused, P2 two pauses, failed team and stage row, first node
through restarts, input defaults at start, resume and fork, bad configs at resume and fork,
G-a sweeps, the run view). Every team test ends with `check_invariants` (I1–I8 plus the act
rules) through an autouse teardown. Tests are named by the R2 rule they prove
(`test_b9_...` to `test_b16_...`), or by the M4 switch-on item (`test_sw..._`):
`pi_team/test_schema_version.py` (SW-12, SW-13), `pi_team/test_role_snapshots.py` (SW-25),
`tests/test_pi_agent/test_member_tree.py` (SW-25, SW-51, SW-27), the `test_sw51_` project
copy tests (SW-51), the `test_sw09_`/`test_sw32_` workflow tests (SW-09, SW-32) and
`pi_parking/test_settings_wait.py` (SW-85: settings changed while a Pi step or a team
waited, tests 1-7). Run them on SQLite and on the Postgres tier:

```bash
uv run pytest tests/test_runner/pi_team tests/test_runner/pi_parking tests/test_pi_agent
TEMPER_TEST_DATABASE_URL="$(scripts/test-postgres.sh url)" uv run pytest tests/test_runner/pi_team tests/test_runner/pi_parking
```

## Not built yet

`edges` (refused at run start and again at the team node, B7), obligations, and, each
refused with a plain sentence (M4 SW-04, [pi-agent.md](pi-agent.md) "A team stage"):
unanimous mode, `fresh_each_round`, `continue_from`, private children, parallel member
turns; a notebook-write tool or
sending lessons home (M3), the Team page itself (Frontend's; its API is built:
[pi-team-api.md](pi-team-api.md)), and switching it on anywhere but a private test copy.
