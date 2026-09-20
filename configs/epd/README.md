# The EPD loop

A product, design and engineering department as one loop, one bet at a time.

```
report → bet → [owner signs] → tasks → build → ship → measure → report → …
```

Each stage is a function from files to files. Nothing is remembered in a model's
head between stages; everything a later stage needs is written down, which is
what makes the loop resumable, inspectable, and arguable with.

| stage | what it replaces | what it does | writes |
|---|---|---|---|
| `report` | user research | three personas walk a dev stack of `main` in a real browser, then one editor merges the walks and ranks the friction | `report.md` |
| `bet` | the product manager | picks **one** problem from the report, writes the pitch: problem, invariant, appetite, no-gos, and a success threshold **fixed before the work** | `bet.md` |
| *(gate)* | the owner | the only human seat: sign the invariant, edit it, or reject the bet | `decision.md` |
| `tasks` | the engineering lead | three to ten tasks, each with a command and the output that means pass, ordered so each is checkable with only the ones before it | `tasks.json` |
| `build` | the engineers | worktree → plan → implement → review + QA + security in parallel on a deployed dev stack → gate | `build.json` |
| `ship` | release | push, PR, squash-merge, back up prod, deploy the merge commit, seed the QA tenant | `pr.md` |
| `measure` | accountability | on the **live** build: does the invariant hold, was the threshold met, did the friction actually go, and *was that the right threshold* | `outcome.md` |

The next iteration's `report` reads the last `outcome.md`, so the loop learns
from what it shipped rather than from what it intended.

## Why a threshold written before the work matters

A bet that is judged after the fact is always a success — the measurement moves
to wherever the result landed. Here the bet names the number and the method
first, and `measure` is a different agent, on a different run, with the bet in
front of it. Its most valuable output is not `kept`/`iterate`/`killed` but the
paragraph headed **"Was this the right threshold"**, which is the only thing in
the loop that improves the *judgement* rather than the code.

## Layout

```
agents/      epd_*      the loop's own agents (personas, walk, report, bet, tasks, measure)
             task_*     the build pipeline (claim, worktree, plan, implement,
                        review, verify, security, gate, stack up/down, cleanup)
workflows/   epd_*      one workflow per stage; epd_task.yaml is the build pipeline
bin/         epd_loop.py   the driver: state, ledger, stage order, prod deploy
             epd_adopt.py  adopt an in-flight run into the ledger
examples/    rollcall/  the goals and capability profile the loop was built against
```

Agents and workflows are [temper](https://github.com/shine2lay/temper-ai) configs;
the driver talks to temper's HTTP API and to [standee](https://github.com/shine2lay/standee)
for environments.

## Install

temper loads configs from `configs/{agents,workflows,scripts}/local/`, which is
gitignored on purpose. `install.sh` symlinks this repo's files into a temper
checkout, so the repo stays the source of truth and edits land here:

```sh
./install.sh ~/temper-ai
```

## Run

The loop keeps its state in a workspace directory, one per repository:

```
<temper workspaces>/epd/<repo>/
    goals.md     you write this; read fresh every iteration
    profile.md   what the product is and how the code is laid out
    bets.tsv     the ledger: one row per bet, status and outcome
    bets/bNNN/   report.md bet.md decision.md tasks.json build.json pr.md outcome.md state.json
```

```sh
epd_loop.py status                    # the ledger and what happens next
epd_loop.py next                      # run stages until the loop needs you
epd_loop.py approve b001 --invariant '…'   # sign the bet (edited or as proposed)
epd_loop.py reject  b001 --why '…'
epd_loop.py stage ship --bet b001     # one stage on its own files
epd_loop.py down b001                 # tear the bet's stacks down
```

`next` stops at the gate. `--auto-approve` skips it, which is for exercising the
wiring, not for real bets.

Configuration is environment variables, all with defaults for RollCall:
`EPD_REPO`, `EPD_REPO_URL`, `EPD_REPO_CHECKOUT`, `EPD_GH_REPO`, `EPD_BASE_BRANCH`,
`EPD_WORKSPACES`, `EPD_PROD_ENV`, `EPD_PROD_CONTAINER`, `EPD_PROD_ENV_FILE`,
`EPD_QA_EMAIL`, `EPD_QA_PASSWORD`, `TEMPER_API`.

## What it costs

One full bet, measured 2026-09-20 (Opus 5 for the build stages, Fable 5.1 for the
product ones): **$12.57** for build alone — plan 6 min, implement 13 min, review +
QA + security in parallel 18 min, gate. Report and bet are about $1 together.

## Two things it does not do

- **Rate limits.** When every pool token is at its 5-hour ceiling the driver waits
  15 minutes and re-runs the stage, up to 12 times. It does not read the reset
  time out of the response headers, so it can wait longer than it needs to.
- **Rollback.** If `measure` says `killed`, nothing reverts; the bet is recorded
  and the next iteration sees it. `standee rollback` is a manual step.
