// Walk the path a human takes: land on /app/, spot the parked run, click it,
// and check the modal opens. Every earlier check deep-linked straight to a run
// URL -- the one thing the user never does.
import { chromium } from '@playwright/test';

const BASE = process.env.BASE ?? 'https://temper-dev.wai2shine.com';
const browser = await chromium.launch();
const context = await browser.newContext();  // cold cache, no storage
const page = await context.newPage();

const errors = [];
page.on('pageerror', e => errors.push(`PAGEERROR: ${e.message}`));

console.log(`--- landing on ${BASE}/app/ ---`);
await page.goto(`${BASE}/app/`, { waitUntil: 'networkidle' });
await page.waitForTimeout(2500);

// Does the landing page say a human is needed, without being told where to look?
const needsYou = page.locator('text=needs you').first();
console.log('"needs you" visible on landing:', await needsYou.count() > 0);
console.log('"waiting" filter tab present  :', await page.locator('button', { hasText: /^waiting$/ }).count() > 0);
await page.screenshot({ path: '/tmp/journey-1-landing.png', fullPage: false });

// Click the row the badge is on -- as a person would.
const row = page.locator('[role="link"]').filter({ hasText: 'needs you' }).first();
console.log('parked row found:', await row.count() > 0);
await row.click();
await page.waitForTimeout(3500);

console.log('url after click:', page.url());
const modal = page.locator('text=Approval needed').first();
const open = await modal.count() > 0;
console.log('MODAL OPENED BY ITSELF:', open);

if (open) {
  for (const probe of ['ROLLOUT', 'GATES', 'WINDOW', 'Approve', 'Later']) {
    console.log(`  "${probe}":`, await page.locator(`text=${probe}`).count() > 0);
  }
}
await page.screenshot({ path: '/tmp/journey-2-modal.png', fullPage: false });

if (errors.length) {
  console.log('--- page errors ---');
  errors.slice(0, 10).forEach(e => console.log(' ', e));
}
await browser.close();
