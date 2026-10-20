// Fictional offline DOM doubles run the extractor's actual ::before/::after code (queue #103, H9), never a copy.
// The real-browser proof (pixels, the keyed pseudo-v1 pages) is tests/test_converter_pseudo.py's browser test.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const source = fs.readFileSync(process.argv[2], 'utf8');
const between = (a, b) => {
  const i = source.indexOf(a), j = source.indexOf(b, i);
  assert.ok(i >= 0 && j > i, 'section markers moved: ' + a);
  return source.slice(i, j);
};
const make = (code, names, scope) => Function(...Object.keys(scope), code + '\nreturn {' + names.join(',') + '};')(...Object.values(scope));
const camel = (k) => k.replace(/-([a-z])/g, (_, c) => c.toUpperCase());

class Decl {
  constructor(props) {
    this._p = {...props};
    const names = Object.keys(this._p);
    names.forEach((n, i) => { this[i] = n; this[camel(n)] = this._p[n]; });
    this.length = names.length;
  }
  getPropertyValue(n) { return this._p[n] ?? ''; }
}
const PSEUDO_DEFAULTS = {
  display: 'inline', visibility: 'visible', opacity: '1', color: 'rgb(17, 24, 39)',
  'background-color': 'rgba(0, 0, 0, 0)', 'background-image': 'none', 'box-shadow': 'none',
  'outline-style': 'none', 'outline-width': '0px', 'outline-color': 'rgb(17, 24, 39)',
  width: 'auto', height: 'auto', '--brand': '#123456',
  ...Object.fromEntries(['top', 'right', 'bottom', 'left'].flatMap((s) => [
    ['border-' + s + '-width', '0px'], ['border-' + s + '-style', 'none'], ['border-' + s + '-color', 'rgb(17, 24, 39)']])),
};
const pseudoDecl = (props) => new Decl({...PSEUDO_DEFAULTS, ...props});
const INHERITED = ['color', 'line-height', 'font-size', 'font-weight'];
const NONE = new Decl({content: 'none'});

