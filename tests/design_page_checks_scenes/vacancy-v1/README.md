# H12 vacancy recordings (queue #114)

Recorded from `configs/design/testpages/vacancy-v1`, keyed and sealed before the vacancy implementation in
`~/design-lab/seals/vacancy-v1.json`. `expected.json` is the key; these are browser observations, not answers
chosen after implementation.

Host headless Chromium, isolated `@playwright/mcp` on `127.0.0.1:8954`, desktop 1280×800. No model or Temper run.
The candidate vacancy pass was enabled explicitly. The box browser (8931) was not used.

Reproduce with `~/design-lab/homepage-workflow/wave2/w10b/proofs.py fixtures` (fresh output directories).
The three captures each match all 21 keyed pages and produce byte-identical `columns.json`:
`acc0616ddd714170a7a879bb6ab5898b3d8390703b2c9e96b35de18c43a65d4f`.

Each `*.raw.json` is `{ "desktop": <facts.page_checks> }` from the first capture. All 21 match that capture's
raw measurements exactly. Recording format: `~/design-lab/tools/page_checks_record_scenes.py`.

The tests compare run identity, answer and reason to the sealed key, check structural evidence, and verify
that the ordinary facts.md wording ignores the additional vacancy object. No browser is required for them.
