// Design #204: whole-build integration check of draft-a (RollCall option A, index.html built by build.py).
// Many tasks drew their screens into this one folder at the same time, so this looks for breakage BETWEEN screens:
//   1. every data-act in the source has a handler (static), and every open control (action-open, entry-open,
//      more-open, gloss-open, howto-step, ladder-open, open-roll, the ticket and screen opens) found on any screen,
//      clicked for real, draws something (the view changes, no "This screen is being drawn") without an error;
//      opens found inside what an open drew are clicked too (two levels);
//   2. no CSS class collisions: page.html's page-only rules (Today's desktop/phone layout) used by a screen's markup,
//      and a screen's rules that aren't scoped to the screen used by another file's markup;
//   3. the same figures everywhere: net liq, buying power, margin excess, interest a day 8.13, each position's
//      strike, expiry, contracts and shares, in the rendered text of every screen, state and open, and in the
//      Glossary's worked examples (fixtures/glossary.json) against fixture.json; and one price per stock (Design #208):
//      Browse's quote (fixtures/browse.json) equals every fixture's price/spot for the stock and every price a screen states;
//   4. no "Simulated"/"Real money" text outside [data-allow-real-money];
//   5. no visible text under 12px;
//   6. no horizontal overflow at 1440, 390 and 320 (layout width = device width, nothing spills past the view
//      unless an overflow box clips it);
//   7. no console or page errors in any screen, draft state or open.
// usage: node check-integration.mjs [--quick] [--static] [--dump=/tmp/texts.json]
//   --quick: one level of opens; --static: only the source checks (handlers, CSS); --dump: write every rendered text
//   exit 0 = everything passed
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import fs from 'node:fs';

const { chromium } = createRequire('/home/shinelay/temper-ai/frontend/package.json')('playwright');
const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(HERE, 'src');
const URL = 'file://' + path.join(HERE, 'index.html');
const QUICK = process.argv.includes('--quick');
const failures = [];
const notes = [];
const fail = (where, msg) => failures.push(`${where}: ${msg}`);

