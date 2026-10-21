# Context-profile meaning: labelled development cases

Task #137, H-CTX-6b. **Development only; never use these cases for acceptance.**
Builders may read this folder; sealed authors and later blind qualification must not use it.
No checker, scorer, schema, known brief/key or plant was modified. The frozen v2 checker
must pass each profile; the faults are about meaning, not malformed structure.

## Reading a variant

Each folder contains `profile.json` and `labels.json`. The profile is its known case's
reference profile (the key's own `profile`, as `--self` uses), with at most three
hand-authored edits at distinct atomic claim roots, or a byte-pinned #133 import.
Edits at separate roots do not depend on one another. Removing the final goal preserves
valid priority numbering and is labelled as a profile-level omission, not as a fake claim.

Inventory: each sourced fact, measure, item, constraint or goal is one atomic claim;
its value/text, qualifier and source are judged together. Maturity stage, system state,
unknown-valued scalar fields, each unknown record and each assumption record also count.
Section names, contract/hash metadata, and individual words inside source quotes do not
create claims. `/current_system/state` includes the system-level source for comparison.
`/maturity/stage` uses the first reference maturity-evidence span, or `none` if absent.

All claim paths occur exactly once. `origin: reference` means byte-equivalent JSON content
to the reference claim, automatically labelled supported with that reference's source
span; these rows do **not** count toward the hand-labelled good minimum. `origin: hand`
means an explicit case-specific judgment. Every changed or added claim requires one;
no label is inferred from the v2 checker output. Reference/profile SHA-256 fields hash
canonical JSON (sorted keys, UTF-8, compact separators); import SHA-256 hashes raw bytes.

Labels follow the binding design: `supported`, `contradicted`, `unsupported`, `uncertain`.
Every bad claim has exactly one F01–F12 family. Supported and uncertain claims have null
family. `uncertain` means a genuinely open proposition or conflicting/ambiguous sources,
not a random fabricated detail. Assumption-sourced values are supported unless the brief
contradicts them; F11 explicitly tests that an assumption cannot override another section.
`source_span` is byte-exact brief text or literal `none`; two-quote summaries additionally
list both byte-exact `supporting_spans`. Profile-level `omissions` identify the missing
key obligation kind/id and removed claim path. Unknowns and assumptions remain in the
inventory even if their own contract object has no source, in which case the span is `none`.

## Minimums (authored cases only; all #133 imports excluded)

103 authored variants; 60 bad claims;
60 hand-labelled good claims; 60 good traps;
15 uncertain claims; 8 omission variants;
all 14 known cases. Each family has 5 bad claims in 5 different cases.

Traps: comparator_paraphrase: 6, reordering: 44, two_quote_summary: 5, unit_conversion: 5.

| Claim label | Authored claims (all) | Authored hand labels | Imported claims (all) |
|---|---:|---:|---:|
| contradicted | 45 | 45 | 5 |
| supported | 4625 | 60 | 426 |
| uncertain | 15 | 15 | 0 |
| unsupported | 15 | 15 | 2 |

| Family | Bad claims | Different cases | Case IDs |
|---|---:|---:|---|
| F01 Comparator | 5 | 5 | k01, k03, k05, k13, k14 |
| F02 Unit/scale | 5 | 5 | k02, k03, k04, k09, k13 |
| F03 Number | 5 | 5 | k02, k03, k04, k13, k14 |
| F04 Negation/polarity | 5 | 5 | k02, k05, k06, k08, k09 |
| F05 Condition/time/tense | 5 | 5 | k01, k03, k04, k08, k13 |
| F06 Added requirement/permission | 5 | 5 | k01, k04, k05, k11, k12 |
| F07 Scope | 5 | 5 | k03, k06, k08, k12, k14 |
| F08 Label/section | 5 | 5 | k01, k02, k03, k09, k14 |
| F09 Materiality | 5 | 5 | k01, k07, k08, k13, k14 |
| F10 Unknown relevance | 5 | 5 | k02, k03, k04, k09, k12 |
| F11 Cross-section contradiction | 5 | 5 | k05, k06, k08, k11, k14 |
| F12 Source attribution | 5 | 5 | k01, k02, k03, k05, k07 |

| Case | Variants | Hand good | Bad | Uncertain | Omissions |
|---|---:|---:|---:|---:|---:|
| k01-idea-pantry | 10 | 6 | 6 | 1 | 1 |
| k02-startup-invoicing | 9 | 6 | 6 | 0 | 1 |
| k03-growing-scheduling | 10 | 3 | 8 | 0 | 1 |
| k04-large-photos | 11 | 6 | 5 | 3 | 1 |
| k05-small-therapy | 10 | 6 | 5 | 2 | 1 |
| k06-large-simple-transit | 7 | 6 | 3 | 1 | 1 |
| k07-conflict-marketplace | 6 | 3 | 2 | 2 | 1 |
| k08-missing-volunteers | 7 | 3 | 5 | 0 | 1 |
| k09-projected-fitness | 5 | 3 | 4 | 0 | 0 |
| k10-misleading-logistics | 2 | 3 | 0 | 1 | 0 |
| k11-privacy-reading | 6 | 3 | 2 | 3 | 0 |
| k12-internal-expenses | 6 | 3 | 3 | 2 | 0 |
| k13-performance-docks | 7 | 6 | 5 | 0 | 0 |
| k14-large-org-roomkeys | 7 | 3 | 6 | 0 | 0 |

## The five historical #133 pairs

Ten `p0*` profiles are copied byte-exact from the private qualification-v2 pair files;
raw-byte hashes and intended fault paths are independently pinned in the lint test.
P01 tests comparator reversal, p02 unit change, p03 loss polarity, p04 an invented security
control, and p05 an irrelevant unknown question. The p04 clean file has no appended
security claim, so no label is invented for the absent path.

**Historical p05 caveat:** both its clean and bad files predate #135's correction to k07
`/unknowns/6`. They mark unresolved personal-data retention immaterial. Both imports
therefore have an additional hand-labelled contradicted/F09 claim at that path. The clean
p05 file is a control at its intended `/unknowns/4` path, **not** an all-good whole-profile
control. Preserve the original bytes; do not silently bless, repair or use that historical
flaw to reject the intended-path control. This finding does not change the qualification
bars or the fixed design; the accountable lead must reconcile future whole-profile use.

## Deterministic check

From the repo root:

```sh
uv run --extra dev pytest tests/test_architecture/test_context_profile_meaning_cases.py -q
python3 tests/test_architecture/test_context_profile_meaning_cases.py
```

The first is also collected by the normal `wt land` gate. It checks complete unique path
labels, vocabulary/families, canonical bindings, <=3 claim-root edits, omission IDs,
byte-exact spans, frozen checker v2 on every profile, independent raw-byte #133 pins,
all size/spread minimums, README counts, and deliberate negative lint examples.
The second prints the computed counts without a model or service. Counts and reference
spans are mechanical evidence only: an independent review of at least 30 hand labels
is still required; >10% disagreement falsifies H-CTX-6b. No semantic checker is qualified
by these fixtures or this lint.

## Exact computed counts

The lint compares this block to its own calculation; tables above exclude imports unless
explicitly marked imported.

<!-- computed-counts:start -->
```json
{
  "authored_variants": 103,
  "bad_claims": 60,
  "by_case": {
    "k01-idea-pantry": {
      "bad": 6,
      "hand_supported": 6,
      "omissions": 1,
      "uncertain": 1,
      "variants": 10
    },
    "k02-startup-invoicing": {
      "bad": 6,
      "hand_supported": 6,
      "omissions": 1,
      "uncertain": 0,
      "variants": 9
    },
    "k03-growing-scheduling": {
      "bad": 8,
      "hand_supported": 3,
      "omissions": 1,
      "uncertain": 0,
      "variants": 10
    },
    "k04-large-photos": {
      "bad": 5,
      "hand_supported": 6,
      "omissions": 1,
      "uncertain": 3,
      "variants": 11
    },
    "k05-small-therapy": {
      "bad": 5,
      "hand_supported": 6,
      "omissions": 1,
      "uncertain": 2,
      "variants": 10
    },
    "k06-large-simple-transit": {
      "bad": 3,
      "hand_supported": 6,
      "omissions": 1,
      "uncertain": 1,
      "variants": 7
    },
    "k07-conflict-marketplace": {
      "bad": 2,
      "hand_supported": 3,
      "omissions": 1,
      "uncertain": 2,
      "variants": 6
    },
    "k08-missing-volunteers": {
      "bad": 5,
      "hand_supported": 3,
      "omissions": 1,
      "uncertain": 0,
      "variants": 7
    },
    "k09-projected-fitness": {
      "bad": 4,
      "hand_supported": 3,
      "omissions": 0,
      "uncertain": 0,
      "variants": 5
    },
    "k10-misleading-logistics": {
      "bad": 0,
      "hand_supported": 3,
      "omissions": 0,
      "uncertain": 1,
      "variants": 2
    },
    "k11-privacy-reading": {
      "bad": 2,
      "hand_supported": 3,
      "omissions": 0,
      "uncertain": 3,
      "variants": 6
    },
    "k12-internal-expenses": {
      "bad": 3,
      "hand_supported": 3,
      "omissions": 0,
      "uncertain": 2,
      "variants": 6
    },
    "k13-performance-docks": {
      "bad": 5,
      "hand_supported": 6,
      "omissions": 0,
      "uncertain": 0,
      "variants": 7
    },
    "k14-large-org-roomkeys": {
      "bad": 6,
      "hand_supported": 3,
      "omissions": 0,
      "uncertain": 0,
      "variants": 7
    }
  },
  "cases": [
    "k01-idea-pantry",
    "k02-startup-invoicing",
    "k03-growing-scheduling",
    "k04-large-photos",
    "k05-small-therapy",
    "k06-large-simple-transit",
    "k07-conflict-marketplace",
    "k08-missing-volunteers",
    "k09-projected-fitness",
    "k10-misleading-logistics",
    "k11-privacy-reading",
    "k12-internal-expenses",
    "k13-performance-docks",
    "k14-large-org-roomkeys"
  ],
  "claims": {
    "contradicted": 45,
    "supported": 4625,
    "uncertain": 15,
    "unsupported": 15
  },
  "families": {
    "F01": {
      "cases": [
        "k01-idea-pantry",
        "k03-growing-scheduling",
        "k05-small-therapy",
        "k13-performance-docks",
        "k14-large-org-roomkeys"
      ],
      "claims": 5
    },
    "F02": {
      "cases": [
        "k02-startup-invoicing",
        "k03-growing-scheduling",
        "k04-large-photos",
        "k09-projected-fitness",
        "k13-performance-docks"
      ],
      "claims": 5
    },
    "F03": {
      "cases": [
        "k02-startup-invoicing",
        "k03-growing-scheduling",
        "k04-large-photos",
        "k13-performance-docks",
        "k14-large-org-roomkeys"
      ],
      "claims": 5
    },
    "F04": {
      "cases": [
        "k02-startup-invoicing",
        "k05-small-therapy",
        "k06-large-simple-transit",
        "k08-missing-volunteers",
        "k09-projected-fitness"
      ],
      "claims": 5
    },
    "F05": {
      "cases": [
        "k01-idea-pantry",
        "k03-growing-scheduling",
        "k04-large-photos",
        "k08-missing-volunteers",
        "k13-performance-docks"
      ],
      "claims": 5
    },
    "F06": {
      "cases": [
        "k01-idea-pantry",
        "k04-large-photos",
        "k05-small-therapy",
        "k11-privacy-reading",
        "k12-internal-expenses"
      ],
      "claims": 5
    },
    "F07": {
      "cases": [
        "k03-growing-scheduling",
        "k06-large-simple-transit",
        "k08-missing-volunteers",
        "k12-internal-expenses",
        "k14-large-org-roomkeys"
      ],
      "claims": 5
    },
    "F08": {
      "cases": [
        "k01-idea-pantry",
        "k02-startup-invoicing",
        "k03-growing-scheduling",
        "k09-projected-fitness",
        "k14-large-org-roomkeys"
      ],
      "claims": 5
    },
    "F09": {
      "cases": [
        "k01-idea-pantry",
        "k07-conflict-marketplace",
        "k08-missing-volunteers",
        "k13-performance-docks",
        "k14-large-org-roomkeys"
      ],
      "claims": 5
    },
    "F10": {
      "cases": [
        "k02-startup-invoicing",
        "k03-growing-scheduling",
        "k04-large-photos",
        "k09-projected-fitness",
        "k12-internal-expenses"
      ],
      "claims": 5
    },
    "F11": {
      "cases": [
        "k05-small-therapy",
        "k06-large-simple-transit",
        "k08-missing-volunteers",
        "k11-privacy-reading",
        "k14-large-org-roomkeys"
      ],
      "claims": 5
    },
    "F12": {
      "cases": [
        "k01-idea-pantry",
        "k02-startup-invoicing",
        "k03-growing-scheduling",
        "k05-small-therapy",
        "k07-conflict-marketplace"
      ],
      "claims": 5
    }
  },
  "hand_labels": {
    "contradicted": 45,
    "supported": 60,
    "uncertain": 15,
    "unsupported": 15
  },
  "imported_claims": {
    "contradicted": 5,
    "supported": 426,
    "unsupported": 2
  },
  "imported_variants": 10,
  "omission_variants": 8,
  "omissions": 8,
  "traps": {
    "comparator_paraphrase": 6,
    "reordering": 44,
    "two_quote_summary": 5,
    "unit_conversion": 5
  }
}
```
<!-- computed-counts:end -->

## Per-variant purpose

| Variant | Case | Edits / omissions | What it tests |
|---|---|---|---|
| f01-k01 | k01-idea-pantry | `/budget/run_monthly` | Over reverses the founders' stated under-$150 wish; it is still a wish, not a cap. |
| f01-k03 | k03-growing-scheduling | `/reliability/availability` | A contractual uptime promise is a floor; below that percentage reverses the promise. |
| f01-k05 | k05-small-therapy | `/privacy/retention/0` | At most replaces the explicit at-least retention floor with an upper bound. |
| f01-k13 | k13-performance-docks | `/constraints/0` | At least is incompatible with the strictly-below latency ceiling. |
| f01-k14 | k14-large-org-roomkeys | `/workload/peaks/0` | The concurrent-user figure is an upper bound, not a lower bound. |
| f02-k02 | k02-startup-invoicing | `/workload/observed/2` | The source says per month, not per year; the count itself remains 9,000. |
| f02-k03 | k03-growing-scheduling | `/workload/observed/3` | Database size is 900 GB, not 900 MB. |
| f02-k04 | k04-large-photos | `/workload/observed/4` | The media-view total is daily, not per minute. |
| f02-k09 | k09-projected-fitness | `/workload/observed/1` | The observed workout count is per month, not per year. |
| f02-k13 | k13-performance-docks | `/performance/targets/0` | 250 seconds is a thousand-fold relaxation of the stated 250-millisecond ceiling. |
| f03-k02 | k02-startup-invoicing | `/workload/observed/1` | 140 counts paying customers; free-tier users are about 600. |
| f03-k03 | k03-growing-scheduling | `/workload/observed/1` | 380 counts business customers, not the approximately 45,000 monthly staff users. |
| f03-k04 | k04-large-photos | `/workload/observed/0` | 9 million is the daily count; monthly active users are 31 million. |
| f03-k13 | k13-performance-docks | `/workload/observed/0` | 400 is the shift-change peak, not the normal 120-event rate. |
| f03-k14 | k14-large-org-roomkeys | `/workload/observed/1` | Four counts simultaneous users, not the roughly 90 daily transactions. |
| f04-k02 | k02-startup-invoicing | `/security/requirements/0` | The source expressly forbids seeing or storing card numbers and keeps them at Stripe. |
| f04-k05 | k05-small-therapy | `/security/requirements/1` | The brief permits amendments only and explicitly forbids editing a signed note. |
| f04-k06 | k06-large-simple-transit | `/privacy/data_categories/1` | The source explicitly promises that location never leaves the phone. |
| f04-k08 | k08-missing-volunteers | `/privacy/retention/0` | The address must disappear from that view once delivery is done. |
| f04-k09 | k09-projected-fitness | `/privacy/sharing/0` | The agreed HealthKit rules forbid that use. |
| f05-k01 | k01-idea-pantry | `/product` | A possible later shared list is made a present first-version feature. |
| f05-k03 | k03-growing-scheduling | `/security/compliance/0` | The requested report must precede renewal; delivery afterwards loses the required timing. |
| f05-k04 | k04-large-photos | `/privacy/jurisdictions_or_rules/2` | An agreement to implement by the end of next year is not evidence of implementation already complete. |
| f05-k08 | k08-missing-volunteers | `/goals/0` | The qualified aim if-we-can-manage-it is changed into an unconditional guarantee. |
| f05-k13 | k13-performance-docks | `/workload/projected/0` | Contracted starts next quarter are shifted into completed starts last quarter. |
| f06-k01 | k01-idea-pantry | `/security/requirements/0` | Email sign-in does not state any biometric requirement. |
| f06-k04 | k04-large-photos | `/security/requirements/0` | A bounty and penetration test do not impose a hardware-key upload requirement. |
| f06-k05 | k05-small-therapy | `/security/requirements/2` | Durability does not mandate this particular backup appliance. |
| f06-k11 | k11-privacy-reading | `/security/requirements/0` | Data residency says nothing about teacher fingerprint authentication. |
| f06-k12 | k12-internal-expenses | `/security/requirements/2` | The approval flow does not require GPS capture. |
| f07-k03 | k03-growing-scheduling | `/privacy/jurisdictions_or_rules/0` | The agreement covers the named European customers, not every customer worldwide. |
| f07-k06 | k06-large-simple-transit | `/constraints/0` | Only Riverton has this term; Calder and Moorfield expressly do not. |
| f07-k08 | k08-missing-volunteers | `/privacy/sharing/0` | The permission is scoped to the accepting volunteer and that delivery, not all volunteers. |
| f07-k12 | k12-internal-expenses | `/privacy/sharing/0` | A claim is limited to its employee, their manager and finance, not the whole workforce. |
| f07-k14 | k14-large-org-roomkeys | `/security/requirements/2` | Mandatory access is limited to the facilities group, despite the larger organisation. |
| f08-k01 | k01-idea-pantry | `/maturity/stage` | Nothing is built and demand is unproven; the product is explicitly an idea. |
| f08-k02 | k02-startup-invoicing | `/maturity/stage` | A launched, paying service is not a product still at idea stage. |
| f08-k03 | k03-growing-scheduling | `/maturity/stage` | Four years of paying use and sustained rapid revenue growth contradict idea-stage classification. |
| f08-k09 | k09-projected-fitness | `/workload/observed/2` | The investor-deck target is placed in observed workload even though the brief says it is not today's number. |
| f08-k14 | k14-large-org-roomkeys | `/maturity/stage` | Proven demand is flat for three years with no expansion planned, not growing. |
| f09-k01 | k01-idea-pantry | `/unknowns/0` | Marking this unknown immaterial is wrong: Whether health-related allergy data is stored changes consent, sensitivity and legal duties. |
| f09-k07 | k07-conflict-marketplace | `/unknowns/4` | Marking this unknown immaterial is wrong: Recovery is unresolved and materially changes failover and on-call choices for the ranked uptime objective. |
| f09-k08 | k08-missing-volunteers | `/unknowns/5` | Marking this unknown immaterial is wrong: No build allowance is set; whether any funding exists changes the feasible choices. |
| f09-k13 | k13-performance-docks | `/unknowns/0` | Marking this unknown immaterial is wrong: Retry ordering is explicitly unresolved and changes buffering and deduplication. |
| f09-k14 | k14-large-org-roomkeys | `/unknowns/0` | Marking this unknown immaterial is wrong: A real delay complaint blocks lab access; measuring and agreeing the target changes response-path options. |
| f10-k02 | k02-startup-invoicing | `/unknowns/1` | A font question cannot replace the unresolved recovery tolerance at billing time. |
| f10-k03 | k03-growing-scheduling | `/unknowns/0` | A font question does not surface the unresolved EU-hosting demand. |
| f10-k04 | k04-large-photos | `/unknowns/1` | A font question does not ask about cold-storage eligibility or media reuse. |
| f10-k09 | k09-projected-fitness | `/unknowns/4` | A font question does not surface unresolved employment and data-access boundaries. |
| f10-k12 | k12-internal-expenses | `/unknowns/8` | A font question is irrelevant to the SAP integration interface and delivery risk. |
| f11-k05 | k05-small-therapy | `/assumptions/1` | The assumption contradicts unchanged /security/requirements/1 as well as the explicit source; an assumption label is not permission to override a rule. |
| f11-k06 | k06-large-simple-transit | `/assumptions/1` | The assumption contradicts unchanged /privacy/data_categories/1 as well as the explicit source; an assumption label is not permission to override a rule. |
| f11-k08 | k08-missing-volunteers | `/assumptions/1` | The assumption contradicts unchanged /security/requirements/0 as well as the explicit source; an assumption label is not permission to override a rule. |
| f11-k11 | k11-privacy-reading | `/assumptions/1` | The assumption contradicts unchanged /privacy/jurisdictions_or_rules/1 as well as the explicit source; an assumption label is not permission to override a rule. |
| f11-k14 | k14-large-org-roomkeys | `/assumptions/0` | The assumption contradicts unchanged /reliability/data_loss_tolerance as well as the explicit source; an assumption label is not permission to override a rule. |
| f12-k01 | k01-idea-pantry | `/team/skills/0` | The product-designer description is Maya's, not Luis's; no design skill is stated for Luis. |
| f12-k02 | k02-startup-invoicing | `/team/skills/0` | The people are swapped; the quote states React for Sam and Rails/Postgres for Dana, not these swapped attributions. |
| f12-k03 | k03-growing-scheduling | `/security/compliance/0` | The request is from two customers, not from the auditors. |
| f12-k05 | k05-small-therapy | `/privacy/sharing/0` | The source assigns that agreement duty to vendors storing or processing notes, not every therapist. |
| f12-k07 | k07-conflict-marketplace | `/goals/0` | The launch-first ranking is the CEO's; the CTO explicitly wants reliability first. |
| good-k01-combined | k01-idea-pantry | `/budget/run_monthly`, `/privacy/retention/0`, `/team/operating_capacity/0` | Both source quotes are retained without inventing overnight coverage.; Less than preserves under, and wish/until demand preserve the non-binding condition.; Reorders the promised deletion trigger without inventing a retention duration. |
| good-k01-wording | k01-idea-pantry | `/goals/0`, `/product`, `/team/skills/0` | Reordered product description retains the functions and audience stated in the quote.; Paraphrase retains the stated priority and its meaning.; Rewording preserves the exact scope, number and qualification of the source. |
| good-k02-combined | k02-startup-invoicing | `/budget/build`, `/privacy/data_categories/0`, `/team/size` | The two quotes jointly name the same people, capacities and correctly attributed skills.; Must not exceed is the same inclusive ceiling as up to.; Only reorders the explicitly listed data categories. |
| good-k02-wording | k02-startup-invoicing | `/budget/build`, `/goals/0`, `/product` | Reordered product description retains the functions and audience stated in the quote.; Paraphrase retains the stated priority and its meaning.; Rewording preserves the exact scope, number and qualification of the source. |
| good-k03-wording | k03-growing-scheduling | `/goals/0`, `/product`, `/team/size` | Reordered product description retains the functions and audience stated in the quote.; Paraphrase retains the stated priority and its meaning.; Rewording preserves the exact scope, number and qualification of the source. |
| good-k04-combined | k04-large-photos | `/privacy/retention/0`, `/reliability/availability`, `/reliability/recovery_time` | Converts only the viewing duration, retaining the regional-outage condition and separate upload bound.; Both availability percentages keep their operation, and durability still applies to confirmed photos.; No later than preserves the inclusive within-30-days deadline and its trigger. |
| good-k04-wording | k04-large-photos | `/goals/0`, `/product`, `/team/size` | Reordered product description retains the functions and audience stated in the quote.; Paraphrase retains the stated priority and its meaning.; Rewording preserves the exact scope, number and qualification of the source. |
| good-k05-combined | k05-small-therapy | `/goals/1`, `/privacy/retention/0`, `/team/skills/0` | A calendar year has twelve calendar months; the same signed-note minimum is expressed in months.; No person or audit experience is invented in combining these two statements.; Paraphrases the second-ranked low-burn objective. |
| good-k05-wording | k05-small-therapy | `/goals/1`, `/privacy/retention/0`, `/product` | Reordered product description retains the functions and audience stated in the quote.; Paraphrase retains the stated priority and its meaning.; Rewording preserves the exact scope, number and qualification of the source. |
| good-k06-combined | k06-large-simple-transit | `/constraints/0`, `/privacy/data_categories/1`, `/team/operating_capacity/0` | Two minutes equals 120 seconds; only Riverton is covered and publication remains the trigger.; The two statements keep both data-minimization limits intact.; The same approximate individual weekly capacity is reordered. |
| good-k06-wording | k06-large-simple-transit | `/goals/2`, `/product`, `/team/skills/0` | Reordered product description retains the functions and audience stated in the quote.; Paraphrase retains the stated priority and its meaning.; Rewording preserves the exact scope, number and qualification of the source. |
| good-k07-wording | k07-conflict-marketplace | `/goals/0`, `/product`, `/team/size` | Reordered product description retains the functions and audience stated in the quote.; Paraphrase retains the stated priority and its meaning.; Rewording preserves the exact scope, number and qualification of the source. |
| good-k08-wording | k08-missing-volunteers | `/goals/2`, `/product`, `/team/skills/0` | Reordered product description retains the functions and audience stated in the quote.; Paraphrase retains the stated priority and its meaning.; Rewording preserves the exact scope, number and qualification of the source. |
| good-k09-wording | k09-projected-fitness | `/goals/0`, `/product`, `/team/size` | Reordered product description retains the functions and audience stated in the quote.; Paraphrase retains the stated priority and its meaning.; Rewording preserves the exact scope, number and qualification of the source. |
| good-k10-wording | k10-misleading-logistics | `/budget/build`, `/goals/1`, `/product` | Reordered product description retains the functions and audience stated in the quote.; Paraphrase retains the stated priority and its meaning.; Rewording preserves the exact scope, number and qualification of the source. |
| good-k11-wording | k11-privacy-reading | `/budget/build`, `/goals/2`, `/product` | Reordered product description retains the functions and audience stated in the quote.; Paraphrase retains the stated priority and its meaning.; Rewording preserves the exact scope, number and qualification of the source. |
| good-k12-wording | k12-internal-expenses | `/budget/build`, `/goals/0`, `/product` | Reordered product description retains the functions and audience stated in the quote.; Paraphrase retains the stated priority and its meaning.; Rewording preserves the exact scope, number and qualification of the source. |
| good-k13-conversions | k13-performance-docks | `/constraints/1`, `/performance/targets/0`, `/reliability/recovery_time` | Only the unit/value representation changes; the strict p95 ceiling remains the same.; Must not exceed preserves at most and receipt remains the starting event.; A half-hour is exactly thirty minutes, with the same inclusive recovery bound. |
| good-k13-wording | k13-performance-docks | `/goals/1`, `/product`, `/team/skills/0` | Reordered product description retains the functions and audience stated in the quote.; Paraphrase retains the stated priority and its meaning.; Rewording preserves the exact scope, number and qualification of the source. |
| good-k14-wording | k14-large-org-roomkeys | `/goals/0`, `/product`, `/workload/peaks/0` | Reordered product description retains the functions and audience stated in the quote.; Paraphrase retains the stated priority and its meaning.; Rewording preserves the exact scope, number and qualification of the source. |
| omission-k01-g4 | k01-idea-pantry | `/goals/3` | Omit key goal G4 without structural damage. |
| omission-k02-g3 | k02-startup-invoicing | `/goals/2` | Omit key goal G3 without structural damage. |
| omission-k03-g3 | k03-growing-scheduling | `/goals/2` | Omit key goal G3 without structural damage. |
| omission-k04-g4 | k04-large-photos | `/goals/3` | Omit key goal G4 without structural damage. |
| omission-k05-g3 | k05-small-therapy | `/goals/2` | Omit key goal G3 without structural damage. |
| omission-k06-g3 | k06-large-simple-transit | `/goals/2` | Omit key goal G3 without structural damage. |
| omission-k07-g3 | k07-conflict-marketplace | `/goals/2` | Omit key goal G3 without structural damage. |
| omission-k08-g3 | k08-missing-volunteers | `/goals/2` | Omit key goal G3 without structural damage. |
| p01-comparator-bad | k13-performance-docks | `/constraints/0` | The displayed C1 requires API p95 above 250 milliseconds while falsely citing the below-250 requirement. |
| p01-comparator-clean | k13-performance-docks | reference control | The signed warehouse requirement is p95 response strictly below 250 milliseconds; above reverses the constraint. |
| p02-unit-bad | k13-performance-docks | `/performance/targets/0` | The target becomes below 250 seconds: a thousand-fold unit error despite the correct milliseconds quote. |
| p02-unit-clean | k13-performance-docks | reference control | The latency target is below 250 milliseconds, not 250 seconds; value 250 and the below comparator stay fixed. |
| p03-loss-bad | k13-performance-docks | `/reliability/data_loss_tolerance` | The data-loss field now explicitly permits losing acknowledged events, contradicting both its quotation and unchanged C5. |
| p03-loss-clean | k13-performance-docks | reference control | No acknowledged event may be lost. C5 and the original source quotation remain unchanged. |
| p04-security-bad | k13-performance-docks | `/security/requirements/1` | An additional mandatory biometric-authentication assertion is passed off as stated fact under already-populated security.requirements, citing the genuine scanner-certificate quote. |
| p04-security-clean | k13-performance-docks | reference control | The only stated security control here preserves existing scanner certificates through migration. No biometric-authentication requirement is supplied. |
| p05-unknown-bad | k07-conflict-marketplace | `/unknowns/4`, `/unknowns/6` | U5 keeps field reliability.recovery_time and material true but asks only about typography; it no longer surfaces the material recovery question. Historical retention materiality flaw is labelled separately in both pinned files. |
| p05-unknown-clean | k07-conflict-marketplace | `/unknowns/6` | The brief gives no recovery-time target; U5 must ask how quickly service must return, because plausible answers change failover and on-call decisions. Historical retention materiality flaw is labelled separately in both pinned files. |
| uncertain-k01-allergies | k01-idea-pantry | `/privacy/data_categories/2` | Storing allergies is an expressly undecided option: neither storing nor declining it is settled. |
| uncertain-k04-backup-residency | k04-large-photos | `/privacy/jurisdictions_or_rules/4` | The brief explicitly identifies whether the rule extends to backups as unresolved, not as a stated permission or prohibition. |
| uncertain-k04-established | k04-large-photos | `/maturity/stage` | Age and scale are stated but the demand trend needed to distinguish established from growing is absent. |
| uncertain-k04-growing | k04-large-photos | `/maturity/stage` | Large use alone does not establish whether current demand is rising; the growth trend is unstated. |
| uncertain-k05-audio | k05-small-therapy | `/privacy/data_categories/2` | The source expressly leaves the recording feature undecided, so this future-data claim cannot be settled. |
| uncertain-k05-california | k05-small-therapy | `/privacy/jurisdictions_or_rules/2` | The source explicitly says the existence of extra state rules is not known. |
| uncertain-k06-feed-access | k06-large-simple-transit | `/workload/projected/1` | The source expressly says the feed has not been seen and polling permission is unknown. |
| uncertain-k07-ceo-demand | k07-conflict-marketplace | `/workload/projected/0` | The same sentence explicitly says the forecast is unresolved and gives conflicting estimates; the unqualified expected value is not settled. |
| uncertain-k07-cto-demand | k07-conflict-marketplace | `/workload/projected/0` | The CTO expects less while the CEO plans 1,000; neither is established as the resolved demand forecast. |
| uncertain-k10-retention-law | k10-misleading-logistics | `/privacy/retention/1` | The source explicitly leaves legal defensibility of this particular retention period unchecked. |
| uncertain-k11-established | k11-privacy-reading | `/maturity/stage` | Four years of school use does not establish whether demand is steady or rising fast. |
| uncertain-k11-growing | k11-privacy-reading | `/maturity/stage` | Known usage and age leave the demand trend genuinely open. |
| uncertain-k11-training-consent | k11-privacy-reading | `/privacy/retention/2` | Existing consent covering this use is the explicit open question, not an unrelated invented consent provision. |
| uncertain-k12-established | k12-internal-expenses | `/maturity/stage` | It is unresolved whether this replacement inherits the long-running expense service's lifecycle. |
| uncertain-k12-startup | k12-internal-expenses | `/maturity/stage` | The brief leaves the lifecycle boundary of a new implementation of an existing internal service ambiguous. |
