# Glossary (More > Learn > Glossary) — spec for Frontend

Draft A v3 direction (Show&Tell d_kgrxir5ezb). Prototype: `draft-a/index.html` → More → Glossary (`screens['more:glossary']` in `draft-a/src/screens/glossary.js`). Words: `fixtures/glossary.json` (all 75 entries of today's `lib/glossary.ts`, same ids). Check: `node draft-a/check-howto-glossary.mjs` (exit 0).

## What it is

Today's `/glossary` (`frontend/src/pages/Glossary.tsx` over `GLOSSARY` in `lib/glossary.ts`): 75 terms in source order in one panel, every term fully open (term, short line, formula, "e.g." example, "Why it matters.", "See" links). In option A it becomes a reference you search: **the search box first**, then the terms **A to Z with jump letters**, each term **one plain line** that opens (one at a time) to the longer meaning, an **example in your own book's numbers**, and how it's worked out.

First view (desktop and phone): the sub line, the search box with its count, and "New to this? Start with these four" (Call, Covered call, Strike, Roll). The A–Z list starts right under them.

## Parts, top to bottom

| Part | What it shows | Where its text comes from today |
|---|---|---|
| Header (drawn by more.js) | desktop: back link "More", eyebrow "More · Learn", h1 "Glossary"; phone: top bar with back and "Glossary" | `<h1>Glossary</h1>` |
| Sub line | "Every word RollCall uses, in plain words, worked out on your own book." | replaces "One yield, one formula. These are the same definitions the column headers show." |
| Book status (only when not normal) | one line with icon: loading / empty / error (see States) | NEW |
| Search | label "Find a word", field with search icon and placeholder "Try “roll” or “cushion”", clear × (only with text), count under it: "75 terms · examples from your book at 10:12 AM", or "4 of 75 terms match “cushion”", or "No term matches “vega”" (`aria-live="polite"`) | NEW |
| Start with these four | heading "New to this? Start with these four"; four dark tiles: Call "The promise you sell", Covered call "Shares plus a call on them", Strike "The price you agreed to", Roll "Swap a call for a later one". Tap opens that term. Hidden while searching. | NEW (`basics` in the fixture) |
| Letter bar (sticky) | desktop: search button (back to the field) + one button per letter that has terms (A B C D E F G H I L M N O P R S T U W); phone: "Search" button + "Jump to a letter" button that opens the letter grid (44 px letters) | NEW |
| No match | card "No word matches “vega”", "Try part of a word, like “cush” for both cushions, or clear the search to see all 75 terms." + tonal "Clear the search" | NEW |
| A–Z list | letter headings (36 px Bricolage, teal; 28 px on phone), under each a list of term rows: term in bold, its one plain line under it, chevron | today's `dl` of `dt` + short |
| Open term | 1) the longer meaning, 2) the example box: label "In your book · 10:12 AM" (or "For example · made-up numbers") and the example sentence, with the XOM price line drawn for 8 terms, 3) "How it's worked out" with the formula in words, 4) "See also" chips and one "Where you see it" button | `why`, `example`, `formula`, `related`, `see` |
| Draft preview picker (prototype only, not to build) | Normal / Loading / Empty / Error / No match | — |

### Each term's fields (`fixtures/glossary.json` → `terms[]`)

| Field | Shown as | From today |
|---|---|---|
| `term` | row title | `term` (6 renamed so A–Z reads, below) |
| `line` | the one plain line under the title | `short`, tightened |
| `more` | first paragraph when open (the longer meaning) | `why` ("Why it matters."), tightened |
| `example` | the example box | `example` rewritten in this book's numbers (fixture.json, 10:12 AM); 21 terms where the book has no such figure keep a made-up example, labelled "For example · made-up numbers" (`example_kind: "sample"`) |
| `how` | "How it's worked out" | `formula`, in words where it was code-like |
| `related` | "See also" chips (open that term) | `related`, plus obvious pairs |
| `see` | "Where you see it" button (9 terms) | today's `see` links (alerts, Today, Screener) plus new ones: Assignment risk → "See JPM on Today", Roll → "Review XOM's roll", Next in line → "Open XOM's ladder", Practice account → "Open Settings", Epoch → "See Analysis", Filters passed → "See the Screener" |
| `aliases` | not shown; search finds them (e.g. "time value" finds Extrinsic, "strike price" finds Strike) | NEW |
| `visual` | the drawn XOM price line | NEW |

