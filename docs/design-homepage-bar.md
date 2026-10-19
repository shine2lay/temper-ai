# design_homepage_bar: the homepage A-bar meter, part 1 (Design, queue #78)

The meter measures one built homepage against the script-measurable A bars of
`~/design-lab/homepage-workflow/BAR.md`. It uses no model (AGENTS rule 17). Part 1 measures the
page as it loads. Part 2 (a separate task) adds keyboard, focus, hover, reduced motion and speed
and writes the same row format.

- `configs/design/bin/design_homepage_bar.js`: one in-page function expression. It returns raw
  measurements only, with no limits in it.
- `configs/design/bin/design_homepage_bar.py`: the browser driver, the pure scorer (raw JSON to
  rows, where every limit is applied) and the CLI.
- `configs/design/testpages/bar-v1/`: fixture pages with a known key (`expected.json`), the fixture
  brief, the frozen `verbs.txt` and `placeholders.txt`, and the recorded `raw/*.json`.
- `configs/design/testpages/bar-v2/`: version 2's keyed cases (`expected.json`, committed before the
  version 2 code), their briefs (`brief.json`, `brief-rooms.json`), two `derivations.json` cases and
  the recorded `raw/*.json`.
- `tests/test_design_homepage_bar.py`: the scorer on every recorded raw file must give exactly the
  key, plus unit tests. No browser in the tests.

Written 2026-10-18, before any real page was measured. After the first real page is measured, a
definition changes only with a dated reason written here, and never to make a page pass. Limits
are BAR.md's, word for word; the meter never changes a limit.

