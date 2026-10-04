#!/usr/bin/env node
/**
 * Checks the built dashboard CSS against the Temper logo handoff
 * (design-lab results/temper-logo/UI-HANDOFF.md): every text pair at least
 * 4.5:1 and every control, focus and indicator pair at least 3:1, in both
 * themes, using the WCAG 2 relative-luminance formula (sRGB). It also fails
 * when a colour of the old navy/cyan/blue theme is left in the built CSS or
 * in src/.
 *
 *   npm run build && node scripts/check-brand-contrast.mjs [--json out.json]
 *
 * The colours are read from the built CSS, not copied here, so the check
 * judges what the browser gets. Dark is the default (:root); light is the
 * [data-theme=light] block plus the :root:not(.dark) fixes. The automatic
 * light block (prefers-color-scheme) must match the explicit one exactly.
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
// postcss comes with Vite (no direct dependency, so the lock file stays as it is).
import postcss from 'postcss';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '..');
const assets = path.join(root, 'dist', 'assets');
const cssFile = fs.readdirSync(assets).find((f) => /^index-.*\.css$/.test(f));
if (!cssFile) {
  console.error('No dist/assets/index-*.css: run the build first.');
  process.exit(2);
}
const cssText = fs.readFileSync(path.join(assets, cssFile), 'utf8');
const ast = postcss.parse(cssText);

// ---- collect custom properties per theme ---------------------------------

const dark = {};
const lightExplicit = {};
const lightAuto = {};
const lightFixes = {};

ast.walkRules((rule) => {
  const sel = rule.selector.replace(/\s+/g, '');
  const inMedia = rule.parent?.type === 'atrule' && rule.parent.name === 'media';
  const media = inMedia ? rule.parent.params.replace(/\s+/g, '') : '';
  let target = null;
  if (!inMedia && (sel === ':root' || sel === ':root,:host')) target = dark;
  else if (!inMedia && (sel === '[data-theme=light]' || sel === ':root[data-theme=light]')) target = lightExplicit;
  else if (!inMedia && sel === ':root:not(.dark)') target = lightFixes;
  else if (media === '(prefers-color-scheme:light)' && sel === ':root:not([data-theme=dark])') target = lightAuto;
  if (!target) return;
  rule.walkDecls((d) => {
    if (d.prop.startsWith('--')) target[d.prop] = d.value.trim();
  });
});

const light = { ...dark, ...lightExplicit, ...lightFixes };

function resolve(vars, value, depth = 0) {
  if (depth > 10) throw new Error(`var() loop at ${value}`);
  const m = /^var\((--[\w-]+)(?:,\s*(.+))?\)$/.exec(value.trim());
  if (!m) return value.trim();
  const next = vars[m[1]] ?? m[2];
  if (next === undefined) throw new Error(`undefined ${m[1]}`);
  return resolve(vars, next, depth + 1);
}

// ---- colour maths ----------------------------------------------------------

function parseColour(str) {
  const s = str.trim().toLowerCase();
  let m = /^#([0-9a-f]{3,8})$/.exec(s);
  if (m) {
    let h = m[1];
    if (h.length === 3 || h.length === 4) h = [...h].map((c) => c + c).join('');
    const n = (i) => parseInt(h.slice(i, i + 2), 16);
    return { r: n(0), g: n(2), b: n(4), a: h.length === 8 ? n(6) / 255 : 1 };
  }
  m = /^rgba?\(([^)]+)\)$/.exec(s);
  if (m) {
    const p = m[1].split(/[\s,/]+/).filter(Boolean).map(Number);
    return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
  }
  if (s === 'white') return { r: 255, g: 255, b: 255, a: 1 };
  if (s === 'black') return { r: 0, g: 0, b: 0, a: 1 };
  throw new Error(`cannot parse colour "${str}"`);
}

function over(fg, bg) {
  const a = fg.a;
  return {
    r: fg.r * a + bg.r * (1 - a),
    g: fg.g * a + bg.g * (1 - a),
    b: fg.b * a + bg.b * (1 - a),
    a: 1,
  };
}

function luminance({ r, g, b }) {
  const lin = (c) => {
    const v = c / 255;
    return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}

function ratio(a, b) {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

const hex = ({ r, g, b }) =>
  '#' + [r, g, b].map((v) => Math.round(v).toString(16).padStart(2, '0')).join('');

// ---- the pairs ---------------------------------------------------------------

// [label, foreground var, background var, minimum, kind]
// A background may be "tint:<var>@<alpha>:<ground var>" for a see-through
// colour over a ground.
const TEXT = 4.5;
const UI = 3;

const common = [
  ['text on page', '--temper-text', '--temper-bg', TEXT, 'text'],
  ['text on panel', '--temper-text', '--temper-panel', TEXT, 'text'],
  ['text on surface', '--temper-text', '--temper-surface', TEXT, 'text'],
  ['secondary text on page', '--temper-text-muted', '--temper-bg', TEXT, 'text'],
  ['secondary text on panel', '--temper-text-muted', '--temper-panel', TEXT, 'text'],
  ['secondary text on surface', '--temper-text-muted', '--temper-surface', TEXT, 'text'],
  ['dim text on page', '--temper-text-dim', '--temper-bg', TEXT, 'text'],
  ['dim text on panel', '--temper-text-dim', '--temper-panel', TEXT, 'text'],
  ['dim text on surface', '--temper-text-dim', '--temper-surface', TEXT, 'text'],
  ['green text/link on page', '--temper-accent', '--temper-bg', TEXT, 'text'],
  ['green text/link on panel', '--temper-accent', '--temper-panel', TEXT, 'text'],
  ['label on green button', '--temper-on-accent', '--temper-accent', TEXT, 'text'],
  ['label on green button (hover)', '--temper-on-accent', '--temper-accent-dim', TEXT, 'text'],
  ['text on green tint 10% (panel)', '--temper-text', 'tint:--temper-accent@0.1:--temper-panel', TEXT, 'text'],
  ['text on green tint 20% (panel)', '--temper-text', 'tint:--temper-accent@0.2:--temper-panel', TEXT, 'text'],
  ['shadcn foreground on background', '--foreground', '--background', TEXT, 'text'],
  ['shadcn card text', '--card-foreground', '--card', TEXT, 'text'],
  ['shadcn popover text', '--popover-foreground', '--popover', TEXT, 'text'],
  ['shadcn primary label', '--primary-foreground', '--primary', TEXT, 'text'],
  ['shadcn secondary label', '--secondary-foreground', '--secondary', TEXT, 'text'],
  ['shadcn muted text on muted', '--muted-foreground', '--muted', TEXT, 'text'],
  ['shadcn muted text on background', '--muted-foreground', '--background', TEXT, 'text'],
  ['shadcn accent (hover) label', '--accent-foreground', '--accent', TEXT, 'text'],
  ['control border on page', '--temper-control', '--temper-bg', UI, 'control'],
  ['control border on panel', '--temper-control', '--temper-panel', UI, 'control'],
  ['control border on surface', '--temper-control', '--temper-surface', UI, 'control'],
  ['focus ring on page', '--temper-accent', '--temper-bg', UI, 'focus'],
  ['focus ring on panel', '--temper-accent', '--temper-panel', UI, 'focus'],
  ['focus ring on surface', '--temper-accent', '--temper-surface', UI, 'focus'],
  ['active nav bar on surface', '--temper-accent', '--temper-surface', UI, 'indicator'],
  ['solid green button edge on panel', '--temper-accent', '--temper-panel', UI, 'control'],
  ['shadcn input border on background', '--input', '--background', UI, 'control'],
  ['shadcn ring on background', '--ring', '--background', UI, 'focus'],
  ['shadcn ring on card', '--ring', '--card', UI, 'focus'],
  // Status colours keep their meaning; they must stay readable on the new
  // grounds (they are used as text and as dots/bars).
  ['status completed on panel', '--color-temper-completed', '--temper-panel', TEXT, 'status'],
  ['status running on panel', '--color-temper-running', '--temper-panel', TEXT, 'status'],
  ['status failed on panel', '--color-temper-failed', '--temper-panel', TEXT, 'status'],
  ['status cancelled on panel', '--color-temper-cancelled', '--temper-panel', TEXT, 'status'],
  ['status waiting on panel', '--color-temper-waiting', '--temper-panel', TEXT, 'status'],
  ['status skipped on panel', '--color-temper-skipped', '--temper-panel', TEXT, 'status'],
  ['status completed on page', '--color-temper-completed', '--temper-bg', TEXT, 'status'],
  ['status running on page', '--color-temper-running', '--temper-bg', TEXT, 'status'],
  ['status failed on page', '--color-temper-failed', '--temper-bg', TEXT, 'status'],
  ['status pending dot on panel', '--color-temper-pending', '--temper-panel', UI, 'status'],
  ['badge completed', '--badge-completed-text', 'tint:--badge-completed-bg@1:--temper-panel', TEXT, 'status'],
  ['badge running', '--badge-running-text', 'tint:--badge-running-bg@1:--temper-panel', TEXT, 'status'],
  ['badge failed', '--badge-failed-text', 'tint:--badge-failed-bg@1:--temper-panel', TEXT, 'status'],
  ['badge pending', '--badge-pending-text', 'tint:--badge-pending-bg@1:--temper-panel', TEXT, 'status'],
];

// Green text on the light second surface measures 4.01:1; the handoff keeps
// it off there, so light only checks green text on paper and white (above).
// Dark green text is fine on its second surface too:
const darkOnly = [
  ['green text/link on surface', '--temper-accent', '--temper-surface', TEXT, 'text'],
];

// Light swaps Tailwind's -400 text shades (made for dark grounds) for darker
// ones (the :root:not(.dark) block); they must read on every light ground and
// on their own tint.
const lightOnly = [];
for (const hue of ['emerald', 'blue', 'amber', 'violet', 'red', 'yellow', 'cyan']) {
  for (const ground of ['--temper-bg', '--temper-panel', '--temper-surface']) {
    lightOnly.push([`${hue} text on ${ground.slice(9)}`, `--temper-${hue}`, ground, TEXT, 'semantic']);
  }
  if (['emerald', 'blue', 'amber', 'violet', 'red'].includes(hue)) {
    lightOnly.push([`${hue} text on its tint`, `--temper-${hue}`, `--temper-${hue}-bg`, TEXT, 'semantic']);
  }
}

function colourOf(vars, spec) {
  if (spec.startsWith('tint:')) {
    const [, rest] = spec.split('tint:');
    const [tint, ground] = rest.split(':');
    const [tintVar, alpha] = tint.split('@');
    const c = parseColour(resolve(vars, vars[tintVar] ?? tintVar));
    const g = parseColour(resolve(vars, vars[ground] ?? ground));
    return over({ ...c, a: c.a * Number(alpha) }, g);
  }
  const raw = vars[spec];
  if (raw === undefined) throw new Error(`missing ${spec}`);
  return parseColour(resolve(vars, raw));
}

function measure(themeName, vars, pairs) {
  return pairs.map(([label, fg, bg, min, kind]) => {
    const ground = colourOf(vars, bg);
    const fgc = colourOf(vars, fg);
    const fgFlat = fgc.a < 1 ? over(fgc, ground) : fgc;
    const r = ratio(fgFlat, ground);
    return {
      theme: themeName,
      label,
      kind,
      fg: `${fg} ${hex(fgFlat)}`,
      bg: `${bg} ${hex(ground)}`,
      ratio: Math.round(r * 100) / 100,
      min,
      pass: r >= min,
    };
  });
}

const results = [
  ...measure('dark', dark, [...common, ...darkOnly]),
  ...measure('light', light, [...common, ...lightOnly]),
];

// ---- the automatic light block must equal the explicit one ---------------

const driftKeys = [...new Set([...Object.keys(lightExplicit), ...Object.keys(lightAuto)])];
const drift = driftKeys.filter((k) => lightExplicit[k] !== lightAuto[k]);

// ---- leftovers of the old theme --------------------------------------------

// The old navy/cyan/blue theme (src/index.css before the logo handoff):
// its page, panel, surface, border, text and accent colours in both themes.
const OLD = [
  '#1a1a2e', '#0f1729', '#1e2a4a', '#2a3a5c', '#3a4a6c', '#4fc3f7', '#60a5fa',
  '#e0e0e0', '#8a8fa0', '#8a90a0', '#6a7080', '#5a6070', '#7d8698',
  '#f0f2f5', '#f5f7fa', '#e8ecf2', '#d0d7e3', '#c8cfe0', '#b8c2d4', '#b0bace',
  '#1976d2', '#edf0f5', '#111827', '#f3f4f6', '#e5e7eb', '#d1d5db', '#9ca3af',
  '#4b5563', '#374151',
];
const oldRgb = [
  'rgba(15, 23, 41', 'rgba(15,23,41', 'rgb(15 23 41', 'rgba(100, 116, 139', 'rgba(100,116,139',
];

function scan(text) {
  const lower = text.toLowerCase();
  const hits = OLD.filter((c) => new RegExp(`${c}(?![0-9a-f])`).test(lower));
  return [...hits, ...oldRgb.filter((c) => lower.includes(c))];
}

const leftovers = [];
for (const c of scan(cssText)) leftovers.push({ where: `dist/assets/${cssFile}`, colour: c });
function walk(dir) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, entry.name);
    if (entry.isDirectory()) walk(p);
    else if (/\.(tsx?|css)$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name) && !p.includes('__tests__')) {
      for (const c of scan(fs.readFileSync(p, 'utf8'))) leftovers.push({ where: path.relative(root, p), colour: c });
    }
  }
}
walk(path.join(root, 'src'));

// ---- report -------------------------------------------------------------------

const failed = results.filter((r) => !r.pass);
const pad = (s, n) => String(s).padEnd(n);
for (const r of results) {
  console.log(
    `${r.pass ? 'ok  ' : 'FAIL'} ${pad(r.theme, 5)} ${pad(r.label, 38)} ${pad(r.ratio.toFixed(2), 6)} >= ${r.min}  ${r.fg} on ${r.bg}`,
  );
}
console.log('');
console.log(`pairs: ${results.length}, failed: ${failed.length}`);
console.log(`light blocks identical: ${drift.length === 0 ? 'yes' : 'NO: ' + drift.join(', ')}`);
console.log(`old theme colours left: ${leftovers.length === 0 ? 'none' : ''}`);
for (const l of leftovers) console.log(`  ${l.colour} in ${l.where}`);

const jsonAt = process.argv.indexOf('--json');
if (jsonAt > 0 && process.argv[jsonAt + 1]) {
  fs.writeFileSync(
    process.argv[jsonAt + 1],
    JSON.stringify({ css: cssFile, results, drift, leftovers }, null, 2) + '\n',
  );
}

process.exit(failed.length || drift.length || leftovers.length ? 1 : 0);
