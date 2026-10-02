# Validation Engine — autonomous demand testing for shaped bets

Status: built 2026-10-01 (configs/validation; see [As built](#as-built-configsvalidation)).
The no-spend dry run is proven end to end; live runs wait on the owner's rails, a budget and
the go-ahead. Owner: Product management role. Created 2026-10-01.

## Why this exists (north-star fit)

The north star is a system that *designs great tech products*: generate theses, test them
cheaply against the real market, and only invest where real buyers pull. The pipeline:

```
Scan (idea generation)  ->  Signal Harvest (free demand screen)  ->  Validation Engine (paid, real behaviour)
   configs/epd_* + scan        Rung 0 (this repo, free)                Rungs 1-4 (this spec)
```

The Scan produces a ranked shortlist of wedges. Signal Harvest (Rung 0) screens them with
free passive signals. The Validation Engine is the next, paid step: put each surviving idea
in front of real strangers and measure what they *do*, not what they say — then hand back a
go / pivot / kill decision backed by behaviour and money.

This document is the buildable spec. It is design-only; nothing here spends money or goes
live until the owner provides the rails (see "Rails checklist") and gives the go-ahead.

## Core principle: words -> behaviour -> money

A demand signal is only as strong as the cost the person paid to send it. We climb a ladder
and weight the rungs accordingly (money > behaviour > words):

| Rung | Signal | Cost to send | Covered by |
|---|---|---|---|
| 0 | Search trend, job-post counts, pain frequency, competitor vitals | free, passive | Signal Harvest |
| 1 | Ad click-through (CTR) | a click | Validation Engine |
| 2 | Email / early-access signup | an email | Validation Engine |
| 3 | Refundable deposit / concierge order | real money | Validation Engine |
| 4 | Opt-in, disclosed AI interview | their time | Validation Engine |

Rule: **validate cheapest -> most expensive, one rung at a time; do one rung well before the
next.** A tiny ad budget screens out duds; only survivors earn a bigger spend.

## The funnel — one metric per step

Every step is a filter. The *drop-off between steps* is where belief breaks and is the real
finding.

| Step | Question it answers | Metric |
|---|---|---|
| impression -> click | Does the pain headline land? | CTR |
| click -> engaged view | Did they read, or bounce? | scroll-depth / time-on-page |
| engaged view -> signup | Will they raise a hand? | signup rate |
| signup -> deposit / booked call | Will they put skin in the game? | commitment rate |
| deposit -> uses the concierge | Is the pain real in their workday? | activation |
| first use -> repeat use | Does it stick? | retention |

Diagnostics: great CTR + no signup = headline oversold. Many signups + no deposit =
nice-to-have, not must-have. Deposits + no repeat use = one-off novelty, not a business.

## Pre-registered thresholds (rules of thumb — calibrate per channel before running)

Set the bar *before* running so results cannot be rationalised. Directional B2B ranges to
refine per channel/idea, not gospel:

- CTR: cold social ~0.5-1.5%; search-intent higher. Below ~0.3% = pain does not resonate.
- Landing -> email: ~10%+ is strong for a genuine pain; under ~3% is weak.
- Email -> deposit: 2-5% of a small list putting money down is a strong green light.
- The bar that matters most is an absolute count of costly actions from the target segment,
  e.g. ">= 3 small carriers leave a refundable deposit within 10 days."

## Generating the right engagement (not just any clicks)

Engagement from the wrong people is worse than none — it fools you.

- Target precisely: the exact buyer (e.g. owner-operators / small-fleet dispatchers), by
  interest + geography. A random click is not a buyer.
- Two channels, two intents: a **search ad** (captures existing intent — purest signal if
  volume exists) *and* a **cold social/Reddit ad** (tests whether we can create demand).
  Search-only working = market exists but is small; cold working = room to grow.
- Tag everything with UTM params so every signup/deposit traces to its source and segment.

## Verifying engagement is real (anti-self-deception)

The part most people skip. Build these in:

- Bot / junk filtering: bot-filtering analytics (Plausible/PostHog); discard sub-2s sessions
  and data-centre IPs. Raw "visits" mean nothing.
- Depth over vanity: weight scroll-depth, time-on-page, and repeat visits over raw clicks.
  Did they reach the "how it works" section?
- Escalating ask: curiosity gives an email; demand clears a cost bar. Always include a
  **costly second action** (refundable deposit, booked call, or detailed form). Money and
  time do not lie the way a free email does.
- Follow-up reply: after signup, send one real question ("what's your current process?").
  Replies are a strong intent tell; silence from the whole list is a red flag even when the
  signup rate looked fine.

## Experimental design (so the numbers hold up)

- A/B the **value proposition**, not the button colour — test 2-3 pain framings
  ("stop re-keying BOLs" vs "get paid 2 days faster"). The winner is also future marketing.
- One variable at a time; same budget and audience; run >= 5-7 days to cover weekday rhythms.
- **Sample-size tiers (the honest catch).** A $50 test at ~$2/click is ~25 clicks — enough to
  kill a dud, far too few to prove a winner. So run two tiers (also fits cheapest-first):
  - Screen (~$50/idea): kills the obviously dead ideas fast.
  - Confirm (~$200-400) on survivors only: ~150-300 clicks, a rate you can trust.

## Beyond acquisition: activation and retention

Acquisition engagement can be a sugar high. For survivors, run the **concierge**: manually
deliver the outcome (e.g. do the BOL data-entry by hand) for the people who paid, then watch
whether they send a second load, and a tenth. Repeat usage is the only engagement signal that
predicts a real business.

## Decision rules (pre-registered, per idea)

- Advance: clears the commitment bar (deposits) AND shows real depth/replies.
- Pivot: one message/segment flops but another clearly works — change the framing or segment,
  not the whole idea.
- Kill: cheap screen shows near-zero CTR, or signups with no commitment. A clean "no" is a win.

## Scorecard schema (per idea, machine-readable)

The engine emits one scorecard per idea, updated as data arrives:

```yaml
idea_id: bol-ocr-trucking
run_window: { start: 2026-11-01, end: 2026-11-11 }
segment: us-small-fleet-dispatchers
channels: [google-search, reddit-ads]
funnel:
  impressions: { n: 0 }
  clicks:      { n: 0, ctr: 0.0, threshold: 0.005, pass: null }
  engaged:     { rate: 0.0, scroll90: 0.0, median_seconds: 0 }   # bot-filtered
  signups:     { n: 0, rate: 0.0, threshold: 0.10, pass: null }
  commitment:  { deposits: 0, booked_calls: 0, threshold_n: 3, pass: null }
  activation:  { used_concierge: 0 }
  retention:   { repeat_users: 0 }
variants:      # A/B value-prop framings
  - { id: A, headline: "...", clicks: 0, signups: 0 }
  - { id: B, headline: "...", clicks: 0, signups: 0 }
quality_flags: [ ]        # bot_spike, segment_leak, sample_too_small
spend_usd: 0.0
decision: null            # advance | pivot | kill
evidence: [ ]             # links: live page, ad dashboards, deposit records
```

## Autonomy split

- The agent does: write page copy + A/B variants, deploy the page, instrument events, tag
  UTMs, configure + launch ad campaigns, pull CTR/CPC/spend, read signup + deposit counts,
  recruit opt-in interviewees via a panel and run disclosed AI interviews, and roll everything
  into the live scorecard with an auto go/pivot/kill verdict. It operates accounts via their
  APIs or, where there is no clean API, by driving the dashboards with browser control.
- The owner provides (once): the rails below, a budget, and the go-ahead to spend. After that,
  each surviving idea is validated hands-off.

## Rails checklist (one-time owner setup)

Rungs 1-4 run real money under the owner's identity. Needed before go-live:

- A domain (a neutral test brand, not the owner's main brand).
- A web host account (Vercel/Netlify) + a bot-filtering analytics account (Plausible/PostHog).
- Ad account(s): Google Ads and/or Meta/Reddit, billing attached.
- A Stripe account (for refundable deposits / pre-orders).
- An interview-panel account (Respondent / User Interviews) and an AI-voice-agent account
  (Vapi/Bland/Retell) if running Rung 4.
- A per-idea budget (screen + confirm tiers) and standing go-ahead to spend within it.

The agent operates these; the owner owns them. "Accounts connected + budget set" is treated
as standing authorisation; the agent still stops and asks before exceeding the set budget.

## Guardrails (ethics, honesty, brand, compliance)

- Honest fake-door: deposits are fully refundable; wording is "early access / reserve", never
  implying the product already ships.
- Disclose AI in any interview or call; opt-in panels only — no cold-calling/emailing
  strangers (TCPA / CAN-SPAM / GDPR risk + reputational harm).
- Neutral test brand, never the owner's main brand.
- Respect community rules: no automated posting/astroturfing in forums.

## Build plan (temper workflow shape)

Mirror the Scan/Signal-Harvest pattern. Candidate configs in gitignored `configs/*/local/`
first, in a `wt new` worktree; land only a working engine.

- Workflow `validation_engine` orchestrates per-idea:
  1. `ve_page` — write landing-page copy + 2-3 A/B value-prop variants.
  2. `ve_deploy` — deploy page + wire analytics events + UTM scheme. (needs rails)
  3. `ve_campaign` — configure + launch screen-tier ad campaign(s). (needs rails)
  4. `ve_collect` — poll analytics + ad + Stripe; bot-filter; assemble the scorecard.
  5. `ve_decide` — apply pre-registered thresholds -> advance / pivot / kill; size the
     confirm-tier spend for survivors.
  6. `ve_interview` (optional, Rung 4) — recruit opt-in panel + run disclosed AI interviews +
     theme-extract.
- Steps 2-3-6 are gated: if rails/credentials are absent, the workflow stops and surfaces the
  Rails checklist rather than failing silently.
- Keep tool blocks off agents on `provider: claude` (that provider ignores temper tool schemas;
  it uses its own built-in tool loop). See docs/testing.md and the Scan trial lessons.

## As built (configs/validation)

One idea per run. The steps are plain scripts (`configs/validation/bin/ve.py <step>`) except
the three that need judgement or a browser, which run on `provider: claude` with no `tools:`
block.

```
ve_setup -> ve_page -> ve_deploy -> ve_campaign (live) | ve_simulate (dry run) -> ve_collect -> ve_decide -> ve_interview
```

| Step | Kind | What it does |
|---|---|---|
| `ve_setup` | script | Reads which rails exist (names only, never values), picks the mode, writes and sha256-locks `preregistration.json` (bars, window, budget, channels, decision rules, refund-by date) before any data exists. Live without every rail, a budget or the go-ahead: stops, writes `RAILS_CHECKLIST.md`, nothing is deployed or spent. Refuses a second launch while a live test runs, and a confirm tier for an idea with no advance/pivot. |
| `ve_page` | model | Writes `page/copy.json`: a neutral test brand, 2-3 value-proposition framings (A/B the pain, not the button) with ad creatives, "how it would work", FAQ, the follow-up question; then runs `ve.py check-copy` until the honesty check passes. |
| `ve_deploy` | script | Renders the site (one page per framing, reserve, call, thanks, privacy, deposit-done) with `ve.js`; checks every rendered page again (early-access banner, refund terms, no ships-now wording, no owner brand); dry run: a local test URL; live: Stripe Payment Links per framing + Netlify deploy + form check. Writes `campaign_plan.json`: every ad with its UTM URL and a lifetime cap, the caps never adding up past the budget. |
| `ve_campaign` | model, live only | Phase `all`: launches exactly the plan (API or the signed-in browser), records `campaign_launch.json`, `ve.py check-launch` must pass. Phase `collect`: pulls the ad report into `ad_report.jsonl`, `ve.py check-ad-report` (over budget = pause every ad and tell the owner). |
| `ve_simulate` | script, dry run only | A seeded synthetic crowd (with planted bots: under 2 s, bot user agents, automated browsers, data-centre IPs) clicks the planned ads and goes through the real pages in a real browser (Playwright), fills the forms, reserves through a mock checkout, asks for one refund. Zero spend; every row is marked synthetic. |
| `ve_collect` | script | Live: pulls raw events (PostHog), forms (Netlify) and deposits/refunds (Stripe). Both modes: the bot filter, sessions, the funnel, `scorecard.yaml` in the schema above. |
| `ve_decide` | script | Verifies the pre-registration hash, applies the rules in order, sizes the confirm tier for survivors, writes `decision.json` and `report.md`. Live kill: refunds every deposit. Always runs (a stopped run's report is the rails checklist). |
| `ve_interview` | model, survivors only | `prepare` (dry run, screen tier, or no interview rails): guide, panel screener, AI-disclosure + consent script, invite for signups who asked for a call; contacts no one. `live` (confirm tier with panel + voice rails): opt-in panel only, disclosed AI interviews, themes with quotes. |

**Instrumentation.** `ve.js` sends `page_view`, `scroll` (25/50/75/90), `section_view`
("how it works"), `heartbeat`, `page_leave` (seconds on page), `signup`, `followup_answer`,
`call_click`/`call_request`, `deposit_click`/`deposit_paid`, each with the session, framing and
the UTM tags. Every ad URL carries `utm_source`, `utm_medium`, `utm_campaign=ve-<idea>-<tier>`,
`utm_content=<framing>`, `ve_ad=<ad id>` and, on search, `utm_term={keyword}`. The follow-up
question is asked on the thanks page right after signup (no email rail needed).

**Bot filter.** A session is dropped when it lasts under 2 s, comes from a data-centre range
(`bin/datacenter_cidrs.txt`), has a bot user agent or reports an automated browser. Sessions
without the test's `utm_campaign`, from another test, or (live) marked synthetic are counted
apart. Real sessions outside the target countries are a `segment_leak`. The dry run checks the
filter against the simulator's ground truth (every planted bot caught, no human dropped).

**Rules, in order** (`ve_score.decide`, each step written to the report's trace):
`kill_ctr` (1,000+ impressions, CTR under 0.3%, no framing at 0.5%) ->
`kill_no_commitment` (10+ signups, no deposit, no booked call) -> `kill_signup_rate` (20+
real visits, signup rate under 3%, no framing at 10%) -> screen: `pivot` when one framing
works and another flops by 2x or more with a one-sided Fisher p under 0.05 (drop the flop),
else `advance` (the screen only kills duds) -> confirm: `advance` on 3+ deposits, 30%+ engaged
and an answered follow-up, else `pivot`, else `kill_default`. A moved bar gets no verdict.
Under the data minimums the call is flagged `sample_too_small`, not judged. A verdict before
the window ends is `provisional`.

**Confirm sizing.** max(100 clicks per kept framing, 150), capped at 300, at the screen's
observed CPC (else the assumed $2), over 10 days; above the owner's confirm budget, or with
none set, the owner is asked first.

**Deposits.** $49 by default, fully refundable on request any time, and in full if nothing
launches within 90 days: the refund-by date is in the pre-registration and the report, and
`ve.py refund --dir <idea folder> --why <reason>` gives back every deposit still held (Stripe
calls are idempotent). A live kill refunds at once.

**Running it.**

- Dry run (default, $0): `temper run validation_engine -i idea="<one paragraph>" -i idea_id=<slug>
  -i segment="..." -i evidence=<signal-harvest notes> -i interviews=yes`.
- Live: the owner copies `configs/validation/rails.example.env` to
  `~/.config/validation-engine/rails.env` (chmod 600) and fills it in; `ve.py checklist` shows
  what is still missing. Then `-i mode=live` (phase `all`: page, deposits, ads), and after the
  window `-i mode=live -i phase=collect -i state_root=<same folder>` for the verdict. Confirm
  tier: `-i tier=confirm` on a survivor.
- State per idea: `<state_root>/state/ve/<idea_id>/` (rails.json, preregistration.json,
  page/, site/, campaign_plan.json, events/forms/deposits/ad_report .jsonl, scorecard.yaml,
  decision.json, report.md, evidence/, interview/). A new test archives the previous one.

**Tested** in `tests/test_validation_engine` with no service reached: a whole dry run through
the real page (HTTP crowd), the gate (every missing rail, a budget above the owner's, a second
launch, a secret never printed), the rules, the launch and ad-report checks, and the live
adapters on a fake transport. The Netlify, PostHog and Stripe adapters meet the real services
for the first time on the first live run: run it in Stripe test mode first.

**First dry run** (2026-10-01, hourly-screening, the Signal Harvest's top idea): ve_page wrote
the "Shiftfunnel" page (3 framings) for $0.39 in 2 minutes; the browser crowd took 33 s. 70
visits, 12 planted bots all caught, 0 humans dropped; 10,416 impressions, CTR 0.67%, 49 real
visits in segment, 7 signups (14%), 1 deposit + 2 booked calls, $0 spent; the rules gave
PIVOT (framing A 33% vs B 0%, p=0.02) and sized a $400 confirm tier that needs the owner's
budget. Synthetic numbers: they test the engine, not the idea.

## Cost model (cheapest-first)

- Rung 0 (Signal Harvest): ~free, desk research only.
- Screen tier (Rungs 1-2): ~$50/idea, directional only.
- Confirm tier (Rungs 1-3): ~$200-400 per *surviving* idea.
- Rung 4 interviews: panel incentive + voice-agent minutes, per interview; only on finalists.

Spend climbs only as confidence climbs. Most ideas die cheap at the screen tier.

## Open questions (to calibrate before first live run)

The engine starts from the defaults in `ve_common.DEFAULT_THRESHOLDS` (CTR 0.5% / kill 0.3%,
signups 10% / weak 3%, 3 deposits, 30% engaged, 100 clicks per framing for an A/B call, $49
deposit, screen 7 days, confirm 10 days); `build_preregistration(overrides=...)` changes them
per idea, before the run, never after.

- Exact per-channel CTR / signup / deposit thresholds (seed from benchmarks, update after run 1).
- Deposit size that is "costly enough" to signal intent without killing all conversion.
- Minimum clicks per variant for an A/B call at our budget (power vs spend trade-off).
- Which single channel to pilot first per idea (search-intent vs cold), by idea type.
