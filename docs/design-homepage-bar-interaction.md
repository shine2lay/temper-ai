# design_homepage_bar_interact: the homepage A-bar meter, part 2 (Design, queue #79)

Part 2 measures what part 1 (`docs/design-homepage-bar.md`, queue #78) leaves out: keyboard,
focus, hover, motion, reduced motion and speed, for one built homepage, against the interaction
and speed lines of `~/design-lab/homepage-workflow/BAR.md` (A4, A7, A8). It uses no model
(AGENTS rule 17): every row is a measured number checked against a fixed limit.

- `configs/design/bin/design_homepage_bar_interact.js`: in-page helpers (one function expression
  that installs `window.__bi`). They return raw measurements only, with no limits in them.
- `configs/design/bin/design_homepage_bar_interact.py`: the browser driver, the Lighthouse runner,
  the pure scorer (raw JSON to rows, where every limit is applied) and the CLI.
- `configs/design/testpages/bar-interact-v1/`: fixture pages with a known key (`expected.json`),
  their shared `base.css`, the video clip, and the recorded `raw/*.json`.
- `tests/test_design_homepage_bar_interact.py`: the scorer on every recorded raw file must give
  exactly the key, plus unit tests of the maths. No browser in the tests.

Written 2026-10-18, before any real page was measured. After the first real page is measured, a
definition changes only with a dated reason written at the end of this file, and never to make a
page pass. Limits are BAR.md's, word for word; the meter never changes a limit.

## Running it

```
design_homepage_bar_interact.py --site DIR [--page index.html] --out DIR [--browser URL] \
    [--serve-host HOST] [--lighthouse DIR] [--chrome PATH] [--no-speed] [--raw-only | --from-raw DIR]
design_homepage_bar_interact.py --fixture-proof --out DIR [--record] [--from-raw DIR] [...]
```

- Browser: temper's playwright-mcp service (default `http://playwright-mcp:8931/mcp`; from the host
  use `--browser http://127.0.0.1:8931/mcp --serve-host <the container's address>`, today
  172.21.0.4). The site folder is served over HTTP by `design_capture.serve` (imported, unchanged),
  and the page is driven with `design_capture.run` (`browser_run_code_unsafe`).
- Speed: the pinned local tool in `~/design-lab/tools/bar-interact/` (`--lighthouse`): Lighthouse
  13.5.0 and puppeteer-core 25.14.0 from its `package-lock.json`, on the local Chromium
  (`--chrome`, default `~/.cache/ms-playwright/chromium-1243/chrome-linux-arm64/chrome`, Chrome for
  Testing 153.0.8010.12), headless, with the page served by `design_capture.serve` at 127.0.0.1.
  Its README has the exact install command and the lock file's sha256. With `--no-speed`, or when
  the tool can't run, the three speed rows are `null` (not met) and the error is kept in the raw file.
- `--out DIR` gets `raw-interact.json` (the measurements), `bars-interact.json` and
  `bars-interact.md`, plus `shots/` (the focus crops, for checking a row by eye).
  `--raw-only` stops after `raw-interact.json`; `--from-raw DIR` scores `DIR/raw-interact.json`
  with no browser.
- `--fixture-proof` measures every page in `bar-interact-v1/expected.json` and compares its failing
  rows with the key (exact set equality). `--record` also saves each raw file to
  `bar-interact-v1/raw/`. With `--from-raw DIR` it re-scores the raw files in DIR instead.

## Output contract (shared with part 1)

`bars-interact.json`:
`{meter, version, page, page_sha256, widths, rows: [{bar, check, width, value, limit, pass, evidence}]}`

- `meter` is `design_homepage_bar_interact`; `version` is `1`.
- `page` is the page's path; `page_sha256` is the sha256 of its HTML file.
- `widths`: `["1440x900", "390x844", "412x823"]`. `412x823` is Lighthouse's mobile preset (its
  emulated Moto G Power screen) and is used only by the three speed rows.
- `pass` is `true`, `false` or `null`. `null` means "could not measure" and counts as not met.
- `evidence`: up to 5 items `{selector, text (80 characters or fewer), box: [x, y, w, h]}`, page
  coordinates in CSS px, for the elements that fail the row (for motion-present, the elements
  that move). For an element that moves (animation, transition or transform evidence), the box is
  its layout box without transforms (the offset box), so it does not drift from run to run.
