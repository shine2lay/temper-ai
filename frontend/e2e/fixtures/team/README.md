# Team page fixtures

What the `/api/team` routes (and the run page's cancel route) answer, one JSON file per
state and per refusal. The Team page's tests serve these instead of a live Temper.

Each file is:

```json
{"route": "GET /api/team/runs/{execution_id}", "status": 200, "body": {}}
```

## Making them again

From the repository root:

```bash
uv sync --frozen --extra dev        # once, in a fresh checkout
uv run python frontend/scripts/capture_team_fixtures.py
```

The script starts no server and calls no model. It drives the routes on an in-process Temper
with the Pi switch on and scripted Pi members (the harness of
`tests/test_runner/pi_parking/test_team_api.py` and `test_team_outcomes.py`), saves what they
answer, then writes the derived files below. It deletes the old JSON files first and refuses
to finish if a file holds a home folder, a temporary path or a real id. Every name, goal,
role and path is made up.

## Captured

Everything not listed under Derived came from the real routes:

- `status-*`: the switch on (`status-on`), guard `record` and `enforce`, a project problem,
  and off (`status-off`, the 404).
- `roles-*`: the list, not set up, and a list that could not be read.
- `check-*`: a clean check, every problem at once, and each project problem on its own.
- `trial-start-*`: started, started with a note, a repeated request id, and each refusal.
- `run-*`: one file per team state (`starting` to `didnt_start`), plus variants: two open
  waits, a held message, objections at the end, done after guidance, and stopped at each kind
  of wait. `run-404` is a run that is not a team trial.
- `message-*`, `message-read-*`: sent (pending, held, repeated), each refusal, and one
  message opened (a member's and the owner's).
- `answer-*`: each answer that was taken, and each refusal.
- `cancel-*`: the run page's Stop run, its refusal, and a stop after the end.
- `trials-*`: the list, page 2, filtered, running only, and empty.

## Derived

The harness can't reach these states, so each is made from a captured file, changing only
the fields that differ. Each file names its source in `derived_from`.

| File | From | Why |
| --- | --- | --- |
| `run-starting` | `run-running` | No member turn has begun yet: round 0, no turns, only the goal message. The harness's first turn starts at once. |
| `run-interrupted` | `run-running` | `run_status` interrupted, as after a restart; the state reads it before any wait. |
| `run-member-waiting-question` | `run-paused-two-waits` | A member's question as the asked wait; captured, it waits behind the pause. |
| `run-stress` | `run-running`, entries from `run-done` | The page at its limits (Design's stress board): six members in every activity, one with a 40-character name, one with a failed turn, one whose turns used another model; 400 entries (the view's most) with 1,234 earlier ones not shown; a goal with text that looks like HTML. A layout check, not a state of its own. |
| `trials-error` | `trials-list` | The list could not be read (a 500 with the server's plain body). |
| `answer-400-reply-needs-words`, `answer-400-reply-too-long` | `answer-400-guide-needs-words` | An unasked question can't be answered, so its reply checks never run in the harness. Texts word for word from the routes. |
| `message-409-team-not-started`, `message-409-member-ended` | `message-409-team-ended` | Timing the harness can't hold. Texts word for word from the routes. |
| `answer-403`, `message-403`, `trial-start-403` | the matching `-401` | A run's own key trying an owner action; the text comes from `temper_ai/api/caller.py`. |
