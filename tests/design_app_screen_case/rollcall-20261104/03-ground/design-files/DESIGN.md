# RollCall mobile, direction A: action first ("Tide Table")

Design #171, 2026-11-04. One of two phone directions for RollCall; the owner picks one. Data: `../fixture.json` only (an invented sample book, not the owner's holdings). Problems P1-P12 and keeps K1-K8 are from the #170 phone read (`../index.html`); journeys J1-J6 from `../journeys.md`.

## The idea
You open the app to answer two questions: am I OK, and what needs me now? Direction A answers both on the first screen and lets you act without leaving it.

- **Today** (the home tab) is one status band and a short ranked "Needs you" stack. The band holds this week's premium at stake, the calls expiring Friday and the margin cushion with its word grade. The stack holds the open actions, most urgent first, each with its one recommended action.
- **You act in a bottom sheet** that rises over Today: the roll or sell ticket with the numbers that matter, then review, then send, then pending, then done. Decisions that change nothing at the broker (snooze, mark done, let it be called) can be undone for a few seconds.
- **Everything else waits one tap away**: watch items, the book's numbers, done items, positions and history sit behind disclosures and tabs that say what is inside.

The name: like a tide table, the week runs toward Friday's expiries; the band shows where you are in it.

## Principles
1. Status, then the decision, then the detail. The first screen at 390 and at 320 shows the status band and the top action; numbers and explanations open on demand (owner m60552).
2. One solid button per view, always the recommended step. Other steps are tonal or quiet (fixes P8).
3. Say it in words and colour together: severity chips carry "Do today", "Today, before close", "This week" (K2).
4. Every press answers at once: the button changes to its pending look before the broker replies; the result says what happened and what to do next (owner Board bp-0550c87d, bp-9345c6a9).
5. The real price before anything is sent; "Nothing is sent until you press Send roll" stays (K7).
6. Drawn data, not tables: a week bar toward Friday, a cushion ring, price lines that put strike, spot and basis on one axis, and a value bar of the book by status (owner 10-19: modern and dynamic, never a flat list).

## What direction A fixes
| Finding | How direction A fixes it | Measured by |
|---|---|---|
| P1 Must: what needs you is 3.3 screens down | Today's band is followed directly by the Needs you stack; the top card's headline is in the first screen at 390 and 320 | measure: first card top within the first view |
| P2 Must: header and number strip don't fit | One-line top bar (mark, SIMULATED, freshness with the time in full); no sideways strip; the book's numbers open in a grid under "Your book" | measure: page width equals phone width, no text outside the screen |
| P4 Must: the roll ticket hides the choice | The ticket opens on the suggested roll: what it pays and the new strike and date come first, then a price line, then both legs. Other calls are cards behind "Choose another call", grouped by expiry, each saying what it pays and whether it's inside the rules. Close is in the sheet's header at all times | measure: result and Close inside the first view at 320 |
| P5 Must: Positions is a squeezed desktop table | One card per stock: symbol, status word, the call and days left, and a drawn cushion bar; a value bar groups the book by status. No keyboard hints | measure: no horizontal overflow, nothing cut |
| P3 Should: ten tabs in two rows, no Alerts tab | Five tabs in one row: Today, Positions, Orders, Alerts, More. Setup pages live under More. The current tab is marked by a pill, bold label and colour | measure: one row, 64 px |
| P6 Should: small text in eleven sizes | Four sizes (36/20/16/14); sentences, buttons and inputs 16 px; nothing under 14 px | measure: size floor and distinct sizes per view |
| P7 Should: small tap targets | Every control at least 44 x 44 px; primary buttons 48 px | measure: targets |
| P8 Should: filters and eight links per card | No filters on a three-item stack; one action per card; the rest in the card's sheet | review: one solid per view (measured) |
| P9 Should: long explanations always open | A short line plus "Why" disclosures; the practice-broker notice is one line on Orders | review |
| P10 Could: Settings is one 27-screen page | Out of scope for this direction: More lists the setup pages, each its own page | not designed here |
| P11 Could: loading says "from —" | Loading keeps the shapes, says "Reading your book from the broker…" with the last known time, and after 8 s "Still reading — the broker is slow right now." | review |
| P12 Could: error header collides with title | Fixed by P2's one-line top bar | measure |

