/**
 * The free-flowing Team page's words and states outside the map (Design's
 * rows D8, D9 and D35-D77), on Temper's final serializer replies (flow/real)
 * and the states derived from them (flow/derived). Every /api/team answer
 * comes from them, so no Temper is needed and nothing is written.
 *
 * Happy path first, as the owner's test rule asks (bp-be8d76b9): a working
 * team read at a glance in both themes at 390x844, 1024x768 and 1440x900,
 * then 320 px (reflow). Now names who works on what, You and Spend say what
 * they mean, the cards put role and leader under the name, Latest says "...
 * ago" and All activity tells the time to the second; with axe, 24 px
 * targets, 14 px header buttons, no text under 14 px and no sideways
 * scroll; on a phone the band ends on the first screen.
 * Then contract points only: a member's own long question (named, cut in
 * the band, whole with Temper's note in the answer view), the phone band in
 * every state Temper can be in, a usage check that can't be read, ended
 * runs, and a page whose Temper stops answering.
 */
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { expect, test, type Locator, type Page } from '@playwright/test';
import { STATUS_ICONS } from '../src/lib/constants';
import { expectAxeClean, expectTargets, glanceFontsSettled, nothingSent, serveActions, serveTeam, type Fixture } from './team-helpers';

type Raw = Record<string, unknown>;
type Feed = { events: Raw[]; as_of: string };

const FLOW_DIR = path.join(process.cwd(), 'e2e/fixtures/team/flow');

/** A flow reply as Temper sent it (real) or as derived from one (derived), as a fresh copy. */
function flowRaw(name: string, feed = false): Raw {
  for (const dir of ['real', 'derived']) {
    const file = path.join(FLOW_DIR, dir, `${name}${feed ? '-events' : ''}.json`);
    if (existsSync(file)) return JSON.parse(readFileSync(file, 'utf8')) as Raw;
  }
  throw new Error(`no flow fixture ${name}`);
}

/** Every state there is a reply for, real and derived. */
const STATES = ['real', 'derived']
  .flatMap((dir) => readdirSync(path.join(FLOW_DIR, dir)))
  .filter((f) => f.endsWith('.json') && !f.endsWith('-events.json'))
  .map((f) => f.slice(0, -'.json'.length))
  .sort();

const ENDED = new Set(['done', 'stopped', 'failed', 'interrupted']);
const phaseOf = (name: string) => (flowRaw(name).phase as { name: string }).name;

/** A contract test's change to the run or its feed (applied to fresh copies at each read). */
interface Change {
  run?: (run: Raw) => void;
  feed?: (feed: Feed) => void;
}

/**
 * Temper for one page, at one state: the run reads as that state (or, once
 * `down`, Temper doesn't answer); the feed answers what is past `after`, up
 * to the run's own events_cursor. Answers and messages are kept, not sent.
 */
async function serveState(page: Page, name: string, change: Change = {}) {
  const state = { down: false };
  const sent = nothingSent();
  const run = (): Fixture => {
    if (state.down) return { route: '', status: 503, body: { detail: 'Temper is not answering' } };
    const body = flowRaw(name);
    change.run?.(body);
    return { route: '', status: 200, body };
  };
  await serveTeam(page, { run });
  await serveActions(page, sent, {});
  // Set up after serveTeam, so it answers the feed first.
  await page.route(/\/api\/team\/runs\/[^/]+\/events(\?|$)/, async (route) => {
    const url = new URL(route.request().url());
    const after = Number(url.searchParams.get('after') ?? '0');
    const limit = Number(url.searchParams.get('limit') ?? '200');
    const upTo = flowRaw(name).events_cursor as number;
    const feed = flowRaw(name, true) as unknown as Feed;
    change.feed?.(feed);
    const past = feed.events.filter((e) => (e.seq as number) > after && (e.seq as number) <= upTo);
    const shown = past.slice(0, limit);
    const more = past.length > shown.length;
    const cursor = more ? (shown[shown.length - 1].seq as number) : Math.max(after, upTo);
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ events: shown, cursor, more, as_of: feed.as_of }),
    });
  });
  return { state, sent };
}

/** Open one state at its own id, the page's clock pinned to Temper's as_of, its history read. */
async function open(page: Page, name: string, change?: Change) {
  const run = flowRaw(name);
  await page.clock.setFixedTime(new Date(run.as_of as string));
  const served = await serveState(page, name, change);
  await page.goto(`/app/team/runs/${run.execution_id as string}`);
  await expect(page.getByTestId('glance-page')).toBeVisible();
  await expect(page.getByTestId('glance-just-sent')).not.toContainText('Reading the team');
  await glanceFontsSettled(page);
  return served;
}

const nowWord = (page: Page) => page.getByTestId('glance-now-word');
const nowSentence = (page: Page) => page.getByTestId('glance-now-sentence');
const youTitle = (page: Page) => page.getByTestId('glance-you-title');
const activity = (page: Page) => page.getByRole('region', { name: 'All activity' });
// The header's Stop (You's own stop, D92, reads "Stop project" too).
const stopButton = (page: Page) => page.getByRole('main').locator('header').getByRole('button', { name: 'Stop project' });

/** Where the status band ends, in CSS px from the top of the window (D9: at most 844 on a 390x844 phone). */
const bandEnd = (page: Page) =>
  page.getByTestId('glance-band').evaluate((band) => Math.round(band.getBoundingClientRect().bottom * 10) / 10);

