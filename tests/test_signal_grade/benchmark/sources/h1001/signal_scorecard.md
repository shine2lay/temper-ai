# Signal Scorecard — Rung-0 Synthesis

Synthesized 2026-10-01 from `state/signal/{search,jobs,pain,competitors}.md`.
No new research performed; every figure/quote/URL below is carried from one
of those four files. Weights (owner rule, money > behavior > words): jobs
.35, competitors .30, pain .20, search .15. Each signal scored 0-3, then
multiplied by a confidence discount (high=1.0, med=0.8, low=0.5) before
weighting. Confidence labels below are my read of each signal agent's stated
confidence for that candidate, collapsed to low/med/high (compound labels
like "low-med" or "med-high" are resolved per-cell by the composition of the
underlying evidence — e.g. a hedge built on a directly-fetched primary page
is kept at "med," a hedge built on vendor/listicle synthesis is pulled down
to "low" — never mechanically rounded).

## SCORECARD TABLE

| # | Idea | search (raw×conf=disc) | jobs (raw×conf=disc) | pain (raw×conf=disc) | competitors (raw×conf=disc) | **weighted** | overall conf |
|---|---|---|---|---|---|---|---|
| 1 | Unit-turn / vacancy-days coordination | 1×0.5=0.50 | 2×0.8=1.60 | 2×0.8=1.60 | 2×0.8=1.60 | **1.44** | HIGH* |
| 2 | Detention capture & auto-invoicing | 2×0.5=1.00 | 0×0.5=0.00 | 2×0.8=1.60 | 1×0.5=0.50 | **0.62** | LOW |
| 3 | Vet-clinic documentation layer | 1×0.5=0.50 | 3×0.8=2.40 | 0×0.5=0.00 | 2×0.8=1.60 | **1.40** | LOW |
| 4 | Dental insurance-verification + denial follow-up | 2×0.8=1.60 | 2×0.8=1.60 | 2×0.8=1.60 | 3×0.8=2.40 | **1.84** | HIGH |
| 5 | Hourly/blue-collar applicant screening | 1×0.5=0.50 | 3×1.0=3.00 | 1×0.5=0.50 | 3×0.5=1.50 | **1.68** | LOW† |
| 6 | Post-acute prior-auth + denial-appeal | 2×0.8=1.60 | 3×1.0=3.00 | 2×0.8=1.60 | 1×0.5=0.50 | **1.76** | LOW† |
| 7 | Schedule C record-gathering (tax) | 1×0.5=0.50 | 0×0.5=0.00 | 2×0.8=1.60 | 1×0.5=0.50 | **0.55** | LOW |

\* C1 meets the mechanical "high" bar (3 of 4 signals at med-confidence with
primary-sourced evidence, only 1 low) but no single signal is strong — read
this as "solidly validated as middling," not as a standout.
† Flagged **promising-but-unproven**: a top-3 weighted score sitting on LOW
overall confidence because the competitors signal is unverified. See
RECOMMENDATION.

---

## PER-IDEA DETAIL

### 1. Small-landlord unit-turn / vacancy-days coordination

- **search = 1 × conf low = 0.50.** Evidence is a dense named vendor
  category (NetVendor, HappyCo, Rent Ready, Lula) and two vendor-blog
  savings claims ("$1,200-$2,400 per unit" / "$2,200+ in vacancy loss,"
  lula.life/articles/apartment-make-ready-checklist) that disagree with each
  other — marketing-estimate quality, not measurement. r/PropertyManagement
  is a modest 71,176 members (reddapi.dev, via snippet). No Trends read for
  any candidate in this harvest (429 error) — universal cap. Confidence low:
  mostly vendor-sourced, one secondary community-size figure.
- **jobs = 2 × conf med = 1.60.** SimplyHired measured: 122-135 jobs for
  "Make Ready Coordinator" / "apartment turnover coordinator"
  (simplyhired.com/search?q=Make+Ready+Coordinator, 2026-10-01), real wages
  $18-27/hr, one posting (KLDR Property Management) naming the exact wedge
  task: *"scheduling vendors, turnovers and repairs."* Broader Indeed
  figures (23k-29k) were flagged by the jobs agent as implausible
  title-expansion and excluded. Dedicated title exists but volume is modest
  and likely undercounted (task often folded into generic PM titles).
