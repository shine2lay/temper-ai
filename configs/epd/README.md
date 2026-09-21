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

## Versions

Every agent and workflow here carries a `version:` inside its block:

```yaml
agent:
  name: epd_measure
  # 2: two URLs — the live product, plus a data-bearing twin when the live
  #    server has no QA tenant.
  # 3: the live server has its own paper QA tenant, so the whole measurement
  #    happens on the build people actually use; stay inside that account.
  version: 3
```

Bump it when the **contract** changes — what the agent is asked to decide, what
it must write, which tools it may use — and leave a one-line note saying what
changed. Not for typos or rewording. The loader ignores the field (temper reads
`agent:`/`workflow:` and the keys it knows), so it costs nothing at runtime.

It is not decoration: the driver reads these before every stage and writes them
into the bet's `state.json`, so a recorded outcome names the versions that
produced it:

```json
"_versions": {"workflow:epd_measure": 2, "agent:epd_measure": 3}
```

When bet 7 measures better than bet 3, that is the difference between "the loop
improved" and "`epd_measure` v3 asks a different question than v2 did".

Note: `schema_version` is a different thing — a top-level format pin that temper
accepts only as `"1.0"`. Do not use it for this.

## GitHub credential

Ship talks to GitHub over plain REST (`urllib`), not the `gh` CLI: an
unattended unit gets a minimal environment and no login state, and the first
run proved it by losing `gh` off the PATH. The token is resolved by the same
contract the github MCP server publishes (`agent-tools lib/github-mcp.mjs`),
so one credential serves both:

| order | source |
| ----- | ------ |
| 1 | `GITHUB_TOKEN_EPD_LOOP` in the environment |
| 2 | `~/.config/agent-tools/github/identities/epd-loop/token` (mode 600) |
| 3 | `~/.config/agent-tools/github/identities/epd-loop/app.env` (GitHub App) |

`gh auth token` is deliberately *not* in that list — borrowing gh's login
would be the same dependency wearing a hat. Set `EPD_GH_IDENTITY` to use a
different identity. The token needs contents:write and pull-requests:write on
the repository; `master` carries no branch protection, so an ordinary token
squash-merges (no admin bypass needed).

When a stage ever needs *judgement* about a PR rather than the mechanical
merge, the same identity can be handed to an agent as an MCP server —
`github-mcp epd-loop --profile pr-author` — where the profile, not the model,
decides what it may do.

## Screenshots on the PR

A change the owner could see is shown, not only described. The QA browser
(`task_verify`, the build's verify node) takes one picture of each page the
change shows on — at most four, after signing in and getting the page into the
state that shows it — and lists them in its result as `screenshots`
(`[{page, file, shows}]`). Nothing is taken for a change no UI shows.

The files are named `<task_slug>-<page>.png` and written by the playwright
container into its working directory, which `docker-compose.yml` mounts from
`workspaces/browser-output` (a name is resolved against the browser's
workspace root, and playwright refuses anything outside it). The ship stage on
the host moves them into `bets/<id>/screenshots/`, commits them to the orphan
branch `epd-screenshots` of the product repository through the Git Data API
(one commit per ship; `EPD_SHOTS_BRANCH` renames it) and embeds them in the PR
body as `blob/<sha>/…?raw=true` links — pinned to the commit, so a later bet
cannot move an earlier PR's pictures, and served only to someone who can see
the repository. The product's own history never carries them.

## Running it unattended

The driver shells out to `standee`, `gh`, `docker` and `git`. Under
`systemd-run --user` the PATH is a minimal one that does not include
`~/.local/bin`, where the first two live, so pass the caller's:

```sh
systemd-run --user --unit=epd --collect \
    --working-directory=$HOME/temper-ai --setenv=PATH="$PATH" \
    sh -c 'exec > /tmp/epd.log 2>&1; python3 ~/temper-ai/configs/epd/bin/epd_loop.py next --keep'
```

`--working-directory` matters too: a user unit starts in `$HOME`, not the
directory you launched it from.

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
