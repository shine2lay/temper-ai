# Fit and revenue evidence kit: data dictionary (`pmf_evidence.params/1`)

Product role, queue #13. The rules `pmf_kit.py` applies, file by file and step by step. The
workflow `configs/workflows/pmf_evidence.yaml` runs them; `docs/product-runs.md` says how to start
it. Blank templates: `templates/` (next to this file).

## What the kit measures, and what it never decides

Three fit indicators, each judged on its own, plus revenue reported apart:

| Indicator | Question | Bar |
|---|---|---|
| Survey | Of eligible respondents, what share would be *very disappointed* if they could no longer use the product (Sean Ellis question)? | 40%, fixed by the mission; at least `survey.min_responses` eligible respondents |
| Retention | Of users who started, what share still do the core value event in each period after they start, and has that share stopped falling? | flat over the last adequate periods (`retention.*`) |
| Payment | How many customer accounts kept a payment of at least the target price, after refunds, in the horizon? | `payment.min_target_price_accounts` |
| Revenue (apart) | Net collected in the horizon: gross receipts minus refunds minus payment fees | `revenue.target` |

The verdict is `fit_indicators_met` only when survey, retention and payment are all `met`;
anything else is `fit_not_shown`. **The survey alone never shows product-market fit.** Even
`fit_indicators_met` is a measurement on the data given, not a claim the kit makes: the report
and its interpretation never say a product has product-market fit.

The kit chooses no market, price or target. Every product-specific value below is required and
has no default; a missing, misspelt or invalid one blocks the run before anything is measured or
any model runs, with one problem per parameter.

## Parameters (`params.json`)

All required. `null` counts as missing. A key the kit does not know is an error (catches typos).

| Parameter | Form | Meaning |
|---|---|---|
| `schema` | `"pmf_evidence.params/1"` | the contract version |
| `product` | text | the product's name, as the report shows it |
| `data_label` | `"synthetic"` or `"real"` | synthetic marks made-up test data: the report then says it is not evidence about any product |
| `buyer` | text | who pays for the product |
| `user_unit` | text | what one row of `users.csv` is: a person, a seat, a traveller |
| `account_unit` | text | what one customer account is: the unit that pays (a company, a household); one account can have many users |
| `value_event` | text, exact event name | the `activity.csv` event that marks the core value delivered (a plan shared, a trip booked), never a login or a page view |
| `observed_until` | `YYYY-MM-DD` | last day the exports cover; nothing after it is known |
| `currency` | three capital letters | currency of every `payments.csv` amount |
| `survey.min_value_events` | whole number >= 1 | value events a respondent needs in the look-back window to be asked and counted |
| `survey.lookback_days` | whole number >= 1 | the window: the answer day and the days before it |
| `survey.min_responses` | whole number >= 1 | eligible respondents needed before the survey is judged |
| `retention.period_days` | whole number >= 1 | length of one retention period; fit it to the usage rhythm (below) |
| `retention.cohort_by` | `week`, `month`, `quarter`, `year` | how users are grouped by start date in the cohort table |
| `retention.min_users_per_period` | whole number >= 1 | users who must be fully observed in a period for it to be adequate |
| `retention.min_periods` | whole number >= 1 | adequate periods, from period 1, needed before retention is judged |
| `retention.flat_last_periods` | whole number, 2 to `min_periods` | how many of the last adequate periods must be flat |
| `retention.flat_max_drop_pp` | number 0-100 | largest drop, in percentage points, from the first to the last of those periods that still counts as flat |
| `retention.min_plateau_rate` | number, above 0, at most 1 | lowest share active in the last adequate period that still counts (0.3 = 30%) |
| `payment.target_price` | decimal text `"49.00"` | the amount one payment must keep after refunds: the price of one billing payment (monthly price if billed monthly) |
| `payment.price_unit` | text | what that payment buys: "per account per month", "per household per year" |
| `payment.min_target_price_accounts` | whole number >= 1 | customer accounts that must pay the target price in the horizon |
| `revenue.target` | decimal text | net revenue to collect in the horizon |
| `revenue.horizon_start`, `revenue.horizon_end` | `YYYY-MM-DD` | the payment and revenue horizon; end not before start |
| `data_quality.max_rejected_share` | number, 0 to below 1 | largest share of a file's rows that may be rejected before the indicators using that file are not judged (0.05 = 5%) |

Problem codes: `missing_param` (absent or null; a missing block is one problem), `invalid_param`
(wrong form, a placeholder such as `TODO`, or a cross-field conflict), `unknown_param`,
`missing_input` (no params file or data folder given), `missing_file`, `unreadable_file`,
`missing_column`, `duplicate_column`. Any of them blocks.

### Fitting the windows to the usage rhythm

Retention counts a user as active in a period when they did the value event at least once in
it. Pick `period_days` so that a loyal user does the value event in nearly every period:

- a weekly work tool: 7 days, `cohort_by` month;
- a monthly bill or report: 30 days;
- travel booked a few times a year: 91 days (a quarter) or 365, `cohort_by` quarter or year.

