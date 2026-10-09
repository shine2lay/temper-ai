# Pi team messages

A member talks through its pinned `send_message` tool. The host owns the tool socket, routing identity and inbox. The member cannot supply another run, member, turn, epoch or account. See [the free-flowing runtime](pi-team-runtime.md) for claims, shared work, done and holds.

## Send and reply

A send names a reachable member, a kind (`work_request`, `reply`, `info`) and body. A reply names the work request it answers. The communication setting is either `all` or an explicit directed `routes` map. Unknown, unreachable and self recipients are refused rather than silently broadcast. Tool permissions are the member's own.

A send is fenced by run, host, participant, session, turn and epoch. A client call id makes it idempotent: repeating the same call returns its first answer; reusing the id for different content is refused. Identity-like fields, credentials and forged claims are rejected and audited. The host never trusts a text prefix as authorization.

Messages and acts are held until the sending turn settles. A completed or accepted turn releases them in order. A failed, cut-off, superseded or cancelled turn voids outgoing sends and acts; a retry does not leak them. A pending message wakes an idle recipient. Member waits hold only that member, while unrelated senders and recipients continue working.

## Inboxes and mid-turn delivery

Before a turn, the host claims the member and selects its pending input under the team transaction. Input ids are stable. The first framing names the member, leader, roster, available tools, request/reply meanings and conflicts. Each member has one kept session. Only the leader receives the goal at start; the others wait for its messages.

Messages released while a recipient is working can be handed into that existing session. Temper polls its own ledger for the current member and sends a framed user entry over the host-owned team socket/RPC steer channel. The entry identifies the real sender and message id but marks the member's body as untrusted content. It cannot grant tools, alter identity, change the environment, or inject images. A general steer is not a back door: the pinned guard only allows this narrowly authenticated hand-in path.

After the box is gone, Temper confirms which handed entries actually landed from the saved session's exact user entries. Only confirmed input is consumed. Unconfirmed input remains pending. A failed/cut-off retry redelivers all input, including confirmed hand-ins, under the same message ids; outgoing messages from that failed turn remain void. Unexpected or refused hand-ins are recorded, not silently counted as delivery.

A leader's done boundary is the time of its `done` call. A non-system message still pending, created or released after that boundary, or delivered after it, refuses done even if it was read later in the same turn. Owner and decision messages count even when they have no release timestamp.

## Claims, rest and recovery

A running claim belongs to `(run_id, host_path, participant_id)`, not the whole team. Claims have epochs. Different members can run together, but a member cannot have overlapping writers. The configured parallel cap is checked inside the same transaction as the claim.

`idle(note?)` rests the member after its turn. A turn with no tool calls also rests. A pending or racing message wins over idle, so no message is hidden by an idle call. Members never messaged at start have `idle_reason: start` and no invented activity or idle note.

`ask_owner(question)` lets any flow member ask one owner-only question and then finish its turn. The fenced settlement opens only that member's wait; its answer is an `owner_reply` in the next turn. Done and ask_owner cannot be recorded together.

A failed/cut-off turn gets one automatic retry only after its box is confirmed removed, or after proving no box was made. The retry framing distinguishes its voided acts and undelivered sends from local edits that remain; old conversation acknowledgments do not imply delivery. A second failure or uncertain turn opens that member's recovery wait. Retry/accept choices are fenced and require confirmation that the old box is gone. Other members may continue; done cannot count while a member wait or failed/uncertain turn is open.

When no turn runs and nothing can be claimed, all answerable owner waits are registered and the run parks on their gate ids durably with no worker held; any one answer can wake it. While members run, asking the owner does not park those members. Settings answers have precedence. Usage limits, dollar check-ins, closing, Stop/cancel and lane drain hold new claims for the whole run.

## Stop and stale callbacks

Stop/cancel/drain prevents new claims, signals all turns and joins their receipts. A kill request is not enough: every created box must be confirmed stopped. Live and final usage is retained before ending the team. Channels for ended members refuse further sends.

Takeover raises the old epoch before stopping leftover boxes. The next attempt cannot claim a new writer until removal is confirmed. A stale turn's message, act, inbox confirmation or usage update cannot alter the new epoch. Kept session input and records remain available for the typed recovery choice.

## Stored records and observability

The versioned ledger keeps participants, turns, messages, acts and waits. Schema version 4 adds member rest/conflict fields and the cursor event table; its upgrade preserves existing rows. Historical review rows are retained for reading old round teams, not for executing new rounds.

The event feed records turn starts/ends, released messages, idle/wake, shares and conflicts, owner waits, limits, check-ins, closing, refused done and done. It has a cursor for incremental reads. Visible event count is separate from the raw sequence cursor: internal bookkeeping can occupy a sequence without appearing as a page event.

Running-turn usage is written only under its current epoch. Final usage replaces, rather than duplicates, the known cost. Failed, cut-off, retried and taken-over turns and compaction all contribute to Project spend. The run view exposes the same meaningful story as the Team page without exposing credentials or private model bodies.

Old ended round records remain readable. Reopening one is refused with “start a new Project”; a new team record has no round field.
