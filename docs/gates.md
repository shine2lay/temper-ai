# Approvals and loops

A step with `gate: true` waits for a person before it runs. A step with
`loop_to:` can send the run back for another round. This page is how both
behave: what an approval answers, what happens across restarts, and what a
loop does when it runs out of rounds.

## Each wait is its own

Every time a gate starts waiting it records one event, and that event **is**
the wait. It carries:

| Field | Meaning |
|---|---|
| `event_id` | the wait's identity; an approval names it |
| `path` | where the step sits: `review`, or `ship.approve` inside stage `ship` |
| `round` | which time this step waits in this run: 1, then 2 after a loop sends it back, … |
| `status` | `waiting`, `approved`, `rejected`, or `replaced` (see restarts below) |

`GET /api/runs/{id}/gates` lists the waits still open, one entry per wait,
with these fields. `GET /api/runs/{id}/decisions` lists every wait the run
ever opened, with who decided it, when, and with which request id.

## Approving

```
POST /api/runs/{id}/approve/{step}
{"event_id": "…", "request_id": "…", "response": "…", "answers": [...], "by": "Ann (Slack)"}
```

Everything in the body is optional.

- **`event_id`** names the wait being answered. It only takes effect while
  that wait is still waiting: the decision is a compare-and-set, so of two
  approvals at the same moment exactly one wins. Every caller temper ships
  sends it: the dashboard, Slack, Telegram, Notion and the MCP tool.
- **`request_id`** names the click. The same request id again returns the
  first answer (`"repeated": true`) and changes nothing, so a retried
  request never answers the next round.
- **`{step}` alone** (no `event_id`) still works when exactly one wait of
  that name is open, as EPD's `approve_pr.py` and the CI smoke do. `{step}`
  may be the name (`approve`) or the path (`ship.approve`).

The reply describes the wait it decided (`event_id`, `path`, `round`,
`answered_by`, `answered_at`, …).

### Refusals

| Status | `detail.reason` | When |
|---|---|---|
| 409 | `already_answered` | the wait was approved already (another tab, Slack, a second click); says by whom and when |
| 409 | `already_rejected` | the wait was rejected, or the run was stopped there |
| 409 | `replaced` | the run was picked up again and asks in a newer wait (`replaced_by`) |
| 409 | `several_waiting` | name only, and several waits of that name are open (same-named steps in two stages); `waiting` lists them; send `event_id` or the path |
| 404 | | no such wait, or the `event_id` is for another step |

`detail.message` is a plain sentence; every caller shows it as it is,
never as a silent no-op.

### A run that is not running

