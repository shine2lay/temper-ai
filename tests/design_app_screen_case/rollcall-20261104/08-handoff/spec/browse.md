# Browse (More > Browse) — spec for Frontend

Draft A v3 direction (Show&Tell d_kgrxir5ezb). Prototype: `draft-a/index.html` → More → Browse (`screens['more:browse']` in `draft-a/src/screens/browse.js`). Data: `fixtures/browse.json` (made by a seeded script; every price, bid, ask and delta that `fixture.json` already states is the same here: spot prices, your open calls' bid/ask/delta, the XOM roll and T sell candidates). Check: `node draft-a/check-browse.mjs` (exit 0, desktop 1440x900, phone 390x844 and 320x568).

## What it is

Look up any stock: where its price is, where it has been, what its calls pay and how likely they are to be called. Two views:

1. **Search** (`/browse`): a search box, recent tickers and the stocks you hold as quick picks. Calm: nothing else.
2. **Ticker** (`/browse/:symbol`): price now, price history chart, the greeks for one near call, the option chain, and "Compare dates" behind a disclosure.

Most important first: the price and today's move, then (when you hold it) what you hold and a way to the position. The greeks' meanings live in an info tip, not on the page.

## Search view, top to bottom

| Part | What it shows | Today's code / data it maps to |
|---|---|---|
| Header (drawn by more.js) | Back to More, eyebrow "More · Trade tools", title "Browse"; phone: top bar with back | route `/browse` (`pages/Browse.tsx`) |
| Search box | Field "Ticker or company" (search icon, clear ×), tonal "Look up". Typing lists up to 5 matches live under it (symbol, "You hold" tag, company, price, today's %); a tap opens that ticker. Enter opens the exact ticker, or the only match; several matches stay listed. | `SymbolSearch` / `SymbolBox`; `GET /api/search?q=` (`BrowseSearchOut`, companies first) |
| No match card | "No match for “ZZQX”" + "Check the spelling, or type the company name." Shown while typing and after Enter. | today's search with zero results |
| Recent | Chips: last tickers looked up (CSCO, XOM, AAPL), 44 px tall | new: kept on the device (localStorage, guarded in try/catch), newest first, max 3 shown |
| You hold | One tile per held stock in Positions order: symbol, price, today's %, a 1-month sparkline (neutral teal; the % carries the colour) | `HeldChips` ("Names you hold:") + `GET /api/browse/{symbol}` quote per held symbol; sparkline from `/history?days=21` |

## Ticker view, top to bottom

| Part | What it shows | Today's code / data it maps to |
|---|---|---|
| Search row | Field "Another ticker or company" (phone: "Another ticker"), "Look up", then chips: recent tickers other than this one + "All tickers" (back to the search view) | `SymbolBox` on the symbol page |
| Price card | `AAPL` Apple, tag "You hold" when held; `$228.40` big; `+$1.86 · +0.82% today` (green up, red down with "−"); "As of 10:12 AM · tastytrade". When held: "You hold 200 shares" / "2 calls sold · Nov 6 $230 · adjusted basis $207.45" (or "No call sold on them · …") and tonal "Open position" → that position's detail on Positions | `BrowseSymbol` stock panel: `BrowseOut.symbol`, `asset.name`, `quote.price`, `quote.change_abs`, `quote.change_pct`, `as_of`, `source`, `held.held`; held line from `GET /api/positions` (shares, call, adjusted basis) |
| Price history | Heading "Price history" + "hover or tap a day" (phone: "tap a day"). Card: readout (date, price, change since the range start), range buttons 1M · 3M · 1Y (3M first), area chart with price gutter on the right, x labels (5 desktop, 3 phone). Held stocks also get two reference lines: your adjusted basis (grey dashed) and your call's strike (red dotted). Legend: Price, the reference lines, and "+$X over 3M". | `PriceHistoryChart`; `GET /api/browse/{symbol}/history?days=21|63|252` (`points[].day/close`, `change_abs`). Today's 6M and 5Y windows are dropped (see below) |
| The greeks | Heading "The greeks" + info button (i) + "Nov 6 calls" (the nearest expiry). Strike chips: the 4 strikes nearest the price (held: your call's strike is picked). Five tiles: **Delta** 0.36 "36% odds of being called · your call" (lead tile, tinted), Time decay `$34.50` "a day, yours as seller", Gamma 0.040 "delta change per $1", Vega `$11.80` "per 1-point IV move", IV 24.6% "expected yearly swing". | `ChainRow.delta` (RollCall's own, `engine/delta.py`), `theta`, `gamma`, `vega`, `iv` of the picked strike at the first expiry; ×100 for per-contract money |
| Greeks tip | Opens under the chips: one plain line per greek — Delta "About the odds the call ends above its strike and your shares get called. 0.36 is about 36%. RollCall works it out itself."; Time decay "What the call loses each day as time passes (theta). When you sold it, that loss is your gain."; Gamma "How much delta moves when the stock moves $1."; Vega "How much the call price moves if expected swings (IV) change by 1 point."; IV "How much the market expects the stock to swing over a year (implied volatility)."; then "Per contract (100 shares). From tastytrade, as of 10:12 AM." | new copy; replaces today's per-column InfoTips |
| Option chain | Heading "Option chain" + "6 dates listed". Calls · Puts switch + "Odds = chance of being called" (puts: "…assigned"). Expiry chips (date + "N days"; 3 a row on phone). Table, high strike at top: Strike · Bid / ask · You collect (desktop only, bid ×100) · Odds called (bar + %, phone header "Odds") · Open int. (hidden under 360 px; still in the row detail) · chevron. The 9 strikes nearest the price; "All 13 strikes" shows every strike ("Only the 9 nearest strikes" goes back). A black price line "AAPL now $228.40" sits between the strikes around the price (same look as the ladder's). Your open call's row has a "Yours ×2" tag (phone: "Yours"). In-the-money rows are tinted. | `Chain` / `ChainTable` / `PutTable` / `ExpiryRail`: `GET /api/browse/{symbol}/chain?expiry=` → `ChainRow.strike`, `bid`, `ask`, `delta`, `open_interest`; `BrowseOut.expiries`, `expiries_total`; `ChainRow.held` for the tag; `moneyness` for the tint |
| Row detail (tap a row) | Four facts. Calls: You collect `$96.00` "a contract, at the bid"; Odds of being called 36% "by RollCall"; If called, over basis (held) / If called, you make (not held, with %); Time decay. Puts: Bid, Odds of being assigned, Open interest, Days left. Then one action line: **your call** → "Your 2 calls: sold at $2.10, $0.97 now." + "Open position"; **other strike on a held stock** → "You hold AAPL. Rolls are planned from the position." + "Open position"; **not held** → "Buy 100 shares and sell this call in one order." + solid "Open this"; **puts** → "RollCall sells calls. Puts are here to look at." | `StrikeDetail` facts: `premium`, `return_if_called_pct`, `theta_per_day`; `EntryTicket` ('Open this'); 'Roll this' becomes "Open position" (rolls are planned on the position / ladder, one place) |
| Open this → confirm | Inline under the row: "Buy 100 CSCO and sell 1 Nov 6 $59 call" / "About $5,801.00 in: $5,812.00 for the shares, less $11.00 you collect." / solid "Send order" + "Cancel". Send turns at once into a disabled "Sending…" with a spinner (`aria-busy`), then "Order sent. It's in Orders." + "See Orders". Escape cancels. | `EntryTicket` → today's buy-write order (`POST /api/orders`, the same path as the entry ticket); `can_ticket` / `ticket_reason` gate the button (no button + the reason when false); `affordable` false → the reason instead of the button |
| Compare dates (closed) | Disclosure with a one-line summary: "$230 call · best a week: Nov 6, 1.47%". Open: one bar per expiry for the picked strike: date + days, bar (bid vs the best bid), `$282.00` and "0.96% a week". | `CompareGrid` (metric "Yield on the money in" → per week = `week_yield_pct`: bid ÷ price ÷ (days ÷ 7)) |
| Source line | "Prices from tastytrade as of 10:12 AM. Odds of being called is RollCall's own delta." | `SourcesStrip` / `SourceLine` |

One solid primary per view: on a held stock there is none (Open position is tonal); on a stock you don't hold the only solid button is "Open this" in the open row (or "Send order" in the confirm).

## States

| State | Search view | Ticker view | Draft preview button |
|---|---|---|---|
| normal | box, Recent, You hold tiles | price card, chart, greeks, chain, compare (closed) | Ready |
| loading | "Getting prices…" + 8 tile skeletons | right after a pick: "Getting AAPL prices…" + skeletons for the card, chart and 5 rows (`aria-busy`). The tapped chip/tile is marked busy at once. | Loading |
| empty | "Nothing looked up yet" + "Type a ticker or a company name above. The ones you look up and the stocks you hold show here." (no recent, no holdings) | **No options listed**: price card + chart, then "Cisco Systems has no options listed, so there is no call to sell on it." + tonal "Look up another ticker" | No options |
| error | "Prices didn't load" + "Couldn't reach the price feed. Check your connection, then try again." + tonal "Try again" | "CSCO didn't load" + same sentence + solid "Try again" (`role="alert"`) | Error |
| partial | "This price is 15 minutes old: the feed is slow today." above the tiles | price card with the same 15-minute note; the chart replaced by "Price history isn't available for CSCO right now. The price and the chain below are live."; greeks, chain and compare as normal | Partial |
| no match | "No match for “ZZQX”" + "Check the spelling, or type the company name." | — | type an unknown ticker |

The "Draft preview, show as:" box at the bottom is for the draft only; don't build it. Server signals: loading = request in flight; empty = `asset.has_options` false; error = request failed; partial = `history.available` false (`unavailable_reason`) or `quote_note` set (stale quote); no match = `/api/search` returns nothing.

## Behaviours

- Click feedback before the reply: a picked chip/tile/match gets `aria-busy` and the ticker view opens straight into its loading state (draft: 0.6 s). "Try again" turns into a disabled "Trying again…" with a spinner. "Send order" turns into "Sending…" (draft: 0.9 s).
- Typing only redraws the results list, so the field keeps focus and caret. Enter: exact ticker or single match opens it; several matches stay listed; none shows No match.
- Chart: mouse hover, touch tap or drag, and keys on the focused chart (ArrowLeft/Right a day, Home the first day, End today) move the marker and the readout ("Tue, Nov 3, 2026 / $226.54 / +x% since Aug 6"); Home reads "Start of 3M". Changing range keeps the marker on today.
- Strike chips change the greeks; expiry chips and Calls/Puts change the chain (open row and ticket close). One row open at a time; tapping it again closes it; Escape closes it (or cancels an open confirm).
- "Open position" opens Positions with that position's detail; coming back to More → Browse keeps the ticker you were on.
- Focus stays on the control you used after every redraw; scroll position is kept.
- Numbers: money with cents for prices and per-contract amounts; "−" (minus sign) for falls; odds as whole %, ">99%" and "<1%" at the ends; open interest as 5.7k / 25k.

## Sizes

Desktop 1440x900 (centre column), phone 390x844 and 320x568. Phone: no sideways scroll at 320 (layout width = screen width); targets 44 px; chain drops "You collect" and shows ask under bid ("ask 0.98"); under 360 px it also drops Open int. and strike chips go 2 a row. Text: body 16 px, labels 14 px, nothing under 14 px except uppercase eyebrows (12 px).

## PNGs (in `draft-a/`, each at `-desktop`, `-phone390`, `-phone320`)

`browse-search`, `browse-nomatch`, `browse-aapl` (held, top), `browse-greeks` (tip open), `browse-chain` (your $230 row open), `browse-compare` (open), `browse-csco-confirm` (not held: Open this → confirm), `browse-empty` (no options), `browse-error`.

## Removed or renamed versus today's page

- "Browse" page head with "Names you hold:" chips → search view with **Recent** chips and **You hold** tiles (price, %, sparkline).
- Empty page "Type a company's name or a ticker to look it up" + InfoTip "What you can research here" → removed; the search view itself is the empty page (its "Nothing looked up yet" card only when there are no recent tickers and no holdings).
- Pill "You hold this" → tag "You hold" plus a "You hold 200 shares" line with "Open position".
- Pill "No options listed" → the **No options listed** card (empty state).
- `MarketSession` line and `held.note` → dropped from the price card (market hours are in the shell's top bar); stale-quote note kept as the partial note.
- Panel "Where the price has been" → **Price history**. Windows "1 month / 3 months / 6 months / 1 year / 5 years" → **1M · 3M · 1Y** (6 months and 5 years dropped: covered calls look weeks ahead; 1Y shows the yearly range).
- "The option chain" / "The put chain" → **Option chain** with a Calls · Puts switch; subtitle "N expiries listed" → "N dates listed".
- Tabs "One expiry | Compare expiries" → the chain always shows one expiry; **Compare dates** is a closed disclosure under it.
- Strike bands "Near the money | Deep in the money | Every strike" → the 9 nearest strikes, plus "All 13 strikes".
- Column groups "What it pays" / "The market and the greeks" → one row: Strike · Bid / ask · You collect · Odds called · Open int.; the greeks moved to their own **The greeks** section (one strike at a time) with the info tip.
- `Drawer` StrikeDetail → the row opens in place (row detail). Its facts "Cost to get in", "One contract costs", "Yield on that", "Most it can make", "Downside protection", "Time value in the price" → dropped from the row (the four kept: You collect, Odds of being called, If called…, Time decay); the confirm shows the money in.
- EntryTicket buttons "Open this" (kept), "Roll this" → "Open position" (rolls are planned on the position), "Look only" / "No price" → no button, a sentence instead.
- CompareGrid metrics "Premium a share" / "Delta" and "The next 6 | 12" → one metric (per week) over all listed dates; the dollar amount per contract is shown beside it.
- `SourcesStrip` → one source line at the bottom.
