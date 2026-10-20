# Context profile stage: the standard (contract v1)

System architecture, queue #122, 2026-10-20. Initiative system-arch-in-temper, project arch-stage-context.
Accountable lead: architecture. Frozen before any model stage is built: what a great "product context and
priorities" stage must produce, and how it is measured. Nothing here runs a model.

The stage reads one product brief and returns a **context profile**: maturity, workload, reliability,
privacy, security, team, budget, hard constraints, ranked goals, unknowns and assumptions, every item
standing on an exact quote from the brief or labelled as an assumption. Every later architecture stage
(options, trade-offs, ADRs, reviews) reuses the profile instead of reading the brief its own way.

## H-CTX-1 (rule 20 hypothesis)

- **What is wrong.** No shared, checked context. Each architecture workflow reads the brief its own way and
  none of them asks for the facts an architecture depends on: epd_plan_architect, epd_plan_lead,
  epd_plan_check, task_review, code_analyst and arch_land_review mention maturity, workload, privacy,
  retention or unknowns zero times (grep, 2026-10-20; task_review mentions budget once). A plan is fitted to
  whatever the model happened to notice, and nobody can tell whether a fact was read, missed or made up.
- **The one change.** One reusable stage turns the brief into a profile under this contract. A script
  checks it (every quote is in the brief, every number is in its quote, ranks, sections) and a second script
  scores it against answer keys written before any model run.
- **Expected result, and how it is measured.** On the 12 known cases, 3 runs each, the stage meets bars
  B0-B10 below: no invented facts, at least 95% of material facts, every material unknown flagged, every
  hard constraint kept a constraint, consistent runs, inside the cost and time ceilings. Measured by
  context_profile_score.py (one run: `--pool`; three runs of a case: `--runs`) and the runs' cost records;
  then confirmed on held-out cases written by another chat.
- **What would prove it wrong.** (a) A careful reading of a brief finds material facts its key does not
  list, or the key lists something that is not material: the keys are the weak point; fix them before any
  stage is judged by them. (b) After three prompt fixes, each with its own hypothesis, a stage still cannot
  meet B2 and B3 without breaking B1: a single model call is the wrong shape (split extraction from
  classification). (c) Profiles that meet the bars still let a later stage make a decision the brief rules
  out: the contract misses something decisions need.

## Where things are

| Path (under configs/architecture/) | What |
|---|---|
| `stages/context_profile/STANDARD.md` | this standard |
| `stages/context_profile/contract.v1.schema.json` | the contract, JSON Schema 2020-12 |
| `bin/context_profile_check.py` | the checker: contract + brief, deterministic |
| `bin/context_profile_score.py` | the scorer: profile against a case's key, deterministic |
| `fixtures/context_profile/known/<case-id>/brief.md` | a known case's brief (synthetic) |
| `fixtures/context_profile/known/<case-id>/key.json` | its answer key, written before any model run |
| `fixtures/context_profile/planted/<plant-id>.json` | a bad profile for a known case, with the failures it must cause |
| `tests/test_architecture/test_context_profile.py` (repo root) | the checker's and scorer's tests |

Both scripts use the standard library only. jsonschema is not a direct dependency of temper-ai (it comes in
through mcp), so the checker carries a small validator that knows exactly the keywords the schema uses and
refuses any other rather than skipping it.

## The contract

One JSON object, `"contract": "context_profile/v1"`. All sections are required; a section with nothing in
the brief is still present (an empty list, or `"unknown"`). No other keys are allowed anywhere.

**Sources.** Every item carries `source`, one of:
- `{"kind": "quote", "quote": "<exact text from the brief>"}`: one span of the brief, at least two words.
  Compared after normalising case, whitespace, curly quote marks, dashes and markdown emphasis (`*`, `_`,
  backticks). Quote the shortest span that carries the whole item.
- `{"kind": "assumption", "why": "<the reasoning>"}`: the stage's own reading or derivation.

