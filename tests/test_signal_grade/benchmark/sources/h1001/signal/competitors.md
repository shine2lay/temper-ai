# Competitor Vitals — Rung-0 Demand Validation

Signal: COMPETITOR-VITALS. Research only — no ranking, no recommendation.
Each candidate below was researched independently (fresh search/fetch per
candidate) against the shortlist from `temper scan_market` (2026-10-01
snapshot). Figures are tagged **measured** (seen directly on a real page) or
**estimate** (traffic/install/share guess, or a number only seen via a
search-engine snippet rather than a directly fetched page), and by
**source_quality**: primary | secondary | vendor | listicle. Several review
platforms (G2 in particular) returned HTTP 403 to direct fetch during this
pass — those figures are marked accordingly and should be treated as
lower-confidence until re-verified.

---

## Candidate 1 — Small-landlord unit-turn / vacancy-days coordination (property management)

**Incumbents named:** Property Meld (direct hit — maintenance/vendor-dispatch
coordination for PM firms), Latchel (funded, overlapping maintenance-ops
model, different pricing structure), Lula (managed-service vendor network,
not pure SaaS), Turnify (off-target — short-term-rental cleaning, not
AppFolio/Buildium make-ready). SmartRent, HappyCo/Rently, Updater, ShowMojo
were not reached within budget — treat as unverified, not absent.

| Vendor | Reviews | Rating | Pricing | Funding/Headcount | Traffic/Installs | Tag | Source | URL | Date |
|---|---|---|---|---|---|---|---|---|---|
| Property Meld | 38 (Capterra) | 3.9/5 (value sub-score 3.5/5, n=24) | From $62/mo, usage-based per-unit | not found | not found | measured (rating); estimate (pricing, secondary) | primary (Capterra) / secondary (pricing via softwarefinder.com) | https://www.capterra.com/p/149045/Property-Meld/reviews/ | 2026-10-01 |
| Latchel | not found on G2/Capterra | "4.8/5 resident satisfaction" (self-reported, not a review-platform score) | Free to PM firm; tenant pays $15-18/mo | $50.93M total raised; $16.7M Series A (F-Prime Capital) | not found | measured (funding); vendor (satisfaction score, self-published) | primary (F-Prime blog) / vendor (latchel.com) | https://www.fprimecapital.com/blog/latchel-the-operating-system-for-property-management/ | 2026-10-01 |
| Lula | not found | not found | "Flat-rate," no published $ | not found | "9,000+ vetted pros, 50+ markets" (vendor claim) | estimate | vendor | https://lula.life/make-ready-service | 2026-10-01 |
| Turnify | 1 review (Capterra) | 1.0/5 | $12/mo starting, 60-day trial | not found | not found | measured | primary (Capterra) | https://capterra.com/p/253601/Turnify/ | 2026-10-01 |

**1-star / low-rating weaknesses (verbatim):**
- "Run don't walk. This company is cut throat and awful...There is NO 30 day guarantee and there is NO satisfaction guarantee." — Deanna C., Owner, Property Meld, Capterra, 2025-04-17 (primary)
- "During our first on-boarding meeting we realized that the product did not work as pitched." — Dustin N., Owner, Property Meld, Capterra, 2022-12-06 (primary)
- "As others have stated - beware of the 12 month contract...they refuse to terminate the contract." — Troy D., Managing Partner, Property Meld, Capterra, 2023-12-12 (primary)
- "It has taken hours to try to make it work well with our current system." — Angela L., Senior Property Management, Property Meld, Capterra, 2024-04-10 (primary) — names the exact PM-system integration friction the wedge targets.

**Read:** Crowded-but-weak-incumbents. Property Meld is the clearest direct incumbent, mid-rated (3.9/5) with recurring, substantive gripes (12-month contract lock-in, broken onboarding-vs-pitch gap, AppFolio integration pain). Latchel is well-funded ($50.93M) but its satisfaction metric is unverified self-report — real strength unknown. No incumbent found that headlines "vacancy-days / lost rent during turn" specifically — a gap, but given Latchel's capital and Property Meld's incumbency this is contested, not empty, territory.

**Confidence: medium** — one verified direct competitor with real review/complaint data; Latchel's strength plausible but unverified; SmartRent/HappyCo/Updater/ShowMojo unchecked, so the full landscape is likely larger than what surfaced.

---

## Candidate 2 — Small-fleet detention capture & auto-invoicing (trucking)