If nothing is running the run (temper restarted while it waited), the
approval is **kept** and the reply says `"needs_resume": true` with a
message: the run needs Resume, and when it comes back it goes on with this
answer without asking again. Slack and Telegram resume it for you. (A Pi run
that let its worker go at the gate needs no Resume: the answer carries it on,
see [Pi workflows](#pi-workflows).)

**Reject** and **Cancel** keep their meaning: they stop the run. A reject or
cancel never overwrites an approval that got there first.

## Restarts

When a run is picked up again (Resume, or the pick-up after a restart) and
reaches a gate it waited at before, it looks at that step's earlier waits
first:

- an approval nobody used yet (given while the worker was down) **is** the
  answer: the step runs with it, and nobody is asked again;
- a wait still open from before is waited on again, so buttons already sent
  keep working;
- any other open wait at that step (a duplicate, or one recorded before waits
  had paths) is closed as `replaced`; a button pressed on it says it was
  replaced and changes nothing.

A run therefore never has two open waits for the same step and round. A
worker still polling a wait that a later attempt replaced stops.

## Loops that run out of rounds

```yaml
- name: review
  gate: true
  loop_to: review
  max_loops: 2
  on_max_loops: fail
  loop_condition: {source: review.structured.verdict, operator: equals, value: again}
```

When `loop_condition` still asks for another round after `max_loops`
rounds, `on_max_loops` decides:

| Value | What happens |
|---|---|
| `silent` (default) | the run goes on with the last round's result |
| `ship_with_open_issues` | the run goes on, and the last verdict is written to the workspace's known issues for later steps |
| `fail` | the step fails with the reason `ran out of rounds: 2 of 2 (it still wanted to go back to 'review')`, and the run fails |

A step that ran out is stored as failed, with the reason, in its event and in
its checkpoint, and the run page shows it red with that reason. **Resume**
runs it again, and whatever used it, with the loop's count kept: no new
budget. If it still asks for another round it fails again the same way, so
the run cannot finish green unless the step now passes. A gated step asks
again before that rerun.

## Pi workflows

A workflow with a Pi step (`type: pi`, [pi-agent.md](pi-agent.md)) is a Pi
workflow (`temper_ai/stage/pi_workflows.py`). Three things differ for it;
every other workflow behaves as described above.

**A gate lets the worker go while it waits.** When a gate in a Pi workflow
starts waiting, the run saves where it is (a `gate_parked` checkpoint whose
id is the wait's event id, so each round has its own), writes its attempt down
as `waiting` with a `parked` note (the wait's id, path and round), and its
worker lets go: the run's box exits, or in in-process mode its thread ends.
The run shows "waiting on you" with nothing running for it. Steps running
beside the gate finish first and are kept.

Your answer carries it on by itself, through Resume's own path: a new box (or
thread) starts from the saved checkpoints, uses the answer without asking
again, and runs nothing that already finished. The reply says
`"carries_on": true` whichever of these starts it (only a run that could not
be started says `"needs_resume": true` instead). It works however long the
run waited and across restarts:

- the approval carries it on when the worker has already let go;
- the worker carries it on as it lets go, when the answer came first (in a
  box, the worker's reaper does it once it sees the box gone);
- an answer given while the worker or server was down is applied when it
  comes back (the reaper, or the server at start-up).

Whoever comes first claims the parked attempt with a compare-and-set, so the
run is carried on once; a second Resume meanwhile gets a 409. The attempt that
waited stays in the run's history as `parked`.

A parked run never expires, never carries on by itself and never starts a new
run. A restart does not mark it interrupted, and the start-up pick-up (with
its 12-hour limit) leaves it alone: only an answer moves it. **Reject** or
**Cancel** ends it (`cancelled`), as for any run. Stale, parallel and repeated
approvals get the answers above (409s, `repeated: true`). You are told once,
when the wait starts; there are no reminders. The Pi step's own "what next"
waits are the step's and still hold its worker (pi-agent.md).

**Resume works before anything finished.** A Pi run often starts by asking
you something, so Resume of a Pi run with no checkpoint yet starts it again
from its first step, instead of refusing with "No checkpoints found": a wait
that step had opened is waited on again, not asked twice, and a first-step
Pi step is handed back to the step like any other node. Other workflows still
need a finished step to resume from.

**Every loop must say `on_max_loops: fail`.** A Pi workflow must never count
as done because a loop ran out of rounds, so `silent` (the default) and
`ship_with_open_issues` are refused when the run starts, with the reason:

```
Node 'review' loops back to 'review' with on_max_loops: silent. In a workflow with a Pi step
every loop must say on_max_loops: fail, so running out of rounds stops the run red instead of
letting it count as done.
```

`temper check` names such loops before anyone starts the run.

## Trying it

`ci_gate_rounds` is all of this with no model call: `review` waits for an
approval each round and always says "again", so it runs out after round 2
(give `verdict: done` to let it pass). `frontend/e2e/gateRounds.spec.ts`
drives it: stale, simultaneous and repeated approvals, the red step, Resume.
Model-free tests: `tests/test_observability/test_gate_approvals.py`,
`tests/test_observability/test_gate_restarts.py` and
`tests/test_stage/test_running_out_of_rounds.py`.

`ci_pi_waits` is the Pi workflow version: `ask` waits on you as its first
node, then the Pi step (`agents/ci_pi_talk.yaml`), then `review` waits each
round in a loop that must fail when it runs out (`verdict: done` ships). It
needs the Pi step switched on; its tests run it on L2's stand-in box, with no
model: `tests/test_runner/pi_parking/` (in-process and box modes, restarts,
waits of days, cancel, 409s) and `tests/test_stage/test_pi_loop_rule.py`.
