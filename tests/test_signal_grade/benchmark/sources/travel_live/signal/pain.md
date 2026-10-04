# Pain-voice signal — travel discovery-by-preference shortlist (2026-10-03)

Method: Hacker News (Algolia API) and Stack Exchange (api.stackexchange.com) via
`voc.py`; App Store customer-review RSS for consumer incumbents (Mindtrip, Layla,
Wanderlog, TripIt, Tripadvisor, Kayak, Polarsteps, "been"); direct page reads of
sites that load without a login (hostagencyreviews.com, independenttraveladvisors.com
forum, fodors.com community); WebSearch for everything else. All dates below are as
printed by the API/page, "recent" = 2025-04-01 or later.

---

## V1 — AI-chat trip planner for leisure travelers (consumer)

**Distinct recent complaints: 6, across 2 venues (App Store reviews of 3 incumbent
AI planners; Hacker News).**

1. "I was surprised at how easy it was to get this thing to confidently make
   mistakes. Can't see myself trusting it to help plan a trip because it gave me
   so many weird results." — App Store review of Mindtrip ("dotheneedful", 1★),
   2025-06-25, https://itunes.apple.com/us/rss/customerreviews/page=1/id=6503107567/sortby=mostrecent/json
   — tool-gripe, primary.
2. "'Layla' is constantly recommending places that are permanently closed, and
   listed as such on google. Also does not follow directions and will take you
   places you said not to go." — App Store review of Layla ("Ambiand3945", 1★),
   2026-07-05, https://itunes.apple.com/us/rss/customerreviews/page=1/id=6758730467/sortby=mostrecent/json
   — tool-gripe, primary.
3. "Really interesting idea, but the inability to search in the 'explore' area made
   this app useless. ... Instead, they'll recommend only their top restaurants
   regardless. And none of them are necessarily in the area you are in." — App
   Store review of Wanderlog ("mikek31555", 2★), 2026-07-14,
   https://itunes.apple.com/us/rss/customerreviews/page=5/id=1476732439/sortby=mostrecent/json
   — tool-gripe, primary.
4. "What I would really like a travel planner that actually helps me decide where
   to travel depending on my situation, family/friends, preferences, budget etc.
   Then, show me options. Your solution seems like a fit if you already know
   where to go." — HN comment (codegeek), 2025-12-11,
   https://news.ycombinator.com/item?id=46231967 — problem-pain, primary.
5. "You'd think in 2026, with all the apps and websites, planning a trip would be
   fun or at least easy. Nope. It's a full-time job. ... Planning a single
   weekend getaway can take hours. A proper vacation? Weeks, sometimes months."
   — HN comment/Show-HN post (CuylerM, pitching his own app "Vialo"), 2026-02-10,
   https://news.ycombinator.com/item?id=46967640 — problem-pain language but
   vendor (self-promotional), source quality vendor.
6. "We built Navoy after my co-founder spent 9 hours planning a 3-day trip to
   Lisbon." — HN Show HN comment (tnaaron), 2025-07-02,
   https://news.ycombinator.com/item?id=44446177 — vendor (founder's own pitch,
   quantified pain claim, not independently verified).

Not counted (older / off-target): Mindtrip review "Knoland" 2025-10-22 is about
mobile-during-trip UX lag, not planning quality — tool-gripe but off the
personalization angle. TripIt/Polarsteps bugs (crashes, login, date pickers) are
reliability gripes, not about planning/personalization — excluded per the "crashes,
logins and pricing are off target" rule.

**Inaccessible:** none attempted beyond scope; Reddit via WebSearch returned no
reddit.com results for any V1 query tried (confirms the known block).

**Recency:** all 6 quotes are 2025-06 through 2026-07 — solidly inside the window.

