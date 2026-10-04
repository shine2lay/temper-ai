# Signal Scorecard — Travel Discovery-by-Preference (V1–V4)

Synthesized 2026-10-03 from four Rung-0 findings files: `state/signal/search.md`,
`state/signal/spend.md`, `state/signal/pain.md`, `state/signal/competitors.md`.
No new research was performed; every figure/quote/URL below is carried from
those four files. Weights (owner rule, money > behavior > words): spend .35,
competitors .30, pain .20, search .15. Each signal score (0–3) is discounted
by the signal agent's own stated confidence (high=1.0, med=0.8, low=0.5)
before weighting; vendor/listicle-only evidence is treated as low-confidence
regardless of what the agent wrote.

## Scorecard table

| Idea | search (raw×conf=disc) | spend (raw×conf=disc) | pain (raw×conf=disc) | competitors (raw×conf=disc) | **weighted_score** | overall confidence | platform overlap |
|---|---|---|---|---|---|---|---|
| V1 — AI-chat trip planner | 2×0.8=1.60 | 3×0.8=2.40 | 3×1.0=3.00 | 3×1.0=3.00 | **2.58** | high | **HEAVY** — Google (AI Mode/Canvas/Gemini), ChatGPT apps (Expedia/Booking.com partners), Kayak Ask AI, Booking.com AI Trip Planner, Trip.com TripGenie, Expedia Romie all give away free chat itinerary-building |
| V2 — Preference quiz | 1×0.5=0.50 | 1×0.5=0.50 | 2×0.8=1.60 | 1×0.5=0.50 | **0.72** | low | **SOME** — Google Flights Explore does the budget-driven consumer half free; no B2B widget-licensing overlap found |
| V3 — Past-trips recs | 0×0.5=0.00 | 1×0.8=0.80 | 3×1.0=3.00 | 1×0.8=0.80 | **1.12** | med | **HEAVY (narrower front)** — Gemini "Personal Intelligence," Trip.com TripGenie, Airbnb travel map all absorb pieces of the taste-profile job free |
| V4 — Advisor matching (business) | 2×0.8=1.60 | 3×1.0=3.00 | 2×0.8=1.60 | 3×0.8=2.40 | **2.33** | high | **NONE found** — no large platform gives away a B2B client-intake + matching engine; genuine software-category gap |

Arithmetic (weighted_score = 0.15×search + 0.35×spend + 0.20×pain + 0.30×competitors):
- V1: 0.15(1.60) + 0.35(2.40) + 0.20(3.00) + 0.30(3.00) = 0.24 + 0.84 + 0.60 + 0.90 = **2.58**
- V2: 0.15(0.50) + 0.35(0.50) + 0.20(1.60) + 0.30(0.50) = 0.075 + 0.175 + 0.32 + 0.15 = **0.72**
- V3: 0.15(0.00) + 0.35(0.80) + 0.20(3.00) + 0.30(0.80) = 0 + 0.28 + 0.60 + 0.24 = **1.12**
- V4: 0.15(1.60) + 0.35(3.00) + 0.20(1.60) + 0.30(2.40) = 0.24 + 1.05 + 0.32 + 0.72 = **2.33**

## Player coverage table completeness

competitors.md's Player Coverage Table carries **23 rows** total: all **19** players
named in the brief (Mindtrip, Layla, Wanderlog, TripIt, Google [Gemini/AI Mode/Flights
Explore bundled], ChatGPT, Expedia's AI assistant [Romie], Booking.com's AI Trip
Planner, Trip.com TripGenie, Kayak, Tripadvisor, Airbnb, Hopper, Polarsteps,
GetYourGuide, Viator, Travefy, Tern, Fora) plus **4 extra** players the agent
surfaced unprompted (GuideGeek, a bundled row of small destination-quiz sites,
Simpleview "Visit Widget," Expedia One Key). Every row has existence, URL+date,
overlap-with-candidate, free/paid/bundled, and at least one traction figure —
**23/23 rows structurally complete, none of the 19 requested players missing.**
Caveat: several of those traction/vitals fields rest on blocked-fetch snippets
rather than confirmed primary reads — Mindtrip's Crunchbase/PhocusWire (403),
Hopper's Business of Apps (403), Tripadvisor's Q2 2026 IR release (403),
Fora's Trustpilot/commission page (429) — so "complete" means all four fields
are populated, not that all are primary-verified.

