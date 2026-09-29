# The gate in front of master

Nothing reaches `master` on `shine2lay/temper-ai` that has not been run, for real, on
this machine. Once it does reach master, temper puts it live by itself and takes it back
out if it turns out to be unwell.

This page is for the owner, the next agent, and the bad evening when it has to be
switched off.

## What happens when you land something

```
wt land                 (in a temper-ai worktree)
  │
  ├─ pushes your branch to GitHub
  ├─ GitHub runs: lint, typecheck, test              ~2 min
  └─ this machine runs: temper/boxes                 ~3 min
       a whole throwaway temper, built from your exact commit,
       with its own database, its own ports, no model keys,
       Slack and Telegram off, every run in a box
  │
  ├─ any of the four red  → nothing moves; you get the failures and their links
  └─ all four green       → master fast-forwards to your commit and is pushed
       │
       └─ temper-ci notices master moved
            ├─ waits until no run is going, restarts the server and worker
            ├─ looks at the live thing: check, hooks, one $0 run in a box, the page
            ├─ fine     → this commit becomes "the last good one"
            └─ not fine → a revert commit back to the last good one, through the same
                          gate (it passes at once: its files already passed), temper
                          restarts onto it, and you get a DM saying what failed
```

A change that only touches writing (`docs/`, `*.md`, `README`) passes `temper/boxes` at
once. So does a commit whose files are exactly those of a commit that already passed —
which is why a revert is quick, and why a rebase that changed nothing does not sit
through the stack again.

## The eight things the throwaway temper has to do

Run `temper-ci check <commit>` to watch it happen. Each one is a thing that has broken
before, or that would be expensive to find broken in front of a person:

| # | What | Why it is in the set |
|---|------|----------------------|
| 1 | a plain run | the engine starts, runs, and finishes |
| 2 | parallel branches with a nested stage | the fan-out, the join, and a stage inside a branch |
| 3 | a gate answered through the API | a run can wait for a person and carry on |
| 4 | Stop, then Resume | checkpoints are written and can be picked up |
| 5 | a fork | a finished run can be branched from a point in its past |
| 6 | the server restarted mid-run | a deploy in the middle of a run does not lose it |
| 7 | the page of a finished run | the UI renders it (screenshot in the report) |
| 8 | the public hooks | unsigned requests are refused; signed test entries from Slack, Telegram, Linear and Notion are taken |

All eight use script agents only, so a check costs $0. There are no model keys in the
box at all — if something ever tries to call a model, it fails rather than spends.

## Where everything lives

