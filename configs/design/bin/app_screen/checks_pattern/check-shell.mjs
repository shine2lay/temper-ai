// Design #182: the v3 app shell of draft-a/index.html, with real clicks.
// Phone at 390x844 and 320x640, desktop at 1440x900. Fails on:
//   a screen without exactly one top bar (phone) or one header tool row (desktop); the old Alerts tab;
//   any "Simulated", "Real money" or "no real money" text; an Account tile without its 3 figures;
//   a premium line that isn't collapsed on first load, doesn't expand on click or isn't remembered;
//   a bell that doesn't open Alerts (or back that doesn't return); a More row that doesn't open its screen
//   (or back that doesn't return to the list); visible text under 12px, or under 14px unless uppercase;
//   a layout wider than the viewport (innerWidth != device width, or scrollWidth > innerWidth); console errors.
// Saves desktop-today, phone-today, phone-more, phone-alerts PNGs (390 wide) next to this file.
// usage: node check-shell.mjs     exit 0 = every step passed
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const { chromium } = createRequire('/home/shinelay/temper-ai/frontend/package.json')('playwright');
const HERE = path.dirname(fileURLToPath(import.meta.url));
const URL = 'file://' + path.join(HERE, 'index.html');
const failures = [];
const passes = [];
const fail = (where, msg) => failures.push(`${where}: ${msg}`);

const NAV = ['Today', 'Positions', 'Orders', 'Analysis', 'More'];
const MORE_ROWS = { ladder: 'Trade', /* Design #192: the Ladder row became the Trade hub */ ideas: 'Ideas', screener: 'Screener', browse: 'Browse', howto: 'How to trade', glossary: 'Glossary', settings: 'Settings', robinhood: 'Robinhood connection', system: 'System status' };
const BANNED = /simulated|real money/i;

function audit(rootSel) {
  // runs in the page: layout width, text sizes and spill inside the active view
  const root = document.querySelector(rootSel);
  const out = { innerWidth: window.innerWidth, scrollWidth: document.documentElement.scrollWidth, small: [], spill: [] };
  const rr = root.getBoundingClientRect();
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const text = n.textContent.trim(); if (!text) continue;
    const el = n.parentElement, cs = getComputedStyle(el);
    if (!el.getClientRects().length || cs.visibility === 'hidden' || el.closest('[hidden], script, style')) continue;
    const size = parseFloat(cs.fontSize), upper = cs.textTransform === 'uppercase' || text === text.toUpperCase();
    if (size < 12 || (size < 14 && !upper)) out.small.push(`${size}px "${text.slice(0, 40)}"`);
  }
  for (const el of root.querySelectorAll('*')) {
    if (!el.getClientRects().length || el.closest('[hidden]')) continue;
    const r = el.getBoundingClientRect();
    if (r.width && (r.right > rr.right + 1 || r.left < rr.left - 1)) out.spill.push(`${el.tagName}.${el.className} ${Math.round(r.left)}-${Math.round(r.right)} vs ${Math.round(rr.left)}-${Math.round(rr.right)}`);
  }
  out.small = out.small.slice(0, 8); out.spill = out.spill.slice(0, 8);
  return out;
}

// one screen as drawn now: top bar count, banned words, sizes, width
async function screen(page, where, { phone, width }) {
  const root = phone ? '#phone' : '#desk';
  const bars = phone
    ? await page.locator('#phone [data-topbar]').count()
    : await page.locator('#desk .dtools').count();
  if (bars !== 1) fail(where, `${bars} ${phone ? 'top bars' : 'desktop header tool rows'} (want exactly 1)`);
  if (phone && bars === 1) {
    const top = await page.locator('#phone [data-topbar]').evaluate(el => {
      const r = el.getBoundingClientRect(), cs = getComputedStyle(el);
      const targets = [...el.querySelectorAll('button')].map(b => b.getBoundingClientRect()).filter(b => b.width < 44 || b.height < 44).length;
      return { top: Math.round(r.top), h: Math.round(r.height), pos: cs.position, small: targets, bell: !!el.querySelector('[data-act=top-bell]'), acct: !!el.querySelector('[data-act=top-account]') };
    });
    if (top.pos !== 'sticky') fail(where, `top bar position ${top.pos} (want sticky)`);
    if (top.h < 56) fail(where, `top bar ${top.h}px tall (want 56+)`);
    if (top.small) fail(where, `${top.small} top bar buttons under 44x44`);
    if (!top.bell || !top.acct) fail(where, 'top bar lacks the bell or the account button');
  }
  // "real money" is allowed only on the arm control itself (Settings, marked data-allow-real-money); never as a badge
  const text = await page.evaluate(() => {
    let t = document.body.innerText;
    for (const el of document.querySelectorAll('[data-allow-real-money]')) t = t.split(el.innerText).join('');
    return t;
  });
  const banned = text.match(BANNED);
  if (banned) fail(where, `shows "${banned[0]}"`);
  const a = await page.evaluate(audit, root);
  if (phone && a.innerWidth !== width) fail(where, `layout width ${a.innerWidth} (want ${width})`);
  if (a.scrollWidth > a.innerWidth) fail(where, `page ${a.scrollWidth}px wide in a ${a.innerWidth}px viewport`);
  if (a.small.length) fail(where, `text too small: ${a.small.join('; ')}`);
  if (a.spill.length) fail(where, `spills out of the view: ${a.spill.join('; ')}`);
}

