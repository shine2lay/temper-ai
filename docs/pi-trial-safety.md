# A trial on real folders: claim checks, copies, version records, the token scan and the run's account — switched off

What keeps a Pi team trial safe when it works on a real project folder (M4 ADR-M4-12, ADR-M4-09
as amended by ADR-M4-14, ADR-M4-16 and ADR-M4-18). All of it runs only in the Pi lane
([pi-lane.md](pi-lane.md)), which stays switched off until the switch-on checklist is done.

In short:

- the project folder is checked on its real paths when `pi-worker` claims the run, before any
  copy or model call;
- members work in copies of the folder's **committed** content only;
- every version the leader puts up for review, and the approved one, is stored as a version
  record, and `team_version` serves it from there;
- nothing token-like leaves a run: answers, messages, files, version records, the done record
  and the logs are scanned;
- each run uses one account, picked once at its first claim and recorded; a limit is a
  recovery wait on that same account, and an account refusal or a provider error never passes
  for work done.

## At claim (`runner/pi_lane.py` `claim_checks`)

After the preflight and before the run is marked running, `pi-worker` settles two things. A
refusal fails the run red with its `kind`, names why, and nothing is copied and no model is
called.

**The project folder** (`kind: project_folder`, ADR-M4-12, SW-33). Only for a workflow with a
team stage and a workspace. The check is the same function the team's node runs before it
makes a copy (`team_folders.folder_check`, authoritative), on resolved real paths:

- the folder is inside a listed project root (`project_roots` in the team settings) and is the
  top of a git work tree;
- its git folder and its common git folder are inside the roots too (a worktree whose
  repository lives elsewhere fails);
- a link leading outside the roots fails, wherever it is on the way;
- a repository in a format this git can't read is named as such;
- on a fresh start the folder must have a commit and no uncommitted changes to tracked files;
  on a resume or retry, the start commit the copies were made from (recorded under the
  state root) must still exist.

**The run's account** (`kind: account`, ADR-M4-09, -14, -18). See "One account per run" below.

## Copies of committed content only (SW-34)

Each member gets its own git copy (`team_leader.ProjectCopies`): fetched from the workspace at
its start commit and reset to it. Untracked and ignored files (a `.env`, say) never reach a
copy, nor do submodules (fetch and reset run with `--no-recurse-submodules`; a gitlink stays a
gitlink) or LFS content (system git config is off, so no filter runs; a pointer stays a
pointer). git runs hardened (no hooks, no fsmonitor, no system or global config). The copies'
git data lives outside every member's folder. Nothing is ever written to the source repository
except the approved branch, through the host helper's create-only verb
([pi-team-api.md](pi-team-api.md) "The approved branch").

## Version records (`pi_team_versions`, SW-36)

When the leader asks for a review, and again when the trial ends done, `pi-worker` stores a
version record (`team_versions.py`), in the same transaction as the review it belongs to:

| field | what |
| --- | --- |
| `commit`, `start_commit` | the version's commit and the commit the copies started from |
| `files`, `files_total` | each file's path and sha256 (the first 500; a submodule or link shows its `kind` and object id instead) and how many there are |
| `diff`, `diff_bytes`, `truncated`, `note` | the diff against the start commit, cut at 200,000 bytes; when cut, `truncated: true` and a note saying how much was left out |
| `kind`, `review_id`, `round`, `made_by`, `made_at` | a `review` or the `done` version, and where it came from |

The table came with the `pi_` tables' version step 3 (forward only; `pi_turns.account_slot`
came with it). `GET /api/team/runs/{execution_id}/version` serves the newest record, never a
live read of the leader's copy ([pi-team-api.md](pi-team-api.md)).

## The token scan (`pi_agent/token_scan.py`, SW-52)

Everything that leaves a run is scanned before it goes: a member's answer and messages, the
files and diff of a version record (names and contents), the done record, the trial branch,
and every log line of a Pi run. The rules:

- `run_token`: the exact login tokens (and the account ids in them) this process handed to the
  run's boxes, remembered where the hand-off happens;
- `anthropic_oauth_access_token`, `anthropic_oauth_refresh_token`, `anthropic_api_key`: the
  shapes of such tokens, whoever's they are.

A hit is reported by rule name, where and how many, and never the matched text:

- an answer with a hit fails the turn, naming the rules; the answer is withheld;
- a message with a hit is refused;
- a version record with a hit stores no files and no diff, only the rules and paths that hit
  (`withheld`), and a done version with a hit makes no branch (`branch.made: false` with the
  why);
- a log line has the match replaced by `[withheld: a login token]`.

