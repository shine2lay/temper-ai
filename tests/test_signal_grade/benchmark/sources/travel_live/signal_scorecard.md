# Signal Scorecard — Travel Discovery by Preference (V1–V4)

Rung 0 synthesis. Inputs: `state/signal/search.md`, `state/signal/jobs.md`,
`state/signal/pain.md`, `state/signal/competitors.md`. No new research — every
figure/quote/URL below is carried from those four files.

Weights (money > behavior > words): **jobs .35, competitors .30, pain .20, search .15**.
Confidence discount: high=1.0, med=0.8, low=0.5. `discounted = raw_score × confidence_mult`.

---

## SCORECARD TABLE

| Idea | search (raw×conf=disc) | jobs (raw×conf=disc) | pain (raw×conf=disc) | competitors (raw×conf=disc) | **weighted_score** | **overall confidence** |
|---|---|---|---|---|---|---|
| V1 — AI-chat trip planner | 2×low(0.5)=1.0 | 3×med(0.8)=2.4 | 2×med(0.8)=1.6 | 3×high(1.0)=3.0 | **2.21** | **high** |
| V4 — Client-preference matching (B2B) | 1×low(0.5)=0.5 | 2×low(0.5)=1.0 | 1×low(0.5)=0.5 | 3×med(0.8)=2.4 | **1.25** | **low** |
| V3 — Recs from past trips | 1×low(0.5)=0.5 | 1×low(0.5)=0.5 | 1×low(0.5)=0.5 | 1×med(0.8)=0.8 | **0.59** | **low** |
| V2 — Destination-match quiz | 1×low(0.5)=0.5 | 1×low(0.5)=0.5 | 2×med(0.8)=1.6 | 0×low(0.5)=0.0 | **0.57** | **low** |

Arithmetic (weights search .15 / jobs .35 / pain .20 / competitors .30):
- V1: .15×1.0 + .35×2.4 + .20×1.6 + .30×3.0 = 0.15+0.84+0.32+0.90 = **2.21**
- V4: .15×0.5 + .35×1.0 + .20×0.5 + .30×2.4 = 0.075+0.35+0.10+0.72 = **1.245 ≈ 1.25**
- V3: .15×0.5 + .35×0.5 + .20×0.5 + .30×0.8 = 0.075+0.175+0.10+0.24 = **0.59**
- V2: .15×0.5 + .35×0.5 + .20×1.6 + .30×0.0 = 0.075+0.175+0.32+0.00 = **0.57**

---

## PER-IDEA DETAIL

### V1 — AI-chat trip planner for leisure travelers (consumer)

- **search — score 2, confidence LOW → 1.0.** search.md reports Google's own page
  showing "3 in 4 users say AI Mode/AI Overviews help them decide faster" (Google-commissioned
  Ipsos, Dec 2025) and "53% of travellers regularly use Google Search" for travel
  (business.google.com/en-all/think/search-and-video/ai-travel-marketing-search-trends/) —
  but the more dramatic "+350%/+315% search growth" figures could **not** be
  reproduced on that same primary page and are flagged vendor/secondary. The one
  solid, independently-measured datum is Wanderlog's install base (1M+ Play
  installs, ~36.5K reviews, 4.7★). Raw score 2 (real community, murky trend);
  confidence forced to low because the headline "rising" claim driving that score
  is vendor-sourced and unverified (search.md's own caveat: this category is
  "capped at low or low-med confidence").
- **jobs — score 3, confidence MED → 2.4.** jobs.md: LinkedIn render shows "5,000+
  Travel Advisor" and "4,000+ Travel Consultant" jobs in the US (measured, primary,
  2026-10-03), with salary bands $35k–$100k+ (luxury $75k+) recurring across
  snapshots — thousands of tightly-matched, salaried postings for the exact
  hand-done task (interview traveler → build itinerary). Confidence explicitly
  "medium" per jobs.md: real and well-populated, but magnitude is volatile (Indeed
  blocked at HTTP 403; LinkedIn's own snapshot metadata showed 52,000+ for the
  same query — a 10x internal discrepancy, logged not resolved).