Version 2 (2026-10-19, queue #91, H3b) changed six definitions after the first real pages were
measured. Each change, its reason, and the old and new readings are under "Changes to definitions".
The tables below give the version 2 definitions. No limit changed.

## Running it

```
design_homepage_bar.py --site DIR [--page index.html] --brief brief.json --out DIR \
    [--browser URL] [--serve-host HOST] [--raw-only | --from-raw DIR]
design_homepage_bar.py --fixture-proof --out DIR [--record] [--browser URL] [--serve-host HOST]
```

- The browser is temper's playwright-mcp service (default `http://playwright-mcp:8931/mcp`; from
  the host use `--browser http://127.0.0.1:8931/mcp --serve-host <the container's address>`).
  The site folder is served over HTTP by `design_capture.serve`, at this machine's address on the
  route to `--serve-host` (default: the browser's host name).
- `--out DIR` gets `raw.json` (the measurements), `bars.json` and `bars.md`.
  `--raw-only` stops after `raw.json`; `--from-raw DIR` scores `DIR/raw.json` with no browser.
- `--fixture-proof` measures every page of both keys and compares each page's failing rows with its
  key (exact set equality). bar-v1 pages are held to `bar-v1/expected.json` on the version 1 checks,
  and to the `bar-v1` section of `bar-v2/expected.json` on the two version 2 rows. Each `bar-v2` case
  is held to its failing set and its keyed rows. `--record` also saves each raw file to `bar-v1/raw/`
  and `bar-v2/raw/`.
- When the page's folder holds `derivations.json`, `raw.json` carries it, with its sha256 (A5 numbers).

## Output contract (shared with part 2)

`bars.json`:
`{meter, version, page, page_sha256, brief, widths, rows: [{bar, check, width, value, limit, pass, evidence}]}`

- `meter` is `design_homepage_bar`; `version` is the meter's version (`2`). Version 2 only added
  rows (A5 cta-wording, A7 word-split). No row was renamed or removed.
- `page` is the page's path; `page_sha256` is the sha256 of its HTML file; `brief` is the brief's path.
- `widths`: `["1440x900", "1024x768", "768x1024", "390x844", "320x568"]`.
- `width` in a row is one of those, or `all` for a check made once over the whole page.
- `pass` is `true`, `false` or `null`. `null` means "could not measure", and it counts as not met.
- `evidence`: up to 5 items `{selector, text (80 characters or fewer), box: [x, y, w, h]}`, page
  coordinates in CSS px.
- Rows come in a fixed order (bar, check, width), and the file has no timestamps, so two runs of
  the same page give byte-identical files.

`bars.md` has the table `bar | check | width | value | limit | pass` and a summary per bar. A bar is
met only when every one of its rows passes.

## How a page is loaded and what counts as visible

- Widths: 1440x900, 1024x768, 768x1024, 390x844 and 320x568 (BAR.md A: "Measured by script at
  1440x900, 1024x768, 768x1024, 390x844 and 320 wide").
- At each width: set the viewport, open the page, wait for network idle and
  `document.fonts.ready`. Then every finite CSS animation or transition is finished
  (`Animation.finish()`) and every infinite one is paused at its start, so the page is measured at
  rest and two runs agree. Measured at scroll 0, light colour scheme.
- First viewport: the top 900 px at 1440 and the top 844 px at 390, after the above. Checks that use
  it run at those two widths.
- Visible element: it has a box larger than 0x0, it is not `display: none`, `visibility: hidden` or
  `opacity: 0`, and some of it survives clipping. Clipping is the intersection of the boxes of the
  element and its ancestors that have non-visible overflow on that axis, or a `clip` or `clip-path`.
  So screen-reader-only text (clipped to 1 px) is not visible text.
- Text element: an element with its own non-blank text node, outside `svg`, `script`, `style`,
  `noscript` and `template`. Its line boxes are the Range client rects of its own text nodes, after
  clipping. A text element is in the first viewport when the vertical centre of one of its line
  boxes lies inside it.
- Sections: the page header (the first `header` or `[role=banner]` outside main and articles), each
  element child of `main` (or `[role=main]`), and the page footer (the first `footer` or
  `[role=contentinfo]` outside main and articles), in document order. A page without `main` uses the
  body's element children.
- Composited colour: the text colour blended over the background colours behind it, rounded to
  whole RGB values (as design_measure.js does).
- Controls: visible `a[href]`, `button`, `[role=button]` and `input` of type submit, button or reset.
  A control's text is its whitespace-normalised `innerText` (an input's value).
- Solid button: an `a`, `button` or `[role=button]` whose background colour is fully opaque and has
  3:1 or more against the composited background behind it.
- CTA wording is compared after normalising: lower case, whitespace collapsed, arrows (`↓ → › >`)
  removed at either end, and trailing `… . !` removed.
- Primary CTA (at each width), picked by the first rule that finds one:
  1. "brief wording": the first visible control whose wording equals the brief's `cta` and whose
     vertical centre is in the first viewport;
  2. "most prominent filled button in the first screen": the solid button with the largest area
     among those whose vertical centre is in the first viewport;
  3. "brief wording, outside the first screen": the first control on the page whose wording matches;
  4. "largest filled button on the page": the solid button with the largest area.
  If none of them finds one, there is none. The rule that picked it is evidence (`(picked by)`).
- Reused, unchanged: `design_capture.serve` and its result reader; axe-core 4.13.0 with
  design_capture's `AXE_TAGS` (wcag2a, wcag2aa, wcag21a, wcag21aa, wcag22aa), violations only;
  `design_measure.js` (text contrast, WCAG 2.5.8 target geometry); `design_page_checks`
  (text over an image, a gradient or a translucent layer: contrast from the pixels behind it).

## The checks

Each check names its BAR.md source line. "Widths" says where it runs: 5 = every width,
2 = 1440 and 390, 1440 = only there, all = once over the page.

### A1, first screen
BAR.md A1: "at 1440 and 390 the first viewport shows the product name, a value headline of 12 words
or fewer, one fully visible primary call to action, and at least one visual anchor (illustration,
product picture or diagram), from DOM boxes."

| check | widths | definition | limit |
|---|---|---|---|
| product-name | 2 | The brief's product name appears in the visible text of the first viewport or in the alt of an img that is in it. The text is the text elements in the first viewport joined in order; the match ignores case and whitespace. | product name in the first viewport |
| h1-words | 2 | The first rendered h1 has 12 words or fewer (words: runs of non-space characters). No h1 fails. | 12 words or fewer |
| cta-in-view | 2 | The primary CTA's box lies wholly inside the first viewport (0 to the width, 0 to 900 or 844). No primary CTA fails. Evidence: the CTA and the rule that picked it. | one fully visible primary call to action |
| visual-anchor | 2 | At least one anchor is at least 120x120 px at 1440 (96x96 at 390), after clipping, and has at least 50% of its area inside the first viewport. An anchor is a visible img, svg (outermost), video, canvas or element with a CSS `background-image: url(...)` (not html or body), or a picture built in HTML. An HTML picture is an element (not img or svg) exposed as an image: role=img with a non-empty name (aria-labelledby, aria-label or title), or a figure (no role, or role=figure) with a non-empty figcaption child or aria-labelledby name, not inside `aria-hidden="true"`. At least a third of its visible box must be painted by its descendants' non-text boxes, counted on a 4 px grid of cell centres. Painting boxes are svg, img, canvas and video; an element with a background image; an element whose background colour differs from the colour behind it; and visible borders (all four: the whole box; else the border strips). The picture's own background and border don't paint. An anchor counts once. Gradients alone and type alone are not anchors. When none counts, evidence names each HTML picture in the first viewport and why. | at least one visual anchor |

### A2, hierarchy
BAR.md A2: "H1 used once and is the largest text on the first screen; one solid primary button per
viewport; every font size from one declared scale of 7 steps or fewer; at most 4 text sizes and 3
text-contrast levels per section; at least 90% of spacing values on the 4-px grid; the gap between
sections is at least 2x the median gap inside a section."

| check | widths | definition | limit |
|---|---|---|---|
| one-h1 | 2 | The number of rendered h1 elements (not `display: none`, `visibility: hidden` or `aria-hidden`; a clipped h1 counts). | exactly 1 |
| h1-largest | 2 | The first rendered h1 is in the first viewport, and no text element in the first viewport outside it has a larger font size. | H1 is the largest text on the first screen |
| primary-per-window | 5 | Primary style is the primary CTA's background colour; a solid button is primary-style when its background is within OKLab distance 0.02 of it. Windows are one viewport high, starting at 0 and stepping half a viewport, until a window starts below the page. A button is in a window when its vertical centre is. Value: the most primary-style buttons in one window. No primary CTA, or one that is not solid: 0. | 1 or fewer per viewport |
| font-sizes | 5 | Distinct font sizes of visible text elements, rounded to 0.5 px. | 7 or fewer |
| section-sizes | 5 | In each section, distinct font sizes (0.5 px) of its visible text elements, leaving out text inside solid buttons. Value: the highest section. | 4 or fewer per section |
| section-colours | 5 | In each section, distinct composited text colours of its visible text elements, leaving out text inside solid buttons. Value: the highest section. | 3 or fewer per section |
| spacing-grid | 5 | Over every visible element (not inside svg, larger than 1x1): its margin and padding on each side, and its row and column gap when it is a flex or grid box. Values given as a keyword (`auto`, `normal`) are skipped, so auto margins don't count; the rest are taken from the computed style in px, and 0 is skipped. The share of values within 0.5 px of a multiple of 4 (absolute value). | 90% or more |
| rhythm | 2 | Content boxes: text elements (the union of their line boxes), img, svg, video, canvas, background-image elements and form controls, at least 2x2 px after clipping. In each section, sorted by top: an inside gap is the space between a box and the lowest bottom above it, when positive. The page's median inside gap pools every section. A gap between sections runs from the lowest bottom of one section's boxes to the highest top of the next section's (sections without boxes are skipped). The gap under the page header is skipped: the page header is the banner (role=banner, or a header without a role that is not inside article, aside, main, nav or section). Its inside gaps still count. Every other gap between sections must be at least 2x the median. | at least 2x the median gap inside a section |

### A3, readability
BAR.md A3: "body text at least 16 px at every width; body line height 1.2-1.5; at least 90% of body
paragraphs 45-90 characters per line at 1440; body copy at Flesch-Kincaid grade 9 or below."

Body text: a visible p, li, dd or blockquote of 8 or more words (its `innerText` split on
whitespace), not inside `nav`, `footer`, `[role=navigation]` or `[role=contentinfo]`.

| check | widths | definition | limit |
|---|---|---|---|
| body-size | 5 | The smallest font size of any body text element. No body text: met. | 16 px or more |
| line-height | 5 | Line height over font size for each body text element: computed line height in px over font size; for `normal`, the element's content height divided by its number of lines. Every element must be in range (inclusive). | 1.2 to 1.5 |
| measure | 1440 | Running text only. Each character of a body text element (Range client rect wider and taller than 0) belongs to its block. The block is the nearest element from the character's parent up to the body text element whose display is not inline-level (`inline*` or `contents`), else the body text element. A block's characters are grouped into lines by vertical centre. A block is running text when it has 2 or more lines, or 60 or more characters. A block's value is the average count over its full lines (all but the last); a one-line block uses its one line. Value: the share of running blocks averaging 45 to 90 (inclusive). None: met ("no running text"). | 90% or more |
| fk-grade | 1440 | Flesch-Kincaid grade of all body text joined: 0.39 x words per sentence + 11.8 x syllables per word - 15.59. Sentences end at `.`, `!` or `?` followed by a space or the end, and each element ends one. Words are runs of letters, digits and apostrophes with a letter or digit. Syllables: the built-in rule below. No body text: could not measure. | grade 9 or below |

The syllable rule (unit-tested): lowercase the word and keep letters only; a word without letters
(a number) is 1 syllable; 3 letters or fewer is 1. Otherwise drop a final `es`, `ed` or `e`, but
not `le` after a consonant (table) or `ee`/`ye`; count the groups of vowels (`aeiouy`); at least 1.

### A4, accessibility (the static parts)
BAR.md A4: "axe shows 0 violations (any impact) at 1440 and 390; every text node meets 4.5:1 (3:1
large) against its computed background, including over images; ... targets are 24x24 or spaced
(2.5.8); ... reflow at 320 with no horizontal scroll at any width (1.4.10); ... one h1, no skipped
heading levels, landmarks, lang set, every meaningful image has alt and every decorative one is
hidden." Keyboard, focus, focus-indicator contrast and reduced motion are part 2.