let heads = [];
const doc = {tagName: 'HTML', localName: 'html', parentElement: null, cs: {opacity: '1'}};
const body = {tagName: 'BODY', localName: 'body', parentElement: doc, children: [], cs: {opacity: '1'}};
const descendants = (n) => (n.children || []).flatMap((c) => [c, ...descendants(c)]);
const document = {
  documentElement: doc, body,
  head: {appendChild(s) { heads.push(s); s.remove = () => { heads = heads.filter((x) => x !== s); }; }},
  createElement(tag) {
    const style = {setProperty(k, v) { this[camel(k)] = v; this._set[k] = v; }, _set: {}};
    const span = {tagName: tag.toUpperCase(), localName: tag, namespaceURI: 'http://www.w3.org/1999/xhtml', style, dataset: {},
      textContent: '', children: [], parentElement: null,
      remove() { if (this.parentElement) this.parentElement.children = this.parentElement.children.filter((c) => c !== this); this.parentElement = null; },
      size() {
        const w = parseFloat(this.style.width), h = parseFloat(this.style.height);
        // an auto text span measures 8 px per character and 20 px high; a fixed size is used as given
        return {w: w >= 0 ? w : this.textContent.length * 8 + (this.autoExtra || 0), h: h >= 0 ? h : (this.textContent ? 20 : 0)};
      },
      getBoundingClientRect() { const s = this.size(); return {x: 0, y: 0, width: s.w, height: s.h}; }};
    body.created.push(span);
    return span;
  },
};
body.created = [];
body.querySelectorAll = () => descendants(body);
const el = (tag, opts = {}) => {
  const e = {tagName: tag.toUpperCase(), localName: tag, namespaceURI: 'http://www.w3.org/1999/xhtml', id: opts.id || '',
    attrs: {...(opts.attrs || {})}, pseudo: opts.pseudo || {}, cs: {display: 'block', visibility: 'visible', opacity: '1', ...(opts.cs || {})},
    srOnly: !!opts.srOnly, rendered: opts.rendered !== false, children: [], parentElement: null, rectFn: opts.rectFn,
    getAttribute(k) { return Object.hasOwn(this.attrs, k) ? this.attrs[k] : null; },
    setAttribute(k, v) { this.attrs[k] = String(v); },
    removeAttribute(k) { delete this.attrs[k]; },
    get firstChild() { return this.children[0] || null; },
    insertBefore(n, ref) { n.parentElement = this; const i = ref ? this.children.indexOf(ref) : -1; if (i < 0) this.children.push(n); else this.children.splice(i, 0, n); },
    appendChild(n) { n.parentElement = this; this.children.push(n); },
    getClientRects() { return this.rendered ? [this.getBoundingClientRect()] : []; },
    getBoundingClientRect() { return this.rectFn ? this.rectFn(this) : {x: 10, y: 10, width: 100, height: 20}; }};
  return e;
};
const add = (parent, child) => { child.parentElement = parent; parent.children.push(child); return child; };
const getComputedStyle = (e, pseudo) => {
  if (e.style && e.size) {  // a created span: initial values, what it inherits from its host, its inline style
    const s = e.size();
    const host = e.parentElement || {cs: {}};
    const inherited = Object.fromEntries(INHERITED.filter((n) => host.cs[n] !== undefined).map((n) => [n, host.cs[n]]));
    const set = e.style._set;
    // an inline span has no used size (width and height compute to auto), any other box measures
    const sized = (set.display || 'inline') !== 'inline';
    return new Decl({...PSEUDO_DEFAULTS, ...inherited, ...set,
      width: sized ? s.w + 'px' : 'auto', height: sized ? s.h + 'px' : 'auto'});
  }
  if (!pseudo) return e.cs;
  const side = pseudo.replace('::', '');
  if ((e.getAttribute('data-pp-pseudo-off') || '').split(' ').includes(side)) return NONE;
  return e.pseudo[side] ? pseudoDecl(e.pseudo[side]) : NONE;
};
const parseColor = (v) => {
  if (!v || v === 'transparent') return {opacity: 0};
  const m = String(v).match(/rgba?\(([^)]*)\)/);
  if (!m) return null;
  const parts = m[1].split(',').map((x) => parseFloat(x));
  return {opacity: parts.length > 3 ? parts[3] : 1};
};
const issues = [];
const issue = (kind, e, detail) => issues.push({kind, id: e && e.id, detail});
const where = (e) => (e && e.id ? '#' + e.id : '');
const screenReaderOnly = (e) => !!e.srOnly;
const SKIP = new Set(['script', 'style']);

const code = between('  // ---------- pseudo-elements (::before, ::after) ----------', '  materialise();');
const fresh = () => make(code, ['pseudoContent', 'boxPaint', 'materialise', 'pseudoRestore', 'pseudoRecords', 'pseudoSpans'],
  {getComputedStyle, parseColor, issue, where, screenReaderOnly, SKIP, doc, document});

// ---- content values -> text, or why it can't be drawn
const P = fresh();
const host = el('p', {attrs: {'data-unit': 'per candle'}});
assert.deepEqual(P.pseudoContent('"✓"', host), {text: '✓'});
assert.deepEqual(P.pseudoContent('"\\2713  x"', host), {text: '✓ x'});
assert.deepEqual(P.pseudoContent('"a" "b"', host), {text: 'ab'});
assert.deepEqual(P.pseudoContent('" " attr(data-unit)', host), {text: ' per candle'});
assert.deepEqual(P.pseudoContent('"→" / "next"', host), {text: '→'});
assert.deepEqual(P.pseudoContent('""', host), {text: ''});
assert.deepEqual(P.pseudoContent('counter(step) "."', host), {undrawable: 'counter'});
assert.deepEqual(P.pseudoContent('counters(item, ".")', host), {undrawable: 'counter'});
assert.deepEqual(P.pseudoContent('url("dot.svg")', host), {undrawable: 'image'});
assert.deepEqual(P.pseudoContent('linear-gradient(red, blue)', host), {undrawable: 'image'});
assert.deepEqual(P.pseudoContent('open-quote', host), {undrawable: 'quote'});
assert.deepEqual(P.pseudoContent('no-open-quote "x"', host), {text: 'x'});

