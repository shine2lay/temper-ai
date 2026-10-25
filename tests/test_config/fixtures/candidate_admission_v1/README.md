# Independent synthetic contract fixtures

Handwritten literals, no compiler/loader/codec-derived expected semantic values.
`descriptor.json` and `raw-*.json` are exact CAJ-1 bytes without final newline.
`canonical.json` fixes exact encoding answers, including binary64 decimal and
Unicode cases. `refusals.json` fixes rejection codes for literal bad bytes.
`pins.json` fixes domain hashes calculated independently using hashlib over the
literal files and stdlib JSON for their integer-only projections, not production
normalization. Source IDs, roots, worker, mode and permission labels are synthetic
and are NOT attestations. These intentionally tiny field inventories are not
full real engine projections; the Architecture independent 14x3 oracle remains
separate and must use the actual source field inventory.

For avoiding redundant huge escaped literals, `record-layout.json` is an input
assembly layout, not wire: replace $descriptor-file with descriptor.json text,
$pinned-descriptor/$pinned-graph/$pinned-immutable with pins.json constants, and
raw_records with the three raw files in call/prepare/workflow order. Nothing
else is supplied or normalized by production code. The root variant replaces
the one null policy with the independently handwritten root-policy.json and
uses root-descriptor/root-immutable pins. readiness.json is an independently
handwritten successful receipt, not actual filesystem measurements. Its running
dispatch is nonce ...003, previous nonce ...002, attempt 1, synthetic-worker.

Tests construct mutant inputs with stdlib serialization. Semantic guard controls
may independently repin that mutant to get past authority and reach a particular
guard; those are explicitly not the external-authority substitution control,
which keeps the original pin unchanged. No expected acceptance/refusal code or
semantic answer comes from the implementation under test. No real private or
model-bound data is read, emitted or mocked as a request body.
