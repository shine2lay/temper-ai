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
answer without asking again. Slack and Telegram resume it for you.

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

## Trying it

`ci_gate_rounds` is all of this with no model call: `review` waits for an
approval each round and always says "again", so it runs out after round 2
(give `verdict: done` to let it pass). `frontend/e2e/gateRounds.spec.ts`
drives it: stale, simultaneous and repeated approvals, the red step, Resume.
Model-free tests: `tests/test_observability/test_gate_approvals.py`,
`tests/test_observability/test_gate_restarts.py` and
`tests/test_stage/test_running_out_of_rounds.py`.