const title = page => page.locator('#phone [data-topbar] .tb-title').innerText().catch(() => '');

async function phoneRun(browser, width, height) {
  const name = `phone ${width}`;
  const ctx = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: 1, isMobile: true, hasTouch: true });
  const page = await ctx.newPage();
  page.on('console', m => { if (m.type() === 'error') fail(name, `console error: ${m.text()}`); });
  page.on('pageerror', e => fail(name, `page error: ${e.message}`));
  await page.goto(URL + '?view=phone');
  await page.waitForTimeout(600);
  const opts = { phone: true, width };
  const shot = file => width === 390 && page.screenshot({ path: path.join(HERE, file) });

  // Today: brand on the left, freshness at 390 only, nav without Alerts
  if (!(await page.locator('#phone [data-topbar] .tb-brand, #phone [data-topbar] [class*=brand]').count())) fail(`${name} today`, 'no RollCall mark in the top bar');
  const freshOn = await page.locator('#phone [data-topbar] .tb-fresh').isVisible();
  if (width >= 360 && !freshOn) fail(`${name} today`, 'freshness line hidden at 390');
  if (width < 360 && freshOn) fail(`${name} today`, 'freshness line shown below 360');
  const tabs = (await page.locator('#phone .tabbar [data-nav]').allInnerTexts()).map(t => t.replace(/\d+/g, '').trim());
  if (tabs.join(',') !== NAV.join(',')) fail(`${name} nav`, `tabs ${tabs.join(',')} (want ${NAV.join(',')})`);

  // Account tile: three figures in order, sizes
  const figs = await page.locator('#phone .acct-figs').evaluate(dl => [...dl.querySelectorAll('dt')].map(dt => ({ k: dt.textContent.trim(), ks: parseFloat(getComputedStyle(dt).fontSize), v: dt.nextElementSibling?.textContent.trim() || '', vs: parseFloat(getComputedStyle(dt.nextElementSibling).fontSize) }))).catch(() => []);
  if (figs.map(f => f.k).join(',') !== 'Buying power,Margin excess,Net liq') fail(`${name} account tile`, `figures ${figs.map(f => f.k).join(',') || 'missing'}`);
  for (const f of figs) {
    if (!/^\$[\d,]+$/.test(f.v)) fail(`${name} account tile`, `${f.k} value "${f.v}"`);
    if (f.vs < 16 || f.ks < 14) fail(`${name} account tile`, `${f.k} figure ${f.vs}px / label ${f.ks}px (want 16+ / 14+)`);
  }
  if (/\bSafe\b/.test(await page.locator('#phone').innerText())) fail(`${name} account tile`, 'still says "Safe"');

  // Premium line: collapsed first, opens on click, remembered after reload
  const prem = page.locator('#phone [data-act=prem-toggle]');
  const premMore = page.locator('#phone .prem-more');
  if ((await prem.getAttribute('aria-expanded')) !== 'false' || (await premMore.isVisible())) fail(`${name} premium`, 'not collapsed on first load');
  if (!/at stake this week/.test(await prem.innerText())) fail(`${name} premium`, 'summary row lacks "at stake this week"');
  await screen(page, `${name} today`, opts);
  await shot('phone-today.png');
  await prem.click();
  await page.waitForTimeout(200);
  if ((await prem.getAttribute('aria-expanded')) !== 'true' || !(await premMore.isVisible())) fail(`${name} premium`, 'click did not expand it');
  else if (!/Nov/.test(await premMore.innerText()) || !/this year/i.test(await premMore.innerText())) fail(`${name} premium`, 'expanded part lacks Nov and this year');
  await screen(page, `${name} today premium open`, opts);
  await page.reload(); await page.waitForTimeout(500);
  if ((await page.locator('#phone [data-act=prem-toggle]').getAttribute('aria-expanded')) !== 'true') fail(`${name} premium`, 'open choice not remembered after reload');
  await page.locator('#phone [data-act=prem-toggle]').click();
  await page.waitForTimeout(200);

  // Tabs: each draws one top bar
  for (const [id, label] of [['positions', 'Positions'], ['orders', 'Orders'], ['analysis', 'Analysis'], ['more', 'More']]) {
    await page.locator(`#phone .tabbar [data-nav=${id}]`).click();
    await page.waitForTimeout(300);
    if ((await title(page)) !== label) fail(`${name} ${id}`, `top bar title "${await title(page)}" (want ${label})`);
    await screen(page, `${name} ${id}`, opts);
    if (id === 'more') await shot('phone-more.png');
  }
  // Positions detail and back
  await page.locator('#phone .tabbar [data-nav=positions]').click();
  await page.waitForTimeout(300);
  await page.locator('#phone [data-act=positions-open]').first().click();
  await page.waitForTimeout(300);
  if (!(await page.locator('#phone [data-topbar] [data-act=positions-back]').count())) fail(`${name} position detail`, 'top bar has no back');
  await screen(page, `${name} position detail`, opts);
  await page.locator('#phone [data-topbar] [data-act=positions-back]').click();
  await page.waitForTimeout(300);
  if ((await title(page)) !== 'Positions') fail(`${name} position detail`, 'back did not return to Positions');

  // Bell opens Alerts, back returns to where it was pressed
  const bellN = await page.locator('#phone [data-act=top-bell] .tb-n').count();
  if (!bellN) fail(`${name} bell`, 'no unread count on the bell');
  await page.locator('#phone [data-act=top-bell]').click();
  await page.waitForTimeout(400);
  if ((await title(page)) !== 'Alerts' || !(await page.locator('#phone .scr-alerts').isVisible())) fail(`${name} bell`, 'bell did not open Alerts');
  if (!(await page.locator('#phone [data-topbar] [data-act=top-back]').count())) fail(`${name} alerts`, 'Alerts top bar has no back');
  await screen(page, `${name} alerts`, opts);
  await shot('phone-alerts.png');
  await page.locator('#phone [data-topbar] [data-act=top-back]').click();
  await page.waitForTimeout(300);
  if ((await title(page)) !== 'Positions') fail(`${name} alerts`, `back went to "${await title(page)}" (want Positions)`);

  // Account button opens its menu (Design #195, check-auth-tips.mjs covers the menu); its Settings item opens Settings, which carries the freshness line
  await page.locator('#phone [data-act=top-account]').click();
  await page.waitForTimeout(300);
  await page.locator('#phone .acct-menu [data-act=acct-settings]').click();
  await page.waitForTimeout(300);
  if ((await title(page)) !== 'Settings') fail(`${name} account button`, `opened "${await title(page)}" (want Settings)`);
  if (!/10:12 AM/.test(await page.locator('#phone .scr-more').innerText())) fail(`${name} account button`, 'Settings lacks the 10:12 AM freshness');

  // More: every row opens its screen with the shared top bar and back
  await page.locator('#phone .tabbar [data-nav=more]').click();
  await page.waitForTimeout(300);
  const rows = await page.locator('#phone [data-act=more-open]').evaluateAll(els => els.map(e => e.dataset.sub));
  if (rows.join(',') !== Object.keys(MORE_ROWS).join(',')) fail(`${name} more`, `rows ${rows.join(',')} (want ${Object.keys(MORE_ROWS).join(',')})`);
  if (await page.locator('#phone .scr-more').getByText('Alerts', { exact: true }).count()) fail(`${name} more`, 'More lists Alerts (it opens from the bell)');
  for (const [sub, label] of Object.entries(MORE_ROWS)) {
    await page.locator(`#phone [data-act=more-open][data-sub=${sub}]`).click();
    await page.waitForTimeout(300);
    if ((await title(page)) !== label) fail(`${name} more ${sub}`, `top bar title "${await title(page)}" (want ${label})`);
    const stub = await page.locator('#phone .scr-more-stub').count();
    // a row with its own drawn screen (screens['more:<id>'], see more.js) has no stub card; its own check covers it
    // page.html's script is wrapped in an IIFE, so `screens` isn't global: read the DOM instead
    const drawnScreen = (await page.locator('#phone .scr-more > :not(.scr-more-stub)').count()) > 0;
    if (!['settings', 'ladder'].includes(sub) && !drawnScreen && !stub) fail(`${name} more ${sub}`, 'no "what it does today" card');
    if (stub && !/Designed in the full build/.test(await page.locator('#phone .scr-more-stub').innerText())) fail(`${name} more ${sub}`, 'card lacks "Designed in the full build"');
    await screen(page, `${name} more ${sub}`, opts);
    await page.locator('#phone [data-topbar] [data-act=more-back]').click();
    await page.waitForTimeout(300);
    if ((await title(page)) !== 'More' || (await page.locator('#phone [data-act=more-open]').count()) !== rows.length) fail(`${name} more ${sub}`, 'back did not return to the More list');
  }
  await ctx.close();
  passes.push(name);
}

