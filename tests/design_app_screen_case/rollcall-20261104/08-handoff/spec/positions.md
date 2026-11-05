# Positions (list and a position's detail) — spec for Frontend

Draft A v3 direction (Show&Tell d_kgrxir5ezb). Prototype: `draft-a/index.html` → Positions (`draft-a/src/screens/positions.js`). Data: `fixture.json` (positions, calls, actions, journeys), `fixtures/position_history.json` (History, see `spec/position-history.md`) and `fixtures/positions_more.json` (stock quotes, theta and IV, upcoming events, tip words, keys, copy). Checks: `node draft-a/check-positions-more.mjs` (this spec: desktop 1440x900, phone 390x844 and 320x568) and `node draft-a/check-positions.mjs` (the first Positions draft); both exit 0.

This adds to the first Positions draft what RollCall's audit of option A v3 (rm-57e6ca43) found missing: today's two lanes, the three row facts, the full detail (open actions, legs and quotes, upcoming events, the journey chart) and the desktop keys.

## List

### First view

Eyebrow "Positions · 8 holdings · as of 10:12 AM" with **Keys (i)** on the right (desktop). Headline "**3 of 8** need you this week." and one sentence naming them: "XOM's roll is due, JPM may be called tonight and T has no call. The other 5 need nothing from you now." Then two lanes. On the phone the dark band says "8 holdings · **3 need you** this week".

### Lanes

| Lane | Who is in it | Order | Hint (right of the title) | Today's code |
|---|---|---|---|---|
| **Needs attention** (count in coral) | positions whose status asks for the owner now: roll due, may be called (assignment risk), no call (uncovered) | most urgent first: roll due, may be called, no call | "roll due · may be called · no call" | `Positions.tsx` lane "Attention" |
| **Later** (count in grey) | everything else: covered and safe, expiring as planned, a roll sent, and any position whose open action was marked done | soonest expiry first, then the smaller price cushion | "nothing to do now · soonest expiry first" | lane "Later" |

Needs attention empty (every action done, or nothing needs him): a green line in its place, "✓ Nothing needs attention. Next expiry Fri 11/6 (4 calls).", headline "Nothing needs you." and "All 8 positions are in Later. Nothing needs you now." Later is left out when empty.

### Row

Each row is one button that opens the position (`data-act="positions-open"`, `data-sym`): a coloured left edge (the status colour), the symbol, the call ("11/6 $112 call · 2 days left", or "No call sold"), a status chip on the right, a chevron. The row facts follow today's meanings exactly:

