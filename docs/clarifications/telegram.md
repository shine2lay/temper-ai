# Clarification answers over Telegram (M2)

`temper_ai/integrations/telegram/clarifications.py` is the intended provider-backed
path for a person's answer to a clarification question. It sits at the
Telegram bot's own `getUpdates` call and turns a person's reply into an
`ActionReceipt` from the frozen contract (`docs/clarifications/contract.md`),
judged by the contract's `validate_receipt` and kept before anything else
happens.

**Off by default.** `Poller` and `TelegramService` take `clarifications=None`,
and nothing in the server builds a `ClarificationEdge`. While no edge is bound,
or while an edge is bound but has delivered no question, every update goes the
ordinary way, exactly as before. It goes live only in a later, separate step,
once the responder policy and its decisions exist (M4).

The edge only keeps receipts. Applying an accepted answer is the store's job
(M3), as wired by the caller (M4): its transaction must recheck current question,
active-answer and confirmation-once rules as well as the revision. "Received."
acknowledges a validated receipt, not successful application, consent or resume.

## How a person answers

1. temper sends the question as one plain message for a persisted
   `Presentation` (`ClarificationEdge.present`). Telegram shows a reply box.
2. The person replies to that message, in their own words. The words are kept
   exactly as Telegram decoded them: never trimmed, normalised or repaired.
   On their own they apply nothing.
3. The bot replies to their words: "How does your reply count?", with three
   buttons: *This is my answer* (`answered`), *Answer later* (`deferred`),
   *I don't know* (`unknown`).
4. The same person presses one. That press, bound to that one typed message, is
   the explicit disposition. The press is answered "Received." when it was
   accepted, otherwise "Not applied.".

Nothing is guessed from the words. "yes", "answered" or a button's data typed as
text is kept as a reply with no disposition. Only a press whose data is exactly
one of the payloads kept with that prompt chooses how the reply counts.

## Where an answer may come from

Only the server's own pull. `ClarificationEdge.pull(client, offset, ...)` makes
the `getUpdates` call with the poller's own client (any other client is refused)
and returns a `PulledBatch`. At pull time it privately captures independent
nested snapshots and their canonical JSON. `claim(update)` checks the separately
captured original object membership, then consumes that snapshot, not whatever
the exposed object holds now. A later nested edit (including through a provider
alias or during a policy call) cannot change kept text, disposition or digest.
The public iteration tuple, namespace, offset and originating edge cannot be
rebound. Appending/replacing membership is not supported; a foreign dict is
refused even if it looks identical. Replaying the same captured object still
uses that pull's original contents and the usual receipt replay check. The
constructor requires `pull`'s private token.

This is **capture integrity for the supported API**, not a hostile-Python
sandbox. Server code, injected store and policy are trusted. The real client,
HTTPS provider, bot token and endpoint must remain fixed for the lifetime of
an edge; client object identity does not authenticate a replacement token or
endpoint. Arbitrary code that replaces clients or invokes private methods is
outside this boundary. No examined handler/API/inbox route gives callers a
batch. Provider account authentication is not proof of physical human presence,
original authorship or uncompromised accounts.

So there is no route from:

- `Handler.handle(dict)`, `TelegramService.save(dict)` or `Handler.handle_saved`;
- an inbox row, including one re-run by the events replay API
  (`POST /api/events/{id}/replay`), with a service key or not;
- a caller's dict, or a `source` or `ingress` label in it.

These keep their ordinary meaning. The existing gate and approve API never
appends a clarification. Edited messages are never pulled (`ALLOWED` has no
`edited_message`), so kept words cannot change afterwards.