- Rows come in a fixed order (the check order below, then width), and the file has no timestamps.
  Two runs of the same page give identical rows, except the speed rows' values (lab timings
  vary run to run; their pass or fail must not).

`bars-interact.md` has the table `bar | check | width | value | limit | pass` and a summary per
bar. A bar is met only when every one of its rows passes. Merging this meter with part 1 into one
gate step is later work.

## How a page is loaded

- Widths: 1440x900 and 390x844 for every check except speed (the plan for #79, decided with the
  Design lead). BAR.md's A header lists five widths; the interaction checks use the two
  first-screen widths for now. Widening them is later work, not a lowered bar.
- Each phase below opens the page fresh: set the viewport, emulate `prefers-reduced-motion`
  (`no-preference`, or `reduce` in the reduced-motion phase) and the light colour scheme, go to the
  page and wait for network idle and `document.fonts.ready`, then wait 500 ms more.
- Settle (used by the keyboard, focus, UI-part, hover and focus-state phases, never by the motion
  phases): every finite animation or transition is finished (`Animation.finish()`), every infinite
  one is paused at its start, and every video is paused, so the page is at rest and two pictures
  differ only by the state under test. Settle runs before every reading in those phases.
- Scrolling by the meter is instant. After focus moves, the meter waits until the scroll position
  is the same for 3 animation frames (at most 1.5 s), so pages with smooth scrolling are read after
  the scroll ends.
