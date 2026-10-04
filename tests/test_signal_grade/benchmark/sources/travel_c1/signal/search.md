# Search-Demand Signal — Travel Discovery-by-Preference (4 versions)

Budget used: 14 WebSearches, 8 WebFetch attempts (4 succeeded; Reddit, G2, and
Travel Stack Exchange blocked direct fetch — HTTP 403/429/"unable to fetch").
Google Trends (`trends.google.com`) could not be fetched (429) — per the brief,
this is downgraded to "direction not directly fetched," not invented.

This is Rung-0 WORDS evidence only: it shows people type these queries and
that products/communities around them exist and are active. It does NOT show
willingness to pay or usage depth — treat all confidence ratings below as
capped at "medium" for that reason.

---

## V1 — AI-chat trip planner for leisure travelers (consumer)

**Core queries checked:** "AI trip planner", "where should we go" (vacation
overwhelm), trip-planning-app reviews (Wanderlog, Mindtrip, Layla).

**Trend direction:** rising (estimate) — direction not directly fetched from
Google Trends; inferred from review-volume growth and proliferation of
competing apps/listicles, which is a weaker proxy than Trends itself.

**Evidence:**
1. Figure: Wanderlog iOS app — 4.9★ average, **36,000 ratings**.
   URL: https://apps.apple.com/us/app/wanderlog-travel-planner/id1476732439?see-all=reviews
   Date accessed: 2026-10-03.
   Quote: "Exact Rating: 4.9 out of 5 with 36K Ratings" (page content, App
   Store ratings summary); review quote: "Planning has actually been fun
   instead of tedious because of this app."
   measured_or_estimate: measured (fetched directly). source_quality: primary
   (Apple's own App Store page).

2. Figure: Mindtrip iOS app — 4.7★ average, **816 ratings**.
   URL: https://apps.apple.com/us/app/mindtrip-ai-travel-companion/id6503107567?see-all=reviews&platform=ipad
   Date accessed: 2026-10-03.
   Quote: "The app has an average rating of 4.7 out of 5 with a total of 816
   ratings."
   measured_or_estimate: measured (fetched directly). source_quality: primary.

3. Figure: Layla iOS app — reported "4.7 out of 5 with 191 ratings" (one
   source) vs. "4.6... as of September 2026" (another), i.e. roughly an
   order of magnitude fewer ratings than Mindtrip/Wanderlog.
   URL: https://apps.apple.com/us/app/layla-ai-trip-planner/id6758730467
   Date: search snippet dated September 2026.
   Quote: "Layla: 4.7 out of 5 with 191 ratings on the Apple App Store...
   4.6 on the iOS App Store and 4.7 on Google Play as of September 2026."
   measured_or_estimate: estimate (not independently fetched — pulled from a
   search-engine synthesis of third-party comparison blogs). source_quality:
   secondary/vendor (comparison blogs that sell or review these same apps).

4. Figure: a Reddit travel-planning community size used as a proxy for how
   many people actively crowdsource "where should I go" / itinerary help:
   r/solotravel — **4,574,353 members**.
   URL: https://reddapi.dev/subreddits/solotravel/insights
   Date: accessed 2026-10-03 (live counter).
   Quote: "r/solotravel: 4,574,353 members, 720 posts"
   measured_or_estimate: measured (scraper reads Reddit's live count), but
   direct reddit.com fetch was blocked for this harvest, so this number
   comes from a third-party mirror. source_quality: secondary.

**Confidence: medium.** Multiple independent, well-known competing products
(Wanderlog, Mindtrip, Layla, plus Stardrift/Stippl per listicles) and tens of
thousands of real App Store ratings show a genuine, sizeable existing market
of people using AI/semi-AI trip planners — this is the most evidenced
candidate. But no Trends number was obtained, so "rising" is an inference
from review-count/competitor-count growth, not a measured slope.

---

## V2 — Preference quiz that matches travelers to destinations (consumer /
widget for media & sellers)

**Core queries checked:** "where should I travel quiz", "destination
finder quiz", quiz-widget licensing for travel media/sellers.

**Trend direction:** unknown / likely flat — this is a long-standing,
evergreen content format (major publishers have run near-identical quizzes
for years), not a newly emerging query pattern. No Trends data obtained.

**Evidence:**
1. Figure: at least **8 distinct, named "where should I travel" quiz
   products** found in one search pass, spanning big publishers to small
   tools: National Geographic, Hotels.com, AAA, Interact (tryinteract.com),
   DestList, TripMemo, Detour, Sierra in the City.
   URLs: https://www.nationalgeographic.com/travel/article/where-should-you-travel-2025-quiz ;
   https://in.hotels.com/go/world/quiz-perfect-destination ;
   https://www.tryinteract.com/quiz/where-should-you-travel-next/ ;
   https://www.destlist.com/vacation-decision-tool
   Date: accessed 2026-10-03 (all live pages as of search).
   Quote: "National Geographic's 2025 travel quiz is inspired by their
   annual Best of the World list"; "DestList's free 'Where Should I Travel'
   quiz helps you discover the best destination based on your budget,
   travel style, and vibe."
   measured_or_estimate: measured (count of distinct live results for the
   exact query). source_quality: mixed — some primary (NatGeo, Hotels.com
   are the publishers themselves), some vendor/listicle (DestList, TripMemo,
   Interact are themselves quiz-tool vendors).

2. Figure: a real organic traveler thread discussing a destination quiz
   on a major travel forum (not a vendor page).
   URL: https://www.tripadvisor.com/ShowTopic-g1-i50384-k13880330-Where_to_travel_next_Take_this_quiz_and_get_inspired-Games.html
   Date: accessed 2026-10-03.
   Quote: Title: "Where to travel next...? Take this quiz and get inspired!"
   (Tripadvisor Games forum thread).
   measured_or_estimate: measured (thread exists). source_quality: primary
   (Tripadvisor's own forum), but it is a single thread, not a count of many.

3. Figure: quiz-widget vendors (Outgrow, involve.me) explicitly pitch this
   exact format as a lead-gen tool to "travel agencies, tourism boards, and
   bloggers" — i.e. the B2B-widget wedge in V2 already has commercial
   precedent, not just a hypothesis.
   URL: https://outgrow.co/blog/travel-quiz ; https://www.involve.me/templates/find-your-next-travel-destination-quiz
   Date: accessed 2026-10-03.
   Quote: "ideal for travel agencies, tourism boards, and bloggers, helping
   brands connect with their audience while capturing valuable leads."
   measured_or_estimate: estimate (vendor marketing copy, not independent
   usage data). source_quality: vendor.

**Confidence: low.** The query and format clearly exist and are widely
reused, but that is consistent with "a commodity content trope everyone
already does" as much as with "rising unmet demand." No subscriber/traffic
numbers, no Trends read, and no evidence distinguishing growing vs. static
interest were found.

---

## V3 — Recommendations from a traveler's own past trips (consumer)

**Core queries checked:** "travel app recommend based on past trips",
loyalty-program personalization, direct checks of TripIt and Polarsteps
(the two consumer apps closest to this wedge).

**Trend direction:** unknown — no query-level search evidence (autocomplete,
forum threads, Trends) was found with travelers themselves asking for this;
evidence here is indirect (competitor-gap analysis), not demand-side.

**Evidence:**
1. Figure: Polarsteps (closest existing consumer app with trip-history data)
   explicitly does **not** do destination recommendations from past trips.
   URL: https://www.wandrly.app/reviews/polarsteps
   Date: accessed 2026-10-03.
   Quote: "unlike other apps, PolarSteps won't suggest attractions,
   restaurants, or activities at your destinations, and it's not designed
   for trip planning or organization—you can't... get destination
   recommendations like you would with comprehensive travel apps."
   measured_or_estimate: estimate (third-party reviewer's characterization,
   not Polarsteps' own spec page). source_quality: secondary.

2. Figure: TripIt's personalization is scoped to logistics (seat
   preference, lounge recommendations by loyalty tier, carbon tracking), not
   next-destination recommendations from travel history.
   URL: https://apps.apple.com/us/app/tripit-travel-planner/id311035142
   (plus aggregated reviews at https://www.trustradius.com/products/tripit/reviews )
   Date: accessed 2026-10-03.
   Quote: "TripIt Pro provides... recommendations for the best lounges based
   on your itinerary and loyalty programs... tracks carbon emissions from
   flights."
   measured_or_estimate: estimate (search-engine synthesis of review pages,
   not a direct fetch of TripIt's own page — direct Apple fetch for TripIt
   was not performed in this pass). source_quality: secondary.

3. Figure: the "personalize from history" pitch currently lives mainly in
   B2B loyalty-tech vendor content (iSeatz, Arrivia, MoEngage), not in
   traveler-voiced complaints — i.e. the push is coming from the supply side
   (loyalty programs wanting to look more personalized), not from a visible
   groundswell of traveler search queries.
   URL: https://www.iseatz.com/blog/why-personalization-matters-in-travel-loyalty ;
   https://www.arrivia.com/insights/ai-personalization-for-unique-member-journeys/
   Date: accessed 2026-10-03.
   Quote: "AI-powered travel experiences enable personalized rewards
   tailored to each member's behaviors, preferences, and past interactions."
   measured_or_estimate: estimate. source_quality: vendor (both iSeatz and
   Arrivia sell loyalty/personalization tech).
   Caveat: one real demand-side data point appeared — "Just over 70% of
   those who get individualized content via their rewards booking site say
   their loyalty programs provide them with value" — but the primary survey
   behind that figure was not identified/verified, so treat as not verified.

**Confidence: low.** No subreddit, forum thread, or autocomplete evidence of
travelers themselves searching for "recommend my next trip from my past
trips" was found in this pass — the strongest finding is a *negative* one
(existing apps with the data, like Polarsteps and TripIt, explicitly don't
do this), which is suggestive of a gap but is not search-demand evidence of
people looking for it.

---

## V4 — Client-preference matching sold to travel businesses (business)

**Core queries checked:** independent travel advisor communities, client
intake/time-spent surveys, reviews of Travefy, Tern, Fora.

**Trend direction:** rising (estimate) — driven by the structural shift to
independent-contractor advisor models (more advisors = more buyers for this
kind of tool), not by a measured query-volume trend.

**Evidence:**
1. Figure: a Travel Market Report survey of advisors found **researching
   (38%)**, **customizing itineraries for clients (21%)**, **comparing
   multiple suppliers/packagers (20%)**, and **managing client communication
   (20%)** as the phases that take the most time.
   URL: https://www.travelmarketreport.com/articles/Attention-Advisors-Heres-How-to-Streamline-Your-Workflow
   Date: accessed 2026-10-03 (article undated in snippet; treat as recent
   trade-press content).
   Quote: "When asked about phases of the planning and booking process that
   take the most time, advisors ranked researching (38%)... customizing
   itineraries for clients (21%)... comparing multiple suppliers and
   packagers (20%)... managing client communication (20%)."
   measured_or_estimate: measured (named survey result, directly quoted).
   source_quality: secondary (trade publication reporting a survey; the
   survey's own underlying data was not independently located).

2. Figure: a travel-advisor trade article states intake forms largely fail
   to capture useful client-preference data, and that discovery for complex
   trips runs **60–90 minutes per client** in live conversation.
   URL: https://www.luxurytravelmagazine.com/news-articles/how-travel-advisors-build-a-client-preference-profile
   Date: accessed 2026-10-03.
   Quote: "While every agency has an intake form, almost none of the useful
   material arrives on it... For complex trips, planning conversations
   typically run 60 to 90 minutes."
   measured_or_estimate: estimate (qualitative trade-press claim, no sample
   size given). source_quality: secondary.

3. Figure: existing paid tools in this exact space have real, if thin,
   review footprints — Travefy Agent: **4.5/5 on Capterra across 20
   verified reviews** (no 1–2★ reviews) and reported 4.5/5 on G2; Fora:
   **4-star rating on Trustpilot from 60 reviews**; Tern: described as
   having a deliberately thin G2/Capterra footprint because advisor tools
   "spread through the trade, not software marketplaces."
   URLs: https://www.capterra.com/p/148927/Travefy-Agent/reviews/ ;
   https://www.trustpilot.com/review/foratravel.com ;
   https://tripkit.com/tern-reviews
   Date: accessed 2026-10-03.
   Quote: "Travefy Agent has a 4.5/5 rating across 20 verified reviews with
   no single 1- or 2-star reviews"; "Customer reviews show a 4-star rating
   on Trustpilot from 60 reviews"; "Tern's G2 and Capterra footprints are
   thin — like most advisor tools it spreads through the trade, not
   software marketplaces."
   measured_or_estimate: estimate (figures read via search-engine synthesis
   of these pages; direct fetch of g2.com was blocked with HTTP 403 in this
   pass, so none of these review counts were independently re-verified by
   fetching the page ourselves). source_quality: secondary (Capterra/
   Trustpilot are primary platforms, but accessed indirectly here) / vendor
   (tripkit.com itself sells into this category).

**Confidence: medium.** The time-spent-on-research survey figures (38%/21%
etc.) are the most concrete, named-source numbers in this whole harvest, and
three distinct named competitors (Travefy, Tern, Fora) with live, recent
review pages confirm a real, currently-monetized category. The main
limitation: none of the review-platform pages were fetched directly
(blocked), so those specific counts are one hop removed from primary source.

---

## Cross-cutting notes
- Reddit, G2, and Travel Stack Exchange could not be fetched directly in
  this session (403/429/tooling block), which is why several figures above
  are tagged "estimate"/"secondary" rather than "measured"/"primary" even
  though the underlying number likely exists on a primary page. A rerun with
  working Reddit/G2 access would strengthen several of these to primary.
- Google Trends could not be read (429) for any candidate — no trend slope
  in this report is a real fetched Trends value; all trend directions are
  explicitly labeled as inferred/estimate.
- monkeytravel.app, the source of the one "1.1 million searches" report
  quoted for V1, is itself a vendor in this exact market (an AI trip
  planner) — its self-reported search-funnel stats (e.g. "free ai trip
  planner" 5.9% CTR vs 1.7%) are flagged vendor-quality, not independent.
