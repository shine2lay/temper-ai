# The gate in front of master

Nothing reaches `master` on `shine2lay/temper-ai` that GitHub's checks have not passed:
lint, types, the tests and the frontend. Once it does reach master, temper puts it live by
itself, when no run is going, and takes it back out if it turns out to be unwell.

There is one temper: the live one. Nothing here builds a test copy of it. Until
2026-10-08 this machine built a whole throwaway temper for every pushed commit and put a
smoke set through it; the owner stopped that ("only use the live temper, no more test
temper"), and GitHub's browser tests no longer start a short-lived temper of their own
either (they run against the commit's built pages only; [testing.md](testing.md)). So the
live check after a deploy is now the only look at the code on a real temper, and the
revert behind it is what puts a bad land right.

This page is for the owner, the next agent, and the bad evening when it has to be
switched off.

## What happens when you land something

```
wt land                 (in a temper-ai worktree)
  │
  ├─ pushes your branch to GitHub
  ├─ GitHub runs: lint, typecheck, tests, frontend, e2e      a few minutes
  │    (e2e: the browser tests that need no temper; none is started)
  └─ this machine posts: temper/boxes                        at once
       the commit is recorded; nothing is built, no temper is started
  │
  ├─ any red   → nothing moves; you get the failures and their links
  └─ all green → master fast-forwards to your commit and is pushed
       │
       └─ temper-ci notices master moved
            ├─ waits until no run is going on the live temper, then two quiet minutes
            ├─ asks temper-deploy to restart the server and worker
            ├─ looks at the live thing: check, hooks, one $0 run, the page, then
            │    on quiet $0 runs: an ordinary run's box environment, and the
            │    owner's controls: stop and resume, a gate answered through the API
            │    (and the Pi pins: shown in the report, never counted)
            ├─ fine     → this commit becomes "the last good one"
            ├─ owed     → a part met someone else's run and stepped aside: temper
            │             stays on it, and tries that part again once no run is going
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
* A live check that ended owed (below) is finished before anything newer is deployed on
  top, even when master has moved on meanwhile.
* `temper-ci deploy <commit>` by hand is not held: that is a person's call.

## Where everything lives

| Thing | Path |
|---|---|
| the gate's code | `scripts/temper_ci/` in this repo (`gate.py`, `deploy.py`, `live_checks.py` (the owner's controls, tried live), `stack.py` (the git mirror), `report.py`, `shot.py`) |
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
them per commit any more. The deploy's live check runs `smoke_test`, `ci_slow`,
`gate_smoke` and `ci_box_env` on the live temper; the rest (`ci_parallel`,
`ci_run_token`, ...) only by hand.

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
run, the page, and then the owner's own controls (below). It also runs the Pi pin check (`scripts/pi_pins_check.py --json`,
model-free and read-only; [pi-lane.md](pi-lane.md), "The pins") and shows what it says,
but never counts it: the pins match (`ok`), a mismatch naming the pins or a check that
couldn't run (`FAIL (doesn't block)`), or not set up (`info`). A pin that's off already
stops every Pi run at the Pi lane's own preflight, and a revert would put no pin right.
All of it goes on the commit's report under "After it went live" and in `temper-ci
status`.

### The owner's controls, on runs of its own

What the owner does to his live Projects is tried on the live temper after every deploy,
each on a $0 run of temper-ci's own, started with temper-ci's key
(`scripts/temper_ci/live_checks.py`):

* **an ordinary run's box environment**, first: a `ci_box_env` run, and its one step,
  must complete (it fails when a box sees a name it must not; it prints names, never
  values, and the look copies none of its output; [boxes.md](boxes.md)). It looks at its
  own box, an ordinary run's: Pi member boxes are not covered (Security's watch covers
  those during a Project). It fails closed: an error, a timeout, or a cancel by anyone
  but temper-ci itself fails it (Security);
* **stop, then resume**: a `ci_slow` run (`seconds: 40`) is stopped a few seconds into
  its long step, must leave a checkpoint, is resumed, and must complete;
* **a gate answered through the API**: a `gate_smoke` run parks at its gate; temper-ci
  answers it (`POST /api/runs/{id}/approve/decide`), the run must complete, and the
  decision must name `temper-ci` as the caller.

They are quiet: every run the live check starts (these, and the free `smoke_test`) says
`"notify": {"question": "off", "stuck": "off", "failed": "off", "finished": "off"}`, so
none of them sends the owner a notice. They still show in the dashboard's plain run list
(temper has no way to hide a run), never on the Team page.

They tidy up after themselves: pass or fail, before its verdict each part cancels any run
of its own that has not ended. A run of its own still going after that fails the part,
because a run left waiting would hold every later deploy, and this deploy's revert too.

They never run beside someone else's run. A box of temper-ci's own up while a Team
Project runs would be a STOP for Security's watch of that Project, and the owner's runs
come first anyway. The deploy already waits until no run is going, so the look normally
has the temper to itself; if someone's run is going all the same, a part does not start,
and a part under way cancels its own runs at once (it looks every 10 s). That part is
**owed**: not passed and not failed. Owed is never a pass (Security's conditions):

* Temper stays on the new commit, but it is not recorded as the good one to go back to:
  `last good` stays where it was, and `temper-ci status` shows the commit, the owed
  parts, which look in a row this is, and the ids of the runs they stepped aside for.
* A part stepped aside only when temper-ci itself cancelled its runs and they ended with
  no box of theirs left up (docker, by the run's `temper.execution_id` label). A run of
  its own still going, a box still up after a minute, or docker unable to say: the part
  fails.
* What is owed is kept in `deploy.json`, so it outlasts a restart of temper-ci. A record
  of it that is missing or cannot be read fails what it owed; a `deploy.json` that cannot
  be read is kept aside, the owner is told once, and no commit counts as good until one
  passes its whole live check.
* Once no run has gone for two minutes, the same wait as a deploy, temper-ci tries just
  the owed parts again, before anything newer goes on top. When they pass, the commit is
  good; one that fails fails the look like any other.
* The third look in a row at one commit that ends owed fails it: a temper never quiet for
  long enough does not keep an untried commit live for ever.

Nobody is told about an owed part: nothing is wrong yet. The free run can be owed the
same way; the dashboard then only has to come up, and is looked at again, run and all,
with the free run. The box environment can be owed too (Security: failing it would only
revert, and the revert waits for the runs as well). A box of the look's own that is up
when a Pi member's box starts still trips the watch's quiet-window STOP, which is
intended. temper-ci's log (`gate.log`) has a line for each step-aside (whose run, and
which runs of its own it cancelled), each try again and each outcome: ids and names only.

The write guard is not tried here (Security's call). The live guard records writes
rather than refusing them (`GET /api/guard` shows mode `record`), so a check that a box's
key is refused cannot pass on the live temper, and probe writes would only add to the
`seen` counts the switch to enforce is decided on. It joins the look once the live guard
enforces; until then `ci_run_token` keeps that check for a temper whose guard enforces,
run by hand.

If any of the parts that count fail (an owed part has not, yet):

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
* One temper only: nothing here builds or starts a test copy of temper, and neither does
  GitHub (its e2e job serves the commit's built pages with no temper behind them).
* What the live check starts on the live temper is $0, quiet (notify off) and tidied away,
  pass or fail.
* The gate looks only at commits the owner pushed to a branch *of this repository*. A
  stranger's pull request never starts anything here; that is the whole reason there is
  no self-hosted GitHub runner. A fork PR's commit is vouched for only if the owner reads
  it and asks for that commit by hand.
* Real runs are never cancelled, paused or restarted. temper restarts only through
  `temper-deploy`, and temper-ci asks for that only after two minutes with no run going
  (a person's `temper-ci deploy` excepted).