- **pain — score 2, confidence MED → 1.6.** pain.md: 6 distinct complaints across
  2 venues (App Store + HN), 2025-06 to 2026-07. Strongest: Layla, 1★,
  "constantly recommending places that are permanently closed... does not follow
  directions" (2026-07-05); Wanderlog, 2★, "the inability to search in the
  'explore' area... they'll recommend only their top restaurants regardless [of
  area]" (2026-07-14); HN first-person, "I would really like a travel planner
  that actually helps me decide where to travel depending on my situation..."
  (codegeek, 2025-12-11). Confidence med per pain.md: 2 of 6 quotes are vendor
  Show-HN self-pitches, and only 2 venues total.
- **competitors — score 3, confidence HIGH → 3.0.** competitors.md: Mindtrip
  ($19M total — $7M seed Sep 2023 + $12M Series A Sep 2024, Costanoa/Forerunner;
  816 iOS ratings, 4.7★), Layla (**acquired by Expedia Group, late Jul 2026**;
  482 Play reviews + 91 Trustpilot, 4.7/4.2★), Wanderlog ($1.65M, YC S19; 36K
  iOS ratings, 4.9★) — plus every major OTA (Expedia Romie, Booking.com AI Trip
  Planner, Trip.com TripGenie) and ChatGPT building the identical wedge. The
  Expedia-acquires-Layla event is real-money, independently reported
  (phocuswire.com, endlesstravelplans.com). competitors.md rates this "high"
  confidence: multiple independently-corroborated review counts, press-sourced
  funding, and an actual acquisition.
