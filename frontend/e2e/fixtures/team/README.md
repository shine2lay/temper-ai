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

The journey's files can be made again on their own, leaving every other file as it is:

```bash
uv run python frontend/scripts/capture_team_fixtures.py --only journey
```

The journey's test pins the page clock five minutes after their last event
(`NOW` in `e2e/team-journey.spec.ts`); move it with them.

## Captured

Everything not listed under Derived came from the real routes:

- `status-*`: the switch on (`status-on`), guard `record` and `enforce`, a project problem,
  and off (`status-off`, the 404).
- `roles-*`: the list, not set up, and a list that could not be read.
- `check-*`: a clean check, every problem at once, and each project problem on its own.
- `trial-start-*`: started, started with a note, a repeated request id, and each refusal.
- `run-*`: one file per team state (`starting` to `didnt_start`), plus variants: two open
  waits, a held message, objections at the end, done after guidance, stopped at each kind
  of wait, and a member waiting after a cut-off turn, a failed turn (after a Resume), a
  usage limit, and an answer that named no choice (asked again). `run-404` is a run that is
  not a team trial. The settings wait (contract E24): asked with the pause's continue held
  (`run-settings-changed`), asked again after words that named neither choice
  (`run-settings-asked-again`), changed again before go on, so go on applied nothing and a
  new wait asks (`run-settings-changed-again`), after go on (`run-settings-go-on`) and after
  stop (`run-settings-stopped`). `run-refused-done` is a done Temper refused because the
  leader changed the copy after the review (E14): the round counts as keep going.
- `message-*`, `message-read-*`: sent (pending, held, repeated), each refusal, and one
  message opened (a member's and the owner's).
- `answer-*`: each answer that was taken, and each refusal, including an answer that reaches
  Temper after Stop run closed its question (`answer-404-after-stop`) and one for a question
  Temper already asked again (`answer-409-asked-again-old`).
- `cancel-*`: the run page's Stop run, its refusal, a stop after the end, and a run that
  doesn't exist (`cancel-404`).
- `trials-*`: the list, page 2, filtered, running only, empty, and a trial waiting at a
  settings check (`trials-settings`).
- `answer-200-settings-go-on`, `answer-200-settings-stop`, `answer-409-behind-settings`: the
  settings wait's two answers, and the held question's answer refused while the settings
  wait is open.
- `journey-*`: one trial as the page journey (`e2e/team-journey.spec.ts`) drives it, with the
  journey's tag in its goal and message: started from the form with the owner's key
  (`journey-trial-start-201`), running (`journey-run-running`), running with more entries
  (`journey-run-running-more`), paused after its first round (`journey-run-paused`), the
  owner's continue (`journey-answer-200`, `journey-run-answered`), the owner's message to the
  leader (`journey-message-201`, `journey-run-messaged`), done (`journey-run-done`) and the
  trials list holding it (`journey-trials`).

## Hand-written: free-flowing teams (until the engine is in)

The `flow-*.json` files are written by hand from the free-flowing teams' field list (FLOW E5/E6)
while the engine is being built, so the Team page can be coded against them. They are not made
by the script yet, and running it deletes them; once the engine is in, the script captures them
from a model-free free-flowing team like the files above.

| File | What it shows |
| --- | --- |
| `flow-run-working` | `GET /api/team/runs/{id}` of a free-flowing team: two members working, one idle, one held by its own recovery wait while the others carry on; three shares in the shared version. |
| `flow-run-check-in` | The $100 check-in asked: no turn running, the pause wait open at team level. |
| `flow-run-done` | Done counted: the leader's summary, the shared version's shares in order, turns per member. |
| `flow-events` | `GET /api/team/runs/{id}/events?after=0`: the start of a run's event feed (cursor paging). |

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
| `answer-200-needs-resume` | `answer-200-guide` | The answer is kept but the run isn't running (it can't be carried on in process). The message is the route's `NEEDS_RESUME`, word for word. |
| `answer-409-replaced`, `answer-409-already-rejected` | `answer-409-already-answered` | A later wait took this one's place after the run was picked up again, and the run was stopped at this question; each body is `temper_ai/stage/gate.py`'s `refusal()` for that status. |
| `run-stopped-by-ci`, `run-stopped-by-unknown`, `run-stopped-from-chat`, `run-cancelled-by-ci`, `run-cancelled-by-unknown`, `run-cancelled-from-chat` | `run-stopped`, `run-cancelled` | Who stopped the run and from where: the CI key through the API, a caller Temper can't name, and a chat. Only `outcome.by`, the stop's `by` and `source`, and (for an answer stop) the timeline's `owner_answer` entry for that answer (`answered_by` and `answered_source`, top level and in `data`) change. |
| `run-done-branch-not-made`, `run-done-no-project` | `run-done` | The branch name was taken (`why` "exists"), and a trial with no project (no branch). |
| `run-failed-cant-go-on`, `run-failed-copies`, `run-failed-cant-open`, `run-failed-recorder` | `run-failed` | The other ways a team fails, in the words `temper_ai/pi_agent/team_leader.py` writes them; the problems come from the check's own texts. |
| `run-done-big` | `run-done` | A 4,000-character summary and 500 files in the approved version. |
| `run-stopped-script`, `run-member-waiting-question-script` | `run-stopped`, `run-member-waiting-question` | HTML in the owner's words and in a member's question, which must show as text. |
| `trials-with-reruns` | `trials-list` | A re-run and a fork of the stopped trial, started from the run page (contract A-8): each is its own item after the trial's own run, newest first, with its own run, state, round, cost and caller. Starting runs from the run page is outside the harness. |
| `run-settings-stress` | `run-settings-changed` | The settings wait at its limits (Design's S8): the leader renamed to a 40-character name everywhere; the team's own settings, its 24 add-ons (one removed), the checker's model and four of the maker's settings changed: 30 changes. The question, `settings_changes` and `pins` come from `temper_ai/pi_agent/settings_wait.py`'s `team_subject`, with example digests. |
| `run-paused-long-next` | `run-paused-two-waits` | The question waiting behind the asked one is long (Design's R16). |
| `run-unknown-wait` | `run-paused` | A wait of a kind this page doesn't know (`budget`, made up): the page must fall back to Temper's own question and answers. |