**Incumbents named:** DockClaim (near-identical wedge match — GPS geofencing, passive detention capture, auto-invoicing, targeted at small/independent carriers), Vektor TMS (tiered per-truck pricing with detention auto-invoice feature), Vector (withvector.com, named only in a listicle), Samsara (dwell-time feature inside a much larger TMS/telematics platform, not a dedicated product). Outgo, Trucker Tools' dedicated detention product, Motive/KeepTruckin and Revenova/Parade detention features, and Rose Rocket were not independently verified within budget.

| Vendor | Reviews | Rating | Pricing | Funding/Headcount | Traffic/Installs | Tag | Source | URL | Date |
|---|---|---|---|---|---|---|---|---|---|
| Vektor TMS | 8 (snippet) | 5.0/5 (snippet) | $30/mo (1-25 trucks) → $24/mo (500+), free trial | not found | not found | **estimate** (search-snippet only, not a directly fetched page) | secondary | https://www.capterra.com/p/10014344/Vektor-TMS/ | 2026 |
| DockClaim | not found | not found | not found (not published) | not found | not found | n/a — no data located | n/a | https://dockclaim.com/compare/detention-tracking-software | 2026 |
| Vector | not found | not found | not found | not found | not found | n/a | vendor (named in listicle) | https://www.withvector.com/blog/logistics-apps-the-only-list-you-need-to-find-the-right-one/ | n/a |
| Samsara (detention feature) | not found | not found | not found | publicly traded, large (not re-verified here) | not found | n/a | listicle/vendor | https://www.torotms.com/blog/driver-detention-management-software | 2026-08-17 |

**1-star / low-rating weaknesses (verbatim):** **Not found.** No actual review-platform page (G2/Capterra/Trustpilot/App Store) could be fetched with verbatim 1-star text within budget; the only "weakness" language found was a competitor's own marketing blog characterizing Samsara ("detention billing and charge automation typically happen outside the platform" — torotms.com, 2026-08-17), which is vendor-sourced positioning, not a user complaint, and is not counted as a weakness quote.

**Read:** Crowded-but-weak-incumbents (tentative, low confidence). DockClaim's own product description is nearly a word-for-word match to the candidate's wedge, and Vektor TMS already ships a "clock starts on arrival, auto-invoice at the contractual hour mark" feature priced for 1-25-truck carriers — so this is **not** an empty niche. But neither incumbent has a visible review footprint, which could mean low traction/awareness (an opening) rather than strength. General TMS/ELD giants treat detention as a secondary, manual feature, leaving room for a dedicated player — but that lane already has at least two entrants.

**Confidence: low** — no review-platform page was successfully fetched directly (two attempts); the one number found (Vektor TMS 5.0/8 reviews) is an unverified snippet, not a measured figure; zero verbatim complaints recovered.

---

## Candidate 3 — Vet-clinic documentation / records layer on PIMS (veterinary)

