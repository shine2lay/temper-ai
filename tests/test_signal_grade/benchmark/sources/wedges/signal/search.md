# Search-Demand Signal (Rung 0 / WORDS tier) — 2026-10-01

Scope note: this is the weakest of the four evidence rungs. It measures
whether people TYPE queries about the problem, not whether they pay.
Google Trends did not render numeric values via fetch (HTTP 429 on
trends.google.com; this was tried once and not retried further to stay
within budget) — all "trend direction" calls below are therefore based on
repeat-survey deltas, vendor-launch cadence, or job-posting snapshots, NOT
on a fetched Trends slope. Direct Reddit fetches (reddit.com/r/*/about.json)
were blocked by the tool ("unable to fetch from www.reddit.com"), and the
third-party aggregator subredditstats.com rendered its page shell without
populating any subscriber numbers — so no numeric subreddit-size figure is
reported for any candidate; this is a real gap, not an omission.

---

## Candidate A (NEW) — Dental denied/underpaid-claim follow-up for Open Dental offices

**Core queries checked:** "dental insurance claim denied follow up", "Open
Dental outstanding insurance claims report", "dental insurance aging
report unpaid claims", "dental insurance coordinator claims follow-up job"

**Trend direction:** unknown — no Trends read, no historical snapshot to
diff against. Qualitative proxy (multiple vendors publishing fresh 2026
content + active job postings) is consistent with sustained-to-rising
interest but is an estimate, not a measured slope.

**Evidence:**
1. Open Dental's own manual documents a built-in "Outstanding Insurance
   Claims Report" whose explicit purpose is tracking/delegating follow-up
   on claims that haven't been paid — i.e. the PMS vendor itself already
   ships a tool for exactly this task, confirming it's a named, recurring
   workflow inside the target user's own software.
   - URL: https://opendental.com/manual/reportoutins.html
   - Date accessed: 2026-10-01
   - Quote (via search synthesis of page): "Outstanding Insurance Claims
     Report to track outstanding insurance claims and preauthorizations,
     where users can update tracking status for many claims at once or
     delegate staff to follow-up on claims."
   - measured_or_estimate: measured (feature exists, confirmed by vendor
     manual)
   - source_quality: primary (the PMS vendor's own documentation)

2. A small cluster of vendors sell point solutions against this exact pain
   for Open Dental specifically — DayDream Dental publishes "How to Resubmit
   Denied Claims in OpenDental: Step-by-Step Process for Claim Recovery" and
   "Why Dental Claims Get Denied & How to Fix Them," and separately Dental
   Claim Support (an outsourced dental billing company) runs its blog
   around the insurance aging report as "the #1 report your dental team
   needs to understand."
   - URLs: https://www.daydream.dental/blog-post/how-to-resubmit-denied-claims-in-opendental-step-by-step-process-for-claim-recovery ;
     https://www.dentalclaimsupport.com/blog/how-to-manage-your-aging-report
   - Date accessed: 2026-10-01
   - Quote: "Continue working the insurance aging report at least twice a
     week until your collections are at 98%."
   - measured_or_estimate: estimate (existence of vendor content, not a
     volume number)
   - source_quality: vendor

3. Dentaltown — the largest online dental-professional community, 250,000+
   registered members per its own "What is Dentaltown" article — runs a
   dedicated "Dental Billing Support - Insurance Tips" channel with
   recurring posts specifically on aging-report accuracy and unpaid-claim
   handling; individual posts drew measured view counts in the ~266-305
   range at fetch time (small numbers, but this is a narrow niche channel
   inside a quarter-million-member community, not the community's overall
   traffic).
   - URLs: https://www.dentaltown.com/magazine/article/7233/what-is-dentaltown ;
     https://www.dentaltown.com/channel/1169/dental-billing-support-insurance-tips
   - Date accessed: 2026-10-01
   - Quote: "Is Your Insurance Aging Report Inflated?" (303 views); "How to
     Avoid Claims Hitting Timely Filing Period" (305 views)
   - measured_or_estimate: measured (member count and view counts as
     fetched)
   - source_quality: secondary (Dentaltown's own about-page for member
     count; the channel view counts are primary/platform-reported)

4. Job boards show live, concrete hiring demand for the human version of
   this task: Glassdoor lists "2,621 Dental claims jobs in United States,"
   and postings for "Dental Insurance Coordinator" / "Dental Claim Support
   Specialist" explicitly name "claims follow-up," "pending or delayed
   claims," and "A/R" as core duties.
   - URL: https://www.glassdoor.com/Job/dental-claims-jobs-SRCH_KO0,13.htm
   - Date accessed: 2026-10-01
   - Quote: "2,621 Dental claims jobs in United States"
   - measured_or_estimate: measured (job-board count at fetch time, not a
     trend)
   - source_quality: secondary (job aggregator listing count)

**Confidence: low-med.** The problem is clearly named and staffed-for (PMS
vendor's own report, dedicated billing-service companies, job postings),
but there is no independently-fetched search-volume number, no Trends
slope, and no subreddit-size figure — only adjacent proxies. Treat this as
"the problem is real and named" rather than "search interest is rising."

---

## Candidate A0 (CONTROL, OLD) — Dental insurance-eligibility verification before the visit

**Core queries checked:** "dental insurance eligibility verification
software", "automated dental insurance verification benefits"

**Trend direction:** unknown on searcher demand specifically, but the
SUPPLY side shows a clear, dated escalation — which is itself the brief's
own "bundled for free" thesis playing out in public press releases.

**Evidence:**
1. Henry Schein One (the company behind Dentrix, one of the largest dental
   PMS platforms) issued a press release introducing built-in "Dentrix
   Eligibility Offerings" — i.e. the incumbent practice-management vendor
   folding eligibility verification into its own platform rather than
   leaving it to a standalone paid tool.
   - URL: https://www.businesswire.com/news/home/20240904669213/en/Henry-Schein-One-Introduces-Dentrix-Eligibility-Offerings
   - Date: 2024-09-04 (per URL date-stamp and businesswire listing)
   - Quote: "Henry Schein One Introduces Dentrix Eligibility Offerings"
   - measured_or_estimate: measured (press release exists, dated)
   - source_quality: vendor (primary vendor PR)

2. Roughly 16 months later, a second major dental-AI vendor launched a
   competing feature: VideaHealth's "AutoVerify."
   - URL: https://www.businesswire.com/news/home/20260114241532/en/VideaHealth-Launches-AutoVerify-to-Bring-Speed-and-Accuracy-to-Insurance-Eligibility-Checks
   - Date: 2026-01-14
   - Quote: "VideaHealth Launches AutoVerify to Bring Speed and Accuracy to
     Insurance Eligibility Checks"
   - measured_or_estimate: measured (press release exists, dated)
   - source_quality: vendor

3. Multiple additional vendors (Overjet, Curve Dental "Eligibility+",
   Dentrix "Verify Coverage Instantly") all market near-identical automated
   eligibility features as of 2026, and secondary buyer's-guide content
   explicitly frames eligibility checks as commoditized: "Automated
   appointment reminders and digital insurance eligibility checks are now
   considered baseline requirements, not differentiators."
   - URL: https://www.patientdesk.ai/blog/dental-practice-management-software-8-must-know-facts-for-2026
   - Date accessed: 2026-10-01
   - Quote: "digital insurance eligibility checks are now considered
     baseline requirements, not differentiators"
   - measured_or_estimate: estimate (editorial framing, not a measured
     number)
   - source_quality: listicle

4. A broader (non-dental-specific) market-research estimate puts the
   general "insurance eligibility verification" software market at "$2.39
   billion in 2025 growing to $2.57 billion in 2026" (7.5% CAGR) — directionally
   rising, but this figure spans all of healthcare, not dental specifically,
   so it is only weak corroboration.
   - URL: https://www.researchandmarkets.com/reports/6076343/insurance-eligibility-verification-market-report
   - Date accessed: 2026-10-01 (report dated 2026)
   - Quote: "grow from $2.39 billion in 2025 to $2.57 billion in 2026 at a
     CAGR of 7.5%"
   - measured_or_estimate: estimate (market-research sizing, not search
     volume)
   - source_quality: vendor (market-research-firm report summary)

**Confidence: med.** Strong, dated, corroborating evidence that this
specific front-end task is being actively absorbed into free/bundled PMS
features by multiple incumbents (exactly the dynamic the opportunity brief
flagged) — but that is evidence about the competitive/supply landscape,
not a direct measurement of rising or falling searcher demand. No Trends
or community-size figure obtained.

---

## Candidate B (NEW) — Medicare Advantage admission-denial appeal packets for rehab hospitals (IRFs/LTCHs)

**Core queries checked:** "Medicare Advantage denial appeal inpatient
rehabilitation facility admission", "AMRPA Medicare Advantage denial
survey", "IRF prior authorization denial appeal overturn rate"

**Trend direction: rising** — based on the trade association's own
repeated survey, the denial rate it measures has increased between its two
most recent fielding rounds (2021 vs. 2024), and the two most relevant
federal oversight reports both post in 2026, indicating sustained/growing
regulatory and industry attention to the same number. This is a measured
problem-prevalence trend, not a literal search-query trend — flagged
explicitly because this is a narrow B2B niche with no visible public
forum/community trail (no subreddit, no consumer search community found
for IRF admissions/UR staff).

**Evidence:**
1. AMRPA (American Medical Rehabilitation Providers Association) fielded a
   nationwide survey of 367 IRFs (~30% of IRFs nationwide, ~19,000 licensed
   beds) covering July-August 2024, logging 27,135 total MA prior-auth
   requests.
   - URL: https://amrpa.org/medicare-advantage-prior-authorization-survey/
   - Date: survey period July-August 2024; page accessed 2026-10-01
   - Quote: "15,571 of those requests were initially denied by the MA plan
     (57.4% of all requests)... 24.8% appealed (3,866)... 34.4% were
     overturned by the plan upon appeal (1,329)."
   - measured_or_estimate: measured
   - source_quality: primary (the trade association's own fielded survey)

2. AMRPA's earlier (August 2021) survey round found MA plans "overrule
   rehabilitation physician judgment" at a 53% rate, versus the 2024
   round's 57.4% initial-denial rate — a measured increase across the two
   survey waves the association itself ran.
   - URL: https://amrpa.org/medicare-advantage-prior-authorization-survey/
     (same page, historical section) and corroborating secondary coverage
     found via search
   - Date: 2021 survey vs. 2024 survey, both referenced on the above page;
     accessed 2026-10-01
   - Quote: "Earlier Survey (August 2021): The survey found that MA plans
     overrule rehabilitation physician judgment at a rate of 53%."
   - measured_or_estimate: measured
   - source_quality: primary

3. HHS Office of Inspector General report (OEI-09-24-00330, published
   2026-06-08) reviewed 19 Medicare Advantage Organizations and found they
   "collectively overturned 36 percent of LTCH denials and 43 percent of
   IRF denials" on appeal, with IRF overturn rates ranging 14%-86% by
   plan — independent federal corroboration of the AMRPA figures.
   - URL: https://oig.hhs.gov/reports/all/2026/the-three-largest-medicare-advantage-organizations-denied-requests-for-long-term-acute-care-and-inpatient-rehabilitation-at-some-of-the-highest-rates/
   - Date: issued 2026-06-08, posted 2026-06-11
   - Quote: "MAOs collectively overturned 36 percent of LTCH denials and 43
     percent of IRF denials." IRF overturn rates ranged "from 14 percent to
     86 percent."
   - measured_or_estimate: measured
   - source_quality: primary (federal oversight agency)

4. KFF's independent analysis (2026-07-06) of the same underlying CMS data
   found LTCH denial rate 65%, IRF denial rate 54%, against an overall MA
   prior-auth denial rate of under 8% — i.e. post-acute requests are denied
   roughly 7-8x more often than the average MA prior-auth request, a
   striking and independently-replicated magnitude.
   - URL: https://www.kff.org/medicare/medicare-advantage-insurers-deny-prior-authorization-requests-for-post-acute-care-at-substantially-higher-rates-than-the-overall-denial-rate/
   - Date: 2026-07-06
   - Quote: "Long-Term Care Hospitals (LTCH): 65%; Inpatient Rehabilitation
     Facilities (IRF): 54%; Overall MA Prior Authorization Rate: Less than
     8%."
   - measured_or_estimate: measured
   - source_quality: secondary (independent policy-research org analyzing
     primary government data)

**Confidence: med.** This candidate has by far the strongest, most
independently-corroborated PROBLEM-PREVALENCE data of the four (three
separate sources — a trade association, a federal watchdog, and an
independent policy analyst — converge on denial rates in the 50-65% range
for this exact population). However, that is a measure of how often the
problem occurs and how much money is at stake, not a measure of searcher
query behavior — I found zero forums, subreddits, or query-suggestion data
for this niche's staff (admissions directors, UR/billing leads), so the
WORDS-tier signal proper (people typing queries) is effectively absent;
confidence is capped at "med" specifically because of that gap, despite
the strength of the underlying problem data.

---

## Candidate B0 (CONTROL, OLD) — Prior-authorization submission and tracking for post-acute providers

**Core queries checked:** "prior authorization automation software
post-acute care", "prior authorization burden survey AMA physicians"

**Trend direction:** unknown on searcher-query trend specifically (no
Trends data obtained); the underlying national prior-auth burden is
reported as persistently high in AMA's recurring survey series, and the
post-acute-specific automation market already shows multiple competing
incumbents — both signals point to a mature, contested space rather than
an emerging one.

**Evidence:**
1. AMA's national prior-authorization survey (covered by AHA 2026-05-14)
   found physicians and staff complete ~40 prior authorizations per
   physician per week, spending ~13 hours/week on the work; CMS separately
   estimates ~700 hours and ~$34,000 per provider annually in PA burden.
   This is physician-wide, not post-acute-specific, but is the best
   available proxy national figure.
   - URL: https://www.aha.org/news/headline/2026-05-14-ama-survey-shows-physicians-patients-continue-be-heavily-burdened-prior-authorization
   - Date: 2026-05-14
   - Quote: "Physicians and their staff complete an average of 40 prior
     authorizations per physician each week and spend 13 hours on the
     work."
   - measured_or_estimate: measured (AMA's own survey, reported via AHA)
   - source_quality: secondary (AHA summarizing the AMA's primary survey)

2. The post-acute PA-automation vendor space is already dense: SPRY claims
   "500+ rehab clinics" as customers and "automates up to 80% of prior
   authorization requests"; Silna Health, CarePort, and Aidin all market
   directly to post-acute/rehab referral and authorization workflows; CB
   Insights tracks "Prior Authorization Software" as a defined market
   category under Health Insurance & RCM Tech.
   - URLs: https://www.sprypt.com/prior-authorization ;
     https://www.cbinsights.com/esp/healthcare-&-life-sciences/health-insurance-&-rcm-tech/prior-authorization-software
   - Date accessed: 2026-10-01
   - Quote: "SPRY automates up to 80% of prior authorization requests with
     AI and streamlines insurance operations for 500+ rehab clinics."
   - measured_or_estimate: estimate (vendor-claimed customer count, not
     independently verified)
   - source_quality: vendor

3. Silna Health's own positioning spans "behavioral health, physical
   health, ambulatory specialty care, and post-acute care including home
   health, skilled nursing, and hospice" — i.e. a well-funded multi-vertical
   PA vendor already covers this exact use case, reinforcing the "already
   bundled/commoditized" read the brief used to deprioritize this as the
   wedge.
   - URL: https://www.silnahealth.com/resources/best-prior-authorization-software/
   - Date accessed: 2026-10-01
   - measured_or_estimate: estimate
   - source_quality: vendor

**Confidence: low-med.** The national PA-burden number is solid and
primary-sourced (AMA), but every post-acute-specific figure here is a
vendor claim, and no independent search-volume, Trends, or
community-size data was obtained. The clearest honest read is: the
general problem (PA burden) is well-documented and large, but the
specific SaaS niche this control targets already has several funded
incumbents, which is consistent with — but does not by itself prove —
the brief's claim that this front-end task is becoming commoditized.
