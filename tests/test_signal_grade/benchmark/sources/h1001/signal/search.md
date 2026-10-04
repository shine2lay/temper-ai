# Search-Demand Signal — Rung-0 Harvest (WORDS tier)

Captured 2026-10-01. Budget used: ~20 WebSearch calls (slightly over the
12-16 guideline, spent on reddit-subscriber lookups since direct WebFetch to
reddit.com/old.reddit.com was blocked — "Claude Code is unable to fetch from
www.reddit.com" / old.reddit.com) + ~8 WebFetch calls. Google Trends was
attempted once (trends.google.com/trends/explore?q=detention%20pay%20trucking)
and returned HTTP 429 — consistent with the brief's warning that Trends is a
JS app that often won't render via fetch. **No Trends direction was
successfully read for any candidate below** — this is a hard limitation of
this harvest, not a per-candidate finding, and every candidate's confidence is
downgraded accordingly. All "trend direction" fields are therefore
"unknown (not directly fetched)" unless stated otherwise.

Reddit subscriber counts below came from reddapi.dev (a third-party Reddit
analytics index), reached via WebSearch snippets, with one figure
(r/CodingandBilling) confirmed via direct WebFetch to reddapi.dev. These are
measured numbers but from a secondary tool reading Reddit's public counts, not
a direct fetch of reddit.com itself — tagged accordingly.

---

## Candidate 1 — Small-landlord unit-turn / vacancy-days coordination

**Core queries checked:** `make ready turn property management software vendor
scheduling vacancy days`; `reddit property management make ready turn vacancy
coordination`.

**Trend direction:** unknown (not directly fetched). Qualitative signal is
strong — a dense, named vendor category exists (make-ready/turn software),
which only forms around a problem people are actively searching solutions
for, but that is an inference, not a measured trend.

**Evidence:**
1. Vendor category is well populated and recently active: NetVendor, HappyCo,
   AppWorks ("Make Ready Board"), Rent Ready, Lula, and at least two 2026-dated
   blog posts quantifying the cost ("Unit Turnover Delays Cost Property
   Managers Thousands 2026", "Turn Units in 5 Days, Not 15").
   URL: https://ustechautomations.com/resources/blog/property-management-unit-turnover-pain-solution-2026
   Date: search accessed 2026-10-01 (page self-dated 2026).
   Quote: "properties using turnover automation reducing average turn time
   from 12-18 days to 5-7 days, saving $1,200-$2,400 per unit in vacancy costs"
   measured_or_estimate: estimate (vendor-stated savings figure, not an
   independently verified number). source_quality: vendor.
2. r/PropertyManagement subreddit size (proxy for community actively
   discussing this workflow): ~71,176 members, 653 indexed posts.
   URL: https://reddapi.dev/subreddits/propertymanagement/insights
   Date: accessed 2026-10-01.
   Quote (from search snippet of that page): "r/propertymanagement has
   71,176 members... 653 posts indexed on reddapi.dev."
   measured_or_estimate: measured (via secondary tool reading Reddit's
   counts). source_quality: secondary.
3. Average-turn-cost framing repeated independently across two unrelated
   vendor pages ("$2,200+ in vacancy loss" vs "$1,200-$2,400 per unit"),
   suggesting the pain point is commonly quantified in sales copy, though the
   two figures don't fully agree — a sign of marketing estimation, not a
   single authoritative source.
   URL: https://lula.life/articles/apartment-make-ready-checklist
   Date: accessed 2026-10-01.
   Quote: "The average turn takes 34.4 days, which is $2,200+ in vacancy loss
   before $3,500-$5,000 in direct turn costs."
   measured_or_estimate: estimate. source_quality: vendor.

**Confidence: low.** No Trends read, no forum thread counts, no autocomplete
evidence gathered. The vendor-density signal is real but is evidence of
*existing commercial activity*, not directly of *search volume* — it's an
indirect proxy. r/PropertyManagement's size is a genuine community-size data
point but I did not confirm thread-level discussion volume specifically about
make-ready/turn coordination within it.

---

## Candidate 2 — Small-fleet detention capture & auto-invoicing (trucking)

**Core queries checked:** `detention pay trucking invoice automation
software`; `reddit truckers detention pay unpaid shipper receiver`.

**Trend direction:** unknown (not directly fetched; Trends fetch for
"detention pay trucking" returned HTTP 429).

**Evidence:**
1. Multiple dedicated point-solution vendors exist and are actively
   positioning specifically for small/mid carriers: ChargeGuard ("detention
   pay software for small trucking"), DetentionIQ ("for 50-200 truck
   carriers"), Detention Source.
   URL: https://chargeguard.net/ ; https://www.detentioniq.com/
   Date: accessed 2026-10-01.
   Quote: "DetentionIQ captures dwell from your ELD, builds the proof, and
   invoices detention automatically for 50-200 truck carriers."
   measured_or_estimate: estimate (vendor positioning, not a volume number).
   source_quality: vendor.
2. Industry-wide dollar-scale estimate of the underlying problem (not vendor
   marketing — cited to FMCSA/MIT-adjacent research in search synthesis):
   Quote: "detention representing more than 3 billion dollars in waste to the
   industry and over 6 billion dollars to society."
   URL: https://www.fmcsa.dot.gov/sites/fmcsa.dot.gov/files/docs/mission/advisory-committees/mcsac/82096/mcsac-driver-detention-time-discussion-notes.pdf
   Date: accessed 2026-10-01 (document undated in snippet; FMCSA advisory
   committee notes, historically an older document — treat the dollar figure
   as a long-standing industry estimate, not a 2026 figure).
   measured_or_estimate: estimate. source_quality: primary (government
   advisory-committee document) but likely an older estimate re-surfaced.
3. r/Truckers community size: 351,491 members, 2,508 indexed posts — one of
   the larger occupation-specific subreddits found in this whole harvest,
   meaning there's a large standing audience for which detention is a
   frequently-cited pain (per secondary trade coverage), though I did not
   verify thread-level counts specifically on detention pay within it.
   URL: https://reddapi.dev/subreddits/truckers/insights
   Date: accessed 2026-10-01.
   Quote: "r/truckers has 351,491 members and 2,508 indexed posts... 'The
   best trucker subreddit out there.'"
   measured_or_estimate: measured (secondary tool). source_quality: secondary.

**Confidence: low-med.** The existence of 3+ dedicated detention-invoicing
vendors naming small carriers as the target is a meaningfully strong
commercial-interest signal (stronger than most candidates here), and the
subreddit is large. But I have no autocomplete/PAA evidence and no direct
Trends read, and the dollar-loss figure's age is uncertain.

---

## Candidate 3 — Vet-clinic documentation / records layer on PIMS

**Core queries checked:** `veterinary ambient AI scribe documentation burnout
clinic`; `reddit veterinarian charting burnout after hours documentation`.

**Trend direction:** unknown (not directly fetched).

**Evidence:**
1. Burnout prevalence, confirmed via direct fetch: "over 50% of veterinarians
   experience high levels of burnout," citing a 2022 Merck Animal Health
   study.
   URL: https://www.co.vet/post/veterinarian-burnout
   Date: accessed 2026-10-01 (underlying study dated 2022/2024 per
   cross-source references — treat as a few years old, not fresh).
   Quote: "over 50% of veterinarians experience high levels of burnout."
   measured_or_estimate: measured (survey-reported stat), but note
   source_quality: secondary (blog citing the study, not the study itself).
2. Multiple named competing vendors already selling directly into this
   wedge — Scribenote, Scribvet, CoVet, PetDesk documentation features —
   indicating active commercial demand recognition, independent of our
   query.
   URL: https://scribenote.com/blog/combatting-veterinary-burnout-with-scribenote-embracing-ai-scribe-technology
   Date: accessed 2026-10-01.
   measured_or_estimate: estimate. source_quality: vendor.
3. Community size proxy: r/AskVet ~413K members (general vet Q&A, likely
   includes pet owners, so an imperfect proxy for *clinic-staff* burnout
   specifically); r/veterinaryprofession ~31,213 members / 360 posts (closer
   proxy — professionals-only community, much smaller).
   URL: https://reddapi.dev/subreddits/veterinaryprofession/insights (per
   search snippet); r/AskVet figure from painonsocial.com listicle.
   Date: accessed 2026-10-01.
   Quote: "r/veterinaryprofession has 31,213 members with 360 posts
   indexed."
   measured_or_estimate: measured (secondary tool) for the
   veterinaryprofession figure; the AskVet 413K figure is listicle-sourced
   and not cross-checked, so treat as estimate. source_quality: secondary
   (veterinaryprofession) / listicle (AskVet).

**Confidence: low-med.** Burnout and documentation-burden framing is
consistent across multiple independent sources, and a real vendor category
exists, but the professional-only community (r/veterinaryprofession,
~31K) is much smaller than I expected for a "top driver of burnout" framing,
and I found no autocomplete/PAA evidence or thread counts.

---

## Candidate 4 — Dental insurance-verification + denial follow-up

**Core queries checked:** `dental insurance verification outsourcing service
eligibility benefits`; `reddit dental office front desk insurance
verification time consuming`.

**Trend direction:** unknown (not directly fetched).

**Evidence:**
1. Per-patient time cost, repeated across several outsourcing-vendor pages
   (Invensis, OutsourceStrategies, Capline, Qodoro) and confirmed again in a
   follow-up search citing Overjet/Medusind/Curve Dental:
   Quote: "manual verification takes 12 to 13 minutes per patient on
   average."
   URL: https://www.outsourcestrategies.com/blog/five-compelling-reasons-outsource-dental-insurance-verification/
   Date: accessed 2026-10-01.
   measured_or_estimate: estimate (vendor-cited, not independently sourced
   to a named study). source_quality: vendor.
2. Very recent (last ~2 months) EHR/PMS vendor product launches targeting
   exactly this wedge — VideaHealth "AutoVerify" (2026-01-14) and Planet DDS
   "AutoEligibility" for Denticon (2025-11-18) — a concrete, dated signal that
   incumbent practice-management vendors see enough demand to ship native
   features.
   URL: https://www.businesswire.com/news/home/20260114241532/en/VideaHealth-Launches-AutoVerify-to-Bring-Speed-and-Accuracy-to-Insurance-Eligibility-Checks
   Date: 2026-01-14 (press release date).
   Quote: "VideaHealth Launches AutoVerify to Bring Speed and Accuracy to
   Insurance Eligibility Checks."
   measured_or_estimate: measured (a real, dated product launch — strong
   evidence of vendor-side demand belief, though not a direct demand-query
   measurement). source_quality: vendor (press release).
3. r/Dentistry community size: ~166K members (per gummysearch listicle
   synthesis — note WebFetch directly to gummysearch.com returned HTTP 500,
   so this number is via WebSearch snippet only, not independently
   corroborated beyond one other source quoting 105K for an earlier period).
   URL: https://gummysearch.com/r/Dentistry/ (fetch failed; number via search
   snippet of this page).
   Date: accessed 2026-10-01.
   measured_or_estimate: estimate (snippet-reported, could not verify by
   direct fetch). source_quality: secondary.

**Confidence: med.** This candidate has the cleanest signal of the seven: two
independent incumbent-vendor product launches dated within the last ~10
months specifically building the exact wedge described (automated
eligibility/benefit checks on top of existing PMS), which is a real,
dated, named-URL fact — stronger than most of the other candidates'
evidence. Still no Trends/autocomplete read, so capped at "med" not "high."

---

## Candidate 5 — Hourly / blue-collar high-volume applicant screening

**Core queries checked:** `high volume hourly hiring applicant screening
software QSR retail warehouse`; `reddit recruiting high volume applicants
unqualified screening overwhelmed`.

**Trend direction:** unknown (not directly fetched).

**Evidence:**
1. Applicant-volume growth stat, cited from a recruiting-ops newsletter (not
   a vendor):
   Quote: "Applications have doubled since 2021, with a 207% increase in
   business role applications and a 161% rise for technical roles."
   URL: https://gbdtalent.substack.com/p/how-to-manage-the-surge-in-applicant
   Date: accessed 2026-10-01 (post date not independently confirmed).
   measured_or_estimate: estimate (secondary-newsletter-reported, underlying
   source not verified). source_quality: secondary.
2. Dense, competitive, named vendor category specifically for hourly/QSR/
   retail/warehouse volume hiring: Workstream (serves "46 of the top 50
   restaurant brands"), Fountain ("500+ employers"), HigherMe ("20,000+
   locations"), Paradox/Olivia (built McDonald's McHire), Jobalign.
   URL: https://sapia.ai/resources/blog/best-high-volume-hiring-software/
   Date: accessed 2026-10-01 (listicle dated "2026").
   measured_or_estimate: estimate (vendor self-reported customer counts).
   source_quality: listicle / vendor.
3. r/humanresources community size: ~240K members (one source) vs 236,397
   (another, close agreement — two independent snippets converge within
   ~1.5%, which is reassuring for this one figure specifically).
   URL: https://gummysearch.com/r/humanresources/ (fetch attempt returned
   HTTP 500; number via WebSearch snippet).
   Date: accessed 2026-10-01.
   measured_or_estimate: estimate (snippet-reported). source_quality:
   secondary.

**Confidence: low-med.** The vendor category is the most saturated/competitive
of all seven candidates (several nine-figure-funded incumbents already
dominate: Fountain, Paradox, Workstream) — that is itself a signal worth
flagging honestly: this reads as a demand signal for the *problem*, but an
already-crowded solution space, which this search-demand harvest is not
designed to judge (that's for the synthesizer). No direct Trends/autocomplete
evidence gathered.

---

## Candidate 6 — Specialty / post-acute prior-auth + denial-appeal packets

**Core queries checked:** `prior authorization denial appeal automation
inpatient rehab LTCH software`; `reddit medical billing prior authorization
time consuming hours per week`.

**Trend direction:** unknown (not directly fetched).

**Evidence:**
1. Confirmed via direct WebFetch (verbatim, from an AMA survey of 1,000
   physicians, late 2024):
   Quote: "On average, practices complete 39 prior authorization requests
   per physician, per week." and "Physicians and their staff spend an
   average of 13 hours completing those requests each week."
   URL: https://www.ama-assn.org/practice-management/prior-authorization/fixing-prior-auth-nearly-40-prior-authorizations-week-way
   Date: survey late 2024; article accessed 2026-10-01.
   measured_or_estimate: measured. source_quality: primary (AMA, the
   professional body that ran the survey).
2. Segment-specific denial-overturn-rate stat (directly relevant to the
   "many are overturned on appeal" framing in the brief), from an HHS OIG
   report specifically on LTCH/IRF:
   Quote: "Medicare Advantage Organizations collectively overturned 36
   percent of LTCH denials and 43 percent of IRF denials."
   URL: https://oig.hhs.gov/reports/all/2026/the-three-largest-medicare-advantage-organizations-denied-requests-for-long-term-acute-care-and-inpatient-rehabilitation-at-some-of-the-highest-rates/
   Date: report dated 2026; accessed 2026-10-01.
   measured_or_estimate: measured. source_quality: primary (HHS OIG,
   government oversight body) — the strongest single source-quality rating
   found anywhere in this harvest.
3. r/CodingandBilling community size, confirmed via direct WebFetch: 35,500
   members, 189 indexed posts, "created on 2014-06-07... marked as '[ok]
   active' with its feed indexed."
   URL: https://reddapi.dev/subreddits/codingandbilling/insights
   Date: accessed 2026-10-01.
   measured_or_estimate: measured (direct fetch). source_quality: secondary.
   A vendor, SPRY, separately claims "75% fewer auth-related denials" and
   "80% of Prior Authorizations Automated" for rehab-therapy clinics
   specifically — directly on-target for this candidate's segment, but this
   is a vendor's own product-performance claim, not independent demand
   evidence (source_quality: vendor; not counted as one of the 3 above).

**Confidence: med.** This candidate has the single strongest-quality source
found in the whole harvest (HHS OIG, a primary government source, with a
segment-specific overturn-rate stat that matches the brief's framing almost
exactly) plus a confirmed AMA physician-survey figure. Still capped at "med"
because none of this is a direct measurement of *search* behavior — it's
problem-prevalence evidence, which is adjacent to but not the same as
search-demand.

---

## Candidate 7 — Schedule C client record-gathering for tax preparers

**Core queries checked:** `tax preparer client portal chasing missing
documents Schedule C deadline`; `reddit taxpros chasing clients for documents
tax season`.

**Trend direction:** unknown (not directly fetched).

**Evidence:**
1. Industry-survey ranking (Wolters Kluwer annual trends survey): tax/
   accounting professionals ranked "late and unprepared clients" as their
   #1 challenge. I could not directly fetch either the Wolters Kluwer page
   or the Businesswire press release (both returned HTTP 403), so this is
   reported via WebSearch synthesis only, not a verbatim-confirmed quote.
   URL: https://www.wolterskluwer.com/en/news/wolters-kluwer-annual-accounting-survey-reveals-top-5-challenges-and-2023-goals
   Date: survey referenced as 2022/2023-cycle; accessed via search
   2026-10-01.
   measured_or_estimate: estimate (not independently verified by direct
   fetch — downgrade accordingly). source_quality: secondary (survey
   write-up).
2. A dedicated vendor category exists naming this exact wedge (client
   portals that "stop chasing clients for documents"), e.g. Sliq360,
   Dokutrak, Fast.io, Superdocu, CCH Axcess Client Collaboration (the
   Wolters Kluwer product built specifically in response to the survey
   finding above).
   URL: https://sliq360.com/stop-chasing-clients-for-documents/
   Date: accessed 2026-10-01.
   measured_or_estimate: estimate. source_quality: vendor.
3. r/taxpros community size: ~90,718 members, 227 indexed posts (per search
   snippet of reddapi.dev; not independently confirmed by direct fetch).
   URL: https://reddapi.dev/subreddits/taxpros/insights
   Date: accessed 2026-10-01.
   measured_or_estimate: estimate (snippet-reported, not direct-fetch
   confirmed). source_quality: secondary.

**Confidence: low.** No Reddit search specifically surfaced actual
r/taxpros thread discussion (only general search-engine results about IRS
scam warnings and unrelated tax-season content) — I could not confirm this
is a live, frequently-discussed topic within that community itself, only
that the community exists at a decent size and that a vendor category/survey
exists around the adjacent "late/unprepared clients" framing.

---

## Cross-candidate notes (not a ranking)

- No candidate got a directly-measured Google Trends read; the one Trends
  fetch attempted (detention pay trucking) returned HTTP 429. Every
  "trend_direction" below is "unknown" for this reason, not because
  interest is flat — this is a tooling limitation of this harvest, stated
  per the brief's instructions rather than guessed at.
- Direct WebFetch to reddit.com and old.reddit.com was blocked outright
  ("Claude Code is unable to fetch from www.reddit.com"), so all subreddit
  sizes are via a third-party index (reddapi.dev) or listicle (gummysearch,
  painonsocial), reached mostly through WebSearch snippets rather than
  direct fetch confirmation (two reddapi.dev figures — r/CodingandBilling
  and the AMA prior-auth quote — were directly fetch-confirmed; the rest
  were not).
- Candidate 6 (prior-auth/denial-appeal) and Candidate 4 (dental insurance
  verification) produced the highest source-quality evidence (HHS OIG, AMA,
  and two independently-dated incumbent-vendor product launches). Candidate
  7 (tax document chasing) produced the thinnest, least-verified evidence.
