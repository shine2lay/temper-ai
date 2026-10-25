# capture_page: full-page web capture

Owner: Design. `capture_page` is three **script** stages — preflight →
capture → verify — and makes **zero model calls**. It captures evidence, not a
semantic or visual-quality verdict. It uses only temper-dev's existing
Playwright MCP service; it never starts another browser service or Temper.

## Library entry (for Temper's shared tool library)

Ready to register when the shared library exists (Temper's plan,
`/home/shinelay/company-lab/workflow-tool-library/PLAN.md`). Until the library
marks it reliable, the workflow description starts "Library tool candidate:".

- **Name:** `capture_page` (candidates run as `capture_page_next`).
- **Purpose:** Capture a web page as-is and in full, with exact slices,
  positioned text and an honest status.
- **Owner:** Design (declared). **Version:** 1 (the full-page capture of
  Design #150; former name `design_web_capture`, renamed in #151 with no
  behaviour change).
- **Config:** `configs/design/workflows/capture_page.yaml`, three script stages
  (`capture_page_preflight`, `capture_page_capture`, `capture_page_verify`),
  zero model calls, $0.
- **Inputs:** `workspace_path` (string, required; an existing folder the worker
  can write), `url` (string, required; public http(s) only), `ready_selector`
  (default `body`), `viewports` (default desktop 1440 × 900 and mobile
  390 × 844), `timeout_ms` (default 30000), `browser_url` (default
  `http://playwright-mcp:8931/mcp`).
- **Outputs:** `verified` (the evidence contract passed; not that the page is
  usable), `receipt_path` (the verification receipt), `captures` (per view:
  first screen and full page, each with status usable / incomplete / not usable
  / uncertain, reasons, notes, images, slices, text, cookie action, `cut_off`,
  `horizontal_overflow`).
- **Ref snippet:**

  ```yaml
  - name: page_evidence
    type: stage
    ref: capture_page
    input_map:
      workspace_path: input.workspace_path
      url: input.url
  ```

