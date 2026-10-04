# pmf_evidence benchmark (queue #13)

Nine labelled synthetic cases for `configs/workflows/pmf_evidence.yaml`. Every value is made up:
no real product, person, account or payment. `construct.py OUTDIR` writes them;
`expected.json` holds what the kit must compute (and each file's sha256) and is never staged into
a run; `score.py CASE=WORKSPACE` scores a finished run; `independent.py CASE_DIR` is a second,
separately written calculation used to cross-check the hand-worked values below before the kit's
calculator existed.

## How each case is built, and what follows

Shared weekly setup (N1, D1, L1, R1): 60 planner seats `u01`-`u60` in 20 agency accounts
(`a01` = u01-u03, ...). u01-u30 start Mon 2026-01-05, u31-u60 start Mon 2026-02-02. Observed
until 2026-03-31, so the January cohort is observed for 86 days = 12 full weeks (periods 0-11)
and the February cohort for 58 days = 8 full weeks (periods 0-7). Every seat logs in once a week
(a `login` event, never the value event); the value event `plan_shared` comes twice in each
active week (days 1 and 3). Per cohort: 16 core seats active every week, 8 fading seats active
in weeks 0-2, 6 seats active only in week 0. u05 skips week 10.

- **N1.** Retention: week 0 60/60; weeks 1-2 48/60 = 80.0%; weeks 3-7 32/60 = 53.3%; weeks 8-11
  only the January cohort is observed: 16/30, except week 10 15/30 (u05). With at least 20 users
  per period, weeks 1-11 are adequate (11 >= 6); the last three (9-11) go 53.3% -> 53.3%: drop 0.0
  points <= 5, last 53.3% >= 30%: **met**. Events after a seat's last full week (Mar 30-31) fall in
  a censored week and do not count. Survey on 2026-03-20, look-back 14 days (Mar 7-20), two value
  events needed: all 32 core seats are eligible (weeks 9-10, or 5-6 for February); the 8 fading
  and 4 dropped respondents are not (their last value events are in January/February). Eligible
  answers 14 very / 12 somewhat / 6 not: 14/32 = 43.8% >= 40%, n 32 >= 30: **met** (95% Wilson
  interval 28.2%-60.7%). Counting the 12 ineligible respondents (10 "not", 2 "somewhat") would give
  14/44 = 31.8%. Payments in Jan 1 - Mar 31: a01-a08 3 x 49.00, a09-a10 3 x 39.00, a11-a14
  2 x 49.00, a15-a16 2 x 39.00, a17-a20 none; a fee row (1.72 per 49.00, 1.43 per 39.00) on each.
  Target-price accounts 12 >= 10: **met**; paying 16, below target 4. Gross 1176 + 234 + 392 + 156
  = 1958.00; fees 32 x 1.72 + 10 x 1.43 = 69.34; net 1888.66 >= 1500.00: **met**. Verdict
  `fit_indicators_met` on synthetic data.
- **E1.** All four files have a header and no rows. Every indicator is insufficient (no data);
  shares and intervals undefined; 30 more eligible responses needed. Verdict `fit_not_shown`.
- **I1.** 30 seats (10 accounts) start 2026-01-26, observed until 2026-02-15 = 21 days = weeks
  0-2. 24 seats active every week, 6 only in week 0: weeks 1-2 24/30 = 80.0%; 2 adequate weeks
  < 6: **insufficient**. Week 6 is complete for all 30 seats on 2026-03-15 (start + 49 days - 1),
  so retention can be judged from then. Survey 2026-02-12 (look-back Jan 30 - Feb 12): 12 active
  respondents eligible, 3 dropped ones not; 6/12 = 50.0% but 12 < 30: **insufficient**, 18 more
  needed. a01-a06 pay 49.00 on Jan 26 (+ 1.72 fee): 6 target-price accounts, horizon to Mar 31
  still open: **insufficient** (not "not met"). Gross 294.00, fees 10.32, net 283.68, open. a07's
  490.00 promise is reported apart and never counted.
- **D1.** N1 plus planted rows. users: an exact copy of u01 (dropped), u61 dated 2026-02-30
  (bad_date), u63 twice with different accounts (both conflicting_duplicate): 3 of 64 rejected =
  4.7% <= 5%. activity: two exact copies (dropped), unknown users u99 and u63, a 2026-13-01 date,
  a 2026-04-01 event, a February seat's event before its start, two rows sharing id eX06 with
  different dates, a blank event name: 8 of 1460 rejected. survey: an exact copy of u01's
  response (dropped), a second answer from u01 on Mar 25 (a repeat respondent: the first answer
  counts), "Very dissapointed" (bad_answer), a blank answer (missing_value): 2 of 48 rejected;
  u03's answer is written "Very disappointed" (the label, same answer). payments: an exact copy
  (dropped) and 11 bad rows (two rows sharing id pX01, three bad amounts, EUR, kind "chargeback",
  account a99, a refund of an unknown row, a 60.00 refund of a 49.00 payment, a payment with a
  reference): 11 of 96 = 11.5% > 5%, so payment and revenue are **not judged** (data quality).
  Survey and retention equal N1's. Verdict `fit_not_shown`.
- **L1.** N1's layout, but the January core seats stop: u08-u09 after week 10, u10-u12 after week
  9, u13-u16 after week 8. Weeks 3-8 stay at 53.3%, then week 9 12/30 = 40.0%, week 10 8/30 =
  26.7% (u05 skips it), week 11 7/30 = 23.3%. Last three: drop 16.7 points > 5 and 23.3% < 30%:
  **not met**. Survey (min 25): eligible 28 (12 January seats active in weeks 9-10 and the 16
  February core seats); 13 very of 28 = 46.4%: **met**. u13-u16 answered "very" but stopped
  before the look-back, so they are not eligible. Payments as N1: **met**. Verdict
  `fit_not_shown`.
- **R1.** N1's seats, usage and survey; payments with refunds (refund rows follow their payment):
  a01's March payment refunded; a02 and a05 fully refunded; a03 keeps 29.00 of January only;
  a04 keeps 44.00 of January but pays February and March in full; a07 keeps 34.00 of March only;
  a14 keeps 39.00 of March but paid February in full; a18 paid on 2025-12-28 (outside the
  horizon); a19 paid on 2026-03-31 (inside, last day); a17 and a20 only promised (590.00, 49.00).
  Target-price accounts a01, a04, a06, a08, a11-a14, a19 = 9 < 10, horizon complete: **not met**
  (ignoring refunds would give 13). Paying 15, below target 6, fully refunded 2. Gross 2007.00,
  refunds 589.00, fees 33 x 1.72 + 10 x 1.43 = 71.06 (fees stay with refunded payments), net
  1346.94 < 1900.00: **not met**, although gross alone would pass. Verdict `fit_not_shown`.
- **F1.** 80 travellers, each its own household account; t001-t040 start 2024-01-15, t041-t080
  2024-07-15; observed to 2026-06-30 = 898 and 716 days = 9 and 7 full 91-day periods. Per
  cohort: 24 book a trip (`trip_booked`) every period, 4 in even periods, 4 in period 0 and odd
  periods, 8 only in period 0; everyone opens the app each period (not the value event).
  Periods 1-6: 56/80 = 70.0%; periods 7-8 (first cohort only) 28/40 = 70.0%; 8 adequate periods
  (>= 30 users), last three flat at 70.0% >= 50%: **met**. With weekly periods the same data would
  look like churn; the period fits the rhythm. Survey 2026-06-01 with a 365-day look-back and one
  trip needed: 64 eligible (every traveller but the one-trip ones), 28 very = 43.8% >= 40%,
  n 64 >= 40: **met**. Payments in H1 2026 (EUR): 48 regulars pay 79.00 (two refunded in full),
  16 occasional travellers pay 59.00; the 16 one-trip travellers paid 79.00 in 2024 (outside).
  Target-price households 46 >= 30: **met**. Gross 3792 + 944 = 4736.00, refunds 158.00, net
  4578.00 >= 3000.00: **met**. Verdict `fit_indicators_met` on synthetic data.
- **S1.** 50 team members (25 accounts, 2 each) start 2026-02-02, observed to 2026-03-01 = 28
  days = weeks 0-3; 40 active weekly, 10 only in week 0: weeks 1-3 40/50 = 80.0%, 3 adequate
  weeks < 6: **insufficient**; judged from 2026-03-22. Survey 2026-02-27: 40 eligible (exactly the
  minimum 40), 18 very = 45.0%: **met**. a01-a04 pay 49.00 (+ fees), a05-a07 promise 49.00;
  horizon Feb 1 - Apr 30 open: payment and revenue **insufficient** (4 target-price accounts;
  gross 196.00, fees 6.88, net 189.12; promises 147.00 apart). Verdict `fit_not_shown`: the
  survey alone never shows fit.
- **P1.** N1's exports; parameters: `observed_until`, `value_event`, `retention.period_days`,
  `payment.target_price` and the whole `revenue` block left out; `retention.perod_days` misspelt;
  `data_label` "test", `currency` "usd", `survey.min_responses` 0 and
  `payment.min_target_price_accounts` "10" (a string) wrong. Setup blocks with exactly those ten
  problems, before any model step, at no cost.
