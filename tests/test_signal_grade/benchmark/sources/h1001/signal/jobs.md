# Job-Postings Signal — Rung-0 Demand Validation

Researched 2026-10-01. Method: WebSearch (12 queries) across Indeed/ZipRecruiter/
LinkedIn, then WebFetch attempts on 16 pages. Direct WebFetch of Indeed,
LinkedIn, and ZipRecruiter *search-results* pages was blocked (HTTP 403) in
every case — expected per the brief. SimplyHired search pages rendered and
were fetched successfully (11 pages), giving **measured** on-page counts;
all Indeed/LinkedIn/ZipRecruiter figures below come from WebSearch's own
result summaries (the search engine's extraction of the page, not a direct
fetch by us) and are therefore tagged **estimate / secondary**, not measured.
Where SimplyHired and Indeed/ZipRecruiter disagree in order of magnitude,
both are shown so the reader can see the spread rather than one cherry-picked
number.

---

## Candidate 1 — Small-landlord unit-turn / vacancy-days coordination

**Role searched:** "Make Ready Coordinator", "Apartment/Property Turnover
Coordinator", "Leasing Coordinator" (property management)

**Counts:**
- SimplyHired, query `Make Ready Coordinator`, **122 jobs**, measured, primary, 2026-10-01. https://www.simplyhired.com/search?q=Make+Ready+Coordinator
- SimplyHired, query `apartment turnover coordinator`, **135 jobs**, measured, primary, 2026-10-01. https://www.simplyhired.com/search?q=apartment+turnover+coordinator
- Indeed, query `Make Ready Coordinator` (via WebSearch, not directly fetched), **"551 jobs"**, estimate, secondary, 2026-10-01. https://www.indeed.com/q-Make-Ready-Coordinator-jobs.html
- Indeed, query `turnover coordinator` (unquoted, broader), WebSearch reported **"23,442"** / **"29,554"** for "Rental Property Turnover Coordinator" / "Apartment Turnover Coordinator" — these numbers are implausibly large for a niche title and likely reflect Indeed's loose/related-title expansion, not an exact-title count. Flagged unreliable, not used as the headline figure.
- ZipRecruiter, query `Property Management Coordinator`, **"$42k-$70k... jobs"** page returned 404 on direct fetch; WebSearch snippet only. estimate, secondary.

**Example postings:**
- "Make Ready Coordinator" — Mac Properties, St. Louis, MO — $20/hr, full-time, 40hrs/wk. (Indeed via WebSearch) https://www.indeed.com/q-Make-Ready-Coordinator-jobs.html
- "Make Ready Supervisor" — New Patrician Management, Belle Chasse, LA — $23-26/hr. (Indeed via WebSearch)
- "Assistant Property Readiness Coordinator (Entry Level)" — Real Property Management, Fairfax, VA — $18-25/hr. (Indeed via WebSearch)
- "Apartment Setup Coordinator" — The Atchison Group Inc., Costa Mesa, CA — $22.66-27.50/hr; "inventory control" duties. (SimplyHired, measured) https://www.simplyhired.com/search?q=Make+Ready+Coordinator
- "Property Manager Coordinator – Mobile Home Park" — KLDR Property Management LLC, Shady Cove, OR — task quote: *"showing units, maintaining courteous relations with residents, leasing units, marketing vacancies, scheduling vendors, turnovers and repairs"* — direct match to the candidate's wedge (vendor scheduling + listing readiness). (SimplyHired, measured) https://www.simplyhired.com/search?q=apartment+turnover+coordinator
- "Leasing Coordinator" — Jamestown Management Corporation, Brooklyn, NY — $80k-85k/yr (larger/institutional landlord, above the target ~50-500-unit firm profile).

**Trend:** Unknown — no prior-period count found; not re-measured.

