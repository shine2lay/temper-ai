# Free-flowing Pi teams

A `strategy: team` stage runs a leader and its members as a free-flowing team. It does not run review rounds. Each member keeps one session and its own working copy. Temper keeps one shared version of their work.

See [the message protocol](pi-team-messages.md), [Pi nodes and settings](pi-agent.md), and [the Team API](pi-team-api.md).

## Starting and working

Only the leader receives the goal and starts. Every other member is attached, with `idle_reason: start`, but takes no turn until it receives a message. The leader splits the goal and sends work requests. Once woken, members work in parallel. The default `max_parallel` is the number of members; a smaller explicit value caps running member turns, not the amount of work.

A claim belongs to `(run_id, host_path, participant_id)`. A member never has two writers. The driver fills available slots, then waits for a receipt or checks for messages, owner answers, limits, cancel, and drain. An unsettled act blocks that member's later acts, not another member's.

A member's next turn starts as soon as its previous turn settles. `idle(note?)` says it has nothing to do for now. A turn with no tool calls also goes idle. Pending or newly released messages wake an idle member; a racing idle cannot hide a message. There is no empty-turn-count guard, round limit, or time-based Project pause.

Every turn carries the roster, leader, available tools, its inbox and recorded conflicts. Only the leader's first turn carries the goal. Member messages arriving during a turn are handed into the existing session over Temper's fenced channel; see the message protocol for confirmation and redelivery.

## One shared version

The private team root contains a bare repository, `git/_shared.git`. Each member has its own working tree and git directory. Neither the shared repository nor another member's folder is mounted in a box.

Before a member's turn, with no box writing its copy, Temper commits leftovers and merges the latest shared version into that copy. `share(note?)` records an act; once the turn settles, Temper commits the member's work and merges it into the shared version. The shared branch advances with an expected-old `update-ref` transaction. A racing change cannot be silently overwritten. Share history records version, commit, author, time, note and changed-file counts.

At every sync and share Temper records git's unmerged paths, including conflicts without text markers, and names them in the next framing. A share is refused while a recorded file still contains conflict markers. For binary, modify/delete or rename conflicts without markers, the member's next share after being told is its choice. Temper finishes every merge it starts, including a merge that leaves a member with conflicts to resolve. Git commands and filesystem choices are made by Temper, not by a box operating on another copy.

## Done and closing

Only the leader has `done(summary)`. Temper shares the leader's copy, opens `closing`, stops new claims and lets running turns settle. The decision's boundary is the **done call's timestamp**, not the beginning of its turn.

Done is refused if the leader's share was refused, its copy differs from the latest shared version, a non-system message is still pending for it or was created, released or delivered after the done call, another member shared after the call, or any member wait or failed/uncertain turn remains open. A refused done names its reasons and gives the leader one turn on its own. The leader can carry on or call done again. No objection count substitutes for this check.

A successful record has `kind: flow`, decision, summary, the shared commit and file hashes, ordered shares, per-member turn counts, cost, project, leader and optional branch information. It has no round number. Publishing an optional branch does not publish private records or change the decision.

## Holds, answers and recovery

`ask_owner(question)` records one question (up to 1,000 characters); the member finishes its turn, then only that member waits for the answer. It cannot also call done in that turn. Other members keep working. A second failed turn or an uncertain turn likewise holds only its member. Questions can be presented without parking while turns are running. Once no turn runs and nothing can be claimed, the run registers all answerable waits and parks on all their gate ids with its durable checkpoint and no worker held: answering any one can wake it. Settings questions take precedence over other owner answers.

A failed or cut-off turn is retried once automatically, **only after its box is confirmed gone**. A failure before a box was ever made has no writer to stop and gets the same one retry; a known box without a gone receipt remains uncertain and held. Its incoming messages keep their ids and are redelivered; its outgoing messages and acts are void. The next framing explicitly says any old tool acknowledgments are not carried effects, names voided act kinds and withheld recipients, and distinguishes retained local edits. A second failure opens a typed recovery choice: retry, accept where permitted, or stop. Manual retry/accept also requires confirmation that the old box is gone. Usage-limit interruptions do not consume this retry.

A call-cap or turn-time-limit receipt with the box confirmed gone is a normal turn end: carry its acts and start the next turn. The structured time-limit cause survives stream error wording; Temper clears queued steering, aborts Pi and waits up to 10 seconds for settlement before closing. If the saved session is still incomplete, only that confirmed natural boundary may reopen it at its last settled point; the next framing says its acts and sends **were carried**, not retried, so they must not be repeated. Box defaults are 1,000,000 model calls and 86,400 seconds per turn. These are turn-end safeguards, not work or Project limits.

Run-level holds are the dollar check-in, account usage limit, settings wait, Stop/cancel, lane drain and closing. Member waits or failures prevent done, even while other members are productive.

## Dollar check-ins and spend

`pause_every_usd` defaults to `100`. Once recorded spend reaches that amount since start or the owner's last continue/guide, no new turn starts. Running turns finish; then the owner chooses `continue`, `guide`, or `stop`. Guide sends the owner's words to the leader. Continue/guide records the current spend as the next baseline: if finishing turns overshoot $100 to $155, the next check-in is at $255, not $200.

Spend includes completed, failed, cut-off, retried, superseded and taken-over turns, including compaction. Known usage is written on the fenced running-turn row as calls settle, so a long-running turn can trigger the check-in before its final receipt. A final receipt replaces that turn's usage rather than adding it again; an empty receipt cannot erase already recorded spend.

A check-in has no expiry or stage timeout. It is not a failure, holds no worker, survives restart and makes no model call while waiting. Its wait label names the dollar boundary.

## Account limits

A Project keeps its one account; it never switches to another account to evade a limit.