- **Proof (#150, 24–25 October 2026):** report
  `/home/shinelay/design-lab/results/full-page-capture-20261024/REPORT.md`.
  Known pages 72/72 (18 cases × 2 widths × 2 repeats, `known-proof-v7.json`);
  8 real sites × 2 widths natively on temper-dev, 16/16 verified, 0 model
  calls, every slice read by eye and the status agreed on all 16 views
  (`native-state-r4.json`; run ids: Airbnb 64740bc6, b715d095; Mayo Clinic
  f6189da0, 48571b38; Patagonia 1f21580a, 673d50e4; Monzo bfe5a198, c1ee960f;
  Brilliant cf384acc, 49ea8352; Fathom d6593651, 2b647c53; The Modern House
  25880b67, f4719baa; Edenmoor d85df03c, 6c294827; preflight 2656d35a).
  Landed db51c0d, live 25 October 01:30 PDT.
- **Rename proof (#151, 25 October 2026):** the renamed code gave #150's
  answers again: known pages 72/72, with the same status, checks and reasons
  on every row; the retained #149 captures the same (Airbnb flagged
  incomplete at both widths, Fathom and Brilliant not); preflight passed;
  the browser script is byte-identical. Report, with the live example run:
  `/home/shinelay/design-lab/results/capture-page-rename-151-20261025/REPORT.md`.
- **Known limits:** the statuses describe what this headless route on
  temper-dev is served (403, holding and robot-check pages stay not usable;
  no stealth or bypass), not the site itself; a cookie window without a
  Reject / Only necessary control is left open, so slice 1 may be partly
  covered (uncertain); script-driven entrance animations can be caught at
  their first frame, unflagged; a robot check that reloads the page mid-capture
  reports the raw browser error as the reason; pages that never go
  network-quiet take several minutes per view (up to about 9 minutes seen);
  sampled occlusion, CSS backgrounds, video, closed shadow roots and nested
  frames are not fully measured; width is not handset emulation. Full list:
  "Status meanings" and "Known limits" below.
- **Receipt schema id:** receipts keep `design.web_capture.v2` (the stages
  check it); it is a data contract, unchanged by the rename so #150's
  receipts stay readable.

## Run

Use the normal native workflow API/CLI with `workspace_path` and a public
HTTP(S) `url`. The workspace must already exist and be writable by the worker.
`capture_page_example` shows reuse as one nested workflow stage.

Optional inputs:

- `ready_selector`: CSS selector to wait for, default `body`.
- `viewports`: array of `{name, width, height}`. Defaults: desktop 1440×900,
  mobile 390×844. Names must be unique safe filenames; sizes positive integers.
- `timeout_ms`: browser-operation/load-settle timeout, default 30,000 ms.
  A timeout is diagnostic failure, never a completeness pass.
- `browser_url`: existing MCP endpoint, default
  `http://playwright-mcp:8931/mcp` inside temper-dev.

No credentials, local/private target URLs, logins, CAPTCHA/robot solving,
stealth, proxies, CSP bypass or alternate pages. Width is not handset emulation.
Every view gets a new isolated browser context, closed in `finally`; the
service's supplied tab and other runs' tabs are never navigated or closed.

## Capture order

1. Preflight validates the input and proves isolated-context, PNG screenshot and
   cleanup capability on the existing service.
2. Navigate normally and wait for the selected element, fonts, in-view images
   and a short network quiet period. Save the **untouched first screen** and its
   positioned text before taking any cookie action. This first image keeps the
   first visitor's cookie obstruction, if present.
3. Examine visible cookie/consent controls in the document and consent iframes.
   Click only an **exact** case-insensitive label in this list:
   `reject all`, `reject`, `decline`, `decline all`, `only necessary`,
   `necessary only`, `use necessary cookies only`, `refuse`, `deny`.
   The control must be in cookie/consent context. Platform IDs such as
   OneTrust's reject control do not override the safe-label requirement.
   Recheck immediately before clicking; record the exact label, selector, ID,
   frame URL, click time and before/after candidates. Never click
   Accept/Agree/Allow/OK or enter preference menus. Without a reject control,
   leave the notice and record `cookie window left open`.
4. Scroll in viewport-height increments, waiting at each position for in-view
   images, fonts and network quiet. The end requires two consecutive bottom
   observations without growth. If the document reaches 25 screen heights,
   stop scrolling and set `cut_off: true`; this is the approved endless-feed
   stop, not proof of the end. Do not silently call the truncated page usable.
   A page that never goes network-quiet (analytics beacons) waits the full
   `timeout_ms` at every step, so one view can take several minutes (Edenmoor
   desktop: 407 s). The capture stage's browser connection therefore waits up to
   the stage's own 3,600 s timeout; a call with no answer by 3,500 s ends in a
   recorded error rather than a silent kill (the MCP client's default 300 s
   stream read timeout used to leave such calls waiting forever).
5. Return to the top and take one native `fullPage` PNG, animations disabled,
   caret hidden, CSS scale, clipped to the viewport's width (what a visitor sees
   without scrolling sideways). No stitching of browser screenshots or injected
   styles: fixed/sticky headers are not repeated once per slice. A page wider
   than the viewport is recorded in `horizontal_overflow` and noted; its text
   past the right edge is marked `past_right_edge`.
6. Cut the saved full image into viewport-height PNG slices; the last can be
   shorter. Slice 1 is the **post-cookie full image's** first screen, not a
   replacement for the separately preserved as-is image.
7. Independently decode/hash-check saved evidence; rejoin all slices and compare
   RGB pixel bytes with the full PNG, with no gaps/overlap; check text/image,
   viewport, source observation and slice-coordinate bindings; reject any
   unsafe consent record. A failed verifier never certifies a diagnostic image.

## Evidence and outputs

Each fresh run has `web-captures/<capture-id>/` containing:

- `preflight.json`, `capture.json`, `verification.json`: input binding,
  capability, browser/navigation, consent, scroll/settle and independent checks.
- `<view>.first_screen.png`, `<view>.first_screen.text.json`: untouched initial
  viewport and text.
- `<view>.full_page.png`, `<view>.full_page.text.json`: post-cookie whole document.
- `<view>.slice-001.png`, etc.: exact full-image slices in top-to-bottom order.

Text records include live text, stable element/text-node ID, tag, document-space
`bbox` and rects, visibility/occlusion reason, `slice_index` and, for the full
page, all intersecting `slice_indices`. Scroll samples supply below-fold
visibility; geometry comes from the screenshot bracket. Accessible frame text
is namespaced, retains frame URL and is mapped into document coordinates;
frame export errors are explicit. The text file binds to its image SHA-256.
Hidden/obscured/uncertain records are labelled, not represented as definitely
visible text. First-screen text is limited to that initial viewport. Each item
also has `in_column`, `past_right_edge` and `changed_during_capture`; the
file's `bracket` lists text items that changed between the observations taken
just before and after the screenshot.