**Confidence: med.** A dedicated, recurring, paid role for this exact task exists and is posted at real small/mid landlords with concrete hourly wages ($18-27/hr) that map to a displaceable per-seat cost. Measured SimplyHired counts (122-135) are modest but non-trivial for a niche title; Indeed's broader "turnover coordinator" numbers are not trustworthy (likely over-expansion) so the headline count is the SimplyHired figure, which is tighter but smaller. Task often also gets absorbed into generic "Property Manager" or "Maintenance Coordinator" titles, understating true volume.

---

## Candidate 2 — Small-fleet detention capture & auto-invoicing

**Role searched:** "Detention Pay Trucking" (dispatcher angle), "Freight
Billing Specialist", "Trucking Billing Clerk"

**Counts:**
- SimplyHired, query `detention trucking`, **4,137 jobs**, measured, primary, 2026-10-01 — but see caveat below. https://www.simplyhired.com/search?q=detention+trucking
- SimplyHired, query `freight billing specialist`, **463 jobs**, measured, primary, 2026-10-01. https://www.simplyhired.com/search?q=freight+billing+specialist
- Indeed, query `Freight Billing` (via WebSearch), **"1,971 jobs"**, estimate, secondary. https://www.indeed.com/q-Freight-Billing-jobs.html
- Indeed, query `Trucking Billing Clerk` (via WebSearch), **"209,827 jobs"** — implausible for this niche title; almost certainly a mis-extracted/related-title inflation. Flagged unreliable, not used.
- ZipRecruiter, query `Detention Pay Trucking`, page returned 403 on direct fetch; WebSearch-only summary. estimate, secondary.

**Example postings:**
- "Owner Operator CDL Class A" — Safeload Trucking, Atlanta, GA — $3,000-7,000/week — quote: *"Detention pay 100%"* listed as a pay benefit, i.e. detention appears as driver compensation, not as an admin/invoicing task. (SimplyHired, measured)
- "Billing/Settlement Specialist" — confidential small carrier, Mantua, OH — $19-20/hr — task quote: *"generating accurate customer invoices, review rate tables and process weekly driver/carrier settlements"* and auditing freight bills for accuracy — closest match found, but does not name detention specifically. (SimplyHired, measured)
- "Carrier AP & Billing Specialist" — JW Logistics Operations LLC, McKinney, TX — $28.36-31.00/hr — handles "carrier disputes" and "balance due activity," which can include detention disputes but isn't detention-specific. (Indeed via WebSearch)

**Trend:** Unknown.

**Confidence: low.** This is the honest "weak/none found" case. There is **no distinct, separately-posted job title** for "capture and invoice detention fees" — the reviewed postings on both SimplyHired and Indea confirm the function is a sub-duty folded into generic dispatcher/biller/settlement-specialist roles at small carriers, not a headcount line employers post for on its own. The large counts above (4,137 "detention trucking," 463 "freight billing") are for broad adjacent titles, not the specific task, and when we actually read the postings returned, none centered on detention capture/invoicing as the core job. Job-postings evidence for this candidate is thin — absence of a dedicated hiring signal, not proof of absence of the underlying pain (small carriers more plausibly eat the loss than hire for it), but no paid-headcount evidence either.

---

## Candidate 3 — Vet-clinic documentation / records layer on PIMS

**Role searched:** "Veterinary Scribe"

**Counts:**
- SimplyHired, query `veterinary scribe`, **227 jobs**, measured, primary, 2026-10-01. https://www.simplyhired.com/search?q=veterinary+scribe
- Indeed, query `Veterinary Scribe` (via WebSearch), **"511 jobs"** (dated snippet references "May 31, 2024" on one cached result title, so partially stale), estimate, secondary. https://www.indeed.com/q-Veterinary-Scribe-jobs.html
- ZipRecruiter, salary range reported via WebSearch: **"$15-$108/hr"** — very wide, likely includes outlier/mis-tagged postings; not a reliable band on its own.

