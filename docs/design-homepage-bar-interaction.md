# design_homepage_bar_interact: the homepage A-bar meter, part 2 (Design, queue #79)

Part 2 measures what part 1 (`docs/design-homepage-bar.md`, queue #78) leaves out: keyboard,
focus, hover, motion, reduced motion and speed, for one built homepage, against the interaction
and speed lines of `~/design-lab/homepage-workflow/BAR.md` (A4, A7, A8) and, since version 4, A11 (d),
motion with a purpose. It uses no model (AGENTS rule 17): every row is a measured number checked
against a fixed limit.

- `configs/design/bin/design_homepage_bar_interact.js`: in-page helpers (one function expression
  that installs `window.__bi`). They return raw measurements only, with no limits in them.
- `configs/design/bin/design_homepage_bar_interact.py`: the browser driver, the Lighthouse runner,
  the pure scorer (raw JSON to rows, where every limit is applied) and the CLI.
- `configs/design/testpages/bar-interact-v1/`: fixture pages with a known key (`expected.json`),
  their shared `base.css`, the video clip, and the recorded `raw/*.json`.
- `configs/design/testpages/bar-interact-v2/`: the keyed cases for version 2's UI-part reading
  (each page is bar-interact-v1's `clean.html` plus one case), with a copy of `base.css`, its own
  `expected.json` and `raw/*.json`.
- `configs/design/testpages/bar-interact-a11-v1/`: the sealed keyed cases for version 4's A11 (d)
  rows (each planted page is its `clean-motion.html` plus one plant), with its own `base.css`,
  `expected.json` and `raw/*.json`. The key's sha256 is in `~/design-lab/seals/bar-interact-a11-v1.json`.
- `tests/test_design_homepage_bar_interact.py`: the scorer on every recorded raw file must give
  exactly the key, plus unit tests of the maths. No browser in the tests.

Written 2026-10-18, before any real page was measured. After the first real page is measured, a
definition changes only with a dated reason written at the end of this file, and never to make a
page pass. Limits are BAR.md's, word for word; the meter never changes a limit.

## Running it

```
design_homepage_bar_interact.py --site DIR [--page index.html] --out DIR [--browser URL] \
    [--serve-host HOST] [--lighthouse DIR] [--chrome PATH] [--no-speed] [--raw-only | --from-raw DIR]
design_homepage_bar_interact.py --fixture-proof --out DIR [--set NAME ...] [--record] [--from-raw DIR] [...]
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
  the tool can't run, the three speed rows are `null` (could not measure; never met) and the error is
  kept in the raw file. The speed runs are taken only on a quiet machine (1-minute load under 6; see
  "Speed"); when the machine stays busy, the speed rows are `null` in the same way.
- `--out DIR` gets `raw-interact.json` (the measurements), `bars-interact.json` and
  `bars-interact.md`, plus `shots/` (the focus crops, for checking a row by eye).
  `--raw-only` stops after `raw-interact.json`; `--from-raw DIR` scores `DIR/raw-interact.json`
  with no browser.
- `--fixture-proof` measures every page in `bar-interact-v1/expected.json`,
  `bar-interact-v2/expected.json` and `bar-interact-a11-v1/expected.json` and compares its failing
  rows with the key (exact set equality, over the rows the key covers). `--set NAME` (repeatable)
  limits it to the named sets.
  `--record` also saves each raw file to its set's `raw/`. With `--from-raw DIR` it re-scores
  `DIR/<set>/raw/<page>.json` instead (DIR is normally `configs/design/testpages`, the recorded runs).
  Its outputs go to `--out`'s `<set>/<page>/` folders.

## Output contract (shared with part 1)

`bars-interact.json`:
`{meter, version, page, page_sha256, widths, rows: [{bar, check, width, value, limit, pass, evidence}]}`

- `meter` is `design_homepage_bar_interact`; `version` is `4` (UI parts read per WCAG 1.4.11 since
  version 2, and speed rows measured only on a quiet machine since version 3, both 2026-10-19; the
  four A11 (d) rows since version 4, 2026-10-20; see "Changes to definitions").
- `page` is the page's path; `page_sha256` is the sha256 of its HTML file.
- `widths`: `["1440x900", "390x844", "412x823"]`. `412x823` is Lighthouse's mobile preset (its
  emulated Moto G Power screen) and is used only by the three speed rows.
- `pass` is `true` (met), `false` (not met) or `null` (could not measure). A `null` row is never
  met, so a bar with one is never met. Since version 3 it is counted apart from met and not met: in
  `bars-interact.md` (the bar's summary and the row counts) and in the fixture proof.
- `evidence`: up to 5 items `{selector, text (80 characters or fewer), box: [x, y, w, h]}`, page
  coordinates in CSS px, for the elements that fail the row (for motion-present, the elements
  that move). For an element that moves (animation, transition or transform evidence), the box is
  its layout box without transforms (the offset box), so it does not drift from run to run.
  The A11 (d) rows' items also have `property` and `value` (what moves or fails, and how: for
  example `property: "background-color"`, `value: "transition 800 ms ease"`). The motion-feedback
  row's evidence lists every element without feedback, not only 5 (BAR.md's row names them all).
- Rows come in a fixed order (the check order below, then width; the speed rows, then the four
  A11 (d) rows at each of the two widths, come last), and the file has no timestamps.
  Two runs of the same page give identical rows, except the speed rows' values (lab timings
  vary run to run; their pass or fail must not). On a busy machine a speed row may come out `null`
  (could not measure) instead; the gate never turns it into a pass or a fail.

`bars-interact.md` has the table `bar | check | width | value | limit | pass` (pass `yes`, `no` or
`could not measure`) and a summary per bar. A bar is met only when every one of its rows passes:
its line says `met`; otherwise `not met (check width, ...)` for the rows that fail and
`could not measure (check width, ...)` for the rows with no value, joined by `; `. The A11 line
covers only the (d) rows (part 1 has A11's other rows), and the line under it reports A8's `cls`
row next to (d), unchanged (see "Motion with a purpose"). Under the bars,
the line `Rows: X met, Y not met, Z could not measure.` counts the rows apart. Then come
"Evidence for rows not met" (the `false` rows, with their evidence) and "Rows that could not be
measured" (each `null` row with its reason, and the elements its evidence names, if any). Merging
this meter with part 1 into one gate step is later work.

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
centre of the viewport. Candidates are interactive elements of three kinds:
- field: `input` of a text-like type (text, email, search, tel, url, password, number, date, time,
  datetime-local, month, week, or no type), `select`, `textarea`;
- button: `button`, `[role=button]`, `input` of type submit, button or reset;
- link: `a[href]`, at any height (version 1 took only links 80 px tall or less, as buttons).
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
Part contrast: the higher of contrast(fill, behind) and contrast(border, behind).

Visible text: a text node inside the candidate with a character that is not white space, drawn in
the candidate's box. Its parent element is visible, its `color` is not fully transparent, and one of
its line boxes (`Range` client rects), cut to the candidate's box and clipped by its parent and
every ancestor (overflow, `clip`, `clip-path`, as for a visible element), keeps more than 1 x 1 px.
So text kept for screen readers only (a 1 px box with `clip` or `clip-path`) and text pushed out of
the box (`text-indent: -9999px`) are not visible text. An `input` button draws its value: it has
visible text when its value is not empty, or when it is of type submit or reset (the browser draws
a default label), and its `color` is not transparent. Visible text is read with the style, with the
candidate on screen.

What is measured (version 2; WCAG 1.4.11 and its Understanding document, "Boundaries"):
- A field is always a UI part, identified by its boundary. Its value is its part contrast.
- A control is a button, or a link whose fill differs from the behind colour (more than 2 in any
  channel) or that has a full border. A link with neither is a text link with no boundary to
  measure; it is not a UI part.
- A control with visible text is identified by its text. Its text contrast is part 1's
  text-contrast row; its fill and border are not measured here.
- A control with no visible text is identified by its icon. Its value is its icon contrast (below).
- A control with no visible text and no icon pixels is identified by its shape alone. Its value is
  its part contrast, when it has a fill or a full border. One that draws nothing at all (no visible
  text, no fill, no full border, no icon pixels) is not measured.

Icon contrast (from a screenshot, with no model):
- The shot: the control's viewport box, cut to the viewport and widened to whole CSS pixels, taken
  at rest just before the behind shot.
- Inside pixels: pixels whose centres lie at least 1 px inside the control's padding box (inside its
  border) and at least 1 px inside its rounded corners (each corner's radius, less the border's
  width there; percentages resolved and overlapping radii scaled down as CSS does). The 1 px keeps
  out the edge pixels that anti-aliasing blends with what is behind.
- Reference: the fill when it differs from the behind colour, otherwise the behind colour: what is
  directly behind the icon.
- Icon pixels: inside pixels that differ from the reference by more than 2 in any channel.
- Icon contrast: rank the icon pixels by their contrast with the reference, lowest first. The value
  is the contrast of the 90th-percentile pixel (the ceil(0.9 x n)-th of n) with the reference.
  Anti-aliased icon edges sit below it, and a few stray pixels cannot lift it.
- Known limits: a gradient or image fill, an inset shadow and a picture inside a control (an image
  link) are read as icon pixels; a glyph from an icon font is a text node, so its control reads as
  a text control.

| check | bar | definition | limit |
|---|---|---|---|
| ui-contrast | A4 | UI parts whose value is under 3:1: fields by part contrast (border or fill against what is behind them); controls with no visible text by icon contrast (or, with no icon, by part contrast). Value: their number. | UI parts and focus indicators meet 3:1 |

Raw files measured before version 2 have no visible-text reading. Their candidates are scored as in
version 1 (every button and link with a fill or full border by part contrast), so version 1's results
can still be re-scored as they were.

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
127.0.0.1. Three runs one after another, each on a quiet machine (below). Each run's `numericValue`
of `largest-contentful-paint` (ms), `cumulative-layout-shift` and `total-blocking-time` (ms).
Value: the median of the three runs (LCP and TBT in whole ms, CLS to 4 decimals); the pass is
decided on the median. If any run gives no value, the row could not be measured (`null`).

Quiet machine (version 3, H3d): the 1-minute load average (the first number in `/proc/loadavg`)
is read before and after each Lighthouse run.

- Before: if it is 6 or more, the meter waits 15 s and reads it again, until it is under 6.
- After: if it is 6 or more, the machine got busy during the run. That run is thrown away (kept in
  the raw file under `dropped`) and redone.
- The cap: 600 s per page, from the start of its speed step. It is checked before each wait and
  before each run (a run under way finishes and is judged as above), so a page's speed step takes
  at most 600 s plus one run. If the cap passes before three quiet runs are in, all three speed
  rows are `null`, with the reason `could not measure: machine busy (load X)` (X: the last reading
  of 6 or more, to two decimals) or, if no reading was 6 or more, `could not measure: N of 3 quiet
  runs in 600 s`. The quiet runs already in are kept in the raw file, never scored alone.
- The load counts every process on the machine, the meter's own Lighthouse and Chrome too.

Raw file: `speed` is `{runs, dropped, gate, nodes, lighthouse, chrome}`, plus `error` when the rows
could not be measured. Each item of `runs` and `dropped` is `{lcp, cls, tbt, load_before,
load_after}`. `gate` is `{load_limit: 6.0, poll_s: 15, cap_s: 600, waited_s, polls, redone,
elapsed_s, busy_load}`: `waited_s` is the time spent waiting before runs, `polls` the number of
waits, `redone` the number of runs thrown away, `elapsed_s` the whole step, and `busy_load` the last
reading of 6 or more (`null` if none). A Lighthouse error still ends the step at once, as before,
with its message as the reason. Raw files from before version 3 have no loads and are scored as
before.

| check | bar | width | limit |
|---|---|---|---|
| lcp | A8 | 412x823 | LCP 2.5 s or less (2500 ms or less) |
| cls | A8 | 412x823 | CLS 0.1 or less |
| tbt | A8 | 412x823 | total blocking time 200 ms or less |

### Motion with a purpose (A11 (d), version 4)
BAR.md A11 (d): "Motion with a purpose: one signature motion moment on the first screen (entrance or
scroll-linked); hover or press feedback on every interactive element (transform, shadow or colour
change); transitions 120-500 ms with easing, and nothing but loops longer than 1 s; all of it stops
under prefers-reduced-motion, and A8's CLS still holds." BAR.md's words are fixed. The numbers they
leave open were set by Design (home) for queue #113, before any code and before any real page was
measured, and the sealed key `bar-interact-a11-v1` holds the meter to them. The row's own sources:
Material 3 motion durations, NN/g animation timing (100-500 ms), Apple HIG motion, WCAG 2.3.3.
Widths: 1440x900 and 390x844.

Two readings per width, each a fresh load, taken after every older phase of both widths (so the
older rows are measured exactly as before): the normal reading (`prefers-reduced-motion:
no-preference`) for the signature, feedback and timing rows, and the reduced reading (`reduce`
emulated) for the reduced-motion row. Each reading has four steps:

1. Load. A script added before the page's own scripts reads `document.getAnimations()` on every
   animation frame, from the start of the load to the end of the reading, and records every
   animation it sees whose target is an element: CSS animations, CSS transitions and Web
   Animations. The page loads with the mouse off the page (-20, -20). The meter waits for network
   idle and fonts, then until 3,100 ms after the end of the load event (`loadEventEnd`), so every
   animation that starts within 3 s of load has been seen.
2. Scroll. The first 2 screens are scrolled in 8 instant steps of a quarter of the viewport height
   (to twice its height), with 200 ms after each step. After each step the progress of every
   scroll-driven animation (one on a scroll or view timeline) is read.
3. Hover and press: every element of the feedback check, as described there.
4. End. The page is scrolled to the top and settled (as in "How a page is loaded"). Each recorded
   animation's target box is read: its layout box without transforms, at scroll 0. The elements
   whose computed `scroll-behavior` is `smooth` are listed.

An animation's record: its kind (CSS animation, CSS transition or Web Animation); its name (the
animation name, the transition's property or the Web Animation's id); its target (selector and
pseudo-element); its duration (one iteration, in ms), iterations and delay; its timing functions
(the effect's, and each keyframe's except the last, which never applies); the properties it
changes (a transition's property; for the others, each property in its keyframes, except one
that has the same value in every keyframe, the first and last included); when it was first seen
(the load step, scroll step 1 to 8, or hover and press); and, if it is scroll-driven, its progress
after each scroll step. One animation is one (kind, target, pseudo-element, name, duration, timing
function): a transition that runs on every hover counts once. An animation that starts and ends
between two frames (under about 17 ms) is not seen.

motion-signature. "At least one animation (document.getAnimations(): CSS animation, transition or
Web Animations) on an element of the first screen. It must change transform, translate, scale,
rotate, opacity, clip-path or offset. It starts within 3 s of load, or as the first 2 screens are
scrolled (a scroll-timeline or view-timeline, or a class or style change on scroll, read after
each scroll step). It lasts 120 ms or more." Read as:

- An element of the first screen: its target box (above) overlaps the first viewport (0 to the
  width, 0 to the height) by more than 0.
- Offset: any of `offset-path`, `offset-distance`, `offset-rotate`, `offset-anchor` and
  `offset-position`.
- Starts within 3 s of load: first seen in the load step, and its active start (start time plus
  delay, on the document timeline) is at most 3,000 ms after the end of the load event.
- Starts as the first 2 screens are scrolled: first seen during a scroll step (a class or style
  change on scroll started it), or scroll-driven with a progress that is not the same after every
  scroll step (it moves with the scroll). A script that writes a style on every scroll event, with
  no animation or transition, makes nothing in `document.getAnimations()`, so it is not an
  animation here.
- Lasts 120 ms or more: its active duration (duration times iterations; infinite counts) is
  120 ms or more. A scroll-driven animation has no length in time; it lasts as long as the scroll,
  so its progress changing stands for it.

motion-feedback. "Every visible interactive element is checked: a[href], button, [role=button],
input, select, textarea and summary. Scroll each one into view. Hover it, wait past its transition,
and compare computed styles. If nothing changed, press (mouse down, read, mouse up). Met per element
when transform, box-shadow, filter, opacity or a colour property (color, background-color or
background-image, border-color, outline-color, text-decoration-color or text-decoration-line, fill,
stroke) differs. The row lists the elements without feedback." Read as:

- The elements: visible (as defined above), not `input[type=hidden]`, not disabled, not inside
  `[inert]`, in document order.
- For each: the mouse moves off the page (-20, -20); the element is scrolled to the viewport's
  centre; 2 animation frames; settle; the rest values are read.
- Hover: the mouse moves to the element's hover point, found as for hover states (its centre, or
  the first of its four inset corners where `elementFromPoint` is the element or inside it). An
  element with no such point is first given focus and its rest values are read focused; with none
  even then, it is "covered" and has no feedback. 2 frames; settle (every finite animation and
  transition is finished, so the reading is past its transition); the values are read.
- Press, only when the hover changed nothing: mouse down at the same point; 2 frames; settle; the
  values are read; mouse up. The click that follows is cancelled by a listener the meter adds
  before the page's own, so nothing navigates, submits or toggles. Then the element is blurred,
  and for a `select`, Escape closes its list.
- Compared, on the element, its descendant elements (the first 60) and their rendered `::before`
  and `::after`, as for hover states: `transform`, `translate`, `scale` and `rotate` (transform),
  `box-shadow`, `filter`, `opacity`, `color`, `background-color`, `background-image`, the four
  border colours (border-color), `outline-color`, `text-decoration-color`, `text-decoration-line`,
  `fill` and `stroke`. As for hover states, a property that draws nothing is not compared: a border
  side's colour only when its style is not none or hidden and its width is more than 0 in at least
  one of the two states; `outline-color` only when `outline-style` is not none and `outline-width`
  is more than 0 in at least one; `text-decoration-color` only when `text-decoration-line` is not
  none in at least one.

motion-timing. "Every transition and animation duration is 120-500 ms, with a non-linear timing
function. Infinite loops longer than 1000 ms are exempt. Delays are not counted. 0 s means none."
Read as:

- Every animation of the normal reading (load, scroll, hover and press).
- Its duration is one iteration's. 120 ms and 500 ms are inside the range. A duration of 0 is no
  animation and is not counted. A scroll-driven animation has no duration in time and is not
  counted here.
- An infinite loop longer than 1000 ms: infinite iterations and a duration of more than 1000 ms
  (a loop of exactly 1000 ms is not exempt).
- Linear: every timing function that applies to it (the effect's, and each keyframe's except the
  last) is linear, that is, its output equals its input at 0.1, 0.2, ... 0.9 within 0.001. So
  `linear`, `cubic-bezier(a, a, b, b)` and a `linear()` on the diagonal are linear; `ease`, other
  curves and `steps()` are not. (A CSS animation's timing function is on its keyframes; a CSS
  transition's is on its effect.)

motion-reduced. "Reload with prefers-reduced-motion: reduce emulated. Met when no animation or
transition changes transform, translate, scale, rotate, offset, position, size or scroll." Read as:

- Every animation of the reduced reading (the same load, scroll, hover and press).
- Offset: as above. Position: `top`, `right`, `bottom`, `left` and the `inset` properties, the
  margins, `background-position` and `object-position` (each moves a box or its picture). Size:
  `width`, `height`, `inline-size` and `block-size`, and their `min-` and `max-`. Scroll: smooth
  scrolling, read as an element whose computed `scroll-behavior` is `smooth`.
- Counted: an animation that changes one of these with a duration of 17 ms or more (under one
  frame at 60 Hz no step is drawn between its start and end, so nothing moves; the common reset
  `animation-duration: 0.01ms` lands here), or a scroll-driven one whose progress is not the same
  after every scroll step.
- Colour, opacity and blur (`filter`) may remain, because WCAG 2.3.3's Understanding defines
  motion animation as movement, not colour or opacity changes. The definition it quotes (WCAG 2.2,
  fetched 2026-10-20): "addition of steps between conditions to create the illusion of movement or
  to give a sense of a smooth transition", and "Motion animation does not include changes of color,
  blurring, or opacity which do not change the perceived size, shape, or position of the element."
  The page also lists an erratum, "Amending the definition to not exclude blurring"; blur stays
  allowed here, as decided, and a later version may follow the erratum.
- Video is not read here; A4's reduced-motion-video row reads it.

CLS: A8's `cls` row (412x823) is reported next to (d), unchanged. In `bars-interact.md` the A11
line is followed by its value and outcome. It is not a new row: its value, limit and pass are A8's
(BAR.md: "and A8's CLS still holds").

| check | bar | definition | limit |
|---|---|---|---|
| motion-signature | A11 | Signature animations, as above. Value: their number; met at 1 or more. Evidence: up to 5 (property: what they change; value: kind, name, duration and how they start, for example `animation rise 400 ms, load`). | one signature motion moment on the first screen (entrance or scroll-linked) |
| motion-feedback | A11 | Elements with no hover or press feedback. Value: their number; met at 0. Evidence: every one of them (value `no change on hover or press`, or `covered`). | hover or press feedback on every interactive element (transform, shadow or colour change) |
| motion-timing | A11 | Animations of the normal reading outside 120-500 ms, or linear, and not exempt. Value: their number; met at 0. Evidence: up to 5 (property: the animation name or transition property; value: kind, duration and timing function, for example `transition 800 ms ease`). | transitions 120-500 ms with easing, and nothing but loops longer than 1 s |
| motion-reduced | A11 | Animations of the reduced reading that move, plus elements with smooth scrolling. Value: their number; met at 0. Evidence: up to 5 (property: what moves; value: kind, name and duration, or `scroll-behavior smooth`). | all of it stops under prefers-reduced-motion |

Raw file: `phases[width]` gets `a11d` (the normal reading) and `a11d_reduced`, each
`{vw, vh, window_ms, steps, anims, feedback, smooth}`, or `{error}` when the reading failed; then its
rows are `null` (could not measure): the first three rows for the normal reading, motion-reduced
for the reduced one. Raw files from before version 4 have no such readings and are scored as
before, with no A11 rows.

## The fixture proof (bar-interact-v1, bar-interact-v2 and bar-interact-a11-v1)
`bar-interact-v1/expected.json` was written before the meter, with each page's exact failing
`(bar, check, width)` rows. `bar-interact-v2/expected.json` (five keyed cases for version 2's UI-part
reading) was written before version 2's code. `clean.html` meets every part-2 check; each planted page is
`clean.html` plus one plant, and between them they break every check at least once. The meter is
right only when its failing rows equal the key exactly on every page, in two runs, with identical
non-speed rows and the same pass or fail on every speed row in both runs. When they differ, the
meter is fixed, never the key.

`bar-interact-a11-v1/expected.json` (version 4's key) was written before version 4's code, and its
sha256 was sealed in `~/design-lab/seals/bar-interact-a11-v1.json` before the code too. Its
`clean-motion.html` meets every A11 (d) row; `static.html` (no motion at all) fails the signature
and feedback rows; every other page is `clean-motion.html` plus one plant, one plant per check,
with near-threshold pairs (110 against 120 ms, 500 against 520 ms, a 1000 against an 1100 ms loop)
and a page whose only signature is scroll-linked. A key may name the rows it covers (`checks`, a
list of `[bar, check]`): the A11 set covers only the four A11 (d) rows, and the older sets, which
name none, cover every row but A11's. Rows a key does not cover are left out of its comparison.
Version 4's proof: every page of the three sets matches its key in 3 of 3 runs, with the non-speed
rows byte-identical between runs, and the raw A11 readings (`a11d`, `a11d_reduced`) byte-identical
too. (The older normal-motion reading keeps the live transform values of running animations, so
that part of the raw file differs from run to run by design, as it has since version 1; its rows do
not.) The A11 set keys no speed row, so its repeat runs may use `--no-speed`; one full run with
speed is kept.

Since version 3 each page gets one of three verdicts:

- `match`: every row was measured, and the failing rows equal the key.
- `differ`: a row the key does not name failed (`extra`), or a row the key names was met
  (`missing`). A row that could not be measured is never counted as either.
- `could not measure`: no row differs from the key, but at least one row is `null`
  (`unmeasured`), so the page proves nothing either way.

The proof prints `MATCH set/page`, `DIFF  set/page  extra=[...] missing=[...]` or
`COULD NOT MEASURE set/page  rows=[...]: <reason>` for each page, then `fixture proof: M/N pages
match, D differ, C could not measure`. `fixture-proof.json` is `{all_match, match, differ,
could_not_measure, pages: [{set, page, match, verdict, extra, missing, unmeasured}]}`. Exit code: 0
when every page matches, 1 when any page differs, 3 when none differs but some could not be
measured.

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
- Until one of these exists, a worker run would score the speed rows `null` (could not measure;
  never met). Run speed on the host and merge the rows.

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

### Version 2, 2026-10-19 (Design, queue #96, H3c): UI-part contrast follows WCAG 1.4.11

Written before version 2's code, and before any page was measured with it. The decision and its
hypothesis are H3c in `~/design-lab/homepage-workflow/HYPOTHESES.md` (Design's home chat). Its five
keyed cases are in `bar-interact-v2/expected.json`, committed with this entry (8e5fb895), before the
code. No limit changed: ui-contrast's limit is still BAR.md A4's "UI parts and focus indicators meet 3:1",
and BAR.md's A4 is WCAG 2.2 AA. No other row's definition changed.

Reason: W3C's Understanding document for 1.4.11 (fetched 2026-10-19 from
w3.org/WAI/WCAG22/Understanding/non-text-contrast.html), section "Boundaries": a control with
visible text needs no contrasting boundary, and its Figures 1 and 30 pass text buttons with a faint
fill or none. What has to reach 3:1 is the visual information needed to identify the control: a
field's boundary, and the icon of a control with no text. Version 1 was stricter than BAR.md's words
in one place and looser in another. The first baseline run (`BASELINE-INTERACT.md`) showed both.

1. Controls with visible text (definition).
   - Old reading: every button whose fill differs from what is behind it, or that has a full
     border, was a UI part, and its fill or border had to reach 3:1 against what is behind it.
     Driftwatch v2.1r's red text button on its cobalt section (1.65:1) failed at 1440, and an
     ordinary white button on a pale section would fail the same way.
   - New reading: a control with visible text is identified by its text. Its fill and border are
     not measured; its label is part 1's text-contrast row. Keyed case: `text-button-faint.html`
     (a 1.60:1 fill, a readable label): met.
2. Controls with no visible text (definition and method).
   - Old reading: an icon-only button was judged by its fill or border, and its icon was never
     looked at. One with neither counted as having no boundary.
   - New reading: its icon contrast (see UI parts) must reach 3:1: the screenshot pixels inside the
     control that differ from its fill, and the contrast of the 90th-percentile one against the
     fill (or against what is behind, when there is no fill). Keyed cases: `icon-faint.html`
     (2.04:1): not met; `icon-ok.html` (3.75:1): met.
3. Links (definition).
   - Old reading: a link was a button candidate only when its box was 80 px tall or less. BAR.md
     has no such limit, and it hid Driftwatch's same red button at 390, where it is 122 px tall.
   - New reading: a link is a control when it has a fill that differs from what is behind it, or a
     full border, at any height. Keyed case: `tall-link-icon.html` (120 px tall, a full border, no
     text, a 1.48:1 icon): not met.
4. Fields: unchanged, by border or fill against what is behind them. Keyed case:
   `field-border-faint.html` (a 1.50:1 border): not met.

Old plants: none of bar-interact-v1's plants rests on the old reading, so none is re-planted and
its key is unchanged. Its only ui-contrast plant, `faint-input.html`, is a field (border `#e5e7eb`,
about 1.2:1), which version 2 reads as before. On its other pages every button has visible text,
and no link has a fill or a full border (the outlined "See how it works" has text).

Output: `version` becomes 2. Raw files measured before version 2 have no visible-text reading and
are scored as in version 1, so version 1's results can still be re-scored as they were.

Precisions written with this entry, beyond H3c's words, so that the reading is exact and
deterministic: what visible text is (screen-reader-only text and text pushed out of the box are
not); which pixels are inside (1 px in from the padding box and its rounded corners, so the box's
corners and border are never read as icon); the nearest-rank percentile; and the control with no
text and no icon, which keeps version 1's reading by its shape.

### Version 3, 2026-10-19 (Design, queue #110, H3d): speed rows measured only on a quiet machine

Written before version 3's code, and before any page was measured with it. The decision and its
hypothesis are H3d in `~/design-lab/homepage-workflow/HYPOTHESES.md` (Design's home chat). Its keyed
cases are the `test_h3d_*` tests in `tests/test_design_homepage_bar_interact.py`, committed with this
entry, before the code. They use a fake load reader, clock and Lighthouse run, so no case needs a
busy machine. No limit changed (A8: LCP 2,500 ms, CLS 0.1, TBT 200 ms), and neither did the three
runs, the median, the mobile preset or any other row.

Reason: in queue #96 (H3c), with the 1-minute load between 17 and 65 on this 20-core machine, TBT
failed on 1 to 8 of the 18 unplanted fixture pages per run (up to 536 ms, against 0 to 64 ms on a
quiet machine) and on 2 baseline pages, one of them with LCP too (2,253 -> 2,532 ms). The median of
three runs did not absorb it; runs were clean only behind a gate (1-minute load under 6). A busy
machine made the meter fail good pages, and W15 needs every A bar met on every proof page.

1. Quiet machine (method): the gate in "Speed". The 1-minute load is read before and after each
   run; the meter waits in 15 s steps while it is 6 or more; a run whose after-reading is 6 or more
   is thrown away and redone; each page has a cap of 600 s.
2. Could not measure (definition): when the cap passes before three quiet runs are in, the three
   speed rows are `null`, with the reason `could not measure: machine busy (load X)`. They are
   never met or not met, and they are counted apart in `bars-interact.md` and in the fixture proof
   (see the output contract and the fixture proof). The fixture proof's exit code 3 is new.
3. Raw file (output): each run carries `load_before` and `load_after`; `dropped` keeps the runs
   thrown away; `gate` keeps the waits.

Precisions written with this entry, beyond H3d's words: the cap is checked before each wait and
each run, so a run under way finishes, and a page's speed step takes at most 600 s plus one run; X is
the last reading of 6 or more, to two decimals; the load is the whole machine's, the meter's own
Lighthouse and Chrome included; a Lighthouse error still ends the step as before; raw files measured
before version 3 have no loads and are scored as before. `version` becomes 3.

### Version 4, 2026-10-20 (Design, queue #113): A11 (d), motion with a purpose

Written before version 4's code, and before any page was measured with it. This is a new
measurement, not an improvement: the owner asked on 2026-10-19 for pages that are modern and
dynamic, BAR.md row A11 measures it, and `~/design-lab/homepage-workflow/HYPOTHESES.md` ("A11
meter") says it gets a proof instead of a hypothesis. The numbers BAR.md's (d) leaves open were set
by Design (home), not the owner, in the plan for #113. Its key is
`bar-interact-a11-v1/expected.json`, committed with this entry and sealed (its sha256) in
`~/design-lab/seals/bar-interact-a11-v1.json` before the code. The meter is fixed to the key, never
the key to the meter; a new key would be `bar-interact-a11-v2`.

1. Four new rows, bar A11, at 1440x900 and 390x844, after the speed rows: motion-signature,
   motion-feedback, motion-timing and motion-reduced (see "Motion with a purpose"). No older row,
   limit or method changed: the two new readings run after every older phase of both widths, and
   A8's CLS row is only reported next to them.
2. Raw file (output): `phases[width]` gets `a11d` and `a11d_reduced`. Raw files measured before
   version 4 have neither, and are scored as before, with no A11 rows.
3. Fixture proof (method): a key may name the rows it covers (`checks`); the older keys, which name
   none, cover every row but A11's, so their comparison is unchanged. `--set NAME` limits the proof
   to the named sets (repeatable). Version 4's proof is 3 of 3 runs (see "The fixture proof").

Precisions written with this entry, beyond the plan's words, so that the reading is exact and
deterministic: the first screen is the target's layout box at scroll 0 (an entrance's own transform
does not move it out); offset is the five `offset-*` properties; one animation is one (kind, target,
pseudo-element, name, duration, timing function); a scroll-driven animation stands in for "lasts
120 ms" by moving with the scroll, and is not timed; linear is checked numerically at nine points;
position and size are the properties listed under motion-reduced; smooth scrolling is the computed
`scroll-behavior`; an animation under 17 ms moves nothing that is drawn; feedback compares the same
nodes, and gates the same properties, as hover states; the click after a press is cancelled; and
evidence is the selector, the property and the value per element and width. `version` becomes 4.