| Thing | Path |
|---|---|
| the gate's code | `scripts/temper_ci/` in this repo (`stack.py`, `smoke.py`, `gate.py`, `deploy.py`, `report.py`) |
| the command | `temper-ci` → `scripts/temper-ci` |
| its state | `~/.local/state/temper-ci/` (`gate.json`, `deploy.json`, `reports/`, `work/`, `mirror/`) |
| the reports | `~/.local/state/temper-ci/reports/<commit>/` — `report.html`, `report.json`, screenshots |
| the watcher | `systemd --user` unit `temper-ci.service` |
| the compose files | `docker-compose.yml` + `docker-compose.ci.yml` (the box's overrides) |
| GitHub's side | `.github/workflows/ci.yml` |

## Commands

```bash
temper-ci status              # what is being checked, the last deploy, the last good commit
temper-ci check <commit>      # run the whole thing by hand (also posts the status)
temper-ci check <commit> --no-post     # ... without telling GitHub
temper-ci watch               # the loop the service runs
temper-ci report <commit>     # where that commit's report is
temper-ci deploy <commit>     # restart onto a commit and check it live (the watcher does this)
```

## The throwaway stack, and why it cannot hurt anything

A box is `temper-box-<commit>`: its own compose project, its own volumes, its own
database, and ports picked free at the time. It mounts a worktree of that exact commit.

It never touches the live stack because:

* different compose project → different containers, different volumes, different network;
* different ports → nothing is taken from the live server;
* `TEMPER_SLACK_ENABLED=false`, `TEMPER_TELEGRAM_ENABLED=false`, and no model keys → it
  cannot speak to anyone, inside or outside;
* every run it starts is stamped `ci_box: temper-box-<commit>` in its inputs.

And it is checked, not just intended: before and after every check, `temper-ci` records
the live containers (their ids, start times and volumes) and afterwards asks the live
database whether any run carries that box's stamp. If either has changed, the check
fails on that alone, whatever the smoke set said.

When the image's inputs change — `Dockerfile`, `pyproject.toml`, `uv.lock`,
`package.json`, `package-lock.json`, `docker-compose*.yml` — the box builds a fresh
image instead of reusing the live one, and the report says so.

## Every way into master, and where its gate is

| Who | What they do | Gate |
|---|---|---|
| you, or an agent, with `wt land` | pushes the branch, waits for all four checks, then fast-forwards master | `land: gated` in `~/.config/wt/wt.yaml` |
| the EPD driver (`epd-ship`) | opens a pull request; never merges | branch protection: the PR cannot merge until the four checks pass |
| Linear and Notion agents (`OpenPullRequest`) | open a pull request; the tool refuses protected branches outright | same |
| host scripts (`scripts/epd/*`) | open pull requests only | same |
| another chat, by hand | `git push origin master` | GitHub refuses it: master is protected and force pushes are off |

Branch protection is the floor under all of it. `wt land` is the pleasant way through;
protection is what makes it the *only* way.

## The emergency switch

If the gate itself is broken — the watcher is down, docker is wedged, the check cannot
pass a commit that is plainly fine — and something must go to master now:

**An agent must never do this. It is the owner's, by hand, and it is written here so it
can be done quickly and put back.**

1. Open <https://github.com/shine2lay/temper-ai/settings/branches>.
2. On the `master` rule, either:
   * untick **Do not allow bypassing the above settings** (lets an admin push through), or
   * untick the failing check under **Require status checks to pass**, or
   * **Delete** the rule outright.
3. Push what has to go.
4. **Put it back the same day.** The rule should be: require `lint`, `typecheck`, `test`
   and `temper/boxes`; require branches to be up to date; include administrators; no
   force pushes; no deletions.

From a terminal, the same thing:

```bash
# See what the rule is now (keep this output — it is how you put it back)
gh api repos/shine2lay/temper-ai/branches/master/protection > /tmp/protection-backup.json

# Turn it off
gh api -X DELETE repos/shine2lay/temper-ai/branches/master/protection

# ... push what must go ...

# Put it back exactly as it was
temper-ci protect        # writes the rule described above
```

If you only need the *machine* half out of the way — GitHub is fine, the box check is
the problem — the smaller switch is to stop the watcher and post the status yourself:

```bash
systemctl --user stop temper-ci
gh api -X POST repos/shine2lay/temper-ai/statuses/<commit> \
  -f state=success -f context=temper/boxes \
  -f description="passed by hand: <why>"
```

That leaves lint, typecheck and test still standing in front of master, and it leaves a
trail: the status says a person did it and why.

## When the deploy goes wrong

The watcher restarts temper onto the new master once no run is going, then looks at it:
`temper-deploy check`, `temper-deploy hooks`, one $0 run in a box, and the page. If any
of those fail:

* it makes a revert commit back to the last good commit and takes it through the gate
  (which passes it at once, since those files already passed);
* it restarts temper onto the revert;
* it DMs the owner: what failed, which commits went out, what was taken back.

`master` never moves backwards — the history keeps the bad commit and the revert both.
`temper-ci status` shows the last good commit and the last deploy at any time.

## The rules this gate keeps

* Agents never switch protection off, and `wt` has no bypass flag.
* A check runs only for a commit pushed by the owner to a branch *of this repository*.
  A stranger's pull request never starts anything here — that is the whole reason there
  is no self-hosted GitHub runner. A fork PR can be checked only if the owner reads it
  and asks for that commit by hand.
* One check at a time, so two lands cannot fight over docker.
* The live database, the live containers and the live Slack and Telegram connections are
  never touched by a check.
* Real runs are never cancelled, paused or restarted; temper restarts only through
  `temper-deploy`, and only when nothing is running.