**Incumbents named:** Talkatoo (vet-specific dictation/voice-to-text with templates — closest verified incumbent, though it's dictation-on-demand rather than fully passive ambient capture), ScribbleVet (closer ambient-capture analog; recently acquired), Scribenote, CoVet. Vetology, VetRocket, Covetrus, VitusVet, Rhapsody AI, Otterbot, Vetsource were not independently verified within budget.

| Vendor | Reviews | Rating | Pricing | Funding/Headcount | Traffic/Installs | Tag | Source | URL | Date |
|---|---|---|---|---|---|---|---|---|---|
| Talkatoo | 221 (Capterra) | 4.7/5 | $40/user/mo (1-user tier); ~$50-126/user/mo across SOAP Notes → Ultimate tiers | not found | not found | measured (Capterra) / estimate (tier breakdown, listicle) | primary (Capterra) / listicle (vetsoftwarehub) | https://www.capterra.com/p/198507/Talkatoo/pricing | 2026 |
| ScribbleVet | not found | not found | not found | Acquired by Instinct Science, 2026-01-16; deal value undisclosed | not found | estimate | secondary (deepcura.com) | https://www.deepcura.com/resources/best-ai-scribe-for-veterinarians | 2026 |
| Scribenote | not found | not found | Free tier (capped) + paid plans, exact price not fetched | not found | not found | estimate | listicle/secondary | https://www.deepcura.com/resources/best-ai-scribe-for-veterinarians | 2026 |
| CoVet | not found | not found | not found | not found | not found | n/a | listicle | https://co.vet/post/veterinary-ai-scribe | 2026 |

**1-star / low-rating weaknesses (verbatim):** **Not found.** G2 (likely richest source) returned HTTP 403 on fetch. A search-result summary paraphrased recurring Talkatoo complaint themes ("transcription errors needing manual dosage review," "iPad/iPhone lockups mid-use") but these are paraphrases, not verbatim quotes, so they are excluded per evidence discipline.

**Read:** Crowded-and-growing, moderate confidence. At least 6 SEO listicles actively rank/compare veterinary AI-scribe vendors in 2026 (category-heat proxy). Talkatoo shows a large, high-sentiment review base (221 reviews, 4.7/5, ~98% positive per Capterra) — not a weak incumbent. ScribbleVet's acquisition by PIMS vendor Instinct Science (Jan 2026) signals active consolidation, i.e. incumbents being absorbed/strengthened, arguing against "thin-or-none."

**Confidence: low-medium** — only Talkatoo was independently verified via a fetched page; ScribbleVet/Scribenote/CoVet rest on unfetched listicle summaries; zero verbatim weakness quotes recovered. Directional signal (crowded, consolidating, leader well-reviewed) is consistent across multiple independent sources, which lifts confidence slightly.

---

## Candidate 4 — Dental insurance-verification + denial follow-up (dental)

**Incumbents named:** Zuub (direct hit, strong review base), Vyne Trellis/Vyne Dental (direct hit, thin review base), DentalXChange, pVerify. Listicles also named Needletail AI, CareStack, Sikka, ClaimScore as adjacent players (not independently verified).

| Vendor | Reviews | Rating | Pricing | Funding/Headcount | Traffic/Installs | Tag | Source | URL | Date |
|---|---|---|---|---|---|---|---|---|---|
| Zuub | 38 (Capterra) | 4.7/5 (95% positive, 3% neutral, 3% negative) | $299/user/mo, no free trial | not found | not found | measured | primary (Capterra) | https://www.capterra.com/p/200040/Zuub/ | accessed 2026-10-01; reviews through Mar 2026 |
| Vyne Trellis | 1 (SourceForge) | 1.0/5 | not found (listicle claims "unlimited monthly fee," no figure verified) | not found | not found | measured (but n=1, statistically thin) | primary (SourceForge) | https://sourceforge.net/software/product/Vyne-Trellis/ | review posted 2025-03-13 |
| DentalXChange | not found | not found | not found; listicle claims "lowest cost," no figure | not found | not found | estimate (listicle) | listicle | https://www.dentalclaimsupport.com/blog/top-dental-insurance-verification-software | 2026 |
| pVerify | not found | not found | not found | not found | not found | n/a — EDI 270/271 + API description only | listicle | same as above | 2026 |

**1-star / low-rating weaknesses (verbatim):**
- "Nobody can help you" (title); "Tech support cannot help solve problems. many many phone calls for one solution. Passes you around over and over." — Vyne Trellis, SourceForge, 2025-03-13 (primary; caveat: this is the product's only review, n=1)
- "There are too many connection errors when the websites are working." — Annie G., Insurance Co-Ordinator, Zuub, Capterra, 2026-03-19, 3-star review (primary)
- "Wish Zuub had access to ALL insurance payers and could populate treatment history." — Zuub, Capterra cons aggregation (primary)

**Read:** Crowded-and-growing. At least 4 distinct operating vendors confirmed, plus several more named in listicles. Where review volume actually exists (Zuub, n=38), satisfaction is high (4.7/5) — not a weak-incumbent signal. Vyne Trellis's 1.0 rating is real but rests on a single review about support hold-times, not core eligibility-check accuracy — too thin to call the incumbent weak overall. Low review counts across the board (max 38) likely reflect a modest-visibility B2B dental-vertical niche rather than absence of competition.

**Confidence: medium** — Zuub's figures are directly fetched/measured from a primary review platform; Vyne Trellis measured but n=1; DentalXChange/pVerify rest entirely on listicle characterization.

---

## Candidate 5 — Hourly / blue-collar high-volume applicant screening (recruiting)

**Incumbents named:** Fountain, Paradox (Olivia), Workstream — all well-funded, multi-hundred-employee vendors already selling into this exact niche. Sense returned no verifiable data this pass.

| Vendor | Reviews | Rating | Pricing | Funding/Headcount | Traffic/Installs | Tag | Source | URL | Date |
|---|---|---|---|---|---|---|---|---|---|
| Fountain | 127 (search synthesis) | 4.3/5 | not found ("contact sales") | $219M raised (Series C); 251-500 employees | not found | **estimate** (G2 direct fetch returned 403; figures are search-engine synthesis, not a page I read) | secondary | https://www.g2.com/products/fountain/reviews | 2026 |
| Paradox (Olivia) | not found | ~4.7/5 (one aggregator claim, unconfirmed) | not found ("contact sales," long implementation per write-ups) | 501-1000 employees (Crunchbase synthesis); funding $ not found | not found | estimate | secondary | https://www.crunchbase.com/organization/paradox-olivia | 2026 |
| Workstream | 61 (search synthesis) | 4.7/5 | not found (tiered by location count per write-ups) | 101-250 employees (Crunchbase synthesis); funding $ not found | not found | estimate | secondary | https://www.g2.com/products/workstream-workstream/reviews | 2026 |
| Sense | not found | not found | not found | not found | not found | n/a | n/a | n/a | n/a |

**1-star / low-rating weaknesses (verbatim):** **Not found.** G2 blocked direct fetch (403 on both Fountain and Workstream review pages), so no verbatim quotes could be sourced. (A search-engine paraphrase suggested "integration limitations/difficult calendar scheduling" for Fountain and "robotic AI conversations/complex implementation" for Paradox — excluded here as non-verbatim.)

**Read:** Crowded-and-growing. Three well-staffed, well-funded vendors (Fountain ~$219M raised / 250-500 heads; Paradox 500-1000 heads; Workstream 100-250 heads) are already selling specifically into hourly/high-volume screening+scheduling, each with double-to-triple-digit G2 review volume. This is the most clearly crowded, most clearly funded candidate in the set — a thin-wedge entrant would be competing against established ATS integrations and enterprise sales motions, not an empty category.

**Confidence: low** — both G2 fetch attempts returned 403; essentially all figures rest on search-engine synthesis rather than a page directly read; zero verbatim complaints sourced. The directional read (crowded, well-funded) is very likely correct even if exact numbers need re-verification.

---

## Candidate 6 — Specialty / post-acute prior-auth + denial-appeal packets (healthcare RCM)

**Incumbents named:** Cohere Health, Rhyme (per search; possible naming discrepancy with the seed "formerly Para" — unverified), Myndshft. Waystar, Infinitus, AKASA, Banjo Health were not searched this pass. No vendor surfaced that specifically brands around inpatient-rehab/LTCH/post-acute appeal packets — all confirmed players appear to target the general payer-agnostic PA/UM market.

| Vendor | Reviews | Rating | Pricing | Funding/Headcount | Traffic/Installs | Tag | Source | URL | Date |
|---|---|---|---|---|---|---|---|---|---|
| Cohere Health | not found (G2 fetch 403) | 4.4/5 (aggregator, not G2 itself) | not found ("contact sales" implied) | $200M total raised; $90M Series C (reported May 2025) | "~600,000 providers; 12M+ PA requests/yr" (vendor-scale claim) | estimate | secondary (revcycleai.com) / vendor (scale claim) | https://revcycleai.com/blog/cohere-health-vendor-deep-dive/ | 2026 |
| Rhyme | not found (G2 fetch 403) | not found | not found | $25M raised (reported 2022-02-14) | "4M+ PA/yr for 83 of the largest providers" (vendor claim) | estimate | secondary/listicle (CB Insights) | https://www.cbinsights.com/compare/cohere-health-vs-priorauthnow | n/a |
| Myndshft | not found (G2 fetch 403) | 3.5/5 (search snippet of G2 listing — **not independently verified**, direct fetch blocked) | not found | not found | "600+ payer rule sets" (vendor claim) | estimate | secondary (unverified snippet) | https://www.g2.com/products/myndshft/reviews | n/a |

**1-star / low-rating weaknesses (verbatim):** **Not found.** Both WebFetch attempts at G2 (category page and Myndshft reviews) returned HTTP 403. This is a fetch-access gap, not evidence that no complaints exist.

**Read:** Crowded-but-niche-unclaimed (hybrid). The general PA/UM automation space is crowded with well-funded enterprise vendors (Cohere Health $200M+, Rhyme $25M+, Myndshft), all enterprise-priced and payer-agnostic — but none found branding specifically around inpatient-rehab/LTCH/post-acute appeal packets. One strong supporting secondary stat: per an OIG-sourced figure cited in a billing-industry blog, Medicare Advantage plans denied 65% of LTCH and 54% of IRF admission requests reviewed in a 2024 sample, yet 95% of appealed SNF denials were overturned (https://www.onemedbilling.com/blog-details/prior-authorization-statistics, 2026 — secondary, not independently re-verified against the original OIG report). This points toward the post-acute/specialty niche being underserved by name-brand incumbents specifically, even though the broader PA category is well-funded and contested.

**Confidence: low** — both direct-verification fetches were blocked; every rating/funding/review figure traces to search-engine-summarized secondary sources; no post-acute-specific competitor search was completed; zero verbatim review quotes obtained.

---

## Candidate 7 — Schedule C client record-gathering for tax preparers (accounting/tax)

**Incumbents named:** TaxDome, Canopy, Liscio — all generalist tax/accounting practice-management suites that bundle document-collection portals as one feature among many. A naming collision was found: "Keeper.app" (B2B bookkeeping tool) rebranded to "Double"; this is distinct from the unrelated consumer app "Keeper Tax" (keepertax.com) for freelancers — the latter's large review count should not be read as evidence for this B2B niche. SmartVault, Intuit Link/ProConnect, Karbon, Financial Cents, Jetpack Workflow were not researched within budget.

| Vendor | Reviews | Rating | Pricing | Funding/Headcount | Traffic/Installs | Tag | Source | URL | Date |
|---|---|---|---|---|---|---|---|---|---|
| TaxDome | not found (G2 403, Capterra 404) | not found | $800-$1,200/user/yr (Essentials/Pro/Business tiers) | not found | not found | estimate (listicle synthesis, not a directly fetched vendor page) | secondary | taxdome.com (via checkthat.ai synthesis) | 2026 |
| Canopy | not found (G2 403) | not found | $74/$109/$149/user/mo (annual billing) + $432/yr doc-mgmt add-on + $384-480/yr workflow add-on | not found | not found | estimate | secondary (listicle) | canopytax.com (via checkthat.ai synthesis) | 2026 |
| Liscio | not found | not found | Starter $45, Pro $60, Enterprise $75/user/mo (annual) | not found | not found | estimate | secondary (unclekam.com) | liscio.me | 2026 |
| Keeper/Double | ambiguous (one snippet: "6 reviews, 4.0"; another: "4.6/5, 7,874 reviews" — the latter likely conflates with the unrelated consumer app) | not found (conflated, low-confidence) | not found | not found | not found | estimate, low-confidence | secondary (search snippet, not fetched) | capterra.com/p/10012825/Keeper | 2026 |

**1-star / low-rating weaknesses (verbatim, via search-snippet of review pages — not independently fetch-confirmed, so treat as lower-confidence than primary):**
- "If I had known how difficult it was to set up and how poor their support is, I would not have signed on." — TaxDome, Capterra (secondary, date not visible)
- "Getting a TaxDome support person is a long, arduous process. You cannot call a human, only a chat or schedule a 15 minute 1:1 a week out." — TaxDome, Capterra (secondary)
- "Tried to get assistance requesting a phone call, however no one called me" / "Customer Service is Terribly — This Company is too new to meet deadlines." — Canopy, Capterra (secondary)

**Read:** Crowded-but-weak-incumbents (tentative). TaxDome, Canopy, and Liscio are established, multi-tiered practice-management suites competing head-to-head in numerous 2026 comparison listicles; the recurring complaint theme is support/onboarding friction, not a gap in document collection itself. None brands specifically around "proactive Schedule C small-business document chasing" — it's one feature bundled inside generalist suites, suggesting room for a narrower wedge, though confidence in the underlying review/rating data is limited.

**Confidence: low** — primary review-platform pages were unreachable via direct fetch (403/404) for all three main vendors; pricing came from secondary listicles, not confirmed vendor pricing pages; funding/headcount unresearched; the Keeper/Double naming collision itself is the most solid single finding from this pass.

---

## Cross-candidate note on method

Several platforms (G2 especially) returned HTTP 403 on direct WebFetch across multiple candidate passes (trucking, recruiting, RCM, tax). Where this happened, review counts/ratings are flagged **estimate** and sourced from search-engine result synthesis rather than a page actually rendered and read — this is weaker evidence than a direct fetch and is called out per-candidate above rather than smoothed over. Re-verification via a non-blocked path (e.g. Capterra/Trustpilot direct fetch, or a different user agent) would raise confidence on candidates 2, 5, 6, and 7 specifically.