| Fact | Shows | Formula (today's glossary) | Colour |
|---|---|---|---|
| **Protection** | "ITM 2.3%" / "OTM 0.7%" | (price − strike) ÷ price; ITM = above the strike (`itm-depth`) | red when in the money, amber when out of the money by under 1%, green otherwise |
| **Extrinsic left** | desktop "$0.13 a share", phone "$0.13 left" | call price − max(price − strike, 0) (`extrinsic`) | ink |
| **If flat** | "0.1% in 2 days" | time value left ÷ (price − call price), over the days left; never scaled to a year under 30 days (`ann`) | ink, the % bold |

- Desktop: a header row above each lane's rows ("Protection · Extrinsic left · If flat"), each with an info tip (i) in the first lane, giving the meaning, the formula and a worked example (XOM: (114.60 − 112) ÷ 114.60 = ITM 2.3%). The name and shares sit under the symbol.
- Phone: one key line above the lanes, "Each row: **Protection** · **Extrinsic left** · **If flat**" with one tip holding all three meanings; each row shows the three facts on one line under the call ("ITM 2.3% · $0.13 left · 0.1% in 2 days"). At 320 the facts wrap to a second line and the shares count hides, nothing is cut. The rest of the numbers live in the detail.
- No call (T): "Last: Oct 30 $27 call expired worthless" in place of the facts.
- Marked done: the chip becomes a grey "Marked done" and the edge turns grey; the row moves to Later.
- Stale price (partial): a "price from 9:58 AM" tag on that row and an amber note above the lanes, "DIS has no fresh price since 9:58 AM. Its row shows the last price, marked stale." with Try again.

Numbers (fixture, must hold): XOM ITM 2.3% · $0.13 · 0.1% in 2 days; JPM ITM 2.7% · $0.22 · 0.09% in 2 days; AAPL OTM 0.7% · $0.97 · 0.4% in 2 days; KO OTM 2.6% · $0.01 · 0.01% in 2 days; DIS OTM 2.3% · $0.93 · 0.8% in 9 days; MSFT OTM 1.5% · $6.47 · 1.3% in 16 days; PFE OTM 3.6% · $0.23 · 0.9% in 16 days. Percentages under 0.1 show two decimals.

### List states

| State | Headline / sub | Body | Server signal |
|---|---|---|---|
| normal | "3 of 8 need you this week." + sentence | two lanes | positions read |
| loading | "Reading your positions…" / "Last read 10:12 AM. The list fills in as soon as tastytrade answers." | spinner line + two lane skeletons (`aria-busy`) | request in flight |
| empty | "No positions yet." / "Buy 100 shares of a stock and sell a call on them: each one shows here." | card "You hold no shares yet. Covered calls start with 100 shares of a stock." + tonal "Find a stock to start" (opens Screener) | no lots |
| error | "Positions didn't load." / "Nothing changed in your account." | card (`role="alert"`) "Couldn't read your positions from tastytrade. Your shares and calls are safe at the broker. Check your connection, then try again." + "Try again" + "Check the connection" (Settings) | request failed |
| partial (stale price) | normal | amber note + stale tag per row (above) | a quote older than the read |

"Try again" turns at once into a disabled "Trying again…" with a spinner. The "Draft preview, show the list as:" row is for the draft only; don't build it.

## A position's detail

Order, top to bottom. What matters now comes first; the lower parts are closed disclosures with a one-line summary, open state kept per position while the app runs.

| # | Part | What it shows | Today's code / data |
|---|---|---|---|
| 1 | Head | "‹ All positions" (focus lands here) and Keys (i) on desktop; eyebrow "Exxon Mobil · 200 shares · as of 10:12 AM"; the symbol with its status chip; one sentence ("The $112 call is $2.60 in the money and expires Friday.") | page head, `StatusPill` |
| 2 | Call card | unchanged from the first Positions draft: call, expires, in the money, kept if closed now; the price line; the suggestion; one primary ("Review the roll") and plain links | lead Panel, `PositionExpiry`, bignums |
| 3 | **Open actions** (count) | each open action for this stock: its chip (Do today / Today, before close / This week / Watch), the kind (Roll, May be called, Sell a call, Expires as planned) and "due Fri 11/6"; **Open in Today** (`data-act="action-open" data-id`) and **Done**. None open: "No open actions." plus the last one done ("Last done Nov 3: …") | Panel "Open actions (n)" (`AttentionList`), `GET /api/actions?symbol=` |
| 4 | **Legs and quotes** (closed) | summary "200 shares at $114.60 · 2 calls at $2.73". Open: "Quotes as of 10:12 AM" + tip (bid, ask, mark, theta), then two leg cards. Shares: bought at, bid, ask, mark, gain now. Call: "2 × 11/6 $112 call, sold", sold at and premium in, bid, ask, mark, delta, theta a day (what he earns), IV, gain now. No call: "No call. 400 shares earn nothing until one is sold." | Panel "Everything about this position" → `LegsTable`, `PositionGroups` Quotes; today has no bid/ask here (it is on the Trade view), the legs read adds it |
| 5 | **Coming up** | a short timeline: Today (price and how far in or out of the money), each ex-dividend and earnings date before expiry (amount, "estimated" when the company hasn't said), then the expiry with what happens ("In the money: the shares are called away at $112.00 unless you roll." / "Out of the money: it expires and you keep the premium."). One line after: "After it expires: ex-dividend Fri 11/13, $0.99 (estimated) · earnings Fri 1/29 (estimated)". Header right: the next thing ("ex-dividend tomorrow", "call expires in 2 days"). | Panel "Upcoming" (events, `danger`) |
| 6 | Your cost | unchanged (first draft) | `PriceAndSunk` |
| 7 | **Journey** (closed) | summary "5 calls since May 4 · rolled once · $112 call open". Open: a drawn chart of the price (ink line) and each strike sold as a step (teal; the open call dashed), your cost (dotted coral), a mark where each call ended (amber ↻ rolled, red diamond called away, green dot expired, white ring open now), strike labels, month labels, a legend and one sentence ("XOM went from $108.20 to $114.60. Of the 5 calls you sold, 3 expired, 1 was rolled, 1 is open now."). | CollapsibleSection "Where you have rolled it" (`StrikeJourneyChart`), `GET /api/analysis/{symbol}` |
| 8 | History (closed) | as `spec/position-history.md` | CollapsibleSection "The journey" |

### Coming up warning

When the call is in the money and its time value left is less than a dividend before expiry, the card gets the coral edge and that stop reads in red: "Time value left $0.22 is less than the $1.50 dividend: the call may be exercised the night before." (JPM). Otherwise one plain line under each event: "Time value left … is more than the dividend, so an early call is unlikely.", "The call is out of the money, so an early call is unlikely.", earnings "Before the call expires: the price can jump either way that day." No events on file: "No ex-dividend or earnings date on file."

### Journey chart rules

- Same read and the same states as History (loading "Getting trades…" skeleton, error "Chart didn't load", partial "Trades before … aren't read yet, so the chart starts there.", none "No history yet" with "The chart of T's price and the strikes you sold draws once RollCall reads its trades from tastytrade.").
- Every mark sits inside the chart and on its strike step; strike labels never overlap each other (a label that would is left out; the step and its mark stay); month labels keep 8 px apart (a part month at the start is dropped). Labels have a light halo so the price line never hides them.
- Mark counts must match History: XOM 3 expired, 1 rolled, 1 open; JPM 1 expired, 1 called away, 1 open.
- Analysis draws the same chart: build one shared chart component for both.

### Numbers (must hold, the prototype throws at load if not)

- Shares gain now = (mark − bought at) × shares: XOM (114.60 − 108.20) × 200 = +$1,280.
- Call gain now = premium kept if closed now: XOM −$176 of $370.
- Theta a day = −theta × 100 × contracts: XOM 0.05 × 200 = +$10; JPM +$9.
- Stock mark = the position's price; call bid, ask, mark and delta are the fixture's; JPM's ex-dividend (Thu 11/5, $1.50) is the fixture's `ex_dividend` and `dividend`.
- Every event date is a weekday after today.

## Behaviours

- **Done** (on an open action, or `d`): turns at once into a disabled "Marking done…" with a spinner and a dark toast "Marking XOM's action done…"; then the action reads "✓ Roll marked done. It moved to Later." with **Undo**, the toast says "XOM: Roll marked done. It moved to Later." with Undo and ×, the row moves to Later. Undo puts it back in Needs attention ("XOM: Roll is open again, back in Needs attention.").
- **Open in Today**: goes to Today and scrolls to that action's card with a short teal ring; focus on its first button. Cards that sit in Today's Watching (AAPL, KO) open that disclosure first.
- Back keeps the list's scroll and puts focus on the row that was open.
- Disclosures and tips never move the scroll; only one tip is open at a time.

### Desktop keys

Shown in the **Keys (i)** tip at the top of the list and the detail ("Keys on this screen"):

| Key | Does |
|---|---|
| `j` / `k` | next / previous position (on the list: moves focus across both lanes; in a detail: opens the next or previous position's detail) |
| `Enter` or `o` | open it |
| `d` | mark its open action done (none: a toast "T has no open action to mark done.") |
| `Esc` | closes an open tip first, then back to the list |

Never while typing in a field, with the roll sheet open or with Ctrl/Cmd/Alt held. Phone has no keys and no Keys tip. Focus is always visible (row outline).

## Sizes

Desktop 1440x900 (centre column), phone 390x844 and 320x568. Text 14 px or more (body 16); targets 44 px; one solid primary per view; nothing cut off, the page never wider than the screen. Phone detail: leg cards stack; Coming up dates narrow to 76 px; Open actions buttons wrap under the kind.

## PNGs (in `draft-a/`, each at desktop, phone390 and phone320 unless noted)

`posmore-list` (lanes), `posmore-later`, `posmore-tip` (Protection tip open), `posmore-detail-xom` (desktop and phones), `posmore-detail-t` (phones, no call), `posmore-legs-xom`, `posmore-legs-t` (phones), `posmore-upcoming-jpm` (warning), `posmore-journey-xom`, `posmore-journey-jpm`, `posmore-done-busy`, `posmore-done`, `posmore-open-in-today`, `posmore-lane-empty`, `posmore-list-{loading,empty,error,stale}`, `posmore-keys-desktop`, `posmore-keys-done-desktop`.

## Removed or renamed versus today's page

List (`pages/Positions.tsx`):
- Lane "Attention" → **Needs attention**; its hint "expiring this week · roll suggested · assignment risk · uncovered" → "roll due · may be called · no call" (expiring-this-week calls that are safe now sit in Later).
- Lane "Later" hint "nothing to do: inside the band, a hold, or a roll card that was closed" → "nothing to do now · soonest expiry first".
- Empty Attention "✓ Nothing needs a look this week · next expiry <date> (<n>)" → "✓ Nothing needs attention. Next expiry Fri 11/6 (4 calls)."
- Table columns "Symbol · Strike / Expiry (days) · Protection · Extrinsic left · If flat · Status" → a row per position (symbol and call on top, facts below, status chip on the right); the three fact names and meanings are kept.
- Attention rows' own sentence and button → in the position's detail (call card, Open actions) and on Today.
- Keyboard hint "j/k move · Enter expand · o detail" → the **Keys (i)** tip; Enter now opens the position (no inline expand).
- "Group by" (Underlying / Expiry), the "Sort" select and "Scan now": not drawn. The lanes fix the order (urgency, then soonest expiry); the as-of time and Try again cover a fresh read. Frontend: keep them only if the owner asks.
- Empty "You hold nothing in this <broker> account yet. When you buy shares or sell a call, it shows here." → "No positions yet." + "You hold no shares yet. Covered calls start with 100 shares of a stock." + "Find a stock to start"; failed and stale states keep their meaning with new words (above); "unconnected" is Settings' state, not drawn here.

Detail (`pages/PositionDetail.tsx`):
- "← Positions" → "‹ All positions".
- Lead Panel buttons "Roll this / See the order / See the ladder", "Details", "See the whole ladder" and "Why — the numbers behind this" → the call card's "Review the roll", "Choose another call", "Let it be called" (first draft).
- Bignums (PriceAndSunk, Extrinsic left, Protection) → call card figures, row facts and Your cost.
- Panel "Everything about this position" (PositionGroups Position / Chain / Quotes + LegsTable) → **Legs and quotes** (legs, bid/ask/mark, delta, theta a day, IV, gain now), with Collected and margin interest in History. Not drawn: Maintenance, Position net liq, Locked-in, Captured, Break-even (Price cushion = Protection; Stock average price = "Bought at"; Days to expiry is in the call line).
- Panel "Upcoming" → **Coming up** (same events and danger rule, drawn as a timeline with Today and the expiry).
- Panel "Open actions (n)" → **Open actions**, moved up under the call card, with Open in Today and Done.
- AlarmPanel (his own price alarm): not drawn here (see `spec/alerts.md`).
- CollapsibleSection "Where you have rolled it" (StrikeJourneyChart) → **Journey**, a closed disclosure with the chart and one sentence.
- CollapsibleSection "The journey" → **History** (`spec/position-history.md`).

## Draft seams (not to build as drawn)

- Chip classes: the draft's page.html uses `.sent` for the sent-order view, so the "Roll sent" chip is `.chip.rsent`; in the build, give status chips their own namespace.

- Open in Today is handled in `positions.js` for the draft; Today's own file (Design #191) takes it over.
- The sidebar and tab-bar badges (Today 3, Positions 8) don't change with Done or the list states in the draft: build them from the same actions and positions read.