- **pain = 2 × conf med = 1.60.** 3 distinct recent primary complaints
  across 2 venues: BiggerPockets forum (*"Coordinating maintenance with
  vendors and tenants... more back-and-forth text threads than I can
  count,"* Parris Taylor, 2025-06-23) and an AppFolio App Store review
  naming work-order/photo-attachment friction (StotleZ, 2026-09-01). Recent
  (through 2026-09), on-target, but only 3 sources — not "many."
- **competitors = 2 × conf med = 1.60.** Property Meld verified via direct
  Capterra fetch: 38 reviews, 3.9/5, with recurring substantive complaints
  (*"beware of the 12 month contract...they refuse to terminate,"* Troy D.,
  2023-12-12; *"taken hours to try to make it work well with our current
  system,"* Angela L., 2024-04-10 — the exact PM-system-integration friction
  the wedge targets). Latchel is well-funded ($50.93M total, F-Prime Capital
  blog) but its "4.8/5 satisfaction" is self-reported. Crowded-with-a-
  weak-incumbent read, but only one vendor fully verified; SmartRent/HappyCo/
  Updater/ShowMojo unchecked.
- **Arithmetic:** weighted = .15×0.50 + .35×1.60 + .20×1.60 + .30×1.60
  = 0.075 + 0.560 + 0.320 + 0.480 = **1.435 ≈ 1.44**

### 2. Small-fleet detention capture & auto-invoicing

- **search = 2 × conf low = 1.00.** 3+ dedicated vendors naming small
  carriers (ChargeGuard, DetentionIQ "for 50-200 truck carriers,"
  detentioniq.com) and the largest subreddit found in the whole harvest
  (r/Truckers, 351,491 members, reddapi.dev). One primary-but-old government
  figure: FMCSA advisory-committee notes citing detention as *"more than 3
  billion dollars in waste to the industry and over 6 billion dollars to
  society"* (fmcsa.dot.gov PDF, undated, "likely an older estimate
  re-surfaced"). Confidence low: core claim rests on vendor positioning plus
  an undated figure, not a volume measurement.
- **jobs = 0 × conf low = 0.00.** The jobs agent's own words: *"the honest
  'weak/none found' case... no distinct, separately-posted job title"* for
  detention capture/invoicing. The 4,137 "detention trucking" and 463
  "freight billing specialist" SimplyHired counts are broad adjacent titles;
  read postings (Mantua, OH billing/settlement specialist, $19-20/hr) never
  named detention specifically. No dedicated paid headcount line found.
- **pain = 2 × conf med = 1.60.** 3 distinct recent primary complaints,
  TruckersReport forum (×2 threads) + Samsara Driver App Store: *"TQL were
  masters at NOT paying detention... I finally blocked their phone calls
  entirely,"* FloridaRetired, 2026-05-26; a companion poll shows 53.8% say
  claims are denied because carriers are simply ignored/out-hassled.
  Recent, vivid, but 3 sources only.
- **competitors = 1 × conf low = 0.50.** DockClaim (dockclaim.com) is a
  near word-for-word match to the wedge (geofenced capture + auto-invoicing)
  and Vektor TMS already ships a "clock starts on arrival, auto-invoice at
  the contractual hour mark" feature priced for 1-25-truck carriers — so
  it's not an empty niche — but **zero** review-platform pages were
  successfully fetched (two attempts), the one number found (Vektor TMS
  "5.0/5, 8 reviews") is an unverified search snippet, and zero verbatim
  complaints were recovered. Real competing products exist; their strength
  is unverifiable from this pass.
- **Arithmetic:** weighted = .15×1.00 + .35×0.00 + .20×1.60 + .30×0.50
  = 0.150 + 0.000 + 0.320 + 0.150 = **0.62**
- **Tension to flag:** decent search + pain, but literally zero job-posting
  budget signal and thin competitor verification — money signals (jobs,
  competitors) disagree sharply with the words/voice signals here.

### 3. Vet-clinic documentation / records layer on PIMS

- **search = 1 × conf low = 0.50.** Burnout stat ("over 50% of
  veterinarians experience high levels of burnout," co.vet citing a 2022
  Merck study) is secondary and a few years old. Vendor category exists
  (Scribenote, Scribvet, CoVet, PetDesk — vendor-sourced). The
  professionals-only community proxy, r/veterinaryprofession, is only
  31,213 members/360 posts (reddapi.dev) — smaller than expected for a
  "top driver of burnout" framing; r/AskVet's 413K is an imperfect
  pet-owner-mixed proxy from an uncorroborated listicle.
- **jobs = 3 × conf med = 2.40.** SimplyHired measured 227 jobs for
  "Veterinary Scribe" (simplyhired.com/search?q=veterinary+scribe,
  2026-10-01), salary band $25-30/hr (Pender Veterinary Centre), posted by
  both independent single-doctor clinics and a large chain (VCA/Ethos/Mars),
  plus a third-party staffing vendor (ScribeAmerica) actively placing —
  multiple independent signs of a recurring, budgeted role, not a one-off.
  Tightest, cleanest title-match volume of the seven alongside C5/C6.
- **pain = 0 × conf low = 0.00.** Pain agent's own words: *"Distinct recent
  complaints: 0 recent found... came up sparse."* The one strong quote
  (*"constantly behind on charts... 30 or more that she takes home to
  work on, never gets to them"*, forums.studentdoctor.net) is from 2016 and
  explicitly excluded as pre-window; reddit returned zero results across two
  attempts.
- **competitors = 2 × conf med = 1.60.** Talkatoo verified via direct
  Capterra fetch: 221 reviews, 4.7/5 (capterra.com/p/198507/Talkatoo) — a
  strong, well-reviewed incumbent, not a weak one. ScribbleVet's acquisition
  by PIMS vendor Instinct Science (2026-01-16) is a verified, dated
  consolidation event. Crowded-and-growing read, but zero verbatim weakness
  quotes recovered (G2 blocked) and 3 of 4 named vendors rest on unfetched
  listicle summaries.
- **Arithmetic:** weighted = .15×0.50 + .35×2.40 + .20×0.00 + .30×1.60
  = 0.075 + 0.840 + 0.000 + 0.480 = **1.395 ≈ 1.40**
- **Tension to flag:** strong jobs signal, essentially zero pain-voice
  evidence in this pass — the underlying pain is plausible (burnout is
  well-attested in secondary/vendor sources) but unverified first-person in
  the accessible venues checked.

### 4. Dental insurance-verification + denial follow-up

- **search = 2 × conf med = 1.60.** The search agent's own read: *"the
  cleanest signal of the seven."* Two independently-dated incumbent
  practice-management-vendor product launches in the last ~10 months
  targeting exactly this wedge — VideaHealth "AutoVerify"
  (businesswire.com, 2026-01-14) and Planet DDS "AutoEligibility" for
  Denticon (2025-11-18) — real, dated, named-URL facts that incumbents
  believe there's enough demand to ship native features. Per-patient time
  cost ("12 to 13 minutes per patient," outsourcestrategies.com) is
  vendor-estimate. r/Dentistry's 166K figure is secondary/unconfirmed
  (gummysearch fetch failed, HTTP 500).
- **jobs = 2 × conf med = 1.60.** SimplyHired's 6,101 for "dental insurance
  verification" is measured but overbroad (mixes in general medical
  verification roles on inspection). The dental-specific slice — Indeed,
  822 jobs for "dental insurance verification specialist" — is tighter but
  estimate-tier (via WebSearch, not direct fetch). Salary band $16-23/hr
  (ZipRecruiter) is consistent with the broader, well-evidenced insurance-
  verification/follow-up admin role.
- **pain = 2 × conf med = 1.60.** 2 distinct recent primary complaints, both
  from Open Dental's own forum — the exact incumbent PMS named in the
  candidate: *"errors come from the transfer of the info into open
  dental... creates a collection issue if they need to chase down payment
  or give a refund"* (Papilla, opendentalsoft.com, 2026-02-01); a claim
  rejected for "missing information" that wasn't actually missing (Toni
  DeFazio, 2026-09-16). Both squarely on-wedge, both 2026, but single venue.