The workflow returns `verified`, `receipt_path`, and `captures`. Every capture
has `views.first_screen` and `views.full_page`, each with status, reasons,
notes, artifact references, dimensions and measured completeness. Top-level capture
status/`usable` refer to the full-page view. `cut_off` and cookie action are
explicit. `verified: true` means the evidence contract passed — **not** that the
page is usable. Inaccessible sites can have correctly verified diagnostic
captures whose status is `not usable`.

## Status meanings

- **usable**: measured checks passed, screenshot/text coherent and settling
  recorded; no known obstruction or cutoff. Not proof of semantic completeness.
- **incomplete** with reasons: broken/unloaded rendered images; implausibly
  little homepage content; an empty homepage shell; large interior blank
  regions; or the endless-feed stop.
- **not usable** with reason: blocked 4xx/5xx, security/robot/error page,
  holding or queue page ("sit tight", "hang tight", "automatically refresh",
  "waiting room", "in the queue" in the title or in short visible text), login
  wall, timeout, missing image or diagnostic-only output. No bypass.
- **uncertain**: text in the picture changed wording, visibility or slice
  during the screenshot, or the page height changed (the text layer may not
  match the image); unresolved cookie notice; frame-text export failure; fonts
  or network that did not settle. Do not promote it to usable or use it as an
  unobstructed review source. Text that only moved within the same slice
  (sliders), and changes outside the picture (off-screen carousels, hidden
  items, image source swaps), are notes, not uncertainty.

Measured heuristics, calibrated against known pages and frozen #149 evidence:

- Uniform-row samples: interior 8–92% of image width, approximately 96 points,
  RGB quantized by 8, dominant colour at least 98%; consecutive interior blank
  rows at least 60% of a viewport are a blank band. Interior bounds come from
  non-overlay text, excluding leading/trailing whitespace. A band predominantly
  within a one-screen section with exactly one heading is exempt (100vh hero).
- Little content: under 30 body characters and under 3% viewport graphic area.
- Shell: no sampled-visible h1 and fewer than 80 main-content characters. This
  catches #149's unloaded Airbnb header/footer shell, not its clean Fathom or
  Brilliant references. The rule can conservatively flag unconventional pages;
  reasons and manual inspection remain necessary.
- Broken media: rendered `<img>` not complete or `naturalWidth == 0`, counted
  only if its box overlaps the picture (the viewport's column; for the first
  screen also its height). Far lazy images and carousel images parked off to
  the side are not what a visitor sees there.

Known limits: sampled occlusion is not all-pixels visibility proof; CSS background
loading, video, closed shadow roots and nested-frame clipping are not fully
measured. Screenshot animation freezing covers CSS animations only, so a
script-driven entrance animation can be caught at its first frame (faint tiles
on Monzo); nothing flags it yet. When a robot check reloads the page mid-capture
(The Modern House mobile), the status is correctly `not usable` but the reason is
the raw browser error rather than "security/robot check". Runtime errors, failed requests, frame errors, pending requests and
settle evidence remain in the receipt. Images of an obstructed/partial page are
useful diagnostics, never substituted for a successful target capture.

## Proof and maintenance

`tests/test_capture_page.py` covers input, isolation, PNG corruption,
exact slice tiling, receipt binding, consent allowlist, text geometry and honest
statuses. `tests/fixtures/capture_page_cases.py` defines fixed browser
pages: short complete, lazy media, sticky header, 100vh hero, Reject, Accept-only,
iframe consent, blank band, broken image, endless feed, blocked page, wide
overflow, far lazy image, parked carousel, ticker, off-screen marquee, sideways
slider and queue page.
Serve/route these only inside a new test context on the existing temper-dev
browser, not by starting another Temper instance. Exercise preflight, capture
and verify independently; repeat each browser case twice before whole native
workflow runs. Verify the iframe as-is export includes the consent text too.

Task #150 evidence, repaired hypotheses, known-case proof, native 8-site ×
2-width receipts, first-screen contact sheet and per-slice inspection:
`/home/shinelay/design-lab/results/full-page-capture-20261024/`.
Frozen comparison (never altered):
`/home/shinelay/design-lab/results/real-homepages-149-20261024/`.
A later workflow change needs a written hypothesis and affected-stage proof
before rerunning the whole cohort.
