// Fictional offline DOM doubles execute the actual extractor helpers, never a copy of them.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const source = fs.readFileSync(process.argv[2], 'utf8');
const between = (a, b) => source.slice(source.indexOf(a), source.indexOf(b));
const make = (code, names, scope) => Function(...Object.keys(scope), code + '\nreturn {' + names.join(',') + '};')(...Object.values(scope));
const r2 = v => Math.round(v * 100) / 100;
const clean = s => String(s || '').replace(/\s+/g, ' ').trim();
const warnings = [];
const issue = (...args) => warnings.push(args);
const getComputedStyle = (el, pseudo) => pseudo ? el.pseudo : el.cs;
const el = (tag, attrs = {}) => ({tagName: tag.toUpperCase(), cs: {display: 'list-item'}, attrs,
  hasAttribute(k) { return Object.hasOwn(this.attrs, k); }, getAttribute(k) { return this.attrs[k] ?? null; }});
const list = (attrs, items = [{}, {}, {}]) => {
  const root = el('ol', attrs); root.children = items.map(a => el('li', a));
  root.children.forEach(c => c.parentElement = root); return root;
};
const markers = make(between('  const alphabet =', '  // ---------- layout facts'),
  ['markerText', 'drawMarker'], {getComputedStyle, issue, r2,
    stats: {list_items: 0, markers: 0}, lists: [], registering: true,
    where: () => 'ul > li', sx: 0, sy: 0,
    styleOf: (_e, pseudo) => {assert.equal(pseudo, '::marker'); return {family: 'Beacon Sans', size: 18, weight: '400', style: 'normal', color: '#17634A', opacity: 1};},
    document: {createElement: () => ({getContext: () => ({measureText: s => ({width: s.length * 8})})})}});
const value = (root, style, pseudo = {}) => root.children.map(e => markers.markerText(e, {listStyleType: style}, pseudo));
assert.deepEqual(value(list({start: '4'}), 'decimal'), ['4.', '5.', '6.']);
assert.deepEqual(value(list({reversed: '', start: '9'}, [{}, {value: '6'}, {}]), 'upper-roman'), ['IX.', 'VI.', 'V.']);
assert.deepEqual(value(list({reversed: ''}), 'decimal'), ['3.', '2.', '1.']);
assert.deepEqual(value(list({start: '26'}), 'lower-alpha'), ['z.', 'aa.', 'ab.']);
assert.deepEqual(value(list({start: '-2'}), 'decimal-leading-zero'), ['-02.', '-01.', '00.']);
for (const [type, symbol] of [['disc', '•'], ['circle', '◦'], ['square', '▪'], ['none', '']])
  assert.equal(value(list({}), type)[0], symbol);
assert.equal(value(list({}), 'disc', {content: '"→"'})[0], '→');
const item = list({}).children[0];
item.getBoundingClientRect = () => ({left: 32, top: 100});
item.pseudo = {content: 'normal'};
const children = [{kind: 'text', text: {lines: [{text: 'Check label', x: 32, y: 120, h: 20}]}}];
markers.drawMarker(item, {display: 'list-item', listStyleType: 'disc', listStylePosition: 'outside', paddingLeft: '0', lineHeight: '24'}, children);
const drawn = children[1];
assert.equal(drawn.text.plain, '•');
assert.equal(drawn.text.paragraphs[0][0].style.color, '#17634A');
assert.equal(drawn.text.paragraphs[0][0].style.size, 18);
assert.equal(drawn.box.x, 16); assert.equal(drawn.box.y, 100);

const textures = [];
const fnv = make(between('  const fnv =', '  const FULL_SIZE'), ['fnv'], {}).fnv;
const hidden = make(between('  const screenReaderOnly =', '  const alphabet ='), ['screenReaderOnly', 'formText', 'nativeWidget'],
  {clean, getComputedStyle, sx: 0, sy: 0, short: s => s, omittedText: [], where: () => 'span.sr-only',
    textures, fnv, r2, issue, box: r => ({x:r.left, y:r.top, w:r.width, h:r.height}),
    document: {body: {appendChild() {}}, createElement() { const m = {style: {setProperty(k, v) {this[k] = v;}}, remove() {this.removed = true;}};
      Object.defineProperty(m, 'childNodes', {get: () => [{data: m.textContent}]}); return m; }},
    emitRun(nodes, mirror, out) {out.push({kind: 'text', fit: 'height', text: {plain: nodes[0].data}, mirror});}});
assert.equal(hidden.screenReaderOnly({getBoundingClientRect: () => ({width: 1, height: 1})},
  {position: 'absolute', clip: 'rect(0px,0px,0px,0px)', clipPath: 'none', overflow: 'hidden'}), true);
assert.equal(hidden.screenReaderOnly({getBoundingClientRect: () => ({width: 200, height: 20})},
  {position: 'absolute', clip: 'auto', clipPath: 'none', overflow: 'hidden'}), false);
const field = (tag, opts) => ({tagName: tag.toUpperCase(), type: 'text', value: '', pseudo: {color: '#657784'},
  getAttribute: name => name === 'placeholder' ? 'Enter reference' : null, ...opts});
