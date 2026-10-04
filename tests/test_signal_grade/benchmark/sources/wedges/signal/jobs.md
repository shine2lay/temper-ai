# Job-Postings Signal — Rung-0 Demand Validation

Researched 2026-10-01. Method: 15 WebSearches across Indeed/SimplyHired/ZipRecruiter,
then 13 WebFetch attempts on result pages. Direct WebFetch of **Indeed** search-results
pages was blocked (HTTP 403) every time it was tried, consistent with prior runs on this
board — all Indeed figures below therefore come from WebSearch's own extraction of the
page (not a direct fetch by us) and are tagged **estimate / secondary**. **SimplyHired**
search pages fetched successfully and gave **measured** on-page counts (11 successful
fetches). ZipRecruiter was only reachable via WebSearch snippets (estimate/secondary) —
no direct ZipRecruiter fetch was attempted given Indeed's block made a similar block
likely and budget was limited. Each candidate below was researched independently with
fresh queries; no figures were carried over from any prior brief or prior run.

---

## Candidate A (NEW) — Dental denied/underpaid-claim follow-up for Open Dental offices

**Role searched:** "Dental Insurance Coordinator / Claims Specialist", "Dental AR
Follow-Up Specialist", "Dental Billing Specialist" (independent dental practice)

**Counts:**
- SimplyHired, query `dental claims specialist`, **7,241 jobs**, measured, primary, 2026-10-01. https://www.simplyhired.com/search?q=dental+claims+specialist — **caveat: broad title**; first-page results mix general claims-*submission*/billing roles with denial-*chasing* roles, so this overstates the specific follow-up-on-denied-claims task.
- SimplyHired, query `dental insurance claims` (via WebSearch extraction of the same board, since the direct fetch did not surface a clean count heading), **"1,569 jobs"**, estimate, secondary, 2026-10-01. https://www.simplyhired.com/k-dental-insurance-claims-jobs.html
- Indeed, query `dental accounts receivable specialist` (via WebSearch), **"1,052 jobs"**, estimate, secondary, 2026-10-01. https://www.indeed.com/q-dental-accounts-receivable-specialist-jobs.html
- ZipRecruiter, query `Medical Claims Follow Up Specialist` (via WebSearch) — **"1000+"** jobs, $18-79/hr — **broader than dental**, flagged not used as headline. https://www.ziprecruiter.com/Jobs/Medical-Claims-Follow-Up-Specialist

**Example postings:**
- eAssist Dental Billing — "Dental Billing Success Consultant" — Remote (national outsourced dental-billing vendor serving independent practices) — $40,000-80,000/yr — eAssist's own service description (via WebSearch) is independent contractors performing "dental insurance billing and follow-up to unpaid claims," a near-exact match to the candidate's wedge, framed as an *outsourced service* rather than software — a direct competitor-adjacent signal that practices already pay for this task to be done. (SimplyHired listing, measured) https://www.simplyhired.com/search?q=dental+claims+specialist
- Adelfi Medical Billing Solutions — "Medical Billing AR Specialist – Appeals & Out-of-Network Expert" — Remote — $65,000-70,000/yr — appeals and out-of-network claim recovery (medical RCM vendor, not dental-specific, illustrating adjacent demand for the same appeal-chasing skill). (SimplyHired, measured) https://www.simplyhired.com/search?q=denial+management+specialist
- Independent dental-office "Insurance Coordinator" postings (WebSearch aggregation across several Indeed-style listings, not one single verified posting) — task quote: *"Follow up on outstanding insurance claims; post insurance payments and adjustments accurately to patient accounts; investigate denied or delayed claims and initiate appeals when necessary."* — $16-40/hr, some salaried $50-80k/yr. estimate, secondary.

**Trend:** Unknown — no prior-period count found.

**Confidence: med.** A dedicated, recurring, paid role for chasing denied/delayed dental claims exists at independent dental offices (consistent $16-40/hr wage, explicit "investigate denied or delayed claims and initiate appeals" duty), and a national vendor (eAssist) sells this exact task as an outsourced service — real corroborating evidence of willingness to pay. However, no job-board query isolates "denied/underpaid-claim chasing" cleanly from general claims-*submission* billing work; the best measured count (7,241) is a broad title, and the tightest-sounding query's count (1,569) is estimate-tier only.