| check | widths | definition | limit |
|---|---|---|---|
| axe | 2 | axe-core 4.13.0 violations with design_capture's AXE_TAGS, any impact. | 0 violations |
| text-contrast | 5 | Text that design_measure.js finds under its need (4.5:1, or 3:1 for large text, inactive controls exempt), except text that design_page_checks finds over an image, gradient or translucent layer; that text is judged by the contrast measured from the pixels behind it instead. If design_measure's list is full (25) and every item was replaced by a pixel result, could not measure. | every text node meets 4.5:1 (3:1 large), including over images |
| targets | 5 | design_measure.js's targets that fail WCAG 2.5.8 by size and by spacing (its targetGeometry). | 24x24 or spaced (2.5.8) |
| no-hscroll | 5 | `document.documentElement.scrollWidth` against `innerWidth`. | no horizontal scroll at any width |
| headings | 2 | Rendered headings h1-h6 (as in one-h1, clipped ones count): exactly one h1, and no heading more than one level deeper than the one before it (the first may be any level). | one h1, no skipped heading levels |
| landmarks | 2 | Rendered `main` or `[role=main]`; `header`, `[role=banner]`, `nav` or `[role=navigation]`; and `footer` or `[role=contentinfo]`. | landmarks |
| lang | 2 | `<html lang>` is set and not blank. | lang set |
| img-alt | 2 | Every img element in the document has an alt attribute (alt="" marks a decorative one). | every meaningful image has alt |
| svg-names | 2 | Every rendered outermost svg whose longer side is 48 px or more either has role=img and a name (aria-label, aria-labelledby or a title child), or has aria-hidden="true" on itself or an ancestor. | every decorative one is hidden |