**Confidence: med.** Two strong primary tool-gripes on exactly the complaint the
wedge targets (generic/wrong recommendations from Mindtrip and Layla, "top
restaurants regardless of area" from Wanderlog) plus one clean first-person
problem-pain quote (codegeek) across two venues. Weakened by two of six being
vendor self-pitches rather than independent complaints, and no venue beyond HN +
App Store was reachable (travel.stackexchange.com had zero relevant hits — see V2).

---

## V2 — Preference quiz that matches travelers to destinations (consumer + widget)

**Distinct recent complaints: 5, across 2 venues (Hacker News; App Store review of
Kayak's "Explore by budget" feature, which is the closest incumbent to this wedge).**

1. "I've been going round in circles for 3 days trying to decide where to go
   travelling. I can go pretty much anywhere I want to and there are lot of places
   I want to go. I've even found some /really/ good deals but couldn't pull the
   trigger." — HN comment (octo888), 2025-08-31,
   https://news.ycombinator.com/item?id=45088100 — problem-pain, primary.
2. "What I would really like a travel planner that actually helps me decide where
   to travel depending on my situation, family/friends, preferences, budget etc.
   Then, show me options." — HN comment (codegeek), 2025-12-11,
   https://news.ycombinator.com/item?id=46231967 — problem-pain, primary (same
   quote also applies to V1; counted once per candidate as it directly names the
   "decide where to go" job).
3. "I was baited from an ad on Instagram. I liked the explore feature, but I would
   set my budget and it would show options on the map… but wouldn't show the
   actual flights that matched the price shown. They were all 500+ more. I tried
   several other destinations and the same thing." — App Store review of Kayak
   ("Tell your friends", 1★), 2025-11-03,
   https://itunes.apple.com/us/rss/customerreviews/page=4/id=305204535/sortby=mostrecent/json
   — tool-gripe on exactly the budget-to-destination matching feature, primary.
4. "I've spent the last 4 months building Lupath to solve 'destination
   paralysis.' ... the hardest part of a trip isn't the logistics—it's that
   initial gap where you know you need a break, but you have 20 browser tabs open
   trying to decide where to go." — HN Show HN comment (LUpath), 2026-02-15,
   https://news.ycombinator.com/item?id=47026363 — vendor (founder's own pitch).
5. "Planning a trip shouldn't feel overwhelming. Yet today, travelers often spend
   hours juggling flights, accommodations, activities, maps, and budgets across
   multiple websites." — HN Show HN comment (CuylerM, pitching "Wanderly"),
   2026-01-05, https://news.ycombinator.com/item?id=46494776 — vendor.

Not counted: travel.stackexchange.com searches for "decide where to go", "pick a
destination", "narrow down destination" returned only logistics Q&A (immigration,
baggage, routing) with zero genuinely on-target recent hits — logged, not used.

**Inaccessible:** FlyerTalk forum returned HTTP 403 (logged, not retried);
Fodor's community thread that matched the search loaded fine but its only relevant
post was from 2010 (pre-window, not counted); Reddit via WebSearch returned no
reddit.com results.

**Recency:** 2025-08 through 2026-02 — inside the window.

**Confidence: med.** Two independent, non-vendor, first-person "I can't decide
where to go" quotes (octo888, codegeek) plus a concrete tool-gripe on the one
incumbent feature that already tries to do this (Kayak Explore) across two venues.
Weakened by travel.stackexchange.com being a dead end and two of five sources being
vendor pitches.

---

## V3 — Recommendations from a traveler's own past trips (consumer)

**Distinct recent complaints: 2, 1 venue (App Store reviews of TripIt and
Polarsteps, the two incumbents that hold a traveler's trip history) — sparse, and
what's there is adjacent (tool-gripe about losing/blocking past-trip data) rather
than direct complaints about missing personalization.**

1. "20 years a user, most of them Pro. On 8/29/26 TripIt killed all third-party
   sync — Flighty, Tripsy, everything — after promising existing connections would
   keep working. ... My travel history is now hostage to a GDPR request." — App
   Store review of TripIt ("ShadowfaxCA", 1★), 2026-09-17,
   https://itunes.apple.com/us/rss/customerreviews/page=1/id=311035142/sortby=mostrecent/json
   — tool-gripe (incumbent locking up the very trip-history data this wedge would
   need), primary.
2. "I really enjoyed this app for a few years until it lost all my past trip
   history for 2025 and 2026. So it became an average app." — App Store review of
   TripIt ("Hobbyist99", 3★), 2026-08-25,
   https://itunes.apple.com/us/rss/customerreviews/page=1/id=311035142/sortby=mostrecent/json
   — tool-gripe, primary.

Also found but not counted as distinct problem-pain (same theme, same app, folded
into the count-cap, listed for texture): "They constantly break access to my past
trips. I worked with Support for literally nine months..." (Mikedvzo, 2026-08-07);
Polarsteps reviews about being unable to add past trips without exact dates
("TinTin858585", 2026-04-14; "JP de la M", 2026-02-19) — these are onboarding/UX
gripes about logging past trips, not about recommendation quality, so tagged
tool-gripe but weakly on-target.

**Inaccessible / dead ends:** HN searches for "recommendations based on past
trips", "travel app remember preferences", "frequent traveler app wish", "every
trip from scratch" returned zero genuinely on-target recent hits (all off-topic
noise from the broader corpus). "been" app (680148327) had only 1 qualifying
recent 1-3★ review and it was about UI complexity, not personalization. WebSearch
for a Reddit "start from scratch every trip" angle returned no quotable results
(app-store listicles only).

**Recency:** 2026-04 through 2026-09 — inside the window, but thin.