async function boxOf(locator: Locator) {
  const box = await locator.boundingBox();
  if (!box) throw new Error('not drawn');
  return box;
}

/** Nothing scrolls sideways: not the window, not the page column. */
async function expectNoSideways(page: Page) {
  const wide = await page.evaluate(() => {
    const out: string[] = [];
    const boxes = [document.scrollingElement, ...Array.from(document.querySelectorAll('main, [data-testid="glance-page"]'))];
    for (const el of boxes) {
      if (el && el.scrollWidth > el.clientWidth + 1) out.push(`${el.tagName.toLowerCase()} ${el.scrollWidth} > ${el.clientWidth}`);
    }
    return out;
  });
  expect(wide, 'sideways scroll').toEqual([]);
}

/** No visible text on the page is under 14 px (SPEC: "Nothing is smaller than 14"); the sidebar is not the page's. */
async function expectNoSmallText(page: Page) {
  const small = await page.getByRole('main').evaluate((main) => {
    const out: string[] = [];
    const walker = document.createTreeWalker(main, NodeFilter.SHOW_TEXT);
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      const el = n.parentElement;
      if (!n.textContent?.trim() || !el || el.closest('.sr-only, svg') || !el.getClientRects().length) continue;
      const s = getComputedStyle(el);
      if (s.visibility === 'hidden' || parseFloat(s.fontSize) >= 14) continue;
      out.push(`${s.fontSize} "${n.textContent.trim().slice(0, 40)}"`);
    }
    return out;
  });
  expect(small, 'text under 14 px').toEqual([]);
}

const SIZES = [
  { width: 390, height: 844 },
  { width: 1024, height: 768 },
  { width: 1440, height: 900 },
] as const;

for (const theme of ['dark', 'light'] as const) {
  for (const { width, height } of SIZES) {
    test(`words journey: a working team at a glance, ${theme}, ${width}x${height}`, async ({ page }) => {
      test.setTimeout(90_000);
      const phone = width < 768;
      await page.setViewportSize({ width, height });
      await page.addInitScript((t) => localStorage.setItem('temper_theme', t), theme);
      await open(page, 'working');

      // Header: both breadcrumbs are whole targets (D35); the buttons are 14 px (D8/D9),
      // and a phone leaves out "3 members", since Now counts them on the same screen (D74).
      const crumbs = page.getByRole('navigation', { name: 'Breadcrumb' }).getByRole('link');
      await expect(crumbs).toHaveText(['Team', 'Projects']);
      for (const crumb of await crumbs.all()) {
        const box = await boxOf(crumb);
        expect(Math.min(box.width, box.height), 'breadcrumb target').toBeGreaterThanOrEqual(24);
      }
      for (const name of ['Message a member', 'Stop project']) {
        await expect(page.getByRole('button', { name })).toHaveCSS('font-size', '14px');
      }
      const facts = page.getByTestId('glance-facts');
      if (phone) await expect(facts).not.toContainText('3 members', { useInnerText: true });
      else await expect(facts).toContainText('3 members', { useInnerText: true });

      // Now: Temper's count first, then who works on what, one line each (D8); a phone lists one and counts the
      // rest (D111), 768 px and wider list three (D84).
      await expect(nowWord(page)).toHaveText('Working');
      await expect(nowSentence(page)).toHaveText(/^3 of 3 members working\. Last activity \d+\u00a0s\u00a0ago\.$/);
      const working = page.getByTestId('glance-working');
      await expect(working).toHaveAttribute('aria-label', 'Working now');
      await expect(working.getByTestId('glance-working-row').locator('b')).toHaveText(phone ? ['lead'] : ['lead', 'builder', 'checker']);
      await expect(working.getByTestId('glance-working-on')).toHaveText(
        phone ? [] : ['\u201cBuild the builder part and share it.\u201d', '\u201cBuild the checker part and share it.\u201d'],
      );
      const rest = working.getByText('and 2 more working', { exact: true });
      if (phone) await expect(rest).toBeVisible();
      else await expect(rest).toHaveCount(0);

      // You and Spend: nothing needs you; the general hint stays off a phone (D9).
      await expect(youTitle(page)).toHaveText('Nothing needs you');
      const hint = page.getByTestId('glance-you').getByText('Questions and check-ins show up here.');
      if (phone) await expect(hint).toBeHidden();
      else await expect(hint).toBeVisible();
      const spend = page.getByTestId('glance-spend');
      await expect(spend).toContainText('$0.00');
      await expect(spend).toContainText('of $100');
      await expect(spend).toContainText('At $100 the team pauses and asks you.');

      // On a phone the whole band, Spend's line included, ends on the first screen (D9).
      if (phone) expect(await bandEnd(page), 'band end').toBeLessThanOrEqual(844);

      // Cards: role and leader on their own line under the name, no middot (D51).
      const cards = page.locator('[data-member]:visible');
      await expect(cards).toHaveCount(3);
      for (const card of await cards.all()) {
        const name = card.locator('h3 > span').first();
        const role = card.getByTestId('glance-role');
        await expect(role).not.toContainText('\u00b7');
        expect((await boxOf(role)).y, 'role under the name').toBeGreaterThanOrEqual((await boxOf(name)).y + (await boxOf(name)).height - 1);
      }
      await expect(page.locator('[data-member="lead"]:visible').getByTestId('glance-role')).toContainText('leader');

      // Latest: ages say "ago" in a 76 px column, 68 on a phone (D59).
      const ages = page.getByTestId('glance-latest-time');
      expect(await ages.count()).toBeGreaterThan(0);
      for (const age of await ages.all()) {
        await expect(age).toHaveText(/^\d.*\sago$/);
        expect((await boxOf(age)).width).toBeCloseTo(phone ? 68 : 76, 0);
      }

      // All activity: clock times to the second (D46).
      const times = await activity(page).locator('time').allTextContents();
      expect(times.length).toBeGreaterThan(0);
      for (const time of times) expect(time).toMatch(/^\d{2}:\d{2}:\d{2}$/);

      // The message box says when the chosen member gets it (D56).
      const composer = page.locator('#glance-message');
      await composer.getByLabel('To').selectOption('builder');
      await expect(composer.getByText('is working: it gets your message during this turn.')).toBeVisible();
      await expect(composer.locator('b', { hasText: 'builder' })).toBeVisible();

      await page.getByRole('main').evaluate((main) => main.scrollTo(0, 0));
      await expectAxeClean(page);
      await expectTargets(page);
      await expectNoSideways(page);
      await expectNoSmallText(page);
      if (phone) {
        await page.setViewportSize({ width: 320, height: 568 });
        await expect(working.getByTestId('glance-working-row')).toHaveCount(1);
        await expect(rest).toBeVisible();
        // D84: the band ends on a 844 px screen at the 320 reflow too.
        await page.getByRole('main').evaluate((main) => main.scrollTo(0, 0));
        expect(await bandEnd(page), 'band end at 320').toBeLessThanOrEqual(844);
        await expectTargets(page);
        await expectNoSideways(page);
        await expectNoSmallText(page);
      } else if (width === 1024) {
        // D84: at 1024x768 the band ends on the first screen.
        expect(await bandEnd(page), 'band end at 1024x768').toBeLessThanOrEqual(768);
      }
    });
  }
}

