# Orders: Unfinished entries — spec for Frontend

Draft A v3 direction. Prototype: `draft-a/index.html` → Orders (`draft-a/src/screens/orders.js`, the part marked "unfinished entries (Design #194)"). Data: `fixtures/orders_more.json` (stands in for `GET /api/entry`, the rows today's "Unfinished entries" panel lists). Check: `node draft-a/check-orders-alerts-more.mjs` (exit 0; real clicks at 1440×900, 390×844, 320×568). The rest of Orders (working orders, cancel, filled) is unchanged by this part and still checked by `node draft-a/check-orders.mjs`.

## What it is

An entry has two steps: buy 100 shares, then sell a call over them. When the shares are bought but the call hasn't sold, the entry is unfinished: the shares sit in the account with no call over them, and they hold more margin until the call sells. Orders shows these first, in their own group, because they are the one thing on the page waiting on the user. Each says what is done, what is missing, and offers two ways out: finish it (Continue) or stop here and keep the shares (Abandon).

The group only appears when there is at least one unfinished entry. Nothing unfinished: no group, no extra line in the headline.

## Parts, top to bottom

| Part | What it shows | Today's code / data it maps to |
|---|---|---|
| Headline note (desktop: bold line inside the hero's sub-line; phone: line in the top band) | Desktop "2 entries are unfinished: shares bought, call not sold yet." / "The MRK entry is unfinished: …" for one. Phone "2 unfinished entries: call not sold". Counts only open entries; gone when none or while the list is loading or failed | count of `EntryOut` rows with state `half_done` or `call_working` |
| Group header | "Unfinished" + meta "finish or abandon" (after the last is abandoned: "all settled") | today's `Panel title="Unfinished entries" subtitle="shares bought whose call has not sold yet"` (`components/UnfinishedEntries.tsx`) |
| Entry card (one per group) | symbol, chip ("Call not sold" for `half_done`, "Call waiting" for `call_working`, "Abandoned" after), company name, lead sentence, the two steps, buttons | one `EntryOut` row (`group_id`, `symbol`, `state`) |
| Lead sentence | `half_done`: "Your 100 PEP shares have no call over them yet. Until the call sells, they need $2,270 more margin." `call_working`: "Your 100 PEP shares have no call over them until the waiting call sells." The margin sentence is left out when the backend has no figure (MRK) | `half_done_extra_requirement` (`engine/entry/requirement.py`); shares from the group |
| Step 1 (done, check mark) | "Step 1 · done" / "Bought 100 shares" / "at $151.34, 9:52 AM" | the stock leg's fill price and time |
| Step 2 (to do, "2") | "Step 2 · not sold yet" (or "waiting to sell") / "Sell 1 call" / "11/6 $152.50 call" (waiting: ", asking $<its limit>") / "Buyers pay $0.92 now ($92)" — or "No buyers right now" (bid 0) or "No price right now" (no quote) | the call leg (expiry, strike, contracts, limit) + the call's bid when the list was read (today's "Buyers pay …" line) |
| Continue (solid primary on the first open entry only, tonal on the rest) | `half_done`: "Continue: sell the call"; `call_working`: "Continue: change the call". `data-act="entry-open" data-sym="PEP" data-from="orders" data-step="call" data-group="ent-pep-1104"` — opens the entry ticket (Design #186) at its call step, for this group | replaces today's "Write the call" (`entryApi.resume` → `POST /api/entry/{group}/continue`) and, for `call_working`, "Sell now / Change price / Change strike / Cancel the call" (all inside the ticket's call step now) |
| Abandon (line button) | "Abandon" → confirm in place | replaces today's "Keep the shares" (`entryApi.abandon(group, { sellStock: false })` → `POST /api/entry/{group}/abandon?sell_stock=false`) |

One solid primary per view: when the first entry is abandoned, the next open entry's Continue becomes the primary.

## Continue: the entry ticket, opened at the call step

Continue opens the same entry ticket Screener and Ideas use (`src/screens/entry.js`, one ticket with an Orders variant), not a second ticket. With `data-from="orders" data-step="call" data-group=<group_id>` it resumes that unfinished entry:

| Part | Normal entry ticket | Resumed from Orders |
|---|---|---|
| Title | "Buy PEP, sell a call" | "Sell a call on PEP" |
| Source line | "PepsiCo · from Screener / Ideas" | "PepsiCo · from Orders" |
| Price-now banner | yes | yes, unchanged |
| Step 1 | — | done box: "Step 1 done: shares bought" / "100 PEP at $151.34, 9:52 AM" (from `shares`, `stock_price`, `bought_at`) |
| Big number | "Total cost" | "Step 2: premium in, after fees" = premium − option fee (PEP: $92.00 − $1.10 = $90.90) |
| The call | the suggested call | the group's own call (`call.expiry`, `call.strike`) picked; "Choose another call" still works |
| Share stepper | yes | none: the share count is what was bought |
| Margin | — | "Selling it frees the $2,270 of extra margin these shares need now." (only when `extra_requirement` > 0) |
| Legs | stock, premium, fees | stock shown "Done" (bought 100 PEP at $151.34, 9:52 AM), premium, fees (option fee only) |
| "Pays x% of the shares' cost" | of the cost to buy | of what the shares cost when bought (PEP 0.6%) |
| Terms | limit shares + call | limit call only; good for, fees unchanged |
| Confirm sentence | "Buy … and sell …" | "Sell 1 PEP 11/6 $152.50 call at $0.92 a share or more against the 100 PEP shares you bought at 9:52 AM, good for today only: it brings in $90.90 after $1.10 in fees and leaves … of buying power." |
| Send, 5 s undo, sending, sent | unchanged | unchanged; sent line "Sell 1 PEP 11/6 $152.50 call at $0.92 or more against your 100 PEP shares: $90.90 in after fees." |
| Send refused | "The order wasn't sent: … share price …" | "The call wasn't sold: tastytrade refused its price because PEP's calls moved. Your shares are untouched." (`copy.ticket_fail`) |

Fails loud: an unknown group, a symbol that isn't the group's, a step other than `call`, or a group call missing from the ticket's calls throws (a wrong button is a bug, not a blank ticket). Frontend: today's equivalent is `entryApi.resume(group)` → `POST /api/entry/{group}/continue`, which sells the call for a `half_done` group; the ticket only adds the review and confirm in front of it.

Checked by `check-orders-alerts-more.mjs` (PNGs `orders-continue-ticket-*`, `orders-continue-confirm-*`).

## Abandon, step by step

| Step | What shows | Focus |
|---|---|---|
| Confirm (in the card, replaces the buttons) | **"Abandon this entry?"** "Your 100 PEP shares stay in your account with no call over them. Nothing is sold." `call_working` adds first: "RollCall cancels the waiting 11/6 $152.50 call first." Buttons "Yes, abandon" (stop red) · "Keep the entry" (ghost) | "Yes, abandon" |
| Keep the entry | back to Continue + Abandon | "Abandon" |
| Undo window (5 s) | "Abandoning in 5 s. Your 100 PEP shares stay." counting down in place, tonal "Undo". Nothing is sent to the server yet: the backend has no un-abandon, so Undo is a hold before sending | "Undo" |
| Undo | "Not abandoned. Nothing changed." above Continue + Abandon | that line |
| Sending (after the window) | pulse + "Abandoning…", disabled stop button "Abandoning…" with spinner (`aria-busy`) | the box |
| Done | check + "Abandoned at 10:12 AM. Your 100 PEP shares stay in your account with no call over them. Sell one from Positions any time." Chip "Abandoned", card dimmed, no buttons. Headline count drops by one | the box |
| Refused | **"Couldn't abandon."** + the server's plain reason (draft: "RollCall couldn't reach its server, so nothing changed. Check your connection, then try again."), `role="alert"`; "Try again" (line) · "Keep the entry" (ghost). Try again sends at once (no second undo window) | "Try again" |

Errors never show codes, URLs or stack text. "Abandoning…" shows the instant the window ends, before any reply.

## The list's own load states

| State | What shows | How to get it in the draft |
|---|---|---|
| ready | the group and cards above | default |
| loading | group header, a card with spinner + "Checking for unfinished entries…" and two skeleton lines, `aria-busy="true"`; no headline count yet | `index.html?unfinished=loading` |
| failed | group header, alert box **"Couldn't check for unfinished entries."** "The orders below are up to date. Try again in a moment." + "Try again" (→ loading at the tap, then the list) | `?unfinished=failed` |
| none | no group, no headline note | `?unfinished=none` |

The rest of Orders draws whatever state the list is in; a failed entry list never blocks the working orders below it.

## Sizes and type

Desktop 1440×900 (center column), phone 390×844 and 320×568: the Unfinished group sits in the first screen at every size. Steps sit side by side (step 2 wider) at every size. Phone buttons stack full width, 44 px+. Body 16 px, step labels 14 px, 12 px only for uppercase eyebrows; no clipped or ellipsed text. Tokens and classes from `draft-a/src/page.html` (`.card`, `.chip`, `.btn`, `.confirm`, `.undobox`, `.donebox`, `.failbox`, `.spin`).

## PNGs (made by the check, in `draft-a/`, one each for `desktop`, `phone390`, `phone320`)

- `orders-unfinished-<size>.png` — first screen, both entries
- `orders-unfinished-confirm-<size>.png`, `orders-unfinished-undo-<size>.png`, `orders-unfinished-done-<size>.png`, `orders-unfinished-error-<size>.png`
- `orders-unfinished-loading-<size>.png`, `orders-unfinished-loadfailed-<size>.png`

## Removed or renamed versus today's page

| Today (`components/UnfinishedEntries.tsx`) | Draft A |
|---|---|
| Panel "Unfinished entries", subtitle "shares bought whose call has not sold yet" | Group "Unfinished", meta "finish or abandon"; count also in the page headline |
| One sentence per row | Lead sentence (with the margin cost) + the two steps drawn as done / to do |
| "Write the call" | "Continue: sell the call" → entry ticket at its call step |
| `call_working`: "Sell now" / "Change price" / "Change strike" / "Cancel the call" | "Continue: change the call" → the same choices inside the ticket's call step; "Abandon" cancels the waiting call first |
| "Keep the shares" | "Abandon" with a confirm saying the shares stay, then a 5 s Undo |
| "Sell the shares" | Removed from Orders; selling shares is done from Positions (the done line says so) |
