# Ideas (More > Ideas) — spec for Frontend

Draft A v3 direction (Show&Tell d_kgrxir5ezb). Prototype: `draft-a/index.html` → More → Ideas (`screens['more:ideas']` in `draft-a/src/screens/ideas.js`). Data: `fixtures/ideas.json` (numbers agree with `fixture.json` and `fixtures/screener.json`). Check: `node draft-a/check-ideas-screener.mjs` (exit 0).

## What it is

One place for everything RollCall suggests you could do this week that brings money in: rolls and calls on stocks you hold, and new positions from the last screener run. Each idea says what to do, what it pays, why, and the risk, in plain words. The one thing to do first is the only solid button on the screen.

Things that need a decision today (XOM roll, JPM before the close) also stay on Today; Ideas is the full list, ranked.

## Parts, top to bottom

| Part | What it shows | Today's code / data it maps to |
|---|---|---|
| Header (drawn by more.js) | Back to More, eyebrow "More · Trade tools", title "Ideas" (phone: top bar with back) | route `/actions` (and `/recommendations`, which redirects to it) |
| Money band (dark) | "Could come in this week" + info tip; big total `$115`; "from 4 ideas · 2 on stocks you hold, 2 new"; one bar per idea (XOM $8, T $40, CSCO $43, VZ $24), teal = stocks you hold, amber = new, per lot; legend | sum of `Recommendation.est_net_credit` (held ideas, net credit) + `StockScreenRow.entry` premium × 100 (new ideas, one lot). Tip text = `ideas.json.tip` |
| Filter | Segmented: `All 4` · `Stocks you hold 2` · `New 2` (counts live) | replaces today's tabs + rule/position filters |
| Group "On stocks you hold" | "N to look at", then idea cards | `GET /api/recommendations` (`RecommendationsOut.recommendations`, status open, not snoozed) — `act-xom-roll`, `act-t-new-call` |
| Group "New positions" | "N to look at", then idea cards | today's "This week's entry picks" (`isEntryPick`), i.e. qualified rows of `GET /api/screener` not held — CSCO (rank 4), VZ (close call) |
| Idea card | symbol, chip (Do today / This week / New / Under your $50 floor), company name (desktop), title ("Roll the call to Nov 20"), `+$8` + pays words ("net, and the strike goes up $2"), reason sentence, risk box ("Risk: …"), buttons | `Recommendation.action`, `.covered_call`, `.target`, `.est_net_credit`/`.quoted_net_credit`, `.rationale` → reason; risk sentence = from the rule that made it (if-called / breakeven); new ideas from `StockScreenRow.entry` (strike, expiry, bid, breakeven) |
| Card buttons | 1. go button: held → "See the ladder" (`data-act="ladder-open" data-sym="XOM|T" data-from="card"`, opens the existing ladder); new → "Start a position" (`data-act="entry-open" data-sym="CSCO|VZ" data-from="ideas"`, opens the entry ticket, task #186). Solid primary only on the first visible card, tonal on the rest. 2. "Details" (ghost, toggles the details list, `aria-expanded`). 3. "Not now" (ghost) | ladder = existing ladder screen; entry ticket = #186 |
| Details list | label/value rows, e.g. "Buy back: 2 of Nov 6 $112 at $2.75", "Sell: 2 of Nov 20 $114 at $2.79", "You get: +$8 now, $400 more if called", "Price now: $114.60" | `Recommendation.covered_call` / `.target` legs, `quote_side`, `priced_at` |
| Hidden card stub | "XOM is hidden until tomorrow." + "Undo" | today's Snooze (`Snoozes` map, `lib/metrics/recs.ts`, snooze until tomorrow) |

## States

| State | What shows | How to get it in the draft |
|---|---|---|
| normal | band, filter, both groups, 4 cards | Draft preview "Ready" |
| loading | skeleton band, filter pill and two cards; `aria-busy="true"`, screen-reader "Loading ideas"; no solid button yet | "Loading" |
| empty | bulb icon, "No ideas this week", "Every stock you hold has a call working, and your last screener run found no new stock that passed.", primary "Open the screener" | "Empty" |
| error | unplugged icon, "Ideas didn't load", "RollCall couldn't reach tastytrade. Your positions and orders are unchanged.", primary "Try again" (`role="alert"`) | "Error" |
| partial | held ideas only (total $48, filter "New 0"); in "New positions": "New-position ideas need a screener run from the last 5 days. Your last run was Thu Oct 29." + tonal "Open the screener"; group meta "need a screener run" | "Partial" — server: screener run older than 5 days (`ScreenerOut.stale_fetched_at` set, no rows) |

The "Draft preview, show as:" box at the bottom is for the draft only; don't build it.

## Behaviours

- Click feedback before any reply: "Try again" turns at once into a disabled "Trying again…" with a spinner (`aria-busy`), then the list comes back (draft: ~1.1 s).
- "Not now" replaces the card with the hidden stub in place, focus moves to "Undo"; the total, bars and the group's "N to look at" drop that idea at once (filter counts stay). "Undo" brings it back, focus on its "Not now".
- "Details" ↔ "Hide details"; focus stays on the button.
- Filter keeps scroll position and focus; its counts are the ideas the current data has.
- The solid primary moves to the first visible card when the first is hidden or filtered out (one solid primary per view).
- "Open the screener" (empty, partial) opens More > Screener at its top.
- Info tip: round "i" button (44 px hit area), `aria-expanded`, tip text below the total.
- Sort inside a group: Do today first, then This week, then by pay. New positions: passed stocks by screener rank, then close calls.
- Held-stock ideas never open the entry ticket; new-position ideas never open the ladder.

## Sizes and type

Desktop 1440×900 (center column), phone 390×844 and 320×568 (cards full width; phone buttons: go button full width, Details + Not now side by side, 44 px+). Body 16 px, labels 14 px, 12 px only for uppercase eyebrows. Tokens and classes from `draft-a/src/page.html` (`.card`, `.chip`, `.btn`, `.p-h`, `.skel`, `.tipbtn`).

## PNGs

- `draft-a/ideas-desktop.png` (1440, normal), `draft-a/ideas-phone.png` (390, normal)
- Every state at 1440/390/320, scrolled end to end: `/tmp/draft-a-187/ideas-<state>-<desk-1440|phone-390|phone-320>-<n>.png` (re-made by `node draft-a/check-ideas-screener.mjs`)

## Removed or renamed versus today's page

Today's page is "Actions" (`frontend/src/pages/Actions.tsx`; `/recommendations` redirects there).

| Today | Draft A |
|---|---|
| Page title "Actions" | "Ideas", under More > Trade tools; urgent items also on Today |
| Tabs "Needs attention" / "Everything" | Removed; one list, filter "All · Stocks you hold · New" |
| "This week" checkbox | Removed; Ideas is always this week |
| "Show snoozed (N)" | Removed; a hidden idea shows a stub with "Undo" until tomorrow |
| Position filter, rule filter | Removed (four to eight ideas a week don't need them) |
| Group "Needs attention" | Merged into "On stocks you hold" (Do today chip, sorted first) |
| Group "This week's entry picks" | Renamed "New positions" |
| Groups "Sent", "Everything else", "Closed" | Removed from Ideas; sent orders live in Orders, history in a position's history |
| Group "About positions you no longer hold" | Removed; ideas for stocks no longer held are not shown |
| Buttons "Done" / "Snooze" / "Dismiss" (with reason) + undo toast | "Not now" (= snooze till tomorrow) with in-place "Undo"; "Done" happens by sending the order from the ladder or ticket; "Dismiss" removed |
| One "Details" toggle per card | Kept: "Details" / "Hide details" |
| "Keyboard shortcuts" help (j/k/d/o/Esc) | Removed from view (keys may stay, no visible panel) |
| Empty "Nothing needs attention." / "All N rolls handled this week." | "No ideas this week" + "Open the screener" |
| (none) | New: money band with total and bars; New-position ideas with "Start a position" (entry ticket) |