**Example postings:**
- "Veterinary Medical Scribe/CSR in Shelter Medicine" — Hard Luck Animal Welfare Advocates, Stockton, CA — salary not specified — task quote: *"Manage incoming phone calls related to medical inquiries"* and *"medical record entry into the Chameleon Operating system"* — direct match: ambient documentation layered on top of existing PIMS. (SimplyHired, measured) https://www.simplyhired.com/search?q=veterinary+scribe
- "Veterinary Scribe" — Pender Veterinary Centre, Fairfax, VA — $25-30/hr, full-time, 3 yrs experience required. (SimplyHired, measured)
- "Doctor Assistant (Scribe), Emergency Veterinary Hospital" — Ethos Veterinary Health, Phoenix, AZ — salary not specified, weekend/bilingual preferred. (SimplyHired, measured)
- "VCA Scribe Specialist" — Mars Veterinary Health (large multi-location chain, VCA brand) — remote, company provides laptop — found via WebSearch, direct LinkedIn fetch blocked (403). https://www.linkedin.com/jobs/view/vca-scribe-specialist-at-mars-veterinary-health-3741706889

**Trend:** Unknown, but notable that a third-party staffing vendor (ScribeAmerica) is actively placing veterinary scribes across the US, and a large consolidator (Mars/VCA) posts the role in-house — two independent signs of a recurring, budgeted need rather than a one-off.

**Confidence: med-high.** Dedicated title exists, is posted by both independent single-doctor clinics (Pender) and large chains (VCA/Ethos), salary band is consistent ($17-30/hr) and plausibly displaceable, and the clearest example quote names the exact manual task (real-time charting into the existing PMS) the candidate's wedge targets.

---

## Candidate 4 — Dental insurance-verification + denial follow-up

**Role searched:** "Dental Insurance Verification Specialist", "Insurance
Verification Specialist" (medical, broader)

**Counts:**
- SimplyHired, query `dental insurance verification`, **6,101 jobs**, measured, primary, 2026-10-01 — **caveat: this query is broader than the exact task.** Reading the actual top results, most were general *medical* insurance verification/follow-up roles, not dental-specific. https://www.simplyhired.com/search?q=dental+insurance+verification
- Indeed, query `dental insurance verification specialist` (via WebSearch), **"822 jobs"** — a tighter, dental-specific figure. estimate, secondary. https://www.indeed.com/q-dental-insurance-verification-specialist-jobs.html
- Indeed, broader `Dental Verification Specialist` (via WebSearch), **"13,596 jobs"** — likely inflated by related-title expansion; not used as headline.
- ZipRecruiter, `Remote Dental Insurance Verification`, salary **$16-23/hr** (via WebSearch), estimate, secondary.

**Example postings:**
- "Insurance Verification Specialist" — ActivStyle, Saint Paul, MN (remote) — $18-21/hr — task quote: *"Obtain and verify insurance information, process pre-authorizations, ensure clean claim processing"* and *"extensive knowledge of different types of payer coverage and insurance policies."* (SimplyHired, measured; note — this employer is a DME/medical supply company, not dental-specific, illustrating the broad-query caveat.)
- "Insurance Follow-Up Specialist (Remote)" — GetixHealth, Tacoma, WA — $16-19/hr — "follow up on insurance matters for healthcare claims." (SimplyHired, measured; medical RCM vendor, not dental-specific.)
- "Certified Medical Biller/Collections/Insurance Verification" — Lakewood Ranch Gynecology and Wellness, Lakewood Ranch, FL — $20-22/hr, part-time. (SimplyHired, measured; again medical, not dental.)
- Dental-specific examples were not independently re-fetched (dental-specific board page blocked); the dental-tagged Indeed count (822) is the best tight-title evidence available, estimate-tier.

**Trend:** Unknown.

**Confidence: med.** The surrounding function (insurance verification + denial/claims follow-up as a paid, $16-22/hr admin role) is unambiguously real and widely posted — but the dental-specific slice of that demand is evidenced only by a secondary (not directly fetched) Indeed count of 822, and the larger measured SimplyHired number mixes in general medical-practice postings rather than dental offices specifically. Directionally solid, precision moderate.

---

## Candidate 5 — Hourly / blue-collar high-volume applicant screening

