# Context-profile meaning checker — deterministic layers 1 and 2

Architecture #139; hypothesis H-CTX-6a. This is a separate, deliberately incomplete checker, not a grader.
Binding design: `DESIGN-H-CTX-6.md`, SHA-256
`6264abc6178c83024c9757d07a3a189bb78e0568cdef25f269b1057d7ac5cba8`.
The existing scorer remains BLOCKED / NOT_MEASURED. Nothing consumes this output.

## Invocation and boundary

```
python configs/architecture/bin/context_profile_meaning.py --case CASE_DIR PROFILE.json
```

CASE_DIR contains brief.md and key.json. The existing read-only key loader lints them; the existing schema
validator checks the input shape. Only plain context_profile/v2 profiles are inputs (no plant wrappers).
Profile and key brief hashes must agree with the brief bytes. Duplicate JSON members and non-finite JSON
numbers are refused. A completed check always exits **1**, even with no contradictions. Cannot-run errors
(IO, Unicode, malformed JSON, broken key/schema or wrong brief binding) produce an error object and exit
**2**. Argument errors also exit 2. There is no exit-0 path, including --help. No model or service is used.

## Layer 1: exhaustive inventory, not proof of coverage of meaning

Paths are RFC 6901 JSON pointers. Enumerate every present semantic scalar leaf, including measure what,
value and unit; item kind/text; name/role; maturity/state; sensitivity level; goal criterion/rank/note;
unknown question/why_it_matters/material/field/each decisions_affected; assumption text/why; and source.why.
Empty lists are explicit placeholder claims; nonempty scalar lists (decisions_affected) have a collection
claim as well as each leaf. Scalar "unknown" is also a claim. Do not enumerate envelope
contract/brief_sha256, structural id, or provenance source.kind/source.quote as separate assertions. Those
are retained with the enclosing record. Validation prevents unknown schema locations being silently lost.

Also enumerate assertion-bearing objects as **groups**: every sourced item, each unknown and assumption,
and maturity (whose source is its evidence). Group paths allow an outcome at an entire-item fault path.
Every group AND leaf has an outcome. Groups aggregate their own direct assertion leaves; they do not
propagate a fault to innocent sibling leaves. A measure is compared as what + value + unit, but number
findings belong to value, unit/scale findings with unchanged literal number to unit, and comparator findings
to what. A container containing a fault is not an independent clean assertion. Empty placeholders and
unquoted explanatory leaves defer. Deferral summaries count all inventory entries and identify that unit;
the numeric/limit trigger counts groups once (and never their duplicate leaves).

Enumerate key facts, constraints, goals, unknowns, plus fields_unknown without not_material_reason. Skip
an entry only when explicitly material=false or carrying a not_material_reason. Keep its key pointer, id,
anchors/terms/field, and full obligation data. Facts' primary and optional alt sections, constraints/goals'
own sections and unknowns' declared fields constrain **candidate** mappings. A quote matches an anchor
when the existing checker's whitespace/punctuation-normalized anchor is a substring. Unknown candidate
mappings require material=true, equal field when the key supplies it, AND every supplied terms group
(one normalized substring from each group) in the question/explanation/decisions text. fields_unknown
requires an equal field on a material unknown. No fallback from an explicitly different field.

Mappings are group-level candidates, not entailment: a quoted but reversed requirement can still map.
All child leaves inherit that candidate mapping for traceability. Each obligation lists candidate group
paths. Report missing obligations (no candidate), unmapped claim paths (no candidate), duplicate mappings
(multiple groups for one obligation), and duplicate claim groups (same direct assertion and provenance).
Legitimate repeated evidence is still reported as a duplicate candidate, not rejected. Keep many-to-many
mappings; do not pick one and silently discard the others.

## Layer 2: conservative extraction rules

Compare only with a single nonempty cited quote found in the brief using the existing quote normalization.
Multiple evidence quotes, assumptions, absent/bad quotes, unknowns and empty placeholders defer. Normalize
semantic text with Unicode NFKC, case folding, straight punctuation and whitespace; keep operators.
Matching extraction **never** establishes entailment: the result remains needs_judgment.