Book examples worked out from fixture.json (Frontend: compute these from the live book, same formulas): margin cushion (152,880 − 50,045) ÷ 152,880 = 67.3%; price cushion XOM (114.60 − 104.10) ÷ 114.60 = 9.2%; gain over basis 114.60 ÷ 104.10 − 1 = 10.1%; ITM depth $2.60; extrinsic 2.73 − 2.60 = $0.13; captured 1 − 0.13 ÷ 1.85 = 93.0%; break-even $111.87; gain if assigned (112 − 104.10) × 200 = $1,580; locked-in $370; spread 1.5%; leverage 1.31×; margin usage 22.5%; net liq $152,880; interest per day 45,000 × 6.5% ÷ 360 = $8.13 (day count = rules.carry.day_count, default 360, per RollCall rm-6d8e5047: backend/rollcall/config/rules.py:31, engine/carry.py:192; Analysis now shows $8.13 too; show "÷ 360" only inside an InfoTip, never claim the broker's convention; annualized returns stay × 365); T: premium $0.10, net debit $27.20, week yield 0.37%, return if called 2.9%; roll XOM +$0.04 a share = +$8.

### The price line (8 terms)

Terms with a distance on the price: price cushion, gain over basis, ITM depth, break-even, adjusted basis, gain if assigned, call, strike. One track with three dots for XOM: Basis $104.10, Strike $112, Now $114.60; the term's part is highlighted (a teal band from basis to now for price cushion; the strike dot for strike) with a caption in plain words, e.g. "$10.50 of room, 9.2% of the price · XOM today". Desktop: name and value at each dot. Phone: names at the dots, values in a legend line under the track (they'd collide at 320). The figure has an `aria-label` that says the caption.

## States

| State | Book status line | List | Example boxes |
|---|---|---|---|
| Normal | none (the count says "examples from your book at 10:12 AM") | all 75 | "In your book · 10:12 AM" |
| Loading (book being read) | pulsing dot, "Reading your book for the examples…" | all 75 at once (definitions are fixed text) | skeleton bars under "In your book" until the read ends; made-up examples show at once |
| Empty (no shares yet) | info icon, "You hold no shares yet, so every example uses RollCall's sample book: made-up positions, not yours." | all 75 | label "Sample book, not yours", tinted sand; Practice account uses its own empty sentence |
| Error (broker unreachable) | warning, "RollCall can't reach tastytrade right now, so the examples use your book as of 9:41 AM." | all 75 | "In your book · as of 9:41 AM"; count says 9:41 AM |
| Partial (search with no match) | — | list and letters hidden | the No match card |

A search that matches some terms: only the matching rows and their letters show, "Start with these four" hides, the count says "N of 75 terms match …".

## Behaviours

