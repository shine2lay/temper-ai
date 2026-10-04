# Job-Postings Signal — Travel Discovery-by-Preference Shortlist (V1–V4)

Method note: Indeed and ZipRecruiter block direct page fetch (HTTP 403) for this
session, so most of their counts come from Google-indexed search-result titles
(estimate, secondary) rather than a verified on-page render (measured, primary).
LinkedIn's `/jobs/<slug>-jobs` pages *did* render via WebFetch, so those counts are
tagged measured/primary — but note LinkedIn itself shows different numbers for the
same URL depending on crawl path (search-snippet title vs. rendered page body); this
is flagged per-item below, not papered over.

Across V1–V4, "people paid to do this by hand today" converges on one BLS occupation
— **Travel Agents** (BLS SOC code covers travel advisors/consultants/counselors) —
plus adjacent titles (Destination Specialist, Travel Concierge, Proposal Coordinator,
Group Tour Coordinator) that each capture a slice of the task. None of these titles
map 1:1 onto any single candidate; they overlap, which is itself informative — it
means today's "product" for all four problems is largely the same human role.

---

## Shared base-rate: BLS Travel Agents occupation (primary, measured)

- **Board/source**: U.S. Bureau of Labor Statistics, Occupational Outlook Handbook
- **URL**: https://bls.gov/ooh/sales/travel-agents.htm (fetched 2026-10-03)
- **Figures**: 61,500 people employed as travel agents (2025 OEWS); median pay
  $50,160/yr ($24.11/hr); projected growth 2025–2035 ≈ 0% ("little or no change");
  ~5,900 openings/year on average, "most resulting from workers transferring to
  other occupations or retiring" rather than net growth.
- **Why it matters for all four candidates**: this is the closest thing to a
  national headcount of people currently paid to match travelers to destinations
  and build itineraries by hand. Flat growth + ~5,900 annual replacement openings
  = a stable, non-growing budget line, not a shrinking or exploding one. It is a
  *ceiling-ish* number (broader than "AI chat itinerary builder" specifically) and
  a floor for V4's addressable seat count.
- **Tag**: measured, primary, trend = flat (basis: BLS 2025–2035 projection).

---

## V1 — AI-chat trip planner for leisure travelers (consumer)

**Role that does this by hand**: Travel Advisor / Travel Consultant / Trip
Designer — someone who interviews a traveler about preferences/budget/constraints
and returns a day-by-day itinerary with bookable places, stays and activities.

**Counts**:
- Indeed, query "travel advisor" (US): shown as **973** in one search-engine
  snapshot and **600** in another, same query, same day (2026-10-03) — Indeed's
  shown count is volatile/estimate; direct WebFetch of
  https://www.indeed.com/q-travel-advisor-jobs.html returned HTTP 403, so the
  number could not be independently re-verified on-page. Tag: estimate, primary
  board but secondary (search-cache) read.
- Indeed, query "luxury travel advisor": **1,065** (search snapshot, 2026-10-03,
  estimate). URL: https://www.indeed.com/q-luxury-travel-advisor-jobs.html
- LinkedIn, query "Travel Advisor" (US): WebFetch of
  https://www.linkedin.com/jobs/travel-advisor-jobs on 2026-10-03 rendered
  **"5,000+ Travel Advisor jobs in United States"** (measured, primary) — but the
  same URL's search-engine title metadata said **"52,000+ Travel Advisor jobs in
  United States (2,385 new)"**. Flagging this 10x discrepancy rather than picking
  one; LinkedIn's displayed total is known to vary by session/location/login
  state, so treat both as directional, not precise.
- LinkedIn, query "Travel Consultant" (US): WebFetch rendered **"4,000+ Travel
  Consultant Jobs in United States"** (measured, primary), 2026-10-03.
- LinkedIn, query "Corporate Travel Consultant" (US): **729** (28 new) per
  search snapshot (estimate), URL:
  https://www.linkedin.com/jobs/corporate-travel-consultant-jobs
- Indeed, query "travel itinerary planner": **711** (search snapshot, estimate),
  URL: https://www.indeed.com/q-travel-itinerary-planner-jobs.html

**Example postings**:
1. "Reserve Travel Designer" — Chase Travel (JPMorganChase), Heathrow FL,
   hybrid, posted ~2 days before 2026-10-03. Title implies 1:1 itinerary design;
   full task text and salary not rendered in list view. URL:
   https://www.linkedin.com/jobs/travel-advisor-jobs
2. "Travel Experience Counselor III" — American Express Global Business Travel,
   Washington DC. Same limitation (list view only). URL: same as above.
3. "Sr. Corporate Travel Consultant" — ALTOUR, Santa Monica CA, posted ~3 weeks
   before 2026-10-03. URL: https://www.linkedin.com/jobs/travel-consultant-jobs
4. Generic Indeed/ZipRecruiter description language recurring across many
   postings (search snapshot, not a single verbatim posting): "create customized
   travel itineraries that align with client interests and budgets" /
   "tailoring travel itineraries to suit individual client preferences."
   Salary bands seen in snapshots: $35,000–$45,000/yr (entry advisor),
   $50,000–$100,000/yr (personal travel planner), $75,000+/yr (luxury/private
   aviation advisor), $16–$25/hr (hourly/entry roles).