---

## Candidate A0 (CONTROL, OLD) — Dental insurance-eligibility verification before the visit

**Role searched:** "Dental Insurance Verification Specialist", "Dental Benefits
Verification Specialist"

**Counts:**
- SimplyHired, query `dental insurance verification`, **6,129 jobs**, measured, primary, 2026-10-01. https://www.simplyhired.com/search?q=dental+insurance+verification
- SimplyHired, query `dental insurance verification specialist`, filtered `l=remote`, **3 jobs**, measured, primary, 2026-10-01 (location filter narrows sharply; not representative of national volume). https://www.simplyhired.com/search?q=dental+insurance+verification+specialist&l=remote
- Indeed, query `dental insurance verification specialist` (via WebSearch), **"822 jobs"**, estimate, secondary, 2026-10-01. https://www.indeed.com/q-dental-insurance-verification-specialist-jobs.html
- Indeed, query `dental insurance verification` remote-only (via WebSearch), **"494 jobs"**, estimate, secondary.
- ZipRecruiter, `Remote Dental Insurance Verification` (via WebSearch), salary band **$16-23/hr**, estimate, secondary. https://www.ziprecruiter.com/Jobs/Remote-Dental-Insurance-Verification

**Example postings:**
- Saminity — "Patient Access & Insurance Coordinator" — Remote — $21-24/hr — task quote (fetched directly): *"Verify dental insurance eligibility and benefits before patient appointments."* — exact match to the wedge's task. (SimplyHired, measured) https://www.simplyhired.com/search?q=dental+insurance+verification
- Clean Claims Dental Management — "Remote Dental Insurance Specialist (CA/WA candidates only)" — $500-2,000/month, part-time/contract. (SimplyHired, measured) https://www.simplyhired.com/search?q=dental+insurance+verification+specialist&l=remote
- CORA Physical Therapy — "Insurance Verification Coordinator" — $18-20/hr — medical/PT, not dental, but same verification function (adjacent segment). (SimplyHired, measured) same URL.
- General task quote (Indeed, via WebSearch): *"reviewing and confirming patients' dental insurance coverage before their appointments, including checking eligibility, benefits, deductibles, coverage limitations, and copayments by contacting insurance companies or using online portals"* — $16-32/hr. estimate, secondary.

**Trend:** Unknown.

**Confidence: high.** Large measured count (6,129) on an exact-title query, a directly fetched example posting whose task line is verbatim the candidate's wedge, and a consistent $16-32/hr wage band across multiple independent sightings — the cleanest, most directly-matching evidence of the four candidates.

---

## Candidate B (NEW) — Medicare Advantage admission-denial appeal packets for rehab hospitals

**Role searched:** "Utilization Review / Denials & Appeals Specialist or Nurse"
(freestanding inpatient rehabilitation facility / LTCH)

**Counts:**
- SimplyHired, query `admission denial appeal rehabilitation`, **43 jobs**, measured, primary, 2026-10-01 — tightest query attempted, but first-page results were generic case-management/utilization-review titles (VP Case Management, RN Case Manager), not appeal-letter-writing-specific. https://www.simplyhired.com/search?q=admission+denial+appeal+rehabilitation
- SimplyHired, query `utilization review appeals coordinator`, **1,784 jobs**, measured, primary, 2026-10-01 — broad; first page dominated by SNF "MDS Coordinator" titles, not IRF/LTCH appeal roles. https://www.simplyhired.com/search?q=utilization+review+appeals+coordinator
- SimplyHired, query `rehabilitation authorization specialist`, **1,005 jobs**, measured, primary, 2026-10-01 — broad/mismatched on the first page, but it did surface one direct hit (see below). https://www.simplyhired.com/search?q=rehabilitation+authorization+specialist
- SimplyHired, query `prior authorization rehabilitation hospital`, **707 jobs**, measured, primary, 2026-10-01 — first page almost entirely unrelated titles (psych NP, sales manager, SLP); flagged noisy, not used as a headline figure. https://www.simplyhired.com/search?q=prior+authorization+rehabilitation+hospital
- Indeed, query `Encompass Health utilization review` (via WebSearch; direct Indeed fetch returned HTTP 403), **"1,247 jobs"**, estimate, secondary, 2026-10-01. Encompass Health is the largest freestanding IRF operator in the US, so this is a direct employer-segment hit even though the count aggregates many clinical roles/locations, not only appeal-writing ones. https://www.indeed.com/q-encompass-health-utilization-review-jobs.html