## One account per run (ADR-M4-09, -14, -18)

The team settings name the account slots Pi runs may use (`account_slots`, defaults in
`configs/team/team.yaml`; none in code, so a missing setting allows none) and the
account-room file to pick by (`account_room_file`, set only in the private
`configs/team/local/team.yaml`). Account 1, the base provider's own slot (`anthropic`), is
refused by name wherever a slot is named, and is never picked.

The account-room file is ops' read-only snapshot of each slot's 5-hour and 7-day use
(schema version 1, ADR-M4-18). `pi-worker` reads it once at a run's **first** claim: one bounded
read of a regular file, no links followed. A file that can't be trusted (missing, a link, too
big, not JSON, a duplicate key, an unknown schema or field, a slot listed twice) refuses the
run, naming the file in fixed words: a refusal never repeats a key or a value from the file,
and every refusal's words leave with any login token withheld before they are logged or stored
(SW-52). A slot can't be picked when it has no reading, is `unavailable`, has a
missing, out-of-range or non-numeric figure, a reading 15 minutes old or more (or from the
future), a reset time that has already passed, or 85% or more of its 5-hour or 90% or more of
its 7-day use. Of the slots that pass, the one with the least 7-day use is picked; ties go to
the settings' order.

When none passes, the run is refused at its claim with each slot's figures, or why it has
none, and the reset times known; it never waits and never retries by itself. Start it again
once an account has room.

The pick is recorded on the run's row (`spawner_metadata.pi_lane.account`: `slot`,
`picked_at`, `by: room`, the slot's figures with their reading and reset times, and the file's
sha256 and schema version) before any member works. A second claim of the same run finds it
and keeps it; it is never overwritten. A claim that loses that race (its row was read before
another claim recorded the account) runs on the account the database kept, checked by the same
rules as any recorded account: if the settings no longer allow it, the run is refused. A resume or retry uses the recorded slot even if the
file changed, went stale or is gone; a run that ran before with no account recorded is refused,
never picked again; and a slot the settings no longer allow refuses the run rather than move
it to another account.

Each turn records the slot (`pi_turns.account_slot`, `agent.started` events). The Team API's
run view shows the run's `account` and each turn's `account_slot`; the run page's agent rows
show it too. Inside the member's box the provider stays the canonical `anthropic`: the slot
only decides whose login the host helper hands over (ADR-M4-15).

## How a model call can end (ADR-M4-16)

`accounts.turn_ending` decides it after each turn, on the error path only:

| ending | turn | then |
| --- | --- | --- |
| completed | done | the answer is the member's answer |
| a limit on the run's account | held | a recovery wait naming the slot, the limit and when it resets; retry keeps the same account, model and thinking |
| the account refused the call (disabled, or not allowed for the organization) | red, naming the slot and the refusal | the team (or the single Pi step) stops failed with a plain problem: "account <slot> refused the call (not allowed for this organization); the team was stopped". No recovery wait, no other account, no retry |
| the model refused the request (a safety classifier) | red, naming it | failed turn |
| any other provider error, with or without text | failed | the error text is never shown as the answer |

The refusal is recognised only from a provider error (an HTTP 403 `permission_error` /
`oauth_not_allowed_for_organization`, or the refusal sentences in the error itself), or from a
call that produced no model output at all whose whole result is a refusal sentence. Never from
text inside a normal answer: a member that quotes the refusal sentence in its answer completes
normally. The sentences are shared with the CLI providers' token pool
(`llm/account_messages.py`), whose drop-and-retry stays there: a Pi member's slot is pinned
for the run and no Pi module imports the pool.

## Switching on (not done here)

- the private `configs/team/local/team.yaml` names `account_room_file`;
- `pi-worker` mounts the account-room folder read-only (its own mount; the preflight's
  `account_room` check);
- ops' writer of the file runs (disabled until switch-on).

## Tests (no model, no network)

```bash
uv run pytest tests/test_pi_agent/test_accounts.py tests/test_pi_agent/test_token_scan.py \
  tests/test_runner/pi_lane/test_claim_checks.py tests/test_runner/pi_lane/test_preflight.py \
  tests/test_runner/pi_team/test_account_endings.py tests/test_runner/pi_team/test_team_versions.py
TEMPER_TEST_DATABASE_URL="$(scripts/test-postgres.sh url)" uv run pytest tests/test_runner/pi_team
```

They use fake boxes, throwaway git repositories with planted links, a fake token in each way
out, a scripted limit, a scripted 403, a call with no model output, an error reply carrying
text, and a normal answer quoting the refusal sentence.
