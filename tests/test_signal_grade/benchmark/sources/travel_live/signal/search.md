# Search-Demand Signal — Travel Discovery by Preference (4 versions)

Tier: WORDS (Rung 0, weakest evidence tier — people typing queries, not paying or using).
Method: 16 WebSearches + 9 WebFetches, budget-capped. Google Trends did not render
actual numeric series via fetch in this session (JS app) — all "trend direction" claims
below are sourced from secondary write-ups that themselves cite Google-internal or
Google-commissioned trend data, NOT a directly-read Trends chart. Downgraded accordingly.

---

## V1 — AI-chat trip planner for leisure travelers (consumer)

**Core queries checked:** "AI trip planner", "where should I go on vacation" / trip-planning-overwhelm
language, "Wanderlog Mindtrip reviews reddit".

**Trend direction:** rising (estimate, secondary sources) — direction not directly fetched from
trends.google.com itself.

**Evidence:**
1. Google's own 2026 travel-trends messaging (relayed via a secondary SEO write-up, not confirmed
   on blog.google itself in this session): "Search interest in 'AI travel assistant' and 'AI
   concierge' has grown by 350% over the past year... 'AI flight booking' spiked by +315%."
   Source: search-engine results summarizing a Google 2026 travel trends report.
   URL: https://business.google.com/en-all/think/search-and-video/ai-travel-marketing-search-trends/
   (direct fetch of this page did NOT surface the 350%/315% figures — it surfaced different stats,
   see below — so this number is estimate/secondary, not independently verified; quoted only because
   two separate search-result snippets repeated it).
   Date: 2026 report. measured_or_estimate: estimate. source_quality: secondary (SEO aggregator
   paraphrasing a vendor/Google report; not independently confirmed on the primary page).
2. Direct WebFetch of business.google.com/.../ai-travel-marketing-search-trends/ (primary, Google's
   own site) gave different, independently verified figures: "3 in 4 users say AI Mode and/or AI
   Overviews help them make faster and more confident decisions" (Google-commissioned Ipsos
   research, Dec. 2025) and "53% of travellers regularly use Google Search to learn about, stay
   informed, or simply enjoy content related to travel" (Google-commissioned Ipsos, July 2025).
   URL: https://business.google.com/en-all/think/search-and-video/ai-travel-marketing-search-trends/
   Date: page as of access 2026-10-03. measured_or_estimate: measured (stat is stated on the
   primary page, though the underlying survey itself is Google-commissioned, i.e. vendor-adjacent).
   source_quality: primary (Google's own page) but vendor-interested (Google sells AI Mode/Search ads).
3. monkeytravel.app's 2026 Travel Planning Report (analysis of "more than 1.1 million searches"
   across 3 months of 2026 Google Search Console impressions on their own travel content): "Free AI
   trip planner searches convert at approximately 5.9%" vs. "Generic 'AI trip planner' searches
   convert at roughly 1.7%"; conclusion stated as "Planning Is Now AI-First."
   URL: https://monkeytravel.app/blog/travel-planning-trends-2026
   Date: 2026. measured_or_estimate: measured (their own GSC data) but source_quality: vendor
   (MonkeyTravel sells a travel-planning product; sample is their own site's traffic, not
   representative of overall search volume).
4. Consumer community check: Wanderlog and Mindtrip both have active, sizeable Reddit discussion
   (r/travel threads comparing them) and app-store presence — Wanderlog: 1M+ Google Play installs,
   ~36.5K Play Store reviews, 4.7★ (AppBrain/Play Store, aggregated via search). This confirms a
   real, large user base actively discussing/rating AI-ish trip planners, i.e. the category is
   searched and used, not just Google's own PR framing.
   URL: https://play.google.com/store/apps/details?id=com.wanderlog.android ;
   https://www.appbrain.com/dev/Wanderlog/
   Date: accessed 2026-10-03. measured_or_estimate: measured (store listing counts).
   source_quality: primary (app store listing) for the install/review counts.