- Visible element (as in part 1): it has a box larger than 0x0, it is not `display: none`,
  `visibility: hidden` or `opacity: 0` (its own or an ancestor's), and some of it survives clipping
  by ancestors with non-visible overflow, `clip` or `clip-path`.
- Interactive element: a visible `a[href]`, `button`, `input` (not `type=hidden`), `select`,
  `textarea`, `summary`, or element with a `tabindex` of 0 or more, that is not disabled and not
  inside `[inert]`. Radio buttons with the same name in the same form count as one control.
  Frames and shadow trees are out of scope.
- Fixed or sticky element: an element whose computed `position` is `fixed` or `sticky`, or one
  inside such an element.
- Selector in evidence: the element's path from the nearest ancestor with an id (or from `body`),
  each step `tag:nth-child(n)`.

## The checks

BAR.md A4: "UI parts and focus indicators meet 3:1; ... every interactive element is reached by Tab
in reading order with a visible, unhidden focus (2.4.7, 2.4.11); ... prefers-reduced-motion stops
all non-essential motion".
BAR.md A7: "hover and focus states exist for every interactive element; the concept's motion idea
is present and respects reduced motion." (The reduced-motion part is measured by the A4 rows.)
BAR.md A8: "Speed (lab, Lighthouse mobile preset): LCP 2.5 s or less, CLS 0.1 or less, total
blocking time 200 ms or less."

### Keyboard walk (feeds the first five rows)
Settle, blur, scroll to the top. Press Tab up to 200 times. After each press read
`document.activeElement`; the walk ends when it is the body, the html element or null (focus left
the page), or when it is the walk's first stop again. At each stop the meter records the element,
its box in page and viewport coordinates and its fixed or sticky container, and then:
1. tests five points of the focused element's viewport box: the centre and the four corners inset
   by 4 px (or a quarter of the width or height, if smaller). A point is hidden when it lies outside
   the viewport, or when `document.elementFromPoint` there is inside a fixed or sticky element that
   does not contain the focused element and is not the focused element or inside it;
2. settles and takes a screenshot (CSS px) of the focused element's viewport box grown by 16 px on
   each side, cut to the viewport (16 px, not the 4 px first written: see "Changes to definitions",
   2026-10-19);
3. blurs the element, settles, takes the same clip again, then focuses it again with
   `focus({preventScroll: true})` and settles, so the next Tab continues from it.

Changed pixel: a pixel of the clip whose colour differs between the two shots by more than 2 (of
255) in any channel. Perimeter: 2 x (width + height) of the focused element's box cut to the
viewport, at least 4. Indicator contrast of a stop: for each changed pixel, the WCAG contrast ratio
between its focused and unfocused colours; the stop's value is the perimeter-th highest of those
ratios (the contrast that at least a perimeter's worth of changed pixels reach), or 1 when fewer
pixels changed.

| check | bar | definition | limit |
|---|---|---|---|
| keyboard-reach | A4 | Interactive elements (radio groups as one) that the walk never reached. Value: their number. | every interactive element is reached by Tab |
| keyboard-order | A4 | Consecutive stops (p, then c), with boxes in page coordinates. A pair is compared only when neither stop is in a fixed or sticky element, or both are in the same one (then viewport coordinates are used). An inversion is (a) c's top more than 24 px above p's top, unless c lies wholly right of p (c's left edge at or right of p's right edge: a move to the next column, as in card grids and footer columns); or (b) c and p on the same row (their vertical spans overlap by at least half the shorter box's height) with c wholly left of p. Each pair counts once. Value: the number of inversions. | reached by Tab in reading order |
| focus-visible | A4 | Stops not entirely hidden (see focus-not-obscured) whose changed pixels are fewer than the perimeter. Value: their number. | with a visible, unhidden focus (2.4.7, 2.4.11) |
| focus-not-obscured | A4 | Stops whose five points are all hidden (WCAG 2.4.11: focus not entirely hidden). Value: their number. | with a visible, unhidden focus (2.4.7, 2.4.11) |
| focus-contrast | A4 | Stops that pass focus-visible and are not entirely hidden, whose indicator contrast is under 3:1. Value: their number. | UI parts and focus indicators meet 3:1 |

Notes:
- The column exemption in keyboard-order is a precision written before any real page was measured:
  without it, the correct card-by-card order of a card grid (title link, then "Read more", then the
  next card's title above and to the right) would count as inversions.
- A stop on an element that is not an interactive element by the definition above (for example a
  focusable element that is clipped away) is still a stop for order and focus.
- If the walk reaches 200 stops, it stops there; what it did not reach counts as unreached.

### UI parts
After settle, with nothing focused and the mouse off the page, each candidate is scrolled to the
centre of the viewport. Candidates are interactive elements of two kinds:
- field: `input` of a text-like type (text, email, search, tel, url, password, number, date, time,
  datetime-local, month, week, or no type), `select`, `textarea`;
- button: `button`, `[role=button]`, `input` of type submit, button or reset, and `a[href]` whose
  box is 80 px tall or less.
Checkboxes, radios, ranges, colour and file inputs are drawn by the browser and are not measured.
A candidate that is still not on screen after it is centred (for example a skip link kept above the
page until it has focus) is measured where it shows: it is given focus (the browser scrolls it into
view), and its style, behind colour and fill are read while it has focus. If it is still not on
screen, its contrast cannot be measured and the row is `null`.

Behind colour: a screenshot of the element's viewport box taken while the element is set to
`visibility: hidden` (set for the shot only); the behind colour is its pixel of median relative
luminance. Fill: the computed `background-color` composited over the behind colour; when the element
has a `background-image`, the pixel of median luminance of a screenshot of its padding box instead.
Border: the top border's computed colour composited over the behind colour, when all four sides have
a style other than none or hidden, a width of 1 px or more and a colour that is not transparent
(a full border).
A button is a UI part when its fill differs from the behind colour (more than 2 in any channel) or
it has a full border; a button with neither is a text button with no boundary to measure (its text
contrast is part 1's). A field is always a UI part. Part contrast: the higher of contrast(fill,
behind) and contrast(border, behind).

| check | bar | definition | limit |
|---|---|---|---|
| ui-contrast | A4 | UI parts whose part contrast is under 3:1 (solid buttons' fill against what is behind them; input and outlined-button borders against their background). Value: their number. | UI parts and focus indicators meet 3:1 |

### Hover and focus states
Compared properties, on the element, its descendant elements (the first 60) and their rendered
`::before` and `::after`: `color`, `background-color`, `background-image`, the four borders' colour,
style and width, `box-shadow`, `outline-color`, `outline-style`, `outline-width`,
`outline-offset`, `text-decoration-line`, `-color`, `-style` and `-thickness`, `transform`,
`translate`, `scale` and `rotate`. A state exists when any of them differs between rest and the
state. Descendants and pseudo-elements count because a control's state is often shown on its
contents (a card link's heading, an underline drawn by `::after`). Properties that draw nothing
are not compared: the outline's colour, width and offset only when `outline-style` is not none in
at least one of the two states; a border side's colour and width only when its style is not none
or hidden in at least one; the text decoration's colour, style and thickness only when
`text-decoration-line` is not none in at least one. (Otherwise `outline: none` on focus, next to
an `outline-offset` left by another rule, would count as a focus state.)

- Hover: for each interactive element, the mouse is moved off the page (-20, -20); the element is
  scrolled to the centre; settle; rest values are read. The mouse moves to the element's centre, or,
  when `elementFromPoint` there is not the element or inside it, to the first of its four inset
  corners that is. If none is, the element cannot be hovered and has no hover state (evidence
  "covered"). Settle; hover values are read. An element with no such point at rest is first given
  focus, the way a keyboard user reveals it (a skip link kept above the page until it has focus),
  and the same is done with focus kept: rest is read focused, then hovered and focused, so only the
  hover's own change counts (raw evidence `via: focus`). Only when it still has no such point is it
  "covered".
- Focus: one Tab press puts the page in keyboard focus mode, then focus is removed. For each
  interactive element: `focus()` (the browser scrolls it into view), wait for the scroll, settle,
  read; `blur()`, settle, read. An element that does not become `document.activeElement` has no
  focus state (evidence "not focusable").

| check | bar | definition | limit |
|---|---|---|---|
| hover-states | A7 | Share of interactive elements with a hover state, in percent (one decimal). No interactive elements: 100. | hover and focus states exist for every interactive element |
| focus-states | A7 | Share of interactive elements with a focus state, in percent (one decimal). | hover and focus states exist for every interactive element |

Pass for both: 100%.

### Motion
Normal motion (`no-preference`), a fresh load with the mouse off the page (-20, -20) and a
passive listener installed before the page's own scripts, recording every `animationstart` and `transitionstart` event. Samples of running
animations (`document.getAnimations()` with play state running): at the load event, after network
idle and fonts plus 500 ms, and 100, 300 and 600 ms after the meter scrolls down one viewport
height. The computed `transform`, `translate`, `scale` and `rotate` of every element are read before
the scroll and 1000 ms after it.

Reduced motion (`reduce` emulated), a fresh load; after network idle and fonts plus 2000 ms: R1 =
running animations; the videos; transforms read. Then the meter scrolls down one viewport height:
R2 = running animations 100, 300 and 600 ms after the scroll; transforms read again 1000 ms after.
An animation's length is its active duration (`getComputedTiming().activeDuration`; infinite counts
as longer than any limit).

| check | bar | definition | limit |
|---|---|---|---|
| reduced-motion-animation | A4 | Distinct running animations in R1 or R2 longer than 200 ms. Value: their number. | prefers-reduced-motion stops all non-essential motion |
| reduced-motion-video | A4 | Video elements with a box larger than 0x0 that are playing (not paused, not ended) 2 s after load. Value: their number. | prefers-reduced-motion stops all non-essential motion |
| reduced-motion-scroll | A4 | Elements whose transform values differ before and 1000 ms after the one-screen scroll, leaving out elements with an animation in R1 or R2 (the animation row counts those). Value: their number. | prefers-reduced-motion stops all non-essential motion |
| motion-present | A7 | Elements that move with normal motion: targets of a recorded animation or transition event, of a running animation in any sample, or with a transform change across the scroll. Value: their number; met at 1 or more. | the concept's motion idea is present |

Notes: R2 and the scroll-started events are included so that motion started by scrolling (reveal
effects) is judged too. The exclusion in reduced-motion-scroll keeps each moving thing in one row.

### Speed
Lighthouse 13.5.0, its default mobile configuration (the mobile preset: 412x823 screen at 1.75
device pixel ratio, simulated throttling with 150 ms round trip, 1,638.4 Kbps and a 4x CPU
slowdown), performance category only, on the pinned Chromium, headless, the page served at
127.0.0.1. Three runs one after another. Each run's `numericValue` of `largest-contentful-paint`
(ms), `cumulative-layout-shift` and `total-blocking-time` (ms). Value: the median of the three runs
(LCP and TBT in whole ms, CLS to 4 decimals); the pass is decided on the median. If any run gives no
value, the row could not be measured (`null`).

| check | bar | width | limit |
|---|---|---|---|
| lcp | A8 | 412x823 | LCP 2.5 s or less (2500 ms or less) |
| cls | A8 | 412x823 | CLS 0.1 or less |
| tbt | A8 | 412x823 | total blocking time 200 ms or less |

## The fixture proof (bar-interact-v1)
`bar-interact-v1/expected.json` was written before the meter, with each page's exact failing
`(bar, check, width)` rows. `clean.html` meets every part-2 check; each planted page is
`clean.html` plus one plant, and between them they break every check at least once. The meter is
right only when its failing rows equal the key exactly on every page, in two runs, with identical
non-speed rows and the same pass or fail on every speed row in both runs. When they differ, the
meter is fixed, never the key.

## Running it inside temper's worker (finding only; no stack change)
Checked 2026-10-19 against `Dockerfile` and `docker-compose.yml` on main. Nothing was changed.

- Browser rows (keyboard, focus, UI parts, hover and focus states, motion, reduced motion): these
  already fit temper. They use only the playwright-mcp service (`http://playwright-mcp:8931/mcp` on
  the compose network, `browser_run_code_unsafe`; reduced motion is `page.emulateMedia` there) and
  `design_capture.serve` and `design_capture.run`, as the design workflows do today. A worker run
  passes `--serve-host` with an address of the worker container that playwright-mcp can reach.
- Speed rows (A8): these cannot run in the worker image as it is.
  - The image has Node 20 (`setup_20.x` in the `base` stage), and Lighthouse 13.5.0 needs Node
    22.19 or later.
  - The image has no Chromium. That is on purpose: the compose file keeps the browser (about
    1.5 GB) in the playwright-mcp service alone.
  - playwright-mcp's Chromium can't stand in for it. The service starts no remote-debugging port,
    and Lighthouse needs its own Chrome over CDP.
- What would let a workflow run the speed rows, for whoever owns the stack (temper, systems) to
  choose:
  1. A small Lighthouse service built like playwright-mcp: its own image with Node 22, Chromium and
     this folder's `package-lock.json`, called over HTTP on the compose network. This keeps the
     worker small, and it is the recommended option.
  2. Node 22 plus Chromium in the worker image. This is simpler, but it adds about 1.5 GB to every
     worker, against the reason the compose file gives.
  3. Keep running speed on the host, as now (the pinned tool and the local Chromium). This needs no
     change, but only the host can run it.
- Until one of these exists, a worker run would score the speed rows `null` (not met). Run speed
  on the host and merge the rows.

## Changes to definitions
No limit has changed. One definition and two methods changed, after the first baseline run, each
because a hand check showed the meter misreading a page, never to make a page pass:

- 2026-10-19, focus clip 4 px -> 16 px (definition; the plan for #79 said "box plus 4 px"). In the
  first baseline run every page failed focus-visible (Morrow Rooms v2.1r 22 stops at 1440). Opened
  by hand, Morrow Rooms' "Demo rooms" link has a clear focus ring: `outline: 3px solid` at
  `outline-offset: 4px`, so the ring lies 4 to 7 px outside the box and a 4 px clip contains none
  of it (0 changed pixels; perimeter 296). With a 16 px clip, 1,020 pixels change, at 3.66:1. All
  four baseline pages draw rings this way (3 px at a 4 px offset); 16 px holds a ring up to 6 px
  wide at an offset up to 10 px. The bar is unchanged: changed pixels must still reach the box's
  perimeter, at 3:1. The fixtures' rings (3 px at 1 px) lie inside both clips.
- 2026-10-19, elements off the page at rest (method). Driftwatch v2.1r's skip link sits at
  `top: -96px` until it has focus, so the hover phase called it "covered" (hover-states 92%) and
  the UI-part phase could not measure it (ui-contrast `null`), although its CSS has a hover rule
  (`.skip:hover { text-decoration: underline; }`) and it shows on focus. Both phases now reveal such
  an element with focus first (see UI parts, and Hover and focus states). An element that focus
  cannot bring on screen is still "covered" or unmeasured.
- 2026-10-19, perimeter of a box wholly outside the viewport is 4 (the minimum), not its full
  size: nothing of it is drawn, so its whole perimeter cannot be asked of it (unit test case).

Changes to fixtures and evidence, all made before any real page was measured:

- 2026-10-19, fixture slow-script.html (plant made effective; key unchanged): in fixture proof run 1
  its LCP row passed (median 901 ms, the same as clean.html) while expected.json says it fails. The
  meter reported Lighthouse's value correctly: Lighthouse's simulated throttling did not put the
  700 ms busy-wait written inline in the head on the LCP path (its TBT did count it, 5,351 ms). The
  same 700 ms of work moved into a parser-blocking external script (`busy.js`) gives a simulated LCP of
  3,703 to 3,706 ms in scratch runs, so the plant now really is "a heavy blocking script", as the
  plan for #79 asks. The meter and expected.json were not changed for it.
- 2026-10-19, evidence only (no effect on any pass): moving elements report their offset box (see
  the output contract), and the LCP element is read from Lighthouse 13's `lcp-breakdown-insight`
  (its `largest-contentful-paint-element` audit no longer exists).