/**
 * The symbols Source Sans Pro lacks, which index.css draws from small Noto faces (Design rm-753d7aa4 (b), D100,
 * D101): the four arrows, the minus sign, the status signs (check, cross, circle, square, circled slash, pause,
 * play), the warning sign, the multiplication x, command and return, and the less-or-equal, greater-or-equal and
 * almost-equal signs.
 */
const SYMBOLS = [
  '\u2190', '\u2191', '\u2192', '\u2193', '\u2212', '\u2713', '\u2717', '\u25CB', '\u25A0', '\u2298',
  '\u23F8', '\u25B6', '\u26A0', '\u2715', '\u2318', '\u21B5', '\u2264', '\u2265', '\u2248',
];
/**
 * The ones the glance page can show, whose faces its ready point (D80) waits for: the right and down arrows, the
 * play and warning signs, and the check, cross and square of an ended run's badge (the Stop dialog).
 */
const GLANCE_SYMBOLS = ['\u2192', '\u2193', '\u25B6', '\u26A0', '\u2713', '\u2717', '\u25A0'];
const FONT_FILE = /\.(woff2|ttf)(\?|$)/;

/** A unicode-range's characters ("U+2192-2193, U+25B6" gives the three). */
const rangeCharacters = (range: string) =>
  range.split(',').flatMap((part) => {
    const [from, to] = part.trim().replace(/^U\+/i, '').split('-');
    const start = parseInt(from, 16);
    return Array.from({ length: (to ? parseInt(to, 16) : start) - start + 1 }, (_, i) => String.fromCodePoint(start + i));
  });

interface SymbolFace {
  family: string;
  file: string;
  weight: string;
  characters: string[];
  status: string;
}

/**
 * The symbol faces as the browser read index.css (the faces with a unicode-range; the page's own two files have
 * none): each one's file, weight, characters and load status.
 */