**Confidence: low.** No first-person complaint was found that directly says
"my travel app doesn't learn from my past trips" or "every plan starts from
zero" in the traveler's own words — the two counted quotes are tool-gripes about
TripIt losing/gatekeeping trip-history data, which is adjacent corroboration (it
shows travelers do value their trip history and get angry when it's taken away)
but not a direct statement of the V3 problem. Sparse / mostly adjacent.

---

## V4 — Client-preference matching sold to travel businesses (business)

**Distinct recent complaints: 1 primary quote (software-review site) plus
inconclusive WebSearch summaries that could not be quoted verbatim — sparse.**

1. "The modular framework of Travefy makes creating itineraries super intuitive
   and easy. It also allows me to create my own library of content, which I love
   because it can be very time consuming to lay out descriptions and attachments
   just the way I want them for more complex itinerary items." — review of
   Travefy by advisor Desiree Dantona, dated June 09, 2026 on the page (page itself
   generated 2026, exact day confirmed in page text), https://hostagencyreviews.com/travel-agency-software/travefy/reviews
   — tool-gripe (manual, time-consuming proposal-building work), primary. ("I used
   to use Canva, which was so time-consuming" — Kandita Post, same page, 2026-02-11
   — tool-gripe/problem-pain about the manual alternative, primary, same venue so
   not counted as a second distinct source.)

**Not counted — no verbatim quote available:**
- WebSearch summaries repeatedly described advisors spending "four to six hours"
  on a proposal, or clients "spending 2 weeks" before asking an advisor for help,
  attributed to pages like Alignable forum threads and Travel Market Report — but
  the WebSearch tool in this session returns only titles/links plus its own
  paraphrased summary, never the underlying page's literal snippet text, so none
  of this is quotable as a verbatim complaint. Tagged secondary/unusable, not
  counted.
- G2's Travefy discussion board and Capterra/Trustpilot/Glassdoor reviews of
  advisor software are explicitly reach-only-as-snippet per the brief; the
  snippets returned were paraphrases, not quotes, so nothing from them is counted.
- hostagencyreviews.com pages for Fora Travel (host agency) and Tern (advisor CRM)
  loaded fine and were read in full, but their recent reviews are almost entirely
  5-star marketing-toned testimonials ("Tern has been an absolute game changer...")
  with no first-person complaint about the time cost of learning client tastes or
  matching clients to destinations — logged as checked, off-target.
- independenttraveladvisors.com/forums/ loads normally (XenForo site, dates
  confirmed 2023-2026) but is a very low-traffic community (single-digit threads
  per sub-forum) with no thread on client-preference pain found.
- FlyerTalk's travel-advisor thread returned HTTP 403 — inaccessible, logged, not
  retried.
- HN searches ("travel advisor clients", "my clients travel agent", "travel
    agency AI proposal", "qualified leads tour operator") returned no on-target
  recent hits — the advisor/host-agency/DMO audience essentially doesn't appear in
  the HN corpus.

**Recency:** the one counted quote is from 2026 (inside window), but the sample
is a single source.

**Confidence: low.** Only one venue produced anything quotable, and it is a single
tool-gripe about manual itinerary-layout work, not a direct complaint about the
hours spent learning a client's tastes or matching them to a destination — the
core of V4's wedge. This is genuinely sparse: the target users (independent
advisors, host agencies, DMOs) mostly aren't present in the open, automatable
sources this task can reach (no login-free trade forum equivalent to
BiggerPockets/TruckersReport was found for this trade; their real venues are
closed Facebook groups and host-agency intranets).

---

## Sources and method

- **Hacker News (Algolia API):** the most productive open source for V1/V2 —
  surfaced both genuine first-person complaints (octo888, codegeek) and several
  vendor Show-HN pitches that restate the same pain in marketing language (logged
  as vendor, not counted as independent evidence). Essentially silent on V3 and V4
  — multiple phrasings tried, no on-target recent hits.
- **Stack Exchange (api.stackexchange.com, travel.stackexchange.com):** checked
  for V1/V2 phrasings ("decide where to go", "pick a destination", "narrow down
  destination", "can't decide destination", "where should we go budget") — the
  site's traffic is almost entirely operational/logistics Q&A (visas, baggage,
  routing), zero on-target recent hits. Confirms the brief's warning that SE
  rarely covers these niches.
- **App Store customer-review RSS:** the second-most productive source — read
  Mindtrip, Layla, Wanderlog, TripIt, Tripadvisor, Kayak, Polarsteps, and "been",
  filtering to 1-3★ reviews since 2025-04-01 with job keywords. Produced the
  strongest tool-gripe quotes for V1-V3. Business-side tools for V4 (Travefy,
  Tern) are not meaningfully present as consumer App Store apps with review
  volume, so this channel was weak for V4.
- **Direct page reads (voc.py page):** hostagencyreviews.com (Travefy, Fora,
  Tern reviews — loads normally, dated, mostly positive/marketing-toned);
  independenttraveladvisors.com/forums/ (loads, low traffic, nothing on-target);
  fodors.com community (loads, but matching thread's relevant post predates the
  window). FlyerTalk returned HTTP 403 — logged inaccessible, not retried.
- **WebSearch:** used for Reddit/G2/Capterra/Glassdoor/Trustpilot snippets per
  the brief. In every attempt across both venues and all four candidates, the
  tool returned only titles/links plus its own narrative paraphrase — it never
  surfaced literal snippet text in quotation marks that could be verified against
  the source, and explicit `site:reddit.com` queries returned zero reddit.com
  results. Per the evidence-discipline rule ("quote ONLY words shown verbatim...
  if the result paraphrases, it is not a quote"), nothing from WebSearch is
  counted as a quote in this report — it is logged only as "checked, not
  quotable" or used to find URLs that were then read directly with `voc.py page`.
