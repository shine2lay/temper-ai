# Job-Postings Signal — Rung 0 Demand Validation

Method note (read first): Indeed, Glassdoor, and ZipRecruiter all returned
HTTP 403 to direct WebFetch on every attempt in this session (search-result
pages and several individual job postings alike; two ATS postings had also
expired/been pulled). This matches the expected reality of free scraping
described in the brief. Counts below that are not prefixed "directly
fetched" come from WebSearch's synthesized read of the board's own page
(title/snippet), not from a page I rendered myself — they are tagged
`estimate` throughout, even when the board's title string states a precise
number, because I could not independently confirm the page content. Only
the handful of smaller sites (Getro/Sila, staffingly.com, nursefern.com,
BLS.gov) rendered for direct WebFetch; those are tagged `measured`.

Research date: 2026-10-02 (US).

---

## Candidate 1 — Missed-call recovery and booking for small electrical contractors

**Role that does this by hand today:** Customer Service Representative /
Service Dispatcher / Service Coordinator at an HVAC, plumbing, or electrical
contractor (answers inbound calls, books into dispatch software, handles
missed-call follow-up). No board indexes "electrical contractors" alone at
useful volume, so the tightest queries blend HVAC/plumbing/electrical —
flagged as broader than electrical-only.

**Counts (all via WebSearch synthesis of board result pages, not directly fetched — estimate):**
- Indeed, query "Customer Service Representative Call Center HVAC" — **837 jobs** — 2026-10-02 — https://www.indeed.com/q-Customer-Service-Representative-Call-Center-HVAC-jobs.html
- Indeed, query "HVAC Dispatch Service Coordinator" — **988 jobs** — 2026-10-02 — https://www.indeed.com/q-hvac-dispatch-service-coordinator-jobs.html
- Indeed, query "HVAC Call Center" — **~800 jobs** ("Now Hiring: 800") — 2026-10-02 — https://www.indeed.com/q-hvac-call-center-jobs.html
- ZipRecruiter, general "call center representative" — average pay **$18.05/hr** US, 2026-10-01 — https://www.ziprecruiter.com/Jobs/Call-Center
- (Excluded as too broad/wrong sense: Indeed "Electric Dispatcher" 15,813 — this is dominated by electric-utility grid/power-line dispatchers, not small-contractor service dispatch.)

**Example postings:**
1. Astar Heating, Cooling, Plumbing & Electrical (Middletown, NY), posted via Sila Services — Customer Service Representative — **$20–24/hour** — posted 2026-08-12. Directly fetched (measured), source: aggregator/ATS (Getro community board), quality=secondary.
   Quote: *"Answer inbound customer calls, texts, and service inquiries"*; *"Follow up on missed calls, open opportunities, and customers who may still need service."*
   URL: https://community.getro.com/companies/sila-services/jobs/89677941-customer-service-representative
2. South West Plumbing, Waterheaters Inc. (Seattle, WA) — Customer Service Representative, call-center setting — **$23.00/hour**, no on-call shifts. Found via WebSearch synthesis only; direct fetch failed (posting no longer live) — estimate, source=primary (board) but unverified.
   Quote (via synthesis): *"urgently hiring for a Customer Service Representative in a call center setting."*
   URL: https://recruiting.paylocity.com/recruiting/jobs/Details/4450680/South-West-Plumbing-Waterheaters-Inc/Customer-Service-Representative
3. Anderson's Heating and Air Conditioning (Missoula, MT) — Customer Service Representative, "first point of contact... key link between the office, dispatch, and technicians." Direct fetch failed (job "temporarily unavailable") — estimate, source=primary (board) but unverified.
   URL: https://www.simplyhired.com/job/b4TM--pjHk0G18mCzWyep9ef_fIoV_GkNbBhoYnXVwUp6o3ilJ4-eA

**Trend:** Not independently found this session (no prior-period count or BLS category cleanly matches "home-services dispatcher"). Unknown.

