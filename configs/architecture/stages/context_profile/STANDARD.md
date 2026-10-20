# Context profile stage: the standard (contract v2)

System architecture, queue #122, 2026-10-20. Initiative system-arch-in-temper, project arch-stage-context.
Accountable lead: architecture. Frozen before any model stage is built: what a great "product context and
priorities" stage must produce, and how it is measured. Nothing here runs a model.

The stage reads one product brief and returns a **context profile**: lifecycle maturity, current and
external systems, workload, performance, reliability, privacy, security, team, budget, hard constraints,
ranked goals, unknowns and assumptions, every item
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

## H-CTX-2 (rule 20 hypothesis, contract v2)

Written before any v2 change (queue #127, 2026-10-20), from the architecture lead's review of #122's landed
foundation (temper-ai 3794e277).

- **What is wrong.** (1) The maturity scale contradicts three keys: `scaled` needs formal operations, yet
  three keys accept it for products without them, and one key fits no stage at all. (2) The contract has no
  place for the current system, the systems the product depends on, or performance targets: C4's context
  level and ATAM's performance attribute have no home, and such facts in five briefs are unkeyed or squeezed
  into `team.skills`. (3) A field left open is not required to be named as an unknown, so material gaps can
  pass silently. (4) Quotes have no length cap and the scorer matches by containment with no one-to-one
  pairing, so one padded quote can carry several facts and inflate recall (B2).
- **The one change.** Contract v2: a lifecycle-only maturity scale; `current_system`, `external_systems`
  and `performance.targets` with a `performance` goal criterion; every unknown or silent field named in
  `unknowns`; quotes of 2 to 40 words; one-to-one matching of items to key facts; one primary section per
  key fact; two more known cases and new planted profiles. Bars and ceilings unchanged.
- **Expected result, and how it is measured.** All known keys pass checker v2 and score 100% against
  themselves; every planted profile fails with exactly its named reasons, including the padded quote
  (credited once) and the long quote; no brief fact about current systems, external systems or performance
  is left unkeyed.
- **What would prove it wrong.** A known brief cannot be keyed without ambiguity under the new definitions,
  or padding still raises recall.

## Where things are

| Path (under configs/architecture/) | What |
|---|---|
| `stages/context_profile/STANDARD.md` | this standard |
| `stages/context_profile/contract.v2.schema.json` | the contract, JSON Schema 2020-12 |
| `bin/context_profile_check.py` | the checker: contract + brief, deterministic |
| `bin/context_profile_score.py` | the scorer: profile against a case's key, deterministic |
| `fixtures/context_profile/known/README.md` | the known-case table; no case content belongs in this standard or the schema |
| `fixtures/context_profile/known/<case-id>/brief.md` | a known case's brief (synthetic) |
| `fixtures/context_profile/known/<case-id>/key.json` | its answer key, written before any model run |
| `fixtures/context_profile/planted/<plant-id>.json` | a bad profile for a known case, with the failures it must cause |
| `tests/test_architecture/test_context_profile.py` (repo root) | the checker's and scorer's tests |

Both scripts use the standard library only. jsonschema is not a direct dependency of temper-ai (it comes in
through mcp), so the checker carries a small validator that knows exactly the keywords the schema uses and
refuses any other rather than skipping it.

## The contract

One JSON object, `"contract": "context_profile/v2"`. All sections are required; a section with nothing in
the brief is still present (an empty list, or `"unknown"`). No other keys are allowed anywhere.

**Sources.** Every item carries `source`, one of:
- `{"kind": "quote", "quote": "<exact text from the brief>"}`: one span of the brief, **2 to 40 words**.
  Compared after normalising case, whitespace, curly quote marks, dashes and markdown emphasis (`*`, `_`,
  backticks). Quote the shortest span that carries the whole item.
- `{"kind": "assumption", "why": "<the reasoning>"}`: the stage's own reading or derivation.

| Field | Shape | Holds |
|---|---|---|
| `brief_sha256` | optional hex | the brief it was made from; checked when present |
| `product` | `{summary, source}` | one line: what the product is |
| `maturity.stage` | idea, startup, growing, established, unknown | lifecycle only; see Maturity |
| `maturity.evidence[]` | facts | the evidence for that lifecycle stage |
| `current_system` | `{state: none\|exists\|unknown, source?, items[]}` | whether a system exists now; none and exists require a quote; unknown needs an unknowns entry and may omit source |
| `current_system.items[]` | `{kind, text, source}` | owned components, stack, hosting, data stores and clients as they are now; kind is component, stack, hosting, data_store, client or other |
| `external_systems[]` | `{name, role, source}` | systems not owned by the product that it reads from, writes to or depends on: feeds, ERPs, identity providers, payment processors, devices, partner APIs |
| `workload.observed[]` | `{what, value, unit, source}` | measured load now; must be quoted |
| `workload.projected[]` | same | forecasts, capacity forecasts and hoped-for workload |
| `workload.peaks[]` | same | busiest moments, bursts, seasonality and qualitative load or speed complaints without a stated response target |
| `performance.targets[]` | same | stated latency, throughput, freshness or capacity targets, not observations or invented numbers |
| `reliability.availability` | fact or `"unknown"` | uptime target, SLA or stated outage tolerance |
| `reliability.data_loss_tolerance` | fact or `"unknown"` | how much data may be lost (RPO) |
| `reliability.recovery_time` | fact or `"unknown"` | how fast it must come back (RTO), not uptime or on-call coverage |
| `privacy.data_categories[]` | facts | kinds of personal data held |
| `privacy.sensitivity` | `{level, source}` or `"unknown"` | none, low, moderate, high; see Sensitivity |
| `privacy.retention[]` | facts | how long data is kept, when deleted |
| `privacy.sharing[]` | facts | who else gets data (processors, partners) |
| `privacy.jurisdictions_or_rules[]` | facts | laws, regions, contracts that bind data |
| `security.requirements[]` | facts | controls the brief asks for |
| `security.threats[]` | facts | named attackers, abuse, incidents; not a load slowdown |
| `security.compliance[]` | facts | certifications, audits and binding compliance obligations |
| `team.size` | fact or `"unknown"` | people who build and run it |
| `team.skills[]` | facts | what they know and do not know; not a substitute for the installed stack |
| `team.operating_capacity[]` | facts | time and on-call they can give |
| `budget.build` | fact or `"unknown"` | money available to build (or total available funding), never a revenue figure |
| `budget.run_monthly` | fact or `"unknown"` | money to run, per month |
| `constraints[]` | `{id: C<n>, text, source}` | must-holds; see Constraints and goals |
| `goals[]` | `{id: G<n>, criterion, rank, note, source}` | ranked, tradeable preferences |
| `unknowns[]` | `{question, why_it_matters, decisions_affected[], material, field?}` | what the brief leaves open |
| `assumptions[]` | `{text, why}` | working assumptions the stage made |

A fact is `{value, source}`; `value` is a short statement in the stage's words. `unknowns[].field`, when
given, names the contract field the unknown is about (the schema lists the allowed names).

## Rules for filling it

**Unknown, never guessed.** A fact the brief does not give is `"unknown"` (scalar fields) or an empty
list. Every such field needs an `unknowns` entry with `field` equal to its path, `material: true` or `false`,
and `why_it_matters`. This includes non-material silence: explain why no decision turns on it rather than
silently dropping it. The checker enforces this without a key. Empty `current_system.items` is exempt when
state is none or unknown (there is no known system to describe); empty maturity evidence is covered by
`maturity.stage: unknown`. Empty `unknowns` and `assumptions` do not recursively create unknowns. Empty
constraints or goals do need their own entries. An assumption may *interpret* or *derive from* stated
facts (sensitivity, a computed number); it may not fill a field the brief says nothing about.
Working assumptions go in `assumptions`.

**Numbers.** Every number an item states (digits, words like "two hundred", scales like "1.2M" or "40k")
must appear in that item's quote, by value. A number the brief does not say, such as a rate computed from a
monthly figure, makes the item an assumption.

**Observed, projected, peaks.** Observed workload is measured now and must be quoted. Forecasts, targets,
hopes and investor-deck figures are projected, however they are worded. A number given in the present tense
and later called a target or a plan is projected. Someone else's numbers (a competitor, a market size) are
not this product's workload at all.

**Maturity is lifecycle only**, never a scale or organisation label:
- `idea`: nothing in users' hands.
- `startup`: in use, demand not yet proven or stable.
- `growing`: proven demand rising fast enough that scale or team growth is a near-term concern.
- `established`: proven, steady demand with slow or flat growth, at any size or team.
- `unknown`: the brief does not settle which stage applies. Any other stage must name its evidence.

`scaled` and `large` are removed. Workload, team and constraint facts carry volume, organisation size and
governance. Age, user count and formal operations alone cannot settle demand trend. A replacement does not
automatically reset an existing product's lifecycle: if its boundary is unclear, name that unknown.

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
  never traded for cost (owner, 2026-10-20). A mandatory performance target is also a constraint, on the
  same rule; record the target in performance and its must-hold in constraints.
- A **goal** is a preference to rank and trade: want, prefer, ideally, as cheap as possible, fast. Each goal
  has one criterion: `cost` (money spent), `efficiency` (resource use per unit of work), `performance`
  (speed for users: latency, throughput, freshness), `privacy`, `security`, `reliability`, `delivery_speed`,
  `operability` (effort to run it), `change_cost` (effort to change it), `scalability`, `other`. Efficiency
  is not user-visible speed; delivery speed is how quickly the team ships. Cost and efficiency are
  separate; so are privacy and security.
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
| `quote_too_long` | a quote of more than 40 words (counted after normalising, split on whitespace) |
| `quote_not_in_brief` | a quote that is not one span of the brief after normalising |
| `number_not_in_quote` | an item states a number its quote does not hold |
| `system_name_not_in_quote` | a quoted external system's name is not in its quote |
| `observed_not_quoted` | observed workload sourced as an assumption |
| `current_system_not_quoted` | state none or exists has no quote |
| `unknown_field_unnamed` | a scalar is unknown, or a fact list is empty, without an unknowns entry for its path |
| `maturity_without_evidence` | a stage other than unknown with no evidence |
| `rank_duplicate`, `rank_gap` | goal ranks are not 1 to n, each once |
| `duplicate_id` | two constraints or two goals share an id |
| `constraint_goal_overlap` | a constraint and a goal stand on the same text (one quote inside the other) |

## The scorer: context_profile_score.py

Compares a profile with a known case's key, by text, never by a model. An item is eligible for a fact when
its quote contains a key anchor (normalised as the checker does), it is in the primary or alternative
section, and it states the key's number, if any. Facts and items are then paired **one-to-one by maximum
bipartite matching** (augmenting paths): one item counts for at most one fact, however much its quote
contains. Duplicate mentions can be separate items; padding one item cannot buy several facts.

**Tie-break:** facts in key order, eligible items in profile order. A matched fact stays matched, although
an augmenting path may move it to another item. If there are too few items, later facts in key order are
left unmatched. This is deterministic and finds maximum cardinality, not a greedy first-hit count.

- `--case DIR PROFILE` one profile; `--case DIR --self` the key's reference profile (must score 100%);
  `--case DIR --runs P1 P2 P3` several runs of one case, each scored, then compared (B5);
  `--pool S1 ... SN` one run's case scores pooled against the bars. Every mode lints the key first and
  refuses a broken key (anchor not in the brief, wrong brief hash, duplicate ids, a fact allowed in a field
  the key says is open).

| Reason | Means |
|---|---|
| `checker:<reason>` | any checker error, carried over |
| `fact_missed` | no item quotes the fact |
| `fact_quote_shared` | every eligible item is already paired with another fact; no extra recall credit |
| `fact_misplaced` | quoted, but in a section the key does not allow |
| `fact_wrong_value` | quoted in the right section without the key's number |
| `open_field_filled` | a field the brief says is open was filled from that very sentence |
| `unsupported_fill` | a field the brief leaves open was filled from a quote that does not carry it (invented) |
| `guessed_unknown` | a field the brief leaves open was filled by assumption (invented) |
| `unknown_not_flagged` | no unknown matches the key's material unknown (equal field paths when both named; otherwise every term group) |
| `unknown_not_material` | it is named but marked `material: false` |
| `constraint_as_goal`, `constraint_also_goal`, `constraint_missing` | a hard constraint was made a goal, made both, or left out |
| `goal_as_constraint`, `goal_also_constraint`, `goal_missing`, `goal_wrong_criterion` | the same for a goal, or its criterion is wrong |
| `goal_order` | the top three criteria differ from every order the key accepts |
| `maturity_mismatch`, `sensitivity_mismatch` | outside the key's accepted values |
| `trap:<reason>` | an item in a forbidden section stands on trap text (invented) |

Trap reasons: `projected_as_observed` (a forecast used as measured), `not_this_product` (someone else's
numbers), `contradicted_claim` (a claim the brief later corrects), `hedged_as_fact` (a hope or guess used as
a fact), `future_scope` (a later idea used as a current need), `superseded` (a figure the brief replaces).

**Invented** = checker `quote_not_in_brief`, `number_not_in_quote`, `observed_not_quoted` or
`system_name_not_in_quote`, plus
`unsupported_fill`, `guessed_unknown` and every trap hit. `score_pct` is the mean of nine rates (facts,
unknowns, constraints, goals, goal order, maturity, sensitivity, open fields kept open, no invention), for
tracking only; the bars decide.

**Key format** (`"key": "context_profile_key/v2"`): `case_id`, `category`, `tests` (what the case tests),
`brief_sha256`; `maturity.accepted[]` `{stage, quotes[]}` (each accepted stage has supporting brief quotes),
`sensitivity.accepted[]`; `facts[]` `{id, anchors[], primary, alt?, why_alt?, value?}` (one primary section,
at most one alternative, justified by why_alt); `constraints[]` `{id, anchors[]}`; `goals[]` `{id, anchors[],
criterion, rank}`; `goal_order.accepted_top3` (optional; default the key's own top three); `unknowns[]`
`{id, field?, terms?}` where explicit field paths take priority when both sides name one, otherwise every
terms group needs one of its words; `traps[]` `{id, anchors[], reason,
forbidden_in[]}`; `fields_unknown[]` `{field, open_anchors[], not_material_reason?}`; and `profile`, the
reference profile. Each fields_unknown entry either names a required material unknown in unknowns, or
has a not_material_reason, never both. It lists exactly the fact fields the reference leaves unknown or
empty. Ids are unique across the key. Anchors are short exact spans. A key is written before model runs
and changes only with a recorded reason.

**Report only, no new bar:** `material_unknowns_not_in_key` lists material profile unknowns not matched to
a key unknown (field and question); `quote_words` gives median and maximum word length over quoted items.
They invite review, not an automatic failure or a lower bar.

**Planted profile format** (`"planted": "context_profile_planted/v2"`): `plant_id`, `case_id`, `fault`,
`expect[]` `{reason, ref}` (every failure, no more or fewer), and either a full `profile` or `edits[]`
`{op: set|remove|append, path: [key or index, ...], value?}` applied to the reference profile. The CLI exits
0 when the bad profile fails exactly as expected; this is a plant-test pass, not a clean profile.

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

Synthetic briefs, no real customer data or secrets. The case table lives only in
`fixtures/context_profile/known/README.md`, not in this standard or the schema: stage and held-out writers
may read these two documents without seeing known-case answers. Known keys predate any model run and must
pass the checker and score 100% against themselves.

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

## v2 changes and why

Architecture lead review of #122 (temper-ai 3794e277), queue #127, 2026-10-20; H-CTX-2 above. No consumer
exists yet, so v2 replaces v1 rather than maintaining a compatibility path; v1 remains in git history.

- Lifecycle-only maturity removes size and governance labels that contradicted the keys. Each accepted
  stage is re-derived from the brief with its own supporting quotes; absence of trend evidence stays unknown.
- Current and external systems give C4 context a home; performance targets and a separate performance goal
  give ATAM's user-visible response measures a home. Efficiency means resource use per unit of work.
- Every silent field is explicitly named, material or not; key omissions need a non-material rationale or
  a required material unknown. This closes silent gaps without inventing answers.
- Quotes are bounded to 2–40 words; maximum one-to-one matching prevents padded evidence inflating B2.
  Facts have one primary section and at most one justified alternative, not broad section allowances.
- Two fresh cases and seven additional planted profiles exercise these changes. The case table and all
  case-derived examples are outside the standard and schema; no model stage is built or run here.
- Extra material unknowns and quote-length summaries are report-only. **B0–B10 and all cost and time
  ceilings are unchanged.** The task report records the hypothesis result and any keying ambiguity.

## Sources

- Simon Brown's C4 model: a system context includes what is being changed and the external systems it
  reads, writes or depends on. Here: current_system and external_systems separate installed reality from
  team skills and proposed architecture.
- SEI's ATAM (Kazman, Klein, Clements): business drivers and a quality-attribute utility tree, refined into
  measurable scenarios ranked by importance. Here: goals with one criterion each and a rank are the tree's
  top; workload, performance, reliability and peak items with value and unit are the scenarios' response measures;
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
