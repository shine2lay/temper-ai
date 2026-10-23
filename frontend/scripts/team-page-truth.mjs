#!/usr/bin/env node
/**
 * Team page truth check: does the Team page show what Temper's own records hold?
 *
 * Opens the Team list and every Project's run view in headless Chromium and reads what a
 * person sees there, by role, label and text (never the Team API, never CSS classes). Then
 * it fetches Temper's own records for each Project and compares six fields: members, state,
 * waits, cost so far, result (with the words given with a stop) and whether each member card
 * says its member is at work, plus whether the Team list shows the Project at all. Each field is
 * judged by the one record Temper names as its truth (the cost: the recorded model calls; the
 * stop words: the team's stop record; a member at work: a running turn in the turns record); where
 * Temper's other records of it hold something else, the report lists them under "Temper's
 * records disagree", for the temper role. Every Project is every team-trial-* run in the run
 * list, paged to its total. The comparing is scripts/teamPageTruth.ts (tests:
 * src/__tests__/teamPageTruth.test.ts).
 *
 * Read only: the page may send nothing but GET (anything else is aborted and reported), and
 * the records are GETs. No model calls.
 *
 *   node scripts/team-page-truth.mjs [--base <url>] [--out <folder> [--name <file stem>]] [<execution id or its start> ...]
 *     (from frontend/) --base: Temper's address, default http://127.0.0.1:8420. Without ids, every
 *     Project. --out writes <stem>.json and <stem>.md there (stem: --name, default
 *     team-page-truth-<time>); without it the Markdown goes to stdout.
 *     Exit 0: the page shows what the records it is judged by hold (Temper's records that
 *     disagree with each other are listed, not failed); 1: the page mismatches a record, or a
 *     record is missing ("no record"); 2: the check couldn't run.
 *   Chromium keeps a socket under TMPDIR, and a long TMPDIR makes it abort ("Socket path too
 *   long"): run it with a short one, e.g. TMPDIR=/tmp.
 */
import { mkdirSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { chromium } from '@playwright/test';
import { compareAll, exitCode, numberOf, pageStateClass, runDetail, stopRecord, toMarkdown, turnsRecord } from './teamPageTruth.ts';

const DEFAULT_BASE = 'http://127.0.0.1:8420';
const PAGE = 200;
const READ_TIMEOUT = 45_000;
const ENDED = new Set(['done', 'stopped', 'failed', 'didnt_start']);
const LIVE_STATUSES = new Set(['running', 'pending', 'queued', 'waiting', 'paused']);
/** The Team list's state words (frontend/src/lib/teamText.ts TEAM_STATE_WORDS). */
const STATE_WORDS = [
  'Starting',
  'Running',
  'Paused',
  'Quiet',
  'Member waiting',
  'Settings changed',
  'Interrupted',
  'Done',
  'Stopped',
  'Failed',
  "Didn't start",
];
/** A rounds run's outcome card is a region named by its title (frontend/src/lib/teamOutcome.ts). */
const OUTCOME_TITLES = /^(Done: the leader's version was approved|Stopped|Failed|Didn't start)$/;
/** A stop-words quote is a figure named by its caption (frontend/src/lib/teamText.ts ownerWordsLabel). */
const WORDS_CAPTION = /^(Your words|Words from an unknown caller|.+['\u2019]s words)$/;

const USAGE = `Usage: node scripts/team-page-truth.mjs [--base <url>] [--out <folder> [--name <stem>]] [<execution id> ...]`;

function parseArgs(argv) {
  const args = { base: DEFAULT_BASE, out: null, name: null, ids: [], help: false };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--base') args.base = argv[++i];
    else if (a === '--out') args.out = argv[++i];
    else if (a === '--name') args.name = argv[++i];
    else if (a === '-h' || a === '--help') args.help = true;
    else if (a.startsWith('-')) throw new Error(`unknown option ${a}\n${USAGE}`);
    else args.ids.push(a);
  }
  if (!args.base) throw new Error(`--base needs an address\n${USAGE}`);
  args.base = args.base.replace(/\/+$/, '');
  return args;
}

// ------------------------------------------------------------------ records (GET only)

async function getJson(url) {
  try {
    const res = await fetch(url, { headers: { accept: 'application/json' } });
    if (!res.ok) return { ok: false, status: res.status, body: null };
    return { ok: true, status: res.status, body: await res.json() };
  } catch (e) {
    return { ok: false, status: 0, body: null, error: String(e) };
  }
}

/** Every run in the run list, paged until its total. */
async function readRunList(base) {
  const byId = new Map();
  let total = 0;
  for (let offset = 0; ; offset += PAGE) {
    const r = await getJson(`${base}/api/workflows?limit=${PAGE}&offset=${offset}`);
    if (!r.ok) throw new Error(`the run list (GET /api/workflows) answered ${r.status || r.error}`);
    total = Number(r.body.total ?? 0);
    const runs = r.body.runs ?? [];
    for (const run of runs) byId.set(run.id, run);
    if (runs.length === 0 || offset + runs.length >= total) break;
  }
  return { total, runs: [...byId.values()] };
}

/** The members a Project was made with: its workflow config's agents, their roles, the leader. */
async function membersOf(base, workflow) {
  const node = (workflow?.nodes ?? []).find((n) => Array.isArray(n.agents) && n.agents.length > 0);
  if (!node) return null;
  const leader = node.strategy_config?.mode?.leader ?? null;
  const prefix = `${workflow.name}-`;
  const out = [];
  for (const entry of node.agents) {
    const ref = typeof entry === 'string' ? entry : String(entry?.name ?? '');
    const r = await getJson(`${base}/api/studio/configs/agent/${encodeURIComponent(ref)}`);
    const name = r.ok && r.body?.agent?.name ? String(r.body.agent.name) : ref.startsWith(prefix) ? ref.slice(prefix.length) : ref;
    out.push({ name, role: r.ok ? (r.body?.agent?.role ?? null) : null, leader: leader !== null && name === leader });
  }
  return out;
}

function waitOf(g) {
  const header = (g.questions ?? []).map((q) => q?.header).find(Boolean) ?? '';
  const m = /^(.+?) asks$/.exec(String(header).trim());
  return { node: String(g.node_name ?? ''), asker: m ? m[1] : null };
}

async function readRecords(base, run) {
  const id = encodeURIComponent(run.id);
  const [detail, agents, gates, decisions, wf, team] = await Promise.all([
    getJson(`${base}/api/workflows/${id}`),
    getJson(`${base}/api/workflows/${id}/agents`),
    getJson(`${base}/api/runs/${id}/gates`),
    getJson(`${base}/api/runs/${id}/decisions`),
    getJson(`${base}/api/studio/configs/workflow/${encodeURIComponent(run.workflow_name)}`),
    // The team's own record of the run: its owner_actions hold each stop, with the words given (detail.reason).
    getJson(`${base}/api/team/runs/${id}`),
  ]);
  return {
    executionId: run.id,
    workflow: run.workflow_name,
    status: run.status,
    costUsd: numberOf(run.total_cost_usd),
    detail: detail.ok ? runDetail(detail.body ?? {}) : null,
    turns: agents.ok ? turnsRecord(agents.body?.agents ?? []) : null,
    members: wf.ok ? await membersOf(base, wf.body?.workflow) : null,
    openWaits: gates.ok ? (gates.body?.gates ?? []).map(waitOf) : null,
    waitingDecisions: decisions.ok ? (decisions.body?.decisions ?? []).filter((d) => d.status === 'waiting').length : null,
    stop: team.ok ? stopRecord(team.body) : null,
    stopRead: team.ok,
  };
}

/** The Team API's view, read only to say where a gap most likely comes from. */
async function readTeamApi(base, ids) {
  const listed = new Map();
  for (let offset = 0; ; offset += PAGE) {
    const r = await getJson(`${base}/api/team/trials?limit=${PAGE}&offset=${offset}`);
    if (!r.ok) break;
    const trials = r.body?.trials ?? [];
    for (const t of trials) listed.set(t.execution_id, t);
    if (trials.length === 0 || offset + trials.length >= Number(r.body?.total ?? 0)) break;
  }
  const out = {};
  for (const id of ids) {
    const t = listed.get(id) ?? null;
    const r = await getJson(`${base}/api/team/runs/${encodeURIComponent(id)}`);
    const run = r.ok ? r.body : null;
    // A member's state: flow members carry state, rounds members activity.
    const members = run?.members
      ? run.members.map((m) => ({
          name: m.name,
          role: m.role ?? null,
          leader: Boolean(m.leader),
          costUsd: numberOf(m.cost_usd),
          state: m.state ?? m.activity ?? null,
        }))
      : t?.members
        ? t.members.map((m) => ({ name: m.name, role: m.role ?? null, leader: m.name === t.leader, costUsd: null, state: null }))
        : null;
    out[id] = {
      listed: listed.has(id),
      members,
      state: run?.state ?? t?.state ?? null,
      runStatus: run?.run_status ?? t?.run_status ?? null,
      costUsd: numberOf(run?.cost_usd ?? t?.cost_usd),
      openWaits: Array.isArray(run?.open_waits) ? run.open_waits.length : null,
      decision: run?.outcome?.decision ?? t?.decision ?? null,
      reason: run?.outcome?.reason ?? run?.phase?.reason ?? null,
      ownerWords: run?.outcome?.owner_words ? String(run.outcome.owner_words) : null,
    };
  }
  return out;
}

// ------------------------------------------------------------------ the page (what a person sees)

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** Read until two reads 700 ms apart agree (a live page moves), at most a few seconds. */
async function steady(read, tries = 6) {
  let last = JSON.stringify(await read());
  for (let i = 0; i < tries; i++) {
    await sleep(700);
    const next = JSON.stringify(await read());
    if (next === last) break;
    last = next;
  }
  return JSON.parse(last);
}

async function until(check, what, timeout = READ_TIMEOUT) {
  const end = Date.now() + timeout;
  for (;;) {
    if (await check()) return;
    if (Date.now() > end) throw new Error(`timed out waiting for ${what}`);
    await sleep(250);
  }
}

/** In the page: the Team list's rows (each main row, then its re-runs and forks). */
function readListInPage(ul, stateWords) {
  const text = (el) => (el.textContent || '').replace(/\s+/g, ' ').trim();
  const idOf = (el) => {
    const m = /\/team\/runs\/([^/?#]+)/.exec(el.getAttribute('href') || '');
    return m ? decodeURIComponent(m[1]) : null;
  };
  const person = (p, leader) => {
    const m = /^(.*?) \(([^()]*)\)$/.exec(p.trim());
    return { name: (m ? m[1] : p).trim(), role: m ? m[2].trim() : null, leader, cost: null };
  };
  const people = (s) => {
    const out = [];
    for (const part of s.split(' \u00b7 ').slice(1)) {
      if (part.startsWith('Leader ')) out.unshift(person(part.slice(7), true));
      else for (const p of part.split(', ')) if (p.trim()) out.push(person(p, false));
    }
    return out;
  };
  const readRow = (root, skip, subRow) => {
    const own = [...root.querySelectorAll('*')].filter((el) => !skip || !skip.contains(el));
    const link = own.find((el) => el.tagName === 'A' && idOf(el));
    if (!link) return null;
    const texts = own.map(text);
    const who = own.find((el) => el.tagName === 'P' && / \u00b7 Leader /.test(text(el)));
    const phrase = texts.find((t) => /^run list: /.test(t));
    const cost = own.filter((el) => el.tagName === 'P').map(text).find((t) => /^Cost\s/.test(t));
    return {
      executionId: idOf(link),
      subRow,
      members: subRow || !who ? [] : people(text(who)),
      stateWord: texts.find((t) => stateWords.includes(t)) ?? null,
      needsYou: texts.includes('needs you'),
      runListWord: phrase ? phrase.replace(/^run list:\s*/, '') : null,
      cost: cost ? cost.replace(/^Cost\s*/, '') : null,
    };
  };
  const rows = [];
  for (const li of ul.children) {
    if (li.tagName !== 'LI') continue;
    const subs = li.querySelector('[aria-label="Re-runs and forks"]');
    const head = readRow(li, subs, false);
    if (head) rows.push(head);
    if (subs) {
      for (const s of subs.children) {
        const r = readRow(s, null, true);
        if (r) rows.push(r);
      }
    }
  }
  return rows;
}

async function readTeamList(page, base) {
  await page.goto(`${base}/app/team`, { waitUntil: 'domcontentloaded' });
  const list = page.getByRole('list', { name: 'Projects', exact: true });
  const empty = page.getByRole('heading', { name: 'No projects yet', exact: true });
  await list.or(empty).first().waitFor({ timeout: READ_TIMEOUT });
  await page.waitForLoadState('networkidle', { timeout: 15_000 }).catch(() => {});
  if ((await list.count()) === 0) return { listTotal: 0, rows: [] };
  const rows = [];
  let listTotal = null;
  const showing = page.getByText(/^Showing \d/).first();
  for (let n = 0; n < 1000; n++) {
    rows.push(...(await steady(() => list.evaluate(readListInPage, STATE_WORDS))));
    const words = (await showing.count()) ? await showing.innerText() : '';
    const m = /of (\d+)/.exec(words);
    if (m) listTotal = Number(m[1]);
    const next = page.getByRole('button', { name: 'Next', exact: true });
    if ((await next.count()) === 0 || !(await next.isEnabled())) break;
    await next.click();
    await until(async () => (await showing.innerText()) !== words, 'the next page of the Team list');
  }
  return { listTotal, rows };
}

/** In the page: the flow view's Status band, its Now, You and Spend cells. */
function readStatusInPage(sec) {
  const cell = (label) => [...sec.querySelectorAll('h3')].find((h) => h.textContent.trim() === label)?.parentElement ?? null;
  const lines = (el) => (el ? el.innerText.split('\n').map((s) => s.trim()).filter(Boolean) : []);
  const paras = (el) => (el ? [...el.children].filter((c) => c.tagName === 'P').map((p) => p.innerText.replace(/\s+/g, ' ').trim()) : []);
  const now = cell('Now');
  return { now: paras(now), nowText: now ? now.innerText : null, you: lines(cell('You')), spend: lines(cell('Spend')) };
}

/** In the page: the flow view's member cards (only the layout on screen; the other one is hidden). */
function readCardsInPage(sec) {
  const out = [];
  for (const h of sec.querySelectorAll('h3')) {
    if (h.getClientRects().length === 0) continue;
    const li = h.closest('li');
    if (!li || !sec.contains(li)) continue;
    const head = h.innerText.split('\n').map((s) => s.trim()).filter(Boolean);
    const turns = [...li.querySelectorAll('p')].map((p) => p.innerText.replace(/\s+/g, ' ').trim()).find((t) => /\b\d+ turns?\b/.test(t)) ?? null;
    // The state chip: the line right after the name, role and leader tag.
    const next = h.nextElementSibling;
    const chip = next && next.tagName === 'P' ? next.innerText.replace(/\s+/g, ' ').trim() || null : null;
    out.push({ head, turns, chip });
  }
  return out;
}

const money = (s) => (s ? (/\$\d+(?:\.\d+)?/.exec(s)?.[0] ?? null) : null);

/** A chip's state, without its live duration ("Working \u00b7 2m" -> "Working"), which ticks every second. */
const chipWord = (s) => (s ? s.split(' \u00b7 ')[0].trim() || null : null);

/**
 * The stop-words quotes a person sees in a part of the page: figures named by their caption
 * ("Your words", "temper's words", "Words from an unknown caller"), the words in their blockquote.
 * The caption is read as written (its text is the figure's name), not as styled (capitals).
 */
async function readWords(scope) {
  const out = [];
  for (const figure of await scope.getByRole('figure', { name: WORDS_CAPTION }).all()) {
    if (!(await figure.isVisible())) continue;
    const label = (await figure.locator('figcaption').first().textContent()) ?? '';
    const quote = figure.getByRole('blockquote');
    const words = (await quote.count()) ? ((await quote.first().textContent()) ?? '') : '';
    out.push({ label: label.replace(/\s+/g, ' ').trim(), words });
  }
  return out;
}

async function readFlowOnce(page, id) {
  const status = page.getByRole('region', { name: 'Status', exact: true });
  const cells = await status.evaluate(readStatusInPage);
  const team = page.getByRole('region', { name: 'Team now', exact: true });
  const cards = (await team.count()) ? await team.evaluate(readCardsInPage) : null;
  const word = cells.now[0] ? cells.now[0].replace(/^Last seen:\s*/, '') : null;
  const ended = ENDED.has(pageStateClass(word));
  const title = cells.you[1] ?? '';
  const any = /^Needs you/i.test(title);
  const more = /and (\d+) more/.exec(title);
  const amount = cells.spend.slice(1).find((l) => /^\$\d/.test(l) || l === 'Not known') ?? null;
  return {
    executionId: id,
    kind: 'flow',
    problem: null,
    stateWord: word,
    members: cards
      ? cards.map(({ head, turns, chip }) => {
          const rest = head.slice(1);
          const leader = rest[rest.length - 1] === 'leader';
          return { name: head[0], role: (leader ? rest.slice(0, -1) : rest).join(' ') || null, leader, cost: money(turns), stateWord: chipWord(chip) };
        })
      : null,
    costs: amount ? [{ place: 'Spend', value: amount }] : [],
    waits: { any, count: any ? 1 + (more ? Number(more[1]) : 0) : 0, from: cells.you.map((l) => /^From (.+)$/.exec(l)?.[1]?.trim()).filter(Boolean) },
    outcomeWord: ended ? word : null,
    outcomeReason: ended ? cells.now.slice(1).join(' / ') || null : null,
    outcomeText: ended ? cells.nowText : null,
    // A stopped run's words, as the Status band quotes them.
    stopWords: await readWords(status),
  };
}

/** In the page: a rounds view's header (its state and cost) and its "Needs you" chips. */
function readRoundsHeadInPage() {
  const text = (el) => (el.textContent || '').replace(/\s+/g, ' ').trim();
  const live = [...document.querySelectorAll('[aria-live]')].map(text).find((t) => t.startsWith('Team state:'));
  const header = [...document.querySelectorAll('h1')].map((h) => h.closest('header')).find(Boolean);
  const m = header ? /\bCost( so far)?\s*(\$\d+(?:\.\d+)?)/.exec(text(header)) : null;
  const own = (el) => [...el.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent).join('').trim();
  return {
    stateWord: live ? live.replace(/^Team state:\s*/, '') : null,
    cost: m ? { place: m[1] ? 'header "Cost so far"' : 'header "Cost"', value: m[2] } : null,
    needsYou: [...document.querySelectorAll('body *')].filter((el) => own(el) === 'Needs you').length,
  };
}

function readRoundMembersInPage(sec) {
  return [...sec.querySelectorAll('li')].map((li) => ({
    lines: li.innerText.split('\n').map((s) => s.trim()).filter(Boolean),
    line: [...li.querySelectorAll('p')].map((p) => p.innerText.replace(/\s+/g, ' ').trim())[0] ?? '',
  }));
}

function readRegionInPage(sec) {
  const by = sec.getAttribute('aria-labelledby');
  return {
    title: by ? (document.getElementById(by)?.textContent ?? '').trim() : (sec.getAttribute('aria-label') ?? ''),
    lines: sec.innerText.split('\n').map((s) => s.trim()).filter(Boolean),
    text: sec.innerText,
  };
}

async function readRoundsOnce(page, id) {
  const head = await page.evaluate(readRoundsHeadInPage);
  const membersRegion = page.getByRole('region', { name: /^Members \(\d+\)$/ });
  const rows = await membersRegion.first().evaluate(readRoundMembersInPage);
  const outcomeRegion = page.getByRole('region', { name: OUTCOME_TITLES });
  const outcome = (await outcomeRegion.count()) ? await outcomeRegion.first().evaluate(readRegionInPage) : null;
  // innerText follows the page's text-transform ("TEMPER'S REASON"): find labels case aside.
  const after = (label) => {
    const i = outcome ? outcome.lines.findIndex((l) => l.toLowerCase() === label.toLowerCase()) : -1;
    return i >= 0 ? (outcome.lines[i + 1] ?? null) : null;
  };
  const costs = [];
  if (head.cost) costs.push(head.cost);
  const outcomeCost = after('Cost');
  if (outcomeCost) costs.push({ place: 'outcome "Cost"', value: outcomeCost });
  return {
    executionId: id,
    kind: 'rounds',
    problem: null,
    stateWord: head.stateWord,
    members: rows.map(({ lines, line }) => {
      const at = lines.findIndex((l) => l.replace(/\s+/g, ' ') === line);
      const top = at > 0 ? lines.slice(0, at) : lines;
      const middle = top.slice(1, -1);
      return {
        name: top[0],
        role: middle.filter((x) => x !== 'leader').join(' ') || null,
        leader: middle.includes('leader'),
        cost: money(line),
        // The activity chip closes the name line ("Working", "Idle", "Waiting on you", "Ended").
        stateWord: top.length > 1 ? top[top.length - 1] : null,
      };
    }),
    costs,
    waits: { any: head.needsYou > 0, count: null, from: [] },
    outcomeWord: outcome ? outcome.title : null,
    outcomeReason: outcome ? after("Temper's reason") : null,
    outcomeText: outcome ? outcome.text : null,
    // A stopped run's words, as the outcome card quotes them.
    stopWords: outcome ? await readWords(outcomeRegion.first()) : [],
  };
}

function problemView(id, problem) {
  return {
    executionId: id,
    kind: null,
    problem,
    stateWord: null,
    members: null,
    costs: [],
    waits: null,
    outcomeWord: null,
    outcomeReason: null,
    outcomeText: null,
    stopWords: [],
  };
}

async function readRunView(page, base, id) {
  const status = page.getByRole('region', { name: 'Status', exact: true });
  const rounds = page.getByRole('region', { name: /^Members \(\d+\)$/ });
  const notTeam = page.getByText("This run isn't a team project", { exact: true });
  // A busy machine can keep a view from loading in time: open it once more before calling it a problem.
  for (let attempt = 1; ; attempt++) {
    await page.goto(`${base}/app/team/runs/${encodeURIComponent(id)}`, { waitUntil: 'domcontentloaded' });
    try {
      // The flow view's Status band first shows empty cells while it loads: wait for the Now word.
      await until(async () => {
        if ((await rounds.count()) > 0 || (await notTeam.count()) > 0) return true;
        if ((await status.count()) === 0) return false;
        return (await status.evaluate(readStatusInPage)).now.length > 0;
      }, 'the run view');
      break;
    } catch {
      if (attempt >= 2) return problemView(id, 'the run view showed neither a Status band nor a Members card in 45 s, opened twice');
    }
  }
  if ((await notTeam.count()) > 0) return problemView(id, "it says \"This run isn't a team project\"");
  await page.waitForLoadState('networkidle', { timeout: 15_000 }).catch(() => {});
  if ((await rounds.count()) > 0) return steady(() => readRoundsOnce(page, id));
  return steady(() => readFlowOnce(page, id));
}

// ------------------------------------------------------------------ the check

function resolveIds(asked, runs) {
  return asked.map((a) => {
    const hits = runs.filter((r) => r.id === a || r.id.startsWith(a));
    if (hits.length !== 1) {
      throw new Error(`${a} ${hits.length ? 'names more than one' : 'is not a'} team-trial-* run in the run list`);
    }
    return hits[0].id;
  });
}

async function check(args) {
  const at = new Date().toISOString();
  const runList = await readRunList(args.base);
  const teamRuns = runList.runs.filter((r) => String(r.workflow_name ?? '').startsWith('team-trial-'));
  const only = args.ids.length ? resolveIds(args.ids, teamRuns) : null;
  const checked = teamRuns.filter((r) => !only || only.includes(r.id));
  const records = {};
  for (const run of checked) records[run.id] = await readRecords(args.base, run);

  const browser = await chromium.launch({ headless: true });
  const blocked = [];
  let pageRead;
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
    await context.route('**/*', (route) => {
      const req = route.request();
      if (req.method() === 'GET' || req.method() === 'HEAD') return route.continue();
      blocked.push(`${req.method()} ${new URL(req.url()).pathname}`);
      return route.abort();
    });
    const page = await context.newPage();
    const list = await readTeamList(page, args.base);
    const views = {};
    for (const run of checked) views[run.id] = await readRunView(page, args.base, run.id);
    pageRead = { ...list, views };
  } finally {
    await browser.close();
  }

  // A running Project's records move while its page is read: read them again, and let either count.
  const live = checked.filter((r) => LIVE_STATUSES.has(String(r.status)));
  let recordsAfter;
  if (live.length > 0) {
    const again = await readRunList(args.base);
    recordsAfter = {};
    for (const run of live) {
      const now = again.runs.find((r) => r.id === run.id) ?? run;
      recordsAfter[run.id] = await readRecords(args.base, now);
    }
  }
  const teamApi = await readTeamApi(args.base, checked.map((r) => r.id));
  const report = compareAll({
    base: args.base,
    at,
    runListTotal: runList.total,
    records,
    recordsAfter,
    page: pageRead,
    teamApi,
    only,
  });
  return { report, page: pageRead, records, recordsAfter: recordsAfter ?? null, teamApi, blockedRequests: blocked };
}

async function main() {
  let args;
  try {
    args = parseArgs(process.argv.slice(2));
  } catch (e) {
    console.error(String(e.message ?? e));
    return 2;
  }
  if (args.help) {
    console.log(USAGE);
    return 0;
  }
  let out;
  try {
    out = await check(args);
  } catch (e) {
    console.error(`team-page-truth: the check couldn't run: ${e?.message ?? e}`);
    return 2;
  }
  let md = toMarkdown(out.report);
  if (out.blockedRequests.length > 0) {
    md += `\nThe page tried ${out.blockedRequests.length} request(s) other than GET; all were aborted: ${[...new Set(out.blockedRequests)].join(', ')}.\n`;
  }
  if (args.out) {
    const dir = resolve(args.out);
    mkdirSync(dir, { recursive: true });
    const stem = args.name || `team-page-truth-${out.report.at.replace(/[:.]/g, '-')}`;
    writeFileSync(join(dir, `${stem}.json`), `${JSON.stringify(out, null, 2)}\n`);
    writeFileSync(join(dir, `${stem}.md`), md);
    console.error(`team-page-truth: wrote ${join(dir, `${stem}.md`)} and .json`);
  } else {
    process.stdout.write(md);
  }
  const t = out.report.totals;
  console.error(
    `team-page-truth: ${out.report.projects.length} Projects; ${t.match} match, ${t.mismatch} mismatch, ${t['no record']} no record; ` +
      `Temper's records disagree on ${out.report.disagreements.length}`,
  );
  return exitCode(out.report);
}

process.exitCode = await main();