With weekly periods, a traveller who books every quarter looks lost in most weeks; with 91-day
periods the same data shows a flat curve. Set `survey.lookback_days` and `min_value_events` the
same way: "at least twice in the last 14 days" (Superhuman's rule) suits a weekly tool, "at least
one trip in the last 365 days" suits travel. Choose these before looking at the results.

## Files (in one data folder, UTF-8 CSV with a header row)

Extra columns are allowed and ignored. Cells are trimmed. Dates are `YYYY-MM-DD`; a timestamp
(`2026-01-05T10:30:00`) counts by its date as written, so convert time zones before export.
Identifiers should be pseudonymous (no names, emails or other personal details): the kit needs
none, and the data must not be patient or health data.

| File | Columns | One row is |
|---|---|---|
| `users.csv` | `user_id,account_id,started_on` | one user (`user_unit`) and the customer account it belongs to; `started_on` is when the user started (signed up or first used) |
| `activity.csv` | `event_id,user_id,event,occurred_on` | one event; only `event == value_event` counts for retention and eligibility; other events are counted and ignored |
| `survey.csv` | `response_id,user_id,submitted_on,answer` | one answer to "How would you feel if you could no longer use the product?": `very_disappointed`, `somewhat_disappointed` or `not_disappointed` (case, spaces and dashes are forgiven) |
| `payments.csv` | `row_id,account_id,kind,amount,currency,occurred_on,ref_row_id` | one money row of a customer account: `payment` (money received), `refund` (money returned; `ref_row_id` = the payment), `fee` (payment-processing cost; `ref_row_id` = the payment), `promise` (a pledge, letter of intent or unpaid invoice: never money) |

Users and customer accounts differ: the survey and retention count users; payment and revenue
count customer accounts (`account_id`, linked to users in `users.csv`).

### Row rules, in order (a rejected row is listed with its line number and reason)

For every file, first: a row with more cells than the header is `extra_cells`; a row with no id
is `missing_value`. Rows sharing an id: exact copies (same values in every required column) are
kept once and counted as dropped duplicates; copies with different values are all
`conflicting_duplicate`, because the kit cannot know which is right. Then, per kept row:

- `users.csv`: an empty cell `missing_value`; a bad date `bad_date`; a start after
  `observed_until` `after_observation_end`.
- `activity.csv` and `survey.csv`: `missing_value`; `bad_date`; `after_observation_end`; a user
  not kept in `users.csv` `unknown_user`; a date before the user's start `before_user_start`;
  for the survey, any other answer `bad_answer`.
- `payments.csv`: an empty cell other than `ref_row_id` `missing_value`; `bad_date`;
  `after_observation_end`; a kind other than the four `unknown_kind`; an amount that is not a
  positive decimal with at most two places `bad_amount` (refunds are positive amounts too); a
  currency other than `currency` `currency_mismatch`; an account with no kept user
  `unknown_account`; a payment or promise with a `ref_row_id` `unexpected_reference`. Then refunds
  and fees, oldest first: a reference that is not a kept payment of the same account
  `bad_reference`; dated before that payment `before_referenced_payment`; a refund that would
  take the payment's refunds above its amount `refund_exceeds_payment`.

If a file's rejected rows exceed `max_rejected_share` of its rows, the indicators that use it
are not judged (`insufficient_evidence`, reason `data_quality`): survey uses users, activity
and survey; retention uses users and activity; payment and revenue use users and payments.

## Formulas

**Survey.** A respondent's first valid answer counts (earliest date, then file order); later
answers are set aside as repeats. The respondent is eligible when they did the value event at
least `min_value_events` times in the `lookback_days` days ending on the answer day (the answer
day and the `lookback_days - 1` days before it). Share = eligible "very disappointed" /
eligible respondents, shown with one decimal (half up), with a 95% Wilson score interval. Not
judged (`insufficient_evidence`) when a file it uses is over the rejection limit (`data_quality`),
`survey.csv` has no rows (`no_data`) or eligible respondents < `min_responses`
(`too_few_responses`, with how many more are needed). Otherwise `met` at 40% or more, else
`not_met` (`below_threshold`). With no eligible respondents the share is undefined, never 0%.
The share among all first answers is shown as context only.

**Retention.** Period k of a user covers days `started_on + k*period_days` to
`started_on + (k+1)*period_days - 1`. A period is fully observed when it ends on or before
`observed_until`; the last, partly observed period of each user is censored: it is left out,
and so are the value events in it, so a user is never counted as lost for a period not yet
seen. Retention in period k = users fully observed in k who did the value event in k / users
fully observed in k. Period k is adequate when k >= 1 and at least `min_users_per_period` users
are fully observed in it. Not judged when a file it uses is over the limit, when `users.csv` or
`activity.csv` has no rows, or when adequate periods < `min_periods` (`too_few_periods`; the
report says the earliest date when period `min_periods` will be fully observed for
`min_users_per_period` users). Otherwise, over the last `flat_last_periods` adequate periods,
the drop = share in the first of them - share in the last, in percentage points; `met` when the
drop is at most `flat_max_drop_pp` and the last share is at least `min_plateau_rate`, else
`not_met` (`still_declining` and/or `below_plateau`).

**Payment.** Payments dated `horizon_start` to `horizon_end` (and up to `observed_until`)
count. A payment keeps its amount minus all its refunds up to `observed_until`. A customer
account is at the target price when at least one of its payments keeps `target_price` or more.
`met` when such accounts >= `min_target_price_accounts`. If not, `not_met`
(`too_few_accounts`) when the horizon has ended by `observed_until`, else `insufficient_evidence`
(`horizon_open`): an open horizon is never "not met". Promises never count.

**Revenue.** For payments in the horizon: gross receipts = their amounts; refunds = their
refunds; fees = their fees (a fee stays when its payment is refunded); net = gross - refunds -
fees. Promises and payments outside the horizon are shown apart and never counted. `met` when net
>= `revenue.target`; otherwise as payment (`below_target` or `horizon_open`). Revenue is reported
apart: it is not one of the three fit indicators.

Statuses: `met`, `not_met`, `insufficient_evidence` (not judged yet, with reasons). Money is shown
with two decimals; shares with one decimal, rounded half up.