| Field | Shape | Holds | Example |
|---|---|---|---|
| `brief_sha256` | optional hex | the brief it was made from; checked when present | |
| `product` | `{summary, source}` | one line: what the product is | "A phone app that tracks kitchen food and suggests meals" |
| `maturity.stage` | idea, startup, growing, scaled, large, unknown | see Maturity | `"startup"` |
| `maturity.evidence[]` | facts | what the stage is read from | "140 paying customers" |
| `workload.observed[]` | `{what, value, unit, source}` | measured now; must be quoted | 1,200,000 page views a month |
| `workload.projected[]` | same | forecasts, targets, hopes | 10,000 users by the end of next year |
| `workload.peaks[]` | same | busiest moments, bursts, seasonality | 5x normal traffic on Monday 9-10am |
| `reliability.availability` | fact or `"unknown"` | uptime target or SLA | "99.9% monthly uptime in contracts" |
| `reliability.data_loss_tolerance` | fact or `"unknown"` | how much data may be lost (RPO) | "no booking may ever be lost" |
| `reliability.recovery_time` | fact or `"unknown"` | how fast it must come back (RTO) | "back within 4 hours" |
| `privacy.data_categories[]` | facts | kinds of personal data held | "therapists' session notes" |
| `privacy.sensitivity` | `{level, source}` or `"unknown"` | none, low, moderate, high; see Sensitivity | |
| `privacy.retention[]` | facts | how long data is kept, when deleted | "delete photos once read" |
| `privacy.sharing[]` | facts | who else gets data (processors, partners) | "Stripe handles card payments" |
| `privacy.jurisdictions_or_rules[]` | facts | laws, regions, contracts that bind data | "HIPAA", "data stays in the EU" |
| `security.requirements[]` | facts | controls the brief asks for | "SSO through the company's Okta" |
| `security.threats[]` | facts | named attackers, abuse, incidents | "a competitor scraped our listings" |
| `security.compliance[]` | facts | certifications and audits | "SOC 2 Type II by Q3" |
| `team.size` | fact or `"unknown"` | people who build and run it | "3 engineers" |
| `team.skills[]` | facts | what they know and don't | "no one has run Kubernetes" |
| `team.operating_capacity[]` | facts | time and on-call they can give | "part-time, 15 hours a week each" |
| `budget.build` | fact or `"unknown"` | money to build (or total money) | "$12,000 for the first year" |
| `budget.run_monthly` | fact or `"unknown"` | money to run, per month | "hosting under $150 a month" |
| `constraints[]` | `{id: C<n>, text, source}` | must-holds; see Constraints and goals | |
| `goals[]` | `{id: G<n>, criterion, rank, note, source}` | ranked, tradeable preferences | |
| `unknowns[]` | `{question, why_it_matters, decisions_affected[], material, field?}` | what the brief leaves open | |
| `assumptions[]` | `{text, why}` | working assumptions the stage made | |

A fact is `{value, source}`; `value` is a short statement in the stage's words. `unknowns[].field`, when
given, names the contract field the unknown is about (the schema lists the allowed names).

## Rules for filling it

**Unknown, never guessed.** A fact the brief does not give is `"unknown"` (scalar fields) or left out (list
fields), and when it is material it is named in `unknowns` with `material: true`. An assumption may
*interpret* or *derive from* what the brief says (a sensitivity level, a figure computed from stated
numbers); it may not fill a field the brief says nothing about. Working assumptions go in `assumptions`.

**Numbers.** Every number an item states (digits, words like "two hundred", scales like "1.2M" or "40k")
must appear in that item's quote, by value. A number the brief does not say, such as a rate computed from a
monthly figure, makes the item an assumption.

**Observed, projected, peaks.** Observed workload is measured now and must be quoted. Forecasts, targets,
hopes and investor-deck figures are projected, however they are worded. A number given in the present tense
and later called a target or a plan is projected. Someone else's numbers (a competitor, a market size) are
not this product's workload at all.

**Maturity** is read from the product's life stage and stakes, not from its user count alone:
- `idea`: nothing in users' hands yet; validating demand.
- `startup`: live with early or first paying users; small team; still finding fit; changes weekly.
- `growing`: proven demand, growing customers and team; customers depend on it; repeatability and scale
  start to hurt.
- `scaled`: established product with stable demand and formal operations (on-call, SLAs, several teams).
- `large`: a large organisation or product: many teams, high volume, strict governance.
- `unknown`: the brief gives no evidence. Any other stage must name its evidence.
A product with a million users and a two-person team serving read-mostly pages is not "large".