- **Search filters as you type**, in place, without redrawing (the field keeps focus and the caret). Every word typed must appear in the term, its line, its other names or its id ("cush" finds both cushions; "time value" finds Extrinsic). Matching letters stay in the bar; empty letter groups hide.
- **Enter** opens the best match (the term itself, then one that starts with the word, then one that holds it): "strike" opens Strike, not Room to strike. **Escape** empties the field. **×** and "Clear the search" empty it and put focus back in the field.
- **One term open at a time.** Tap a row → it opens and the open one closes; the tapped row stays where it was on screen (no jump). Tap the open row → it closes. Rows are `button[aria-expanded][aria-controls]`.
- **Jump letters**: tap a letter → its heading lands 12 px under the sticky bar, focus on the heading. Phone: "Jump to a letter" opens the grid of letters; choosing one closes the grid. The search button in the bar scrolls back to the top and focuses the field.
- **See also** chips open that term (it scrolls under the bar, opened). **Where you see it** buttons open the screen: Alerts, Today, the Screener, XOM's roll ticket or ladder, Settings, Analysis.
- **From other screens**: any word link (`data-act="gloss-open" data-id="<term id>"`, e.g. How to trade's step 4 call/strike) opens the Glossary with that term open and scrolled under the bar. Today's `/glossary#<id>` deep links keep working with the same ids; replace the yellow highlight with "opened and scrolled into view".
- No solid primary on this page; buttons are tonal.

## Sizes and type

Desktop 1440×900, phone 390×844 and 320×568. Term title 17 px bold (16 px phone), line and body 16 px / 24 px, labels 14 px bold, letter headings 36 px (28 px phone), tiles 20 px (18 px phone). Text column ≤ 60 ch (45–90 characters a line, checked). Phone targets 44 px or more (rows 56 px, chips 44 px, letters 44 px). Nothing under 14 px except uppercase eyebrows. Page never wider than the phone.

## PNGs (in `draft-a/`)

- Desktop: `glossary-desktop.png` (first view), `glossary-desktop-search.png` ("cushion"), `glossary-desktop-nomatch.png`, `glossary-desktop-term.png` (Strike open), `glossary-desktop-priceline.png` (Price cushion with the drawn line), `glossary-desktop-letterT.png`, `glossary-desktop-loading.png` + `-loading-term.png`, `glossary-desktop-empty.png` + `-empty-term.png`, `glossary-desktop-error.png` + `-error-term.png`.
- Phone 390: `glossary-phone.png`, `glossary-phone-search.png`, `glossary-phone-nomatch.png`, `glossary-phone-term.png`, `glossary-phone-letters.png` (letter grid open), `glossary-phone-letterT.png`, `glossary-phone-loading.png` + `-loading-term.png`, `glossary-phone-empty.png` + `-empty-term.png`, `glossary-phone-error.png` + `-error-term.png`; scroll series in `/tmp/draft-a-190/glossary-phone-*.png`.
- Phone 320: `glossary-phone-320.png`, `glossary-phone-320-term.png`, `glossary-phone-320-priceline.png`.

## Removed or renamed versus today's page

- Sub line **"One yield, one formula. These are the same definitions the column headers show."** → "Every word RollCall uses, in plain words, worked out on your own book."
- The **one panel with all 75 terms open, in source order** → A–Z list, each term closed to one line, one open at a time.
- Each term's **formula line (mono, small)** → "How it's worked out" (16 px, not mono; formulas kept, words where it was code).
- **"e.g. …" example (mono, muted)** → the example box "In your book · 10:12 AM", worked out on the book's numbers; made-up ones say "For example · made-up numbers".
- **"Why it matters." paragraph** → the first paragraph of the open term, without the bold "Why it matters." lead.
- **"See" related links** → "See also" chips; the **see link** ("See your alerts", "See the cards that were not pushed", "See the stocks set aside on the Screener") → a "Where you see it" button: "See your alerts", "See what needs you", "See the Screener".
- The **yellow highlight of the #hash term** → that term opened and scrolled under the letter bar.
- Terms renamed so A–Z reads (ids unchanged): **"The shock grid (if the market falls)"** → "Shock grid (if the market falls)"; **"Your up-side rules"** → "Up-side rules"; **"Where a roll up goes"** → "Roll-up target (where a roll up goes)"; **"The one big rule (net credit)"** → "Net credit rule (the one big rule)"; **"The last-days window"** → "Last-days window"; **"What your dollars earned (money-weighted)"** → "Money-weighted return (what your dollars earned)". "Θ/day" sorts under T.
- NEW: search with count, "New to this? Start with these four", jump letters, No match card, book status line, drawn price line, "Where you see it" on 6 more terms.
- Removed: no term; all 75 kept with their meaning (words tightened; the draft never prints "simulated" or "real money").