An update is claimed only when it replies to, or presses a button on, a message
this edge delivered (the store's `delivery(bot, chat, message ID)`). A message
that replies to nothing is never bound to "the last question": it goes the
ordinary way. Claimed updates skip the ten-minute staleness rule: whether an
answer is late is decided by the question's generation, not by the clock.

## What is kept, and when

For each claimed update, before the poller moves the offset and before anything
is answered or sent:

- the **ingress**: the bot, the update ID, the SHA-256 of the update's canonical
  JSON as decoded (sorted keys, ASCII; `None` when it has no JSON form) and the
  offset it came back for. IDs and a digest, never names;
- the **receipt** exactly as pulled, and the contract's **verdict** on it.

An accepted or retained receipt holds its action key (bot, chat, kind, message or
press ID). The same update again is a repeat. A different body under the same key
is refused (`changed_body`) and the held receipt stays. A refused update is kept
as a diagnostic under its own digest and never takes the action key, so the same
action can still count later.

Errors from the store or from the responder policy are raised: the offset stays,
and Telegram sends the update again. Provider errors on a prompt or on a press's
little notice are noted (`status()["last_error"]`) and never undo the kept
receipt.

## Who may answer

The presentation names a responder policy. The edge asks an injected
`ResponderPolicy`:

```python
policy.decide(policy_ref=..., chat_id="<chat where they acted>", sender_id="<numeric user ID>")
```

Only the exact string `"authorised"` lets the person answer there; any other
answer denies. No responder list, chat ID or user ID lives in this module or in
this repo: the real policy is wired by the caller (M4). A group member without
authority is refused. The event's actor is `telegram-user:<numeric ID>`.

## Refusals and retained receipts

Refused by the edge itself (`ContractRefusal`; kept as a diagnostic when it
concerns a pulled update):

| guard | code | when |
|---|---|---|
| `edge.pulled` | `unverified_ingress` | an object this pull did not return |
| `edge.batch` | `unverified_ingress` | a `PulledBatch` built outside `pull` |
| `edge.client` | `transport_mismatch` | a pull with another client |
| `ingress.size` | `malformed` | the update has no JSON form, or is over 256 KiB as canonical JSON |
| `ingress.sender` | `malformed` | no positive numeric sender ID |
| `ingress.text_size` | `malformed` | words over 4096 characters |
| `ingress.callback_size` | `malformed` | button data over 64 bytes |

Refused by the contract's checks, among them: a bot sender, or one with no
`is_bot` flag (`bot_sender`); forwarded or copied words, marked by any of
`forward_origin`, `forward_from`, `forward_from_chat`, `forward_from_message_id`,
`forward_signature`, `forward_sender_name`, `forward_date`,
`is_automatic_forward`, `via_bot`, `sender_chat` (`forwarded_message`); a sender
without responder authority (`responder_not_authorised`); an answer given in
another chat or through another bot (`transport_mismatch`); a question the latest
record no longer asks (`unknown_question`); a press by someone other than the
author of the words (`confirmer_not_author`); words with no UTF-8 form
(`malformed`). Forwarding markers are detectable; manual copying/retyping by
an authenticated account cannot be distinguished from that account's own words.

Retained (kept, bound to its presentation, applies nothing): words with no
explicit disposition, or a press whose data is not exactly a kept payload
(`no_explicit_disposition`); a reply or press for an older generation of the
question (`stale_presentation`); blank words (`blank_text`). A reply with no
words (a sticker, a photo) or with blank words gets no prompt.

## Sending a question

```python
edge.present(presentation, unknown, text, resend=False) -> SendResult
```

It checks that the presentation is for this bot (from the provider's own
`getMe`, never configured), that its question ID and metadata hash match the
unknown, and that the text says something and fits one Telegram message (4096
UTF-16 code units). Then, in order:

- the record already holds an answer: `answered`, nothing kept or sent;
- the generation is not the current one: `not_current`, nothing kept or sent;
- the send intent is kept (`save_send`) under the presentation's ID;
- `start_attempt(send_id, expected_attempts=..., resend=...)` atomically compares
  that saved attempt count with current state and admits at most one caller;
- only the winner sends, then keeps the returned message ID: `sent`. A loser
  returns the committed state, without a provider call or an automatic retry.

A retry uses the same intent and the same presentation: no new question or
presentation ID is ever made here. A different text under the same ID is refused
(`changed_body`, `send.changed`). Once a message ID is kept the result is
`delivered`, and nothing is sent again.

**No exactly-once claim.** When an attempt was started but no message ID was
kept (the provider failed, or temper stopped after sending), the send is
`uncertain`. It is shown as such and sent again only with `resend=True`, after
someone has checked the chat; the flag itself is not proof of that check. The
same presentation keeps its ID. Concurrent callers with the same observed
attempt cannot both win. A later explicit reconciliation can intentionally
overlap an uncertain in-flight network attempt; every ID returned by either
attempt must remain a recognised copy, even when responses arrive out of order.

A reply to a copy whose message ID was never kept is not recognised and goes
the ordinary way (K1). That route is not necessarily a no-op: existing allowed
commands/ask behaviour may start ordinary work under its own permissions. It
never mints a clarification receipt. M4 still owes the lost-copy fallback and
reconciliation choice; this adapter does not accept that operational risk.

The answered/current check and the network send are not atomic (K5). An answer
or new generation can commit in between. A subsequent reply stays tied to the
original presentation; M3 must decide its application against current state.
Exclusive send admission does not remove this separate race.

Each prompt is kept the same way before it is sent, under an ID made from the
typed reply's action key: repeated or concurrent claims share atomic admission
and do not automatically send it again after an admitted attempt. A prompt kept earlier with other
words (an older release) is left as kept and noted; the poller goes on.

## The store

`ClarificationStore` is what the edge needs from durable storage, each call one
transaction: `save_send`, `start_attempt`, `record_delivery`, `delivery`,
`copies`, `current_generation`, `question_ids`, `answered`, `receipt`,
`keep_receipt`, `keep_refusal`. The current generation and questions come from
the record, never from what was sent. M3/M4's future adapter must implement this
protocol; it is not implemented by the M0 contract. The tests use a locked fake,
not a durable production store.

`start_attempt(send_id, *, expected_attempts, resend)` returns `(record, won)`
after committing. It wins only if no message ID is held, the current attempt
count equals `expected_attempts`, and the count is zero or `resend=True`.
Only a win increments the count. On a loss it returns current state without a
write. Compare and increment must be atomic across every edge/process sharing
the store; a local precheck followed by a separate increment is insufficient.
The edge consumes the winner result before any network send. Intent identity
must be immutable, so a mismatch cannot be hidden by a concurrent writer.

`record_delivery` keeps every returned copy, not just the ID in the latest
`SendRecord`. Both `delivery` and `copies` must retain those IDs. A committed
attempt with a lost acknowledgement stays uncertain; a committed delivery
with a lost acknowledgement is delivered on retry. Neither automatically
sends again. These are explicit store requirements, not proof supplied by the
fake of a real database's transactions.

## Tests

`tests/test_integrations/test_telegram_clarifications.py` runs the combined clean
path first, through the fake provider (`FakeTelegram`) and a fake store, then
every refusal and crash point, captured-data mutations, barrier-controlled
concurrent sends/claims, commit-then-raise ambiguity, then the default-off regression. Every guard has
its own bite: `test_every_guard_bites` changes the guard's line in an in-memory
copy of the module (never the file) and the guard's case must then fail. These
fakes prove that the code enforces provenance; they are not evidence of a live
human. No test calls Telegram.
