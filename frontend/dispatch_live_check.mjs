// Watch a dispatch run the way a person with the page open would -- no
// reloads, only the page's own WebSocket and polling -- and check what is
// drawn against what the API says happened, once a second, until the run
// ends. Exits 1 on any failure.
//
//   node dispatch_live_check.mjs                          # starts ui_dispatch_rounds
//     (a local fixture in the gitignored configs/*/local dirs: one dispatcher,
//      four rounds of five slow script children; any dispatch workflow will do)
//   RUN=<id> node dispatch_live_check.mjs                 # watches a run
//   WORKFLOW=ui_dispatch_slowkids INPUTS='{"items":["a","b","c"]}' node dispatch_live_check.mjs
//
// Checks, per sample (a status is allowed one sample to catch up):
//   status   every card shows the status the API reports for its node
//   present  every node the API has started has exactly one card
//   edges    edge ids are unique; every dispatched node has an edge from its
//            dispatcher and sits to its right
//   counts   the summary bar's Stages/Agents totals equal the API's
//   width    the drawing is no wider than MAX_WIDTH (flow units)
//   covered  nothing sits over the middle of the canvas (a panel nobody
//            opened covered it on every load, and no other check noticed)
//   blink    counted on every animation frame, not per sample: the number
//            of edges never drops while the number of cards holds (edges
//            vanished for a frame or more on each status change, and a
//            once-a-second sample only caught it by luck)
//   console  no errors in the page console
// Screenshots at SHOTS seconds and at the end: /tmp/live_<TAG>_<s>s.png
import { chromium, request as pwRequest } from '@playwright/test';

const BASE = process.env.BASE ?? 'https://temper-dev.wai2shine.com';
const API = process.env.API ?? 'http://127.0.0.1:8420';
const WORKFLOW = process.env.WORKFLOW ?? 'ui_dispatch_rounds';
const INPUTS = JSON.parse(process.env.INPUTS ?? '{"items":["alpha","bravo","charlie","delta","echo"]}');
const SHOTS = (process.env.SHOTS ?? '3,9,17,31,45').split(',').map(Number);
const MAX_WIDTH = Number(process.env.MAX_WIDTH ?? 3600);
const TAG = process.env.TAG ?? WORKFLOW;
const TERMINAL = new Set(['completed', 'failed', 'skipped', 'cancelled', 'timeout']);

const api = await pwRequest.newContext({ baseURL: API });
let RUN = process.env.RUN;
if (!RUN) {
  const res = await api.post('/api/runs', { data: { workflow: WORKFLOW, inputs: INPUTS } });
  const body = await res.json();
  RUN = body.execution_id ?? body.id;
  if (!RUN) throw new Error(`could not start ${WORKFLOW}: ${JSON.stringify(body)}`);
}
console.log(`run ${RUN}  ${BASE}/app/workflow/${RUN}`);

/** The API's view: every node in the tree, by name (latest wins). */
async function truth() {
  const wf = await (await api.get(`/api/workflows/${RUN}`)).json();
  const nodes = new Map();
  let agents = 0;
  const walk = (list) => {
    for (const n of list ?? []) {
      nodes.set(n.name, { status: n.status, by: n.dispatched_by, id: n.id });
      agents += (n.agents?.length ?? 0) || (n.agent ? 1 : 0);
      walk(n.child_nodes);
    }
  };
  walk(wf.nodes);
  return { status: wf.status, nodes, agents };
}

const browser = await chromium.launch();
const page = await (await browser.newContext({ viewport: { width: 1600, height: 1000 } })).newPage();
const consoleErrors = [];
page.on('pageerror', (e) => consoleErrors.push(e.message));
page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()); });