---

## V1 — AI-chat trip planner for leisure travelers (consumer)

- **search = 2 × conf 0.8 (med) = 1.60.** Wanderlog iOS: 4.9★/**36,000 ratings**
  (measured, primary, apps.apple.com, 2026-10-03); Mindtrip iOS: 4.7★/**816
  ratings** (measured, primary); r/solotravel **4,574,353 members** (measured
  via third-party mirror, secondary, reddapi.dev). Real, sizeable existing
  market of AI-trip-planner users, but no Google Trends slope was obtained —
  "rising" is inferred from review/competitor-count growth, not measured
  (search.md caps this at medium confidence for exactly that reason).
- **spend = 3 × conf 0.8 (med) = 2.40.** Layla charges **$9.99/mo or
  $49.99/yr** — almost exactly V1's proposed price (measured, primary, App
  Store listing, 2026-10-03). Behaviour: **56% of US travelers now use AI for
  trip planning (up from 43%)**; **37% of Americans planning summer 2026
  travel are using AI** — Allianz Partners/Ipsos, n=2,001 US adults, fielded
  Mar–Apr 2026 (measured, secondary trade press reporting a named, dated
  survey). AAA Consumer Pulse (n=5,000, measured, primary, AAA's own
  newsroom): 81% say travel agents are valuable — the human-paid-for version
  of this job still carries real weight.
- **pain = 3 × conf 1.0 (high) = 3.00.** 7 distinct primary complaints across
  4 incumbent apps + 2 forums, 2025-08–2026-09. "I wasted so many hours with
  this app. And now I'm supposed to start over." (Mindtrip App Store review,
  2026-07-07); "With today's technology a person should not need two or
  three apps in order to plan a vacation." (TripIt App Store, 2026-09-29).
- **competitors = 3 × conf 1.0 (high) = 3.00.** Crowded-and-growing with real
  funding/review evidence: Mindtrip **$22.5M raised** (Costanoa, Capital One
  Ventures, United Airlines Ventures, Amex Ventures — secondary); Expedia
  **acquired Layla outright, announced 2026-07-31** (skift.com). But the same
  file flags this as increasingly **platform-bundling risk**: Google AI
  Mode/Canvas, ChatGPT apps (Expedia/Booking.com partners via MCP, launched
  2025-10-10), Kayak Ask AI, Booking.com's AI Trip Planner, Trip.com
  TripGenie and Expedia Romie all now offer a free conversational itinerary
  builder bundled into platforms travelers already use — none of them
  monetize via V1's proposed $5–10/mo subscription, they're loss-leaders for
  their own booking supply.

**weighted_score = 2.58. Overall confidence: high** (4/4 signals med-or-above,
3 with substantially primary sourcing — pain and competitors cite primary
App Store/press data directly).

---

## V2 — Preference quiz that matches travelers to destinations (consumer /
widget for media & sellers)

- **search = 1 × conf 0.5 (low) = 0.50.** At least **8 distinct named
  "where should I travel" quiz products** exist (NatGeo, Hotels.com,
  Interact, DestList, etc. — measured count, mixed primary/vendor quality).
  But search.md itself calls this "a long-standing, evergreen content format
  ... not a newly emerging query pattern," with no Trends data and no
  subscriber/traffic numbers — consistent with a commodity trope, not
  measured rising demand. Confidence stated low.
- **spend = 1 × conf 0.5 (low) = 0.50.** Direct negative finding: **"No
  incumbent destination-matching quiz charges consumers directly"** — every
  example (DestList, Voyasee, TripMemo, Voyaige) is free/ad-affiliate
  (measured, but secondary/vendor pages read via snippet). The only paid
  comparables are generic, non-travel-specific — Outgrow SaaS pricing
  $22–$720/mo (vendor) and travel CPL estimates of $74–$106/lead
  (causalfunnel.com, listicle, "treat as directional only, not load-bearing"
  per spend.md itself).
- **pain = 2 × conf 0.8 (med) = 1.60.** 4 distinct, recent, primary forum
  quotes: "I'm overwhelmed by choices, and happy to hear any
  opinions/suggestions" (Rick Steves Forum, 2025-09-15); "for whatever reason,
  I am finding planning for a trip to Alaska daunting!" (Rick Steves Forum,
  2025-09-29). pain.md itself flags these are about narrowing an
  already-shortlisted set rather than a blind "where in the world" ask —
  real but off-target evidence, hence moderate not strong.
- **competitors = 1 × conf 0.5 (low) = 0.50.** "Market read: thin-or-none,
  ambiguous." No well-funded, well-reviewed pure-play destination-quiz
  incumbent found; closest adjacent evidence is Google Flights Explore
  (free, folded into a bigger recurring product) and GuideGeek's **"70+"
  DMO partnerships** (vendor claim via Wikipedia). competitors.md explicitly
  rates confidence low here: "could not find funding, headcount, or
  review-count data for any pure-play destination-quiz competitor."

**weighted_score = 0.72. Overall confidence: low** (spend AND competitors
both low-confidence — triggers the low-confidence rule automatically).

---

## V3 — Recommendations from a traveler's own past trips (consumer)

- **search = 0 × conf 0.5 (low) = 0.00.** search.md found no query-level
  evidence (autocomplete, forum thread, Trends) of travelers themselves
  searching for this; the only evidence is indirect competitor-gap analysis
  — Polarsteps "won't suggest attractions, restaurants, or activities at
  your destinations" (secondary reviewer characterization, wandrly.app).
  That is a *negative* finding, not demonstrated search demand.
- **spend = 1 × conf 0.8 (med) = 0.80.** No incumbent prices "recommendations
  from your own past trips" as a standalone feature; the $5–10/mo /$50/yr
  figure is only supported by adjacent pricing (Wanderlog Pro ≈$39.99/yr,
  TripIt Pro $49/yr). Behaviour side is large but secondary: Marriott Bonvoy
  **"more than 295 million members"** (secondary, reporting Marriott's Q2
  2026 release); Hilton Honors **260 million members, up 15% YoY**
  (secondary). Large raw material, but not money paid for this specific job.
- **pain = 3 × conf 1.0 (high) = 3.00.** 5–6 distinct, on-target, recent
  primary complaints, squarely about losing/being unable to manage past-trip
  history inside the exact incumbents V3 would dislodge: "It loses past trip
  histories... I really enjoyed this app for a few years until it lost all
  my past trip history" (TripIt App Store, 2026-08-25); "Wont let me add old
  trips... Who remembers dates?!" (Polarsteps App Store, 2026-04-14).
- **competitors = 1 × conf 0.8 (med) = 0.80.** "Thin-or-none for a dedicated
  product" — no incumbent combines email-confirmation import + loyalty +
  photos into one taste-profile product, but the ingredients already exist
  separately: Gemini's opt-in "Personal Intelligence" (pulls Gmail, Photos,
  Search, YouTube), Trip.com TripGenie (uses behaviour/browsing history even
  at home). competitors.md: "good vitals on the adjacent players... but no
  direct incumbent to benchmark the actual V3 wedge against."

**weighted_score = 1.12. Overall confidence: med** (no signal is low-confidence
in a way that triggers the auto-low rule except search alone; but spend and
competitors are secondary-heavy, so this stops short of high despite pain
being very strong). **Tension to surface:** V3 has the single strongest pain
signal of all four ideas (3×1.0, undiscounted) paired with essentially zero
search-demand evidence and weak money evidence — people who have this problem
complain loudly inside existing apps, but nobody is shown actively searching
or paying for the specific fix.

---

## V4 — Client-preference matching sold to travel businesses (business)

- **search = 2 × conf 0.8 (med) = 1.60.** Travel Market Report survey:
  advisors rank **researching (38%)**, **customizing itineraries (21%)**,
  **comparing suppliers (20%)**, **managing client communication (20%)** as
  most time-consuming (measured, secondary trade press reporting a named
  survey). Luxury Travel Magazine: discovery conversations for complex trips
  run **"60 to 90 minutes per client"** (estimate, secondary, no sample size
  given). search.md's own confidence: medium — "most concrete, named-source
  numbers in this whole harvest," but no review-platform page was fetched
  directly.
- **spend = 3 × conf 1.0 (treated as high; agent stated "medium-high") = 3.00.**
  Strongest evidence in the entire harvest: **Tern $49/seat/mo (monthly),
  $35/seat/mo (annual)** and **Travefy NTAP $25/month, Premium renews at
  $39/month** — both **fetched directly from the vendors' own pricing
  pages** (measured, primary, tern.travel/pricing and travefy.com/plans/ntap,
  2026-10-03) — and both bracket V4's proposed $30–80/advisor/month almost
  exactly. Job-postings side is weaker: Indeed **"1,305 Travel Advisor"** +
  ZipRecruiter **"1000+"** postings (both broad-title, both blocked on direct
  fetch — "logged as inaccessible for direct verification," secondary only).
  *Judgment call flagged:* spend.md's own label was "medium-high," not a
  clean "high" — rounded up here because the software-spend half is
  primary-fetched and decisive, but the postings half remains unverified
  broad-title matches, not tightly-matched roles.
- **pain = 2 × conf 0.8 (med) = 1.60.** 3–4 distinct recent primary
  complaints, but pain.md flags they are **all reviews of a single vendor**
  (Travefy) across 2 venues: "it can be very time consuming to lay out
  descriptions and attachments just the way I want them for more complex
  itinerary items" (Host Agency Reviews, 2026-06-09). No first-person
  complaint was found describing the upstream pain (hours learning a
  client's taste) independent of one specific tool.
- **competitors = 3 × conf 0.8 (med) = 2.40.** "Crowded-but-weak-incumbents is
  the closest fit" — Travefy (G2 4.5/5 on 22 reviews, Trustpilot "too many
  bugs and difficult to book support sessions"), Tern (**$13M Series A,
  2025-05-17, $17M total raised**, measured primary via vendor's own blog),
  Fora ($78.2M raised Series C, estimate/secondary). **Platform-bundling
  read: NONE found** — "No large consumer platform... was found giving away
  a B2B client-intake-plus-matching-engine... genuine software-category gap."
  The specific "intake + AI matching engine that drafts a proposal" feature
  was not found as a standalone product at either Travefy or Tern — both are
  itinerary/proposal **builders**, not preference-**matching engines** — so
  the matching-specific angle looks more open than the broader advisor-
  software space it sits inside.

**weighted_score = 2.33. Overall confidence: high** (4/4 signals med-or-above,
with the decisive spend signal resting on two directly-fetched primary
vendor pricing pages). **Caveat:** the "high" rating leans partly on rounding
spend.md's own "medium-high" label upward and on competitors.md's weak-
incumbent read being itself medium-confidence — treat the top-line number as
solid-but-not-ironclad, not beyond question.

---

## Ranking

1. **V1 — AI-chat trip planner** — weighted_score 2.58, confidence **high**
2. **V4 — Advisor client-matching (business)** — weighted_score 2.33, confidence **high**
3. **V3 — Recommendations from past trips** — weighted_score 1.12, confidence **med**
4. **V2 — Preference quiz** — weighted_score 0.72, confidence **low**

## Recommendation

**Advance to an opportunity brief: V1 and V4.**

- **V1** has the best-rounded evidence of the set — real pain inside named
  incumbent apps, a direct subscription-price comp (Layla at $9.99/mo), and
  two independently-sourced national surveys showing AI trip-planning
  behaviour already at scale (56% of US travelers, Allianz/Ipsos n=2,001).
  Biggest unknown: **platform-bundling risk is the highest of any candidate**
  — Google, ChatGPT, Kayak, Booking.com, Trip.com and Expedia all now ship a
  free version of the core chat-itinerary feature, and the one standalone
  comp (Layla) was just acquired by Expedia rather than surviving
  independently. A brief should focus on whether a neutral, subscription-
  funded wedge can survive next to loss-leader giants, not on whether demand
  exists (it clearly does).
- **V4** has the single most concrete money evidence in the whole harvest —
  two directly-fetched vendor pricing pages (Tern, Travefy) bracketing the
  proposed price almost exactly — plus a genuine platform-bundling gap (no
  giant offers this). Biggest unknown: the pain evidence is thin and
  single-vendor (all Travefy), and the job-postings counts (Indeed,
  ZipRecruiter) were never independently re-verified, so the buyer-side
  pain and headcount-of-buyers are the two things a brief should test for,
  not the willingness-to-pay-for-software-in-this-category (already proven
  by Tern/Travefy's existence).

**Third candidate worth a lighter-touch brief: V3.** Its pain signal (3×1.0,
undiscounted — the single strongest raw signal of any idea) is real and
on-target, but it rides on almost no search-demand evidence and no direct
pricing comp. A brief here should explicitly test whether the loud in-app
complaints ("it lost my trip history") translate into demand for a
*recommendation* product, or just for better data portability/backup —
those are different products.

**Drop (or deprioritize indefinitely): none need outright dropping, but V2
is the weakest candidate and does not clearly earn further free research
ahead of the other three.** Every signal for V2 is low-confidence or
thin, and the one unambiguous finding — "no incumbent destination-matching
quiz charges consumers directly" — is a direct negative data point against
V2's own consumer money model. The B2B widget-licensing half has no
travel-specific pricing precedent at all (Outgrow and CPL figures are
generic/listicle proxies). If the owner wants to keep V2 alive, the cheapest
next step is not a brief but a narrower question: is there a buyer
(a named travel-media site or DMO) who has actually paid for a licensed
quiz widget — that single fact would move competitors/spend off 0.50 before
investing in a full brief.

## Limitations

- This is Rung-0 **desk evidence** — App Store ratings, review-platform
  snippets, trade-press-reported surveys, and vendor pricing pages. None of
  it is real paid behaviour data for *these specific products*; it is all
  proxy/adjacent evidence (incumbents' prices, incumbents' complaints,
  incumbents' funding), which is why even the "high confidence" ideas (V1,
  V4) are proxy-strong, not validated.
- Several figures across all four files are explicitly "estimate" or
  "secondary" because primary pages were blocked (403/429) during
  harvesting: Reddit, G2, Capterra, Trustpilot, ASTA's PDF, Indeed,
  ZipRecruiter, TravelAge West, Travel Weekly, Hopper's Business of Apps
  page, Mindtrip's Crunchbase/PhocusWire pages, and Tripadvisor's Q2 2026 IR
  release all could not be fetched directly in this harvest. Where a number
  from one of those pages is used here, it is one hop removed from primary
  source, exactly as flagged in the originating file.
- **Shakiest individual scores:** V2's competitors score (1×0.5) and V3's
  search score (0×0.5) both rest on genuine gaps/negative findings rather
  than on a bounded "we checked and found nothing" — it is possible a better
  search index (working Reddit/Trends access) would move these. V4's spend
  score required rounding the source file's own "medium-high" label up to a
  clean "high" tier; a stricter reading would move V4's weighted_score down
  to roughly 2.05–2.10 instead of 2.33, which would not change the ranking
  but narrows V4's lead over V3.
- No Google Trends data was obtained for any candidate in search.md — every
  "rising" / "flat" trend direction in this report is an inference from
  review-count or competitor-count growth, never a measured slope.