// ---------------------------------------------------------------- 1a. data-act handlers (static)
const screenFiles = fs.readdirSync(path.join(SRC, 'screens')).filter(f => f.endsWith('.js')).sort();
const pageHtml = fs.readFileSync(path.join(SRC, 'page.html'), 'utf8');
const sources = { 'page.html': pageHtml, ...Object.fromEntries(screenFiles.map(f => [f, fs.readFileSync(path.join(SRC, 'screens', f), 'utf8')])) };
{
  const used = new Map(), handled = new Set(['top-bell', 'top-account', 'top-back']);
  for (const [file, text] of Object.entries(sources)) {
    for (const m of text.matchAll(/data-act=\\?"([a-z0-9-]+)\\?"/g)) (used.get(m[1]) || used.set(m[1], new Set()).get(m[1])).add(file);
    for (const re of [/(?:ctx\.on|\bon)\(\s*'([a-z0-9-]+)'/g, /actions\['([a-z0-9-]+)'\]/g, /act === '([a-z0-9-]+)'/g, /ACT\['([a-z0-9-]+)'\]/g])
      for (const m of text.matchAll(re)) handled.add(m[1]);
  }
  const missing = [...used.keys()].filter(a => !handled.has(a));
  for (const a of missing) fail('data-act', `"${a}" (in ${[...used.get(a)].join(', ')}) has no handler (ctx.on, actions[...] or page.html's act ===)`);
  notes.push(`data-act: ${used.size} literal values in the source, ${used.size - missing.length} with a handler`);
}

// ---------------------------------------------------------------- 2. CSS class collisions (static, n129's method)
const classTokens = sel => [...sel.replace(/\/\*[\s\S]*?\*\//g, '').matchAll(/\.(-?[_a-zA-Z][\w-]*)/g)].map(m => m[1]);
function cssRules(css) {
  const out = [];
  for (const m of css.replace(/\/\*[\s\S]*?\*\//g, '').matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    const sel = m[1].trim();
    if (!sel || /^(from|to|\d+%)/.test(sel) || sel.startsWith('@')) continue;
    out.push([sel, m[2].trim()]);
  }
  return out;
}
function markupClasses(js) {
  const set = new Set();
  for (const m of js.matchAll(/class=\\?"([^"\\]*(?:\$\{[^}]*\}[^"\\]*)*)\\?"/g)) {
    const flat = m[1].replace(/\$\{([^}]*)\}/g, (_, inner) => ' ' + [...inner.matchAll(/'([^']*)'|`([^`$]*)`/g)].map(q => q[1] ?? q[2]).join(' ') + ' ');
    for (const t of flat.split(/\s+/)) if (/^-?[_a-zA-Z][\w-]*$/.test(t)) set.add(t);
  }
  for (const m of js.matchAll(/classList\.(?:add|toggle|remove|contains)\(\s*'([\w-]+)'/g)) set.add(m[1]);
  return set;
}
const styleOf = text => [...text.matchAll(/<style data-screen="([\w-]+)">([\s\S]*?)<\/style>/g)].map(m => ({ id: m[1], css: m[2] }));
const pageStyle = pageHtml.slice(pageHtml.indexOf('<style>\n'), pageHtml.indexOf('</style>', pageHtml.indexOf('<style>\n')));
const pageLocalRules = []; // {sel, body, section}
{
  let major = '', minor = '';
  for (const block of pageStyle.split(/(?=\/\*)/)) {
    const head = (block.match(/^\/\*([\s\S]*?)\*\//) || [, ''])[1];
    if (/-{6,}/.test(head)) { major = head.replace(/-/g, '').trim(); minor = ''; } else if (head) minor = head;
    if (!/^(desktop|phone)$/.test(major) || /ticket/i.test(minor)) continue;
    for (const [sel, body] of cssRules(block)) for (const part of sel.split(',')) {
      const s = part.trim().replace(/::?(before|after|placeholder|marker)\b/g, '').replace(/:(hover|focus-visible|focus|active|focus-within)\b/g, '');
      if (classTokens(s).length) pageLocalRules.push({ sel: s, body: body.slice(0, 80), section: major + (minor ? ' / ' + minor.trim().slice(0, 40) : '') });
    }
  }
}
const SHARED_REASONS = {
  'screen heading every screen uses (page.html draws its own placeholder screen with it)': ['.center .eyebrow', '.hero-h', '.hero-h em', '.hero-sub'],
  'phone screen body and its cards (placeholder screen and every phone screen)': ['.p-body', '.phone .card', '.phone .card p.lead', '.phone .card .btn', '.phone .card .acts', '.card .btn.ghost'],
  'section heading with count and side note, same on every screen': ['.p-h', '.p-h h2', '.p-h .n', '.p-h .m'],
  'card stacks, same spacing on every list screen': ['.p-stack', '.stack'],
  'dark summary band at the top of phone screens (Today, Positions, Orders, Analysis)': ['.band', '.band .eyebrow', '.band .fig', '.band .fig b', '.band .fig span'],
  'ticker in a phone row, same size everywhere': ['.phone .sym'],
  'Orders shows a sent order with the roll ticket\'s own legs and terms, so it reads like what was sent': ['.legs', '.leg', '.leg .k', '.leg .d', '.leg .amt', '.terms', '.terms .k', '.terms .v'],
  'Analysis desktop figures use Today\'s figure style': ['.fig .k', '.fig .v'],
  'Robinhood keeps the No call size and weight, sets its own colour': ['.nocall'],
};
const PAGE_SHARED_OK = new Set(Object.values(SHARED_REASONS).flat());

// ---------------------------------------------------------------- 8. in the money = green (Design #211, static)
const ITM_TOKENS = /^var\(--(itm|itm-wash|otm|otm-wash)\)$/;
const ITM_CLASSES = new Set(['itm', 'f-itm', 'room', 'f-room']);
const CORAL = /--coral-\d+|#(e4573f|c23c26|9a2b19|fee5df|fa9a87)\b|rgb\(228 87 63/i;
const GREEN = /--sea-\d+|#(117555|015f43|d4f4e5|73d4ac)\b|rgb\(115 212 172/i;
{
  const root = (pageStyle.match(/:root\{([^}]*)\}/) || [, ''])[1];
  const tok = n => (root.match(new RegExp(`--${n}:([^;]+);`)) || [, null])[1];
  const gain = (pageStyle.match(/\.pos\{color:([^}]+)\}/) || [, null])[1], loss = (pageStyle.match(/\.neg\{color:([^}]+)\}/) || [, null])[1];
  if (!tok('itm') || tok('itm') !== gain) fail('itm', `--itm is ${tok('itm')}, the gain green (.pos) is ${gain}: in the money is the gain green`);
  if (!tok('otm') || tok('otm') !== loss) fail('itm', `--otm is ${tok('otm')}, the loss red (.neg) is ${loss}: out of the money is the loss red`);
  for (const n of ['itm-wash', 'otm-wash']) if (!tok(n)) fail('itm', `--${n} missing from page.html's :root`);
  const css = [['page.html', pageStyle], ...Object.entries(sources).filter(([f]) => f !== 'page.html').flatMap(([f, t]) => styleOf(t).map(s => [f, s.css]))];
  let rules = 0;
  for (const [file, text] of css) for (const [sel, body] of cssRules(text)) {
    if (!classTokens(sel).some(c => ITM_CLASSES.has(c))) continue;
    rules++;
    for (const d of body.matchAll(/(?:^|;)\s*(color|background(?:-color|-image)?|border(?:-[a-z]+)*|box-shadow|fill|stroke|outline(?:-color)?)\s*:\s*([^;]+)/g)) {
      const off = [...d[2].matchAll(/var\(--[\w-]+\)|#[0-9a-f]{3,8}\b|rgba?\([^)]*\)/gi)].map(r => r[0]).filter(r => !ITM_TOKENS.test(r));
      if (off.length) fail('itm', `${file} "${sel}" ${d[1]} uses ${off.join(', ')}: an ITM/OTM surface takes only --itm, --itm-wash, --otm, --otm-wash`);
    }
  }
  for (const [file, text] of Object.entries(sources)) text.split('\n').forEach((line, i) => {
    if (/--(itm|otm)(-wash)?:/.test(line)) return;
    if (/\b[Ii]n the money\b|\bITM\b|'itm'|\bf-itm\b|class=\\?"itm/.test(line) && CORAL.test(line)) fail('itm', `${file}:${i + 1} names coral on an in-the-money line: ${line.trim().slice(0, 120)}`);
    if (/\b[Oo]ut of the money\b|\bOTM\b|'room'|\bf-room\b/.test(line) && GREEN.test(line)) fail('itm', `${file}:${i + 1} names green on an out-of-the-money line: ${line.trim().slice(0, 120)}`);
  });
  const words = { ...sources, ...Object.fromEntries(['fixture.json', ...fs.readdirSync(path.join(HERE, '..', 'fixtures')).map(f => 'fixtures/' + f)].map(f => [f, fs.readFileSync(path.join(HERE, '..', f), 'utf8')])) };
  for (const [file, text] of Object.entries(words)) {
    for (const m of text.matchAll(/\b(red|coral|pink)\b[^.;<\n]{0,60}\bin the money\b|\bin the money\b[^.;<\n]{0,30}\b(red|coral|pink)\b/gi)) fail('itm', `${file}: "${m[0]}" pairs ${m[1] || m[2]} with in the money`);
    for (const m of text.matchAll(/(?:[\w-]+\s+)?shad(?:ed|ing)\b[^<\n]{0,40}\bin the money\b/gi)) if (!/green/i.test(m[0])) fail('itm', `${file}: "${m[0]}" names the in-the-money shading without saying green`);
  }
  notes.push(`in the money: token pair --itm=${tok('itm')} --otm=${tok('otm')}; ${rules} CSS rules on ITM/OTM classes read`);
}

if (process.argv.includes('--static')) { for (const f of failures) console.log(f); console.log(notes.join('\n')); process.exit(failures.length ? 1 : 0); }

// ---------------------------------------------------------------- runtime: screens, draft states, opens
const SIZES = [
  { name: '1440', width: 1440, height: 900, view: 'desk', root: '#desk' },
  { name: '390', width: 390, height: 844, view: 'phone', root: '#phone' },
  { name: '320', width: 320, height: 640, view: 'phone', root: '#phone' },
];
const MORE_SUBS = ['ladder', 'ideas', 'screener', 'browse', 'howto', 'glossary', 'settings', 'robinhood', 'system'];
const nav = id => `[data-nav="${id}"]`;
export const SCREENS = [
  { key: 'today', steps: [] },
  { key: 'positions', steps: [nav('positions')] },
  { key: 'orders', steps: [nav('orders')] },
  { key: 'analysis', steps: [nav('analysis')] },
  { key: 'more', steps: [nav('more')] },
  ...MORE_SUBS.map(s => ({ key: s === 'ladder' ? 'trade' : s, steps: [nav('more'), `[data-act="more-open"][data-sub="${s}"]`] })),
  { key: 'alerts', steps: ['[data-act="top-bell"]'] },
  { key: 'account-menu', steps: ['[data-act="top-account"]'] },
  { key: 'signed-out', steps: ['[data-act="top-account"]', '[data-act="acct-signout"]', '[data-act="acct-signout-yes"]', { wait: 2600 }] },
];
const OPEN_ACTS = /^(action-open|entry-open|more-open|gloss-open|howto-step|ladder-open|open-roll|today-btc|today-acct-open|today-orders|trade-door|trade-hub|browse-ticket|browse-open|browse-position|positions-open|analysis-open|tip-gloss|ticket-orders|ticket-settings|set-goto|acct-settings|ideas-screener)$/;
const wait = ms => new Promise(r => setTimeout(r, ms));

function audit({ rootSel }) {
  const root = document.querySelector(rootSel), rr = root.getBoundingClientRect();
  const out = { innerWidth: window.innerWidth, scrollWidth: document.documentElement.scrollWidth, small: [], banned: [], spill: [], drawing: false };
  const shown = el => {
    if (!el.getClientRects().length || el.closest('[hidden], script, style')) return false;
    const cs = getComputedStyle(el); return cs.visibility !== 'hidden' && cs.display !== 'none';
  };
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const text = n.textContent.trim(); if (!text) continue;
    const el = n.parentElement; if (!shown(el)) continue;
    const r = el.getBoundingClientRect(); if (r.width <= 1 && r.height <= 1) continue;
    const size = parseFloat(getComputedStyle(el).fontSize);
    if (size < 12) out.small.push(`${size}px "${text.slice(0, 40)}"`);
    if (/simulated|real money/i.test(text) && !el.closest('[data-allow-real-money]')) out.banned.push(`"${text.slice(0, 60)}"`);
    if (/This screen is being drawn/.test(text)) out.drawing = true;
  }
  for (const el of root.querySelectorAll('*')) {
    if (!shown(el)) continue;
    const r = el.getBoundingClientRect();
    if (r.width <= 1 || r.height <= 1 || (r.right <= rr.right + 1 && r.left >= rr.left - 1)) continue;
    let clipped = false;
    for (let a = el.parentElement; a && a !== root.parentElement; a = a.parentElement) {
      const ox = getComputedStyle(a).overflowX;
      if (/auto|scroll|hidden|clip/.test(ox)) { const ar = a.getBoundingClientRect(); if (ar.right <= rr.right + 1 && ar.left >= rr.left - 1) { clipped = true; break; } }
    }
    if (!clipped) out.spill.push(`${el.tagName.toLowerCase()}.${String(el.className).split(' ').slice(0, 2).join('.')} ${Math.round(r.left - rr.left)}..${Math.round(r.right - rr.left)} in ${Math.round(rr.width)}`);
  }
  out.small = [...new Set(out.small)].slice(0, 6); out.banned = out.banned.slice(0, 4); out.spill = out.spill.slice(0, 6);
  out.text = root.innerText;
  out.label = [root.querySelector('section.center')?.getAttribute('aria-label') || root.querySelector('[data-topbar]')?.getAttribute('aria-label') || '',
    (root.querySelector('section.center h1, .p-scroll h1')?.textContent || '').trim()].join(' | ');
  return out;
}
function itmAudit({ rootSel }) {
  const root = document.querySelector(rootSel), bad = [], seen = [];
  const shown = el => el.getClientRects().length && !el.closest('[hidden]') && getComputedStyle(el).display !== 'none' && getComputedStyle(el).visibility !== 'hidden';
  const probe = document.body.appendChild(document.createElement('i'));
  const norm = v => { probe.style.color = ''; probe.style.color = String(v).trim(); return getComputedStyle(probe).color; };
  const tok = (el, n) => norm(getComputedStyle(el).getPropertyValue('--' + n));
  const CORAL100 = norm('#fee5df');
  const name = el => `${el.tagName.toLowerCase()}.${[...el.classList].join('.')} "${(el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 24)}"`;
  const want = (el, kind, prop, n) => {
    const cs = getComputedStyle(el), t = tok(el, n);
    const got = prop === 'color' ? cs.color : prop === 'background' ? [cs.backgroundColor, cs.backgroundImage].join(' ') : cs.backgroundColor;
    seen.push(kind);
    if (prop === 'background' ? !got.includes(t) : got !== t) bad.push(`${kind} ${name(el)} ${prop} ${got} is not --${n} (${t})`);
    if (prop !== 'color' && got.includes(CORAL100)) bad.push(`${kind} ${name(el)} is still coral-100`);
  };
  for (const el of root.querySelectorAll('*')) {
    if (!shown(el)) continue;
    if (el.matches('.f-itm')) want(el, el.closest('.fig') ? 'detail figure' : 'row fact', 'color', 'itm');
    if (el.matches('.f-room')) want(el, el.closest('.fig') ? 'detail figure' : 'row fact', 'color', 'otm');
    if (el.matches('.r.itm')) want(el, 'gauge label', 'color', 'itm');
    if (el.matches('.r.room')) want(el, 'gauge label', 'color', 'otm');
    if (el.matches('.pline .itm, .pos-line-itm')) want(el, 'price line zone', 'background', 'itm-wash');
    if (el.matches('.crow.itm')) want(el, 'chain row', 'background', 'itm-wash');
    if (el.matches('.gl-band.itm')) want(el, 'glossary band', 'background', 'itm-wash');
    if (el.matches('.scr-rh .itm')) { want(el, 'robinhood tag', 'color', 'itm'); want(el, 'robinhood tag', 'background-color', 'itm-wash'); }
    if (el.matches('.legend > span') && /in the money/.test(el.textContent)) {
      seen.push('legend');
      const sw = el.querySelector('i');
      if (!sw || getComputedStyle(sw).backgroundColor !== tok(el, 'itm-wash')) bad.push(`legend ${name(el)} swatch is not --itm-wash`);
      if (!/green/.test(el.textContent)) bad.push(`legend ${name(el)} doesn't say green`);
    }
    if (el.matches('.gauge')) {
      seen.push('gauge');
      const img = getComputedStyle(el).backgroundImage, a = img.indexOf(tok(el, 'itm-wash')), b = img.lastIndexOf(tok(el, 'otm-wash'));
      if (a < 0 || b < 0 || a > b) bad.push(`gauge ${img.slice(0, 90)}: the in-the-money half (left) is not --itm-wash, the other not --otm-wash`);
      const dot = el.querySelector('i'), r = el.parentElement.querySelector('.r');
      if (dot && r) { const n = r.matches('.itm') ? 'itm' : 'otm'; if (getComputedStyle(dot).backgroundColor !== tok(el, n)) bad.push(`gauge dot ${r.textContent} is not --${n}`); }
    }
    const own = [...el.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join('').trim();
    if (/^ITM [\d.]+%$/.test(own)) want(el, 'ITM label', 'color', 'itm');
    if (/^OTM [\d.]+%$/.test(own)) want(el, 'OTM label', 'color', 'otm');
  }
  probe.remove();
  return { bad: [...new Set(bad)].slice(0, 8), seen: [...new Set(seen)] };
}
function cssLeaks({ rootSel, own, pageRules }) {
  const root = document.querySelector(rootSel);
  const body = root.querySelector('section.center') || root.querySelector('.p-scroll');
  if (!body) return [];
  const visible = el => el.getClientRects().length && !el.closest('[hidden], [data-topbar], .tabbar') && getComputedStyle(el).display !== 'none';
  const hits = new Map();
  const test = (src, s) => {
    let els; try { els = body.querySelectorAll(s); } catch { return; }
    for (const el of els) if (visible(el)) { if (!hits.has(src + '|' + s)) hits.set(src + '|' + s, `${el.tagName.toLowerCase()}.${[...el.classList].join('.')} "${(el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 30)}"`); return; }
  };
  const clean = s => s.trim().replace(/::?(before|after|placeholder|marker|-webkit-[\w-]+)\b/g, '').replace(/:(hover|focus-visible|focus|active|focus-within)\b/g, '');
  const walk = (rules, src) => {
    for (const r of rules) {
      if (r.media) { if (matchMedia(r.media.mediaText).matches) walk(r.cssRules, src); continue; }
      if (!r.selectorText) continue;
      for (const part of r.selectorText.split(',')) { const s = clean(part); if (s && !/^(:root|html|body)\b/.test(s)) test(src, s); }
    }
  };
  for (const st of document.querySelectorAll('style[data-screen]')) if (!own.includes(st.dataset.screen)) walk(st.sheet.cssRules, st.dataset.screen + '.js');
  const flat = (rules, out = []) => { for (const r of rules) { if (r.media) { if (matchMedia(r.media.mediaText).matches) flat(r.cssRules, out); } else if (r.selectorText) out.push(r); } return out; };
  const pageSheet = [...document.querySelectorAll('style:not([data-screen])')].find(s => s.textContent.includes('--paper-50'));
  const pageProps = new Map();
  for (const r of flat(pageSheet.sheet.cssRules)) for (const part of r.selectorText.split(',')) {
    const s = clean(part); if (!pageRules.includes(s)) continue;
    const set = pageProps.get(s) || pageProps.set(s, new Set()).get(s); for (const p of r.style) set.add(p);
  }
  const ownRules = [...document.querySelectorAll('style[data-screen]')].filter(st => own.includes(st.dataset.screen)).flatMap(st => flat(st.sheet.cssRules));
  for (const s of pageRules) {
    let els; try { els = body.querySelectorAll(s); } catch { continue; }
    for (const el of els) {
      if (!visible(el)) continue;
      const sets = (st, p) => [p, ...p.split('-').map((_, i, a) => a.slice(0, i).join('-')).filter(Boolean),
        ...(/radius/.test(p) ? ['border-radius'] : []), ...(/gap$/.test(p) ? ['gap'] : []), ...(p === 'line-height' ? ['font'] : []),
        ...(p === 'flex-wrap' ? ['flex-flow'] : [])].some(x => st.getPropertyValue(x));
      const left = [...(pageProps.get(s) || [])].filter(p => !ownRules.some(r => sets(r.style, p) && r.selectorText.split(',').some(x => { try { return el.matches(clean(x)); } catch { return false; } })));
      if (left.length && !hits.has('page.html|' + s)) hits.set('page.html|' + s, `${el.tagName.toLowerCase()}.${[...el.classList].join('.')} "${(el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 30)}" keeps ${left.join(' ')}`);
      if (left.length) break;
    }
  }
  return [...hits].map(([k, v]) => [k, v]);
}
function collectOpens({ rootSel, re }) {
  const R = new RegExp(re), root = document.querySelector(rootSel), out = [], seen = new Set();
  for (const el of root.querySelectorAll('[data-act]')) {
    if (!R.test(el.dataset.act) || el.disabled || !el.getClientRects().length || el.closest('[hidden]') || getComputedStyle(el).visibility === 'hidden') continue;
    el.scrollIntoView({ block: 'center' }); const r = el.getBoundingClientRect(), top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    if (!top || !el.contains(top)) continue;
    const sel = [...el.attributes].filter(a => a.name.startsWith('data-') && !/^data-(no-terms|st-|state)/.test(a.name)).map(a => `[${a.name}="${CSS.escape(a.value)}"]`).join('');
    if (seen.has(sel)) continue; seen.add(sel);
    out.push({ sel, label: (el.getAttribute('aria-label') || el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 40),
      current: !!el.getAttribute('aria-current') || el.getAttribute('aria-pressed') === 'true' || el.getAttribute('aria-selected') === 'true' });
  }
  return out;
}
function collectStates({ rootSel }) {
  const root = document.querySelector(rootSel), out = [];
  for (const s of root.querySelectorAll('span')) {
    if (!/^Draft preview/.test(s.textContent.trim()) || s.children.length) continue;
    for (const b of s.parentElement.querySelectorAll('button[data-act]')) {
      if (!b.getClientRects().length) continue;
      b.scrollIntoView({ block: 'center' }); const r = b.getBoundingClientRect(), top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
      if (!top || !b.contains(top)) continue;
      const sel = [...b.attributes].filter(a => a.name.startsWith('data-')).map(a => `[${a.name}="${CSS.escape(a.value)}"]`).join('');
      out.push({ sel, label: b.textContent.trim() });
    }
  }
  return out;
}

const texts = [];
const opensDone = {};
const stats = { visits: 0, states: 0, opens: 0 };
const itmSeen = new Map();
const OWN = { trade: ['ladder', 'trade', 'more'], 'account-menu': ['today'], more: ['more'] };
const leaks = new Map();
async function check(page, size, where, screen, css = false) {
  if (css) {
    const own = OWN[screen] || [screen, 'more'];
    const pageRules = screen === 'today' || screen === 'account-menu' ? [] : pageLocalRules.filter(r => !PAGE_SHARED_OK.has(r.sel)).map(r => r.sel);
    for (const [k, ex] of await page.evaluate(cssLeaks, { rootSel: size.root, own, pageRules })) {
      const l = leaks.get(k) || leaks.set(k, { screens: new Set(), example: ex }).get(k); l.screens.add(`${size.name} ${screen}`);
    }
  }
  const a = await page.evaluate(audit, { rootSel: size.root });
  if (a.innerWidth !== size.width) fail(where, `layout viewport ${a.innerWidth}px on a ${size.width}px screen`);
  if (a.scrollWidth > a.innerWidth) fail(where, `page ${a.scrollWidth}px wide in a ${a.innerWidth}px viewport`);
  if (a.small.length) fail(where, `text under 12px: ${a.small.join('; ')}`);
  if (a.banned.length) fail(where, `"Simulated"/"Real money" outside data-allow-real-money: ${a.banned.join('; ')}`);
  if (a.spill.length) fail(where, `spills past the view: ${a.spill.join('; ')}`);
  if (a.drawing) fail(where, 'shows the "This screen is being drawn" placeholder');
  const itm = await page.evaluate(itmAudit, { rootSel: size.root });
  for (const b of itm.bad) fail(where, `in the money colour: ${b}`);
  for (const k of itm.seen) (itmSeen.get(k) || itmSeen.set(k, new Set()).get(k)).add(size.name);
  texts.push({ size: size.name, where, screen, label: a.label, text: a.text });
  return a.text;
}
async function click(page, size, sel) {
  const loc = page.locator(`${size.root} ${sel} >> visible=true`).first();
  await loc.click({ timeout: 4000 });
}
async function open(page, size, steps) {
  await page.goto(URL + '?view=' + size.view);
  await wait(250);
  for (const s of steps) {
    if (s.wait) { await wait(s.wait); continue; }
    await click(page, size, s); await wait(350);
  }
}

async function runSize(size) {
  opensDone[size.name] = new Set();
  const browser = await chromium.launch();
  const ctxOpts = size.view === 'phone'
    ? { viewport: { width: size.width, height: size.height }, deviceScaleFactor: 1, isMobile: true, hasTouch: true }
    : { viewport: { width: size.width, height: size.height } };
  const pending = [...SCREENS];
  async function worker(workerIdx) {
    let current = '';
    const ctx = await browser.newContext(ctxOpts);
    const page = await ctx.newPage();
    page.on('console', m => { if (m.type() === 'error') fail(current, `console error: ${m.text()}`); });
    page.on('pageerror', e => fail(current, `page error: ${e.message}`));
    while (pending.length) {
      const sc = pending.shift();
      const base = `${size.name} ${sc.key}`;
      current = base;
      try { await open(page, size, sc.steps); } catch (e) { fail(base, `could not reach the screen: ${e.message.split('\n')[0]}`); continue; }
      stats.visits++;
      await check(page, size, base, sc.key, true);
      const opens = await page.evaluate(collectOpens, { rootSel: size.root, re: OPEN_ACTS.source });
      if (sc.key !== 'signed-out') {
        current = `${base} expanded`;
        try {
          await page.evaluate(r => document.querySelectorAll(`${r} details`).forEach(d => { d.open = true; }), size.root);
          for (let i = 0; i < 90; i++) {
            const sel = await page.evaluate(r => {
              const root = document.querySelector(r), body = root.querySelector('section.center') || root.querySelector('.p-scroll');
              const b = body && [...body.querySelectorAll('button[aria-expanded="false"]:not([data-done-204])')].find(x => x.getClientRects().length && !x.closest('[data-topbar], [hidden]') && !/filter|menu|sheet|account|tip/i.test((x.dataset.act || '') + ' ' + (x.getAttribute('aria-haspopup') || '')) && !x.classList.contains('itip') && !x.classList.contains('tipbtn'));
              if (!b) return null; const id = 'x' + Math.random().toString(36).slice(2); b.setAttribute('data-done-204', id); return id;
            }, size.root);
            if (!sel) break;
            await page.locator(`${size.root} [data-done-204="${sel}"]`).click({ timeout: 3000 }).catch(() => {});
            await wait(120);
          }
          await page.evaluate(r => document.querySelectorAll(`${r} details`).forEach(d => { d.open = true; }), size.root);
          await wait(300);
          await check(page, size, current, sc.key);
        } catch (e) { fail(current, `could not fold everything open: ${e.message.split('\n')[0]}`); }
      }
      for (const st of await page.evaluate(collectStates, { rootSel: size.root })) {
        current = `${base} state ${st.label}`;
        try { await click(page, size, st.sel); await wait(450); } catch (e) { fail(current, `state button not clickable: ${e.message.split('\n')[0]}`); continue; }
        stats.states++;
        await check(page, size, current, sc.key, true);
      }
      const queue = process.argv.includes('--no-opens') ? [] : opens.map(o => ({ path: [o], screen: sc }));
      while (queue.length) {
        const { path: chain } = queue.shift();
        const last = chain[chain.length - 1];
        if (opensDone[size.name].has(last.sel) && chain.length > 1) continue;
        if (chain.length === 1 && opensDone[size.name].has(`${sc.key}:${last.sel}`)) continue;
        opensDone[size.name].add(chain.length === 1 ? `${sc.key}:${last.sel}` : last.sel);
        current = `${base} open ${chain.map(c => `${c.sel.match(/data-act="([^"]+)"/)[1]}(${c.label})`).join(' > ')}`;
        try {
          await open(page, size, sc.steps);
          for (const c of chain.slice(0, -1)) { await click(page, size, c.sel); await wait(700); }
        } catch (e) { fail(current, `could not replay the way there: ${e.message.split('\n')[0]}`); continue; }
        const before = await page.evaluate(r => document.querySelector(r).innerText, size.root);
        const beforeOpens = new Set((await page.evaluate(collectOpens, { rootSel: size.root, re: OPEN_ACTS.source })).map(o => o.sel));
        try { await click(page, size, last.sel); } catch (e) { fail(current, `not clickable: ${e.message.split('\n')[0]}`); continue; }
        await wait(800);
        stats.opens++;
        const after = await check(page, size, current, sc.key);
        if (after === before && !last.current) fail(current, 'the click changed nothing on screen');
        if (!after.trim()) fail(current, 'the view is empty after the click');
        if (!QUICK && chain.length < 2) {
          const next = (await page.evaluate(collectOpens, { rootSel: size.root, re: OPEN_ACTS.source })).filter(o => !beforeOpens.has(o.sel) && !opensDone[size.name].has(o.sel));
          for (const o of next) queue.push({ path: [...chain, o], screen: sc });
        }
      }
    }
    if (workerIdx === 0) {
      current = `${size.name} glossary term itm-depth`;
      try {
        await open(page, size, [nav('more'), '[data-act="more-open"][data-sub="glossary"]']);
        await click(page, size, '[data-term="itm-depth"] .gl-row'); await wait(700);
        stats.visits++;
        await check(page, size, current, 'glossary');
      } catch (e) { fail(current, `could not open the ITM depth term: ${e.message.split('\n')[0]}`); }
    }
    await ctx.close();
  }
  await Promise.all([0, 1, 2, 3].map(i => worker(i)));
  await browser.close();
}

await Promise.all(SIZES.map(size => runSize(size)));
for (const [k, l] of leaks) {
  const [src, sel] = k.split('|');
  const rule = src === 'page.html' ? pageLocalRules.find(r => r.sel === sel) : null;
  fail('css', `${src} rule "${sel}"${rule ? ` {${rule.body}} (${rule.section})` : ''} styles ${l.example} on ${[...l.screens].slice(0, 4).join(', ')}${l.screens.size > 4 ? ` +${l.screens.size - 4}` : ''}`);
}
notes.push(`runtime: ${stats.visits} screen visits, ${stats.states} draft states, ${stats.opens} opens clicked across 1440/390/320`);

// ---------------------------------------------------------------- 3. the same figures everywhere
const F = JSON.parse(fs.readFileSync(path.join(HERE, '..', 'fixture.json'), 'utf8'));
const A = F.account, held = Object.fromEntries(F.positions.map(p => [p.symbol, p]));
const SYMS = Object.keys(held);
const parseMoney = (num, suffix) => { const v = parseFloat(num.replace(/,/g, '')), dec = (num.split('.')[1] || '').length, unit = { k: 1e3, K: 1e3, m: 1e6, M: 1e6 }[suffix] || 1; return { v: v * unit, tol: unit * 0.5 * 10 ** -dec + 1e-6 }; };
const md = iso => { const [, m, d] = iso.split('-').map(Number); return `${m}/${d}`; };
const figureMisses = [];
const ACCOUNT = [
  [/\bnet liq(?:uidat(?:ing|ion))?(?: value)?\b/gi, A.net_liq, 'net liq'],
  [/\bbuying power\b/gi, A.buying_power, 'buying power'],
  [/\bmargin excess\b|\bexcess\b/gi, A.margin_excess, 'margin excess'],
];
const seenMiss = new Set();
const miss = (t, what, ctx) => { const k = `${t.screen}|${what}|${ctx}`; if (seenMiss.has(k)) return; seenMiss.add(k); figureMisses.push(`${t.where}: ${what.replace(/\s+/g, ' ')}: "…${ctx.replace(/\s+/g, ' ')}…"`); };
for (const t of texts) {
  if (/^(robinhood|signed-out)$/.test(t.screen) || /robinhood/i.test(t.label)) continue;
  const s = t.text;
  for (const [re, want, name] of ACCOUNT) for (const m of s.matchAll(re)) {
    const after = s.slice(m.index + m[0].length, m.index + m[0].length + 48);
    const mm = after.match(/^[^$\d]{0,24}?(−|-)?\$\s?(\d[\d,]*(?:\.\d+)?)(?:([kKmM])(?![a-zA-Z]))?(?![\d,])/);
    if (!mm || /^[^$]*\b(say|e\.g\.|like)\b/i.test(after)) continue;
    const { v, tol } = parseMoney(mm[2], mm[3]);
    if (Math.abs(v - want) > tol) miss(t, `${name} reads ${mm[0].trim()}, fixture ${want}`, s.slice(Math.max(0, m.index - 30), m.index + m[0].length + 48));
  }
  for (const m of s.matchAll(/\$(\d+\.\d{2})\s*(?:a day|\/\s?day|per day|each day)/gi)) {
    const before = s.slice(Math.max(0, m.index - 70), m.index);
    if (!/interest/i.test(before) || /\bSay\b|earned|theta|carry|position/i.test(before) || SYMS.some(sym => new RegExp(`\\b${sym}\\b`).test(before))) continue;
    if (Number(m[1]) !== F.analysis.margin_interest.per_day_now) miss(t, `interest a day reads $${m[1]}, fixture ${F.analysis.margin_interest.per_day_now}`, before + m[0]);
  }
  for (const m of s.matchAll(/\b(\d{1,2}\/\d{1,2})\s+\$(\d+(?:\.\d+)?)\s+calls?\b/g)) {
    const before = s.slice(Math.max(0, m.index - 90), m.index);
    const syms = [...before.matchAll(new RegExp(`\\b(${SYMS.join('|')})\\b`, 'g'))];
    if (!syms.length) continue;
    const sym = syms[syms.length - 1][1], c = held[sym].call;
    const tail = before.slice(syms[syms.length - 1].index);
    if (!c || /→|\bto\b|\bnew\b|\bsell\b|\bsold\b|\binstead\b|\bpick|\broll|\bnext\b|\bor\b|\bthen\b/i.test(tail)) continue;
    const sameDate = m[1] === md(c.expiry), sameStrike = Number(m[2]) === c.strike;
    if (sameDate !== sameStrike) miss(t, `${sym} call reads ${m[0]}, fixture ${c.label}`, tail + m[0]);
  }
  for (const m of s.matchAll(new RegExp(`\\b(${SYMS.join('|')})\\b[^\\n.;]{0,40}?\\b([\\d,]+) (shares|contracts?)\\b|\\b([\\d,]+) (${SYMS.join('|')}) (shares|calls|contracts)\\b`, 'g'))) {
    const sym = m[1] || m[5], n = Number((m[2] || m[4]).replace(/,/g, '')), unit = m[3] || m[6];
    const mid = m[0];
    if (/\b(buy|buying|bought|sell|selling|add|adding|more|of|lot|lots|each|per)\b/i.test(mid.replace(new RegExp(`^${sym}\\b`), '').replace(/\d[\d,]* (shares|contracts?|calls)$/, ''))) continue;
    const p = held[sym], want = unit === 'shares' ? p.shares : p.call?.contracts;
    if (want != null && n !== want) miss(t, `${sym} ${unit} read ${n}, fixture ${want}`, mid);
  }
}
// Glossary worked examples (fixtures/glossary.json) recomputed from fixture.json
{
  const G = JSON.parse(fs.readFileSync(path.join(HERE, '..', 'fixtures', 'glossary.json'), 'utf8'));
  const ex = Object.fromEntries(G.terms.filter(t => t.example).map(t => [t.id, t.example]));
  const x = held.XOM, mi = F.analysis.margin_interest;
  const fmt = (n, d = 2) => n.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
  const want = {
    'excess': [fmt(A.margin_excess, 0)],
    'net-liq': [fmt(A.stock_value, 0), fmt(A.calls_owed, 0), fmt(-A.cash, 0), fmt(A.net_liq, 0)],
    'leverage': [fmt(A.stock_value, 0), fmt(A.net_liq, 0)],
    'interest-day': [fmt(mi.loan, 0), `${mi.rate_pct}%`, `$${mi.per_day_now}`],
    'net-carry': [`$${mi.per_day_now}`],
    'price-cushion': [`$${fmt(x.spot)}`, `$${fmt(x.adjusted_basis_per_share)}`],
    'itm-depth': [fmt(x.spot), `${x.call.strike}`, `$${fmt(x.call.intrinsic)}`],
    'extrinsic': [fmt(x.call.mark), fmt(x.call.intrinsic), `$${fmt(x.call.extrinsic)}`],
    'captured': [fmt(x.call.extrinsic), fmt(x.call.sold_at)],
    'adj-basis': [fmt(x.cost_basis_per_share), fmt(x.premium_collected_per_share), `$${fmt(x.adjusted_basis_per_share)}`],
    'gain-if-assigned': [`(${x.call.strike} − ${fmt(x.adjusted_basis_per_share)}) × ${x.shares}`],
    'locked-in': [`${fmt(x.call.sold_at)} × ${x.call.contracts} × 100 = $${fmt(x.call.premium_received, 0)}`],
    'realized': [`${fmt(x.call.premium_received, 0)} − ${fmt(x.call.owed, 0)}`],
    'call': [`XOM ${x.call.label}`, `${x.shares} XOM shares at $${x.call.strike}`, `$${fmt(x.call.premium_received, 0)}`],
    'covered-call': [`${x.shares} XOM shares with ${x.call.contracts} calls`, `${held.T.shares} T shares`],
    'strike': [`$${x.call.strike} strike`, `$${fmt(x.spot)}`, `${x.shares} shares`],
    'delta': [`Δ ${fmt(x.call.delta)}`],
    'spread': [fmt(x.call.ask), fmt(x.call.bid), fmt(x.call.mark)],
    'drop-to-call': [`${A.drop_to_call_pct}%`],
    'maintenance': [`$${fmt(A.maintenance_requirement, 0)}`, `${x.shares} shares`],
  };
  for (const t of G.terms) if (/margin cushion|cushion \(two/i.test(JSON.stringify(t)) || ['margin-cushion', 'cushion'].includes(t.id)) figureMisses.push(`glossary.json ${t.id}: names Margin cushion, which the owner removed`);
  for (const [id, parts] of Object.entries(want)) {
    if (!ex[id]) { figureMisses.push(`glossary.json: term ${id} has no example`); continue; }
    for (const p of parts) if (!ex[id].includes(p)) figureMisses.push(`glossary.json ${id}: example "${ex[id]}" lacks "${p}" (from fixture.json)`);
  }
}
// One price per stock (Browse's quote = every fixture's price/spot and every price a screen states)
{
  const FX = Object.fromEntries(fs.readdirSync(path.join(HERE, '..', 'fixtures')).filter(f => f.endsWith('.json'))
    .map(f => [`fixtures/${f}`, JSON.parse(fs.readFileSync(path.join(HERE, '..', 'fixtures', f), 'utf8'))]));
  FX['fixture.json'] = F;
  const QUOTES = FX['fixtures/browse.json'].tickers;
  const PRICE = Object.fromEntries(Object.entries(QUOTES).map(([s, q]) => [s, q.price]));
  if (!PRICE.CSCO) figureMisses.push('fixtures/browse.json: no CSCO quote to hold the other screens to');
  const cents = n => n.toFixed(2);
  const strs = v => typeof v === 'string' ? [v] : Array.isArray(v) ? v.flatMap(strs) : [];
  const walk = (o, where, sym) => {
    if (Array.isArray(o)) { o.forEach((v, i) => walk(v, `${where}[${i}]`, null)); return; }
    if (!o || typeof o !== 'object') return;
    const own = PRICE[o.symbol] ? o.symbol : PRICE[o.sym] ? o.sym : sym;
    if (own) for (const k of ['price', 'spot']) if (typeof o[k] === 'number' && o[k] !== PRICE[own]) figureMisses.push(`${where}.${k}: ${own} at $${cents(o[k])}, Browse quotes $${cents(PRICE[own])}`);
    if (own && typeof o.stock_limit === 'number' && (o.stock_limit < PRICE[own] || o.stock_limit > PRICE[own] * 1.01)) figureMisses.push(`${where}.stock_limit: ${own} limit $${cents(o.stock_limit)} is not just above its $${cents(PRICE[own])} price`);
    if (own) for (const v of Object.values(o).flatMap(strs)) for (const m of v.matchAll(/\babout \$(\d+\.\d{2})\b/g)) if (Number(m[1]) !== PRICE[own]) figureMisses.push(`${where}: "${m[0]}" for ${own}, Browse quotes $${cents(PRICE[own])}`);
    for (const [k, v] of Object.entries(o)) if (v && typeof v === 'object') walk(v, `${where}.${k}`, PRICE[k] ? k : null);
  };
  for (const [file, data] of Object.entries(FX)) walk(data, file, null);
  for (const [s, q] of Object.entries(QUOTES)) {
    const closes = String(q.history && q.history.closes || '').trim().split(/\s+/).map(Number);
    if (closes.length && closes[closes.length - 1] !== q.price) figureMisses.push(`fixtures/browse.json ${s}: last close $${cents(closes[closes.length - 1])}, price $${cents(q.price)}`);
  }
  const esc = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const SYMS_Q = Object.keys(PRICE);
  const symRe = new RegExp(`\\b(${SYMS_Q.join('|')})\\b`, 'g');
  const stated = Object.fromEntries(SYMS_Q.map(s => [s, new Set()]));
  for (const t of texts) {
    if (t.screen === 'signed-out') continue;
    const s = t.text;
    for (const sym of SYMS_Q) {
      if (!s.includes(sym)) continue;
      const name = QUOTES[sym].name ? `|${esc(QUOTES[sym].name)}` : '';
      const re = new RegExp(`\\b${sym}\\b((?:[ \\t\\n]*(?:·|now|stock price|\\d{1,2}:\\d{2} [AP]M${name}))*)[ \\t\\n]*\\$(\\d+\\.\\d{2})(?![\\d,])`, 'g');
      for (const m of s.matchAll(re)) {
        stated[sym].add(m[2]);
        if (Number(m[2]) !== PRICE[sym]) miss(t, `${sym} priced $${m[2]}, Browse quotes $${cents(PRICE[sym])}`, s.slice(Math.max(0, m.index - 20), m.index + m[0].length + 20));
      }
      for (const m of s.matchAll(new RegExp(`\\b(?:buy|buying) [\\d,]+ ${sym} at up to \\$(\\d+\\.\\d{2})`, 'gi'))) {
        const v = Number(m[1]);
        if (v < PRICE[sym] || v > PRICE[sym] * 1.01) miss(t, `${sym} limit $${m[1]} is not just above its $${cents(PRICE[sym])} price`, m[0]);
      }
    }
    for (const m of s.matchAll(/\bshares at about \$(\d+\.\d{2})/g)) {
      const before = [...s.slice(Math.max(0, m.index - 160), m.index).matchAll(symRe)];
      if (!before.length) continue;
      const sym = before[before.length - 1][1];
      stated[sym].add(m[1]);
      if (Number(m[1]) !== PRICE[sym]) miss(t, `${sym} "${m[0]}", Browse quotes $${cents(PRICE[sym])}`, s.slice(Math.max(0, m.index - 60), m.index + m[0].length));
    }
  }
  if (!stated.CSCO || !stated.CSCO.size) figureMisses.push('no screen stated CSCO\'s price: the one-price check read nothing (Browse, Screener and the entry ticket should)');
  notes.push(`one price per stock: CSCO stated as ${[...(stated.CSCO || [])].map(v => '$' + v).join(', ') || 'nothing'} across ${texts.filter(t => /\bCSCO\b/.test(t.text)).length} rendered views`);
}
for (const m of figureMisses) fail('figures', m);
for (const k of ['row fact', 'detail figure', 'price line zone', 'legend', 'gauge', 'gauge label', 'ITM label', 'OTM label', 'robinhood tag', 'glossary band', 'chain row'])
  if (!itmSeen.has(k)) fail('itm', `no ${k} was drawn: the in-the-money colour check read nothing there`);
notes.push(`in the money colours checked: ${[...itmSeen].map(([k, s]) => `${k} (${[...s].join('/')})`).join(', ')}`);

const dump = process.argv.find(a => a.startsWith('--dump='));
if (dump) fs.writeFileSync(dump.slice(7), JSON.stringify(texts, null, 1));
for (const n of notes) console.log(n);
if (failures.length) { console.log(`FAIL (${failures.length})`); for (const f of failures) console.log(f); process.exit(1); }
console.log('PASS: data-act handlers, opens draw without errors (2 levels), no page-only or unscoped CSS collisions, same figures everywhere, no Simulated/Real money text, no text under 12px, no overflow at 1440/390/320, no console errors');
