# H12b vacancy recordings (queue #118)

Recorded from `configs/design/testpages/vacancy-v2`, keyed and sealed before the H12b code in
`~/design-lab/seals/vacancy-v2.json` (2026-10-20 10:09:30 PDT). `expected.json` is the key; these are browser
observations, not answers chosen after implementation. Every page has a heading and an intro above its grid or row.

Host headless Chromium, isolated `@playwright/mcp` on a loopback port of its own, desktop 1280×800. No model or Temper
run. The candidate vacancy pass was enabled explicitly. The box browser (8931) was not used.

The pre-code commit held recordings made with the H12 code (b9c96c0e), with the six yes pages and new-craft02 as
strict xfails. The H12b code commit re-records them from the first of three fresh captures
(`~/design-lab/homepage-workflow/wave2/w10c/proofs.py fixtures --set vacancy-v2`). The three captures each match all
13 keyed pages and produce byte-identical `columns.json`:
`28cd451c569ec7b44cdcd9629da77c635f8f7977414fe26c63beef608367b7d6`. Only the six yes pages' recordings changed;
the seven no pages' recordings are byte-identical to the H12 ones.

`../vacancy-known/new-craft02.raw.json` is W10a's sealed new-craft02 case site (the one known case H12 answered
no/block), captured the same way with its primary action "Book a taster class"; re-recorded from
`w10c/cases/r1/new-craft02`. Only the classes run's `vacancy` object changed.

Each `*.raw.json` is `{ "desktop": <facts.page_checks> }`. Recording format:
`~/design-lab/tools/page_checks_record_scenes.py`.