- **weighted_score = 2.21, overall confidence = HIGH** (jobs=med, pain=med,
  competitors=high → ≥3 signals med/high with primary sources; search alone
  being low doesn't trigger the auto-low rule).

### V2 — Preference quiz matching travelers to destinations (consumer / widget)

- **search — score 1, confidence LOW → 0.5.** search.md: the query is heavily
  served already by a long-standing listicle-quiz genre (BuzzFeed, Refinery29,
  evergreen for years) and Hotels.com already runs the *identical* consumer wedge
  at scale ("Destination Comparison" tool, hotels.com/why/destination-comparison).
  No volume/trend number obtained (Google Trends didn't render). search.md:
  "Confidence: low" — flat/saturated, not rising.
- **jobs — score 1, confidence LOW → 0.5.** jobs.md: Indeed snapshots of
  "destination specialist" (602/564/122, all HTTP-403-blocked estimates);
  LinkedIn's "10,000+ Destination Specialist" count is explicitly flagged as
  **noisy/overbroad** — example postings pulled were "Guest Experience
  Specialist" (private-jet ground staff) and "Business Travel Specialist"
  (corporate booking), neither doing destination-matching. jobs.md: "no clean
  example posting... describes the V2 task as its primary duty"; confidence
  "low."
- **pain — score 2, confidence MED → 1.6.** pain.md: 5 distinct complaints, 2
  venues. Two independent, non-vendor, first-person quotes: "I've been going
  round in circles for 3 days trying to decide where to go travelling..."
  (octo888, HN, 2025-08-31) and the same codegeek quote as V1 (2025-12-11, "help
  me decide where to travel depending on my situation... then show me options").
  Plus a direct tool-gripe on the one incumbent feature closest to this wedge:
  Kayak Explore, 1★, "I would set my budget and it would show options on the
  map… but wouldn't show the actual flights that matched the price shown"
  (2025-11-03). pain.md: "Confidence: med."
  **Tension flagged:** pain signal (2) is stronger than both search (1) and
  competitors (0) for this idea — real people voice this exact "can't decide
  where to go" frustration, but no one has built a funded, reviewed product to
  capture it.
- **competitors — score 0, confidence LOW → 0.0.** competitors.md found no
  funded/reviewed incumbent at all — only a long tail of small SEO-affiliate
  sites (Voyasee, DestList, WhichAtlas, LocalsInsider) with no app-store or
  review-platform presence, so no verifiable review/pricing/funding evidence
  exists either way. This is the rubric's literal "0 = nothing found (and you
  cannot tell if that's open or dead)" case — competitors.md says exactly this:
  "absence of incumbents could mean thin demand or a genuine gap... rests on
  absence of evidence." Confidence low.
- **weighted_score = 0.57, overall confidence = LOW** (jobs AND competitors both
  low-conf → auto-low).

### V3 — Recommendations from a traveler's own past trips (consumer)

- **search — score 1, confidence LOW → 0.5.** search.md: a handful of small,
  recent apps (Travel Mind, Travel Mate AI, Trippin, Next Trip AI, Tripify) are
  trying this wedge but none has an established community footprint. The one
  large adjacent community, FlyerTalk ("889,211 members and 37,236,570 posts"),
  is focused on manual miles/points optimization, not taste-based recommendation
  — off-target. No "I wish my app knew my taste"-type thread surfaced anywhere.
  search.md: "Confidence: low... thinnest signal of the four."
- **jobs — score 1, confidence LOW → 0.5.** jobs.md: no distinct job title
  exists for this task. ZipRecruiter "Travel Concierge" (622 jobs, $14–72/hr,
  estimate) and LinkedIn "8,000+ Travel Concierge" (measured) both pull
  *corporate VIP-servicing* examples (BCD Travel, ADTRAV), not past-trip
  personalization. jobs.md: "no posting found... that names the specific V3 task
  as a job duty... looks like a product feature, not a role"; confidence "low."
- **pain — score 1, confidence LOW → 0.5.** pain.md: only 2 distinct complaints,
  1 venue (App Store, TripIt). Both are adjacent, not direct: "TripIt killed all
  third-party sync... My travel history is now hostage to a GDPR request"
  (ShadowfaxCA, 1★, 2026-09-17) and "lost all my past trip history for 2025 and
  2026" (Hobbyist99, 3★, 2026-08-25) — these show travelers value trip history
  and get angry when it's taken away, but no one states the V3 problem
  ("my app doesn't learn from my past trips") directly. pain.md: "Confidence:
  low... sparse/mostly adjacent."
- **competitors — score 1, confidence MED → 0.8.** competitors.md: the
  *data-layer* is crowded and proven — Polarsteps (9.7K iOS + 195K Play ratings,
  4.9/4.7★, "10 million travelers" claimed-unverified), TripIt (307K iOS
  ratings 4.8★, but 1.7★ on Trustpilot — flagged as platform-selection-bias),
  Wanderlog (same as V1) — but **no product closes the loop** from past trips to
  a next-destination recommendation. competitors.md: "clearest 'untapped, not
  absent' case... genuinely no visibility into whether anyone has tried and
  failed at the recommendation layer (survivorship)." Ambiguous → score 1,
  confidence med (stated explicitly).
- **weighted_score = 0.59, overall confidence = LOW** (jobs low-conf → auto-low).
  **Tension flagged:** competitors evidence (crowded, proven data habit) reads
  more promising in prose than its numeric score suggests, because the gap is a
  missing *feature* on top of large existing audiences, not an open/dead market
  verdict — but jobs and pain give almost no independent confirmation that
  travelers feel this specific problem, so the score stays low.

### V4 — Client-preference matching sold to travel businesses (B2B)

- **search — score 1, confidence LOW → 0.5.** search.md: advisor population is
  growing (see jobs/HAR below) but no evidence of rising *search* interest in
  "client-matching" specifically — advisors search broadly for "travel agency
  software." The one easily-measured advisor community, r/travelagent, is tiny
  ("~2,642 members" per reddapi.dev vs. r/travel's "14,424,720" — a
  ~5,000x gap); Facebook groups are larger but unmeasured ("~51,000 members" in
  the largest advisor FB group, travelresearchonline.com, 2025-10). search.md:
  "Confidence: low-med" — downgraded to low here because the wedge is already a
  checkbox feature inside reviewed incumbents (Travefy, Tern), so most search
  demand likely routes to broad "best agency software" queries, not this wedge.
- **jobs — score 2, confidence LOW → 1.0.** jobs.md: reuses V1's Travel
  Advisor/Consultant counts (LinkedIn 4,000–5,000+, measured) as the seat base
  V4 would sell into, plus BLS's 61,500 national travel-agent headcount
  (measured, primary, flat growth) as a ceiling. But the titles specific to
  V4's actual wedge are noisy: "Proposal Coordinator" (846/800, estimate) is
  explicitly flagged as **not travel-specific** (spans construction, SaaS,
  government contracting), and "Group Tour Coordinator" (1,224, estimate) is the
  cleanest travel-specific match but thin. jobs.md: "medium for the
  advisor-seat-count portion... low for the proposal-coordinator/DMO portion" —
  since the V4-specific slice is the weaker half, confidence is taken as low here.
- **pain — score 1, confidence LOW → 0.5.** pain.md: only 1 quotable, on-target
  complaint found in the entire search — a Travefy review calling manual
  itinerary-layout work time-consuming (Desiree Dantona, hostagencyreviews.com,
  2026-06-09) — and even that is about proposal *layout*, not the core V4 claim
  (hours spent learning a client's taste). pain.md: "Confidence: low... genuinely
  sparse: the target users... mostly aren't present in the open, automatable
  sources this task can reach" (real venues are closed Facebook groups/intranets).
- **competitors — score 3, confidence MED → 2.4.** competitors.md: advisor
  software is real, paid and reviewed — Travefy ($31–59/mo, 20 Capterra reviews,
  4.5★), Tern ($35–49/seat/mo, volume discounts to $25/seat/mo), and critically
  Fora Travel (**$60M Series B/C** — Thrive Capital, Insight Partners, Forerunner,
  Heartcore; ~200 employees; 121 reviews). None of the three has built the
  specific AI-intake-to-matched-proposal feature by name. competitors.md's own
  framing — "**Crowded-but-weak-on-the-specific-wedge**" — is close to a literal
  match for the rubric's "crowded-with-weak-incumbents (a clear wedge)" tier,
  backed by real funding/pricing/review evidence, hence score 3; confidence
  "med" per the file (solid on named incumbents, lower on whether the exact
  feature already exists unsurfaced).
- **weighted_score = 1.25, overall confidence = LOW** (jobs low-conf → auto-low).
  **PROMISING-BUT-UNPROVEN flag:** 58% of V4's weighted score (0.72 of 1.25)
  comes from the competitors signal alone, while the other three signals
  (search, jobs, pain) are all low-confidence and thin — in particular pain.md
  found almost no first-person advisor complaints at all because advisors
  cluster in closed Facebook groups/intranets this harvest couldn't reach. The
  score looks respectable on paper but rests on one money-adjacent signal
  (funded incumbents + real pricing) with the behavioral and jobs evidence
  underneath it largely unverified.

---

## RANKING

1. **V1 — AI-chat trip planner** — weighted_score **2.21**, confidence **high**
2. **V4 — Client-preference matching (B2B)** — weighted_score **1.25**, confidence **low** (promising-but-unproven, see flag above)
3. **V3 — Recommendations from past trips** — weighted_score **0.59**, confidence **low**
4. **V2 — Destination-match quiz** — weighted_score **0.57**, confidence **low**

(V3 vs V2 tie-break not needed — scores differ; both low-confidence and close,
driven by opposite profiles: V2 has decent pain (2) but zero competitor signal;
V3 has weak everything except an ambiguous-but-real adjacent competitor base.)

---

## RECOMMENDATION

**Advance V1 to Rung 1 (paid validation).** It is the only idea with high
overall confidence: real paid budget for the manual task (LinkedIn measured
4,000–5,000+ Travel Advisor/Consultant jobs, $35k–$100k+ salary bands), a
crowded-and-funded competitive field with a real liquidity event (Expedia
acquiring Layla, Jul 2026; Mindtrip's $19M raise), and matching first-person
complaints about exactly the generic/wrong-recommendation problem the wedge
targets (Layla "recommending places that are permanently closed," Wanderlog
"only their top restaurants regardless [of area]"). **Biggest remaining
unknown:** differentiation against free OTA-bundled AI assistants (Expedia
Romie, Booking.com's planner, ChatGPT) that are zero-marginal-cost add-ons to
platforms with existing booking funnels — competitors.md flags this explicitly
as the hard part, not whether the category exists.

**Conditionally advance V4 as a #2 candidate, but only after a cheap gut-check,
not straight into paid validation.** Its score is pulled up almost entirely by
one signal — funded, reviewed B2B incumbents (Fora's $60M Series B/C, Travefy/
Tern's confirmed per-seat pricing) — while jobs and pain evidence specific to
the actual wedge (client-preference matching, as opposed to generic advisor
software) are both thin and low-confidence. Before spending paid-validation
budget: run a handful of direct interviews with independent advisors (closed
Facebook groups — "Luxury Travel Social Media & Marketing Strategies," ~51,000
members — are where pain.md and search.md both note the real conversation is
happening, out of this harvest's reach) to check whether "hours learning a
client's taste" is actually a felt, nameable pain, not just an inferred one.

**Drop V2.** It is the only candidate with a competitors score of 0 — not "low
evidence found," but *no funded, reviewed incumbent found at all*, which
search.md and competitors.md both attribute ambiguously to either thin demand
or a genuine gap; there is no budget signal (jobs score 1, noisy) to resolve
that ambiguity in V2's favor, and the category itself is a saturated,
multi-year-old SEO-listicle genre with an OTA (Hotels.com) already running the
identical wedge at distribution V2 wouldn't have.

**V3 is not recommended to advance as a standalone idea**, but its most solid
finding — a crowded, proven adjacent data layer (Polarsteps, TripIt, Wanderlog
all hold large, well-reviewed past-trip-history user bases) with no
recommendation layer on top — reads better as a **future feature inside V1**
than as its own Rung-1 bet; raised here rather than silently dropped because
the underlying "untapped, not absent" read in competitors.md is genuinely
more interesting than its 0.59 score alone conveys.

---

## LIMITATIONS

- Rung 0 is entirely desk evidence — search snippets, app-store ratings, press
  write-ups, job-board listings — not real paid behavior. Nothing here is a
  signed contract, a completed purchase, or a user test; it is a proxy stack for
  "does a budget line and a felt problem plausibly exist," not proof either does.
- **Shakiest inputs across all four ideas:** every Indeed/ZipRecruiter job count
  is from a search-engine snapshot, not a verified page render (both sites
  returned HTTP 403 on direct fetch all session) — treat every such integer as
  directional, not precise. LinkedIn's own numbers were internally inconsistent
  for "Travel Advisor" (5,000+ on render vs. 52,000+ in snapshot metadata, same
  URL) — a 10x spread feeding V1's and V4's jobs scores. No Google Trends chart
  was directly read for any candidate; every "rising/flat" trend claim in
  search.md is inferred from secondary write-ups.
- **V1's score is the most load-bearing on vendor-adjacent figures** despite
  being the highest-confidence idea overall: Google's own "+350%/+315%" search-
  growth claim could not be reproduced on the primary page it was attributed to,
  and TripGenie's "+200% traffic" is a bare, uncorroborated vendor claim. These
  were explicitly down-weighted (search confidence forced to low) rather than
  taken at face value, but they were in the room shaping the narrative.
- **V4's pain signal is structurally, not just currently, thin:** pain.md notes
  the target users (independent advisors, host agencies, DMOs) mostly live in
  closed Facebook groups and host-agency intranets that this harvest's
  open-web/API tools cannot reach (no FlyerTalk-equivalent login-free trade
  forum was found) — so a low pain score for V4 should be read as "this method
  can't see the venue," not "the pain doesn't exist."
- **V2 and V3's near-tie (0.57 vs 0.59) is not meaningful precision** — both
  rest on low-confidence signals in 3 of 4 columns; the ranking between them is
  directional at best.
- Reddit (reddit.com) and travel.stackexchange.com were unreachable by direct
  fetch all session across all four signal files; every subreddit-size figure
  used above (r/travelagent, r/travel, FlyerTalk membership) comes from
  third-party aggregators carrying their own accuracy disclaimers.
