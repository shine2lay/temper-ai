# H12 live-output byte regression (queue #114)

Known local pages, captured with an isolated host headless browser at 1280×800 (never the box browser).
These are browser facts and script outputs, not model requests or answers. No model or Temper run.

- `before`: capture/page-check/report code extracted from base `origin/master` `19e24046bc415496b9639f008b0de34b12e4187d`.
- `after-off`: candidate H12 code with the vacancy environment flag unset (the live/default path).
- `after-on`: candidate H12 code with the vacancy pass explicitly enabled (the _next path).

Sources: W10a's sealed `quarry-b4`, `new-craft02` and `fernlight-price` case folders. Neither sources nor seals were edited.
Both source-code versions used the same browser and page assets. Reproduction driver and hashes:
`~/design-lab/homepage-workflow/wave2/w10b/proofs.py live`, `~/design-lab/homepage-workflow/wave2/w10b/live/proof.json`.

`before` and `after-off` are byte-identical for every saved file: capture.json, facts.md, raw facts,
measured.json, candidates.json and anchors.json (including all raw dark-theme views and craft-metrics.json).
The local .gitattributes preserves the live writer's literal trailing space on an empty tab-order line;
stripping it would invalidate the byte regression. Even with the pass on, facts.md is byte-identical and
page_checks differs only by the additional `columns[].vacancy` object, not the other checks or run geometry.

The unit regression compares those bytes and regenerates facts.md, measured.json, candidates.json and
anchors.json with current code on `before` facts, to catch future changes as well as document this proof.
Screenshots, fonts and private absolute source folders are not needed by the regression.
