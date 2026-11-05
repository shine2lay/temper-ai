# Tickets: entry ticket, and the anatomy every ticket keeps — spec for Frontend

Design #186, RollCall option A v3 (Show&Tell d_kgrxir5ezb). Prototype: `draft-a/src/screens/entry.js` (entry ticket), the ticket code in `draft-a/src/page.html` (roll and sell tickets, shared parts), data in `fixtures/entry.json` and `fixtures/fees.json`. Proof: `draft-a/check-tickets.mjs` (exit 0 = every step below passed at 1440x900, 390x844, 320x568).

## What it is

- **Entry ticket:** buy shares in lots of 100 and sell one call against each lot, in one order. Opened from Screener ("Start a position") and Ideas. Today: `frontend/src/components/EntryTicket.tsx` with `EntryConfirm` and the strike list.
- **Every ticket (roll, sell, entry)** keeps four things: the price-now banner, the order terms (limit, good for, fees), the fees in the money lines, and a confirm step that restates the whole order before Send. The owner removed only the Simulated / Real money labels; none are drawn.

## How it opens (contract other screens use)

- Any button `data-act="entry-open" data-sym="<SYM>" data-from="screener|ideas"`.
- Only CSCO, VZ, MRK, HD and PEP have a ticket. Any other symbol throws `entry.js: no entry ticket for "<SYM>" ...` and opens nothing; any other `data-from` throws too. In the app: the ticket opens for any symbol the entry preview answers for; a symbol it can't answer gets the error state, never a half-drawn ticket.
- Desktop: right panel (540 px). Phone: bottom sheet. Same look as the roll ticket.

## Entry ticket: parts, top to bottom

| Part | Shows (CSCO example) | Today's field |
|---|---|---|
| Title | "Buy CSCO, sell a call" | Drawer title `${symbol}: buy N shares and sell {callPhrase}` |
| From line | "Cisco Systems · from Screener" (or "from Ideas") | new (name from the quote; source from the button) |
| Price-now banner | "CSCO stock price now · 10:12 AM  $71.40" | `SpotBanner` (ChoiceNote.tsx); no banner when spot is missing or 0, as today |
| Hero | eyebrow "TOTAL COST", "$7,100.10", "100 shares, with 1 call sold against them" | "Net cash it takes" plus fees (shares − premium + fees) |
| The call you sell | "Fri 11/6 $72 call", "2 days · 38% may be called · pays 0.6% of the shares' cost", "Inside your rules" or "Outside your rules: <why>" | `EntryContractBlock` (suggested call, delta, rule checks) |
| Choose another call | link; opens an inline list: expiry chips (Fri 11/6 · 2 days, …), calls high strike first with a "Now $71.40" line, each "pays $x a share", "+$premium", "N% may be called", Inside/Outside your rules, Suggested, a tick on the current one | `EntryStrikeList` / chain picker, `/api/entry/strikes`, `changeCall` |
| Put the suggestion back | link, shown only when another call is picked | "Put RollCall's suggestion back" |
| Shares | "Shares, in 100s, one call each", − 100 + (44 px buttons); at the most buying power covers: "That's as many as your buying power covers." | `SizeControl` (contracts, `max_contracts`); 1 lot = 100 shares = 1 contract |
| Money lines | Stock "buy 100 CSCO at up to $71.42" −$7,142.00 · Premium in "sell 1 × 11/6 $72 call at $0.43 or more" +$43.00 · Fees "tastytrade, 1 contract" −$1.10 | "What it costs in cash": Stock you buy, Premium the call pays you; fees from `preview.fees` |
| Buying power after | "$202,140.90" | `AccountEffectBlock` / "Buying power you have" minus what the order uses |
| Terms | Limit "Shares $71.42 / Call $0.43" · Good for "Today only" · Fees "$1.10" with an (i) tip: the broker's fee schedule | stock limit, `EntryCallPrice` (call limit), time in force (`tifWords`: day), `preview.fees` |
| Footer | one solid button "Check the order" | "Review and place…" |

Figures: total = shares × stock limit − contracts × 100 × call bid + fees; buying power used = 50% of the shares' cost − premium + fees (fixture `margin.initial_pct`; in the app the broker's own figure). Fees in the draft come from `fixtures/fees.json` (tastytrade: $1 a contract to open, at most $10 a leg, closing free, $0.10 a contract clearing, shares free); in the app always the order check's own `preview.fees`, and when the broker sends none the Fees cell says "Not reported by tastytrade", never $0.