**Sensitivity** of the personal data held:
- `none`: no personal data.
- `low`: contact and account details, business data about companies.
- `moderate`: personal data whose leak harms people: purchase or location history, employee records,
  messages, minors' names without more.
- `high`: health, financial accounts or card data, government ids, biometrics, precise tracking, children's
  data in volume, anything in a legal special category (GDPR article 9, HIPAA's PHI).

**Material.** A fact is material when a different value would change an architecture decision: scale and
growth, peaks, reliability targets, data kinds and sensitivity, laws and contracts, security and
compliance demands, team size, skills and operating time, budgets, deadlines, systems that must be kept.
Founders' stories, brand and marketing copy are not material. An unknown is material when the brief does
not settle something the architecture needs and the plausible answers lead to different decisions: name
the decisions in `decisions_affected`. A contradiction or an unclear authority is an unknown too.

### Constraints and goals

- A **constraint** is a must-hold, kept whatever it costs: a law, regulation or signed contract; an
  explicit must, never or non-negotiable from someone with authority; a fixed money cap; a hard deadline
  with a stated consequence; a system that must be kept. Privacy and security requirements the brief makes
  mandatory (a promise to users, a regulation, a customer contract) are constraints, never goals, and are
  never traded for cost (owner, 2026-10-20).
- A **goal** is a preference to rank and trade: want, prefer, ideally, as cheap as possible, fast. Each goal
  has one criterion: `cost` (money spent), `efficiency` (resources used per unit of work), `privacy`,
  `security`, `reliability`, `delivery_speed`, `operability` (effort to run it), `change_cost` (effort to
  change it), `scalability`, `other`. Cost and efficiency are separate; so are privacy and security.
- Nothing is both. When a brief has a mandatory floor and a wish beyond it ("must be HIPAA compliant; we'd
  like more than the minimum"), the floor is a constraint and the wish is a goal, each on its own text.
- **Ranks** run 1 (top) to n, each once, from the brief's own words of priority ("above all", "first",
  "right after that"). When stakeholders disagree, rank by the words of whoever the brief says decides, and
  name the disagreement as a material unknown when the brief leaves it open.

## The checker: context_profile_check.py

`context_profile_check.py --brief brief.md profile.json` (a key.json is checked through its reference
profile). Prints one JSON report; exit 0 clean, 1 errors, 2 cannot run.

| Reason | Fails when |
|---|---|
| `missing_section` | a required top-level section is absent |
| `bad_enum` | a value outside its list (maturity stage, sensitivity level, criterion, unknown field) |
| `schema` | anything else the schema refuses: wrong type, unknown key, empty text, bad id |
| `brief_hash_mismatch` | `brief_sha256` is given and is not the brief's |
| `quote_too_short` | a quote of fewer than two words |
| `quote_not_in_brief` | a quote that is not one span of the brief after normalising |
| `number_not_in_quote` | an item states a number its quote does not hold |
| `observed_not_quoted` | observed workload sourced as an assumption |
| `maturity_without_evidence` | a stage other than unknown with no evidence |
| `rank_duplicate`, `rank_gap` | goal ranks are not 1 to n, each once |
| `duplicate_id` | two constraints or two goals share an id |
| `constraint_goal_overlap` | a constraint and a goal stand on the same text (one quote inside the other) |

## The scorer: context_profile_score.py

Compares a profile with a known case's key, by text, never by a model: an item carries a key entry when its
quote contains one of the entry's anchors (normalised as the checker does).

- `--case DIR PROFILE` one profile; `--case DIR --self` the key's reference profile (must score 100%);
  `--case DIR --runs P1 P2 P3` several runs of one case, each scored, then compared (B5);
  `--pool S1 ... S12` one run's case scores pooled against the bars. Every mode lints the key first and
  refuses a broken key (anchor not in the brief, wrong brief hash, duplicate ids, a fact allowed in a field
  the key says is open).

| Reason | Means |
|---|---|
| `checker:<reason>` | any checker error, carried over |
| `fact_missed` | no item quotes the fact |
| `fact_misplaced` | quoted, but in a section the key does not allow |
| `fact_wrong_value` | quoted in the right section without the key's number |
| `open_field_filled` | a field the brief says is open was filled from that very sentence |
| `unsupported_fill` | a field the brief leaves open was filled from a quote that does not carry it (invented) |
| `guessed_unknown` | a field the brief leaves open was filled by assumption (invented) |
| `unknown_not_flagged` | no unknown matches the key's material unknown (by field, or by every term group) |
| `unknown_not_material` | it is named but marked `material: false` |
| `constraint_as_goal`, `constraint_also_goal`, `constraint_missing` | a hard constraint was made a goal, made both, or left out |
| `goal_as_constraint`, `goal_also_constraint`, `goal_missing`, `goal_wrong_criterion` | the same for a goal, or its criterion is wrong |
| `goal_order` | the top three criteria differ from every order the key accepts |
| `maturity_mismatch`, `sensitivity_mismatch` | outside the key's accepted values |
| `trap:<reason>` | an item in a forbidden section stands on trap text (invented) |

Trap reasons: `projected_as_observed` (a forecast used as measured), `not_this_product` (someone else's
numbers), `contradicted_claim` (a claim the brief later corrects), `hedged_as_fact` (a hope or guess used as
a fact), `future_scope` (a later idea used as a current need), `superseded` (a figure the brief replaces).

**Invented** = checker `quote_not_in_brief`, `number_not_in_quote` or `observed_not_quoted`, plus
`unsupported_fill`, `guessed_unknown` and every trap hit. `score_pct` is the mean of nine rates (facts,
unknowns, constraints, goals, goal order, maturity, sensitivity, open fields kept open, no invention), for
tracking only; the bars decide.

**Key format** (`"key": "context_profile_key/v1"`): `case_id`, `category`, `tests` (what the case tests),
`brief_sha256`; `maturity.accepted` and `sensitivity.accepted` (lists); `facts[]` `{id, anchors[], in[],
value?}`; `constraints[]` `{id, anchors[]}`; `goals[]` `{id, anchors[], criterion, rank}`;
`goal_order.accepted_top3` (optional; default the key's own top three); `unknowns[]` `{id, field?,
terms?}` where `terms` is a list of groups and every group needs one of its words; `traps[]` `{id,
anchors[], reason, forbidden_in[]}`; `fields_unknown[]` `{field, open_anchors[]}` (fields the brief leaves
open; `open_anchors` is where it says so); and `profile`, the reference profile. Ids are unique across the
key. Anchors are short exact spans of the brief. A key is written before any model run and changes only
with a recorded reason.

**Planted profile format** (`"planted": "context_profile_planted/v1"`): `plant_id`, `case_id`, `fault` (what
was planted), `expect[]` `{reason, ref}` (every failure the scorer must report, no more, no fewer) and
`profile`.

## Bars

The stage is great when one set of 3 runs over all known cases, and then the held-out cases, meets every bar.

| Bar | What | Measured by | Origin |
|---|---|---|---|
| B0 | every profile passes the checker | pool `B0_contract` | the contract |
| B1 | no invented facts (see Invented) | pool `B1_no_invented`, `invented` = 0 | frozen |
| B2 | at least 95% of material facts captured, pooled per run | pool `fact_recall` | frozen |
| B3 | every material unknown flagged, marked material | pool `B3_unknowns_flagged` | frozen |
| B4 | every hard constraint is a constraint, never a goal | pool `B4_constraints_classified` | frozen |
| B5 | 3 runs per case consistent: same maturity, sensitivity, constraint and goal classes, flagged unknowns and top-three order, each run clean | `--runs` `consistent` | frozen |
| B6 | list price per run: median at most $1.00, max at most $2.00; wall time median at most 4 min | the runs' cost and time records | frozen |
| B7 | maturity within the key's accepted stages, every case | pool `B7_maturity` | added by #122 |
| B8 | sensitivity within the key's accepted levels, every case | pool `B8_sensitivity` | added by #122 |
| B9 | top-three goal order agrees on at least 90% of positions, pooled | pool `goal_order` | added by #122 |
| B10 | no goal promoted to a constraint | pool `B10_goals_stay_goals` | added by #122 |

B0-B6 are the project's frozen bars and are never lowered. B7-B10 were added by #122 and only make the bar
stricter: maturity and sensitivity drive later choices directly (the owner's maturity-fit rule), the plan
asked the scorer for goal-order agreement, and a preference treated as a must-hold over-constrains every
later option (the mirror of B4).

## Known cases

Synthetic briefs (300-1,500 words), no real customer data, no secrets. Each key was written before any
model run and passes the checker and scores 100% against itself (the tests hold both).

| Case | Category | What it tests |
|---|---|---|
| k01-idea-pantry | idea_stage | nothing built; guesses kept projected; a competitor's numbers; a public deletion promise is a constraint |
| k02-startup-invoicing | startup_paying | paying customers; card data handled by a processor; small budget; reliability stated loosely |
| k03-growing-scheduling | growing_b2b_saas | growing B2B SaaS; contract SLA and SOC 2 from customers; EU data; peaks |
| k04-large-photos | large_consumer | large consumer product; many teams; regional rules; minors excluded |
| k05-small-therapy | small_high_risk | three people holding therapy notes: HIPAA is a constraint, never a cost trade-off |
| k06-large-simple-transit | large_simple | a million monthly users, read-mostly, two-person team: not "large" |
| k07-conflict-marketplace | conflicting_priorities | CEO, CTO and sales disagree; the decider's ranking; the conflict is an unknown |
| k08-missing-volunteers | missing_budget_workload | no budget and no workload numbers: unknown, never guessed |
| k09-projected-fitness | projected_as_observed | deck figures in the present tense that are targets |
| k10-misleading-logistics | misleading_claim | "no personal data" contradicted later by stored GPS traces |
| k11-privacy-reading | privacy_vs_cost | children's data minimisation and retention limits against a cheaper hosting push |
| k12-internal-expenses | internal_tool_deadline | internal tool, hard deadline, systems that must be kept |

## Changes from the plan's contract sketch, and why

- Added `contract` (a version const) and optional `brief_sha256`, so a profile names its contract and the
  brief it was made from.
- `product` is `{summary, source}`: every item carries a source.
- `maturity.stage` also allows `unknown`, because missing facts are unknown, never guessed; the checker then
  requires evidence for every other stage. `evidence` is a list of facts.
- `reliability` holds three fields, each a fact or `"unknown"`, instead of one shared `source`: the three
  usually come from different sentences, and one source cannot quote all three.
- `privacy.retention` and `privacy.sharing` are lists of facts (briefs give several); `privacy.sensitivity`
  is `{level, source}` or `"unknown"`. `security`'s three fields, `team.skills` and
  `team.operating_capacity` are lists of facts; `team.size`, `budget.build` and `budget.run_monthly` are a
  fact or `"unknown"`.
- `constraints[].id` is C<n> and `goals[].id` G<n>; `unknowns[].decisions_affected` is a list of at least
  one decision; `unknowns[].field` (optional) names the field an unknown is about, so the scorer can match it
  without reading the text.

## Sources

- SEI's ATAM (Kazman, Klein, Clements): business drivers and a quality-attribute utility tree, refined into
  measurable scenarios ranked by importance. Here: goals with one criterion each and a rank are the tree's
  top; workload, reliability and peak items with value and unit are the scenarios' response measures;
  unknowns feed ATAM's risks and sensitivity points.
- Privacy by design (Cavoukian's seven principles) and GDPR article 5: data minimisation, purpose and
  storage limitation; article 9 special categories; HIPAA's minimum-necessary rule. Here: data kinds,
  sensitivity, retention and sharing are captured explicitly, and mandatory privacy terms are constraints.
- Nygard's architecture decision records: the profile is the shared "context" section later ADRs cite by
  item, instead of each restating the brief.
- The last responsible moment and one-way/two-way doors: `decisions_affected` lets a later stage defer a
  decision that waits on an unknown, and see which doors it must not close yet.
- The Twelve-Factor App, where relevant: backing services, dev/prod parity and disposability are judged by
  later stages; this stage records the facts they need (team operating time, systems that must be kept,
  hosting limits).
- Google's engineering practices and our grader rule (notebook): measured checks first; a model judge counts
  only after it agrees with known cases more than once (rules 16 and 17). This stage's checker and scorer
  have no model in them.
