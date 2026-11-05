# Robinhood connection (More > Robinhood connection) — spec for Frontend

Draft A v3 direction (Show&Tell d_kgrxir5ezb). Prototype: `draft-a/index.html` → More → Robinhood connection (`screens['more:robinhood']` in `draft-a/src/screens/robinhood.js`). Data: `fixtures/robinhood.json` (shapes follow today's `RhBook` / `RhName` / `RhCall` / `RhImportResult`). Check: `node draft-a/check-robinhood-system.mjs` (exit 0).

## What it is

Your Robinhood book (the cc-dash book view): the covered calls you hold at Robinhood, what they earn per day after costs, and what you'd walk away with. RollCall reads it from Robinhood activity CSVs; only the live price feed is borrowed from RollCall's own connection. The first view answers two things: are prices live (and if not, what to do), and how much the book makes per day. Everything else sits lower or behind a closed section. Margin figures stay hidden until you open "Show margin".

Only logins in `ROLLCALL_ROBINHOOD_EMAILS` see this row (today the route returns 404 for everyone else). Keep it that way: hide the More row for them.

## Parts, top to bottom

| Part | What it shows | Today's code / data it maps to |
|---|---|---|
| Header (drawn by more.js) | Back to More, eyebrow "More · Account and setup", title "Robinhood connection" (phone: top bar with back) | route `/robinhood` (`pages/Robinhood.tsx`) |
| Connection line | Dot + one line + one short sentence + one button. Three looks: **connected** (green dot) "Prices live", "Book read from your Robinhood CSVs, newest row Nov 3.", tonal "Add a CSV" (opens and scrolls to "Add a Robinhood CSV"); **needs sign-in** (amber) "Sign in again for live prices", "Your broker sign-in ended at 6:02 AM. Until you sign in, prices are Robinhood's own marks from your Nov 3 CSV.", solid "Sign in again"; **failed** (coral) "Live prices failed", "The price feed didn't answer at 10:11 AM. Prices are Robinhood's own marks from your Nov 3 CSV. RollCall tries again every minute.", tonal "Try now" | `RhBook.live_note` ('' = connected); needs sign-in = the price feed isn't set up or the broker sign-in expired (`try_ports` "why"); failed = the feed answered with an error. `last_day` gives the CSV date. There is no separate Robinhood login: "Sign in again" opens RollCall's own broker sign-in (the same place Settings › Connections sends you) |
| Net per day (hero card) | "Net per day" + info tip; big `$131` "a day"; "`$1,051` over the next 30 days if you sell no new calls." Beside it (phone: below) four figures: Walk away with `$66,243` "if you closed it all today"; Total P&L `+$8,243` "14.2% · 8.3% a year"; Collected `$11,946` "premium, dividends, sales"; Net liq `$90,243` "shares less calls owed" | `net_day`, `totals.next_30d − margin_day×30` (see chart), `walk_away`, `total_pnl`, `total_return_pct`, `return_per_year_pct`, `totals.collected`, `totals.net_liq`. Tip: "What your open calls earn today (theta), less what the book costs to carry. It falls as calls end unless you sell new ones." (with margin open it names theta and the interest in dollars) |
| 30-day chart | Readout at the top left: the day ("Thu, Nov 5 · tomorrow"), "`$131 net`", "from your open calls, after costs", and when calls end that day "· **BAC and F** calls end, then $61 a day"; top right "Next 30 days `$1,051`". One bar per calendar day for the next 30 days, amber dot on each day a call ends, y labels $0 / half / top, x labels every week (phone: first, middle, last). Legend "Net a day", "A call ends". With Show margin open: teal bars "From your calls" above zero, coral bars "Margin interest" below zero, readout "$136 from calls − $4 margin", total line "$1,184 calls − $133 margin" | Per call: earns `theta_day` each day while day ≤ `dte`, never more than `extrinsic` in total (same rule as `engine/robinhood.py` `next_30d = min(extrinsic, theta_day × min(30, dte))`); day net = sum of calls − `margin_day`. Sum of the 30 call days must equal `totals.next_30d` (the prototype throws if not). Compute on the client from `names[].calls[]`, or add a `days[]` array to `RhBook` if Backend prefers |
| Names you hold | Heading + "7 names · 6 with a call"; names filter (see "Names filter" below). Desktop table: Name (button, + "1,000 shares"), Price (+ "Nov 3 mark" when not live), Open call ("10 × 11/13 $15 call", "ends in 9 days", "in the money" when it is), Collected, P&L now, Net a day; total row "All 7 names". Phone: one card per name: symbol (+ "in the money" / "Nov 3 mark" tags), "`$27` a day", "11/13 $15 call · 9 days · P&L +$4,630", chevron | `names[]`: `symbol`, `shares`, `price`, `price_source`/`price_day`, `calls[0]` (`contracts`, `expiry`, `strike`, `dte`, `intrinsic>0`), `collected`, `pnl_now`, `net_day`; totals from `totals` and `net_day` |
| Name details (row/card opens) | Two-column facts: Shares cost, Call premium, Dividends, Share sales, Shares worth, Calls to buy back, Paid a share, Cost a share now, Extrinsic left, Theta today, P&L at expiry, A year now. With Show margin open also: Its margin interest, P&L after margin. Phone adds "Name · 400 shares at $23.60" above | `cost`, `premium`, `dividends`, `realized`, `stock_value`, `buyback`, `avg_cost`, `adj_per_share`, `extrinsic`, `theta_day`, `pnl_at_expiry`, `apy_now_pct`, `margin_to_date`, `pnl_after_margin` |
| Show margin (closed by default) | "Balance, interest, leverage, and margin per name". Open: Margin balance `$24,000` "at 6.8% a year", Interest a day `$4.44`, Paid so far `$1,034`, Leverage `1.35×` "shares ÷ your equity", and "The chart above now splits each day into what calls earn and what margin costs. Change the balance or rate under Book settings." Coral edge only while open (matches the margin bars) | `margin_balance`, `margin_rate`, `margin_day`, `totals.margin_to_date`, `leverage` |
| Other money (closed) | "Names you no longer hold and account fees". Open: each past name with "no longer held · closed Sep 19" and what it collected; then other codes (fees, interest paid out, adjustments) signed. Margin-only codes hidden unless Show margin is open | `past_names_collected` + per-name rows, `other[] {code,label,amount}` |
| Add a Robinhood CSV (closed) | "Your book runs Mar 3, 2025 – Nov 3 · 1,186 rows". Open: three steps (see "CSV upload" below) | `POST /api/robinhood/import` (see below); audit `robinhood.imported` |
| Robinhood settings (closed) | "Margin, cash and deposits the CSV doesn't hold · used only on this page". Open: three groups of fields (see "Robinhood settings" below) | `GET/PUT /api/robinhood/settings`; audit `robinhood.settings_updated` |

## States

| State | What shows | How to get it in the draft |
|---|---|---|
| normal | everything above, connected | "Normal" + "Connected" |
| needs sign-in | connection line amber with solid "Sign in again" (the one solid button on the page, unless a CSV preview is waiting); every price shows "Nov 3 mark" | "Connection: Needs sign-in" |
| failed | connection line coral with tonal "Try now"; prices on marks | "Connection: Failed" |
| loading | skeleton connection line, "Reading your Robinhood book…" with a spinner (`aria-live`), skeleton hero, chart and four rows; `aria-busy="true"`; no buttons yet | "Loading" |
| empty | no connection line (nothing to price). Card "No Robinhood rows yet." / "Upload an activity report from Robinhood and this page fills in: your names, calls, net per day and what you'd walk away with." / where to find it / solid "Choose a CSV file"; picking it opens the same preview, adding it fills the page | "Empty" (`has_data: false`) |
| error | card "Couldn't load your Robinhood book." / "RollCall didn't answer. Your stored rows are safe. Try again in a moment." / solid "Try again" (`role="alert"`) | "Error" |
| partial | connected, but some names have no live price: note "INTC and AMD have no live price right now, so they use Robinhood's Nov 3 mark."; those rows show "Nov 3 mark" | "Partial" (some `names[].price_source` ≠ `live`) |

The "Draft preview, show as:" box at the bottom is for the draft only; don't build it. Its rows "Next CSV file:" (Good / Row errors / Wrong file / Nothing new) and "Saving settings:" (Works / Fails) choose what the next file pick or save answers.

## Names filter (Design #197)

Today's `components/robinhood/Names.tsx` filter, kept whole and redrawn.

| Part | What it shows | Today's code |
|---|---|---|
| Name search | desktop placeholder "Find names, like BAC, F", phone "Find names" (the placeholder must fit its box; the check measures it); `aria-label="Find names: one or more, with commas or spaces between"`. Several names at once (commas or spaces); a name shows when any word is in its symbol or company name | Name filter box (same rule) |
| Open calls chips | All · Call in the money · Out of the money · No call (`aria-pressed`, one group with its label "Open calls") | Open calls segmented control |
| Call ends within chips | Any time · 7 days · 14 days · 30 days (a name shows when one of its calls ends within that many days) | "Call ends within" select |
| Where | desktop: search and both chip groups in one toolbar above the table; phone: search + a "Filter" button (filter icon, a count badge of the groups that are on, `aria-expanded`/`aria-controls`) that opens the chips in a panel, so the cards start high | — |
| What's shown | while anything filters: "Showing **3 of 7** names" + ghost "Show all"; the total row becomes "2 shown" and sums only what's shown (desktop: Collected, P&L now, Net a day; phone: "2 shown · net $68 a day · P&L +$4,127") | today's count + "Show all" |
| No match | "No names match “xyz” with call in the money and a call ending within 7 days." (only the parts that are on) + tonal "Show all names" | today's empty filter result |

Behaviours: typing keeps focus and caret; chips keep scroll and focus; "Show all" / "Show all names" clears search and both chip groups; a filtered-out name's open details close. The filter is on the client (all names are in `RhBook.names`).

## CSV upload (Design #197)

Three steps, drawn as a step line "Choose the file · Check what it adds · Add it" (phone "Choose · Check · Add"; done ✓, current `aria-current="step"`, a failed check marked red).

| Step / result | What shows | Today's code / data |
|---|---|---|
| 1 Choose | desktop: drop area "Drop the CSV here" + tonal "Choose a CSV file"; phone: the button alone. Under it: "In Robinhood: Account › Reports and statements › Reports, then download an activity report (CSV). You check what it adds before anything is stored." Picking → button "Reading the file…" with a spinner at once | file input; `POST /api/robinhood/import {csv, commit:false}` |
| 2 Check what it adds | file line "robinhood-activity-2026-11-04.csv · 58 rows, Oct 27 – Nov 4"; three counts **8** new rows · **48** already here · **2** left out (tip: "2 rows: Put option rows. RollCall tracks covered calls only, so it leaves them out. Rows already here are never added twice."); "What it adds" by kind with sums (Dividends 3 rows +$388.25 · Deposits 1 row +$2,000.00 · Interest and lending 2 rows +$2.10 · Fees and margin interest 2 rows −$138.20); "What changes" as before → after (Book runs to Nov 3 → Nov 4 · Rows 1,186 → 1,194 · Collected · Money you put in when it comes from deposits · Names you hold: "no new names" or "adds X"); "See the 8 new rows" disclosure (desktop table Date · Code · What · Name · Amount; phone list); solid "Add 8 rows" + ghost "Cancel"; hint "Nothing is stored until you press Add. Rows are only added, never changed." | `RhImportResult`: `rows_in_file`, `new`, `duplicates`, `skipped[]` (rows + why), `first_day`, `last_day`, plus `new_rows[]` (date, Trans Code, symbol, what, amount) and `after_rows`. Kinds by Trans Code: CDIV dividends; STO/BTC calls; ACH deposits; INT/SLIP interest and lending; MINT/GOLD fees and margin interest. "Collected" = premium + dividends + share sales, as `RhBook` |
| 3 Add it | "Adding 8 rows…" with a spinner at once (Cancel disabled) → status line "Added 8 rows from robinhood-activity-2026-11-04.csv. Your book now runs to Nov 4 (1,194 rows)." + tonal "Add another file"; the page's figures and the section's summary line update | `{csv, commit:true}` → `stored` |
| Rows to fix | coral box (`role="alert"`): file line, "3 rows need fixing. Nothing was added.", then per row: Row 9 · Amount · It says `$2,OOO.00` · "Letter O in place of zeros. Make it $2,000.00."; Row 23 · Activity Date · `11/31/2026` · "November has 30 days. Use the date in Robinhood."; Row 40 · Trans Code · empty · "Every row needs its code, like STO or CDIV." (desktop table Row · Column · It says · How to fix it; phone list); hint "Easiest fix: download the report from Robinhood again and choose it without opening it in a spreadsheet."; solid "Choose the fixed file" + Cancel | **Backend needed:** today answers 400 with one whole-file message (`RhCsvError`). Add `row_errors[] {row, column, value, fix}` and store nothing while any exist |
| Wrong file | "This isn't a Robinhood activity report." / "It has no “Activity Date” column. In Robinhood, open Account › Reports and statements › Reports and download an activity report, not a positions or tax file. Nothing was added." + "Choose another file" | today's `RhCsvError` for missing columns, with the missing column named |
| Nothing new | calm box (`role="status"`): "Nothing new to add." / "All 41 rows are already in your book, which runs to Nov 3. Nothing changed." + tonal "Choose another file" | `new == 0` |

The empty page (no rows yet) uses the same three steps from its own "Choose a CSV file". One solid primary while a preview or a fix waits ("Add 8 rows" / "Choose the fixed file"); Cancel goes back to step 1 with nothing stored.

## Robinhood settings (Design #197)

Today's seven settings for this tab, in three groups (`fieldset` + `legend`), each field with a label, a one-line help under it and its own error:

| Group | Field | Help | Wire |
|---|---|---|---|
| Margin | Margin balance ($) | What you owe Robinhood today. | `margin_balance` |
| | Margin rate (% a year) | Your Robinhood Gold rate. 6.75 means 6.75%. | `margin_rate` (fraction on the wire, % in the field) |
| Money the CSV doesn't show | Cash on hand ($) | Cash sitting in the account. | `cash_on_hand` |
| | Other money, + or − ($) | Anything else to count, like a transfer the CSV lacks. | `other_adjustment` |
| What you put in | Money you put in ($) (placeholder "Blank: use deposits") | Blank: RollCall adds up the deposits in your CSVs ($…). | `initial_investment` (null = blank) |
| | Deposits before your first CSV row ($) | Only used while Money you put in is blank. | `pre_ledger_deposits` |
| | Date that money went in (YYYY-MM-DD) | Blank: your first CSV row, Mar 3, 2025. | `pre_ledger_date` (null = blank) |

Field checks on leaving a field and on Save (`aria-invalid`, the help line turns into the error): "“abc” isn't a number. Use digits, like 24000."; "Type a number, or 0 for none." (empty where blank isn't allowed); "Type the yearly rate in %, from 0 to 99.99."; "Can't be below zero." (all but Other money); "Use YYYY-MM-DD, like 2025-02-14." A field with an error blocks Save and gets focus.

Buttons: tonal "Save settings", disabled until something changed; ghost "Undo changes" shows only while something changed and puts the saved values back. Saving: "Saving…" with a spinner at once, fields disabled → "Saved. The figures above use them now." (`role="status"`) and the page's figures recompute. Save fails: "Couldn't save: RollCall didn't answer. Your changes are still here, so try again in a moment." (`role="alert"`), the button reads "Try again", every edit stays. Settings are used only on this page (they don't change RollCall's own account figures).

Today's "Could not refresh: … figures from the last time it worked." callout (a refresh failed while old data is on screen) becomes the **failed** connection look when prices fail, or the **error** card when the book itself can't load; keep the old figures on screen under the failed line.

## Behaviours

- Click feedback before any reply: "Sign in again" → disabled "Opening sign-in…" with a spinner, then "Signed in. Prices are live again." and the line turns green; "Try now" → "Trying…", then, if still down, "Still no answer. Prices stay on the Nov 3 marks; nothing else is affected." (`role="status"`); "Try again" → "Trying again…"; "Choose a CSV file" → "Reading the file…"; "Add 12 rows" → "Adding…"; "Save settings" → "Saving…". Every busy button is `disabled` + `aria-busy` and ignores a second click.
- Chart: hover or tap a bar to read that day; the chart is focusable and Left/Right/Home/End move the day; the picked day stays picked when the page redraws. All chart text is real HTML at real size (no text inside a scaled SVG).
- Show margin is closed on every visit. Opening it changes the chart (calls above, margin below), the tip, the details (adds two margin facts) and Other money (adds margin codes). Closing it puts them back.
- Names: search filters as you type (keeps focus and caret); filter chips keep scroll and focus; nothing matching → "No names match “x” with call in the money." + tonal "Show all names". One name's details open at a time; the name button has `aria-expanded`/`aria-controls`.
- "Add a CSV" in the connection line opens "Add a Robinhood CSV" and scrolls it into view.
- Closed sections are buttons with `aria-expanded`; their one-line summary says what's inside.
- One solid primary per view: "Sign in again" when sign-in is needed, "Add 12 rows" while a preview waits, "Choose a CSV file" when empty, "Try again" on error; otherwise none (the page is for reading).

## Sizes and type

Desktop 1440×900 (center column; hero: net per day left, four figures right; chart full width; table). Phone 390×844 and 320×568 (hero stacks; chart with 3 x labels; names as cards; filter chips wrap as separate 44 px pills; buttons 44 px+). Body 16 px, labels 14 px, 12 px only for uppercase eyebrows. Numbers in the tabular number font (`.num`). Tokens and classes from `draft-a/src/page.html` (`.card`, `.btn`, `.p-h`, `.skel`, `.spin`, `.tipbtn`, `.note`, `.legend`); screen styles are scoped under `.scr-rh`.

## PNGs

- Normal: `draft-a/robinhood-desktop.png` (1440), `draft-a/robinhood-phone.png` (390), `draft-a/robinhood-phone320.png` (320)
- Show margin open: `draft-a/robinhood-desktop-margin.png`, `draft-a/robinhood-phone-margin.png`, `draft-a/robinhood-phone320-margin.png`
- States: `draft-a/states/robinhood-<desktop|phone>-<loading|empty|error|partial|needs-signin|failed>.png`
- Extras (Design #197), each at desktop / phone / phone320: `draft-a/robinhood-<desktop|phone|phone320>-filter.png` (names filtered, count + Show all), `-csv.png` (check what it adds), `-csv-errors.png` (rows to fix), `-settings.png` (open with a field error); `draft-a/states/robinhood-<desktop|phone>-<csv-wrong|csv-nothing|settings-failed>.png`

(All re-made by `node draft-a/check-robinhood-system.mjs`.)

## Removed or renamed versus today's page

Today's page is "Robinhood" (`frontend/src/pages/Robinhood.tsx`, `components/robinhood/*`).

| Today | Now |
|---|---|
| Page head "Robinhood" + subtitle (rows, first..last day) | Title "Robinhood connection"; the rows and dates moved into "Add a Robinhood CSV"'s summary line |
| "Loading your Robinhood book…" | "Reading your Robinhood book…" with skeletons |
| Error state + retry | Error card, same retry, says your stored rows are safe |
| Callout "Could not refresh: … figures from the last time it worked." | The failed connection line (prices) or the error card (book); see States |
| Empty state "No Robinhood rows yet." | Same title, plus where to get the CSV and the upload button inside the card |
| Live price callout | The connection line, always shown, with what to do |
| Section "Current state" (Walk-away, Total P&L, Return a year, Invested; Net liq, Leverage, Collected) | Hero card's four figures: Walk away with, Total P&L (return and a-year return under it), Collected, Net liq. **Invested** removed from the first view (it's in Total P&L's return); **Leverage** moved into Show margin |
| Section "Net per day" (Theta today, Margin costs, Net per day, Next 30 days; Extrinsic left, Calls: in the money part, Margin paid so far; note + InfoTip) | Hero "Net per day" + the 30-day chart. **Theta today** and **Margin costs** are in the tip and, with margin open, in the chart readout; **Margin paid so far** moved to Show margin; **Extrinsic left** and **Calls: in the money part** moved into each name's details (Extrinsic left) and the "in the money" tag |
| Section "Names you hold": Name filter, Open calls segmented (All / Call in the money / Out of the money / No call), "Call ends within" (any/7/14/30), "Show all" | Kept whole (Design #197): search for several names, "Open calls" chips, "Call ends within" chips (Any time / 7 / 14 / 30 days); on phone behind a "Filter" button; "Showing N of 7 names" + "Show all"; total row sums what's shown; "Show all names" when nothing matches |
| Table columns Name, Shares, Price, Paid a share, Collected, Cost a share now, Net liq, P&L now, P&L at expiry, Open calls, Extrinsic left, Net per day | Six columns: Name (shares under it), Price, Open call, Collected, P&L now, Net a day. **Paid a share, Cost a share now, Net liq, P&L at expiry, Extrinsic left** moved into the name's details |
| Row details (Shares cost, Call premium, Dividends, Share sales, Shares worth, Calls to buy back, Extrinsic left, Theta today, Its margin interest, P&L after margin, A year now, A year at expiry) | Same facts plus Paid a share and Cost a share now; **Its margin interest** and **P&L after margin** only with Show margin open; **A year at expiry** replaced by P&L at expiry |
| Section "Other money" (Names you no longer hold + other codes) | "Other money" closed section, same content |
| Section "Upload a Robinhood CSV" (preview counts + sample rows, then store) | "Add a Robinhood CSV" closed section, three steps: choose → check what it adds (counts, by kind with sums, before → after, all new rows) → add; rows to fix listed one by one (needs Backend `row_errors`), wrong file, nothing new |
| Section "Settings for this tab" (seven fields in one list) | "Robinhood settings" closed section: the same seven fields in three groups, help per field, field checks, Save only when changed, Undo changes, failed save keeps the edits |
| — | New: "Show margin" closed section (margin balance, interest a day, paid so far, leverage) |