async function symbolFaces(page: Page): Promise<SymbolFace[]> {
  const { rules, faces } = await page.evaluate(() => ({
    rules: Array.from(document.styleSheets)
      .flatMap((sheet) => {
        try {
          return Array.from(sheet.cssRules);
        } catch {
          return []; // a sheet from another origin keeps its rules to itself
        }
      })
      .filter((rule): rule is CSSFontFaceRule => rule instanceof CSSFontFaceRule)
      .map((rule) => ({
        family: rule.style.getPropertyValue('font-family'),
        src: rule.style.getPropertyValue('src'),
        weight: rule.style.getPropertyValue('font-weight'),
        range: rule.style.getPropertyValue('unicode-range'),
      })),
    faces: Array.from(document.fonts)
      .filter((face) => face.unicodeRange.toUpperCase() !== 'U+0-10FFFF')
      .map((face) => ({ weight: face.weight, range: face.unicodeRange, status: face.status })),
  }));
  const key = (weight: string, range: string) => `${weight} ${rangeCharacters(range).join('')}`;
  const status = new Map(faces.map((face) => [key(face.weight, face.range), face.status]));
  const fileOf = (src: string) => {
    const url = /url\("?([^")]+)"?\)/.exec(src)?.[1] ?? '';
    // A file small enough for Vite to put into the stylesheet, unless its url says ?no-inline: every page carries it.
    return url.startsWith('data:') ? `${url.slice(0, url.indexOf(';'))}, inlined into the stylesheet` : new URL(url, page.url()).pathname;
  };
  return rules
    .filter((rule) => rule.range !== '')
    .map((rule) => ({
      family: rule.family.replace(/["']/g, ''),
      file: fileOf(rule.src),
      weight: rule.weight,
      characters: rangeCharacters(rule.range),
      status: status.get(key(rule.weight, rule.range)) ?? 'not in document.fonts',
    }));
}

/** The path of every font file the page asks for, in the order asked. */
function fontFiles(page: Page) {
  const files: string[] = [];
  page.on('request', (request) => {
    if (FONT_FILE.test(request.url())) files.push(new URL(request.url()).pathname);
  });
  return files;
}

/** The symbol files among the font files a page asked for. */
function symbolFiles(faces: SymbolFace[], fetched: string[]) {
  const all = new Set(faces.map((face) => face.file));
  return [...new Set(fetched.filter((file) => all.has(file)))].sort();
}

/** The symbol files some text calls for: the file of each face holding one of its characters, at either weight. */
const filesFor = (faces: SymbolFace[], text: string) =>
  [...new Set(faces.filter((face) => face.characters.some((c) => text.includes(c))).map((face) => face.file))].sort();

/**
 * index.css's symbol faces join the page's family at its two weights, and each weight holds every symbol in one face
 * only: no two files of one weight overlap, so which file draws a symbol is never left to the browser.
 */
function expectSymbolFaces(faces: SymbolFace[], where: string) {
  expect([...new Set(faces.map((face) => face.family))], where).toEqual(['Source Sans Pro']);
  expect([...new Set(faces.map((face) => face.weight))].sort(), where).toEqual(['400', '500 900']);
  for (const weight of ['400', '500 900']) {
    const held = faces.filter((face) => face.weight === weight).flatMap((face) => face.characters);
    expect(held.sort(), `${where}: the symbols at ${weight}, each once`).toEqual([...SYMBOLS].sort());
  }
}

/**
 * Each element whose own text holds one of the symbols, with the fonts Chromium drew its text in
 * (CDP CSS.getPlatformFontsForNode): a system font there means a fallback the browser chose.
 */
async function symbolFonts(page: Page) {
  const cdp = await page.context().newCDPSession(page);
  try {
    await cdp.send('DOM.enable');
    await cdp.send('CSS.enable');
    await cdp.send('DOM.getDocument', { depth: -1 });
    const query = `//*[text()[${SYMBOLS.map((symbol) => `contains(., "${symbol}")`).join(' or ')}]]`;
    const { searchId, resultCount } = await cdp.send('DOM.performSearch', { query });
    const found: Array<{ html: string; fonts: Array<{ familyName: string; isCustomFont: boolean; glyphCount: number }> }> = [];
    if (resultCount > 0) {
      const { nodeIds } = await cdp.send('DOM.getSearchResults', { searchId, fromIndex: 0, toIndex: resultCount });
      for (const nodeId of nodeIds) {
        const { fonts } = await cdp.send('CSS.getPlatformFontsForNode', { nodeId });
        const { outerHTML } = await cdp.send('DOM.getOuterHTML', { nodeId });
        found.push({ html: outerHTML, fonts });
      }
    }
    await cdp.send('DOM.discardSearchResults', { searchId });
    return found;
  } finally {
    await cdp.detach();
  }
}

/** Every element drawing a symbol is drawn in the page's own faces only: no system font. */
function expectOwnFaces(drawn: Awaited<ReturnType<typeof symbolFonts>>, where: string) {
  for (const { html, fonts } of drawn) {
    expect(fonts.filter((font) => !font.isCustomFont).map((font) => font.familyName), `${where}: system font for ${html}`).toEqual([]);
  }
}

/** The run list with one run in each status it marks with a sign (STATUS_ICONS); nothing else is answered. */
async function serveRunList(page: Page) {
  const runs = Object.keys(STATUS_ICONS).map((status, i) => ({
    id: `00000000-0000-4000-8000-00000000000${i}`,
    workflow_name: `signs-${status}`,
    status,
    start_time: '2026-10-10T09:00:00Z',
    end_time: null,
    duration_seconds: 60,
    total_tokens: 1200,
    total_cost_usd: 0.01,
    total_llm_calls: 2,
    total_tool_calls: 1,
  }));
  await page.route(/\/api\/workflows(\?|$)/, (route) => route.fulfill({ json: { runs, total: runs.length } }));
  return runs;
}

const SYMBOL_SIZES = [
  { theme: 'dark', width: 1440, height: 900 },
  { theme: 'light', width: 1440, height: 900 },
  { theme: 'dark', width: 390, height: 844 },
] as const;

for (const { theme, width, height } of SYMBOL_SIZES) {
  test(`contract: the run list draws its status signs in the page's own faces and fetches only their files, ${theme}, ${width}x${height} (D101)`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height });
    await page.addInitScript((t) => localStorage.setItem('temper_theme', t), theme);
    const files = fontFiles(page);

    // With no run to list it shows no symbol, and the unicode-range keeps every symbol file unloaded.
    await page.goto('/app/');
    await page.waitForLoadState('networkidle');
    await page.evaluate(() => document.fonts.ready);
    const empty = (await page.locator('body').textContent()) ?? '';
    expect(empty).toContain('Workflows');
    expect(SYMBOLS.filter((symbol) => empty.includes(symbol)), 'symbols on the empty run list').toEqual([]);
    expect(files.some((file) => /sourcesanspro-regular/.test(file)), `font files: ${files.join(', ')}`).toBe(true);
    const faces = await symbolFaces(page);
    expectSymbolFaces(faces, 'empty run list');
    expect(symbolFiles(faces, files), 'symbol files on the empty run list').toEqual([]);
    expect(faces.filter((face) => face.status !== 'unloaded').map((face) => `${face.file} ${face.status}`)).toEqual([]);

    // With one run in each status it shows each status's sign, drawn in the page's own faces only.
    const runs = await serveRunList(page);
    await page.goto('/app/');
    for (const run of runs) await expect(page.getByText(run.workflow_name).first()).toBeVisible();
    await page.waitForLoadState('networkidle');
    await page.evaluate(() => document.fonts.ready);
    const text = (await page.locator('body').textContent()) ?? '';
    const signs = [...new Set(runs.map((run) => STATUS_ICONS[run.status]))].sort();
    expect(SYMBOLS.filter((symbol) => text.includes(symbol)).sort(), 'symbols on the run list').toEqual(signs);
    const drawn = (await symbolFonts(page)).filter(({ fonts }) => fonts.length > 0);
    expect(drawn.length, 'elements drawing a sign').toBeGreaterThanOrEqual(runs.length);
    expectOwnFaces(drawn, 'run list');
    // It fetches the files of the signs it shows and no other: never the arrows' or the minus sign's.
    const fetched = symbolFiles(faces, files);
    expect(fetched, 'symbol files on the run list').toEqual(filesFor(faces, signs.join('')));
    expect(fetched.filter((file) => /arrows|minus/.test(file)), 'arrow or minus files on the run list').toEqual([]);
  });

  test(`contract: the glance page draws its symbols in the page's own faces on every state, never a system font, and fetches only the files of those it can show, ${theme}, ${width}x${height} (rm-753d7aa4, D101)`, async ({
    page,
  }) => {
    test.setTimeout(240_000);
    await page.setViewportSize({ width, height });
    await page.addInitScript((t) => localStorage.setItem('temper_theme', t), theme);
    const files = fontFiles(page);
    const shown: string[] = [];
    const held = new Set<string>(GLANCE_SYMBOLS);
    let faces: SymbolFace[] = [];
    for (const name of STATES) {
      await page.unrouteAll();
      await open(page, name);
      faces = await symbolFaces(page);
      expectSymbolFaces(faces, name);
      const text = (await page.locator('body').textContent()) ?? '';
      for (const symbol of SYMBOLS) if (text.includes(symbol)) held.add(symbol);
      // The ready point (D80) waited for the faces of the symbols the page can show, at both weights: the map's
      // measure was taken with them. A face holding none of those, nor any of the page's text, stays unloaded.
      for (const face of faces) {
        const where = `${name}: ${face.file} at ${face.weight}`;
        if (face.characters.some((c) => GLANCE_SYMBOLS.includes(c))) expect(face.status, where).toBe('loaded');
        else if (!face.characters.some((c) => text.includes(c))) expect(face.status, where).toBe('unloaded');
      }
      // Every element showing one is drawn in the page's own faces only (one not drawn has no fonts).
      const drawn = (await symbolFonts(page)).filter(({ fonts }) => fonts.length > 0);
      expectOwnFaces(drawn, name);
      if (drawn.length > 0) shown.push(name);
    }
    // The Just sent line's arrow is on every state today; a state without one is noted, not failed.
    expect(shown.length, 'states showing a symbol').toBeGreaterThan(0);
    test.info().annotations.push({ type: 'states-without-symbols', description: STATES.filter((name) => !shown.includes(name)).join(', ') || 'none' });
    // It fetches the files of the symbols it can show, and no file but those and the files of symbols its text holds.
    const fetched = symbolFiles(faces, files);
    expect(fetched, 'symbol files for the glance').toEqual(expect.arrayContaining(filesFor(faces, GLANCE_SYMBOLS.join(''))));
    const used = filesFor(faces, [...held].join(''));
    expect(fetched.filter((file) => !used.includes(file)), 'symbol files the glance has no use for').toEqual([]);
  });
}

