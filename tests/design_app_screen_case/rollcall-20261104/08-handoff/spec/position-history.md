# Position history (Positions > a position > History) — spec for Frontend

Draft A v3 direction (Show&Tell d_kgrxir5ezb). Prototype: `draft-a/index.html` → Positions → XOM or JPM → History (`tradeHistory(p)` in `draft-a/src/screens/positions.js`). Data: `fixtures/position_history.json` (XOM and JPM; the same steps and amounts as the Analysis journeys in `fixture.json`). Check: `node draft-a/check-browse.mjs` step 10 (exit 0, desktop 1440x900, phone 390x844 and 320x568); `check-positions.mjs` still passes with it.

## What it is

Every trade on one position, newest first, and how they add up to the position's **Collected** figure (the cost card's "Premium collected" a share × shares). It answers "how did I get to this adjusted basis?" without leaving the position. Closed by default: the first view of a position stays calm (status, call, cost); the history is one tap away with its answer in the summary line.

## Parts, top to bottom

| Part | What it shows | Today's code / data it maps to |
|---|---|---|
| Disclosure (closed) | White card under the cost card: **History** (20 px) and one summary line: "6 trades since May 4 · $820 collected". Trades = buys, calls sold, rolls and call-aways (expiries and dividends are listed but not counted as trades); "since" = first buy. Chevron turns when open. | `CollapsibleSection id=rollhistory` "The journey" in `pages/PositionDetail.tsx`; `GET /api/analysis/{symbol}` (`fetchPositionLedger`): `legs[].events[]`, `dividends`, `share_realized`, `row.collected` |
| Timeline | One row per event, newest first (the open call leads): a coloured dot on a line, the date ("Oct 19"), a kind chip, the object in bold, one plain detail line, and the money on the right (green +, red −). | `JourneyLeg.events[]` (`day`, `kind`, `contracts`, `amount`) grouped per leg; roll = `roll_events` (same-day buyback + sale pair) |
| Kind chips | **Bought** (dark dot), **Sold call** (teal), **Rolled** (amber), **Expired** and **Dividend** (green), **Called away** (red), plus **Open now** on the call still open | wire kinds STO → Sold call, BTC + STO same day → Rolled, EXPIRE → Expired, ASSIGN → Called away; share buys from the lot; dividends from `dividends` |
| Detail line per kind | Bought: "$108.20 a share · $21,640 paid" (no amount on the right: buying shares isn't income). Sold call: "$1.85 a share". Rolled: two lines, "Bought back 2 · Jul 17 $113 at $1.45: −$290" / "Sold 2 · Aug 21 $116 at $1.50: +$300", net on the right (+$10). Expired: "You kept all of it" (no amount). Dividend: "$0.99 a share". Called away: "$1 a share under the $236 you paid" (−$100). | leg `credit`, `buyback`, `net`, `contracts`, `strike`, `expiry`; `share_realized` for called away |
| Totals | Lines that add up: **Calls, net** (+$792), **Dividends** (+$198), **Shares called away under cost** (only when there was one: JPM −$100), **Margin interest** (−$170); a rule; **Collected $820** (22 px) with "$4.10 a share × 200, as in your cost". | sum of leg nets; `dividends`; `share_realized`; margin interest = `row.interest_taken` (Analysis); `row.collected` must equal `premium_collected_per_share × shares` |
| Call numbers | Unchanged from the Positions screen: a second, grey disclosure under History ("sold at $1.85 · now $2.73") for positions with an open call. | as Positions spec |

The order is newest first because the open call is what the owner acts on; the totals sit at the bottom, where a ledger ends.

## Sums (must hold, the prototype throws at load if not)

- events: calls net + dividends + shares called away − margin interest = Collected.
- Collected = position `premium_collected_per_share × shares` = Analysis banked `collected`.
- a roll's two legs add up to its net.
- XOM: 150 + 140 + 10 + 122 + 370 = 792 calls; + 198 dividend − 170 interest = **$820** ($4.10 × 200).
- JPM: 300 + 40 + 320 = 660 calls; + 140 dividend − 100 called away under cost − 140 interest = **$560** ($5.60 × 100).

## States

| State | Summary line | Body | Draft preview button |
|---|---|---|---|
| normal | "6 trades since May 4 · $820 collected" | timeline + totals | Ready |
| loading | spinner + "Getting trades…" | 4 row skeletons (`aria-busy`) | Loading |
| error | "Trades didn't load" | (`role="alert"`) "Couldn't reach tastytrade for XOM's trades. Check your connection, then try again." + tonal "Try again" | Error |
| partial | "Some trades not read yet · $820 collected" | amber note "Trades before Aug 14 aren't read yet. They're one line in the total below." + the events read + totals with a "Before Aug 14, not read yet" line (+$300) so Collected still matches | Partial |
| empty (no ledger) | "No history yet" | "No trades read for T yet. They show here once RollCall reads them from tastytrade." + "Last known: <last call>." (when known) + "Collected so far: $1.10 a share, $440 in all." | — (AAPL, MSFT, KO, PFE, DIS, T in the draft) |

The "Draft preview, show as:" box inside the open History is for the draft only; don't build it. Server signals: loading = ledger request in flight (start it when the position opens, so the summary line is ready before the tap); error = request failed; empty = 404 / no ledger; partial = the ledger's first read event is later than the lot's first buy (`notes` or a first-read date from the ledger); the "not read yet" line = Collected − what was read.

## Behaviours

- Closed on first view of every position; open/closed is kept per position while the app runs (coming back to XOM keeps it open).
- "Try again" turns at once into a disabled "Trying again…" with a spinner, then the history comes back in place, still open, focus on its summary.
- Changing state never closes the disclosure or moves the scroll position.
- Money: whole dollars in the timeline and totals unless cents exist; "−" (minus sign) for money out; per-share prices with cents.

## Sizes

Desktop 1440x900 (centre column), phone 390x844 and 320x568. Phone: the date sits above the chips, the amount stays on the right; nothing under 14 px; the summary line wraps instead of cutting; targets 44 px (the summary row is 68 px tall).

## PNGs (in `draft-a/`)

`history-xom-{desktop,phone390,phone320}` (open, top), `history-xom-total-{…}` and `history-jpm-total-{…}` (totals), `history-jpm-desktop` (with a call-away), `history-t-phone390` (empty), `history-xom-partial-{…}`, `history-xom-loading-{desktop,phone390}`, `history-xom-error-{…}`.

## Removed or renamed versus today's page

- Section "The journey" (hint "what he paid · what every call has returned · what is still sunk in a share", `PositionJourney`) → **History**, a closed disclosure whose summary line gives the count, the start date and Collected.
- Its empty state "No call written against this lot" / "The journey appears once a call is sold against these shares." → **No history yet** with what is known (last call, collected so far).
- Section "Where you have rolled it" (`StrikeJourneyChart`) → not on the position; the strike chart lives on Analysis (the value chart and journeys there).
- "Still sunk in a share" → not repeated here: the cost card above already shows adjusted basis.
- The draft's earlier grey "History" disclosure for positions without a call (the last call only) → folded into History's empty state ("Last known: …").
