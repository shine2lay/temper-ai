// What the checks step (stage 6a) measures that design_measure.js and measure_in_page.js do not:
// the prototype contract's marks, the figures in the rendered text, the colours/fonts/sizes actually
// used, the hierarchy counts and control labels that wrap. Evaluated in the page by checks_render.py
// after the other two, look-only: it reads the DOM and computed styles and changes nothing.
// One function expression, called with the thresholds: (cfg) => ({...}).
(cfg) => {
  const LIMIT = cfg.limit || 25;
  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const visible = (el) => {
    if (!el || !el.getClientRects().length) return false;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none' || parseFloat(cs.opacity) === 0) return false;
    return !el.closest('[hidden], .sr-only, [aria-hidden="true"]');
  };
  const sel = (el) => {
    const parts = [];
    for (let e = el; e && e !== document.body && parts.length < 4; e = e.parentElement) {
      if (e.id) { parts.unshift('#' + e.id); break; }
      let s = e.tagName.toLowerCase();
      if (e.classList.length) s += '.' + [...e.classList].slice(0, 2).join('.');
      const sib = e.parentElement ? [...e.parentElement.children].filter((x) => x.tagName === e.tagName) : [];
      if (sib.length > 1) s += `:nth-of-type(${sib.indexOf(e) + 1})`;
      parts.unshift(s);
    }
    return parts.join(' > ');
  };
  const label = (el) => clean(el.getAttribute('aria-label') || el.innerText || el.value || el.title || '').slice(0, 60);
  const parse = (c) => {
    const m = (c || '').match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const p = m[1].split(/[\s,\/]+/).filter(Boolean).map(Number);
    return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1];
  };
  const lum = ([r, g, b]) => {
    const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
  };
  const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
  const blend = (fg, bg) => { const a = fg[3]; return [0, 1, 2].map((i) => fg[i] * a + bg[i] * (1 - a)).concat([1]); };
  const bgOf = (el) => {
    const layers = [];
    for (let e = el; e; e = e.parentElement) {
      const c = parse(getComputedStyle(e).backgroundColor);
      if (c && c[3] > 0) { layers.push(c); if (c[3] >= 1) break; }
    }
    let bg = [255, 255, 255, 1];
    for (let i = layers.length - 1; i >= 0; i--) bg = blend(layers[i], bg);
    return bg;
  };
  const rgb = (c) => `rgb(${c.slice(0, 3).map(Math.round).join(',')})`;

  const out = { url: location.pathname + location.hash, viewport: [innerWidth, innerHeight] };

  // ---------------------------------------------------------------- the contract's marks
  const screens = [...document.querySelectorAll('[data-screen]')];
  const shownScreens = screens.filter(visible);
  out.contract = {
    marked: screens.length > 0,
    screens: [...new Set(screens.map((el) => el.getAttribute('data-screen')))].slice(0, 60),
    shown: [...new Set(shownScreens.map((el) => el.getAttribute('data-screen')))].slice(0, 60),
    states: [...new Set([...document.querySelectorAll('[data-view-state]')].filter(visible)
      .map((el) => el.getAttribute('data-view-state')))].slice(0, 20),
    banned_state_attr: [...document.querySelectorAll('[data-state], [data-st-state]')]
      .filter((el) => el !== document.documentElement && el !== document.body)
      .slice(0, LIMIT).map((el) => ({ sel: sel(el), attr: el.hasAttribute('data-st-state') ? 'data-st-state' : 'data-state' })),
  };
  out.reqs = {};
  for (const el of document.querySelectorAll('[data-req]')) {
    for (const id of (el.getAttribute('data-req') || '').split(/\s+/).filter(Boolean)) {
      const rec = out.reqs[id] || (out.reqs[id] = { visible: 0, hidden: 0, sel: '', text: '' });
      if (visible(el)) { rec.visible++; if (!rec.sel) { rec.sel = sel(el); rec.text = clean(el.innerText).slice(0, 60); } }
      else rec.hidden++;
    }
  }
  // idx = this control's place among the elements carrying the same data-action, so the click step can
  // find it again by attribute: a CSS path drifts when the page re-renders between measure and click.
  const actionSeen = {};
  out.actions = [...document.querySelectorAll('[data-action]')].slice(0, 200).map((el) => {
    const action = el.getAttribute('data-action');
    const idx = actionSeen[action] = (action in actionSeen ? actionSeen[action] + 1 : 0);
    return { action, idx, sel: sel(el), label: label(el), visible: visible(el),
             tag: el.tagName.toLowerCase() };
  });

  // ---------------------------------------------------------------- visible text: sizes, colours, figures
  const runs = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const node = walker.currentNode;
    const text = clean(node.textContent);
    if (!text) continue;
    const el = node.parentElement;
    if (!el || el.closest('script, style, noscript, template, svg') || !visible(el)) continue;
    const cs = getComputedStyle(el);
    const bg = bgOf(el);
    const fg = blend(parse(cs.color) || [0, 0, 0, 1], bg);
    runs.push({ el, text, size: parseFloat(cs.fontSize), weight: parseInt(cs.fontWeight, 10),
      family: cs.fontFamily.split(',')[0].replace(/["']/g, '').trim(), color: rgb(fg), background: rgb(bg),
      contrast: +ratio(fg, bg).toFixed(2) });
  }
  const sizes = [...new Set(runs.map((r) => r.size))].sort((a, b) => b - a);
  const colours = {};
  for (const r of runs) if (r.text.length > 1) colours[r.color] = (colours[r.color] || 0) + 1;
  // A contrast level is how strongly the text stands against its background, not its hue: two colours of
  // the same strength (a purple link beside black body text) are one level, and that is what the eye
  // sorts by. The bands come from the thresholds file.
  const bands = cfg.contrast_levels || [12, 7, 4.5, 3];
  const bandNames = ['strongest', 'strong', 'normal', 'soft', 'faint'];
  const levels = {};
  for (const r of runs) {
    if (r.text.length <= 1) continue;
    let i = 0;
    while (i < bands.length && r.contrast < bands[i]) i++;
    const entry = levels[i] || (levels[i] = { runs: 0, colours: {}, example: r.text.slice(0, 30) });
    entry.runs++;
    entry.colours[r.color] = (entry.colours[r.color] || 0) + 1;
  }
  out.hierarchy = {
    text_sizes: sizes,
    text_levels: Object.entries(levels).sort((a, b) => Number(a[0]) - Number(b[0])).map(([i, v]) => ({
      level: bandNames[Number(i)] || `band ${i}`, runs: v.runs, example: v.example,
      colours: Object.entries(v.colours).sort((a, b) => b[1] - a[1]).map(([c]) => c).slice(0, 3),
    })),
    text_colours: Object.entries(colours).sort((a, b) => b[1] - a[1]).map(([c, n]) => ({ colour: c, runs: n })),
    biggest: runs.filter((r) => r.size === sizes[0]).slice(0, 3).map((r) => ({ sel: sel(r.el), text: r.text.slice(0, 40), size: r.size })),
    examples: sizes.slice(0, 12).map((s) => {
      const r = runs.find((x) => x.size === s);
      return { size: s, sel: sel(r.el), text: r.text.slice(0, 40) };
    }),
  };

  // Figures: money, percent, numbers that carry a separator or two decimals, and plain counts of 100 or
  // more (a year is not a count). Small bare numbers are left alone: they are ranks, dates and "2 of 3".
  const FIG = /(?:(?:[-−]?\$\s?)(\d[\d,]*(?:\.\d+)?)\s?([kKmM])?(?![\w.])|(\d[\d,]*(?:\.\d+)?)\s?%|(?<![\w.$])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d{2})(?![\w.%])|(?<![\w.$,])(\d{3,})(?![\w.,%]))/g;
  const DATEISH = /\b(\d{1,2}\/\d{1,2}(\/\d{2,4})?|\d{1,2}:\d{2}|\d{4}-\d{2}-\d{2})\b/;
  const figures = [];
  for (const r of runs) {
    if (figures.length >= (cfg.max_figures || 400)) break;
    const stripped = r.text.replace(DATEISH, ' ');
    for (const m of stripped.matchAll(FIG)) {
      const kind = m[1] !== undefined ? 'money' : m[3] !== undefined ? 'percent'
        : m[4] !== undefined ? 'number' : 'count';
      const raw = (m[1] ?? m[3] ?? m[4] ?? m[5]);
      const n = Number(String(raw).replace(/,/g, ''));
      if (kind === 'count' && (n < (cfg.min_bare_count || 100) || (n >= 1900 && n <= 2100))) continue;
      figures.push({ kind, raw, suffix: m[2] || '', token: m[0].trim(), sel: sel(r.el),
        context: r.text.slice(0, 90) });
    }
  }
  out.figures = figures;

  // ---------------------------------------------------------------- colours, fonts and sizes in use
  const used = { colours: {}, fonts: {}, sizes: {} };
  const note = (bag, key, el) => { if (!key) return; const b = bag[key] || (bag[key] = { count: 0, sel: '', text: '' });
    b.count++; if (!b.sel) { b.sel = sel(el); b.text = clean(el.innerText || '').slice(0, 40); } };
  for (const el of document.body.querySelectorAll('*')) {
    if (!visible(el)) continue;
    const cs = getComputedStyle(el);
    const ownText = [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim());
    if (ownText) {
      note(used.colours, rgb(blend(parse(cs.color) || [0, 0, 0, 1], bgOf(el))), el);
      note(used.fonts, cs.fontFamily.split(',')[0].replace(/["']/g, '').trim(), el);
      note(used.sizes, String(parseFloat(cs.fontSize)), el);
    }
    const bgc = parse(cs.backgroundColor);
    if (bgc && bgc[3] >= 0.98) note(used.colours, rgb(bgc), el);
    for (const side of ['Top', 'Right', 'Bottom', 'Left']) {
      if (parseFloat(cs[`border${side}Width`]) > 0 && cs[`border${side}Style`] !== 'none') {
        const bc = parse(cs[`border${side}Color`]);
        if (bc && bc[3] >= 0.5) note(used.colours, rgb(blend(bc, bgOf(el))), el);
      }
    }
  }
  const top = (bag) => Object.entries(bag).sort((a, b) => b[1].count - a[1].count).slice(0, 60)
    .map(([value, b]) => ({ value, count: b.count, sel: b.sel, text: b.text }));
  out.used = { colours: top(used.colours), fonts: top(used.fonts), sizes: top(used.sizes) };

  // ---------------------------------------------------------------- solid fills (competing primaries)
  const controls = [...document.querySelectorAll('a[href], button, [role=button], input[type=submit], input[type=button]')]
    .filter(visible);
  const fills = {};
  for (const el of controls) {
    const cs = getComputedStyle(el);
    const c = parse(cs.backgroundColor);
    if (!c || c[3] < 0.9) continue;
    const around = bgOf(el.parentElement || document.body);
    if (ratio(c, around) < 2) continue;                       // a tinted chip is not a solid primary
    const key = rgb(c);
    const b = fills[key] || (fills[key] = { count: 0, sel: '', label: '' });
    b.count++;
    if (!b.sel) { b.sel = sel(el); b.label = label(el); }
  }
  out.solid_fills = Object.entries(fills).sort((a, b) => b[1].count - a[1].count)
    .map(([colour, b]) => ({ colour, count: b.count, sel: b.sel, label: b.label }));

  // ---------------------------------------------------------------- labels that split onto a second line
  const wrapped = [];
  for (const el of controls) {
    const text = clean(el.innerText);
    if (!text || text.split(/\s+/).length > (cfg.label_max_words || 4)) continue;
    const cs = getComputedStyle(el);
    const lh = parseFloat(cs.lineHeight) || parseFloat(cs.fontSize) * 1.2;
    const inner = el.getBoundingClientRect().height
      - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom)
      - parseFloat(cs.borderTopWidth) - parseFloat(cs.borderBottomWidth);
    const lines = Math.max(1, Math.round(inner / lh));
    if (lines <= (cfg.label_lines || 1) || el.querySelectorAll('br').length) continue;
    // A label wraps because its control is narrow. That is only a fault when the row it sits in has the
    // room to show it on one line: a label wrapping in a column that is already full is the layout, not a
    // flaw. needed = the line pieces laid end to end; free = what the row has left beside this control.
    const range = document.createRange();
    range.selectNodeContents(el);
    const pieces = [...range.getClientRects()].filter((r) => r.width > 0);
    const needed = pieces.reduce((n, r) => n + r.width, 0) + 4 * Math.max(0, pieces.length - 1);
    const box = el.getBoundingClientRect();
    const content = box.width - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight)
      - parseFloat(cs.borderLeftWidth) - parseFloat(cs.borderRightWidth);
    const parent = el.parentElement;
    let free = 0;
    if (parent) {
      const ps = getComputedStyle(parent);
      const room = parent.clientWidth - parseFloat(ps.paddingLeft) - parseFloat(ps.paddingRight);
      const row = [...parent.children].filter((c) => {
        const r = c.getBoundingClientRect();
        return r.width > 0 && r.bottom > box.top + 1 && r.top < box.bottom - 1;
      });
      const used = row.reduce((n, c) => n + c.getBoundingClientRect().width, 0);
      const gap = (parseFloat(ps.columnGap) || 0) * Math.max(0, row.length - 1);
      free = Math.max(0, room - used - gap);
    }
    if (needed > content + 1 && needed <= content + free + 1)
      wrapped.push({ sel: sel(el), text: text.slice(0, 50), lines, height: Math.round(inner),
        line_height: Math.round(lh), width: Math.round(box.width), needed: Math.round(needed),
        free: Math.round(free) });
  }
  out.wrapped_labels = wrapped.slice(0, LIMIT);

  // ---------------------------------------------------------------- the page's own joins
  const ids = {};
  for (const el of document.querySelectorAll('[id]')) ids[el.id] = (ids[el.id] || 0) + 1;
  out.duplicate_ids = Object.entries(ids).filter(([, n]) => n > 1).slice(0, LIMIT)
    .map(([id, count]) => ({ id, count, sel: sel(document.getElementById(id)) }));
  out.dead_links = [...document.querySelectorAll('a[href^="#"]')].filter(visible)
    .map((a) => ({ href: a.getAttribute('href'), text: label(a), sel: sel(a) }))
    .filter((l) => /^#[^/#]+\/[^/#]+$/.test(l.href)).slice(0, LIMIT);
  out.counts = { runs: runs.length, controls: controls.length, screens: screens.length };
  return out;
}