**Trend**: flat (BLS, see shared base-rate above).
**Confidence**: medium — role exists and is well-populated across boards, but
the exact counts are volatile/unverifiable (Indeed blocked fetch; LinkedIn's two
reads disagree by 10x), so treat magnitude as "thousands of US openings for this
exact task," not a precise figure.

---

## V2 — Preference quiz that matches travelers to destinations (consumer / widget)

**Role that does this by hand**: Destination Specialist — the "where should we
go" matching step, typically bundled into a Travel Advisor/Consultant's intake
rather than a standalone job, but "Destination Specialist" is also a distinct
posted title.

**Counts**:
- Indeed, query "destination specialist": **602** broader / **564** for "travel
  destination specialist" / **122** for entry-level (search snapshot,
  2026-10-03, estimate). Direct fetch of
  https://www.indeed.com/q-destination-specialist-jobs.html returned HTTP 403.
- LinkedIn, query "Destination Specialist" (US): WebFetch rendered **"10,000+
  Destination Specialist jobs in United States"** (measured, primary,
  2026-10-03) — but the example postings returned were "Guest Experience
  Specialist" at Signature Aviation (private-jet FBO ground staff) and "Business
  Travel Specialist" at a corporate-travel vendor — i.e. the query is noisy and
  pulls in roles that are not destination-matching at all. **This count
  materially overstates the specific pain** and should be read as an upper
  bound on a broad title, not a clean measure of this task.
- ZipRecruiter, query "Destination Specialist": salary band **$42k–$205k**
  shown (search snapshot, estimate, wide enough to suggest a mixed bag of
  seniority/industries). URL: https://www.ziprecruiter.com/Jobs/Destination-Specialist

**Example postings**:
1. "Guest Experience Specialist" — Signature Aviation, multiple US airports.
   Not actually destination-matching (private aviation ground ops) — included to
   illustrate query noise, not as supporting evidence.
2. "Business Travel Specialist" — CADENCE, San Diego CA. Corporate travel
   booking, not consumer destination matching.
3. No clean example found of a posting whose task description is specifically
   "match traveler preferences to a ranked list of destinations" as a
   standalone job — this function appears embedded inside Travel
   Advisor/Consultant roles (see V1) rather than independently posted.

**Trend**: unknown — no clean time series for this specific title; BLS doesn't
break "destination specialist" out separately from travel agents.
**Confidence**: low — the only large count (LinkedIn 10,000+) is demonstrably
noisy/overbroad on inspection, Indeed's fetch was blocked, and no verified
example posting actually describes the V2 task as its primary duty.

---

## V3 — Recommendations from a traveler's own past trips (consumer, personalization)

**Role that does this by hand**: no distinct job title exists for "build a
taste profile from a traveler's past trips and recommend what's next." The
closest adjacent roles are "Personal/Loyalty Travel Concierge" (repeat-client
relationship roles where remembering past preferences is implicit) and generic
"Personalization Specialist" (marketing, not travel-specific).