const t0 = Date.now();
const secs = () => ((Date.now() - t0) / 1000).toFixed(1);
await page.goto(`${BASE}/app/workflow/${RUN}`, { waitUntil: 'domcontentloaded' });
await page.evaluate(() => {
  const drops = [];
  window.__edgeDrops = drops;
  let last = { e: 0, c: 0 };
  const t0 = performance.now();
  const tick = () => {
    const e = document.querySelectorAll('.react-flow__edge').length;
    const c = document.querySelectorAll('.react-flow__node').length;
    if (e < last.e && c >= last.c) {
      drops.push({ t: Math.round(performance.now() - t0), from: last.e, to: e, cards: c });
    }
    last = { e, c };
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
});

/** What the page draws. Positions are flow coordinates (zoom-independent). */
function readPage() {
  return page.evaluate(() => {
    const cards = [...document.querySelectorAll('.react-flow__node')].map((el) => {
      const card = el.querySelector('[data-testid="agent-card"], [data-testid="agent-pill"]');
      const m = /translate\(\s*(-?[\d.]+)px,\s*(-?[\d.]+)px\)/.exec(el.style.transform ?? '');
      return {
        id: el.getAttribute('data-id'),
        name: card?.getAttribute('data-name') ?? null,
        status: card?.getAttribute('data-status') ?? null,
        pill: card?.getAttribute('data-testid') === 'agent-pill',
        x: m ? Number(m[1]) : NaN,
        w: el.offsetWidth,
      };
    });
    const edges = [...document.querySelectorAll('.react-flow__edge')].map(
      (el) => el.getAttribute('data-id') ?? (el.getAttribute('data-testid') ?? '').replace(/^rf__edge-/, ''),
    );
    const text = document.body.innerText.replace(/\s+/g, ' ');
    const frac = (label) => {
      const m = new RegExp(`${label}\\s*(\\d+)\\s*/\\s*(\\d+)`).exec(text);
      return m ? { done: Number(m[1]), total: Number(m[2]) } : null;
    };
    const rf = document.querySelector('.react-flow');
    let covered = null;
    if (rf) {
      const r = rf.getBoundingClientRect();
      const hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
      if (hit && !rf.contains(hit)) {
        const over = hit.closest('[role="dialog"], aside, section') ?? hit;
        covered = (over.innerText ?? over.tagName).split('\n')[0].slice(0, 40);
      }
    }
    return { cards, edges, stages: frac('Stages'), agents: frac('Agents'), covered };
  });
}

const failures = new Map();   // check -> [messages]
const fail = (check, msg) => {
  const list = failures.get(check) ?? [];
  if (list.length < 6) list.push(`@${secs()}s ${msg}`);
  failures.set(check, list);
};

let prevBad = new Set();        // status/present problems seen last sample
let lastApi = null;
let endedAt = null;
const shotsLeft = [...SHOTS];

while (true) {
  const [view, api1] = await Promise.all([readPage(), truth()]);
  lastApi = api1;
  const bad = new Set();
  const byName = new Map();
  for (const c of view.cards) {
    if (!c.name) continue;
    if (byName.has(c.name)) fail('present', `two cards for ${c.name}`);
    byName.set(c.name, c);
  }

  // status + present (one sample of grace: the WS may be a beat behind)
  for (const [name, n] of api1.nodes) {
    if (n.status === 'pending') continue;
    const card = byName.get(name);
    if (!card) {
      const key = `missing:${name}`;
      bad.add(key);
      if (prevBad.has(key)) fail('present', `no card for ${name} (API: ${n.status})`);
      continue;
    }
    const shown = card.status;
    const wrong = TERMINAL.has(n.status) !== TERMINAL.has(shown ?? '') || (TERMINAL.has(n.status) && shown !== n.status);
    if (wrong) {
      const key = `status:${name}`;
      bad.add(key);
      if (prevBad.has(key)) fail('status', `${name} shows ${shown}, API says ${n.status}`);
    }
    if (card.pill && n.status !== 'skipped') {
      const key = `pill:${name}`;
      bad.add(key);
      if (prevBad.has(key)) fail('present', `${name} drawn as an empty pill (API: ${n.status})`);
    }
  }
  prevBad = bad;

  // edges
  if (new Set(view.edges).size !== view.edges.length) {
    fail('edges', `${view.edges.length} edges, ${new Set(view.edges).size} unique`);
  }
  const edgeSet = new Set(view.edges);
  for (const [name, n] of api1.nodes) {
    if (!n.by) continue;
    const child = byName.get(name);
    const parent = byName.get(n.by);
    if (!child || !parent) continue;
    if (!edgeSet.has(`e-${parent.id}-${child.id}`)) {
      const near = view.edges.filter((e) => e.includes(child.id)).join(' ') || 'none';
      fail('edges', `no edge ${n.by} -> ${name} (want e-${parent.id}-${child.id}; edges into it: ${near})`);
    }
    if (!(child.x > parent.x)) fail('edges', `${name} (x=${child.x}) not right of ${n.by} (x=${parent.x})`);
  }

  // counts
  const started = [...api1.nodes.values()].filter((n) => n.status !== 'pending').length;
  if (view.stages && Math.abs(view.stages.total - started) > 0) {
    const key = 'count:stages';
    if (prevBad.has(key) || bad.has(key)) fail('counts', `Stages total ${view.stages.total}, API ${started}`);
    bad.add(key);
  }
  if (view.agents && view.agents.total !== api1.agents) {
    const key = 'count:agents';
    if (prevBad.has(key) || bad.has(key)) fail('counts', `Agents total ${view.agents.total}, API ${api1.agents}`);
    bad.add(key);
  }

  if (view.covered) fail('covered', `canvas covered by "${view.covered}"`);

  // width
  const xs = view.cards.filter((c) => Number.isFinite(c.x));
  if (xs.length) {
    const width = Math.max(...xs.map((c) => c.x + c.w)) - Math.min(...xs.map((c) => c.x));
    if (width > MAX_WIDTH) fail('width', `drawing ${Math.round(width)} wide (max ${MAX_WIDTH})`);
  }

  const t = (Date.now() - t0) / 1000;
  const running = view.cards.filter((c) => c.status === 'running').map((c) => c.name);
  console.log(`@${t.toFixed(1)}s api=${api1.status} nodes=${api1.nodes.size} cards=${view.cards.length} edges=${view.edges.length}`
    + ` stages=${view.stages ? `${view.stages.done}/${view.stages.total}` : '-'}`
    + ` agents=${view.agents ? `${view.agents.done}/${view.agents.total}` : '-'} running=[${running.join(',')}]`);

  while (shotsLeft.length && t >= shotsLeft[0]) {
    await page.screenshot({ path: `/tmp/live_${TAG}_${shotsLeft.shift()}s.png` });
  }
  if (TERMINAL.has(api1.status) && endedAt === null) endedAt = Date.now();
  if (endedAt !== null && Date.now() - endedAt > 4000) break;
  if (t > 300) { fail('status', 'run did not finish within 300s'); break; }
  await page.waitForTimeout(1000);
}

await page.screenshot({ path: `/tmp/live_${TAG}_end.png` });
const drops = await page.evaluate(() => window.__edgeDrops);
for (const d of drops) fail('blink', `edges ${d.from} -> ${d.to} with ${d.cards} cards (frame at ${(d.t / 1000).toFixed(2)}s)`);
if (drops.length) console.log(`blink: ${drops.length} frames where edges dropped`);
if (consoleErrors.length) fail('console', consoleErrors.slice(0, 3).join(' | '));

console.log(`\nrun ${lastApi.status}, ${lastApi.nodes.size} nodes, ${lastApi.agents} agents`);
for (const check of ['status', 'present', 'edges', 'blink', 'counts', 'width', 'covered', 'console']) {
  const list = failures.get(check);
  console.log(`${list ? 'FAIL' : 'ok  '} ${check}${list ? `\n       ${list.join('\n       ')}` : ''}`);
}
await browser.close();
await api.dispose();
process.exit(failures.size ? 1 : 0);
