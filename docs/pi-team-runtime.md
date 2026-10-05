# The team runtime: leader mode and review rounds — switched off

A `strategy: team` stage ([pi-agent.md](pi-agent.md), "A team stage") runs as one node,
`<stage>.team`. That node runs the leader loop (`temper_ai/pi_agent/team_leader.py`,
`LeaderTeam`, `run_team_node`), built on the team's messages and inboxes
([pi-team-messages.md](pi-team-messages.md)) to Architecture's rules (R2 B7–B16, PARK P1/P2,
the T4T5 bindings, `pi-agent-proofs/M1/answer-1.md`).

Everything is behind `TEMPER_PI_AGENT` (default off). With it off, a team stage is refused
at load ("Unknown strategy: 'team'") and nothing here is imported. In external mode the run
box needs the switch too.

## Starting

The team node runs `check_team` again when it starts, with the goal it was handed, because
a resume or a fork never runs the run-start check and a goal mapped from an earlier node is
only seen here. Any problem fails the node red ("the team can't start: ...") before any
member is set up. The goal comes from the run's filled inputs, so a declared `default:`
counts (docs/reference/workflow-inputs.md).

Then the team opens (`Team.open`, which refuses reserved member names again as a backstop),
each member gets its own git copy of the project, and the leader is sent the goal. A team
node may be a workflow's first node.

**Project copies** (`ProjectCopies`): each member works on a clone of the run's workspace,
committed content only, in its own folder. The copies' git data is kept outside every
member's folder, so nothing a member writes can change how Temper's git runs. Untracked and
ignored files (`.env`) are never copied; a workspace with uncommitted changes is refused
with the reason. The copies are separate, but the project is shared: Temper moves every
reviewer's copy to the leader's review commit. That reopens A7's shared-file side channel
(the leader can pass anything to the reviewers through the files it commits, outside the
message rules), which the first slice accepts.

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
that turn has finished (completed, or accepted by the owner at a recovery wait). Temper
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
record and the `leader`. After done, Temper takes no new work: pending messages are marked
undelivered and late sends are refused.

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
  `stop`; continue and guide restart the count. Anything else is not taken as an answer and
  the owner is asked again. It never expires, resumes or cancels by itself, and it is never a
  generated gate node with a loop back: there is no overall round limit, and a team stage
  takes no `timeout_seconds` and no failure hold.
- **Stalled**: nothing is running, nothing waits to be delivered, no review is open and the
  leader hasn't said done. The owner answers `nudge` (optionally with words for the leader)
  or `stop`.
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
| owner stop (pause, stalled, recovery) | failed: "stopped by the owner ..." (`decision: stopped`) | failed | failed |
| a member's turn failed, the team ended early | failed, with the reason | failed | failed |
| cancelled | cancelled; queued and held messages undelivered (B12) | cancelled | cancelled |

A failed team node fails its stage too, never completed (B13); the tolerant stage rule
stays for every other stage (`fails_stage` on the node, `stage/executor.py`).

A cancelled run's team is ended again later if the process died between ending the run row
and ending its team (`runner/parked.py` `_end_pi_teams`, `end_cancelled_pi_teams`): when a
team opens, at start-up (`carry_on_at_startup`) and in the trim sweep. Ending is re-runnable,
so its queued and held messages are always marked undelivered in the end.

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
(`test_b9_...` to `test_b16_...`). Run them on SQLite and on the Postgres tier:

```bash
uv run pytest tests/test_runner/pi_team tests/test_runner/pi_parking tests/test_pi_agent
TEMPER_TEST_DATABASE_URL="$(scripts/test-postgres.sh url)" uv run pytest tests/test_runner/pi_team tests/test_runner/pi_parking
```

## Not built yet

`edges` (refused at run start and again at the team node, B7), obligations, unanimous mode,
`fresh_each_round`, `continue_from`, parallel member turns, a notebook-write tool or
sending lessons home (M3), the Team page (M3), and switching it on anywhere but a private
test copy.