## Entry ticket: the steps

1. **Opening (loading):** at the click, before any reply: skeleton, "Getting CSCO prices from tastytrade…", the button "Getting prices…" with a spinner, disabled. (Draft: 1 s.)
2. **Review:** the parts above.
3. **Confirm** ("Check the order"): banner hidden (as today). "Check this before it goes", then the whole order in one sentence: "Buy **100 CSCO shares** at up to **$71.42** and sell **1 CSCO 11/6 $72 call** at **$0.43** a share or more, good for today only: it costs **$7,100.10** with **$1.10** in fees and leaves **$202,140.90** of buying power." Below: Goes to "tastytrade · Main account", Market "open till 1 PM". Footer: "Nothing is sent until you press Send order. Prices may move by the time it reaches the market.", solid "Send order", link "Back to the ticket".
4. **Undo (5 s):** "Sending in 5 s" counting down with a draining bar, solid "Undo". Close (X) and Esc do nothing here. Undo -> back to the review with "Not sent. The order is still here: change it or send it when you're ready." In the app: the client waits 5 s before it calls place; nothing reaches the broker before then (today's code has no undo; no new endpoint is needed).
5. **Sending:** "Sending your order…", button "Sending…" disabled. Close disabled.
6. **Sent:** tick, "Order sent", "Working at the broker; it shows in Orders.", a card "Working · today only: Buy 100 CSCO shares at up to $71.42, sell 1 CSCO 11/6 $72 call at $0.43 or more ($7,100.10)." Footer: solid "Done", link "See it in Orders". Done closes and redraws the screen behind (`state.entrySent[sym]` is set so Screener/Ideas can mark the row).
7. **Send failed:** the confirm step stays with the order sentence, and above it: "**The order wasn't sent: tastytrade refused the share price because MRK moved. Nothing changed in your account.** Check the new price, then send again." Footer: solid "Check the new price" (back to the review, with fresh prices in the app), link "Send again".

## Entry ticket: other states

| State | What shows | Can send |
|---|---|---|
| Loading | the opening skeleton, as step 1 | no |
| Empty | banner, "No calls to sell this week", "tastytrade sent no calls for MRK this week, so there is nothing to sell against the shares.", solid "Try again", link "Close" | no |
| Error (broker unreachable) | amber banner "MRK stock price at 9:41 AM", alert "RollCall can't reach tastytrade right now, so these numbers are from 9:41 AM.", the ticket below with those numbers, footer "Sending orders is paused until the broker answers." + solid "Try again" | no |
| Partial (no buying power) | the ticket, Buying power after "Not known: your broker didn't send it this time" in amber; the confirm sentence leaves out buying power | yes |
| Send fails | step 7 | Send again |

The draft has a dashed "Draft preview, show as:" picker at the foot of the review (Normal, Loading, Empty, Error, Partial, Send fails). It is for review only; not built in the app.

## Behaviours

- Click feedback before any reply: opening shows the skeleton at once; Send shows the undo at once; every step change moves focus to that step's main button.
- Double-click guard: the second click of a double-click on "Check the order" lands on "Send order" and is ignored (`event.detail > 1`). Today moves the footer instead.
- Redrawing the open ticket (stepper, a pick, a step) keeps its scroll and doesn't replay the slide-in.
- Esc: closes the call list first, then the ticket; ignored during undo and sending.
- Shares: − disabled at 100; + disabled at the most buying power covers (`max_lots` / `max_contracts`), with the note.
- Picking a call closes the list, updates every figure and the rules line; a call outside the rules can still be sent, the line says why ("expires in 9 days; yours stop at 7").
- Fail loud: `entry.js` checks `fixtures/entry.json` at load (every call's fields, inside_rules agreeing with the rules, the suggested call among the calls, exactly the five symbols) and throws rather than draw wrong money.

## Roll and sell tickets (page.html): what was there, what was added

| Anatomy | Already in v3 | Added in #186 |
|---|---|---|
| Price-now banner | no (only the "Now $114.60" dot on the price line) | `spotBanner()` at the top of the review ("XOM stock price now · 10:12 AM $114.60"); hidden on the confirm step, as today's `OrderTicket` |
| Limit | yes ("$0.04 credit a share", "$0.10 a share") | kept |
| Good for | yes ("Today only") | kept |
| Fees | "None" hard-coded (wrong: tastytrade charges to open) | the fee rule: XOM roll 2 contracts $2.40, T sale 4 contracts $4.40, with the (i) fee tip |
| Confirm step | no: Send sat in the review footer | review footer "Check the order" (+ "Choose another call"); confirm: "Check this before it goes", one sentence ("Buy back 2 XOM 11/6 $112 calls and sell 2 XOM 11/20 $114 calls for a $0.04 credit a share or more, good for today only: you get +$8.00, +$5.60 after $2.40 in fees."), Goes to / Market, footer with today's confirm copy, "Send roll" / "Send order", "Back to the ticket" |
| Send guards | none | Send works only from the confirm step, never on a double-click's second click; Close disabled while sending |

Pending and sent are unchanged (no undo on roll/sell, as v3). Shared parts live on `ctx.ticket` (`fees`, `spotBanner`, `terms`, `confirmBlock`, `alert`, `signedCents`), so all three tickets draw them the same way. `check.mjs`, `check-ladder.mjs` and `check-orders.mjs` now click "Check the order" before "Send roll" / "Send order".

## Sizes and type

Desktop 1440x900 (panel 540 px), phone 390x844 and 320x568 (sheet). Body 16 px, labels 14 px, 12 px only for uppercase eyebrows; phone targets 44 px or more; one solid primary button per view; page never wider than the phone. At 320 the call list's cards stack (strike, pays, then premium and odds on one line).

## PNGs

In `draft-a/`, `tickets-<desk|390|320>-<step>.png` (desk 19, each phone size 21): entry-opening, entry-review, entry-review-end, entry-picker, entry-other-call, entry-confirm, entry-undo, entry-undone, entry-sending, entry-sent, entry-loading, entry-empty, entry-error, entry-partial, entry-failed, roll-review, roll-confirm, sell-review, sell-confirm; phone also roll-review-end, sell-review-end.

## Removed or renamed versus today's ticket

Entry ticket (`EntryTicket.tsx`, `EntryConfirm`):
- Title "`<SYM>`: buy N shares and sell `<call>`" -> "Buy `<SYM>`, sell a call".
- "Heads up." caution and `StatusLine` -> removed; broker trouble shows as the error state's alert, a missing figure as the partial state.
- `et-lead` headline -> the "Total cost" hero.
- "What it costs in cash" -> the money lines: "Stock you buy" -> "Stock"; "Premium the call pays you" -> "Premium in"; "Net cash it takes" -> "Total cost" (the hero, fees included); "Borrowed on margin" -> removed; "Buying power you have" -> "Buying power after".
- `AccountEffectBlock` (margin requirement, excess, drop-to-call now -> after) -> removed; only "Buying power after" stays.
- `EntryAgreementBox`, `EntryModelNote` -> removed.
- `EntryFold` "Show them / Hide them" with every check -> removed; the rules line says inside or outside your rules and why.
- `BrokerAnswer` (broker dry run) -> not shown; its fees feed the Fees line and a refusal shows as the failed send.
- `SizeControl` in contracts -> "Shares" in 100s.
- Footer "Cancel" -> the X and Esc; "Review and place…" -> "Check the order".
- `EntryConfirm` list of send lines -> one sentence; the two tick boxes (the two-leg risk box and "I have read what is above and want to send it.") and "Tick the box to enable this." -> removed; the 5 s undo is the safety net instead.
- Send button inside the confirm body -> "Send order" in the footer; "Placing…" -> "Sending in 5 s" (undo), then "Sending your order…".
- "The entry was not placed." -> "The order wasn't sent: … Nothing changed in your account." plus what to do.
- Placed "Done" -> "Done" plus "See it in Orders".

Roll and sell tickets (`OrderTicket.tsx`, `ticket/RollConfirm.tsx`):
- `RollConfirm`'s will-send list -> one sentence; `tifWords` "It stands until tonight's close and then expires" -> "good for today only"; `MarketClock` line -> "Market: open till 1 PM".
- The tick box "I have read what is above and want to send it." -> removed.
- "Placing your order…" -> "Sending your roll…" / "Sending your order…".
- Sections "How much of it to roll", "Your price", "The two trades in this order", "What it pays / What it costs", "Before and after" -> as v3 already had them (You get, New call, Buy back / Sell lines, price line, terms); #186 changed none of them.