async function deskRun(browser) {
  const name = 'desktop';
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  page.on('console', m => { if (m.type() === 'error') fail(name, `console error: ${m.text()}`); });
  page.on('pageerror', e => fail(name, `page error: ${e.message}`));
  await page.goto(URL + '?view=desk');
  await page.waitForTimeout(600);
  const opts = { phone: false, width: 1440 };
  const tools = page.locator('#desk .dtools');
  for (const sel of ['[data-act=top-bell]', '[data-act=top-account]', '.tb-fresh']) if (!(await tools.locator(sel).count())) fail(`${name} header`, `lacks ${sel}`);
  const nav = (await page.locator('#desk [data-nav]').allInnerTexts()).map(t => t.replace(/\d+/g, '').trim());
  if (nav.join(',') !== NAV.join(',')) fail(`${name} nav`, `nav ${nav.join(',')} (want ${NAV.join(',')})`);
  const figs = await page.locator('#desk .acct-figs dt').allInnerTexts();
  if (figs.join(',') !== 'Buying power,Margin excess,Net liq') fail(`${name} account tile`, `figures ${figs.join(',') || 'missing'}`);
  const prem = page.locator('#desk [data-act=prem-toggle]');
  if ((await prem.getAttribute('aria-expanded')) !== 'false' || (await page.locator('#desk .prem-more').isVisible())) fail(`${name} premium`, 'not collapsed on first load');
  await screen(page, `${name} today`, opts);
  await page.locator('#deskFit').screenshot({ path: path.join(HERE, 'desktop-today.png') });
  await prem.click(); await page.waitForTimeout(200);
  if (!(await page.locator('#desk .prem-more').isVisible())) fail(`${name} premium`, 'click did not expand it');
  await prem.click(); await page.waitForTimeout(200);
  for (const id of ['positions', 'orders', 'analysis', 'more']) {
    await page.locator(`#desk [data-nav=${id}]`).click();
    await page.waitForTimeout(300);
    await screen(page, `${name} ${id}`, opts);
  }
  await tools.locator('[data-act=top-bell]').click();
  await page.waitForTimeout(300);
  if (!(await page.locator('#desk .scr-alerts').isVisible())) fail(`${name} bell`, 'bell did not open Alerts');
  await screen(page, `${name} alerts`, opts);
  await page.locator('#desk [data-nav=more]').click();
  await page.waitForTimeout(300);
  for (const [sub, label] of Object.entries(MORE_ROWS)) {
    await page.locator(`#desk [data-act=more-open][data-sub=${sub}]`).click();
    await page.waitForTimeout(300);
    const h = await page.locator('#desk .scr-more-h').innerText().catch(() => '');
    if (h !== label) fail(`${name} more ${sub}`, `heading "${h}" (want ${label})`);
    await screen(page, `${name} more ${sub}`, opts);
    await page.locator('#desk [data-act=more-back]').click();
    await page.waitForTimeout(300);
    if ((await page.locator('#desk [data-act=more-open]').count()) !== Object.keys(MORE_ROWS).length) fail(`${name} more ${sub}`, 'back did not return to the More list');
  }
  await ctx.close();
  passes.push(name);
}

const browser = await chromium.launch();
try {
  await phoneRun(browser, 390, 844);
  await phoneRun(browser, 320, 640);
  await deskRun(browser);
} finally { await browser.close(); }

if (failures.length) { console.log('FAIL'); for (const f of failures) console.log(f); process.exit(1); }
console.log(`PASS: ${passes.join(', ')}: one top bar per screen, nav ${NAV.join('/')}, no Simulated/Real money text, Account tile with 3 figures, premium line collapsed then expands and is remembered, bell opens Alerts and back returns, ${Object.keys(MORE_ROWS).length} More rows open and back returns, no text under 12px (14px unless uppercase), layout width = viewport. PNGs: desktop-today, phone-today, phone-more, phone-alerts`);