test("contract: a member's own long question names it, fits the phone band, and opens whole with Temper's note (D62, S1)", async ({ page }) => {
  test.setTimeout(90_000);
  await page.setViewportSize({ width: 390, height: 844 });
  const wait = (flowRaw('member_question').open_waits as Raw[])[0];
  const question = wait.question as string;
  expect(question.length).toBeGreaterThan(900);
  await open(page, 'member_question');

  // The band: the first line cut after a whole word at 90 (D62), from the member, never "owner".
  const title = /^Needs you: \u201c(.+)\u2026\u201d$/.exec(((await youTitle(page).textContent()) ?? '').trim());
  const shown = title?.[1] ?? '';
  expect(shown.length + 1, 'cut at 90').toBeLessThanOrEqual(90);
  expect(shown.length, 'cut late enough').toBeGreaterThan(54);
  expect(question.startsWith(shown), 'the question\'s own first words').toBe(true);
  expect(question.charAt(shown.length), 'after a whole word').toMatch(/[^\p{L}\p{N}]/u);
  const you = page.getByTestId('glance-you');
  await expect(you).not.toContainText(/\bowner\b/i);
  const from = page.getByTestId('glance-from-row');
  const asker = from.getByText('From builder', { exact: true });
  const answer = from.getByRole('button', { name: 'Answer' });
  // "From builder" shares its row with a 24 px Answer (D9).
  const a = await boxOf(answer);
  const f = await boxOf(asker);
  expect(Math.min(a.width, a.height), 'Answer target').toBeGreaterThanOrEqual(24);
  expect(Math.abs(a.y + a.height / 2 - (f.y + f.height / 2)), 'same row').toBeLessThan(a.height / 2);
  // The phone's compact band leaves Temper's note to the answer view (D9, D79), so it still ends on the first screen.
  await expect(page.getByTestId('glance-you-note')).toBeHidden();
  await expect(page.getByTestId('glance-question-note')).toHaveCount(0);
  expect(await bandEnd(page), 'band end').toBeLessThanOrEqual(844);
  // The others keep working while builder waits: a phone lists one and counts the other (D111); its card and the
  // activity rows keep 160 (D62).
  await expect(page.getByTestId('glance-working-row').locator('b')).toHaveText(['lead']);
  await expect(page.getByTestId('glance-working').getByText('and 1 more working', { exact: true })).toBeVisible();
  expect((wait.words as string).length).toBeLessThanOrEqual(160);
  await expect(page.locator('[data-member="builder"]:visible').getByTestId('glance-on')).toHaveText(wait.words as string);
  await expect(activity(page)).toContainText('builder asked you:');

  // The answer view (D79): titled with Temper's header as sent ("builder asks"), the whole question,
  // then Temper's fixed note exactly as sent, right above the box.
  await answer.click();
  const view = page.getByTestId('glance-answer-view');
  await expect(view.getByTestId('glance-answer-header')).toHaveText(wait.header as string);
  await expect(view).toHaveAccessibleName(wait.header as string);
  await expect(view.getByTestId('glance-question')).toHaveText(question);
  expect((await boxOf(view.getByTestId('glance-answer-header'))).y, 'header first').toBeLessThan(
    (await boxOf(view.getByTestId('glance-question'))).y,
  );
  const note = view.getByTestId('glance-question-note');
  await expect(note).toHaveText(wait.note as string);
  const box = view.getByRole('textbox');
  await expect(box).toBeVisible();
  const noteId = await note.getAttribute('id');
  expect(noteId).toBeTruthy();
  expect((await box.getAttribute('aria-describedby'))?.split(' ')).toContain(noteId);
  expect((await boxOf(note)).y + (await boxOf(note)).height, 'note above the box').toBeLessThanOrEqual((await boxOf(box)).y);
  await expect(you).not.toContainText(/\bowner\b/i);
  await expectAxeClean(page);
  await expectTargets(page);
  await expectNoSideways(page);

  // While the question is open the message box says builder reads it after the answer (D56).
  const composer = page.locator('#glance-message');
  await composer.getByLabel('To').selectOption('builder');
  await expect(composer.getByText("is waiting for an answer: it gets your message once that's answered.")).toBeVisible();

  // At 320 px the whole question and the note still wrap inside the page (D50).
  await page.setViewportSize({ width: 320, height: 568 });
  await expectNoSideways(page);
  await expectTargets(page);
});