const cs = {getPropertyValue: name => ({color:'#14212E', 'overflow-wrap':'break-word', 'word-break':'normal'}[name] || '0px'), appearance: 'none'};
for (const [control, expected, fit] of [[field('input', {value: 'Harbor depot'}), 'Harbor depot', 'clip'],
  [field('input', {}), 'Enter reference', 'clip'], [field('select', {selectedOptions: [{text: 'East loop'}]}), 'East loop', 'clip'],
  [field('textarea', {value: 'First\n\nLast'}), 'First\n\nLast', 'height'],
  [field('input', {type: 'password'}), 'Enter reference', 'clip'],
  [field('input', {type: 'password', value: 'private'}), '•••••••', 'clip']]) {
  const out = []; hidden.formText(control, cs, {left: 20, top: 60, width: 300, height: 100}, out);
  assert.equal(out[0].text.plain, expected); assert.equal(out[0].fit, fit); assert.equal(out[0].mirror.removed, true);
  if (!control.value && control.tagName !== 'SELECT') assert.equal(out[0].mirror.style.color, '#657784');
  if (control.tagName === 'TEXTAREA') {
    assert.equal(out[0].mirror.style['overflow-wrap'], 'break-word');
    assert.equal(out[0].mirror.style['word-break'], 'normal');
  }
}
const empty = []; hidden.formText(field('input', {type: 'checkbox'}), cs, {}, empty); assert.deepEqual(empty, []);
const skin = [], rect = {left:32, top:100, width:16, height:16};
const checkbox = field('input', {type:'checkbox', checked:true});
const nativeStyle = {appearance:'auto', accentColor:'#17634A', colorScheme:'normal'};
hidden.nativeWidget(checkbox, nativeStyle, rect, skin);
hidden.nativeWidget(checkbox, nativeStyle, rect, skin);
assert.equal(textures.length, 1); assert.equal(textures[0].widget.checked, true); assert.equal(skin[0].fills[0].texture, true);
assert.deepEqual(textures[0].crop, {x:32, y:100, w:16, h:16});
hidden.nativeWidget({...checkbox, checked:false}, nativeStyle, rect, skin); assert.equal(textures.length, 2);
hidden.nativeWidget(checkbox, {...nativeStyle, appearance:'none'}, rect, skin); assert.equal(skin.length, 3);

// Independent underline colour and offset are not silently changed to text ink.
const underlineStyle = {fontSize:'16px', fontWeight:'400', fontStyle:'normal', lineHeight:'20px', color:'#FFFFFF',
  textDecorationLine:'underline', textDecorationColor:'#71DBAB', textUnderlineOffset:'2px', textDecorationThickness:'auto',
  textDecorationStyle:'solid', letterSpacing:'normal', textTransform:'none'};
const styles = make(between('  const styleOf =', '  const sameStyle'), ['styleOf'],
  {getComputedStyle: () => underlineStyle, familyOf: () => 'Beacon Sans',
    parseColor: v => v ? {color:v, opacity:1} : null, usedFonts:new Map(), issue});
const styled = styles.styleOf({tagName:'A', closest:() => null});
assert.equal(styled.decoration, 'none'); assert.equal(styled.underline.color, '#71DBAB'); assert.equal(styled.underline.offset, 2);

// Active computed custom properties: an inactive selector's value is never enumerated.
const varsCode = between('  const vars = [];', '  // ---------- fonts');
const style = Object.assign(['--paper', '--ink', '--size'], {getPropertyValue: n => ({'--paper': '#14212E', '--ink': '#FFFFFF', '--size': '12px'})[n]});
const vars = make(varsCode, ['vars'], {doc: {}, getComputedStyle: () => style,
  parseColor: v => /^#[0-9A-F]{6}$/.test(v) ? {color: v, opacity: 1} : null}).vars;
assert.deepEqual(vars.map(v => v.color), ['#14212E', '#FFFFFF']);

const layout = make(between('  const layoutOf =', '  // How this element sits'), ['layoutOf', 'widthSamples'],
  {r2, gapPx: () => 0, tracks: () => [], specified: () => '', getComputedStyle,
    document: {createElement() {return {style: {setProperty(k, v) {this[k] = v;}}, appendChild(child) {child.parent = this;}, remove() {this.removed = true;},
      getBoundingClientRect() {return {width: parseFloat(this.parent.style.width) / 3 - 128 / 3};}};}}});
const row = {cells: [180, 300, 120].map(width => ({colSpan: 1, getBoundingClientRect: () => ({width})})),
  getBoundingClientRect: () => ({height: 32}), closest() {return {rows: [this]};}};
const rowLayout = layout.layoutOf(row, {display: 'table-row', textAlign: 'left'});
assert.equal(rowLayout.display, 'grid'); assert.equal(rowLayout.colsSpec, '30.00000000% 50.00000000% 20.00000000%');
assert.deepEqual(rowLayout.cols, [180, 300, 120]); assert.equal(rowLayout.tableColumns, true);
const parent = {clientWidth: 1340, cs: {paddingLeft: '10px', paddingRight: '10px'}, appendChild(host) {this.host = host;}};
const measured = layout.widthSamples({parentElement: parent}, Object.assign(['--allowance'], {getPropertyValue: () => '128px'}), 'calc((100% - 128px) / 3)');
assert.equal(measured.parent, 1320); assert.equal(measured.samples.length, 4); assert.equal(parent.host.removed, true);
for (const [p, w] of measured.samples) assert.ok(Math.abs(w - (p - 128) / 3) < .011);

// Requested synthetic mono weight retains its nearest actually loaded face for upload.
const fontCode = 'const selected = ' + between('fonts.filter((f) => [...usedFonts.values()].some((u) => {', '    fontsUsed:').replace(/,\s*$/, '') + ';';
const fonts = [{family: 'Beacon Sans', weight: '400', style: 'normal'}, {family: 'DejaVu Sans Mono', weight: '400', style: 'normal'}];
const selected = make(fontCode, ['selected'], {fonts, usedFonts: new Map([['mono', {family: 'DejaVu Sans Mono', weight: '600', style: 'normal'}]])}).selected;
assert.deepEqual(selected, [fonts[1]]);
console.log(JSON.stringify({passed: true, contracts: ['list markers', 'form text', 'hidden text', 'active theme', 'table columns', 'width probes', 'synthetic mono weight']}));