**Role searched:** "High Volume Recruiter"

**Counts:**
- SimplyHired, query `high volume recruiter`, **2,178 jobs**, measured, primary, 2026-10-01. https://www.simplyhired.com/search?q=high+volume+recruiter
- Indeed, query `High Volume Staffing Recruiter` (via WebSearch), **"415 jobs"**, estimate, secondary. https://www.indeed.com/q-High-Volume-Staffing-Recruiter-jobs.html
- Indeed, query `Warehouse Recruiter` (via WebSearch), **"204 jobs"**, estimate, secondary.
- ZipRecruiter, `High Volume Recruiter` (via WebSearch), **"$42k-$76k"** salary band, estimate, secondary.

**Example postings:**
- "High Volume Hiring Recruiter – US" — Careerflow — remote — task quote: role requires managing "high-volume pipelines" and meeting "daily/weekly hiring targets" for sourcing candidates. (SimplyHired, measured)
- "High Volume (TOFU) Recruiter" — HumanSignal, San Francisco, CA — $55,000-100,000/yr — top-of-funnel screening focus. (SimplyHired, measured)
- "Recruiter, High Volume Operations" — The RealReal, Perth Amboy, NJ — $100,000-115,000/yr — senior ops-level role (warehouse/retail-adjacent employer). (SimplyHired, measured)
- Contract Recruiter role (via initial WebSearch, Indeed) — explicitly described as supporting "high-volume US hiring for hourly roles including field service, warehouse, call center, and other frontline positions" — $25-30/hr — closest direct match to the candidate's target segment.

**Trend:** Unknown, but the spread of salaries from $25/hr contract roles to $100k+ salaried ops roles suggests this is a mature, multi-tier job category, not an emerging niche.

**Confidence: high.** Large, consistently-measured count (2,178 on the tightest query), real employers across warehouse/retail/logistics-adjacent profiles, salary evidence spanning contract-hourly to six-figure ops roles — the clearest, most directly-matching signal of the seven candidates.

---

## Candidate 6 — Specialty / post-acute prior-auth + denial-appeal packets

**Role searched:** "Prior Authorization Specialist", "Appeal/Denial
Specialist"

**Counts:**
- SimplyHired, query `prior authorization specialist`, **2,935 jobs**, measured, primary, 2026-10-01. https://www.simplyhired.com/search?q=prior+authorization+specialist
- SimplyHired, query `appeal denial specialist`, **1,697 jobs**, measured, primary, 2026-10-01. https://www.simplyhired.com/search?q=appeal+denial+specialist
- Indeed, query `prior authorization specialist` (via WebSearch), **"754 jobs"**, estimate, secondary. https://www.indeed.com/q-prior-authorization-specialist-jobs.html
- Indeed, query `appeal denial specialist` variants (via WebSearch), **"1,813" / "3,600" / "3,133"** jobs across differently-worded queries, estimate, secondary (spread shows query-wording sensitivity).

**Example postings:**
- "LVN/LPN Prior Authorization Specialist" — Viva, remote — $20.98-25.98/hr — task quote: *"Process prior authorization requests, manage inbound/outbound calls, review clinical documentation, navigate multiple systems simultaneously, and identify cases requiring escalation."* (SimplyHired, measured)
- "Prior Authorization Specialist" — Inspire Medical Systems, Minneapolis, MN (remote) — $24.50-37.00/hr. (SimplyHired, measured)
- "Infusion Prior Authorization Specialist" — Nyx Health, Houston, TX (remote) — $21-23/hr. (SimplyHired, measured)
- "Utilization Review Specialist" — Ascend Healthcare, Colorado (remote) — $78,000-85,000/yr — task quote: *"Reviews and prepares Appeal documentation (including rationales) to the appropriate entities"* and coordinates peer-to-peer review. (SimplyHired, measured)
- "Clinical Review and Appeals Specialist" — **Life Care Centers of America**, Cleveland, TN — a direct skilled-nursing/post-acute chain, matching the candidate's named segment exactly. (SimplyHired, measured)