| Rule | Unambiguous disagreement required for contradicted |
|---|---|
| number | Exactly one quantity on each side, same identifiable unit/dimension, unequal exact canonical amounts. Bare counts need the same immediately following count noun. |
| unit_scale | Same as number, but literal amounts equal and unit/scale factors differ, or both explicit dimensions are incompatible. An unsupported or ambiguous unit never supplies this finding. |
| comparator | Same single canonical quantity and explicit comparators on BOTH sides disagree: <, <=, >, >=, =. Different endpoint strictness counts as a changed requirement. |
| range | Both sides explicitly say between A and B, with exact common units; unequal converted lower/upper bounds. No claim about inclusivity is inferred from between. |
| polarity | Exactly one explicit modal/polarity marker per side and the remaining subject/predicate text is identical: must versus must not/must never, may versus may not, allowed versus forbidden. No syntactic paraphrase or singular/plural inference. |
| time | Exactly one was/were/is/are/will/would marker per side, otherwise identical text; past/present/future/conditional categories differ. will be and would be are single markers. |
| condition | Identical main clause AND condition text with explicit if versus unless. Prefix condition with comma and suffix condition are normalized. when is inventoried but is not declared incompatible with if. |
| label | Quote explicitly labels the same attribute (maturity:, sensitivity:, system state:, criterion:, item kind:), and a schema label leaf names a different value. |
| section | Quote STARTS with observed:, projected:/forecast:, constraint: or goal:; the claim's section explicitly declares the incompatible counterpart (observed/projected or constraint/goal). |

Numeric tokenization excludes embedded identifiers (p95, SOC2). Decimal and comma-grouped numbers and
attached k/m/b or words thousand/million/billion use exact rational arithmetic; factors are 1,000,
1,000,000, 1,000,000,000. Percent/% is ratio /100, not percentage points. Word numbers are not inferred;
unsupported words, multiple quantities (except an explicit two-bound between range), approximate markers,
negated limits, disjunctions and mixed/ranged expressions defer. No selecting a convenient number from a
multi-number quote. A recognized numeric/limit candidate can therefore still defer.

Exact conversions only:
- ms/millisecond(s) = 1/1000 s; s/second(s) = 1 s; min/minute(s) = 60 s;
  h/hour(s) = 3600 s. Days used as durations are compared only to days, months only to months.
- B/byte(s); KB/MB/GB/TB are decimal (10^3/10^6/10^9/10^12 B).
  KiB/MiB/GiB/TiB are binary (2^10/2^20/2^30/2^40 B). kb denotes KB here, never bits.
  Bits, bare memory prefixes and unstated factors defer.
- Count noun per second/minute/hour/day divides by 1/60/3600/86400 respectively into a per-second rate.
  Count noun per month stays a per-calendar-month rate. Month versus fixed-duration rates is ambiguous,
  not contradicted; no invented 30-day month. /s, /min, /h, /day, /month are equivalent spellings.
- Unlisted count nouns compare only when identical (simple trailing s plural normalization); currency
  symbols $, £ and € are separate dimensions. No exchange rates. No inferred conversion of people,
  bookings or events to each other.

Comparator aliases: below/under/less than/< -> lt; at most/no more than/<= -> le;
above/over/more than/> -> gt; at least/no less than/>= -> ge; equal to/exactly/= -> eq.
Only the operator immediately preceding a numeric bound is used. Absent operators do not mean equality.
"within", "up to", "no faster than" and qualitative comparisons defer. Reordered nonnumeric wording
alone is never a contradiction. Extraction requiring linguistic judgment defers, even if a human sees a
clear problem (including #133 p03–p05). Findings carry rule, claim side, quote side and responsible path.

## Output: context_profile_meaning/v0-layers12

```
{
  "format": "context_profile_meaning/v0-layers12",
  "case_id": "...",
  "brief_sha256": "...",
  "inventory": {
    "claims": [{"path": "...", "kind": "group|leaf|collection|empty", "value": "...",
                "group": "...", "quotes": [], "obligations": []}],
    "obligations": [{"path": "...", "id": "...", "data": {}, "claim_groups": []}],
    "unmapped": [], "missing": [], "duplicate_mappings": [], "duplicate_claims": []
  },
  "claims": [{"path": "...", "outcome": "contradicted|needs_judgment",
              "findings": [{"rule": "...", "claim": {}, "quote": {}, "path": "..."}],
              "reason": "..."}],
  "summary": {"entries": 0, "contradicted": 0, "needs_judgment": 0,
              "numeric_limit_groups": 0, "numeric_limit_deferred": 0}
}
```

Actual values are typed JSON, not necessarily strings. Exactly one outcome per inventory path; no positive
outcome, score, acceptance boolean or successful exit. Summary counts are observations, not qualification.
The typed-claims reopen triggers remain the design's >5% good-dev false rejects or >60% numeric/limit
deferrals. Known references are not an independently judged dev set: report their false-reject proxy as a
proxy, not measured dev acceptance. The numeric/limit denominator includes recognizable digits or limit
markers in ANY group assertion, even when its quote or extraction is ambiguous. Empty denominators are
reported as null rates by analysis, never silently treated as zero.