**Example postings:**
- Encompass Health (largest freestanding IRF chain, exact target employer type) — Utilization Review role — $40.61-60.96/hr (via WebSearch, estimate) — task quote: *"provides utilization review and denials management for an assigned patient case load... Facilitating/coordinating physician-to-physician (P2P) reviews... Serving as a subject matter expert for appeals and denials, preparing clinical discussions and appeal letters."* This is the closest direct match found to the candidate's wedge (same-day appeal packets with payer-criteria matching and letter drafting) at exactly the named target segment. https://www.indeed.com/q-encompass-health-utilization-review-jobs.html
- Life Care Centers of America — "Clinical Review and Appeals Specialist" — Cleveland, TN — salary not listed — a large post-acute/SNF chain (adjacent to, not identical to, the IRF/LTCH target), same appeals function. (SimplyHired, measured) https://www.simplyhired.com/search?q=rehabilitation+authorization+specialist
- MedReview — "Appeals Coordinator II" — Remote — $28.20/hr — task quote: *"Research, investigate, and resolve provider appeals, grievances, and complaints."* **Caveat:** MedReview is an independent review organization that adjudicates appeals on behalf of payers/CMS, i.e. the *payer* side of the same workflow, not a provider-side admissions/UR department — an adjacent-market signal, not a direct hit on the candidate's target user. (SimplyHired, measured) https://www.simplyhired.com/search?q=utilization+review+appeals+coordinator

**Trend:** Not a job-board trend, but relevant demand context found during research: per OIG reporting, the three largest Medicare Advantage organizations denied LTCH/IRF prior-authorization requests at some of the highest rates among care types in 2024, and appeals overturned 36% of LTCH denials and 43% of IRF denials — i.e., appealing usually works, which is the economic reason budget exists for this task, but this is a regulatory-outcomes data point, not a hiring-trend measurement.

**Confidence: med.** The single clearest hit (Encompass Health's own UR job description naming appeal-letter drafting for denials, at exactly the named target employer type) is a strong direct match — but it is WebSearch-extracted, not directly fetched (Indeed itself 403'd), and every broader SimplyHired query (43-1,784 jobs) came back heavily diluted with unrelated titles (MDS coordinators, psych nurse practitioners, case managers). The appeal-writing function clearly exists as a paid duty, but appears bundled inside broader "Utilization Review Nurse/Specialist" job titles rather than posted as a distinct, cleanly countable headcount line — same pattern as the "task folded into a generalist title" weak-signal cases seen in other job-postings research on this project.

---

## Candidate B0 (CONTROL, OLD) — Prior-authorization submission and tracking for post-acute providers

**Role searched:** "Prior Authorization Specialist", "Prior Authorization
Coordinator" (post-acute / skilled nursing / long-term care)

**Counts:**
- SimplyHired, query `prior authorization specialist` (national, no location), **2,982 jobs**, measured, primary, 2026-10-01 — broad query spanning all healthcare settings, not post-acute-specific. https://www.simplyhired.com/search?q=prior+authorization+specialist
- SimplyHired, same query + location filter `l=skilled+nursing`, **0 jobs**, measured, primary, 2026-10-01 — SimplyHired's location field doesn't act as a setting/industry filter, so this returns a literal (and uninformative) zero rather than "no SNF-specific postings." https://www.simplyhired.com/search?q=prior+authorization+specialist&l=skilled+nursing
- SimplyHired, query `authorization coordinator skilled nursing`, **200 jobs**, measured, primary, 2026-10-01 — mostly MDS Coordinator / care-management titles rather than prior-auth-submission-specific roles. https://www.simplyhired.com/search?q=authorization+coordinator+skilled+nursing
- Indeed, query `prior authorization coordinator` (via WebSearch), **"3,084 jobs"**, estimate, secondary, 2026-10-01; query `Rehabilitation Authorization Specialist` (via WebSearch), **"3,261 jobs"**, estimate, secondary, 2026-10-01. https://www.indeed.com/q-prior-authorization-coordinator-jobs.html

