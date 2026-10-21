# D3/D4 invented fixture corpus

`synthetic.py` builds every fixture in a private pytest temporary directory:

- A separate 37-row toy key, SHA256-bound freeze, label-free Unicode/quote packet,
  raw decisions and the D1/D2 task's `context-t1-validation/v1` receipt shape.
- Six fresh synthetic attempt records, comparisons, per-case Architecture
  acceptance receipts, and a complete list-price ledger. No actual route is
  selected or contacted. Fixture timestamps, UUIDs and metadata are invented.
- Negative tests mutate one property and retain the fixed denominators. A known
  subtotal never substitutes for an unknown total. Nothing pools across runs.

The class/family inventory literals are independently copied from the frozen
aggregate-only T1 acceptance plan, not from production scoring constants.
Invented IDs `invented-001` through `invented-037`, paths `/toy/1` through
`/toy/37`, blue toy lamp assertions and the brief are unrelated to C1 content.
Unsupported spans use literal `none` (ERRATUM-1); other fixture spans are literal
substrings of the invented brief. Alternative exact spans/rationales still
match in D3 and repeat in D4, but require independent source review in real use.

These are deterministic stage checks, not a model evaluation, an isolated judge
rehearsal, real-key evidence, Stage 1 qualification or admission. The helpers do
not inspect C1, heldout material, any other session or model request/response
boundaries. Generated fixtures are not retained as experiment results.

Contracts live in `configs/architecture/stages/context_profile/t1/`.
The future J attempt/ledger contract and D4 failure precedence are documented in
`configs/architecture/bin/context_t1_aggregate.py`'s module docstring and
`attempt.v1.schema.json`; D3's private equality contract is in its docstring
and `comparison.v1.schema.json`. D4 has no key access and takes independent
binding/freeze/packet pins from its caller. Neither script dispatches work.

Standalone tests (after implementation):

```
uv run --quiet pytest tests/test_architecture/test_context_t1_compare.py tests/test_architecture/test_context_t1_aggregate.py -q
```

Both CLIs return 0 only for PASS/T1_ACCEPTED, 1 for a valid non-pass result and
2 for refused evidence/files. They print only status, not fixture/key content.
Outputs use exclusive 0600 create; inputs must already be regular single-link
0600 files in 0700 directories. The descriptor-relative local envelope does
not establish OS isolation or effective judge blindness.