**Confidence: medium.** Multiple boards show several hundred to ~1,000 open roles whose task language ("answer inbound calls," "follow up on missed calls," "schedule into dispatch software") is a near-verbatim match to the wedge's manual task, and $18–24/hr postings show a real per-seat labor cost the product would displace. Held at medium rather than high because (a) every count is board-synthesized, not independently confirmed by direct fetch, (b) no query isolates "electrical contractors" specifically — all usable volume is HVAC/plumbing-inclusive, and (c) two of three example postings could not be re-verified live.

---

## Candidate 2 — Denial triage and appeal letters for independent physician groups

**Role that does this by hand today:** Prior Authorization Specialist /
Denials & Appeals Specialist / AR Denials Specialist in a medical billing
office or outsourced billing company.

**Counts:**
- Glassdoor, query "prior authorization specialist" — **2,796 jobs**, United States — 2026-10-02 (via WebSearch synthesis of Glassdoor's own page title) — estimate — https://www.glassdoor.com/Job/prior-authorization-specialist-jobs-SRCH_KO0,30.htm
- Indeed, query "Denials Appeals Specialist" — **~1,341 jobs** (page titled "1,000 Denials Appeals Specialist Jobs & Work") — 2026-10-02 — estimate — https://www.indeed.com/q-denials-appeals-specialist-jobs.html
- Indeed, query "Medical Claim Denial Specialist" — **2,853 jobs** — 2026-10-02 — estimate — https://www.indeed.com/q-medical-claim-denial-specialist-jobs.html
- Indeed, query "Inpatient Denials Specialist" — **9,068 jobs** — 2026-10-02 — note: broader hospital-inpatient-denials title, not physician-group-specific — estimate — https://www.indeed.com/q-inpatient-denials-specialist-jobs.html
- ZipRecruiter, query "Prior Authorization Specialist" — pay range **$17–26/hr** — 2026-10-02 — estimate — https://www.ziprecruiter.com/Jobs/Prior-Authorization-Specialist

**Example postings:**
1. Staffingly Inc. (healthcare BPO/staffing vendor, placing remote PA staff for "a confidential US multi-specialty outpatient practice") — Remote Prior Authorization Specialist — **$399/week** (single hire, 40 hr/wk; $349/wk at 5+ hires, India-based remote labor). Directly fetched (measured), source=vendor listing, quality=vendor.
   Quote: *"prior authorization submission, appeals and peer-to-peer coordination for commercial and government payers"*; *"appeal letter, peer-to-peer scheduling and supporting documentation"*; reports "92% approval rate on first submissions and 20% denial overturn rate."
   URL: https://staffingly.com/insights/talent/radiology-prior-authorization-specialist-epic-medical-pa-263.html
   This is notable as inverse evidence: a vendor is already selling *outsourced human labor* to do exactly this task at ~$10/hr-equivalent, i.e., a live, priced substitute for the product.
2. General Physician, P.C. (Williamsville, NY) — Prior Authorization Specialist — found via WebSearch synthesis only (not independently fetched) — estimate, source=primary (board) unverified.
   Quote (via synthesis): *"facilitating the authorization process for medical procedures... contacting insurance carriers to verify patients' insurance eligibility and benefits."*
   URL: https://www.tealhq.com/job/prior-authorization-specialist_97b5a02a-c107-4062-b786-d9292b12d598 (fetch returned 403)
3. (Context only, not counted as target-user evidence) UnitedHealth Group — 17 Prior Authorization Specialist roles nationally per LinkedIn — payer-side, not an independent physician group, included only to show the role title is in active use at scale across the industry.

**Trend:** BLS Occupational Outlook for "Claims Adjusters, Examiners, and Investigators" (directly fetched, measured, primary) — 376,100 jobs in 2025, **projected to decline 6% 2025–2035** (~21,800 fewer positions), ~21,600 openings/year from turnover, median pay $78,000/yr. This category is much broader than medical-specific PA/denials work and includes property/casualty adjusters, so treat as a weak proxy only — directionally it suggests claims-adjudication-adjacent headcount is already shrinking as software absorbs volume, which cuts both ways for market sizing (shrinking manual-labor base, but also a buyer base already primed to replace headcount with software).
URL: https://www.bls.gov/ooh/business-and-financial/claims-adjusters-appraisers-examiners-and-investigators.htm

**Confidence: medium-high.** Role titles ("prior authorization specialist," "denials specialist") are an exact match to the manual task described in the wedge (sort denials, write appeals), and multiple boards independently show thousands of open roles nationally, with a directly-fetched vendor posting proving a real, currently-paid outsourced-labor substitute exists at a specific dollar rate. Not higher because no board count could be independently re-rendered via fetch (all board figures are search-synthesized), and none of the counts isolate "independent physician group" specifically — large health systems and payers are mixed into every query.

---

## Candidate 3 — Invoice capture and approval routing for small businesses, sold through bookkeepers

**Role that does this by hand today:** Accounts Payable Clerk / Bookkeeper
(Accounts Payable) — typically at a bookkeeping firm or in-house for an SMB,
keying vendor invoices into QuickBooks/Xero and chasing approvals.

**Counts:**
- Indeed, query "Accounts Payable Clerk" — **~2,000 jobs** ("Now Hiring: 2,000 Accounts Payable Clerk Jobs") — 2026-10-02 — estimate — https://www.indeed.com/q-accounts-payable-clerk-jobs.html
- Indeed, query "Accounts Payable Receivable Bookkeeper" — **~2,000 jobs** — 2026-10-02 — estimate — https://www.indeed.com/q-Accounts-Payable-Receivable-Bookkeeper-jobs.html
- Indeed, query "Bookkeeping Clerk" (broader) — **9,786 jobs** — 2026-10-02 — note: broader than AP-only — estimate — https://www.indeed.com/q-bookkeeping-clerk-jobs.html
- LinkedIn, query "Bookkeeping" (broad) — **21,000+ jobs**, US — 2026-10-02 — estimate — https://www.linkedin.com/jobs/bookkeeping-jobs
- ZipRecruiter, "Accounts Payable Specialist" in San Francisco, CA — average pay **$27.92/hr** — 2026-09-22 — estimate — https://www.ziprecruiter.com/Jobs/Accounts-Payable-Specialist/-in-San-Francisco,CA
- ZipRecruiter, "Accounts Payable Bookkeeper" — pay range **$21–36/hr** — 2026-10-02 — estimate — https://www.ziprecruiter.com/Jobs/Accounts-Payable-Bookkeeper

**Example postings:** No specific, independently-citable posting from a
bookkeeping firm serving multiple SMB clients could be confirmed this
session — every ATS/board target page either 403'd or had been pulled. A
WebSearch synthesis described "$24–27/hr at bookkeeping firms serving
multi-client environments" and task lines like "reviewing, verifying, and
processing vendor invoices... ensuring proper approvals and coding are
completed prior to payment" but did not attach a specific employer name or
URL I can stand behind — omitted here rather than fabricated. This is a
real gap in this candidate's evidence relative to the other three.

**Trend:** BLS Occupational Outlook for "Bookkeeping, Accounting, and
Auditing Clerks" (directly fetched, measured, primary) — **1.5 million
jobs in 2025**, projected to **decline 6% 2025–2035** (~85,600 fewer
positions), but **~144,100 openings/year** from turnover; median pay
$50,670/yr ($24.36/hr); BLS attributes the decline explicitly to
"automation of routine accounting tasks." This is the clearest direct
signal in the whole dataset that software is already displacing this
exact role — strong qualitative fit for the wedge, but the category is
far broader than "AP invoices at a multi-client bookkeeping firm" (includes
AR, payroll, general ledger clerks of all kinds).
URL: https://www.bls.gov/ooh/office-and-administrative-support/bookkeeping-accounting-and-auditing-clerks.htm

**Confidence: medium.** Thousands of open AP/bookkeeping-clerk roles nationally with hourly pay in the displaceable range, plus a BLS occupational trend that explicitly names automation as the cause of decline — directionally strong. Held at medium, not higher, because (a) no query could isolate "bookkeeping firm with multiple SMB clients" from "in-house AP clerk at one company" — the two target-user types are conflated in every count, and (b) no example posting with task-quote + salary + URL survived verification this session.

---

## REFERENCE — Medicare Advantage admission-denial appeal packets for rehab hospitals (screened 2026-10-02)

**Role that does this by hand today:** Utilization Review (UR) Nurse /
Clinical Appeals Nurse / Denials & Appeals Nurse — typically an RN inside
the admissions/UR department of an inpatient rehabilitation facility (IRF)
or LTCH, or working the payer side of the same transaction.

**Counts:**
- Indeed, query "Utilization Review Appeal RN" — **791 jobs** — 2026-10-02 — estimate — https://www.indeed.com/q-Utilization-Review-Appeal-RN-jobs.html
- Indeed, query "Clinical Appeal Nurse" — **~600 jobs** — 2026-10-02 — estimate — https://www.indeed.com/q-clinical-appeal-nurse-jobs.html
- Indeed, query "LPN Utilization Review" — **~800 jobs** — 2026-10-02 — estimate — https://www.indeed.com/q-lpn-utilization-review-jobs.html
- Glassdoor, query "clinical denials appeals nurse" — **414 jobs**, US — 2026-10-02 — estimate — https://www.glassdoor.com/Job/clinical-denials-appeals-nurse-jobs-SRCH_KO0,30.htm
- Glassdoor, query "denials appeals nurse" — **333 jobs**, US — 2026-10-02 — estimate — https://www.glassdoor.com/Job/denials-appeals-nurse-jobs-SRCH_KO0,21.htm
- ZipRecruiter, "Clinical Appeals Nurse" — pay range **$71k–137k/yr** — 2026-10-02 — estimate — https://www.ziprecruiter.com/Jobs/Clinical-Appeals-Nurse

**Example postings:**
1. Mary Free Bed Rehabilitation Hospital (Grand Rapids, MI — freestanding IRF, directly matches target user) — Utilization Review/Reimbursement Specialist — found via WebSearch synthesis only (not independently fetched) — estimate, source=primary (board) unverified.
   Quote (via synthesis): *"coordinate utilization management review functions and conduct complex case reviews for determination of inpatient admission criteria."*
2. Rehabilitation Hospital of Indiana (Indianapolis, IN — freestanding IRF) — Utilization Reviewer — found via WebSearch synthesis only — estimate, source=primary (board) unverified.
   Quote (via synthesis): *"perform thorough review of total resources available to patients pre and post-discharge from rehabilitation care."*
3. nursefern.com career-guide article (directly fetched, measured) — "Remote Denials & Appeals Nurse" role overview, not IRF-specific (general payer/health-system appeals nurse) — source=secondary (listicle/career guide).
   Quote: *"Reviewing medical records and provider notes... Filing appeals and speaking with insurance companies about denied claims."* Salary cited in the article (sourced to ZipRecruiter): average **$87,245/yr**.
   URL: https://nursefern.com/remote-denials-and-appeals-nurse/

**Trend:** Not independently measured this session — no prior-period count, BLS category, or industry report was fetched that isolates Medicare Advantage IRF-admission-denial volume or appeal-staffing trend. Unknown (not a negative finding, simply not captured by the bounded search budget).

**Confidence: medium.** Two named freestanding IRFs (Mary Free Bed, Rehabilitation Hospital of Indiana — both exact target-user matches) are actively hiring for roles whose stated task is "determination of inpatient admission criteria" and "review of resources pre/post-discharge," i.e., the same admissions-and-denial-criteria work the wedge targets; several hundred appeals/denials-nurse roles appear nationally on two boards, consistent in order of magnitude. Not higher because the role title "utilization review nurse" is used industry-wide across payers, hospitals of every type, and insurers — no query isolates IRF/LTCH-specific admission-denial appeal work from general UR — and most figures are board-synthesized rather than independently re-fetched.

---

## Cross-candidate note on evidence discipline

Every board-level count above that is not explicitly marked "directly
fetched (measured)" should be read as **estimate**: it is WebSearch's
reported read of a job board's own result-count or page title, not a count
I personally rendered and verified via WebFetch. All four candidates hit
the same wall — Indeed, Glassdoor, and ZipRecruiter 403'd every direct
WebFetch attempt in this session — so the estimate/measured split is a
property of board access, not of any one candidate's underlying demand.
