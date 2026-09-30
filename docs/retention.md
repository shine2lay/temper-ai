# Trimming old runs

The event log was 13 GB of a 14 GB database, and the history could not be
backed up because of it. `temper trim` fixes that without losing the story of
any run.

## What it drops, and what it keeps

Nearly all the weight is material temper **sent** to a model, not anything that
came back:

| event row | what it holds | size |
| --- | --- | --- |
| `llm.call.started` → `messages` | the whole transcript handed to the model, again on every iteration | 7.4 GB |
| `agent.started` → `input_data`, `agent_config.system_prompt`, `agent_config.task_template` | the agent's setup | 3.0 GB |

Everything that says what *happened* is small: results 700 MB, call outcomes
402 MB, tool results 181 MB, failures 2.4 MB.

So a trimmed run loses exactly those fields and keeps everything else — what
came back, what it cost, how long it took, what failed, what a person decided.
The run page still draws it in full; only the "what exactly was in the prompt"
panels are empty, where the page shows its usual "No data".

The event itself records what went: a trimmed row carries a `trimmed` list of
the field names dropped, so anyone reading the data can tell the difference
between "never recorded" and "trimmed later". The page does not show that list
today; if the empty panels ever cause confusion, that is the thing to surface.

Checkpoint `output` on a trimmed run is cut to the same 5000 characters
`agent.completed` already stores, so a checkpoint never holds less of the
outcome than the event log does. Every other checkpoint column is untouched.

## What is never trimmed

Nothing is dropped for a run that:

- **did not complete** — still going, failed, cancelled, interrupted;
- **asked a person something** — any gate with an answer in it;
- belongs to a **workflow on the keep-whole list** (`epd_*` by default: the
  loop we are actively grading, where the prompt itself is the evidence);
- is **younger than `older_than_days`** (30 by default);
- is one of the **newest `keep_recent_per_workflow`** of its workflow (5 by
  default), so every workflow always keeps complete examples to read.

A resumed run counts as one run whose outcome is the worst of its attempts, so
one bad attempt keeps the whole thing.

The choosing is one plain function, `decide()` in
`temper_ai/observability/trim.py`, with a unit test per refusal.

## Settings

`configs/retention/retention.yaml`, or `configs/retention/local/retention.yaml`
when it exists. Picked up on the next pass — no restart.

## Running it

```bash
temper-trim --dry-run     # what it would do, changing nothing
temper-trim               # do it
temper-trim --limit 500   # stop after 500 runs; safe to repeat
temper-trim --vacuum      # afterwards, hand the freed space back for reuse
```

Weekly, Sunday 04:10, before the 05:00 offsite copy:

```bash
bash scripts/systemd/install-trim.sh
```

It says nothing on success. `~/.local/state/temper-trim/trim.log` gets one JSON
line per pass: how many runs, how many events, how many bytes, and what was
kept whole and why.

## Safe to run while temper is busy

- a run that has not completed is never chosen;
- the outcome is **re-read immediately before** each run is touched, so a run
  that started again between choosing and trimming is skipped;
- each run commits on its own, so stopping half way loses nothing and running
  it again simply carries on;
- a trimmed run is stamped, so a second pass skips it;
- the `--vacuum` afterwards is the plain kind, never `FULL`: it takes no
  exclusive lock and cannot stall a run.

## Which database

Every report and log line begins with the database it changed, as
`host:port/name`.

This is not decoration. Several projects on this machine export a
`TEMPER_DATABASE_URL`, and more than one of them has a database called
`temper_ai`; an inherited value once pointed a dry run at an entirely different
project's database. `temper-trim` therefore ignores an inherited
`TEMPER_DATABASE_URL` and builds its own from the project's `.env`, the same
way `docker-compose.yml` does. To aim it elsewhere on purpose, set
`TEMPER_TRIM_DATABASE_URL`.

## Proving it on a copy first

`scripts/trim_proof.py` copies real old runs into a scratch database, asks the
same questions the run page asks, trims, asks again, and reports any outcome
field that changed. It never writes to the live database.

```bash
uv run python scripts/trim_proof.py --sample 60
```

On 60 real runs: 837 events and 95 checkpoints trimmed, every outcome field
byte-identical, and a backup of them went from 3.69 MB to 1.92 MB.

## What the first real pass did

30 September 2026, the whole log in one pass: **248,813 runs trimmed**, 2,498
left whole. It took 32 minutes and touched nothing that was running.

Where the weight went, measured after:

| | before | after |
| --- | --- | --- |
| `llm.call.started` (the transcript sent) | 7.4 GB | 4.96 GB |
| `agent.started` (the agent's setup) | 3.0 GB | 208 MB |
| the nightly dump of the whole database | 7.9 GB gzipped, and left out | 4.2 GB gzipped, and carried |

The 4.96 GB still in `llm.call.started` is not missed trimming: 248,758
trimmed runs hold 63 MB of it, and 2,498 kept-whole runs hold 4,899 MB. Of
that, **4,817 MB belongs to runs younger than 30 days**, which the weekly pass
will trim as they age. Only 82 MB sits in older runs a rule protects for good
— the failed ones, the ones where a person was asked, `epd_*`, and the newest
five of every workflow.

So the copy settles at roughly one month of sent material plus a small
permanent archive, and it does not grow with the years. `older_than_days` is
the lever if that is still too much: at 7 days it would be about 1.2 GB.

A plain `VACUUM` hands the space back for reuse but does not shrink the file,
so `pg_database_size` still reads 15 GB. That is deliberate — `VACUUM FULL`
takes an exclusive lock and would stop every run on the machine, and the
backup only ever carries live rows, which is the number that mattered here.
