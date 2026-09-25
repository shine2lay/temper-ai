// Walk a dispatch run's DAG in a real browser and measure what is drawn.
//
// A screenshot alone lets a bug hide in plain sight (a node drawn twice looks
// like "a busy graph"), so this also reads the DOM: every card's name and box,
// every edge, and checks the things a correct dispatch DAG must satisfy.
//
//   RUN=<id> EXPECT=root,level_two,level_three SHOT=/tmp/x.png node dispatch_dag_check.mjs
import { chromium } from '@playwright/test';

const BASE = process.env.BASE ?? 'https://temper-dev.wai2shine.com';
const RUN = process.env.RUN;
const EXPECT = (process.env.EXPECT ?? '').split(',').filter(Boolean);
const SHOT = process.env.SHOT ?? '/tmp/dispatch_dag.png';

const browser = await chromium.launch();
const page = await (await browser.newContext({ viewport: { width: 1600, height: 1000 } })).newPage();
const consoleErrors = [];
page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()); });
page.on('pageerror', (e) => consoleErrors.push(`pageerror: ${e.message}`));

await page.goto(`${BASE}/app/workflow/${RUN}`, { waitUntil: 'networkidle' });
await page.waitForTimeout(3500);

const drawn = await page.evaluate(() => {
  const cards = [...document.querySelectorAll('.react-flow__node')].map((el) => {
    const r = el.getBoundingClientRect();
    return {
      id: el.getAttribute('data-id'),
      type: [...el.classList].find((c) => c.startsWith('react-flow__node-'))?.replace('react-flow__node-', ''),
      text: el.innerText.split('\n').slice(0, 3).join(' | '),
      lines: el.innerText.split('\n').map((s) => s.trim()),
      x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height),
      parent: el.closest('.react-flow__node:not(:scope)')?.getAttribute('data-id') ?? null,
    };
  });
  const edges = [...document.querySelectorAll('.react-flow__edge')].map((el) => ({
    id: el.getAttribute('data-testid') ?? el.id,
    cls: el.getAttribute('class'),
  }));
  return { cards, edges };
});

console.log(`--- ${drawn.cards.length} cards ---`);
for (const c of drawn.cards) console.log(`  [${c.type}] ${c.id}  @${c.x},${c.y} ${c.w}x${c.h}  "${c.text}"`);
console.log(`--- ${drawn.edges.length} edges ---`);
for (const e of drawn.edges) console.log(`  ${e.id}  (${e.cls})`);

const fail = [];
// 1. Every expected node is on screen, exactly once.
for (const name of EXPECT) {
  // The name's own line, not "by <name>" on a child's card.
  const hits = drawn.cards.filter((c) => c.lines.some((l) => l === name || l === `⚡ ${name}`));
  if (hits.length !== 1) fail.push(`"${name}" drawn ${hits.length}x`);
}
// 2. No two cards overlap (the old failure: everything piled at one point).
const agents = drawn.cards.filter((c) => c.w > 0 && c.h > 0);
for (let i = 0; i < agents.length; i++) {
  for (let j = i + 1; j < agents.length; j++) {
    const a = agents[i], b = agents[j];
    const inside = (p, q) => p.x >= q.x && p.y >= q.y && p.x + p.w <= q.x + q.w && p.y + p.h <= q.y + q.h;
    if (inside(a, b) || inside(b, a)) continue; // a group containing its member is fine
    const overlap = a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
    if (overlap) fail.push(`overlap: ${a.id} / ${b.id}`);
  }
}
// 3. Every dispatch hop has an edge.
if (EXPECT.length > 1 && drawn.edges.length < EXPECT.length - 1) {
  fail.push(`${drawn.edges.length} edges for a ${EXPECT.length}-node chain`);
}
if (consoleErrors.length) fail.push(`console errors: ${consoleErrors.slice(0, 3).join(' || ')}`);

await page.screenshot({ path: SHOT, fullPage: false });
console.log(fail.length ? `\nFAIL:\n  - ${fail.join('\n  - ')}` : '\nPASS');
await browser.close();
process.exit(fail.length ? 1 : 0);