**Example postings:**
- Glencoe Regional Health — "Business Services & Prior Authorization Specialist" (long-term care) — $22.06-30.90/hr — task quote (via WebSearch): *"processes prior authorizations for both skilled nursing and hospital services... initiating prior authorizations and pre-determinations, following through with authorization appeals, and following up on authorization requests."* Direct, explicit skilled-nursing-facility match. estimate, secondary.
- Optum — "Hospital Admissions / Prior Authorization Coordinator" — Quincy, MA — $17.98-32.12/hr — task quote (via WebSearch): *"tracking and documenting authorization statuses, assisting providers with authorization questions, and reviewing denials and initiating appeals."* (Indeed via WebSearch, estimate) https://www.indeed.com/q-prior-authorization-coordinator-jobs.html
- Care Plus Bergen, Inc. — "Prior Authorization Specialist" (continuum of care) — Paramus, NJ — $45,000-58,000/yr — continuum-of-care/post-acute-adjacent nonprofit employer. (via WebSearch, estimate) same URL.
- Genesis HealthCare — "Prior Authorization Nurse (LVN)" — Texarkana, TX — salary not listed — a large post-acute/SNF chain, though this specific listing is in its primary-care clinic arm rather than an inpatient SNF/LTCH. (via WebSearch, estimate)

**Trend:** Unknown.

**Confidence: med-high.** "Prior Authorization Specialist/Coordinator" is an extremely well-established, widely-posted job title (2,982-3,261 across two boards) with a consistent $17-32/hr (or $45-58k/yr) wage band, and multiple examples explicitly name skilled-nursing/long-term-care/post-acute settings. However, no posting found (fetched or searched) was from a freestanding IRF/LTCH specifically — the brief's named target — most hits are SNF, home-health, or general post-acute-adjacent employers, and the large headline counts are for the broad, cross-industry title rather than an IRF/LTCH-specific one.

---

## Cross-candidate summary

| Candidate | Tightest role title | Best count (board, date) | Basis |
|---|---|---|---|
| A — Dental denied-claim follow-up (NEW) | Dental Claims Specialist / Insurance Coordinator | 7,241 (SimplyHired, 2026-10-01), broad title | measured, weak-match caveat |
| A0 — Dental eligibility verification (CONTROL) | Dental Insurance Verification Specialist | 6,129 (SimplyHired, 2026-10-01) | measured |
| B — IRF/LTCH admission-denial appeals (NEW) | Utilization Review / Denials & Appeals Specialist | 1,247 Encompass Health UR roles (Indeed via WebSearch) — employer-segment match, not appeal-specific | estimate |
| B0 — Post-acute prior-auth submission/tracking (CONTROL) | Prior Authorization Specialist/Coordinator | 2,982-3,261 (SimplyHired measured + Indeed estimate, 2026-10-01), broad/cross-industry | measured + estimate |

Note on the NEW-vs-CONTROL pairs as measured here: in both pairs, the OLD/CONTROL
front-end task (A0, B0) returned a cleaner, tighter, more confidently-matched job-board
signal than its NEW back-end counterpart (A, B). For A vs A0, both show real, dedicated,
well-paid roles, but A0's exact-title count is larger and its example quote is a verbatim
match while A's best count is diluted by general billing titles. For B vs B0, B0 has a
larger and cleaner measured count across two boards, while B's strongest evidence is a
single employer-specific (Encompass Health) hit rather than a broad, clean count — the
appeal-writing function for denied admissions appears to be bundled inside generalist
"Utilization Review" job titles industry-wide rather than posted as its own line item.
This is a job-postings-signal observation only, not a ranking or recommendation.
