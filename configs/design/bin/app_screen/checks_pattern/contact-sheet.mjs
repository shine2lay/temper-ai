// Design #204: contact sheets of every screen's first view in draft-a, one PNG per size (1440 desktop, 390 phone),
// to judge at a glance whether each first view is calm and whether the screens look like one product.
// Each screen is shot at real size into contact/<size>/<screen>.png, then laid out on one sheet with its name.
// usage: node contact-sheet.mjs   -> contact/contact-1440.png, contact/contact-390.png
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import fs from 'node:fs';

const { chromium } = createRequire('/home/shinelay/temper-ai/frontend/package.json')('playwright');
const HERE = path.dirname(fileURLToPath(import.meta.url));
const URL = 'file://' + path.join(HERE, 'index.html');
const OUT = path.join(HERE, 'contact');
const nav = id => `[data-nav="${id}"]`;
const more = s => [nav('more'), `[data-act="more-open"][data-sub="${s}"]`];
const SCREENS = [
  ['Today', []], ['Positions', [nav('positions')]], ['Orders', [nav('orders')]], ['Analysis', [nav('analysis')]],
  ['More', [nav('more')]], ['Alerts', ['[data-act="top-bell"]']], ['Trade', more('ladder')], ['Ideas', more('ideas')],
  ['Screener', more('screener')], ['Browse', more('browse')], ['How to trade', more('howto')], ['Glossary', more('glossary')],
  ['Settings', more('settings')], ['Robinhood', more('robinhood')], ['System status', more('system')],
  ['Account menu', ['[data-act="top-account"]']],
  ['Signed out', ['[data-act="top-account"]', '[data-act="acct-signout"]', '[data-act="acct-signout-yes"]', 2600]],
];
const SIZES = [
  { name: '1440', view: 'desk', ctx: { viewport: { width: 1500, height: 1000 } }, shot: '#desk', root: '#desk', cols: 3, scale: 0.5 },
  { name: '390', view: 'phone', ctx: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true }, shot: null, root: '#phone', cols: 6, scale: 0.6 },
];
const slug = s => s.toLowerCase().replace(/[^a-z0-9]+/g, '-');
const browser = await chromium.launch();
for (const size of SIZES) {
  const dir = path.join(OUT, size.name); fs.mkdirSync(dir, { recursive: true });
  const ctx = await browser.newContext({ ...size.ctx, deviceScaleFactor: 1 });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  const shots = [];
  for (const [name, steps] of SCREENS) {
    await page.goto(URL + '?view=' + size.view); await page.waitForTimeout(300);
    for (const s of steps) {
      if (typeof s === 'number') { await page.waitForTimeout(s); continue; }
      await page.locator(`${size.root} ${s} >> visible=true`).first().click({ timeout: 4000 }); await page.waitForTimeout(450);
    }
    await page.evaluate(() => document.fonts.ready);
    const file = path.join(dir, slug(name) + '.png');
    if (size.shot) await page.locator(size.shot).screenshot({ path: file }); else await page.screenshot({ path: file });
    shots.push([name, file]);
  }
  if (errors.length) { console.log(`${size.name}: page errors: ${errors.join(' | ')}`); process.exitCode = 1; }
  // lay the shots out on one sheet, in the browser
  const { width, height } = await (async () => { const p = await ctx.newPage(); await p.goto('file://' + shots[0][1]); const d = await p.evaluate(() => ({ width: document.images[0].naturalWidth, height: document.images[0].naturalHeight })); await p.close(); return d; })();
  const w = Math.round(width * size.scale), h = Math.round(height * size.scale);
  const html = `<!doctype html><html><body style="margin:0;padding:24px;background:#d9d5cc;font:600 18px system-ui;color:#13233b">
    <h1 style="margin:0 0 16px;font-size:26px">RollCall option A, every screen's first view at ${size.name} px (shown at ${Math.round(size.scale * 100)}%)</h1>
    <div style="display:grid;grid-template-columns:repeat(${size.cols},${w}px);gap:20px 16px">
    ${shots.map(([n, f]) => `<figure style="margin:0"><figcaption style="margin-bottom:6px">${n}</figcaption><img src="file://${f}" width="${w}" height="${h}" style="display:block;box-shadow:0 1px 4px rgb(0 0 0/.25);background:#fff"></figure>`).join('')}
    </div></body></html>`;
  const sheetHtml = path.join(dir, 'sheet.html'); fs.writeFileSync(sheetHtml, html);
  const p = await ctx.newPage();
  await p.setViewportSize({ width: size.cols * (w + 16) + 48, height: 800 });
  await p.goto('file://' + sheetHtml); await p.waitForTimeout(300);
  await p.screenshot({ path: path.join(OUT, `contact-${size.name}.png`), fullPage: true });
  fs.rmSync(sheetHtml);
  await p.close(); await ctx.close();
  console.log(`contact/contact-${size.name}.png: ${shots.length} screens`);
}
await browser.close();
