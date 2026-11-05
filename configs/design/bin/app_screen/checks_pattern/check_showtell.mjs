// Design #170: look-only check that the published Show&Tell page draws in the real viewer, at 1440x900 and 390 wide:
// iframe present, main view has text, every <img> loaded (naturalWidth > 0), each picture URL answers HTTP 200,
// no console errors, and the viewer's Loading / Empty switch shows those views. Writes screenshots to /tmp/rc170/st-*.png.
// usage: node check_showtell.mjs <doc_id> [base]   base defaults to http://127.0.0.1:8650/
import { createRequire } from 'node:module';
const requireFromTemper = createRequire('/home/shinelay/temper-ai/frontend/package.json');
const { chromium } = requireFromTemper('playwright');

const docId = process.argv[2];
const base = process.argv[3] || 'http://127.0.0.1:8650/';
if (!docId) { console.error('usage: node check_showtell.mjs <doc_id> [base]'); process.exit(2); }

const browser = await chromium.launch();
const results = {};
let failed = false;
for (const [label, viewport] of [['1440', { width: 1440, height: 900 }], ['390', { width: 390, height: 844 }]]) {
  const page = await browser.newPage({ viewport });
  const errors = [];
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.goto(`${base}#/d/${docId}`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(2500);
  const frameEl = await page.$('iframe[data-testid="html-preview-iframe"]');
  if (!frameEl) { results[label] = { iframe: false, errors }; failed = true; await page.close(); continue; }
  const frame = await frameEl.contentFrame();
  // Scroll the page inside the frame so lazy images (none expected) and every figure get a chance to load.
  await frame.evaluate(async () => { for (let y = 0; y < document.body.scrollHeight; y += 600) { window.scrollTo(0, y); await new Promise((r) => setTimeout(r, 60)); } window.scrollTo(0, 0); });
  await page.waitForTimeout(1200);
  const drawn = await frame.evaluate(() => {
    const main = document.querySelector('main[data-st-state="default"]');
    const imgs = [...document.querySelectorAll('main img')];
    return {
      mainVisible: !!main && getComputedStyle(main).display !== 'none' && main.offsetHeight > 0,
      mainTextLength: (main?.innerText || '').length,
      images: imgs.length,
      imagesLoaded: imgs.filter((i) => i.complete && i.naturalWidth > 0).length,
      broken: imgs.filter((i) => !(i.complete && i.naturalWidth > 0)).map((i) => i.getAttribute('src')),
      srcs: imgs.map((i) => i.currentSrc || i.src),
      docWidth: document.documentElement.scrollWidth,
      frameWidth: window.innerWidth,
    };
  });
  const statuses = [];
  for (const src of [...new Set(drawn.srcs)]) {
    const res = await page.request.get(src);
    statuses.push(res.status());
  }
  drawn.pictureStatuses = statuses;
  delete drawn.srcs;
  await page.screenshot({ path: `/tmp/rc170/st-${label}-default.png` });
  const states = {};
  for (const state of ['loading', 'empty']) {
    // The viewer's own state switch (bottom right): buttons labelled Normal / Loading / Empty.
    const button = page.getByRole('button', { name: state === 'loading' ? 'Loading' : 'Empty', exact: true });
    if (!(await button.count())) { states[state] = 'no switch button found'; failed = true; continue; }
    await button.first().click();
    await page.waitForTimeout(500);
    states[state] = await frame.evaluate((s) => {
      const view = document.querySelector(`[data-st-state="${s}"]`);
      return view && getComputedStyle(view).display !== 'none' && !view.hidden ? `shown: ${view.innerText.replace(/\s+/g, ' ').slice(0, 60)}` : 'NOT shown';
    }, state);
    await page.screenshot({ path: `/tmp/rc170/st-${label}-${state}.png` });
  }
  const back = page.getByRole('button', { name: 'Normal', exact: true });
  if (await back.count()) await back.first().click();
  if (Object.values(states).some((s) => !String(s).startsWith('shown'))) failed = true;
  results[label] = { iframe: true, ...drawn, states, errors };
  if (!drawn.mainVisible || drawn.imagesLoaded !== drawn.images || statuses.some((s) => s !== 200) || errors.length) failed = true;
  await page.close();
}
console.log(JSON.stringify(results, null, 1));
await browser.close();
process.exit(failed ? 1 : 0);