**Counts**:
- ZipRecruiter, query "Travel Concierge": **622 jobs currently hiring**,
  **$14–$72/hr** (per-hour rate, i.e. the per-seat labor cost), per search
  snapshot 2026-10-03 (estimate; direct fetch of
  https://www.ziprecruiter.com/Jobs/Travel-Concierge returned HTTP 403).
- LinkedIn, query "Travel Concierge" (US): WebFetch rendered **"8,000+ Travel
  Concierge Jobs in United States"** (measured, primary, 2026-10-03). Example
  postings pulled ("VIP Travel Consultant" at BCD Travel, "Government VIP
  Travel Consultant" at ADTRAV) are corporate VIP-servicing roles, not
  consumer past-trip personalization — another sign the title is broader than
  the specific V3 task.
- Glassdoor, query "Personalization specialist" (all industries, not
  travel-specific): **512 jobs** in US per search snapshot (estimate). URL:
  https://www.glassdoor.com/Job/personalization-specialist-jobs-SRCH_KO0,26.htm
  — flagged explicitly as a broader, non-travel title; included only to show
  that "personalization" as a hired function exists elsewhere, with no travel
  analog found.

**Example postings**:
1. "VIP Travel Consultant" — BCD Travel, Indiana, posted ~1 week before
   2026-10-03. Task text not rendered in list view.
2. "Remote Luxury Travel Concierge" roles (various employers, ZipRecruiter
   snapshot) — "curate and elevate private clients' social and lifestyle
   experiences," $50,000–$70,000/yr hybrid roles or $56,800–$64,800/yr remote
   per search snapshot. Implies repeat-client familiarity but does not name
   "past trip history" or "loyalty data import" as a task.
3. No posting found (across ~5 queries) that names the specific V3 task —
   mining a traveler's own trip history/loyalty data to drive recommendations —
   as a job duty. This appears to be a feature inside existing concierge/advisor
   roles, not a role or budget line of its own.

**Trend**: unknown.
**Confidence**: low — weakest match of the four candidates. The adjacent roles
exist and are reasonably well-populated, but no evidence ties hiring specifically
to the "recommend from your own past trips" task; this looks like a product
feature, not a role employers currently pay humans to do as a distinct function.

---

## V4 — Client-preference matching sold to travel businesses (business)

**Target is the employer, not the worker** — V4's buyer (host agency, tour
operator, hotel group, DMO) is the entity currently paying humans (Travel
Advisors, Proposal Coordinators, Group Tour Coordinators) to do client intake,
preference research and proposal drafting by hand. Evidence here is about the
size of that paid-headcount base, i.e. the "seats" V4 would sell a $30–80/
advisor/month tool into.

**Counts**:
- Same Travel Advisor/Consultant counts as V1 above (Indeed ~600–973 estimate;
  LinkedIn 4,000–5,000+ measured, with a 52,000+ outlier in snapshot metadata)
  represent the seat base V4 prices per-advisor.
- Indeed, query "Proposal Coordinator" (general, **not travel-specific** —
  spans construction, government contracting, SaaS, etc.): **846** / **800**
  across two search snapshots (2026-10-03, estimate). URL:
  https://www.indeed.com/q-proposal-coordinator-jobs.html. Flagged explicitly:
  this title is much broader than "tour-operator proposal drafting," so it
  substantially overstates the specific pain; no travel-specific sub-filter
  was findable.
- Indeed, query "Group Tour Coordinator": **1,224** (search snapshot, estimate,
  2026-10-03). URL: https://www.indeed.com/q-group-tour-coordinator-jobs.html.
  Example: a Long Beach, CA tour operator posting "$30–$35/hr" for a
  tour-coordinator managing international/domestic tours (search snapshot
  quote) — this is the tour-operator-side analog of V4's proposal/matching
  workflow.
- Host-agency hiring activity (secondary, listicle source
  https://hostagencyreviews.com/travel-jobs, 2026-10-03): active recruiting by
  1000 Mile Travel Group, Ovation Travel Group, Cruises Inc./World Travel
  Holdings, and Carlisle Travel for independent, commission-based travel
  advisors — i.e. host agencies are actively growing the exact advisor base
  that V4's per-advisor SaaS would be sold into, though compensation here is
  commission-based (no posted hourly/salary figure), so it doesn't convert
  cleanly into a "labor cost displaced" number the way salaried roles do.
- BLS base rate (shared section above): 61,500 travel agents nationally is the
  closest approximation of V4's total addressable seat count if V4 sold to
  every independent/host-agency advisor in the US.

**Example postings**:
1. Long Beach, CA tour operator — "Tour Coordinator," $30–$35/hr, manages
   international and domestic tours (search snapshot quote, 2026-10-03). URL:
   https://www.indeed.com/q-group-tour-coordinator-jobs.html
2. Proposal Coordinator (general industries) — $86,000–$128,900/yr salary band
   seen in one listing per search snapshot; not travel-specific, included only
   to bound the adjacent-role cost. URL:
   https://www.indeed.com/q-proposal-coordinator-jobs.html
3. Host agencies (1000 Mile Travel Group, Ovation Travel Group, Carlisle
   Travel) recruiting independent travel advisors — commission-based, no fixed
   salary posted. URL: https://hostagencyreviews.com/travel-jobs

**Trend**: flat/unknown — BLS flat growth applies to the underlying advisor
headcount; no specific trend data found for "proposal coordinator, travel" or
"group tour coordinator" as distinct series.
**Confidence**: medium for the advisor-seat-count portion (same underlying data
as V1, shared limitations), low for the proposal-coordinator/DMO portion (title
too broad, no travel-specific carve-out found, no clean trend).

---

## Cross-cutting caveats

- Indeed and ZipRecruiter blocked all direct WebFetch attempts in this session
  (HTTP 403 on every URL tried); every Indeed/ZipRecruiter figure above comes
  from a search-engine snapshot of the page title/snippet, not a verified
  render. Treat as estimate even where a specific integer is quoted.
- LinkedIn rendered successfully via WebFetch, so those four counts (Travel
  Advisor, Travel Consultant, Travel Concierge, Destination Specialist) are
  tagged measured/primary — but LinkedIn's own numbers were internally
  inconsistent for "Travel Advisor" (5,000+ on render vs. 52,000+ in snapshot
  metadata for the identical URL), so "measured" here means "the number the
  page showed when fetched," not "a number known to be stable or precise."
  No second-source cross-check (e.g. Glassdoor, SimplyHired) was done for every
  query given the search budget; where it was done (Glassdoor for
  "personalization specialist"), results are noted inline.
- No candidate has a job title that maps cleanly 1:1 onto its specific wedge.
  All four draw, in overlapping proportions, on the same underlying human role
  (Travel Advisor/Consultant) plus noisier adjacent titles. This overlap is
  itself a finding: the "manual version" of all four ideas is largely the same
  job, at a flat-growth, ~61,500-person, ~$50k-median-salary scale nationally.
