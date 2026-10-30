# Clarification answers over Telegram (M2)

`temper_ai/integrations/telegram/clarifications.py` is the one path by which a
real person's answer to a clarification question reaches temper. It sits at the
Telegram bot's own `getUpdates` call and turns a person's reply into an
`ActionReceipt` from the frozen contract (`docs/clarifications/contract.md`),
judged by the contract's `validate_receipt` and kept before anything else
happens.

**Off by default.** `Poller` and `TelegramService` take `clarifications=None`,
and nothing in the server builds a `ClarificationEdge`. While no edge is bound,
or while an edge is bound but has delivered no question, every update goes the
ordinary way, exactly as before. It goes live only in a later, separate step,
once the responder policy and its decisions exist (M4).

The edge only keeps receipts. Applying an accepted answer to the record, with
its revision check, is the store's job (M3), as wired by the caller (M4).

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
and returns a `PulledBatch`. `PulledBatch.claim(update)` takes only the very
objects that call returned; anything else is refused, whatever it holds. A
`PulledBatch` cannot be built outside `pull`.

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
(`malformed`).

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
- the send intent is kept (`save_send`) under the presentation's ID, one attempt
  is counted, the message is sent, and its message ID is kept: `sent`.

A retry uses the same intent and the same presentation: no new question or
presentation ID is ever made here. A different text under the same ID is refused
(`changed_body`, `send.changed`). Once a message ID is kept the result is
`delivered`, and nothing is sent again.

**No exactly-once claim.** When an attempt was started but no message ID was
kept (the provider failed, or temper stopped after sending), the send is
`uncertain`. It is shown as such and sent again only with `resend=True`, after
someone has checked the chat; the same presentation keeps its ID. A reply to a
copy whose message ID was never kept is not recognised and goes the ordinary way.

Each prompt is kept the same way before it is sent, under an ID made from the
typed reply's action key: when the update comes again, the kept prompt says
whether it went out, so it is never sent twice. A prompt kept earlier with other
words (an older release) is left as kept and noted; the poller goes on.

## The store

`ClarificationStore` is what the edge needs from durable storage, each call one
transaction: `save_send`, `start_attempt`, `record_delivery`, `delivery`,
`copies`, `current_generation`, `question_ids`, `answered`, `receipt`,
`keep_receipt`, `keep_refusal`. The current generation and the record's questions
come from the record, never from what was sent. M3 implements it; the tests use
a fake.

## Tests

`tests/test_integrations/test_telegram_clarifications.py` runs the combined clean
path first, through the fake provider (`FakeTelegram`) and a fake store, then
every refusal and crash point, then the default-off regression. Every guard has
its own bite: `test_every_guard_bites` changes the guard's line in an in-memory
copy of the module (never the file) and the guard's case must then fail. These
fakes prove that the code enforces provenance; they are not evidence of a live
human. No test calls Telegram.