test('contract: in every state Temper can be in, the band ends on the first screen (390x844 and 1024x768, D84; 320 reflows, D103), no text is under 14 px, and Stop is offered only while the team is live', async ({
  context,
}) => {
  test.setTimeout(240_000);
  const ends: Record<string, number> = {};
  for (const name of STATES) {
    const page = await context.newPage();
    await page.setViewportSize({ width: 390, height: 844 });
    await open(page, name);
    ends[name] = await bandEnd(page);
    expect(ends[name], `${name}: band end`).toBeLessThanOrEqual(844);
    // Stop by liveness, never from owner_actions (that is history).
    await expect(stopButton(page), `${name}: Stop`).toHaveCount(ENDED.has(phaseOf(name)) ? 0 : 1);
    // A phone band leaves Temper's note to the answer view (D9, D79).
    await expect(page.getByTestId('glance-question-note'), `${name}: no answer view`).toHaveCount(0);
    await expect(page.getByTestId('glance-you-note'), `${name}: no note in the phone band`).toBeHidden();
    await expectNoSmallText(page);
    // Reflow: nothing sideways at 320 px in any state; where the band ends is checked for all states below (D84).
    await page.setViewportSize({ width: 320, height: 568 });
    await expectNoSideways(page);
    ends[`${name} at 320`] = await bandEnd(page);
    // D84: at 1024x768 the band ends on the first screen; no text under 14 px, phone or wide.
    await page.setViewportSize({ width: 1024, height: 768 });
    ends[`${name} at 1024`] = await bandEnd(page);
    expect(ends[`${name} at 1024`], `${name}: band end at 1024x768`).toBeLessThanOrEqual(768);
    await expectNoSmallText(page);
    await page.close();
  }
  test.info().annotations.push({ type: 'band-ends', description: JSON.stringify(ends) });
  // D103: 320 px is a reflow check, not a first-screen check: the band may end below 844 there (its ends are in the
  // annotation, for Design), never sideways (checked above).
});

