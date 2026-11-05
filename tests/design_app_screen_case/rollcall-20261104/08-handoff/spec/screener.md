# Screener (More > Screener) — spec for Frontend

Draft A v3 direction (Show&Tell d_kgrxir5ezb). Prototype: `draft-a/index.html` → More → Screener (`screens['more:screener']` in `draft-a/src/screens/screener.js`). Data: `fixtures/screener.json` (numbers agree with `fixture.json`, `fixtures/ideas.json` and `fixtures/entry.json`). Check: `node draft-a/check-ideas-screener.mjs` (exit 0).

## What it is

Stocks you don't own yet, scored against your eight stock rules, so you can start a new position. First view: when it last ran, how many passed, the ranked list, and one button to run it again. Why each stock passed, and why the others didn't, sit behind a tap.

Manual runs only: one "Run screener" button. No scheduled run, no quick scan, no "Re-check every stock" menu.

## Parts, top to bottom

| Part | What it shows | Today's code / data it maps to |
|---|---|---|
| Header (drawn by more.js) | Back to More, eyebrow "More · Trade tools", title "Screener" (phone: top bar with back) | route `/screener` (`pages/Screener.tsx`) |
| Last run line | dot + "Last run **9:48 AM today** · **4 of 16** passed" + info tip "How stocks are scored" (tip: "Six checks must pass. The last two only change the order: stocks that have fallen rank first, stocks that keep rising rank lower. Change them in Settings.") | `ScreenerOut.fetched_at` / `run.started`, `ScreenerOut.qualified`, `ScreenerOut.screened` |
| Hidden line | eye icon + "8 stocks you hold are hidden" + info tip "Why some stocks are hidden" (tip names AAPL, MSFT, KO, JPM, XOM, PFE, DIS, T and says buy orders still working are left out too; "No buy orders are working now.") | NEW: held symbols from `GET /api/positions`; working entry (buy-to-open stock) orders from `GET /api/orders`. Line wording: "N stocks you hold are hidden", and when there are working buy orders "N stocks you hold and M with a buy order working are hidden" |
| Run screener | the one solid primary, top right on desktop, under the lines on phone | `POST /api/screener/refresh` (no `mode`, no `recheck_all`) |
| "Passed every check" | meta "falling stocks first"; ranked rows MRK 1 (86), PEP 2 (78), HD 3 (61), CSCO 4 (54) | `ScreenerOut.rows` where `qualified`, minus hidden symbols, by `score` |
| "Close call" | meta "missed one check"; VZ (fails "One share over $50", $41.20) | rows not qualified that failed exactly one must-pass check (`filters` with one fail) |
| Row (closed) | button: rank, symbol + chevron, "Merck · $98.60", "+$84 per lot · 0.85%" (phone: "per lot"; never "a lot", which reads as "much"), Score bar + number, desktop: eight dots (one per check); close calls show chip "Missed 1 check" instead of score | `symbol`, `name`, `spot`, `entry.premium`×100, `entry.week_yield`, `score`, `filters[]` |
| Start a position | tonal button on every row: `data-act="entry-open" data-sym="<SYM>" data-from="screener"`; opens the entry ticket (task #186) | today's row button that opens `EntryTicket` in place |
| Row (open) "why" | one plain sentence why; "Your eight checks" list, each with mark (✓ passed, ↑ ranks higher, – no effect, ↓ ranks lower, ✕ failed, ? not checked) and its value, the last two marked "only changes the order"; four tiles: 100 shares ($9,860 at $98.60), Nov 6 $99 call pays (+$84, 0.85% this week), If called Friday (+$124, 1.26% · 45% chance), Loses money under ($97.76 a share, on Friday) | `filters[]` (FilterResult status pass/fail/skip/none/na), `boosts`, `entry` (strike, expiry, bid, `return_if_called`, protection/breakeven, delta) |
| How 16 became 4 | desktop: column chart, one column per check with stocks left (16, 13, 13, 11, 5, 4, 4) and drops (−3, −2, −6, −1), then disclosure "12 stocks didn't make it · which check stopped each"; phone: one disclosure "12 didn't make it · how 16 became 4" with horizontal bars + the list | `reject_parts`, `rejected`, `run.stages[]` |
| Didn't-make-it list | grouped by the check that stopped them: Analysts say buy (INTC, WFC, C), Over $50 (VZ, BAC), Volatile enough (WMT, CVX, ABBV, GOOGL, AMZN, META), Margin OK (NVDA), each with a short why | `rejected[]` with `reject_reason` |
| Set aside for later (Design #197) | card after the chart, **closed by default**: "Set aside for later" + count pill **10** + "runs skip these until their date" (0: "nothing set aside"). Open: see "Set aside for later" below | `GET /api/screener/exclusions` (`total`, `groups[]`, `enabled`); count from `total` |
| Footer | "Prices from tastytrade at 9:48 AM · calls priced at the bid · a lot is 100 shares and one call" | `source`, `fetched_at`, quote side |

The eight checks, in order: Most analysts say buy · Has weekly options · One share over $50 · Volatility 30% or more · Broker holds 30% or less · Options trade easily (all six must pass) · Down 10% or more in 30 days · Falling over the year (these two only change the order). Same rules as today's `CHECK_NAME` (analyst rating, listed options, price floor, implied volatility, margin tier, option liquidity, pulled back from high, trend).

## States

| State | What shows | Draft preview button |
|---|---|---|
| normal | as above | "Normal" |
| loading | skeleton lines and three rows, `aria-busy="true"`, screen-reader "Loading the screener"; no solid button | "Loading" |
| no recent run (empty) | when the last run is older than 5 days: clock icon, "No recent run", "Your last run was Thu Oct 29, 6 days ago. Prices that old aren't safe to trade on.", primary "Run screener"; no rows (same rule as today's server: rows older than 5 days aren't sent, `stale_fetched_at` set) | "No recent run" |
| running | top lines + disabled primary with spinner ("Starting…" then "Running…"); dark progress panel: "Step 3 of 6" + step name, progress bar (`role="progressbar"`, 0–6), the six steps listed (done / now / to do); below, the previous results dimmed with "Results from your 9:48 AM run, until this one finishes" (not shown when starting from "No recent run") | press Run screener |
| done | back to normal with "Done at 10:12 AM: 4 of 16 passed." (`role="status"`), last run line updated to 10:12 AM | after a run |
| failed | stop icon, "The run didn't finish", "The run stopped at step 4 of 6: tastytrade didn't send option prices. Nothing changed in your account. Run it again in a minute.", primary "Run again" (`role="alert"`); then hidden line and the previous results labelled "Results from your 9:48 AM run" | "Failed run" — `run.status == "failed"`, `run.error` turned into plain words |
| partial | normal list with a note: "Analyst ratings didn't load, so that check was skipped. The other seven ran."; that check shows "?" (not checked) in every row and "skipped" in the chart | "Partial" — a stage with `status` skip in `run.stages` |

Set-aside list states (second row of the draft picker, "Set-aside list:"):

| State | What shows | Draft preview button |
|---|---|---|
| closed | heading, count pill, one-line summary, chevron; nothing loaded | default |
| loading | opening fetches the list (today's page fetches it only when opened): three skeleton lines, `aria-busy="true"`, screen-reader "Loading the set-aside list" | "Loading" |
| normal | lead line "Each failed a check on a run. Runs skip it until its date." + info tip; three groups; price-floor line; "Clear all 10" (tonal) | "Normal" |
| empty | count **0**, summary "nothing set aside", "Nothing set aside: every run checks every stock." + price-floor line; no Clear all | "Empty" (also after Clear all) |
| load error | coral box (`role="alert"`): "Couldn't load the list. Nothing changed; runs still skip these stocks." + tonal "Try again" ("Trying again…" with spinner at once, then the list) | "Load error" |
| clearing | the pressed Clear / Clear all turns at once into disabled "Clearing…" with a spinner (`aria-busy`) | press Clear |
| cleared one | the stock's line becomes a tinted line "INTC cleared. Your next run checks it again." + "Undo" (focus moves to Undo); group count drops (3 → 2), pill 10 → 9 | after Clear |
| clear all confirm | amber box: "**Clear all 10?** Your next run checks every one of them again, so it takes a little longer." + tonal "Clear all 10" + ghost "Keep them" | press Clear all |
| cleared all | status line "Cleared all 10. Your next run checks them again." + "Undo"; empty text; pill 0 | after confirming |
| clear fails | red line under the stock (`role="alert"`): "Couldn't clear it: RollCall didn't answer. Nothing changed, so try again in a moment."; the stock stays; for Clear all the same line shows inside the confirm box | "Clear fails", then Clear or Clear all |

Run steps (six, plain words): Getting the stock list · Reading analyst ratings · Getting share prices · Reading option prices · Checking margin and trading · Scoring the trend. Map from `ScreenerRunOut.stage` / `stage_completed` / `stage_total` / `stages[]`.

The "Draft preview, show as:" box at the bottom is for the draft only; don't build it.

## Behaviours

- Click feedback before the server answers: Run screener turns at once into disabled "Starting…" with a spinner (`aria-busy`), then "Running…" as steps arrive (poll `GET /api/screener/runs/{run_id}`). One run at a time; the button stays disabled while running.
- Leaving the screen during a run keeps the run going; coming back shows its progress.
- Tapping a row toggles its why (`aria-expanded`, chevron turns); several rows can be open. Focus stays on the row button.
- "Start a position" never needs the row open. On phone it sits under the row (44 px), under the why when open.
- Info tips: round "i" buttons (44 px hit area), `aria-expanded`, tip text appears below the line.
- Hidden stocks never show anywhere on this screen (passed, close call or the didn't-make-it list); the hidden line counts them. A stock leaves the hidden set as soon as it's sold and its buy order is gone.
- A stock under your $50 floor can still show as a close call with its reason; the price floor stays a must-pass check (today's affordability rule: warn, don't block).
- The didn't-make-it list is closed by default on both sizes.

## Set aside for later (Design #197)

Today's exclusion memory: a stock that fails a check is set aside, and runs skip it until its date. This card lets you see who is set aside and why, and clear one stock or all of them. Manual runs only: no "Re-check everything" run option (`recheck_all`) and no quick or scheduled scan.

Open card, top to bottom:

| Part | What it shows | Today's code / data it maps to |
|---|---|---|
| Lead line | "Each failed a check on a run. Runs skip it until its date." + info tip "About stocks set aside" ("When a stock fails a check, the screener sets it aside and skips it until its date, so runs take less time. Clear one to check it on your next run. Stocks under your price floor are never set aside: every run checks them again.") | `components/screener/StockLists.tsx` `SetAsideSection` intro text, reworded |
| Groups, one per check that set stocks aside | heading = what went wrong + "N · until <date>": "Analysts don't say buy 3 · until Dec 4" (INTC, WFC, C), "Not volatile enough 6 · until Nov 18" (WMT, CVX, ABBV, GOOGL, AMZN, META), "Broker holds too much 1 · until Dec 4" (NVDA). Desktop: two columns of lines; phone: one | `groups[]` (`rule`, `label`, `next_recheck`); dates = run day + `config/screener.py` memory days (analyst 30, margin 30, volatility falls to `default_days` 14) |
| Stock line | symbol (display font) + company name; under it the short reason ("10 of 31 say buy", "19% volatility", "broker holds 50%"); ghost "Clear" on the right (44 px), `aria-label="Clear INTC: check it on your next run"` | `stocks[]` (`symbol`, `name`, `reason`, `recheck_after`) |
| Price-floor line | "VZ, BAC were under your price floor. They're never set aside: every run checks them again." (partial run: VZ, BAC, INTC) | today's "Under the price floor on the last run (N)" block |
| Clear all | tonal "Clear all 10" → inline confirm (see states) | `DELETE /api/screener/exclusions` (no `rule`) |

Who is set aside is the last run's turned-down stocks minus the price floor, so the card and the chart never disagree (normal run 10; partial run 9: INTC fell on the price floor that run, WFC and C on volatility). The failed view keeps the 9:48 run's list. The card isn't drawn while loading, running or in "No recent run".

Behaviours:

- Closed by default on both sizes; opening loads the list (skeleton at once). Closing and reopening keeps it loaded.
- Clear (one stock): "Clearing…" at once → the line turns into "<SYM> cleared. Your next run checks it again." + Undo; Undo shows "Undoing…" then puts the stock back with its date. Leaving or closing the card drops the cleared lines.
- Clear all: never one tap. It opens an inline confirm (Clear all N / Keep them); confirming shows "Clearing…", then "Cleared all N" + Undo. "Keep them" closes the confirm with nothing changed.
- A failed clear changes nothing and says so next to the button that was pressed; the button comes back.
- A run skips the stocks still set aside: the done line adds "It skipped the 10 set aside for later." and the chart gets a step "Not set aside" (16 → 6, −10) right after "Checked", so later steps drop only stocks really checked (the price floor still drops VZ, BAC; 4 pass). Stocks cleared before the run go through every check again; those that fail again are set aside again.
- Backend needs (today has neither): clearing one stock (`DELETE /api/screener/exclusions?symbol=INTC`; today only `?rule=` or all), and Undo (a restore call that puts back the cleared stocks with their old dates, e.g. `POST /api/screener/exclusions/restore` with the `stocks[]` returned by the DELETE). Without a restore call, Frontend can hold the DELETE for about 8 seconds while Undo shows and send it only when Undo isn't pressed. Today's audit action `screener.memory_cleared` should record the symbol too.
- Today's "This server doesn't keep an exclusion memory yet" text (`enabled` false): show the empty state's line instead, without Clear all.

## Sizes and type

Desktop 1440×900 (center column; row grid rank 44 · name · pay 112 · score 140), phone 390×844 and 320×568. Body 16 px, labels 14 px, 12 px only for uppercase eyebrows. Targets 44 px on phone. Tokens and classes from `draft-a/src/page.html` (`.card`, `.chip`, `.btn`, `.p-h`, `.skel`, `.tipbtn`, `.sentrow`).

## PNGs

- `draft-a/screener-desktop.png` (1440, normal), `draft-a/screener-desktop-open.png` (1440, MRK open), `draft-a/screener-phone.png` (390, normal), `draft-a/screener-phone-running.png` (390, running)
- Set aside for later (Design #197): `draft-a/screener-desktop-setaside.png` (1440, open list), `draft-a/screener-phone-setaside.png` (390, open list), `draft-a/screener-phone-setaside-cleared.png` (390, INTC cleared with Undo)
- Every state at 1440/390/320, scrolled end to end: `/tmp/draft-a-187/screener-<state>-<desk-1440|phone-390|phone-320>-<n>.png` (re-made by `node draft-a/check-ideas-screener.mjs`); set-aside states are `screener-mem`, `-mem-cleared`, `-mem-confirm`, `-mem-clearedall`, `-mem-loading`, `-mem-empty`, `-mem-error`, `-mem-clearfail`, `-mem-clearallfail`

## Removed or renamed versus today's page

Today's page: `frontend/src/pages/Screener.tsx`.

| Today | Draft A |
|---|---|
| Title "Screener" | Kept, under More > Trade tools |
| "Run the screen" button with ▾ menu ("Re-check every stock") | "Run screener", one button, no menu |
| "Run unavailable" pill | Removed; the failed state says what happened and offers "Run again" |
| "Screening settings" button | Removed from this screen; the rules are changed in Settings (named in the scoring tip) |
| Run note line (scope, last run time, prices from) | Split: "Last run … · 4 of 16 passed" on top, prices source in the footer |
| Section "This run" (headline, progress bar, "<label> · <dur> so far") | Running panel: "Step n of 6", bar, the six steps listed |
| Find box | Removed (a run shows about five stocks) |
| Presets "Qualified" · "All checked" · "Roll candidates", filters, sort ("Downtrend first" / "Best score") | Removed; one order: passed by score (falling stocks first), then "Close call"; the rest in the didn't-make-it list |
| Table columns Symbol · Price · Entry call · Premium · Week yield · If called · Protection · IV · Trend · Filters · Score | Row shows symbol, name, price, pay a lot, week %, score (+ eight dots on desktop); entry call, if called, protection (as "Loses money under") in the open why; IV and trend as values in "Your eight checks" |
| Row detail: sentence, three chips, "Passed all 6 checks — …▸" numbered checks, entry math, stock facts (analyst counts, margin tier, option liquidity, drawdown), Trend block, "See this in Actions", strike ladder | Open why: one sentence, "Your eight checks" with values, four math tiles; "See this in Actions" removed (new-position ideas show in Ideas); strike ladder removed here (the entry ticket picks the call) |
| Row button opening `EntryTicket` in place | "Start a position" → entry ticket (`entry-open`) |
| Disclosure "N stocks didn't make it" / "Checks not run" (stage by stage + turned-down list) | "How 16 became 4" chart (desktop) + disclosure "12 stocks didn't make it" / phone "12 didn't make it" |
| Disclosure "Stocks set aside for later (N)" (`SetAsideSection`) with one "Re-check all N set aside for …" button per group, find box | Kept as "Set aside for later" + count, closed by default (Design #197): grouped by check with the date, "Clear" per stock (new; needs Backend), "Clear all N" with a confirm and Undo (new); find box removed (10 stocks); per-group button removed |
| "Under the price floor on the last run (N)" block | One line inside the card: "VZ, BAC were under your price floor. They're never set aside: every run checks them again." |
| Run option "Re-check everything" (`recheck_all`) | Removed; clear the stocks you want checked instead |
| No-room note "See where the money is →" | Removed (affordability is warned in the entry ticket) |
| Footers: source, prices date, counts, "premiums at the bid", "This run: <time>" (run id on hover), sources strip | One footer line: "Prices from tastytrade at 9:48 AM · calls priced at the bid · a lot is 100 shares and one call" |
| Test-account "forget runs" | Removed from view |
| First open "Starting the first screen…" (`ScreenerNoRun`) | "No recent run" + "Run screener" (no automatic run) |
| Stale: "The last screen ran <day>, more than five days ago, so its picks are not shown." | "No recent run" / "Your last run was Thu Oct 29, 6 days ago. Prices that old aren't safe to trade on." |
| Empty "This run has no stocks", "Nothing matches" with loosen chips | Covered by "No recent run" and Ideas' empty state; "Nothing matches" removed with the filters |
| (none) | New: hidden line ("8 stocks you hold are hidden") with tip; held stocks and stocks with a working buy order are left out |