**Confidence: low-med.** The headline "AI trip planning search is exploding" framing comes
overwhelmingly from Google's own marketing content and SEO-aggregator sites that have an interest
in selling into this trend (vendor bias) and whose specific growth percentages (350%, 315%,
190% YoY for "help planning my trip") could not be independently reproduced on the cited primary
page. The install-base/review-count evidence for Wanderlog is solid and measured, but that reflects
usage of an existing non-conversational planner more than proof of unmet "AI chat planner" demand.
No independently-read Google Trends chart was obtained.

---

## V2 — Preference quiz that matches travelers to destinations (consumer / widget)

**Core queries checked:** "where should I go on vacation quiz", "find your perfect destination" /
"takes the guesswork" quiz phrasing, Hotels.com destination-comparison tool.

**Trend direction:** flat-to-unknown — this is an old, well-established content genre (listicle
quizzes), not a newly emerging search spike; no evidence found of a recent surge.

**Evidence:**
1. A plain search for "where should I go on vacation quiz" returns a crowded field of long-standing
   publishers already serving this exact query: Refinery29, BrainFall, BuzzFeed, Sierra in the City,
   Scott Dunn, Tripadvisor forum thread, AAA ("Travel Ideas: Where Should I Go on Vacation in
   2022?"). The presence of a BuzzFeed/Refinery29 personality-quiz genre dating back years indicates
   this is a durable, evergreen query, not a fresh wedge.
   URL: https://www.buzzfeed.com/lady_emerald/vacation-destination-quiz ;
   https://www.refinery29.com/en-us/where-to-go-on-vacation-quiz ;
   https://sierrainthecity.com/where-should-i-go-on-vacation-quiz/
   Date: accessed 2026-10-03 (BuzzFeed/Refinery29 quizzes are multi-year-old evergreen content).
   measured_or_estimate: estimate (inferred from breadth/age of competing content, not a volume
   number). source_quality: listicle.
2. An established commercial player already runs exactly this wedge at scale: Hotels.com's
   "Destination Comparison" tool / "Let's find your ideal holiday destination" quiz, localized
   across US/UK/CA/ES markets.
   URL: https://www.hotels.com/why/destination-comparison ; https://in.hotels.com/go/world/quiz-perfect-destination
   Date: accessed 2026-10-03. measured_or_estimate: estimate (existence confirmed; no traffic
   numbers obtained). source_quality: vendor (Hotels.com sells bookings off this tool, exactly the
   V2 model — same wedge already live at an OTA with distribution V2 wouldn't have).
3. Tripadvisor's own "Games" sub-forum has a long-running user-made thread, "Where to travel
   next...? Take this quiz and get inspired!", i.e. travelers organically create and share these
   quizzes in a major travel forum — a sign the format resonates with real travelers, not just SEO
   farms.
   URL: https://www.tripadvisor.com/ShowTopic-g1-i50384-k13880330-Where_to_travel_next_Take_this_quiz_and_get_inspired-Games.html
   Date: forum thread, long-running (accessed 2026-10-03). measured_or_estimate: estimate (no reply
   count captured). source_quality: secondary (user-generated forum content, not platform metrics).

**Confidence: low.** The query clearly exists and is heavily served already (strong qualitative
signal), but no volume or trend numbers were obtainable (Google Trends did not render), and the
market is visibly saturated with free listicle-quiz competitors plus at least one major OTA
(Hotels.com) running the identical consumer wedge, which undercuts both "is there unmet demand"
and "could a widget business differentiate." No subreddit or forum size specific to "destination
quiz" was found (people ask "where should I go" inside general travel subreddits/forums rather than
a dedicated community, so no clean community-size metric applies here).

---

## V3 — Recommendations from a traveler's own past trips (consumer)

**Core queries checked:** "travel app remembers your preferences" / "learns your travel style",
loyalty-program / frequent-flyer recommendation apps, FlyerTalk community size.

**Trend direction:** unknown — too early/niche a query shape to show a clear direction; the apps
that exist in this space are small, newly launched, and not clearly in response to a visible search
trend (more a supply-side AI feature trend than a demand-pull one).

**Evidence:**
1. A search for apps matching this description surfaces a long tail of small, recent entrants —
   Travel Mind, Travel Mate AI, Trippin, Next Trip AI, Tripify — i.e. the idea is being tried by
   multiple small teams, but none of them have an established community discussion footprint
   (no subreddit, no notable review volume found for any of them in this search).
   URL: https://play.google.com/store/apps/details?id=com.mycompany.travelmind ;
   https://apps.apple.com/app/id6742312107 (Next Trip AI) ; https://apps.apple.com/us/app/-/id6753917809 (Trippin)
   Date: accessed 2026-10-03. measured_or_estimate: estimate (existence only; no install/review
   counts surfaced in search snippets). source_quality: vendor (app-store self-descriptions).
2. The adjacent, much larger community for "frequent travelers" (V3's named target user) is
   FlyerTalk, not a "remembers my preferences" app community: "FlyerTalk is the largest expert
   travel community with 889,211 members and 37,236,570 posts" — a real, large, active audience of
   exactly the 3+ trips/year / loyalty-program user V3 targets, but their active discussion is about
   manually optimizing miles/points, not about a tool that auto-profiles their taste from past
   trips. This is a community-size data point for the target USER, not direct evidence of demand
   for this specific PROBLEM framing.
   URL: https://www.flyertalk.com/
   Date: accessed 2026-10-03. measured_or_estimate: measured (membership/post counts, as reported
   by a secondary aggregator of FlyerTalk's self-description, not independently re-verified on
   flyertalk.com directly). source_quality: secondary (search-result paraphrase of the site's own
   self-description banner, counts as close to primary but not independently re-fetched).
3. No query of the form "I wish my travel app knew my taste" or similar surfaced any sizeable
   discussion thread, Quora question cluster, or Stack Exchange tag in this search round — the
   absence itself is notable and is reported here as a negative/thin finding rather than omitted.
   measured_or_estimate: estimate (absence of evidence). source_quality: n/a.

**Confidence: low.** This is the thinnest signal of the four. The problem statement ("every plan
starts from zero") is plausible but no one appears to be typing this complaint in a way that
surfaces in general web search; the nearest adjacent community (FlyerTalk) is large but is focused
on a different, adjacent problem (points optimization, not taste-based recommendation). Several
small apps are already attempting this exact wedge, which is weak evidence of a genuine felt need
among builders but says nothing about traveler-side search volume.

---

## V4 — Client-preference matching sold to travel businesses (business/B2B)

**Core queries checked:** Travefy/Tern/Fora reviews, r/travelagent and r/TravelAgentFinance
subreddit size, travel-advisor Facebook groups, Host Agency Reviews' Independent Travel Advisor
Report.

**Trend direction:** flat-to-rising on the underlying advisor-economy (more advisors, more sales),
but no direct evidence of rising *search* interest specifically in "client-matching" or
"preference-matching" software as a sub-category — advisors appear to search for and discuss
"travel agency software" broadly (CRM, itinerary builders, invoicing), and matching/intake is one
feature among many already bundled into incumbents.

**Evidence:**
1. Host Agency Reviews' Independent Travel Advisor Report 2023 (survey-based, advisor-industry
   authority site): "Of the 2068 total travel advisors who completed HAR's 2023 Travel Advisor
   survey... [they] reported producing over $1.5 billion in sales, generating 218,342 bookings...
   Average annual sales landed at $530,744 in 2022," a 32% YoY increase, and "50% of travelers were
   more likely to use a travel advisor than in the past." This establishes the target user
   population is active and growing, a precondition for any B2B demand, though it is not itself a
   search-query metric.
   URL: https://hostagencyreviews.com/blog/the-independent-travel-advisor-report-2023
   Date: 2023 survey (published ~2023, referencing 2022 data). measured_or_estimate: measured
   (their own survey of 2068 advisors). source_quality: secondary/industry-authority (Host Agency
   Reviews is itself a reviewer/affiliate in this space, so mildly vendor-adjacent, but the report
   is the closest thing to a primary advisor-population dataset found).
2. The dedicated Reddit community for this target user is tiny: r/travelagent shows only ~2,642
   members per a Reddit-stats aggregator (reddapi.dev), vs. r/travel's 14,424,720 and r/solotravel's
   4,574,353 — a roughly 1,700x–5,000x gap versus the consumer-side subreddits checked for
   V1-V3. This strongly suggests travel advisors do not congregate on Reddit to discuss their
   workflow pain, so Reddit search-demand signal is structurally weak for V4 regardless of actual
   advisor pain.
   URL: https://reddapi.dev/subreddits/travelagent/insights (r/travelagent) vs.
   https://reddapi.dev/subreddits/travel/insights (r/travel)
   Date: accessed 2026-10-03. measured_or_estimate: measured (subscriber counts as reported by
   third-party aggregator, not Reddit's own API directly — Reddit itself was unreachable via fetch
   in this session). source_quality: secondary (third-party scraper of Reddit data, not Reddit
   primary).
3. Advisors instead congregate on Facebook at meaningfully larger scale than Reddit: "the largest
   travel advisor Facebook group is 'Luxury Travel Social Media & Marketing Strategies for Travel
   Professionals'... with about 51,000 members with typically 90+ posts a month"; "The Travel
   Professional Community... welcomed its 15,000th member." This is a better proxy community size
   for V4's target user than Reddit, and shows a real, moderately active (not viral) community.
   URL: https://www.travelresearchonline.com/blog/index.php/2025/10/whats-the-biggest-group-you-ever-put-together-tall-tales-and-top-tips-from-travel-advisors/ ;
   https://travelprofessionalnews.com/the-largest-online-travel-professional-community-reaches-15000-members/
   Date: 2025-10 / undated (accessed 2026-10-03). measured_or_estimate: measured (counts as stated
   in the articles) but source_quality: secondary (industry blog reporting on group sizes, not a
   first-party Facebook API read).
4. Direct competitor confirmation: Travefy ("ranked #1 across itinerary building, form building,
   website building, and CRM in the latest Host Agency Reviews survey") and Tern ("all-in-one
   platform offering interactive itineraries and proposals with AI drafting, an integrated CRM with
   intake forms...") both already exist, are reviewed, and already bundle an "intake form" /
   "AI drafting" matching-like feature into broader advisor-CRM suites — meaning V4's specific
   wedge (intake + matching engine for proposals) is not white space; it's a feature inside
   incumbents' bundles already being searched for and compared ("Tern vs Travefy" comparison pages
   exist on CB Insights).
   URL: https://travefy.com/solutions/agency ; https://tripkit.com/tern-reviews ;
   https://www.cbinsights.com/compare/tern-software-vs-travefy
   Date: accessed 2026-10-03 (2026-dated review content). measured_or_estimate: estimate (feature
   existence confirmed qualitatively; no search-volume numbers for "travel advisor CRM" obtained).
   source_quality: vendor (Travefy/Tern's own sites) and secondary (review aggregators).

**Confidence: low-med.** The advisor population and sales volume are real and documented
(strongest "population exists" evidence of the four candidates), but the specific B2B search-demand
signal is weak: advisors' own online communities are small on the one platform (Reddit) that is
easy to measure, larger-but-unmeasured on Facebook, and the exact wedge (intake quiz + matching
engine for proposals) is already a checkbox feature inside at least two funded, reviewed incumbents
(Travefy, Tern), meaning most of any search demand likely routes to "best travel agency software"
comparisons rather than to a matching-specific query.

---

## Cross-cutting caveats

- Reddit's own site (reddit.com) could not be fetched directly in this session ("Claude Code is
  unable to fetch from www.reddit.com"); all subreddit subscriber counts above are from third-party
  aggregators (reddapi.dev, subredditstats.com) which themselves carry disclaimers about data
  staleness/accuracy ("Please do not rely on the accuracy of this site's data for anything
  serious/important"). Treat all subscriber counts as directionally indicative, not precise.
- travel.stackexchange.com could not be fetched ("Claude Code is unable to fetch from
  travel.stackexchange.com"), so no Stack Exchange question-count evidence was obtained for any
  candidate — a gap, not a zero finding.
- Google Trends (trends.google.com) was not directly queried/rendered in this session for any
  candidate; every "trend direction" above is inferred from secondary sources describing Trends-like
  movement, never a chart this agent read itself. This is the single biggest limitation of this
  report and the reason every candidate is capped at low or low-med confidence.