### A5, words (the script parts)
BAR.md A5: "every factual claim maps to a brief fact (script claim list; ...); 0 unsourced claims; call
to action 40 characters or fewer, starting with a verb; fictional products carry the disclosure
line; no placeholder text." The content critic's reading of meaning is not part of this meter.

Page text: `document.body.innerText` at each width (it includes clipped screen-reader text). The
checks run once (`all`) over the page.

| check | widths | definition | limit |
|---|---|---|---|
| cta-length | all | The primary CTA's text at 1440 (else at 390): its length in characters. No primary CTA: could not measure. | 40 characters or fewer |
| cta-verb | all | The CTA's first word (lowercase, letters only) is in `bar-v1/verbs.txt`, a frozen list of imperative verbs written before any real page was measured. | starting with a verb |
| disclosure | all | For a brief with `"fictional": true`, the brief's `disclosure` appears verbatim (whitespace normalised, case kept) in the page text at every width. Not fictional: met. | fictional products carry the disclosure line |
| placeholders | all | No line of page text, at any width, matches a pattern of `bar-v1/placeholders.txt`, a frozen list of regular expressions (lorem ipsum, to-do markers, double-brace template tags, example.com and the like). | no placeholder text |
| numbers | all | Number tokens: an optional `$`, `£` or `€`, digits with optional `,000` groups and decimals, and an optional `%`, `x`, `×` or `k` right after (not followed by a letter). A page token is sourced when the brief's facts hold a token with the same number (commas dropped), and, if the page token has a currency or suffix mark, the same mark. The facts' number words (zero to nineteen, the tens, and compounds such as twenty-one; "one-hour" gives 1) count as plain numbers. Exempt: the disclosure line, and years 1900-2099 inside the footer's text. Not claims, so taken out of the page text: step labels, and the rendered text of pictures exposed as an image (each number taken out removes one page number written the same way). A step label is the 1-2 digit number (`1`, `01`) that starts the first rendered text of each item in a run of 2 or more sibling elements numbered 1, 2, 3 ... in order; an ol's markers are never in the page text. A picture is exposed as an image by the test in A1 visual-anchor, or by being an svg with role=img and a name (an img's pixels are never page text). The picture's accessible name is checked as text instead. A number worked out from brief facts is sourced only by an entry `{shown, operation, operands, facts}` in the page folder's `derivations.json`. Every listed fact must be a brief fact word for word, and each operand a number one of them holds, with the same marks. The shown number's marks must be on an operand. Recomputing left to right (add, subtract, multiply or divide) must give exactly the shown number. Over the union of page text at all widths. Evidence: each unsourced number, or a way it could be worked out from a fact (`$36 = 2 x $18`), and why a listed derivation was rejected. | 0 unsourced claims |
| cta-wording | all | The primary CTA at 1440 (else at 390). Its wording, normalised, equals the brief's `cta`, normalised. Value: its text. No primary CTA, or a brief without a `cta`: could not measure. Evidence: the CTA, the rule that picked it, and the brief's wording. | the brief's call to action, normalised |

### A7, built to last (layout)
BAR.md A7: "no text box overlaps another; no clipped text (scrollWidth > clientWidth on text = 0)".
Hover, focus and motion are part 2.

| check | widths | definition | limit |
|---|---|---|---|
| overlap | 5 | Each line box of a text element is cut to its glyph band (the middle 0.7 em of the line box, or all of it if smaller) and clipped. Two text elements overlap when some band of one overlaps some band of the other by more than 2 px on both axes, unless one element contains the other. Value: the number of overlapping pairs. | no text box overlaps another |
| clipped | 5 | Elements other than html and body, visible and larger than 1x1, with non-visible overflow on an axis whose scroll size exceeds the client size by more than 1 px, where the overflow is text: the element has its own text, or a line box of a text element inside it reaches more than 1 px past its client box. Also an active ellipsis: `text-overflow: ellipsis` with scrollWidth over clientWidth by 1 px or more. | no clipped text |
| word-split | 5 | Words: runs of letters, marks and digits of 2 or more characters in one text node of a visible element, outside svg, script, style, noscript and template, and not in a script written without spaces (Han, Hiragana, Katakana, Thai, Lao, Khmer, Myanmar). A word is split when its Range boxes sit on 2 or more lines and, at a break between two of its characters, no hyphen is drawn. A hyphen is drawn when the word's box on the earlier line reaches 1 px or more past its last glyph there, as a soft hyphen or `hyphens: auto` does. Value: the number of split words. Evidence: each word with ` / ` at the break. Raw files from before version 2: not measured. | no word split across two lines without a hyphen |

## Not in part 1
A6 (model) and A10 (blind read); A9 (the converter's verify); keyboard, focus, focus-indicator
contrast, hover, reduced motion and speed (part 2); Design's manual WCAG pass (hand).

## The fixture proof (bar-v1)
`bar-v1/expected.json` was written before the meter, with each page's exact failing
`(bar, check, width)` rows: `clean.html` meets every part-1 check at all five widths; the planted
pages between them break every part-1 check at least once. The meter is right only when its
failing rows equal the key exactly on every page, in two runs, and its two `bars.json` files are
byte-identical. When they differ, the meter is fixed, never the key.

Two fixture pages were corrected after the key was committed (2026-10-18, before any real page was
measured), so that each page is what the key says it is; the key itself never changed:

- `base.css` (so `clean.html`): the footer's top padding went from 32 to 48 px. The band-to-footer
  gap was 34 px against a median inside gap of 18.4 px, below 2x, so the "clean" page really broke
  A2 rhythm at 1440 and 390.
- `p-access.html`: the footer links' rows were set to 16 px with line height 1. The planted
  undersized links were 24 px or more apart from centre to centre, so they passed 2.5.8 by spacing
  and the plant did not break A4 targets as the key says.

Result: both proof runs (2026-10-18) matched the key exactly on all 7 pages, and every page's
`bars.json` and `raw.json` were byte-identical between the runs.

Version 2's keyed cases are in `bar-v2/expected.json`. The key was committed on 2026-10-19 (67c2c789),
before the version 2 code. It has 13 cases, at least one per change:

- (a) step labels and number words;
- (b) one unsourced price;
- (c) a derived sum, with a right and a wrong `derivations.json`;
- (d) an HTML mock as role=img and as a figure;
- (e) the same mock unlabelled;
- (f) a role=img around numerals only;
- (g) a CTA with an arrow;
- (h) a hero CTA with other words;
- (i) a header flush on the hero;
- (j) split-flap cells;
- (k) a word broken at 320.

Its `bar-v1` section keys the two new rows on the seven bar-v1 pages. Only `p-structure.html` fails
one: cta-wording, because its only filled button, "Our ledger keeps every household bill sorted for
you", is not the brief's "Start a free ledger".

Result: both version 2 proof runs (2026-10-19) matched both keys exactly on all 20 pages (7 bar-v1,
13 bar-v2). `bar-v1/expected.json` kept its sha256 (05436368...). Every page's `bars.json` and
`raw.json` were byte-identical between the runs.

## Changes to definitions

### Version 2, 2026-10-19 (Design, queue #91, H3b)

The first real pages were measured with version 1 on 2026-10-18
(`~/design-lab/results/homepage-bar-baseline/BASELINE.md`). Its notes 1-6 found six places where the
meter read BAR.md's words wrongly. Each change below is Design's decision (home chat, H3b in
`~/design-lab/homepage-workflow/HYPOTHESES.md`). Its keyed case in `bar-v2/expected.json` was
committed (67c2c789) before its code, and no definition was tuned to the baseline pages. No bar and
no limit changed. The output gained two rows and lost or renamed none. bar-v1's key is unchanged and
still matches. Re-measured baseline: `BASELINE-v2.md`, next to BASELINE.md. Raw files measured before
version 2 (no claims, HTML pictures, banner flag, text blocks or word boxes) are scored as in version 1,
and their word-split rows read "not measured".

1. A5 numbers: what counts as a claim (note 1).
   - Reason: BAR.md A5, "every factual claim maps to a brief fact". A step's ordinal labels the step
     and claims nothing. "one-hour" in the brief and "1 hour" on the page are the same fact. Numerals
     drawn inside a picture belong to the picture (rule 2's test); what the picture claims is its
     accessible name. A number worked out from brief facts maps to them only when the working is
     written down and checks out.
   - Old reading: every number in the page text was a claim. bar-v2 `a-steps.html` had 8 unsourced
     numbers: the step labels 01, 02, 03 and 1, 2, 3, plus "7 days" and "10 years" against the
     brief's "seven days" and "ten-year". $10 = $4 + $6 was unsourced with no way to source it.
   - New reading: step labels and pictures' numerals are taken out, and the pictures' names are
     checked. Fact number words source plain numbers. A derived number is sourced by a
     `derivations.json` entry that recomputes exactly. `a-steps.html` has 0. The evidence offers a
     possible derivation, such as `$10 = $4 + $6`.
2. A1 visual anchor: pictures built in HTML (note 2).
   - Reason: BAR.md A1, "at least one visual anchor (illustration, product picture or diagram), from
     DOM boxes". A product picture built from DOM boxes is an anchor when it is exposed as an image
     (rule 2's test, WCAG 1.1.1) and is mostly painted, not type.
   - Old reading: only img, svg, video, canvas and url() backgrounds counted. A labelled HTML mock of
     the product, or a figure with a caption around a sample report, was not an anchor.
   - New reading: such a picture counts when a third or more of its box is painted, under the same
     size and first-screen rule. Unlabelled, it does not count, and the evidence says it is not
     exposed as an image. A role=img wrapper around big numerals is painted 0% and does not count.
3. A1 call to action: which button is the primary one (note 3).
   - Reason: BAR.md A1, "one fully visible primary call to action". The primary call to action is the
     first screen's main button, and an arrow or a trailing mark does not change its words.
   - Old reading: an exact text match. "Explore demo rooms ↓" did not match the brief's "Explore
     demo rooms", so the meter measured the closing button 5,000 px down, and cta-in-view failed.
   - New reading: the match is made after normalising. When nothing in the first screen matches,
     the most prominent filled button there is measured. A new A5 row, cta-wording, fails when that
     button's words differ from the brief's, so the switch is never silent. The evidence names the rule.
4. A2 rhythm: the gap under the page header (note 4).
   - Reason: BAR.md A2, "the gap between sections is at least 2x the median gap inside a section".
     The page header is the banner landmark, not a section of content, and a header that sits on the
     hero is a layout choice, not crowding. Every rhythm row that failed in the baseline failed on
     this gap.
   - Old reading: the gap between the header and the first section was a section gap.
   - New reading: that one gap is skipped. Every other gap stays, and so do the header's inside gaps.
5. A3 measure: running text only (note 5).
   - Reason: BAR.md A3, "at least 90% of body paragraphs 45-90 characters per line at 1440". Line
     length is a measure of running text (Practical Typography: 45-90 characters per line). Labels and
     one-character cells have no line length.
   - Old reading: all of a body element's characters counted as one paragraph. So a row of
     split-flap cells, one letter each, or a dd of sums read 8-18 characters per line.
   - New reading: characters are grouped by their block (the nearest element that is not
     inline-level). A block counts only when it is running text: 2 or more lines, or 60 or more
     characters.
6. A7 word-split, a new row (note 6).
   - Reason: A7 ("built to last") holds the layout's text intact, next to overlap and clipped text. A
     word broken without a hyphen reads as two words: "CEDA / R" on Morrow Rooms at 320.
   - New reading: at every width, no word may be split across two lines unless a hyphen is drawn
     at the break. Word boxes come from Range client rects.
