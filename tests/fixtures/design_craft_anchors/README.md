# design_craft_anchors fixtures

`craft-v1/page-NN/craft-metrics.json`: what the measure stage's own code,
`design_homepage_v2.craft_metrics` (CRAFT_CODE, widths 1440 and 390), gives each page of
`configs/design/testpages/craft-v1`, saved with `design_homepage_v2.save`, so each page folder
reads like a review folder. Measured on 2026-10-19 at master 18d61ffe in a headless Chromium
(Playwright headless shell 1208, through @playwright/mcp on the host), with each page's site built
as `design_craft_bench.prepare` builds it. Two measuring runs were byte-identical.

Against the box browser's stored runs of the same pages, every number the anchors read (share on a
4 px grid, scale ratio, body and largest text, text sizes, fonts not loaded) is the same; only
section heights and page height differ on some pages, where text wraps differently.

No answer key is here: the tests read it from the host.
