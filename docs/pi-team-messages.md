# Team messages and inboxes for Pi members — switched off

The first half of the team runtime (T4 messaging + T5 inboxes, queue #37): the members of a
team stage ([pi-agent.md](pi-agent.md), "A team stage") talk to each other only through
Temper. Every message is stored once and delivered exactly once, between the receiver's
turns, never in the middle of one. It is built to Architecture's R2 rules B1–B17
(`company-lab/pi-agent-proofs/R2/review.md`); the tables are in
`company-lab/pi-agent-proofs/T4T5/tables.md`.

Everything is behind `TEMPER_PI_AGENT` (default off). With it off nothing is imported, no
`pi_` table is created and a team stage is refused at load ("Unknown strategy: 'team'").
The leader loop (#38, [pi-team-runtime.md](pi-team-runtime.md)) drives it from the team
node.

## How a message goes

1. A member sends with the `send_message` tool. The tool comes from the box's temper-box
   extension and exists only in a team member's box (`TEMPER_BOX_TEAM=1`); its arguments
   are `to` (a member's team name), `kind` (`work_request`, `info` or `reply`), `body`, and
   for a reply `in_reply_to` (the id of the message it answers) and `outcome` (`answered`,
   the default, or `declined`). The tool call's own id is the message's client id.
2. The tool writes one line to the box's team socket. The socket belongs to that member's
   running turn (`team_runtime.TeamChannel`): Temper stamps the sender, its session and the
   turn from its own record of which box runs which member, never from what the model
   wrote (B2). A message that claims another sender is refused and the claim is audited on
   the turn (`pi_turns.refusals`, no bodies). No channel token exists for a model to see.
3. Temper routes it by A7's rules (`temper_ai/pi_agent/route/`, a near-unchanged port of
   A7's `model.py` and `policy.py`, plus the durable router). Communication `all` means
   one group rule: every member may send `work_request` or `info` to every other member;
   a reply goes to whoever sent the message it answers, and only to a message the member
   received. An unknown name gets the same answer whether or not it was ever a member.
4. The same client id with the same content returns the original message; with different
   content it is refused (`idempotency_conflict`, B3; key = run, sender, client id, plus a
   content digest).
5. What a turn sends is **held** with that turn and leaves only when the turn settles:
   when it completes, or when the owner accepts a cut-off turn. A failed or superseded
   turn's messages stay recorded as undelivered (`turn_failed`, `turn_superseded`); a retry
   never sends them twice (B4). At release each recipient is checked again: a retired or
   ended member's message becomes undelivered instead of pending.
6. The receiver gets its **pending** messages at its next turn as one ordered batch, oldest
   first (`inbox.render_batch`). Every header line starts with a tag drawn fresh for that
   batch and names the real sender, kind and message id from the ledger; every line of a
   body is shown after `| `, so no body can pass for Temper's lines (B5). A message that
   arrives during a turn waits for the next batch (B6). Each delivered message records the
   turn that took it (`pi_messages.turn_id`, `delivery_count`).

## Turns, one at a time

- The team's next turn goes to the idle member holding the oldest pending message
  (`Team.step`). The claim is one guarded write per team (`pi_turns.claim_key`, unique):
  two processes never run the same turn, and no turn starts while any team wait is open.
  Writes to a team take a per-team lock (an advisory lock on Postgres).
- Every write a turn's owner makes (effect state, events, sends, settle) is fenced on the
  turn still running with the same epoch, so a stale owner's late writes change nothing.
- A turn cut off after its prompt was sent (box gone, timeout, the service stopped) is
  never replayed: it becomes uncertain and opens a recovery wait that pauses the whole team
  (B11), answered `accept` (keep what it did; its held messages leave) or `retry`. A turn
  that failed visibly is answered `retry` or `stop` (`accept` is not offered for a failed
  turn, also in the single Pi step). A retried turn gets the same messages again, with the
  same ids, marked "given again" (B1); they are never posted as new.
- Taking over a turn whose owner is gone first confirms its box is stopped: the box name is
  recorded on the turn before the box is created; at take-over the box is inspected, killed
  and removed if still there, and the result recorded (`pi_turns.box_stop`). If that can't
  be confirmed the team fails red and nothing is taken over (C1).

## Kept conversations

One Pi session per member per run, reused for every turn (B8): A → B → A keeps A's
conversation. A member's box exists only during its turn; an idle member has no box and its
next turn's box reopens the same session file. Each member's pin carries a digest of the team
settings (members and roles, communication, leader, `pause_after_rounds`). Reopening a team
whose roster changed is refused with "team settings changed" before any turn (C3); any other
change to the team's settings or a member's is asked about first, at a settings wait, before
any turn (SW-85, [pi-team-runtime.md](pi-team-runtime.md) "Owner waits").

## Ending

The owner's cancel ends the team in the same transaction: a running or cut-off turn is
cancelled (its held messages undelivered, `turn_cancelled`), every queued message is recorded
undelivered (`run_cancelled`), open waits are cancelled and every member is ended (B12). A
run cancelled while it is parked ends its teams from Temper's cancel path
(`runner/parked.py`, switch on only, C2). A message posted after the end is recorded
undelivered (`late`), never dropped and never reopening the run.

## The tables

L2's ledger (`temper_ai/pi_agent/ledger.py`) extended in place, no parallel tables:
`pi_participants` (one row per member: role, state, session), `pi_messages` (stable id,
sequence, sender stamp, A7 key and digest, state `held` / `pending` / `consumed` /
`undelivered`, the delivering turn), `pi_turns` (claim key, epoch, box name and stop result,
batch and cut-off sequence, refusals), `pi_waits`, and `pi_reviews` (room for #38's review
record: the leader's commit and the views collected for it). The team's whole state can be
rebuilt from these rows (`Ledger.team_state`): sessions, pending and held messages, open
waits, the unsettled turn, and whether the team is quiet (nothing running, nothing pending,
no open review, no done). `temper trim` never touches `pi_` rows (B17). "Held" here means
"waiting for its turn to settle"; in A7 it meant "refused at dispatch", which never happens
under `all`.

## Tests (no model, no network)

`tests/test_runner/pi_team/` (delivery, recovery, sessions, team state, A7's cases that
apply to `all`, and separate processes racing for one turn),
`tests/test_runner/pi_parking/test_team_cancel.py` (C2),
`tests/test_observability/test_trim_pi.py` (B17) and `tests/test_pi_agent/test_switch.py`
(switch off). They run on SQLite and on the Postgres tier (`tests/pgtier.py`). Every test is
mapped to its case and rule in `pi-agent-proofs/T4T5/report.md`, with the offline box
rehearsal (real worker boxes and Pi, a local stand-in for the provider, zero provider
connections).

## Not built yet

`edges`, obligations, unanimous mode, parallel turns, the leader loop, rounds, pause, done
and parking a team wait (#38, #39), the Team page.