test("contract: on a wide screen Temper's note sits under a member's own question, said once, and never under Temper's own waits (D79)", async ({
  context,
}) => {
  test.setTimeout(120_000);
  const page = await context.newPage();
  await page.setViewportSize({ width: 1024, height: 768 });
  const wait = (flowRaw('member_question').open_waits as Raw[])[0];
  await open(page, 'member_question');
  const note = page.getByTestId('glance-you-note');
  await expect(note).toHaveText(wait.note as string);
  // 14 px muted text, right under the question.
  expect(await note.evaluate((el) => getComputedStyle(el).fontSize)).toBe('14px');
  const title = await boxOf(youTitle(page));
  expect((await boxOf(note)).y, 'under the question').toBeGreaterThanOrEqual(title.y + title.height - 1);
  await expectAxeClean(page);
  // With the answer view open the note is said once, right above the box.
  await page.getByTestId('glance-from-row').getByRole('button', { name: 'Answer' }).click();
  await expect(note).toHaveCount(0);
  await expect(page.getByTestId('glance-answer-view').getByTestId('glance-question-note')).toHaveText(wait.note as string);
  await expect(page.getByText(wait.note as string, { exact: true })).toHaveCount(1);
  await page.close();
  // Temper's own waits carry no note, and none is made up.
  for (const name of ['failed', 'check_in', 'limit_asked', 'settings', 'stalled']) {
    expect((flowRaw(name).open_waits as Raw[]).every((w) => w.note === null), `${name}: note null`).toBe(true);
    const other = await context.newPage();
    await other.setViewportSize({ width: 1024, height: 768 });
    await open(other, name);
    await expect(youTitle(other)).toContainText('Needs you');
    await expect(other.getByTestId('glance-you-note'), `${name}: no note`).toHaveCount(0);
    await other.close();
  }
});

/** The band's cells: where each starts and how wide it is, and its top. */
function bandCells(page: Page, testId: string) {
  return page
    .getByTestId(testId)
    .locator('.glance-band-grid > *')
    .evaluateAll((els) =>
      els.map((el) => {
        const r = el.getBoundingClientRect();
        return { x: Math.round(r.left), width: Math.round(r.width), top: Math.round(r.top) };
      }),
    );
}

test("contract: before Temper's first reply the band keeps its loaded shape; a failed first read says so (SPEC 10, D7, D53, D70)", async ({
  page,
}) => {
  test.setTimeout(90_000);
  await page.setViewportSize({ width: 1024, height: 768 });
  const name = 'working';
  const run = flowRaw(name);
  await page.clock.setFixedTime(new Date(run.as_of as string));
  await serveState(page, name);
  // The first read waits until the loading view has been looked at.
  let release = () => {};
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route(/\/api\/team\/runs\/[^/?]+(\?|$)/, async (route) => {
    await held;
    await route.fallback();
  });
  await page.goto(`/app/team/runs/${run.execution_id as string}`);
  await expect(page.getByTestId('glance-loading')).toBeVisible();
  // One page heading, for screen readers only; nothing about the kind of run yet (D7, D53).
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Team run');
  await expect(page.getByRole('heading', { level: 1 })).toHaveClass(/sr-only/);
  await expect(page.getByRole('navigation', { name: 'Breadcrumb' }).getByRole('link')).toHaveText(['Team', 'Projects']);
  const skeleton = page.getByTestId('glance-band-loading');
  await expect(skeleton).toHaveAttribute('aria-busy', 'true');
  await expect(skeleton.getByRole('heading', { level: 3 })).toHaveText(['Now', 'You', 'Spend']);
  await expect(page.getByRole('status').filter({ hasText: 'Loading the project from Temper\u2026' })).toBeVisible();
  await expectAxeClean(page);
  const loadingCells = await bandCells(page, 'glance-band-loading');
  release();
  await expect(page.getByTestId('glance-page')).toBeVisible();
  const loadedCells = await bandCells(page, 'glance-band');
  // D70: at 1024 Now runs across the top with You and Spend side by side under it, loading and loaded alike.
  expect(loadingCells.map(({ x, width }) => ({ x, width }))).toEqual(loadedCells.map(({ x, width }) => ({ x, width })));
  for (const cells of [loadingCells, loadedCells]) {
    expect(cells[1].top).toBeGreaterThan(cells[0].top);
    expect(cells[2].top).toBe(cells[1].top);
    expect(cells[0].width).toBeGreaterThan(cells[1].width + cells[2].width - 2);
  }

  // The first read fails: the page says so, changes nothing, and offers Try again and the way back.
  await page.unrouteAll({ behavior: 'ignoreErrors' });
  const failed = await serveState(page, name);
  failed.state.down = true;
  await page.goto(`/app/team/runs/${run.execution_id as string}`);
  await expect(page.getByTestId('glance-read-failed')).toBeVisible();
  await expect(page.getByRole('heading', { level: 1 })).toHaveText("This project couldn't be read");
  const alert = page.getByRole('alert');
  await expect(alert).toContainText("Temper didn't answer");
  await expect(alert).toContainText(
    'The page asked Temper for this project and got no answer. Nothing was changed. It may be restarting.',
  );
  await expect(alert.getByRole('link', { name: 'Back to Projects' })).toHaveAttribute('href', /\/team$/);
  await expectAxeClean(page);
  await expectTargets(page);
  failed.state.down = false;
  await alert.getByRole('button', { name: 'Try again' }).click();
  await expect(page.getByTestId('glance-page')).toBeVisible();
});

