// html_dom_extract.js (design role): read a rendered page into a "scene" that
// html_to_penpot.py turns into editable Penpot layers. Runs inside the page
// (page.evaluate) after fonts and images have loaded, at scroll position 0.
//
// The scene is a tree of nodes in page pixels: boards (sections, components,
// decorated boxes), groups, rects, text (paragraphs, style runs and the
// browser's own line boxes) and paths (inline SVG, normalised to absolute
// M/L/C/Z in page coordinates). Anything it cannot carry faithfully is listed
// in `issues` so the conversion report shows it instead of hiding it.
(opts) => {
  opts = opts || {};
  const sx = window.scrollX, sy = window.scrollY;
  const doc = document.documentElement;
  const W = doc.clientWidth;
  const H = Math.max(doc.scrollHeight, document.body ? document.body.scrollHeight : 0);
  const issues = [];
  const stats = {elements: 0, boards: 0, groups: 0, rects: 0, texts: 0, paths: 0, images: 0};
  const SKIP = new Set(['script', 'style', 'noscript', 'template', 'head', 'meta', 'link', 'title', 'base']);
  const ISSUE_LIMIT = 200;
  const issue = (kind, el, detail) => {
    if (issues.length < ISSUE_LIMIT) issues.push({kind, where: where(el), detail: detail || ''});
  };
  const where = (el) => {
    if (!el || !el.tagName) return '';
    const parts = [];
    for (let x = el; x && x !== document.body && parts.length < 4; x = x.parentElement) {
      let s = x.tagName.toLowerCase();
      if (x.id) { parts.unshift(s + '#' + x.id); break; }
      if (x.dataset && x.dataset.name) { parts.unshift(s + '[data-name="' + x.dataset.name + '"]'); break; }
      if (x.classList && x.classList.length) s += '.' + [...x.classList].slice(0, 2).join('.');
      parts.unshift(s);
    }
    return parts.join(' > ');
  };
  const r2 = (v) => Math.round(v * 100) / 100;
  const r4 = (v) => Math.round(v * 10000) / 10000;
  const box = (r) => ({x: r2(r.left + sx), y: r2(r.top + sy), w: r2(r.width), h: r2(r.height)});
  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const short = (s, n) => { s = clean(s); return s.length > n ? s.slice(0, n - 1).trimEnd() + '…' : s; };

  // ---------- colours ----------
  const parseColor = (v) => {
    if (!v) return null;
    v = v.trim();
    let m = v.match(/^rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)(?:\s*[,/]\s*([\d.]+%?))?\s*\)$/);
    if (m) {
      let a = m[4] === undefined ? 1 : (m[4].endsWith('%') ? parseFloat(m[4]) / 100 : parseFloat(m[4]));
      const hex = '#' + [m[1], m[2], m[3]].map((c) => Math.max(0, Math.min(255, Math.round(parseFloat(c)))).toString(16).padStart(2, '0')).join('').toUpperCase();
      return {color: hex, opacity: r2(a)};
    }
    m = v.match(/^#([0-9a-f]{3,8})$/i);
    if (m) {
      let h = m[1];
      if (h.length <= 4) h = h.split('').map((c) => c + c).join('');
      const a = h.length === 8 ? parseInt(h.slice(6, 8), 16) / 255 : 1;
      return {color: '#' + h.slice(0, 6).toUpperCase(), opacity: r2(a)};
    }
    // color(srgb ...), oklch(...), named colours: let the browser normalise.
    const probe = document.createElement('i');
    probe.style.color = v;
    if (!probe.style.color) return null;
    document.body.appendChild(probe);
    const out = getComputedStyle(probe).color;
    probe.remove();
    return out && out !== v ? parseColor(out) : null;
  };
  const visibleColor = (c) => c && c.opacity > 0.001;

  // ---------- CSS custom properties (become shared colours) ----------
  const vars = [];
  const seenVar = new Set();
  const rootStyle = getComputedStyle(doc);
  for (const sheet of document.styleSheets) {
    let rules;
    try { rules = sheet.cssRules; } catch (e) { issue('stylesheet-unreadable', null, String(sheet.href || '')); continue; }
    const walkRules = (list) => {
      for (const rule of list) {
        if (rule.cssRules && !rule.selectorText) { walkRules(rule.cssRules); continue; }
        if (!rule.style || !rule.selectorText) continue;
        if (!/^(:root|html)$/.test(rule.selectorText.trim())) continue;
        for (let i = 0; i < rule.style.length; i++) {
          const name = rule.style[i];
          if (!name.startsWith('--') || seenVar.has(name)) continue;
          seenVar.add(name);
          const value = rootStyle.getPropertyValue(name).trim();
          const c = /gradient|url\(/.test(value) ? null : parseColor(value);
          if (c) vars.push({name, value, color: c.color, opacity: c.opacity});
        }
      }
    };
    walkRules(rules);
  }

  // ---------- fonts (only faces that actually loaded) ----------
  const faceRules = [];
  for (const sheet of document.styleSheets) {
    let rules;
    try { rules = sheet.cssRules; } catch (e) { continue; }
    for (const rule of rules) {
      if (rule.constructor && rule.constructor.name === 'CSSFontFaceRule') {
        const fam = clean(rule.style.getPropertyValue('font-family')).replace(/^["']|["']$/g, '');
        const src = rule.style.getPropertyValue('src');
        const url = (src.match(/url\(\s*["']?([^"')]+)["']?\s*\)/) || [])[1];
        const base = sheet.href || location.href;
        faceRules.push({family: fam, weight: clean(rule.style.getPropertyValue('font-weight')) || '400',
          style: clean(rule.style.getPropertyValue('font-style')) || 'normal', url: url ? new URL(url, base).href : null});
      }
    }
  }
  const loadedFamilies = new Set();
  const fonts = [];
  for (const f of document.fonts) {
    if (f.status !== 'loaded') continue;
    const fam = f.family.replace(/^["']|["']$/g, '');
    loadedFamilies.add(fam.toLowerCase());
    const rule = faceRules.find((r) => r.family.toLowerCase() === fam.toLowerCase() && String(r.weight) === String(f.weight) && r.style === f.style);
    fonts.push({family: fam, weight: String(f.weight), style: f.style, url: rule ? rule.url : null});
  }
  const usedFonts = new Map();
  const familyOf = (cs, el) => {
    const list = cs.fontFamily.split(',').map((s) => s.trim().replace(/^["']|["']$/g, ''));
    for (const fam of list) {
      if (loadedFamilies.has(fam.toLowerCase())) return fam;
    }
    issue('font-not-loaded', el, cs.fontFamily);
    return list[0];
  };

  // ---------- gradients / backgrounds ----------
  const splitTop = (s) => {
    const out = []; let depth = 0, cur = '';
    for (const ch of s) {
      if (ch === '(') depth++;
      if (ch === ')') depth--;
      if (ch === ',' && depth === 0) { out.push(cur.trim()); cur = ''; } else cur += ch;
    }
    if (cur.trim()) out.push(cur.trim());
    return out;
  };
  const len = (v, ref) => {
    v = v.trim();
    if (v.endsWith('%')) return parseFloat(v) / 100 * ref;
    if (v.endsWith('px')) return parseFloat(v);
    if (v === '0') return 0;
    return NaN;
  };
  const stopsOf = (parts, lineLength) => {
    const stops = [];
    for (const p of parts) {
      const m = p.match(/^(rgba?\([^)]*\)|#[0-9a-fA-F]+|[a-z]+(?:\([^)]*\))?)\s*(.*)$/);
      if (!m) return null;
      const c = parseColor(m[1]);
      if (!c) return null;
      const positions = m[2] ? m[2].split(/\s+/).filter(Boolean) : [];
      if (!positions.length) stops.push({color: c.color, opacity: c.opacity, offset: null});
      for (const pos of positions) {
        const px = len(pos, lineLength);
        stops.push({color: c.color, opacity: c.opacity, offset: Number.isFinite(px) && lineLength ? px / lineLength : null});
      }
    }
    if (!stops.length) return null;
    if (stops[0].offset === null) stops[0].offset = 0;
    if (stops[stops.length - 1].offset === null) stops[stops.length - 1].offset = 1;
    for (let i = 1; i < stops.length - 1; i++) {
      if (stops[i].offset !== null) continue;
      let j = i; while (stops[j].offset === null) j++;
      const a = stops[i - 1].offset, b = stops[j].offset;
      for (let k = i; k < j; k++) stops[k].offset = a + (b - a) * (k - i + 1) / (j - i + 1);
    }
    let last = 0;
    for (const s of stops) { s.offset = r2(Math.max(last, Math.min(1, s.offset))); last = s.offset; }
    return stops;
  };
  const linear = (args, w, h) => {
    let parts = splitTop(args);
    let angle = 180;
    const first = parts[0];
    const dirs = {'to top': 0, 'to right': 90, 'to bottom': 180, 'to left': 270,
      'to top right': null, 'to right top': null, 'to bottom right': null, 'to right bottom': null,
      'to bottom left': null, 'to left bottom': null, 'to top left': null, 'to left top': null};
    if (/^-?[\d.]+(deg|turn|rad|grad)$/.test(first)) {
      const n = parseFloat(first);
      angle = first.endsWith('turn') ? n * 360 : first.endsWith('rad') ? n * 180 / Math.PI : first.endsWith('grad') ? n * 0.9 : n;
      parts = parts.slice(1);
    } else if (first in dirs) {
      if (dirs[first] !== null) angle = dirs[first];
      else {
        const v = first.includes('top') ? -1 : 1, hz = first.includes('left') ? -1 : 1;
        // Corner directions: the gradient line is perpendicular to the diagonal
        // through the other two corners, so its direction is (hz*h, v*w).
        angle = (Math.atan2(hz * h, -v * w) * 180 / Math.PI + 360) % 360;
      }
      parts = parts.slice(1);
    }
    const t = angle * Math.PI / 180;
    const L = Math.abs(w * Math.sin(t)) + Math.abs(h * Math.cos(t));
    const dx = Math.sin(t), dy = -Math.cos(t);
    const stops = stopsOf(parts, L);
    if (!stops || !L) return null;
    // Penpot draws gradients in the shape's unit box (SVG objectBoundingBox), where colour
    // lines stay perpendicular to the vector in unit space. CSS keeps them perpendicular in
    // pixels. Position t = A(u - .5) + B(v - .5) + .5 is linear in unit space, so the unit
    // vector (A, B) / (A^2 + B^2) through the centre reproduces CSS exactly, corners included.
    const A = w * dx / L, B = h * dy / L, n = A * A + B * B;
    const vx = A / n, vy = B / n;
    return {type: 'linear', start: [r4(0.5 - vx / 2), r4(0.5 - vy / 2)],
      end: [r4(0.5 + vx / 2), r4(0.5 + vy / 2)], width: 1, stops};
  };
  const radial = (args, w, h) => {
    let parts = splitTop(args);
    let cx = 0.5, cy = 0.5, shape = 'ellipse';
    const head = parts[0];
    if (!/^(rgba?\(|#)/.test(head)) {
      parts = parts.slice(1);
      if (/circle/.test(head)) shape = 'circle';
      const at = head.split(' at ')[1];
      if (at) {
        const kw = {left: 0, center: 0.5, right: 1, top: 0, bottom: 1};
        const [ax, ay] = at.trim().split(/\s+/);
        const conv = (v, ref) => v in kw ? kw[v] : (Number.isFinite(len(v, ref)) ? len(v, ref) / ref : 0.5);
        cx = conv(ax || 'center', w); cy = conv(ay || ax || 'center', h);
        if ((ax === 'top' || ax === 'bottom') && !ay) { cy = kw[ax]; cx = 0.5; }
      }
    }
    // farthest-corner radius, in pixels
    const px = cx * w, py = cy * h;
    const fx = Math.max(px, w - px), fy = Math.max(py, h - py);
    let rx = fx * Math.SQRT2, ry = fy * Math.SQRT2;
    if (shape === 'circle') { rx = ry = Math.hypot(fx, fy); }
    const stops = stopsOf(parts, ry);
    if (!stops) return null;
    return {type: 'radial', start: [r2(cx), r2(cy)], end: [r2(cx), r2(cy + ry / h)], width: r2((rx / w) / (ry / h)), stops};
  };
  const backgroundFills = (cs, el, rect) => {
    const fills = [];
    const bg = parseColor(cs.backgroundColor);
    if (visibleColor(bg)) fills.push({type: 'color', color: bg.color, opacity: bg.opacity});
    if (cs.backgroundImage && cs.backgroundImage !== 'none') {
      const layers = splitTop(cs.backgroundImage);
      // Size, repeat and position are per-layer lists that repeat when shorter (CSS Backgrounds 3).
      const sizes = splitTop(cs.backgroundSize), repeats = splitTop(cs.backgroundRepeat);
      const positions = splitTop(cs.backgroundPosition);
      const pick = (list, i) => (list.length ? list[i % list.length] : '').trim();
      // CSS lists the top layer first; fills are listed bottom to top here.
      for (let i = layers.length - 1; i >= 0; i--) {
        const layer = layers[i];
        let m;
        if ((m = layer.match(/^(repeating-)?linear-gradient\((.*)\)$/s))) {
          const g = linear(m[2], rect.width, rect.height);
          if (g && !m[1]) fills.push(g); else issue('gradient-approximated', el, layer.slice(0, 80));
        } else if ((m = layer.match(/^(repeating-)?radial-gradient\((.*)\)$/s))) {
          const g = radial(m[2], rect.width, rect.height);
          if (g && !m[1]) fills.push(g); else issue('gradient-approximated', el, layer.slice(0, 80));
        } else if ((m = layer.match(/^url\(\s*["']?([^"')]+)["']?\s*\)$/))) {
          const size = pick(sizes, i), repeat = pick(repeats, i), position = pick(positions, i);
          fills.push({type: 'image', src: new URL(m[1], location.href).href, fit: size === 'contain' ? 'contain' : (size === 'cover' ? 'cover' : 'fill')});
          if (!/^(cover|contain)$/.test(size) && repeat !== 'no-repeat') issue('background-repeat-approximated', el, size + ' ' + repeat);
          if (/^(cover|contain)$/.test(size) && !/^(50% 50%|center( center)?)$/.test(position)) issue('background-position-approximated', el, position);
        } else {
          issue('background-unsupported', el, layer.slice(0, 80));
        }
      }
    }
    return fills;
  };
  const radiiOf = (cs, rect) => {
    const v = ['borderTopLeftRadius', 'borderTopRightRadius', 'borderBottomRightRadius', 'borderBottomLeftRadius']
      .map((k) => { const p = cs[k].split(' ')[0]; return p.endsWith('%') ? parseFloat(p) / 100 * Math.min(rect.width, rect.height) : parseFloat(p) || 0; });
    const cap = Math.min(rect.width, rect.height) / 2;
    return v.map((x) => r2(Math.min(x, cap)));
  };
  const shadowsOf = (cs, el) => {
    if (!cs.boxShadow || cs.boxShadow === 'none') return [];
    const out = [];
    for (const part of splitTop(cs.boxShadow)) {
      const cm = part.match(/(rgba?\([^)]*\)|#[0-9a-fA-F]+)/);
      const c = cm ? parseColor(cm[1]) : {color: '#000000', opacity: 1};
      const rest = part.replace(cm ? cm[1] : '', '').trim();
      const inset = /\binset\b/.test(rest);
      const nums = rest.replace('inset', '').trim().split(/\s+/).map(parseFloat).filter((n) => Number.isFinite(n));
      if (nums.length < 2 || !c) { issue('shadow-unsupported', el, part); continue; }
      out.push({style: inset ? 'inner-shadow' : 'drop-shadow', x: nums[0], y: nums[1], blur: nums[2] || 0,
        spread: nums[3] || 0, color: c.color, opacity: c.opacity});
    }
    // CSS paints the first shadow on top.
    return out.reverse();
  };
  const bordersOf = (cs) => {
    const sides = ['Top', 'Right', 'Bottom', 'Left'].map((s) => ({
      side: s.toLowerCase(), width: parseFloat(cs['border' + s + 'Width']) || 0,
      style: cs['border' + s + 'Style'], color: parseColor(cs['border' + s + 'Color'])}));
    return sides.filter((s) => s.width > 0 && s.style !== 'none' && s.style !== 'hidden' && visibleColor(s.color));
  };
  const decoration = (el, cs, rect) => {
    const fills = backgroundFills(cs, el, rect);
    const borders = bordersOf(cs);
    const shadows = shadowsOf(cs, el);
    const radius = radiiOf(cs, rect);
    let strokes = [], sideRects = [];
    if (borders.length === 4 && borders.every((b) => b.width === borders[0].width && b.color.color === borders[0].color.color && b.style === borders[0].style && b.color.opacity === borders[0].color.opacity)) {
      const b = borders[0];
      strokes = [{color: b.color.color, opacity: b.color.opacity, width: b.width, align: 'inner',
        style: b.style === 'dashed' ? 'dashed' : b.style === 'dotted' ? 'dotted' : 'solid'}];
    } else if (borders.length) {
      sideRects = borders.map((b) => ({side: b.side, width: b.width, color: b.color.color, opacity: b.color.opacity}));
      if (radius.some((x) => x > 0)) issue('border-sides-approximated', el, 'unequal borders on a rounded box');
    }
    const visible = fills.length > 0 || strokes.length > 0 || sideRects.length > 0 || shadows.length > 0;
    return {fills, strokes, sideRects, shadows, radius, visible};
  };

  // ---------- naming ----------
  const headingIn = (el) => {
    const hd = el.querySelector('h1, h2, h3');
    return hd ? short(hd.textContent, 36) : '';
  };
  const titleCase = (s) => s.charAt(0).toUpperCase() + s.slice(1);
  const nameOf = (el, kind) => {
    const d = el.dataset && (el.dataset.component || el.dataset.name);
    if (d) return short(d, 60);
    const label = el.getAttribute('aria-label');
    if (label) return short(label, 60);
    const tag = el.tagName.toLowerCase();
    if (kind === 'section') {
      const h = headingIn(el);
      const base = {header: 'Header', footer: 'Footer', nav: 'Navigation', main: 'Main'}[tag] || 'Section';
      if (el.id) return base + ' / ' + el.id;
      return h ? base + ' / ' + h : base;
    }
    if (el.id) return titleCase(tag) + ' / ' + el.id;
    const cls = el.classList && el.classList.length ? el.classList[0] : '';
    return titleCase(tag) + (cls ? ' / ' + cls : '');
  };

  // ---------- SVG -> absolute paths ----------
  const pathSegments = (d) => {
    const toks = d.match(/[MmLlHhVvCcSsQqTtAaZz]|[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?/g) || [];
    const out = [];
    let i = 0, cmd = null, cx = 0, cy = 0, sx0 = 0, sy0 = 0, lc = null, lq = null;
    const num = () => parseFloat(toks[i++]);
    const isCmd = (t) => /^[A-Za-z]$/.test(t);
    while (i < toks.length) {
      if (isCmd(toks[i])) cmd = toks[i++];
      else if (cmd === null) break;
      const rel = cmd === cmd.toLowerCase();
      const C = cmd.toUpperCase();
      if (C === 'Z') { out.push(['Z']); cx = sx0; cy = sy0; lc = lq = null; if (i < toks.length && !isCmd(toks[i])) cmd = 'L'; continue; }
      if (C === 'M') {
        let x = num(), y = num(); if (rel) { x += cx; y += cy; }
        out.push(['M', x, y]); cx = sx0 = x; cy = sy0 = y; lc = lq = null;
        cmd = rel ? 'l' : 'L';
        continue;
      }
      if (C === 'L') { let x = num(), y = num(); if (rel) { x += cx; y += cy; } out.push(['L', x, y]); cx = x; cy = y; lc = lq = null; continue; }
      if (C === 'H') { let x = num(); if (rel) x += cx; out.push(['L', x, cy]); cx = x; lc = lq = null; continue; }
      if (C === 'V') { let y = num(); if (rel) y += cy; out.push(['L', cx, y]); cy = y; lc = lq = null; continue; }
      if (C === 'C') {
        let a = [num(), num(), num(), num(), num(), num()];
        if (rel) a = a.map((v, k) => v + (k % 2 ? cy : cx));
        out.push(['C', ...a]); lc = [a[2], a[3]]; lq = null; cx = a[4]; cy = a[5]; continue;
      }
      if (C === 'S') {
        let a = [num(), num(), num(), num()];
        if (rel) a = a.map((v, k) => v + (k % 2 ? cy : cx));
        const c1 = lc ? [2 * cx - lc[0], 2 * cy - lc[1]] : [cx, cy];
        out.push(['C', c1[0], c1[1], a[0], a[1], a[2], a[3]]); lc = [a[0], a[1]]; lq = null; cx = a[2]; cy = a[3]; continue;
      }
      if (C === 'Q' || C === 'T') {
        let q, x, y;
        if (C === 'Q') { q = [num(), num()]; x = num(); y = num(); if (rel) { q = [q[0] + cx, q[1] + cy]; x += cx; y += cy; } }
        else { x = num(); y = num(); if (rel) { x += cx; y += cy; } q = lq ? [2 * cx - lq[0], 2 * cy - lq[1]] : [cx, cy]; }
        out.push(['C', cx + 2 / 3 * (q[0] - cx), cy + 2 / 3 * (q[1] - cy), x + 2 / 3 * (q[0] - x), y + 2 / 3 * (q[1] - y), x, y]);
        lq = q; lc = null; cx = x; cy = y; continue;
      }
      if (C === 'A') {
        let rx = Math.abs(num()), ry = Math.abs(num()); const phi = num() * Math.PI / 180; const fa = num(), fs = num();
        let x = num(), y = num(); if (rel) { x += cx; y += cy; }
        out.push(...arcToCubics(cx, cy, rx, ry, phi, fa, fs, x, y)); cx = x; cy = y; lc = lq = null; continue;
      }
      i++; // unknown token
    }
    return out;
  };
  const arcToCubics = (x1, y1, rx, ry, phi, fa, fs, x2, y2) => {
    if (rx === 0 || ry === 0 || (x1 === x2 && y1 === y2)) return [['L', x2, y2]];
    const cos = Math.cos(phi), sin = Math.sin(phi);
    const dx = (x1 - x2) / 2, dy = (y1 - y2) / 2;
    const x1p = cos * dx + sin * dy, y1p = -sin * dx + cos * dy;
    let lam = (x1p * x1p) / (rx * rx) + (y1p * y1p) / (ry * ry);
    if (lam > 1) { rx *= Math.sqrt(lam); ry *= Math.sqrt(lam); }
    const sign = fa === fs ? -1 : 1;
    const num = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p;
    const co = sign * Math.sqrt(Math.max(0, num / (rx * rx * y1p * y1p + ry * ry * x1p * x1p)));
    const cxp = co * rx * y1p / ry, cyp = -co * ry * x1p / rx;
    const ccx = cos * cxp - sin * cyp + (x1 + x2) / 2, ccy = sin * cxp + cos * cyp + (y1 + y2) / 2;
    const ang = (ux, uy, vx, vy) => { const a = Math.atan2(ux * vy - uy * vx, ux * vx + uy * vy); return a; };
    let t1 = ang(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry);
    let dt = ang((x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry);
    if (!fs && dt > 0) dt -= 2 * Math.PI;
    if (fs && dt < 0) dt += 2 * Math.PI;
    const n = Math.ceil(Math.abs(dt) / (Math.PI / 2));
    const out = [];
    const d = dt / n;
    const k = 4 / 3 * Math.tan(d / 4);
    for (let s = 0; s < n; s++) {
      const a1 = t1 + s * d, a2 = a1 + d;
      const p = (a) => [Math.cos(a), Math.sin(a)];
      const [c1, s1] = p(a1), [c2, s2] = p(a2);
      const e1 = [c1 - k * s1, s1 + k * c1], e2 = [c2 + k * s2, s2 - k * c2];
      const map = (u, v) => [ccx + rx * u * cos - ry * v * sin, ccy + rx * u * sin + ry * v * cos];
      const q1 = map(e1[0], e1[1]), q2 = map(e2[0], e2[1]), q3 = map(c2, s2);
      out.push(['C', q1[0], q1[1], q2[0], q2[1], q3[0], q3[1]]);
    }
    return out;
  };
  const shapeD = (el) => {
    const tag = el.tagName.toLowerCase();
    const n = (a) => parseFloat(el.getAttribute(a)) || 0;
    if (tag === 'path') return el.getAttribute('d') || '';
    if (tag === 'rect') {
      const x = n('x'), y = n('y'), w = n('width'), h = n('height');
      let rx = el.hasAttribute('rx') ? n('rx') : (el.hasAttribute('ry') ? n('ry') : 0);
      let ry = el.hasAttribute('ry') ? n('ry') : rx;
      rx = Math.min(rx, w / 2); ry = Math.min(ry, h / 2);
      if (!rx && !ry) return `M${x} ${y}H${x + w}V${y + h}H${x}Z`;
      return `M${x + rx} ${y}H${x + w - rx}A${rx} ${ry} 0 0 1 ${x + w} ${y + ry}V${y + h - ry}A${rx} ${ry} 0 0 1 ${x + w - rx} ${y + h}H${x + rx}A${rx} ${ry} 0 0 1 ${x} ${y + h - ry}V${y + ry}A${rx} ${ry} 0 0 1 ${x + rx} ${y}Z`;
    }
    if (tag === 'circle' || tag === 'ellipse') {
      const cx = n('cx'), cy = n('cy');
      const rx = tag === 'circle' ? n('r') : n('rx'), ry = tag === 'circle' ? n('r') : n('ry');
      return `M${cx - rx} ${cy}A${rx} ${ry} 0 1 0 ${cx + rx} ${cy}A${rx} ${ry} 0 1 0 ${cx - rx} ${cy}Z`;
    }
    if (tag === 'line') return `M${n('x1')} ${n('y1')}L${n('x2')} ${n('y2')}`;
    if (tag === 'polyline' || tag === 'polygon') {
      const pts = (el.getAttribute('points') || '').trim().split(/[\s,]+/).map(parseFloat);
      let d = '';
      for (let i = 0; i + 1 < pts.length; i += 2) d += (i ? 'L' : 'M') + pts[i] + ' ' + pts[i + 1];
      return tag === 'polygon' ? d + 'Z' : d;
    }
    return '';
  };
  const fmt = (v) => { const s = (Math.round(v * 1000) / 1000).toString(); return s === '-0' ? '0' : s; };
  const svgPaint = (paint, opacity, el, svg) => {
    if (!paint || paint === 'none') return null;
    const m = paint.match(/url\(["']?#([^"')]+)["']?\)/);
    if (m) {
      const g = svg.ownerDocument.getElementById(m[1]);
      if (g && /linearGradient|radialGradient/.test(g.tagName)) {
        const stops = [...g.querySelectorAll('stop')].map((s) => {
          const cs = getComputedStyle(s);
          const c = parseColor(cs.stopColor);
          const off = s.getAttribute('offset') || '0';
          return c && {color: c.color, opacity: r2(c.opacity * (parseFloat(cs.stopOpacity) || 1)),
            offset: r2(Math.max(0, Math.min(1, off.endsWith('%') ? parseFloat(off) / 100 : parseFloat(off))))};
        }).filter(Boolean);
        if (!stops.length) return null;
        if (g.tagName === 'linearGradient' && (g.getAttribute('gradientUnits') || 'objectBoundingBox') === 'objectBoundingBox' && !g.getAttribute('gradientTransform')) {
          const a = (k, dflt) => { const v = g.getAttribute(k); return v === null ? dflt : (v.endsWith('%') ? parseFloat(v) / 100 : parseFloat(v)); };
          return {type: 'linear', start: [a('x1', 0), a('y1', 0)], end: [a('x2', 1), a('y2', 0)], width: 1, stops, opacity};
        }
        issue('svg-gradient-approximated', el, g.tagName);
        return {type: 'color', color: stops[0].color, opacity: r2(stops[0].opacity * opacity)};
      }
      issue('svg-paint-unsupported', el, paint);
      return null;
    }
    const c = parseColor(paint);
    return c && visibleColor(c) ? {type: 'color', color: c.color, opacity: r2(c.opacity * opacity)} : null;
  };
  const emitSvg = (svg, out) => {
    const rect = svg.getBoundingClientRect();
    if (rect.width < 0.5 || rect.height < 0.5) return;
    const label = svg.getAttribute('aria-label') || (svg.querySelector('title') && svg.querySelector('title').textContent) || svg.dataset.name || '';
    const group = {kind: 'group', name: 'SVG' + (label ? ' / ' + short(label, 40) : ''), box: box(rect), children: []};
    for (const bad of svg.querySelectorAll('text, use, image, foreignObject')) {
      if (!bad.closest('defs, symbol, clipPath, mask, pattern, marker')) issue('svg-element-unsupported', bad, bad.tagName);
    }
    if (svg.querySelector('[clip-path], [mask], [filter]')) issue('svg-effect-ignored', svg, 'clip-path/mask/filter');
    const els = svg.querySelectorAll('path, rect, circle, ellipse, line, polyline, polygon');
    let idx = 0;
    for (const el of els) {
      if (el.closest('defs, symbol, clipPath, mask, pattern, marker')) continue;
      const cs = getComputedStyle(el);
      if (cs.display === 'none' || cs.visibility === 'hidden') continue;
      const d = shapeD(el);
      if (!d) continue;
      const m = el.getScreenCTM();
      if (!m) continue;
      const segs = pathSegments(d);
      if (!segs.length) continue;
      const tx = (x, y) => [m.a * x + m.c * y + m.e + sx, m.b * x + m.d * y + m.f + sy];
      let str = '';
      for (const s of segs) {
        if (s[0] === 'Z') { str += 'Z'; continue; }
        const pts = [];
        for (let k = 1; k < s.length; k += 2) pts.push(...tx(s[k], s[k + 1]));
        str += s[0] + pts.map(fmt).join(' ');
      }
      const op = parseFloat(cs.opacity);
      const fill = svgPaint(cs.fill, parseFloat(cs.fillOpacity), el, svg);
      const strokeP = svgPaint(cs.stroke, parseFloat(cs.strokeOpacity), el, svg);
      const scale = Math.sqrt(Math.abs(m.a * m.d - m.b * m.c));
      const sw = parseFloat(cs.strokeWidth) * scale;
      const strokes = strokeP && sw > 0 && strokeP.type === 'color' ? [{color: strokeP.color, opacity: strokeP.opacity, width: r2(sw), align: 'center',
        style: cs.strokeDasharray && cs.strokeDasharray !== 'none' ? 'dashed' : 'solid', cap: cs.strokeLinecap, join: cs.strokeLinejoin}] : [];
      if (strokeP && strokeP.type !== 'color') issue('svg-stroke-gradient-approximated', el, '');
      const b = el.getBoundingClientRect();
      const fills = fill ? [fill] : [];
      if (!fills.length && !strokes.length) continue;
      idx += 1;
      group.children.push({kind: 'path', name: (el.dataset && el.dataset.name) || (el.getAttribute('id') || el.tagName.toLowerCase()) + ' ' + idx,
        d: str, box: box(b), fills, strokes, opacity: Number.isFinite(op) ? op : 1, fillRule: cs.fillRule});
      stats.paths += 1;
    }
    if (group.children.length) { out.push(group); stats.groups += 1; }
  };

  // ---------- text runs ----------
  const INLINE = new Set(['inline', 'contents']);
  const isInlineLevel = (node) => {
    if (node.nodeType === Node.TEXT_NODE) return true;
    if (node.nodeType !== Node.ELEMENT_NODE) return false;
    const tag = node.tagName.toLowerCase();
    if (tag === 'br') return true;
    if (tag === 'img' || tag === 'svg' || tag === 'input' || tag === 'textarea' || tag === 'select' || tag === 'video' || tag === 'canvas' || tag === 'iframe') return false;
    const cs = getComputedStyle(node);
    if (!INLINE.has(cs.display) || cs.position === 'absolute' || cs.position === 'fixed' || cs.cssFloat !== 'none') return false;
    // An inline element that holds block-level content is walked like a block.
    for (const c of node.children) if (!isInlineLevel(c)) return false;
    return true;
  };
  const styleOf = (el) => {
    const cs = getComputedStyle(el);
    const fam = familyOf(cs, el);
    const size = parseFloat(cs.fontSize);
    const color = parseColor(cs.color) || {color: '#000000', opacity: 1};
    const weight = String(cs.fontWeight);
    usedFonts.set(fam.toLowerCase() + '|' + weight + '|' + cs.fontStyle, {family: fam, weight, style: cs.fontStyle});
    if (cs.webkitBackgroundClip === 'text' || cs.backgroundClip === 'text') issue('text-background-clip-approximated', el, 'gradient text drawn as its solid colour');
    if (cs.webkitTextStroke && parseFloat(cs.webkitTextStrokeWidth) > 0) issue('text-stroke-ignored', el, cs.webkitTextStroke);
    if (cs.textShadow && cs.textShadow !== 'none') issue('text-shadow-ignored', el, cs.textShadow.slice(0, 60));
    return {family: fam, weight, style: cs.fontStyle, size, lineHeight: cs.lineHeight === 'normal' ? null : parseFloat(cs.lineHeight),
      letterSpacing: cs.letterSpacing === 'normal' ? 0 : parseFloat(cs.letterSpacing) || 0, transform: cs.textTransform,
      decoration: (cs.textDecorationLine || 'none').includes('underline') ? 'underline' : ((cs.textDecorationLine || '').includes('line-through') ? 'line-through' : 'none'),
      color: color.color, opacity: color.opacity, role: (el.closest('[data-typography]') || {dataset: {}}).dataset.typography || null,
      tag: el.tagName.toLowerCase()};
  };
  const sameStyle = (a, b) => JSON.stringify(a) === JSON.stringify(b);
  const range = document.createRange();

  // Turn one run of inline content into a text node, in DOM order, keeping the browser's line boxes.
  const emitRun = (nodes, block, out) => {
    const paragraphs = [[]];
    const lines = [];           // line boxes: {top, bottom, frags: [...]}
    const decor = [];
    let cur = null;             // current line
    let prevRight = -Infinity, prevTop = -Infinity;
    let lastWasSpace = true;
    let anyText = false;
    let plain = '';
    const pushChar = (ch, leafRef, rc) => {
      const top = rc.top + sy, bottom = rc.bottom + sy, left = rc.left + sx, right = rc.right + sx;
      const cyy = (top + bottom) / 2;
      const wrapped = cur && (cyy > cur.bottom || (left < prevRight - 1 && top > prevTop + (bottom - top) * 0.3));
      if (!cur || wrapped) {
        cur = {top, bottom, frags: []};
        lines.push(cur);
      }
      cur.top = Math.min(cur.top, top); cur.bottom = Math.max(cur.bottom, bottom);
      let f = cur.frags[cur.frags.length - 1];
      if (!f || f.leaf !== leafRef) {
        f = {leaf: leafRef, left, right, top, bottom, text: ''};
        cur.frags.push(f);
      }
      f.left = Math.min(f.left, left); f.right = Math.max(f.right, right);
      f.top = Math.min(f.top, top); f.bottom = Math.max(f.bottom, bottom);
      f.text += ch;
      prevRight = right; prevTop = top;
    };
    const visit = (node) => {
      if (node.nodeType === Node.TEXT_NODE) {
        const parent = node.parentElement;
        plain += node.data;
        const st = styleOf(parent);
        const para = paragraphs[paragraphs.length - 1];
        let leaf = para[para.length - 1];
        if (!leaf || !sameStyle(leaf.style, st)) { leaf = {text: '', style: st}; para.push(leaf); }
        const ws = getComputedStyle(parent).whiteSpace;
        const pre = /^(pre|pre-wrap|break-spaces|pre-line)$/.test(ws);
        const data = node.data;
        for (let i = 0; i < data.length; i++) {
          const ch = data[i];
          range.setStart(node, i); range.setEnd(node, i + 1);
          const rects = range.getClientRects();
          const rc = rects.length ? rects[rects.length - 1] : null;
          const isWs = /\s/.test(ch);
          if (isWs && !pre) {
            // Collapsed white space still separates words in the live text (soft wraps
            // included); only a space with a visible box joins a line fragment.
            if (lastWasSpace || !anyText) continue;
            if (!leaf) { const p2 = paragraphs[paragraphs.length - 1]; leaf = {text: '', style: st}; p2.push(leaf); }
            leaf.text += ' ';
            lastWasSpace = true;
            if (rc && rc.width > 0.01) pushChar(' ', leaf, rc);
            continue;
          }
          if (isWs && ch === '\n') { paragraphs.push([]); leaf = null; lastWasSpace = true; continue; }
          if (!rc) continue;
          if (!leaf) { const p2 = paragraphs[paragraphs.length - 1]; leaf = {text: '', style: st}; p2.push(leaf); }
          leaf.text += ch;
          lastWasSpace = ch === ' ';
          if (!isWs) anyText = true;
          pushChar(ch, leaf, rc);
        }
        return;
      }
      if (node.nodeType !== Node.ELEMENT_NODE) return;
      const tag = node.tagName.toLowerCase();
      if (tag === 'br') { paragraphs.push([]); lastWasSpace = true; plain += ' '; return; }
      const cs = getComputedStyle(node);
      if (cs.display === 'none' || cs.visibility === 'hidden') return;
      const dec = decoration(node, cs, node.getBoundingClientRect());
      if (dec.visible) {
        for (const rc of node.getClientRects()) {
          decor.push({kind: 'rect', name: nameOf(node) + ' (inline box)', box: box(rc), fills: dec.fills, strokes: dec.strokes,
            radius: dec.radius, shadows: dec.shadows, opacity: 1});
        }
      }
      for (const c of node.childNodes) visit(c);
    };
    for (const n of nodes) visit(n);
    if (!anyText) return;
    // Trim trailing spaces of each paragraph's last leaf; drop empty leaves/paragraphs at the ends.
    for (const para of paragraphs) {
      while (para.length && !para[para.length - 1].text.trim()) para.pop();
      if (para.length) para[para.length - 1].text = para[para.length - 1].text.replace(/\s+$/, '');
      if (para.length) para[0].text = para[0].text.replace(/^\s+/, '');
    }
    while (paragraphs.length && !paragraphs[paragraphs.length - 1].length) paragraphs.pop();
    while (paragraphs.length && !paragraphs[0].length) paragraphs.shift();
    if (!paragraphs.length || !lines.length) return;
    const bcs = getComputedStyle(block);
    const br = block.getBoundingClientRect();
    const pl = parseFloat(bcs.paddingLeft) + parseFloat(bcs.borderLeftWidth);
    const pr = parseFloat(bcs.paddingRight) + parseFloat(bcs.borderRightWidth);
    const contentLeft = br.left + sx + pl, contentRight = br.right + sx - pr;
    const first = paragraphs[0][0].style;
    const firstSize = first.size;
    const lh = first.lineHeight;
    const lineTops = lines.map((l) => l.top);
    let pitch = null;
    if (lines.length > 1) pitch = (lineTops[lineTops.length - 1] - lineTops[0]) / (lines.length - 1);
    const lineBox = lh || pitch || (lines[0].bottom - lines[0].top);
    const half = Math.max(0, (lineBox - (lines[0].bottom - lines[0].top)) / 2);
    const minLeft = Math.min(...lines.flatMap((l) => l.frags.map((f) => f.left)));
    const maxRight = Math.max(...lines.flatMap((l) => l.frags.map((f) => f.right)));
    const x = Math.min(contentLeft, minLeft);
    const right = Math.max(contentRight, maxRight);
    const top = lines[0].top - half;
    const lastHalf = Math.max(0, (lineBox - (lines[lines.length - 1].bottom - lines[lines.length - 1].top)) / 2);
    const bottom = lines[lines.length - 1].bottom + lastHalf;
    let align = bcs.textAlign;
    align = align === 'start' || align === '-webkit-left' ? 'left' : align === 'end' || align === '-webkit-right' ? 'right' : align === '-webkit-center' ? 'center' : align;
    if (!['left', 'center', 'right', 'justify'].includes(align)) align = 'left';
    const leafIndex = new Map();
    paragraphs.forEach((para, pi) => para.forEach((leaf, li) => leafIndex.set(leaf, [pi, li])));
    const frags = [];
    for (const line of lines) {
      for (const f of line.frags) {
        const idx = leafIndex.get(f.leaf);
        if (!idx) continue;
        const text = f.text;
        if (!text.trim()) continue;
        frags.push({p: idx[0], l: idx[1], x: r2(f.left), y: r2(f.bottom), w: r2(f.right - f.left), h: r2(f.bottom - f.top), text});
      }
    }
    for (const d of decor) out.push(d);
    const label = short(paragraphs.map((p) => p.map((l) => l.text).join('')).join(' '), 40);
    const tag = block.tagName.toLowerCase();
    const role = /^h[1-6]$/.test(tag) ? tag.toUpperCase() : (tag === 'a' || tag === 'button' ? titleCase(tag) : 'Text');
    out.push({kind: 'text', name: (block.dataset && block.dataset.name && block.childElementCount === 0 ? block.dataset.name : role + ' — ' + label),
      box: {x: r2(x), y: r2(top), w: r2(right - x), h: r2(bottom - top)},
      text: {align, lineHeight: r2(lineBox), paragraphs: paragraphs.map((para) => para.map((leaf) => ({text: leaf.text, style: leaf.style}))), lines: frags,
        plain: clean(plain)}});
    stats.texts += 1;
    void firstSize;
  };

  // ---------- elements ----------
  const paintKey = (el) => {
    if (el.nodeType !== Node.ELEMENT_NODE) return 0;
    const cs = getComputedStyle(el);
    const z = parseInt(cs.zIndex, 10);
    const positioned = cs.position !== 'static';
    if (positioned && Number.isFinite(z) && z < 0) return -1 + z / 1e6;
    if (positioned && Number.isFinite(z) && z > 0) return 2 + z / 1e6;
    if (positioned) return 1;
    return 0;
  };
  const isSectionEl = (el) => {
    if (el.dataset && el.dataset.section !== undefined) return true;
    const p = el.parentElement;
    if (!p) return false;
    const tag = el.tagName.toLowerCase();
    const parentTag = p.tagName.toLowerCase();
    const wrapperOnly = parentTag !== 'body' && p.parentElement && p.parentElement.tagName.toLowerCase() === 'body' && p.parentElement.children.length === 1;
    if (parentTag === 'body' || parentTag === 'main' || wrapperOnly) {
      return ['header', 'section', 'footer', 'nav', 'aside', 'div', 'article'].includes(tag) && el.getBoundingClientRect().height >= 24;
    }
    return false;
  };
  const textContentOnlyWhitespace = (nodes) => nodes.every((n) => n.nodeType !== Node.TEXT_NODE || !n.data.trim());

  const processChildren = (el, out) => {
    const kids = [...el.childNodes];
    // Paint order: negative z-index, in-flow, positioned, positive z-index (stable).
    const ordered = kids.map((n, i) => ({n, i, k: paintKey(n)})).sort((a, b) => a.k - b.k || a.i - b.i).map((x) => x.n);
    let run = [];
    const flush = () => {
      if (run.length && !textContentOnlyWhitespace(run.filter((n) => n.nodeType === Node.TEXT_NODE)) || run.some((n) => n.nodeType === Node.ELEMENT_NODE && n.tagName.toLowerCase() !== 'br' && clean(n.textContent))) {
        emitRun(run, el, out);
      }
      run = [];
    };
    for (const n of ordered) {
      if (n.nodeType === Node.COMMENT_NODE) continue;
      if (n.nodeType === Node.TEXT_NODE || (n.nodeType === Node.ELEMENT_NODE && isInlineLevel(n))) { run.push(n); continue; }
      if (n.nodeType !== Node.ELEMENT_NODE) continue;
      flush();
      walk(n, out);
    }
    flush();
  };

  const walk = (el, out) => {
    const tag = el.tagName.toLowerCase();
    if (SKIP.has(tag)) return;
    const cs = getComputedStyle(el);
    if (cs.display === 'none') return;
    stats.elements += 1;
    if (cs.visibility === 'hidden' || parseFloat(cs.opacity) === 0) {
      if (el.querySelector('*') && cs.visibility === 'hidden') issue('hidden-subtree-skipped', el, 'visibility:hidden');
      return;
    }
    for (const pseudo of ['::before', '::after']) {
      const ps = getComputedStyle(el, pseudo);
      if (ps.content && ps.content !== 'none' && ps.content !== 'normal' && ps.display !== 'none') {
        const pd = (parseColor(ps.backgroundColor) || {}).opacity > 0 || ps.backgroundImage !== 'none' || (ps.content !== '""' && ps.content !== "''");
        if (pd) issue('pseudo-element-ignored', el, pseudo + ' ' + ps.content.slice(0, 30));
      }
    }
    if (cs.transform && cs.transform !== 'none' && !/^matrix\(1, 0, 0, 1, [-\d.]+, [-\d.]+\)$/.test(cs.transform)) issue('transform-approximated', el, cs.transform);
    if (cs.filter && cs.filter !== 'none') issue('filter-ignored', el, cs.filter.slice(0, 60));
    if (cs.mixBlendMode && cs.mixBlendMode !== 'normal') issue('blend-mode-ignored', el, cs.mixBlendMode);
    if (cs.backdropFilter && cs.backdropFilter !== 'none') issue('backdrop-filter-ignored', el, cs.backdropFilter);
    const rect = el.getBoundingClientRect();
    if (tag === 'svg') { emitSvg(el, out); return; }
    if (tag === 'img' || tag === 'picture') {
      const img = tag === 'img' ? el : el.querySelector('img');
      if (!img) return;
      const r = img.getBoundingClientRect();
      if (r.width < 0.5 || r.height < 0.5) return;
      const ics = getComputedStyle(img);
      const fit = ics.objectFit === 'cover' ? 'cover' : ics.objectFit === 'contain' ? 'contain' : 'fill';
      if (fit === 'contain') issue('object-fit-contain-approximated', img, '');
      out.push({kind: 'rect', name: 'Image / ' + short(img.alt || img.getAttribute('src') || 'image', 40), box: box(r),
        fills: [{type: 'image', src: img.currentSrc || img.src, fit, natural: [img.naturalWidth, img.naturalHeight]}],
        strokes: [], radius: radiiOf(ics, r), shadows: shadowsOf(ics, img), opacity: parseFloat(ics.opacity) || 1});
      stats.images += 1;
      return;
    }
    if (tag === 'video' || tag === 'canvas' || tag === 'iframe') { issue('media-unsupported', el, tag); return; }
    if (tag === 'input' || tag === 'textarea' || tag === 'select') {
      const dec = decoration(el, cs, rect);
      out.push({kind: 'board', name: nameOf(el), box: box(rect), fills: dec.fills, strokes: dec.strokes, radius: dec.radius,
        shadows: dec.shadows, opacity: parseFloat(cs.opacity) || 1, clip: true, children: [], formControl: tag});
      issue('form-control-text-not-carried', el, 'value/placeholder not converted');
      stats.boards += 1;
      return;
    }
    const section = isSectionEl(el);
    const component = el.dataset ? el.dataset.component || null : null;
    const dec = decoration(el, cs, rect);
    const layout = /flex|grid/.test(cs.display);
    const named = el.dataset && el.dataset.name;
    const visibleKids = [...el.children].filter((c) => getComputedStyle(c).display !== 'none').length;
    let node = null;
    const opacity = parseFloat(cs.opacity);
    if (section || component || dec.visible || (layout && named)) {
      node = {kind: 'board', name: nameOf(el, section ? 'section' : 'element'), box: box(rect), fills: dec.fills, strokes: dec.strokes,
        radius: dec.radius, shadows: dec.shadows, opacity: Number.isFinite(opacity) ? opacity : 1,
        clip: cs.overflow !== 'visible' || cs.overflowX !== 'visible' || cs.overflowY !== 'visible' || false,
        section, component, layout: layout ? {display: cs.display, direction: cs.flexDirection, gap: cs.gap, justify: cs.justifyContent, align: cs.alignItems,
          padding: [cs.paddingTop, cs.paddingRight, cs.paddingBottom, cs.paddingLeft]} : null, tag, children: []};
      for (const s of dec.sideRects) {
        const b = box(rect);
        const sr = s.side === 'top' ? {x: b.x, y: b.y, w: b.w, h: s.width} : s.side === 'bottom' ? {x: b.x, y: b.y + b.h - s.width, w: b.w, h: s.width}
          : s.side === 'left' ? {x: b.x, y: b.y, w: s.width, h: b.h} : {x: b.x + b.w - s.width, y: b.y, w: s.width, h: b.h};
        node.borderSides = node.borderSides || [];
        node.borderSides.push({kind: 'rect', name: 'Border / ' + s.side, box: sr, fills: [{type: 'color', color: s.color, opacity: s.opacity}], strokes: [], radius: [0, 0, 0, 0], shadows: [], opacity: 1});
      }
      stats.boards += 1;
    } else if (named || (layout && visibleKids >= 2) || (opacity < 1)) {
      node = {kind: 'group', name: nameOf(el), opacity: Number.isFinite(opacity) ? opacity : 1, tag, children: []};
      stats.groups += 1;
    }
    const target = node ? node.children : out;
    processChildren(el, target);
    if (node && node.borderSides) { node.children.push(...node.borderSides); delete node.borderSides; }
    if (node) {
      if (node.kind === 'group' && !node.children.length) return;
      if (node.kind === 'group' && node.children.length === 1 && !named && node.opacity === 1) { out.push(node.children[0]); return; }
      out.push(node);
    }
  };

  const body = document.body;
  const bodyCs = getComputedStyle(body);
  let pageBg = parseColor(bodyCs.backgroundColor);
  if (!visibleColor(pageBg)) pageBg = parseColor(getComputedStyle(doc).backgroundColor);
  if (!visibleColor(pageBg)) pageBg = {color: '#FFFFFF', opacity: 1};
  const pageFills = [{type: 'color', color: pageBg.color, opacity: 1}];
  const bodyDec = decoration(body, bodyCs, body.getBoundingClientRect());
  for (const f of bodyDec.fills) if (f.type !== 'color') pageFills.push(f);
  const nodes = [];
  processChildren(body, nodes);
  return {version: 1, url: location.href, title: document.title, width: W, height: H,
    viewport: [window.innerWidth, window.innerHeight], background: pageFills, vars,
    fonts: fonts.filter((f) => usedFonts.has(f.family.toLowerCase() + '|' + f.weight + '|' + f.style)),
    fontsUsed: [...usedFonts.values()], nodes, issues, stats};
}