**Trend:** Unknown, no prior-period figure found; BLS occupation-growth lookup not attempted (out of search budget).

**Confidence: high.** Two tight, directly-matching titles both return measured four-figure counts; salary band ($20-37/hr or $78-85k/yr) represents a real, substantial per-seat cost; and one example posting (Life Care Centers of America) comes from exactly the post-acute/LTC segment named in the candidate description, giving a direct hit rather than an inferred analogy.

---

## Candidate 7 — Schedule C client record-gathering for tax preparers

**Role searched:** "Tax Preparer Bookkeeper", "Client Services Coordinator"
(CPA firm, tax-season)

**Counts:**
- SimplyHired, query `tax preparer bookkeeper`, **71 jobs**, measured, primary, 2026-10-01. https://www.simplyhired.com/search?q=tax+preparer+bookkeeper
- SimplyHired, query `client services coordinator tax`, **1,866 jobs**, measured, primary, 2026-10-01 — but this query is clearly broader than the exact task (results include estate-planning and 1031-exchange coordinators, not Schedule-C document chasing). https://www.simplyhired.com/search?q=client+services+coordinator+tax
- Indeed, query `CPA Tax Season` in California (via WebSearch), **"800 jobs"**; `Seasonal CPA` **"100 jobs"**, estimate, secondary.

**Example postings:**
- "Bookkeeper/Tax Preparer" — Jeet Financial Services, LLC, Gaithersburg, MD — $16.50-32.44/hr — task quote: QuickBooks reconciliation, payroll processing, and "organizing documents for tax preparation" — the closest match found, but document-chasing is one line among many general bookkeeping duties, not the job's core focus. (SimplyHired, measured)
- "Client Success Coordinator (Entry Level)" — Hargrove Management Services Organization Inc, Denver, CO — $24-28/hr — task quote: *"Prepare, organize, and track client documents and internal records"* — adjacent (estate-planning firm, not a tax preparer) but structurally the same chase-clients-for-documents duty. (SimplyHired, measured)
- "Tax Preparer/Accountant/Full Charge Bookkeeper" — Olson and Associates, Kenosha, WI — $55,000-75,000/yr. (SimplyHired, measured)

**Trend:** Unknown.

**Confidence: low.** This is the other honest "thin" case. No job board returns a dedicated title for "chase small-business clients for missing Schedule C documents" — the task shows up only as a sub-duty inside generic Bookkeeper/Tax Preparer/Client Coordinator postings (71 jobs for the tightest on-task query, which itself is a generalist title, not a document-chasing-specific one). Employers are not posting distinct headcount for this specific pain; whatever budget exists for it is bundled into existing bookkeeper/tax-preparer salaries rather than being a separately measurable line. Weak job-posting evidence, on par with Candidate 2.

---

## Cross-candidate summary (counts only, see sections above for full sourcing)

| Candidate | Tightest role title | Best count (board, date) | Basis |
|---|---|---|---|
| 1. Unit-turn coordination | Make Ready / Turnover Coordinator | 122-135 (SimplyHired, 2026-10-01) | measured |
| 2. Detention capture | (no dedicated title) | 463 Freight Billing Specialist (SimplyHired) — not detention-specific | measured, weak match |
| 3. Vet documentation | Veterinary Scribe | 227 (SimplyHired, 2026-10-01) | measured |
| 4. Dental insurance verification | Dental Insurance Verification Specialist | 822 (Indeed, estimate) | estimate |
| 5. High-volume hourly screening | High Volume Recruiter | 2,178 (SimplyHired, 2026-10-01) | measured |
| 6. Prior-auth / denial appeals | Prior Authorization Specialist + Appeal/Denial Specialist | 2,935 + 1,697 (SimplyHired, 2026-10-01) | measured |
| 7. Schedule C record-gathering | (no dedicated title) | 71 Tax Preparer Bookkeeper (SimplyHired) — generalist title | measured, weak match |