Kept from today: K1 plain sentences with real numbers (the fixture's headlines are used word for word), K2 urgency in words and colour, K3 a position leads with one recommendation and one solid button, K4 alerts grouped by day with one button each, K5 errors and empty pages in one sentence with one way forward, K6 loading keeps the page's shape, K7 SIMULATED on every screen, price before sending, the "Now" marker in the strike list and the order brake, K8 the cushion as one number with a word grade.

## Screens and journeys
| Journey | Where | Steps in the prototype |
|---|---|---|
| J1 Glance | Today | status band, Needs you (3), Watching (2), Your book, Done lately |
| J2 Act | Today card, then its sheet | card button or card title, sheet with headline, why, key numbers, the one primary and quieter choices: choose another call, let it be called away, snooze, mark done (undo) |
| J3 Roll | Roll ticket sheet | suggested roll, choose another call (12 candidates in two expiries), review, send, pending, sent or refused |
| J4 One stock | Positions, then a stock | value bar, cards by status, detail with recommendation, price line, facts, the numbers behind it, history |
| J5 Alerts | Alerts tab | unread first, grouped by day, one button to the action, mark all read |
| J6 Orders | Orders tab, then an order | working first, cancel with confirm, pending, cancelled or a safe failure; finished orders; the order brake |

Sheets: action, roll ticket (XOM), sell ticket (T), order (KO), and a JPM roll-choices sheet. The sample data has roll prices for XOM only, so JPM's sheet says so instead of inventing prices.

## States (every screen)
- **Normal**: the sample book as of 10:12 AM, market open.
- **Loading**: skeletons in the final shapes, "Reading your book from the broker…", the last known time, the tab bar and SIMULATED stay; after 8 s the slow line.
- **Empty**: a connected account with $25,000 cash and no shares: each screen's own sentence from the fixture and one way forward ("Find a stock to start").
- **Error**: the broker is unreachable: a banner with the time of the last good numbers and Try again; sending is paused, and tickets say so on the disabled Send. Orders and Alerts say what didn't load and that nothing is lost.
- **Partial**: the broker left out buying power and margin excess, and DIS's price is stale: the cushion shows "Not graded" with its last grade, the missing figures say why, DIS is marked stale.
- **In-flight results** (inside sheets): pending, sent, refused ("The roll wasn't sent: the broker refused the price. Nothing changed in your account."), cancelled, and undo toasts.

## Type
- Display: Bricolage Grotesque (OFL), optical size on, 700. Body: Atkinson Hyperlegible Next (OFL), chosen because money figures must not be misread (distinct 0/O, 1/l/I). Both use tabular figures where numbers line up. Fonts are embedded in the prototype, so they render the same everywhere.
- Scale: display 36/40, title 20/26, body 16/24, label 14/20. Uppercase eyebrows use the label size at 700 with 0.06em tracking. Four sizes, by design: the status figure needs a display size; everything else is title, body or label.

## Colour
- Ink (cool navy) for the top bar and the status band, giving the first view depth; warm paper for content; white cards.
- Tide (petrol) is the action colour: the one solid button, links, the active tab.
- Signals: coral for Do today and costs, amber for before-close and stale, week-blue for This week, sea-green for credits, covered and the green grade.
- Values in `tokens.json`: OKLCH with hex fallback, every pair used for text checked at 4.5:1 or more; control borders and icons at 3:1 or more.

## Spacing, shape, depth, motion
- 8 px base (4, 8, 12, 16, 24, 32, 48). 16 px screen and card padding; 8 px inside a group, 24 px between groups.
- Radius 12 for cards and buttons, 20 for sheets, pill for chips.
- Three elevations: cards (e1), the top card (e2), sheets (e3).
- Motion: press scale, cards rise in with a stagger, the sheet slides up, cards that are done collapse away, the ring and the status figure draw in once, working orders pulse. All off under reduced motion.

## Components
Top bar · status band (figure, week bar, cushion ring) · severity chip · action card (lead and compact) · disclosure row (label + one-line summary) · bottom sheet (header with Close, scrolling body, sticky footer) · price line (strike, spot, basis on one axis) · candidate card (radio) · leg row · result block · banner (error, partial) · skeleton · toast with Undo · tab bar · order card · alert card · position card with cushion bar · value bar.

Top bar on narrow phones: the RollCall wordmark shows from 400 px wide (the wave mark always shows); under 340 px the freshness word (open, offline, partial) drops and the time stays, the banner below still says what is wrong. SIMULATED never drops.

## Bars (checked by `tools/measure.mjs`, exit 0 only when all pass)
At 390 x 844 and 320 x 568, for every screen and sheet in every state:
- layout width equals the screen width; no text outside the screen; nothing cut by ellipsis, clamp or overflow, sideways or (inside a fixed box) up and down;
- no words run together (two pieces of text touching on one line with no space);
- text 14 px or more, text runs over 64 characters 16 px or more, at most 4 sizes per view;
- every control 44 x 44 px or more, and nothing sits on top of it (the 6-second toast excepted: while it shows, the page pads its scroll so content and focus move clear of it);
- text contrast 4.5:1 (3:1 for large text) against its real background;
- axe-core (WCAG 2.2 A/AA rules): 0 serious or critical;
- at most one solid primary button active per view;
- Today: the top Needs-you card starts inside the first view; sheets: Close inside the first view;
- no console errors; both fonts loaded.

The same script also passes at 360 x 740, 375 x 667, 414 x 896 and 430 x 932 (`node tools/measure.mjs --sizes 375x667,360x740,414x896,430x932`).

## Not in this direction
Setup pages (Settings, System, Screener, Browse, Analysis, How to trade, Glossary) are listed under More, not redesigned. Dark theme: not drawn; the tokens leave room for it. Desktop: the prototype shows the phone; RollCall's desktop layout is unchanged.
