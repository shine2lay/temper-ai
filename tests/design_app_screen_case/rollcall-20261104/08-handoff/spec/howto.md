# How to trade (More > Learn > How to trade) — spec for Frontend

Draft A v3 direction (Show&Tell d_kgrxir5ezb). Prototype: `draft-a/index.html` → More → How to trade (`screens['more:howto']` in `draft-a/src/screens/howto.js`). Words: `fixtures/howto.json` (today's words, tightened; meaning kept). Check: `node draft-a/check-howto-glossary.mjs` (exit 0).

## What it is

Today's `/how-to-trade` (`frontend/src/pages/HowToTrade.tsx`, steps in `HOW_TO_STEPS`, the account line from `lib/guideAccount.ts`): six steps, in order, from an empty app to an order with your broker. In option A it becomes a numbered path with **one step open at a time**, and each step has buttons that open the screen where you do it.

First view (desktop and phone): the sub line, then straight away step 1 open with its one-line summary and its "Do it here" button. There is no "Practice or real?" card (owner, comment #2 on v2: "most of the accounts are real, we dont need to show simulated"); the only card above the steps is "No broker yet", in the Empty state. The longer explanation sits under the button; the other five steps are one tap away.

## Parts, top to bottom

| Part | What it shows | Where its text comes from today |
|---|---|---|
| Header (drawn by more.js) | desktop: back link "More", eyebrow "More · Learn", h1 "How to trade"; phone: top bar with back and "How to trade" | `<h1>How to trade</h1>` |
| Sub line | "Six steps, in order, from an empty app to an order with your broker." | same words, `page-head` span |
| "No broker yet" card (Empty only) | plug icon, label "No broker yet", then the no_broker sentence (see States). Not drawn in any other state: the steps start right under the sub line. | `AccountLine` → `guideAccountLine(settings)`, its no-broker line only |
| Last-good-read line (Partial only) | amber dot, 14 px bold: "From the last good read at 9:41 AM; the newest read failed.", right under the sub line | NEW |
| Path (desktop only) | six numbered nodes on a line, with short names: Connect, Allow orders, Go live, Find a stock, Read the ticket, Roll and watch. Done steps (before the open one) are filled teal and the line fills up to the open step; the open node is ink with a halo. | NEW (today's steps are one long list); names are new short forms of the step titles |
| Step card (desktop) / open row (phone) | eyebrow "Step N of 6" (desktop), icon, title, one-line summary, "Do it here" buttons, the explanation, a grey box for the paired cases (steps 3, 4, 5), "Words on this step" (step 4), Back/Next | `HOW_TO_STEPS[n]`: `title`, `body`, `links`, `terms` |
| Step list (phone only) | six rows: number in a 44 px circle, title, chevron; a line joins the circles. The open row becomes a white card with its content under the title. | the `ol.howto-list` |
| Footer | book icon, "Words you don't know are in the Glossary, with how each one is worked out." + "Open the Glossary" | today: "Words you do not recognise are in the glossary, with the formula behind each one." |
| Draft preview picker (prototype only, not to build) | Normal / Loading / Empty / Error / Partial | — |

### The six steps (title · one-line summary · Do it here buttons)

Text in `fixtures/howto.json` → `steps[]` (`title`, `line`, `body[]`, `cases`, `links[]`, `terms[]`). Body paragraphs are today's paragraphs, tightened; where the one-line summary already says a paragraph's first sentence, the paragraph no longer repeats it.

| # | Title | One-line summary (NEW, short form of today's first paragraph) | Buttons: label · where (prototype target → today's route) |
|---|---|---|---|
| 1 | Connect your broker | RollCall reads your positions, balances and prices from one broker. | Connect a broker · In Settings (`more:settings` → `/settings#connection`) |
| 2 | Let RollCall place orders, and see what it may place | One switch decides whether RollCall may send anything at all. | Placing orders · In Settings (→ `/settings#trading`) |
| 3 | Turn on live orders, and know what that means | A deliberate second switch lets orders spend your own money. | Can orders go live here? · In Settings (→ `/settings#connection`); Live orders · In Settings (→ `/settings#trading`) |
| 4 | Find a stock to write a call on | The Screener ranks stocks by your rule; Browse prices the one you name. | Find one by the rule · In the Screener (→ `/screener`); Look a name up · In Browse (→ `/browse`). Words: call, strike |
| 5 | Read the ticket, and pick the call you want | The ticket says what the order is, what it pays, and what stands in its way. | Open a ticket · XOM's roll ticket (prototype opens the v3 roll ticket; today → `/ladder`) |
| 6 | Roll the call before it takes your shares | Today says which calls need a roll and why; Orders is where you watch them. | What needs you · The Today tab (→ today's `/actions`); Roll a call · XOM's ladder (→ `/ladder`); What you've placed · The Orders tab (→ `/orders`) |

Paired cases (owner-approved b061 pairs; never show one without the other):
- Step 3, box "First: is there a switch at all?" shown **before** the paragraphs: read-only server / paper or sandbox login.
- Step 4, box "A new position is two orders": the two orders / one order at a broker that takes both ("The order").
- Step 5, box "If the market is shut": new position greys Send and says when the market opens / when Send still works, what happens to the order until it opens.
Capability-neutral as today: never say what a given broker takes.

Each button: tonal, 60 px tall (16 px label, 14 px "where" line under it), arrow on the right; two per row on desktop, full width on phone. They go first, right under the summary, so the action is in the first view on both sizes; the explanation follows under a hairline.

## States

| State | Between the sub line and the steps | Steps |
|---|---|---|
| Normal (this book: live tastytrade) | nothing | step 1 open (or the last one opened) |
| Loading (settings not read yet) | nothing | the six steps show at once (fixed text); nothing waits |
| Empty (no broker connected) | card "No broker yet": "No broker is connected to this account yet: RollCall has nothing to read, and nothing you try here can spend your own money." | step 1 open, with a coral "Start here" chip (node on desktop, row on phone) |
| Error (settings can't be read) | nothing (the read only decides whether the Empty card shows) | unchanged |
| Partial (newest read failed, last good kept) | a small line: "From the last good read at 9:41 AM; the newest read failed." | unchanged |

The other account lines (`live`, `live_cannot_send`, `paper`, `sandbox`, `mock`, `reads_other`, the loading and unread lines and the unread link, still in `fixtures/howto.json` → `account`) are not drawn on this page. Settings, Connection is where the account's kind is shown.

## Behaviours

- One step open at a time. Desktop: click a node, or the buttons at the foot of the card (back: "← Step 1: Connect", ghost; next: "Next: Allow orders →", tonal) → that step's card replaces the open one with a short rise; the line animates from the previous step to the new one; focus moves to the new step's title (`h2`, `tabindex=-1`). Nodes are buttons with `aria-current="step"` on the open one.
- Phone: tap a row → it opens and the open one closes; the opened row scrolls to just under the top bar. Tap the open row → it closes (all six titles visible). Rows are `button[aria-expanded][aria-controls]` inside `h2`. "Next: <short name>" at the end of each panel (none after step 6); no Back on phone (the row above is the way back).
- Do it here buttons open the real screen: Settings (at the named section), Screener, Browse, the roll ticket, the ladder, the Today and Orders tabs. Closing an overlay returns to How to trade with the same step open.
- Words on this step (step 4: call, strike) open the Glossary with that term open and scrolled under its bar (`data-act="gloss-open" data-id`). Today these are inline links in the paragraph; here they're 36 px chips (44 px on phone) under the text.
- "Open the Glossary" opens More > Glossary.
- No solid primary on this page: it's a reference page; the buttons are tonal.

## Sizes and type

Desktop 1440×900, phone 390×844 and 320×568. Body 16 px / 25 px line, summary 18 px (16 px phone), step title 28 px Bricolage (phone row title 16 px bold), labels 14 px, eyebrows 14 px uppercase. Text column ≤ 56 ch (≈ 45–90 characters a line, checked). Phone targets 44 px or more. No text under 14 px except uppercase eyebrows. Page never wider than the phone.

## PNGs (in `draft-a/`)

- Desktop: `howto-desktop.png` (first view), `howto-desktop-step4.png` (step 4 open, path filled to 4), `howto-desktop-loading.png`, `howto-desktop-empty.png`, `howto-desktop-error.png`, `howto-desktop-partial.png`.
- Phone 390: `howto-phone.png`, `howto-phone-loading.png`, `howto-phone-empty.png`, `howto-phone-error.png`, `howto-phone-partial.png`; scroll series in `/tmp/draft-a-190/howto-phone-*.png`.
- Phone 320: `howto-phone-320.png`.

## Removed or renamed versus today's page

- **"Turn on real money, and know what that means"** (step 3 title) → "Turn on live orders, and know what that means". Its buttons **"Is real money possible here?"** → "Can orders go live here?" and **"Real money"** → "Live orders". Body words follow (live orders, your own money). The draft never prints the words "real money" or "simulated".
- **"Read the ticket, and pick the contract you want"** (step 5) → "…pick the call you want".
- Step 6 button **"What needs attention"** → "What needs you", and it opens the **Today** tab (today: `/actions`); **"What you have placed"** → "What you've placed".
- The **one long list of six steps in a panel** → numbered path (desktop) / numbered list (phone), one step open.
- Each step's **links row** ("Connect a broker →" ghost buttons at the end) → "Do it here" tonal buttons right under the summary, each naming where it goes.
- **Inline glossary links inside step 4's text** (call, strike) → "Words on this step" chips under the text.
- The **account line** (plain paragraph, practice or real, and its unread line with the link **"Settings → Connection says which."**) → removed (owner, comment #2 on v2: "most of the accounts are real, we dont need to show simulated"). Only when no broker is connected does a card show, "No broker yet", with today's no-broker line. NEW: the last-good-read line in Partial.
- Footer **"Words you do not recognise are in the glossary, with the formula behind each one."** → "Words you don't know are in the Glossary, with how each one is worked out." + "Open the Glossary".
- NEW: one-line summary per step, short step names on the path, step icons, the "Start here" chip when no broker is connected.
- Removed: nothing else; every paragraph and paired case of today's six steps is kept (tightened).