// ---- box paint: background, a visible border on any side, shadow, outline; never transparent or zero-width
const paint = (props) => P.boxPaint(pseudoDecl(props));
assert.equal(paint({}), false);
assert.equal(paint({'background-color': 'rgb(34, 197, 94)'}), true);
assert.equal(paint({'background-color': 'rgba(34, 197, 94, 0)'}), false);
assert.equal(paint({'background-image': 'linear-gradient(red, blue)'}), true);
assert.equal(paint({'border-bottom-width': '3px', 'border-bottom-style': 'solid'}), true);
assert.equal(paint({'border-bottom-width': '3px', 'border-bottom-style': 'none'}), false);
assert.equal(paint({'border-left-width': '2px', 'border-left-style': 'solid', 'border-left-color': 'rgba(0, 0, 0, 0)'}), false);
assert.equal(paint({'box-shadow': 'rgb(0, 0, 0) 0px 0px 0px 2px'}), true);
assert.equal(paint({'outline-style': 'solid', 'outline-width': '1px'}), true);

// ---- the materialiser on a fictional page
const dot = {content: '""', display: 'inline-block', width: '8px', height: '8px', 'background-color': 'rgb(34, 197, 94)', 'border-top-left-radius': '50%'};
const page = [
  // the tick inherits its line height from the li, as Signalbox's do; the arrow sets its own
  ['tick', el('li', {id: 'tick', cs: {'line-height': '27.2px', 'font-size': '17px'},
    pseudo: {before: {content: '"✓"', color: 'rgb(63, 98, 18)', 'margin-right': '8px', 'line-height': '27.2px', 'font-size': '17px'}}})],
  ['arrow', el('p', {id: 'arrow', cs: {'line-height': '24px'}, pseudo: {after: {content: '"→"', 'line-height': '16px'}}})],
  ['dot', el('span', {id: 'dot', pseudo: {before: dot}})],
  ['pill', el('p', {id: 'pill', pseudo: {before: {content: '"New"', display: 'inline-block', width: '24px', height: '20px', 'background-color': 'rgb(253, 230, 138)'}}})],
  ['fixed', el('p', {id: 'fixed', pseudo: {after: {content: '"Hi"', display: 'inline-block', width: '40px', height: '20px'}}})],
  ['none', el('div', {id: 'none', pseudo: {before: {content: 'none', 'background-color': 'rgb(255, 0, 0)', width: '10px', height: '10px'}}})],
  ['clear', el('div', {id: 'clear', pseudo: {after: {content: '""', display: 'table'}}})],
  ['clear-text', el('div', {id: 'clear-text', pseudo: {after: {content: '"x"', color: 'rgba(0, 0, 0, 0)'}}})],
  ['zero', el('div', {id: 'zero', pseudo: {after: {content: '""', width: '0px', height: '0px', 'background-color': 'rgb(1, 2, 3)'}}})],
  ['count', el('li', {id: 'count', pseudo: {before: {content: 'counter(step) "."'}}})],
  ['icon', el('a', {id: 'icon', pseudo: {after: {content: 'url("arrow.svg")'}}})],
  ['image-box', el('a', {id: 'image-box', pseudo: {after: {content: 'url("arrow.svg")', 'background-color': 'rgb(1, 2, 3)'}}})],
  ['hidden', el('p', {id: 'hidden', rendered: false, pseudo: {before: {content: '"✓"'}}})],
  ['sr', el('p', {id: 'sr', srOnly: true, pseudo: {before: {content: '"✓"'}}})],
  ['img', el('img', {id: 'img', pseudo: {before: {content: '"x"'}}})],
  ['mover', el('p', {id: 'mover', pseudo: {before: {content: '"→"'}}})],
];
const byId = Object.fromEntries(page.map(([k, e]) => [k, add(body, e)]));
// 'mover' grows when its span is in it: as an element it would move the page, so it must be undone
const sibling = add(body, el('p', {id: 'sibling', rectFn: () => ({x: 10, y: byId.mover.children.length ? 41 : 40, width: 100, height: 20})}));
// the fixed-width pseudo's span really needs its width: sized by itself it measures 16 px, not 40
const M = fresh();
M.materialise();
const rec = Object.fromEntries(M.pseudoRecords.map((r) => [r.id, r]));
assert.deepEqual(Object.keys(rec).sort(), ['arrow', 'count', 'dot', 'fixed', 'icon', 'image-box', 'mover', 'pill', 'tick'].sort());
assert.equal(rec.tick.kind, 'text'); assert.equal(rec.tick.text, '✓'); assert.equal(rec.tick.pseudo, '::before');
assert.equal(rec.dot.kind, 'shape'); assert.equal(rec.dot.text, '');
assert.equal(rec.pill.kind, 'box'); assert.equal(rec.pill.text, 'New');
assert.equal(rec.count.not_drawn, 'counter');
assert.equal(rec.icon.not_drawn, 'image'); assert.equal(rec['image-box'].not_drawn, 'image');
assert.equal(rec.mover.not_drawn, 'layout-changed');
const spanOf = (e) => e.children.find((c) => c.dataset && c.dataset.ppPseudo);
// a text span carries the pseudo's text and copied style, never 'content' or custom properties
const tick = spanOf(byId.tick);
assert.equal(tick.textContent, '✓');
assert.equal(tick.style._set.color, 'rgb(63, 98, 18)');
assert.ok(!('content' in tick.style._set) && !('--brand' in tick.style._set));
// only what differs from what the span gets in its place is set: an inherited line height stays inherited
// (pinning its rounded value moved Signalbox's pricing lists by 1/64 px), one of its own is set
assert.deepEqual(Object.keys(tick.style._set).sort(), ['color', 'margin-right'].sort());
assert.equal(spanOf(byId.arrow).style._set['line-height'], '16px');
assert.equal(spanOf(byId.arrow).textContent, '→');
assert.equal(tick.dataset.ppSide, '::before');
assert.equal(byId.tick.children[0], tick);  // ::before goes first
assert.equal(byId.tick.getAttribute('data-pp-pseudo-off'), 'before');
// a text pseudo that sizes to its text keeps auto size; one whose fixed size matters keeps it
assert.equal(spanOf(byId.pill).style.width, '');
assert.equal(spanOf(byId.fixed).style.width, '40px');
assert.equal(byId.fixed.children[byId.fixed.children.length - 1], spanOf(byId.fixed));  // ::after goes last
// the shape keeps its size and paint
const dotSpan = spanOf(byId.dot);
assert.equal(dotSpan.style.width, '8px'); assert.equal(dotSpan.style.backgroundColor, 'rgb(34, 197, 94)');
assert.equal(dotSpan.textContent, '');
// nothing for no paint, a zero-size box, hidden hosts, replaced elements, or undrawable content
for (const k of ['none', 'clear', 'clear-text', 'zero', 'hidden', 'sr', 'img', 'count', 'icon', 'mover'])
  assert.equal(spanOf(byId[k]), undefined, k);
assert.equal(byId.mover.getAttribute('data-pp-pseudo-off'), null);
// undrawable or undone ones are filed, by name of the problem
const filed = issues.filter((i) => i.kind === 'pseudo-element-not-drawn').map((i) => i.id).sort();
assert.deepEqual(filed, ['count', 'icon', 'image-box', 'mover'].sort());
assert.ok(issues.every((i) => i.kind === 'pseudo-element-not-drawn'));
assert.equal(heads.length, 1);  // the rule that switches the pseudo-elements off while their spans stand in
// restore: the page is back as it was
M.pseudoRestore();
for (const e of body.children) {
  assert.equal(spanOf(e), undefined);
  assert.equal(e.getAttribute('data-pp-pseudo-off'), null);
}
assert.equal(heads.length, 0);
assert.equal(sibling.getBoundingClientRect().y, 40);
console.log(JSON.stringify({passed: true}));
