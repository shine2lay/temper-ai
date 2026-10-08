# The gate in front of master

Nothing reaches `master` on `shine2lay/temper-ai` that GitHub's checks have not passed:
lint, types, the tests and the frontend. Once it does reach master, temper puts it live by
itself, when no run is going, and takes it back out if it turns out to be unwell.

There is one temper: the live one. Nothing here builds a test copy of it. Until
2026-10-08 this machine built a whole throwaway temper for every pushed commit and put a
smoke set through it; the owner stopped that ("only use the live temper, no more test
temper"). So the live check after a deploy is now the only look at the code on a real
temper, and the revert behind it is what puts a bad land right.

This page is for the owner, the next agent, and the bad evening when it has to be
switched off.

## What happens when you land something

```
wt land                 (in a temper-ai worktree)
  │
  ├─ pushes your branch to GitHub
  ├─ GitHub runs: lint, typecheck, tests, frontend, e2e      a few minutes
  └─ this machine posts: temper/boxes                        at once
       the commit is recorded; nothing is built, no temper is started
  │
  ├─ any red   → nothing moves; you get the failures and their links
  └─ all green → master fast-forwards to your commit and is pushed
       │
       └─ temper-ci notices master moved
            ├─ waits until no run is going on the live temper, then two quiet minutes
            ├─ asks temper-deploy to restart the server and worker
            ├─ looks at the live thing: check, hooks, one $0 run, the page
            │    (and the Pi pins: shown in the report, never counted)
            ├─ fine     → this commit becomes "the last good one"
            └─ not fine → a revert commit back to the last good one, through the same
                          gate; temper restarts onto it (waiting, like any deploy,
                          while a run is going), and you get a DM saying what failed
```

`temper/boxes` keeps its old name because master's branch protection and `wt land` wait
for it, and because the way back reads what it records: a revert goes only to a commit
the gate recorded and passed.

## No restart under a run

temper-deploy restarts within 30 seconds of being asked, runs or no runs: runs live in
boxes and carry on in them. temper-ci is what waits. Before it asks for a restart, for a
new master or for a revert, it asks the live temper which runs are not over yet
(`pending`, `queued`, `running`, `waiting`, `cancelling`: the server's own list) and holds
while there are any, or while the live temper cannot say. Once none is going, it waits two
quiet minutes more, so the gap between one run and the next is not taken for a quiet
temper; a run that starts meanwhile starts the two minutes over.

* Lands that arrive while it holds go live together, in one deploy.
* A run parked at a gate, or waiting on a person, is not over: it holds deploys for as
  long as it waits.
* `temper-ci status` shows the hold, since when and why (which runs).
* If a live check fails while runs are going, the owner is told at once and the revert
  waits for the runs. If master moves on first, the newer commit's own deploy and live
  check decide instead.
* `temper-ci deploy <commit>` by hand is not held: that is a person's call.

## Where everything lives

| Thing | Path |
|---|---|
| the gate's code | `scripts/temper_ci/` in this repo (`gate.py`, `deploy.py`, `stack.py` (the git mirror), `report.py`, `shot.py`) |
| the command | `temper-ci` → `scripts/temper-ci` |
| its state | `~/.local/state/temper-ci/` (`gate.json`, `deploy.json`, `reports/`, `mirror/`) |
| the reports | `~/.local/state/temper-ci/reports/<commit>/`: `index.html`, `report.json`, `live.json` (the deploy's live check), screenshots |
| the watcher | `systemd --user` unit `temper-ci.service` |
| GitHub's side | `.github/workflows/ci.yml` |

## Commands

```bash
temper-ci status              # the last deploy, the last good commit, a deploy held for runs
temper-ci check <commit>      # record a commit and post its status by hand (nothing is built)
temper-ci check <commit> --no-post     # ... without telling GitHub
temper-ci watch               # the loop the service runs
temper-ci report <commit>     # where that commit's report is
temper-ci deploy <commit>     # restart onto a commit and check it live, now, runs or no runs
                              # (the watcher does this when it is quiet; by hand, it also
                              # tries a held-back commit again)
```

The `ci_*` workflows in `configs/` were the throwaway temper's smoke set. Nothing runs
them per commit any more; the deploy's live check runs `smoke_test`.

## Every way into master, and where its gate is

| Who | What they do | Gate |
|---|---|---|
| you, or an agent, with `wt land` | pushes the branch, waits for the required checks, then fast-forwards master | `land: gated` in `~/.config/wt/wt.yaml` |
| the EPD driver (`epd-ship`) | opens a pull request; never merges | branch protection: the PR cannot merge until the required checks pass |
| Linear and Notion agents (`OpenPullRequest`) | open a pull request; the tool refuses protected branches outright | same |
| host scripts (`scripts/epd/*`) | open pull requests only | same |
| another chat, by hand | `git push origin master` | GitHub refuses it: master is protected and force pushes are off |

Branch protection is the floor under all of it. `wt land` is the pleasant way through;
protection is what makes it the *only* way.

## The emergency switch

If the gate itself is broken (the watcher is down and `temper/boxes` never comes, or
GitHub's checks cannot pass a commit that is plainly fine) and something must go to
master now:

**An agent must never do this. It is the owner's, by hand, and it is written here so it
can be done quickly and put back.**

1. Open <https://github.com/shine2lay/temper-ai/settings/branches>.
2. On the `master` rule, either:
   * untick **Do not allow bypassing the above settings** (lets an admin push through), or
   * untick the failing check under **Require status checks to pass**, or
   * **Delete** the rule outright.
3. Push what has to go.
4. **Put it back the same day.** The rule should be: require GitHub's checks and
   `temper/boxes`; require branches to be up to date; include administrators; no force
   pushes; no deletions.

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

If you only need the *machine* half out of the way (GitHub is fine, but the watcher is
down), the smaller switch is to post the status yourself:

```bash
gh api -X POST repos/shine2lay/temper-ai/statuses/<commit> \
  -f state=success -f context=temper/boxes \
  -f description="passed by hand: <why>"
```

That leaves GitHub's checks still standing in front of master, and it leaves a trail: the
status says a person did it and why.

## When the deploy goes wrong

Once no run is going (above), the watcher asks `temper-deploy restart` for the new
master, then waits for that restart to have happened: for temper-deploy's record of a
restart that began after the ask and carried the commit
(`~/.local/state/temper-deploy/last-restart.json`). It looks every 10 s. Nothing counts
while temper-deploy still holds a request (`request.json`): not an older record that
already names the commit, because temper-deploy restarts whenever it is asked, and
looking before that restart is done sees temper half-way down; and not even its own
restart's record while someone else's restart waits behind it, since that one starts
straight after. Only once temper-deploy has let the request go with no new restart does
the old record answer: on the commit, temper is already on it (a restart under way when
it asked carried it); not on it, nothing went live. A restart still waiting after an hour
is left to the next loop, which asks again.

Then it looks at the live temper: `temper-deploy check`, `temper-deploy hooks`, one $0
run, and the page. It also runs the Pi pin check (`scripts/pi_pins_check.py --json`,
model-free and read-only; [pi-lane.md](pi-lane.md), "The pins") and shows what it says,
but never counts it: the pins match (`ok`), a mismatch naming the pins or a check that
couldn't run (`FAIL (doesn't block)`), or not set up (`info`). A pin that's off already
stops every Pi run at the Pi lane's own preflight, and a revert would put no pin right.
All of it goes on the commit's report under "After it went live" and in `temper-ci
status`.

If any of the four fail:

* it makes a revert commit back to the last good commit and takes it through the gate
  (which records it and passes it at once);
* it restarts temper onto the revert: at once if no run is going, otherwise once none is;
* it DMs the owner: what failed, which commits went out, what was taken back, or that
  the revert waits for runs.

One revert at a time: if one is already outstanding, or no commit the gate passed is
there to go back to, it DMs the owner and stops there.

Each failure is said once. The commit is written down as handled (`handled` in
`deploy.json`) and the watcher leaves it alone until master moves on; `temper-ci status`
shows it as held back. The same goes for a commit temper-deploy let go without restarting
onto it (a rebuild needed, which temper-deploy DMs about itself, or a cancel). After
fixing what was wrong, `temper-ci deploy <commit>` tries that commit again.

`master` never moves backwards: the history keeps the bad commit and the revert both.
`temper-ci status` shows the last good commit and the last deploy at any time.

## The rules this gate keeps

* Agents never switch protection off, and `wt` has no bypass flag.
* One temper only: nothing here builds or starts a test copy of temper.
* The gate looks only at commits the owner pushed to a branch *of this repository*. A
  stranger's pull request never starts anything here; that is the whole reason there is
  no self-hosted GitHub runner. A fork PR's commit is vouched for only if the owner reads
  it and asks for that commit by hand.
* Real runs are never cancelled, paused or restarted. temper restarts only through
  `temper-deploy`, and temper-ci asks for that only after two minutes with no run going
  (a person's `temper-ci deploy` excepted).