A five-hour limit parks the team until reset, then carries on automatically only after fresh usage shows room. A weekly limit holds the state through reset, then asks the owner to restart or stop after that same verification. Nothing restarts after a weekly limit without that answer. An unknown limit kind is conservative, not an automatic-resume permission. Limit waits do not expire.

The durable timer checkpoint releases the worker. The lane reaper uses the normal guarded resume path when its timer is due, but a timer alone never permits a turn or an owner restart question. The host helper's read-only `usage <kept slot>` checks the provider's current five-hour, overall weekly and per-model weekly windows, without a model call, login refresh, account choice or room-writer change. Any still-exhausted window keeps the hold; a weekly window makes it a weekly hold. A missing, expired-sign-in, unavailable or stale reading keeps waiting and schedules another check (15 minutes when no usable reset time is known). The page shows the reason and next check.

A ready weekly answer is applied before scheduling another timer; Stop is not hidden behind a usage read. A delayed weekly restart answer is checked afresh before clearing its hold. Once a blocked weekly scope is known, every later reading must include that scope: an overall weekly window cannot stand in for a missing per-model window. Missing scopes keep the hold, including after a previously verified reset. If usage is unavailable or spent again, the team keeps its state and re-arms the wait, rather than starting or spinning on the old answer. Timer events close when checked or stopped, and re-arming updates the same event's next wake time. Concurrent weekly receipts elevate an existing five-hour wait without losing known window scopes or permitting automatic resume. A timer wake refused by a transient preflight condition returns to waiting and schedules another guarded check after 15 minutes; permanent lane/configuration refusals still fail. These Team rules do not change allowance handling for ordinary non-Team workflows.

## Stop, cancel, drain and takeover

Stop and cancel stop new claims immediately, signal every running turn, join their receipts, and confirm each box stopped before ending the team. A kill request alone is not confirmation. Unconfirmed boxes keep their claims; Temper reports the problem instead of starting another writer. Final usage is recorded before end fences close the member channels.

A lane drain also stops claims and settles all current boxes. The page reports `draining`; after restart the same members and sessions continue. Takeover raises each old epoch before stopping its leftover box. Old message, tool and usage callbacks cannot write into the new epoch. No new writer is claimed until the previous box is confirmed gone.

## Settings and compatibility

Settings digest changes open a settings wait before new turns. The owner can continue with the displayed changes or stop. Members affected by an accepted change are re-pinned; kept sessions and existing records are not thrown away.

New Projects, configs and saved settings use `pause_every_usd` and optional `max_parallel`. A non-null `pause_after_rounds` is refused with “start a new Project”; a null field from the old form is ignored. An omitted or null `pause_every_usd` uses the $100 default. An already-run round team cannot be reopened as flow: **start a new Project**. Old round records, views, story and outcomes remain readable, and are never rewritten to look like flow.

The Team API exposes `kind: flow | rounds`. Flow data includes phase, spend and next check-in, open owner questions, each member's state and current work, tools, turns, cost, shared version/history and a cursor event feed. A stopped or interrupted view freezes elapsed time at its recorded end while `as_of` remains current. Compatibility story entries also reach the general run view.

Git sync/share still hold the process-wide ledger lock. Successful operations exceeding 10 seconds log the member and elapsed time; first-Project checks must watch these warnings and tool timeouts before a narrower lock change. A crash between git's merge commit and its conflict-row transaction can lose conflict framing; a durable conflict sidecar is deferred. The files and shared commits are not discarded, but this is not a crash-atomic git/database transaction.

The additive ledger upgrade is forward-only to version 4. Rows remain readable by this build, but rolling back to a pre-FLOW build that knows only version 3 makes Pi refuse the ledger; it does not reverse that upgrade.

## Rule changes (ADR-FLOW)

These are the exact runtime replacements for the earlier team rules:

| Earlier rule | Free-flowing rule |
| --- | --- |
| R2-review: one-at-a-time; concurrent turns not built | Per-member claims; members work in parallel up to `max_parallel`. |
| B6: a team wait blocks the team claim | A member wait blocks only that member; run holds block all new claims. |
| B7: leader mode | Kept: the leader splits the goal and is the only member allowed to call done. |
| B8: one kept session per member | Kept: turns and resumes reuse that member's session. |
| B9: done after a reviewed version | Replaced by F5 closing and R2: the actual done-call boundary, shared-copy checks and no open member wait/failure. |
| B10: pause after review rounds | Replaced by F6 and R4: dollar spend; no expiry, no stage timeout, not a failure, no worker held, durable restart and no model call while paused. |
| B11/B12: team recovery and cancel | Applied per turn; automatic retry once only after confirmed removal; Stop/cancel joins and confirms every box. |
| W: `move_to` / review-copy movement | Removed; only a member's own claim/settle may touch its copy. |
| T4/T5: turns one at a time | Removed; inbox and message fences are per member and epoch. |
| NB6: concurrent shared writers | Closed by separate member copies and an unmounted shared repository; confirmed Stop remains required. A5's other safety rules are unchanged. |
| SW60: revisit concurrent turns | Closed: parallel member turns are built. |
| ADR-M4-11 / ADR-M4-22 | Unchanged: one Project at a time and one account per Project. |

## Verification

The main combined, model-free test exercises leader-first work requests, several overlapping members, two shares per working member, a never-woken member, the shared version, a member's native owner question and reply, a dollar check-in, continue and done. It also checks the actual mount builder and the real run/event serializers. Existing relevant messaging, recovery, settings, parking and API tests remain. Removed round-only behavior is not recreated as a second execution mode.

The unit suite uses SQLite and its dedicated Postgres test database. No rehearsal, model call, second Temper or throwaway server is needed for this change.
