// The run the user actually took: answer gate 1 in the UI, then check that
// gate 2 opens by itself AND is readable. Gate 2 is the one no test reached:
// its input is the human's own free-text answer, which is what broke it.
import { chromium } from '@playwright/test';

const BASE = process.env.BASE ?? 'https://temper-dev.wai2shine.com';
const RUN = process.env.RUN;
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
const fail = [];

await page.goto(`${BASE}/app/workflow/${RUN}`, { waitUntil: 'networkidle' });
await page.waitForTimeout(3000);

const modal = () => page.locator('[role="dialog"], .fixed').filter({ hasText: 'Approval needed' }).first();

console.log('--- GATE 1 ---');
console.log('opened by itself :', await modal().count() > 0);
const body1 = await modal().innerText();
console.log('shows raw JSON   :', body1.includes('"questions"') || body1.trimStart().startsWith('{'));

// Answer it the way a person does: click options, type, approve.
const option = (name) => modal().locator('button').filter({ hasText: name }).first();
await option('Canary, 10% for 30 minutes').click();
await option('Fresh backup').click();
const box = page.locator('textarea, input[type="text"]').last();
if (await box.count()) await box.fill('tonight after 9');
await page.locator('button', { hasText: /Approve/ }).first().click();

// Gate 2 arrives on the poll, while the page is already open.
await page.waitForTimeout(9000);

console.log('--- GATE 2 (the one that broke) ---');
const open2 = await modal().count() > 0;
console.log('opened by itself :', open2);
if (!open2) fail.push('gate 2 did not open by itself');

if (open2) {
  const body2 = await modal().innerText();
  const rawJson = body2.includes('"questions"') || body2.includes('\\n') || body2.includes('"summary"');
  console.log('shows raw JSON   :', rawJson);
  if (rawJson) fail.push('gate 2 showed raw JSON');

  for (const want of ['Run the migration against production now?', 'Canary, 10% for 30 minutes', 'Dry-run only', 'Fresh backup']) {
    const seen = body2.includes(want);
    console.log(`  contains "${want.slice(0, 38)}":`, seen);
    if (!seen) fail.push(`gate 2 missing: ${want}`);
  }
  // The answers from round one must be visible: that is the context for
  // the decision being asked now.
  console.log('  carries round-one answers:', body2.includes('tonight after 9'));
}

await page.screenshot({ path: '/tmp/gate2.png' });
console.log(fail.length ? `\nFAIL: ${fail.join('; ')}` : '\nPASS');
await browser.close();
process.exit(fail.length ? 1 : 0);
