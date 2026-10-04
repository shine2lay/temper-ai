# Spend & behaviour signal — travel discovery-by-preference (V1–V4)

Methodology note: 29 WebSearches and 15 WebFetches were run. Several primary pages blocked
automated fetches (403/429: ASTA fact sheet rendered as unreadable binary, Fora's own commission
page, TravelAge West, Travel Weekly, ZipRecruiter, Indeed, TripIt pricing page, Wanderlog pricing
page, Marriott's own press release). Per instructions these were logged as inaccessible and not
worked around; where a trade-press or aggregator page reports the same primary figure, it is used
and tagged "secondary," naming the primary source it is reporting on.

---

## V1 — AI-chat trip planner for leisure travelers (CONSUMER)

Target user is the traveler, who pays personally or not at all; no job postings apply.

### Money already paid for this job (incumbent consumer products)
- **Layla (AI trip planner, owned by Expedia per secondary reviews): $9.99/month or $49.99/year.**
  Fetched directly from the app's own App Store listing.
  URL: https://apps.apple.com/us/app/layla-ai-trip-planner/id6758730467 — 2026-10-03
  Quote: "Monthly subscription: $9.99 ... Yearly subscription: $49.99" (rendered from the iOS app page)
  measured | primary (store listing)
- **TripIt Pro: $49/year**, a comparable "planning/travel utility" subscription travelers already
  pay for (not AI-matching, but the closest priced consumer-travel-app comp).
  URL: https://monkeyeatingmango.com/blog/tripit-pricing-2026/ — 2026-10-03 (tripit.com/pro itself
  returned no readable pricing text on fetch, logged as inaccessible for pricing detail)
  Quote: "TripIt Pro costs US$49 for an annual subscription."
  measured | secondary (reporting TripIt's own listed price)
- **Mindtrip is free with no subscription tier**; monetizes only via booking commission with
  partners (Priceline, Viator). This is evidence AGAINST a standalone subscription being the norm
  for AI trip planners today.
  URL: https://www.datastudios.org/post/mindtrip-ai-travel-planning-in-chat-booking-and-pricing — 2026-10-03
  Quote: "Mindtrip monetizes on a pay-as-you-book basis through partners like Priceline and Viator:
  you plan for free, and Mindtrip earns a commission only if you book through it."
  measured | secondary (vendor-reported business model, not an official Mindtrip pricing page — that page sits behind a login wall, logged inaccessible)
- **What consumers pay humans for the same job (trip-planning fee):** advisor planning fees
  cluster at $50–$150 for most clients, with an average fee near $1,200 per trip among advisors
  who charge, per TravelAge West/Travel Weekly reporting (both publishers' own pages 403'd on
  direct fetch).
  URL: https://www.travelagewest.com/Industry-Insight/Business-Features/travel-agent-fees — 2026-10-03 (inaccessible, 403)
  Quote (via search-engine cache of the page): "Most advisors (54%) make between $50 and $150 on
  fees per client ... The average fee per trip for 2025 was just under $1,200 among advisors who
  successfully charge fees."
  measured | secondary (listicle-adjacent trade coverage; could not confirm on the publisher's own page)

### Money that flows through it (affiliate/commission terms)
- **Booking.com affiliate commission: 25%–40% of Booking's own commission, tiered by volume**
  (25% at 0–50 stayed reservations up to 40% at 501+), 30-day cookie, pay-per-stay, minimum
  payout €100. Not fetched directly from partner.booking.com (not attempted at the authenticated
  partner portal); sourced from affiliate-directory aggregation of the programme's published terms.
  URL: https://getlasso.co/affiliate/booking/ — 2026-10-03
  Quote: "The affiliate partner commission on Booking.com ranges from 25% to 40% across four
  performance tiers: 25% for 0-50 stayed reservations, 30% for 51-150, 35% for 151-500, and 40%
  for 501+ stayed reservations."
  measured | secondary (aggregator reporting Booking's own terms page)
- **Expedia TAAP commission: tiered, roughly 3.5%–13% on hotels** depending on agency tier (Basic
  to Premium Plus), paid at completed stay with clawback on cancellation.
  URL: https://track360.io/blog/expedia-affiliate-program-ean-taap-operator-teardown-2026 — 2026-10-03
  Quote: "Properties – Premium Plus: 11-13%, Properties – Premium: 9-11%, Properties – Basic Plus:
  6.5-8.5%, and Properties – Basic: 3.5-5% depending on agency status level."
  measured | secondary (trade teardown of Expedia's own incentive-plan structure)
- **GetYourGuide affiliate: ~8% commission, 30-day cookie window**, no minimum payout.
  URL: https://getlasso.co/affiliate/getyourguide-content-partnerships/ — 2026-10-03
  Quote: "GetYourGuide affiliates can earn up to 8% commission every time their audience books
  through their links... Every purchase made within 30 days of clicking your link is attributed to you."
  measured | secondary (aggregator reporting GYG's own programme terms)
- **Viator affiliate: 8% commission, 30-day cookie, $50 minimum payout.**
  URL: https://phptravels.com/blog/how-to-earn-with-the-viator-affiliate-program — 2026-10-03
  Quote: "The standard commission rate for the Viator Affiliate Program is 8% on all experiences
  booked through your affiliate link."
  measured | secondary

### Behaviour at scale
- **56% of US travelers now use AI for trip planning (up from 43% the year before)**, and **37% of
  Americans planning summer 2026 travel are using AI to help plan**, per Allianz Partners' Global
  Travel Confidence Index (with Ipsos), n=2,001 US adults, fielded Mar 20–Apr 14, 2026.
  URL: https://www.hoteldive.com/news/artificial-intelligence-mainstream-travel-planning-tool/826002/ — 2026-10-03
  Quote: "More than one-third (37%) of Americans planning to travel this summer are using AI to
  help them plan their vacations."
  measured | secondary (trade press reporting Allianz Partners' own named, dated survey)
- **AAA Consumer Pulse survey, n=5,000, fielded Jan 26–Feb 5, 2026**: 39% of Americans plan more
  vacations in 2026 than 2025; 58% expect to take multiple trips; separately 81% say they find
  travel agents valuable (showing the human alternative still carries weight).
  URL: https://newsroom.acg.aaa.com/aaa-2026-vacation-intentions-surge/ — 2026-10-03
  Quote: "conducted online among 5,000 residents living in The Auto Club Group territory from
  January 26 – February 5, 2026" / "81% of Americans find travel agents valuable"
  measured | primary (AAA's own newsroom release)
- **Incumbent install/engagement scale (App Store, fetched directly, 2026-10-03):**
  - Wanderlog: 4.9★, "36K Ratings" — https://apps.apple.com/us/app/wanderlog-travel-planner/id1476732439 — measured | primary
  - Mindtrip: 4.7★, "816 Ratings" — https://apps.apple.com/us/app/mindtrip-ai-travel-companion/id6503107567 — measured | primary
  - Layla: 4.7★, 191 ratings — https://apps.apple.com/us/app/layla-ai-trip-planner/id6758730467 — measured | primary
  (Rating counts, not install bands — Apple does not publish install bands on these listings — so
  these are a lower bound on an engaged user base, not a size estimate.)

**Confidence: medium.** The target behaviour (AI-assisted trip planning) is large and growing per
two independently named, dated, reasonably sized US surveys, and a direct incumbent (Layla) charges
almost exactly the proposed $5–10/month. But no incumbent discloses paying-subscriber counts or
AI-planner-specific revenue, and the affiliate-term figures are all aggregator-sourced rather than
fetched from the programmes' own (gated) partner portals.

---

## V2 — Preference quiz that matches travelers to destinations (CONSUMER + licensed widget)

Target user is primarily the traveler (consumer); secondarily travel media/sellers who would
license the quiz. Consumer job-postings do not apply; for the widget-licensing line there is no
single "job posting" either since it is a licensing/B2B2C product, not a role — evidence here is
pricing comparables and lead economics.

### Money already paid for this job
- **No incumbent destination-matching quiz charges consumers directly.** Every example found
  (DestList, Voyasee, TripMemo, Voyaige) is a free, presumably ad/affiliate-supported lead-gen tool,
  not a paid product. This is a direct (negative) data point against a standalone consumer paywall
  for this specific wedge.
  URL: https://www.destlist.com/vacation-decision-tool ; https://voyasee.com/destination-quiz/ ;
  https://voyaige.to/tools/where-should-i-go — 2026-10-03
  measured (free tier is observable) | secondary/vendor (own product pages, read via search snippet, not independently fetched)

### Money that flows through it
- Same affiliate commission structure travelers' bookings would carry applies here as in V1
  (Booking.com 25–40% of Booking's commission; Expedia TAAP ~3.5–13%; GetYourGuide and Viator ~8%
  each) — see V1 section for sourced quotes; not re-quoted to avoid duplication.
- **Widget-licensing price comparable (not travel-specific):** Outgrow, a general interactive
  quiz/calculator SaaS that media sites license to embed lead-gen quizzes, prices from $22/month
  (Freelancer) up to $720/month (Business, annual-equivalent $600/month), with the
  white-label/custom-domain tier starting around $95–115/month.
  URL: https://www.trustradius.com/products/outgrow/pricing — 2026-10-03
  Quote: "Outgrow offers a Freelancer Plan at $22/month ... an Essentials Plan at $115/month, a
  Business Plan at $720/month."
  measured | vendor (Outgrow's own listed pricing, not travel-specific — used only as a generic
  proxy for what media sites pay to license an embeddable quiz, not evidence of travel-quiz demand)
- **DMO/tour-operator lead costs (weak, flagged):** DMOs reportedly pay $3–$30 per lead and tour
  operators $10–$50 per lead; broader travel-industry paid-search CPL is cited at ~$74–$106.
  URL: https://www.causalfunnel.com/blog/what-is-cost-per-lead-cpl-for-travel-businesses-complete-2025-guide/ — 2026-10-03
  Quote: "the average cost per lead in travel and hospitality is pegged at $74."
  estimate | listicle (SEO cost-per-lead roundup; no named survey or primary source identified — treat as directional only, not load-bearing)

### Behaviour at scale
- No direct survey was found quantifying what share of travelers "don't know where to go" (the
  core problem V2 targets) — this is an honest gap, not a fabricated figure.
- General addressable pool: AAA's 2026 survey (above) shows 58% of Americans expect multiple
  trips in 2026 and 39% plan more vacations than last year — i.e., a large population making
  repeated destination choices, which is the precondition for a destination-matching tool to matter,
  though it does not measure quiz-specific intent.
  (same URL/quote as V1 AAA entry) measured | primary

**Confidence: low.** The clearest, most directly relevant observation — that every existing
destination-matching quiz is free — cuts against a consumer paywall. The widget-licensing line has
no travel-specific pricing precedent at all; the Outgrow comparison and the CPL figures are the
weakest tier of evidence in this whole report (vendor/listicle), and the core behavioural claim
("travelers don't know where to go") has no measured survey behind it.

---

## V3 — Recommendations from a traveler's own past trips (CONSUMER)

Target user: frequent US leisure travelers (3+ trips/year) and loyalty-program members.

### Money already paid for this job
- Closest priced comparables are the same freemium travel-planning subscriptions as V1/V3's
  proposed $5–10/mo or ~$50/yr: **Wanderlog Pro ≈ $39.99/year** and **TripIt Pro = $49/year**
  (TripIt figure fetched-confirmed path failed directly; see V1 sourcing for both).
  URL: https://monkeyeatingmango.com/blog/wanderlog-pricing-2026/ — 2026-10-03
  Quote: "Wanderlog Pro Cost 2026: $39.99/yr"
  measured | secondary (wanderlog.com/pricing itself 404'd on direct fetch, logged inaccessible)
  No incumbent specifically monetizes "recommendations from your own past trips" as a standalone
  paid feature today — this is inferred from adjacent subscription pricing, not a direct comp.

### Money that flows through it
- Same affiliate commission terms as V1 apply to any bookings a past-trip-based recommendation
  would steer (Booking.com 25–40%; Expedia TAAP ~3.5–13%; GetYourGuide/Viator ~8%) — see V1 for
  sourced quotes.

### Behaviour at scale
- **Loyalty program membership is very large**, which is the raw material V3 would mine:
  - Marriott Bonvoy: "more than 295 million members" as of Q2 2026 close.
    URL: https://pulse2.com/marriott-bonvoy-membership-tops-295-million-as-credit-card-fees-help-franchise-revenue-rise-19/ — 2026-10-03
    Quote: "Marriott Bonvoy Membership Tops 295 Million"
    measured | secondary (reporting Marriott's own Q2 2026 earnings release; the release itself,
    https://marriott.gcs-web.com/news-releases/..., timed out on direct fetch — logged inaccessible)
  - Hilton Honors: "260 million members" as of Q2 2026, "up 15% year over year."
    URL: https://www.businesswire.com/news/home/20260728481839/en/Hilton-Reports-Second-Quarter-Results — 2026-10-03 (press release syndication; not independently re-fetched, figure taken from search synthesis)
    Quote: "Hilton Honors membership grew 15% year-over-year to 260 million members"
    measured | secondary (reporting Hilton's own Q2 2026 results release)
  - ~52% of Americans are enrolled in at least one hotel loyalty program; ~60–62% in an airline
    program.
    URL: https://blog.accessdevelopment.com/the-ultimate-collection-of-loyalty-statistics — 2026-10-03
    Quote: "52% of Americans are enrolled in at least one hotel loyalty program."
    estimate | listicle (statistics-roundup page; underlying survey not named — weak, flagged)
- **Frequent-traveler base:** a Phocuswright US Consumer Travel Report figure cited elsewhere puts
  average US traveler trip frequency at 3.2 trips in the past 12 months; a separate 2026 survey
  states 53% of Americans plan 3+ trips in 2026.
  URL: https://www.wandrly.app/blog/us-travel-statistics — 2026-10-03
  Quote: "average of 3.2 trips taken in the past 12 months for U.S. travelers according to the
  Phocuswright report"
  estimate/measured mixed | secondary (listicle citing a named primary research firm's report,
  report itself not independently located/fetched — Phocuswright reports are typically paywalled)

**Confidence: medium.** The behavioural base (hundreds of millions of loyalty memberships, a
majority of Americans taking multiple trips a year) is large and reasonably well evidenced, even
though several supporting figures are secondary citations of primary releases rather than
directly fetched. The money side is the weak link: there is no incumbent product that prices
"recommendations from your own past trips" specifically, so the $5–10/mo or $50/yr figure is only
supported by adjacent-category pricing (Wanderlog, TripIt), not a direct comparable.

---

## V4 — Client-preference matching sold to travel businesses (BUSINESS)

Target user: independent travel advisors/host agencies first, then tour operators/hotel
groups/DMOs. Job-postings + software-spend method applies.

### Postings (role exists, approximate scale)
- Indeed shows **1,305 results** for "Travel Advisor" and **637** for "Travel Planner" per
  search-engine-rendered page text; direct fetch of indeed.com was blocked (403/429) both times
  attempted, so these counts could not be independently re-confirmed on the live page and are
  logged as inaccessible for direct verification.
  URL: https://www.indeed.com/q-Travel-Advisor-jobs.html — 2026-10-03 (inaccessible to WebFetch; count read from search engine's cached rendering)
  Quote: "1,305 Travel Advisor jobs available on Indeed.com"
  estimate | secondary (board's own listing count, but not independently re-verified on-page — treat as directional)
- ZipRecruiter shows **"1000+" Travel Advisor jobs** nationally and **814** for "Remote Travel
  Advisor"; average pay cited on-page as "$48,925.00" per year, range "$39,500.00–$55,000.00."
  Direct fetch also blocked (403).
  URL: https://www.ziprecruiter.com/Jobs/Travel-Advisor?version=next — 2026-10-03 (inaccessible to WebFetch)
  Quote: "the average yearly pay for travel advisor in the United States is $48,925.00... Most
  workers in this role earn between $39,500.00 and $55,000.00 per year"
  estimate | secondary
- No individual verbatim job-posting task lines were obtainable (both boards blocked direct
  fetch, and search snippets did not surface individual posting text) — this is an honest gap
  against the "2-3 example postings with a verbatim task line" requirement.
- **Market size context (trade association, not independently fetched — PDF returned unreadable
  binary on fetch):** ASTA states it represents "310,000 individual travel advisors and 655
  international travel supplier companies, with 9,500 domestic travel agencies" (figure read via
  search synthesis of ASTA's own fact sheet, not confirmed from the rendered PDF itself).
  URL: https://www.asta.org/Common/Uploaded%20files/ASTA/Advocacy/2025%20ASTA%20Fact%20Sheet.pdf — 2026-10-03 (fetched but returned unreadable PDF binary; figure not independently confirmed from readable text)
  estimate | secondary (association's own self-description, could not verify verbatim from the PDF)

### Software spend already in place (this is the strongest evidence in the whole report)
- **Tern for Advisors — fetched directly from tern.travel/pricing, 2026-10-03:**
  Solo advisor: "$49/seat/mo" monthly, "$35/seat/mo" quarterly/annual. Agency tiers (3+ seats) run
  roughly $22–33/seat/month depending on size and billing cadence. An optional "Tern Pro" AI add-on
  runs $19–$149/month.
  URL: https://tern.travel/pricing — 2026-10-03
  Quote: "$49/seat/mo" (monthly) / "$35/seat/mo" (quarterly, labeled BEST VALUE)
  measured | primary (fetched directly from the vendor's own pricing page)
- **Travefy — fetched directly from travefy.com/plans/ntap, 2026-10-03:**
  New Travel Agent Program (first year, for advisors in the industry <12 months): "$25/month"
  billed annually; thereafter the Premium plan renews at "$39 per month paid annually." Standard
  entry plan elsewhere cited at $39/month ($31/month annual).
  URL: https://travefy.com/plans/ntap — 2026-10-03
  Quote: "$25/month" (NTAP first year) / "$39 per month paid annually" (Premium renewal)
  measured | primary (fetched directly)
- **Fora — membership fee and commission split** (direct fetch of foratravel.com's own article
  returned 429 twice; figures below are from search-engine synthesis of that same primary page,
  not independently re-confirmed by WebFetch):
  Membership "$299 per year or $99 per quarter"; commission split starts 70/30 (advisor/Fora),
  moves to 80/20 after $300,000 in commissionable travel in a calendar year, and 90/10 at $2
  million.
  URL: https://www.foratravel.com/help/en/articles/14303041-how-commission-works-at-fora — 2026-10-03 (inaccessible to WebFetch, 429)
  Quote (via search cache): "Fora's starting split is 70/30... The split advances to 80/20 after
  $300,000 in commissionable travel in a calendar year, and advisors reach 90/10 at $2 million in
  bookings. ... Fora membership is $299 per year or $99 per quarter."
  measured | secondary (could not independently re-fetch the vendor's own page, logged inaccessible)
- These three incumbents bracket the proposed V4 price (~$30–80/advisor/month) closely: Tern's
  $35–49/seat/month and Travefy's $25–39/month sit inside that exact band; Fora's $99/quarter
  membership (~$33/month) is also inside it.

### Behaviour / planning-fee context (advisors already charge clients, evidence of willingness to spend on tools that save time)
- 54–62% of advisors charge some kind of planning fee (varying by survey), with a typical fee of
  $50–$150 per client and an average of ~$1,200/trip among fee-charging advisors in 2025. See V1
  section for the sourced quote (TravelAge West/Travel Weekly reporting, both publisher pages
  403'd on direct fetch; evidence logged as secondary/trade-press there).

**Confidence: medium-high.** This is the best-evidenced candidate in the set: two of the three
software comparables (Tern, Travefy) were confirmed by direct fetch of the vendor's own pricing
page, both bracketing the proposed $30–80/advisor/month price almost exactly, which is strong
proof that travel-selling businesses already pay recurring per-seat software fees in this range
for adjacent (CRM/itinerary/proposal) tools. The weak points are the job-board postings counts
(both Indeed and ZipRecruiter blocked direct verification) and the absence of verbatim example
postings, plus the ASTA market-size figure not being independently confirmed from the readable
PDF text.