- **competitors = 3 × conf med = 2.40.** Zuub verified via direct Capterra
  fetch: 38 reviews, 4.7/5, 95% positive, real pricing ($299/user/mo,
  capterra.com/p/200040/Zuub). Vyne Trellis also directly fetched
  (SourceForge, 1 review, 1.0/5: *"Nobody can help you... Passes you around
  over and over,"* 2025-03-13). Four distinct operating vendors confirmed
  (Zuub, Vyne Trellis, DentalXChange, pVerify); where review volume exists,
  satisfaction is high — not an empty or obviously weak field, but real,
  measured, and crowded-and-growing, with two vendors independently
  verified by direct fetch (the strongest competitor verification depth of
  the seven).
- **Arithmetic:** weighted = .15×1.60 + .35×1.60 + .20×1.60 + .30×2.40
  = 0.240 + 0.560 + 0.320 + 0.720 = **1.84**

### 5. Hourly / blue-collar high-volume applicant screening

- **search = 1 × conf low = 0.50.** Applicant-volume growth stat ("doubled
  since 2021... 207% increase in business role applications,"
  gbdtalent.substack.com) is an unverified secondary newsletter figure. The
  vendor category is the most saturated of the seven (Workstream, Fountain,
  Paradox/Olivia, HigherMe — all vendor-sourced self-reported customer
  counts). r/humanresources ~236-240K members is a cross-validated secondary
  figure (two snippets agree within 1.5%) — the one solid data point, but
  the rest is vendor/listicle, pulling confidence to low per the override
  rule.
- **jobs = 3 × conf high = 3.00.** SimplyHired measured 2,178 jobs for
  "high volume recruiter" (simplyhired.com/search?q=high+volume+recruiter,
  2026-10-01) — the largest clean measured count in the harvest for a tight
  query. Real employers across the target profile (a contract role
  explicitly described as supporting *"high-volume US hiring for hourly
  roles including field service, warehouse, call center,"* $25-30/hr),
  salary spread from $25/hr contract to $100k+ ops roles. The jobs agent's
  own read: *"the clearest, most directly-matching signal of the seven
  candidates."*
- **pain = 1 × conf low = 0.50.** Pain agent found 0 solid primary sources;
  the single quote counted is secondhand (*"hiring managers... say they are
  overwhelmed with hiring because of the amount of spam,"* trod1234,
  news.ycombinator.com, 2025-07-29 — reporting what managers told him, not
  his own role). Reddit (r/recruiting, r/humanresources,
  r/KitchenConfidential) returned zero results across every attempt.
- **competitors = 3 × conf low = 1.50.** Three well-funded, well-staffed
  incumbents already sell directly into this niche: Fountain ($219M raised,
  251-500 employees), Paradox/Olivia (501-1000 employees), Workstream
  (101-250 employees) — the most clearly crowded, most clearly funded
  candidate in the set per the competitors agent. But **both** G2
  fetch attempts returned HTTP 403, so every rating/review figure is
  search-engine synthesis rather than a directly-read page, and zero
  verbatim complaints were sourced — confidence low despite a score of 3.
  Note: a high competitors score here is *bad* news for a new entrant
  (crowded field), not good news — it should not be read the same way a
  high competitors score reads for, e.g., C4.
- **Arithmetic:** weighted = .15×0.50 + .35×3.00 + .20×0.50 + .30×1.50
  = 0.075 + 1.050 + 0.100 + 0.450 = **1.675 ≈ 1.68**
- **Promising-but-unproven:** 3rd-highest weighted score, but overall
  confidence is LOW (competitors unverified, pain near-absent, search
  vendor-heavy). The strong jobs number is real and high-confidence, but it
  is evidence of *recruiter* headcount, not proof that small/med employers
  would buy a *new* screening tool rather than use what Fountain/Paradox/
  Workstream already sell them.

### 6. Specialty / post-acute prior-auth + denial-appeal packets

- **search = 2 × conf med = 1.60.** The two highest source-quality facts in
  the entire harvest: AMA physician survey, confirmed via direct fetch —
  *"practices complete 39 prior authorization requests per physician, per
  week"* and *"spend an average of 13 hours completing those requests each
  week"* (ama-assn.org, survey late 2024); and an HHS OIG report, confirmed
  via direct fetch — *"Medicare Advantage Organizations collectively
  overturned 36 percent of LTCH denials and 43 percent of IRF denials"*
  (oig.hhs.gov, 2026) — a segment-specific stat matching the candidate's own
  framing almost exactly. r/CodingandBilling confirmed at 35,500 members
  (direct fetch, reddapi.dev). Capped at med (not high) because, as the
  search agent notes, none of this is a direct measurement of *search*
  behavior — it's problem-prevalence evidence, adjacent to but not the same
  thing.
- **jobs = 3 × conf high = 3.00.** SimplyHired measured: 2,935 "prior
  authorization specialist" + 1,697 "appeal/denial specialist"
  (simplyhired.com, 2026-10-01), salary $20-37/hr to $78-85k/yr, and one
  posting directly from a post-acute chain in the named segment: "Clinical
  Review and Appeals Specialist," Life Care Centers of America — an exact
  segment hit, not an inferred analogy.
- **pain = 2 × conf med = 1.60.** 2 distinct recent primary complaints, AAPC
  billing/coding forum: *"We submit authorization for 97162, and 97110.
  They void the authorization on 97162 and approve 97110... That seems like
  fraudulent billing to us,"* Cassi3434, 2025-07-12; a denial-appeal
  workflow complaint from JDACPC, 2025-07-15. Caveat: both are general
  outpatient therapy/surgery contexts, not confirmed inpatient-rehab/LTCH
  specifically — same pain, unconfirmed exact segment.
- **competitors = 1 × conf low = 0.50.** Cohere Health ($200M+ raised),
  Rhyme ($25M+ raised), and Myndshft are all well-funded, enterprise,
  **payer-agnostic** PA/UM vendors — none found branding specifically around
  inpatient-rehab/LTCH/post-acute appeal packets, the exact narrow segment
  named in the candidate. Both G2 fetch attempts returned HTTP 403, zero
  verbatim complaints recovered, and — critically — no post-acute-specific
  competitor search was completed within budget. "Crowded-but-
  niche-unclaimed" per the competitors agent, which maps to "ambiguous/thin"
  (score 1), not "clear wedge" (score 3): the general category is crowded,
  but we genuinely don't know if the narrow wedge is open or just unsearched.
- **Arithmetic:** weighted = .15×1.60 + .35×3.00 + .20×1.60 + .30×0.50
  = 0.240 + 1.050 + 0.320 + 0.150 = **1.76**
- **Promising-but-unproven:** 2nd-highest weighted score, driven by the
  single best-sourced search evidence and the strongest jobs evidence in
  the harvest, but overall confidence is LOW because the competitors signal
  for this specific narrow niche is unverified, not verified-open — the
  biggest unknown is literally "does a post-acute-specific competitor
  already exist," and this pass could not answer that either way.

### 7. Schedule C client record-gathering for tax preparers

- **search = 1 × conf low = 0.50.** The one potentially-strong figure
  (Wolters Kluwer survey: tax/accounting pros rank "late and unprepared
  clients" as their #1 challenge) could **not** be directly fetched (both
  URLs returned HTTP 403) and is reported via search-synthesis only — the
  search agent explicitly downgrades it for this reason. Vendor category
  exists (Sliq360, Dokutrak, Fast.io, Superdocu — vendor-sourced).
  r/taxpros' ~90,718 members is an unconfirmed snippet figure, and no actual
  thread-level discussion was surfaced to confirm it's a live topic there.
- **jobs = 0 × conf low = 0.00.** Jobs agent's own words: *"the other
  honest 'thin' case... No job board returns a dedicated title for 'chase
  small-business clients for missing Schedule C documents.'"* The tightest
  on-task query ("tax preparer bookkeeper") returns only 71 jobs and is
  itself a generalist title, not a document-chasing-specific one; whatever
  budget exists is bundled into existing bookkeeper/tax-preparer salaries.
- **pain = 2 × conf med = 1.60.** 2 distinct recent primary complaints
  across 2 venues: Intuit Accountants Community practice-advice thread
  (*"Manual entry of the brokerage 1099s is very time consuming — My
  backlog is usually full by mid-March,"* ptax255, 2026-04-24) and TaxDome
  App Store reviews about missed client-document notifications (2026-08-31).
  Both on-target for the document-chasing/client-communication wedge.
- **competitors = 1 × conf low = 0.50.** TaxDome, Canopy, and Liscio are
  established generalist practice-management suites that bundle
  document-collection as one feature among many — but **every** primary
  review page was unreachable (G2 403, Capterra 404 for all three), so
  pricing/rating/weakness data is entirely secondary-listicle-synthesis or
  unconfirmed search-snippet quotes (explicitly flagged by the competitors
  agent as lower-confidence than primary). The most solid single finding
  from this pass was a naming collision (Keeper.app → Double, distinct from
  the unrelated consumer app Keeper Tax) — not demand evidence.
- **Arithmetic:** weighted = .15×0.50 + .35×0.00 + .20×1.60 + .30×0.50
  = 0.075 + 0.000 + 0.320 + 0.150 = **0.55**
- **Tension to flag:** real, recent, on-target pain-voice evidence, but
  zero job-posting budget signal and zero verified competitor data —
  money signals are the weakest of all seven candidates here.

---

## RANKING

| Rank | Idea | weighted_score | overall confidence |
|---|---|---|---|
| 1 | Dental insurance-verification + denial follow-up | 1.84 | HIGH |
| 2 | Post-acute prior-auth + denial-appeal packets | 1.76 | LOW (promising-but-unproven) |
| 3 | Hourly/blue-collar applicant screening | 1.68 | LOW (promising-but-unproven) |
| 4 | Unit-turn / vacancy-days coordination | 1.44 | HIGH* |
| 5 | Vet-clinic documentation layer | 1.40 | LOW |
| 6 | Detention capture & auto-invoicing | 0.62 | LOW |
| 7 | Schedule C record-gathering (tax) | 0.55 | LOW |

No ties arose, so the jobs-score/confidence tie-break was not needed.

---

## RECOMMENDATION

**Advance #1 — Dental insurance-verification + denial follow-up.** The only
candidate with HIGH overall confidence *and* the top weighted score, with no
weak leg: two independently-dated incumbent-vendor product launches
(VideaHealth AutoVerify, Planet DDS AutoEligibility) proving vendor-side
demand belief, a directly-verified paid competitor (Zuub: 38 reviews, 4.7/5,
$299/user/mo) proving willingness-to-pay exists in this exact category, and
two 2026-dated primary complaints from Open Dental's own forum confirming
the manual-entry/claim-rejection pain. **Biggest unknown:** the
dental-*specific* job-posting volume (822) is estimate-tier, not measured,
and it's unclear whether Zuub/Vyne Trellis already cover the "denial
follow-up" half of the wedge as well as they cover "eligibility checks" —
cheap check: a handful of calls to independent Open Dental/Dentrix offices
asking specifically what they use for denial follow-up (not just
verification) would resolve this before spending on Rung 1.

**Advance #2 (with a caveat) — Post-acute prior-auth + denial-appeal
packets.** 2nd-highest score, carried by the single best-sourced evidence in
the whole harvest (AMA: 39 PA requests/physician/week, 13 hrs/week; HHS OIG:
36%/43% LTCH/IRF denial-overturn rates) and the strongest jobs signal
(2,935 + 1,697 measured postings, one direct hit at Life Care Centers of
America). **This is explicitly promising-but-unproven, not a clean pick**:
overall confidence is LOW because the competitors signal never got a
post-acute-specific check — we know the general PA/UM space is crowded
(Cohere Health, Rhyme, Myndshft, all enterprise/payer-agnostic) but do not
know whether the *narrow* LTCH/IRF-specific wedge is open or already
quietly claimed. Cheap check before committing Rung-1 budget: a direct,
non-blocked search (Capterra/Trustpilot rather than G2) specifically for
"LTCH," "inpatient rehab," or "post-acute" named PA/appeals vendors, plus 2-3
conversations with post-acute billing managers about what they already use.

**Also notable, not recommended yet — Hourly/blue-collar applicant
screening.** 3rd-highest score on the strength of a very strong jobs signal
(2,178 measured postings, the clearest title-match in the harvest), but
overall confidence is LOW across three of four signals, and critically the
competitors signal — even though unverified by direct fetch — already shows
three well-funded incumbents (Fountain $219M raised, Paradox 500-1000
employees, Workstream) selling directly into this exact niche. Unlike C6,
where the unknown is "is the narrow wedge open," here the broad signal
already points to "no, it's not" — this is closer to a reasoned pass than a
promising unknown, but it is not being dropped outright because the
competitor data itself is unverified (G2 blocked both times).

**Drop — Detention capture & auto-invoicing, and Schedule C
record-gathering.** Both share the same disqualifying pattern: **no
budget signal** (jobs = 0 for both — the jobs agent's own words call both
"the honest weak/none found case," with the underlying task folded into
generic biller/bookkeeper titles rather than separately budgeted headcount)
*and* the weakest, least-verified competitor data (both score 1, confidence
low, no primary review-platform fetch succeeded for either). Decent
pain-voice evidence exists for both (score 2 each), so the underlying
problems are real — but with zero evidence anyone has a dedicated budget
line for solving them and zero verified picture of who else is already
trying, these are the two to deprioritize for paid validation.

---

## LIMITATIONS

Rung 0 is desk evidence (search proxies, job-ad text, forum/app-review
words) — it is not observed paid behavior. Nothing here confirms anyone
would actually buy a new tool; it only triangulates that a problem, a
vocabulary, and in some cases a budget line exist.

Specific limitations that could change the picture:

- **Google Trends was unreachable for every candidate** (one attempt
  returned HTTP 429); every search score in this scorecard is therefore
  capped well below what a real rising/flat-interest read would allow,
  across all seven candidates equally. This is a tooling gap, not a finding
  of flat interest.
- **Reddit could not be fetched directly** for any candidate; every
  subreddit-size figure above comes from a third-party index (reddapi.dev)
  or listicle, reached mostly via WebSearch snippets rather than a
  confirmed direct fetch. Community *size* is not community *activity* —
  none of these figures confirm the problem is actively, recently discussed
  at volume inside the subreddit itself.
- **G2 — likely the richest competitor-review source — returned HTTP 403
  on every attempt** for candidates 2, 5, 6, and 7. This directly weakens
  the two "promising-but-unproven" picks (C5, C6): their competitors scores
  rest on funding/headcount facts and search-engine synthesis, not a single
  directly-fetched review page, for either.
- **Job-board counts vary by orders of magnitude** depending on query
  wording (e.g., C1's tight "Make Ready Coordinator" = 122-135 vs. loose
  "turnover coordinator" = 23k-29k, excluded as implausible). The tight
  counts used here may still *undercount* true demand that's folded into
  generic titles — this cuts against C1, C2, and C7 specifically, all of
  which explicitly show the target task absorbed into broader roles.
- **Pain-voice sample sizes are small everywhere** — 2-3 distinct quotes at
  best per candidate, never "many." Treat every pain score of 2 as "real,
  recent, on-target, but thin," not as validated demand at scale.
- **Shakiest individual scores:** C6's competitors score (1, low) rests on
  zero verified review pages and *no post-acute-specific competitor search
  was ever completed* — it is a genuine "don't know," not a verified-open
  niche, and is the single biggest risk behind the #2 recommendation. C5's
  competitors score (3, low) similarly rests entirely on unverified
  funding/headcount synthesis. C3's pain score (0) and C2/C7's jobs scores
  (0) are confident absences within the venues checked, but all three
  signal agents explicitly note the underlying pain/budget could still
  exist outside what was searched in this pass.