test("contract: paths and quoted words break inside the page at 320 px, never sideways (D50)", async ({ page }) => {
  test.setTimeout(60_000);
  await page.setViewportSize({ width: 320, height: 568 });
  const longPath = 'frontend/src/components/team/glance/averyveryverylongfoldernamewithnobreaks/StatusBandWordsAndStates.tsx';
  await open(page, 'working', {
    run: (run) => {
      for (const m of run.members as Raw[]) if (m.on) (m.on as Raw).text = `Fix ${longPath} and share it.`;
    },
    // All activity reads the events feed, the page's one history (home decision 3).
    feed: (feed) => {
      for (const e of feed.events) if (e.kind === 'message' && e.message_kind === 'work_request') e.text = `Fix ${longPath} and share it.`;
    },
  });
  await expect(page.locator('[data-member="builder"]:visible').getByTestId('glance-on')).toContainText(longPath);
  await expect(activity(page)).toContainText(longPath);
  await expectNoSideways(page);
  await expectTargets(page);
});

test("contract: a usage check that can't be read names the next check, promises no resume, and asks nothing (D65)", async ({ page }) => {
  test.setTimeout(60_000);
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, 'limit_start_check');
  await expect(nowWord(page)).toHaveText('Usage limit');
  await expect(nowSentence(page)).toHaveText(
    /^Usage cannot be checked; the team keeps waiting\. Next allowance check at [^.]+\. No usable reset time\.$/,
  );
  await expect(page.getByTestId('glance-band')).not.toContainText(/resume|carries on|starts again/i);
  await expect(youTitle(page)).toHaveText('Nothing needs you');
  await expect(page.getByRole('button', { name: /restart/i })).toHaveCount(0);
  // Latest's limit row names the check while the team is in its limit.
  await expect(page.getByTestId('glance-latest')).toContainText(/Usage limit: next allowance check at [^;]+; no usable reset time/);
  await expect(stopButton(page)).toHaveCount(1);
  await expectAxeClean(page);
});

test('contract: an ended run says how it ended once, spends "in all", and offers no Stop and no dead link (D41, D54, D67)', async ({ page }) => {
  test.setTimeout(120_000);
  await page.setViewportSize({ width: 1440, height: 900 });
  const ended = STATES.filter((name) => ENDED.has(phaseOf(name)));
  expect(ended.length).toBeGreaterThanOrEqual(4);
  for (const name of ended) {
    await page.unrouteAll({ behavior: 'ignoreErrors' });
    await open(page, name);
    await expect(page.getByTestId('glance-spend'), name).toContainText(/Spent in all\. \d+ check-ins?, none to come/);
    await expect(stopButton(page), name).toHaveCount(0);
    await expect(page.locator('#glance-message'), name).toHaveCount(0);
    // D54: no version view is reachable from this page, so no "See the changes"; never "#".
    await expect(page.getByRole('link', { name: /see the changes/i }), name).toHaveCount(0);
    await expect(page.locator('main a[href="#"]'), name).toHaveCount(0);
    // D41: the label, then the reason, never the label twice.
    const rows = [
      ...(await page.getByTestId('glance-latest').locator('li').allInnerTexts()),
      ...(await activity(page).locator('li').allInnerTexts()),
    ];
    for (const row of rows) expect(row, name).not.toMatch(/(Stopped|Failed|Cancelled|Ended: done): (stopped|failed|cancelled|ended)\b/i);
  }
  await expectAxeClean(page);
});

test('contract: when Temper stops answering, Now says "Last seen" and You says when something last needed you (D48, D64)', async ({ page }) => {
  test.setTimeout(60_000);
  await page.setViewportSize({ width: 390, height: 844 });
  const { state } = await open(page, 'working');
  state.down = true;
  await expect(page.getByText(/^Temper hasn.t answered for /).first()).toBeVisible({ timeout: 15_000 });
  await expect(nowWord(page)).toHaveText('Last seen: Working');
  await expect(nowSentence(page)).toHaveText('3 of 3 members working.');
  // D111, D113: with the stale note on a phone, Now lists no member and no "and N more"; the count line keeps the number.
  const working = page.getByTestId('glance-working');
  await expect(working).toHaveCount(0);
  await expect(page.getByText(/^and \d+ more working$/)).toHaveCount(0);
  expect(await bandEnd(page), 'band end').toBeLessThanOrEqual(844);
  await expect(youTitle(page)).toHaveText(/^Nothing needed you .+ ago$/);
  await expect(page.getByTestId('glance-you')).toContainText('Questions show up once Temper answers.');
  await expectAxeClean(page);
  await expectTargets(page);
  await expectNoSideways(page);
  // Wider, Now lists who worked when last seen, under its own name.
  await page.setViewportSize({ width: 1440, height: 900 });
  await expect(working).toHaveAttribute('aria-label', 'Working when last seen');
  await expect(working.getByTestId('glance-working-row').locator('b')).toHaveText(['lead', 'builder', 'checker']);
});
